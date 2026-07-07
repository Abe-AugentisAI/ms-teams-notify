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


def _post_card(token, chat_id, card):
    """Post an Adaptive Card into an existing chat (1:1, group, or meeting)."""
    _graph("POST", f"/chats/{chat_id}/messages", token, json={
        "body": {"contentType": "html", "content": '<attachment id="1"></attachment>'},
        "attachments": [
            {"id": "1",
             "contentType": "application/vnd.microsoft.card.adaptive",
             "content": json.dumps(card)},  # Graph requires the card as a STRING
        ],
    })


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


def send_dm(card, upn):
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
             "user@odata.bind": f"{GRAPH}/users('{upn}')"},
        ],
    })

    _post_card(token, chat["id"], card)
    print(f"[ok] sent DM to {upn}.")


def send_chat(card, chat_id):
    """Post to any existing chat (group/meeting/1:1) by its Graph chat id."""
    token = _graph_token()
    _post_card(token, chat_id, card)
    print(f"[ok] posted to chat {chat_id}.")


def send_group(card, topic):
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
    _post_card(token, chat["id"], card)
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
def main():
    p = argparse.ArgumentParser(description="Post a message to Teams (channel, DM, or group/meeting chat).")
    p.add_argument("--target", required=True,
                   help="'channel', 'user:<upn>' (1:1 DM), 'chat:<id>' (group/meeting chat by id), "
                        "'group:<topic>' (group/meeting chat by name), or 'list-chats' (discover ids)")
    p.add_argument("--card-file", dest="card_file",
                   help="Path to a pre-built Adaptive Card JSON, or '-' for stdin. "
                        "When set, build flags below are ignored.")
    p.add_argument("--title", help="Card title (declarative sentence recommended)")
    p.add_argument("--status", default="info", choices=list(STATUS.keys()))
    p.add_argument("--text", default="", help="Optional body text")
    p.add_argument("--link", action="append", help="Repeatable 'Label=https://url' (GitHub PRs/issues/files)")
    p.add_argument("--fact", action="append", help="Repeatable 'Key=value' fact rows")
    args = p.parse_args()

    # Discovery target needs no card — list chats and exit.
    if args.target == "list-chats":
        list_chats()
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
        upn = args.target.split("user:", 1)[1].strip()
        if not re.match(r"[^@]+@[^@]+\.[^@]+", upn):
            sys.exit(f"[error] '{upn}' does not look like a UPN/email.")
        send_dm(card, upn)
    elif args.target.startswith("chat:"):
        chat_id = args.target.split("chat:", 1)[1].strip()
        if not chat_id:
            sys.exit("[error] --target chat:<id> requires a chat id (see --target list-chats).")
        send_chat(card, chat_id)
    elif args.target.startswith("group:"):
        topic = args.target.split("group:", 1)[1].strip()
        if not topic:
            sys.exit("[error] --target group:<topic> requires a topic (see --target list-chats).")
        send_group(card, topic)
    else:
        sys.exit("[error] --target must be 'channel', 'user:<upn>', 'chat:<id>', "
                 "'group:<topic>', or 'list-chats'.")


if __name__ == "__main__":
    main()
