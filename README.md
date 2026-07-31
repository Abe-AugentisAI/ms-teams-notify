# teams-notify

Send rich Microsoft Teams messages — to a **channel**, a colleague's **DM**, or a **group/meeting chat** — from Claude Code via a `/teams` slash command. Carries status, ad-hoc text, GitHub links, structured facts, and full Adaptive Cards.

## One-line install

**Linux / WSL / macOS**
```bash
git clone git@github.com:Abe-AugentisAI/ms-teams-notify.git ~/teams-notify && bash ~/teams-notify/install.sh
```

**Windows (PowerShell)**
```powershell
git clone git@github.com:Abe-AugentisAI/ms-teams-notify.git $HOME\teams-notify; & $HOME\teams-notify\install.ps1
```

The installer creates an isolated `.venv`, puts a `teams` command on your `PATH`, and links the `/teams` skill into `~/.claude/skills/` so it is available in **every** project. Requires `git` and Python 3.

The skill is **symlinked** to `skills/teams/` in this repo, so `git pull` updates it with no reinstall — the live skill and the committed file are the same file and cannot drift. (Windows copies instead, since symlinks need Developer Mode; re-run `install.ps1` after a pull.)

## Configure (one-time)

Edit the `.env` the installer created in the repo root:

| Var | Used for | Where it comes from |
|---|---|---|
| `TEAMS_WEBHOOK_URL` | Channel posts | Teams channel → `•••` → **Workflows** → *"Post to a channel when a webhook request is received"* |
| `GRAPH_TENANT_ID` | DMs & chats | Entra → App registrations → your app → Directory (tenant) ID |
| `GRAPH_CLIENT_ID` | DMs & chats | Same app → Application (client) ID |

**Entra app for DMs & group/meeting chats** (public client, no secret): New registration → Authentication → enable *Allow public client flows* → API permissions → delegated `Chat.ReadWrite`, `ChatMessage.Send`, `User.Read` → **Grant admin consent**. The first DM or chat post triggers a one-time device-code login, then the token caches to `~/.config/teams-notify/token_cache.json`.

> Channel posts do not require the Graph app; DMs and chats do not require the webhook. Configure only what you need.

**Fast path:** run `bash configure.sh` to populate `.env` in one command (press Enter to keep any existing value), then `bash verify.sh` to sanity-check the paths. By default `verify.sh` posts nothing — it checks webhook reachability and acquires a Graph token. Add `--send` (channel), `--dm <upn>` (direct message), or `--chat <id|topic>` (group/meeting chat) to post one labeled test card; `bash verify.sh --list` prints your group/meeting chat ids without sending anything.

## Usage

```
/teams channel "The nightly verify loop passed on staging" success
/teams user:jordan@example.com "Wave 6 PDF export shipped" info
/teams user:Jordan "Wave 6 PDF export shipped" info
/teams group:Team Stand-Up "Nightly build is green" success
```

**Targets** (`--target`):

| Target | Destination | Needs |
|---|---|---|
| `channel` | The team channel wired to the webhook | `TEAMS_WEBHOOK_URL` |
| `user:<upn>` | A 1:1 direct message, sent as you | Graph app |
| `user:<name>` | The same DM, by display/first name (errors if ambiguous) | Graph app |
| `chat:<id>` | An existing group or **meeting** chat, by its Graph chat id | Graph app |
| `group:<topic>` | A group/meeting chat resolved by name (errors if ambiguous) | Graph app |
| `list-chats` | Prints your group/meeting chats + ids for discovery (sends nothing) | Graph app |
| `list-people` | Prints people + the `user:` target that reaches each (sends nothing) | Graph app |

Direct CLI:
```bash
.venv/bin/python src/teams_notify.py --target channel \
  --title "Build passed" --status success \
  --link "PR #142=https://github.com/example/repo/pull/142" \
  --fact "Skill=skill-creator" --fact "Duration=4m12s"

# @-mention real people in a group/meeting chat so Teams actually notifies them:
.venv/bin/python src/teams_notify.py --target "group:Team Stand-Up" \
  --title "Nightly build is green" --status success --mention Taylor --mention chris@example.com

# Group or meeting chat — by name, or by id from `--target list-chats`:
.venv/bin/python src/teams_notify.py --target "group:Team Stand-Up" \
  --title "Nightly build is green" --status success
.venv/bin/python src/teams_notify.py --target list-chats   # discover chat ids/topics (sends nothing)

# Pre-built card, from file or stdin:
.venv/bin/python src/teams_notify.py --target user:sam@example.com --card-file report.json
your-generator | .venv/bin/python src/teams_notify.py --target channel --card-file -
```

## Nicknames (aliases)

Give any target a short nickname, then use it anywhere a target goes — matching is case-, space-, and punctuation-insensitive (`StandUp`, `standup`, `stand-up` all work):

```bash
bash alias.sh add StandUp "Team Stand-Up"   # bare topic → resolves + pins chat:<id>
bash alias.sh add sam user:sam@example.com            # or map to any full target
bash alias.sh list                                        # show saved nicknames
bash alias.sh rm StandUp
```

```
/teams standup "Nightly build is green" success
```
```bash
.venv/bin/python src/teams_notify.py --target standup --title "Nightly build is green" --status success
.venv/bin/python src/teams_notify.py --target alias-list   # show saved nicknames
```

Aliases live in `~/.config/teams-notify/aliases.json` (user-level, not committed to the repo). `add` accepts a full target (`channel`, `user:<upn>`, `chat:<id>`, `group:<topic>`) or a bare chat topic, which it resolves once and pins as `chat:<id>`.

## Notes

- Legacy Teams "Incoming Webhook" connectors retire May 2026 — this uses **Workflows**, the sanctioned replacement.
- DMs and group/meeting-chat posts send **as you** (delegated, via the same Graph app). Channel posts appear from the **Flow bot** (a Microsoft platform constraint).
- `chat:<id>` / `group:<topic>` post to any chat you're a member of — including recurring **meeting** chats (that's how "Daily Stand-Up"–style chats are reached). Use `--target list-chats` to find ids.
- **`--mention` is the only way to actually notify someone.** A Teams @-mention needs both
  an `<at id="N">` tag in the message body *and* a matching entry in the Graph `mentions`
  array carrying the person's AAD object id — plain "@Name" text pings nobody. So an
  unresolvable name is a hard error that lists the chat roster rather than a silent no-op —
  and so is an *ambiguous* one, since picking the first of two same-named members would
  notify the wrong person while reporting success. It works on `chat:`/`group:` targets only
  (including an alias that expands to one) and is rejected on `channel` and on `user:`
  targets; the person must already be in the chat.
- **Name lookup (`user:<name>`) resolves against people in your existing chats**, not the
  directory — a directory search would need `User.ReadBasic.All`, an extra admin-consented
  permission and a forced re-login. Someone you share no chat with must be addressed by
  full `user:<upn>`. Matching tries exact forms first (full name, address, address
  local-part, a whole first/last name) and only falls back to substring, so `Chris` will
  not be swallowed by `Christa`. First names are ambiguous often in a real tenant — on more
  than one match the tool prints the candidates with their addresses and **sends nothing**.
- **Do not copy the skill into a project's `.claude/`.** It is deliberately global — one entry in `~/.claude/skills/teams`, live in every project. A project-local `.claude/skills/teams/` or `.claude/commands/teams.md` would shadow it, and you would be editing a stale fork.
