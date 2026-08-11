---
name: teams
description: Use when the user wants to send, post, or share something on Microsoft Teams — message, DM, or ping a colleague by name, notify or tag someone, drop an update in a group, meeting, or stand-up chat, post a build/deploy/PR/test result to the team channel, or announce that something shipped, passed, failed, or needs review. Also use to look up who or what is reachable on Teams — list people, chats, or saved nicknames. Sends real messages as the signed-in user and they cannot be unsent, so it always confirms the target and content before posting. Do not use for email (that is Outlook) or for reading Teams history.
user-invocable: true
argument-hint: <channel|user:upn|user:name|chat:id|group:topic|nickname> "<title>" [status] [notes...]
allowed-tools:
  - Bash(teams --target list-people)
  - Bash(teams --target list-chats)
  - Bash(teams --target alias-list)
---

Post a rich Adaptive Card to Microsoft Teams — a channel, a colleague's DM, or a
group/meeting chat — via the `teams` CLI.

**Requested target and message:** $ARGUMENTS

## Rule 0 — sending is irreversible

Messages post **as the signed-in user** to real colleagues, and Microsoft Graph provides no
delete: a wrong message can only be removed by hand in the Teams UI. Therefore:

- **Never infer a target.** There is no default destination. If the user did not name one,
  ask. Do not fall back to `channel`.
- **Preview with `--dry-run`, then confirm.** Adding `--dry-run` resolves the target and
  prints the exact card without sending anything or creating a chat. Use it to show the
  user precisely who this reaches and what they will see, then re-run the identical command
  without the flag once they agree. Never run a send command to "check that it resolves" —
  there is no other way to inspect a target, and the message posts.
- **Never guess between candidates.** Ambiguous names are a hard error by design; relay the
  candidates and ask which was meant.
- The discovery targets below send nothing and need no confirmation — prefer them when the
  user is only asking *who* or *where*, not asking to post.

Only the three discovery commands are pre-approved in `allowed-tools`; every send raises a
real permission prompt. That is deliberate — it is the one machine-enforced checkpoint in
front of an irreversible message, and it still applies in contexts that never read this
file. Do not work around it.

You cannot DM yourself: Graph has no 1:1 chat with a single member. Your own notes are
`--target chat:48:notes` (it accepts a card but not a `--mention`).

## Discovery (sends nothing)

```bash
teams --target list-people    # who is addressable, with the user: target that reaches each
teams --target list-chats     # group/meeting chats + their chat: ids
teams --target alias-list     # saved nicknames
teams --dry-run --target <t> --title "..."   # resolve + preview the card; sends nothing
```

## Targets

| Target | Goes to |
|---|---|
| `channel` | the team channel wired to the webhook (posts as the Flow bot) |
| `user:<upn>` | a 1:1 DM, e.g. `user:jordan@example.com` |
| `user:<name>` | the same DM by display or first name, e.g. `user:Jordan` |
| `chat:<id>` | a group or meeting chat by Graph id, e.g. `chat:19:meeting_...@thread.v2` |
| `group:<topic>` | a group/meeting chat by name, e.g. `group:Team Stand-Up` |
| `<nickname>` | a saved alias (case/space/punctuation-insensitive) expanding to any of the above |

`user:<name>` resolves against people you already share a chat with — not the directory — so
someone you share no chat with needs their full `user:<upn>`. First names are frequently
ambiguous in a real tenant; on more than one match the tool prints the candidates and sends
nothing. Pass one of the printed values verbatim. `group:<topic>` behaves the same way.

Name/topic resolution, `list-people`, and `list-chats` walk every chat through paginated
Graph calls — expect **30–120 s**, with `[scan] N chats scanned…` progress on stderr. Wait
for completion; **never kill and re-run a slow `teams` command** — each retry restarts the
full walk from zero. `user:<upn>` and `chat:<id>` targets skip the walk and are fast.

## Composing

- `--title` — a **declarative, full-sentence** assertion, e.g. "The nightly-build verify loop
  passed on staging". Not a topic fragment.
- `--status` — `success | warn | fail | info`. Infer it (build passed → success, failure →
  fail); default `info`.
- `--text` — optional one-line body.
- `--fact "Key=value"` — repeatable. Context worth carrying: skill, duration, environment.
- `--link "Label=https://..."` — repeatable. Include any GitHub PR, issue, or file the user
  referenced; build the URL from the reference.
- `--mention "<name>"` — repeatable, and the **only** way to actually notify someone.
  Writing "@Name" into `--text` renders as plain text and notifies **nobody**. Works on
  `chat:`/`group:` targets only; rejected on `channel` and on `user:` targets, since a DM
  already notifies its recipient. The person must already be in that chat. A name matching
  nobody — or more than one member — is a hard error listing the candidates.

For a richer report, write a full Adaptive Card JSON and pass `--card-file <path>` (or pipe
it with `--card-file -`); the compose flags above are then ignored.

If the message reports on work that just ran in this session, summarize the real outcome
into `--title`/`--text`/`--fact` first. Never invent secrets — the CLI loads
`TEAMS_WEBHOOK_URL`, `GRAPH_TENANT_ID`, and `GRAPH_CLIENT_ID` from its own `.env`.

## Examples

```bash
teams --target "group:Team Stand-Up" \
  --title "Nightly build is green" --status success --mention Taylor

teams --target sam \
  --title "Feature X dispatch merged" --status success \
  --link "PR #142=https://github.com/example/repo/pull/142"
```

## Reporting back

Relay the tool's `[ok]` / `[dry-run]` / `[error]` line verbatim — never paraphrase a
failure into a success, and never report a `[dry-run]` preview as though it were sent. If a first run triggers a device-code login, surface the sign-in URL and code to
the user; that login is interactive and cannot be completed non-interactively.
