---
task_id: W-003
round: R0-A-on-plan
verdict: needs_architect
findings_count:
  red: 0
  yellow: 2
  green: 8
---

# W-003 R0-A on plan (architect-dispatched pre-impl review)

| Field | Value |
|---|---|
| Round | R0-A-on-plan (architect-dispatched per RC-9; 6th instance after W-001-impl + P1.3 + P1.4 + W-002 + P1.5) |
| Reviewer | architect-partner (Claude Opus 4.7, 1M context) in primary session |
| Date | 2026-05-27 |
| Artifacts reviewed | `docs/process/architect-briefs/W-003.md`; `docs/process/senior-plans/W-003.md` (commit `4b582cf`). Cross-referenced: W-002 + W-002.5 plans (prior workflow refinement cycles for shape comparison); ADR-008 (state-machine canonical contract); P1.4 retro §4 RC-13 + P1.5 retro §4 RC-16 + R0-A G4 verify-workspace capability. |
| Branch base note | `claude/W-003-plan` was cut from `a80cc7b` (W-003 brief commit). Main has since advanced to `6365cce` (RC-10 + RC-15 codifications). PR merge will be **clean** (3-way merge; non-overlapping file additions: `reviews/README.md` extension + `dual-lens-r0b.md` new on main; `senior-plans/W-003.md` new on branch). The diff-vs-main showing "deletions" is normal git optics, not senior intent. |

---

## Lens

W-003 is mechanical workflow refinement (4 atomics + landing). Plan is comprehensive — every brief In-scope item addressed; every push-back disposed substantively; no scope creep into deferred items. Plan length ~1850 words within brief's 1500-2000 budget. Same shape as W-002 + W-002.5 (small mechanical scope; no ADR; no new module; no new layering edge).

R0-A-distinct lens: brief-compliance audit, push-back substantive defense, predicted-self-discovery handling, parallelism-rule application post-RC-17 codification, architect-partner-distinct observations on "decision deferred to junior at impl time" patterns (P1.5 retro §4 Y1 trail).

---

## Findings

### 🟡 Y1 — `_has_commit_since` investigation scope deferred to impl-time (self-discovery #1)

**Where:** plan §2 W-003-1 acceptance ("`_has_commit_since` related concern"); plan §5 self-discovery #1.

**What:** Senior surfaces "`_has_commit_since` may have the same working-tree-vs-origin issue" as a predicted self-discovery, then **defers the decision to impl-time**: "investigate during impl; report findings. If fix is mechanical (≤10 LoC), bundle into W-003-1. If larger, surface in §5 as new W-003-1b atomic. Lean: investigate during impl; report findings."

The lean reads: "probably correct-by-design (the function is asking 'has the task author committed locally' which is independent of whether the work is on origin yet), but worth verifying."

**Concern:** This is the **same pattern P1.5 R0-A Y1 flagged**: architecturally-relevant decision deferred to junior at impl-time. If junior reads `_has_commit_since` and finds it IS buggy (same shape as RC-16), they then have to decide whether to bundle vs split — that's a plan-stage scope decision happening at impl-time.

**Options for resolution:**

- **(α) Senior pre-investigates** `_has_commit_since` semantics during plan revision; pins the call-up-front:
  - If `_has_commit_since` IS correct-by-design (its current semantic — "any local commit since `since`" — is what the auto-trigger needs) → plan acceptance language: "investigation confirmed correct-by-design; no fix needed."
  - If `_has_commit_since` IS buggy (same RC-16 shape) → plan adds W-003-1b atomic explicitly with fix scope + tests.
- **(β) Keep current deferral**: junior investigates at impl; surfaces in commit body OR plan-vs-impl review.
- **(γ) Split investigation as W-003-0**: a pre-impl investigation atomic that runs first; senior plan absorbs findings before junior dispatches the rest.

**My lean: (α)** — senior takes 5-10 minutes to grep + read `_has_commit_since` body during plan revision; settles the question; updates plan accordingly. Removes the impl-time scope-decision burden from junior. Matches the "architectural decisions inscribed in plan, not at impl" discipline named in P1.5 retro.

**Severity 🟡**: not a runtime bug; impl-time scope decision that's resolvable at plan-time with minimal effort.

### 🟡 Y2 — Subprocess helper extract decision deferred to junior at impl-time (self-discovery #3)

**Where:** plan §5 self-discovery #3.

**What:** Senior identifies that W-003-1 + W-003-3 both add `git show` subprocess patterns and predicts "if call sites total ≥3, extract `_git_show(rel_path, ref) -> str | None` helper. Lean: inline if 2 sites; extract if 3+. Junior decides at W-003-3 impl time based on actual call-site count."

**Concern:** Same shape as Y1 — design decision (extract helper or inline) deferred to junior at impl-time. The threshold (2 vs 3) is sensible but unprincipled; whether the helper exists changes the testing surface + the extraction commit count.

**Options for resolution:**

- **(α) Senior pre-pins**: "extract `_git_show` helper as part of W-003-1; both W-003-1 and W-003-3 consume it." Single-source-of-truth + symmetric subprocess error handling at the helper boundary. Cost: 5 extra LoC in W-003-1 to wrap the existing inline subprocess.
- **(β) Senior pre-pins inline**: "inline subprocess in both W-003-1 + W-003-3 + `_has_commit_since` (if buggy); helper extracted only if a 4th call site lands in W-004+." Simpler; matches the "extract when actually needed" discipline.
- **(γ) Keep current deferral**: junior counts call sites at impl + decides.

**My lean: (α)** — extract helper upfront for the 2-3 call sites; the helper is small (~5-10 LoC); centralizes subprocess error handling (timeout; non-zero exit; missing-file return-None semantic) which is exactly the kind of thing easy to inconsistently inline. Single helper makes W-003-3's tests less duplicative.

**Severity 🟡**: same as Y1 — design decision deferred to impl; resolvable at plan-time. (β) is also defensible; the architect-partner concern is that the decision-shape is unclear in the plan, not that the lean is wrong.

### 🟢 G1 — All 4 brief In-scope items addressed substantively

| Brief In-scope | Plan task | Mapping |
|---|---|---|
| W-003-1 RC-16 fix (`_read_plan_frontmatter` reads origin/main) | W-003-1 | ✓ exact match; `git show origin/main:<rel_path>` impl path; backwards-compat preserved; edge case (plan on branch) handled |
| W-003-2 RC-13 forcing function (verify-merge-readiness CLI) | W-003-2 | ✓ exact match; warn-don't-block discipline preserved; structured output; exit 0 |
| W-003-3 verify-workspace divergence detection | W-003-3 | ✓ exact match; per-task state-file comparison; warn-don't-block |
| W-003-4 junior-session CLI capability watch closure | W-003-4 | ✓ exact match; investigation phase first; lean docs-gap; minimal fix in `CLAUDE.md` OR `.claude/hooks/session-start.sh` |

### 🟢 G2 — All 4 brief Out-of-scope items respected

| Brief Out-of-scope | Plan disposition |
|---|---|
| Multi-ADR granular Accept tracking | §5 push-back #6: keep deferred; no concrete consumer through P1.5 |
| Plan-frontmatter CI enforcement | Not mentioned in plan; correctly out-of-scope |
| RC-10 codification | Plan §1 explicitly notes "process-doc codifications (RC-10 / RC-15) are architect-partner-direct work orthogonal to senior/junior cycle" — out-of-scope honored |
| RC-15 codification | Same as above |

### 🟢 G3 — All 6 brief push-backs disposed substantively

| # | Brief push-back | Plan §5 disposition |
|---|---|---|
| 1 | verify-merge-readiness shape | #1: CLI subcommand (matches lean); rejected GHA + PR-template-Q3 with rationale |
| 2 | RC-16 edge case (plan on branch) | #2: "merge IS the publish event" per ADR-008 D1; treats not-on-origin as "no frontmatter" via fallback |
| 3 | verify-workspace output shape | #3: structured (matches `workflow status` style) |
| 4 | Junior-session capability investigation | #4: docs-gap lean (env issue would have surfaced in prior cycles) |
| 5 | Atomic-task count | #5: 5 commits separated for tracking clarity; rejected W-003-2 + W-003-3 bundle |
| 6 | Multi-ADR granular Accept | #6: keep deferred (no concrete consumer) |

All 6 substantively defended; no silent ignores.

### 🟢 G4 — Three senior self-discoveries surfaced

| # | Self-discovery | Disposition |
|---|---|---|
| 1 | `_has_commit_since` working-tree-vs-origin investigation | Surfaced; deferred to impl (see Y1 above) |
| 2 | verify-workspace state-file invariant scope | Senior call: "keep W-003-3 narrowly scoped; defer cycle-monotonicity + override_history checks until real bug surfaces." YAGNI discipline. ✓ |
| 3 | Subprocess error handling helper extract | Surfaced; deferred to impl (see Y2 above) |

Two of three deferred; (1) + (3) are the Y1 + Y2 above. (2) cleanly resolved with explicit YAGNI defense.

### 🟢 G5 — No new ADR; ADR-014 path correctly conditional

Senior matches brief Architect-settled decision 3: "no new ADR expected (mechanical refinement). If senior surfaces a design surface I didn't anticipate, draft ADR-014 per senior-drafts-ADR rule (RC-3)." Plan §1 + header table: "Senior may surface ADR-014 if a design surface emerges during impl." Conditional; correct shape. None of the 5 atomic tasks have emergent design surface; no ADR-014 needed.

### 🟢 G6 — Parallelism rule applied post-RC-17 codification

Plan §3 declares the parallel set explicitly: `[W-003-1 ‖ W-003-4]`. Senior reasoning: independent files (`io.py` vs `CLAUDE.md`/docs); distinct test files; no shared mutable state. Sequential W-003-2 → W-003-3 (both edit `cli.py`).

Per the `senior-planner.md` RC-17 amendment ("one atomic = one commit subject"): plan is set up correctly. Junior dispatches W-003-1 + W-003-4 as 2 parallel agents producing 2 commits with respective subjects. **First post-RC-17-codification parallelism use** — the discipline gap that surfaced in P1.5 (P1.5-4 bundled under P1.5-6) is now codifiable forward; junior reads `senior-planner.md` parallelism section + RC-17 amendment + dispatches accordingly.

### 🟢 G7 — Branch base benign; PR merge will be clean

Branch `claude/W-003-plan` cut from `a80cc7b` (W-003 brief commit; pre-codification). Main has since advanced to `6365cce` (RC-10 + RC-15 codifications at `reviews/README.md` extension + `dual-lens-r0b.md` new file). PR merge will perform 3-way merge across non-overlapping file additions; codifications stay on main post-merge.

Senior plan doesn't reference the codifications (correct — they're out of W-003 scope per brief). Impl team can consult codifications from main post-merge if relevant (W-003 reviews themselves may use RC-10 verdict-bump protocol).

### 🟢 G8 — Distance test discipline preserved

Plan §6: same-day end-to-end fine per RC-8 substrate canon (mechanical workflow refinement; no architectural inscription). Substrate pause recommended between W-003 close and P1.6 dispatch (per brief cross-reference). Senior preserves this.

---

## Cross-checks

- [x] Frontmatter contract followed; no `adr:` key (dogfoods W-002-2b no-ADR routing per brief; third use after W-002.5 + P1.5.5-original).
- [x] All 4 brief In-scope items addressed (G1).
- [x] All 4 brief Out-of-scope items respected (G2).
- [x] All 6 push-backs disposed substantively (G3).
- [x] All 3 self-discoveries surfaced (G4; though Y1 + Y2 flag the deferred-to-impl pattern).
- [x] No new ADR; ADR-014 path conditional (G5).
- [x] Parallelism rule applied per RC-17 codification (G6).
- [x] Branch base benign; PR merge will be clean (G7).
- [x] Distance test discipline preserved (G8).
- [x] No new constitutional tests (no new module; consistent with brief).
- [x] No new LLM imports in `workflow/`; existing constitutional test stays green.
- [ ] Y1 — `_has_commit_since` investigation scope; lean (α) senior pre-investigates at plan revision.
- [ ] Y2 — Subprocess helper extract decision; lean (α) senior pre-pins extract upfront.

---

## Push-back disposition table (architect-decision view)

All 6 substantively disposed; 3 self-discoveries surfaced (2 with Y-flag for deferred-to-impl pattern). Y1 + Y2 are the substantive items requiring architect routing.

---

## Net assessment

**Verdict: needs_architect.** Two 🟡 findings, both architect-routable; eight 🟢 confirmations document a tight plan.

The two 🟡 (Y1: `_has_commit_since` investigation deferred; Y2: subprocess helper extract deferred) share the same pattern: architectural-relevant decision deferred to junior at impl-time. Same shape as P1.5 R0-A Y1 (required-vs-default for Agent.applies_to). The codifiable lesson: **plan-stage decisions belong in plan; impl-stage decisions belong at impl; "I'll decide when I get there" is a smell.**

Architect picks routing on Y1 + Y2 separately (each has α / β / γ options). My lean: α on both (senior pre-investigates + senior pre-pins helper extraction).

**Plan is otherwise structurally sound.** Brief compliance complete; push-back disposition substantive; predicted self-discoveries surfaced; parallelism rule applied per RC-17 codification (first post-codification use); branch-base scenario benign (PR merge will be clean).

**Recommendation:** plan is revisable to clean in one revision pass absorbing Y1 + Y2. No 🔴; no return-to-senior-for-redraft warranted. Cross-family R0-B skip confirmed per brief + RC-15 narrowly-applied precedent.

## Captured for W-003 retro

- **"Decision deferred to junior at impl-time" pattern recurrence**: P1.5 R0-A Y1 first; W-003 Y1 + Y2 second + third. Three instances now; pattern worth surfacing as a candidate W-003 retro item for codification (e.g., `senior-planner.md` addendum: "plan §5 self-discoveries flagged as deferred-to-impl should be pre-resolved in plan revision unless the impl-time decision genuinely depends on impl-time data").
- **First post-RC-17-codification parallelism use**: G6 above. Track in retro whether the discipline holds (one atomic = one commit subject) on the W-003 impl branch.
- **Branch-base scenarios**: W-003-plan cut pre-codification + 3-way merge benign. Pattern likely to recur with parallel senior dispatches in future. Watch item: does any future cycle have a non-benign branch-base scenario (overlapping file edits)?
