#!/usr/bin/env bash
# teams-notify installer (Linux / WSL / macOS)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "==> teams-notify: installing from $REPO_DIR"

command -v "$PY" >/dev/null 2>&1 || { echo "[error] '$PY' not found. Install Python 3."; exit 1; }

echo "==> Creating virtual environment (.venv)"
"$PY" -m venv "$REPO_DIR/.venv"
"$REPO_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$REPO_DIR/.venv/bin/pip" install --quiet -r "$REPO_DIR/requirements.txt"

echo "==> Installing the /teams slash command"
CMD_DIR="$HOME/.claude/commands"
mkdir -p "$CMD_DIR"
VENV_PY="$REPO_DIR/.venv/bin/python"
SCRIPT="$REPO_DIR/src/teams_notify.py"
sed -e "s|__VENV_PY__|$VENV_PY|g" -e "s|__SCRIPT__|$SCRIPT|g" \
    "$REPO_DIR/commands/teams.md" > "$CMD_DIR/teams.md"

echo "==> Preparing .env"
if [ ! -f "$REPO_DIR/.env" ]; then
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
    chmod 600 "$REPO_DIR/.env"
    echo "    created $REPO_DIR/.env  (fill in your values)"
else
    echo "    $REPO_DIR/.env already exists — left untouched"
fi

cat <<EOF

Done. Next:
  1. Edit $REPO_DIR/.env with your Teams webhook + Graph app values.
  2. Test:  $VENV_PY $SCRIPT --target channel --title "Install check" --status success
  3. In Claude Code (any project):  /teams channel "Install check" success
EOF
