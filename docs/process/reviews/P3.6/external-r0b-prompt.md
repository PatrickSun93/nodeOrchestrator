# External R0-B prompt — P3.6 confirm-then-execute (dual-lens, gating-approval trust surface)

**Cycle:** P3.6 (D-B=(c)) — the live human-in-the-loop confirm-then-execute loop.
**Why dual-lens (`requires_cross_family_review: true`):** this slice adds a **gating-approval trust surface** — a new write path that turns a gated-but-unexecuted tool call into a real, human-approved execution. The `dual-lens-r0b.md` criteria hold: a contract referenced by future clients (the confirm endpoint), a first runtime exercise of a previously-deferred pattern (confirm-then-execute), and a new failure/concurrency surface (idempotent approval atomic with execution on the single writer). Run the **proxy lens** (Claude, contrarian) first; then the **true cross-family lens** (non-Claude). Append both to `docs/process/reviews/P3.6/R0-B-cross-family.md` (single-file dual-section per the P1.4 precedent).

## Your stance

Take a deliberately **outside-Claude** lens. Over-correct for Claude's biases: trust-the-types-means-trust-the-runtime, over-engineering, agreeableness. **Trace failure modes across module boundaries** and ask "what happens when this specific call fails / races / is replayed at 3am?" Default to **refuted/skeptical** when uncertain; a finding you can't substantiate by tracing the code is not a finding. Cite `file:line`.

## What changed (read these first)

- **ADR-030** (`docs/decisions/ADR-030-confirm-then-execute-human-gating-approval.md`) — the decision. **Senior plan** `docs/process/senior-plans/P3.6.md` — the atomic graph + the §5 surfaced representation gap. **Brief** `docs/process/architect-briefs/P3.6.md`.
- Backend: `core/event.py` (`TOOL_CALL_PENDING` + `ToolCallPendingMeta`, `TOOL_CALL_CANCELLED`), `agents/tool_dispatch.py` (the countdown/hard branch now records a pending event), `derived/snapshot.py` (`tool_calls_pending_confirm` re-pointed), `api/{wire.py,app.py,openapi.json,asyncapi.md}` (the `/confirm` endpoint). **Unchanged (verify they stayed unchanged):** `autonomy/{scoring.py,emission.py}`, `tools/executor.py`.
- Frontend: `ui/src/` — `useConfirm`, the pending-decision surface, the store pending-set, richer rendering.

## Probe surfaces (the trust-surface crux — spend your budget here)

1. **GUI-forge-a-`TOOL_CALL`.** The spine forbids the GUI appending a `TOOL_CALL` (the gate-approval/"forge"). Confirm the **only** path to a `TOOL_CALL` from a client is `/confirm` over a **persisted** `TOOL_CALL_PENDING` record, and that `tool_name`/`params`/`author` are read from that record, **never** from the request body. Can a crafted `ConfirmRequest` (extra fields, a `pending_event_id` pointing at a non-pending or cross-room event, a fabricated id) cause a `TOOL_CALL` with attacker-influenced params/author? Is `ConfirmRequest` `extra="forbid"`? Is the appended `TOOL_CALL` author forced to `agent:<initiating_agent>` from the record (not client-settable)?

2. **Idempotency / double-execution.** Confirming the same pending call twice must append **at most one** `TOOL_CALL` and execute **at most once**. Trace both layers: (a) the endpoint's still-pending check (scan for an existing `TOOL_CALL`/result/cancel for the `call_id`) and (b) the executor's full-room `call_id` guard (`executor.py:97-104`). Are both **atomic on the single writer** (no TOCTOU between check and append)? Race **two concurrent confirms** (two GUI tabs) — does the single-writer serialization actually hold, or is there a window? What about confirm racing the cancel of the same call? What if the LLM re-emits the same `call_id` across turns (the cross-turn collision ADR-028 D2 worried about) — does the guard still hold for a confirmed call?

3. **COUNTDOWN timer semantics.** ADR-030 D4 rules **explicit-confirm, no server-side auto-fire**. Verify nothing fires a `TOOL_CALL` on a timer (no scheduler, no headless execution path). Is the countdown purely a UI affordance? Could a pending call ever execute without a human `approve`? Is the affordance-only treatment of `autonomy_tier` actually leak-free in the GUI (D7e / 不暴露)?

4. **Partial-turn on confirm.** Distinguish `stage:"append"` (nothing actuated → safe retry) from `stage:"execute"` (the `TOOL_CALL` landed → do-not-re-confirm). Trace: if `execute_pending_tool_calls` raises after the `TOOL_CALL` appended, is `stage:"execute"` returned with the `appended_event_id`? Does the store/`useConfirm` honor it (no re-post)? Is the store consistent (the user event/TOOL_CALL durable, no partial write surfaced as success — the ADR-025 D5 invariant extended)?

5. **Backend-authoritative edge cases.** Confirm on a **closed** room / after a state transition; confirm of an **already-resolved** (executed or cancelled) pending call; a `pending_event_id` that is some other event type; server **restart** mid-pending (the `TOOL_CALL_PENDING` is durable — does a restart lose anything? can a stale GUI confirm a call the server already resolved?). All must fail closed, never double-act.

6. **The gate/executor stayed unchanged.** Verify `score`/`decide_tier`/`emit_gate_decision` and `execute_pending_tool_calls` are **not** modified (the empty-gate-diff claim). Confirm `EventType.TOOL_CALL` still has exactly **one** appender (the AUTO branch) and `TOOL_CALL_PENDING` is a distinct type the executor ignores — so the downstream-of-gate guarantee (ADR-028 D6 t4) is preserved, not eroded.

7. **Snapshot re-point correctness.** Does the new `tool_calls_pending_confirm` predicate correctly drop a call once resolved (by `TOOL_CALL`/`TOOL_RESULT`/`TOOL_FAILED`/`TOOL_CALL_CANCELLED`)? Any `call_id` collision or ordering assumption that breaks it? Does it stay a pure function?

## Out of scope (do not file)

- Auth (localhost-trust MVP, ADR-025 D7). Auto-fire-on-timer (deferred, ADR-030 D4). Agent re-dispatch on the result (deferred, ADR-028 D4). The non-confirm FE completeness views (D-A) except for the 不暴露/no-forge invariant on the pending surface.

## Output

`docs/process/reviews/P3.6/R0-B-cross-family.md`, frontmatter `verdict: clean | needs_architect | blocking` + `verdict_history`. Per finding: `file:line`, the failure mode traced, severity (🔴 must-fix / 🟡 should / 🟢 nit), and your confidence. A **🔴 only** for a concretely-traced double-execute / forge / headless-execution / lost-write — not a hypothetical. Note explicitly if you **refute** a plan claim (correction-mode is in scope, per RC-20).
</content>
