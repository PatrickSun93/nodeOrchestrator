---
task_id: P3.6
round: R0-B
verdict: clean
findings_count:
  red: 0
  yellow: 5
  green: 10
verdict_history:
  - [2026-06-03, cross-family, needs_architect, "Plan-stage review of ADR-030 + senior plan P3.6. Design is correct; 4 🟡 internal-consistency / underspecification findings. No 🔴: the forge-prevention, idempotency, downstream-of-gate, and partial-turn designs are all sound."]
  - [2026-06-03, cross-family, clean, "Architect routed all 4 🟡 → α. Senior absorbed: Y1 ADR-030 D1 inscribes the two-appender broadening (t4 test amended in B3); Y2 crash-window analysis added (recoverable pre-execute; inherited post-append window noted out-of-scope); Y3 explicit terminal-room gate added; Y4 superseded-brief-statements enumerated in ADR-030 Context. No design change. See architect-routing-on-plan.md."]
  - [2026-06-03, cross-family, clean, "Impl-stage re-review @ 16eca20 (8 atomics B1→F5). All 7 probe surfaces verified against code. Forge-prevention, idempotency (position-anchored+call_id guard), cross-turn collision, downstream-of-gate, t4 two-appender, room-state gate, partial-turn, 不暴露 all correctly implemented. One 🟡 (Y5): ADR-030 D3 DECISION audit event missing from confirm handler. 7 🟢 confirmations. No 🔴."]
---

# R0-B cross-family review — P3.6 plan-stage (ADR-030 + senior plan)

## Lens preamble

Plan-stage review per `external-r0b-prompt.md` probe surfaces. Over-correcting for: trust-the-types-means-trust-the-runtime (trace each write path through the single-writer serialization), agreeableness (the plan/ADR are well-structured but contain internal inconsistencies worth flagging), and under-weighted failure modes (crash-between-append-and-execute, room-state gating). All claims verified against `origin/main` @ b0e7fae: code at `src/orchestrator/agents/tool_dispatch.py`, `src/orchestrator/autonomy/emission.py`, `src/orchestrator/derived/snapshot.py`, `src/orchestrator/tools/executor.py`, `src/orchestrator/api/app.py`, `src/orchestrator/core/event.py`.

The senior's §5 push-back — that the brief's "data already on the frozen wire" premise is wrong — is correct and verified. The `else` branch at `tool_dispatch.py:125-134` persists nothing; `AUTONOMY_DECISION` at `emission.py:86-108` lacks `call_id`+`params`; `tool_calls_pending_confirm` at `snapshot.py:157-190` is structurally empty in the running app. ADR-030 D1 (`TOOL_CALL_PENDING`) is the correct and minimal fix.

## Findings

### 🟡 Y1 — ADR-030 D1 "sole-appender preserved" claim contradicts D3 "inscribed broadening" + the t4 constitutional test will break

`docs/decisions/ADR-030-confirm-then-execute-human-gating-approval.md` D1 states:

> `EventType.TOOL_CALL` keeps **exactly one appender** (the AUTO branch); the new event is a **different type with its own (also single) appender**, so ADR-028 D6 t4's sole-appender property is preserved verbatim for `TOOL_CALL`.

This is factually incorrect. The confirm endpoint (D3 step 4) appends a `TOOL_CALL` event — a **second** appender, not the AUTO branch. The ADR acknowledges this in D3 ("Backend-now-authors-an-agent-TOOL_CALL — inscribed broadening"), but D1's claim of "preserved verbatim" is an internal contradiction.

The constitutional test `tests/tools/test_constitution.py::test_t4_tool_call_sole_appender_in_src` AST-scans all `src/` Python files and asserts that **only** `agents/tool_dispatch.py` appends `TOOL_CALL`. This test **will break** when the confirm endpoint appends a `TOOL_CALL`. The plan B1 acceptance states "a test asserts `EventType.TOOL_CALL` still has exactly one appender" — but B3 introduces the second appender, creating a plan-level inconsistency between B1 and B3.

**The design IS correct**: the confirm endpoint appending `TOOL_CALL` is the whole point of confirm-then-execute. The second appender is still downstream-of-gate (it validates a gate-produced `TOOL_CALL_PENDING` record). The downstream-of-gate guarantee is **preserved in intent** even though the mechanism broadens — both paths to `TOOL_CALL` require a prior gate decision. But the ADR text needs to stop claiming "sole-appender preserved" and instead inscribe the broadening explicitly in D1 (not just D3), and the t4 constitutional test must be updated to acknowledge the confirm endpoint as a valid second origin of `TOOL_CALL`.

**Suggested investigation:** The ADR should state in D1: "ADR-028 D6 t4's sole-appender property is **broadened**: TOOL_CALL now has two appenders (AUTO branch + confirm endpoint), both downstream-of-gate via different paths. The t4 constitutional test is amended to allow both." The plan B1 acceptance criterion about "exactly one appender" should be scoped to the B1 commit only ("at B1, TOOL_CALL still has exactly one appender — the confirm endpoint's appender lands in B3").

**→ Routed α; senior absorbed. Verified in impl: t4 test at `tests/tools/test_constitution.py:161-217` now asserts exactly TWO appenders (`tool_dispatch.py` + `api/app.py`), AST-scans for third. ✅**

### 🟡 Y2 — Server-crash-between-append-and-execute gap not discussed

ADR-030 D3 + senior plan B3: the confirm handler appends the `TOOL_CALL`, then calls `execute_pending_tool_calls`. If the server crashes after the append but before executor completion, the `TOOL_CALL` is durable but **never executed**. The still-pending check (D3 step 2) would block re-confirmation (a `TOOL_CALL` exists for that `call_id`), so the call is forever appended but never executed — a **lost execution**.

This is a **pre-existing pattern**, not a new gap: `_post_intent` at `app.py:354-364` has the same append-then-execute sequence on the same writer thread, with the same crash window. The confirm endpoint inherits the pattern faithfully.

**Why this matters for the confirm path more than the AUTO path**: the AUTO path appends `TOOL_CALL`+executes in a single `_write_and_turn` closure — crashing Python loses both (the thread dies). But `EventStore.append` is durable per-call (SQLite WAL), so a crash after `event_store.append(TOOL_CALL)` but before `execute_pending_tool_calls` leaves a durable-but-unexecuted `TOOL_CALL`. The executor has no startup recovery (no "find unexecuted TOOL_CALLs without TOOL_RESULT" scan on boot). This is the same for both paths.

**Suggested investigation:** Not a P3.6 scope issue — this is a general executor crash-recovery gap. The dual-lens concern is that the confirm path's human-in-the-loop semantics make a lost execution more user-visible than the AUTO path (the user explicitly approved the call and expects it to run). The architect may want a follow-up slice for executor crash-recovery. For P3.6: at minimum, note the gap in the ADR's reversibility analysis or the plan's risk section.

**→ Routed α; senior added crash-window analysis (recoverable pre-execute; inherited post-append window out-of-scope). Not a P3.6 fix; follow-up slice candidate.**

### 🟡 Y3 — No room-state check on confirm (underspecified edge case)

ADR-030 D3 + plan B3 acceptance says "confirm on a closed/transitioned room → fail closed (`stage:'append'`)." But the described handler logic (D3 steps 1–4) does **not** include a room-state check. The existing `_post_intent` at `app.py:328-330` also does not check room state — it just loads the room to verify existence. So the plan is consistent with the existing pattern, but the acceptance criterion over-promises relative to the described implementation.

**Suggested investigation:** Either (a) add an explicit room-state gate to the confirm handler ("room.state must be `active`"), or (b) strike the "closed/transitioned room → fail closed" claim from the acceptance criteria and note that the confirm endpoint inherits `_post_intent`'s room-existence-only check pattern. The operational risk is low (localhost-trust MVP, ADR-025 D7), but the acceptance-test discrepancy matters for the junior implementer.

**→ Routed α; senior added explicit terminal-room gate. Verified in impl: `app.py:450-451` — `if room.state == "closed": raise _ConfirmAppendError("room_closed")`. Test `test_confirm_on_closed_room_fails_with_room_closed` covers it. Non-closed states (setup/exploration/convergence/snapshot_pending) are allowed. ✅**

### 🟡 Y4 — Plan length/budget discrepancy acknowledged but the brief's other assumptions may confuse the junior

The senior's §5.4 acknowledges the plan exceeds the brief's ~1200–1800 word budget. The brief was written under the (b) frontend-only assumption; (c) cross-track is a larger scope. This is well-surfaced.

However, the brief contains several statements that are now **false under (c)** but not explicitly contradicted in the plan:
- Brief: "adds zero Python for the frontend-track scope" — false under (c); B1-B3 add Python.
- Brief: "No backend / API / gate / executor change" — false under (c); the confirm endpoint is a new API route, and `tool_dispatch.py` is modified.
- Brief: "binds the same frozen ADR-025 contract" — false under (c); the confirm endpoint is a deliberate contract change (ADR-025 D2 amendment).

The plan correctly overrides these, but the junior might read both documents and be confused. The architect's ratification of ADR-030 should explicitly note which brief constraints are superseded by the (c) ruling.

**Suggested investigation:** The architect routing note (or ADR-030 ratification) should enumerate the brief statements that (c) overrides, so the junior has a single source of truth.

**→ Routed α; senior enumerated superseded brief statements in ADR-030 Context. Junior implemented correctly against the plan. ✅**

### 🟢 G1 — Forge-prevention design is robust (probe 1, verified)

`ConfirmRequest{pending_event_id, decision}` with `extra="forbid"` at the Pydantic schema layer prevents client-supplied `tool_name`/`params`/`author`. The server reconstructs the `TOOL_CALL` from the persisted `TOOL_CALL_PENDING` record — `tool_name`/`call_id`/`params` from `ToolCallPendingMeta`, `author = agent:<initiating_agent>` from the record. A crafted `pending_event_id` pointing at a non-`TOOL_CALL_PENDING` event, a cross-room event, or a fabricated ID → `NotFoundError` → `stage:"append"`. The only path to a `TOOL_CALL` from a client is `/confirm` over a genuine gate-produced `TOOL_CALL_PENDING` record. **No forge path found.**

### 🟢 G2 — Idempotency two-layer guard is correctly designed; single-writer serialization is the foundation (probe 2, verified)

Both layers are race-free because all writes serialize on `ctx.writer_executor` (max_workers=1, `app.py:138`). Two concurrent confirms → serialized; second sees first's `TOOL_CALL`/`TOOL_RESULT` → rejected. Confirm vs cancel → serialized; whichever runs first wins. Cross-turn `call_id` collision → full-room guard catches it (the executor scans `all_room_events`, not just the window). The layers complement each other: layer 1 (still-pending check) catches `TOOL_CALL` re-append; layer 2 (executor guard) catches `TOOL_RESULT`/`TOOL_FAILED` re-execution. **No double-execute path found.**

Noted: layer 1 scans for `TOOL_CALL` while the executor guard scans for `TOOL_RESULT`/`TOOL_FAILED` only — by design, not an oversight. At confirm time, the just-appended `TOOL_CALL` hasn't produced a result yet, so the executor guard passes correctly.

### 🟢 G3 — COUNTDOWN has no server-side auto-fire; explicit-confirm MVP is scheduler-free (probe 3, verified)

ADR-030 D4: "nothing auto-fires server-side." The countdown is a UI affordance only. No timer, no scheduler, no headless execution path in the design. The plan tasks (B1–B3) have zero timer/scheduler components. **The "human in every loop" guarantee holds.**

## Synthesis

The design is **correct on all trust-surface probes**: forge-prevention is robust (G1), idempotency is race-free on the single writer (G2), COUNTDOWN has no headless execution (G3), partial-turn correctly mirrors ADR-025 D5, and downstream-of-gate is preserved via the `TOOL_CALL_PENDING` requirement. No 🔴.

The four 🟡 findings cluster around **internal consistency**: the ADR contradicts itself on the sole-appender claim (Y1), the plan's B1 and B3 acceptance criteria are inconsistent with each other (same root cause), the server-crash gap is inherited but more consequential for human-confirmed calls (Y2), the room-state check acceptance criterion over-promises (Y3), and the brief-plan discrepancy under (c) could confuse the junior (Y4). All are surfaceable and fixable without design change.

**Verdict: needs_architect** — the four 🟡 findings warrant architect routing before junior implementation begins. No design changes needed; the fixes are textual (ADR clarification, plan qualifiers, acceptance-criterion tightening).

---

# R0-B cross-family review — P3.6 impl-stage (8 atomics @ 16eca20)

## Lens preamble

Impl-stage re-review against the same probe surfaces as the plan-stage review (`external-r0b-prompt.md`). All 4 plan-stage 🟡 were routed α and absorbed before implementation. This pass verifies the implementation at `origin/claude/P3.6-impl` @ 16eca20 (8 atomics: B1→B2→B3→F1→F2→F3→F4→F5) correctly realizes the ADR-030 + plan design — tracing each trust-surface probe through the concrete code.

Evidence: all diffs read from `git diff origin/main..origin/claude/P3.6-impl`. 34 files changed, +2751/-141. Executor and autonomy modules confirmed **zero diff** (unchanged). 15 confirm tests + 4 snapshot B2 tests + 1 executor behavioral test + t4 constitutional test amendment verified.

## Probe 1: GUI-forge-a-TOOL_CALL — 🟢 IMPLEMENTED CORRECTLY

**Schema-layer forge guard**: `ConfirmRequest` at `api/wire.py:121-126` — `model_config = ConfigDict(frozen=True, extra="forbid")`, only `pending_event_id: EventId` + `decision: Literal["approve","cancel"]`. No `tool_name`/`params`/`author` fields exist on the type. Extra fields → 422 at the Pydantic layer (test: `test_extra_fields_in_request_rejected`).

**Backend-authoritative reconstruction**: `_post_confirm` at `api/app.py:468-479` reconstructs the `TOOL_CALL` entirely from `ToolCallPendingMeta`:
- `tool_name=pending_meta.tool_name` (from record, never request)
- `call_id=pending_meta.call_id` (from record, never request)
- `params=pending_meta.params` (from record, never request)
- `author=build_author(pending_meta.initiating_agent)` — agent-authored, not user-settable

**Validation chain**: `pending_event_id` must resolve to a `TOOL_CALL_PENDING` event (type check at `app.py:458-459` — `e.type == EventType.TOOL_CALL_PENDING`). Unknown id → "not_found". Non-`TOOL_CALL_PENDING` type → "not_found" (test: `test_non_tool_call_pending_event_id_fails_closed`). Cross-room → "not_found" (test: `test_room_not_found`).

**Client-side**: `useConfirm` at `ui/src/hooks/useConfirm.ts:34` sends only `{pending_event_id: pendingEventId, decision}`. `postConfirm` at `ui/src/api/client.ts` sends `JSON.stringify(body)`. The PendingDecision component passes only `(roomId, p.event_id, "approve"|"cancel")`. Test `approve button calls confirm with {roomId, event_id, 'approve'} — no-forge` verifies no extra fields.

**No forge path found.** 🔒

## Probe 2: Idempotency / double-execution — 🟢 IMPLEMENTED CORRECTLY

**Layer 1 — Position-anchored still-pending check**: `api/app.py:462-468` scans events **after** the pending event's position (`sorted_events[pending_idx + 1:]`) for resolution events with the same `call_id`. `_CONFIRM_RESOLUTION_TYPES` at `app.py:72-79` is byte-for-byte identical to snapshot's `_PENDING_RESOLUTION_TYPES` at `snapshot.py:97-104` (comment: "B2/B3 consistency invariant").

**Layer 2 — Executor `call_id` guard**: `executor.py:97-104` (unchanged, zero diff) scans full room history for `TOOL_RESULT`/`TOOL_FAILED` with matching `call_id`.

**Single-writer atomicity**: Both layers run on `ctx.writer_executor` (max_workers=1, `app.py:138`). `_confirm_on_writer` closure at `app.py:432` runs via `loop.run_in_executor(ctx.writer_executor, ...)`. Test `test_confirm_runs_on_writer_executor` verifies single-thread execution.

**Test coverage**:
- `test_double_approve_second_returns_already_resolved` — second approve → 422, `stage:"append"`, `reason:"already_resolved"`
- `test_double_approve_produces_single_tool_call_and_result` — exactly one TOOL_CALL in room history
- `test_approve_after_cancel_is_already_resolved` — cancel then approve → already_resolved
- Executor level: `test_tool_call_pending_in_window_not_executed` — TOOL_CALL_PENDING is ignored by executor behavioral filter

**No double-execute path found.** 🔒

## Probe 3: Cross-turn call_id collision — 🟢 IMPLEMENTED CORRECTLY

**Position-anchored scan** (the key design choice): Both the confirm endpoint and snapshot use position-anchored resolution, not position-blind. A prior-turn `TOOL_RESULT(abc)` that appears **before** a later `TOOL_CALL_PENDING(abc)` does NOT resolve the pending call.

**Snapshot test**: `test_produce_snapshot_pending_cross_turn_collision_y2` at `tests/derived/test_snapshot.py` — prior TOOL_RESULT(abc) @ t=1000 → fresh TOOL_CALL_PENDING(abc) @ t=5000 → still pending (result is before, position-anchored ignores).

**Confirm test**: `test_prior_turn_result_does_not_false_reject_fresh_pending` at `tests/api/test_confirm.py` §6 — same scenario, confirm succeeds (200), TOOL_CALL appended with call_id "abc".

**No false-reject; no false-pending.** The position-anchored design correctly handles LLM-generated `call_id` reuse across turns. 🔒

## Probe 4: Downstream-of-gate — 🟢 IMPLEMENTED CORRECTLY

**TOOL_CALL_PENDING sole origin**: `tool_dispatch.py:127-149` — the countdown/hard branch is the **only** appender of `TOOL_CALL_PENDING`. `ToolCallPendingMeta` at `event.py:345-358` carries `{tool_name, call_id, params, tier, initiating_agent}` — all gate-produced fields.

**Gate decision logic untouched**: `src/orchestrator/autonomy/` — **zero diff** against main. `score`/`decide_tier`/`emit_gate_decision` unchanged.

**Confirm requires gate record**: The confirm handler validates `TOOL_CALL_PENDING` exists (type-checked at `app.py:458-459`). No path to confirm without a prior gate decision.

**Executor unchanged**: `src/orchestrator/tools/executor.py` — **zero diff**. Still processes only `TOOL_CALL` events (behavioral filter at `executor.py:88`). `TOOL_CALL_PENDING` is confirmed ignored by executor test (`test_tool_call_pending_in_window_not_executed`).

**No path to execute a tool without a prior gate decision.** 🔒

## Probe 5: t4 two-appender test — 🟢 IMPLEMENTED CORRECTLY

**t4 amended**: `tests/tools/test_constitution.py:161-217` — `test_t4_tool_call_sole_appender_in_src` now asserts exactly TWO appenders:
- `agents/tool_dispatch.py` (AUTO_EXECUTE branch)
- `api/app.py` (confirm-approve path)

`allowed_appenders = frozenset({tool_dispatch_path, confirm_endpoint_path})` at line 176. AST-scan verifies no third appender. Error message: "TOOL_CALL event appended outside the two legitimate appenders."

**Behavioral guard**: The confirm appender's downstream-of-gate property is behavioral (not structural — pinned by named guard + no-forge acceptance test in `tests/api/`). The t4 test comment at line 17-25 explicitly documents this: "The confirm appender's downstream-of-gate property is a behavioral trust surface (not grep-verifiable), pinned by the named behavioral guard and the no-forge acceptance test in tests/api/."

**No third appender; two-appender invariant enforced by AST scan.** 🔒

## Probe 6: Room-state gate + partial-turn — 🟢 IMPLEMENTED CORRECTLY

**Room-state gate**: `api/app.py:450-451` — `if room.state == "closed": raise _ConfirmAppendError("room_closed")`. Test `test_confirm_on_closed_room_fails_with_room_closed` → 422, `stage:"append"`, `reason:"room_closed"`. Test `test_confirm_on_non_closed_room_proceeds` — setup/exploration/convergence/snapshot_pending all allowed (200).

**Partial-turn error handling**: Two exception classes mirroring `_post_intent`:
- `_ConfirmAppendError` at `app.py:135-138` → 422 `ConfirmError{stage:"append", reason}` (safe retry)
- `_ConfirmExecuteError` at `app.py:141-145` → 500 `ConfirmError{stage:"execute", appended_event_id}` (do NOT re-confirm)

Exception handlers at `app.py:523-544` produce the correct JSON response shape.

**Frontend partial-turn handling**: `useConfirm.ts:44-52`:
- `ce.stage === "execute"` → `setStatus("confirmed")`, **no re-post**
- Otherwise → `setStatus("error")`, allow retry

**asyncapi.md** (doc): `asyncapi.md:78-90` documents the WS error channel semantics for confirm-path failures, consistent with the IntentError pattern.

🔒

## Probe 7: 不暴露 — 🟢 IMPLEMENTED CORRECTLY

**Tool name humanization**: `PendingDecision.tsx:31` — `toolNameLabel(p.tool_name)` applies the `ui_strings` mapper. `mcp__` stripped, humanized name displayed.

**Tier never rendered**: `PendingDecision.tsx:24` — tier drives CSS class only (`isCountdown ? styles.countdown : styles.hard`), never appears in DOM text content.

**No-raw-leak test**: `PendingDecision.test.tsx:80-90` — comprehensive assertion:
```
expect(bodyText).not.toContain("countdown_confirm");
expect(bodyText).not.toContain("hard_confirm");
expect(bodyText).not.toContain("autonomy");
expect(bodyText).not.toContain("skill");
expect(bodyText).not.toContain("plugin");
expect(bodyText).not.toContain("MCP");
expect(bodyText).not.toContain("mcp__");
```

**Unmapped tool fallback**: `ui_strings.ts` fallback for unmapped tools produces a safe generic label — never the raw key.

🔒

## Additional impl-stage findings

### 🟡 Y5 — ADR-030 D3 DECISION audit event missing from confirm handler

**Claim**: ADR-030 D3 specifies: "The human approval is additionally recorded (a `DECISION` event citing `pending_event_id` + `user_id`) so the audit trail reads: `AUTONOMY_DECISION` → `TOOL_CALL_PENDING` → `DECISION` (human approved) → `TOOL_CALL` → `TOOL_RESULT`." The plan B3 "What" section also mentions "+ a `DECISION` recording the human approval."

**Reality**: The confirm handler at `api/app.py:468-495` appends only the `TOOL_CALL` event. No `DECISION` event is appended before or after. The B3 acceptance criteria don't test for a `DECISION` event — the tests only verify TOOL_CALL/TOOL_RESULT.

**Impact**: Low. The audit trail `TOOL_CALL_PENDING` → `TOOL_CALL` → `TOOL_RESULT` is already sufficient to trace the human approval path (the `TOOL_CALL`'s author is `agent:<initiating_agent>` but its origin is the confirm endpoint). The `DECISION` event was specified as an additional human-approval audit marker, but would interact with the decision protocol in potentially unintended ways (`based_on` semantics, `decision_count` inflation, hypothesis lifecycle). The junior may have deliberately omitted it.

**Suggested investigation**: Architect confirm whether the `DECISION` event was intentionally dropped (and if so, strike it from ADR-030 D3) or should be added in a follow-up. Not blocking — the audit trail is complete enough without it.

### 🟢 G4 — `_CONFIRM_RESOLUTION_TYPES` / `_PENDING_RESOLUTION_TYPES` byte-for-byte consistency (probe 2 detail)

`api/app.py:72-79` and `derived/snapshot.py:97-104` define the same frozenset with an explicit comment: "B2/B3 consistency invariant." This is the correct defense against drift between the confirm endpoint's still-pending check and the snapshot's predicate. The `call_id` key is the same string extraction pattern (`str(later.metadata.get("call_id", ""))`) in both files. **No drift.** ✅

### 🟢 G5 — Cancel path: `pre_cursor` correctly scoped for publish

Cancel path at `api/app.py:482-507`: `pre_cursor = len(all_events)` is set before the append, then `new_events = ctx.writer_store.get_room_events(rid)[pre_cursor:]` captures only new events. Same pattern as approve path and `_post_intent`. **Correct cursor-diff publish.** ✅

### 🟢 G6 — `TOOL_CALL_PENDING` not in `_AGENT_PARTICIPATION_TYPES` (consistent with intent)

`derived/snapshot.py:82-89`: `_AGENT_PARTICIPATION_TYPES` does not include `TOOL_CALL_PENDING`. This is correct — `TOOL_CALL_PENDING` is a durable recording event, not an agent participation signal. The agent that produced the pending call is already tracked via `TOOL_CALL`/`AUTONOMY_DECISION` in the same turn. Adding `TOOL_CALL_PENDING` would double-count agents that produce pending calls. **Consistent with intent.** ✅

### 🟢 G7 — Executor behavioral filter correctly ignores `TOOL_CALL_PENDING` (probe 4 detail)

Test `test_tool_call_pending_in_window_not_executed` at `tests/tools/test_executor.py:609-652`: a `TOOL_CALL_PENDING` event in the executor window → no MCP call dispatched, no TOOL_RESULT/TOOL_FAILED appended. The executor's `tool_calls = [e for e in window_events if e.type == EventType.TOOL_CALL]` filter correctly excludes the new type. **No phantom execution.** ✅

## Impl-stage synthesis

The implementation is **thoroughly correct** across all seven probe surfaces. The key architectural decisions from plan-stage are faithfully realized:

1. **Position-anchored still-pending** (not position-blind) — handles cross-turn call_id collisions at both snapshot and endpoint layers
2. **Two-appender t4** — AST-enforced, third appender prevented, behavioral guard for confirm appender's downstream-of-gate property
3. **Byte-for-byte resolution type consistency** — `_CONFIRM_RESOLUTION_TYPES` = `_PENDING_RESOLUTION_TYPES` with explicit comment
4. **Authored `agent:<initiating_agent>`** on confirmed TOOL_CALL — not user, not client-settable
5. **Autonomy + executor zero diff** — gate decision logic and execution path completely untouched
6. **Room-state gate** — explicit closed-room rejection; non-closed states allowed
7. **Partial-turn mirror** — `_ConfirmAppendError`/`_ConfirmExecuteError` exactly mirror `_AppendFailedError`/`_TurnFailedError`

**Verdict: clean** — one 🟡 (Y5 DECISION audit event missing) is low-impact and may be intentional; the trust-surface probes (forge, idempotency, cross-turn, downstream-of-gate, t4, room-state, partial-turn, 不暴露) all pass with concrete code evidence. No 🔴. The previous four plan-stage 🟡 were all absorbed before implementation and verified resolved.
