# ADR-013: Operator tool-dispatch contract

**Status:** Accepted — 2026-05-27
**Scope:** Locks the runtime contract for converting LLM-emitted tool-call blocks into autonomy-gated event-stream entries. Governs operator-style agents (any agent with `required_capabilities: [tools]`); does not govern tool execution itself (P1.6+).

## Context

P1.4 added the `agents → autonomy` import edge as allowed by constitutional tests but never exercised — `dispatch_turn` captured `LLMResponse.content` and silently discarded `LLMResponse.tool_calls` (`agents/dispatch.py:117-127`). P1.5.5 is the first runtime use. The substrate is mature: `autonomy.gate()`, `autonomy.emit_gate_decision`, `ToolCallMeta`, `EventType.TOOL_CALL`, and a normalized `LLMResponse.tool_calls: list[ToolCall]` (P1.1 — `openai_compatible.py:270-283` and `claude_code_output.py:89-108` both produce the same `ToolCall(id, name, arguments)` shape). What was missing is the **call site** that consumes a non-empty `response.tool_calls` and routes each through the gate.

Three call-site candidates were considered (per P1.5.5 brief push-back #2):

1. **Inside `dispatch_turn`** — add the loop directly after the LLM call. Bloats `dispatch_turn`'s lean per-agent shape.
2. **In `RoomRuntime.run_turn` after `dispatch_turn` returns** — pre-investigated and found **structurally impossible**: `dispatch_turn` discards `response.tool_calls` before returning, and extending `TurnResult` to carry per-agent `tool_calls` breaks the reviewer-validated P1.4/P1.5 contract.
3. **Sibling module called from `dispatch_turn`** — `agents/tool_dispatch.py` exports the gating function; `dispatch_turn` adds a single call site (`if response.tool_calls: process_tool_calls(...)`). Mirrors ADR-011 D4's "separate concern" pattern (dispatch vs context-builder).

Touches Principle 1 (event log is truth — every autonomy gate evaluation emits an audit event), Principle 5 (code decides what code can; LLM proposes, code gates), Principle 9 (no orphaned spec — the tool-call event has a concrete producer, no longer just a vocabulary entry).

**Hard requirements the decision must satisfy**:
- Every tool-call gating returns an event (`autonomy_decision` or `autonomy_refusal`) — Principle 1.
- `TurnResult` contract from P1.4 is preserved unchanged (no breaking field additions).
- `autonomy_decision` event lands before `tool_call` event in stream order for `AUTO_EXECUTE` tier (decision-then-action causality per ADR-005 D6).
- `dispatch_turn` shape (lean per-agent loop) preserved — at most one new call site, no buried sub-loops.
- LLM-tool-call parsing is reused, not reimplemented — `LLMResponse.tool_calls` is the single normalized input.
- Constitutional invariant: `agents → autonomy` direction allowed; reverse `autonomy → agents` still forbidden.

## Decisions

### 1. Dispatch site lives in a sibling module `agents/tool_dispatch.py` called from `dispatch_turn`

`dispatch_turn` adds exactly one new call site after `event_store.append(utterance)`:

```python
if response.tool_calls:
    process_tool_calls(
        response.tool_calls,
        agent_id=agent.id,
        room_id=room.id,
        current_event=current_event,
        event_store=event_store,
        tools=tools,
        thresholds=agent.autonomy_thresholds,
    )
```

The sibling module owns: per-`ToolCall` `Operation` construction; `emit_gate_decision` invocation; tier-conditional `tool_call` event emission; per-call error containment (one `UnknownToolError` doesn't poison the batch).

**Why**: Option 2 from "Considered alternatives" is structurally impossible (tool_calls discarded by the time `RoomRuntime.run_turn` could consume them). Option 1 (inline) viable but mixes concerns — dispatch_turn becomes responsible for both agent loop AND tool-call gating; the reviewer-validated lean shape (one LLM call + one event append per agent) is compromised. Option 3 keeps `dispatch_turn`'s shape, isolates tool-call logic in a testable surface, and matches ADR-011 D4's precedent (separate concern, separate file).

**TurnResult unchanged**: `process_tool_calls` returns `ToolDispatchResult` for logging/observability but `dispatch_turn` does NOT add it to `TurnResult`. Consumers who need tool-dispatch outcomes query `event_store` (the canonical observability path per ADR-001). This preserves reviewer-validated contract from P1.4 + P1.5 — refactor cost of contract change > marginal value of additional return field.

### 2. Tier-to-event mapping is fixed (re-states ADR-005 D6 + ADR-007 D3 for tool-call call site)

For each processed `ToolCall`, the call site behaves as:

| `gate()` outcome | Events appended (in stream order) | `tool_call_event_appended` |
|---|---|---|
| `AUTO_EXECUTE` | `autonomy_decision` (synchronous; from `emit_gate_decision`); then `tool_call` (`ToolCallMeta(tool_name, call_id, params)`) | `True` |
| `COUNTDOWN_CONFIRM` | `autonomy_decision` only | `False` — P2 UI countdown emits `tool_call` if user doesn't intervene |
| `HARD_CONFIRM` | `autonomy_decision` only | `False` — P2 explicit user approval emits `tool_call` |
| `UnknownToolError` (ADR-006) | `autonomy_refusal` (`refusal_reason="unknown_tool"`); no `tool_call` | `False` |

**Causal ordering**: `emit_gate_decision` appends `autonomy_decision` before returning the `AutonomyScore` (P1.2-C4 contract). The call site then appends `tool_call` only on `AUTO_EXECUTE`. Stream timestamp order therefore is decision-then-action — `autonomy_decision` < `tool_call`. This is the audit-record invariant from ADR-005 §6.

**Why re-stated here**: this ADR is what future tool-using agents reference; embedding the mapping locally (with cross-reference) keeps the contract visible at the call site. ADR-005 D6 + ADR-007 D3 remain authoritative; ADR-013 D2 is the operational restatement.

### 3. `Operation.user_explicit_intent` is derived from `current_event.type == EventType.USER_INPUT`

At the dispatch site, `process_tool_calls` reads `current_event.type` and sets `Operation.user_explicit_intent = (current_event.type == EventType.USER_INPUT)`.

**Why**: `current_event` is the only signal available at the dispatch site that distinguishes user-typed action from system-internal flows. The autonomy modifier semantic (ADR-005 D5: user_explicit_intent lowers effective thresholds, granting more autonomy when the user explicitly asked) is honored only when the event chain originates from `USER_INPUT`. Other trigger types (`hypothesis`, `state_transition`, agent-utterance follow-ups) flow through system-internal reasoning and should NOT receive the autonomy boost. P1.6+ snapshot/context layers that need richer intent inference inherit this baseline.

**Alternative considered**: walk the event chain backward to find the originating `user_input`. Rejected: dispatch site is per-turn; multi-event chains are P1.6 snapshot scope. The single-event signal at the dispatch site is sufficient for P1.5.5 and forward-compatible (any chain-based enrichment additively raises the user_explicit_intent signal; defaults are conservative).

### 4. Tools registry threads through `RoomRuntime.run_turn` → `dispatch_turn` → `process_tool_calls` as a keyword parameter

`run_turn` and `dispatch_turn` gain `tools: dict[str, ToolMeta]` as a keyword-only parameter. The caller (config loader → orchestrator entry point) constructs the registry once via `load_tools_config` and passes it through.

**Why**: mirrors existing keyword-parameter threading for `available_agents`, `available_skills`, `regex_registry`. Avoids constructor/singleton patterns (testability cost; hidden coupling). The registry is per-orchestrator-process-lifetime stable; threading via keyword aligns with the prevailing "explicit dependency injection at function boundary" style P1.4 + P1.5 codified.

### 5. LLM-tool-call parsing reuses existing `LLMResponse.tool_calls`; no new shim module

`process_tool_calls` consumes `LLMResponse.tool_calls: list[ToolCall]` directly. Both shipped providers (`openai_compatible.py`, `claude_code_output.py`) already produce the normalized `ToolCall(id, name, arguments)` shape (P1.1 era; verified at this ADR's drafting via grep). The brief's lean toward "probably needs a shim" is refuted by pre-investigation.

**Field mapping** (pinned for the call site):
- `ToolCall.id → ToolCallMeta.call_id` (Pydantic `min_length=1` validation already enforced upstream; malformed cases raise `PermanentProviderError` from the parser)
- `ToolCall.name → ToolCallMeta.tool_name` and → `Operation.tool_id`
- `ToolCall.arguments → ToolCallMeta.params` and → `Operation.params`

**Why pinned here**: future readers asking "where does the LLM tool-call shape become the autonomy `Operation`?" find the mapping in ADR-013 D5; the mapping is otherwise distributed across `llm/types.py`, `core/event.py`, `autonomy/scoring.py`. Inscribing the mapping at the ADR level is cheap (3 lines) and saves cross-file archaeology.

## Considered alternatives

### A. Inline tool-call gating in `dispatch_turn`

Add the gating loop directly after the LLM response capture in `dispatch_turn`. No new module.

**Why rejected (ruled out by D1)**: bloats `dispatch_turn`'s reviewer-validated lean shape (one LLM call → one event append per agent). Mixes concerns; harder to test the tool-call path independently. The sibling-module pattern from ADR-011 D4 (context-builder as separate file) is project precedent for "extract this kind of secondary logic."

### B. Post-dispatch gating in `RoomRuntime.run_turn`

Have `dispatch_turn` carry per-agent tool_calls in `TurnResult`; `RoomRuntime.run_turn` calls a gating function after `dispatch_turn` returns.

**Why rejected (ruled out by D1)**: structurally impossible without breaking the `TurnResult` contract from P1.4 + P1.5. The refactor cost of extending `TurnResult` (and re-validating all consumers + reviewers) exceeds the marginal separation benefit. Also conflates the room-level orchestration with the agent-level tool-call handling — `run_turn` already has 6 responsibilities; adding tool-dispatch would push it past the cognitive-load threshold reviewed in P1.5 R0-A.

### C. LLM-layer shim normalizing tool-call shapes

Add `src/orchestrator/llm/tool_call_parser.py` to unify OpenAI / Anthropic tool-call shapes into a common type before the agent layer consumes them.

**Why rejected (ruled out by D5)**: pre-investigation showed `LLMResponse.tool_calls: list[ToolCall]` is **already** the unified normalized shape. Both providers produce identical `ToolCall(id, name, arguments)` instances. A shim would duplicate existing normalization code; the brief's "probably needs a shim" lean was refuted by reading the parser implementations.

### D. Eager tool execution within `process_tool_calls`

Execute the tool synchronously inside `process_tool_calls` when tier is `AUTO_EXECUTE`; emit both `tool_call` and `tool_result` events from the same call site.

**Why rejected**: violates P1.5.5 brief out-of-scope (tool execution is P1.6+). The decision to defer execution to a separate layer is per ADR-001 — events represent intent + outcome as separate vocabulary entries; collapsing proposal and execution into one site breaks the future executor's ability to consume `tool_call` events uniformly from any source (operator, scheduled task, user-explicit invocation).

## Consequences

**Easier:**

- Every tool-call emission has a single observable code path (`process_tool_calls`) — debugging "why did this tool_call fail/succeed?" follows one trace. The decision/refusal event always precedes (or replaces) the `tool_call` event in stream order; reading the event log linearly explains the autonomy gate's behavior for each call.
- Future tool-using agents (operator-style, scheduled-task, P1.6+ executor agents) inherit the dispatch contract for free — `agents/tool_dispatch.py` is the reuse surface. New agent yamls with `required_capabilities: [tools]` work end-to-end without changes to `dispatch_turn` or the gating path.
- Independent testability: tool-call dispatch logic is tested without standing up `dispatch_turn`'s full fixture (agent + skill + regex_registry + room + snapshot). Test §1 cross-module integration becomes a one-function-under-test exercise; faster, simpler, less brittle.
- ADR-005 D6 + ADR-007 D3 + ADR-006 cascade across the runtime exactly as inscribed — first verification that the existing autonomy substrate carries through to a real producer.

**Harder:**

- One more file to read for a new contributor tracing tool-call behavior — the dispatch_turn → tool_dispatch hop adds a file boundary. Mitigated by the sibling-module pattern being already established (ADR-011 D4 context-builder, autonomy/scoring + autonomy/emission split).
- `dispatch_turn` and `run_turn` signatures gain one new required keyword param (`tools`). All callers update. Production caller updated by P1.5.5-4; test fixtures gain a default `tools={}` where tool calls aren't expected — small ergonomic cost, no contract risk.
- The `agents → autonomy` runtime import edge is now real (not just allowed). Constitutional test `test_constitution_no_llm_calls_in_autonomy_module` continues to pass; the reverse `autonomy → agents` direction stays forbidden. Any future violation surfaces immediately.

**Neutral:**

- `TurnResult` shape unchanged — observability comes via `event_store` queries (per ADR-001), which is the project-canonical path. Consumers wanting per-turn tool-dispatch summaries query the event store directly; no contract change for existing consumers.
- `process_tool_calls` is per-turn synchronous (matches `dispatch_turn` D1; P1.5+ concurrent dispatch reshape will reshape both).
- Tool execution still doesn't happen — emitting `tool_call` events without a consumer can feel artificial. Per ADR-001 + brief §"Architect-settled design decisions" #4, this is intentional: P1.5.5 produces the events; P1.6+ executor consumes uniformly regardless of source.

## Reversibility

| Decision | 6-month reversal cost |
|---|---|
| D1 (dispatch site in sibling module from dispatch_turn) | **Medium.** Reversing to option (a) inline means moving the body back into `dispatch_turn`; tests follow. Reversing to option (b) post-dispatch requires extending `TurnResult` (a contract change requiring R0-A re-review of all consumers). The sibling-module choice has the lowest reversal-cost-to-flexibility ratio. |
| D2 (tier-to-event mapping) | **Low.** The mapping is data-shaped (a small dispatch table); changing the AUTO_EXECUTE event ordering or adding a new tier just edits `process_tool_calls`. The constitutional invariant is the audit-event-must-exist guarantee, which is preserved by any mapping that emits one event per gate evaluation. |
| D3 (`user_explicit_intent` from `current_event.type`) | **Trivial.** One-line predicate at the call site. P1.6+ richer intent inference replaces the predicate additively (e.g., walk chain backward; query snapshot); the field's semantic contract is unchanged. |
| D4 (tools registry as keyword param) | **Low.** Pattern-matched to existing keyword threading; changing to constructor-injected or singleton involves the same N call sites that currently pass `available_skills` / `available_agents` — moderate mechanical refactor, no contract risk. |
| D5 (no shim; reuse `LLMResponse.tool_calls`) | **Trivial.** If a future provider's shape diverges from `ToolCall(id, name, arguments)`, a shim is added at the provider's parser, not at the agent layer — same place P1.1 already normalizes. ADR-013 reuses the existing seam; reversing means adding what P1.1 already does. |

## References

- ADR-001 — event log as single source of truth (informs D1, D2 — separation of proposal/outcome events).
- ADR-005 — autonomy scoring + tier enum + Decision 6 (synchronous emission semantic; D2 restates).
- ADR-006 — unknown tool semantic (D2 refusal-path mapping).
- ADR-007 — autonomy_refusal event type + Decision 3 (emission-before-raise semantic; D2 restates).
- ADR-008 — workflow state machine (this ADR routes via `awaiting_architect_accept` per W-002-1 single-ADR path β).
- ADR-010 — should_agent_speak contract (informs that operator's gating happens AFTER speech eligibility; tool-call evaluation is in the speaker's body, not in trigger selection).
- ADR-011 — multi-agent dispatch (D1 sibling-module pattern matches D4 "separate concern"; D2 restates causal-ordering invariant).
- ADR-012 — room state machine (operator's `applies_to.room_types` honored at room-load + room-state filter per D3/D4).
- `handoff.md` §3.1 (LLM proposes, code decides — D1 D2 first runtime exercise); §4.4 (Agent schema includes operator); §5.1 (per-agent room_type filtering); §5.4 (first-layer tools); §5.5 (`required_capabilities: [tools]` example).
- `docs/process/architect-briefs/P1.5.5.md` — brief that prompted this ADR (architect-partner authored 2026-05-27).
- `docs/process/senior-plans/P1.5.5.md` — plan that locks the atomic-task breakdown.
- `src/orchestrator/llm/providers/openai_compatible.py:270-283` — pre-investigation cite for D5.
- `src/orchestrator/llm/parsers/claude_code_output.py:89-108` — pre-investigation cite for D5.
- `src/orchestrator/agents/dispatch.py:117-127` — the location where pre-investigation found `response.tool_calls` discarded (the absent wiring that this ADR addresses).
- Implementation lands on `claude/P1.5.5-impl` post-Accept; ADR text lands on `claude/P1.5.5-plan`.
