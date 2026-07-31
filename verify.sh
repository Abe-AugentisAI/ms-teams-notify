#!/usr/bin/env bash
# verify.sh — sanity-check the delivery paths.
#   bash verify.sh                reachability + token acquisition only (posts nothing)
#   bash verify.sh --send         also POST a labeled test card to the channel (visible)
#   bash verify.sh --dm <upn|name>  also send a labeled test DM (visible to them)
#   bash verify.sh --chat <t>     also post a labeled test to a group/meeting chat, where
#                                 <t> is a chat id ('19:...@thread.v2') or a topic name
#   bash verify.sh --list         list your group/meeting chats + ids (posts nothing) and exit
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$REPO_DIR/.env"
VENV_PY="$REPO_DIR/.venv/bin/python"
SCRIPT="$REPO_DIR/src/teams_notify.py"

SEND=0; DM=""; CHAT=""; LIST=0
while [ $# -gt 0 ]; do
    case "$1" in
        --send) SEND=1; shift;;
        --dm) DM="${2:-}"; shift 2;;
        --chat) CHAT="${2:-}"; shift 2;;
        --list) LIST=1; shift;;
        *) echo "unknown argument: $1"; exit 2;;
    esac
done

if [ -t 1 ]; then G=$'\e[32m'; R=$'\e[31m'; Y=$'\e[33m'; N=$'\e[0m'; else G=; R=; Y=; N=; fi
pass=0; fail=0
ok()   { echo "  ${G}PASS${N} $1"; pass=$((pass+1)); }
no()   { echo "  ${R}FAIL${N} $1"; fail=$((fail+1)); }
skip() { echo "  ${Y}SKIP${N} $1"; }

# Load .env through the same parser teams_notify.py uses (python-dotenv), NOT bash
# `source` — so values containing '&' or other shell metacharacters are read
# identically and can never disagree with the dispatcher. Falls back to loading
# nothing if the venv is missing (the toolchain check below reports that).
if [ -f "$ENV_FILE" ] && [ -x "$VENV_PY" ]; then
    while IFS= read -r line; do
        [ -n "$line" ] && export "$line"
    done < <("$VENV_PY" - "$ENV_FILE" <<'PY'
import sys
from dotenv import dotenv_values
for k, v in dotenv_values(sys.argv[1]).items():
    print("%s=%s" % (k, "" if v is None else v))
PY
    )
fi

# --list is a discovery shortcut: print chats and exit (sends nothing).
if [ "$LIST" = "1" ]; then
    [ -x "$VENV_PY" ] || { echo "venv python missing — run install.sh"; exit 1; }
    exec "$VENV_PY" "$SCRIPT" --target list-chats
fi

echo "teams-notify verification  ($REPO_DIR)"
echo
echo "[0] Toolchain"
[ -x "$VENV_PY" ] && ok "venv python present" || no "venv python missing — run install.sh"
[ -f "$SCRIPT" ]  && ok "dispatcher present"  || no "src/teams_notify.py missing"

echo
echo "[1] Channel webhook"
if [ -z "${TEAMS_WEBHOOK_URL:-}" ]; then
    skip "TEAMS_WEBHOOK_URL unset — channel path not configured"
else
    case "$TEAMS_WEBHOOK_URL" in
        https://*) ok "URL is HTTPS";;
        *) no "URL is not HTTPS";;
    esac
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$TEAMS_WEBHOOK_URL" || true)"
    if [ -z "$code" ] || [ "$code" = "000" ]; then
        no "endpoint unreachable (DNS/TLS/connection failed)"
    else
        ok "endpoint reachable (HTTP $code; nothing posted)"
    fi
    if [ "$SEND" = "1" ]; then
        if "$VENV_PY" "$SCRIPT" --target channel --status info \
            --title "teams-notify verification — safe to ignore" \
            --text "Automated reachability test from verify.sh." >/dev/null 2>&1; then
            ok "test card posted to channel"
        else
            no "test card POST failed"
        fi
    fi
fi

echo
echo "[2] Graph (DM) token acquisition"
if [ -z "${GRAPH_TENANT_ID:-}" ] || [ -z "${GRAPH_CLIENT_ID:-}" ]; then
    skip "GRAPH_TENANT_ID/GRAPH_CLIENT_ID unset — DM path not configured"
else
    # Reuses the dispatcher's exact auth path. First run may prompt a one-time device login.
    if "$VENV_PY" - "$REPO_DIR" <<'PY'
import sys
sys.path.insert(0, sys.argv[1] + "/src")
import teams_notify as t
tok = t._graph_token()
print("  token acquired (%d chars)" % len(tok))
PY
    then ok "Graph token acquired"
    else no "Graph token acquisition failed"
    fi
    if [ -n "$DM" ]; then
        if "$VENV_PY" "$SCRIPT" --target "user:$DM" --status info \
            --title "teams-notify verification — safe to ignore" \
            --text "Automated DM test from verify.sh." >/dev/null; then
            ok "test DM sent to $DM"
        else
            no "test DM to $DM failed"
        fi
    fi
fi

echo
echo "[3] Group / meeting chat"
if [ -z "$CHAT" ]; then
    skip "no --chat target — group/meeting chat test not requested"
else
    case "$CHAT" in
        chat:*|group:*) tgt="$CHAT";;
        19:*|*@thread.*) tgt="chat:$CHAT";;
        *)              tgt="group:$CHAT";;
    esac
    if "$VENV_PY" "$SCRIPT" --target "$tgt" --status info \
        --title "teams-notify verification — safe to ignore" \
        --text "Automated chat test from verify.sh." >/dev/null 2>&1; then
        ok "test card posted to $tgt"
    else
        no "post to $tgt failed"
    fi
fi

echo
echo "[4] Global skill install"
# No render step to verify: the skill is a symlink, so 'in sync' is just 'points here'.
SKILL_LINK="$HOME/.claude/skills/teams"
if [ -L "$SKILL_LINK" ] && [ "$(readlink -f "$SKILL_LINK")" = "$REPO_DIR/skills/teams" ]; then
    ok "skill symlinked to this repo (git pull is enough to update it)"
elif [ -d "$SKILL_LINK" ]; then
    ok "skill installed as a copy (Windows-style; re-run the installer after a pull)"
else
    no "skill not installed at $SKILL_LINK — run install.sh"
fi
[ -f "$SKILL_LINK/SKILL.md" ] && ok "SKILL.md reachable" || no "SKILL.md missing at $SKILL_LINK"
if [ -e "$HOME/.claude/commands/teams.md" ]; then
    no "obsolete ~/.claude/commands/teams.md still present — it shadows the skill; run install.sh"
else
    ok "no stale slash command shadowing the skill"
fi
if command -v teams >/dev/null 2>&1; then
    ok "'teams' resolves on PATH ($(command -v teams))"
else
    no "'teams' not on PATH — run install.sh and check ~/.local/bin"
fi
# The skill must stay path-free, or it can no longer be symlinked.
if grep -q '/home/\|__VENV_PY__\|__SCRIPT__' "$REPO_DIR/skills/teams/SKILL.md"; then
    no "SKILL.md contains a machine-specific path — it must stay symlinkable"
else
    ok "SKILL.md is path-free"
fi

echo
echo "Summary: ${G}${pass} passed${N}, ${R}${fail} failed${N}."
[ "$fail" -eq 0 ]
