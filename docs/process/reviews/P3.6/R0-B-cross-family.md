---
task_id: P3.6
round: R0-B
verdict: clean
findings_count:
  red: 0
  yellow: 4
  green: 3
verdict_history:
  - [2026-06-03, cross-family, needs_architect, "Plan-stage review of ADR-030 + senior plan P3.6. Design is correct; 4 🟡 internal-consistency / underspecification findings. No 🔴: the forge-prevention, idempotency, downstream-of-gate, and partial-turn designs are all sound."]
  - [2026-06-03, cross-family, clean, "Architect routed all 4 🟡 → α. Senior absorbed: Y1 ADR-030 D1 inscribes the two-appender broadening (t4 test amended in B3); Y2 crash-window analysis added (recoverable pre-execute; inherited post-append window noted out-of-scope); Y3 explicit terminal-room gate added; Y4 superseded-brief-statements enumerated in ADR-030 Context. No design change. See architect-routing-on-plan.md."]
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

### 🟡 Y2 — Server-crash-between-append-and-execute gap not discussed

ADR-030 D3 + senior plan B3: the confirm handler appends the `TOOL_CALL`, then calls `execute_pending_tool_calls`. If the server crashes after the append but before executor completion, the `TOOL_CALL` is durable but **never executed**. The still-pending check (D3 step 2) would block re-confirmation (a `TOOL_CALL` exists for that `call_id`), so the call is forever appended but never executed — a **lost execution**.

This is a **pre-existing pattern**, not a new gap: `_post_intent` at `app.py:354-364` has the same append-then-execute sequence on the same writer thread, with the same crash window. The confirm endpoint inherits the pattern faithfully.

**Why this matters for the confirm path more than the AUTO path**: the AUTO path appends `TOOL_CALL`+executes in a single `_write_and_turn` closure — crashing Python loses both (the thread dies). But `EventStore.append` is durable per-call (SQLite WAL), so a crash after `event_store.append(TOOL_CALL)` but before `execute_pending_tool_calls` leaves a durable-but-unexecuted `TOOL_CALL`. The executor has no startup recovery (no "find unexecuted TOOL_CALLs without TOOL_RESULT" scan on boot). This is the same for both paths.

**Suggested investigation:** Not a P3.6 scope issue — this is a general executor crash-recovery gap. The dual-lens concern is that the confirm path's human-in-the-loop semantics make a lost execution more user-visible than the AUTO path (the user explicitly approved the call and expects it to run). The architect may want a follow-up slice for executor crash-recovery. For P3.6: at minimum, note the gap in the ADR's reversibility analysis or the plan's risk section.

### 🟡 Y3 — No room-state check on confirm (underspecified edge case)

ADR-030 D3 + plan B3 acceptance says "confirm on a closed/transitioned room → fail closed (`stage:'append'`)." But the described handler logic (D3 steps 1–4) does **not** include a room-state check. The existing `_post_intent` at `app.py:328-330` also does not check room state — it just loads the room to verify existence. So the plan is consistent with the existing pattern, but the acceptance criterion over-promises relative to the described implementation.

**Suggested investigation:** Either (a) add an explicit room-state gate to the confirm handler ("room.state must be `active`"), or (b) strike the "closed/transitioned room → fail closed" claim from the acceptance criteria and note that the confirm endpoint inherits `_post_intent`'s room-existence-only check pattern. The operational risk is low (localhost-trust MVP, ADR-025 D7), but the acceptance-test discrepancy matters for the junior implementer.

### 🟡 Y4 — Plan length/budget discrepancy acknowledged but the brief's other assumptions may confuse the junior

The senior's §5.4 acknowledges the plan exceeds the brief's ~1200–1800 word budget. The brief was written under the (b) frontend-only assumption; (c) cross-track is a larger scope. This is well-surfaced.

However, the brief contains several statements that are now **false under (c)** but not explicitly contradicted in the plan:
- Brief: "adds zero Python for the frontend-track scope" — false under (c); B1-B3 add Python.
- Brief: "No backend / API / gate / executor change" — false under (c); the confirm endpoint is a new API route, and `tool_dispatch.py` is modified.
- Brief: "binds the same frozen ADR-025 contract" — false under (c); the confirm endpoint is a deliberate contract change (ADR-025 D2 amendment).

The plan correctly overrides these, but the junior might read both documents and be confused. The architect's ratification of ADR-030 should explicitly note which brief constraints are superseded by the (c) ruling.

**Suggested investigation:** The architect routing note (or ADR-030 ratification) should enumerate the brief statements that (c) overrides, so the junior has a single source of truth.

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
