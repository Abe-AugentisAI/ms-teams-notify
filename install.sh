#!/usr/bin/env bash
# teams-notify installer (Linux / WSL / macOS)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

echo "==> teams-notify: installing from $REPO_DIR"

command -v "$PY" >/dev/null 2>&1 || { echo "[error] '$PY' not found. Install Python 3."; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' \
    || { echo "[error] '$PY' is older than 3.8 (python-dotenv needs >= 3.8)."; exit 1; }
"$PY" -m ensurepip --version >/dev/null 2>&1 \
    || { echo "[error] '$PY' cannot create venvs (ensurepip missing). Debian/Ubuntu: sudo apt-get install -y python3-venv"; exit 1; }

echo "==> Creating virtual environment (.venv)"
"$PY" -m venv "$REPO_DIR/.venv"
"$REPO_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$REPO_DIR/.venv/bin/pip" install --quiet -r "$REPO_DIR/requirements.txt"

echo "==> Installing the 'teams' command on PATH"
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
chmod +x "$REPO_DIR/bin/teams"
ln -sfn "$REPO_DIR/bin/teams" "$BIN_DIR/teams"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo "    [warn] $BIN_DIR is not on PATH — add it to your shell profile" ;;
esac

echo "==> Installing the global /teams skill"
# Symlinked, not rendered: bin/teams resolves its own location, so SKILL.md carries no
# machine-specific paths and the live skill IS the committed file. `git pull` is therefore
# enough to update it, and the two can never drift.
SKILL_DIR="$HOME/.claude/skills"
mkdir -p "$SKILL_DIR"
if [ -e "$SKILL_DIR/teams" ] && [ ! -L "$SKILL_DIR/teams" ]; then
    echo "    [warn] $SKILL_DIR/teams exists and is not a symlink — leaving it alone"
else
    ln -sfn "$REPO_DIR/skills/teams" "$SKILL_DIR/teams"
fi

echo "==> Installing the cross-agent skill (~/.agents/skills)"
# ~/.agents/skills is the agentskills.io cross-client convention, read by Codex,
# Antigravity, Gemini CLI, Cursor, Copilot, Amp, Goose, and others. Those hosts honor
# only name/description frontmatter — Claude-specific fields are ignored harmlessly.
AGENTS_SKILL_DIR="$HOME/.agents/skills"
mkdir -p "$AGENTS_SKILL_DIR"
if [ -e "$AGENTS_SKILL_DIR/teams" ] && [ ! -L "$AGENTS_SKILL_DIR/teams" ]; then
    echo "    [warn] $AGENTS_SKILL_DIR/teams exists and is not a symlink — leaving it alone"
else
    ln -sfn "$REPO_DIR/skills/teams" "$AGENTS_SKILL_DIR/teams"
fi

echo "==> Installing the Antigravity skill (~/.gemini/config/skills)"
# Antigravity reads .agents/skills only at workspace level; its global path — the one
# shared by AGY, the agy CLI, and the IDE — is ~/.gemini/config/skills.
GEMINI_SKILL_DIR="$HOME/.gemini/config/skills"
mkdir -p "$GEMINI_SKILL_DIR"
if [ -e "$GEMINI_SKILL_DIR/teams" ] && [ ! -L "$GEMINI_SKILL_DIR/teams" ]; then
    echo "    [warn] $GEMINI_SKILL_DIR/teams exists and is not a symlink — leaving it alone"
else
    ln -sfn "$REPO_DIR/skills/teams" "$GEMINI_SKILL_DIR/teams"
fi

# Retire the pre-symlink slash command; two entries named 'teams' would shadow each other.
if [ -e "$HOME/.claude/commands/teams.md" ]; then
    rm -f "$HOME/.claude/commands/teams.md"
    echo "    removed obsolete ~/.claude/commands/teams.md (superseded by the skill)"
fi

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
  2. Test (sends nothing):  teams --target list-people
  3. In Claude Code, any project:  /teams channel "Install check" success

The skill is SYMLINKED from $REPO_DIR/skills/teams, so 'git pull' updates it with no
reinstall. Re-run this installer only after changing bin/, the venv, or the repo path.
Restart Claude Code to pick up a newly installed skill.
EOF
