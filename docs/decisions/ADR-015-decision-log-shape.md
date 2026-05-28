# ADR-015: Decision log shape — derived-live filter over event stream

**Status:** Proposed — 2026-05-28
**Scope:** Locks the structural shape, filter semantic, ordering invariant, and consumer protocol for the `DecisionLog` derived view. Governs `produce_decision_log` in `derived/decision_log.py`. Does not govern snapshot vocabulary (separate ADR-014) or cross-room memory persistence (deferred).

## Context

Decision-class events (`decision`, `decision_pivot`, `rejection`, `retraction`) have been produced since P0 but never read into a structured chronological view. Cross-room agents + future UI surfaces need an easy way to consume "what was decided in this room?" without re-parsing the full event stream every time.

Two design questions:

1. **Materialized vs derived live**: store DecisionLog as a separate persisted entity (table) OR derive on demand from event_store?
2. **Shape minimalism vs richness**: include only structural fields (event_id, timestamp, author, excerpt, parent) OR add semantic fields (dissent_dimension for decision_pivot, verification_state for hypothesis-chain decisions)?

Architect-partner brief lean (architect-settled decision 5): minimal v1 shape; derived live; richer fields land when consumer surface materializes. Senior pre-investigation confirms: Principle 1 (event log is truth) + Principle 9 (no orphan spec) both favor minimal-derived; richer enrichment requires consumer-driven amendment.

Touches Principle 1 (event log is truth — DecisionLog derives, doesn't shadow), Principle 5 (code decides — `produce_decision_log` is pure code), Principle 9 (shape inscription before consumers ship).

**Hard requirements**:
- `produce_decision_log` is pure: same input events → same output DecisionLog.
- Chronological strict ordering by timestamp; ties broken deterministically.
- Filter semantic is binary (event type ∈ {decision, decision_pivot, rejection, retraction} → in log; else skip). No semantic enrichment beyond the type set.
- `DecisionEntry.content_excerpt` is verbatim — no paraphrase, no LLM summarization (per Logger's existing `forbidden_behaviors` in `logger.yaml`).
- Consumer protocol: query event_store + call `produce_decision_log(events, room)`; no persistence layer.

## Decisions

### 1. `produce_decision_log(events, room) -> DecisionLog` is a pure function over event stream

Pure function in `src/orchestrator/derived/decision_log.py`. Input: pre-fetched `events: list[Event]` + `room: Room`. Output: frozen `DecisionLog` Pydantic model. No I/O; no LLM; no event_store calls inside the function.

Mirrors ADR-014 D1 — derived views are pure derivations; caller handles event-store I/O. Same constitutional invariant (`test_constitution_no_llm_calls_in_derived_module` covers both files).

### 2. Filter semantic: 4-event-type binary filter

Events with `event.type ∈ {decision, decision_pivot, rejection, retraction}` are included; all other event types are skipped.

**Why this exact set** (per pre-investigation):
- `EventType.DECISION` at `core/event.py:80` — primary decision events.
- `EventType.DECISION_PIVOT` at `core/event.py:92` — explicit re-orientation moves.
- `EventType.REJECTION` at `core/event.py:81` — first-class rejections of prior events (per `core/event.py:151-153` docstring: "must cite the specific event it rejects").
- `EventType.RETRACTION` at `core/event.py:82` — additive supersession of prior events (per `core/event.py:160-168` docstring: "retraction is an additive event that supersedes it").

**Why no semantic enrichment** (per senior §5 #3 defense): brief proposed adding `dissent_dimension` for `decision_pivot` events and `verification_state` for hypothesis → decision chains. Both are LLM-derived semantic fields with no current consumer; per Principle 9, vocabulary capture-now creates orphan fields. Richer fields land via ADR-015 amendment when a real consumer (cross-room agent OR UI surface) drives the shape.

### 3. `DecisionEntry.content_excerpt` is verbatim first-200-chars

```python
class DecisionEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_id: str
    event_type: Literal["decision", "decision_pivot", "rejection", "retraction"]
    timestamp: int
    author: str  # canonical "user" / "agent:<id>" / "system" per core.event.build_author
    content_excerpt: str  # event.content[:200] verbatim
    parent_event_id: str | None  # populated from event.metadata for rejection/retraction; None for decision/decision_pivot
```

**Why verbatim**: per Logger agent's existing `forbidden_behaviors` at `config/agents/logger.yaml:14` (TODO placeholder "paraphrasing_decisions") + handoff §3.1 "log preserves what was said." `produce_decision_log` is code-decided per Principle 5; no LLM-augmented summarization (`LLMPurpose.SNAPSHOT_SEMANTIC` deferred per brief Out-of-scope #3). The 200-char cap is for log readability; consumers wanting full content query `event_store` via `event_id`.

**Why `parent_event_id`**: rejection events carry `RejectionMeta.rejects: EventId` at `core/event.py:155-157`; retraction events carry `RetractionMeta.retracts: EventId` at `core/event.py:160-168`. Decision + decision_pivot don't have parent semantics in their typed metadata; `parent_event_id` is None for those. Consumers walking rejection/retraction chains have the link.

### 4. Chronological strict ordering; ties broken by event_id lexicographic

```python
class DecisionLog(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    room_id: RoomId
    entries: list[DecisionEntry]  # strict chronological by timestamp; ties by event_id lex
```

Sort key: `(entry.timestamp, entry.event_id)` ascending. **No reordering for "importance" or "priority"** — chronological order preserves causal narrative; consumers needing other orderings re-sort the materialized list.

**Tie-break rationale** (per R0-A Y3 → α routing absorption — rewritten for precision about UUID v4 randomness):

- DecisionLog requires **deterministic ordering across test runs** (same input set → same output ordering) for reproducibility.
- `generate_event_id()` at `core/event.py:38-49` returns `evt_<uuid4-hex>` — UUID v4 is random, NOT time-sortable. Lex sort of UUID v4 event_ids achieves **per-set determinism** (the same set of events always sorts the same way) — but it is **NOT insertion order, NOT causal order**.
- This is acceptable for P1.6 DecisionLog because:
  1. **ADR-011 D1 sequential per-room dispatch** makes same-ms decision ties rare in P1.6 scope (one agent decides at a time).
  2. **Consumers needing causal ordering** query event_store directly via `parent_event_id` chains (RejectionMeta.rejects / RetractionMeta.retracts links).
  3. **DecisionEntry semantics**: decisions arriving at the same ms are conceptually unordered relative to each other; lex tie-break is acceptable representation.

**Why lex-of-random-UUID is acceptable here but was NOT in P1.5 R1's case**:

- **P1.5 R1 retro** (`docs/process/reviews/P1.5/R0-A.md`, R1 round) caught random-UUID tiebreak instability in `event_store.get_room_events()` queries where insertion-order preservation was load-bearing for downstream room state machine transitions. The fix landed at P1.5 R1 commit `307a8fa`: changed the tiebreaker to SQLite `rowid` (implicit auto-increment B-tree key, insertion-order-preserving).
- **DecisionLog is a different consumer surface** from `get_room_events`: decisions arriving at the same ms within a single room are conceptually unordered relative to each other; no downstream consumer in P1.6 scope requires insertion-order preservation across same-ms decisions. **Lex tie-break is the correct representation for this semantic.**

**P1.6 scope decision — stay with lex tie-break, do NOT migrate to rowid**:

- Migrating DecisionLog to rowid-based ordering would require querying SQLite-level `rowid` from `event_store` (currently `event_store.get_room_events` returns ORM-mapped Events without rowid); breaks the pure-function contract (`produce_decision_log` would need event_store access for rowid lookup, violating D1).
- Future-amendment hook below names the conditions where this rationale breaks.

**When this rationale breaks** (future-amendment hook):

- **P1.5+ async-reshape** introduces concurrent dispatch → multiple agents may emit decisions at the same ms (ADR-011 D1 reserves this re-shape). If causal/insertion ordering becomes load-bearing for DecisionLog consumers (e.g., dependency graphs across same-ms decisions), revisit via ADR-015 amendment toward rowid-based ordering. The amendment would need to revisit D1 (pure function) — likely by passing rowid as a derived field on Event (caller-pre-fetched).
- **Cross-room memory promotion logic** (P1.6.5/P1.7 per `handoff.md` §4.5 deferred) may add insertion-order-dependent semantics; revisit at that ADR.

### 5. Consumer protocol: query event_store + derive; no persistence

Consumers retrieve DecisionLog via:

```python
events = event_store.get_room_events(room.id)
dlog = produce_decision_log(events, room)
```

**No materialized DecisionLog table or event**. Unlike Snapshot (which is persisted-via-event per ADR-014 D4 because the room state machine consumes the `summary_snapshot` event), DecisionLog has no analogous state-machine consumer; derivation is cheap (single pass over event stream); cross-room agents query event_store directly.

If future cross-room memory promotion requires persistent DecisionLog snapshots, that's an ADR-015 amendment (or a separate ADR if cross-room memory persistence lands first).

## Considered alternatives

### A. Materialized DecisionLog as a SQLite table

Add `decision_log` table; append rows on every decision-class event; consumers query the table directly.

**Why rejected (ruled out by D1 + D5)**: violates Principle 1 — DecisionLog table becomes alternative source of truth; sync semantics with event_store is non-trivial; no current consumer justifies the persistence cost. Derivation is cheap; cache later if profiling shows need.

### B. LLM-enriched DecisionEntry with summary text + dissent dimensions

`DecisionEntry` gains `summary: str | None` (LLM-composed short label), `dissent_dimensions: list[str]` (extracted from decision_pivot context).

**Why rejected**: `LLMPurpose.SNAPSHOT_SEMANTIC` deferred per brief Out-of-scope #3 + W-004-2 (c) literal-reading discipline; no consumer for LLM-enriched fields yet. Verbatim 200-char excerpt gives consumers ad-hoc browsing without LLM cost. Amend ADR-015 when consumer materializes.

### C. Combined ADR-014 + ADR-015 (single ADR for both derived views)

One ADR locking both snapshot vocabulary + decision log shape, reducing routing overhead.

**Why rejected (split per senior §5 #5)**: snapshot vocabulary (structural) and decision log shape (filter-semantic) are orthogonal concerns — future readers asking "what fields does Snapshot have?" find ADR-014; "which events count as decisions?" find ADR-015. W-002.5 multi-ADR aggregation pattern (precedent: ADR-010 + ADR-011 in W-002.5) supports the split routing cleanly. Combined ADR conflates concerns.

### D. Filter set includes `hypothesis` (hypothesis → decision chain readers)

Include `EventType.HYPOTHESIS` so DecisionLog captures investigative-cycle events.

**Why rejected**: hypothesis events are precursors to decisions, not decisions themselves. Including them dilutes the "what was decided?" semantic. Consumers wanting hypothesis-chain reads use `Snapshot.open_hypotheses` (ADR-014 D2) + walk via `event_store` queries. Filter set stays decision-class-only.

## Consequences

**Easier:**

- Cross-room agents + future UI surfaces have a stable derived view for "what was decided in this room?" — one function call.
- Chronological + deterministic tie-break makes DecisionLog reproducible across test runs; no flakiness.
- Verbatim excerpts preserve audit-trail fidelity; no semantic drift via paraphrase.
- ADR-015 amendment process forces future readers to defend why richer fields are needed.

**Harder:**

- Adding decision-relevant fields (e.g., `dissent_dimension`, `verification_state`) requires ADR amendment; consumers waiting for richer fields face latency.
- Cross-room memory promotion logic (when it lands) will need to decide whether to persist DecisionLog snapshots OR re-derive on demand; deferred decision.
- 200-char excerpt cap may truncate important context for consumers; mitigation: full content always accessible via `event_id` query.

**Neutral:**

- No persistence layer means consumer must re-derive on each query; cost is single pass over event_store (cheap at P1.6 scale; revisit if profiling shows otherwise).
- `parent_event_id` is None for decision/decision_pivot but populated for rejection/retraction; consumers handle the Optional shape.
- Logger does NOT produce decision_log events (unlike `summary_snapshot`); DecisionLog is only consumed via direct derivation, not persisted-via-event. Per D5 — no state-machine consumer needs it.

## Reversibility

| Decision | 6-month reversal cost |
|---|---|
| D1 (pure function over event stream) | **Trivial.** Same as ADR-014 D1 — signature change with no caller-contract breakage. |
| D2 (4-event-type filter) | **Low.** Adding event types to the filter is data-shaped (one Literal extension); removing requires consumer audit. |
| D3 (verbatim content_excerpt) | **Trivial.** If consumers want richer text, the field is forward-compatible to additive enrichment via amendment. |
| D4 (chronological strict + lex tie-break) | **Trivial.** Sort key change; consumers depending on ordering would need test update. |
| D5 (derived-live; no persistence) | **Medium.** Adding persistence means deciding when to materialize (every event? on snapshot? on query?). Each option has trade-offs; would need its own ADR. |

## References

- ADR-001 — event log as truth (informs D1, D5 — DecisionLog derives, doesn't shadow).
- ADR-008 — workflow state machine (this ADR routes via `awaiting_architect_accept` per multi-ADR W-002.5 aggregation alongside ADR-014).
- ADR-013 D5 — typed-metadata-mirror pattern (informs ADR-014 D5 not this ADR; DecisionLog has no `core/event` typed metadata since not persisted-via-event).
- ADR-014 — snapshot contract (sibling ADR; shared package + constitutional test; shared `produce_*` pattern).
- `handoff.md` §3.1 (log preserves what was said — informs D3 verbatim discipline); §4.5 (cross-room memory deferred).
- `config/agents/logger.yaml:14` — Logger's `forbidden_behaviors` placeholder ("paraphrasing_decisions") — aligned with D3 verbatim discipline.
- `src/orchestrator/core/event.py:80-82` + `:92` — decision-class EventType definitions (consumed by D2 filter set).
- `src/orchestrator/core/event.py:151-168` — RejectionMeta + RetractionMeta (consumed by D3 `parent_event_id` population).
- `docs/process/architect-briefs/P1.6.md` — brief that prompted this ADR.
- `docs/process/senior-plans/P1.6.md` — plan that locks atomic-task breakdown.
- Implementation lands on `claude/P1.6-impl` post-Accept.
