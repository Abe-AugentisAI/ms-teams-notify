---
description: Full end-to-end codebase audit (security, correctness, performance, simplification, test/CI/infra/docs drift) that profiles the repo, fans out parallel reviewers, adversarially verifies every finding, deduplicates against open GitHub issues, and publishes each confirmed finding as a story-pointed issue ready for triage
argument-hint: "[--scope <path|area>] [--dimension security|correctness|performance|simplification|quality|all] [--min-severity P0|P1|P2|P3] [--dry-run] [--no-enrich] [--since <git-ref>] [--base <branch>]"
---

<!--
  Project-agnostic. Everything repository-specific lives in an optional overlay
  file at `.claude/codebase-audit.overlay.md` (principles with severity floors,
  label vocabulary, report path, cell hints, hazards, known-open issues). The
  command works with no overlay at all.

  Install for one repo: keep this file at `.claude/commands/codebase-audit.md`.
  Install for every repo on a machine: copy it to `~/.claude/commands/codebase-audit.md`
  (user-level commands are discovered in any project) and add an overlay per repo.
  Progress is observable from the CLI and from a Claude Code web/desktop session
  on the same repo: the report file lands in the repo, and issues carry the
  `audit` label, so any surface can read the state.
-->

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Goal

Produce a verified, deduplicated inventory of defects and improvement
opportunities across the codebase and turn each one into a GitHub issue with
a severity, an area, and a Fibonacci story-point estimate so the team can
triage and assign. The audit is **evidence-first**: a finding that cannot be
tied to a file and line, reproduced, or demonstrated with a failing check is
not published.

It reads code, tests, config, CI, and infra. It does not grade sprint or
roadmap progress; use the project's planning tooling for that.

## Arguments

| Flag | Effect |
|------|--------|
| *(empty)* | Full audit: all areas, all dimensions, publish P0–P3 |
| `--scope <s>` | Restrict to one area from the profile (`backend`, `frontend`, `infra`, a package name) or a path prefix. Default all |
| `--dimension <d>` | Restrict to one dimension (see Step 2). Default `all` |
| `--min-severity <P>` | Only publish findings at or above this severity. Default `P3` |
| `--dry-run` | Run every step, write the report, create **no** issues and post **no** comments; print the exact payloads that would be sent |
| `--no-enrich` | Never comment on or relabel an existing issue; only avoid filing duplicates |
| `--since <ref>` | Limit deep review to files changed since `<ref>` on the base branch (incremental). Scanners still run on the whole tree |
| `--base <branch>` | Branch to audit. Default: the overlay's base branch, else the repo default branch |

## Severity rubric

| Severity | Definition | Examples |
|---|---|---|
| P0 | Exploitable in the deployed product, or silent data loss/corruption on a main path | Auth bypass, IDOR, SQL/command injection, secret in repo, mutable audit log, unauthorized data egress |
| P1 | Security weakness needing preconditions, authorization gap, missing audit trail on a mutating path, a user-facing defect in a core flow, or any violation of an overlay principle | Missing rate limit on login, stale-state authorization, state machine allows a wrong transition, hard-coded credential seeded by a migration |
| P2 | Robustness, performance, or maintainability defect with a plausible production trigger | N+1 query, unbounded list endpoint, blocking I/O in an async path, job timeout not enforced, flaky or quarantined test masking coverage, Docker/CI fragility |
| P3 | Simplification, dead code, duplicated logic, docs drift, minor a11y or i18n inconsistency | Duplicate helper, unused module, README steps that no longer work |

Overlay principles raise the floor: any finding touching one publishes at **≥ P1** and names the principle in the body.

## Story-point rubric (Fibonacci, top-level only)

| SP | Meaning |
|---|---|
| 1 | One-line or config change; existing test covers it |
| 2 | Local fix in one function plus one regression test |
| 3 | One-module fix with a new test; no schema or contract change |
| 5 | Multi-file fix, or a small design decision, or a concurrency/two-session test |
| 8 | Cross-cutting change, migration, or contract change across services |
| 13 | Epic-sized; the issue must say it should be split before assignment |

## Noise floor (do not publish)

Style-only nits a linter already enforces; findings inside dependency dirs,
build output, generated code, or vendored files; speculative "could be a
problem if" claims with no concrete trigger; anything already fixed on the
audited branch; anything an open issue already states at the same location
(enrich instead, Step 4). P3 findings are **batched**: one issue per area
listing every item with file:line.

---

## Step 0: Preflight and project profile

1. `git fetch --prune origin` and resolve the audited ref: `--base`, else the
   overlay's base branch, else the default branch. Record the SHA; every issue
   body cites it. Audit `origin/<base>`, never the local worktree.
2. Read the overlay `.claude/codebase-audit.overlay.md` if present. Read the
   project's own operating manual if present (`AGENTS.md`, `CLAUDE.md`,
   `CONTRIBUTING.md`, `docs/adr/`) for principles, canary tests, and hazards
   that the overlay does not already state.
3. **Build the project profile** and write it to the report (§9). Detect from
   the tree, do not assume:
   - Ecosystems: `pyproject.toml`/`uv.lock`/`requirements*.txt` (Python),
     `package.json` + lockfile (Node; note the package manager from the
     lockfile and any `packageManager` field), `go.mod`, `Cargo.toml`,
     `pom.xml`/`build.gradle*`, `*.csproj`, `Gemfile`, `composer.json`.
   - Layout: monorepo packages, service dirs, frontend dirs, worker/job dirs,
     migration dirs, IaC/infra dirs, CI system (`.github/workflows`,
     `.gitlab-ci.yml`, `Jenkinsfile`, …), Dockerfiles and compose files.
   - Tests: test roots per ecosystem, e2e frameworks, coverage config and
     thresholds, quarantine/skip lists.
   - Size: LOC per top-level area (exclude dependency/build dirs).
   - GitHub: existing labels, issue types, issue templates, CODEOWNERS.
4. Load every **open** issue (number, title, labels, assignees) and every
   open PR (number, title, head branch) into scratch files. Use the GitHub MCP
   tools when `gh` is unavailable.
5. Install dependencies in the background so Step 1 can run, honouring the
   overlay hazards (package-manager pinning, env vars, forbidden commands).
   After installing, confirm `git status --short` shows no lockfile change.

## Step 1: Automated scanners (cheap signal, run in parallel)

Run what the profile supports; skip and note the rest. Scanner output is
**input to review, not findings**: a hit becomes a finding only after Step 3.

| Ecosystem | Lint / types | Vulnerabilities |
|---|---|---|
| Python | `ruff check --output-format=json` (or the repo's linter), `mypy` if configured | `pip-audit -r <exported requirements> --desc --format=json` |
| Node | `tsc --noEmit`, `eslint . -f json` — call binaries from `node_modules/.bin` | `<pm> audit --json` using the pinned package-manager major |
| Go | `go vet ./...`, `staticcheck` if present | `govulncheck ./...` |
| Rust | `cargo clippy --message-format=json` | `cargo audit --json` |
| JVM | the build's lint task | `dependency-check` or `gradle dependencyCheckAnalyze` if configured |
| .NET | `dotnet build -warnaserror` | `dotnet list package --vulnerable` |
| Any | secrets: `git grep -nE "(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY|ghp_[A-Za-z0-9]{30,}|service_role)" -- ':!*.lock'` then `git log -p --all -S` on any hit | blocking-call smell in async code: `grep -rnE "asyncio\.run\(|time\.sleep\(|requests\.|open\(|subprocess\."` over async service dirs |
| Any | coverage: the repo's coverage command when its services (DB, cache) are available; otherwise the last CI coverage artifact | |

## Step 2: Parallel deep review (fan out subagents)

Derive **8–12 cells** from the profile so that each cell covers one coherent
concern over at most ~15k LOC. Use the template below; drop cells whose file
set is empty, split cells that are too large, and apply overlay cell hints.
Every subagent receives: the audited SHA, its file set, the dimension
checklist, the severity and SP rubrics, the noise floor, the open-issue and
open-PR lists, the overlay principles, and the output contract. Each writes
its findings to `<scratch>/findings/<cell>.md` and returns a three-line
summary only.

| Cell template | Files | Dimension checklist |
|---|---|---|
| `api-security` | HTTP routes, auth, middleware, permission helpers | AuthN/AuthZ on every route; object-level authorization (ownership vs role); every mutating route leaves an audit trail if the project requires one; session/token handling; rate limiting; CORS; upload validation (magic bytes, size, path); SSRF; secrets and config exposure; error responses leaking internals; PII in logs vs any scrubber; mass assignment |
| `domain-correctness-<n>` (one per bounded context) | service/domain modules for one context | State-machine completeness; TOCTOU and stale-object reuse; transaction boundaries and rollback reuse; idempotency; enum/status drift between layers; date/time handling; silently swallowed exceptions |
| `integrations` | LLM/AI, email, storage, payment, third-party clients | Provenance/audit fields on AI outputs if required; retry/timeout semantics; prompt-injection surface (untrusted text interpolated into prompts; model output driving decisions); output parsing strictness; residency/egress of sensitive data; template injection; temp-file cleanup; cost caps |
| `data-and-jobs` | models, migrations, DB helpers, background workers/queues | Migration-vs-model drift; missing indexes for known query patterns; nullable/default mismatches; append-only guarantees; cascade deletes; job idempotency, timeouts, retries, graceful shutdown; engine/pool lifecycle in workers; whether worker settings actually reach the runtime |
| `performance` | routes and services | N+1 and lazy loads; unbounded lists; blocking calls in async paths (hashing, sync HTTP, file I/O, CPU work); redundant queries; large objects in memory; per-request client construction; locks or transactions held across slow calls |
| `frontend-security-correctness` | app routes, API client, auth, validation, state | Route protection and role gating; token storage and refresh; error handling; open redirects; unsafe HTML; client vs server schema drift; query invalidation races; effects that reset state on identity changes; error boundaries |
| `frontend-components` | UI components | Hard-coded strings bypassing i18n; physical CSS properties breaking RTL if bilingual; status by color alone; missing loading/empty/error/stale states; a11y (labels, focus traps, keyboard); hooks misuse; locale-aware formatting |
| `frontend-performance` | frontend tree | Client/server component boundary; unbounded lists without virtualization; refetch storms; heavy client imports; polling cost; render waterfalls |
| `quality-ci-infra-docs` | tests, CI config, Dockerfiles, compose, IaC, scripts, README, ADRs | Canary tests present and unweakened; skipped/quarantined tests and why; coverage gate wiring (can it pass vacuously?); mocked-DB integration tests where the project forbids them; CI steps that pass vacuously; unpinned actions; concurrency groups cancelling post-merge runs; Docker env propagation, healthchecks, signals, `.dockerignore`; README steps that no longer work; missing ADRs for dependencies if the project requires them. Treat timeout-cancelled CI jobs as cancelled, not failed |
| `simplify-<area>` (one per area) | whole area | Duplicate helpers, dead code, over-abstraction, inconsistent error handling, deprecated API usage; linter output as input. Report as one batched P3 list; promote only when a duplication hides a behavioral inconsistency |

### Output contract for every finding

```markdown
### <declarative defect statement, ≤ 90 chars>
- **Cell**: api-security
- **Dimension**: security | correctness | performance | simplification | quality
- **Severity**: P0 | P1 | P2 | P3
- **Area**: <area from the profile>
- **Location**: path/file.py:123 (and every other file:line involved)
- **Evidence**: what the code does (quoted), the concrete trigger
- **Impact**: who is affected and how
- **Suggested fix**: one paragraph
- **Estimate**: sp:N — one-sentence rationale against the rubric
- **Related open issues**: DUPLICATE of #n | related #n (why distinct) | none
- **Principle**: <overlay principle> | none
- **Verified**: not yet
```

P3 simplification items go in one `## P3 batch` table per cell:
`| # | Location | Issue | Fix | Effort(1-3) |`.

## Step 3: Adversarial verification (mandatory before publishing)

For every P0–P2 finding, spawn a fresh verifier subagent that has **not**
seen the reviewer's reasoning. It receives only the title, locations, and a
one-line assertion, and must try to **refute** it from the code, tests,
installed packages, and specs, answering `CONFIRMED`, `PLAUSIBLE`, or
`REJECTED` with its own decisive evidence, its own severity and SP, and a
reproduction or failing check. Batch related claims (2–4 per verifier) when
they share a file set.

- `REJECTED` findings are dropped and listed in the report (§8) with the reason.
- `PLAUSIBLE` findings publish one severity lower with the verdict stated.
- A verifier may raise or lower severity with evidence; use the verifier's
  values and record both.
- P3 batches are spot-checked (every fifth row, minimum three); a batch with
  two rejections is re-reviewed in full.

## Step 4: Deduplicate against open issues (policy: keep the older issue)

For each verified finding:

1. Search open and closed issues by keyword and by file path; scan the
   preloaded title list for semantic matches; check the open-PR list for a
   fix already in flight.
2. Classify:
   - **Same defect, same location** → duplicate. Do **not** file. Unless
     `--no-enrich`, post one comment on the existing issue (audit date, SHA,
     new evidence, the audit's severity/SP) and add `audit`, `severity:Pn`,
     `area:*`, `sp:N` labels only where missing. Never change title, body,
     assignee, or state.
   - **Same theme, different location or root cause** → file it and link the
     related issue.
   - **Existing issue is a superset** (story/epic) → file as a sub-issue.
   - **Open PR already fixes it** → file it anyway (the PR may not merge) and
     link the PR in Related.
3. Existing-vs-existing overlaps among open issues are **reported, not
   acted on** (§7), each with a keep/close recommendation.

## Step 5: Draft and publish (publishing skipped under `--dry-run`)

**Draft** one JSON payload per finding to `<scratch>/issues/<slug>.json`
(`slug, title, type, labels, severity, sp, area, body`) and validate all
payloads with a script before publishing (title ≤ 90 chars, type valid,
required labels present, body starts with `## Summary`). Merge findings
that share a root cause into one issue.

- **Title**: a declarative defect statement, no prefix, no trailing period,
  matching the repo's recent issue style.
- **Type**: `Bug` for security/correctness/performance defects; `Task` for
  simplification, quality, docs (only if the repo has issue types).
- **Labels**: `audit`, `severity:Pn`, `area:<area>`, `sp:N`, plus a
  dimension label (`security` | `bug` | `performance` | `tech-debt` |
  `documentation` | `simplification`), plus any overlay mapping labels.
  GitHub creates missing labels on issue creation for users with push access.
- **Assignee**: none. Triage assigns.
- **Body** sections, in order: `## Summary` · `## Current Behavior` ·
  `## Expected Behavior` · `## Root Cause / Evidence` (file:line, quoted code,
  reproduction) · `## Impact` · `## Scope` · `## Non-Goals` ·
  `## Acceptance Criteria` (checkboxes; last item is always a regression
  test) · `## Verification` · `## Related / Duplicate Check` · `## Estimate`
  (SP and severity rationale, verifier verdict) · `## Audit provenance`
  (date, SHA, cell, report path).
- **P3 batches**: one issue per area, `Simplification batch (<area>): <n>
  low-risk cleanups from the <date> audit`, sp 3 for ≤ 20 rows, 5 for
  21–40, 8 above; the table plus one checkbox per row.

**Publish** severity-first (P1 before P2 before P3) so the most important
findings get the lowest numbers. Create one issue alone first to confirm
labels and type are accepted, then the rest in a few sequential lanes with
a few seconds between creates (GitHub secondary rate limits on content
creation). Before each create, search open issues for the exact title and
skip if it exists (resume-safe). Record `slug → issue #` as you go. After
publishing, run an independent verification that lists open issues labelled
`audit`, matches every payload title, and reports missing issues, duplicate
titles, and label gaps.

## Step 6: Report

Write the report to the overlay's report path, else
`docs/audits/codebase-audit-YYYY-MM-DD.md` (UTC date; overwrite if it
exists). Commit and push the report skeleton **before** publishing so a
following session can resume from it, then fill it in.

0. **Run state and handoff** — a step table with status and where the state
   lives; resume instructions (an issue labelled `audit` whose body cites
   the same location is already filed; never double-file).
1. **Executive summary** — counts by severity and area, issues created,
   enriched, rejected, SP total, highest-leverage fixes.
2. **P1 findings** — table: issue link, area, dimension, SP, title, summary.
3. **P2 findings** — same.
4. **P3 issues and batches** — table.
5. **Dependency advisories** — per ecosystem with fix versions.
6. **Scanner results** — commands and raw counts.
7. **Existing-issue overlaps** — keep/close recommendations, no action taken.
8. **Rejected findings** — title, cell, verifier reason.
9. **Coverage of this run** — the project profile, cells run, exclusions,
   `--since`/`--scope` if any.
10. **Methodology** — agents, verification policy, dedup policy, hazards.

Then print the console summary:

```
Codebase Audit Complete (YYYY-MM-DD)
------------------------------------------------
Audited ref:              origin/<base> @ <sha>
Cells run:                N
Findings raw / verified:  R / V   (rejected X)
By severity:              P0 a · P1 b · P2 c · P3 d (batched into e issues)
Issues created:           N   (Bug n · Task m)
Existing issues enriched: N
Existing overlaps flagged: N (no action taken)
Advisories:               <ecosystem> n · <ecosystem> m
Report:                   <path>
Mode:                     full | dry-run | scope=<s> | since=<ref>
```

## Operating Constraints

1. **No fabrication.** A finding without a file:line and a concrete trigger
   is not a finding. Never invent CVE IDs; copy them from scanner output.
2. **The audited branch on `origin` is the only ground truth** for code.
3. **Read-only on the repo** except the report file and, when asked, an
   overlay. The audit never fixes code; fixes are separate PRs.
4. **Never weaken a canary** or suggest skipping one as a fix.
5. **Graceful degradation.** If a scanner cannot run, say so in §6 and
   continue with review-only evidence.
6. **Idempotent publishing.** A second run on the same day must not
   double-file (title search before create; `audit` label + location in body).
7. **Existing issues are not yours.** Enrichment is additive. Closing or
   retitling an existing issue is the maintainer's decision.
8. **Overlay principles are explicit.** A finding touching one names it in
   the body and gets at least P1.
9. **Performance.** Scanners and cells in parallel; verifiers in parallel;
   publishing in a few paced lanes.
10. **Rate-limit resilience.** Long fan-outs can be cut off by session
    limits; write intermediate state to files (findings, verdicts, payloads,
    report skeleton) so any step can be re-run without repeating the others.
