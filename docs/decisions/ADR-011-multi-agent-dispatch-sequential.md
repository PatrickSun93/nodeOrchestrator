# ADR-011: Multi-Agent Dispatch — Sequential, Snapshot-Per-Turn

**Status:** Proposed — 2026-05-26
**Scope:** Governs the per-turn primitive that decides which loaded
agent(s) speak on a given event and how their LLM calls are
dispatched. Inscribes the sequential-dispatch model for P1.4 (with
an additive-upgrade path to concurrent in P1.5+), the per-turn
event-stream snapshot semantics, the priority + alphabetical-id
conflict resolution rule, the skill-integration boundary via a
separate `build_agent_context` function, the layering rules for
`src/orchestrator/agents/` (3 new constitutional tests), and the
§2 concurrency-safety strategy for sequential dispatch. Out of
scope: `should_agent_speak` contract internals (ADR-010); summon
decisions (deferred to P1.5); cross-room agent state (P1.6); user-
facing dispatch UI (P2).

## Context

P1.4 introduces multi-agent dispatch — the project's first
concurrency-adjacent surface. The brief enumerates three boundary
questions (sequential vs concurrent dispatch; conflict resolution;
snapshot-vs-live event-stream reading) and explicitly asks senior to
pick and defend. The brief also asks senior to decide where the
skill-selection wire lives (inline in dispatch vs separate
`build_agent_context` function).

Five constraints bind the design:

- **No LLM in dispatch.** Per Principle 3.1, the dispatch decision
  (which agent speaks) is code; only the agent's response generation
  is LLM. Locked by `test_constitution_no_llm_calls_in_agents_module`.
- **Event stream as single source of truth.** Per Principle 11,
  cooldown and trigger evaluation read the event stream, never side
  state. ADR-010 inscribes the per-agent half; this ADR inscribes
  the cross-agent half (snapshot-per-turn).
- **`LLMPurpose.AGENT_RESPONSE`** is the existing purpose; this ADR
  does not add new purposes. `caller_agent_id` discriminates per
  `handoff.md` §5.5.
- **`handoff.md` §4.4 layering**: `agent → core` and `agent → llm`
  required; `agent → skills` required for context build;
  `core → agent`, `llm → agent`, `skills → agent` forbidden (the
  reverse-import constitutional tests).
- **§2 concurrency safety becomes a real test category for the
  first time.** Even with sequential dispatch, snapshot semantics
  need a test proving turn N+1 sees turn N's appends but not
  partial-turn-N state.

The brief explicitly accepts that P1.4 may run for ~1.5 weeks; the
shape change here is worth the time. Architectural inscribing in
this ADR will be referenced by every future agent + every multi-
agent test.

Hard requirements:

1. Sequential vs concurrent: pick and defend; additive-upgrade path
   to the rejected option preserved if cheap.
2. Conflict resolution among multiple speak=True agents:
   deterministic; code-only; tunable per agent.
3. Per-turn snapshot semantics: every `should_agent_speak` call
   within one turn reads the same event-stream snapshot.
4. Skill integration: separate function callable by dispatch.
5. Layering: three new constitutional tests
   (`core_does_not_import_agents`, `no_llm_calls_in_agents_module`,
   `skills_does_not_import_agents`).
6. §2 concurrency test exists even under sequential dispatch
   (snapshot semantics test).

## Decisions

### 1. Sequential dispatch for P1.4 — concurrent is additive in P1.5+

P1.4 dispatches agents **sequentially within a turn**: for each
loaded agent (in conflict-resolution order from Decision 3), the
dispatch primitive calls `should_agent_speak`; for every agent that
returns `speak=True`, it calls the LLM (via the existing
`LLMRouter` with `LLMPurpose.AGENT_RESPONSE` and the agent's
`llm_config`); each successful response appends one `utterance`
event to the stream before the next agent's LLM call begins. Total
parallelism per turn: one LLM call in flight at a time.

Rejected alternative: concurrent dispatch (multiple agents'
`should_agent_speak` calls in parallel, then concurrent LLM calls
via `asyncio.gather`, then deterministic-ordered event append after
all complete). Reasons for sequential:

- **Smaller test surface.** §2 concurrency safety becomes the
  snapshot-semantics test only (one test, well-bounded). Under
  concurrent dispatch, §2 expands to race-condition tests on
  event-stream append, on LLM call cancellation interaction, on
  shared `LLMRouter` state — multiple test classes, many edge
  cases.
- **Project has no prior concurrency surface.** Introducing
  `asyncio.gather`-style concurrency at the same time as the
  multi-agent dispatch contract triples the cognitive load on R0-A
  reviewers and on future contributors reading the code.
- **No measured perf need.** With 2-3 agents loaded per room and
  LLM call latencies of 5-15s, concurrent dispatch saves 10-30s
  per turn. This is real but not load-bearing for P1.4 (which has
  no real-time SLA). Concurrent becomes valuable once 5+ agents are
  loaded; P1.5+ scope.
- **Run > polish (project value)**: sequential is the simplest
  thing that demonstrates the multi-agent decision contract.

The dispatch primitive's signature stays async-shaped (`async def
dispatch_turn(...)`), so a P1.5+ amendment can replace the body
with concurrent semantics without changing callers. The interface
is concurrent-ready; the implementation is sequential. This is the
additive-upgrade path.

### 2. Per-turn snapshot semantics

Each turn begins by computing one event-stream snapshot
(`snapshot: list[Event]` — the event log as of the turn's `current_event`).
**All `should_agent_speak` calls within that turn use the same
snapshot.** Agents do NOT see each other's responses from the same
turn within `should_agent_speak` — they see only events from prior
turns.

After all speaking agents have been dispatched and their utterances
appended, the turn ends. The NEXT turn's snapshot includes those
appended utterances. Turn boundaries are observable in the event
stream by the relative ordering of `utterance` events with the same
parent `current_event` reference (P1.4 does NOT introduce new
EventType values for turn boundaries; see Considered Alternative D).

This rule resolves brief Boundary (c). Implications:

- Cooldown evaluation (ADR-010 Decision 2) uses the same snapshot,
  so an agent that spoke 3 turns ago in real-time sees consistent
  cooldown across all agents within a single turn — the snapshot's
  last-utterance lookup is identical for every agent in the turn.
- An agent CANNOT chain off another agent's response within the
  same turn ("agent A says X; agent B sees X and adds Y"). That
  pattern requires two turns: A's response in turn N, B sees it in
  turn N+1.
- The "agent A speaks, agent B's cooldown check fires against the
  pre-A snapshot" question from senior's self-discoveries: yes, B
  sees the pre-A snapshot. This is correct by design — within one
  turn, agents act on the same world state, and the world state
  changes between turns. Turn-as-atomic-unit is the right
  abstraction.

### 3. Conflict resolution — priority then alphabetical id

When multiple loaded agents return `speak=True` for the same
`current_event`, dispatch order is:

1. **Priority ascending** (`agent.priority`, int 0-100, default 50,
   lower = earlier). Author-tunable per agent yaml.
2. **Alphabetical by `agent.id`** as tiebreaker (deterministic;
   portable across OSes; greppable).

All speak=True agents dispatch within the turn — the priority order
controls the **order of their utterance events** in the stream, not
which agents are skipped. This matches handoff §4.4's "multi-
perspective by default" (Principle 6) — we don't silently drop
agents.

`Agent.priority` is a new schema field (P1.4-4 schema landing). Its
inclusion is a senior judgement: parallels `Skill.priority` (ADR-009
D6), tunable conflict resolution becomes essential once 3+ agents
are loaded per room (P1.5+), and the migration cost of adding it
later is higher than the cost of including it now.

### 4. Skill integration via `build_agent_context` function

Skill selection lives in a separate function:

```python
def build_agent_context(
    agent: Agent,
    room_type: RoomType,
    room_state: str,
    *,
    available_skills: dict[str, Skill],
    snapshot: list[Event],
) -> AgentContext:
    """Build the per-turn context for one agent. Pure function;
    no I/O, no LLM. Calls `decide_skills_for_context` (from
    orchestrator.skills.decision) and assembles the skill bodies
    into a prompt-ready structure.
    """
```

The dispatch primitive calls `build_agent_context` once per
speaking agent before invoking that agent's LLM call. The function
is pure (skill selection is pure per ADR-009), takes the per-turn
snapshot as an explicit parameter (Decision 2 invariant), and
returns an `AgentContext` Pydantic model carrying the skills'
bodies plus any other per-turn data (system prompt, persona, recent
event excerpts) the LLM call needs.

Rationale for separate function (rather than inline in dispatch):

- **Testable in isolation.** "Given this agent and this room state,
  what skills enter context?" is a pure-function unit test, no
  dispatch mocking required.
- **Reusable.** A future "preview what agent X would see" UI
  (P2-ish) can call `build_agent_context` without dispatching.
- **Single concern per function.** Dispatch primitive decides
  *which agent speaks*; context-builder decides *with what
  background*. Mixing concerns makes both harder to change.

Skill→agent integration is one-directional (dispatch calls
context-builder calls `decide_skills_for_context`; skills package
never imports from agents). Locked by
`test_constitution_skills_does_not_import_agents`.

### 5. Layering — three new constitutional tests

`src/orchestrator/agents/` imports from:
- `orchestrator.core` (`EventType`, `RoomType`, `Event`)
- `orchestrator.llm` (`LLMRouter`, `LLMRequest`, `LLMPurpose`)
- `orchestrator.skills` (`decide_skills_for_context`, `Skill`)
- `orchestrator.autonomy` — **NOT imported in P1.4.** Defer until
  agents are autonomy-aware (P1.5+ if needed).

Forbidden directions, locked by new constitutional tests:

- **`test_constitution_no_llm_calls_in_agents_module`** — no
  LLM SDK import inside `src/orchestrator/agents/` (the LLM call
  goes through `LLMRouter`, not direct SDK). Same shape as
  the autonomy / workflow / skills analogues.
- **`test_constitution_core_does_not_import_agents`** — `core`
  must remain agent-agnostic. Y1 pattern from W-001-impl.
- **`test_constitution_skills_does_not_import_agents`** — `skills`
  must remain agent-agnostic. Skills are about content; agents
  are about gating; the wire is `agents → skills`, never reverse.

The `agents → autonomy` direction is left open (no constitutional
test forbidding it). When P1.5+ adds autonomy-aware agents (the
operator with tool dispatch), agents will import autonomy's
`Operation` and `gate()`. That import is natural; no test needed
to block it.

### 6. §2 concurrency safety — snapshot-semantics test under sequential

Even with sequential dispatch (Decision 1), §2 applies:

- **The snapshot invariant** (Decision 2) must be tested. The test
  constructs a turn where agent A speaks first; asserts that agent
  B's `should_agent_speak` call within the same turn receives a
  snapshot that does NOT include A's utterance; then advances to
  turn N+1 and asserts B's snapshot DOES include A's utterance.

This is the §2 test for P1.4. It is bounded, deterministic, and
doesn't require `asyncio.gather`-style concurrency.

Under sequential dispatch, the race conditions that §2 typically
catches (concurrent appends, partial reads) cannot occur. The
snapshot-semantics test is the categorical equivalent — it catches
"caller forgot to take a snapshot at turn start" and "snapshot
gets mutated mid-turn", which are the sequential-dispatch failure
modes equivalent to race conditions in concurrent code.

When P1.5+ upgrades to concurrent dispatch, §2 expands to true
race-condition tests; this ADR's §2 test remains valid (snapshot
invariant is preserved under concurrent — same contract).

## Considered alternatives

### A. Concurrent dispatch (`asyncio.gather` on all speak=True agents)

Multiple agents' LLM calls fire in parallel; results appended in
priority order after all complete. **Rejected** (Decision 1):
larger test surface, no perf need at P1.4 scale, introduces
project's first true concurrency surface alongside the multi-agent
contract — too much novelty at once. Path preserved as P1.5+
additive upgrade behind the same `async def dispatch_turn` signature.

### B. Live event-stream reads (agent B sees agent A within same turn)

Each agent's `should_agent_speak` reads the current event stream
(not a snapshot). Agent A speaks → A's utterance lands → agent B
evaluates against the post-A stream. **Rejected** (Decision 2): the
turn loses its atomicity; cooldown logic becomes order-dependent;
debugging "why did agent B fire" requires reconstructing the
intermediate stream state. Snapshot-per-turn keeps the turn as the
atomic reasoning unit.

### C. Conflict resolution by first-to-evaluate (no priority field)

Whichever agent's `should_agent_speak` returns first wins (under
concurrent dispatch) or matches list order (under sequential).
**Rejected** (Decision 3): non-determinism under concurrent; under
sequential, list order is an accidental artifact of the loader's
filesystem traversal — not author-controllable. Priority field
gives explicit author control with deterministic tiebreak.

### D. New EventType values for turn boundaries (`turn_started`, `turn_ended`)

Introduce explicit turn-boundary events to make snapshot semantics
observable in the event log. **Rejected for P1.4**: the project
hasn't surfaced a use case for cross-turn analytics that needs
explicit boundary events. The turn boundary is observable from the
relative ordering of `utterance` events with the same parent. If
P1.5+ surfaces a real need (e.g., turn-level cost accounting), a
new EventType lands then via ADR amendment. Don't pre-extend the
event vocabulary on speculation (closed-enum discipline from
ADR-001).

### E. Skill integration inline in dispatch primitive

Dispatch primitive calls `decide_skills_for_context` directly,
assembles prompt inline, calls LLM. **Rejected** (Decision 4):
mixes two concerns (which agent speaks vs with what background) in
one function, harder to test and harder to change independently.
The separate `build_agent_context` function is the single-concern
shape.

### F. Drop `Agent.priority` field; rely on alphabetical id alone

**Rejected** (Decision 3): alphabetical id is portable but not
author-controllable. Adding priority later requires schema migration
across all agent yamls. Including it now matches Skill.priority
(ADR-009 D6) and keeps the schema consistent.

## Consequences

**Easier:**

- Sequential dispatch makes turn semantics easy to reason about:
  one LLM call at a time, deterministic event order, no race
  conditions.
- Snapshot-per-turn makes multi-agent debugging tractable: every
  agent's decision is reproducible from the snapshot + the agent's
  configuration.
- Separate `build_agent_context` function is unit-testable without
  dispatch mocking.
- The three new constitutional tests catch layering slips at PR
  time (analogous to W-001-impl Y1 pattern paying off).
- P1.5+ upgrade to concurrent dispatch is additive: change the
  body, not the interface. The decision is documented as the
  reverse path.

**Harder:**

- Sequential dispatch means a 5-agent room has 5× LLM-call latency
  per turn (~30-75s with current models). For P1.4 this is fine
  (no SLA); for production this becomes the prompt to land the
  concurrent upgrade.
- The snapshot-per-turn rule is non-obvious. Newcomers wonder "why
  doesn't agent B see agent A in the same turn?" — the answer is
  in this ADR and in ADR-010 D5, but it's not the most intuitive
  default.
- `Agent.priority` adds a schema field that's MVP-overengineering
  for 2 agents. The cost is one int field + one validator + one
  test; the alternative (migration to add it later) is higher.
- The dispatch primitive's body is async-shaped even though the
  P1.4 body is sequential. Reading the code, "why is this async
  if it doesn't await anything concurrent" is a real question
  newcomers ask. Mitigated by a docstring note pointing at this
  ADR.

**Neutral:**

- `Agent.priority` is `int 0-100, default 50` to match `Skill.priority`.
  No semantic difference; parallel structure aids readability.
- The decision to defer `agents → autonomy` import means
  operator-agent (which needs tool dispatch) cannot fully land in
  P1.4 — but operator-agent isn't in P1.4 scope per the brief
  (only skeptic + prober). Aligned by accident; not a constraint.
- §2 concurrency safety category exists but is exercised by one
  test (snapshot semantics). This is honest: the project doesn't
  have race conditions yet, so the §2 surface is bounded. P1.5+
  concurrent upgrade expands §2 naturally.

## Reversibility

| Decision | 6-month reversal cost |
|---|---|
| 1. Sequential dispatch (concurrent additive) | **Low** — the additive-upgrade path is explicit. P1.5+ replaces the body of `dispatch_turn` with concurrent semantics without changing callers. The reversal is a code change, not an ADR rewrite. |
| 2. Per-turn snapshot semantics | **Expensive** — switching to live reads breaks turn atomicity, breaks every multi-agent test, breaks cooldown determinism. Pick this once. |
| 3. Priority + alphabetical id conflict resolution | **Low** — alternative orderings are loader-code changes; agent yamls keep `priority` field. Removing `Agent.priority` requires migration across all yamls. |
| 4. `build_agent_context` separate function | **Low** — inlining is a refactor; downstream callers update. The separate-function shape preserves testability. |
| 5. Three constitutional tests for layering | **Trivial** — adding more tests is additive. Removing means accepting a layering risk we deliberately rejected. |
| 6. §2 sequential-snapshot test only | **Low** — when concurrent dispatch lands (P1.5+), §2 tests expand additively. The snapshot test remains valid because the snapshot invariant persists under concurrent. |

## References

- `handoff.md` §3.1 (decision paths in code), §4.4 (agent schema +
  speaking_triggers), §5.1 (5-agent set), §5.5 (LLM layer +
  AGENT_RESPONSE purpose + caller_agent_id discriminator).
- `docs/contributing.md` Q1 (no LLM calls in gating), Q2
  (`decision_trace`), Q3 (5-surface scan).
- `docs/architecture/test-coverage-standard.md` — six categories;
  P1.4 first to exercise §2 non-trivially (snapshot semantics
  test).
- ADR-001 (event store foundation) — `EventType` closed-enum
  discipline reused (Decision D rejection: no new turn-boundary
  EventType in P1.4).
- ADR-008 (workflow state machine) — `.workflow/P1.4.yaml` governs
  this task's lifecycle.
- ADR-009 (SKILL.md frontmatter + decision shape) — `Skill.priority`
  precedent reused for `Agent.priority`; `decide_skills_for_context`
  consumed by `build_agent_context`.
- ADR-010 (`should_agent_speak` contract) — sibling ADR; this ADR
  consumes `SpeechDecision` and enforces the per-turn snapshot
  invariant from ADR-010 D5.
- `docs/process/architect-briefs/P1.4.md` — architect-settled
  decisions (Boundaries (a)/(b)/(c), cross-family R0-B mandate).
- `docs/process/senior-plans/P1.4.md` — implementation plan.
- Implementation entry point: P1.4-8 (`dispatch_turn` primitive +
  §2 snapshot-semantics test) is the load-bearing impl commit;
  P1.4-4 schema lands `Agent.priority`; P1.4-6 lands
  `build_agent_context` and `decide_agents_for_room`.
