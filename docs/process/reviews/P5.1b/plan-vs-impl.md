---
task_id: P5.1b
stage: senior-plan-vs-impl
actor: senior
date: "2026-06-09"
verdict: needs_architect
reviewed_branch: origin/claude/P5.1b-impl
reviewed_at: a7e485c
plan: docs/process/senior-plans/P5.1b.md
adr: ADR-042
routing_absorbed: docs/process/reviews/P5.1b/architect-routing-on-plan.md
inputs:
  - docs/process/senior-plans/P5.1b.md            # the plan (ADR-042 Accepted)
  - docs/process/reviews/P5.1b/architect-routing-on-plan.md  # Y1 interval-only / Y2 keep / N3 GC
  - docs/decisions/ADR-042-recurring-pipeline-scheduler.md
findings:
  - id: PVI-1
    severity: yellow
    atomic: P5.1b-5
    title: "DELETE/PATCH owner-check binds to the URL pipeline, not the schedule's parent pipeline (cross-pipeline authorization gap)"
  - id: PVI-2
    severity: green
    atomic: P5.1b-2
    title: "Partial index added beyond 'DDL exactly the ADR-042 D2 columns' — realizes the D2 'indexable' intent; harmless additive"
  - id: PVI-3
    severity: green
    atomic: P5.1b-4
    title: "Missing-parent-pipeline act does not advance next_fire → schedule re-discovered every tick (log churn); matches plan spec but worth a follow-on note"
  - id: PVI-4
    severity: green
    atomic: P5.1b-5
    title: "GET on a missing pipeline returns [] while POST/DELETE/PATCH return 404 — minor verb inconsistency (plan did not mandate either)"
---

# P5.1b — senior plan-vs-impl

Reviewed `origin/main...origin/claude/P5.1b-impl` @ `a7e485c` (6 atomics) against
`docs/process/senior-plans/P5.1b.md`, ADR-042 (Accepted), and the absorbed plan-stage routing
(`architect-routing-on-plan.md`: Y1 interval-only / Y2 keep endpoints / N3 ack-deferred-GC). Read
on `main` via diff (no checkout — shared worktree).

**Bottom line:** The impl is **faithful to the plan and ADR-042 on every constitutional axis** —
spine byte-untouched, cron correctly deferred, interval-only arithmetic, the new 1:N
`pipeline_schedules` table, the sibling sweeper sharing **zero** spine code, claim-before-run +
writer re-check, boot re-arm = skip-to-next, opt-in default-OFF, ADR amendments inscribed, and
ADR-042 Accept performed by the architect (not the junior, RC-3). Tests are non-vacuous and cover
both Lens A (scheduler safety) and Lens B (spine no-regression). **One 🟡** plan-implied-invariant
drift on the owner-private endpoint surface (PVI-1) routes the verdict to `needs_architect`; three
🟢 observations are non-blocking.

---

## Per-atomic faithfulness

### P5.1b-1 — `pipeline/schedule.py` interval-only arithmetic — ✅ faithful

- `compute_next_fire` interval = `after_ms + int(expr) * 1000`; `validate_schedule_expr` rejects
  non-positive / non-integer / empty; **unknown kind → `ValueError`**; **`kind=cron` →
  `ValueError` (validate) / `NotImplementedError` (compute)** — exactly the Y1 absorption and
  ADR-042 D3.
- Pure, no LLM / no I/O (ADR-042 D3); **no new `LLMPurpose`** (grep clean across the diff).
- The **N2 drift doc-comment** ("recompute at claim time … drifts by up to `sweep_interval_s` … the
  correct price of skip-to-next") is present in the module docstring, as the routing required.
- Cron is rejected before the sweeper can ever see it (validated at create, P5.1b-5) — the
  "`kind` column never implies a working cron path" guarantee holds.

### P5.1b-2 — `pipeline_schedules` table + store CRUD + due-query — ✅ faithful (1 🟢)

- DDL columns match ADR-042 D2 byte-for-byte; appended to `PIPELINE_SCHEMA` via `CREATE TABLE IF
  NOT EXISTS` (idempotent, no ALTER to `pipelines`).
- All seven store functions present with the planned signatures; `list_due_schedules` =
  `WHERE enabled=1 AND next_fire <= ?` (reader-path discovery). Record round-trips `bool(enabled)`
  correctly. `psch_` + uuid4, `created_at` epoch-ms — as specified.
- **PVI-2 (🟢):** an extra `CREATE INDEX IF NOT EXISTS idx_pipeline_schedules_due ON
  pipeline_schedules (enabled, next_fire) WHERE enabled = 1` is added beyond the plan's "DDL
  exactly the ADR-042 D2 columns" wording. This is **not** scope expansion — it *realizes* the
  explicit ADR-042 D2 rationale ("it gives the sweeper an **indexable** `WHERE enabled=1 AND
  next_fire <= ?` discovery", ADR-042:138). Additive, idempotent, zero behavior change. Noted, not
  blocking.

### P5.1b-3 — `PipelineSchedulerConfig` + loader + `config/pipeline.yaml` + wiring — ✅ faithful

- `PipelineSchedulerConfig{frozen, extra="forbid", enabled=False, sweep_interval_s: int = Field(60,
  ge=1)}`.
- `load_pipeline_scheduler_config` is the **byte-for-byte control-flow mirror** of
  `load_countdown_auto_fire_config` (`autonomy/config.py:33-57`): absent file → default; `None`
  → default; non-dict top level → `ValueError`; absent section → default; malformed section →
  `ValueError` (refuse-start). Verified line-by-line against the reference.
- `AppContext.pipeline_scheduler` default-factory (test-compat default OFF), `_build_context`
  loads `config_dir / "pipeline.yaml"` and threads it into the `AppContext(...)` return.
- `config/pipeline.yaml` ships `{enabled: false, sweep_interval_s: 60}` with the ADR-042-D7
  fail-closed header comment.

### P5.1b-4 — sibling `_schedule_sweeper` + `_discover_due_schedules` + boot re-arm + lifespan — ✅ faithful (1 🟢)

- `_discover_due_schedules` runs on the **reader** (`get_reader_conn`), returns `schedule_id`s,
  never appends.
- `_schedule_act_on_writer` follows the **ADR-042 D4 order**: (1) authoritative re-read +
  still-due re-check (`enabled and next_fire <= now`), (2) parent-pipeline re-check, (3) **claim:
  `update_schedule_next_fire(compute_next_fire(...))` BEFORE the run**, (4)
  `run_pipeline(... owner_user_id=schedule.owner_user_id)` → `create_pipeline_run(run_id=
  result.run_id, ...)`. `PipelineDeps` constructed exactly as `/run`. Disabled parent → next_fire
  advanced (claim runs before the `if not pipeline.enabled` skip), run skipped — matches D4 step 2.
- **Claim-before-run double-fire crux** is implemented and **tested non-vacuously**
  (`test_act_double_fire_guard`: second act asserts `router.call.call_count == 0`).
- **Boot re-arm** = advance past-due without running (`test_rearm_advances_past_due_without_running`
  asserts `call_count == 0` *and* next_fire advanced; `test_rearm_leaves_future_schedules_unchanged`
  asserts future schedules untouched) — D5 skip-to-next, distinct from discover-and-run.
- **Sibling shares zero spine code:** `_schedule_act_on_writer` / `_schedule_sweeper` import and
  call **none** of `_countdown_sweeper` / `_discover_expired_pendings` / `_writer_approve_helper`;
  the diff adds only new functions — **no `-` removals** touch any spine symbol,
  `countdown_auto_fire=None`, `_execute_local_call`, or the gate. `runner.py`, `tool_dispatch.py`,
  and `autonomy/` are **absent from the diffstat** (byte-untouched). Lens-B asserted in-test
  (`countdown_auto_fire.enabled is False`; `"countdown_auto_fire=None" in module_source`).
- Lifespan: when `enabled`, boot re-arm on the writer executor **before** `create_task`; teardown
  cancels both sweepers + `suppress(CancelledError)` **before** `ctx.shutdown()`; when disabled,
  nothing started (byte-identical to P5.1a).
- **PVI-3 (🟢):** when the parent pipeline is **missing** (deleted), the act returns at step 2
  **without** advancing `next_fire` — so the orphaned schedule stays due and is re-discovered +
  re-warn-logged on **every** sweep tick. This **matches the plan/ADR-042 D4 spec** ("missing →
  log + skip") and is not a safety issue (no run fires), so it is not a drift. Flagging only as a
  cheap future-hardening candidate (advance-or-delete the orphan to stop the log churn) — architect
  may capture for the cron/GC follow-on or ignore.

### P5.1b-5 — owner-private schedule-management endpoints — 🟡 PVI-1 + 🟢 PVI-4

- POST: `validate_schedule_expr` **first** → 422 (incl. **`kind=cron` → 422 deferred**); owner
  check on reader (404 missing, 403 non-owner); initial `next_fire = compute_next_fire(...)`;
  `create_schedule` on writer with `owner_user_id = principal.user_id` (server-derived, never from
  the body — `_ScheduleCreateRequest` is `extra="forbid"`). 201. Faithful.
- GET / DELETE / PATCH owner-gated; PATCH recomputes `next_fire` from now on re-enable (plan's
  "does not fire immediately"). Tests cover owner happy-path + non-owner-403 each verb,
  missing-404, malformed-422, cron-422, and create→appears-in-due.

- **PVI-1 (🟡) — authorization is bound to the wrong object on DELETE and PATCH.** Both verbs do:
  ```
  pipeline = get_pipeline(writer_conn, pipeline_id)      # pipeline_id from the URL
  if pipeline.owner_user_id != principal.user_id: 403
  sched = get_schedule(writer_conn, schedule_id)         # schedule_id from the URL — UNRELATED fetch
  if sched is None: 404
  delete_schedule / set_schedule_enabled(...)            # acts on sched
  ```
  There is **no check that `sched.pipeline_id == pipeline_id`**. The owner gate is evaluated against
  the **URL pipeline**, but the mutation targets a schedule fetched by **global `schedule_id`**.
  The plan's invariant (P5.1b-5 acceptance: *"Owner-check reuses the **parent pipeline's**
  `owner_user_id` — a schedule inherits **its** pipeline's owner"*; ADR-042 D9 *"owner of the
  parent pipeline only"*) means the **schedule's actual parent** (`sched.pipeline_id`), not an
  arbitrary URL-supplied pipeline.

  **Consequence:** a user who owns *any* pipeline `P_self` can `DELETE` / `PATCH` *another* user's
  schedule `S_victim` by calling `…/pipelines/{P_self}/schedules/{S_victim}` — the owner gate
  passes (caller owns `P_self`), then the act lands on `S_victim`. This is exactly the class
  ADR-039 D1 / ADR-041 D7 fail-closed owner-private posture exists to prevent: a cross-tenant
  authorization bypass on a mutating verb.

  **Why this slipped the acceptance criteria + both test paths:** the criteria say "non-owner gets
  403"; the impl *does* 403 a non-owner of the URL pipeline (`test_delete_schedule_non_owner_403`
  / `test_patch_schedule_non_owner_403` both reuse the **same** `pipe_id` for URL and schedule
  parent), so the surface passes. The drift is on the **plan-implied invariant** the criteria
  don't spell out: owner-of-the-schedule's-parent ≠ owner-of-the-URL-pipeline when they differ.
  **No cross-pipeline test exists** (grep: no `cross`/`other_pipeline`/`mismatch` case).

  **Practical exploitability is low** — `schedule_id` is `psch_` + uuid4 hex (128-bit,
  unguessable), so an attacker must already know a victim's id (leak via logs / shared UI / error
  text) and own ≥1 pipeline. It is a **defense-in-depth / correctness gap**, not a trivially
  reachable hole. But it sits on the constitutional owner-private surface and the fix is one cheap
  guard. **Surfaced for architect routing — not fixed here** (senior does not self-route; the
  natural α-fix is `if sched.pipeline_id != pipeline_id: raise 404` in DELETE + PATCH, plus a
  cross-pipeline 404 test; GET is already safe because it scopes via
  `list_schedules_for_pipeline(pipeline_id)`, and POST creates under the URL pipeline so it is
  inherently consistent).

- **PVI-4 (🟢):** `GET` on a missing pipeline returns `[]`; POST/DELETE/PATCH return 404. Minor
  verb inconsistency; the plan did not mandate a code for GET-on-missing and `[]` arguably avoids a
  trivial existence-oracle. Non-blocking; mention only.

### P5.1b-6 — inscribe ADR-042 amendments — ✅ faithful

- **ADR-041 D8** gains the `pipeline_schedules` side-table note; **ADR-041 D10** flips to
  "P5.1b realized (ADR-042); P5.1c (`RB-PIPELINE-EMAIL`) remains deferred" with interval-only/cron
  -deferred wording.
- **ADR-040** annotation: `_schedule_sweeper` reuses the *pattern*, shares **no** spine code,
  `RB-PIPELINE-SCHED` named as the **milder neighbor** of `RB-AUTOFIRE`.
- **ADR-025 D6** annotation: the **second** bounded background task (discover-on-reader /
  act-on-writer, clean teardown).
- **ADR-042 Status = Accepted (architect, 2026-06-09)** — performed by the architect during
  routing absorption; the impl branch did **not** touch ADR-042's status (absent from the
  diffstat), so RC-3 (no junior/senior self-accept) holds.

---

## Constitutional carry-forward (Lens B) — all clear

| Invariant | Result |
|---|---|
| `run_pipeline` byte-identical | ✅ `runner.py` absent from diffstat (scheduler is a *second caller*) |
| `_countdown_sweeper` / `_discover_expired_pendings` / `_writer_approve_helper` byte-untouched | ✅ no `-` removals on any; only additive new functions |
| `countdown_auto_fire=None` preserved (reversible-only) | ✅ unchanged; asserted in-test |
| gate (`score`/`decide_tier`/`emit_gate_decision`) + `_execute_local_call` untouched | ✅ absent from diff |
| No new routing `LLMPurpose` | ✅ grep clean (no `LLMPurpose`/`content-gen` in the diff) |
| scheduler-OFF ⇒ byte-identical to P5.1a | ✅ lifespan gates all new work behind `pipeline_scheduler.enabled`; default OFF |

No-LLM-in-scheduling held: the only LLM in a scheduled run remains the analyze/reduce content-gen
inside the unchanged `run_pipeline`. `RB-PIPELINE-SCHED` inscribed honestly, not softened.

---

## Plan-external expansion / omission scan

- **Omissions:** none — all six atomics and every acceptance criterion are present.
- **Expansions:** only PVI-2 (the partial index), which realizes an explicit ADR-042 D2 stated
  intent rather than adding new scope. No unrequested feature, no out-of-scope file, no opportunistic
  bundling under deferral language (cron stays fully deferred; no stub cron path leaked in).

---

## Verdict

**`needs_architect`** — one 🟡 plan-implied-invariant drift (PVI-1: DELETE/PATCH bind the owner
check to the URL pipeline rather than the schedule's actual parent, a cross-tenant authorization gap
on the owner-private surface, untested). The three 🟢 items are non-blocking observations. All
constitutional/spine invariants hold; the slice is otherwise faithful to the plan, ADR-042, and the
absorbed routing.

Per ADR-008 Amendment 1 (Route B, W-005), state advances to `awaiting_R0_A` regardless of verdict;
this `needs_architect` frontmatter flags PVI-1 for architect routing (the natural disposition is an
α in-cycle fix — the guard + a cross-pipeline 404 test — but the routing call is the architect's,
not mine; senior does not self-route a finding).
</content>
</invoke>
