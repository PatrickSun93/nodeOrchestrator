# ADR-012: Per-RoomType State Machine + `agent.applies_to` Filtering

**Status:** Accepted — 2026-05-27
**Scope:** Governs the per-`RoomType` state machine implemented in
`src/orchestrator/rooms/`, the `next_room_state` pure decision
function, the `agent.applies_to.room_types` / `room_states` Pydantic
filtering fields on `Agent`, the integration site between the state
machine and `dispatch_turn` (a new `RoomRuntime` orchestrator), and
the extension of `StateTransitionMeta` to carry `prior_state`. Out
of scope: snapshot mechanics (P1.6); decision log persistence
(P1.6); operator agent + autonomy-aware tool dispatch (P1.5.5);
non-Research room templates' full content (P2 content polish).

## Context

P1.4 closed the multi-agent dispatch contract (ADR-010 +
ADR-011). The current `decide_agents_for_room` accepts only
`available_agents` and returns every loaded agent (DeepSeek R0-B
🟡#3 routing dropped the `room_type` / `room_state` params as
"signature-honesty: a function that takes parameters it ignores
trains readers to distrust signatures"). P1.5 is where those
parameters come back for real consumption — the room state
machine drives which agents speak when.

This is the **third code-driven decision-function module** in the
project after `autonomy/gate` and `skills/decide_skills_for_context`
+ `agents/should_agent_speak`. The pattern stays consistent: pure
function consumes inputs (state + event stream + current event);
returns a typed result; no LLM judgment. The state machine
inscription needs to settle:

- Where per-`RoomType` state sets live (typed at module level vs
  config yaml vs Pydantic schema).
- The transition trigger shape (event-stream-driven; same
  snapshot semantic as `should_agent_speak`).
- How `agent.applies_to` field filters at load-time vs dispatch-time.
- The integration site between `next_room_state` and `dispatch_turn`
  (inline in `dispatch_turn` body, or as a separate `RoomRuntime`
  orchestrator).
- Whether `StateTransitionMeta` needs to extend with `prior_state`
  to carry the state-machine arc explicitly (P1.4 added the
  metadata schema with `new_state` only; this is the first real
  consumer).
- Three new layering edges (`rooms → agents` allowed; reverse +
  LLM + skills→rooms forbidden) per the W-001-impl + P1.3 + P1.4
  pattern.

Hard requirements:

1. **Pure code, no LLM** in `rooms/`. Constitutional test
   `test_constitution_no_llm_calls_in_rooms_module` enforces.
2. **Event stream is single source of truth** (Principle 11):
   state transitions append `state_transition` events; state
   derivable from event-stream replay.
3. **Per-RoomType discrimination**: each of the 5 `RoomType`
   values has its own state set + transition table. Research is
   fully implemented; other 4 are scaffolded (matches P1.3 "2
   sample skills + full library is content task" pattern).
4. **Decision-trace pattern** (`contributing.md` Q2): `next_room_state`
   returns enough context to explain transitions.
5. **Layering**: `rooms → agents` allowed; `agents → rooms`,
   `core → rooms`, `skills → rooms`, LLM imports in `rooms/` all
   forbidden via constitutional tests.

## Decisions

### 1. State machines are per-`RoomType`, code-driven, event-triggered

Each `RoomType` (5 values: `free_chat`, `bug_fix`, `research`,
`code_review`, `idea_validation`) has its own state set + transition
function. State machines live as Python data + functions in
`src/orchestrator/rooms/state_machine.py`, not as config yamls — the
transition predicates are code-level pattern matches on event-stream
events (not data-driven enumeration), and code is the simpler home.

The decision function signature mirrors `autonomy/gate` and
`workflow/next_state`:

```python
def next_room_state(
    room: Room,
    event_stream_snapshot: list[Event],
    *,
    current_event: Event,
) -> RoomStateTransition | None:
    """Pure function. Returns a typed transition when the
    (current_state, snapshot, current_event) tuple matches a
    transition rule; None when no transition fires (most events).
    Never reads files or appends events; caller persists.
    """
```

`RoomStateTransition` is a Pydantic model carrying `prior_state`,
`new_state`, and a trace (which event triggered, which rule
matched). The caller (`RoomRuntime`, Decision 7) appends a
`state_transition` event with `StateTransitionMeta(prior_state,
new_state)` if the function returns non-None.

The function is "pure" in the same sense as ADR-010's
`should_agent_speak`: no I/O, no LLM, snapshot passed in by
caller. Constitutional test enforces no-LLM-imports under
`src/orchestrator/rooms/`.

### 2. RoomState type — a discriminated `Literal` per `RoomType`

Each `RoomType` has a closed enum of state values:

```python
ResearchRoomState = Literal[
    "setup", "exploration", "divergence",
    "convergence", "snapshot_pending", "closed"
]

BugFixRoomState = Literal["setup", "closed"]       # scaffold
CodeReviewRoomState = Literal["setup", "closed"]   # scaffold
IdeaValidationRoomState = Literal["setup", "closed"]  # scaffold
FreeChatRoomState = Literal["setup", "closed"]     # scaffold

RoomState = (
    ResearchRoomState | BugFixRoomState |
    CodeReviewRoomState | IdeaValidationRoomState |
    FreeChatRoomState
)
```

Research's 6-state set comes from the brief's architect-partner
lean. The other 4 RoomTypes ship as 2-state scaffolds (`setup →
closed` only; no architecturally interesting transitions). This
matches the P1.3 pattern (2 sample skills demonstrate the format;
full library is downstream content work).

The `Room.state: str` field (from `core/room.py`) stays a free
string — the per-`RoomType` Literal lives in `rooms/state_machine.py`
and is consulted by `next_room_state`'s type-narrowed body. Cross-
RoomType state validation does NOT happen at the `Room` Pydantic
layer (the existing free-string field stays; rooms module validates
state-vs-room-type at transition time).

### 3. `agent.applies_to` shape — `list[str]` with `["*"]` sentinel

```python
class AgentAppliesTo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    room_types: list[str] = Field(min_length=1)
    room_states: list[str] = Field(min_length=1)

    @field_validator("room_types", "room_states")
    @classmethod
    def _reject_mixed_star(cls, v: list[str]) -> list[str]:
        if "*" in v and len(v) > 1:
            raise ValueError(
                '"*" cannot be mixed with concrete values; '
                'use ["*"] alone or list specific values'
            )
        return v
```

This is the **third use of the `["*"]` sentinel pattern**, after:
- ADR-009 D3 (`Skill.applies_to.agents`)
- W-002.5 + ADR-009 D3 amendment (`adr: list[str]` and the broader
  list-with-sentinel convention)

The pattern is now codify-ready as a project convention (per the
brief's architect-partner-direct addendum). Senior recommends the
codification land separately (a sub-finding of W-003 or a process
doc update at architect-partner discretion); this ADR uses the
pattern but doesn't codify it project-wide.

Validation parallels `Skill.applies_to.agents`: non-empty list;
`"*"` is exclusive with concrete values (rejects `["*", "research"]`).

`room_types` accepts the 5 `RoomType` enum string values OR `["*"]`.
`room_states` accepts any non-empty string (cross-RoomType validation
is too much coupling — see Considered Alternative D).

**`AgentAppliesTo` has a class-level `default_factory` producing
`{room_types: ["*"], room_states: ["*"]}`** (architect routing
2026-05-27, R0-A Y1 → β; brief lean restored after senior's
over-disciplined "required no default" choice). Existing
skeptic.yaml + prober.yaml omit the field; the default applies.
New agent yamls declaring specific filters override the default.
Backwards compat: every agent yaml that predated this ADR continues
to load unchanged.

```python
class Agent(BaseModel):
    ...
    applies_to: AgentAppliesTo = Field(
        default_factory=lambda: AgentAppliesTo(
            room_types=["*"],
            room_states=["*"],
        )
    )
```

### 4. Two-layer filtering — `room_types` load-time, `room_states` dispatch-time

```python
def decide_agents_for_room(
    room_type: RoomType,
    room_state: str,
    *,
    available_agents: dict[str, Agent],
) -> AgentSelection: ...
```

The signature regains `room_type` and `room_state` (DeepSeek R0-B
🟡#3 dropped them in P1.4 as "signature-honesty: params it ignores"
— P1.5 implements the real filtering).

**Filter layers:**

- **Load-time (`room_types`)**: `decide_agents_for_room` returns
  only agents whose `applies_to.room_types` contains `room_type`
  OR is `["*"]`. These are the agents that *can be loaded* into
  the given room. Result is `AgentSelection.loaded`.

- **Dispatch-time (`room_states`)**: within a turn, `dispatch_turn`
  (or RoomRuntime, Decision 7) filters the loaded set further by
  `room_state` before calling `should_agent_speak`. Agents whose
  `applies_to.room_states` doesn't include the current `room_state`
  (and isn't `["*"]`) are skipped for that turn.

This two-layer design separates "which agents enter the room"
from "which loaded agents are active in the current state." A
research-room snapshot_pending state, for example, might activate
only the logger (recording the snapshot) while skeptic and prober
are loaded-but-quiet.

### 5. Integration site — separate `RoomRuntime` orchestrator

`dispatch_turn` (from ADR-011 D1) stays as it is — sequential per-
turn LLM dispatch with snapshot semantics. A new `RoomRuntime`
class (or function — Decision deferred to impl) orchestrates the
per-room loop:

1. Take event-stream snapshot at turn start.
2. Call `next_room_state` against snapshot + current event. If
   non-None, append `state_transition` event AND update room
   state.
3. Call `decide_agents_for_room(room_type, room_state, ...)` with
   the (possibly newly-updated) state to filter loaded agents.
4. Call `dispatch_turn(filtered_agents, ...)` against the same
   snapshot.
5. Returned `TurnResult` is processed by the caller.

The `RoomRuntime` lives in `src/orchestrator/rooms/runtime.py`.
Junior decides whether it's a class with state or a stateless
function module — both are defensible (matching dispatch-vs-
context-builder separation from ADR-011 D4). The lean is
**function-based for P1.5** (stateless; pure dispatch over snapshot
+ room data); P1.5.5+ may introduce a class if operator + autonomy
gate state requires it.

The decision NOT to inline `next_room_state` into `dispatch_turn`'s
body is load-bearing: `dispatch_turn` is already complex (10
acceptance bullets in P1.4-8); coupling state-machine drive into
it would inflate the §2 + §3 test surface and conflate concerns.

### 6. `state_transition` event metadata — `prior_state` added

P1.4-4 added `StateTransitionMeta(new_state: str)` to
`core/event.py`'s `TYPED_METADATA`. P1.5 is the first real
consumer of this event type — the state-machine arc is more
useful with both endpoints visible.

Extension:

```python
class StateTransitionMeta(_BaseMeta):
    new_state: str = Field(min_length=1)
    prior_state: str = Field(min_length=1)
    # Future: transition_reason — additive per ADR-001 EventType-
    # metadata precedent when needs surface (e.g., user-explicit
    # state override).
```

Backwards-compat: P1.4-4 shipped with `new_state` only; no real
events were ever written using the old shape (P1.5 is the first
producer). The extension is technically additive (no migration of
existing data needed). The Pydantic `extra="forbid"` invariant
preserves type safety.

Test coverage: extend the existing P1.4-4 `test_schema.py` tests
for `StateTransitionMeta` to cover the new field (frozen + extra-
forbid + Field min_length on `prior_state`).

### 7. Layering — four new constitutional tests

`src/orchestrator/rooms/` is the **fourth new top-level module**
after autonomy/, skills/, workflow/, agents/. Likely imports:
- `core` (`Event`, `EventType`, `Room`, `RoomType`,
  `StateTransitionMeta`).
- `agents` (`Agent`, `AgentAppliesTo`, `AgentSelection`,
  `dispatch_turn`, `decide_agents_for_room`). **First `rooms →
  agents` import direction edge.**

Forbidden directions, locked by new constitutional tests in P1.5-3:
- `test_constitution_no_llm_calls_in_rooms_module` — no LLM SDK
  import in `src/orchestrator/rooms/`.
- `test_constitution_core_does_not_import_rooms` — `core` must
  stay agent-/room-/skill-/workflow-agnostic. Same Y1 pattern.
- `test_constitution_agents_does_not_import_rooms` — `agents`
  module is consumed by `rooms`, not the reverse. Locked.
- `test_constitution_skills_does_not_import_rooms` — defensive;
  skills remain room-agnostic. (Skills are content; rooms are
  orchestration; the wire flows rooms → agents → skills.)

The reverse-import pattern is now established across 4 modules
(autonomy, skills, agents, rooms); each new module gets a
constitutional test for its `core → X` and one for its reverse-
direction-with-the-module-that-consumes-it.

## Considered alternatives

### A. LLM-driven state machine

Ask the LLM "given this event stream, what state should the room
be in?" and use the response.

**Rejected** on Principle 3.1 + Principle 11: state transitions are
deterministic functions of (state, events); LLM judgment introduces
non-replayability, non-determinism, and a load-bearing dependency on
inference that has no ground truth (Principle 11). Same shape as why
`autonomy/gate` and `skills/decide_skills_for_context` are code.

### B. Single shared state set across all RoomTypes

Define `RoomState = Literal["setup", "active", "closed"]` and use
the same set for all 5 RoomTypes.

**Rejected**: Research room's transitions (`exploration → divergence
→ convergence → snapshot_pending`) are categorically different from
bug_fix's (`debugging → fix_proposed → tests_passed`). Forcing a
shared vocabulary either over-abstracts (states become so generic
they explain nothing) or under-specifies (the room's actual
behavior is hidden in transition tables). Per-RoomType Literal
preserves type-level documentation of each room's lifecycle.

### C. Inline `next_room_state` into `dispatch_turn`

`dispatch_turn` body calls `next_room_state` at the end of each
turn, in the same function.

**Rejected** (Decision 5): `dispatch_turn` is already the largest
function in the project; coupling state-machine drive into it
conflates two concerns (which agents speak this turn vs how does
room state evolve). Separate orchestrator (`RoomRuntime`) is
testable in isolation; matches the dispatch-vs-context-builder
separation from ADR-011 D4.

### D. Cross-RoomType `room_states` validation at agent-yaml load

Validate `agent.applies_to.room_states` strings against the actual
per-RoomType state set at load time (e.g., reject `room_states:
["exploration"]` on an agent that has `room_types: ["bug_fix"]`).

**Rejected**: requires coupling `Agent` schema to `rooms/state_machine`
state-set definitions, inverting the layering direction (agents
becomes upstream of rooms). The agent-yaml validation stays
RoomType-agnostic; the dispatch-time filter is where `room_states`
matters, and an agent declaring a state that doesn't exist in any
room is harmless (the agent just never matches at dispatch).

### E. One-layer filtering — `room_types` only; ignore `room_states`

Drop `room_states` from `AgentAppliesTo`; load decides by
`room_types`; dispatch is room-state-agnostic.

**Rejected**: research-room's `snapshot_pending` state needs the
logger to be active without skeptic + prober — that's exactly what
`room_states` filtering provides. Without per-state filtering, the
room state machine would need to track per-state agent activation
elsewhere (which loaded agents are quiet vs active), adding state
to the wrong place.

### F. No `state_transition` events; track state in `Room.state` field only

Skip event-stream representation; just mutate `Room.state` at
each transition.

**Rejected**: violates Principle 11 (event stream is single source
of truth) + `Room` is supposed to be a snapshot derivable from
events (per `handoff.md` §3.1). Without `state_transition` events,
replay can't reconstruct room state at any point in history.

## Consequences

**Easier:**

- Adding a new RoomType: declare its state Literal, add the
  transition function, add the placeholder template — no
  architectural decision needed; pattern matches the existing 5
  RoomTypes.
- Per-state agent activation: an agent's `applies_to.room_states`
  declares when it's quiet vs active. No imperative state-tracking
  needed in agent code.
- Event-stream replay reconstructs room state: every transition
  is an event; replay walks the stream and rebuilds.
- `next_room_state` is a pure function; testable in isolation
  with synthetic event streams.
- The 4 constitutional tests catch layering slips at PR time
  (Y1 pattern continues paying).

**Harder:**

- Per-RoomType state sets means each new RoomType is a code
  change (vs a config-data change). For 5 RoomTypes this is fine;
  if user-defined RoomTypes ever land (P3+), the pattern would
  need amendment (configurable transition tables).
- Two-layer filtering (`room_types` load-time, `room_states`
  dispatch-time) adds cognitive load — newcomers must learn the
  layer split. Documented in `rooms/README.md` and the docstring
  of `decide_agents_for_room`.
- `StateTransitionMeta` extension means `tests/core/test_event.py`
  (P1.4) grows two §6 tests for the new `prior_state` field.
  Minor but real test-surface growth.
- `RoomRuntime` as a separate module means one more layer to
  navigate when debugging "why didn't agent X speak?" — the call
  flow is RoomRuntime → dispatch_turn → should_agent_speak →
  trigger evaluation. Mitigated by the per-layer `decision_trace`.

**Neutral:**

- The 6-state Research lifecycle is an architect-partner lean,
  not a binding constraint. P1.5 senior may propose a different
  state set; the ADR documents this as a per-RoomType decision,
  not a project invariant.
- Function-vs-class for `RoomRuntime`: deferred to impl. Both
  shapes are compatible with this ADR's contracts.
- `["*"]` sentinel: third use in the project; ready for explicit
  codification at architect-partner discretion (a process doc
  update; not part of P1.5 scope).

## Reversibility

| Decision | 6-month reversal cost |
|---|---|
| 1. Per-RoomType code-driven state machines | **Expensive** — replacing with LLM-driven requires re-litigating Principle 3.1 grounding and breaking event-stream replay determinism. Pick this once. |
| 2. Per-RoomType Literal state sets | **Low** — adding states to a Literal is additive (existing events stay valid; new transitions add new Literal values). Removing a state would break replay of historical events using it. |
| 3. `applies_to` with `["*"]` sentinel + `default_factory` | **Medium** — switching to required (no default) is a Pydantic shape change + agent yaml migration across all extant agent yamls (5 in MVP set). Switching to separate `Optional[list]` fields with `None`-means-all is similarly Medium (Pydantic shape change + yaml migration). |
| 4. Two-layer filtering (room_types + room_states) | **Low** — collapsing to one layer is a function-body change; agent yamls unchanged (existing `["*"]` defaults stay valid). |
| 5. Separate `RoomRuntime` orchestrator | **Low** — inlining into `dispatch_turn` is a refactor; the call sites are P1.5.5+ scope so no migration cost in P1.5. |
| 6. `StateTransitionMeta` extension with `prior_state` | **Low** — already extending P1.4 surface; reverting to `new_state`-only would require migration of any existing events (none yet, since P1.5 is the first producer). |
| 7. Four new constitutional tests (layering) | **Trivial** — adding more tests is additive. Removing them means accepting layering risks the project's discipline rejects. |

## References

- `handoff.md` §3.1 (decisions in code; LLMs generate content),
  §4.2 (Room + RoomType data structures), §4.4 (Agent schema +
  `speaking_triggers`), §5.2 (5 room templates), §7 (P1.5
  scope).
- `docs/contributing.md` Q1 (no LLM in decision functions), Q2
  (`decision_trace` obligation), Q3 (5-surface scan).
- `docs/architecture/test-coverage-standard.md` — six categories;
  P1.5 exercises §1 + §4 + §5 + §6 + §3 (minor).
- ADR-001 (event store foundation) — `EventType` + closed-enum
  + metadata schema precedent.
- ADR-008 (workflow state machine) — first per-task state
  machine; `next_state` is the conceptual ancestor of `next_room_state`.
- ADR-009 (SKILL.md frontmatter) — `["*"]` sentinel pattern
  first introduction; `Skill.applies_to.agents` is the analog
  for `Agent.applies_to.room_types`.
- ADR-010 + ADR-011 (P1.4 multi-agent dispatch) — direct
  predecessors; `dispatch_turn` + `should_agent_speak` are
  consumed by `RoomRuntime`; `decide_agents_for_room` signature
  comes back into use here.
- `docs/process/architect-briefs/P1.5.md` — architect-settled
  decisions feeding into this ADR.
- `docs/process/senior-plans/P1.5.md` — implementation plan
  consuming this ADR.
- Implementation entry point: P1.5-3 schema commit lands the
  Pydantic models declared in Decisions 3 + 6; P1.5-4 state
  machine module lands Decisions 1 + 2; P1.5-5 selection update
  lands Decision 4; P1.5-7 RoomRuntime lands Decision 5.

## Amendments

### 2026-06-02 (P2.7-S1) — Proposed (senior-drafted; awaiting architect accept)

**Amendment to Decision 2 (+ Decision 1's scaffold note) — the four scaffold RoomTypes gain real, event-triggered transition tables ("state-machine evolution").**

**Context / what was deferred.** P1.5 shipped Research as a full 6-state machine; the other four RoomTypes (`bug_fix`, `code_review`, `idea_validation`, `free_chat`) shipped as 2-state `setup → closed` **scaffolds** with **no automatic transitions** (`_next_scaffold_state` returns `None` for every event — `state_machine.py:219-231`). Decision 2 noted this ("other 4 RoomTypes ship as 2-state scaffolds") and Decision 1 deferred their transitions per the P1.3 "scaffold-now, content-later" pattern. P2.7-S1 is that content: real per-RoomType lifecycles.

> **Note (senior self-discovery, surfaced + architect-confirmed).** P2.7-S1 was *initially* framed as "consume the ADR-012 🟡#3 deferred `room_type`/`room_state` params." That consumption is **already shipped** (P1.5): load-time `room_type` filtering at `agents/selection.py:50-65`, dispatch-time `room_state` filtering at `rooms/runtime.py:111-115`, both tested (`tests/rooms/test_runtime.py:269-323`). The `_ = room_state` discard at `selection.py:46` is intentional (room_state is filtered at dispatch-time, not load-time, per Decision 4's two-layer split); the "deferred to P1.5-7" comments are stale. The architect re-pinned S1 to the scaffold-buildout interpretation of "状态机演化" — this amendment.

**Amended state sets (Decision 2).** The four scaffold `Literal`s extend from `{setup, closed}` to real lifecycles. `setup` and `closed` are **preserved** in every set (additive Literal extension — ADR-012 Reversibility row 2; existing events/replay stay valid since scaffolds never auto-transitioned):

```python
BugFixRoomState = Literal[
    "setup", "reproduced", "diagnosed", "fix_proposed", "closed"
]
CodeReviewRoomState = Literal[
    "setup", "reviewing", "changes_requested", "approved", "closed"
]
IdeaValidationRoomState = Literal[
    "setup", "pitching", "validating", "decided", "closed"
]
FreeChatRoomState = Literal["setup", "active", "closed"]
```

**Transition tables (new — replacing the always-`None` `_next_scaffold_state` with one `_next_<type>_state` per RoomType, each mirroring `_next_research_state`'s idiom: pattern-match on `room.state` + `current_event.type`, `_guard_valid_state`, return a typed `RoomStateTransition`).** Each arc is a **pure code** match on the event stream (Principle 11; no LLM — Hard Requirement 1 unchanged); `SUMMARY_SNAPSHOT` is the universal close trigger (consistent with Research's `snapshot_pending → closed`):

| RoomType | Arc | Trigger (`current_event.type`) | `rule_matched` |
|---|---|---|---|
| **bug_fix** | setup → reproduced | `OBSERVATION` | `observation_triggers_reproduced` |
| | reproduced → diagnosed | `HYPOTHESIS` | `hypothesis_triggers_diagnosed` |
| | diagnosed → fix_proposed | `DECISION` | `decision_triggers_fix_proposed` |
| | fix_proposed → closed | `SUMMARY_SNAPSHOT` | `snapshot_triggers_closed` |
| **code_review** | setup → reviewing | `OBSERVATION` | `observation_triggers_reviewing` |
| | reviewing → changes_requested | `REJECTION` | `rejection_triggers_changes_requested` |
| | changes_requested → approved | `DECISION` | `decision_triggers_approved` |
| | approved → closed | `SUMMARY_SNAPSHOT` | `snapshot_triggers_closed` |
| **idea_validation** | setup → pitching | `UTTERANCE` | `utterance_triggers_pitching` |
| | pitching → validating | `HYPOTHESIS` | `hypothesis_triggers_validating` |
| | validating → decided | `DECISION` | `decision_triggers_decided` |
| | decided → closed | `SUMMARY_SNAPSHOT` | `snapshot_triggers_closed` |
| **free_chat** | setup → active | `UTTERANCE` | `utterance_triggers_active` |
| | active → closed | `SUMMARY_SNAPSHOT` | `snapshot_triggers_closed` |

These state sets + triggers are a **senior design fork** (the "6-state Research lifecycle is an architect-partner lean, not a binding constraint" precedent — Consequences/Neutral). They are deliberately linear (no branches) for determinism + discriminating tests; per-state agent activation continues to work through the *existing* `applies_to.room_states` dispatch-time filter (`runtime.py:111-115`) — agents reference the new states with no code change. `next_room_state`'s `match`/`case` dispatch (`state_machine.py:299-305`) is updated to route each of the four RoomTypes to its own function; `_VALID_STATES` is updated to the new sets.

**Out of scope (this amendment):** populating the four scaffold **room templates'** agent lists (`rooms/templates.py:11-12` — currently `[]`, marked "P2 content work") is *related but separate content* — the state machine (code decision) is the S1 deliverable; the per-room agent rosters are a follow-on content task (noted in P2.7 plan §2-S1, architect to scope). Backward-compat: the `Room.state` field stays a free string (Decision 2 unchanged); cross-RoomType validation stays at transition time via `_guard_valid_state`.
