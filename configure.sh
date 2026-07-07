#!/usr/bin/env bash
# configure.sh — populate .env in one command (press Enter to keep the current value).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$REPO_DIR/.env"

# Load existing values (if any) so they become the defaults.
if [ -f "$ENV_FILE" ]; then set -a; . "$ENV_FILE"; set +a; fi

ask() {
    # ask VAR "Human label"  ->  prints chosen value on stdout
    local var="$1" label="$2" cur ans
    eval "cur=\${$var:-}"
    local shown="${cur:-<unset>}"
    read -r -p "$label [$shown]: " ans
    printf '%s' "${ans:-$cur}"
}

echo "Populating $ENV_FILE"
echo "(leave blank to keep the shown value; only what you need is required)"
echo
WEBHOOK="$(ask TEAMS_WEBHOOK_URL 'Teams Workflows webhook URL')"
TENANT="$(ask GRAPH_TENANT_ID  'Entra tenant (Directory) ID')"
CLIENT="$(ask GRAPH_CLIENT_ID   'Entra application (client) ID')"

umask 077
cat > "$ENV_FILE" <<EOF
# Populated by configure.sh — teams_notify.py auto-loads this file.
TEAMS_WEBHOOK_URL=$WEBHOOK
GRAPH_TENANT_ID=$TENANT
GRAPH_CLIENT_ID=$CLIENT
EOF
chmod 600 "$ENV_FILE"

echo
echo "Wrote $ENV_FILE (permissions 600)."
echo "Next: bash verify.sh"
