# ADR-001: Event Store Foundation

**Status:** Accepted — 2026-05-08
**Scope:** P0 event log, room storage, structural relations cache,
related read APIs, and the project-wide working patterns established
during this PR.

## Context

The Orchestrator project (see `handoff.md` §1, `chat-history.md` §1)
needs a single source of truth for everything that happens in the
system: user inputs, agent utterances, tool calls and results,
hypotheses, decisions, rejections, retractions, escalations, and so on.
Every higher-level abstraction in the design — snapshots, decision
logs, cross-room memory, room state, agent context windows, the
analytics on which future "honest interlocutor" features rest — must
be derivable from this log. If the log is correct, the system is
recoverable. If the log is wrong, every derivation is wrong.

Three project principles bear directly on the foundation's shape:

- **Principle 9 (term audit / naming the trap)** — flat `message`
  hides semantic structure that downstream code needs.
- **Principle 11 (no ground truth → drift)** — anything mutable drifts;
  LLM-judgment without ground truth is the failure mode this project
  is most worried about.
- **§3.1 (decision-path codification)** — routing/gating/scoring/
  selection lives in code, not LLM judgment. This ADR is the first
  large-scale enforcement of that principle.

The foundation must support: thread reconstruction (root → leaf),
graph queries (`rejects`, `retracts`, `based_on`, `replies_to`),
bug-fixable derivations (extraction logic can change), audit-friendly
read paths, and overlapping-defense append-only.

## Decisions

### 1. Sixteen typed events; no `generic_message` fallback

The system's constitutional vocabulary is fixed at 16 event types:
`user_input`, `utterance`, `hypothesis`, `decision`, `rejection`,
`retraction`, `observation`, `tool_call`, `tool_result`, `tool_failed`,
`escalation`, `summary_snapshot`, `state_transition`, `milestone`,
`term_definition`, `decision_pivot`.

Adding a type requires an ADR. A `generic_message` (or `note`, `info`,
`thing`) catch-all is explicitly forbidden — pressure-valve types route
everything through them and the meaningful types decay into trivia
within quarters. See `event-model.md` §"Why the type field is
constitutional" for the full argument.

### 2. Append-only, enforced at three layers

Implemented in three independent layers:

1. **Schema (SQLite TRIGGERs)** — `events_no_update` and
   `events_no_delete` raise `events are append-only` on any non-INSERT
   statement, including field-level UPDATE. Catches raw-SQL bypass.
2. **Application (Pydantic)** — `Event.model_config = {"frozen": True,
   "extra": "forbid"}`. Catches accidental in-process mutation.
3. **Public API** — `EventStore` exposes no `update` or `delete`.
   Catches well-intentioned PRs that propose mutation as a small fix.

Overlapping defense is the design intent. If any one layer is
bypassed, the next catches it.

The schema layer alone is the most load-bearing: a future contributor
opening a console and "just fixing one row" hits `IntegrityError`,
not silent corruption. The constitutional test
`tests/core/test_constitution.py::test_constitution_append_only_at_schema_level`
exercises this directly.

The `events` table is the only fully append-only table. The `rooms`
table is append-only by convention (no API exposes mutation), not by
trigger — room state changes flow through `state_transition` events,
which keeps the door open for adding room metadata fields without
breaking writes. The `relations` table is explicitly NOT append-only;
it is a derived cache (decision 5).

#### Trigger refresh semantics

Tables and indexes use `IF NOT EXISTS` (data preservation across
re-init). Triggers use `DROP IF EXISTS` + `CREATE` so that
`init_schema()` always installs the trigger body currently in
`SCHEMA`. `CREATE TRIGGER IF NOT EXISTS` would silently leave OLD
triggers in place after future logic edits — a multi-month silent
bug; caught during interface review and now a project-wide pattern
(saved to `feedback_schema_enforcement` memory).

### 3. Per-type metadata: progressive strictness

Six event types have strict Pydantic schemas
(`extra="forbid", frozen=True`):

- `hypothesis` (`confidence: float ∈ [0,1]`, `based_on: list[EventId]`)
- `decision` (`based_on: list[EventId]` non-empty, `trade_offs: dict`)
- `rejection` (`rejects: EventId`, `reason: str` non-empty)
- `retraction` (`retracts: EventId`, `reason: str` non-empty)
- `tool_call` (`tool_name`, `call_id`, `params`)
- `tool_result` (`call_id`, `success`, `output_truncated_at`,
  `error_class`)

The other ten types pass through as `dict[str, Any]` until a use case
justifies tightening (with a follow-up ADR per the rule in
`event-model.md`).

**Considered:**
- *All 16 typed upfront.* Defines schemas for code that won't touch
  them in P0/P1; high churn risk as the use cases reveal themselves.
- *All open dict.* Abandons the per-type contract that the type system
  exists to provide.

The progressive route bets that schemas added when used will be more
correct than schemas guessed in advance.

`validate_metadata(event_type, metadata)` is the dispatcher:
typed types parse via Pydantic and return the normalized dict
(defaults filled in); open types pass through unchanged. Called at
write time in `EventStore.append()`. Lives in `event.py` (a parser, not
a routing decision — safe to keep alongside the data definitions).

### 4. Event ID format: `evt_<uuid4-hex>`

Stripe-style typed prefix + uuid4 hex. Rooms are `room_<uuid4-hex>`.

**Considered:**
- *Raw uuid4.* No entity-type signal in logs; debugging cost adds up.
- *uuid7.* Chronologically sortable, but Python 3.12 stdlib lacks it
  (added in 3.13); requires a third-party package, and the `timestamp`
  column already provides chronological order with explicit semantics.
- *ULID.* Same trade-off as uuid7.

The format is opaque to external API by convention; if uuid7 becomes
important later (e.g., for distributed cluster ordering), the format
can change without affecting callers, since ids are always treated as
opaque strings.

### 5. Relations table is a cache, not a source of truth

The `relations` table stores edges — `rejects`, `retracts`, `based_on`,
`replies_to` — extracted from events by a pure function:

```python
extract_structural_relations(event: Event) -> list[Relation]
```

The same function runs on the write path (`EventStore.append`) and the
recompute path (`recompute_relations(event_id)`,
`recompute_all_relations()`). Same input, same output, no I/O, no
clock dependency.

The table is **not** append-only. If the extraction function had a
bug, fix the function and call `recompute_all_relations()` — the
events are unchanged, only the index gets fixed. This is invalidation
by truncation.

`Relation.extracted_at = event.timestamp` (NOT wall-clock at extraction
time). This makes the cache stable across rebuilds: `extracted_at DESC`
queries (e.g., "latest event to retract X") return consistent results
regardless of when the cache was last recomputed.

### 6. `InvalidParentError` with `reason` discriminator

Single exception class, three failure modes via a `Literal`:

```python
class InvalidParentError(ValueError):
    reason: Literal["not_found", "cross_room", "self_parent"]
```

**Considered:** separate exception classes (`ParentNotFoundError`,
`CrossRoomParentError`, `SelfParentError`).

**Chose discriminated single class** because:
- Callers that want different behavior per mode discriminate on
  `.reason`, not by parsing `str(e)` (one of the worst Python
  anti-patterns).
- `match exc.reason: case ...` lets mypy flag missing cases at build
  time.
- Adding a new failure mode (e.g., `"wrong_user"` if multi-user
  arrives) is one literal value, not a new class plus inheritance
  bookkeeping.

`RoomNotFoundError` stays a separate class — only one failure mode, so
a discriminator would be theatre.

### 7. Read-API empty-vs-unknown semantics

Different read APIs treat "the id you asked for doesn't exist"
differently, based on whether the empty case has a meaningful state:

| Method | Unknown id | Reason |
|---|---|---|
| `get_event(id)` | returns `None` | "Is it there?" has a legitimate "no". |
| `get_room(id)` | returns `None` | Same. |
| `get_room_events(room_id)` | returns `[]` | A freshly created room is empty; `[]` is normal. |
| `get_thread(event_id)` | raises `EventNotFoundError` | Every event is at least the root of its own thread, so empty is impossible. `[]` would be a hidden flag for "id is unknown" — exactly the prose-hedging shape Principle 4 rejects. |
| `recompute_relations(event_id)` | raises `EventNotFoundError` | Same. |

This was caught during interface review and overturned an earlier
"return `[]` for `get_thread(unknown)`" decision; the ADR is now the
documented anchor for the decision.

### 8. Retraction is structural child of decision, not sibling

When appending a retraction event, `parent_id` points to the decision
being retracted. The retraction is a child, not a sibling.

**Considered:** retraction's `parent_id` set to the decision's parent
(hypothesis), making retraction a fork-sibling of decision —
representing "alternative path at the decision point."

**Decided against** because `get_thread(retraction)` reconstructs the
conversational context the retraction lives in. You cannot retract a
decision without that decision being part of the context — a thread
that doesn't include the retracted event is incoherent. So the natural
shape is `parent_id = decision_id`, and the thread reads as "decision
happened, then was retracted."

The fork-at-decision-point semantic is the responsibility of
`decision_pivot`, a separate event type that means "we were asking the
wrong question; change direction." Retraction means "we no longer
stand by that"; pivot means "different path entirely." Two distinct
types, two distinct uses. Conflating them at the structural level
would defeat both.

The standard fixture demonstrates fork via `rejection` (skeptic
dissents) and `retraction` (user withdraws) as siblings under
`decision`, showing multi-child branching without misshaping
retraction.

### 9. `get_thread` is a single recursive CTE

Naive Python: walk `parent_id` upward with one `SELECT` per ancestor —
N+1 queries, linear in depth, fine for shallow threads, pathological
deep.

**Chose** SQLite recursive CTE in a single query. Sub-millisecond at
depth 100 in tests; the perf baseline test
`test_perf_baseline_get_thread_depth_100` enforces a 50ms ceiling
specifically to catch a regression to the N+1 shape.

The CTE includes a `path_seen` column (delimited string of visited
ids) so the recursion terminates if a cycle is somehow present.
Cycles in `parent_id` should be impossible given append-only at the
schema level (you cannot mutate `parent_id` post-insertion), but
defense in depth is cheap.

### 10. Index covers `ORDER BY` end-to-end

`idx_events_room_ts_id` is on `(room_id, timestamp, id)`, covering
`WHERE room_id = ? ORDER BY timestamp ASC, id ASC` without a separate
sort step. The trailing `id` is the deterministic tiebreaker for
events at the same millisecond. (Caught during interface review;
the original index was `(room_id, timestamp)` and would have required
a sort phase.)

### 11. Author format

`Event.author` is `user | agent:<id> | system` where `<id>` is
`[a-zA-Z0-9_-]+`. Application-layer regex validation; SQLite-level
CHECK was considered but rejected (pure-SQL parsing is awkward and
the regex is more readable in Python).

The format exists because future code (should-agent-speak gating,
UI rendering, decision-trace attribution) needs to discriminate
speakers without parsing prose.

## Process decisions established by this PR

These are project-wide patterns set by the work, not specific to the
event store. Future modules and PRs should follow them.

### Interface freeze before implementation

For non-trivial new modules, deliver the **interface** as a standalone
commit before implementation:

- Pydantic models and dataclasses, fully defined.
- Public function/method signatures with full docstrings stating
  contracts (raises, returns, side effects, ordering).
- Custom exception classes defined.
- Schema/SQL constants if applicable.
- Method bodies stubbed with `raise NotImplementedError`.
- Trivial utilities (id generators, regex predicates) MAY be
  implemented — they have no judgment.

Pause for review BEFORE writing implementation or tests.

**Why this is now a pattern:** The interface review on this PR caught
- `InvalidParentError` should carry a `reason: Literal[...]` instead
  of a `ParentNotFoundError`/`CrossRoomParentError` split,
- `get_thread(unknown_id)` should raise `EventNotFoundError`, not
  return `[]`,
- triggers should be DROP+CREATE, not `IF NOT EXISTS`,
- the events index should include `id` for ORDER BY coverage.

All four would have been more expensive to fix post-implementation
(rewriting tests, migrating callers) than during interface review.

Saved to memory as `feedback_interface_freeze`.

### PR template (mandatory two questions)

Every PR description must answer:

1. **Does this PR contain LLM calls?** If yes, for each call, explain
   why this decision could not be done in code.
2. **Do all decision functions return a `decision_trace`?**

The template is in `docs/contributing.md`. Reviewers must check each
LLM call site explicitly. The first question is the working enforcement
of §3.1 (decision-path codification); the second forces audit-friendly
return shapes for routing/gating/scoring code.

## Consequences

**Easier:**
- Audit and replay: every system state is reconstructable from the
  event log; no derived state can lie about its provenance.
- Bug-fixable derivations: extraction functions can change, and a
  single `recompute_all_relations()` call rebuilds the cache from
  truth.
- Confidence in append-only: three independent layers; raw-SQL bypass
  is contained at the deepest layer.
- Type-safe code paths: mypy-strict + Pydantic catches metadata
  violations and parent_id misuse at build time.
- Future schema evolution: tables `IF NOT EXISTS` preserves data;
  triggers DROP+CREATE auto-refreshes logic. New trigger logic in a
  future PR doesn't require a manual migration step.

**Harder:**
- Schema migrations that legitimately need to UPDATE old events would
  require a documented "migration mode" toggle that disables triggers,
  runs the migration, and re-enables. Deferred to P2 (added to known
  unresolved questions in `handoff.md` §13).
- Adding a new event type now requires an ADR (intended friction —
  prevents the `generic_message` slide).
- For the 10 untyped event types, consumers handle `dict[str, Any]`
  carefully — first reader to want a strict shape writes the schema
  with an ADR.
- Two-step writes (events + relations cache) require care across
  transaction boundaries; covered by the integrated `with self.conn:`
  block in `append`.

**Neutral:**
- 100 tests run in ~0.4s on the verified toolchain. Adding tests is
  cheap; the cost will scale with test count, not infrastructure.

## Reversibility

| Decision | 6-month reversal cost |
|---|---|
| 16 event types | Adding: cheap (one enum value, one optional schema, ADR). Removing/renaming: expensive (data migration). |
| Append-only at 3 layers | Removing a layer: trivially reversible. Removing append-only entirely: catastrophic — derivations become unreliable. Don't. |
| Progressive metadata schemas | Tightening an open type: cheap (write schema, ADR, run validation pass). Loosening a typed type: cheap. |
| `evt_` prefix + uuid4 | Switching to uuid7 internally: cheap (callers treat ids as opaque). Changing the format publicly: breaks any external system using ids as keys. |
| Relations as cache | Trivial — drop the table, change extraction logic, rebuild. Events unchanged. |
| `InvalidParentError` discriminator | Splitting into multiple classes: small refactor (~4 catch sites). Reverse: same. |
| `get_thread` raises on unknown | Switching to `[]`: trivial code change but reverses the structured-uncertainty stance — would need an ADR-NNN to overrule. |
| Retraction-as-child | Switching to sibling: requires event-tree reshape across stored data; expensive. |
| Recursive CTE for thread | Replacing with N+1: regression test catches it. Replacing with a different graph algorithm: cheap. |
| Index `(room_id, timestamp, id)` | Cheap — DROP and CREATE the new index in one PR. |
| Interface-freeze process | Trivially reversible (it's a pattern, not code). |
| PR template | Trivially reversible (edit `docs/contributing.md`). |

## References

- `handoff.md` §1 (project vision), §2 (12 design principles),
  §3.1 (decision-path codification), §4 (data model)
- `chat-history.md` §5 (event types and threading), §7 (autonomy
  scoring foundations), §8 (decision-path codification rationale)
- `docs/architecture/event-model.md` — full event model design
- `docs/contributing.md` — PR template and ADR format
- This PR: 14 source files, 100 tests, mypy-strict + ruff clean.
  Toolchain verified: uv 0.11.11, Python 3.14.4 (selected from
  `requires-python = ">=3.12"`), pytest 9.0.3.
