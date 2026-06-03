---
task_id: P3.6
stage: R0-A
reviewer: architect-partner
verdict: needs_architect
verdict_history:
  - needs_architect
adr_under_review: ADR-030
impl_branch: origin/claude/P3.6-impl@16eca20
date: 2026-06-03
scope: >-
  R0-A impl-stage lens over the 8 atomics (B1-B3 backend, F1-F5 frontend). Six probes the architect set:
  (1) no-forge/backend-authoritative, (2) t4 two-appender guard, (3) downstream-of-gate empty-diff,
  (4) idempotency two-layer + position-anchored, (5) plant-bypass, (6) 不暴露 (D-C).
findings:
  - id: Y1
    severity: should-fix
    probe: 4
    title: >-
      Y2's routed "byte-for-byte consistent" resolution-set is achieved by duplication, not construction:
      _PENDING_RESOLUTION_TYPES (snapshot.py:97) and _CONFIRM_RESOLUTION_TYPES (app.py:74) are identical
      today but have no shared constant and no equality test — a future one-sided edit silently re-opens Y2.
  - id: Y2
    severity: should-fix
    probe: 1
    title: >-
      The partial-turn execute-stage branch (app.py:532, _ConfirmExecuteError -> stage:"execute") — a
      do-not-reverse invariant (ADR-030 D5) — has no test; the 7 confirm test classes never inject an
      executor failure. The append-stage half IS tested.
---

# R0-A (impl-stage) — P3.6 (confirm-then-execute + GUI completeness), ADR-030

**Verdict: `needs_architect`.** The implementation is strong and faithful to the absorbed plan — **every one of the six trust-surface focus points holds, verified structurally *and* behaviorally** (not eyeballed): the gate/executor are byte-for-byte unchanged, `TOOL_CALL` has exactly the two ratified appenders (no third), `TOOL_CALL_PENDING` has exactly one (gate-produced — the plant-bypass guard), the no-forge reconstruction is from the persisted record, and 不暴露 holds on the new GUI surface. The two findings are **should-fix robustness/coverage tightenings, both leaning α-absorb** — a missing consistency *guard* (Y1) and a missing test on a correct-but-do-not-reverse branch (Y2). **Neither is a design defect or a trust-surface hole.** I surface them rather than self-route.

## Verification basis (impl-stage — `origin/claude/P3.6-impl@16eca20` vs `origin/main`)

| Probe | Verified | Evidence |
|---|---|---|
| **(3) empty-diff** — gate + executor unchanged | ✅ | `autonomy/scoring.py`, `autonomy/emission.py`, `tools/executor.py` = **0 diff lines** vs main. |
| **(2) t4 two-appender** | ✅ | `TOOL_CALL` appended at exactly 2 sites: `tool_dispatch.py:106` (AUTO) + `app.py:507` (confirm-approve). The amended `test_t4_…` (AST-walks all `src/`, allows only those two files, flags a 3rd) enforces it. |
| **(5) plant-bypass** | ✅ | `TOOL_CALL_PENDING` has **exactly one** appender (`tool_dispatch.py:133`, the gate-produced countdown/hard branch). A client cannot author one; `_BaseMeta` is `extra="forbid", frozen=True` (`event.py:125`). |
| **(1) no-forge** | ✅ | approve reconstructs `tool_name`/`params`/`author=agent:<initiating_agent>` from `pending_meta` (`app.py:511-516`) — **never** the request; `ConfirmRequest` is `frozen, extra="forbid"`, only `{pending_event_id, decision}` (`wire.py:121-129`). |
| **(4) idempotency** | ✅ | layer-1 still-pending is **position-anchored** (`sorted_events[pending_idx+1:]`, `app.py:468-474`) + layer-2 executor `call_id` guard (unchanged); both on `writer_executor` (`app.py:540`, atomic). |
| **(6) 不暴露** | ✅ | tier drives **only** the CSS affordance (`PendingDecision.tsx:24,29`), never rendered as text; `toolNameLabel` strips `mcp__` + falls back to "一个工具" (`uiStrings.ts:100-102`). |

## Per-focus-point detail

**(1) no-forge / backend-authoritative — clean.** The approve path (`app.py:502-516`) builds the `TOOL_CALL` purely from the persisted `ToolCallPendingMeta`; the request supplies only `pending_event_id` + `decision`. Tested: `test_approve_author_from_pending_record`, `test_extra_fields_in_request_rejected` (extra field → 422). The FE mirrors it (`PendingDecision` → `confirm(roomId, event_id, decision)` only), and even if it didn't, the backend `extra="forbid"` is the authoritative guard.

**(2) t4 two-appender guard — clean.** The constitutional test is a real AST guard (not a grep heuristic): it walks every `src/` file except the two allowed appenders and fails on any `*.append(Event(type=EventType.TOOL_CALL …))`. The docstring honestly states the two are *both downstream-of-gate* and that the confirm appender's property is **behavioral** (pinned by the no-forge test), exactly the honest restatement Y1-plan asked for.

**(3) downstream-of-gate — clean.** Zero diff in `score`/`decide_tier`/`emit_gate_decision`/`executor`. The confirm endpoint appends a `TOOL_CALL` then calls the **unchanged** `execute_pending_tool_calls`; it never re-gates. `tools/test_constitution.py` t2 (no `decide_tier`/`score`/`gate` in `tools/`) still holds.

**(4) idempotency — clean (position-anchored, both layers, atomic).** Layer-1 scans only events *after* the pending event for a same-`call_id` resolution (`_CONFIRM_RESOLUTION_TYPES`), so a stale cross-turn `call_id` cannot false-reject a fresh pending — directly tested by `TestConfirmCrossTurnY2::test_prior_turn_result_does_not_false_reject_fresh_pending`. `test_double_approve_produces_single_tool_call_and_result` proves at-most-one execution; `test_confirm_runs_on_writer_executor` pins the atomicity (N3).

**(5) plant-bypass — clean.** Two independent guards: (i) structural — `TOOL_CALL_PENDING`'s sole appender is the gate-produced branch, so there is no client path to a pending record; (ii) validation — the endpoint requires the id to resolve to an actual `TOOL_CALL_PENDING` in *this* room (`app.py:454-463`), tested by `test_unknown_pending_event_id_fails_closed` + `test_non_tool_call_pending_event_id_fails_closed`. You cannot fabricate a pending, nor bypass to execute (the executor runs only on `TOOL_CALL`, produced only by the two gate-approved appenders).

**(6) 不暴露 — clean.** `autonomy_tier` is affordance-only; `mcp__` stripped; unknown tool → safe generic. The no-raw-leak component tests exist (`PendingDecision.test.tsx`, `MessageItem.test.tsx`).

## Y1 — Y2's routed consistency is shipped as duplication, not guarded (probe #4) — **should-fix, α-lean**

The architect routed R0-A-on-plan Y2 as "make the snapshot(D2) and endpoint(D3) predicates **position-anchored *and* consistent (byte-for-byte)**." Position-anchoring landed correctly (above). **Consistency, however, is achieved by two independent copies:** `_PENDING_RESOLUTION_TYPES` (`snapshot.py:97-103`) and `_CONFIRM_RESOLUTION_TYPES` (`app.py:74-80`) — identical today ({`TOOL_CALL`, `TOOL_RESULT`, `TOOL_FAILED`, `TOOL_CALL_CANCELLED`}), but with **no shared constant and no test asserting their equality.** A future change that adds a resolution type to one and not the other silently re-opens the exact snapshot-vs-endpoint divergence Y2 was routed to close — and `snapshot.py:175`'s comment ("byte-for-byte consistent with the B3 confirm endpoint") would become a false claim no test defends. **Lean α-absorb:** hoist to one shared frozenset (a common home both import) *or* add a test `assert _PENDING_RESOLUTION_TYPES == _CONFIRM_RESOLUTION_TYPES`. Low-urgency (identical now), but it's a constitutional-consistency property the architect explicitly called, shipped without a guard.

## Y2 — the partial-turn execute-stage branch is untested (probe #1/D5) — **should-fix, α-lean**

`app.py:532-534` raises `_ConfirmExecuteError(reason, tool_call_event.id)` → `ConfirmError{stage:"execute", appended_event_id=<tool_call id>}` when the executor fails *after* the `TOOL_CALL` appended — the "approval landed, do **NOT** re-confirm, reconcile via replay" half of ADR-030 D5, which the ADR marks **do-not-reverse**. **No test exercises it.** The 7 confirm test classes (HappyPath / Idempotency / Cancel / RoomStateGate / NoForge / CrossTurnY2 / WriterExecutorAtomicity) never inject an executor failure; the only partial-turn assertion is the *append*-stage half (`appended_event_id is None`, `test_confirm.py:324`). The branch is correctly *implemented*, but the most regression-prone, hardest-to-reason-about half of the partial-turn contract has no safety net. **Lean α-absorb:** add a test — executor raises after the `TOOL_CALL` appends (a failing/mock tool) → assert `ConfirmError{stage:"execute", appended_event_id=<tool_call id>}`, the `TOOL_CALL` is **durably present** (not rolled back), and a re-confirm returns `already_resolved` (idempotent under the failure, layer-1 catches the orphaned `TOOL_CALL`).

## 🟢 Nits (senior/junior discretion)

- **N-a:** `test_event.py:131 test_all_16_event_types_constructible` loops `for et in EventType` (dynamic — correctly covers all 21 incl. the 2 new), but the name + docstring "16" is stale (now 21). Rename.
- **N-b (precision note, not a defect):** the position-anchoring makes layer-1 + the snapshot collision-safe, but the executor's **layer-2 guard remains full-room `call_id`** by ADR-028 D2 design. So in a rare cross-turn `call_id` collision where an earlier identical `call_id` already has a `TOOL_RESULT`, a freshly-confirmed call is **false-skipped by the executor** (`executor.py:100-115`) — fail-safe (no double-exec, no forge; liveness-only). Worth a one-line ADR-030 note that position-anchoring is consistent at the snapshot+endpoint layers, with layer-2 retaining the inherited ADR-028 D2 full-room posture (so the "consistent" claim is scoped accurately).

## Absorbed plan-stage findings — all landed ✅

| Plan-stage | Impl evidence |
|---|---|
| Y1 → t4 two-appender restatement + test | `test_constitution.py` t4 amended (AST, exactly-two); honest docstring. ✅ |
| Y2 → position-anchored + consistent | snapshot + endpoint both `[idx+1:]` (✅ position); **consistency unguarded → Y1 above**. |
| R0-B Y3 → reject closed room | `app.py:447-448` + `test_confirm_on_closed_room_fails_with_room_closed`. ✅ |
| N1 → drop provenance-less `user_id`/`DECISION` | approve appends **no** `DECISION` event (`app.py:502-538`); audit = AD → PENDING → TOOL_CALL → RESULT. ✅ |
| N2 → `TOOL_CALL_CANCELLED` discipline | in `EventType` + `TYPED_METADATA` (`event.py:97-98,386`) + `ToolCallCancelledMeta`. ✅ |
| N3 → writer-executor-atomicity test | `test_confirm_runs_on_writer_executor`. ✅ |

## State note (for the orchestrator)
`.workflow/P3.6.yaml` reads **`awaiting_junior_impl`** — the impl has landed (8 atomics pushed) but the state has not advanced to a review state. R0-A is mandatory regardless (ADR-008 Amд1); I ran it on the architect's dispatch. Flagging the state for advance + noting **`requires_cross_family_review: true`** → the **impl-stage dual-lens R0-B** is still pending (the plan-stage R0-B does not discharge it; cf. the ADR-028 precedent of an impl-stage re-probe). Routing leans are **α-absorb for both Y1 and Y2**; I do not route.
