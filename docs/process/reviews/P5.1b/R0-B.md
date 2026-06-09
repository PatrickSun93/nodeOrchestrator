---
task_id: P5.1b
stage: impl
review: R0-B (cross-family, impl-stage)
lens: runtime-integration + failure-mode (dual-lens-r0b.md §contrarian)
reviewer: cross-family (DeepSeek)
verdict: needs_architect
verdict_history:
  - needs_architect   # 3 🟡 surfaced; no 🔴
date: "2026-06-09"
commit_reviewed: a7e485c (origin/claude/P5.1b-impl, 6 atomics)
gates:
  ruff: pass
  mypy: pass (4 new untyped-decorator, same pre-existing class; no novel errors)
  pytest: 2418 passed, 0 failures (full suite)
artifacts_reviewed:
  - docs/process/senior-plans/P5.1b.md
  - docs/decisions/ADR-042-recurring-pipeline-scheduler.md (Accepted)
  - docs/process/reviews/P5.1b/architect-routing-on-plan.md (Y1/Y2/N3 routed)
  - docs/process/reviews/P5.1b/R0-A-on-plan.md
  - docs/process/reviews/P5.1b/plan-vs-impl.md
  - src/orchestrator/pipeline/schedule.py (new)
  - src/orchestrator/pipeline/config.py (new)
  - src/orchestrator/pipeline/schema.py (modified)
  - src/orchestrator/pipeline/store.py (modified)
  - src/orchestrator/api/app.py (modified, +462)
  - config/pipeline.yaml (new)
  - docs/decisions/ADR-041/040/025 (amended, P5.1b-6)
  - tests/pipeline/test_schedule.py (new, 15 tests)
  - tests/pipeline/test_schedule_store.py (new, 15 tests)
  - tests/pipeline/test_scheduler_config.py (new, 9 tests)
  - tests/api/test_schedule_sweeper.py (new, 13 tests)
  - tests/api/test_schedule_endpoints.py (new, 12 tests)
---

# R0-B impl-stage — P5.1b (recurring pipeline scheduler)

Cross-family impl-stage review of `origin/claude/P5.1b-impl` @ `a7e485c` (6 atomics,
+1996/−16 over 15 files). Lens: **runtime-integration + failure-mode** per
`dual-lens-r0b.md` §contrarian — the cross-family structural advantage is tracing
"what happens when this call fails at 3am?" across module boundaries.

**All 10 user-specified invariants verified.** Details in §Verified below.

---

## Verdict: `needs_architect`

0 🔴 blocking, 3 🟡 for architect routing. The impl is faithful to the plan, ADR-042,
and the architect-routed Y1/Y2/N3. The load-bearing safety invariants (claim-before-run
double-fire guard, boot re-arm skip-to-next, countdown_auto_fire=None preservation,
spine byte-frozen, discover-on-reader/act-on-writer, clean teardown) are all correctly
implemented and tested with fail-on-revert discipline. The 3 🟡 are genuine
runtime-behavior edge cases worth the architect's attention, none safety-critical.

---

## Lens preamble

This is a true cross-family R0-B. The plan-stage R0-B-on-plan was already clean (zero
findings against plan + ADR-042). The impl-stage cross-family value is tracing the
**actual code paths** for failure modes the in-family reviewers may under-weight:
restart timing, stale-reader TOCTOU, writer-executor serialization, orphan-data loops,
and error-path audit gaps. The plan-stage dual-lens already caught the spec-level
concerns (Y1 cron deferred, Y2 endpoints kept, N3 acknowledged). My job is: does the
**running code** hold the invariants the plan inscribed?

**Short answer: yes.** The load-bearing crux — claim-before-run, boot skip-to-next,
spine byte-frozen, `countdown_auto_fire=None` inheritance — is correct and tested.
Three 🟡 surface edge cases the architect should route; none are 🔴.

---

## 🔴 Blocking — none

No safety or correctness blocking issues found.

---

## 🟡 Needs architect routing

### Y1 — `_schedule_act_on_writer` docstring/code mismatch on missing-pipeline path

- **File/line:** `src/orchestrator/api/app.py`, `_schedule_act_on_writer` docstring
  (step 2) vs body (pipeline-missing check)
- **Claim:** The docstring says step 2 handles "pipeline missing or disabled (still
  advance next_fire so re-enable resumes cleanly)". The code does NOT advance
  `next_fire` when the pipeline is missing — it returns immediately (line ~"pipeline
  … missing, skip" + `return`). The code behavior is the **more defensible one**
  (advancing for a non-existent pipeline is pointless), but the docstring claims
  otherwise.
- **Severity:** 🟡 — documentation-only (the code is correct); could mislead a future
  maintainer into thinking advance-on-missing is implemented.
- **Suggested investigation:** Fix the docstring to read: "skip if pipeline missing (no
  advance); skip run if pipeline disabled (advance next_fire so re-enable resumes
  cleanly)."

### Y2 — Orphan schedules (pipeline deleted, schedule survives) cause perpetual warning-log loop

- **File/line:** `src/orchestrator/api/app.py`, `_schedule_act_on_writer` ~pipeline-missing
  branch
- **Claim:** When a pipeline is deleted but its schedule persists, the sweeper enters
  a perpetual loop:
  1. Reader discovers the schedule (stale `next_fire` in the past)
  2. Act re-reads on writer → pipeline missing → `_log.warning` → **returns without
     advancing `next_fire`**
  3. `next_fire` stays in the past → re-discovered on the next sweep tick
  4. Repeats every `sweep_interval_s` (default 60s), logging a warning each time,
     forever, until the schedule is manually deleted
  Boot re-arm briefly advances the schedule past current time, but once it becomes due
  again, the loop restarts. There is no self-healing path — the schedule must be
  manually deleted by the operator, but the operator may not be watching warning logs.
- **Severity:** 🟡 — resource/noise, not safety (no runs fire, no data corruption).
  Log-spam at ~1 warning/minute per orphan schedule; CPU cost negligible (a SELECT +
  return). The operational concern is that a genuine warning (e.g., a different
  schedule hitting an error) is drowned in "pipeline … missing, skip" noise.
- **Suggested investigation:** Two options, architect's call:
  (a) Advance `next_fire` even for missing-pipeline schedules (consistent with the
      disabled-pipeline path) — breaks the loop; schedule is re-discovered only after
      the next interval elapses, giving the operator time to notice and clean up
  (b) Auto-delete orphan schedules (check at create/delete time is simpler:
      `ON DELETE CASCADE`-style cleanup when a pipeline is deleted — out of P5.1b
      scope since pipeline-delete is not in the endpoint surface)
  (a) is the minimal fix, consistent with the disabled-pipeline behavior.

### Y3 — `create_pipeline_run` failure after successful `run_pipeline` leaves audit gap

- **File/line:** `src/orchestrator/api/app.py`, `_schedule_act_on_writer` try/except
  block (step 4)
- **Claim:** `run_pipeline` and `create_pipeline_run` share a single `try/except`.
  If `run_pipeline` succeeds (room created, events appended) but `create_pipeline_run`
  fails (e.g., transient DB I/O error), `next_fire` has already been advanced (step 3)
  and the `except` logs the error — but no `pipeline_runs` index row exists for a run
  that actually happened. The run's events are in the room (reversible output), so this
  is **data-completeness, not safety**.
- **Severity:** 🟡 — audit-trail gap, not safety. The `pipeline_runs` table is an
  index, not a source of truth (the room events are the truth). Consistent with the
  countdown sweeper's error-handling pattern (same single-try-block shape in
  `_countdown_sweeper`). Worth surfacing because the headless context means no human
  is watching for "run not recorded" — a manual `/run` user would notice the missing
  response; a scheduled run's audit gap is silent.
- **Suggested investigation:** Split the try block: `run_pipeline` in one try,
  `create_pipeline_run` in a nested try/except that logs but does not lose the
  successful run result. Or note in ADR-042 consequences that this is a known
  accepted gap (consistent with ADR-040's sweeper pattern).

---

## 🟢 Observations (non-findings)

- **N1 — Interval drift from claim-time `now_ms_val` is correct and documented.**
  `compute_next_fire` uses the sweep tick's `now_ms_val`, not the actual
  writer-processing time. The drift (up to `sweep_interval_s` + writer queueing per
  fire) is the architect-ratified price of skip-to-next (ADR-042 D3/D4, plan N2).
  The `schedule.py` module docstring explicitly documents this.

- **N2 — All schedule acts in one sweep tick share the same `now_ms_val`.**
  Captured once at loop start, reused for all due schedules in that tick. Consistent
  with the documented drift posture; each schedule's `next_fire` is computed relative
  to the same epoch.

- **N3 — Sweeper serializes acts one-at-a-time via `await` in the for-loop.**
  `for schedule_id in due_ids: await loop.run_in_executor(writer_executor, …)` —
  each act completes before the next starts. Combined with `writer_executor(max_workers=1)`,
  this correctly serializes schedule acts against each other and against countdown
  sweeper acts + manual `/run`. The writer-side authoritative re-read (step 1) is the
  TOCTOU guard — the second act in a stale-reader double-discovery always sees the
  first act's advanced `next_fire`.

- **N4 — `_rearm_schedules_on_boot` correctly uses the writer connection.**
  Runs on `writer_executor` via `ctx.writer_store.conn`. The `list_due_schedules`
  call uses the writer connection (not the reader), which is correct for an
  authoritative boot-time mutation.

---

## Verified invariants (all confirmed)

### Runtime safety (Lens A)

| Invariant | How verified | Status |
|---|---|---|
| Claim-before-run double-fire guard | `_schedule_act_on_writer` step 3 advances `next_fire` before step 4's `run_pipeline`; `test_act_double_fire_guard` asserts second act with same `now_ms` sees advanced `next_fire` and skips | ✅ |
| Boot re-arm advances past-due without running | `_rearm_schedules_on_boot` iterates past-due schedules, calls `compute_next_fire` + `update_schedule_next_fire` only; `test_rearm_advances_past_due_without_running` asserts `router.call.call_count == 0` | ✅ |
| Skip-to-next: missed fires dropped, never backfilled | Boot re-arm uses `compute_next_fire(kind, expr, now)` (current time), not the old `next_fire`; act does the same at claim time. Both compute from `now`, not from `old_next_fire` | ✅ |
| 3am restart: no burst, no double-fire | Boot re-arm runs before sweeper task created → all past-due schedules advanced to future → first sweeper tick sees zero due schedules. Crash mid-run: `next_fire` already advanced → on reboot, schedule is in the future → untouched by re-arm | ✅ |
| `countdown_auto_fire=None` preserved for scheduled runs | `runner.py` byte-unchanged (zero diff); `countdown_auto_fire=None` at both `process_tool_calls` call sites (`runner.py:153,223`); the scheduler is a caller, does not edit the runner | ✅ |
| Scheduled run attributed to config-time schedule owner | `_schedule_act_on_writer` passes `owner_user_id=schedule.owner_user_id` to both `run_pipeline` and `create_pipeline_run`; `test_act_run_attributed_to_schedule_owner` asserts `pipeline_runs.owner_user_id == _USER` | ✅ |
| `pipelines.enabled=0` → advance `next_fire`, skip run | `_schedule_act_on_writer` step 2/3: advances next_fire, then checks `pipeline.enabled` and returns without running; `test_act_disabled_pipeline_advances_next_fire_no_run` asserts `next_fire` advanced and `router.call.call_count == 0` | ✅ |
| `schedule.enabled=0` → not discovered, not fired | `list_due_schedules` WHERE clause `enabled = 1`; `test_discover_due_excludes_disabled` asserts sid not in due | ✅ |

### Spine no-regression (Lens B)

| Invariant | How verified | Status |
|---|---|---|
| `run_pipeline` byte-unchanged | `git diff origin/main...origin/claude/P5.1b-impl -- src/orchestrator/pipeline/runner.py` → empty | ✅ |
| No new routing `LLMPurpose` | Grep: zero `LLMPurpose` in any new/modified code; `pipeline/` uses only `LLMPurpose.AGENT_RESPONSE` (content-gen, pre-existing in runner.py) | ✅ |
| Gate/spine byte-frozen | `git diff` for `autonomy/`, `core/`, `tools/`, `agents/` → all empty | ✅ |
| `_countdown_sweeper` / `_discover_expired_pendings` / `_writer_approve_helper` untouched | Grep: only in pre-existing code locations (diff context) + docstring mentions (zero actual calls). AST test `test_schedule_sweeper_does_not_call_countdown_spine` parses `_schedule_sweeper` source and asserts zero `ast.Call` name references to the three forbidden symbols | ✅ |
| Scheduler OFF → byte-identical to P5.1a | `config/pipeline.yaml` default `enabled: false`; when disabled, lifespan creates zero sweeper tasks, runs zero boot re-arm. `test_scheduler_off_no_effect_on_countdown` asserts default state | ✅ |
| `countdown_auto_fire=None` preserved in runner source | `test_run_pipeline_not_modified_by_scheduler` asserts the sentinel string appears in `runner.py` module source | ✅ |

### Persistence + API (ADR-042 D2/D9)

| Invariant | How verified | Status |
|---|---|---|
| `pipeline_schedules` 1:N schema | `CREATE TABLE IF NOT EXISTS pipeline_schedules` with ADR-042 D2 columns + `idx_pipeline_schedules_due` partial index; `test_schema_has_pipeline_schedules_table` | ✅ |
| Due-query indexable | `CREATE INDEX IF NOT EXISTS idx_pipeline_schedules_due ON pipeline_schedules (enabled, next_fire) WHERE enabled = 1` — covers the sweeper's exact discovery query | ✅ |
| Owner-private endpoints fail-closed | All 4 endpoints check `pipeline.owner_user_id != _principal.user_id` → 403; principal from `request.state.principal` (server-derived, never body); `_ScheduleCreateRequest` has `extra="forbid"` and no `owner_user_id` field | ✅ |
| `kind=cron` → 422 | `validate_schedule_expr("cron", …)` raises `ValueError` → endpoint returns 422; `test_create_schedule_cron_422_deferred` asserts 422 + "deferred" in detail | ✅ |
| Default OFF fail-closed | `config/pipeline.yaml` ships `enabled: false`; absent file/section → `PipelineSchedulerConfig()` (default); malformed → `ValueError` at startup | ✅ |

### Lifespan + teardown

| Invariant | How verified | Status |
|---|---|---|
| Second background task clean teardown | Lifespan `yield` → `_schedule_sweeper_task.cancel()` + `await` with `suppress(CancelledError)` before `ctx.shutdown()`; `test_schedule_sweeper_cancels_cleanly` asserts `task.done()` | ✅ |
| Sweeper task not created when disabled | `if ctx.pipeline_scheduler.enabled:` guards both boot re-arm and `asyncio.create_task` | ✅ |
| Teardown ordering: sweepers before shutdown | Countdown sweeper cancelled first, then schedule sweeper, then `ctx.shutdown()` — both cancelled+awaited before executor shutdown | ✅ |
| Writer not blocked | Discovery runs on `reader_executor` via `ctx.get_reader_conn()` (per-thread reader pool); only the act touches `writer_executor`. Act serialization is correct (one writer, serialized) | ✅ |

### Test discipline

| Check | Result |
|---|---|
| fail-on-revert for double-fire guard | `test_act_double_fire_guard`: second act with same `now_ms` → `router.call.call_count == 0`. Would fail if claim-before-run ordering were reversed | ✅ |
| fail-on-revert for boot re-arm without run | `test_rearm_advances_past_due_without_running`: asserts `router.call.call_count == 0`. Would fail if re-arm called `run_pipeline` | ✅ |
| All 64 new tests pass | ✅ |
| Full suite 2418 pass | ✅ |

---

## Synthesis

The impl is **high-quality** — correct where it matters, tested where it counts. The
three 🟡 share a common thread: **the missing-pipeline edge case**. The code correctly
handles the disabled-pipeline case (advance `next_fire`, skip run) but the
missing-pipeline case is half-handled: the docstring claims advance, the code doesn't,
and the consequence is a perpetual log loop. The fix is narrow (advance on missing too)
and architecturally neutral (ADR-042 D4 step 2 already says "log + skip" for missing;
adding "advance next_fire" is within the decision surface). The architect may prefer to
keep the current behavior as an intentional "orphan schedules are operator error" signal,
but the docstring should match either way.

The audit gap (Y3) is a known pattern — the countdown sweeper has the same shape — and
is unlikely to fire in practice (SQLite on localhost doesn't have transient I/O errors).
Surfacing for completeness; the architect may route N3-style (acknowledge known gap in
ADR-042 consequences).

**No 🔴. The constitutional crux holds:** `_schedule_sweeper` is a genuinely independent
sibling that shares zero spine-critical code with `_countdown_sweeper`, and
`countdown_auto_fire=None` is preserved by construction (the runner is untouched, the
scheduler is merely its second caller). The product is safe to merge after architect
routing of the 3 🟡.
