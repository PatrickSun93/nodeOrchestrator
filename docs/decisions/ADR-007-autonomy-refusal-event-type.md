# ADR-007: `autonomy_refusal` Event Type

**Status:** Proposed — 2026-05-20
**Scope:** Governs the new `EventType.AUTONOMY_REFUSAL` and its
`AutonomyRefusalMetadata` schema — the audit-event written by the
autonomy emission layer when `gate()` raises rather than returns.
Also records the **first** layering rule from `orchestrator.autonomy`
to `orchestrator.core` (autonomy.emission imports core.event_store).
Out of scope: P1.3 Hard Guards refusal logic (will reuse this event
with new `refusal_reason` values via ADR amendment); the emission
module's implementation details (C4-5); the autonomy decision event
itself (ADR-005 Decision 6).

## Context

ADR-005 Decision 6 established `autonomy_decision` events emitted
*synchronously before tool execution proceeds*, on the normal path
where `gate()` returns an `AutonomyScore`. ADR-006 Decision 3 then
settled that `gate()` propagates `UnknownToolError` unwrapped on the
registry-miss path — explicitly leaving "what event records the
refusal" to a follow-up. That follow-up is this ADR.

The gap: with no event for the refusal path, the audit trail
distinguishes "tool call evaluated and tier assigned" from "tool
call never evaluated because the tool was unknown" only by *absence*
of an `autonomy_decision` row. Absence-as-signal violates Principle
4 (structured uncertainty — no record looks identical to no
attempt) and contradicts ADR-005 §6's invariant that *every gate
evaluation* produces an audit event. P1.3 Hard Guards will
introduce more refusal classes (destructive overreach, cost ceiling,
external-visibility veto). Each of those needs the same auditable
shape; designing for one class today without anticipating reuse
would either force a new EventType per class (vocabulary bloat) or
force `AutonomyDecisionMetadata` to grow optional fields (schema
smell + breaks the existing constitutional sync test).

The decision must support:

- Synchronous emission before raising upward — mirroring ADR-005 §6.
- Extensible discriminator so P1.3 Hard Guards reasons add via
  Literal extension, not new EventType.
- Field set deliberately lighter than `AutonomyDecisionMetadata`
  (12 fields) — refusal has no decision trace to mirror.
- Explicit layering rule for the first cross-package import in
  `orchestrator.autonomy → orchestrator.core` direction.

## Decisions

### 1. Event type name: `autonomy_refusal`

The new `EventType` enum value is `AUTONOMY_REFUSAL` with string
value `"autonomy_refusal"`. The name is deliberately general so
P1.3 Hard Guards can write the same event type with different
`refusal_reason` values without needing yet another EventType for
each refusal class.

A more specific alternative (`unknown_tool_attempted`) would force
new EventTypes for every future refusal kind — `destructive_refused`,
`cost_ceiling_refused`, etc. — multiplying the type vocabulary along
an axis that is not categorically different (all are "the gate
refused"; the *reason* varies). Principle 9 (terminology audit) cuts
in favor of "kind of event" being one concept and "specific reason
within kind" being a discriminator field. ADR-001's "adding a type
requires an ADR" rule also makes EventType inflation deliberately
costly; an extensible discriminator is the cheaper, equally
queryable substitute (`SELECT … WHERE refusal_reason = …`).

### 2. Metadata field set — four fields

```python
class AutonomyRefusalMetadata(_BaseMeta):
    operation_tool_id: str
    operation_initiating_agent: str
    user_explicit_intent: bool
    refusal_reason: Literal["unknown_tool"]
```

Field justifications:

- `operation_tool_id`: the input that triggered the refusal. Required
  for diagnosis ("which call was refused?"). Matches the
  `operation_tool_id` field name in `AutonomyDecisionMetadata` so a
  union query across both EventTypes joins cleanly.
- `operation_initiating_agent`: same shape as
  `AutonomyDecisionMetadata` — refusal attributable to the same
  agent whose call would have been recorded as a decision.
- `user_explicit_intent`: the same input the scorer would have
  consumed. Preserved so future analysis (e.g., "did users push
  refused tools when they were explicit?") is answerable from the
  event log alone.
- `refusal_reason`: discriminator. P1.2-C4 writes only
  `"unknown_tool"`. Future ADRs (P1.3 Hard Guards) extend the
  Literal additively. Extension is safe for replay: old records
  always carried one of the originally-defined values; new records
  may carry new values, but old records remain valid.

Absent fields (and why):

- No decision trace. There was no decision — the gate raised before
  computing one. A trace field set to a placeholder or empty value
  would manufacture false data (Principle 4).
- No `score` or `tier`. Same reason: never computed.
- No timestamp. Events carry their own timestamp at append time via
  `EventStore.append()`; duplicating it in metadata is redundant.
- No `error_message` or `tool_id_attempted` (separate from
  `operation_tool_id`). Single source of truth: `operation_tool_id`
  IS what was attempted; `UnknownToolError.tool_id` (the original
  exception attribute) equals this value.

### 3. Synchronous emission, before raising upward

The emission layer (`autonomy.emission`, location confirmed in
P1.2-C4 senior plan §5 push-back #1) writes the
`autonomy_refusal` event **before** re-raising the
`UnknownToolError` to its caller. Shape (illustrative, not
prescriptive — exact code lives in C4-5):

```python
try:
    result = gate(operation, tools, thresholds)
    event_store.append(...autonomy_decision metadata...)
    return result
except UnknownToolError:
    event_store.append(...autonomy_refusal metadata...)
    raise
```

This mirrors ADR-005 §6's "synchronously before tool execution
proceeds" invariant. The refusal record exists in the event log
before the caller is told the operation was refused; even if the
caller crashes before logging the failure elsewhere, the audit
trail is complete.

If `event_store.append()` itself raises (e.g., disk failure mid-
append), behavior is implementation-defined in C4-5 and is NOT
governed by this ADR. The conservative default is "let both
exceptions surface" — losing the audit record is bad but masking
the original `UnknownToolError` would be worse.

### 4. Layering: `orchestrator.autonomy` imports from `orchestrator.core`

C4-5 introduces the **first** import edge from `autonomy.emission`
to `core.event_store` (and to `core.event` for the metadata class).
This direction is the natural one: `core` defines foundational
event primitives; `autonomy` consumes them.

The reverse — `core` importing from `autonomy` — remains forbidden
per the C2 freeze decision (preserved through `AutonomyDecisionMetadata`
being deliberately duplicated in `core.event` rather than importing
`DecisionTrace` from `autonomy.scoring`; see the docstring at
`src/orchestrator/core/event.py:209-211`).

This ADR records the rule explicitly so future contributors know
which direction is OK. A constitutional test enforcing
`core → autonomy` forbidden is recommended (P1.2-C4 plan §5
push-back #2 carries the proposal; architect decides whether to
land it in C4-5 or defer).

## Considered alternatives

### A. Reuse `autonomy_decision` for refusal (optional fields)

Add nullable `score`, `tier`, `trace` fields to
`AutonomyDecisionMetadata` that are `None` on refusal. One event
type, branching on field presence.

Rejected on Principle 4: optional fields in a strict event schema
let `None` impersonate "no decision was made", indistinguishable
from "we forgot to write the field". The existing constitutional
test `test_constitution_autonomy_decision_event_carries_trace`
pins field-set parity with `DecisionTrace`; adding optional fields
either breaks that test or weakens its assertion to "field present
OR explicitly null", which is exactly the drift the test exists
to catch.

### B. Silent omission (no event for refusal)

`gate()` raises, caller catches and logs externally (or just
propagates). No new EventType, no new metadata schema.

Rejected: contradicts ADR-005 §6's invariant. Creates an audit-trail
gap exactly where it's most likely to matter (when something went
wrong). External logging is non-replayable; the event log IS the
audit trail.

### C. Specific event type `unknown_tool_attempted`

Each refusal class gets its own EventType. P1.3 Hard Guards adds
`destructive_refused`, `cost_ceiling_breached`, etc.

Rejected: EventType inflation. `EventType` is the
constitutional vocabulary (per ADR-001); each new value carries a
fixed cost (ADR + table row + metadata schema + constitutional
test). Reusing one EventType with a discriminator preserves the
vocabulary at small ADR cost (each new `refusal_reason` value is
an ADR amendment, not a new EventType + everything-that-comes-with).

### D. Refusal as a fourth tier in `AutonomyTier`

Add `REFUSED` to the AutonomyTier enum; `gate()` returns
`AutonomyScore(tier=REFUSED, ...)` instead of raising.

Rejected: ADR-005 §1 explicitly removed `FORBIDDEN` from the tier
enum because refusal belongs in a sibling layer (Hard Guards / the
unknown-tool registry), not as a tier output. Reintroducing as
`REFUSED` reverses that decision. Tiers are output of *successful*
scoring; refusal happens *before* scoring (no reversibility value
available) or *outside* it (Hard Guards). Conflating these creates
the case-collapse ADR-006 already rejected.

## Consequences

**Easier:**

- Every gate evaluation has an audit event — no absence-as-signal
  ambiguity. Querying "what did the gate do?" is a single
  `SELECT type, metadata FROM events WHERE type IN
  ('autonomy_decision', 'autonomy_refusal')`.
- Future Hard Guards refusals extend `refusal_reason` Literal by
  ADR amendment, not by new EventType. Adding one value is one
  ADR + one Literal extension + one constitutional test extension.
- Layering rule "autonomy → core OK; core → autonomy forbidden"
  is documented in one place future contributors can find.
- Refusal-class analysis (`GROUP BY refusal_reason`) becomes
  available the moment P1.3 lands; no schema change needed.

**Harder:**

- Two parallel metadata schemas exist (`AutonomyDecisionMetadata`
  with 12 fields, `AutonomyRefusalMetadata` with 4). Drift cost
  is small because the two are semantically different — the
  constitutional tests pin both independently. But a reader new
  to the autonomy module must learn both shapes.
- C4-5 emission code branches on success/exception. The two-branch
  structure is acknowledged here so future readers don't try to
  "unify" the branches via a refusal-as-tier hack (alternative D
  above).
- `event-model.md` now has 18 types instead of 17 — every prose
  reference to "17" updates in lockstep (per `feedback_doc_spec_drift_5_surfaces.md`).

**Neutral:**

- `AutonomyRefusalMetadata` field count is deliberately small.
  Future readers may wonder why; the answer is "no decision trace
  to mirror". The constitutional test docstring should say so.
- The discriminator pattern (Literal with one value, extensible)
  is the first instance of this pattern in the event metadata
  vocabulary. P1.3 will be the first user of the extension; until
  then, the Literal-of-one is harmless.

## Reversibility

| Decision | 6-month reversal cost |
|---|---|
| 1. Event type name `autonomy_refusal` | Low — rename is one ADR + one migration script. No external consumer yet. |
| 2. Metadata field set (4 fields) | Medium — adding fields is additive (new records grow, old records replay). Removing or renaming breaks replay and forces an event-store version bump. |
| 3. Synchronous emission before raise | Low-Medium — switching to async/queued is a refactor in `emission.py`; data path unchanged on revert. |
| 4. Layering `autonomy → core` | Expensive — undoing means inverting the dependency (e.g., emission lands in `agents/` instead of `autonomy/`). That's a code move + constitutional test rewrite. The expensive cost is intentional — pick the direction once, deliberately. |

## References

- ADR-001 (event store foundation) — EventType + constitutional
  test conventions reused.
- ADR-005 Decision 6 (autonomy_decision event) — sibling event
  type; this ADR fills the refusal gap left.
- ADR-006 (unknown tool_id semantics) — Decision 3 (`gate()`
  propagates unwrapped) hands the refusal-event-writing concern
  to this ADR.
- `docs/architecture/event-model.md` — "17 types" → "18 types"
  prose updates + new row in the types table (5-surface scan
  surface 4; pre-edit grep sub-rule applies).
- `docs/process/senior-planner.md` § "ADR drafting" — this is the
  third senior-drafted ADR (after ADR-005 architect-bootstrap and
  ADR-006).
- `docs/process/architect-briefs/P1.2-C4.md` — architect-settled
  design decisions feeding into this ADR (event name lean, field
  count lean, emission location lean).
- `docs/process/senior-plans/P1.2-C4.md` — task plan landing the
  implementation; ADR acceptance (status `Proposed → Accepted`)
  gates C4-3 and onward.
- Implementation entry points: P1.2-C4-3 (enum + metadata +
  constitutional test) and P1.2-C4-5 (emission layer that writes
  the event).
