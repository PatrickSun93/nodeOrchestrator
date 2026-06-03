---
task_id: P3.6
stage: architect-routing-on-plan
adr_under_review: ADR-030
plan_under_review: docs/process/senior-plans/P3.6.md
routed_by: architect (Peidong)
routed_via: orchestrator
date: 2026-06-03
reviews_routed:
  - docs/process/reviews/P3.6/R0-A-on-plan.md  # needs_architect: Y1, Y2 + N1-N3
  - docs/process/reviews/P3.6/R0-B-cross-family.md  # needs_architect: 0R/4Y/3G
disposition: all-α (+ Y1 constitutional broadening ratified)
---

# Architect routing — P3.6 plan-stage (ADR-030 + senior plan)

Architect (Peidong) routed the two plan-stage reviews on 2026-06-03 via the orchestrator. **All findings → α (senior absorb).** No β/γ. The one constitutional-invariant call (Y1, both lenses converged) is **ratified as a generalization**, not deferred. The design is sound on every trust-surface probe (R0-B 0🔴; R0-A affirmed probes 1/2/3/6/7) — the absorptions are textual/test tightening, no design change.

## Y1 (R0-A Y1 + R0-B Y1 — converged) → **ratify the broadening + honest restatement**

The confirm endpoint is a **second `TOOL_CALL` appender**, generalizing ADR-028 D6 t4's "sole appender" structural invariant. Architect **ratifies the generalization**. Senior:
- **(a)** ADR-030 D1 **stops claiming "sole-appender preserved verbatim"** and honestly inscribes: `TOOL_CALL` now has **two appenders** (AUTO branch + confirm endpoint), **both downstream-of-gate** (AUTO = gate-approval for `AUTO_EXECUTE`; confirm = human-approval over the gate-produced `TOOL_CALL_PENDING` record). Declared an explicit **broadening of ADR-028 D6 t4**, ratified as part of ADR-030.
- **(b)** Plan **amends the t4 constitutional test** (`tests/tools/test_constitution.py::test_t4_tool_call_sole_appender_in_src`) to allow the two legitimate appenders (`tool_dispatch.py` + confirm endpoint), as part of the **B3** atomic.
- **(c)** Plan **B1's "sole appender" acceptance is scoped to the B1 commit** (the second appender lands in B3).
- Plus: `external-r0b-prompt.md` point 6 patched (it had primed the dual-lens against the property the slice changes).

## Remaining findings → **α (senior tighten)**

- **R0-A Y2 (idempotency-predicate consistency)** → make the two idempotency predicates explicit: the endpoint still-pending check + the executor `call_id` guard have **no gap and are single-writer atomic**; resolve the snapshot(D2)-vs-endpoint(D3) inconsistency by making **both position-anchored** after the target `TOOL_CALL_PENDING` (no cross-turn `call_id` false-reject).
- **R0-B Y2 (server-crash between append and execute)** → document the crash window: post-restart the `TOOL_CALL_PENDING` is durable and the pending call stays confirmable + unexecuted (**recoverable**); the post-append-pre-execute window is the inherited `_post_intent` pattern (executor boot-recovery is a general out-of-scope gap). Note in ADR Consequences + plan risk note.
- **R0-B Y3 (room-state check)** → **add the check**: the confirm endpoint rejects a confirm on a terminal (`closed`) room.
- **R0-B Y4 (brief assumptions superseded under (c))** → tighten the plan for the junior: enumerate the brief statements (c) overrides ("zero Python", "no backend/API/gate change", "binds the frozen contract") so the junior has a single source of truth (ADR-030 ratification owns this list).
- **R0-A nits N1–N3** (senior discretion) → N1 drop the provenance-less `user_id`/`DECISION`; N2 give `TOOL_CALL_CANCELLED` the same event-type discipline as `TOOL_CALL_PENDING`; N3 add a writer-executor-atomicity test target.

## Brief-correction acknowledgment

R0-A (architect-partner) owns a **brief defect**: the P3.6 brief framed pending calls as "already on the frozen wire," which is false against the live code (the field is structurally empty). The senior **surfaced rather than improvised** (§5 #1) and the resolution (recording-only `TOOL_CALL_PENDING`, gate logic untouched) is the minimal correct fix. Recorded here so the project's mental model is corrected; ADR-030 Context now carries the superseded-brief-statements enumeration.

## State / next

- **ADR-030 stays `Proposed`** (RC-23-safe; no literal accept-substring until the architect signs off).
- Both reviews' `verdict` bump to `clean` (RC-10 verdict-bump; `verdict_history` grows a post-routing-absorbed entry).
- State stays `awaiting_senior_plan` — R0-A-on-plan / R0-B-on-plan are manual RC-9 dispatches (no state change). After the senior re-commits the absorptions, the architect's next action is **ADR-030 sign-off + dispatch** (junior, or a further review round if desired).
</content>
