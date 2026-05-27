---
task_id: W-002
round: R0-A-on-plan
verdict: needs_architect
findings_count:
  red: 0
  yellow: 2
  green: 5
---

# W-002 R0-A on plan (architect-dispatched pre-impl review)

| Field | Value |
|---|---|
| Round | R0-A-on-plan (architect-dispatched per RC-9; fourth instance after W-001-impl + P1.3 + P1.4) |
| Reviewer | architect-partner (Claude Opus 4.7, 1M context) in primary session |
| Date | 2026-05-27 |
| Artifacts reviewed | `docs/process/architect-briefs/W-002.md`; `docs/process/senior-plans/W-002.md` (commit `edadf4b`); `docs/decisions/ADR-008-workflow-state-machine.md` (referenced); `docs/retrospectives/P1.3-candidates.md` RC-11 capture; `docs/retrospectives/P1.3.md` §4 + §5.2 + §8 rec #4 |
| Dispatch note | Architect explicitly dispatched per chat ("1"); brief lean was "skip R0-B for W-002" but RC-9 R0-A-on-plan is architect-decision-gated and architect chose dispatch. Fourth consecutive R0-A-on-plan dispatch — the pattern is now project-default for ADR-touching cycles; W-002 doesn't draft an ADR (path β) but DOES amend ADR-008, which lands it in the "architect-dispatched-by-default" basket. |

---

## Lens for this review

W-002 is mechanical bug-fix scope — no ADR drafted, no new module, no new layering. R0-A's value-add is checking the senior's three resolution-path picks (β over α and γ, optional inclusions disposition, surface-area discipline) and looking for ambiguities that would otherwise surface at impl-time and absorb junior cycles.

The plan is unusually tight (~2050 words, 4 atomic tasks, all bug fixes pre-scoped by the brief). My finding-set is correspondingly small: 2🟡 (one routing decision, one convention question) + 5🟢 (substantive defenses).

---

## Findings

### 🟡 Y1 — ADR-008 amendment shape: clarification paragraph vs cross-link convention

**Where:** plan W-002-1 acceptance criterion (`docs/process/senior-plans/W-002.md:34`): "Modify: `docs/decisions/ADR-008-workflow-state-machine.md` — add one paragraph cross-link at Decision 1's `awaiting_architect_accept` row clarifying that the ADR-id resolution mechanism is plan-frontmatter (per W-002), with the direct `ADR-{task-id}.md` path as backward-compat fallback. **This is a clarification, not a re-decision** — ADR-008 Decision 1's transition table is unchanged."

**What:** the senior is editing the body of an Accepted ADR with a post-Accept clarification. The project has precedent for this (ADR-009 D8 was added during P1.3 R0-A-on-plan revisions), but that amendment happened **within the same review cycle** before the ADR's first real consumer. W-002 amends ADR-008 ~6 days post-Accept, after ADR-008 has shipped and been dogfooded twice (W-001-impl, P1.3). **Two conventions are reasonable; the project hasn't picked one:**

- (a) ADRs are immutable after first consumer ships against them; new clarifications live elsewhere and cross-link TO the ADR. In this case, `docs/process/senior-plans/README.md` would carry the W-002 plan-frontmatter convention, with one sentence pointing at ADR-008 Decision 1.
- (b) ADRs can carry dated post-Accept clarifications inline as long as the Decision text itself isn't rewritten. Format: "**Note (added 2026-05-27 per W-002):** [text]" appended to the Decision row.

The plan picks (b) implicitly (unnamed clarification paragraph). My read: **(b) is defensible**, but the project should pick deliberately because this is the first non-same-review-cycle ADR amendment. If (b) is adopted as the convention, plan should specify the date-stamp format. If (a) is adopted, the clarification moves out of ADR-008.

**Options for resolution:**

- **(α) Pick (b) + date-stamp.** Plan W-002-1 acceptance amended: "add one paragraph **with the prefix `**Note (added 2026-05-27 per W-002):**`** at Decision 1's row..." Sets the project convention for future post-Accept amendments.
- **(β) Pick (a).** Move the clarification entirely to `docs/process/senior-plans/README.md`'s post-W-002 frontmatter section (already in scope of W-002-1). ADR-008 stays untouched. Future readers find the convention via senior-plans/README cross-link.
- **(γ) Defer the convention question; pick (b) without date-stamp for W-002, capture as W-003 candidate** (codify the post-Accept-amendment convention in a small process doc).

**My lean: (β).** ADR-008 stays untouched preserves the "ADRs as audit snapshots" semantic; senior-plans/README.md is the natural home for the plan-frontmatter convention (it's the doc that authors of new plans read first). The cost is one missed cross-link from ADR-008 → senior-plans/README, which is a 5-surface-scan concern not an ADR concern.

**Severity 🟡**: convention question with project-level precedent implications; architect should pick.

### 🟡 Y2 — Plan §5 push-back #3 (state-machine bug for no-ADR tasks) — needs explicit routing

**Where:** plan §5 push-back #3 (`docs/process/senior-plans/W-002.md:188-196`): "The current state-machine routes `awaiting_senior_plan → awaiting_architect_accept` unconditionally on senior plan push ... regardless of whether an ADR is drafted alongside. For W-002 (no ADR), this is a dead-end ... **Architect-partner will need to override.**"

**What:** the senior correctly surfaces a third state-machine bug discovered during W-002 plan-writing — tasks without ADRs route through `awaiting_architect_accept` (which never advances because no ADR → no Accept event). Senior recommends "do not extend W-002 scope to fix this; surface in retro candidates." Three issues with this recommendation:

- **The bug WILL manifest on W-002's own state file** the moment this plan pushes (`.workflow/W-002.yaml: awaiting_senior_plan → awaiting_architect_accept` auto-trigger fires; W-002 has no ADR; state is stuck). Architect-partner will be the one performing the override. That's a second override on the project's young override_history (P1.3's `cfbf087` was the first). Override-frequency is becoming a signal worth weighting.
- **The fix is small.** W-002-1's plan-frontmatter parser already reads the `adr` field. The `next_state` function in `transitions.py` can read the same field at plan-publish-detection time: if no `adr` key declared, skip `awaiting_architect_accept` and route directly `awaiting_senior_plan → awaiting_junior_impl`. **One additional if-branch in `next_state`, one additional test.** This is ~20 LoC and would fit naturally as a W-002-1 sub-task or a new W-002-2b atomic.
- **Senior's recommendation (a) — override-as-dogfood — preserves the bug** as known-and-worked-around. If P1.4 or P1.5 lands tasks without ADRs (e.g., a content-only task with no architectural decision), the override accumulates. The fix is cheaper than the recurring override cost.

**Options for resolution:**

- **(α) Architect routes (a) override / dogfood per senior's lean.** W-002-1's plan-frontmatter parsing lands; the no-ADR routing fix waits for W-003. Captures a fourth state-machine refinement candidate.
- **(β) Architect extends W-002 scope to include the no-ADR routing fix.** Adds W-002-2b atomic (or extends W-002-1 acceptance) for `next_state` to consult the plan frontmatter and skip `awaiting_architect_accept` when no `adr` key declared. ~20 LoC + 2 tests; minimal plan-revision impact; gets W-002 to land without architect override on its own state.
- **(γ) Defer entirely to W-003.** W-002 ships as planned; architect overrides W-002.yaml; both this bug and the next non-ADR task hit the override path; W-003 absorbs all state-machine refinements together.

**My lean: (β).** The fix is small enough to land in W-002 and the alternative (architect override on every W-002 / similar task) is the exact pattern RC-11 sub-finding (a) tried to close. We caught the bug pre-impl during plan-writing; landing the fix in the same cycle is the cleanest precedent.

**Severity 🟡**: routing decision with measurable cycle-cost implication; architect should pick (α/β/γ) explicitly rather than defaulting to senior's lean.

---

### 🟢 G1 — Brief decision compliance is complete

All 4 brief Architect-settled decisions honored:

- **§1 (sub-finding (a) path picker)** — path β chosen with three substantive defenses (RC-6 entanglement avoidance; multi-ADR future intersects α; γ rejected per brief con-list). Aligned with brief lean.
- **§2 (sub-finding (b) single-if-branch fix)** — W-002-2 inscribes the `from_state == AWAITING_ARCHITECT_DECISION AND to_state == AWAITING_JUNIOR_IMPL` guard. Tests cover the P1.3-case regression + defense-in-depth + warning-emission narrowing. Mechanical fix, mechanically planned.
- **§3 (optional verify-workspace inclusion)** — deferred to W-003 per brief lean (4-task ceiling honored). Defense is substantive: (a) gap detectable in <60s; (b) cross-cutting work earns its own brief; (c) W-002 has calendar pressure (P1.4 dependency) that W-003 doesn't.
- **§4 (optional skills loader fix)** — included as W-002-3. Sentinel design (`_NotASkillFile` class vs `None`) defended explicitly (None collides with valid-empty-dict). Logger pattern matches W-002 project convention (`logging.getLogger(__name__).debug`). Comprehensive test coverage (skip cases + still-raises cases).

### 🟢 G2 — All 5 brief push-backs addressed substantively; senior adds a 6th honest meta-discovery

Plan §5 enumerates 6 push-backs:
- #1: path β over α and γ (brief invited; defended with 3 reasons including RC-6 boundary respect)
- #2: verify-workspace deferred to W-003 (brief invited)
- #3: **NEW** state-machine bug for no-ADR tasks surfaced from plan-writing (senior self-discovery; this is the Y2 above)
- #4: multi-ADR-per-task future anchored via path β's additive extensibility (brief invited)
- #5: CI-enforcement of plan-frontmatter convention deferred to W-003 (brief predicted; senior agreed)
- #6: `_read_adr_status` other edge cases (Superseded, two-ADRs-one-task) documented as out-of-scope-for-W-002 (brief predicted)

**Push-back #3 is the kind of senior-honest surface-as-you-discover that the architect-partner role exists to invite.** Even though it's the Y2 above (needs architect routing), the act of surfacing it pre-impl is exactly right.

### 🟢 G3 — Backwards compatibility for existing plans correctly handled

W-002-1 acceptance explicitly covers: P1.3, W-001-impl, P1.4 plans (predating the frontmatter convention) get the direct `ADR-{task-id}.md` fallback path. Existing test fixtures continue to pass without modification. Acceptance criterion line names this:

> "Existing P1.3 (`docs/process/senior-plans/P1.3.md` has no frontmatter) returns 'none' under the fallback — matches today's behavior. Existing W-001-impl similarly. Existing test fixtures continue to pass without modification."

This is the right discipline. A schema/convention change that breaks existing artifacts is the worst kind of W-002 regression; the fallback path explicitly prevents it.

### 🟢 G4 — Sentinel design for non-skill `.md` is sound

W-002-3 acceptance line 93: "I prefer a typed sentinel class (`class _NotASkillFile: pass`) over `None` because `None` collides with 'valid dict but empty' (which Pydantic would reject downstream anyway, but the boundary is cleaner with a distinct type)."

This matches the project's Pydantic-strict + closed-type discipline (frozen + extra-forbid models; closed-Literal discriminators; no `Any` if a discriminated union fits). `_NotASkillFile` as a singleton via module-level `_NOT_A_SKILL = _NotASkillFile()` is idiomatic and testable. **Implementation note for junior**: `isinstance(x, _NotASkillFile)` check in `load_skills` is the clean caller pattern; equality-against-singleton works but `isinstance` is clearer at the type-narrowing boundary.

### 🟢 G5 — 5-surface scan in W-002-4 is thoroughly itemized

W-002-4 acceptance enumerates each of the 5 surfaces with concrete file paths + the RC-1 pre-edit grep requirement:

- §1 `src/`: 3 files named (cli.py, transitions.py, loader.py)
- §2 `config/`: none — explicitly justified (no `.yaml.example` change)
- §3 ADRs: ADR-008 named (W-002-1 amendment; tied to Y1 above)
- §4 `docs/architecture/`: none expected; note caveat for `test-coverage-standard.md`
- §5 narrative: `handoff.md` mentioned with conditional scope ("extend §16 if appropriate")
- §6 `senior-plans/README.md`: tied to W-002-1

The RC-1 grep on ADR-008 is explicit: "confirm no other text in ADR-008 still says 'no `task_id → adr_id` mapping' (none should — that phrasing lives in the P1.3 candidates file as historical record, not in ADR-008)." **Tight discipline; matches the W-001-impl-8 scan precedent.**

---

## Push-back disposition table (architect-decision view)

| # | Brief push-back | Plan disposition (§5) | Substantive? | My read |
|---|---|---|---|---|
| 1 | path α / β / γ | #1: β | yes (3 defenses) | ✓ matches architect-partner lean; well-defended |
| 2 | verify-workspace inclusion | #2: defer to W-003 | yes (4-task ceiling + 3 sub-reasons) | ✓ correct cut |
| 3 | optional skills fix inclusion | included (W-002-3) | yes (sentinel design defended; tests comprehensive) | ✓ included with quality |
| 4 | multi-ADR-per-task future | #4: path β extends additively | yes (no migration needed) | ✓ best-case forward-compat |
| 5 | cycle-counter test placement | tests in existing `test_transitions.py` | yes (matrix coverage; no new file) | ✓ standard placement |

**Verdict on push-back coverage:** 5/5 substantive. Plus senior surfaces #3 (state-machine bug for no-ADR) and #5 (CI enforcement deferred) and #6 (`_read_adr_status` edge cases) as honest meta-discoveries.

---

## Cross-checks

- [x] Frontmatter contract on this file followed.
- [x] Plan §3 execution order coherent (W-002-1..4 sequential).
- [x] No new constitutional tests expected (no new module, no new layering) — plan §4 confirms.
- [x] Test count delta consistent (≥9 new tests, ≥463 total post-W-002; brief's "no regression in 78 workflow tests" satisfied).
- [x] Backwards compat for existing plans (P1.3, W-001-impl, P1.4) explicit and tested.
- [x] No new LLMPurpose / no LLM imports in workflow module.
- [x] RC-1 pre-edit grep applied per surface in W-002-4 scan.
- [x] Path β additive-extensibility for multi-ADR future preserved.
- [ ] **ADR-008 amendment convention** — Y1 above; project hasn't picked (a) inline-dated vs (b) external-cross-link.
- [ ] **State-machine bug for no-ADR tasks** — Y2 above; architect should route.

---

## Net assessment

**Recommendation: needs_architect.** Two 🟡 findings, both routing decisions architect should make explicitly:

- Y1 (ADR-008 amendment shape) — convention-level pick; 1-2 sentence resolution either way.
- Y2 (no-ADR routing fix scope) — architect picks (α defer / β include in W-002 / γ defer to W-003); ~20 LoC delta if β.

**Five 🟢 findings document a tight, well-defended plan.** Path β chosen with substantive defense; brief push-backs all addressed; backwards compat handled; sentinel design sound; 5-surface scan thoroughly itemized.

**The plan is revisable to clean status in one revision pass** absorbing Y1 (architect picks amendment convention; senior adjusts W-002-1 acceptance text accordingly) + Y2 (architect picks α/β/γ; senior adjusts §5 push-back #3 + possibly adds W-002-2b atomic).

**Sequencing note for architect:** Y2 routing decision intersects the broader W-002 → P1.4 sequencing pressure (P1.3 retro §8 rec #4: W-002 must land before P1.4 ADR Accept). Option (β) extends W-002 scope slightly but the extension is bounded; (α) and (γ) keep W-002 narrow but cost an override per W-002.yaml that the harness's own dogfood will then need to perform. If the architect-partner is willing to perform W-002.yaml's override at land-time (precedent: cfbf087 for P1.3), (α) costs nothing immediate. If the override-frequency signal is becoming concerning, (β) is the closing move.

**No 🔴 findings.** Plan is structurally sound; no impl-detail ship-bugs surfaced from architect-partner lens (consistent with W-002 being a mechanical bug-fix plan with no novel design surface).

Cross-family R0-B explicitly NOT dispatched per brief (RC-2 stays accepted for non-shape-change work; W-002 is mechanical workflow refinement). This R0-A is the only review the plan receives before architect acceptance.
