#!/usr/bin/env bash
# alias.sh — manage /teams target nicknames (stored in ~/.config/teams-notify/aliases.json).
#
#   bash alias.sh list
#   bash alias.sh add <name> <target-or-topic>
#       <target-or-topic> may be a full target:
#         channel | user:<upn> | chat:<id> | group:<topic>
#       or a bare chat topic (e.g. "Team Stand-Up"), which is resolved
#       once to a pinned chat:<id>.
#   bash alias.sh rm <name>
#
# Then send with the nickname:  /teams <name> "message" success
#                       or CLI:  .venv/bin/python src/teams_notify.py --target <name> ...
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="$REPO_DIR/.venv/bin/python"
SCRIPT="$REPO_DIR/src/teams_notify.py"

cmd="${1:-}"; shift || true
case "$cmd" in
    list)
        exec "$VENV_PY" "$SCRIPT" --target alias-list
        ;;
    add)
        name="${1:-}"; shift || true
        target="$*"   # keep spaces (topics contain them)
        if [ -z "$name" ] || [ -z "$target" ]; then
            echo "usage: bash alias.sh add <name> <target-or-topic>"; exit 2
        fi
        "$VENV_PY" - "$REPO_DIR" "$name" "$target" <<'PY'
import sys, json
sys.path.insert(0, sys.argv[1] + "/src")
import teams_notify as t
name, target = sys.argv[2], sys.argv[3]

# Guard: don't let a nickname collide with a built-in target form.
_reserved = {t._norm_alias(x) for x in ("channel", "list-chats", "alias-list")}
if ":" in name or t._norm_alias(name) in _reserved:
    sys.exit(f"[error] '{name}' is reserved — pick a different nickname.")

# Full target passes through; a bare topic is resolved and pinned to chat:<id>.
if target == "channel" or target.startswith(("user:", "chat:", "group:")):
    resolved = target
else:
    tok = t._graph_token()
    hits = t._resolve_chat_by_topic(tok, target)
    if not hits:
        sys.exit(f"[error] no group/meeting chat matches '{target}'. "
                 f"See: --target list-chats")
    if len(hits) > 1:
        lines = "\n".join(f"    chat:{h['id']}  ({h.get('topic')})" for h in hits)
        sys.exit(f"[error] '{target}' matched {len(hits)} chats — add by id instead:\n{lines}")
    resolved = "chat:" + hits[0]["id"]

p = t.ALIAS_PATH
p.parent.mkdir(parents=True, exist_ok=True)
data = {}
if p.exists():
    try:
        data = json.loads(p.read_text()) or {}
    except json.JSONDecodeError:
        data = {}
# Replace any existing nickname that normalizes the same, then set this one.
data = {k: v for k, v in data.items() if t._norm_alias(k) != t._norm_alias(name)}
data[name] = resolved
p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
print(f"[ok] alias '{name}' -> {resolved}")
PY
        ;;
    rm)
        name="${1:-}"
        if [ -z "$name" ]; then echo "usage: bash alias.sh rm <name>"; exit 2; fi
        "$VENV_PY" - "$REPO_DIR" "$name" <<'PY'
import sys, json
sys.path.insert(0, sys.argv[1] + "/src")
import teams_notify as t
name = sys.argv[2]
p = t.ALIAS_PATH
data = {}
if p.exists():
    try:
        data = json.loads(p.read_text()) or {}
    except json.JSONDecodeError:
        data = {}
removed = [k for k in list(data) if t._norm_alias(k) == t._norm_alias(name)]
for k in removed:
    del data[k]
p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
print(f"[ok] removed {removed}" if removed else f"[warn] no alias matching '{name}'")
PY
        ;;
    *)
        echo "usage: bash alias.sh {list | add <name> <target-or-topic> | rm <name>}"; exit 2
        ;;
esac
