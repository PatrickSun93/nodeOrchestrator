---
task_id: P5.1c
stage: impl (R0-A on impl) — isolated dual-lens (Lens A ∥ Lens B)
reviewer: architect-partner (R0-A)
verdict: needs_architect
verified_against: >
  origin/claude/P5.1c-impl @ 4f08f20 (P5.1c-1..6 + mypy fixup) vs origin/main @ 34a309e;
  plan docs/process/senior-plans/P5.1c.md; ADR-043 (Accepted);
  architect-routing-on-plan.md (all-α absorbed)
gates: "ruff clean · mypy --strict clean (305 files) · pytest green (PYTEST_EXIT=0, full suite 100%)"
lenses: A (crossing / over-actuation + irreversible-send safety) · B (spine + reversible-envelope no-regression)
findings: "0🔴 · 3🟡"
disposition_surface:
  Y1-dryrun-meta-not-in-typed-metadata: "α(lean) — ADR-043 D6 mechanism infeasible-as-written; impl callsite-typed (correct) but un-surfaced; D6 text ↔ impl contradiction → amend ADR-043 D6 (architect-only, no code change)"
  Y2-live-gate-omits-both-non-empty: "α(lean,small) — live recipient gate misses ADR-043 D3 'both non-empty'; diverges from dry-run would_actuate; not API-reachable; mirror the dry-run guard"
  Y3-live-branch-fail-open-on-unknown-mode: "α(lean,small) — live actuation entered by `!= 'dry_run'` (negation), not explicit `== 'live'`; fail-OPEN on any unknown email_mode, contra ADR-043 D5 'live requires email_mode explicitly set'; not API-reachable; match `== 'live'` explicitly"
---

# R0-A on impl — P5.1c headless pipeline email (the P5 honesty crux)

Reviewed strict — the first headless **irreversible actuation** in the product. Read
`git diff origin/main...origin/claude/P5.1c-impl` from `main` (no checkout, shared worktree);
canonical gates run in an isolated detached worktree (`uv sync --all-extras`). The crossing is
**structurally sound and faithful to ADR-043 C0–C8 across both lenses**: every named Lens-A and
Lens-B invariant holds, and the **R0A-Y1 headline** (the vacuous-isolation-test risk) is honestly
resolved. Two 🟡 are ADR-vs-impl faithfulness gaps that need an architect routing call — **neither
is an over-actuation hole; no 🔴**.

## Gates (independent run — detached worktree @ 4f08f20, `uv sync --all-extras`)

- `ruff check .` — **clean** ("All checks passed!")
- `uv run mypy` (strict; `files=src,tests`) — **clean** ("no issues found in 305 source files")
- `pytest` — **green** (`PYTEST_EXIT=0`, full suite at 100%, all-passed; the four P5.1c test files —
  `test_pipeline_email_actuator` · `test_schedule_sweeper` · `test_schedule_store` ·
  `test_schedule_endpoints` — re-run clean independently). The lone stderr line ("Exception in
  thread Thread-227" from `test_net_trust.py`'s hung-DNS timeout test) is **pre-existing noise** — a
  daemon thread raising `LocalToolError: network_timeout` by design; `net_trust.py` is not in this diff
  and the suite exit is 0.

## Lens A — over-actuation + irreversible-send safety (held)

Verified against the actual actuator `_actuate_pipeline_emails` (`app.py`, post-`_discover_due_schedules`):

1. **`send_email`-only.** Module-level literal `_PIPELINE_EMAIL_TOOL = "send_email"`; discovery
   filters `meta.tool_name != _PIPELINE_EMAIL_TOOL → continue`. The **D4 HARD-never** test
   (`test_schedule_sweeper.py::test_hard_never_generalize_non_send_email_not_actuated`) genuinely
   appends `git_push` **and** `apply_edit` HARD pendings with `email_enabled`+`live` and asserts
   `TOOL_CALL == 0` — **non-vacuous**; it exercises real non-`send_email` HARD pendings.
2. **Opted-in + promoted-to-live only.** `if not schedule.email_enabled: return` (OFF never touches
   pendings); `dry_run` → record + `continue`; `live` → gate → actuate. The opt-in state is the
   **authoritative writer re-read** at step 1 (`app.py:809`, `get_schedule(writer_conn, …)`), not the
   stale reader.
3. **Config-pinned recipient, case-insensitive.** `pending_to.lower() != pinned.lower() → continue`
   (left waiting); `to` is read from the **pending record** and compared to schedule **config** — the
   LLM cannot redirect even within the domain allowlist. `test_live_mode_case_insensitive_recipient_match`
   (`Alice@Example.Com` ↔ `alice@example.com`) actuates. *(But see Y2 — the "both non-empty" half of D3
   is missing.)*
4. **`send_email` allowlist still enforced.** The actuator routes through `_writer_approve_helper →
   execute_pending_tool_calls → _execute_local_call → _make_send_email` (allowlist,
   `network_tools.py:466-495`), all byte-unchanged — the pin is an *additional* narrowing, not a
   replacement (verified by the unchanged downstream path).
5. **Idempotent (at-most-once).** Two independent guards: the actuator's own `resolved_call_ids`
   scan (skips any pending already resolved by a `TOOL_CALL`/`TOOL_RESULT`/`TOOL_CALL_CANCELLED` —
   `PENDING_RESOLUTION_TYPES`) **and** the inherited still-pending check in `_writer_approve_helper`.
   `test_idempotency_no_double_send` re-invokes the actuator twice → **exactly 1** `TOOL_CALL`.
   A crash between run and actuation **under**-sends (next_fire already advanced in step 3), never
   double-sends.
6. **Owner-attributed.** Actuates with `approval_source="auto_pipeline"` +
   `approver_user_id=schedule.owner_user_id`; `test_live_mode_actuates_matching_pending` asserts
   `tool_name=="send_email"`, `approval_source=="auto_pipeline"`, `approver_user_id==owner` on the
   appended `TOOL_CALL`.
7. **Fail-closed unconfigured.** `email_enabled INTEGER NOT NULL DEFAULT 0`; the guarded
   `ALTER TABLE` migrates pre-existing rows to OFF; `test_actuate_noop_when_email_disabled` → 0
   `TOOL_CALL` + 0 `OBSERVATION`.
8. **Dry-run truly does not send.** `_record_email_dry_run` appends **one** `OBSERVATION` carrying a
   typed `PipelineEmailDryRunMeta` then `continue`s — no helper, no `TOOL_CALL`, no transport; the
   pending stays waiting. `test_dry_run_records_observation_no_actuation` asserts 0 `TOOL_CALL`,
   exactly 1 schema-valid `OBSERVATION`, pending still present.

## Lens B — spine + reversible-envelope no-regression (held)

1. **Gate + executor byte-frozen.** `autonomy/scoring.py` (`score`/`decide_tier`/`emit_gate_decision`),
   `tools/executor.py` (`_execute_local_call`), `agents/tool_dispatch.py` (the two RB-AUTOFIRE stamps),
   `pipeline/runner.py` — **none appear in the diff**. `test_lens_b_autofire_guard_logic_unchanged` +
   `test_lens_b_countdown_auto_fire_none_preserved` pin them.
2. **COUNTDOWN spine untouched.** `_countdown_sweeper` / `_discover_expired_pendings` appear in the
   `app.py` diff **only** inside docstring text; their bodies are byte-unchanged. The actuator uses a
   **dedicated scan** keyed on `tool_name` + resolution and **never reads/writes `expires_at`**
   (isolation test Part 2 pins this).
3. **`run_pipeline` `countdown_auto_fire=None` preserved** (`runner.py` not in diff; test asserts ≥2
   sentinels).
4. **No new routing `LLMPurpose`.** `test_lens_b_no_new_llm_purpose` + the existing canonical
   constitutional test; the recipient is **config**, not an LLM judgment.
5. **Existing `_writer_approve_helper` callers behavior-identical.** Only the param `Literal` is
   widened to `["human","auto_timer","auto_pipeline"]`; the body is unchanged; the `human`/`auto_timer`
   paths and interactive `/confirm` are untouched.
6. **Field-set constitutional pin byte-unchanged.** `tests/core/test_constitution.py` is **not in the
   diff**; `test_lens_b_field_set_pin_byte_unchanged` re-asserts the canonical five `ToolCallMeta`
   field names. (R0A-Y2 absorbed correctly — value-set widening, not field-set.)

## R0A-Y1 special re-check — the isolation test is honestly rewritten (held; the headline)

`test_schedule_act_on_writer_does_not_call_countdown_spine` (`test_schedule_sweeper.py:492-553`) is
rewritten exactly per the absorbed routing:

- **drops** `_writer_approve_helper` from `_schedule_act_on_writer`'s forbidden set (now legitimately
  reachable — but only via the narrow `_actuate_pipeline_emails` path);
- **keeps** `_countdown_sweeper` + `_discover_expired_pendings` forbidden for **both**
  `_schedule_act_on_writer` (Part 1) **and** `_actuate_pipeline_emails` (Part 2 — the second-function
  AST check the old one-hop test lacked);
- **adds the positive pin** (Part 3): `_schedule_act_on_writer` **must** call `_actuate_pipeline_emails`,
  `_actuate_pipeline_emails` **must** call `_writer_approve_helper`, and `_schedule_act_on_writer` **must
  not** call `_writer_approve_helper` directly.

The `_schedule_act_on_writer` docstring is rewritten truthfully — the false "Never calls
`_writer_approve_helper`" line is gone; step 6 states the crossing. The ADR-042 amendment (P5.1c-6)
names the lift explicitly ("deliberately lifted … an **intentional lift, not a silent bypass**") and
points at this test. The test is **no longer vacuous**: it fails if the COUNTDOWN spine is touched, if
the helper is reached off the named path, or if the positive reach disappears. **The P5.1b-cyc3
vacuous-test failure mode is closed.**

## ADR amendments (P5.1c-6) — faithful

All eight inscribed as brief annotation blocks, originals preserved: **ADR-041** D5 (the one authorized
irreversible exception) + D10 ("the P5.1 wave closes with P5.1c"); **ADR-040** D3 (third caller,
additive) + D4 (value-set widening; field-set pin byte-unchanged) + `RB-PIPELINE-EMAIL` ("heavier
neighbour" crossing the reversibility line RB-AUTOFIRE held); **ADR-036** (HARD tier unchanged,
allowlist enforced downstream, ADR-037 R9 unsandboxed warning intact); **ADR-005/013/027** (post-gate
note, no logic change). RC-3 honored — ADR-043's own decision text is untouched.

## Findings (0🔴 · 2🟡 — both need an architect routing call)

### 🟡 Y1 — `PipelineEmailDryRunMeta` is not registered in `TYPED_METADATA`; the impl deviates from ADR-043 D6's named mechanism, un-surfaced

**Evidence.** ADR-043 D6 (Accepted), plan P5.1c-4, and the absorbed **R0B-Y2** all state the dry-run
meta is "**registered in `TYPED_METADATA` (`core/event.py:394`)** — structurally enforced, not
convention-by-string." The impl does **not** register it: `event.py:428-431` leaves a NOTE, and
structural typing is achieved by **callsite construction** — `PipelineEmailDryRunMeta(...).model_dump()`
in `_record_email_dry_run`.

**The deviation is technically correct — and effectively forced.** `validate_metadata()`
(`event.py:534-553`) runs the registered schema against **every** event of that type at append.
Registering `OBSERVATION → PipelineEmailDryRunMeta` would force **all** OBSERVATION events (runner
output, MCP interpret — free-form metadata) to validate against it and **fail at append**. ADR-043 D6
is internally contradictory: it asks for a strict global schema on OBSERVATION **and** "reuses the
existing OBSERVATION event type (no new `EventType`)." Since a new `EventType` is rejected, callsite
typed-construction is the only honest way to structurally type the preview while reusing OBSERVATION.
The **R0B-Y2 intent is met** — the load-bearing dry-run evidence is a real Pydantic class, validated on
write (construction) and round-trip-validated in `test_dry_run_records_observation_no_actuation` +
`test_pipeline_email_dry_run_meta_schema`.

**Why it still needs you.** (1) It is an **un-surfaced deviation from an Accepted ADR's named
mechanism** on the honesty-crux slice — per "Surface, don't improvise," the junior should have halted on
the D6 contradiction rather than silently substituting (good in-code NOTE notwithstanding).
(2) **ADR-043 D6 text now contradicts the impl** ("registered in TYPED_METADATA" vs callsite
validation); P5.1c-6 correctly left ADR-043's own decision text unedited (RC-3), so the contradiction is
live. At the honesty crux, an Accepted ADR that names a mechanism the impl deliberately does not use is
exactly the inscription-drift this slice must not carry.

**Lean: α.** The impl approach should **stand** (it is correct, arguably more correct than D6 as
written); absorb by amending **ADR-043 D6** text + the R0B-Y2 note to describe **callsite typed
construction** (validated on write; OBSERVATION stays free-form/shared via the `event.py` NOTE) rather
than global registration. This is an **ADR-043 decision-text amendment → architect-only** (RC-3); **no
code change**. (β = leave D6 text as-is and accept the drift — weaker at this slice.)

### 🟡 Y2 — the live recipient-eligibility gate omits ADR-043 D3's "both non-empty"; it diverges from the dry-run path that checks it

**Evidence.** ADR-043 D3 (Accepted): actuate "iff its `to` matches the pinned recipient — a
case-insensitive match (both sides lowercased), **both non-empty**; otherwise the pending keeps waiting
(fail-closed)." The **live** gate checks only `pending_to.lower() != pinned.lower()`. When **both** are
empty, `"" == ""` passes → it would actuate. The **dry-run** path computes
`would_actuate = bool(pending_to and pinned and pending_to.lower() == pinned.lower())` — it **does**
require both non-empty. So the live gate is (a) **less strict than ADR-043 D3** and (b) **inconsistent
with the dry-run preview**, which is meant to be the faithful "what live would do" evidence.

**Reachability.** Not exploitable through the supported surface: the opt-in endpoint requires
`email_recipient: str = Field(min_length=1)` (422 on empty) and promote requires `email_enabled`, so an
API-created live schedule always has a non-empty pinned recipient (→ an empty `pending_to` correctly
mismatches and waits). Even out-of-band, the downstream `send_email` allowlist fail-closes on an empty
`to`. So this is a **defense-in-depth + faithfulness + dry-run/live-consistency** gap, **not** a live
exfil path.

**Lean: α (small).** Mirror the dry-run guard in the live gate — actuate only when
`pending_to and pinned and pending_to.lower() == pinned.lower()` — so the live gate matches ADR-043 D3
"both non-empty" and the preview and live actuation can never diverge. One line, low risk. β (defer) is
defensible given the compounded guards, but at the honesty crux closing the ADR-text gap is cheap.

### 🟡 Y3 — the live branch is entered by negation (`!= "dry_run"`), not an explicit `== "live"` — fail-**open** on any unknown `email_mode`

**Evidence.** The mode discrimination in `_actuate_pipeline_emails` is:

```python
if schedule.email_mode == "dry_run":
    _record_email_dry_run(...)
    continue
# Live mode: eligibility gate ...   ← reached by ANY email_mode != "dry_run"
```

So the **irreversible live-actuation branch is entered for every `email_mode` value that is not exactly
`"dry_run"`** — `"live"`, but equally any unexpected value (`""`, `"LIVE"`, a future 4th state, a
botched-migration default). For the **most dangerous branch in the product** this is **fail-open**:
the safe posture is to actuate **only** on an explicit `== "live"` and treat any other value as
non-actuating. ADR-043 D5 frames it exactly this way — "**LIVE** (`email_enabled=1`, `email_mode='live'`)"
and "the dangerous state (live) requires *both* flags **explicitly set**." Entering live by *negating*
`dry_run` is the opposite of "explicitly set."

**Reachability.** Not exploitable today: `email_mode` is only ever written as `'dry_run'`
(`set_schedule_email_optin` + the DDL default) or `'live'` (`promote_schedule_email_live`); there is no
endpoint to set an arbitrary mode, so `!= "dry_run"` ≡ `== "live"` in practice. Like Y2, this is
**defense-in-depth + faithfulness**, not a reachable exfil path — but it is the one anti-pattern the
honesty crux most exists to forbid (the irreversible step taken on an *implied* rather than *explicit*
signal).

**Lean: α (small).** Make **live** the explicitly-matched branch:
`if email_mode == "dry_run": …record…; elif email_mode == "live": …actuate…; else: …log + skip (no
send)…` — so an unknown mode fails **closed**. One small change; pairs naturally with Y2 (both tighten
the same eligibility gate to ADR-043 D3/D5's fail-closed spec). β (accept, the store enforces the
two-literal invariant) is defensible but weaker at this slice.

> **Y2 + Y3 are the same theme** — the live eligibility gate is looser than ADR-043 D3/D5's fail-closed
> spec in two independent ways (empty-recipient match; live-by-negation). Both are one-line tightenings,
> neither API-reachable, and they are naturally absorbed together. Y1 is the only finding requiring an
> Accepted-ADR text amendment (architect-only).

## Routing surface for the architect

| # | What | Lean | Your call |
|---|---|---|---|
| **Y1** | `PipelineEmailDryRunMeta` not in `TYPED_METADATA`; ADR-043 D6 mechanism infeasible-as-written; impl callsite-typed (correct) but un-surfaced; D6 text ↔ impl contradiction | **α** — amend ADR-043 D6 text + R0B-Y2 note (impl stands; architect-only ADR edit, no code change) | α / β |
| **Y2** | live gate omits ADR-043 D3 "both non-empty"; diverges from dry-run `would_actuate` (not API-reachable) | **α (small)** — mirror the dry-run guard in the live gate | α / β |
| **Y3** | live branch entered by `!= "dry_run"` (negation), not explicit `== "live"`; fail-open on unknown `email_mode`, contra ADR-043 D5 (not API-reachable) | **α (small)** — match `== "live"` explicitly; unknown → fail-closed (pairs with Y2) | α / β |

No 🔴; nothing impossible; all gates green (ruff · mypy · pytest `EXIT=0`). The crossing's bounds —
`send_email`-only literal + HARD-never test, default-OFF + dry-run-first, owner-pinned recipient,
owner-attributed audit, at-most-once idempotency, byte-frozen gate/executor/COUNTDOWN spine — all hold.
Both findings are honest-inscription / faithfulness items: exactly the routing calls this slice's
honesty bar exists for.
