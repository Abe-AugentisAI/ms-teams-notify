---
description: Full end-to-end codebase audit (security, correctness, performance, simplification, test/CI/infra/docs drift) that profiles the repo, fans out area-by-angle finders, adversarially verifies every finding with lens-diverse verifiers and an optional cross-model Codex pass, sweeps for gaps, deduplicates against open GitHub issues by fingerprint, and publishes each confirmed finding as a story-pointed issue ready for triage
argument-hint: "[--scope <path|area>] [--dimension security|correctness|performance|simplification|quality|all] [--min-severity P0|P1|P2|P3] [--dry-run] [--no-enrich] [--no-codex] [--since <git-ref>] [--base <branch>]"
---

<!--
  Project-agnostic. Everything repository-specific lives in an optional overlay
  file at `.claude/codebase-audit.overlay.md` (principles with severity floors,
  label vocabulary, report path, cell hints, hazards, known-open issues). The
  command works with no overlay at all.

  Install for one repo: keep this file at `.claude/commands/codebase-audit.md`.
  Install for every repo on a machine: copy it to `~/.claude/commands/codebase-audit.md`
  and add an overlay per repo. Progress is observable from any surface: the
  report file lands in the repo, issues carry the `audit` label and a body
  fingerprint, and Workflow runs are resumable by run id.

  Lineage: the finder angles, the finding contract (required failure_scenario),
  the "pass every candidate through" rule, the CONFIRMED/PLAUSIBLE/REFUTED
  definitions, and the gap sweep are lifted from the Claude Code bundled
  `/code-review` skill (v2.1.260). The security exclusion list is from the
  bundled `/security-review` skill. The cross-model pass follows this repo's
  `/codex-review` command.
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
triage and assign.

The stance is **recall at find time, precision at the publish gate**. Finders
surface every candidate with a nameable failure scenario; verifiers refute
from the code; only what survives is published. A finding that cannot be tied
to a file and line at the audited SHA, given a concrete failure scenario, and
shown to be reachable is not published. A false positive costs the team more
than a miss: it burns triage time and teaches people to ignore the label.

It reads code, tests, config, CI, and infra. It does not grade sprint or
roadmap progress; use the project's planning tooling for that.

## Arguments

| Flag | Effect |
|------|--------|
| *(empty)* | Full audit: all areas, all angles, publish P0–P3 |
| `--scope <s>` | Restrict to one area from the profile (`backend`, `frontend`, `infra`, a package name) or a path prefix. Default all |
| `--dimension <d>` | Restrict to one dimension; maps to the angle set in Step 2. Default `all` |
| `--min-severity <P>` | Only publish findings at or above this severity. Default `P3` |
| `--dry-run` | Run every step, write the report, create **no** issues and post **no** comments; print the exact payloads that would be sent |
| `--no-enrich` | Never comment on or relabel an existing issue; only avoid filing duplicates |
| `--no-codex` | Skip the cross-model Codex refute pass (Step 3d). Use when `codex` is absent or cost/token limits apply |
| `--since <ref>` | Incremental: deep review only the diff `<ref>...origin/<base>` using the diff angles (Step 2, mode B). Scanners still run on the whole tree |
| `--base <branch>` | Branch to audit. Default: the overlay's base branch, else the PR base named in `CLAUDE.md`, else the repo default branch |

## Severity rubric

| Severity | Definition | Examples |
|---|---|---|
| P0 | Exploitable in the deployed product, or silent data loss/corruption on a main path | Auth bypass, IDOR, SQL/command injection, secret in repo, mutable audit log, unauthorized data egress |
| P1 | Security weakness needing preconditions, authorization gap, missing audit trail on a mutating path, a user-facing defect in a core flow, or any violation of an overlay principle | Missing rate limit on login, stale-state authorization, state machine allows a wrong transition, hard-coded credential seeded by a migration |
| P2 | Robustness, performance, or maintainability defect with a plausible production trigger | N+1 query, unbounded list endpoint, blocking I/O in an async path, job timeout not enforced, flaky or quarantined test masking coverage, Docker/CI fragility |
| P3 | Simplification, dead code, duplicated logic, docs drift, minor a11y or i18n inconsistency | Duplicate helper, unused module, README steps that no longer work |

Security P0/P1 additionally require a **concrete attack path**: an untrusted
entry point, the data it controls, and the sink it reaches. "Best practice
not followed" without that path is P2 at most.

Overlay principles raise the floor: any finding touching one publishes at
**≥ P1** and names the principle in the body. Order of operations: verifier
verdict first (Step 3), then the floor. Both are named in the body.

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
(enrich instead, Step 4); **anything in code that no live entry point reaches
at the audited SHA** (a retired route, an unexported helper, a module nothing
imports): that is one row in the area's P3 dead-code batch, never a Bug.
Code reachable only behind a config flag is not dead: it is PLAUSIBLE with the
flag named as the precondition. An overlay cell hint that says so for a
specific path overrides this paragraph.
P3 findings are **batched**: one issue per area listing every item with
file:line.

---

## Step 0: Preflight and project profile

1. `git fetch --prune origin` and resolve the audited ref: `--base`, else the
   overlay's base branch, else the PR base branch named in `CLAUDE.md`, else
   the default branch. Record the SHA; every issue body cites it.
2. **Check out a scratch worktree at that SHA** and do every read, scan, and
   reproduction there: `git worktree add <scratch>/audit-<sha> origin/<base>`.
   The local checkout is never the ground truth. Remove the worktree at the end.
3. Read the overlay `.claude/codebase-audit.overlay.md` if present. Read the
   project's own operating manual if present (`AGENTS.md`, `CLAUDE.md`,
   `CONTRIBUTING.md`, `docs/adr/`) for principles, canary tests, and hazards
   that the overlay does not already state. These files are also the source
   for the `conventions` angle (Step 2).
4. **Build the project profile** and write it to the report (§9). Detect from
   the tree, do not assume:
   - Ecosystems: `pyproject.toml`/`uv.lock`/`requirements*.txt` (Python),
     `package.json` + lockfile (Node; note the package manager from the
     lockfile and any `packageManager` field), `go.mod`, `Cargo.toml`,
     `pom.xml`/`build.gradle*`, `*.csproj`, `Gemfile`, `composer.json`.
   - Layout: monorepo packages, service dirs, frontend dirs, worker/job dirs,
     migration dirs, IaC/infra dirs, CI system, Dockerfiles and compose files.
   - Entry points: HTTP routers, CLI mains, job/worker registrations, cron
     definitions, frontend routes. The reachability lens (Step 3) uses this list.
   - Tests: test roots per ecosystem, e2e frameworks, coverage config and
     thresholds, quarantine/skip lists.
   - Size: LOC per top-level area (exclude dependency/build dirs).
   - GitHub: existing labels, issue types, issue templates, CODEOWNERS.
5. Load into scratch JSON: every **open** issue (number, title, labels,
   assignees), every open PR (number, title, head branch), and every issue in
   any state whose body contains `codebase-audit-fingerprint:` (number, state,
   fingerprint). Use the GitHub MCP tools when `gh` is unavailable.
6. **Ensure labels exist.** Diff the labels this run will apply (Step 5)
   against `gh label list`; `gh label create` any that are missing.
   Create them first rather than relying on any auto-creation behaviour: a
   label rejected at create time loses the issue mid-run.
7. Install dependencies **into the worktree** in the background so Step 1 can
   run, honouring the overlay hazards (package-manager pinning, env vars,
   forbidden commands). Worktrees lack gitignored files (`.env`,
   `node_modules`); copy or install what the tests need. After installing,
   confirm `git -C <worktree> status --short` shows no lockfile change.
8. Print the run tag line, filled in from the profile, and repeat it in the
   report and console summary, for example:

   ```
   full → 9 areas × 7 angles → dedup → verify (P0/P1 3-lens, P2 1-vote, P3 spot) → sweep → codex → publish
   ```

## Step 1: Automated scanners (cheap signal, run in parallel)

Run what the profile supports; skip and note the rest. Scanner output is
**input to finders, not findings**: a hit becomes a finding only after Step 3.

| Ecosystem | Lint / types | Vulnerabilities |
|---|---|---|
| Python | `ruff check --output-format=json` (or the repo's linter), `mypy` if configured | `pip-audit -r <exported requirements> --desc --format=json` |
| Node | `tsc --noEmit`, `eslint . -f json` from `node_modules/.bin` | `<pm> audit --json` using the pinned package-manager major |
| Go | `go vet ./...`, `staticcheck` if present | `govulncheck ./...` |
| Rust | `cargo clippy --message-format=json` | `cargo audit --json` |
| JVM | the build's lint task | `dependency-check` or `gradle dependencyCheckAnalyze` if configured |
| .NET | `dotnet build -warnaserror` | `dotnet list package --vulnerable` |
| Any | secrets: `git grep -nE "(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY|ghp_[A-Za-z0-9]{30,}|service_role)" -- ':!*.lock'` then `git log -p --all -S` on any hit | blocking-call smell in async code: `grep -rnE "asyncio\.run\(|time\.sleep\(|requests\.|open\(|subprocess\."` over async service dirs |
| Any | coverage: the repo's coverage command when its services (DB, cache) are available; otherwise the last CI coverage artifact | |

## Step 2: Find (recall mode)

### Mode A: full audit, area × angle

Derive **areas** from the profile so that each covers one coherent file set
of at most ~15k LOC: `api` (routes, auth, middleware), one `domain-<context>`
per bounded context, `integrations` (LLM, email, storage, payment, third-party
clients), `data-and-jobs` (models, migrations, workers, queues),
`frontend-app` (routes, API client, auth, state), `frontend-components`,
`quality-ci-infra-docs` (tests, CI, Dockerfiles, IaC, scripts, README, ADRs).
Drop empty areas, split large ones, apply overlay cell hints.

Run **one finder per area × angle**. A finder holds one file set and one
angle, nothing else. This is deliberate: an agent given ten concerns over 15k
lines goes shallow on all of them. Angles (the `--dimension` flag selects a
subset):

| Angle | Dimension | Brief for the finder |
|---|---|---|
| `correctness-scan` | correctness | Read every function in the file set. For every line ask: what input, state, timing, or platform makes this line wrong? Look for inverted/wrong conditions, off-by-one, null/undefined deref, missing `await`, falsy-zero checks, wrong-variable copy-paste, error swallowed in catch, unescaped regex metachars, state-machine transitions that skip a guard, silently swallowed exceptions, date/time handling |
| `cross-file-tracer` | correctness | For each public function or route in the file set, find its callers and callees (Grep for the symbol) and check contracts across the boundary: a precondition the caller does not meet, a changed return shape, an exception no caller handles, enum/status drift between layers, client-vs-server schema drift, a timing/ordering dependency |
| `language-pitfall` | correctness | Scan for the classic pitfalls of the file set's language/framework: JS falsy-zero, `==` coercion, closure-captured loop var; Python mutable default args, late-binding closures, dataclass default evaluated once; Go nil-map write, range-var capture; SQL injection; timezone/DST drift; float equality. For any type that wraps another (cache, proxy, decorator, adapter), check that every method routes to the wrapped instance and not back through a registry/session/global, and that the wrapper forwards every method callers use |
| `security-attack-path` | security | Start from each entry point in the profile. Trace untrusted input to a sink. Check AuthN/AuthZ on every route; object-level authorization (ownership vs role); audit trail on mutating routes if the project requires one; session/token handling; rate limiting; CORS; upload validation; SSRF; secrets and config exposure; error responses leaking internals; PII in logs; mass assignment; prompt-injection surface (untrusted text interpolated into prompts, model output driving decisions); template injection. Apply the exclusion list below |
| `data-and-concurrency` | correctness | TOCTOU and stale-object reuse; transaction boundaries and rollback; idempotency of handlers and jobs; migration-vs-model drift; nullable/default mismatches; missing indexes for known query patterns; append-only guarantees; cascade deletes; job timeouts, retries, graceful shutdown; engine/pool lifecycle in workers; whether worker settings actually reach the runtime; locks or transactions held across slow calls |
| `performance` | performance | N+1 and lazy loads; unbounded lists; blocking calls in async paths (hashing, sync HTTP, file I/O, CPU work); redundant computation or repeated I/O; independent operations run sequentially; per-request client construction; large objects in memory; long-lived objects built from closures that keep the enclosing scope alive; frontend: client/server component boundary, unvirtualized lists, refetch storms, heavy client imports, render waterfalls |
| `conventions` | quality | Find the rules that govern the file set: the repo-root `CLAUDE.md`, any `CLAUDE.md`/`CLAUDE.local.md` in an ancestor directory of a file in the set, `AGENTS.md`, ADRs, and the overlay principles. Read each one that exists, then check the code for clear violations. Only flag a violation when you can quote the exact rule and the exact line that breaks it; no style preferences, no "spirit of the doc" inferences. Name the file and quote the rule. For test and CI files also check: canary tests present and unweakened; skipped/quarantined tests and why; coverage gate wiring (can it pass vacuously?); CI steps that pass vacuously; unpinned actions; concurrency groups cancelling post-merge runs; Docker env propagation, healthchecks, signals; README steps that no longer work. Treat timeout-cancelled CI jobs as cancelled, not failed. If no rule applies, return nothing |
| `cleanup` | simplification | Reuse: code that re-implements something the codebase already has (Grep shared/utility modules; name the existing helper). Simplification: redundant or derivable state, copy-paste with slight variation, deep nesting, dead code. Altitude: special cases layered on shared infrastructure where a simpler change to the underlying mechanism would do; name that change. Frontend: hard-coded strings bypassing i18n, physical CSS properties breaking RTL if bilingual, status by colour alone, missing loading/empty/error states, a11y (labels, focus, keyboard). Output goes to the area's P3 batch; promote to P2 only when a duplication hides a behavioural inconsistency |

**Security exclusion list** (paste into the `security-attack-path` brief):
denial-of-service, rate-limit absence on non-auth routes, and resource
leaks are P2 robustness at most, not security; tabnabbing, XS-Leaks,
prototype pollution, and open redirects only at very high confidence; React
and Angular components are not XSS unless they use `dangerouslySetInnerHTML`,
`bypassSecurityTrust*`, or similar; a missing permission check in client-side
code is not a vulnerability (the server owns authorization; flag the server
route instead); logging non-PII data is not a vulnerability; command
injection in shell scripts and vulnerabilities in CI workflow files or
notebooks only with a concrete path for untrusted input; a medium-impact
finding only when it is obvious and concrete.

### Mode B: incremental (`--since <ref>`)

Replace the grid with the five diff angles over `git diff <ref>...origin/<base>`,
one finder each, plus `conventions` and `cleanup` restricted to touched files.
Read the enclosing function for each hunk; bugs in unchanged lines of a touched
function are in scope.

- **A, line-by-line diff scan**: as `correctness-scan`, per hunk.
- **B, removed-behaviour auditor**: for every line the diff deletes or
  replaces, name the invariant it enforced, then search the new code for where
  it is re-established. A removed guard, a dropped error path, a narrowed
  validation, or a deleted test covering a real case is a candidate.
- **C, cross-file tracer**: as above, for changed functions only.
- **D, language-pitfall specialist**: as above, for introduced code.
- **E, wrapper/proxy correctness**: as above, when the diff adds or changes a wrapper.

### Finder brief (every finder receives this)

The audited SHA and worktree path; its file set; its angle text; the
severity and SP rubrics; the noise floor; the scanner hits for its files; the
overlay principles; the open-issue and open-PR lists; the output schema.

Rules that bind every finder:

- **Every candidate needs a failure scenario**: concrete inputs or state →
  wrong output, crash, or exploit. Cleanup candidates state the concrete cost
  instead (what is duplicated, wasted, harder to maintain, or which rule is
  broken).
- **Pass every candidate with a nameable failure scenario through.** Finders
  that silently drop half-believed candidates bypass the verify step and are
  the dominant cause of misses. Verification is Step 3's job, not yours.
- **Cap: 10 candidates**, ranked most-severe first. If more qualify, keep the
  10 most severe and say how many were cut. If fewer, return fewer; **do not
  pad**.
- Quote the lines you rely on. A candidate without a quote at the audited
  SHA is a hypothesis; return it as PLAUSIBLE-candidate with `evidence` empty
  so the verifier knows.
- Do not spawn subagents. Do not modify the worktree.

### Output schema (every finder, every sweep)

```json
{
  "findings": [
    {
      "title": "declarative defect statement, ≤ 90 chars",
      "short_summary": "the claim compressed to ≤ 60 chars, no rationale",
      "file": "path/from/repo/root.py",
      "line": 123,
      "other_locations": ["path/other.py:45"],
      "angle": "correctness-scan",
      "dimension": "security | correctness | performance | simplification | quality",
      "severity": "P0 | P1 | P2 | P3",
      "area": "api",
      "failure_scenario": "concrete inputs/state → wrong output, crash, or exploit",
      "evidence": "quoted lines from the file at the audited SHA",
      "impact": "who is affected and how",
      "suggested_fix": "one paragraph",
      "sp": 3,
      "sp_rationale": "one sentence against the rubric",
      "principle": "overlay principle name or null",
      "related_issues": [{"number": 123, "relation": "duplicate | related | superset | fix-in-flight"}]
    }
  ],
  "cut": 0
}
```

Each finder's JSON is written to `<scratch>/findings/<area>-<angle>.json`.

### Dedup before verification

Pool all candidates. Two candidates are the same when they point at the same
file and mechanism (same line, or same function and same failure mode). Keep
the one with the most concrete failure scenario and merge the other's
locations into `other_locations`. Record the count. Fingerprint every
survivor: `sha1("<file>|<function or line>|<mechanism slug>")`, first 12 hex.
**A fingerprint is always opaque hex, never a readable string.** GitHub issue
search tokenises words, so a readable marker such as `batch-api-2026-09-04`
matches unrelated issues and the dedup step silently skips a real finding.
Batch issues get a hashed fingerprint too.

## Step 3: Verify (precision mode, mandatory before publishing)

### 3a. Verifier contract

A verifier receives **only**: the title, file:line and other locations, the
failure scenario, the quoted evidence, the audited SHA and worktree path, the
severity and SP rubrics, and the noise floor. Never the finder's reasoning,
never the other candidates. **One candidate per verifier**; batching
correlates verdicts. The verifier's job is to **refute** from the code,
tests, installed packages, and specs, and to return exactly one verdict:

- **CONFIRMED**: can name the inputs/state that trigger it and the wrong
  output or crash. Quote the line.
- **PLAUSIBLE**: mechanism is real, trigger is uncertain (timing, env,
  config). State what would confirm it.
- **REFUTED**: factually wrong (the code does not say that), provably
  impossible (type, constant, or invariant; show it), already guarded
  elsewhere (cite the guard), or pure style with no observable effect. Quote
  the line that proves it.

**PLAUSIBLE by default.** Do not refute a candidate for being "speculative" or
"depends on runtime state" when the state is realistic: concurrency races,
nil/undefined on a rare-but-reachable path (error handler, cold cache,
missing optional field), falsy-zero treated as missing, off-by-one on a
boundary the code does not exclude, retry storms and partial failures, a
regex or allowlist that lost an anchor. These are PLAUSIBLE. REFUTED is only
for what is constructible from the code.

Every verifier also returns its own severity and SP with a one-line
rationale, and a `proof` field: the quoted line, the guard, the invariant, or
the reproduction output.

### 3b. Votes by severity

- **P0 and P1**: three verifiers with distinct lenses, run concurrently.
  Majority rules; a tie between CONFIRMED and PLAUSIBLE is PLAUSIBLE.
  1. **refute-from-code**: the contract above.
  2. **reachability and exploitability**: is the code on a live path at the
     audited SHA (a registered route, an imported module, a scheduled job, a
     rendered component reachable from a live route)? Grep for importers and
     registrations; consult the entry-point list from the profile. For
     security, does an attack path exist from an untrusted entry point to the
     sink, and what does the exclusion list say? Unreachable code returns
     `REFUTED` with `reason: unreachable` and the finding becomes one row in
     the area's P3 dead-code batch. A reachability refutation forces P3 even when
     the other two lenses confirm, and the issue body must name the reachability
     verdict rather than presenting the finding as a live defect.
  3. **reproduce**: write a failing test or a runnable check in the scratch
     worktree (never committed, never pushed), run it, and return the output.
     If a reproduction is impossible without live services, say what would be
     needed and vote PLAUSIBLE at most.
- **P2**: one verifier with the refute-from-code contract plus the
  reachability question folded in.
- **P3 batches**: spot-check every fifth row **and never fewer than three rows**;
  every-fifth alone checks only two rows of eight. A batch with two REFUTED rows
  is re-reviewed in full. The batch issue states plainly that its rows were
  sampled, not individually verified.

### 3c. Verdict outcomes

- `REFUTED` findings are dropped and listed in the report (§8) with the proof.
- **A finding whose verifiers did not run is `UNVERIFIED`, and `UNVERIFIED` is
  never a pass.** When every verifier for a candidate dies (rate limit, credit
  exhaustion, API error), the finding is withheld from publishing and listed in
  the report (§8b) with the lenses that failed, so the next run can resume and
  verify it. Silence from a verifier is not agreement.
- **A partial panel carries a weaker verdict.** When fewer than two of a P0/P1
  finding's three lenses returned, the strongest available verdict is
  PLAUSIBLE, and the body names the lenses that did not run.
- `PLAUSIBLE` findings publish **one severity lower** with the verdict stated.
- The verifier's severity and SP replace the finder's; record both.
- Then apply the overlay principle floor (≥ P1) and name it. A PLAUSIBLE
  P1-floored finding therefore publishes at P1 with the verdict stated.
- Verdicts are written to `<scratch>/verdicts/<fingerprint>.json`.

### 3d. Sweep for gaps (one round)

Run **one fresh finder per area** that holds the verified list for that area.
It re-reads the file set looking **only** for defects not already listed; it
does not re-derive or re-confirm anything. Focus on what a first pass tends
to miss: moved or extracted code that dropped a guard or anchor; second-tier
footguns (dataclass default evaluated once, `hash()` non-determinism,
lock-scope shrink, predicate methods with side effects); setup/teardown
asymmetry in tests; config defaults flipped; a state written but never
compared; two timeouts guarding one operation with equal or inverted
ordering. Up to 8 additional candidates, each naming a defect not on the
list. If nothing new, return an empty sweep; do not pad. Sweep output goes
through dedup and 3a–3c.

### 3e. Cross-model refute pass (default on; `--no-codex` skips)

An independent model catches what the author's model cannot. For every
finding still at P0 or P1 after 3c, ask Codex to refute it, read-only:

```bash
codex login status || { note "codex not logged in; pass skipped"; }
printf '%s' "<title, file:line, failure scenario, evidence>" | \
  codex exec -c sandbox_mode="read-only" -c approval_policy="on-request" \
  "Try to refute this finding from the repository at $WORKTREE. Answer CONFIRMED, PLAUSIBLE, or REFUTED with the quoted line that proves it."
```

A Codex `REFUTED` with a quoted proof demotes the finding to PLAUSIBLE and the
proof is recorded in the body; Codex never promotes. Skip the pass, and say so
in the report, when `codex` is absent, not logged in, or the run is under a
cost or token limit. Codex reviews the worktree; treat its output as claims to
record, not as a current-state audit.

## Step 4: Deduplicate against open issues (policy: keep the older issue)

For each verified finding, in this order:

1. **Fingerprint match** against the preloaded audit-issue list. Same
   fingerprint in an open issue → duplicate. Same fingerprint in a closed
   issue → file it and link the closed issue as "previously closed"; the
   maintainer decides whether it regressed.
2. Search open and closed issues by file path and by keyword; scan the
   preloaded title list for semantic matches; check the open-PR list for a
   fix already in flight.
3. Classify:
   - **Same defect, same location** → duplicate. Do **not** file. Unless
     `--no-enrich`, post one comment on the existing issue (audit date, SHA,
     new evidence, the audit's severity/SP, the fingerprint) and add `audit`,
     `priority:Pn`, `area:*`, `sp:N` labels only where missing. Never change
     title, body, assignee, or state.
   - **Same theme, different location or root cause** → file it and link the
     related issue.
   - **Existing issue is a superset** (story/epic) → file as a sub-issue.
   - **Open PR already fixes it** → file it anyway (the PR may not merge) and
     link the PR in Related.
4. Existing-vs-existing overlaps among open issues are **reported, not
   acted on** (§7), each with a keep/close recommendation.

## Step 5: Draft and publish (publishing skipped under `--dry-run`)

**Draft** one JSON payload per finding to `<scratch>/issues/<fingerprint>.json`
(`fingerprint, title, type, labels, severity, sp, area, body`) and validate
every payload with a script before publishing: title ≤ 100 chars with the
prefix, type valid, required labels present and existing, body starts with
`## Summary`, body contains the fingerprint comment and a `## Verification`
section with a verdict. Merge findings that share a root cause into one issue.

- **Title**: `AUDIT-YYYY-MM-DD-NN: <declarative defect statement>`. `NN` is
  assigned severity-first at publish time (01 is the most severe), zero-padded
  to two digits. No trailing period. P3 batches:
  `AUDIT-YYYY-MM-DD-NN: Simplification batch (<area>): <n> low-risk cleanups`.
- **Type**: `Bug` for security/correctness/performance defects; `Task` for
  simplification, quality, docs (only if the repo has issue types).
- **Labels**: `audit`, the repo's priority label for the severity (overlay
  mapping; default `priority:Pn`), `area:<area>`, `sp:N`, plus a dimension
  label (`security` | `bug` | `performance` | `tech-debt` | `documentation` |
  `refactor`), plus any overlay mapping labels. All exist by Step 0.
- **Assignee**: none. Triage assigns.
- **Body** sections, in order: `## Summary` · `## Current Behavior` ·
  `## Expected Behavior` · `## Root Cause / Evidence` (file:line at the SHA,
  quoted code, failure scenario) · `## Impact` · `## Scope` · `## Non-Goals` ·
  `## Acceptance Criteria` (checkboxes; last item is always a regression
  test) · `## Verification` (each verifier lens, its verdict, its quoted proof
  or reproduction output; the Codex verdict if run) · `## Related / Duplicate
  Check` · `## Estimate` (SP and severity rationale, finder vs verifier
  values, principle floor if applied) · `## Audit provenance` (date, SHA,
  area, angle, report path) · the hidden marker on its own last line:
  `<!-- codebase-audit-fingerprint: <fingerprint> -->`.
- **P3 batches**: one issue per area; sp 3 for ≤ 20 rows, 5 for 21–40, 8
  above; a table `| # | Location | Issue | Fix | SP |` plus one checkbox per
  row; one fingerprint per batch built from the area and date.

**Publish** severity-first so the most important findings get the lowest
numbers. Create one issue alone first to confirm labels and type are
accepted, then the rest in a few sequential lanes with a few seconds between
creates (GitHub secondary rate limits on content creation). Before each
create, search issues for the fingerprint and skip if it exists
(resume-safe). A search hit counts as a duplicate only when the matched issue's
body actually contains the fingerprint marker; confirm before skipping, because
GitHub search matches tokens, not exact strings. Record `fingerprint → issue #` in `<scratch>/published.json`
as you go. After publishing, run an independent check that lists issues
labelled `audit` created today, matches every payload fingerprint, and
reports missing issues, duplicate fingerprints, and label gaps.

## Step 6: Report

Write the report to the overlay's report path, else
`docs/audits/codebase-audit-YYYY-MM-DD.md` (UTC date; overwrite if it
exists). Commit and push the report skeleton on an audit branch **before**
publishing so a following session can resume from it, then fill it in.

0. **Run state and handoff**: the run tag line; a step table with status and
   where the state lives (scratch paths, Workflow run id); resume instructions
   (an issue whose body carries the same fingerprint is already filed; never
   double-file).
1. **Executive summary**: per-stage counts (candidates, after dedup, verified
   by verdict, swept, refuted by Codex, published, enriched); counts by
   severity and area; SP total; highest-leverage fixes.
2. **P0/P1 findings**: table: issue link, area, angle, verdict, SP, title.
3. **P2 findings**: same.
4. **P3 issues and batches**: table.
5. **Dependency advisories**: per ecosystem with fix versions.
6. **Scanner results**: commands and raw counts; scanners that could not run.
7. **Existing-issue overlaps**: keep/close recommendations, no action taken.
8. **Rejected findings**: title, area, angle, refuting lens, quoted proof.
8b. **Withheld (unverified)**: findings whose verifiers could not run, the
   lenses that failed, and the resume command. These were not published.
9. **Coverage of this run**: the project profile, areas and angles run,
   exclusions, `--since`/`--scope` if any, engine used (Workflow, Agent
   fan-out, or single-pass inline).
10. **Methodology**: agents, verification policy, dedup policy, hazards.

Then print the console summary:

```
Codebase Audit Complete (YYYY-MM-DD)
------------------------------------------------
Audited ref:              origin/<base> @ <sha>
Ran:                      <tag line>
Candidates → deduped:     C → D
Verified:                 CONFIRMED a · PLAUSIBLE b · REFUTED c · WITHHELD w   (sweep added s; codex demoted k)
By severity:              P0 a · P1 b · P2 c · P3 d (batched into e issues)
Issues created:           N   (Bug n · Task m)
Existing issues enriched: N
Existing overlaps flagged: N (no action taken)
Advisories:               <ecosystem> n · <ecosystem> m
Report:                   <path>
Mode:                     full | dry-run | scope=<s> | since=<ref> | no-codex
```

## Engine

Steps 2 and 3 are one orchestration: finders → dedup → verify → sweep →
verify. Run it with the first engine available and name the engine in §9.

1. **Workflow tool** (preferred). This command's instructions are the opt-in.
   Invoke the named workflow `codebase-audit-find-verify` from
   `.claude/workflows/` with `args` `{sha, worktree, areas: [{name, files}],
   angles, rubrics, noise_floor, principles, open_issues, scanner_hits,
   mode}`. It returns `{findings, verdicts, sweep, stats}`; write them to the
   scratch paths above. Every `agent()` call carries a `schema`, so no JSON
   is parsed by hand. On a rate-limit cut, relaunch with `resumeFromRunId`;
   finished finders return from cache and only the unfinished stages run.
   The audit exceeds the session's default 15-agent guideline by design;
   say so once when launching. The script withholds `UNVERIFIED` findings from
   its `publishable` list, so a run cut short by rate limits publishes less,
   never publishes unverified claims.
2. **Agent tool fan-out** when Workflow is unavailable. Same briefs, same
   schema, one Agent per finder and per verifier, writing to the same scratch
   paths. Verifiers must be fresh agents that have not seen finder output.
3. **Single pass inline** when neither is available. Work through every
   angle yourself, then re-check each candidate against the code before
   keeping it; drop anything without a concrete failure scenario. State
   clearly in the report and console that this was a single-pass review
   without independent verification, so nobody is misled about what ran.

## Operating Constraints

1. **No fabrication.** A finding without a file:line, a quoted line at the
   audited SHA, and a concrete failure scenario is not a finding. Never invent
   CVE IDs; copy them from scanner output.
2. **The audited SHA in the scratch worktree is the only ground truth** for code.
3. **Read-only on the repo** except the report file and, when asked, an
   overlay. Reproductions live in the scratch worktree and are never
   committed. The audit never fixes code; fixes are separate PRs.
4. **Never weaken a canary** or suggest skipping one as a fix.
5. **Graceful degradation.** If a scanner, engine, or the Codex pass cannot
   run, say so in the report and continue with what did run.
6. **Idempotent publishing.** A second run on the same day must not
   double-file (fingerprint search before create).
7. **Existing issues are not yours.** Enrichment is additive. Closing or
   retitling an existing issue is the maintainer's decision.
8. **Overlay principles are explicit.** A finding touching one names it in
   the body and gets at least P1, applied after the verdict.
9. **Correctness outranks cleanup.** When any cap forces a cut, security and
   correctness findings survive before performance, then quality, then
   simplification.
10. **Rate-limit resilience.** Write intermediate state to files (findings,
    verdicts, payloads, published map, report skeleton) so any step can be
    re-run without repeating the others.
