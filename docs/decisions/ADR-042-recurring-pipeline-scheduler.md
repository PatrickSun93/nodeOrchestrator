# ADR-042: Recurring pipeline scheduler + schedule persistence + restart re-arm (P5.1b)

**Status:** Accepted (architect, 2026-06-09) — extends ADR-041 per its
D10 ("Extends this ADR (or ADR-042)"). Plan-stage dual-lens cleared (R0-B-on-plan clean +
R0-A-on-plan needs_architect, two surfaced unratified decisions routed in
`docs/process/reviews/P5.1b/architect-routing-on-plan.md`: Y1 cron = (c) interval-only/defer-cron,
Y2 schedule-mgmt endpoints = keep, N3 room-growth = acknowledged deferred-GC; senior absorbed, RC-3:
senior did not self-accept). Originally Proposed (senior-drafted) 2026-06-09. Architect-ratified decision surface
(`docs/process/architect-briefs/P5.1b.md` §"Architect ratification", all-by-lean B0–B6,
commit `811412a`). `requires_cross_family_review: true` (set in `.workflow/P5.1b.yaml`):
plan-stage **dual-lens** required (Lens A = scheduler safety + headless-initiation
correctness; Lens B = spine + auto-fire no-regression). Amendments to ADR-041 / ADR-040 /
ADR-025 are inscribed at impl (plan task P5.1b-6), matching the eventual Accepted status
(the ADR-040 / ADR-039 / ADR-037 precedent). **RC-3: the senior does not self-accept —
the architect Accepts after the dual-lens clears.**

**Scope:** The **recurring loop scheduler** + **schedule-definition persistence** +
**restart re-arm** that make the P5.1a pipeline *unattended on a timer*, not merely
unattended on a manual click. P5.1b adds: (i) a **sibling** in-process background sweeper
(`_schedule_sweeper`) that discovers due+enabled schedules on the reader path and
initiates their pipeline run on the writer; (ii) a **`pipeline_schedules` side table**
(1 pipeline : N schedules) carrying `kind`/`expr`/`next_fire`/`enabled`; (iii) **boot
re-arm** of enabled schedules with **skip-to-next** catch-up; (iv) an **opt-in,
default-OFF** config posture; (v) a minimal **owner-private schedule-management** endpoint
surface so schedules can exist; (vi) the honest **`RB-PIPELINE-SCHED`** residual — the
**first headless *initiation* surface** in the product.

Does **NOT** govern: the **runner** (`run_pipeline` — byte-unchanged; the scheduler is its
**second caller**, ADR-041 D7); the **autonomy gate** (`score`/`decide_tier`/
`emit_gate_decision` — byte-frozen; the timer **actuates, never decides**); the **COUNTDOWN
auto-fire spine** (`_countdown_sweeper` / `_discover_expired_pendings` /
`_writer_approve_helper` — byte-untouched; the sibling shares **none** of it); the
**reversible-only output envelope** (ADR-041 D5 `countdown_auto_fire=None` — preserved, so a
scheduled run can **never** headless-actuate a HARD/irreversible pending); **incremental
feed state** (deferred — B0, each scheduled run reads the full current feed); the
**headless email actuator** (`RB-PIPELINE-EMAIL` — that crossing is P5.1c).

## Context

Verified against `origin/main` @ `811412a` (the P5.1b init / current HEAD; ADR-041 merged
PR #67). ADR-041 was written **inscribe-before-producer** so P5.1b extends a written
contract; the relevant already-decided seams:

- **One run path; the scheduler is its *second caller* (ADR-041 D7).** `run_pipeline(
  pipeline_id, definition, *, deps, owner_user_id)` (`pipeline/runner.py:245-251`)
  **generates its own** `run_id` internally (`:263`) and returns it on
  `PipelineRunResult.run_id` (`:430-439`). The **store** function `create_pipeline_run(
  ..., run_id=...)` is the one that **accepts a caller-supplied `run_id`**
  (`pipeline/store.py:134-165`). The manual `/run` endpoint threads `result.run_id` into
  the store row so the index id == the run-anchor event id (`api/app.py:1687-1694`,
  "F-runid"). **The scheduler replicates exactly this on the writer:** `run_pipeline(...)`
  → take `result.run_id` → `create_pipeline_run(run_id=result.run_id, …)`. It does **not**
  pass a `run_id` *into* `run_pipeline`. `owner_user_id` is a required kwarg stamped via
  `build_user_author` (`runner.py:281`) — for a scheduled run it comes from the **stored
  schedule owner**, not a live principal.
- **Reversible-only output, no headless actuation (ADR-041 D5 — the load-bearing safety
  invariant P5.1b inherits).** The runner calls `process_tool_calls(...,
  countdown_auto_fire=None)` (`runner.py:153,223`); the stamp guard
  (`agents/tool_dispatch.py:133-145`) records `expires_at` **iff** `countdown_auto_fire is
  not None and .enabled`, so **no** pipeline-produced `TOOL_CALL_PENDING` is ever stamped
  → the COUNTDOWN sweeper **cannot** auto-fire any pipeline pending. A HARD tool an analyze
  branch proposes (e.g. `send_email`) just **waits**. **P5.1b preserves this byte-for-byte
  — a *scheduled* run is still reversible-only.**
- **The scheduler PATTERN already exists, fully (ADR-040).** `_countdown_sweeper`
  (`api/app.py:476-539`) + `_discover_expired_pendings` (`:430-473`, reader-path discovery)
  + lifespan start-when-enabled + clean teardown (`:1742-1759`) + `CountdownAutoFireConfig`
  opt-in (`autonomy/config.py:17-30`, default OFF, fail-closed) is a **near-perfect
  template**. P5.1b reuses the *pattern*; the *unit* differs (a standing recurring schedule
  vs a one-shot deadline).
- **Persistence precedents.** Mutable side tables: `users`/`sessions` (ADR-039) and the
  P5.1a `pipelines`/`pipeline_runs` tables (`pipeline/store.py:25-42`, "No schedule columns
  … those are P5.1b"). `init_pipeline_schema` is `CREATE TABLE IF NOT EXISTS` (idempotent),
  called from `_build_context` (`api/app.py:638-641`).

**The boundary this slice turns on.** ADR-040's `RB-AUTOFIRE` posture *actuates an
already-gated `TOOL_CALL_PENDING`* with no human at fire time. P5.1b's scheduler
*initiates a whole **reversible** run* with no human **at start time** — it actuates no
gated pending; the run's only output is the **ungated, reversible** room summary (ADR-041
D5). This is a **different mechanism with a strictly milder blast radius**, yet it is
genuinely the **first thing in the product that *starts work* with no human at start time**
(P4.6's sweeper only *actuated a pre-gated pending*). The constitutional line that keeps
this safe is the inherited `countdown_auto_fire=None`: a scheduled run **cannot** cross
into irreversible actuation. Hold that line and the slice is a *recurring-initiation*
addition over a frozen run path, not a new authorization surface.

## Decisions

### D1. A sibling `_schedule_sweeper` — reuse the ADR-040 *pattern*, share **nothing** spine-critical (B1 = (b))

P5.1b adds a **second** bounded background task, `_schedule_sweeper`, parallel to
`_countdown_sweeper` and built on the **identical lifespan-asyncio shape**:
start-when-enabled (D7), `while True: await asyncio.sleep(interval)` loop,
**discover-on-reader / act-on-writer**, `except asyncio.CancelledError: raise` /
`except Exception: log + continue`, cancelled cleanly in teardown. Its **logic is
independent**: it discovers *due schedules* (not *expired pendings*) and its act is
`run_pipeline` + `create_pipeline_run` + re-arm (D4) — **never** `_writer_approve_helper`.

**The sibling shares NONE of the countdown actuation path.** `_countdown_sweeper`,
`_discover_expired_pendings`, and `_writer_approve_helper` are the `RB-AUTOFIRE` security
crux (still-pending predicate + writer-atomic actuation of a *gated* op). A recurring
schedule shares their *shape*, not their *invariants*. The ~10-line loop skeleton is
**duplicated, not extracted** — consistent with ADR-041 D2's own precedent (duplicate
trivial scaffolding to keep the load-bearing path byte-untouched: **spine-untouched > DRY**
for trivial control flow). A bug in schedule logic therefore **cannot** regress auto-fire
idempotency, because the two sweepers share zero code.

> **P5.1c amendment (ADR-043 D2/D8):** The "never calls `_writer_approve_helper`"
> isolation stated above is **deliberately lifted** for the email actuator in P5.1c.
> `_schedule_act_on_writer` now calls `_actuate_pipeline_emails` (a **dedicated, separate
> function**) as a post-run step (step 6), and `_actuate_pipeline_emails` calls
> `_writer_approve_helper` — but **only for `send_email`** and **only when the schedule
> is opted-in and promoted to live**. The COUNTDOWN spine (`_countdown_sweeper` /
> `_discover_expired_pendings`) stays genuinely uncalled. This is an **intentional lift,
> not a silent bypass**: the isolation test is rewritten honestly in P5.1c-5 to reflect
> the actual invariant (COUNTDOWN spine forbidden; positive pin that the sole new
> actuation reach is `_actuate_pipeline_emails`). Additionally, `pipeline_schedules` gains
> three email opt-in columns (`email_enabled`, `email_mode`, `email_recipient`) via a
> guarded `ALTER TABLE ADD COLUMN` (ADR-043 D5).

**Rejected — (a) generalize the ADR-040 sweeper into one `Scheduler`:** DRY, but couples
two unlike concerns onto spine-critical code and risks regressing the auto-fire spine under
a refactor (a Lens-B hazard). **Rejected — (c) external scheduler** (cron/APScheduler/
separate process): already rejected by ADR-040 D1 (new dependency + deployment surface,
breaks single-process localhost).

### D2. Schedule persistence — a new `pipeline_schedules` side table, 1 : N (B2 = (b))

P5.1a's `pipelines` table is *deliberately* schedule-free. P5.1b adds a **new side table**,
co-located in the main DB via `CREATE TABLE IF NOT EXISTS` (the `init_pipeline_schema`
precedent):

```
pipeline_schedules(
    schedule_id   TEXT PRIMARY KEY,     -- "psch_" + uuid4 hex
    pipeline_id   TEXT NOT NULL,        -- FK → pipelines.pipeline_id
    owner_user_id TEXT NOT NULL,        -- audit owner, stamped at create from the principal
    kind          TEXT NOT NULL,        -- 'interval' | 'cron'
    expr          TEXT NOT NULL,        -- interval seconds (as str) | 5-field cron expr
    next_fire     INTEGER NOT NULL,     -- absolute epoch-ms; hot mutable runtime state
    enabled       INTEGER NOT NULL DEFAULT 1,
    created_at    INTEGER NOT NULL
)
```

**Why a new table, not `ALTER pipelines`.** (i) **1 : N** — a pipeline may carry several
schedules ("hourly weekday + daily weekend"); (ii) it keeps the **two `enabled` meanings
distinct** — `pipelines.enabled` (is this pipeline active) vs `pipeline_schedules.enabled`
(is this timer armed); (iii) it isolates **hot mutable timer state** (`next_fire`, UPDATEd
on every fire) from the **frozen `PipelineDefinition`** (`pipeline/schema.py:31`,
`frozen=True`) — the definition stays frozen; (iv) it gives the sweeper an **indexable**
`WHERE enabled=1 AND next_fire <= ?` discovery rather than a JSON-blob scan.

**Rejected — (a) `ALTER pipelines` ADD COLUMN (1:1):** mechanically supported (the
`memory/store.py:116-130` guarded-ALTER precedent) and lighter, **but** forces strict 1:1
and **collides the two `enabled` meanings** into one column. **Rejected — (c) schedule in
the JSON `definition` blob:** `PipelineDefinition` is `frozen=True` and the JSON column is
non-queryable, so every fire would rewrite the whole definition and the sweeper could not
index due-ness.

### D3. `next_fire` arithmetic is **code**, never an LLM judgment — **interval + cron both implemented** (amended in place by P6.7)

The computation of *when* a schedule next fires — `compute_next_fire(kind, expr, after_ms)`
— is **pure deterministic code** in a new isolated module (`pipeline/schedule.py`):

- **`interval`** (implemented in P5.1b) → `next = after_ms + interval_s * 1000`. UTC epoch-ms;
  the act recomputes from claim-time (D4/D5 skip-to-next), so an interval drifts by up to
  `sweep_interval_s` per fire — the correct price of skip-to-next (computing from the old
  `next_fire` would re-introduce the backfill storm B3 rejects).
- **`cron`** (**implemented in P6.7** — hand-rolled 5-field UTC-only subset; no new dependency):
  - **Fields (5, whitespace-separated):** `minute hour DOM month DOW`. Exactly 5 fields
    required; 4 or 6 → `ValueError`.
  - **Domains:** minute `0-59`, hour `0-23`, DOM `1-31`, month `1-12`, DOW `0-6` (0 = Sunday).
    DOW `7` accepted as a Sunday alias (Vixie convention), normalised to `0` at parse time.
  - **Tokens (compositional, comma-list of terms per field):** `*` (full domain), `a` (single
    value), `a-b` (inclusive range, `a ≤ b`), `*/n` (full domain stepped by `n`), `a-b/n`
    (range stepped by `n`). Step `n ≥ 1`. Numbers only — name tokens (`JAN`/`MON`) excluded.
  - **DOM-vs-DOW union (standard Vixie):** when both DOM and DOW fields are restricted (neither
    is the literal `*`), a minute matches if `DOM matches OR DOW matches`. A `*/n`/range/list
    counts as *restricted* even if it spans the full domain (Vixie flag = literal-`*` test, not
    full-domain-coverage). When exactly one is restricted, only that field constrains. When
    both are `*`, day is unconstrained.
  - **Bounded never-match guard:** forward search capped at `_CRON_SEARCH_HORIZON_MIN = 4 ×
    366 × 24 × 60` minutes (~4 years) to cover legitimate `0 0 29 2 *` (Feb-29-only). On cap
    exhaustion raises `ValueError` (fail-closed — never loops forever). Malformed exprs are
    rejected at validate time and never reach the search.
  - **All calendar arithmetic via stdlib** `datetime` / `timezone.utc` (leap years, month
    lengths, day/hour/minute rollover, year-wrap — not hand-written). Weekday conversion:
    `cron_dow = (dt.weekday() + 1) % 7` (Python Mon=0..Sun=6; cron Sun=0..Sat=6).
  - **UTC-only** — consistent with interval; no timezone token.
  - `validate_schedule_expr("cron", expr)` raises `ValueError` for malformed cron (un-gating
    the 422 for valid cron — D9 narrows from "all cron" to "malformed cron only").

**Historical note (P5.1b interval-only routing, `architect-routing-on-plan.md` Y1 — preserved
for audit trail).** The ratified B2 table named `kind ∈ {interval, cron}`, but *how* to
evaluate cron was never in the decision surface (B0–B6 silent). A hand-rolled 5-field cron
evaluator is exactly the **greenfield-correctness class** P5.1a cyc1 shipped as the
RSS billion-laughs hole; keeping it **out** of the scheduler dual-lens (which exists to
scrutinize the *scheduler*, not a parser) mirrored B0's own discipline of deferring
incrementality to keep the slice tight. Cron evaluation was deferred to P6.7 with a dedicated
greenfield-correctness review; that review has now cleared (P6.7 dual-lens). *(Rejected for
P5.1b: (a) hand-rolled subset — strong runner-up; (b) `croniter` — against 4-dep conservatism,
ADR-040 D1. P6.7 ratified (a) on 2026-06-14 for the same reason: honoring ADR-040 D1 posture.)*

**No new routing `LLMPurpose`.** Cron arithmetic = orchestration = code/config (ADR-041 §9).
The **only** LLM in a scheduled run remains the analyze + reduce content-gen inside the
unchanged `run_pipeline`. The scheduler **actuates, never decides** (ADR-040 D2 framing): the
operator defined the schedule (**when**) and the pipeline (**what**); the timer only
**initiates** the configured run at the configured time.

### D4. Discover-on-reader / act-on-writer; **claim-then-run** re-arm + writer-side authoritative re-check (B1 act-split; the double-fire guard)

Mirroring ADR-040 D1's reader/writer split:

- **Discover (reader, approximate, stale-OK):** `list_due_schedules(reader_conn, now_ms)`
  → `SELECT … WHERE enabled=1 AND next_fire <= ?`. Runs on `reader_executor`; never
  appends. (A pipeline whose `pipelines.enabled=0` is excluded by an act-time re-check, not
  the discovery query — see below.)
- **Act (writer, authoritative, atomic on `writer_executor`, `max_workers=1`):** for each
  discovered `schedule_id`, on the single writer:
  1. **Re-read the schedule authoritatively** (writer connection) and **re-verify**
     `enabled=1 AND next_fire <= now` — the **sole TOCTOU guard** (the reader was stale; a
     human may have disabled/deleted the schedule, or a prior sweep tick already claimed it).
     If not still due → **log + skip** (benign, like the sweeper's `already_resolved`).
  2. **Re-check the parent pipeline:** load via `get_pipeline(writer_conn, pipeline_id)`. If
     the pipeline is **missing** (deleted) → log + **advance `next_fire`** + skip the run
     (breaks the orphan re-discovery loop; A3 routing). If `pipelines.enabled=0` → skip the
     run **but still advance `next_fire`** (so re-enabling resumes cleanly; the disabled
     pipeline simply never runs).
  3. **Claim — advance `next_fire` FIRST** via `update_schedule_next_fire(writer_conn,
     schedule_id, compute_next_fire(kind, expr, now))` (skip-to-next, D5), **before** the run.
  4. **Run:** `run_pipeline(pipeline_id, definition, deps=…, owner_user_id=schedule.
     owner_user_id)` → `create_pipeline_run(writer_conn, run_id=result.run_id, …)`.

**Why claim (advance `next_fire`) *before* run, not after.** A server crash *after*
`run_pipeline` but *before* a deferred re-arm would leave `next_fire` in the past →
**double-fire** on reboot (the recurring analog of ADR-040's double-fire hazard).
Advancing `next_fire` first means a crash mid-run leaves the schedule **already advanced**:
the interrupted run is **dropped, not retried** — exactly the skip-to-next posture (D5). A
partially-appended run's events are reversible room content (ADR-041 D5), harmless. Because
all of `/run`, the countdown fire (`_writer_approve_helper`), and the schedule act share the
**one** `writer_executor`, they **serialize**; the writer-side re-read (step 1) is the
authoritative still-due predicate exactly as the still-pending re-check is for ADR-040.

A scheduled `run_pipeline` occupies the single writer for its duration (`N × per-branch
wall-clock`), the same property a manual `/run` has (ADR-041 D3) — acceptable for infrequent
scheduled analysis; LLM-overlap remains the deferred perf optimization.

### D5. Boot re-arm + catch-up = **skip-to-next** (B3 = (ii)); conservatism inverts vs ADR-040

Because `next_fire` is **mutable side-table state** (D2), re-arm is a plain `UPDATE`,
sidestepping ADR-040's append-only `expires_at` read-time-derivation friction entirely.

- **Boot re-arm (advance-without-running).** At lifespan startup, **before** the sweeper
  task is created, a writer-side step advances **past-due** enabled schedules forward:
  `UPDATE … SET next_fire = compute_next_fire(kind, expr, now) WHERE enabled=1 AND
  next_fire <= now`. Schedules whose `next_fire` is still in the future are left untouched
  (their absolute timestamp is still valid). **The missed-during-downtime fire is dropped,
  not run** — this is what distinguishes boot re-arm from the sweeper's discover-and-*run*.
- **Catch-up = skip-to-next** (D4 step 3 uses the same `compute_next_fire(…, now)`): a
  missed occurrence is never backfilled.

**The conservatism inverts vs ADR-040, deliberately.** ADR-040's conservatism was
"never fire an *irreversible actuation* without a *fresh live cancel window*"
(safety-over-liveness for an irreversible op → re-arm a *fresh full window* and *re-run*).
P5.1b's run is **reversible + safe**, so the conservative direction becomes "**don't run a
stale/wasteful analysis**" → skip-to-next, do **not** run-immediately. Same word
("conservative"), opposite default, because the blast radius differs.

**Rejected — (i) run-once-immediately on boot:** risks a thundering boot-time run on stale
data. **Rejected — (iii) run-all-missed:** a restart-gap thundering herd of stale runs;
almost never wanted for analysis.

### D6. Reversible-only envelope preserved — the scheduler is a *second caller*, `run_pipeline` byte-unchanged (§0 carry-forward)

P5.1b does **not** edit `run_pipeline` or any stage logic. The scheduler is a **second
caller** of the existing run path (ADR-041 D7), threading `result.run_id` into
`create_pipeline_run` exactly as `/run` does (§0). The inherited `countdown_auto_fire=None`
(`runner.py:153,223`) is **preserved**, so:

- A scheduled run **cannot** stamp `expires_at` on any pending → the COUNTDOWN sweeper
  cannot auto-fire any pipeline-produced pending → a scheduled run **cannot headless-actuate
  an irreversible op.** That crossing is **P5.1c** (`RB-PIPELINE-EMAIL`), explicitly out of
  P5.1b.
- The `agent:pipeline` identity keeps its conservative explicit `ThresholdConfig(8, 5, 0)`
  (`runner.py:67`); any HARD tool an analyze branch proposes produces a **waiting** pending,
  exactly as in P5.1a.

This is the load-bearing detail that keeps `RB-PIPELINE-SCHED` **categorically milder** than
`RB-AUTOFIRE` (D8).

### D7. Opt-in, default OFF, fail-closed (B5 = (a))

A config surface mirrors `CountdownAutoFireConfig` exactly: a frozen Pydantic
`PipelineSchedulerConfig{enabled: bool = False, sweep_interval_s: int = 60}`, loaded once at
bootstrap. **Absent file/section ⇒ disabled** (fail-closed); **malformed section ⇒
`ValueError` at startup** (refuse-start, never silently enabled). The `_schedule_sweeper` is
**started in lifespan only when `enabled`**, and **cancelled cleanly in teardown** (the
ADR-040 D7 + lifespan template). Boot re-arm (D5) likewise runs only when enabled.

The honesty weight here is **lower** than `RB-AUTOFIRE` (the output is reversible), so the
opt-in is primarily **liveness/resource control of a second background task** (ADR-025 D6) —
but default-OFF-fail-closed is the consistent, established posture: the system never
*silently* begins firing schedules on a fresh deploy.

**Rejected — (b) default-ON when ≥1 enabled schedule exists:** auto-starts a background task
without an explicit feature-enable; less consistent with the established opt-in posture.

### D8. `RB-PIPELINE-SCHED` — the honest residual (B4 = (a))

> **`RB-PIPELINE-SCHED`** — When the pipeline scheduler is enabled, a configured pipeline
> run **is initiated with no human in the loop at start time**. This is the **first headless
> *initiation* surface** in the product: nothing before P5.1b *starts* a multi-stage run
> with no human present (P4.6's `RB-AUTOFIRE` only *actuated a pre-gated pending*). The
> human-in-the-loop moment moves to the **config-time** acts of defining the schedule
> (**when**) and the pipeline (**what**) and enabling the feature. It is **categorically
> milder than `RB-AUTOFIRE`**, bounded by: **reversible output only** — the run's sole
> output is the ungated room summary (ADR-041 D5); **`countdown_auto_fire=None` preserved**
> — a scheduled run **cannot** headless-actuate any HARD/irreversible pending (the boundary
> P5.1c crosses, not this slice); **opt-in, default OFF** (D7); the **config-time schedule
> owner** stands behind every fire (`owner_user_id`, D4). It pairs with the wave's
> **`RB-PIPELINE-EMAIL`** (P5.1c): `…-SCHED` = reversible *initiation*, `…-EMAIL` =
> irreversible *actuation*.

Inscribed as the **real, milder** posture — **never softened, never over-claimed** (the
"never soften a residual" / roadmap §177 discipline). `RB-AUTOFIRE` lets *no account*
actuate a *gated* op within a window; `RB-PIPELINE-SCHED` lets *no account* *initiate* a
*reversible* run at a configured time — a milder neighbor, named honestly.

**Rejected — (b) no new residual** (it is within ADR-041 D5's already-safe reversible
envelope): defensible (no new authorization, no irreversible surface), but under-names the
"first headless *initiation*" novelty; the RB-* discipline names every human-out-of-loop
step even when bounded.

### D9. A minimal owner-private schedule-management endpoint surface (so schedules can exist)

The sweeper is inert without a way to create schedules; P5.1b ships a thin CRUD, mirroring
ADR-041 D7's "minimal definition CRUD ships so there is something to run" and its
**owner-private** access posture (ADR-041 D7 / R0-A F3) under **fail-closed auth**
(ADR-039 D1 — the principal is server-derived, never from the body):

- **`POST /pipelines/{id}/schedules`** — create a schedule (`validate_schedule_expr(kind,
  expr)` → 422 on malformed; per D3 **valid `kind=cron` is accepted** (P6.7), **malformed cron
  still 422s** — the gate narrows from "all cron" to "malformed cron only"; compute the initial
  `next_fire = compute_next_fire(kind, expr, now)` for both `interval` and `cron`); owner of
  the parent pipeline only (403 otherwise).
- **`GET /pipelines/{id}/schedules`** — list the caller's schedules for that pipeline.
- **`DELETE /pipelines/{id}/schedules/{schedule_id}`** and **`PATCH …`
  (enable/disable)** — owner only.

Access checks reuse the parent pipeline's `owner_user_id` (a schedule inherits its
pipeline's owner). No new auth mechanism. *(Exact verb/shape is an impl detail the plan
fixes; the constitutional point is owner-private + fail-closed + create-time `expr`
validation.)*

### Amendments carried by this slice (inscribed at impl — plan task P5.1b-6)

- **ADR-041 D8** (persistence) — gains the `pipeline_schedules` side table.
- **ADR-041 D10** (deferral) — the scheduler / restart re-arm deferral **lands**: P5.1b
  realized; P5.1c (`RB-PIPELINE-EMAIL`) remains deferred.
- **ADR-040** (note) — the *sibling* `_schedule_sweeper` reuses ADR-040's *pattern* and
  shares **none** of its spine-critical actuation code; `RB-PIPELINE-SCHED` references
  `RB-AUTOFIRE` as the **milder neighbor** (reversible initiation vs gated actuation).

### Amendments carried by P6.7 (inscribed at impl — plan task P6.7-5)

**Amended in place by P6.7** (`plan_has_adr=False`, no new ADR, no Accept gate — same
amendment-in-place weight as the P6.x annotation notes; architect ratification 2026-06-14;
dual-lens reviews the cron correctness + this contract inscription):

- **D3** — flipped from "interval-only; cron deferred" to "cron implemented" with the full
  subset contract inscribed (hand-rolled 5-field UTC-only; tokens `* */n a-b a-b/n a,b,c`;
  domains; DOW `7`=Sun alias; DOM-vs-DOW OR-union; bounded never-match guard; stdlib
  `datetime`/`timezone.utc` for all calendar arithmetic).
- **D9** — 422 gate **narrows** from "rejects all `kind=cron`" to "rejects **malformed** cron;
  valid cron accepted".
- **Reversibility D3 row** — updated to reflect cron now implemented.
- **Consequences "Cron is deferred" bullet** — resolved: cron implemented in P6.7 with the
  dedicated greenfield-correctness dual-lens (R0-A + R0-B). Historical Y1 deferral rationale
  preserved as annotated history in D3 (not erased — the audit trail of the deferral stands).
- **ADR-025 D6** (note) — a **second** bounded background-task surface sits beside the
  single writer: it discovers on the reader path and acts via the writer executor,
  preserving single-writer-consistency + reader-liveness; it must shut down cleanly.

## Considered alternatives

- **B1 (a) generalize the sweeper / (c) external scheduler** — see D1 (couples spine-critical
  code / new dependency + deployment surface).
- **B2 (a) ALTER `pipelines` 1:1 / (c) JSON-blob schedule** — see D2 (`enabled` overload /
  frozen non-queryable definition).
- **B3 (i) run-immediately / (iii) run-all-missed** — see D5 (stale boot-run / restart-gap
  thundering herd).
- **B4 (b) no new residual** — see D8 (under-names the first headless initiation).
- **B5 (b) default-ON-when-schedules-exist** — see D7 (silently starts a background task).
- **B6 (b) amend ADR-041 in place** — rejected: ADR-041 scoped itself "P5.1a only";
  bundling dilutes both records and the focused dual-lens. ADR-042 keeps the scheduler a
  clean, separately-reviewable contract for P5.1c to bind to.
- **D3 cron via hand-rolled 5-field subset / `croniter` (new dep)** — both **rejected for
  P5.1b** (architect-routed Y1 = (c) interval-only): (a) hand-rolled is the strong runner-up
  (honors the no-new-dep posture) but adds the RSS-class greenfield-correctness surface into
  the *scheduler* dual-lens; (b) `croniter` cuts against the 4-runtime-dependency conservatism
  (ADR-040 D1). Cron evaluation is deferred to a focused follow-on; all three options leave the
  schema (D2) + sweeper (D1/D4) + endpoints (D9) unchanged — only `pipeline/schedule.py` differs.

## Consequences

**Easier:**
- A pipeline becomes *unattended on a timer* — operators get recurring scheduled analysis
  (reversible GUI output) with **zero** new authorization surface; the irreversible email
  crossing stays isolated for P5.1c.
- `next_fire` re-arm is a plain `UPDATE` (side-table choice, D2) — no append-only friction.
- The scheduler is a **caller**, not a parallel execution model (ADR-041 D7) — `run_pipeline`
  is byte-unchanged; gating correctness + reversible-only safety are **inherited**.

**Harder / residual:**
- `RB-PIPELINE-SCHED` (D8) — a real, if milder, human-out-of-loop *initiation* posture,
  Accepted not softened.
- A **second** bounded background task joins the lifecycle (ADR-025 D6) — it must shut down
  cleanly and never block the writer (discovery is read-path).
- **Cron implemented** (D3, amended in place by P6.7) — P5.1b was interval-only; the cron
  evaluator (the RSS-class greenfield surface) was deferred to its own follow-on. **P6.7**
  completed that follow-on with the dedicated greenfield-correctness dual-lens: hand-rolled
  5-field UTC-only subset, adversarial correctness suite (C5 boundary/leap/`*/n`/DOM-vs-DOW
  union/year-wrap/malformed-reject/never-match/DST-irrelevance), no new dependency (ADR-040 D1
  posture preserved). Valid cron is now accepted at create (422 narrows to malformed-only).
- The `pipeline_schedules` table + the schedule endpoints add schema + API surface the
  P5.1c extension must respect.
- **Unbounded `FREE_CHAT` room growth under automation (N3 — a conscious deferred concern,
  not a gap).** Each run creates a fresh `FREE_CHAT` room (`runner.py:267-271`); under the
  scheduler this becomes **unbounded over time** (an hourly schedule ≈ 720 rooms/month,
  indefinitely). The output stays reversible (ADR-041 D5), so this is **resource/retention,
  not safety**. Room/run **retention + GC is deliberately deferred** to a later slice (like
  incrementality, B0) — named here explicitly so it is an intentional defer, not an oversight.

**Neutral:** with the scheduler **OFF** (the default) behavior is **byte-identical to
P5.1a** — no sweeper started, no boot re-arm, the new table simply unused; the manual `/run`
path is unchanged. The COUNTDOWN auto-fire spine is **byte-untouched** in either state.

## Reversibility

| Decision | Reversibility |
|---|---|
| D1 sibling sweeper | **Low** — removable (off ⇒ never started); shares nothing spine-critical. |
| D2 `pipeline_schedules` side table | **Medium** — the table shape binds P5.1c; additive, droppable with the feature. |
| D3 `next_fire` arithmetic (code, no LLM; interval + cron both implemented) | **Do-not-reverse** (no-LLM-scheduling is a spine invariant) / **Low** (cron now implemented in P6.7 behind the same `kind` column; the subset contract is inscribed). |
| D4 claim-then-run + writer re-check | **Do-not-reverse** — the still-due re-check + claim-first ordering is the double-fire crux. |
| D5 boot re-arm = skip-to-next | **Low** — a read/UPDATE rule, tunable without schema change. |
| D6 reversible-only / second-caller | **Do-not-reverse** — `countdown_auto_fire=None` is the safety floor P5.1c steps beyond. |
| D7 opt-in default OFF | **Do-not-reverse (default)** — fail-closed default is the honesty mechanism. |
| D8 `RB-PIPELINE-SCHED` residual | **Do-not-reverse** — honest inscription of the real surface. |
| D9 schedule endpoints owner-private | **Low** — opening access later is reversible; tightening after release is not (ADR-041 D7). |

## References

- **ADR-041** (the primitive this extends — D5 reversible-only / `countdown_auto_fire=None`,
  D7 one-run-path / second-caller, D8 persistence, **D10** P5.1b/c deferral) +
  `pipeline/runner.py:153,223,245-263,281,430-439`, `pipeline/store.py:25-42,134-165`,
  `pipeline/schema.py:21-35`, `api/app.py:638-641,1637-1707`.
- **ADR-040** (the *pattern* reused, no code shared — D1 reader/writer sweeper, D2
  actuates-never-decides, D6 boot re-arm, D7 opt-in, **D8 `RB-AUTOFIRE`** the milder
  neighbor) + `api/app.py:430-539,1742-1759`, `autonomy/config.py:17-30`,
  `agents/tool_dispatch.py:133-145`, `config/autonomy.yaml`.
- **ADR-025 D6** (single writer + bounded background tasks the sibling sits beside) +
  `api/app.py:102-130` (`AppContext`), `:654-666` (reader/writer executors).
- **ADR-039** (D1 fail-closed server-derived principal; D6 owner attribution) +
  `api/auth/users.py`.
- **ADR-016** (the guarded `ALTER TABLE ADD COLUMN` precedent — the rejected B2(a) path) +
  `memory/store.py:116-130`.
- **Process:** architect brief / decision-surface `docs/process/architect-briefs/P5.1b.md`
  (B0–B6 + the all-by-lean ratification) + wave brief `docs/process/architect-briefs/P5.1.md`
  (DP2/DP7) + `docs/process/dual-lens-r0b.md`.
</content>
</invoke>
