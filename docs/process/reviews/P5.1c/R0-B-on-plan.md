---
task_id: P5.1c
round: R0-B-on-plan
verdict: clean
findings_count:
  red: 0
  yellow: 2
  green: 2
verdict_history:
  - "2026-06-10: R0-B-on-plan cross-family review → needs_architect (0🔴 2🟡 2🟢)"
  - "2026-06-10: architect routed Y1=case-insensitive, Y2=typed-meta (architect-routing-on-plan.md); senior absorbed both into ADR-043 D3/D6 + plan P5.1c-3/-4 (RC-10) → clean"
reviewed_artifacts:
  - "docs/process/architect-briefs/P5.1c.md (architect ratification C0–C8)"
  - "docs/process/senior-plans/P5.1c.md (6 atomics)"
  - "docs/decisions/ADR-043-headless-pipeline-email.md (Proposed)"
  - "src/orchestrator/api/app.py (verified seams: _writer_approve_helper :379-471, _schedule_act_on_writer :600-727, _schedule_sweeper :731-765, _patch_schedule :2116-2175, _confirm_on_writer :1450-1465)"
  - "src/orchestrator/core/event.py (verified: ToolCallMeta :203-225, EventType :68-98, TYPED_METADATA :394-407, PENDING_RESOLUTION_TYPES)"
  - "src/orchestrator/pipeline/store.py (verified: PIPELINE_SCHEMA :44-58, guarded-ALTER precedent cited from memory/store.py)"
  - "src/orchestrator/pipeline/runner.py (verified: countdown_auto_fire=None at :153,223, _PIPELINE_THRESHOLDS at :67)"
  - "src/orchestrator/agents/tool_dispatch.py (verified: two RB-AUTOFIRE stamp guards :137-145)"
  - "src/orchestrator/tools/network_tools.py (verified: _make_send_email :409-532, to from params :458, domain lowercasing :484-488)"
  - "src/orchestrator/llm/purposes.py (verified: LLMPurpose enum — zero pipeline routing purposes)"
  - "tests/core/test_constitution.py (verified: ToolCallMeta field-set pin :281-296)"
  - "tests/api/test_auto_fire.py (verified: existing human/auto_timer provenance + idempotency tests :382-452)"
verify_base: "origin/main @ dd5ced5"
---

# R0-B-on-plan cross-family review — P5.1c headless pipeline email

## Lens preamble

This is a **plan-stage** R0-B from a non-Claude cognitive substrate. The review traces
every runtime-failure path across the six concerns the architect specified in the dispatch:
(1) over-actuation boundary escape, (2) recipient-pin bypass, (3) dry-run→live state
machine correctness, (4) restart/re-sweep double-send, (5) existing callers unchanged,
(6) byte-frozen spine + no-new-LLMPurpose + owner attribution + fail-closed.

The senior plan is structurally sound — every code seam it cites verifies cleanly against
`origin/main @ dd5ced5`. The ADR-043 is comparably thorough, with explicit D1–D8 decisions,
considered-alternatives blocks, and a correctly-layered residue lineage. The concern-by-concern
trace below confirms the crossing is the narrowest possible irreversible actuation:
scheduled-only, `send_email`-only literal constant, owner-pinned recipient, 3-state
OFF→dry-run→live fail-closed, post-gate (no tier/floor change), no new routing surface.

Two 🟡 findings surface edge cases the plan's acceptance criteria cover implicitly but
the ADR text should acknowledge explicitly: (a) the recipient-pin comparison semantics
for email addresses (case sensitivity), and (b) the dry-run OBSERVATION event format
(no typed metadata for a load-bearing compensability audit trail).

No 🔴 blocking findings. The design holds against all six architect-specified concerns.

---

## Concern 1 — Over-actuation boundary (C3 literal-constant guard)

**Traced path:** The eligibility gate in `_actuate_pipeline_emails` checks
`tool_name == _PIPELINE_EMAIL_TOOL` where `_PIPELINE_EMAIL_TOOL = "send_email"`
is a module-level literal constant. A non-`send_email` HARD pending (e.g.,
`git_push`, `apply_edit`) never matches → pending stays waiting, exactly as today.

**Why the single-string-literal guard is structurally adequate:** The three existing
locks (countdown_auto_fire=None, tier==COUNTDOWN gate, reversibility floor gate) all
remain intact on the interactive path. The actuator is a *separate* authorization layer
that bypasses none of them — it operates after the run, discovers by tool_name not by
tier/floor, and only fires when the schedule explicitly opted in AND was promoted to live.
The D4 constitutional test (P5.1c-5 Lens A: "HARD-never-generalize") adds a fourth
lock — a test that asserts the non-`send_email` pending is **never** auto-actuated even
with email enabled + live. Four independent layers = adequate.

**One 🟢 advisory (G1 below):** The constant is a bare `str`, not a `Final`-annotated
or `Enum` member. If a future developer copies the actuator pattern for a second tool
path, the naming convention (`_PIPELINE_EMAIL_TOOL`) doesn't prevent copy-paste from
creating `_PIPELINE_GIT_TOOL = "git_push"` with a structurally identical actuator. An
`Enum` member or `Final` type annotation would make the "one named tool, never a class"
invariant machine-checkable at the type level, adding defense-in-depth beyond the
constitutional test.

**Verdict: ✅ CLEAN.** The structural guard (single literal + constitutional test)
is adequate for the first irreversible crossing.

---

## Concern 2 — Recipient-pin bypass (C2 eligibility gate)

**Traced path:** The actuator reads `params['to']` from the persisted
`ToolCallPendingMeta` (gate-produced, never caller-supplied), compares it against
`schedule.email_recipient` (owner-set at opt-in time). If mismatch → pending stays
waiting (fail-closed). The `_writer_approve_helper` then reconstructs `params` from
the same persisted record at lines 434-449 — the caller (actuator) never provides
`params` to the helper. The `send_email` allowlist (ADR-036, domain + explicit-recipient
checks in `network_tools.py:478-495`) is still enforced downstream.

**🟡 Y1 — Recipient-pin comparison semantics (case sensitivity).** The plan says
"the pending's `to` matches the pinned recipient (exact match)" but does not specify
case sensitivity. `_make_send_email` at `network_tools.py:458` reads `to_addr =
str(params.get("to", ""))` — no normalization. The domain-allowlist check at line
484 lowercases the domain (`to_domain.lower()`) for comparison, but the full `to_addr`
string is passed through unchanged to the email provider.

Per RFC 5321 §2.3.11, the local-part of an email address is *technically*
case-sensitive but treated as case-insensitive by all major providers (Gmail, Outlook,
etc.). The domain part is case-insensitive per RFC. If the owner sets
`email_recipient = "Alice@corp.com"` and the LLM generates `to = "alice@corp.com"`,
a case-sensitive `==` comparison would reject the pending → the email silently never
sends, even though the owner promoted the schedule to live and the addresses are
functionally identical.

This is **fail-closed** (under-send, never wrong-send), so correctness holds. But the
failure is silent: the owner promotes to live expecting emails, and they never arrive
because of a case mismatch the dry-run preview might not surface clearly (both
`"Alice@corp.com"` and `"alice@corp.com"` look like the same address to a human).

**Suggested investigation:** The architect should decide whether the comparison should
be case-insensitive (lowercase both sides before `==`), or whether the plan/ADR should
explicitly acknowledge the case-sensitive posture and document that the dry-run preview
is the owner's opportunity to catch the mismatch. The ADR-043 D3 text says "exact
match" — if case-insensitive is intended, the ADR should say so.

**Verdict: 🟡 NEEDS_ARCHITECT.** Not a correctness bug (fail-closed), but a silently
degrading edge case that should be either specified as case-insensitive or explicitly
acknowledged as case-sensitive with dry-run as the compensating control.

---

## Concern 3 — Dry-run→live state machine (C5 mandatory first state)

**Traced path:** Three-state machine: OFF (`email_enabled=0`) → DRY-RUN
(`email_enabled=1, email_mode='dry_run'`) → LIVE (`email_enabled=1, email_mode='live'`).
Enabling lands in dry-run (P5.1c-1: `set_schedule_email_optin` sets mode to `'dry_run'`).
Only `promote_schedule_email_live` (a separate endpoint, P5.1c-2) flips mode to `'live'`.
The actuator checks `email_mode == 'live'` before calling `_writer_approve_helper`;
otherwise it takes the dry-run branch (append OBSERVATION, no helper, no transport).

**Fail-closed in both dimensions:** `email_mode` defaults to `'dry_run'` at the column
level (DDL: `DEFAULT 'dry_run'`). Even if `email_enabled` somehow flips to 1 without
a corresponding mode change, the mode stays `'dry_run'` → no send. The dangerous `'live'`
state requires both `email_enabled=1` AND `email_mode='live'` — two explicit flags.

**No fall-through path to live:** The eligibility gate's `email_mode == 'live'` check is
a boolean branch — if false, the actuator takes the dry-run path. There is no code path
where dry-run silently promotes to live. The test P5.1c-4 asserts "zero TOOL_CALL/TOOL_RESULT
for send_email is appended" in dry-run mode, which structurally prevents the transport
from being called.

**Recipient change forces dry-run round-trip:** There is no "update recipient" endpoint
in the plan (P5.1c-2 only has enable/promote/disable). To change the recipient, the
owner must disable then re-enable, which lands in dry-run. This means a recipient change
always requires a dry-run validation cycle before going live.

**Verdict: ✅ CLEAN.** The 3-state machine is structurally fail-closed. The dry-run
branch is a hard branch, not a weak default.

---

## Concern 4 — Restart/re-sweep double-send (idempotency)

**Traced path:** Three layers of idempotency guard:

**Layer 1 — Schedule claim-before-run (ADR-042 D4).** `_schedule_act_on_writer` advances
`next_fire` BEFORE `run_pipeline` (line 654: `update_schedule_next_fire`). The actuator
runs as a step 6 AFTER `run_pipeline` + `create_pipeline_run`. Crash scenarios:
- **Crash between claim and run:** `next_fire` advanced, run didn't happen → on restart,
  boot re-arm advances past-due → this run never fires. UNDER-send, never double-send.
- **Crash between run and actuation:** `next_fire` advanced, run completed, actuation
  didn't happen → on restart, boot re-arm advances past-due → the completed run's
  pending is orphaned in the room but the sweeper won't re-fire this schedule.
  UNDER-send, never double-send.
- **Crash during actuation:** `_writer_approve_helper` runs on the single writer
  executor (max_workers=1). If the helper crashed mid-execution, the TOOL_CALL may or
  may not have been appended. The crash-safe claim means the schedule won't re-fire.
  But the sweep itself won't retry — the pending is either resolved (TOOL_CALL appended
  before crash) or still waiting (crash before append). Either way, the schedule's
  next_fire was advanced → no re-sweep of this run. At-most-once.

**Layer 2 — Helper still-pending check (ADR-040 D3).** `_writer_approve_helper` at
lines 422-429 scans events AFTER the pending's position for `PENDING_RESOLUTION_TYPES`
matching the `call_id`. If already resolved → `_ApproveSkipped("already_resolved")`.
This is the authoritative guard — even if the actuator's discovery scan returns a
stale pending, the helper rejects it.

**Layer 3 — Single-writer serialization.** Both the schedule sweeper and the interactive
`/confirm` handler submit to `writer_executor = ThreadPoolExecutor(max_workers=1)`.
Exactly one writer operation executes at a time. No concurrent mail sends.

**Re-sweep scenario:** The sweeper's discovery uses a stale reader. Two ticks could both
discover the same schedule before the first tick's claim advances `next_fire`. Tick 2's
writer-side re-check (`schedule.next_fire > now_ms_val` at line 637) skips because
`next_fire` was already advanced. The schedule runs once. Even if the actuator ran
twice for the same run (impossible given the claim), the helper's still-pending check
rejects the second attempt.

**Verdict: ✅ CLEAN.** The inherited claim-then-run + still-pending machinery covers all
crash and re-sweep scenarios. The actuator adds no new failure mode to the idempotency
story.

---

## Concern 5 — Existing callers unchanged (human/auto_timer)

**Traced path:** The `Literal` widening adds `"auto_pipeline"` to two type annotations:
`_writer_approve_helper`'s `approval_source` param (app.py:383) and
`ToolCallMeta.approval_source` (event.py:224). Both are purely additive — no existing
value is removed or renamed.

**Existing callers verified byte-identical:**
- HTTP confirm (app.py:1453): `_writer_approve_helper(ctx, rid, body.pending_event_id,
  "human", _approver_user_id, loop)` — unchanged.
- Countdown sweeper (app.py:549): `_writer_approve_helper(ctx, rid, pending_event_id,
  "auto_timer", None, loop)` — unchanged.

**Helper behavior unchanged:** `_writer_approve_helper` never branches on
`approval_source` — it only threads the value into `ToolCallMeta.approval_source`
(line 448). The existing callers' error mappings (human: 200/422/500; sweeper:
log.info/debug/error) are in the callers, not the helper.

**Constitutional test:** `test_constitution_tool_call_meta_field_set_pin`
(tests/core/test_constitution.py:281) checks the field SET
`{"tool_name", "call_id", "params", "approver_user_id", "approval_source"}` —
not the `Literal`'s allowed values. Adding a new value to the `Literal` union does
not change the field set, so the existing constitutional test passes without modification.
The plan's acceptance criterion ("update the constitutional test additively") correctly
anticipates this — the update may be a no-op if the test only checks field names.

**Existing provenance tests:** `test_auto_fire.py:382-417` asserts the HTTP confirm
sets `approval_source == "human"` and the sweeper sets `"auto_timer"`. Both tests
pass unchanged — the `Literal` widening is backward-compatible with existing values.

**Verdict: ✅ CLEAN.** The additive `Literal` widening is the minimal change to admit
the third caller. Zero behavioral regression for existing callers.

---

## Concern 6 — Byte-frozen spine, no new LLMPurpose, owner attribution, fail-closed

**Gate (`score`/`decide_tier`/`emit_gate_decision`) — byte-frozen.** The actuator is
layered AFTER the run. `run_pipeline` calls `process_tool_calls` which calls the gate
— the gate's tier decision is unchanged. `send_email` stays HARD. The actuator
authorizes the already-gated pending; it never re-tiers or lowers the floor. ✅

**COUNTDOWN spine — byte-frozen.** `_countdown_sweeper`, `_discover_expired_pendings`,
the two `RB-AUTOFIRE` stamps (tool_dispatch.py:137-145) — all untouched. The actuator
has its own discovery scan that keys on `tool_name`, never on `expires_at`. ✅

**`run_pipeline` reversible envelope — preserved.** `countdown_auto_fire=None` at
runner.py:153,223 — unchanged. The run's output stays reversible; the actuator is
strictly downstream. ✅

**No new routing LLMPurpose.** The pipeline runner uses only
`LLMPurpose.AGENT_RESPONSE` (runner.py:121, 190, 382). The recipient is config
(`schedule.email_recipient`), never an LLM judgment. The email body is the agent's
analysis — content-gen, not routing. Zero new `LLMPurpose` values. ✅

**Owner attribution.** The actuator passes `approval_source="auto_pipeline"` and
`approver_user_id=schedule.owner_user_id` to `_writer_approve_helper`. The resulting
`TOOL_CALL`/`TOOL_RESULT` carries both fields — the event trail is the audit. ✅

**Fail-closed unconfigured.** Default-OFF (`email_enabled=0`), dry-run first state,
absent columns → defaults → OFF. The `send_email` tool's `_make_send_email` is
fail-closed at three levels: unconfigured provider → error, unconfigured allowlist →
error, recipient not in allowlist → error. ✅

**Verdict: ✅ CLEAN.** All six byte-frozen/fail-closed invariants verified against
the code at `origin/main @ dd5ced5`.

---

## Findings

| ID | Severity | File/Line | Claim | Suggested investigation |
|---|---|---|---|---|
| Y1 | 🟡 needs_architect | `tools/network_tools.py:458` / ADR-043 D3 | Recipient-pin `to == pinned` comparison semantics unspecified (case sensitivity). The plan says "exact match" but email addresses are case-insensitive per RFC 5321. A case mismatch (e.g., `"Alice@corp.com"` vs `"alice@corp.com"`) would fail-closed silently — the owner promotes to live expecting emails, and they never arrive because the LLM-generated `to` has different casing. | Decide: case-insensitive comparison (lowercase both sides), or explicit acknowledgment of case-sensitive posture with dry-run as the compensating control. If case-insensitive, update ADR-043 D3 text from "exact match" to "case-insensitive match." |
| Y2 | 🟡 needs_architect | ADR-043 D6 / `core/event.py:83,394-407` | Dry-run OBSERVATION format uses untyped metadata. The dry-run preview record (recipient, subject, would-actuate boolean, owner, approval_source) is a load-bearing compensability mechanism — it's the owner's evidence for the promote-to-live decision. But `OBSERVATION` has no typed metadata schema (not in `TYPED_METADATA`), and `OBSERVATION` is semantically "agent observes something," not "system recorded an actuation preview." The format is convention-enforced (by the P5.1c-4 test) rather than structurally enforced. | Decide: (a) accept convention-based format with test coverage, (b) add a typed metadata class for the dry-run record (e.g., `PipelineEmailDryRunMeta` in `TYPED_METADATA`), or (c) introduce a new event type. The plan deliberately avoids new event types to keep scope narrow — architect should ratify this trade-off explicitly in ADR-043 D6. |
| G1 | 🟢 advisory | Plan P5.1c-3 / C3 | Literal constant `_PIPELINE_EMAIL_TOOL = "send_email"` is a bare `str`. A `Final` type annotation or `StrEnum` member would make the "one named tool, never a class" invariant machine-checkable at the type level, adding defense-in-depth beyond the constitutional test. | Consider `_PIPELINE_EMAIL_TOOL: Final = "send_email"` to signal immutability at the type level. Not blocking — the constitutional test pins the behavior end-to-end. |
| G2 | 🟢 advisory | `api/app.py:619` | `_schedule_act_on_writer` docstring says "Never calls... _writer_approve_helper." After P5.1c-3, the function will call `_writer_approve_helper` indirectly via `_actuate_pipeline_emails`. The docstring should be updated. | Update docstring to reflect the new step 6 actuator, preserving the "shares zero spine-critical code" claim (still true — the actuator is a separate authorization layer). |

---

## Synthesis

The plan + ADR-043 is the strongest plan-stage artifact set in this wave. The 3-state
OFF→dry-run→live opt-in is the correct honesty posture for the first irreversible
crossing: it means the owner cannot accidentally send an email — they must (1) enable,
(2) validate the dry-run preview, (3) explicitly promote to live. Each step is a
separate API call with its own audit trail.

The two 🟡 findings are both edge cases at the boundary of "correctness" and
"operational clarity": the recipient-pin comparison (Y1) is fail-closed but silently
degrading; the dry-run OBSERVATION format (Y2) is correct but structurally untyped
for a load-bearing audit record. Neither compromises the irreversible-send safety
invariant. Both should be architect-acknowledged before the impl phase to prevent
a future reader of ADR-043 from misreading the design's intent.

The byte-frozen spine, the additive Literal widening, and the idempotency inheritance
from ADR-040/ADR-042 are all correctly traced. The crossing is genuinely the narrowest
possible irreversible actuation: one tool, one schedule path, one pinned recipient,
default OFF, dry-run first, fail-closed everywhere.
