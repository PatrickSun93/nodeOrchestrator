---
task_id: P5.1b
round: R0-B-on-plan
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 3
verdict_history:
  - "2026-06-09: R0-B-on-plan cross-family review → clean (0🔴 0🟡 3🟢)"
reviewed_artifacts:
  - "docs/process/architect-briefs/P5.1b.md (architect ratification B0–B6)"
  - "docs/process/senior-plans/P5.1b.md (6 atomics)"
  - "docs/decisions/ADR-042-recurring-pipeline-scheduler.md (Proposed)"
  - "docs/decisions/ADR-040-countdown-auto-fire-on-timer.md (Accepted, pattern reference)"
  - "docs/decisions/ADR-041-deterministic-analysis-pipeline.md (Accepted, base contract)"
  - "src/orchestrator/pipeline/runner.py (verified seams: countdown_auto_fire=None, run_id generation)"
  - "src/orchestrator/pipeline/store.py (verified: PIPELINE_SCHEMA, create_pipeline_run signature)"
  - "src/orchestrator/api/app.py (verified: _countdown_sweeper, _discover_expired_pendings, lifespan, /run endpoint)"
  - "src/orchestrator/agents/tool_dispatch.py (verified: countdown_auto_fire stamp guard)"
  - "src/orchestrator/autonomy/config.py (verified: CountdownAutoFireConfig pattern)"
verify_base: "origin/main @ 811412a"
---

# R0-B-on-plan cross-family review — P5.1b recurring pipeline scheduler

## Lens preamble

This is a **plan-stage** cross-family R0-B (no impl yet; reviewing the senior plan + ADR-042
against the architect's ratified B0–B6 decision surface). My lens is **runtime-integration
failure modes** across the eight concerns the architect specified: double-fire on restart,
catch-up skip-to-next correctness, sibling-sweeper decoupling, `countdown_auto_fire=None`
preservation, owner attribution, spine/gate/runner freezing, B2 schema indexability, and
B4 RB-PIPELINE-SCHED honesty.

The senior plan is unusually thorough: six atomics with per-atomic acceptance criteria,
five push-backs surfacing genuine unresolved calls, verified code seams at `origin/main
@ 811412a`, and Lens-A/Lens-B test specifications. The ADR-042 is comparably detailed,
with explicit D1–D9 decisions, alternatives-rejected blocks, and reversibility tables.
This is the strongest plan-stage artifact set I've reviewed in this project.

I read the code seams the plan cites and confirmed every claim is accurate:
`run_pipeline` self-generates `run_id` at `runner.py:263`, returns it at `:430-439`;
`countdown_auto_fire=None` is hardcoded at `runner.py:153,223` in both the pass-0 and
re-dispatch paths; the stamp guard at `tool_dispatch.py:138-145` checks `is not None and
.enabled` before stamping `expires_at`; the `/run` endpoint at `app.py:1668-1707`
constructs `PipelineDeps` and threads `result.run_id` into `create_pipeline_run`. All
eight architect concerns are correctly addressed by the design. No blocking or
needs-architect findings.

---

## Concern-by-concern trace

### 1. 重启 double-fire / missed re-arm

**Claim-before-run ordering (ADR-042 D4 step 3) is the correct guard.** Advancing
`next_fire` via `update_schedule_next_fire` *before* `run_pipeline` means a crash
mid-run leaves the schedule already advanced; on reboot, the boot re-arm step
(`_rearm_schedules_on_boot`, ADR-042 D5) skips it because `next_fire > now`. This is
the exact structural analog of ADR-040's claim via the still-pending re-check, adapted
to mutable `next_fire` state (simpler: a plain UPDATE, no read-time derivation needed).

The writer-side authoritative re-check (ADR-042 D4 step 1: re-read schedule, verify
`enabled=1 AND next_fire <= now`) is the TOCTOU guard against a stale reader discovery:
if a prior act already advanced `next_fire`, the re-check skips. All three act paths
(run, pipeline-deleted, pipeline-disabled) either advance `next_fire` or skip with the
writer re-check, so a schedule discovered by two ticks runs **once**.

**Boot re-arm vs sweeper act distinction (ADR-042 D5) is correctly articulated.**
Boot re-arm = advance-without-running (past-due during downtime → skip-to-next). Sweeper
act = discover-and-run (normal operation). These are two distinct code paths, not one
path with a conditional. The plan P5.1b-4 acceptance criteria explicitly test both:
"boot re-arm advances past-due without running" and "fires only due+enabled."

**Verified:** the plan's P5.1b-4 test spec includes "a schedule discovered by two ticks
(stale reader) runs once (second act sees advanced next_fire)" — the double-fire guard
is pinned as a test.

### 2. catch-up skip-to-next semantics

**Design is correct and consistent across all three surfaces:** ADR-042 D5 (boot
re-arm skip-to-next), D4 step 3 (claim step uses `compute_next_fire(…, now)` →
skip-to-next), B3 architect ratification = (ii) skip-to-next. The plan P5.1b-4
explicitly distinguishes boot re-arm (advance-without-running) from sweeper act
(discover-and-run). No stale backfill storm possible.

The plan's §5 #4 flagging acknowledges this distinction and asks for architect
confirmation. Appropriate.

### 3. Sibling sweeper — genuine decoupling

**ADR-042 D1 is explicit: "shares NONE of the countdown actuation path."** The
plan P5.1b-4 acceptance criteria: "Imports/calls none of `_countdown_sweeper` /
`_discover_expired_pendings` / `_writer_approve_helper`." The ~10-line loop skeleton
is duplicated per ADR-041 D2 precedent (spine-untouched > DRY for trivial scaffolding).

**Clean teardown:** plan P5.1b-4 lifespan spec: `cancel()` + `with
suppress(asyncio.CancelledError): await` before `ctx.shutdown()` — byte-identical
pattern to `_countdown_sweeper` teardown at `app.py:1755-1758`. No task-leak risk.

**Writer blocking:** discovery on `reader_executor`, act on `writer_executor`
(`max_workers=1`). Act serializes behind any in-flight run or countdown fire — same
property as manual `/run`. Acceptable for infrequent scheduled analysis. The plan
acknowledges LLM-overlap remains deferred (ADR-041 D3).

### 4. `countdown_auto_fire=None` preservation

**Hardcoded in the runner, not passed by the scheduler.** `run_pipeline` internally
calls `process_tool_calls(..., countdown_auto_fire=None)` at `runner.py:153,223` for
both pass-0 and re-dispatch paths. The scheduler is a second *caller* of `run_pipeline`
— it never calls `process_tool_calls` directly, so it cannot accidentally pass a
different `countdown_auto_fire` value.

The plan's constitutional carry-forward assertions (Lens B) include a grep test:
`countdown_auto_fire=None` at both runner call sites is byte-identical post-P5.1b.
Verified at `origin/main @ 811412a`: line 153 and line 223 are the only two call
sites in the runner.

### 5. Owner attribution

**ADR-042 D4 step 4: `owner_user_id=schedule.owner_user_id`.** The schedule's
`owner_user_id` is stamped at create time from the server-derived principal (ADR-042
D9, P5.1b-5), not from a request body. The plan P5.1b-4 test spec: "run attributed
to schedule.owner_user_id." No null/system-owner path exists — the `owner_user_id` is
non-nullable in the `pipeline_schedules` DDL and the `run_pipeline` signature requires
it (`runner.py:250`).

### 6. Spine/gate/runner freezing

**`run_pipeline` byte-identical:** the scheduler is a *caller*, not an editor. Verified
seam at `runner.py:245-263` — `run_pipeline` generates its own `run_id` internally.
The scheduler mimics `/run` exactly: call `run_pipeline(...)` → take `result.run_id` →
`create_pipeline_run(run_id=result.run_id, …)`.

**No new routing `LLMPurpose`:** scheduling = cron/interval arithmetic = code (ADR-042
D3). The only LLM in a scheduled run is the analyze + reduce content-gen inside the
unchanged `run_pipeline`, using the existing `LLMPurpose.AGENT_RESPONSE` (content-gen).
The plan P5.1b-1: "no LLM and no I/O" in `schedule.py`. The plan's forcing functions
include a grep of `LLMPurpose` — only `content-gen`/`AGENT_RESPONSE` in the pipeline.

**Gate/spine byte-frozen:** `_execute_local_call` + `score`/`decide_tier`/
`emit_gate_decision` + `_countdown_sweeper` + `_writer_approve_helper` — all
untouched. The plan's P5.1b-4 Lens B acceptance criteria include a grep/AST assertion.

### 7. B2 schema — 1:N side table

**ADR-042 D2 design is sound:** `pipeline_schedules(schedule_id PK, pipeline_id,
owner_user_id, kind, expr, next_fire INTEGER, enabled INTEGER DEFAULT 1,
created_at INTEGER)`. The due-query `WHERE enabled=1 AND next_fire <= ?` is SQL-
indexable (unlike a JSON-blob scan). The two `enabled` meanings are distinct:
`pipelines.enabled` (is this pipeline active) vs `pipeline_schedules.enabled`
(is this timer armed). The plan P5.1b-4 act correctly handles `pipelines.enabled=0`
→ advance `next_fire` without running (so re-enabling resumes cleanly).

`PipelineDefinition` stays `frozen=True` — schedule state is in the side table,
not the definition JSON.

### 8. B4 RB-PIPELINE-SCHED honesty

**Correctly named and bounded.** ADR-042 D8: "first headless initiation surface"
— `RB-PIPELINE-SCHED` is the milder neighbor of `RB-AUTOFIRE` (reversible initiation
vs gated actuation). The plan's framing matches: "categorically milder than ADR-040's
`RB-AUTOFIRE`" (§1). Bounded by: reversible output only (ADR-041 D5), `countdown_
auto_fire=None` preserved, opt-in default OFF, config-time schedule owner attribution.

No over-claim (the residual explicitly says it cannot cross into irreversible
actuation — that's P5.1c's `RB-PIPELINE-EMAIL`). No under-name (the residual
acknowledges the novelty: first thing that *starts* work with no human at start time).

---

## Findings

No 🔴 or 🟡 findings. Three 🟢 advisories:

| ID | Severity | Surface | Claim |
|----|----------|---------|-------|
| G1 | 🟢 advisory | Plan P5.1b-4 / ADR-042 D4 | **`now` source in act step 3 is implicit.** The plan says `compute_next_fire(kind, expr, now)` inside the writer-side act but doesn't specify whether `now` is the sweeper discovery timestamp or a fresh `now_ms()` inside the act. The natural implementation uses `now_ms()` inside the act function, which is correct (prevents a stale `now` from producing a `next_fire` already in the past for cron schedules). The plan should make this explicit: "`now` = `now_ms()` captured at step 3, not the discovery timestamp." |
| G2 | 🟢 advisory | Plan P5.1b-2 DDL | **No explicit due-query index.** ADR-042 D2 claims the side table enables "an indexable `WHERE enabled=1 AND next_fire <= ?` discovery." The plan's DDL accepts the ADR columns but doesn't specify `CREATE INDEX IF NOT EXISTS idx_pipeline_schedules_due ON pipeline_schedules(enabled, next_fire)`. For the expected scale (tens of schedules, not millions), a full scan is fine; the index is a forward-optimization. The plan should note the index decision (defer or include). |
| G3 | 🟢 advisory | Plan P5.1b-4 act | **`compute_next_fire` error recovery in sweeper act.** If `compute_next_fire` raises inside the act (despite create-time validation in P5.1b-5), the sweeper's `except Exception: log + continue` leaves `next_fire` unadvanced. The schedule is rediscovered as due every sweep tick → log-spam loop. Since `compute_next_fire` is deterministic pure code and validation runs at create time, this is a narrow concern; the plan's adversarial tests should cover the error path. Consider: on `compute_next_fire` failure, disable the schedule (`set_schedule_enabled(conn, schedule_id, False)`) to break the loop. |

---

## Plan push-backs assessment

The senior's §5 push-backs are well-judged:

- **#1 (cron parser mechanism):** correctly identifies the unratified sub-decision. The plan chose (a) hand-rolled with adversarial tests — consistent with ADR-040 D1 no-new-dep posture. Architect's call.
- **#2 (schedule endpoints):** correctly notes endpoints weren't in the brief's B0–B6 foreground but are necessary-for-function (a scheduler with no create path is inert). The ADR-041 D7 "minimal CRUD so there is something to run" precedent applies.
- **#3 (config home):** genuinely low-stakes; either `config/pipeline.yaml` or `config/autonomy.yaml §pipeline_scheduler` works. Plan chose the dedicated file with a reasoned rationale.
- **#4 (boot-re-arm vs sweeper semantics):** correctly flags the distinction for architect confirmation.

All four are appropriate for the plan stage and none indicate a design defect.

---

## Constitutional carry-forward confirmation

Verified against `origin/main @ 811412a`:

| Invariant | Status | Evidence |
|-----------|--------|----------|
| `countdown_auto_fire=None` at both runner call sites | ✅ Preserved | `runner.py:153,223` — scheduler never touches `process_tool_calls` |
| `run_pipeline` byte-identical | ✅ Preserved | Scheduler is second *caller*, not editor; `runner.py:245-263` unchanged |
| Gate byte-frozen (`score`/`decide_tier`/`emit_gate_decision`) | ✅ Preserved | Scheduler imports none of `autonomy/` |
| `_countdown_sweeper` + `_writer_approve_helper` byte-untouched | ✅ Preserved | Sibling shares zero actuation code (ADR-042 D1) |
| No new routing `LLMPurpose` | ✅ Preserved | Scheduling = code; only `AGENT_RESPONSE` content-gen in pipeline |
| Single-writer + reader-liveness (ADR-025 D6) | ✅ Preserved | Discovery on reader_executor, act on writer_executor |
| Opt-in, fail-closed (default OFF) | ✅ Preserved | ADR-042 D7 mirrors `CountdownAutoFireConfig` pattern |
| RB-PIPELINE-SCHED honest inscription | ✅ Preserved | ADR-042 D8: milder than RB-AUTOFIRE, reversible-bounded |

---

## Synthesis

P5.1b's design is cleanly scoped, correctly inherits the byte-unchanged `run_pipeline`
and `countdown_auto_fire=None` safety floor, and honestly names `RB-PIPELINE-SCHED`
as the first headless-initiation surface while keeping it categorically milder than
`RB-AUTOFIRE`. The claim-before-run ordering (ADR-042 D4), the boot re-arm skip-to-next
(ADR-042 D5), and the sibling-sweeper zero-code-sharing (ADR-042 D1) together form a
coherent defense against the double-fire, missed-re-arm, and spine-regression hazards.
The three 🟢 advisories are implementation clarifications, not design defects. Ready
for architect Accept.
