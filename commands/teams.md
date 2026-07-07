---
description: Post a status/message with GitHub links to a Teams channel or a colleague's DM.
argument-hint: <channel|user:upn> "<title>" [status] [notes...]
allowed-tools: Bash(__VENV_PY__ __SCRIPT__:*)
---

You are posting a Microsoft Teams notification via the teams-notify tool.

**Requested target and message:** $ARGUMENTS

Steps:
1. Parse the request into these fields:
   - `--target`: `channel` for a team channel, or `user:<upn>` for a direct message
     (e.g. `user:jordan@example.com`). Default to `channel` if unspecified.
   - `--title`: a **declarative, full-sentence** title (assertion-evidence style),
     e.g. "The nightly verify loop passed on staging" — not a topic fragment.
   - `--status`: one of `success | warn | fail | info`. Infer from context
     (build passed -> success, failure -> fail) or default to `info`.
   - `--text`: optional one-line body.
   - `--fact "Key=value"`: repeatable. Add useful context (skill name, duration, env).
   - `--link "Label=https://..."`: repeatable. Include any GitHub PRs, issues, or files
     relevant to the message. If the user referenced a PR/issue/commit, build the URL.

2. If this message is reporting on a skill or task that just ran in this session,
   summarize its outcome into `--title`/`--text`/`--fact` before sending.

   For richer summaries (e.g. an nightly-build run report), you may instead write a full
   Adaptive Card JSON and pass it via `--card-file <path>` or pipe it with `--card-file -`.
   When `--card-file` is used, the build flags above are ignored.

3. Run the tool with the assembled flags:
   `__VENV_PY__ __SCRIPT__ ...`
   Do **not** invent secrets — the script auto-loads `TEAMS_WEBHOOK_URL`,
   `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID` from the repo `.env`.

4. Report back the tool's `[ok]`/`[error]` line verbatim. If a DM triggers a device-code
   login prompt, surface the sign-in URL/code to the user.
