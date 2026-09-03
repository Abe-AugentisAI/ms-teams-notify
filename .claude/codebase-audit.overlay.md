# Codebase-audit overlay — ms-teams-notify

Read by `/codebase-audit` (Step 0). Every section is optional; delete what does not apply.

## Base branch

`main`

## Principles with severity floors

Findings that touch one of these publish at **P1 or higher** and name the principle in the issue body.

| Principle | Meaning | Canary test (never weaken) |
|---|---|---|
| <name> | <one line> | `<path>` |

## Label vocabulary (reuse; never invent parallel names)

Existing labels: `bug`, `enhancement`, … Issue types (if enabled): `Bug`, `Task`. Mapping labels to add when a finding maps cleanly: …

## Report path

`docs/audits/codebase-audit-YYYY-MM-DD.md`

## Cell hints (optional)

Dirs the profile step should treat as cross-cutting, worker entrypoints, generated code to exclude, design canon files.

## Hazards (read before running any command)

- <package-manager pins, env vars tests need, commands that must never run, CI quirks>

## Known-open issues not to re-discover

- #<n> <title>
