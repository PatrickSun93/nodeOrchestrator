# Event Model

## Why this exists

Events are the system's **single source of truth**. The event log is
append-only and never modified. Every higher-level abstraction — snapshots,
decision logs, cross-room memory, room state, agent context — is **derived**
from the event log. If the event log is correct, the system is recoverable.
If the event log is wrong, every derivation is wrong.

This makes event design constitutional. Adding a type, changing a metadata
field, or relaxing append-only requires an ADR.

## Why the `type` field is constitutional

This is the most load-bearing field in the schema. Four arguments for why
it deserves protection.

### 1. Flat messages violate Principle 9 (term audit / naming the trap)

The earliest design treated everything as `Message(content: str)`. The first
question that broke this design: "is this a hypothesis or a decision?"
Without a type, downstream code can't tell. So you either:

- Ask the LLM to classify (violates Principle 11 — drift without ground truth).
- Pattern-match on content (violates Principle 9 — implicit semantics
  hidden in prose).
- Add a structured field — i.e., readmit `type`.

The 17 types are the result of refusing to lump distinct semantic operations
into "message". They are the system's working vocabulary. Code routes on
type without inferring intent. LLMs are not in the routing path.

Each type also carries a different downstream contract:

- `decision` automatically appears in the decision log and is eligible for
  the `based_on` relation.
- `rejection` and `retraction` must cite the event they reject or retract.
- `escalation` is a first-class "I need the user to choose" signal
  (Principle 5).
- `tool_call` and `tool_result` are paired by `call_id` for replay and
  audit.
- `autonomy_decision` is emitted synchronously before tool execution
  and carries the full `DecisionTrace` of the gate evaluation. Its
  metadata field set is locked to `DecisionTrace` (in
  `orchestrator.autonomy.scoring`) by the constitutional test
  `test_constitution_autonomy_decision_event_carries_trace` — the
  duplication is deliberate so `orchestrator.core` does not import
  from `orchestrator.autonomy`. See ADR-005 Decision 6.

If you can't tell which contract applies, you can't write the routing code.
The type field is what makes the routing code possible.

### 2. The `type` field is append-only at the field level, not just the row level

You cannot turn a `hypothesis` into a `decision` after the fact. The
schema-level `events_no_update` TRIGGER blocks any UPDATE statement,
which forecloses field-level mutation as well as row-level. This matters
because the type defines what the event *was at the moment it happened*.
Rewriting history to call something a "decision" that wasn't decided at
the time is exactly the calibration drift Principle 11 warns about.

To "promote" a hypothesis to a decision, append a new `decision` event
that cites the hypothesis via `based_on`. The hypothesis remains intact.
Both events are visible. The decision log shows the provenance, not a
revised history.

### 3. Refuse the "generic_message fallback"

Sooner or later, someone will propose:

> "Let's add a `generic_message` (or `note`, or `info`) type for things
> that don't fit cleanly. It's just a pressure valve."

**This proposal must be rejected.** Reasons:

- A pressure valve is exactly what defeats the type system. Once a
  catch-all exists, the path of least resistance routes through it. The
  17 meaningful types decay into trivia within a few quarters.
- If you find yourself wanting "generic", you have an unmet design need
  that deserves a *new specific type*, not a fallback. Add an ADR. Name
  the operation. Define the metadata it should carry.
- The cost of a new type is small (one ADR, one entry in the `EventType`
  enum, optionally a metadata schema). The cost of a generic fallback
  is the entire event-type system over time.
- "But it's only for one edge case" is the same argument every time. The
  edge cases compound; the type doesn't.

The same argument applies to widening an existing type to "swallow"
something it wasn't designed for. If you find yourself adding a vague
optional field to `utterance` to handle some new flow, ask whether the
new flow is actually a new type.

### 4. Naming-the-trap reflex when adding a new type

If you do add a new type, audit the name before committing.

**Bad names** that should not appear in `EventType`: `info`, `data`,
`thing`, `note`, `message`, `event`, `update`, `change`. These are
placeholder words pretending to be names. They don't constrain code or
readers, so they don't earn their place in the type system.

**Good names** are specific verbs (for processes) or specific nouns (for
things): `term_definition`, `decision_pivot`, `state_transition`,
`escalation`, `tool_failed`. A reader who sees one of these knows
roughly what the event records and roughly what shape the metadata has.

If you can't think of a specific name, the type might not exist yet.
Defer adding it until the use case is concrete.

## The 17 types

| Type | Meaning | Strict metadata schema? |
|---|---|---|
| `user_input` | Raw input from the user | open |
| `utterance` | Plain agent or system speech | open |
| `hypothesis` | A claim under consideration, with confidence | yes |
| `decision` | A commitment to a path, citing what it's based on | yes |
| `rejection` | An explicit "no" against another event | yes |
| `retraction` | Withdrawal of a prior decision | yes |
| `observation` | A factual datum (often from a tool result) | open |
| `tool_call` | An agent calling a tool | yes |
| `tool_result` | The successful return of a tool | yes |
| `tool_failed` | A tool call that errored | open |
| `escalation` | Question kicked back to the user | open |
| `summary_snapshot` | Structured snapshot of room state | open |
| `state_transition` | Room state machine moved | open |
| `milestone` | Marked-as-significant moment | open |
| `term_definition` | A term being explicitly defined for this room | open |
| `decision_pivot` | Reframe — "we were asking the wrong question" | open |
| `autonomy_decision` | Gate decision before a tool call: tier, score, full trace | yes |

"Strict" types validate via Pydantic at append time. "Open" types accept
`dict[str, Any]` for now and will be tightened (with an ADR) when their
shape is reliably needed by code.

## Append-only enforcement (three layers)

1. **Schema (SQLite TRIGGERs).** `events_no_update` and `events_no_delete`
   raise `events are append-only` on any non-INSERT statement, including
   field-level UPDATE. This protects against direct SQL bypassing the API.
   Triggers are installed via DROP + CREATE in `init_schema()` (not
   `IF NOT EXISTS`) so future trigger-body changes always propagate;
   `IF NOT EXISTS` would silently leave an old trigger in place.
2. **Application (`Event.model_config.frozen = True`).** Pydantic blocks
   attribute reassignment on `Event` instances. This catches accidental
   mutation in code paths that have an `Event` in hand.
3. **Public API.** `EventStore` exposes `append`, `append_room`,
   `get_event`, `get_thread`, `get_room_events`, `get_room`,
   `get_relations_*`, `recompute_relations*`. There is no `update` or
   `delete`. This catches well-intentioned PRs that propose mutation as
   a "small fix".

This is overlapping defense by design. If any one layer is bypassed, the
next catches it. The constitutional test
`test_constitution_append_only_at_schema_level` exercises layer 1
directly via raw SQL.

The `events` table is the only fully append-only table. The `rooms`
table is append-only by convention but not by trigger — room state
changes flow through `state_transition` events instead of mutating the
rooms row. The `relations` table is explicitly NOT append-only; it is a
cache (see below).

## Relations table — a cache, not a source of truth

The `relations` table stores edges between events: `rejects`, `retracts`,
`based_on`, `replies_to`. It is **not** append-only. It is a derived
index of relationships extracted from events, by a pure function:

```python
def extract_structural_relations(event: Event) -> list[Relation]: ...
```

The same function is called on the write path (when an event is appended)
and on the recompute path (`recompute_relations(event_id)` and
`recompute_all_relations()`). The function is total: same input, same
output, every time, no I/O, no clock dependency.

`Relation.extracted_at` is set to `event.timestamp` (the source event's
time, not wall-clock at extraction). This makes the cache stable across
rebuilds: re-extracting later still produces edges with the same
`extracted_at`, so "latest by extracted_at" queries (e.g., "most recent
event to retract X") return consistent results regardless of when the
cache was last recomputed.

Why a cache:

- Querying "what events reject X?" is a single index seek instead of a
  table scan parsing JSON metadata.
- If extraction logic was wrong, fix the function and rebuild the cache.
  The events are unchanged; only the index gets fixed. This is
  invalidation by truncation.

P0 covers four structural relations. Semantic relations (`supersedes`,
`derives_from`, `related_to`) require LLM suggestion + explicit human
confirmation; they are out of P0 scope.

## Cycles

`parent_id` cycles are physically impossible. To create one, you would
have to UPDATE an event's `parent_id` after insertion to point forward
in time — the append-only TRIGGER blocks this.

Semantic relations point backwards in time by construction (you can't
retract an event that doesn't exist yet). Self-loops in metadata are
guarded by Pydantic validators on the metadata schemas.

`get_thread`'s recursive CTE defends with a `path_seen` column that
rejects any parent already encountered in the chain. If the schema-level
guarantees are somehow bypassed and a cycle ends up in the DB, the
recursion stops at the cycle entry and returns the partial path so far.
Defensive programming is cheap; the alternative (infinite loop in
production) is not.

## Author format

`Event.author` is a structured string with a fixed grammar:

- `user` — the human user.
- `agent:<id>` — a specific agent (e.g., `agent:operator`,
  `agent:skeptic`). `<id>` is `[a-zA-Z0-9_-]+`.
- `system` — system-generated events (state transitions, snapshots,
  background bookkeeping).

Application-layer validators reject any other form. We considered
SQLite-level CHECK constraints; pure-SQL parsing was awkward enough that
application-layer validation won. The format exists because future code
(should-agent-speak gating, UI rendering, decision-trace attribution)
needs to discriminate speakers without parsing prose.

## Read-API empty vs unknown

Different read APIs treat "the id you asked for doesn't exist" differently,
based on whether an empty result is a meaningful state for that query:

- `get_event(unknown_id)` — returns `None`. Asking "is this event there?"
  has a legitimate "no" answer.
- `get_room(unknown_id)` — returns `None`. Same.
- `get_room_events(unknown_room_id)` — returns `[]`. A freshly created
  room has no events; an unknown room is indistinguishable from a known
  empty room only because both yield zero events. This conflation is OK
  here because the empty case is genuinely common and useful.
- `get_thread(unknown_event_id)` — **raises `EventNotFoundError`**.
  Returning `[]` would be a violation of Principle 4 (structured
  uncertainty): every event is at least the root of its own thread, so
  "thread is empty" is impossible — the empty value would be a hidden
  flag for "id is unknown", which is exactly the prose-hedging shape we
  reject. A different signal for a different state.
- `recompute_relations(unknown_event_id)` — raises
  `EventNotFoundError`, same reasoning.

## Parent validation (write-time, three failure modes)

`append()` validates `parent_id` at write time, not at read time. Catching
corruption / typos / cross-context bugs at the moment of insertion
prevents orphans from accumulating in the log.

There is one exception class for all three modes:

```python
class InvalidParentError(ValueError):
    reason: Literal["not_found", "cross_room", "self_parent"]
```

Callers that want to react differently per mode discriminate on
`.reason`, not on `str(e)`. The `Literal[...]` lets type checkers flag
missing cases in a `match` statement.

| `reason` | Trigger |
|---|---|
| `not_found` | `parent_id` does not reference an existing event |
| `cross_room` | parent exists, but in a different room |
| `self_parent` | `parent_id == event.id` (typical sign of an id-reuse bug) |

`RoomNotFoundError` is a separate class — `room_id` has only the one
failure mode (the room doesn't exist), so a `reason` discriminator
would be theatre.

## Edge cases (specified, tested)

- **`parent_id` references a non-existent event.** `append()` raises
  `InvalidParentError(reason="not_found")`. SQLite's FK enforcement
  also catches this at the DB layer; our error type is more specific.
- **`parent_id` exists but is in a different room.** `append()` raises
  `InvalidParentError(reason="cross_room")`. Threads are within-room
  conversations by design.
- **`parent_id` equals `event.id` (self-parent).** `append()` raises
  `InvalidParentError(reason="self_parent")`.
- **`room_id` references a non-existent room.** `append()` raises
  `RoomNotFoundError`.
- **Re-retraction.** A `retraction` whose target is itself a `retraction`
  is allowed. Both `retracts` edges live in the relations table.
- **Multiple events retracting the same target.** Allowed. Each edge has
  a different `event_id`. The PRIMARY KEY on
  `(event_id, relation_type, target_event_id)` accepts both. Queries
  ordered by `extracted_at DESC` return the latest retraction first.
- **Cycle in semantic relations across event types.** `get_thread`'s CTE
  uses path-tracking (visited-set encoded in a delimited string column)
  to terminate at the cycle entry.
- **`events_no_update` / `events_no_delete` TRIGGER fires.** SQLite
  raises `IntegrityError` with message `events are append-only`. The
  constitutional test in `tests/core/test_constitution.py` exercises
  these directly via raw SQL to verify the schema-level guarantee.
