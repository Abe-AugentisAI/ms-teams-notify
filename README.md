# teams-notify

Send rich Microsoft Teams messages — to a **channel** or a colleague's **DM** — from Claude Code via a `/teams` slash command. Carries status, ad-hoc text, GitHub links, structured facts, and full Adaptive Cards.

## One-line install

**Linux / WSL / macOS**
```bash
git clone <your-remote> ~/teams-notify && bash ~/teams-notify/install.sh
```

**Windows (PowerShell)**
```powershell
git clone <your-remote> $HOME\teams-notify; & $HOME\teams-notify\install.ps1
```

The installer creates an isolated `.venv`, installs dependencies, and drops a path-resolved `/teams` command into `~/.claude/commands/`. Requires `git` and Python 3.

## Configure (one-time)

Edit the `.env` the installer created in the repo root:

| Var | Used for | Where it comes from |
|---|---|---|
| `TEAMS_WEBHOOK_URL` | Channel posts | Teams channel → `•••` → **Workflows** → *"Post to a channel when a webhook request is received"* |
| `GRAPH_TENANT_ID` | DMs | Entra → App registrations → your app → Directory (tenant) ID |
| `GRAPH_CLIENT_ID` | DMs | Same app → Application (client) ID |

**Entra app for DMs** (public client, no secret): New registration → Authentication → enable *Allow public client flows* → API permissions → delegated `Chat.ReadWrite`, `ChatMessage.Send`, `User.Read` → **Grant admin consent**. First DM triggers a one-time device-code login, then the token caches to `~/.config/teams-notify/token_cache.json`.

> Channel posts do not require the Graph app; DMs do not require the webhook. Configure only what you need.

## Usage

```
/teams channel "The nightly verify loop passed on staging" success
/teams user:jordan@example.com "Wave 6 PDF export shipped" info
```

Direct CLI:
```bash
.venv/bin/python src/teams_notify.py --target channel \
  --title "Build passed" --status success \
  --link "PR #142=https://github.com/example/repo/pull/142" \
  --fact "Skill=skill-creator" --fact "Duration=4m12s"

# Pre-built card, from file or stdin:
.venv/bin/python src/teams_notify.py --target user:sam@example.com --card-file report.json
your-generator | .venv/bin/python src/teams_notify.py --target channel --card-file -
```

## Notes

- Legacy Teams "Incoming Webhook" connectors retire May 2026 — this uses **Workflows**, the sanctioned replacement.
- DMs send **as you** (delegated). Channel posts appear from the **Flow bot** (a Microsoft platform constraint).
- To scope `/teams` to a single repo instead of globally, copy `commands/teams.md` into that project's `.claude/commands/` and point it at the repo's `.venv`.
