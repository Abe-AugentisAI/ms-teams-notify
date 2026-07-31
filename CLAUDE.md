# CLAUDE.md — teams-notify

Guidance for Claude Code working in this repository.

## What this is

A small tool that posts rich Adaptive Cards to Microsoft Teams from Claude Code via a
`/teams` slash command. It has two delivery mechanisms:

- **Channel** → a Power Automate **Workflows** incoming webhook (no auth in the CLI).
- **DMs and group/meeting chats** → **Microsoft Graph**, delegated, using an MSAL
  device-code flow with a cached token.

There is no server and no build step. The entry point is a single Python script.

## Repo layout

| Path | Role |
|---|---|
| `src/teams_notify.py` | The whole dispatcher — card building + all delivery paths. |
| `commands/teams.md` | Template for the `/teams` slash command. Contains `__VENV_PY__` / `__SCRIPT__` placeholders. |
| `install.sh` / `install.ps1` | Create `.venv`, install deps, generate the live `/teams` command, seed `.env`. |
| `configure.sh` | Interactively populate `.env` (writes values **single-quoted**). |
| `verify.sh` | Smoke-test the delivery paths. Posts nothing unless asked. |
| `alias.sh` | Manage `/teams` target nicknames (`list` / `add` / `rm`). |
| `.env.example` | Template copied to `.env` by the installer. |
| `requirements.txt` | `requests`, `msal`, `python-dotenv`. |

`.env` and `.venv/` are git-ignored. **Never commit `.env`** — it holds the webhook URL
(a bearer secret) and the Graph app IDs.

## `--target` types (in `teams_notify.py`)

- `channel` — the channel wired to `TEAMS_WEBHOOK_URL`.
- `user:<upn>` — a 1:1 DM (creates/reuses a oneOnOne chat), sent as the signed-in user.
- `user:<name>` — the same DM by display/first name, resolved against chat members;
  errors and lists candidates with their addresses if ambiguous.
- `chat:<id>` — post to any existing chat by its Graph id (group, **meeting**, or 1:1).
- `group:<topic>` — resolve a group/meeting chat by topic (case-insensitive substring);
  errors and lists candidates if the name is ambiguous.
- `list-chats` — print the user's group/meeting chats + ids; sends nothing.
- `list-people` — print people + the `user:` target that reaches each (address where known,
  display name otherwise); members Graph exposes with neither are flagged as not
  addressable. Sends nothing.
- `<nickname>` — a saved alias that expands to any of the above (see **Aliases** below).
- `alias-list` — print saved aliases; sends nothing.

Shared internals: `_post_card()` posts a card to a chat id; `_iter_chats()` pages
`/me/chats`; `_resolve_chat_by_topic()` backs `group:`; `_resolve_alias()` / `_norm_alias()`
back nicknames. `_iter_people()` / `_match_people()` / `resolve_person()` back `user:<name>`;
`resolve_mentions()` backs `--mention`.

**`--mention` (chat/group only).** A Teams @-mention notifies someone only when the message
carries BOTH an `<at id="N">` tag in the HTML body AND a matching entry in the Graph
`mentions` array with the person's AAD object id — plain "@Name" text pings nobody. So
`resolve_mentions()` maps each requested name against the target chat's members and treats
an unresolvable name as a hard error that prints the roster, never a silent no-op;
`_post_card()` then builds the prefix and the array together. `main()` rejects `--mention`
on any target that is not `chat:`/`group:` (checked once after alias expansion, so an alias
expanding to `user:`/`channel` is caught too) — a 1:1 DM has only two members, so
`resolve_mentions()` would hard-exit on any third party anyway. The body prefix is
`html.escape()`d because the body is `contentType: html`; `mentionText` stays plain.

**Why name lookup reads chat members, not the directory.** `/users?$search=` needs
`User.ReadBasic.All`; the app holds only `User.Read` (own profile). Adding it means a new
Entra permission, fresh admin consent, and a re-login, because the cached token would not
carry the scope. Chat membership is already readable under `Chat.ReadWrite`, and the people
you DM are people you share a chat with — so `_iter_people()` builds the roster from
`_iter_chats()` members. It collapses records on the email address: one human can hold
several AAD object ids (tenant member in one chat, federated guest in another), and without
that the ambiguity error prints the same address twice and cannot be acted on. For the same
reason a name-resolved DM binds by **address** when there is one (object id only as the
fallback for members Graph exposes without an address) — among duplicate object ids there
is no reliable way to tell which is live.

## Aliases (nicknames)

Short-form target names live in `~/.config/teams-notify/aliases.json` (user-level, **not
committed** — keeps internal chat topics/ids out of git). Before dispatch,
`teams_notify.py` expands a bareword target via `_resolve_alias()` (normalized by
`_norm_alias()`, so case/space/punctuation don't matter); explicit forms
(`channel`/`user:`/`chat:`/`group:`/`list-chats`/`list-people`/`alias-list`) are never
shadowed. `--target alias-list`
prints them. `alias.sh` (`list`/`add`/`rm`) edits the JSON and reuses
`_resolve_chat_by_topic()`, so `add <name> <topic>` pins the resolved `chat:<id>`. Alias
values are always full targets.

## Configuration

`.env` (auto-loaded by `teams_notify.py` and `verify.sh` via **python-dotenv**):

- `TEAMS_WEBHOOK_URL` — channel only.
- `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID` — DMs + chats (a public-client Entra app with
  *Allow public client flows* on and delegated Graph `Chat.ReadWrite`, `ChatMessage.Send`,
  `User.Read`, admin-consented).

The first Graph call triggers a one-time **device-code login** (prints a
`microsoft.com/devicelogin` URL + code to stderr, then blocks until the user signs in).
The token caches to `~/.config/teams-notify/token_cache.json` (mode 600); later calls are
silent. Because the login is interactive, it must be completed by the user in a browser —
do not expect a non-interactive shell to complete it on the first run.

## Testing

`verify.sh` is the smoke test (there is no unit-test suite):

```bash
bash verify.sh            # toolchain + webhook reachability + Graph token; POSTS NOTHING
bash verify.sh --send     # + one labeled test card to the channel
bash verify.sh --dm <upn|name>    # + one labeled test DM
bash verify.sh --chat <id|topic>  # + one labeled test to a group/meeting chat
bash verify.sh --list     # print group/meeting chat ids (sends nothing) and exit
```

Default run must stay side-effect-free: unset paths **SKIP**, nothing is posted.

## Conventions & gotchas

- **`.env` values are single-quoted.** Webhook URLs contain `&`; an unquoted value breaks
  bash `source`. `configure.sh` writes quotes; `verify.sh` and `teams_notify.py` read `.env`
  through python-dotenv (never bash-source it), so the two always agree. Preserve this if
  you touch `.env` handling.
- **Regenerate the live command after editing `commands/teams.md`.** The installed file at
  `~/.claude/commands/teams.md` is generated by substituting the placeholders:
  ```bash
  VENV_PY="$PWD/.venv/bin/python"; SCRIPT="$PWD/src/teams_notify.py"
  sed -e "s|__VENV_PY__|$VENV_PY|g" -e "s|__SCRIPT__|$SCRIPT|g" \
      commands/teams.md > "$HOME/.claude/commands/teams.md"
  ```
- **Never invent secrets.** The script pulls all secrets from `.env`; don't hardcode them.
- Channel posts appear from the **Flow bot**; DMs/chats send **as the signed-in user**
  (Microsoft platform behavior, not a bug).
- Graph requires the Adaptive Card as a JSON **string** inside the attachment `content`.

## Dev environment

Python 3, isolated `.venv` created by the installer. On Debian/Ubuntu, `python3 -m venv`
needs the `python3-venv` package (`sudo apt-get install -y python3.X-venv`); `install.sh`
assumes it is present. Run the tool via `.venv/bin/python src/teams_notify.py …`.
