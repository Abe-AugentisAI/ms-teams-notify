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

**Fast path:** run `bash configure.sh` to populate `.env` in one command (press Enter to keep any existing value), then `bash verify.sh` to sanity-check both paths. By default `verify.sh` posts nothing — it checks webhook reachability and acquires a Graph token. Add `--send` to post a labeled test card, or `--dm <upn>` to test a direct message.

## Usage

```
/teams channel "The nightly verify loop passed on staging" success
/teams user:jordan@example.com "Wave 6 PDF export shipped" info
/teams group:Team Stand-Up "Nightly build is green" success
```

**Targets** (`--target`):

| Target | Destination | Needs |
|---|---|---|
| `channel` | The team channel wired to the webhook | `TEAMS_WEBHOOK_URL` |
| `user:<upn>` | A 1:1 direct message, sent as you | Graph app |
| `chat:<id>` | An existing group or **meeting** chat, by its Graph chat id | Graph app |
| `group:<topic>` | A group/meeting chat resolved by name (errors if ambiguous) | Graph app |
| `list-chats` | Prints your group/meeting chats + ids for discovery (sends nothing) | Graph app |

Direct CLI:
```bash
.venv/bin/python src/teams_notify.py --target channel \
  --title "Build passed" --status success \
  --link "PR #142=https://github.com/example/repo/pull/142" \
  --fact "Skill=skill-creator" --fact "Duration=4m12s"

# Group or meeting chat — by name, or by id from `--target list-chats`:
.venv/bin/python src/teams_notify.py --target "group:Team Stand-Up" \
  --title "Nightly build is green" --status success
.venv/bin/python src/teams_notify.py --target list-chats   # discover chat ids/topics (sends nothing)

# Pre-built card, from file or stdin:
.venv/bin/python src/teams_notify.py --target user:sam@example.com --card-file report.json
your-generator | .venv/bin/python src/teams_notify.py --target channel --card-file -
```

## Notes

- Legacy Teams "Incoming Webhook" connectors retire May 2026 — this uses **Workflows**, the sanctioned replacement.
- DMs and group/meeting-chat posts send **as you** (delegated, via the same Graph app). Channel posts appear from the **Flow bot** (a Microsoft platform constraint).
- `chat:<id>` / `group:<topic>` post to any chat you're a member of — including recurring **meeting** chats (that's how "Daily Stand-Up"–style chats are reached). Use `--target list-chats` to find ids.
- To scope `/teams` to a single repo instead of globally, copy `commands/teams.md` into that project's `.claude/commands/` and point it at the repo's `.venv`.
