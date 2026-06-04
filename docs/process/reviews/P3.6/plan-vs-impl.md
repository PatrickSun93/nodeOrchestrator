---
task_id: P3.6
stage: plan-vs-impl
reviewer: senior
verdict: clean
plan_under_review: docs/process/senior-plans/P3.6.md
adr_under_review: ADR-030
impl_branch: claude/P3.6-impl
impl_head: 16eca20
date: 2026-06-03
scope: >-
  Plan-vs-impl fidelity lens over the 8 atomics (B1-B3, F1-F5) vs senior-plans/P3.6.md
  + ADR-030 (Accepted). Focus on the seven routing-absorbed hard points: no-forge,
  position-anchored scan consistency, two-layer idempotency, t4 two-appender amendment,
  room-state gate, TOOL_CALL_PENDING/CANCELLED event discipline, 不暴露 (D-C).
findings: >-
  Faithful on all seven hard points; design invariants implemented + discriminatingly
  tested. 3 🟢 future-drift / cosmetic nits, none blocking. The empty-gate-diff +
  unchanged-executor invariants hold structurally (those source files are not in the diff).
---

# Plan-vs-impl — P3.6 (confirm-then-execute + GUI completeness)

**Verdict: `clean`.** The impl is a faithful realization of the plan + ADR-030. Eight atomics map 1:1 to the planned tasks (B1-B3, F1-F5). Every routing-absorbed hard point is implemented as specified and tested discriminatingly. The unique plan-vs-impl lens (impl satisfies acceptance but drifts on a plan-implied invariant) surfaced **no drift that changes behavior** — only 3 🟢 future-drift/cosmetic nits the senior may note for the junior, none routing-worthy.

Gates were **architect-verified** (backend mypy 220 / pytest 1573; frontend eslint+prettier+tsc+vitest 107+codegen:check) — not a junior self-claim, so the usual src/-only gate-scope caveat does not apply.

## Empty-diff invariants — held structurally (not eyeballed)

The plan's load-bearing constraint is that the gate **decision logic** and the **executor** are untouched. Verified by the change set itself: `src/orchestrator/autonomy/` (scoring.py, emission.py), `src/orchestrator/tools/executor.py`, and `src/orchestrator/rooms/` are **not in the diff** (`git diff --stat origin/main...16eca20`). The only gate-path source touched is `agents/tool_dispatch.py`, and that change is purely the additive `TOOL_CALL_PENDING` append in the previously-empty countdown/hard branch (the AUTO branch + `emit_gate_decision` call are unchanged). So "score/decide_tier/emit_gate_decision unchanged" and "execute_pending_tool_calls unchanged" are true by construction.

## The seven hard points — verified against the diff

1. **No-forge / backend-authoritative (ADR-030 HR#1).** `api/app.py::_post_confirm` reconstructs `ToolCallMeta{tool_name, call_id, params}` + `author=build_author(pending_meta.initiating_agent)` **entirely from `pending_meta`** (the persisted `TOOL_CALL_PENDING` record) — the request `body` is read only for `pending_event_id` + `decision`. `ConfirmRequest` (`wire.py`) is `extra="forbid"` with only those two fields → `tool_name`/`params`/`author` are type-impossible to smuggle. **Faithful.**

2. **Position-anchored scan (B2≡B3).** `derived/snapshot.py` (`_PENDING_RESOLUTION_TYPES`, `for idx,e in enumerate(...)` + `sorted_events[idx+1:]`) and `api/app.py` (`_CONFIRM_RESOLUTION_TYPES`, `sorted_events[pending_idx+1:]`) use the **same 4 resolution types** {TOOL_CALL, TOOL_RESULT, TOOL_FAILED, TOOL_CALL_CANCELLED} and the **same after-the-pending-event** predicate (`later.metadata.get("call_id","") == <pending>.call_id`). A turn-1 result does not resolve a turn-5 same-`call_id` pending event in either. Behaviorally pinned on both sides (`test_snapshot.py` + `test_confirm.py:437-458` cross-turn-collision). **Faithful** (see N1 for the duplication nit).

3. **Two-layer idempotency.** Layer 1 = the still-pending check (rejects `already_resolved` once a `TOOL_CALL` exists after the pending event); layer 2 = the executor's full-room `call_id` guard. The whole `_confirm_on_writer` runs via `loop.run_in_executor(ctx.writer_executor, …)` (`max_workers=1`), so check→append→execute is atomic — two confirms serialize; the second sees the first's `TOOL_CALL` → reject. `test_confirm.py:228` asserts exactly one `TOOL_CALL`/`TOOL_RESULT` under double-approve; `:280` approve-after-cancel → `already_resolved`. **Faithful.**

4. **t4 two-appender amendment (Y1).** `tests/tools/test_constitution.py::test_t4_tool_call_sole_appender_in_src` now AST-allows **exactly two** appenders (`agents/tool_dispatch.py` + `api/app.py`) and asserts no third; the docstring honestly inscribes the broadening + names the confirm appender's behavioral (non-grep-verifiable) downstream-of-gate guard. B1's one-appender assertion is correctly scoped to B1 (the t4 test is amended in the B3 commit `a84f18f`, not B1). **Faithful to the ratified Y1 disposition.**

5. **Room-state gate (Y3).** `_post_confirm` step 2: `if room.state == "closed": raise _ConfirmAppendError("room_closed")` — an **explicit** handler check, returning `stage:"append"`. `test_confirm.py:307` asserts it. **Faithful.**

6. **Event discipline (N2).** `TOOL_CALL_PENDING` + `ToolCallPendingMeta{tool_name,call_id,params,tier,initiating_agent}` and `TOOL_CALL_CANCELLED` + `ToolCallCancelledMeta{call_id}` are added to `EventType`, the `TYPED_METADATA` registry, with `validate_metadata` round-trip + extra-field-rejection tests (`test_event.py:661-695`). **Faithful** — both new types get the same discipline B1 gives `TOOL_CALL_PENDING`.

7. **不暴露 (D-C).** `uiStrings.toolNameLabel` strips `mcp__<server>__`, maps known tools, unknown → "一个工具"; `PendingDecision.tsx` uses `autonomy_tier` only to pick a CSS affordance (`isCountdown`), never renders it; `tool_call_pending`→"等待确认", `autonomy_decision`→"待确认" (humanized). Discriminating no-raw-leak tests assert tier tokens / `mcp__` / "skill"/"plugin" never in the DOM across all 21 event types (`PendingDecision.test.tsx:77-97`, `MessageItem.test.tsx:180-261`); no-forge test asserts the confirm body is only `{pending_event_id, decision}` (`PendingDecision.test.tsx:100`). **Faithful.**

## Partial-turn + the live loop (cross-check)

ADR-030 D5: `_ConfirmAppendError`→`stage:"append"` (422), `_ConfirmExecuteError`→`stage:"execute"`+`appended_event_id` (500). `useConfirm` honors it (`stage:"execute"`→confirmed/no-repost; else→error/retry). The approve path publishes `get_room_events[pre_cursor:]` (TOOL_CALL+TOOL_RESULT) to the bus; the store's `applyPendingCalls` removes the pending call on a matching resolution event — the live loop closes. N1 (dropped `user_id`/`DECISION`) is honored: `_post_confirm` appends only `TOOL_CALL`/`TOOL_CALL_CANCELLED`, no `DECISION` (so `decision_count` is not inflated by confirms).

## Nits (🟢 — senior notes; no architect routing)

- **N1 — the B2/B3 resolution-type set is duplicated, consistency comment-enforced.** `_PENDING_RESOLUTION_TYPES` (snapshot.py) and `_CONFIRM_RESOLUTION_TYPES` (app.py) are two separate frozensets with a "Must be identical to snapshot.py" comment. Currently byte-identical + behaviorally pinned on both sides, so the plan's "byte-for-byte consistent" requirement **is met** — but the consistency is not *structurally* enforced; a future edit to one could silently drift the other. Cheap pin: a test asserting `_PENDING_RESOLUTION_TYPES == _CONFIRM_RESOLUTION_TYPES`, or promote to one shared public constant. (Layering note: `api/` already imports from `derived/`, so sharing is feasible; the duplication is a defensible api↔derived decoupling choice — hence 🟢, not a fix demand.)
- **N2 — `ToolCallRef.autonomy_tier` still includes the now-dead `"unknown"` variant** (snapshot.py producer no longer emits it; the Literal + codegen'd `schema.ts` still carry it). Harmless (the type is wider than the producer; forward-compatible). Could tighten later.
- **N3 — `TOOL_CALL_CANCELLED` author is `agent:<initiating_agent>`**, where the plan's loose wording said "author = the confirming surface". The impl's choice (agent-scoped) is reasonable and keeps the resolution marker agent-authored; purely cosmetic, no correctness impact (the author of a cancel marker is not load-bearing — only its `call_id` + position matter for the predicate).

## Expected next

Per ADR-008 Amendment 1 (Route B), plan-vs-impl auto-advances `awaiting_senior_plan_vs_impl` → `awaiting_R0_A` regardless of verdict. With `requires_cross_family_review: true`, the next dispatch is the **mandatory impl-stage dual-lens R0-B** (the `external-r0b-prompt.md` re-probes no-forge / idempotency / the t4 two-appender guard on the implementation), alongside R0-A.
</content>
