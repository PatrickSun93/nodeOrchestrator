---
task_id: P5.1b
stage: senior-plan-vs-impl
actor: senior
date: "2026-06-10"
cycle: 2
verdict: clean
reviewed_branch: origin/claude/P5.1b-impl
reviewed_at: cf8680a
plan: docs/process/senior-plans/P5.1b.md
adr: ADR-042
routing_absorbed:
  - docs/process/reviews/P5.1b/architect-routing-on-plan.md   # Y1 interval-only / Y2 keep / N3 GC
  - docs/process/reviews/P5.1b/architect-routing-on-impl.md   # all-α, cycle-2 rework
supersedes: "cycle-1 plan-vs-impl (a7e485c, needs_architect: PVI-1 🟡 + PVI-2/3/4 🟢)"
findings: []   # all cycle-1 findings (PVI-1..4) resolved by the cycle-2 α rework
---

# P5.1b — senior plan-vs-impl (cycle 2, covers cycle 1)

Re-reviewed the cycle-2 α rework `cf8680a` (single commit on top of cycle-1 `a7e485c`)
against `docs/process/senior-plans/P5.1b.md`, ADR-042 (Accepted), and the architect's
impl-stage routing (`architect-routing-on-impl.md`: **all-α, one rework cycle**). Read on
`main` via `git show cf8680a` / `git diff` (no checkout — shared worktree). The cycle-2
diff is exactly `app.py` (3 hunks) + `tests/api/test_schedule_endpoints.py` (3 tests) +
`tests/api/test_schedule_sweeper.py` (3 tests) — 177 ins / 23 del, nothing else.

**Bottom line:** all **7 routed α fixes** (A1/PVI-1 must-fix + A2/A3/Y3/A4/A5/A6) are
**implemented faithfully and exhaustively**, each with a **non-vacuous test**, with **no
plan-external expansion** and the **spine still byte-frozen**. The four cycle-1 findings
(PVI-1 🟡, PVI-2/3/4 🟢) are **all closed**. **Verdict → `clean`.**

This file **supersedes the cycle-1 review** (`needs_architect`); the cycle-1 content
remains in git history at `a7e485c` for the audit trail.

---

## Cycle-1 findings — resolution ledger

| Cycle-1 finding | Routed | Cycle-2 fix | Status |
|---|---|---|---|
| **PVI-1 / A1** 🟡 must-fix — DELETE/PATCH bind owner-check to URL pipeline, not the schedule's parent (cross-pipeline IDOR) | α | IDOR guard added to **both** verbs + 2 cross-pipeline 404 tests | ✅ **closed** |
| **PVI-3 / A3** 🟢 — missing-parent act does not advance `next_fire` (log churn every tick) | α | claim restructured **before** the pipeline-state gate → orphan advances + test | ✅ **closed** |
| **PVI-4 / A5** 🟢 — GET on missing pipeline returns `[]` (verb inconsistency) | α | GET now raises 404 + test | ✅ **closed** |
| **PVI-2 / A6** 🟢 — partial index beyond "DDL exactly D2 columns" | α (ratify-as-correct) | confirmed in-spirit (realizes D2 "indexable"); no behavioural change | ✅ **closed** |

Plus the routing's two r0b/R0-A-originated items not in my cycle-1 file:

| Finding | Routed | Cycle-2 fix | Status |
|---|---|---|---|
| **A2 / Y1** 🟡 — `_schedule_act_on_writer` docstring drifts from code | α | docstring rewritten to the new always-claim-then-gate order | ✅ |
| **Y3** 🟡 — single `try` could discard a successful run if `create_pipeline_run` throws | α | **split try** (run in one, create in a nested try/except that warns, never re-raises) + mock test | ✅ |
| **A4** 🟢→α — spine-isolation AST test only covered `_schedule_sweeper` | α | added the mirror AST test for `_schedule_act_on_writer` (the higher-risk act fn) | ✅ |

---

## Per-fix faithfulness (cycle-2 diff)

### A1 / PVI-1 — cross-pipeline IDOR guard (must-fix) — ✅ faithful, non-vacuous

- **DELETE** (`app.py:2104-2107`) and **PATCH** (`app.py:2153-2156`) both gain, immediately
  after the `get_schedule` fetch and the not-None 404, the guard
  `if sched.pipeline_id != pipeline_id: raise HTTPException(404, …)` — exactly the routed
  α-fix and the natural disposition I surfaced in cycle-1. The mutation is now bound to the
  schedule's **actual parent**, not the URL pipeline.
- GET was already safe (it scopes via `list_schedules_for_pipeline(pipeline_id)` and never
  fetches by global `schedule_id`); POST creates under the URL pipeline — both inherently
  consistent. No guard needed there, and none was (wrongly) added. Correct scoping of the fix.
- **Tests non-vacuous** (`test_delete_schedule_cross_pipeline_idor_404`,
  `test_patch_schedule_cross_pipeline_idor_404`): both create `pipe_self` + `pipe_other`
  (same owner — isolates the *new* parent-binding guard from the pre-existing 403 owner
  path), create the schedule under `pipe_other`, then hit `…/{pipe_self}/schedules/{sid_other}`
  and assert **404**. With the guard removed, `get_schedule` returns the row and the verb
  proceeds (200/204) → the assertion fails. **Fail-on-revert holds.** Testing with a single
  owner is the *cleaner* isolation of the binding bug (it does not lean on the ownership
  difference), so the choice is correct, not a weakening.

### A2 / Y1 — docstring truth — ✅ faithful

- The `_schedule_act_on_writer` docstring is rewritten so steps 2–5 describe the **new**
  control flow: step 2 fetches the pipeline (state check deferred), step 3 **always** claims
  (`next_fire` advance) regardless of pipeline state, step 4 is the missing/disabled gate
  (next_fire already advanced), step 5 is the split run/create. This now matches the code
  produced by A3 — the docstring and the body agree. (The routing's literal phrasing
  predated A3; the junior correctly reconciled both into the post-A3 truth rather than
  documenting a state the code no longer has.)

### A3 / Y2 / PVI-3 — orphan advances `next_fire` — ✅ faithful, non-vacuous

- The claim (`update_schedule_next_fire(…, compute_next_fire(...))`) is moved **above** the
  pipeline-state gate; the `pipeline is None` branch now `return`s **after** the advance, as
  does the `not pipeline.enabled` branch. An orphaned (deleted-pipeline) schedule is therefore
  re-discovered only after the next interval, not every tick — the log-churn PVI-3 flagged is
  gone, and the behaviour is now consistent with the disabled path.
- Crash-safety preserved: claim still happens **before** any run, so the double-fire guard is
  unaffected (the existing `test_act_double_fire_guard` is untouched).
- **Test non-vacuous** (`test_act_missing_pipeline_advances_next_fire_no_run`): deletes the
  pipeline row, runs the act, asserts `next_fire` advanced **and** `router.call.call_count == 0`.
  Revert the claim-before-gate reordering → `next_fire` would not advance → assertion fails.

### Y3 — split try, never discard a successful run — ✅ faithful, non-vacuous

- `run_pipeline` now sits in its **own** try (on failure: `_log.error` + `return`; `next_fire`
  already advanced so the failed run is not retried until next interval).
  `create_pipeline_run` sits in a **separate nested** try/except that logs a **warning**
  ("run %s succeeded") and does **not** re-raise — the successful run is never lost to a
  bookkeeping-row write error. Exactly the routed split.
- **Vacuous-test trap checked and cleared:** the test patches
  `orchestrator.pipeline.store.create_pipeline_run`, while `app.py` imports that symbol via a
  **function-local** `from orchestrator.pipeline.store import (create_pipeline_run, …)`
  (`app.py:623-624`) executed on every call. Because the local import re-resolves the module
  attribute at call time, the patch (active around the `_schedule_act_on_writer` call) **does**
  bind the mocked object — the simulated DB failure genuinely fires. The test then asserts the
  call does not raise and `next_fire` is still advanced. **Non-vacuous** (this is the P5.1a-cyc2
  vacuous-mock class; it does not recur here).
- Minor honesty note (🟢, not a finding): after a caught `create_pipeline_run` failure, control
  falls through to the unconditional terminal `_log.info("… run … ok")`. The "ok" refers to
  `run_pipeline` success, which is **truthful** (the run did succeed; only the side-table row
  failed, separately warned). Both facts are logged — acceptable, no drift.

### A4 — spine-isolation AST test for the act fn — ✅ faithful

- `test_schedule_act_on_writer_does_not_call_countdown_spine` mirrors the existing sweeper
  test: `ast.parse(inspect.getsource(_schedule_act_on_writer))`, collect `ast.Call` nodes whose
  `func` is an `ast.Name`, assert none of `_countdown_sweeper` / `_discover_expired_pendings` /
  `_writer_approve_helper` appear. The forbidden symbols are module-level functions invoked as
  bare names, so the `ast.Name`-only scope is **correct** (no `ast.Attribute` false-negative
  gap for these), and the AST approach (vs substring) avoids docstring-mention false positives.

### A5 / PVI-4 — GET verb consistency — ✅ faithful, non-vacuous

- The GET `_read()` helper now `raise HTTPException(404, …)` on a missing pipeline instead of
  `return []`, matching POST/DELETE/PATCH. `test_list_schedules_missing_pipeline_404` asserts
  404 on `nonexistent_pipe` — fails if the `return []` is restored.

### A6 / PVI-2 — partial index ratified — ✅ no change, correct

- No diff (correctly): the routing dispositioned A6 as "ratified as correct — additive,
  in-spirit, no behavioural change." `idx_pipeline_schedules_due` realizes the explicit
  ADR-042 D2 "indexable `WHERE enabled=1 AND next_fire <= ?`" intent. Confirmed kept; nothing
  to rewrite.

---

## Constitutional carry-forward (Lens B) — still all clear in cycle 2

The cycle-2 diff touches **only** `_schedule_act_on_writer` and the two endpoint handlers in
`app.py`, plus the two test files. None of the spine symbols appear in the diff:

| Invariant | Result |
|---|---|
| `run_pipeline` byte-identical | ✅ `runner.py` absent from the cycle-2 diffstat |
| `_countdown_sweeper` / `_discover_expired_pendings` / `_writer_approve_helper` byte-untouched | ✅ no hunk touches them; the new act fn calls **none** of them (now AST-asserted, A4) |
| `countdown_auto_fire=None` reversible-only preserved | ✅ unchanged |
| gate (`score`/`decide_tier`/`emit_gate_decision`) + `_execute_local_call` untouched | ✅ absent from the diff |
| No new routing `LLMPurpose` | ✅ the diff adds no `LLMPurpose`; the only LLM in a scheduled run is the unchanged `run_pipeline` content-gen |
| scheduler-OFF ⇒ byte-identical to P5.1a | ✅ all new work still gated behind `pipeline_scheduler.enabled`; default OFF unchanged |

`RB-PIPELINE-SCHED` remains inscribed honestly; cron stays fully deferred (no stub path
leaked in the rework).

---

## Plan-external expansion / omission scan (cycle 2)

- **Omissions:** none — every one of the 7 routed α items is present (A6 correctly as a
  no-op confirmation).
- **Expansions:** none — the diff is confined to the three files the routing implies, and
  every hunk maps 1:1 to a routed finding. No opportunistic bundling, no defensive hardening
  under deferral language, no cron stub.

---

## Verdict

**`clean`.** The cycle-2 α rework faithfully and completely resolves the must-fix IDOR
(A1/PVI-1) and the full robustness/honesty cluster (A2/A3/Y3/A4/A5/A6), each with a
non-vacuous, fail-on-revert test; the spine is byte-frozen; no plan-external expansion. All
cycle-1 findings are closed and nothing new surfaced.

Per ADR-008 Amendment 1 (Route B, W-005), state advances to `awaiting_R0_A` regardless of
verdict; this `clean` frontmatter signals no senior-side plan-vs-impl drift remains for the
cycle-2 external review round.
