---
task_id: P5.1b
stage: plan
review: R0-A-on-plan
lens: A (scheduler safety + headless-initiation correctness) + B (spine + auto-fire no-regression)
reviewer: architect-partner
verdict: clean
verdict_history:
  - needs_architect   # original — Y1 cron + Y2 endpoints surfaced for architect routing
  - clean             # RC-10 bump after senior absorbed architect-routing-on-plan.md (2026-06-09)
verify_base: "origin/main @ 1a61036 (HEAD); product seam byte-unchanged since ratification 811412a"
artifacts_reviewed:
  - docs/process/senior-plans/P5.1b.md (6 atomics P5.1b-1..6)
  - docs/decisions/ADR-042-recurring-pipeline-scheduler.md (Status: Proposed)
against:
  - docs/process/architect-briefs/P5.1b.md (decision surface + all-by-lean ratification, B0–B6)
---

# R0-A-on-plan — P5.1b (recurring pipeline scheduler)

Plan-stage review of the senior plan + ADR-042 against the architect-ratified decision
surface (all-by-lean B0–B6, `811412a`). No impl exists yet; this review checks **faithfulness
to the ratified decisions, seam correctness, atomic-split soundness, and completeness/
implementability of ADR-042** — the byte-frozen Lens-B *verification* (vs an actual diff) is
deferred to impl-stage R0-A, but the plan's Lens-B *fencing* is checked here.

## Verdict: `needs_architect`

The plan and ADR-042 are **faithful to every ratified decision (B0–B6)** and the full
constitutional carry-forward, and are **built on a correctly-read seam** (I re-verified the
load-bearing seams at HEAD — see §"Seam verification"). The atomic split is clean and
implementable. **However**, the plan embeds **two decisions that were NOT in the ratified
decision surface** and that the senior **correctly surfaced for an architect call** (it did
not silently improvise — the "surface, don't improvise" discipline held). Those two are
genuine architect decisions, so the verdict is `needs_architect`, not `clean`. Nothing is
wrong or impossible (not `blocking`).

---

## Y-findings (architect routes)

### 🟡 Y1 — Cron-parser mechanism is a real, unratified decision (headline)

**The one item I most want an architect call on — same one the senior flagged (plan §5 #1).**

The ratified **B2** table carries `kind ∈ {interval, cron}`, so cron is *in scope* — but
**how to evaluate cron was never in the decision surface** (B0–B6 are silent on it). The plan
(P5.1b-1) + ADR-042 **D3** choose a **hand-rolled 5-field cron subset, no new dependency**.
Confirmed: the repo has **zero** cron dependency (`pyproject.toml:6-11` = pydantic / httpx /
PyYAML / defusedxml only). So this is a new, unratified call with real consequences:

- **(a) hand-rolled subset (senior's lean, ADR-042 D3)** — consistent with ADR-040 D1's
  no-new-dependency / single-process posture; isolated in `pipeline/schedule.py`. **Cost:** a
  non-trivial evaluator we own + maintain, and a **new greenfield correctness surface**. ADR-042
  D3 itself calls it "the RSS-parser analog of ADR-041" — and that analog is load-bearing:
  P5.1a cyc1 shipped the RSS **billion-laughs** hole that R0-A had to reproduce. A hand-rolled
  cron evaluator is exactly that class of surface.
- **(b) `croniter`** — vetted correctness, less code. **Cost:** a new runtime dependency
  (the thing ADR-040 D1 weighed against) + supply surface; cuts against the project's
  established 4-runtime-dep conservatism.
- **(c) interval-only P5.1b, defer cron** — tightest slice; `kind` column stays for
  forward-compat; cron lands in a focused follow-on. **Cost:** the ratified B2 table named
  *both* kinds, so cron-now was arguably implied.

**My lean: (c), with (a) the strong runner-up.** Reasoning: (c) keeps P5.1b *exactly* the
ratified scope — the scheduler **mechanism** (sibling sweeper + persistence + re-arm +
residual + opt-in), which is what B0–B6 actually decided — and isolates the one greenfield
correctness surface into its own slice with its own focused scrutiny, **mirroring B0's own
discipline** (defer incrementality to keep the slice tight). The scheduler crux is fully
exercisable with interval-only; cron is an orthogonal parser feature. It also keeps the
RSS-class risk *out* of the dual-lens that is meant to scrutinize the scheduler. (a) is
genuinely defensible — it honors the no-new-dep posture and the senior pre-empted the risk
well (the adversarial test list in P5.1b-1 is thorough: boundary rollover, month-end/leap,
`*/n` alignment, DOM-vs-DOW union, year-wrap, ≥6 malformed-reject; UTC-only correctly
sidesteps the DST bug-farm). (b) reject-leaning.

**This is the architect's call** (a dependency-posture + scope decision, like B1's
external-scheduler rejection — not the senior's, not mine). **Blast radius of the call: only
`pipeline/schedule.py` (P5.1b-1).** The senior verified — and I concur — that the table
(P5.1b-2), sweeper (P5.1b-4), and endpoints (P5.1b-5) are **identical under all three
options**; only the arithmetic module swaps.

### 🟡 Y2 — Schedule-management endpoints (P5.1b-5 / ADR-042 D9) — necessary-for-function, but not in B0–B6 (confirm or trim)

The senior flagged this too (plan §5 #2). B0–B6 foreground the table + sweeper + re-arm +
residual + config + ADR — but **not an HTTP surface to create a schedule**. ADR-042 adds
**D9** (a minimal owner-private create/list/delete/enable-disable CRUD) which was **not** a
ratified decision point.

**My lean: keep it.** A scheduler with no create path is **inert** — P5.1b would not be
functional or demoable on its own. D9 is a faithful application of the **ADR-041 D7**
precedent ("minimal CRUD ships so there is something to run"), reuses the existing
owner-private + fail-closed posture correctly (owner inherited from the parent pipeline,
403 for non-owner, server-derived principal per ADR-039 D1 — never from the body), and
validates `expr` at create time (422 on malformed). The PATCH-on-enable `next_fire` recompute
("a long-disabled schedule does not fire immediately", P5.1b-5) is a thoughtful, correct
detail. **But** it adds API surface beyond the ratified surface, so the architect should
**confirm** (or say schedules are to be created another way — seeding / a later slice — in
which case P5.1b-5 drops and the slice is intentionally non-functional-alone).

---

## Notes / minor (not blocking; no routing needed unless the architect disagrees)

- **N1 — Config home (plan §5 #3).** The plan puts config in a dedicated
  `config/pipeline.yaml` + `pipeline/config.py` rather than `config/autonomy.yaml
  §pipeline_scheduler`. **Both** were offered in brief B5, so this is *within* the ratified
  options — not an expansion. Low-stakes; the architect may prefer the `autonomy.yaml` home
  for a tighter `CountdownAutoFireConfig` mirror, but either is faithful. If changed, only
  P5.1b-3 moves.
- **N2 — Interval drift (consequence of skip-to-next).** The act computes `next_fire =
  compute_next_fire(kind, expr, now)` at **claim time** (P5.1b-4 step 3 / ADR-042 D4), where
  `now` is the sweep pick-up time. For `interval` schedules this means the interval is
  measured from actual-claim, so it drifts by up to `sweep_interval_s` (+ writer queueing)
  per fire. This is the **correct** price of the ratified skip-to-next posture (B3) — computing
  from the old `next_fire` would re-introduce the backfill-storm B3 rejects — and is harmless
  for analysis cadence. Worth one line of doc-comment in `schedule.py`; not a correctness issue.
- **N3 — Unbounded room growth (a new automation consequence, absent from ADR-042
  Consequences).** Each run creates a fresh `FREE_CHAT` room (`runner.py:267-271`). Under P5.1a
  this was human-paced (manual `/run`); under the scheduler it becomes **unbounded over time**
  (an hourly schedule ≈ 720 rooms/month, indefinitely). Output stays reversible (ADR-041 D5),
  so this is **resource/retention**, not safety — and retention is plausibly a separate
  deferred concern (like incrementality). But it is a genuine "what changes when you automate"
  consequence the ADR's **Consequences** section does not name. Recommend a one-line
  acknowledgement there (deferred-GC is fine); flagging so it is a conscious defer, not a gap.
- **N4 — Dual-lens stage.** ADR-042's header says "plan-stage dual-lens required." That is in
  fact happening — `R0-B-on-plan.md` is already present alongside this review — so the wording
  is accurate. (The brief's lifecycle line also lists `R0-A ∥ R0-B` at impl; both stages
  carrying the dual-lens is consistent, not contradictory.) No action.

---

## Verified clean (the faithfulness + seam checks that passed)

**Faithfulness to ratified B0–B6 — all honored:**

| Ratified | Where realized | Faithful? |
|---|---|---|
| B0 defer incrementality | ADR Scope ("each scheduled run reads the full current feed"); no cursor work in any atomic | ✅ |
| B1 sibling `_schedule_sweeper`, share **nothing** spine-critical | ADR D1 + P5.1b-4 ("imports/calls none of `_countdown_sweeper`/`_discover_expired_pendings`/`_writer_approve_helper`"; grep/AST Lens-B test) | ✅ |
| B2 new `pipeline_schedules` 1:N side table; frozen `PipelineDefinition` untouched | ADR D2 + P5.1b-2 (DDL = the ratified columns; `CREATE TABLE IF NOT EXISTS`, no ALTER) | ✅ |
| B3 boot re-arm = plain UPDATE + skip-to-next | ADR D5 + P5.1b-4 `_rearm_schedules_on_boot` (advance-without-running `WHERE enabled=1 AND next_fire<=now`) | ✅ |
| B4 `RB-PIPELINE-SCHED` honest/milder, never softened, `countdown_auto_fire=None` preserved | ADR D8 (inscribed as the real, milder posture; bounded by reversible-only + `countdown_auto_fire=None` + opt-in + config-time owner; pairs with `RB-PIPELINE-EMAIL`) | ✅ |
| B5 default OFF, fail-closed, mirror `CountdownAutoFireConfig` | ADR D7 + P5.1b-3 (`enabled=False`, absent→disabled, malformed→ValueError, start-when-enabled, clean teardown) | ✅ |
| B6 ADR-042 + amend ADR-041 D8/D10 + ADR-040 + ADR-025 D6 | ADR "Amendments carried" + P5.1b-6 | ✅ |

**Constitutional carry-forward — all fenced (verification deferred to impl R0-A where a diff exists):**

- **`run_pipeline` byte-unchanged / second-caller.** Verified the seam is exactly as the
  plan/ADR describe (correcting any dispatch shorthand): `run_pipeline(pipeline_id,
  definition, *, deps, owner_user_id)` **self-generates** `run_id` (`runner.py:263`) and
  returns it (`PipelineRunResult.run_id`, `runner.py:430-439`); `create_pipeline_run(...,
  run_id=...)` **accepts** a caller id (`store.py:134-165`); the `/run` endpoint threads
  `result.run_id` into the store row with `status="completed" if result.succeeded else
  "failed"` (`app.py:1687-1694`). **The plan's act (P5.1b-4 step 4) replicates this exactly**
  and constructs `PipelineDeps` identically (`app.py:1668-1683`). The scheduler never passes a
  run_id *into* `run_pipeline`. ✅
- **Reversible-only / `countdown_auto_fire=None`.** Confirmed `run_pipeline` calls
  `process_tool_calls(..., countdown_auto_fire=None)` (`runner.py:153,223`) and the stamp
  guard records `expires_at` **iff** `countdown_auto_fire is not None and .enabled`
  (`tool_dispatch.py:137-145`) — so a scheduled run **cannot** auto-fire any HARD pending; the
  irreversible crossing stays P5.1c. The scheduler is a caller, so this holds by construction. ✅
- **No new routing `LLMPurpose`.** Baseline confirmed clean: `pipeline/` uses **only**
  `LLMPurpose.AGENT_RESPONSE` (content-gen) at `runner.py:121,190,382`. The arithmetic module
  (P5.1b-1) is pure code, no LLM — cron/interval = code (ADR D3). ✅
- **Spine byte-frozen.** P5.1b-4 out-of-scope explicitly fences `run_pipeline`,
  `_countdown_sweeper`, `_writer_approve_helper`, the gate; §4 pins Lens-B byte-frozen
  assertions (`_execute_local_call`/`score`/`decide_tier`/`emit_gate_decision` + the countdown
  sweeper) + a scheduler-OFF ⇒ byte-identical-to-P5.1a test. ✅ (Plan intent correct; the
  actual byte check runs at impl R0-A.)
- **Single-writer + reader-liveness.** ADR D4 + P5.1b-4: discover on `reader_executor` via
  `list_due_schedules`, act on `writer_executor`; `get_reader_conn()` confirmed present
  (`app.py:141`). ✅

**Seam verification (re-read at HEAD `1a61036`).** `git diff 811412a HEAD -- src tests config`
is **empty** — the plan/ADR commits (`3149da4`, `1a61036`) are **docs/state-only**, so every
product line the plan cites is byte-unchanged since ratification; the plan's `verify_base` is
sound. The sweeper pattern (`_countdown_sweeper` loop body + reader-discover/writer-act +
lifespan start-when-enabled + clean teardown, `app.py:476-539,1742-1759`), the
`CountdownAutoFireConfig` mirror (`autonomy/config.py:17-57`), the `AppContext` config field
(`app.py:125`) + `_build_context` load point (`app.py:638-641,674-675`), and the
`CREATE TABLE IF NOT EXISTS` persistence precedent (`store.py:25-51`) all match the plan's
citations. ✅

**Atomic split — sound.** `{P5.1b-1 ∥ 2 ∥ 3} → 4 → 5 → 6` is clean: one commit = one subject
(RC-17); the `api/app.py` serialization caveat (3/4/5 all edit it) is correctly called out;
dependencies (4 needs 1's arithmetic + 2's due-query + 3's config field; 5 needs 1+2) are
respected by the order. P5.1b-4 is the heaviest atomic (sweeper + discover + boot re-arm +
lifespan + both test lenses) but is cohesive ("the sweeper"); splitting would create
artificial seams (boot re-arm is untestable without the sweeper context). Acceptable. ✅

**Double-fire / TOCTOU correctness (Lens A) — the load-bearing invariant, well-specified.**
ADR-042 D4 + P5.1b-4 get the ordering right: writer-side authoritative **re-read** (still
`enabled=1 AND next_fire<=now`) → pipeline re-check (missing→skip; `pipelines.enabled=0`→
advance-without-run) → **claim `next_fire` BEFORE the run** → run. Claim-before-run is the
correct crux: a crash mid-run leaves `next_fire` already advanced ⇒ the interrupted run is
dropped, not double-fired on reboot (skip-to-next, D5) — and all of `/run`, the countdown fire,
and the schedule act share the single `writer_executor`, so they serialize. The
fail-on-revert discipline (each Lens-A guard test must fail if the guard is removed — esp. the
claim-before-run double-fire test and the boot-re-arm-without-run test, P5.1b-4 + §4) is
explicitly carried from the P5.1a cyc3 lesson. ✅

---

## Summary for the architect

Plan + ADR-042 are **faithful, seam-correct, and implementable**. Route the two Y-findings:

- **Y1 (cron mechanism)** — the real call. (a) hand-rolled / (b) `croniter` / (c) interval-only-defer-cron. My lean **(c)** (slice-isolation, keeps P5.1b the ratified scheduler-only scope, isolates the RSS-class greenfield surface), **(a)** strong runner-up. Blast radius: only `pipeline/schedule.py`.
- **Y2 (endpoints)** — confirm the D9 owner-private CRUD stays (my lean: keep — the scheduler is inert without it), or trim if schedules are created elsewhere.

Then the ADR-042 **Accept** is yours (RC-3 — not the senior, not me; the junior leaves it
`Proposed`, P5.1b-6). N1–N4 are notes (N3 — the unbounded-room consequence — is the one worth
a one-line ADR Consequences acknowledgement).

---

## RC-10 absorption (senior, 2026-06-09) — verdict bumped `needs_architect` → `clean`

Architect routing (`architect-routing-on-plan.md`) absorbed into the plan + ADR-042 (both on
`main`, no impl branch yet):

- **Y1 = (c) interval-only, defer cron.** P5.1b-1 narrowed to interval-only
  (`kind=cron` → `ValueError`/`NotImplementedError`); ADR-042 **D3** rewritten (cron deferred
  to a follow-on, `kind` column retained forward-compat, schema/sweeper/endpoints unchanged);
  P5.1b-5 + D9 reject `kind=cron` at create with **422**; the cron adversarial-test list
  dropped, interval boundary/overflow tests kept, UTC-only retained.
- **Y2 = keep.** P5.1b-5 + ADR-042 D9 unchanged.
- **N3 = ack-deferred-GC.** One line added to ADR-042 **Consequences** naming the unbounded
  `FREE_CHAT` room growth as a conscious deferred retention/GC concern (not a gap).
- **N2.** The interval-drift-from-claim-time doc-comment is now an explicit P5.1b-1 acceptance
  criterion (the correct price of skip-to-next). **N1/N4** — no action (within ratified B5 /
  accurate as written).

RC-3: ADR-042 stays **Proposed** — the architect Accepts; the senior does not self-accept.
</content>
