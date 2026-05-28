# ADR-014: Snapshot contract — pure-function derived view + persisted-via-event

**Status:** Accepted — 2026-05-28 · Amended — 2026-05-28 (impl-stage R0 routing absorption: D2.3 `"unknown"` tier expansion, D2.1/D2.2 any-vs-subsequent clarification, new D2.6 `decision_count` predicate, new D7 error-semantic subsection — per `docs/process/reviews/P1.6/architect-routing-on-impl.md` M-R1 + M-Y1 + M-Y2 + Y2).
**Scope:** Locks the structural vocabulary, producer semantic, persistence shape, error semantic, and consumer protocol for the `Snapshot` type. Governs every future producer of `summary_snapshot` events and every consumer of derived state-at-time-X views. Does not govern decision log (separate ADR-015) or cross-room memory persistence (deferred).

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
- **Error semantic (per D7)**: derived module propagates `pydantic.ValidationError` on malformed typed metadata; no silent swallow. Dispatch caller narrows to `ValidationError` only and surfaces failure via `TurnResult`; `event_store.append` failures propagate unwrapped per ADR-011 D7-b.

## Decisions

### 1. `produce_snapshot(events, room, *, snapshot_at)` is a pure function over event stream + caller-provided clock

Pure function in `src/orchestrator/derived/snapshot.py` with **clock-injection** to preserve the purity contract (per R0-A Y2 → α routing absorption). Input: pre-fetched `events: list[Event]` + `room: Room` + `snapshot_at: TimestampMs` (keyword-only). Output: a frozen `Snapshot` Pydantic model.

```python
def produce_snapshot(
    events: list[Event],
    room: Room,
    *,
    snapshot_at: TimestampMs,
) -> Snapshot:
    """Pure derivation; caller provides snapshot_at (typically core.event.now_ms()).

    Pure function: same (events, room, snapshot_at) → same Snapshot.
    Caller (Logger's produce_and_emit_snapshot in snapshot_dispatch.py per P1.6-3)
    calls core.event.now_ms() and passes it; isolates wall-clock impurity at caller layer.
    See D6 (caller-frozen-time semantic).
    """
```

**The function does not call `event_store` internally**; **does not call `now_ms()` internally** (caller's responsibility — restores purity contract per Y2 → α reconciliation); does not append events; does not invoke LLM.

**Why clock-injection**: Y2 → α routing absorption. Original D1 ("pure function") + D6 ("snapshot_at via now_ms() at production time") were internally inconsistent — `now_ms()` is wall-clock impurity. Caller-injection of `snapshot_at` resolves the inconsistency: function stays pure (same input → same output); caller layer owns the clock impurity at a single boundary (P1.6-3 `snapshot_dispatch.py` calls `now_ms()` once, passes result through). Principle 5 (code decides; isolate impurity at boundary) preserved.

**Why pure**: Principle 1 + Principle 5. Snapshot is a derivation, not an authority; isolating purity from event-store I/O + wall-clock I/O makes the function trivially testable + cacheable + deterministic per fixed inputs.

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
    autonomy_tier: Literal["countdown_confirm", "hard_confirm", "unknown"]  # "unknown" per D2.3 anomaly path

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
    snapshot_at: int  # ms timestamp; caller-provided per D1 clock-injection + D6 caller-frozen-time
    event_count: int = Field(ge=0)
    decision_count: int = Field(ge=0)
    open_hypotheses: list[HypothesisRef]  # derivation predicate: D2.1
    closed_decisions: list[DecisionRef]  # derivation predicate: D2.2
    tool_calls_pending_confirm: list[ToolCallRef]  # correlation algorithm: D2.3
    last_state_transition: StateTransitionRef | None  # definition: D2.5
    participants: list[str]  # criterion: D2.4 (sorted alphabetically by agent_id post-prefix-strip)
```

**Field rationale** (per senior pre-investigation §5 #1 defense):
- Structural identifiers (`room_id`, `room_type`, `room_state`, `snapshot_at`, `event_count`, `decision_count`): foundational state-at-time-X identifiers.
- Reference-only collections (`open_hypotheses`, `closed_decisions`, `tool_calls_pending_confirm`): preserve Principle 1 — references not content copies; consumer queries event_store for content.
- `tool_calls_pending_confirm.autonomy_tier`: convenience for "what's awaiting which kind of confirmation?" reads (`countdown_confirm` vs `hard_confirm` vs `"unknown"`); `AUTO_EXECUTE` excluded because not pending. The `"unknown"` value covers the anomaly path where a TC has no preceding correlated AD (D2.3 edge case).
- `last_state_transition`: needed by consumers asking "how did we get here?" — references the most-recent state_transition event.
- `participants`: sorted-alphabetically agent_ids that emitted ≥1 utterance in the room; deterministic ordering for reproducibility.

**Derivation predicates** (per R0-A Y1 → α routing absorption — vocabulary types declared without algorithms is incomplete inscription per Principle 9). All predicates verified against `core/event.py` schemas at plan-revision time.

### 2.1 `open_hypotheses` predicate

A `HYPOTHESIS` event H is "open" iff **no subsequent event** E in chronological-strict order (`(E.timestamp, E.id)` ascending lex) satisfies ANY of:

- E.type == `DECISION` AND `H.id ∈ E.metadata.based_on` (DecisionMeta.based_on cites H — verified `DecisionMeta.based_on: list[EventId] = Field(min_length=1)` at `core/event.py:144`)
- E.type == `REJECTION` AND `E.metadata.rejects == H.id` (RejectionMeta.rejects cites H — verified `RejectionMeta.rejects: EventId` at `core/event.py:156`)
- E.type == `RETRACTION` AND `E.metadata.retracts == H.id` (RetractionMeta.retracts cites H — verified `RetractionMeta.retracts: EventId` at `core/event.py:167`)

**Note (any-vs-subsequent clarification, per impl-stage Y2 routing absorption)**: impl scans **all events** for the cite, not strictly events whose chronological order is after H. For valid event streams (cites never precede their cited target — DECISION can only base_on a HYPOTHESIS that already exists) this is equivalent to the "no subsequent" formulation. For anomaly cite-before-cited streams (out-of-order injection, test fixtures, migration replay), impl's "any-event-cites" semantic is preferred over "subsequent-only" because it gives **conservative closure** — if a cite exists anywhere in the stream, the hypothesis is considered closed. Plus: M-Y2 strict-propagation semantic means malformed metadata raises rather than silently degrading the close-walk, so this any-vs-subsequent looseness cannot mask correctness bugs.

**Why metadata-cite chains (not `parent_id`)**: routing-artifact sketch proposed walking via universal `parent_id` field; senior verification (per "senior decides verification path" clause) finds the typed-metadata cite fields are the load-bearing signal. `parent_id` is universal Event-level (any event can have a parent for general reply chains); the decision/rejection/retraction → hypothesis chain semantics are inscribed in the per-type typed metadata. Walking `parent_id` would include irrelevant reply chains; walking typed metadata captures the actual close-semantic.

Implementation note: walk events in chronological order; build hypothesis_id → closed-by-event-id map; H is open iff not in the map at snapshot_at time.

### 2.2 `closed_decisions` predicate

A `DECISION` event D appears in `closed_decisions` iff D.type == `DECISION` AND **no retraction event** R anywhere in the event list satisfies `R.metadata.retracts == D.id`.

**Note (any-vs-subsequent clarification, per impl-stage Y2 routing absorption)**: impl scans all events for the retracts-cite, not strictly events whose chronological order is after D. For valid streams (a retraction can only retract an already-emitted DECISION) this is equivalent to "no subsequent retraction." For anomaly streams with out-of-order events, "any-event-retracts" gives the same conservative-closure preference as D2.1. M-Y2 strict-propagation semantic on `RetractionMeta.model_validate` makes any malformed retraction surface as ValidationError rather than silently dropping the close-event.

**Note**: `DECISION_PIVOT` events are NOT included in `closed_decisions` — they're re-orientation moves, not closures (DECISION_PIVOT carries no metadata schema in `core/event.py:272-282` TYPED_METADATA dict; semantic is "we're changing direction" not "we decided X").

**Why subsequent-retraction predicate**: A decision is "closed" in the sense that it remains the standing decision unless explicitly retracted. Pivots don't retract — they layer on. Verification: `RetractionMeta.retracts: EventId` at `core/event.py:167` is the load-bearing field.

### 2.3 `tool_calls_pending_confirm` correlation algorithm

For each `TOOL_CALL` event TC in the snapshot's event list, the **correlating `AUTONOMY_DECISION` event** AD is identified as:

- AD.type == `AUTONOMY_DECISION`
- AD.author == TC.author (same agent)
- AD.metadata.operation_tool_id == TC.metadata.tool_name (same tool — verified `AutonomyDecisionMetadata.operation_tool_id: str` at `core/event.py:216`; `ToolCallMeta.tool_name: str` at `core/event.py:179`)
- AD precedes TC in chronological order (per ADR-013 D2 + `tool_dispatch.py:80-115` — autonomy_decision is emitted BEFORE tool_call via `emit_gate_decision` call in `process_tool_calls`)
- AD is the **most-recent** such AD with no intervening AD for the same `(author, tool_name)` pair

TC is in `tool_calls_pending_confirm` iff EITHER:
- its correlating AD has `AD.metadata.tier ∈ {countdown_confirm, hard_confirm}` (verified `AutonomyDecisionMetadata.tier: Literal["auto_execute", "countdown_confirm", "hard_confirm"]` at `core/event.py:219-223`), OR
- no correlating AD exists in the event list (anomaly path — see edge case below).

`AUTO_EXECUTE` tier means the tool call has been (or will be) executed; not pending — excluded.

**Edge case — TC without preceding AD (anomaly path, per impl-stage M-R1 routing absorption)**: per ADR-013 D2 emission ordering, `emit_gate_decision` appends `autonomy_decision` synchronously before `process_tool_calls` appends the corresponding `tool_call` event. Therefore every TC in a well-formed stream has a preceding correlated AD. If a TC exists **without** a preceding correlated AD, that is a data anomaly — caused by (a) a non-validated write path (debug fixture, migration replay), (b) a future P1.5+ async-reshape that weakens the ADR-013 D2 ordering guarantee, or (c) a producer bug. **Conservative-include semantic**: the snapshot includes such TC in `tool_calls_pending_confirm` with `autonomy_tier="unknown"` (per ToolCallRef.autonomy_tier Literal expansion in D2). Rationale: "no decision recorded = treat as awaiting confirmation" preserves the safer-default property of the autonomy gate (a missed TC in pending-confirm risks at-most a redundant confirm prompt; a missed pending-tier classification could allow silent execution downstream).

**Why a Literal value, not `None`**: `None` would collide with the well-formed "no pending TC" semantic elsewhere; an explicit `"unknown"` tier is a positive signal that the correlator could not bind a tier to this TC, surfacing the anomaly rather than masking it. Consumers reading `ToolCallRef.autonomy_tier == "unknown"` should treat as confirm-required AND log/alert for upstream investigation.

### 2.4 `participants` criterion

Agent IDs appearing in `event.author` of any event with `event.type ∈ {UTTERANCE, SUMMARY_SNAPSHOT, TOOL_CALL, AUTONOMY_DECISION, AUTONOMY_REFUSAL}` (i.e., any agent-authored event type; **excludes user + system authors**).

**Why this event-type set**:
- `UTTERANCE`: primary agent speech.
- `SUMMARY_SNAPSHOT`: Logger agent participation (P1.6-3 wires Logger as producer).
- `TOOL_CALL` + `AUTONOMY_DECISION` + `AUTONOMY_REFUSAL`: operator-style agents that engage the autonomy gate (P1.5.5 wired operator as producer).
- Excluded: `STATE_TRANSITION` (author == "system" per `rooms/runtime.py:93`); `USER_INPUT` (author == "user"); `HYPOTHESIS`/`DECISION`/`REJECTION`/`RETRACTION`/`OBSERVATION` (can be authored by user or agent; if agent-authored, the agent has likely also produced an UTTERANCE for the same content — counting via UTTERANCE alone avoids double-count).

Author filter: agent_ids extracted via the pattern `agent:[a-zA-Z0-9_-]+` (verified at `core/event.py:289` — `_AUTHOR_PATTERN = re.compile(r"^(user|system|agent:[a-zA-Z0-9_-]+)$")`). The `agent:` prefix is stripped before storing in `Snapshot.participants` list.

Deterministic ordering: ascending lexicographic by agent_id (post-prefix-strip).

### 2.5 `last_state_transition` definition

The `STATE_TRANSITION` event E maximizing `(E.timestamp, E.id)` ascending lex among all `STATE_TRANSITION` events in the snapshot's event list. `None` if no state_transition events exist in the snapshot (e.g., room never transitioned beyond initial state).

Lex tie-break is consistent with ADR-015 D4 (same `(timestamp, event_id)` ordering convention). Per `StateTransitionMeta` at `core/event.py:259`, the `new_state` + `prior_state` fields are read via typed access (not dict access) for the `StateTransitionRef` construction.

### 2.6 `decision_count` predicate

`decision_count = |{e ∈ events : e.type ∈ {DECISION, DECISION_PIVOT, REJECTION, RETRACTION}}|`.

I.e., the count of all decision-class events in the room — **not filtered by closure** (per D2.2 retraction filter), **not limited to literal DECISION events**. Decision-class includes pivots (re-orientation = decision-making act) + rejections + retractions (each is itself a decision).

**Why this set (not literal DECISION only)**: consumers asking "how decision-active is this room?" want the full decision-class signal, including reversals and re-orientations. Closure-aware count (`len(closed_decisions)`) is available separately via the `closed_decisions` field; `decision_count` complements as "decision-class events total."

**Why not weighted by closure**: decision_count is the room's decision-activity signal, not its decision-stability signal. A high count + low `len(closed_decisions)` means the room is decision-active but not yet stable (high retraction/pivot churn); both fields together expose the shape. Collapsing into a single closure-aware count would lose this orthogonal information.

**Verification path**: `core/event.py` `TYPED_METADATA` (lines 272-282) registers DecisionMeta + RejectionMeta + RetractionMeta; DECISION_PIVOT has no typed metadata schema (semantic is "we're changing direction" — no typed fields beyond event content). All 4 event types are present at the schema layer; the count semantic is over **event types**, not metadata correctness — so M-Y2 strict-propagation does not affect `decision_count` (no `model_validate` call needed for the count itself).

**Cross-references**: impl at `derived/snapshot.py:_DECISION_CLASS_TYPES` frozenset; consumer differentiation `decision_count` (total) vs `len(closed_decisions)` (stable) vs `len(open_hypotheses)` (in-flight) gives the room a three-axis decision-state shape.

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

### 6. Caller-frozen-time semantic (snapshot timestamp invariant under concurrent event append)

Per D1 clock-injection: `Snapshot.snapshot_at` is provided by the **caller** at the moment the caller decides to produce a snapshot. The caller (Logger's `produce_and_emit_snapshot` per ADR-013-D1-style sibling module, P1.6-3) calls `core.event.now_ms()` once and passes the result through to `produce_snapshot(events, room, snapshot_at=...)`.

The `events: list[Event]` argument is a pre-fetched snapshot (caller responsibility — typically `event_store.get_room_events(room.id)` BEFORE calling `produce_snapshot`); any events appended to the event_store AFTER the fetch are NOT in this snapshot. Re-running `produce_snapshot` on a later fetch produces a later snapshot.

**The read-vs-write ordering invariant** (caller-frozen time): snapshot semantic is "state at the caller-frozen time T as observed by the caller who fetched at T" — not "state at universal-time T." Concrete timeline at a snapshot dispatch:

1. Logger triggers on `state_change: snapshot_pending` (P1.6-3 dispatch wiring).
2. Caller `produce_and_emit_snapshot` calls `events = event_store.get_room_events(room.id)` — fetch boundary T₁.
3. Caller calls `snapshot_at = now_ms()` — wall-clock boundary T₂ (T₂ ≥ T₁, typically same ms).
4. Caller calls `snapshot = produce_snapshot(events, room, snapshot_at=snapshot_at)` — pure derivation; deterministic given fixed `(events, room, snapshot_at)`.
5. Caller appends `summary_snapshot` event with `metadata=SummarySnapshotMeta(snapshot.model_dump())`.

Any events appended to event_store between T₁ and step 5 are NOT in this snapshot's view. The next snapshot run (next room turn that triggers `produce_and_emit_snapshot`) reflects the appended events with a later `snapshot_at`.

**Test §2 concurrency pins the contract**: appending an event during `produce_snapshot` execution does NOT change the returned Snapshot (pure function over the input list); the next snapshot run reflects the appended event. Consumers requiring strict universal-time semantics use the `event_store`'s SQLite transaction model directly (P1.7+ scope if needed).

**Why caller-frozen time is sufficient for P1.6**: per ADR-011 D1 sequential per-room dispatch, there is no concurrent-write contention within a single room's turn. The caller-frozen-time semantic gives consumers a clear time-anchor without requiring distributed-clock guarantees. Future async-reshape (P1.5+ deferred per ADR-011 D1 "P1.5+ re-shapes signature for concurrent dispatch") would revisit via ADR-014 amendment. `event_count = len(events)` precision under async dispatch is queued as a named revisit item at the same async-reshape amendment hook (per M-Y5 routing).

### 7. Error semantic — derived module propagates; dispatch caller narrows + surfaces; ADR-011 D7-b preserved for event_store

Per impl-stage M-Y1 + M-Y2 routing absorption (`docs/process/reviews/P1.6/architect-routing-on-impl.md`), the snapshot subsystem has **three layered error responsibilities**, each with a precise contract:

**7.1 Derived module (`derived/snapshot.py`, `derived/decision_log.py`) — strict propagation.**

`produce_snapshot` and `produce_decision_log` propagate `pydantic.ValidationError` on malformed typed metadata. No internal `try / except` wrappers around `model_validate` calls. Rationale:

- `core/event.py` `_BaseMeta` discipline runs `validate_metadata` at event-store **append** time. A `ValidationError` raised during `model_validate` inside the derivation function therefore means either (a) a non-validated write path (debug SQLite, migration replay, test fixture bypassing append-time validation), or (b) a programming error (schema rename without metadata migration; new EventType with stale TYPED_METADATA dict). Both must surface, not silently warp the derivation result.
- Silent swallow has a documented lie-about-room-state risk: a malformed `DecisionMeta.based_on` would leave the cited hypotheses spuriously in `open_hypotheses`; a snapshot consumer would believe the room is still in-flight on a decided question.
- `except Exception` (overly broad) also masks AttributeError / KeyError from programming bugs. Strict propagation surfaces these immediately, at the function the bug touches.

Consumers requiring degraded-snapshot fallback (rather than turn-abort) catch `ValidationError` at the **caller boundary** (e.g., in `snapshot_dispatch.py` if a future requirement materializes). The derivation function does not embed that policy.

**7.2 Snapshot dispatch caller (`agents/dispatch.py:155-173` snapshot block) — narrow + surface.**

The snapshot dispatch block at the Logger trigger site:

- `except ValidationError` only (not `except Exception`) — catches the explicit `StateTransitionMeta.model_validate(current_event.metadata)` failure path on the gate condition.
- Non-`ValidationError` exceptions (e.g., `event_store.append` raising RuntimeError on storage failure) **propagate unwrapped** per ADR-011 D7-b semantics — these are persistence failures, not data-validation failures, and the turn aborts.
- On ValidationError, the failure surfaces via `TurnResult` (either a new `snapshot_failed: bool` field or by including the agent_id in `failed_agents` per existing dispatch convention; impl-time choice). Caller (room runtime) can decide retry / escalate / move on.

Rationale: room state machine has **exactly one** producer for `snapshot_pending → closed` (ADR-012 + this ADR D3). Silent failure = silent liveness violation (room stuck in snapshot_pending). Either path — caller retries, or operator surfaces the failure — needs visibility, not a warn-log buried in dispatch internals.

**7.3 `event_store.append` — ADR-011 D7-b semantics preserved.**

`event_store.append` failures during snapshot dispatch (raised inside `produce_and_emit_snapshot` via the embedded append) propagate unwrapped per ADR-011 D7-b. The dispatch-caller wrapper (7.2) deliberately narrows to `ValidationError` precisely so it does NOT swallow `event_store.append` failures.

**Cross-reference summary**:

| Layer | Catches | Action |
|---|---|---|
| Derivation (`produce_snapshot`, `produce_decision_log`) | Nothing internally | Propagate ValidationError up |
| Snapshot dispatch caller (`dispatch.py` snapshot block) | `ValidationError` only on `StateTransitionMeta.model_validate` gate | Log + surface via TurnResult |
| `event_store.append` failures inside snapshot dispatch | Not caught (passes through 7.2's narrow filter) | Propagate per ADR-011 D7-b |
| Other `ValidationError` inside `produce_and_emit_snapshot` (e.g., `produce_snapshot` raising on malformed `DecisionMeta`) | NOT caught by 7.2 (7.2 wraps only the gate `StateTransitionMeta.model_validate`) | Propagate; turn aborts; room runtime visibility |

The 7.2 narrow catch is **specifically** the gate-check failure (current_event has malformed `StateTransitionMeta`). Other ValidationErrors arising during derivation are NOT inside 7.2's `try` block — they propagate per 7.1 (strict).

**Test invariants (per M-Y4 routing, pinned in `tests/derived/` + `tests/agents/test_dispatch.py`)**:

- DECISION with malformed `based_on` → `produce_snapshot` raises ValidationError.
- RETRACTION with malformed `retracts` → `produce_snapshot` raises ValidationError.
- STATE_TRANSITION with malformed `new_state` → `produce_snapshot` raises ValidationError (via D2.5 path).
- REJECTION with malformed `rejects` → `produce_decision_log` raises ValidationError.
- Snapshot dispatch caller: state_transition event with malformed metadata → TurnResult surfaces failure (not silent).
- Snapshot dispatch caller: simulated `event_store.append` RuntimeError → propagates (NOT swallowed by 7.2).

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
- Per D7 strict propagation: any non-validated write path (debug fixture, migration replay) that inserts malformed typed metadata becomes immediately visible at snapshot dispatch (the room turn aborts with ValidationError). Operators must repair upstream rather than silently observe a degraded snapshot.

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
| D6 (snapshot timestamp invariant under concurrent append) | **Low.** Read-vs-write semantic; if stricter universal-time needed, callers use event_store transactions directly. Doesn't constrain producer; constrains consumer expectation. `event_count` precision under async dispatch revisits at the same amendment hook (M-Y5 queued). |
| D2.6 (`decision_count` as union of decision-class event types) | **Low.** Field semantic is an event-type filter — adding/removing types from the union is an ADR amendment + 1-line `_DECISION_CLASS_TYPES` frozenset update. No persisted-data migration (snapshots compute the count fresh on derivation). |
| D7 (layered error semantic — strict in derivation, narrow + surface in dispatch caller) | **Medium.** Reverting to swallow-and-continue requires re-introducing `try/except` wrappers in derivation + a TurnResult shape change. Cost is proportional to the test suite that pins the strict-propagation semantic (M-Y4 tests). The decision was prompted by a documented lying-snapshot risk (R0-A senior Y2); reversal needs an equally concrete counter-argument. |

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
- `docs/process/senior-plans/P1.6.md` — plan that locks atomic-task breakdown; §4 amended in same routing cycle to add error-semantic forcing-function for new module surfaces.
- `docs/process/reviews/P1.6/architect-routing-on-impl.md` — impl-stage routing that drove the 2026-05-28 amendment (D2.3 `"unknown"`, D2.1/D2.2 clarification, D2.6, D7).
- `docs/process/reviews/P1.6/plan-vs-impl.md` — senior R0-A surface (Y1 + Y2 routed to M-Y1 + M-Y2 via the impl-stage routing).
- `docs/process/reviews/P1.6/R0-A.md` — architect-partner R0-A surface (Y2 routed to D2.6 amendment).
- `docs/process/reviews/P1.6/R0-B-cross-family.md` — proxy R0-B surface (R1 routed to D2.3 `"unknown"` expansion).
- Implementation lands on `claude/P1.6-impl` post-Accept; cycle-2 lands after senior revision (this commit) per architect-routing-on-impl §"Senior revision actions".
