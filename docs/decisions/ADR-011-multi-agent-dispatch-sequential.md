# ADR-011: Multi-Agent Dispatch — Sequential, Snapshot-Per-Turn

**Status:** Proposed — 2026-05-26 (revised 2026-05-27 absorbing R0-A-on-plan + R0-B-cross-family architect-routing — see `docs/process/reviews/P1.4/architect-routing.md`)
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

### 1. Sequential + synchronous dispatch for P1.4 — concurrent is a future re-shape (P1.5+)

P1.4 dispatches agents **sequentially and synchronously within a
turn**: for each loaded agent (in conflict-resolution order from
Decision 3), the dispatch primitive calls `should_agent_speak`;
for every agent that returns `speak=True`, it calls the LLM (via
the existing `LLMRouter` with `LLMPurpose.AGENT_RESPONSE` and the
agent's `llm_config`); each successful response appends one
`utterance` event to the stream before the next agent's LLM call
begins. Total parallelism per turn: one LLM call in flight at a
time. The dispatch primitive is a regular **`def`** (not `async
def`); no `asyncio` surface introduced in P1.4.

**Signature (revised 2026-05-27 per DeepSeek R0-B 🔴#2 routing):**
`def dispatch_turn(agents, room, current_event, *, event_store,
llm_router, available_skills, regex_registry) -> TurnResult`.
Synchronous; returns a `TurnResult` (`utterances: list[Event]`,
`failed_agents: list[str]`, `total_asked: int`) so callers can
programmatically distinguish "nothing wanted to speak" from
"everything broke" — the prior `list[Event]` return collapsed
both cases to `[]` and made the all-agents-fail path silent. See
`TurnResult` in P1.4-4 schema.

**`async def` rejected for P1.4 (2026-05-27 revision per R0-B 🟡#4
routing).** Original draft kept the signature `async def` as a
"concurrent-ready" interface. R0-B correctly challenged: the
project has no `asyncio.run(...)` surface anywhere; introducing
`asyncio` color to satisfy a hypothetical P1.5+ concurrent upgrade
is strictly larger blast radius than re-shaping sync→async when
concurrency actually lands. `dispatch_turn` has exactly one
expected caller (the room runtime, not yet written); changing both
the body and the signature when concurrency lands touches one
call-site at most. **Pick sync now; re-shape both signature and
body in the P1.5+ commit that adds real concurrency.**

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

**Additive-upgrade path (P1.5+):** the commit that introduces
concurrent dispatch will re-shape `dispatch_turn` from `def` to
`async def` AND update its body to use `asyncio.gather`. Callers
update in the same commit. Since P1.4 ships zero callers (the
room runtime is P1.5+ scope), no migration cost is incurred at
the moment of the re-shape.

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

### 3. Conflict resolution — alphabetical by `agent.id` (P1.4); `Agent.priority` added additively in P1.5+

When multiple loaded agents return `speak=True` for the same
`current_event`, dispatch order is **alphabetical by `agent.id`
ascending**. Deterministic; portable across OSes; greppable.

All speak=True agents dispatch within the turn — the order controls
the **order of their utterance events** in the stream, not which
agents are skipped. This matches `handoff.md` §4.4's "multi-
perspective by default" (Principle 6) — we don't silently drop
agents.

**`Agent.priority` is NOT in P1.4 (2026-05-27 revision per R0-B 🟡#3
routing).** Original draft included `Agent.priority: int = 50` for
author-tunable conflict resolution. R0-B correctly challenged: P1.4
ships 2 agents (skeptic + prober) with disjoint speaking-triggers
(prober on user_input regex; skeptic on hypothesis event_type) — no
real conflict surface exists. The Skill.priority precedent (ADR-009
D6) argues the OTHER way than the original draft framing: ADR-009
added `Skill.priority` BECAUSE real ordering needs existed in the
current skill set. P1.4's 2-agent sample doesn't have those needs.
Adding `Agent.priority` later when the first real conflict appears
(P1.5+ with 3+ agents per room) is one field + one default +
migration across 2 (now-existing) agent yamls — cheap.

**Additive-upgrade path:** `Agent.priority: int = 50, ge=0, le=100`
lands as an additive Pydantic field in the P1.5+ commit that
introduces multi-agent conflict. Existing skeptic + prober yamls
get the default; new agents tune. ADR-011 D3 is revised in that
commit to "priority asc, alphabetical id as tiebreak."

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
bodies (P1.4 body is just `[s.body for s in selected]` —
deliberately trivial).

**Honest framing (2026-05-27 revision per R0-B 🟡#5 routing).** The
original draft justified `build_agent_context` with "testable in
isolation" + "reusable for a future preview UI (P2-ish)" + "single
concern per function." R0-B correctly challenged: the testability
argument is partially tautological (the underlying
`decide_skills_for_context` is already pure-function tested in
P1.3); the preview-UI justification is speculative-future-callsite;
the function in P1.4 does one trivial thing (`[s.body for s in
selected]`). **The honest rationale: the function is kept for
symmetry with the dispatch-vs-context concern separation and as a
future-callsite hook, even though the P1.4 body is trivial.** The
separation pays its keep in P1.5+ when context-building grows
(snapshot excerpting, persona templating, autonomy-aware tool
context for operator agent); landing the seam now means those
P1.5+ additions don't reshape `dispatch_turn`. **The trade is
honest: small-now-with-symmetry vs inlined-now-with-refactor-then.**

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

### 7. Per-agent LLM exception policy — log + skip + continue turn (added 2026-05-27 per R0-A Y2 routing)

When an agent's LLM call raises an exception during `dispatch_turn`,
the dispatch primitive **logs the exception via the project logger
convention** (`logging.getLogger('orchestrator.agents.dispatch').warning(...)`
with `agent_id` + the exception type/message), **skips that agent's
utterance append** (no partial event written to the stream), and
**continues to the next agent in the conflict-resolution order**.
The turn completes with the surviving agents' utterances appended.

Cancellation semantics differ: `asyncio.CancelledError` (or any
`BaseException`-not-`Exception`) propagates unwrapped per Python
asyncio convention — turn aborts cleanly; no partial state.

**Rationale.** Multi-perspective Principle 6 (`handoff.md` §3.1)
says we don't silently drop agents. A model-side failure for one
agent (rate-limit, network blip, fallback exhaustion) is exactly
the kind of operational failure that shouldn't lose the rest of
the turn — losing prober because skeptic's Opus call rate-limited
defeats the multi-perspective design. The user's question still
gets prober's answer; skeptic re-tries on the next turn (cooldown
honored against the missing utterance — agent without prior
utterance is not in cooldown per ADR-010 D2).

**Considered alternatives:**

- **Abort-on-first-failure.** One agent fails → whole turn aborts;
  no utterances appended. Rejected: loses surviving agents' work;
  amplifies operational failures into user-facing dead-turns;
  inconsistent with multi-perspective Principle 6.
- **Abort-on-N-failures.** Configurable threshold (e.g., abort if
  2+ agents fail in one turn). Rejected for P1.4: introduces a
  tunable that has no clear default and no operational data to
  guide tuning. Defer until P1.5+ ops surface the need.
- **Per-agent retry within the turn.** Catch exception → retry once
  via fallback model → if still fails, skip. Rejected for P1.4: the
  `LLMRouter` already implements model-level fallback per agent's
  `llm_config.fallback_chain` (P1.1); a higher-level retry on top
  is redundant. If `LLMRouter` exhausts the fallback chain, the
  exception is a real "no model in this agent's stack can serve" —
  retrying the same call doesn't help.

**Log specification.** `logging.getLogger('orchestrator.agents.dispatch').warning(
"agent %s LLM call failed; skipping turn (continuing): %s",
agent.id, exc)`. **No `print`. No stdout.** Honors the
P1.3-R0-A-1 + W-002-3 logging convention precedent.

**TurnResult tracking** (added 2026-05-27 per DeepSeek R0-B 🔴#2
routing). When `LLMRouter.call` raises and this skip path fires,
the failing agent's `id` is appended to the returned
`TurnResult.failed_agents` list — making the failure programmatically
detectable by the caller (room runtime, P1.5+) without log-watching.
`total_asked` (also on `TurnResult`) counts every agent for which
`should_agent_speak` returned `speak=True`. Three observable cases
distinguish:

- *Nothing to say*: `total_asked=0`, `utterances=[]`, `failed_agents=[]`.
- *N succeeded*: `total_asked=N`, `utterances=N`, `failed_agents=[]`.
- *N all failed*: `total_asked=N`, `utterances=[]`, `failed_agents=N ids`.

The log message stays the surface for human operators; the
TurnResult fields are the surface for programmatic callers.

### 7-b. Event-store append failure aborts the turn (added 2026-05-27 per DeepSeek R0-B 🔴#1 routing)

When `EventStore.append(...)` raises during `dispatch_turn` (e.g.,
`sqlite3.OperationalError` on a locked DB or disk I/O failure,
`RoomNotFoundError`, `InvalidParentError`, `MetadataValidationError`),
the dispatch primitive **raises the exception unwrapped — the turn
aborts**. Surviving agents' LLM calls are NOT made. This is
asymmetric from the per-agent LLM-failure semantic in Decision 7
(which continues to the next agent).

**Rationale for the asymmetry.** LLM-call failure is *per-agent*:
agent A's failure does not affect agent B's ability to think and
respond, and per Principle 6 we don't drop surviving agents on
sibling failures. Event-store append failure is *per-turn*: the
single source of truth (event stream) is unavailable, so continuing
to dispatch more agents would burn LLM budget on responses that
also cannot be persisted. The system has nowhere to write the
results; the honest action is to stop, surface the failure, and let
the caller decide whether to retry the turn against a healed event
store.

**Considered alternatives:**

- **Silent skip + log only.** Treat event-store failure like
  LLM-failure: log + skip + continue. Rejected — event store IS
  the truth (Principle 11); silence on its failure is dishonest,
  and continuing produces responses that vanish.
- **Per-turn retry with backoff.** Retry the append once, then
  abort if still failing. Rejected for P1.4: the project has no
  retry infrastructure (subprocess timeouts in `workflow/cli.py`
  are the closest precedent; not transferable). Defer to P1.5+
  when production usage surfaces the need; until then the abort-on-
  first-failure default is honest and conservative.

**Test coverage (P1.4-8 acceptance).** §3 cleanup variant: mock
`event_store.append` to raise `sqlite3.OperationalError` on agent
A's utterance; assert the exception propagates (does not continue
to agent B); assert no further `llm_router.call` invocations are
made (verifiable via the mock's call count); assert agent A's prior
LLM response is NOT discarded by retry (the LLM cost is sunk; only
the persistence path is broken).

**TurnResult relationship.** When the abort path fires, the
`TurnResult` is never constructed (the function raises before
returning). Callers (room runtime, P1.5+) handle the exception path
distinctly from the `TurnResult.failed_agents` path; they are
categorically different failure modes.

**Test coverage (P1.4-8 acceptance).** §3 cleanup test: mock
`LLMRouter.call` to raise on agent A; assert no event for A is
appended; assert subsequent agent B's `should_agent_speak` is still
called; assert B's utterance IS appended; assert the captured log
contains "agent skeptic LLM call failed". Also: `asyncio.CancelledError`
mid-flight (if `LLMRouter.call` ever becomes async — currently sync)
re-raises unwrapped.

## Considered alternatives

### A. Concurrent dispatch (`asyncio.gather` on all speak=True agents)

Multiple agents' LLM calls fire in parallel; results appended in
alphabetical-id order after all complete. **Rejected** (Decision 1):
larger test surface, no perf need at P1.4 scale, introduces
project's first true concurrency surface alongside the multi-agent
contract — too much novelty at once. **The original draft preserved
this as an "additive upgrade behind the same `async def` signature."
The 2026-05-27 revision (R0-B 🟡#4) rejected the async-shape-now
framing** — the project has no asyncio surface to amortize against;
introducing one for a hypothetical P1.5+ caller is strictly larger
blast radius than re-shaping sync→async when concurrency actually
lands. P1.4 dispatch is `def`; P1.5+ concurrent upgrade re-shapes
both signature and body in the same commit (one call-site at most;
the room runtime that calls `dispatch_turn` is itself P1.5+ scope).

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

**Adopted in 2026-05-27 revision (per R0-B 🟡#3 routing).** The
original draft rejected this alternative; R0-B correctly challenged
that argument. P1.4 ships 2 agents with disjoint speaking-triggers
— there is no real conflict for `Agent.priority` to resolve.
Skill.priority precedent (ADR-009 D6) actually argues the other
way: that field was added because real ordering needs existed in
the current skill set; P1.4's 2-agent sample doesn't have those
needs. The migration cost when P1.5+ surfaces real multi-agent
conflict is small (one Pydantic field + one default + tune 2 now-
existing agent yamls). See Decision 3 (revised) for the additive-
upgrade path.

## Consequences

**Easier:**

- Sequential + synchronous dispatch makes turn semantics easy to
  reason about: one LLM call at a time, deterministic event order,
  no race conditions, no `asyncio` color in the project.
- Snapshot-per-turn makes multi-agent debugging tractable: every
  agent's decision is reproducible from the snapshot + the agent's
  configuration.
- Separate `build_agent_context` function preserves the dispatch-vs-
  context concern separation; P1.5+ context-building additions
  (snapshot excerpting, persona templating, autonomy-aware tool
  context) don't reshape `dispatch_turn`.
- The three new constitutional tests catch layering slips at PR
  time (analogous to W-001-impl Y1 pattern paying off).
- D7 LLM-exception policy means one agent's failure doesn't lose
  the whole turn — preserves multi-perspective Principle 6 under
  realistic operational conditions.

**Harder:**

- Sequential dispatch means a 5-agent room has 5× LLM-call latency
  per turn (~30-75s with current models). For P1.4 this is fine
  (no SLA); for production this becomes the prompt to land the
  concurrent upgrade.
- The snapshot-per-turn rule is non-obvious. Newcomers wonder "why
  doesn't agent B see agent A in the same turn?" — the answer is
  in this ADR and in ADR-010 D5, but it's not the most intuitive
  default.
- **User-facing latency cost of snapshot-per-turn (2026-05-27
  revision per R0-B 🟡#7 routing):** snapshot-per-turn means agent
  B's reaction to agent A's utterance is delayed by one turn — the
  user sees A's response → user replies → only NOW B reacts to A's
  earlier hypothesis/observation. For a 2-agent MVP this latency is
  real and user-visible (one full round-trip per cross-agent
  reaction). The trade is determinism + turn-as-atomic-reasoning-
  unit; the Reversibility table correctly marks this Expensive to
  reverse. Honest naming: the rule is correct for P1.4 scope but
  buys atomicity at the cost of cross-agent reaction latency.
  When P1.5+ user-experience work surfaces "skeptic should chain
  off prober's hypothesis in the same turn," that's the prompt to
  re-evaluate Boundary (c).
- P1.5+ concurrent dispatch upgrade re-shapes both signature AND
  body (`def` → `async def` AND body adds `asyncio.gather`). Since
  P1.4 has zero callers (no room runtime yet), the re-shape cost is
  one commit. Mitigated by the deliberate-not-incidental sync
  choice in D1.

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
| 1. Sequential + sync dispatch (concurrent re-shapes both body and signature in P1.5+) | **Low** — zero callers exist in P1.4; the P1.5+ commit that adds concurrency re-shapes both `def → async def` AND body together. One commit, one call-site at most (room runtime, itself P1.5+). |
| 2. Per-turn snapshot semantics | **Expensive** — switching to live reads breaks turn atomicity, breaks every multi-agent test, breaks cooldown determinism. Pick this once. Cross-agent reaction latency is the named cost (Consequences). |
| 3. Alphabetical-id conflict resolution (no `Agent.priority` in P1.4) | **Low** — `Agent.priority: int = 50` lands additively in the P1.5+ commit that surfaces real conflict; existing skeptic + prober yamls get the default; new agents tune. Migration touches 2 yamls at most. |
| 4. `build_agent_context` separate function | **Low** — inlining is a refactor; downstream callers update. The separate-function shape preserves the dispatch-vs-context concern seam for P1.5+ context-building additions. |
| 5. Three constitutional tests for layering | **Trivial** — adding more tests is additive. Removing means accepting a layering risk we deliberately rejected. |
| 6. §2 sequential-snapshot test only | **Low** — when concurrent dispatch lands (P1.5+), §2 tests expand additively. The snapshot test remains valid because the snapshot invariant persists under concurrent. |
| 7. Per-agent LLM exception policy (log + skip + continue) | **Low** — switching to abort-on-first-failure is a one-line change in `dispatch_turn` (re-raise instead of catch). Abort-on-N-failures is additive (counter + threshold). The current policy is the "preserve multi-perspective" default; alternatives ship later if ops surface need. |

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
