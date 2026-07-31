#!/usr/bin/env python3
"""Regression tests for the logic that decides WHO receives a message.

Runs offline with no network and no token: every case uses synthetic rosters, and the
one function that would call Graph is stubbed. Run it with the repo venv:

    .venv/bin/python tests/test_targeting.py

verify.sh runs this as block [5]. These cases exist because each one is a bug that was
actually shipped and caught: a first name silently matching the wrong person, one human
appearing several times under the same address, a printed target the CLI would reject,
and a mention resolving to whichever member Graph happened to return first.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import teams_notify as t  # noqa: E402

failures = []


def check(label, got, want):
    ok = got == want
    print(f"  [{'ok ' if ok else 'FAIL'}] {label}")
    if not ok:
        failures.append(f"{label}: got {got!r}, want {want!r}")


# --------------------------------------------------------------------------- #
# _match_people — exact forms beat substring, so a full first name is not
# swallowed by a longer name that merely contains it.
# --------------------------------------------------------------------------- #
PEOPLE = [
    {"userId": "1", "displayName": "Jordan Vance", "email": "v-jordanv@example.com"},
    {"userId": "2", "displayName": "Jordan Alvarez",   "email": "v-jordana@example.com"},
    {"userId": "3", "displayName": "Chris Park",   "email": "chris@example.com"},
    {"userId": "4", "displayName": "Christa Boyd",   "email": "christa@example.com"},
    {"userId": "5", "displayName": "Guest NoMail",  "email": ""},
    {"userId": "6", "displayName": "",              "email": ""},
]


def ids(hits):
    return sorted(p["userId"] for p in hits)


print("_match_people")
check("exact first-name token wins over substring",
      ids(t._match_people(PEOPLE, "Chris")), ["3"])
check("the longer name is still reachable exactly",
      ids(t._match_people(PEOPLE, "Christa")), ["4"])
check("substring fallback returns every candidate",
      ids(t._match_people(PEOPLE, "Chri")), ["3", "4"])
check("a shared first name stays ambiguous",
      ids(t._match_people(PEOPLE, "Jordan")), ["1", "2"])
check("full display name disambiguates",
      ids(t._match_people(PEOPLE, "Jordan Vance")), ["1"])
check("address matches", ids(t._match_people(PEOPLE, "v-jordana@example.com")), ["2"])
check("address local-part matches", ids(t._match_people(PEOPLE, "chris")), ["3"])
check("leading @ is stripped", ids(t._match_people(PEOPLE, "@Jordan Vance")), ["1"])
check("case-insensitive", ids(t._match_people(PEOPLE, "jOrDaN vAnCe")), ["1"])
check("no match returns nothing", ids(t._match_people(PEOPLE, "zzznobody")), [])
check("a member with no address is still matchable by name",
      ids(t._match_people(PEOPLE, "Guest NoMail")), ["5"])

# --------------------------------------------------------------------------- #
# _person_target — never offer a target the CLI cannot accept. An AAD object id
# can never be matched back by _match_people, so printing one is a dead end.
# --------------------------------------------------------------------------- #
print("_person_target")
check("prefers the address", t._person_target(PEOPLE[0]), "v-jordanv@example.com")
check("falls back to display name", t._person_target(PEOPLE[4]), "Guest NoMail")
check("offers nothing when neither exists", t._person_target(PEOPLE[5]), None)
for person in PEOPLE:
    target = t._person_target(person)
    if target is not None:
        check(f"printed target {target!r} resolves back",
              ids(t._match_people(PEOPLE, target)) != [], True)

# --------------------------------------------------------------------------- #
# _iter_people — one human can hold several AAD object ids (tenant member in one
# chat, federated guest in another). Collapsing on the address is what keeps the
# ambiguity error actionable instead of printing the same address twice.
# --------------------------------------------------------------------------- #
print("_iter_people")
CHATS = [
    {"members": [{"userId": "a", "displayName": "Sam Rivera", "email": "sam@example.com"},
                 {"userId": "x", "displayName": "Other", "email": "other@example.com"}]},
    {"members": [{"userId": "b", "displayName": "Sam Rivera", "email": "SAM@example.com"}]},
    {"members": [{"userId": "c", "displayName": "No Id", "email": None}]},
    {"members": [{"userId": None, "displayName": "Anonymous", "email": None}]},
]
t._iter_chats = lambda token: iter(CHATS)  # no network
roster = t._iter_people("tok")
check("duplicate object ids collapse on address", len(roster), 3)
check("members without an AAD id are dropped",
      all(p["userId"] for p in roster.values()), True)
check("an address-less member survives under its own id",
      any(p["displayName"] == "No Id" for p in roster.values()), True)
check("collapsed record keeps a usable target",
      t._person_target(roster["sam@example.com"]), "sam@example.com")

# --------------------------------------------------------------------------- #
# resolve_mentions — an unresolvable OR ambiguous mention must be a hard error.
# Taking the first match would notify the wrong person and still report success.
# --------------------------------------------------------------------------- #
print("resolve_mentions")
CHAT = {"members": [
    {"userId": "1", "displayName": "Alex Smith", "email": "alex.smith@example.com"},
    {"userId": "2", "displayName": "Alex Jones", "email": "alex.jones@example.com"},
    {"userId": "3", "displayName": "Dana Lee",   "email": "dana@example.com"},
]}
t._graph = lambda *a, **k: CHAT  # no network


def mention(names):
    try:
        return [m["displayName"] for m in t.resolve_mentions("tok", "chat", names)]
    except SystemExit:
        return "EXIT"


check("ambiguous mention refuses", mention(["Alex"]), "EXIT")
check("unknown mention refuses", mention(["Nobody"]), "EXIT")
check("degenerate needle refuses", mention(["@"]), "EXIT")
check("full name resolves", mention(["Alex Smith"]), ["Alex Smith"])
check("address resolves", mention(["alex.jones@example.com"]), ["Alex Jones"])
check("unique first name resolves", mention(["Dana"]), ["Dana Lee"])
check("one bad name poisons the whole batch", mention(["Dana", "Alex"]), "EXIT")

# --------------------------------------------------------------------------- #
# DRY_RUN gates — the reason --dry-run can be trusted. These stub the TRANSPORT,
# not the resolver, so an inverted gate, a gate moved below its write, or an
# unwired --dry-run all fail here. The control run (flag off) is what proves the
# recorder is not simply blind.
# --------------------------------------------------------------------------- #
print("DRY_RUN gates")
CARD = t.build_card(type("A", (), {"status": "info", "title": "t", "text": "",
                                   "fact": None, "link": None})())
writes = []


def _record_graph(method, path, token, **kw):
    if method != "GET":
        writes.append(f"{method} {path}")
    return {"id": "chat-id", "members": []}


def _record_post(*a, **kw):
    writes.append("POST webhook")
    raise AssertionError("webhook POST must not happen under DRY_RUN")


t._graph = _record_graph
t.requests = type("R", (), {"post": staticmethod(_record_post),
                            "get": staticmethod(lambda *a, **k: type("X", (), {"status_code": 599})()),
                            "RequestException": Exception})
t._graph_token = lambda: "tok"
os_environ_backup = t.os.environ.get("TEAMS_WEBHOOK_URL")
t.os.environ["TEAMS_WEBHOOK_URL"] = "https://example.invalid/hook"

t.DRY_RUN = True
writes.clear()
t.send_channel(CARD)
check("dry-run: send_channel writes nothing", writes, [])
writes.clear()
t._post_card("tok", "19:x@thread.v2", CARD)
check("dry-run: _post_card writes nothing", writes, [])
writes.clear()
t.send_dm(CARD, "someone@example.com")
check("dry-run: send_dm writes nothing (incl. chat creation)", writes, [])

# Control: with the flag off, each path must record exactly one write. If these
# come back empty the recorder is broken and the assertions above prove nothing.
t.DRY_RUN = False
writes.clear()
try:
    t.send_channel(CARD)
except AssertionError:
    pass
check("control: send_channel does write", writes, ["POST webhook"])
writes.clear()
t._post_card("tok", "19:x@thread.v2", CARD)
check("control: _post_card does write", writes, ["POST /chats/19:x@thread.v2/messages"])
writes.clear()
t.send_dm(CARD, "someone@example.com")
check("control: send_dm creates the chat then posts",
      writes, ["POST /chats", "POST /chats/chat-id/messages"])

# The gates above are armed by hand, which cannot catch --dry-run being unwired from
# argparse. Drive main() end to end so the flag's actual plumbing is covered too.
argv_backup = sys.argv[:]
t.DRY_RUN = False
writes.clear()
sys.argv = ["teams", "--dry-run", "--target", "chat:19:x@thread.v2", "--title", "t"]
try:
    t.main()
except SystemExit:
    pass
check("--dry-run arms the gate through main()", writes, [])

t.DRY_RUN = False
writes.clear()
sys.argv = ["teams", "--target", "chat:19:x@thread.v2", "--title", "t"]
try:
    t.main()
except SystemExit:
    pass
check("control: without the flag, main() writes", writes, ["POST /chats/19:x@thread.v2/messages"])
sys.argv = argv_backup
t.DRY_RUN = False

if os_environ_backup is None:
    t.os.environ.pop("TEAMS_WEBHOOK_URL", None)
else:
    t.os.environ["TEAMS_WEBHOOK_URL"] = os_environ_backup

# --------------------------------------------------------------------------- #
# _preview must be total: never crash, never print nothing.
# --------------------------------------------------------------------------- #
print("_preview robustness")


def preview_lines(card):
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        t._preview(card, "somewhere")
    return [l for l in buf.getvalue().splitlines() if "destination:" not in l]


def parsed(card, needle):
    """True only if the text was actually WALKED — the raw-JSON fallback also contains
    every string, so asserting presence alone would pass on a broken walker."""
    lines = preview_lines(card)
    return any(needle in l for l in lines) and not any("raw JSON" in l for l in lines)


check("nested containers are parsed, not dumped",
      parsed({"body": [{"type": "Container", "items": [
          {"type": "Container", "items": [{"type": "TextBlock", "text": "BURIED"}]}]}]},
             "BURIED"), True)
check("columns are parsed, not dumped",
      parsed({"body": [{"type": "ColumnSet", "columns": [
          {"items": [{"type": "TextBlock", "text": "INCOL"}]}]}]}, "INCOL"), True)
check("a string body does not crash",
      any("just a string" in l for l in preview_lines({"body": "just a string"})), True)
check("an unrecognised shape falls back to raw JSON",
      any("raw JSON" in l for l in preview_lines([{"type": "AdaptiveCard"}])), True)

# --------------------------------------------------------------------------- #
# _describe_chat — a raw thread id does not answer "who does this reach", and a
# mis-pinned alias is invisible without the topic and roster.
# --------------------------------------------------------------------------- #
print("_describe_chat")


def stub_get(payload=None, status=200):
    def _get(*a, **k):
        return type("X", (), {"status_code": status,
                              "json": staticmethod(lambda: payload)})()
    t.requests = type("R", (), {"get": staticmethod(_get), "RequestException": Exception})


stub_get({"topic": "Daily Stand-Up",
          "members": [{"displayName": "Ada"}, {"displayName": "Grace"}]})
desc = t._describe_chat("tok", "19:x@thread.v2")
check("names the topic", "Daily Stand-Up" in desc, True)
check("names the roster", "Ada" in desc and "Grace" in desc, True)
check("counts the members", "2 members" in desc, True)

stub_get(None, status=400)
check("falls back to the bare id when the chat is unreadable",
      t._describe_chat("tok", "48:notes"), "chat 48:notes")

print()
if failures:
    print(f"FAILED ({len(failures)}):")
    for f in failures:
        print("   ", f)
    sys.exit(1)
print("all targeting tests passed")
