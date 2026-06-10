---
task_id: P5.1b
stage: impl
review: R0-B (cross-family, impl-stage, cycle-2 re-review)
lens: runtime-integration + failure-mode (dual-lens-r0b.md §contrarian)
reviewer: cross-family (DeepSeek)
verdict: clean
verdict_history:
  - needs_architect   # cycle-1: 3 🟡 (Y1 docstring, Y2 orphan-logloop, Y3 audit-gap); missed A1 IDOR
  - clean             # cycle-2: all 6 α items resolved; 0 🔴, 0 🟡
date: "2026-06-10"
commit_reviewed: cf8680a (origin/claude/P5.1b-impl, cycle-2 α rework)
previous_commit: a7e485c (cycle-1, my prior review)
gates:
  ruff: pass (All checks passed!)
  mypy: pass (Success: no issues found in 180 source files)
  pytest: pass (full suite, exit 0; 1 pre-existing starlette + 1 pre-existing hung-DNS thread warning)
artifacts_reviewed:
  - docs/process/reviews/P5.1b/architect-routing-on-impl.md (α disposition, cycle-1→2)
  - docs/process/reviews/P5.1b/R0-A.md (cycle-1, A1..A6)
  - docs/process/reviews/P5.1b/plan-vs-impl.md (cycle-1, PVI-1..4)
  - docs/process/reviews/P5.1b/R0-B.md (cycle-1, my own Y1/Y2/Y3)
  - git diff a7e485c..origin/claude/P5.1b-impl (cycle-2 rework, 3 files, +177/-23)
  - git diff origin/main...origin/claude/P5.1b-impl (full branch, 15 files, +2150/-16)
  - src/orchestrator/api/app.py (_schedule_act_on_writer, _delete_schedule, _patch_schedule, _list_schedules)
  - tests/api/test_schedule_endpoints.py (new tests)
  - tests/api/test_schedule_sweeper.py (new tests)
---

# R0-B impl-stage — P5.1b cycle-2 re-review

Cross-family re-review of `origin/claude/P5.1b-impl` @ `cf8680a` (cycle-2 α rework on
PR #68). In cycle-1 (@ `a7e485c`), I returned `needs_architect` with 3 🟡 (Y1 docstring,
Y2 orphan-logloop, Y3 audit-gap) but **missed A1** (cross-pipeline IDOR on DELETE/PATCH),
which was caught independently by senior (PVI-1) and R0-A (A1). The architect routed
**all-α** across 6 items (including all 3 of my Y* + A4/A5/A6 from R0-A). This cycle-2
review verifies the rework against that routing, with the **hard-won lesson from cycle-1**:
authorization surface requires tracing the data-flow, not just the gate — `sched.pipeline_id`
≠ URL `pipeline_id` when they differ, and both the code and the tests must probe that case.

**Bottom line: all 6 α items are correctly resolved. 0 🔴, 0 🟡. Verdict: `clean`.**

---

## Lens preamble

This is a true cross-family R0-B (DeepSeek). The cross-family structural advantage is
tracing runtime-integration failure modes: "what happens when this call fails at 3am?"
across module boundaries. For this cycle-2 re-review, my lens is specifically:

1. **Authorization correctness** — the A1 IDOR was a data-flow error (gate binds to URL
   pipeline, mutation targets a globally-resolved schedule); I apply the same data-flow trace
   to verify the fix is complete (both verbs, both the guard and the tests).
2. **My own cycle-1 blind spots** — Y1 (docstring), Y2 (orphan loop), Y3 (audit gap) — are
   they genuinely fixed, or did the rework introduce new failure modes?
3. **Cross-family invariants from my cycle-1 verified table** — does the rework preserve
   claim-before-run, boot skip-to-next, spine byte-frozen, clean teardown,
   `countdown_auto_fire=None`, and scheduled-run owner attribution?

---

## Per-α verification

### A1 / PVI-1 (🟡→✅) — Cross-pipeline IDOR on DELETE/PATCH

**Cycle-1 finding:** `_delete_schedule` and `_patch_schedule` evaluated the owner gate
against the URL `pipeline_id`, then fetched + mutated the schedule by its global
`schedule_id` with no check that `sched.pipeline_id == pipeline_id`.

**Cycle-2 fix (verified):**

- `_delete_schedule` (`app.py:2103-2105`): after `get_schedule(writer_conn, schedule_id)`
  and the `sched is None → 404` guard, added:
  ```python
  if sched.pipeline_id != pipeline_id:
      raise HTTPException(status_code=404, detail=f"schedule {schedule_id!r} not found")
  ```
  The 404 detail mirrors the "not found" message — no cross-pipeline information leak.

- `_patch_schedule` (`app.py:2149-2151`): identical guard, same placement.

- **Test `test_delete_schedule_cross_pipeline_idor_404`** (`test_schedule_endpoints.py:272-285`):
  creates two pipelines (both owned by _USER_A), creates schedule under `pipe_other`,
  calls `DELETE /pipelines/{pipe_self}/schedules/{sid_other}` → asserts 404. Correct:
  same-owner cross-pipeline is the minimal case (no 403/404 ambiguity).

- **Test `test_patch_schedule_cross_pipeline_idor_404`** (`test_schedule_endpoints.py:318-331`):
  identical pattern for PATCH with `{"enabled": False}` → asserts 404.

**Cross-family assessment:** The guard is correctly placed *after* `get_pipeline` owner
check + `get_schedule` existence check. Both tests probe the cross-pipeline case with the
same owner (isolation from the 403 path). The 404 is the correct verb — the schedule does
not belong to this pipeline, so "not found" in this pipeline's namespace. **Fixed.**

> **Lesson applied.** Cycle-1 tests reused `pipe_id` for both the URL and the schedule
> parent, so the surface passed. The cycle-2 tests create two distinct pipelines and
> cross them. The data-flow trace (`sched.pipeline_id` ≠ URL `pipeline_id`) is now
> covered by both code and test. I missed this in cycle-1; the fix is complete.

### A2 / Y1 (🟡→✅) — Docstring/code mismatch on missing-pipeline path

**Cycle-1 finding:** The docstring claimed step 2 "still advance next_fire" for
missing-pipeline, but the code returned without advancing.

**Cycle-2 fix (verified):** The `_schedule_act_on_writer` docstring now reads:

```
Order (D4):
  1. Re-read schedule on writer conn; skip if not still due+enabled.
  2. Fetch parent pipeline (state check deferred until after claim).
  3. Claim: advance next_fire BEFORE run (skip-to-next; crash-safe).
     Always claim regardless of pipeline state — orphan/disabled schedules
     are re-due only after the next interval, not every tick.
  4. Skip run if pipeline missing (orphan) or disabled; next_fire already
     advanced in step 3 so a restored/re-enabled pipeline resumes cleanly.
  5. Run: run_pipeline (one try) → create_pipeline_run (nested try/except
     so a log-index failure does not discard the successful run result).
```

The docstring now accurately reflects the code: step 2 only *fetches* (defers the check),
step 3 claims unconditionally, step 4 gates on pipeline state after claim. **Fixed.**

### A3 / Y2 / PVI-3 (🟡→✅) — Orphan schedule perpetual re-discovery

**Cycle-1 finding:** When the parent pipeline was deleted, `next_fire` was not advanced,
so the orphan schedule was re-discovered + warn-logged every sweep tick forever.

**Cycle-2 fix (verified):**

- The `pipeline = get_pipeline(writer_conn, schedule.pipeline_id)` call moved **before**
  the claim (step 2), but the `if pipeline is None` check moved **after** the claim
  (step 4). Result: `next_fire` is always advanced (step 3), then the orphan check
  returns without running.

- **Test `test_act_missing_pipeline_advances_next_fire_no_run`**
  (`test_schedule_sweeper.py:281-299`): creates pipeline + schedule, DELETEs the pipeline
  row, calls `_schedule_act_on_writer`, asserts `next_fire > old_next_fire` AND
  `router.call.call_count == 0`. The delete-before-act order correctly models "pipeline
  deleted between discovery and act" (the worst-case TOCTOU window).

**Cross-family assessment:** The advance-on-missing behavior is now symmetric with the
disabled-pipeline path — both advance `next_fire` before skipping the run. An orphaned
schedule is re-discovered only after the next interval, breaking the perpetual log loop.
The test correctly models the race window. **Fixed.**

### Y3 (🟡→✅) — Split-try: `create_pipeline_run` failure after successful `run_pipeline`

**Cycle-1 finding:** `run_pipeline` and `create_pipeline_run` shared a single `try/except`,
so a `create_pipeline_run` failure after a successful `run_pipeline` discarded the
successful run result and left no audit trail.

**Cycle-2 fix (verified):**

- Outer `try`: wraps only `run_pipeline(...)`. On exception → `_log.error(...,
  exc_info=True)` + `return` (no `create_pipeline_run` called — correct: if the run
  itself failed, there is no `result` to index).

- Nested `try`: wraps only `create_pipeline_run(...)`. On exception → `_log.warning(...)`
  (not error — the run succeeded, only the index write failed). The warning message
  includes `result.run_id` so the orphaned run can be correlated.

- The `_log.info("run %s ... ok/failed")` line runs *after* both try blocks — it always
  fires when `run_pipeline` succeeds, regardless of `create_pipeline_run` outcome.

- **Test `test_act_create_run_fails_after_successful_run_does_not_raise`**
  (`test_schedule_sweeper.py:395-417`): mocks `create_pipeline_run` to raise, calls act,
  asserts no exception propagates AND `next_fire` was advanced. Correct.

**Cross-family assessment:** The split-try is correctly structured. The `_log.warning`
(rather than `_log.error`) on `create_pipeline_run` failure is the right severity —
the run's events are in the room (reversible output, the source of truth); the
`pipeline_runs` table is an index, not the truth. The run result is never lost.
**Fixed.**

> **Residual note (not a finding):** If `create_pipeline_run` fails, the operator has
> no `pipeline_runs` row to discover the run via the GET index — but the room events
> exist and are reachable via the room history. This is a known accepted gap (same
> shape as `_countdown_sweeper`'s error path) and was N3-acknowledged in ADR-042
> Consequences. The split-try makes the gap explicit and non-destructive; no further
> action needed.

### A4 (🟢→✅) — Spine-isolation AST test extended to `_schedule_act_on_writer`

**Cycle-1 finding:** The AST test only covered `_schedule_sweeper`, not the
higher-risk `_schedule_act_on_writer` function that does the actual DB + run work.

**Cycle-2 fix (verified):** New test `test_schedule_act_on_writer_does_not_call_countdown_spine`
(`test_schedule_sweeper.py:470-499`):
- Uses `inspect.getsource(_schedule_act_on_writer)` + `ast.parse`
- Walks all `ast.Call` nodes and collects `func.id` names
- Asserts none of `{_countdown_sweeper, _discover_expired_pendings, _writer_approve_helper}`
  appear in the call sites
- Uses `ast.Name` check (not substring) so docstring mentions don't trigger false positives

**Cross-family assessment:** The test is well-constructed — AST-level verification is
stronger than grep (no false positives from comments/docstrings) and makes the
spine-isolation invariant fail-on-revert. The existing `_schedule_sweeper` test +
this new `_schedule_act_on_writer` test together cover the full call chain.
**Fixed.**

### A5 / PVI-4 (🟢→✅) — GET on missing pipeline returns 404

**Cycle-1 finding:** `_list_schedules` returned `[]` (200) for a missing pipeline,
while POST/DELETE/PATCH returned 404.

**Cycle-2 fix (verified):** `_list_schedules` (`app.py:2059`): missing pipeline now
raises `HTTPException(status_code=404, detail=f"pipeline {pipeline_id!r} not found")`.
Test `test_list_schedules_missing_pipeline_404` asserts 404. Verb-consistent with
the rest of the endpoint surface. **Fixed.**

### A6 / PVI-2 (🟢→✅) — Partial index confirmed

**Architect routing:** "additive, in-spirit; confirm/keep, no behavioural change."
No code change needed or made. The partial index `idx_pipeline_schedules_due` remains
as-is. **Confirmed.**

---

## Cross-family invariant re-verification

All invariants from my cycle-1 verified table (§Verified invariants) re-checked
against the cycle-2 diff — the rework touches only `_schedule_act_on_writer` (internal
reordering + split-try), the endpoint guards, and tests. No invariant is weakened:

| Invariant | Cycle-2 status | Check |
|---|---|---|
| Claim-before-run double-fire guard | ✅ preserved | Step 3 (claim) still before step 5 (run); `test_act_double_fire_guard` passes |
| Boot re-arm advances past-due without running | ✅ preserved | `_rearm_schedules_on_boot` untouched by cycle-2 diff |
| Skip-to-next: missed fires dropped | ✅ preserved | `compute_next_fire(..., now_ms_val)` at claim; boot re-arm uses `now_ms()` |
| 3am restart: no burst, no double-fire | ✅ preserved | Boot re-arm before sweeper task created; claim-before-run unchanged |
| `countdown_auto_fire=None` preserved | ✅ preserved | `runner.py` still absent from diffstat; scheduler does not pass the kwarg |
| Scheduled run attributed to config-time owner | ✅ preserved | `owner_user_id=schedule.owner_user_id` passed to both `run_pipeline` and `create_pipeline_run` |
| `pipelines.enabled=0` → advance `next_fire`, skip run | ✅ preserved | Claim (step 3) before disabled check (step 4) |
| `schedule.enabled=0` → not discovered | ✅ preserved | `list_due_schedules` WHERE clause unchanged |
| discover-on-reader / act-on-writer | ✅ preserved | Reader/executor assignments unchanged |
| Second background task clean teardown | ✅ preserved | Lifespan teardown unchanged: `cancel()` + `suppress(CancelledError)` + `await` before `ctx.shutdown()` |
| Spine byte-frozen | ✅ preserved | `_countdown_sweeper` / `_discover_expired_pendings` / `_writer_approve_helper` untouched; gate zero-diff |
| No new `LLMPurpose` | ✅ preserved | Diff grep clean |
| Scheduler OFF → byte-identical to P5.1a | ✅ preserved | `config/pipeline.yaml` default `enabled: false` unchanged |

---

## New-issue sweep (cross-family lens on the rework)

I traced the reworked `_schedule_act_on_writer` for new failure modes:

1. **`get_pipeline` raising mid-act (DB error).** The `get_pipeline(writer_conn,
   schedule.pipeline_id)` call in step 2 occurs *before* the claim (step 3). If it
   raises (DB I/O error), `next_fire` is NOT advanced, the exception propagates to
   `_schedule_sweeper`'s `except Exception: log + continue`, and the schedule stays
   due for the next tick. **Correct posture** — don't advance the timer if we can't
   even check pipeline state.

2. **`compute_next_fire` raising on a corrupt schedule.** If a schedule's `kind` is
   somehow invalid (should be impossible — cron/unknown rejected at create time with
   422), the `ValueError`/`NotImplementedError` propagates before `next_fire` is
   advanced. The sweeper logs + continues; the corrupt schedule is re-discovered next
   tick. This is an acceptable fail-safe — a corrupt schedule should not be silently
   advanced past.

3. **`run_pipeline` raises → `next_fire` already advanced.** This is the intentional
   skip-to-next posture (ADR-042 D4/D5): claim before run so a crash or exception
   mid-run doesn't double-fire on restart. The schedule skips this tick and fires on
   the next interval. Consistent with the countdown sweeper's error-continue pattern.

4. **`create_pipeline_run` raises → info log still fires.** The `_log.info("run %s
   ... ok/failed")` line runs after the nested try/except, so every successful
   `run_pipeline` is logged regardless of index-write outcome. Correct.

No new 🔴 or 🟡 found.

---

## Gate run (independent, isolated worktree)

Performed in a detached worktree @ `cf8680a` with `uv sync --all-extras`:

| Gate | Result |
|---|---|
| `ruff check src/ tests/` | All checks passed! |
| `mypy` (files=src,tests) | Success: no issues found in 180 source files |
| `pytest` (full suite) | Exit 0; 1 pre-existing starlette deprecation + 1 pre-existing hung-DNS thread warning (both unrelated) |

No new gate regressions. The cycle-1 env-artifact (`untyped-decorator` without `--all-extras`)
does not reproduce — with FastAPI installed via `--all-extras`, mypy is clean.

---

## Synthesis

The cycle-2 rework is **surgically precise**: 6 α items resolved across 3 files, +177/-23
lines, zero unintended changes. The A1 IDOR fix (the material finding, missed by me in
cycle-1) is correctly implemented with data-flow guards on both DELETE and PATCH, backed
by cross-pipeline tests that probe the exact case the cycle-1 tests missed. My three Y*
items are all genuinely fixed: the docstring matches the code, the orphan loop is broken
by advancing `next_fire` on the missing-pipeline path, and the split-try preserves the
run result when `create_pipeline_run` fails. The A4/A5/A6 🟢 items are correctly addressed.

The constitutional crux — claim-before-run, boot skip-to-next, spine byte-frozen,
`countdown_auto_fire=None` preservation, clean teardown — holds unchanged across the
rework. The scheduler remains a correct second caller of the byte-unchanged `run_pipeline`.

**Cycle-1 lesson applied.** The A1 miss was a failure to trace the data flow across the
owner gate: the gate bound to the URL pipeline, the mutation targeted a globally-resolved
schedule, and no test crossed them. The cycle-2 fix + tests close this gap. The cross-family
lens adds value here not by finding new bugs but by verifying that the prior miss is
completely closed — tracing `sched.pipeline_id` through both verbs and both test cases.

**0 🔴, 0 🟡. Verdict: `clean`.**
