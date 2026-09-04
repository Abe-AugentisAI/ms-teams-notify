export const meta = {
  name: 'codebase-audit-find-verify',
  description: 'Codebase audit: area-by-angle finders, dedup, lens-diverse verification, gap sweep',
  whenToUse: 'Invoked by /codebase-audit Steps 2-3. Pass args {sha, worktree, areas, angles, rubrics, noise_floor, principles, open_issues, scanner_hits, mode}.',
  phases: [
    { title: 'Find', detail: 'one finder per area x angle' },
    { title: 'Verify', detail: 'P0/P1 three lenses, P2 one, P3 spot-check' },
    { title: 'Sweep', detail: 'one fresh finder per area hunting only for gaps' },
    { title: 'Verify sweep', detail: 'same lenses on sweep candidates' },
  ],
}

const A = args || {}
const areas = A.areas || []
const angles = A.angles || []

const FINDING = {
  type: 'object',
  properties: {
    title: { type: 'string' },
    short_summary: { type: 'string' },
    file: { type: 'string' },
    line: { type: 'integer' },
    other_locations: { type: 'array', items: { type: 'string' } },
    angle: { type: 'string' },
    dimension: { type: 'string', enum: ['security', 'correctness', 'performance', 'simplification', 'quality'] },
    severity: { type: 'string', enum: ['P0', 'P1', 'P2', 'P3'] },
    area: { type: 'string' },
    failure_scenario: { type: 'string' },
    evidence: { type: 'string' },
    impact: { type: 'string' },
    suggested_fix: { type: 'string' },
    sp: { type: 'integer' },
    sp_rationale: { type: 'string' },
    principle: { type: ['string', 'null'] },
    related_issues: { type: 'array', items: { type: 'object', properties: { number: { type: 'integer' }, relation: { type: 'string' } }, required: ['number', 'relation'] } },
  },
  required: ['title', 'short_summary', 'file', 'line', 'angle', 'dimension', 'severity', 'area', 'failure_scenario', 'evidence', 'sp'],
}
const FINDINGS = { type: 'object', properties: { findings: { type: 'array', items: FINDING }, cut: { type: 'integer' } }, required: ['findings', 'cut'] }
const VERDICT = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['CONFIRMED', 'PLAUSIBLE', 'REFUTED'] },
    reason: { type: 'string' },
    proof: { type: 'string' },
    severity: { type: 'string', enum: ['P0', 'P1', 'P2', 'P3'] },
    sp: { type: 'integer' },
    sp_rationale: { type: 'string' },
    unreachable: { type: 'boolean' },
  },
  required: ['verdict', 'reason', 'proof', 'severity', 'sp'],
}

const common = `Audited SHA: ${A.sha}. Read code ONLY from the worktree at ${A.worktree}. Do not modify it. Do not spawn subagents.
Severity and SP rubrics:\n${A.rubrics || ''}\nNoise floor:\n${A.noise_floor || ''}\nOverlay principles:\n${A.principles || ''}`

function finderPrompt(area, angle, extra) {
  return `${common}
You are ONE finder in a codebase audit. Area: ${area.name}. Files:\n${(area.files || []).join('\n')}
Angle:\n${angle.brief}
Scanner hits for these files:\n${A.scanner_hits && A.scanner_hits[area.name] ? A.scanner_hits[area.name] : '(none)'}
Open issues (number, title) for dedup hints:\n${A.open_issues || '(none)'}
${extra || ''}
Rules: every candidate needs a concrete failure_scenario (cleanup candidates state the concrete cost). Pass every candidate with a nameable failure scenario through; verification is a later stage, not your job. Quote the lines you rely on in evidence. Cap 10 candidates, most severe first; if fewer qualify return fewer, do not pad. Set angle="${angle.name}" and area="${area.name}" on each.`
}

// Fingerprints and dedup keys stay opaque: a readable marker gets tokenised by
// GitHub issue search and produces false duplicate hits at publish time.
// Dedup keys stay opaque: a readable marker gets tokenised by GitHub issue search
// and produces false duplicate hits at publish time.
// A finding is identified by its LOCATION SET (primary plus other_locations) and its
// MECHANISM. Two findings merge only when both overlap, so two distinct defects on one
// line stay distinct and one defect anchored at different ends of a cross-file pair merges.
function loc(file, line) { return `${file}:${line}` }
function locations(f) {
  return [...new Set([loc(f.file, f.line), ...(f.other_locations || []).map(x => String(x).trim())])]
}
function mech(f) {
  return (f.short_summary || f.title || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
}
function sameMech(a, b) {
  const x = mech(a), y = mech(b)
  if (!x || !y) return false
  return x === y || x.startsWith(y) || y.startsWith(x)
}
function merge(keep, drop) {
  if ((drop.failure_scenario || '').length > (keep.failure_scenario || '').length) {
    keep.failure_scenario = drop.failure_scenario
    keep.evidence = drop.evidence || keep.evidence
  }
  // Keep the STRONGEST severity. Keeping the first would let a P3 duplicate arriving
  // before a P0 suppress the three-lens panel the P0 must face.
  if (RANK[drop.severity] < RANK[keep.severity]) {
    keep.severity = drop.severity
    keep.sp = drop.sp
    keep.sp_rationale = drop.sp_rationale
  }
  keep.principle = keep.principle || drop.principle
  keep.other_locations = [...new Set([...(keep.other_locations || []), ...locations(drop)])]
    .filter(l => l !== loc(keep.file, keep.line))
  return keep
}
function dedup(list) {
  const kept = []
  for (const f of list) {
    const locs = locations(f)
    const hit = kept.find(g => sameMech(g, f) && locations(g).some(l => locs.includes(l)))
    if (hit) merge(hit, f); else kept.push({ ...f })
  }
  return kept
}

function verifierPrompt(f, lens) {
  const base = `${common}
Candidate finding to VERIFY (you have not seen the finder's reasoning):
Title: ${f.title}\nLocation: ${f.file}:${f.line}${(f.other_locations || []).length ? ' also ' + f.other_locations.join(', ') : ''}
Failure scenario: ${f.failure_scenario}\nQuoted evidence: ${f.evidence}
Return exactly one verdict:
- CONFIRMED: you can name the inputs/state that trigger it and the wrong output or crash. Quote the line.
- PLAUSIBLE: mechanism is real, trigger is uncertain (timing, env, config). State what would confirm it.
- REFUTED: factually wrong (code does not say that), provably impossible (type/constant/invariant, show it), already guarded elsewhere (cite the guard), or pure style with no observable effect. Quote the line that proves it.
PLAUSIBLE by default: do not refute for being "speculative" when the state is realistic (races, nil on a rare-but-reachable path, falsy-zero, boundary off-by-one, retry storms, regex that lost an anchor). REFUTED only when constructible from the code.
Return your own severity and SP against the rubric with a one-line rationale, and put the quoted line, guard, invariant, or reproduction output in proof.`
  const lenses = {
    refute: `\nLens: refute-from-code. Try hard to refute from code, tests, installed packages, and specs.`,
    reach: `\nLens: reachability and exploitability at the audited SHA. Is this code on a live path (registered route, imported module, scheduled job, component reachable from a live route)? Grep importers and registrations. For security findings, trace an attack path from an untrusted entry point to the sink and apply the exclusion list in the noise floor. If nothing reaches it, return REFUTED with unreachable=true.`,
    repro: `\nLens: reproduce. Write a failing test or runnable check inside the worktree (never commit or push), run it, and put the output in proof. If reproduction needs live services you do not have, say what is needed and vote PLAUSIBLE at most.`,
  }
  return base + lenses[lens]
}

const RANK = { P0: 0, P1: 1, P2: 2, P3: 3 }
function lower(sev) { return { P0: 'P1', P1: 'P2', P2: 'P3', P3: 'P3' }[sev] }
function majority(votes) {
  const counts = { CONFIRMED: 0, PLAUSIBLE: 0, REFUTED: 0 }
  for (const v of votes) counts[v.verdict]++
  if (counts.REFUTED > votes.length / 2) return 'REFUTED'
  if (counts.CONFIRMED > votes.length / 2) return 'CONFIRMED'
  return 'PLAUSIBLE'
}

// Verdicts that must never reach the publish step:
//   REFUTED    - refuted from the code
//   UNVERIFIED - every verifier for this finding died (credits, API error). NOT a pass.
// SPOT_SKIPPED is a P3 row the spot-check sample did not draw; it publishes in the batch.
// P3 spot-check sample: every fifth row, and never fewer than three rows overall.
// `idx % 5` alone checks only two rows out of eight, below the stated minimum.
function spotChecked(idx, total) { return idx % 5 === 0 || idx < Math.min(3, total) }

async function verify(f, idx, phaseName, total = 0) {
  const sev = f.severity
  const lensSet = sev === 'P0' || sev === 'P1' ? ['refute', 'reach', 'repro'] : sev === 'P2' ? ['refute'] : (spotChecked(idx, total) ? ['refute'] : [])
  if (!lensSet.length) return { finding: f, verdict: 'SPOT_SKIPPED', votes: [], severity: sev, sp: f.sp, lenses_run: [] }
  const raw = await parallel(lensSet.map(l => () =>
    agent(verifierPrompt(f, l), { label: `verify:${l}:${f.file.split('/').pop()}:${f.line}`, phase: phaseName, schema: VERDICT })
      .then(v => (v ? { ...v, lens: l } : null))
  ))
  const votes = raw.filter(Boolean)
  const ranLenses = votes.map(v => v.lens)
  const missing = lensSet.filter(l => !ranLenses.includes(l))
  // No vote at all is never a pass: quarantine it for the report, do not publish.
  if (!votes.length) return { finding: f, verdict: 'UNVERIFIED', votes: [], severity: sev, sp: f.sp, lenses_run: [], lenses_missing: missing }
  const verdict = majority(votes)
  const unreachable = votes.some(v => v.unreachable)
  // Severity comes only from the votes that SUPPORT the final verdict. Letting a
  // refuting vote set severity lets one dissenter inflate a finding it rejected.
  const supporting = votes.filter(v => v.verdict === verdict)
  const pool = supporting.length ? supporting : votes
  const strongest = pool.slice().sort((a, b) => RANK[a.severity] - RANK[b.severity])[0]
  let severity = strongest.severity
  // A partial panel does not carry a full-strength verdict: with fewer than two of
  // three lenses back, the strongest a P0/P1 finding can be is PLAUSIBLE.
  const degraded = lensSet.length === 3 && votes.length < 2
  const finalVerdict = degraded && verdict === 'CONFIRMED' ? 'PLAUSIBLE' : verdict
  if (finalVerdict === 'PLAUSIBLE') severity = lower(severity)
  // An unreachable finding is a dead-code row, not a Bug: force P3 and flag it so the
  // issue body names the reachability verdict rather than claiming a live defect.
  if (unreachable) severity = 'P3'
  return { finding: f, verdict: finalVerdict, votes, severity, sp: strongest.sp, unreachable, degraded, lenses_run: ranLenses, lenses_missing: missing }
}

// Phase 1: find. Pipeline: each finder's result is deduped locally as it lands.
const jobs = []
for (const area of areas) for (const angle of angles) jobs.push({ area, angle })
log(`Find: ${jobs.length} finders (${areas.length} areas x ${angles.length} angles)`)
const raw = (await pipeline(jobs, j =>
  agent(finderPrompt(j.area, j.angle), { label: `find:${j.area.name}:${j.angle.name}`, phase: 'Find', schema: FINDINGS })
)).filter(Boolean)
const candidates = raw.flatMap(r => r.findings)
const cut = raw.reduce((n, r) => n + (r.cut || 0), 0)
if (cut) log(`Finders cut ${cut} candidates past their caps`)

// Barrier: dedup needs the whole pool.
const deduped = dedup(candidates)
log(`Candidates ${candidates.length} → ${deduped.length} after dedup`)

// Phase 2: verify. Pipeline per finding; lens votes fan out inside.
const verified = (await pipeline(deduped, (f, _, i) => verify(f, i, 'Verify', deduped.length))).filter(Boolean)

// Phase 3: sweep. One fresh finder per area holding that area's surviving list.
const PUBLISHABLE = v => v.verdict !== 'REFUTED' && v.verdict !== 'UNVERIFIED'
const survivors = verified.filter(PUBLISHABLE)
const sweepRaw = (await pipeline(areas, area => {
  const known = survivors.filter(v => v.finding.area === area.name).map(v => `- ${v.finding.file}:${v.finding.line} ${v.finding.short_summary}`).join('\n')
  const sweepAngle = { name: 'sweep', brief: `You hold the verified list for this area:\n${known || '(empty)'}\nRe-read the file set looking ONLY for defects not already listed. Do not re-derive or re-confirm anything. Focus on what a first pass misses: moved/extracted code that dropped a guard or anchor; second-tier footguns (dataclass default evaluated once, hash() non-determinism, lock-scope shrink, predicate methods with side effects); setup/teardown asymmetry in tests; config defaults flipped; a state written but never compared; two timeouts guarding one operation with equal or inverted ordering. Up to 8 additional candidates. If nothing new, return an empty list; do not pad.` }
  return agent(finderPrompt(area, sweepAngle), { label: `sweep:${area.name}`, phase: 'Sweep', schema: FINDINGS })
})).filter(Boolean)
const seen = new Set(deduped.map(key))
const sweepCandidates = dedup(sweepRaw.flatMap(r => r.findings).filter(f => !seen.has(key(f))))
log(`Sweep surfaced ${sweepCandidates.length} new candidates`)

// Phase 4: verify sweep output with the same lenses.
const sweepVerified = (await pipeline(sweepCandidates, (f, _, i) => verify(f, i, 'Verify sweep', sweepCandidates.length))).filter(Boolean)

const all = [...verified, ...sweepVerified]
const stats = {
  finders: jobs.length, candidates: candidates.length, cut, deduped: deduped.length,
  confirmed: all.filter(v => v.verdict === 'CONFIRMED').length,
  plausible: all.filter(v => v.verdict === 'PLAUSIBLE').length,
  refuted: all.filter(v => v.verdict === 'REFUTED').length,
  unverified: all.filter(v => v.verdict === 'UNVERIFIED').length,
  spot_skipped: all.filter(v => v.verdict === 'SPOT_SKIPPED').length,
  degraded: all.filter(v => v.degraded).length,
  unreachable: all.filter(v => v.unreachable).length,
  swept: sweepCandidates.length,
}
log(`Verify: CONFIRMED ${stats.confirmed} / PLAUSIBLE ${stats.plausible} / REFUTED ${stats.refuted} / UNVERIFIED ${stats.unverified} (agents died) / degraded ${stats.degraded} / unreachable ${stats.unreachable}`)
if (stats.unverified) log(`WARNING: ${stats.unverified} findings could not be verified and are withheld from publishing. Resume this run to verify them.`)
return {
  findings: deduped,
  verdicts: verified,
  sweep: sweepVerified,
  publishable: all.filter(PUBLISHABLE),
  withheld: all.filter(v => v.verdict === 'UNVERIFIED'),
  rejected: all.filter(v => v.verdict === 'REFUTED'),
  stats,
}
