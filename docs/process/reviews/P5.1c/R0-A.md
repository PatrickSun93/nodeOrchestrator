---
task_id: P5.1c
stage: impl (R0-A on impl) — cycle 2 re-review (all-α rework)
reviewer: architect-partner (R0-A)
verdict: clean
verified_against: >
  origin/claude/P5.1c-impl @ c658685 (cycle-2 rework, single commit on 4f08f20);
  cycle-2 delta git diff 4f08f20..c658685; full origin/main...c658685 (origin/main @ 04e16d6);
  cycle-1 R0-A (this file, prior revision — 0🔴 · 3🟡) + architect-routing-on-impl.md (all-α)
gates: "ruff check clean · ruff format = pre-existing backlog only (P5.1c files zero new debt) · mypy --strict clean (305 files) · pytest 2459 passed (EXIT=0, full suite); independent run, detached worktree @ c658685, uv sync --all-extras"
cycle1_resolution:
  Y1-dryrun-meta-not-in-typed-metadata: "RESOLVED (α-doc) — ADR-043 D6 text amended to describe callsite-typed construction + shared-OBSERVATION infeasibility rationale; no code change; core/event.py:431-434 comment it cites genuinely exists"
  Y2-live-gate-omits-both-non-empty: "RESOLVED (α) — live gate now `not (pending_to and pinned and pending_to.lower()==pinned.lower())` (app.py:691), byte-identical to dry-run would_actuate (app.py:754); paths cannot diverge"
  Y3-live-branch-fail-open-on-unknown-mode: "RESOLVED (α) — explicit `elif email_mode != 'live': continue` fail-closed (app.py:679-687); only `== 'live'` reaches actuation; guarded by test_unknown_email_mode_does_not_actuate"
  cross-pipeline-idor-test: "RESOLVED (🟢→α) — 3 tests (optin/promote/disable) assert cross-pipeline schedule → 404; endpoint guards confirmed at app.py:2428/2487/2549"
findings: "0🔴 · 0🟡 (cycle-2 introduces none; all cycle-1 items resolved)"
---

# R0-A on impl — P5.1c headless pipeline email — **cycle 2 (all-α rework re-review)**

Re-review of the single cycle-2 rework commit **`c658685`** against the cycle-1 routing
(`architect-routing-on-impl.md`, all-α). Read `git diff 4f08f20..c658685` for the delta and
`origin/main...c658685` for the full crossing from `main` (no checkout, shared worktree); canonical
gates re-run independently in an isolated detached worktree (`uv sync --all-extras`). The rework
**faithfully absorbs all five routed dispositions, touches nothing outside the routed scope, keeps the
byte-frozen spine intact, and introduces no new findings.** **Verdict: clean.**

The cycle-2 delta is exactly the routed surface — **4 files, +118/−3**: `ADR-043` D6 text (Y1),
`app.py` +12 (Y2 + Y3, both inside `_actuate_pipeline_emails`), and two test files (the Y3 guard +
the 3 cross-pipeline IDOR tests). No spine file, no `core/event.py` code, no `openapi.json`/`schema.ts`
re-touch, no `.workflow/` commit. Nothing opportunistic rode along.

## Cycle-1 findings — resolution verified

### Y3 (fail-open → fail-closed on unknown `email_mode`) — RESOLVED ✓

The live branch is no longer entered by negation. `_actuate_pipeline_emails` now discriminates the
mode **explicitly** (`app.py:670-687`):

```python
if schedule.email_mode == "dry_run":
    _record_email_dry_run(...); continue
elif schedule.email_mode != "live":
    # Unknown mode — fail-closed (ADR-043 D5: live requires email_mode explicitly set).
    _log.debug("... unknown email_mode=%r ... skipping (fail-closed)", ...); continue
# live mode falls through — reachable ONLY when email_mode == "live"
```

Any value that is neither `"dry_run"` nor exactly `"live"` (`""`, `"LIVE"`, a botched-migration
default, a future 4th state) now **fails closed — no actuation, no observation**. This is the
fail-closed-on-unknown posture ADR-043 D5 demands at the irreversible crossing.

**Guard test is real, not vacuous** — `test_unknown_email_mode_does_not_actuate`
(`test_pipeline_email_actuator.py:519`): opts a schedule in (`email_enabled=True`), then corrupts
`email_mode` to `'bogus_unknown'` via direct UPDATE, appends a `send_email` pending whose `to`
**matches** the pinned recipient (so the *only* thing preventing a send is the fail-closed branch),
runs the actuator, asserts `0 TOOL_CALL` **and** `0 OBSERVATION`. Verified executed + passing
(`4 passed` on the targeted run).

### Y2 (live gate omits "both non-empty") — RESOLVED ✓

The live eligibility gate (`app.py:689-691`) now reads:

```python
pending_to = str(meta.params.get("to", "")); pinned = schedule.email_recipient or ""
if not (pending_to and pinned and pending_to.lower() == pinned.lower()): continue
```

This predicate is **byte-identical** to the dry-run path's `would_actuate` computation
(`_record_email_dry_run`, `app.py:754`: `bool(pending_to and pinned and pending_to.lower() ==
pinned.lower())`). The live gate and the dry-run preview now apply the same both-non-empty +
case-insensitive rule and **cannot diverge** — closing the cycle-1 faithfulness/consistency gap. As
noted cycle-1, both-empty remains structurally unreachable through the supported surface
(`_EmailOptinRequest.email_recipient` is `Field(min_length=1)`), so this is a defense-in-depth +
preview-fidelity tightening; the existing live-mismatch / case-insensitive / dry-run-mismatch tests
(`test_live_mode_recipient_mismatch_stays_waiting`, `…case_insensitive_recipient_match`,
`test_dry_run_would_actuate_false_on_mismatch`) continue to pin the shared predicate. (A dedicated
both-empty-live test isn't added — acceptable: unreachable scenario, identical predicate already
covered via the dry-run path.)

### Y1 (ADR-043 D6 mechanism infeasible-as-written) — RESOLVED ✓ (doc-only; no code change)

`core/event.py` is **zero-diff this cycle** (confirmed — the cycle-2 delta does not touch it), so the
correct callsite-typed-construction impl stands untouched, as routed. ADR-043 **D6 text is amended**
to match the sound code: the false "**registered in `TYPED_METADATA`** (`core/event.py:394`) —
structurally enforced" clause is replaced with a description of **callsite-typed construction**
(actuator builds `PipelineEmailDryRunMeta(...)` + `model_dump()` on write; reader
`model_validate()`s on read) **and** the shared-`OBSERVATION` infeasibility rationale (registering
`OBSERVATION → PipelineEmailDryRunMeta` would force every free-form `OBSERVATION` — runner output, MCP
interpret — to validate against it and fail at append; a new `EventType` is out of scope). The ADR
now also points at the in-code NOTE. I verified that NOTE **genuinely exists** at
`core/event.py:431-434` ("OBSERVATION is not globally registered here … enforced at callsites via
explicit `PipelineEmailDryRunMeta.model_validate()` (ADR-043 D6)") — the ADR no longer describes a
mechanism the code doesn't use, and it carries no stale `:394` line-ref. Faithful to the routed intent
("make the ADR match the sound code").

> **Inscription note for the Accept moment (not a finding).** The D6 fix is an **in-place edit of an
> Accepted ADR's own decision text** (the infeasible clause is replaced, not annotation-preserved —
> unlike the cycle-1 P5.1c-6 amendments to *other* ADRs, which were additive blocks preserving
> originals). This is consistent with the routed intent (a factually-infeasible mechanism description
> shouldn't be preserved verbatim), and the architect explicitly routed Y1 as α-doc — so it is
> architect-directed, not self-routing (RC-3 honored). Flagging only so the architect **re-ratifies the
> D6 body at Accept** and decides whether the Status line / amendment-history should log "D6 text
> corrected at cycle-2 per impl-routing Y1" (currently the Status line is unchanged from the original
> Accept).

### 🟢→α cross-pipeline IDOR test — RESOLVED ✓ (the P5.1b A1 lesson)

Three tests added (`test_schedule_endpoints.py`), one per email endpoint —
`test_email_{optin,promote,disable}_cross_pipeline_idor_404`. Each creates **two pipelines under the
same owner** (`_USER_A`), a schedule under `pipe_other`, then drives the email op via `pipe_self`'s URL
with `pipe_other`'s `schedule_id` and asserts **404**. The same-owner construction isolates the
**cross-pipeline** dimension specifically (not cross-user) — exactly the P5.1b A1 gap. I confirmed the
endpoint guards the test pins genuinely exist: each handler does `if sched.pipeline_id != pipeline_id:
raise HTTPException(404, …)` at **`app.py:2428` (optin) / `:2487` (promote) / `:2549` (disable)**,
returning the same "not found" detail as the absent-schedule case (no existence leak). Guard + test
both present.

## Byte-frozen spine — re-confirmed (cycle-2 changed nothing here)

The cycle-2 delta is confined to `_actuate_pipeline_emails` (+ADR +tests); I re-verified the full
`origin/main...c658685` spine set regardless:

- **Constitutional gate / executor** — no `autonomy/*.py`, no `tools/executor.py` in the diff →
  `_execute_local_call` and the scoring/HARD-guard gate are byte-frozen. `tests/core/test_constitution.py`
  is **not in the diff** → the HARD-never `send_email` field-set pin is untouched and still passes (full suite).
- **COUNTDOWN spine** — `_countdown_sweeper` and `_discover_expired_pendings` extracted from both
  refs and **`diff` is empty** (byte-identical); `run_pipeline` `countdown_auto_fire=None`
  (`pipeline/runner.py`) **not in the diff**.
- **Existing approve callers** — the `human` caller (`app.py:1653`) and the `auto_timer` caller
  (inside the byte-identical `_countdown_sweeper`, `app.py:562`) are unchanged. The only spine-adjacent
  edits remain the two **ratified** `Literal` widenings to admit `"auto_pipeline"`
  (`_writer_approve_helper` signature + `ToolCallMeta.approval_source`) — the **mechanism ADR-043 D2
  prescribes**, with the helper body and the `ToolCallMeta` field-set otherwise byte-unchanged. Not a
  spine violation.
- **No new routing `LLMPurpose`** — recipient is owner-config, not an LLM judgment; unchanged.

## R0B-Y2 codegen overshoot — accepted as hygiene (per routing), not re-touched

The routing accepted the cycle-1 whole-`/pipelines` openapi/`ui-schema` regeneration as zero-runtime
hygiene (P5.1b whole-app codegen-lock precedent). Confirmed the cycle-2 delta does **not** re-touch
`openapi.json` or `schema.ts` — no action taken, as routed. Nothing to re-review.

## Gates — independent run (detached worktree @ c658685, `uv sync --all-extras`)

- `uv run ruff check .` — **clean** ("All checks passed!").
- `uv run ruff format --check` — 49 files "would reformat", but this is a **pre-existing repo backlog**:
  `origin/main`'s `app.py` + `event.py` also fail it, and `ruff format --diff` wants to touch **none** of
  the P5.1c-added lines (email-actuator region empty). **Zero new format debt**; `ruff check` (the
  canonical lint gate) is the enforced one and is clean.
- `uv run mypy` (strict; `files=src,tests`) — **clean** ("no issues found in **305** source files");
  matches cycle-1. *(Note: `mypy .` trips the known `plugins/` duplicate-module collision — out of
  canonical scope; the no-arg invocation is the gate.)*
- `uv run pytest` — **2459 passed (EXIT=0)**, full suite, 385s. The lone stderr line ("Exception in
  thread … `test_net_trust.py` … `network_timeout`") is **pre-existing noise** — a by-design hung-DNS
  daemon-thread timeout; `net_trust.py` is not in this diff and the suite exit is 0. The 4 cycle-2
  tests re-run clean independently (`4 passed`).

## Verdict — clean

All three cycle-1 🟡 (Y1 D6-text, Y2 both-non-empty, Y3 fail-closed) and the 🟢→α cross-pipeline IDOR
test are resolved exactly as routed; the rework is confined to the routed surface; the byte-frozen set
(gate · `_execute_local_call` · COUNTDOWN spine · `run_pipeline` `countdown_auto_fire=None` · existing
`human`/`auto_timer` callers · constitutional field-set pin) is intact; gates are green on an
independent run; cycle-2 introduces **0🔴 · 0🟡**. From the R0-A lens the honesty-crux crossing is
ready to Accept. The one Accept-moment item is non-blocking: the architect re-ratifies the in-place
**ADR-043 D6** decision-text edit (Y1) and decides whether to log it in the Status/amendment-history.
