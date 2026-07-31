#!/usr/bin/env python3
"""
teams_notify.py — Post a rich message to a Microsoft Teams channel or a 1:1 DM.

Channel  -> Power Automate "Workflows" incoming webhook (no auth in the CLI).
DM       -> Microsoft Graph POST /chats/{id}/messages (delegated, MSAL device-code).

Config is read from environment variables, auto-loaded from the repo-root .env:
  TEAMS_WEBHOOK_URL   Workflows webhook URL            (required for --target channel)
  GRAPH_TENANT_ID     Entra tenant id                  (required for --target user:*)
  GRAPH_CLIENT_ID     Public-client app (no secret)    (required for --target user:*)

Examples:
  teams_notify.py --target channel \
    --title "Nightly verify loop passed" --status success \
    --text "Phase 3 green on staging." \
    --link "PR #142=https://github.com/example/repo/pull/142" \
    --fact "Skill=skill-creator" --fact "Duration=4m12s"

  teams_notify.py --target user:jordan@example.com --card-file run_summary.json
"""
import argparse
import html
import json
import os
import re
import sys
from pathlib import Path

import requests

# --- Zero-config: auto-load the repo-root .env so slash commands need no shell setup ---
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = ["Chat.ReadWrite", "ChatMessage.Send", "User.Read"]
CACHE_PATH = Path.home() / ".config" / "teams-notify" / "token_cache.json"
ALIAS_PATH = Path.home() / ".config" / "teams-notify" / "aliases.json"

STATUS = {
    "success": {"style": "good", "emoji": "\u2705", "label": "Success"},
    "warn":    {"style": "warning", "emoji": "\u26a0\ufe0f", "label": "Warning"},
    "fail":    {"style": "attention", "emoji": "\u274c", "label": "Failed"},
    "info":    {"style": "emphasis", "emoji": "\u2139\ufe0f", "label": "Info"},
}


# --------------------------------------------------------------------------- #
# Adaptive Card construction
# --------------------------------------------------------------------------- #
def _kv(pairs):
    """Parse repeated 'Label=value' args into a list of (label, value)."""
    out = []
    for raw in pairs or []:
        if "=" not in raw:
            print(f"[warn] ignoring malformed pair (no '='): {raw}", file=sys.stderr)
            continue
        label, value = raw.split("=", 1)
        out.append((label.strip(), value.strip()))
    return out


def load_card(source):
    """Load a pre-built Adaptive Card from a file path, or '-' for stdin."""
    raw = sys.stdin.read() if source == "-" else Path(source).read_text()
    try:
        card = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"[error] --card-file is not valid JSON: {e}")
    if not isinstance(card, dict) or card.get("type") != "AdaptiveCard":
        print("[warn] card JSON has no top-level type 'AdaptiveCard'; sending as-is.",
              file=sys.stderr)
    return card


def build_card(args):
    meta = STATUS[args.status]
    body = [
        {
            "type": "Container",
            "style": meta["style"],
            "bleed": True,
            "items": [
                {
                    "type": "TextBlock",
                    "text": f"{meta['emoji']} {args.title}",
                    "weight": "Bolder",
                    "size": "Medium",
                    "wrap": True,
                }
            ],
        }
    ]

    if args.text:
        body.append({"type": "TextBlock", "text": args.text, "wrap": True, "spacing": "Medium"})

    facts = _kv(args.fact)
    facts.insert(0, ("Status", meta["label"]))
    body.append(
        {
            "type": "FactSet",
            "facts": [{"title": f"{k}:", "value": v} for k, v in facts],
            "spacing": "Medium",
        }
    )

    actions = []
    for label, url in _kv(args.link):
        actions.append({"type": "Action.OpenUrl", "title": label, "url": url})

    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.5",
        "body": body,
    }
    if actions:
        card["actions"] = actions
    return card


# --------------------------------------------------------------------------- #
# Channel path — Workflows webhook
# --------------------------------------------------------------------------- #
def send_channel(card):
    url = os.environ.get("TEAMS_WEBHOOK_URL")
    if not url:
        sys.exit("[error] TEAMS_WEBHOOK_URL is not set (needed for --target channel).")

    payload = {
        "type": "message",
        "attachments": [
            {"contentType": "application/vnd.microsoft.card.adaptive", "content": card}
        ],
    }
    resp = requests.post(url, json=payload, timeout=30)
    if resp.status_code >= 300:
        sys.exit(f"[error] webhook POST failed ({resp.status_code}): {resp.text[:400]}")
    print("[ok] posted to channel.")


# --------------------------------------------------------------------------- #
# DM path — Microsoft Graph (delegated, MSAL device-code with cache)
# --------------------------------------------------------------------------- #
def _graph_token():
    import msal  # imported lazily so the channel path needs no MSAL install

    tenant = os.environ.get("GRAPH_TENANT_ID")
    client = os.environ.get("GRAPH_CLIENT_ID")
    if not (tenant and client):
        sys.exit("[error] GRAPH_TENANT_ID and GRAPH_CLIENT_ID must be set for --target user:*.")

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cache = msal.SerializableTokenCache()
    if CACHE_PATH.exists():
        cache.deserialize(CACHE_PATH.read_text())

    app = msal.PublicClientApplication(
        client,
        authority=f"https://login.microsoftonline.com/{tenant}",
        token_cache=cache,
    )

    result = None
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
    if not result:
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            sys.exit(f"[error] device flow init failed: {json.dumps(flow)[:400]}")
        print(flow["message"], file=sys.stderr)  # "Go to https://microsoft.com/devicelogin ..."
        result = app.acquire_token_by_device_flow(flow)

    if cache.has_state_changed:
        CACHE_PATH.write_text(cache.serialize())
        os.chmod(CACHE_PATH, 0o600)

    if "access_token" not in result:
        sys.exit(f"[error] token acquisition failed: {result.get('error_description', result)}")
    return result["access_token"]


def _graph(method, path, token, **kwargs):
    resp = requests.request(
        method, f"{GRAPH}{path}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=30, **kwargs,
    )
    if resp.status_code >= 300:
        sys.exit(f"[error] Graph {method} {path} -> {resp.status_code}: {resp.text[:400]}")
    return resp.json() if resp.text else {}


def resolve_mentions(token, chat_id, wanted):
    """Map each requested name/email to a real member of `chat_id`.

    A Teams @-mention only notifies someone when the message carries BOTH an
    <at id="N"> tag in the HTML body AND a matching entry in the `mentions`
    array with the person's AAD object id. Plain "@Name" text pings nobody, so
    an unresolvable name is a hard error rather than a silent no-op.
    """
    chat = _graph("GET", f"/chats/{chat_id}?$expand=members", token)
    members = [m for m in chat.get("members", []) if m.get("userId")]
    resolved, unknown = [], []
    for want in wanted:
        needle = want.strip().lstrip("@").lower()
        if not needle:
            unknown.append(want)
            continue
        hit = next(
            (m for m in members
             if needle == (m.get("displayName") or "").lower()
             or needle == (m.get("email") or "").lower()
             or needle == (m.get("email") or "").split("@")[0].lower()
             or needle in (m.get("displayName") or "").lower().split()),
            None,
        )
        if hit:
            resolved.append(hit)
        else:
            unknown.append(want)
    if unknown:
        roster = "\n".join(
            f"    {m.get('displayName')}  <{m.get('email') or 'no-email'}>" for m in members
        )
        sys.exit(
            f"[error] cannot @-mention {unknown} — not a member of this chat.\n"
            f"  A mention that does not resolve would post as plain text and notify nobody.\n"
            f"  Chat members:\n{roster}"
        )
    return resolved


def _post_card(token, chat_id, card, mention_members=None):
    """Post an Adaptive Card into an existing chat (1:1, group, or meeting).

    When `mention_members` is given, prepend real @-mentions to the message body
    so the named people are actually notified.
    """
    prefix, mentions = "", []
    for idx, m in enumerate(mention_members or []):
        name = m.get("displayName") or m.get("email")
        # The body is contentType html, so a name containing & or <> must be escaped.
        # mentionText below stays plain — Graph treats it as text, not markup.
        prefix += f'<at id="{idx}">{html.escape(name)}</at> '
        mentions.append({
            "id": idx,
            "mentionText": name,
            "mentioned": {"user": {
                "id": m["userId"],
                "displayName": name,
                "userIdentityType": "aadUser",
            }},
        })

    payload = {
        "body": {"contentType": "html",
                 "content": f'{prefix}<attachment id="1"></attachment>'},
        "attachments": [
            {"id": "1",
             "contentType": "application/vnd.microsoft.card.adaptive",
             "content": json.dumps(card)},  # Graph requires the card as a STRING
        ],
    }
    if mentions:
        payload["mentions"] = mentions
    _graph("POST", f"/chats/{chat_id}/messages", token, json=payload)


def _iter_chats(token):
    """Yield every chat for the signed-in user, following @odata.nextLink paging."""
    next_link = f"{GRAPH}/me/chats?$expand=members&$top=50"
    while next_link:
        resp = requests.get(next_link, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        if resp.status_code >= 300:
            sys.exit(f"[error] Graph GET /me/chats -> {resp.status_code}: {resp.text[:400]}")
        data = resp.json()
        for chat in data.get("value", []):
            yield chat
        next_link = data.get("@odata.nextLink")


def _resolve_chat_by_topic(token, topic):
    """Return group/meeting chats whose topic contains `topic` (case-insensitive)."""
    needle = topic.strip().lower()
    hits = []
    for chat in _iter_chats(token):
        if chat.get("chatType") in ("group", "meeting"):
            ctopic = (chat.get("topic") or "").strip()
            if ctopic and needle in ctopic.lower():
                hits.append(chat)
    return hits


def _iter_people(token):
    """Return everyone visible in the signed-in user's chats, keyed by AAD object id.

    Chat membership is readable under the `Chat.ReadWrite` scope this tool already
    holds. A directory-wide `/users` search would need `User.ReadBasic.All` — a new
    admin-consented permission and a forced re-login — so the roster is built from
    chat members instead. The trade-off: people you share no chat with are not
    resolvable by name, and still need an explicit `user:<upn>`.
    """
    people = {}
    for chat in _iter_chats(token):
        for m in chat.get("members", []):
            uid = m.get("userId")
            if not uid:
                continue  # anonymous/federated members carry no AAD id
            email = (m.get("email") or "").strip()
            # One human can hold several AAD object ids — a tenant member in one chat
            # and a federated guest in another — so collapse on the address when there
            # is one. Keying on userId alone would list the same person several times
            # under one address, making the "use an exact address" hint unactionable.
            key = email.lower() or uid
            person = people.setdefault(key, {"userId": uid, "displayName": "", "email": email})
            person["displayName"] = person["displayName"] or (m.get("displayName") or "")
    return people


def _match_people(people, needle):
    """Match `needle` against people — exact forms first, substring only as fallback.

    Tiering keeps a full first-name hit ("Jordan") from being drowned by unrelated
    substring matches. The exact forms mirror resolve_mentions() so `--mention`
    and `user:<name>` accept the same spellings.
    """
    n = needle.strip().lstrip("@").lower()
    exact = [
        p for p in people
        if n == (p["displayName"] or "").lower()
        or n == (p["email"] or "").lower()
        or n == (p["email"] or "").split("@")[0].lower()
        or n in (p["displayName"] or "").lower().split()
    ]
    if exact:
        return exact
    return [p for p in people if n in (p["displayName"] or "").lower()]


def _person_target(person):
    """The `user:<...>` value that resolves back to this person, or None if none does.

    An AAD object id is deliberately NOT offered: main() routes `user:<x>` straight to
    send_dm() only when x is an address, and _match_people() compares names and addresses
    only — so an object id printed as a suggested target can never be matched back, and
    printing one hands the reader a value the CLI will reject.
    """
    return person["email"] or person["displayName"] or None


def resolve_person(name):
    """Resolve a display/first name to exactly one person, or exit with guidance."""
    token = _graph_token()
    hits = _match_people(list(_iter_people(token).values()), name)
    if not hits:
        sys.exit(
            f"[error] no one matching '{name}' in your chats. Name lookup only sees people "
            f"you share a chat with — use --target user:<upn> with their full address, or run "
            f"--target list-people to see who is resolvable."
        )
    if len(hits) > 1:
        listing = "\n".join(
            f"    user:{_person_target(p) or p['userId']}  ({p['displayName'] or 'no name'})"
            for p in sorted(hits, key=lambda p: (p["displayName"] or "").lower())
        )
        sys.exit(f"[error] '{name}' matched {len(hits)} people — narrow it with one of these:\n{listing}")
    return hits[0]


def list_people():
    """Print everyone resolvable by name from the signed-in user's chats; sends nothing."""
    token = _graph_token()
    people = sorted(_iter_people(token).values(), key=lambda p: (p["displayName"] or "").lower())
    unreachable = 0
    for p in people:
        print(p["displayName"] or "(no name)")
        ref = _person_target(p)
        if ref:
            print(f"    user:{ref}")
        else:
            unreachable += 1
            print("    (not addressable by name — Graph exposes no address or display name)")
    note = f"\n{len(people)} people across your chats."
    if unreachable:
        note += f" {unreachable} not addressable by name."
    print(note, file=sys.stderr)


def send_dm(card, user_ref, label=None):
    """DM a user by UPN/email or AAD object id — both are valid in a user@odata.bind."""
    token = _graph_token()
    me = _graph("GET", "/me", token)["id"]

    # oneOnOne chat creation is idempotent: returns the existing chat if present.
    chat = _graph("POST", "/chats", token, json={
        "chatType": "oneOnOne",
        "members": [
            {"@odata.type": "#microsoft.graph.aadUserConversationMember",
             "roles": ["owner"],
             "user@odata.bind": f"{GRAPH}/users('{me}')"},
            {"@odata.type": "#microsoft.graph.aadUserConversationMember",
             "roles": ["owner"],
             "user@odata.bind": f"{GRAPH}/users('{user_ref}')"},
        ],
    })

    _post_card(token, chat["id"], card)
    print(f"[ok] sent DM to {label or user_ref}.")


def send_chat(card, chat_id, mention=None):
    """Post to any existing chat (group/meeting/1:1) by its Graph chat id."""
    token = _graph_token()
    members = resolve_mentions(token, chat_id, mention) if mention else None
    _post_card(token, chat_id, card, members)
    who = f" (@{', @'.join(m.get('displayName') for m in members)})" if members else ""
    print(f"[ok] posted to chat {chat_id}{who}.")


def send_group(card, topic, mention=None):
    """Resolve a group/meeting chat by topic name, then post to it."""
    token = _graph_token()
    hits = _resolve_chat_by_topic(token, topic)
    if not hits:
        sys.exit(f"[error] no group/meeting chat found with a topic matching '{topic}'. "
                 f"Run --target list-chats to see available chats, or use --target chat:<id>.")
    if len(hits) > 1:
        listing = "\n".join(f"    chat:{c['id']}  ({c.get('topic')})" for c in hits)
        sys.exit(f"[error] '{topic}' matched {len(hits)} chats — narrow it with --target chat:<id>:\n{listing}")
    chat = hits[0]
    members = resolve_mentions(token, chat["id"], mention) if mention else None
    _post_card(token, chat["id"], card, members)
    print(f"[ok] posted to group chat '{chat.get('topic')}'.")


def list_chats():
    """Print the signed-in user's group/meeting chats (topic + chat id) for discovery."""
    token = _graph_token()
    rows = []
    for chat in _iter_chats(token):
        ct = chat.get("chatType")
        if ct in ("group", "meeting"):
            rows.append((ct, chat.get("topic") or "(no topic)", chat["id"]))
    rows.sort(key=lambda r: (r[0], r[1].lower()))
    for ct, topic, cid in rows:
        print(f"[{ct}] {topic}")
        print(f"    chat:{cid}")
    print(f"\n{len(rows)} group/meeting chats.", file=sys.stderr)


# --------------------------------------------------------------------------- #
# Target aliases (short-form nicknames) — ~/.config/teams-notify/aliases.json
# --------------------------------------------------------------------------- #
def _norm_alias(name):
    """Normalize an alias key so case, spaces, dashes, and dots don't matter."""
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _load_aliases():
    """Return the alias map {name: full-target}, or {} if none/unreadable."""
    if ALIAS_PATH.exists():
        try:
            data = json.loads(ALIAS_PATH.read_text())
            if isinstance(data, dict):
                return data
            print(f"[warn] {ALIAS_PATH} is not a JSON object; ignoring.", file=sys.stderr)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[warn] could not read aliases ({ALIAS_PATH}): {e}", file=sys.stderr)
    return {}


def _resolve_alias(target):
    """Expand a short-form alias to its full target; unchanged if there's no match."""
    aliases = _load_aliases()
    if aliases:
        lookup = {_norm_alias(k): v for k, v in aliases.items()}
        hit = lookup.get(_norm_alias(target))
        if hit:
            return hit
    return target


def print_aliases():
    """Print the saved aliases (used by --target alias-list)."""
    aliases = _load_aliases()
    if not aliases:
        print(f"(no aliases yet — add one with alias.sh; stored at {ALIAS_PATH})")
        return
    width = max(len(k) for k in aliases)
    for k in sorted(aliases, key=str.lower):
        print(f"{k.ljust(width)}  ->  {aliases[k]}")


# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser(description="Post a message to Teams (channel, DM, or group/meeting chat).")
    p.add_argument("--target", required=True,
                   help="'channel', 'user:<upn|name>' (1:1 DM — a name is resolved against "
                        "people in your chats), 'chat:<id>' or 'group:<topic>' (group/meeting "
                        "chat), a saved alias/nickname, 'alias-list', 'list-chats', or 'list-people'")
    p.add_argument("--card-file", dest="card_file",
                   help="Path to a pre-built Adaptive Card JSON, or '-' for stdin. "
                        "When set, build flags below are ignored.")
    p.add_argument("--title", help="Card title (declarative sentence recommended)")
    p.add_argument("--status", default="info", choices=list(STATUS.keys()))
    p.add_argument("--text", default="", help="Optional body text")
    p.add_argument("--link", action="append", help="Repeatable 'Label=https://url' (GitHub PRs/issues/files)")
    p.add_argument("--fact", action="append", help="Repeatable 'Key=value' fact rows")
    p.add_argument("--mention", action="append",
                   help="Repeatable. @-mention a chat member by display name, email, or "
                        "first name (e.g. --mention Taylor). chat:/group: targets only; the "
                        "person must already be in the chat.")
    args = p.parse_args()

    # Expand a short-form alias unless the target is already an explicit form.
    if (args.target not in ("channel", "list-chats", "list-people", "alias-list")
            and not args.target.startswith(("user:", "chat:", "group:"))):
        args.target = _resolve_alias(args.target)

    # --mention only means something on a chat that has other members. Guard once, here,
    # after alias expansion, so an alias that expands to user:/channel is caught too rather
    # than accepting the flag and silently dropping it.
    if args.mention and not args.target.startswith(("chat:", "group:")):
        sys.exit("[error] --mention works only on chat:/group: targets (including an alias "
                 "that expands to one). A 1:1 DM already notifies its recipient and has no "
                 "other members to mention; the channel webhook cannot carry mention entities.")

    # Info targets need no card.
    if args.target == "alias-list":
        print_aliases()
        return
    if args.target == "list-chats":
        list_chats()
        return
    if args.target == "list-people":
        list_people()
        return

    if args.card_file:
        if any([args.title, args.text, args.link, args.fact]) or args.status != "info":
            print("[warn] --card-file supplied; ignoring --title/--text/--link/--fact/--status.",
                  file=sys.stderr)
        card = load_card(args.card_file)
    else:
        if not args.title:
            sys.exit("[error] --title is required unless --card-file is provided.")
        card = build_card(args)

    if args.target == "channel":
        send_channel(card)
    elif args.target.startswith("user:"):
        # Strip a leading @ here too, so an all-@ target cannot survive as the empty
        # needle that _match_people() would match against everyone.
        who = args.target.split("user:", 1)[1].strip().lstrip("@").strip()
        if not who:
            sys.exit("[error] --target user:<upn|name> requires a person (see --target list-people).")
        if re.match(r"[^@]+@[^@]+\.[^@]+", who):
            send_dm(card, who)
        else:
            # Not an address — resolve the name, then bind by address when there is
            # one. Among several object ids for one human there is no reliable way to
            # tell which is live; the address is the identity they actually publish.
            # Object id is the fallback for members Graph exposes without an address.
            person = resolve_person(who)
            ref = person["email"] or person["userId"]
            send_dm(card, ref, label=f"{person['displayName']} <{ref}>")
    elif args.target.startswith("chat:"):
        chat_id = args.target.split("chat:", 1)[1].strip()
        if not chat_id:
            sys.exit("[error] --target chat:<id> requires a chat id (see --target list-chats).")
        send_chat(card, chat_id, args.mention)
    elif args.target.startswith("group:"):
        topic = args.target.split("group:", 1)[1].strip()
        if not topic:
            sys.exit("[error] --target group:<topic> requires a topic (see --target list-chats).")
        send_group(card, topic, args.mention)
    else:
        sys.exit(f"[error] unknown target '{args.target}'. Use channel | user:<upn|name> | "
                 f"chat:<id> | group:<topic> | a saved alias (see --target alias-list) | "
                 f"list-chats | list-people.")


if __name__ == "__main__":
    main()
