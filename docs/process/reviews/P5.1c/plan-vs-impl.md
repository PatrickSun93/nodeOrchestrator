---
task_id: P5.1c
stage: plan-vs-impl
actor: senior
date: "2026-06-11"
cycle: 2
verdict: clean
reviewed_branch: origin/claude/P5.1c-impl
reviewed_commit: c658685
prev_cycle_commit: 4f08f20
plan: docs/process/senior-plans/P5.1c.md
adr: ADR-043
routing_absorbed: docs/process/reviews/P5.1c/architect-routing-on-impl.md
supersedes: "cycle-1 plan-vs-impl (verdict needs_architect @ 4f08f20)"
summary: >
  Cycle-2 all-α rework verified against the architect impl-stage routing. The
  cycle-2 diff is exactly the 4 routed files (ADR-043 D6 text + app.py +12 + 2
  test files) — zero scope creep, frozen spine still zero-diff vs main. All four
  routed dispositions landed faithfully: Y1 (ADR-043 D6 amended to the
  callsite-enforcement pattern + the shared-OBSERVATION-conflict rationale, no
  code change), Y2 (live gate now mirrors the dry-run both-non-empty guard), Y3
  (unknown email_mode fails closed via explicit `!= "live"`), and the
  cross-pipeline IDOR tests on all 3 email endpoints. The cycle-1 surfaced 🟡
  (PvI-Y1) is resolved per the architect's blessed disposition. One residual 🟢
  doc-accuracy nit (the amended D6 text + the event.py comment name
  `model_validate()` as the enforcement, but the production write-callsite enforces
  via the constructor; `model_validate` is the test-only round-trip) — non-blocking,
  rides a future doc-touch. Verdict clean.
findings:
  - id: PvI2-G1
    severity: green
    title: ADR-043 D6 text + event.py comment name model_validate() as enforcement, but the production write-callsite enforces via the constructor (model_validate is test-only)
resolved_from_cycle_1:
  - id: PvI-Y1
    disposition: resolved (architect routed α-doc; ADR-043 D6 amended to callsite-enforcement pattern)
  - id: PvI-G1
    disposition: resolved (3 cross-pipeline IDOR tests added — optin/promote/disable → 404)
  - id: PvI-G2
    disposition: not routed for action; remains as the cycle-1 belt-and-suspenders note (non-blocking)
---

# P5.1c — Senior plan-vs-impl review (cycle 2, re-review)

**Branch reviewed:** `origin/claude/P5.1c-impl` @ `c658685` (read via
`git diff 4f08f20..origin/claude/P5.1c-impl` and `git diff origin/main...` from
`main`; no checkout — shared worktree).

**Supersedes:** the cycle-1 plan-vs-impl review (`verdict: needs_architect` @
`4f08f20`), whose single 🟡 (PvI-Y1) was routed all-α by the architect
(`architect-routing-on-impl.md`). This cycle verifies the rework against that
routing.

**Scope of the cycle-2 diff (4 files, all routed):**

| File | Change | Routed item |
|---|---|---|
| `docs/decisions/ADR-043-headless-pipeline-email.md` | D6 paragraph rewritten (1 line replaced) | Y1 (α-doc) |
| `src/orchestrator/api/app.py` | +12 lines: fail-closed `elif != "live"` branch + both-non-empty live gate | Y3 + Y2 (α) |
| `tests/api/test_pipeline_email_actuator.py` | +48: `test_unknown_email_mode_does_not_actuate` | Y3 test (α) |
| `tests/api/test_schedule_endpoints.py` | +59: 3× `test_email_*_cross_pipeline_idor_404` | IDOR test (α) |

No fifth file. **Zero plan-external expansion.** The byte-frozen spine
(`pipeline/runner.py`, `agents/tool_dispatch.py`, `tools/executor.py`,
`autonomy/scoring.py`) remains **zero-diff vs `origin/main`** — re-confirmed this
cycle.

---

## 1. Per-routed-item fidelity

### Y1 — TYPED_METADATA → ADR-043 D6 text (α, doc-only) ✅ faithful

The architect routed: *"the impl is correct (callsite-typed enforcement);
registering `OBSERVATION → PipelineEmailDryRunMeta` would break every other
free-form OBSERVATION event; amend ADR-043 D6 to describe the
callsite-typed-enforcement pattern + the shared-OBSERVATION-conflict rationale;
**no code change**."*

The cycle-2 D6 amendment does exactly this:
- Names the enforcement as **callsite-typed construction** — the actuator
  constructs `PipelineEmailDryRunMeta(...)` directly + `model_dump()` before
  storing. (Accurate: `app.py:756`.)
- States the **infeasibility rationale** precisely: `validate_metadata()` applies
  the registered schema to *every* OBSERVATION event at append, so all
  pre-existing free-form OBSERVATION producers (runner output, MCP interpret)
  would fail validation.
- Keeps the **scope-narrowing** intact: reuses the existing `OBSERVATION`
  EventType, no new `EventType`; `OBSERVATION` stays free-form in
  `TYPED_METADATA`.
- Points at the `core/event.py` code comment that names the callsite enforcement
  as the explicit design choice (the comment exists, `event.py:432-434`).

**No code change** — verified: the cycle-2 diff touches no `src` file other than
`app.py`, and `event.py` is byte-unchanged. ✅

This resolves cycle-1 **PvI-Y1** per the architect's blessed disposition
(callsite-validation accepted as faithful; ADR text brought into line). One
residual prose nit (PvI2-G1, §3) — non-blocking.

### Y3 — unknown email_mode fails closed (α) ✅ faithful

`app.py:679-686` adds, between the dry-run branch and the live gate:

```python
elif schedule.email_mode != "live":
    # Unknown mode — fail-closed (ADR-043 D5: live requires email_mode explicitly set).
    _log.debug(...); continue
```

The branch order is now: `email_enabled` early-return → `== "dry_run"` record →
`!= "live"` skip (fail-closed) → **only `== "live"` reaches actuation**. An
unknown/garbage `email_mode` no longer falls through to send. This matches the
routed disposition (explicit `== "live"`, fail-closed-on-unknown at the
irreversible crossing) and ADR-043 D5. The test
`test_unknown_email_mode_does_not_actuate` corrupts `email_mode` to
`"bogus_unknown"` via direct SQL, runs the actuator, and asserts **0 TOOL_CALL
and 0 OBSERVATION** — faithfully pinning that an unknown mode neither actuates nor
records. ✅

### Y2 — live gate both-non-empty (α) ✅ faithful

`app.py:689` changes the live eligibility gate from
`pending_to.lower() != pinned.lower()` to:

```python
if not (pending_to and pinned and pending_to.lower() == pinned.lower()):
    ... continue
```

This mirrors the dry-run path's `would_actuate` guard exactly (`app.py:754`:
`bool(pending_to and pinned and pending_to.lower() == pinned.lower())`), closing
the divergence flagged by R0-A: an empty pinned recipient or empty pending `to`
can no longer satisfy the live gate by lowercasing two empty strings to equality.
The two paths now share one predicate shape. ✅ Matches ADR-043 D3/D5.

### IDOR test — cross-pipeline 404 on the 3 email endpoints (🟢→α) ✅ faithful

`test_schedule_endpoints.py` gains `test_email_optin_cross_pipeline_idor_404`,
`test_email_promote_cross_pipeline_idor_404`,
`test_email_disable_cross_pipeline_idor_404`. Each creates a schedule under
`pipe_other`, then hits the endpoint under `pipe_self`'s URL with `pipe_other`'s
`schedule_id` and asserts **404** — exercising the `sched.pipeline_id !=
pipeline_id → 404` guard that the cycle-1 review confirmed was already
implemented in all three endpoints. This is the **P5.1b A1** cross-pipeline
authorization test the architect routed in. The promote case correctly opts-in
under the *correct* pipeline first so the schedule is promote-eligible, isolating
the IDOR path (not a 409). ✅ Resolves cycle-1 **PvI-G1**.

### R0B-Y2 codegen overshoot — accept (hygiene)

Routed `accept-as-is`; no rework expected and none present. ✅

---

## 2. Byte-frozen surface re-scan

`git diff origin/main...origin/claude/P5.1c-impl` on the frozen set returns
**zero diff-lines** (re-confirmed this cycle):

| Surface | Result |
|---|---|
| `pipeline/runner.py` (incl. `run_pipeline`, `countdown_auto_fire=None`) | **0** ✓ |
| `agents/tool_dispatch.py` (RB-AUTOFIRE `expires_at` stamps) | **0** ✓ |
| `tools/executor.py` (`_execute_local_call`) | **0** ✓ |
| `autonomy/scoring.py` (`score`/`decide_tier`/gate) | **0** ✓ |

No new routing `LLMPurpose`; the crossing remains the narrow post-run
authorization layer (`_actuate_pipeline_emails` + `_record_email_dry_run` + step-6
wiring) reaching only the non-frozen `_writer_approve_helper`.

---

## 3. Findings

### 🟢 PvI2-G1 — D6 text + event.py comment name `model_validate()` as enforcement, but the production write-callsite enforces via the constructor

The amended D6 text says *"the reader calls
`PipelineEmailDryRunMeta.model_validate(event.metadata)` to round-trip-validate"*
and the `event.py:432-434` comment says enforcement is *"at callsites via explicit
`PipelineEmailDryRunMeta.model_validate()`"*. In the production code:

- **Write-time** enforcement is real and is via the **constructor** —
  `_record_email_dry_run` builds `PipelineEmailDryRunMeta(...)` then `model_dump()`
  (`app.py:756`). A schema drift fails here, at construction.
- There is **no production reader** that calls `model_validate` — a `git grep`
  across `src` finds `PipelineEmailDryRunMeta` only at the class def, the write
  construction, and docstrings/comments. The `model_validate` round-trip exists
  **only in the test** (`test_pipeline_email_dry_run_meta_schema`).

So the *invariant* the architect blessed (typed, structurally-enforced dry-run
record) holds — write-time construction is the actual guard. The prose just names
the test-only round-trip (`model_validate`) as if it were the production
enforcement/reader. This is a wording imprecision **within an already-blessed
mechanism**, not an invariant drift or a correctness hole.

**Disposition:** non-blocking 🟢. A one-line tighten ("write-time enforced via
construction; read-time `model_validate` round-trip exercised in tests") can ride
any future doc-touch. **Not worth a rework cycle** — P5.1 closes on this merge.
Surfaced for the record, not for routing.

### Carried from cycle-1 (no action this cycle)

- **PvI-G2** (two Lens-B supplementary tests assert substring/token presence, not
  byte content) — not routed for action; the real guards are the existing
  constitutional/byte-frozen tests (§2 zero-diff). Remains as the cycle-1
  belt-and-suspenders note. Non-blocking.

---

## 4. Verdict

**`clean`.** The cycle-2 all-α rework landed all four routed dispositions
faithfully (Y1 doc-only D6 amendment, Y2 both-non-empty, Y3 fail-closed, the 3
cross-pipeline IDOR tests), with **zero scope creep** (exactly the 4 routed
files), the byte-frozen spine **still zero-diff vs main**, no new `LLMPurpose`,
and no further ADR amendment beyond the routed Y1 D6 text. Cycle-1's single 🟡
(PvI-Y1) is resolved per the architect's blessed disposition. The one residual is
a 🟢 doc-accuracy nit (PvI2-G1) that does not block.

Per ADR-008 Amendment 1 (Route B) the state advances to `awaiting_R0_A` for the
cycle-2 dual-lens re-review.
