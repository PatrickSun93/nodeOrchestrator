# ADR-014: Snapshot contract — pure-function derived view + persisted-via-event

**Status:** Proposed — 2026-05-28
**Scope:** Locks the structural vocabulary, producer semantic, persistence shape, and consumer protocol for the `Snapshot` type. Governs every future producer of `summary_snapshot` events and every consumer of derived state-at-time-X views. Does not govern decision log (separate ADR-015) or cross-room memory persistence (deferred).

## Context

The event store has been the project's single source of truth since P0 (ADR-001), but every consumer has had to re-read raw events to compute state-at-time-X (room state, open hypotheses, pending tool calls, etc.). P1.5.5 closed the producer side of `agents → autonomy` (ADR-013) by adding `tool_call` event producers; the consumer side has been empty. ADR-012 declared a room state machine transition `snapshot_pending → closed` that fires when a `summary_snapshot` event is appended, but no producer existed — the transition has been a dead-end since P1.5.

**Three forces shape this ADR:**

1. **Principle 1 (event log is truth)** — derived views are not authoritative; they're cacheable derivations from the canonical event stream.
2. **Principle 9 (no orphan spec)** — vocabulary must be inscribed before producers ship, so future readers don't relitigate "what does field X mean?"
3. **ADR-001 + ADR-013 D5 deliberate-duplication pattern** — typed event metadata duplicates derived-class fields to preserve module layering (`core/event` MUST NOT import from `derived/` or `autonomy/`).

The architect-partner brief proposed an 8-field initial vocabulary (architect-settled decision 4). Senior pre-investigation against future-consumer needs + Principle 9 (capture-now-or-amend-later) confirms all 8 fields warrant inclusion; the alternative ("strip pending-tool-calls field; add when UI consumes") would require ADR amendment when P2 UI surfaces materialize.

Touches Principle 1, Principle 5 (code decides what code can — `produce_snapshot` is pure code), Principle 9 (vocabulary inscription).

**Hard requirements**:
- `produce_snapshot` is pure: same input events → same output Snapshot. No I/O, no LLM, no `event_store.append` inside the function.
- Snapshot is derivable from re-running `produce_snapshot` on the same event stream — re-derivation invariant (no hidden state).
- Persistence is via `summary_snapshot` events whose metadata carries the serialized Snapshot. No separate snapshot table; the event IS the persistence.
- `core/event` MUST NOT import from `derived/`. Typed metadata duplicates the derived-class fields per the documented duplication pattern.
- Constitutional invariant: no LLM imports in `derived/` (snapshot is code-decided per Principle 5).

## Decisions

### 1. `produce_snapshot(events, room) -> Snapshot` is a pure function over event stream

Pure function in `src/orchestrator/derived/snapshot.py`. Input: pre-fetched `events: list[Event]` + `room: Room`. Output: a frozen `Snapshot` Pydantic model. **The function does not call `event_store` internally** — caller is responsible for fetching events (typically via `event_store.get_room_events(room.id)`); the function does not append events; it does not invoke LLM.

**Why**: Principle 1 + Principle 5. Snapshot is a derivation, not an authority; isolating purity from event-store I/O makes the function trivially testable + cacheable. Caller (Logger agent's `produce_and_emit_snapshot` from ADR-013-D1-style sibling module) handles the I/O.

### 2. Bounded snapshot vocabulary — 11 classes (1 Snapshot + 4 Ref + serialized SummarySnapshotMeta in core)

The `Snapshot` Pydantic model + 4 reference types are frozen at this ADR; future fields require ADR amendment per Principle 9.

```python
# src/orchestrator/derived/snapshot.py
class HypothesisRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_id: str

class DecisionRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_id: str

class ToolCallRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_id: str
    tool_name: str
    autonomy_tier: Literal["countdown_confirm", "hard_confirm"]

class StateTransitionRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_id: str
    new_state: str
    prior_state: str

class Snapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    room_id: RoomId
    room_type: RoomType
    room_state: str
    snapshot_at: int  # ms timestamp
    event_count: int = Field(ge=0)
    decision_count: int = Field(ge=0)
    open_hypotheses: list[HypothesisRef]
    closed_decisions: list[DecisionRef]
    tool_calls_pending_confirm: list[ToolCallRef]
    last_state_transition: StateTransitionRef | None
    participants: list[str]  # sorted alphabetically by agent_id
```

**Field rationale** (per senior pre-investigation §5 #1 defense):
- Structural identifiers (`room_id`, `room_type`, `room_state`, `snapshot_at`, `event_count`, `decision_count`): foundational state-at-time-X identifiers.
- Reference-only collections (`open_hypotheses`, `closed_decisions`, `tool_calls_pending_confirm`): preserve Principle 1 — references not content copies; consumer queries event_store for content.
- `tool_calls_pending_confirm.autonomy_tier`: convenience for "what's awaiting which kind of confirmation?" reads (`countdown_confirm` vs `hard_confirm`); `AUTO_EXECUTE` excluded because not pending.
- `last_state_transition`: needed by consumers asking "how did we get here?" — references the most-recent state_transition event.
- `participants`: sorted-alphabetically agent_ids that emitted ≥1 utterance in the room; deterministic ordering for reproducibility.

### 3. Producer semantic: Logger agent triggers on `state_change: snapshot_pending`

Logger agent's `speaking_triggers` includes a `StateChangeTrigger(target_state="snapshot_pending")`. When a `state_transition` event with `new_state=snapshot_pending` is dispatched, Logger's response path calls `produce_snapshot(events, room)` + `produce_decision_log(events, room)` (ADR-015) + appends a `summary_snapshot` event whose metadata carries `Snapshot.model_dump()`.

**Why state-machine-triggered** (over alternatives):
- State IS the semantic signal — room reaches `snapshot_pending` because convergence criteria met; snapshot is the natural response.
- `producer-on-every-state-transition`: too frequent (wastes Logger LLM dispatch even though P1.6 doesn't use LLM-augmented snapshots yet; future LLM-augmented variants would be expensive).
- `producer-on-event-count-threshold`: arbitrary; decoupled from state machine causality; harder to reason about.

Hardcoded `agent.id == "logger"` is acceptable for P1.6 single-producer scope; multi-producer support requires ADR amendment (P1.7+ hook).

### 4. Persisted-via-event: no separate snapshot table

`summary_snapshot` events carry `SummarySnapshotMeta(snapshot.model_dump())` as their typed metadata. The event IS the persistence; **no separate snapshot table or storage layer is added**. Consumers retrieving past snapshots query `event_store.get_room_events(room.id)` filtered by `EventType.SUMMARY_SNAPSHOT` and read `event.metadata`.

This honors ADR-001 (event log is truth) + ADR-008 D7 (event store as canonical observability path). Snapshots are cacheable but never authoritative independent of the event stream.

### 5. Deliberate duplication: `SummarySnapshotMeta` in `core/event.py` mirrors `Snapshot` fields

`core/event` MUST NOT import from `derived/` to preserve module layering (matches ADR-013 D5 + the pattern documented at `autonomy/emission.py:7-11` where `AutonomyDecisionMetadata` in `core/event.py:198+` mirrors `DecisionTrace` from `autonomy/scoring.py`). `SummarySnapshotMeta` accepts the same field names as `Snapshot` but with permissive types (`list[dict[str, Any]]` for the Ref collections; `dict[str, Any]` for nested transition) — Pydantic-level shape match, not class-identity.

**Round-trip invariant**: `Snapshot.model_dump() → dict → SummarySnapshotMeta.model_validate(dict).model_dump() → Snapshot.model_validate(dict)` yields identical Snapshot. Tested in P1.6-2 ≥1 round-trip test.

### 6. Snapshot timestamp invariant under concurrent event append

`Snapshot.snapshot_at` is captured AT `produce_snapshot` call time via `core.event.now_ms()`. The `events: list[Event]` argument is a pre-fetched snapshot (caller responsibility); any events appended to the event_store AFTER the fetch but BEFORE `summary_snapshot` lands are NOT in this snapshot. Re-running `produce_snapshot` on a later fetch produces a later snapshot.

**This is the read-vs-write ordering invariant**: snapshot semantic is "state at time T as observed by the caller who fetched at T"; not "state at time T as universal truth." Test §2 concurrency pins this: appending an event during `produce_snapshot` does NOT change the returned Snapshot (pure function over the input list); the next snapshot run reflects the appended event. Consumers requiring strict universal-time semantics use the `event_store`'s SQLite transaction model directly (P1.7+ scope if needed).

## Considered alternatives

### A. Snapshot as separately persisted entity with own SQLite table

Add `snapshots` table; `produce_snapshot` writes to both event_store AND snapshots table; consumers query the dedicated table for fast lookups.

**Why rejected (ruled out by D1+D4)**: violates Principle 1 (snapshot would become an alternative source of truth alongside event store). Sync semantics between two stores is non-trivial; cache invalidation is hard. ADR-001 explicitly resists this pattern. Cacheability via metadata + derivation is sufficient for P1.6 consumers.

### B. LLM-augmented summary text in initial Snapshot vocabulary

Add `summary_text: str` field; Logger composes via `LLMPurpose.SNAPSHOT_SEMANTIC` (exists at `llm/purposes.py:46`) before appending the event.

**Why rejected**: brief Out-of-scope #3 explicitly defers LLM-augmented snapshot generation; per W-004-2 (c) literal-reading discipline, "deferred" is substantive. No UI consumer for summary text yet; vocabulary capture-now would be orphan field. Add via ADR-014 amendment when consumer materializes.

### C. Split package `snapshot/` + `decisions/` (brief lean)

Two packages, each owning one derived view; two constitutional tests; two `__init__.py`.

**Why rejected (combined per senior §5 #4)**: project precedent for sibling-pattern same-package (`autonomy/{scoring,emission}.py`) is established; reader-cognitive cost of two packages vs one is unjustified; combined package supports shared test fixtures + single constitutional test. Senior deviation defended in plan §5 #4.

### D. Snapshot fields include LLM-derived content excerpts (instead of references)

`Snapshot.open_hypotheses` would be `list[HypothesisContent]` with `content: str` field copied from the original event.

**Why rejected**: violates Principle 1 (content duplication; canonical content in event_store is shadowed by snapshot copy). Reference-only design preserves the "events are truth; snapshots are pointers" model. Consumers needing content query event_store via the ref's `event_id`.

## Consequences

**Easier:**

- Every consumer of "state-at-time-X" reads `Snapshot` once instead of re-computing from raw events — `produce_snapshot` is the single computation point.
- Logger agent's dispatch contract becomes substantively useful — `snapshot_pending → closed` transition fires for the first time in project history.
- Cross-room agents + future UI surfaces inherit a stable contract; ADR-014 D2's frozen vocabulary means consumers can rely on field set.
- Test discoverability: derived-view tests live in `tests/derived/`; one constitutional test covers the module's no-LLM invariant.

**Harder:**

- Adding fields to `Snapshot` requires ADR-014 amendment (Principle 9 — vocabulary fixed). Hidden cost: future-consumer wishes get debated at ADR-revision time, not silently added.
- `core/event.py` + `derived/snapshot.py` carry the deliberate-duplication of fields — keeping them in sync is manual discipline (tested via round-trip invariant in P1.6-2).
- Logger's single-producer assumption hardcodes `agent.id == "logger"` in dispatch wiring; future multi-producer support requires ADR amendment (P1.7+ if a real second producer materializes).

**Neutral:**

- Snapshots are cacheable but consumers may re-derive on demand instead — both paths consistent.
- Snapshot fields capture reference IDs not content; consumers wanting content take one extra `event_store` query.
- LLM-augmented snapshot variants land later (Out-of-scope #3); D2 vocabulary is forward-compatible to additive amendment for `summary_text` etc.

## Reversibility

| Decision | 6-month reversal cost |
|---|---|
| D1 (pure function over event stream) | **Trivial.** Reverting to "function takes event_store ref + queries internally" is a signature change with no caller-contract breakage (caller can pass `event_store`). Reversal probably indicates a performance reason; can be done in-place without ADR amendment if pattern. |
| D2 (bounded 11-class vocabulary) | **Medium.** Each field addition is an ADR-014 amendment. Removing fields requires consumer audit (which consumers use field X?). Frozen ADR-revision pattern. |
| D3 (state-machine-triggered Logger producer) | **Low.** Alternative trigger (e.g., user-request-triggered) is one yaml edit (logger.yaml `speaking_triggers` update) + dispatch path adjustment. Multi-producer support is bigger refactor but additively decided. |
| D4 (persisted-via-event; no separate table) | **Expensive.** Adding a snapshot table means migrating existing event_store snapshots + dual-write semantics + consumer-API change. Major refactor; would need new ADR. ADR-001 alignment is the conservative choice. |
| D5 (deliberate duplication) | **Trivial.** Field-set mirror; if classes diverge, round-trip test catches; can be re-synced. Pattern is intentional per `autonomy/emission.py:7-11` precedent. |
| D6 (snapshot timestamp invariant under concurrent append) | **Low.** Read-vs-write semantic; if stricter universal-time needed, callers use event_store transactions directly. Doesn't constrain producer; constrains consumer expectation. |

## References

- ADR-001 — event log as truth (informs D1, D2, D4 — snapshots derive from events; never authoritative).
- ADR-008 — workflow state machine (this ADR routes via `awaiting_architect_accept` per multi-ADR W-002.5 aggregation alongside ADR-015).
- ADR-010 — should_agent_speak contract + StateChangeTrigger (informs D3 — Logger's `state_change: snapshot_pending` trigger).
- ADR-011 — multi-agent dispatch (D4 separate-concern pattern matches P1.6-3 `snapshot_dispatch.py` sibling module).
- ADR-012 — room state machine (`snapshot_pending → closed` transition declared at `rooms/state_machine.py:26`; this ADR provides the producer).
- ADR-013 — operator tool-dispatch contract (D1 sibling-module pattern matches P1.6-3 wiring; D5 typed-metadata-mirror pattern matches D5).
- `handoff.md` §4.5 (cross-room memory deferred per brief Out-of-scope #1); §5.7 (state machines); §5.8 (persistence).
- `src/orchestrator/autonomy/emission.py:7-11` — deliberate-duplication rationale (precedent for D5).
- `src/orchestrator/core/event.py:88` — `EventType.SUMMARY_SNAPSHOT` existing definition (consumed by D4 + D5).
- `src/orchestrator/core/event.py:272-282` — `TYPED_METADATA` dict (P1.6-2 adds `EventType.SUMMARY_SNAPSHOT: SummarySnapshotMeta` per D5).
- `src/orchestrator/agents/schema.py:39-50` — `StateChangeTrigger.target_state: str` (consumed by D3 — accepts `snapshot_pending` as-is).
- `src/orchestrator/rooms/state_machine.py:26` — `snapshot_pending → closed` transition declaration (consumed by D3 — Logger's snapshot append fires this).
- `docs/process/architect-briefs/P1.6.md` — brief that prompted this ADR.
- `docs/process/senior-plans/P1.6.md` — plan that locks atomic-task breakdown.
- Implementation lands on `claude/P1.6-impl` post-Accept.
