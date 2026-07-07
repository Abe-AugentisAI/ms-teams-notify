#!/usr/bin/env bash
# verify.sh — sanity-check both delivery paths.
#   bash verify.sh              reachability + token acquisition only (posts nothing)
#   bash verify.sh --send       also POST a labeled test card to the channel (visible)
#   bash verify.sh --dm <upn>   also send a labeled test DM to <upn> (visible to them)
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$REPO_DIR/.env"
VENV_PY="$REPO_DIR/.venv/bin/python"
SCRIPT="$REPO_DIR/src/teams_notify.py"

SEND=0; DM=""
while [ $# -gt 0 ]; do
    case "$1" in
        --send) SEND=1; shift;;
        --dm) DM="${2:-}"; shift 2;;
        *) echo "unknown argument: $1"; exit 2;;
    esac
done

if [ -t 1 ]; then G=$'\e[32m'; R=$'\e[31m'; Y=$'\e[33m'; N=$'\e[0m'; else G=; R=; Y=; N=; fi
pass=0; fail=0
ok()   { echo "  ${G}PASS${N} $1"; pass=$((pass+1)); }
no()   { echo "  ${R}FAIL${N} $1"; fail=$((fail+1)); }
skip() { echo "  ${Y}SKIP${N} $1"; }

[ -f "$ENV_FILE" ] && { set -a; . "$ENV_FILE"; set +a; }

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
            --text "Automated DM test from verify.sh." >/dev/null 2>&1; then
            ok "test DM sent to $DM"
        else
            no "test DM to $DM failed"
        fi
    fi
fi

echo
echo "Summary: ${G}${pass} passed${N}, ${R}${fail} failed${N}."
[ "$fail" -eq 0 ]
