---
task_id: P5.1b
stage: impl
review: R0-A (architect-partner, impl-stage)
actor: architect-partner
lens: "Lens A = scheduler safety + headless-initiation correctness; Lens B = spine + auto-fire no-regression"
verdict: needs_architect
date: "2026-06-09"
reviewed_branch: origin/claude/P5.1b-impl
reviewed_at: a7e485c
plan: docs/process/senior-plans/P5.1b.md
adr: ADR-042
routing_absorbed: docs/process/reviews/P5.1b/architect-routing-on-plan.md
read_method: "git diff origin/main...origin/claude/P5.1b-impl (no checkout — shared worktree); gates in isolated detached worktree @ a7e485c"
gates:
  ruff: pass (All checks passed!)
  mypy: pass (Success: no issues found in 304 source files — files=src,tests scope)
  pytest: pass (2418 passed, 1 pre-existing starlette warning, full suite)
peer_reviews:
  - docs/process/reviews/P5.1b/plan-vs-impl.md   # senior, needs_architect (PVI-1..4)
  - docs/process/reviews/P5.1b/R0-B.md            # r0b cross-family, needs_architect (Y1..3)
findings:
  - id: A1
    severity: yellow            # authz-correctness; must-fix-before-merge; low practical reachability
    atomic: P5.1b-5
    title: "Cross-pipeline IDOR on DELETE/PATCH — owner gate binds to the URL pipeline, not the schedule's actual parent (concur senior PVI-1; r0b MISSED it)"
  - id: A2
    severity: yellow
    atomic: P5.1b-4
    title: "_schedule_act_on_writer docstring claims missing-pipeline 'still advance next_fire' but the code returns without advancing (concur r0b Y1) — doc-only"
  - id: A3
    severity: yellow
    atomic: P5.1b-4
    title: "Orphan schedule (parent pipeline deleted) re-discovered + warn-logged every sweep tick — spec-faithful, benign (concur senior PVI-3 / r0b Y2); shares a root with A2"
  - id: A4
    severity: green             # NOVEL — neither peer raised
    atomic: P5.1b-4
    title: "Spine-isolation AST test covers only _schedule_sweeper, not _schedule_act_on_writer (the higher-risk act fn) — faithful to ADR-042 D1 wording; act is verifiably spine-free today"
  - id: A5
    severity: green
    atomic: P5.1b-5
    title: "GET on missing pipeline returns [] while POST/DELETE/PATCH return 404 — minor verb inconsistency (concur senior PVI-4)"
  - id: A6
    severity: green
    atomic: P5.1b-2
    title: "Partial index idx_pipeline_schedules_due realizes the ADR-042 D2 'indexable' intent — additive, in-spirit (concur senior PVI-2)"
---

# R0-A impl-stage — P5.1b (recurring pipeline scheduler)

Independent architect-partner review of `origin/claude/P5.1b-impl` @ `a7e485c` (6 atomics
P5.1b-1..6, +1996/15 files) against `docs/process/senior-plans/P5.1b.md`, **ADR-042 (Accepted)**,
and the absorbed plan-stage routing (`architect-routing-on-plan.md`: Y1 interval-only / Y2 keep
endpoints / N3 ack-deferred-GC). Read on `main` via `git diff` (no checkout — shared worktree);
canonical gates run independently in an isolated detached worktree @ `a7e485c`.

**Bottom line.** The slice is **constitutionally sound and faithful to the plan/ADR-042** — the
spine is byte-frozen (verified at function granularity), the sibling sweeper shares zero spine
code, `run_pipeline` is byte-unchanged with the scheduler as a correct second caller,
`countdown_auto_fire=None` is preserved (a scheduled run can never headless-actuate an
irreversible op), cron is correctly deferred (interval-only, `kind=cron`→422), and boot re-arm =
skip-to-next + claim-before-run are implemented and tested with fail-on-revert discipline. **One
🟡 must-fix authorization-correctness finding (A1) on the owner-private endpoint surface** routes
the verdict to `needs_architect`; the remaining items are documentation/robustness/cosmetic.

---

## Lens A — scheduler safety + headless-initiation correctness

All eight dispatched Lens-A invariants **verified PASS**:

| Invariant | Verification | Status |
|---|---|---|
| Only fire due+enabled | `list_due_schedules` `WHERE enabled=1 AND next_fire<=?` (reader discovery) + writer re-check step 1 (`if not schedule.enabled or schedule.next_fire > now_ms_val: skip`) | ✅ |
| No double-fire on restart (boot re-arm) | `_rearm_schedules_on_boot` advances past-due **without running**, on the writer, **before** `create_task` | ✅ |
| Claim-before-run double-fire guard | step 3 `update_schedule_next_fire(compute_next_fire(...,now))` **before** step 4 `run_pipeline`; stale-reader second act sees advanced `next_fire`→skips (`test_act_double_fire_guard` asserts 2nd act `call_count==0` — fails if claim removed) | ✅ |
| skip-to-next catch-up, no thunder / no silent drop | `compute_next_fire(...,now)` at claim time, not from old `next_fire`; boot re-arm drops missed (logged "skip-to-next") | ✅ |
| `next_fire` re-arm correct | advanced exactly once at claim; disabled-pipeline still advances (step 3 before the `enabled` skip) — `test_act_disabled_pipeline_advances_next_fire_no_run` | ✅ |
| Run attributed to config-time owner (not null/system) | `run_pipeline(... owner_user_id=schedule.owner_user_id)` + `create_pipeline_run(... owner_user_id=schedule.owner_user_id)`; `test_act_run_attributed_to_schedule_owner` asserts `pipeline_runs.owner_user_id==owner` | ✅ |
| discover-on-reader / act-on-writer (single-writer + reader-liveness) | discovery on `reader_executor`/`get_reader_conn()`; act + all mutations on `writer_executor`/`writer_store.conn` | ✅ |
| 2nd background task clean teardown | lifespan `cancel()` + `suppress(CancelledError)` + `await` **before** `ctx.shutdown()`; `test_schedule_sweeper_cancels_cleanly` | ✅ |
| interval-only; `kind=cron` create→422 | `validate_schedule_expr("cron",…)` raises `ValueError`→422 ("deferred"); `test_create_schedule_cron_422_deferred` | ✅ |

`PipelineDeps` construction + the `create_pipeline_run(run_id=result.run_id, …)` call are **byte-for-byte
the manual `/run` pattern** (`app.py` `_run_pipeline`) — confirmed by side-by-side read; the only
intended deltas are `owner_user_id` from the stored schedule (config-time owner) and the direct
`writer_conn`.

---

## Lens B — spine + auto-fire no-regression (all clear, independently verified)

| Invariant | Verification (my run) | Status |
|---|---|---|
| `_countdown_sweeper` / `_writer_approve_helper` / `_discover_expired_pendings` byte-frozen | **AST-extracted each fn from `origin/main` vs branch `app.py` → byte-identical** (2378b / 3540b / 1883b, all match) | ✅ |
| gate (`score`/`decide_tier`/`emit_gate_decision`) + `_execute_local_call` zero diff | `autonomy/`, `agents/`, `tools/executor.py` **absent from diffstat** | ✅ |
| `run_pipeline` byte-unchanged (second caller) | `pipeline/runner.py` zero diff; scheduler threads `result.run_id` **into** `create_pipeline_run`, never **into** `run_pipeline` | ✅ |
| `countdown_auto_fire=None` preserved | runner untouched; scheduler does not pass the kwarg → inherits the hardcoded `None`; `test_run_pipeline_not_modified_by_scheduler` sentinel | ✅ |
| no new routing `LLMPurpose` | grep clean across pipeline modules + app.py diff; spine untouched | ✅ |
| scheduler-OFF ⇒ byte-identical to P5.1a | every new path gated behind `ctx.pipeline_scheduler.enabled`; default OFF (`config/pipeline.yaml`, fail-closed loader mirrors `load_countdown_auto_fire_config` line-by-line) | ✅ |

**Gate run (isolated detached worktree @ `a7e485c`, `uv sync --all-extras`):** `ruff check` → *All
checks passed!*; `mypy` (files=src,tests) → *Success: no issues found in 304 source files*; `pytest`
→ *2418 passed* (1 pre-existing starlette/httpx deprecation warning, unrelated).

> **Env-artifact note (reconciles r0b's gate line).** A first gate pass in an **under-provisioned**
> worktree (`uv sync` without the `api`/`mcp` extras) produced `fastapi`/`mcp` import-not-found and a
> lone `_patch_schedule` `untyped-decorator` error. Re-running with `--all-extras` cleared **all** of
> them (mypy clean, 304 files). r0b's frontmatter note "*mypy pass (4 new untyped-decorator …)*" is
> the **same env artifact**, not a code defect — with FastAPI installed there are zero untyped-decorator
> errors. Flagging so the architect does not read it as a real mypy regression.

---

## Findings

### A1 — 🟡 **must-fix** · Cross-pipeline IDOR on DELETE/PATCH (P5.1b-5) — concur senior PVI-1; **r0b missed it**

`_delete_schedule` and `_patch_schedule` evaluate the owner gate against the **URL** `pipeline_id`,
then fetch + mutate the schedule by its **global** `schedule_id` with **no check that
`sched.pipeline_id == pipeline_id`**:

```python
pipeline = get_pipeline(writer_conn, pipeline_id)        # pipeline_id from the URL
if pipeline.owner_user_id != _principal.user_id: 403
sched = get_schedule(writer_conn, schedule_id)           # global lookup — parent NOT re-bound
if sched is None: 404
delete_schedule / set_schedule_enabled(writer_conn, schedule_id, …)   # acts on sched by id
```

**Consequence:** a user who owns *any* pipeline `P_self` can `DELETE`/`PATCH` *another owner's*
schedule `S_victim` via `…/pipelines/{P_self}/schedules/{S_victim}` — the gate passes (caller owns
`P_self`), the mutation lands on `S_victim`. This is precisely the cross-tenant bypass the ADR-039 D1 /
ADR-041 D7 fail-closed owner-private posture exists to prevent. The plan's own P5.1b-5 acceptance
("Owner-check reuses **the parent pipeline's** `owner_user_id` — a schedule inherits **its**
pipeline's owner") and ADR-042 D9 ("owner of the **parent** pipeline only") mean the schedule's
*actual* parent (`sched.pipeline_id`), not an arbitrary URL pipeline.

**Severity call (independent):** I rate this **must-fix-before-merge**. Practical reachability is
**low** — `schedule_id` is `psch_`+uuid4 (128-bit, unguessable) and GET only lists the caller's own
schedules, so an attacker must already hold a leaked victim id and own ≥1 pipeline — which is why I
land it 🟡 rather than 🔴, but it is an authorization-correctness gap on the constitutional
owner-private surface and should **not** merge unfixed. GET is already safe (scopes via
`list_schedules_for_pipeline(pipeline_id)`); POST is safe (creates **under** the URL pipeline). Only
the two mutating verbs that accept a `schedule_id` are exposed.

**Why it slipped:** the non-owner-403 tests reuse the **same** `pipe_id` for URL and schedule parent,
so the surface passes; **no cross-pipeline test exists**. The natural disposition is an **α in-cycle
fix** — `if sched.pipeline_id != pipeline_id: raise HTTPException(404)` in both verbs + a
cross-pipeline 404 test — **but the routing is the architect's call; I do not self-route.**

> **Synthesis weight:** senior PVI-1 ✓ + R0-A (me) ✓ — **2-of-3 reviewers**; **r0b did not flag it**
> (its lens was runtime/failure-mode). The independent confirmation raises confidence this is real.

### A2 — 🟡 · Docstring/code mismatch on the missing-pipeline path (P5.1b-4) — concur r0b Y1

`_schedule_act_on_writer`'s docstring (step 2) says the act handles "pipeline missing or disabled
(**still advance next_fire** so re-enable resumes cleanly)". The **code advances `next_fire` only for
the *disabled* case**; for *missing* it `_log.warning(...)` + `return` **before** the step-3 claim.
The code behaviour is the more defensible one (advancing a nonexistent pipeline's timer is pointless),
but the docstring is inaccurate and would mislead a maintainer. **Doc-only** (no runtime impact).

### A3 — 🟡/🟢 · Orphan-schedule perpetual re-discovery (P5.1b-4) — concur senior PVI-3 / r0b Y2

When the parent pipeline is **deleted** but the schedule survives, the act returns without advancing
`next_fire`, so the orphan stays due and is re-discovered + warn-logged **every** sweep tick
(~1 warn/`sweep_interval_s` per orphan), indefinitely. **Spec-faithful** (ADR-042 D4 / plan P5.1b-4
"missing → log + skip") and **benign** (no run fires, no double-fire, ~2 SELECTs/tick) — so not a
drift. It is the resource/log-noise tail of the **already-deferred N3 GC** concern. **A2 and A3 share
one root** (the missing-pipeline branch): r0b's option-(a) one-line fix — advance `next_fire` on
missing too, mirroring the disabled path — **resolves both** (breaks the loop *and* makes the docstring
true). Architect may also route to the cron/GC follow-on, or N3-acknowledge in ADR-042 Consequences.

### A4 — 🟢 · Spine-isolation AST test under-covers (P5.1b-4) — **NOVEL (neither peer raised)**

`test_schedule_sweeper_does_not_call_countdown_spine` AST-walks **only `_schedule_sweeper`** and
asserts zero calls to `_countdown_sweeper`/`_discover_expired_pendings`/`_writer_approve_helper`. But
`_schedule_sweeper` merely dispatches to `_schedule_act_on_writer` — **the act fn is where a future
regression would most plausibly introduce a spine call** (it is the function that does the DB + run
work), and it is **not** covered by the assertion. This is **faithful to ADR-042 D1's literal wording**
("assertion that `_schedule_sweeper` references none of them") and the act is **verifiably spine-free
today** (I read its imports: only `run_pipeline` / `compute_next_fire` / store CRUD). Suggest
broadening the AST assertion to include `_schedule_act_on_writer` + `_rearm_schedules_on_boot` for
stronger fail-on-revert. Non-blocking.

### A5 — 🟢 · GET-on-missing returns `[]` vs 404 elsewhere (P5.1b-5) — concur senior PVI-4

`_list_schedules` returns `[]` (200) for a missing pipeline; POST/DELETE/PATCH (and P5.1a
`_get_pipeline`) return 404. Minor verb inconsistency; no safety impact (an existing pipeline's
non-owner still gets 403). The 403-vs-404 existence-distinction itself is the **established P5.1a
posture** (`_get_pipeline`/`_run` already do it), so this is not a new enumeration regression.

### A6 — 🟢 · Partial index realizes ADR-042 D2 "indexable" (P5.1b-2) — concur senior PVI-2

`CREATE INDEX IF NOT EXISTS idx_pipeline_schedules_due ON pipeline_schedules (enabled, next_fire)
WHERE enabled = 1` is beyond the plan's "DDL exactly the ADR-042 D2 columns" wording, but it
**realizes** the explicit D2 rationale ("gives the sweeper an **indexable** … discovery"). Additive,
idempotent, zero behaviour change. Positive observation, not a scope expansion.

**Concurrence with r0b Y3 (audit gap):** `run_pipeline` + `create_pipeline_run` share one
try/except, so a `create_pipeline_run` failure after a successful `run_pipeline` leaves the run's
(reversible) events in the room with no `pipeline_runs` index row. I concur it is a **real but
non-safety** 🟡 audit-completeness gap, **identical in shape to the existing `_countdown_sweeper`**
error path — architect may split the try or N3-acknowledge in ADR-042 Consequences.

---

## Plan/ADR/routing faithfulness scan

- **Omissions:** none — all 6 atomics + every acceptance criterion present.
- **Expansions:** only the partial index (A6), which realizes a stated ADR-042 D2 intent. No
  out-of-scope file, no opportunistic bundling under deferral language; **cron stays fully deferred**
  (no stub cron path leaked — `validate`/`compute` both reject it, create gates 422).
- **Routed decisions honored:** Y1 interval-only ✓ · Y2 endpoints kept ✓ · N3 room-growth
  ack-deferred-GC present in ADR-042 Consequences ✓.
- **Test discipline:** non-vacuous; the pre-existing `test_schema_has_no_schedule_columns` was
  **correctly evolved** (split to keep the `pipelines`-table-stays-clean intent + added a positive
  side-table existence test) rather than vacuously deleted. The double-fire + boot-re-arm tests are
  fail-on-revert.

---

## Verdict: `needs_architect`

One 🟡 must-fix authorization-correctness finding (**A1** cross-pipeline IDOR on DELETE/PATCH —
confirmed independently, concurring with senior PVI-1, **missed by r0b**) routes the verdict to
`needs_architect`. A2 (docstring) + A3 (orphan loop) share the missing-pipeline root and admit one
combined one-line fix; A4 (test-robustness, novel), A5 (verb cosmetic), A6 (index, positive) are
non-blocking. **All Lens-B / constitutional invariants hold** (spine byte-frozen at function
granularity, `run_pipeline` byte-unchanged, `countdown_auto_fire=None` preserved, no new
`LLMPurpose`, scheduler-OFF byte-identical) and **all three gates are green on my independent run**.

Per ADR-008 Amendment 1 (Route B), R0-A is mandatory regardless of the plan-vs-impl verdict; with
plan-vs-impl + R0-B + R0-A all `needs_architect`, the joint-verdict routes to
`awaiting_architect_decision` (synthesis). The natural disposition for A1 is an **α in-cycle fix**
(guard + cross-pipeline test), but the α/β/γ call — and the severity ceiling on A1 — are the
architect's, not mine.
