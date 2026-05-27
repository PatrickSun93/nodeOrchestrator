# ADR-010: `should_agent_speak` Decision Contract

**Status:** Proposed — 2026-05-26 (revised 2026-05-27 absorbing R0-A-on-plan + R0-B-cross-family architect-routing — see `docs/process/reviews/P1.4/architect-routing.md`)
**Scope:** Governs the per-turn pure-function decision of whether a
given agent speaks on a given turn: `should_agent_speak(agent,
event_stream_snapshot, *, current_event) -> SpeechDecision`.
Inscribes the trigger-type vocabulary (regex / event_type /
state_change), the cooldown evaluation rule (event-stream-driven,
per-snapshot), the `SpeechDecision` shape with embedded decision
trace, the trigger-evaluation order and short-circuit semantics, the
snapshot-reading invariant, and the load-time validation of
`speaking_triggers`. Out of scope: multi-agent conflict resolution
(ADR-011), summon decisions (deferred to P1.5), turn-boundary
events, cross-turn agent state (P1.6).

## Context

`handoff.md` §4.4 declares each agent has `speaking_triggers: list`
elements that are regex / event_type / state_change. Per §3.1
("decision paths in code, LLMs generate content"), the gating
decision of whether an agent gets to speak is code-only — no LLM
introspection of "is this agent relevant?", just structured
predicate matching. P1.4 turns this into a working contract.

`should_agent_speak` is **the load-bearing new decision function
P1.4 introduces**. Every agent's `speaking_triggers` field, every
test of agent dispatch, every future agent role added in P1.5+
depends on its exact shape. Three constraints bind:

- **Pure code, no LLM.** Locked by
  `test_constitution_no_llm_calls_in_agents_module` (P1.4 adds).
- **Event-stream-driven cooldown.** Per brief Architect-settled
  decision 2 — `agent.cooldown_seconds` is enforced against the
  agent's most recent `utterance` event in the snapshot, NOT a
  wall-clock timer. Survives crashes, session restarts, multi-
  session interleaving.
- **Decision trace.** Per `contributing.md` Q2, the function returns
  enough info to explain *why* the agent was (or wasn't) selected to
  speak — which trigger matched, what cooldown said, whether the
  current_event was the right kind.

The shape must support a turn-dispatch primitive (ADR-011) calling
`should_agent_speak` against all loaded agents in deterministic
order, against the same pre-turn event-stream snapshot, and
collecting per-agent decisions with traces.

Hard requirements:

1. Trigger-type vocabulary closed (Principle 4 — closed enums over
   free strings). Three types in P1.4: `regex`, `event_type`,
   `state_change`. Adding a type is an ADR amendment.
2. Cooldown rule unambiguous and snapshot-driven (not wall-clock).
3. Trigger evaluation order deterministic (no ordering surprises
   across runs).
4. `SpeechDecision` shape carries trace inline (per ADR-005 D6 and
   ADR-009 D6 precedents — trace lives with the decision).
5. Load-time validation of `speaking_triggers` (malformed triggers
   are caught at agent-load, not at first dispatch).

## Decisions

### 1. Three trigger types — closed Literal

`speaking_triggers` is a `list[SpeakingTrigger]` where
`SpeakingTrigger` is a discriminated-union Pydantic model. The
discriminator field is `type: Literal["regex", "event_type",
"state_change"]`. P1.4 ships all three types — each one exercises a
real agent need:

- `regex` — pattern matched against `current_event.content` (text
  field). Used by prober on user-input ("when user says X, prober
  speaks").
- `event_type` — matches when `current_event.type` equals a target
  value. Used by skeptic on hypothesis density ("when a new
  `hypothesis` event lands, skeptic wants the next turn").
- `state_change` — matches when the current event is a
  `state_transition` event AND the room's new state matches a target
  value. Used for "room enters research state, prober speaks."
  **Depends on `StateTransitionMeta(new_state: str)` typed
  metadata** (added to `core/event.py` `TYPED_METADATA` in P1.4-4
  per R0-B 🔴#2 routing; closes the un-typed-metadata gap that made
  this trigger type ship-incomplete in the original draft). The
  trigger evaluation reads `current_event.metadata.new_state` (typed
  field access; not `metadata["new_state"]` dict access).

Adding a fourth trigger type (e.g., `multi_agent_disagreement` for
arbiter agents in P1.5+) requires an ADR amendment + a constitutional
test extension. The closed-enum cost is documented at
`feedback_schema_enforcement.md`-style enforcement.

```python
class RegexTrigger(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["regex"] = "regex"
    pattern: str = Field(min_length=1)
    # Compiled-at-load; see Decision 6.

class EventTypeTrigger(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["event_type"] = "event_type"
    event_type: EventType  # validated against the closed enum

class StateChangeTrigger(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["state_change"] = "state_change"
    target_state: str = Field(min_length=1)

SpeakingTrigger = Annotated[
    RegexTrigger | EventTypeTrigger | StateChangeTrigger,
    Field(discriminator="type"),
]
```

### 2. Cooldown — event-stream-driven, per-snapshot

`agent.cooldown_seconds` is enforced against the agent's most recent
`utterance` event in the **same event-stream snapshot** the trigger
evaluation reads.

**Unit-conversion contract (added in 2026-05-27 revision, R0-B 🔴#1):**
`agent.cooldown_seconds` is human-readable seconds (yaml unit; `int`,
seconds, ≥0). `event.timestamp` is project-internal milliseconds
(`TimestampMs = NewType("TimestampMs", int)` per `core/event.py`,
populated by `now_ms() = int(time.time() * 1000)`). **The conversion
site is `should_agent_speak`'s cooldown evaluation, named here so
the impl cannot silently get it wrong:**

```python
elapsed_s = (current_event.timestamp - last_utterance.timestamp) / 1000.0
if elapsed_s < agent.cooldown_seconds:
    cooldown_remaining_s = float(agent.cooldown_seconds) - elapsed_s
    return SpeechDecision(speak=False, reason="cooldown_active",
                          cooldown_remaining_s=cooldown_remaining_s, ...)
```

Yaml stays human-readable seconds. Event stream stays ms. The `/1000.0`
in the comparison + the `cooldown_remaining_s: float` field both
match the seconds-as-float human-readable unit. The cost of getting
this wrong is silent (a `cooldown_seconds=60` agent would block for
60ms not 60s; tests that don't sleep wouldn't catch it). The fix is
load-bearing for the contract to ship correctly. P1.4-7's
`should_agent_speak` body MUST inscribe this exact `/1000.0` site
per ADR cross-reference.

**Mechanics (in order):**

1. Find the most recent event in the snapshot where `author ==
   f"agent:{agent.id}"` and `type == EventType.UTTERANCE`.
2. Compute `elapsed_s = (current_event.timestamp - last_utterance.timestamp) / 1000.0`.
3. If `elapsed_s < agent.cooldown_seconds`, the agent is in cooldown;
   `should_agent_speak` returns `SpeechDecision(speak=False,
   reason="cooldown_active", cooldown_remaining_s=...)` regardless
   of trigger match.
4. If no prior utterance exists in the snapshot, the agent is not
   in cooldown.

Timestamps come from `event.timestamp` (event-stream-stored). NOT
`time.time()`. Wall-clock comparison would make cooldown drift
across crashes and replay; event-timestamp comparison is replayable
and deterministic.

The cooldown check fires **before** trigger evaluation. Rationale:
trigger evaluation can be expensive (regex compile, multi-pattern
match); cooldown is O(1) lookup in the snapshot. Short-circuiting on
cooldown is the cheap path. The trace records cooldown-blocked as a
distinct reason from no-trigger-matched (see Decision 3).

### 3. `SpeechDecision` shape with embedded trace

```python
class SpeechDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    agent_id: str
    speak: bool
    reason: Literal[
        "trigger_matched",
        "no_trigger_matched",
        "cooldown_active",
        "no_triggers_configured",
    ]
    matched_trigger_index: int | None = None
    cooldown_remaining_s: float | None = None
```

`speak` is the binary output. `reason` is the closed-Literal
discriminator — every code path returns one of four values, no free
strings. `matched_trigger_index` (0-based) points to the entry in
`agent.speaking_triggers` that fired (or `None` when none fired).
`cooldown_remaining_s` is populated when `reason == "cooldown_active"`,
None otherwise.

The trace fields are deliberately small. A `should_agent_speak` call
runs N times per turn (once per loaded agent); returning a
`considered_triggers: list[...]` per call would balloon the event
log under multi-agent dispatch. The matched-trigger-index + cooldown
fields cover the diagnosis-from-logs case; deeper trigger-by-trigger
inspection is a debugger concern, not an audit-log concern.

Reason values explained:

- `trigger_matched` — at least one trigger fired AND cooldown was
  satisfied. `speak=True`.
- `no_trigger_matched` — none of the configured triggers fired
  against this event. `speak=False`.
- `cooldown_active` — cooldown short-circuited before triggers were
  evaluated. `speak=False`. `cooldown_remaining_s` populated.
- `no_triggers_configured` — `agent.speaking_triggers == []`. The
  agent never speaks autonomously (e.g., a logger that only fires
  on explicit summon). `speak=False`. This is a distinct reason from
  `no_trigger_matched` because it's an agent-config statement
  ("never speak autonomously"), not a per-event mismatch.

### 4. Trigger evaluation order — list order, first-match short-circuit

Triggers are evaluated in `agent.speaking_triggers` list order. The
**first matching trigger wins**; subsequent triggers are not
evaluated. `matched_trigger_index` is the 0-based index of the
winning trigger. Rationale: list order is deterministic and author-
controlled; the agent author orders triggers by what they want
matched first. Alternative ("evaluate all and report most-specific
match") requires defining specificity — which has no obvious
ordering across the three trigger types and adds complexity for no
gain.

If `speaking_triggers == []`, the function short-circuits to
`SpeechDecision(speak=False, reason="no_triggers_configured")`
without computing cooldown — Decision 2's cooldown-check-first rule
applies only when triggers exist.

### 5. Snapshot-reading invariant

`should_agent_speak` reads exclusively from the
`event_stream_snapshot` parameter — a frozen list passed by the
caller. The function does NOT call `event_store.get_events()` or
any I/O. The caller (the turn-dispatch primitive from ADR-011) is
responsible for taking the snapshot at turn start and passing the
same snapshot to every `should_agent_speak` call within the turn.

This invariant is what makes ADR-011 Boundary (c) work: every
agent's decision within a turn is computed against the same pre-
turn event view. The pure-function constraint is enforced by the
constitutional test (no I/O imports) and by the function signature
itself — the snapshot is a required positional argument, not a
keyword default or a global.

### 6. Load-time validation of `speaking_triggers`

The agent loader validates `speaking_triggers` at agent-load time:

- Every entry parses as a valid `SpeakingTrigger` (discriminated
  union — Pydantic does this automatically).
- Every `RegexTrigger.pattern` compiles via `re.compile()` at load
  time (a malformed regex caught at agent-load, not at first
  dispatch). The compiled pattern is cached in a **separate loader-
  level registry** (chosen explicitly in the 2026-05-27 revision per
  R0-A Y3 routing). The registry shape is `dict[(agent_id: str,
  trigger_index: int), re.Pattern[str]]`; the loader populates it
  at agent-load time. `should_agent_speak` accepts the registry via
  a keyword-only parameter (threaded through `dispatch_turn` per
  ADR-011 D1). **Rationale for separate registry over
  `model_post_init` private attribute:** frozen-model semantics are
  load-bearing for the project's invariant discipline; storing a
  mutable compiled-pattern as a private attribute on a `frozen=True,
  extra="forbid"` model bypasses the discipline enforced elsewhere
  (Pydantic models in `core/`, `autonomy/`, `skills/`, `workflow/`
  are all frozen-with-no-mutable-private-state). The separate
  registry preserves the frozen-model invariant at the small cost
  of threading the registry as a parameter through `dispatch_turn`
  → `should_agent_speak`.
- Every `EventTypeTrigger.event_type` is in the `EventType` enum
  (Pydantic enforces).
- Every `StateChangeTrigger.target_state` is a non-empty string
  (Pydantic Field min_length).

Load-time failures raise `AgentLoadError` with `agent_id` + the
offending trigger index. Per §4 payload obligation.

The load-time regex compile is the load-bearing case: a regex that
compiles late causes a runtime exception during dispatch, deep in
the call stack — far from the misconfigured agent yaml. Catching at
load is the fail-fast path.

## Considered alternatives

### A. Free-string `type` field on `SpeakingTrigger`

`type: str` instead of `Literal[3 values]`. **Rejected**: violates
Principle 4 (closed vocabulary over open strings). A typo'd type
string ("regexp" instead of "regex") would silently fail at
dispatch instead of at agent-load.

### B. Wall-clock cooldown

`elapsed = time.time() - agent._last_spoke_wall_clock`. **Rejected**:
violates brief Architect-settled decision 2. Wall-clock cooldown
fails on crashes (state lost), on event-stream replay (cooldown
fires against a different clock than the event-author saw), on
multi-session interleaving (agent's cooldown in session A leaks
into session B). The event stream is the project's single source of
truth (Principle 11) — derived state belongs there.

### C. Evaluate-all-triggers with specificity ranking

Evaluate every trigger, return the most-specific match. **Rejected**:
specificity has no obvious cross-type ordering (is a regex more or
less specific than an event_type?). The list-order rule pushes the
ordering decision to the agent author where they have the context.

### D. `SpeechDecision.considered_triggers: list[...]` for full trace

Carry per-trigger match-or-not in every decision. **Rejected**: N
agents × M triggers per agent × per-turn = N×M log entries per turn.
At scale (5+ agents, 5+ triggers each, 100 turns per session) this
is hundreds of KB of trace. The matched-index + cooldown-remaining
fields cover diagnosis-from-logs; full per-trigger inspection is a
debugger concern (re-run with verbose flag), not an audit concern.

### E. Reason as bitfield / list

`reason: list[Literal[...]]` to capture combinations (e.g., "matched
trigger AND cooldown active" — though Decision 2 forbids this combo
by short-circuit ordering). **Rejected**: the short-circuit ordering
(cooldown → triggers → no-trigger) makes the reason naturally
singular. A list-of-reasons would invite recipients to combine reasons
in surprising ways.

## Consequences

**Easier:**

- Adding a new agent: one yaml file with `speaking_triggers:` list.
  Loader validates at startup; dispatch uses the same function for
  every agent.
- "Why didn't this agent speak?" is a single trace read —
  `SpeechDecision.reason` is one of four values, plus
  `matched_trigger_index` and `cooldown_remaining_s` for context.
- Cooldown survives crashes and replay — event-stream-driven means
  the rule replays identically.
- Snapshot invariant makes multi-agent dispatch reasoning
  tractable: every agent in a turn sees the same event view.
- Load-time regex compile catches misconfigured agents at startup,
  not at dispatch.

**Harder:**

- Three trigger types now need to be learned by every agent author.
  Mitigated by the skeptic + prober yamls in P1.4-9 acting as
  templates.
- Snapshot semantics are non-obvious for newcomers — "why doesn't
  agent B see agent A's response within the same turn?" The answer
  is ADR-011 Boundary (c); this ADR documents the half of the
  contract that lives in `should_agent_speak`.
- Adding a fourth trigger type requires an ADR amendment + a
  Pydantic union extension + a constitutional test extension —
  three coordinated changes, not one. The cost is intentional
  (closed-enum discipline) but worth naming.
- `SpeechDecision.reason` is deliberately narrow (4 values). When a
  fifth distinct cause-of-not-speaking emerges (e.g., a future
  "agent paused by user" mechanism), the Literal extends per the
  refusal_reason precedent from ADR-007 D2.

**Neutral:**

- The frozen-model + compiled-regex-cache uses a **separate
  loader-level registry** (D6, revised pick). Threading the registry
  through `dispatch_turn` → `should_agent_speak` adds one keyword-only
  parameter to two function signatures. Pure ergonomic cost; no
  behavior impact. The alternative (`model_post_init` private attr)
  was explicitly rejected to preserve frozen-model invariants.
- Trigger evaluation is O(N) per agent per turn where N is the
  number of triggers. For MVP agents (3-5 triggers each, 2-5 agents
  per room) this is bounded; at scale the per-turn cost is
  recomputable from snapshot characteristics.

## Reversibility

| Decision | 6-month reversal cost |
|---|---|
| 1. Three trigger types (closed Literal) | **Medium** — adding a trigger type is additive (new Pydantic model + Literal extension + new branch in evaluator). Removing a type is a migration across all agent yamls that use it. |
| 2. Event-stream-driven cooldown | **Expensive** — switching to wall-clock requires re-architecting every cooldown-aware test, breaking replay determinism, and forfeiting Principle 11 alignment. Pick this once, deliberately. |
| 3. `SpeechDecision` shape with embedded trace | **Low** — adding fields is additive; removing breaks downstream tooling that reads the trace. The 4-reason Literal extends additively per ADR-007 D2 precedent. |
| 4. List-order first-match | **Low** — switching to specificity-ranking is a `should_agent_speak` body change; agent yamls don't change shape. But all existing tests rely on first-match semantics. |
| 5. Snapshot invariant | **Expensive** — relaxing to live-read breaks ADR-011's turn semantics and forces every test of multi-agent dispatch to re-account for non-determinism. The pure-function constraint is load-bearing. |
| 6. Load-time `speaking_triggers` validation | **Trivial** — moving to runtime validation is a loader-code change; doesn't affect agent yamls. But late-failure debug cost increases. |

## References

- `handoff.md` §3.1 (decision paths in code), §4.4 (Agent schema
  with `speaking_triggers`), §5.1 (5-agent set), §5.3 (skill
  library, ADR-009).
- `docs/contributing.md` Q1 (no LLM calls), Q2 (`decision_trace`
  obligation), Q3 (5-surface scan).
- `docs/architecture/test-coverage-standard.md` — six categories;
  P1.4 first to exercise §2 (concurrency) non-trivially.
- ADR-001 (event store foundation) — `EventType` closed-enum
  precedent reused for the `event_type` trigger type discriminator.
- ADR-005 Decision 6 (autonomy_decision metadata) +
  ADR-009 Decision 6 (`SkillSelection` embeds trace) — the embed-
  trace-in-return-type precedent reused by `SpeechDecision`.
- ADR-007 Decision 2 (`refusal_reason` Literal extensibility) —
  same additive-Literal pattern reused for `SpeechDecision.reason`.
- ADR-008 (workflow state machine) — `.workflow/P1.4.yaml` governs
  this task's lifecycle.
- ADR-009 (SKILL.md frontmatter + decision shape) — sibling
  decision-function ADR (analogous shape; agents/ and skills/
  modules parallel by design).
- ADR-011 (multi-agent dispatch + concurrency) — sibling ADR
  consuming `SpeechDecision` to gate turn dispatch.
- `docs/process/architect-briefs/P1.4.md` — architect-settled
  decisions feeding into this ADR.
- `docs/process/senior-plans/P1.4.md` — implementation plan.
- Implementation entry point: P1.4-7 (`should_agent_speak` body +
  table-driven test file) is the load-bearing impl commit; P1.4-4
  schema lands the Pydantic surface this ADR declares; P1.4-5
  loader lands the load-time validation from Decision 6.
