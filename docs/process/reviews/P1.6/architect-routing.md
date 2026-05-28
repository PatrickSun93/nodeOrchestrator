---
task_id: P1.6
kind: architect-routing
date: 2026-05-28
reviews_acked:
  - R0-A-on-plan.md
decisions:
  Y1: α (senior amends ADR-014 D2 with 5 derivation-predicate subsections)
  Y2: α (senior reconciles ADR-014 D1 purity contract via clock-injection — produce_snapshot signature gains snapshot_at keyword param)
  Y3: α (senior amends ADR-015 D4 with precise lex-tiebreak rationale + P1.5 R1 cross-reference + decision on rowid scope for P1.6)
---

# P1.6 architect routing — "ack α / α / α"

**Architect decisions (this session):** all three Y findings resolve to reviewer's lean α. Same shape as W-003 + P1.5.5 R0-A-on-plan α-α routing precedent. **Pattern-recurrence note**: this is the 3rd consecutive cycle to route α on every plan-stage Y finding (W-003 = α α; P1.5.5 = α α; P1.6 = α α α). 7 cumulative α routings; discipline gradient holds.

This file is the **signal artifact for the senior revision session**. Senior picks P1.6 next, reads this file + `R0-A-on-plan.md` + the current plan + ADR-014 + ADR-015, applies the routed actions, pushes a revision commit on `claude/P1.6-plan`.

## Per-finding routing

### Y1 → α — Senior amends ADR-014 D2 with 5 derivation-predicate subsections

**Action:** insert 5 new subsections (D2.1 through D2.5) into ADR-014 D2 inscribing the predicate logic for each currently-underspecified field. Senior verifies predicate substance against the impl-time consumer (`produce_snapshot` in P1.6-1 acceptance); reviewer's sketch is **a starting draft** — senior pins exact predicate per "senior decides verification path" clause.

**Sketch (per R0-A Y1 §"Architect-partner lean")**:

```markdown
### 2.1 `open_hypotheses` predicate
A hypothesis event H is "open" iff no subsequent event E in chronological-strict order satisfies E.parent_id == H.id AND E.type ∈ {decision, rejection, retraction}. Walk via parent_id chain, NOT metadata.based_on (since based_on is an optional HypothesisMeta field and parent_id is universal).

### 2.2 `closed_decisions` predicate
A decision event D appears in closed_decisions iff D.type == decision AND no subsequent retraction event R satisfies R.metadata.retracts == D.id. decision_pivot events are NOT included (they're re-orientation, not closure).

### 2.3 `tool_calls_pending_confirm` correlation algorithm
Walk events forward; for each tool_call event TC, find the most-recent preceding autonomy_decision event AD with AD.author == TC.author AND AD.metadata.operation_tool_id == TC.metadata.tool_name AND no intervening AD for the same author+tool. TC is "pending" iff AD.tier ∈ {countdown_confirm, hard_confirm}. (Per P1.5.5 dispatch order: autonomy_decision lands BEFORE tool_call from process_tool_calls.)

### 2.4 `participants` criterion
Agent IDs appearing in event.author of any event with event.type ∈ {utterance, summary_snapshot, tool_call, autonomy_decision, autonomy_refusal} (i.e., any agent-authored event-type; excludes user + system). Deterministic ordering: ascending lexicographic by agent_id.

### 2.5 `last_state_transition` definition
The state_transition event E maximizing (E.timestamp, E.id) lex among all state_transition events in the room. None if no state_transition events. (Matches ADR-015 D4 lex tie-break.)
```

**Senior's verification path** per "senior decides X" clause: for each predicate, verify against:
- (Y1.1 open_hypotheses) `HypothesisMeta` schema at `core/event.py` — does `based_on` field exist? Is `parent_id` the right chain-walk target?
- (Y1.2 closed_decisions) `DecisionMeta` + `RetractionMeta` shapes — does `retracts: EventId` exist on RetractionMeta?
- (Y1.3 tool_calls_pending_confirm) `AutonomyDecisionMetadata` shape — does `operation_tool_id` exist? Verify P1.5.5 `tool_dispatch.py:91-115` emission-order claim.
- (Y1.4 participants) `EventType` enum — confirm agent-authored event types list.
- (Y1.5 last_state_transition) consistency with Y3 lex tie-break.

Plan §2 P1.6-1 acceptance (lines 105-108) gets updated to **reference the ADR-014 D2.1-D2.5 subsections** instead of restating predicates in plan-text. Per Principle 9 inscription discipline.

**Why α (not β/skip)**: matches W-003 R0-A Y1+Y2 → α routing pattern + W-004-2 (a) discipline + Principle 9. β (skip + leave predicates as "junior decides at impl time") risks junior implementing one of the candidates senior didn't decide; post-impl re-routing > 10-min ADR amendment now.

### Y2 → α — Senior reconciles ADR-014 D1 vs D6 via clock-injection

**Action:** add `snapshot_at` keyword parameter to `produce_snapshot` signature; ADR-014 D1 purity claim restored; ADR-014 D6 reframed to describe caller-frozen-time semantic.

**Sketch** (per R0-A Y2 §"Architect-partner lean"):

```python
def produce_snapshot(events: list[Event], room: Room, *, snapshot_at: TimestampMs) -> Snapshot:
    """Pure derivation; caller provides snapshot_at (typically core.event.now_ms()).

    Pure function: same (events, room, snapshot_at) → same Snapshot.
    Caller (Logger's produce_and_emit_snapshot in snapshot_dispatch.py per P1.6-3)
    calls core.event.now_ms() and passes it; isolates wall-clock impurity at caller layer.
    See ADR-014 D1 (purity contract) + D6 (caller-frozen-time semantic).
    """
```

**ADR-014 changes:**
- **D1 stays** ("pure function" + "same input → same output") — restored to truth under clock-injection.
- **D6 reframes**: snapshot_at is set by caller at fetch+production moment; produce_snapshot operates against caller-frozen time; "the read-vs-write ordering invariant" reads from caller's perspective, not wall-clock.

**Plan §2 P1.6-1 acceptance updates**:
- Signature freeze adds `snapshot_at: TimestampMs` keyword parameter.
- Acceptance line 102 ("`produce_snapshot(events, room)` is pure: same input → same output; no I/O") becomes "`produce_snapshot(events, room, snapshot_at=t)` is pure: same (events, room, snapshot_at) → same Snapshot; no I/O; no LLM; no event_store reads inside the function."

**Plan §2 P1.6-3 acceptance updates**:
- `snapshot_dispatch.py` `produce_and_emit_snapshot(...)` calls `now_ms()` then passes to `produce_snapshot(events, room, snapshot_at=now_ms())`. Caller layer owns the clock impurity.

**Why α (not β/γ)**: β (reframe D1 wording to "deterministic in business-logic outputs") weakens the purity contract value + leaves the P1.6-1 acceptance test impossible-as-stated. γ (skip + accept impurity as conventional) breaks discipline gradient. α adds 1 keyword param + restores purity contract semantically; trivial caller adjustment.

### Y3 → α — Senior amends ADR-015 D4 with precise rationale + P1.5 R1 cross-reference

**Action:** rewrite ADR-015 D4 rationale paragraphs to be precise about UUID v4 randomness; cross-reference P1.5 R1 retro lesson; decide on whether rowid-based ordering is needed for P1.6 scope.

**Sketch** (per R0-A Y3 §"Architect-partner lean"):

```markdown
### 4. Chronological strict ordering; ties broken by event_id lexicographic

Sort key: (entry.timestamp, entry.event_id) ascending.

**Tie-break rationale**:
- DecisionLog requires **deterministic ordering across test runs** (same input set → same output ordering) for reproducibility.
- Lexicographic sort of UUID v4 event_ids (per `core/event.py:38-49` — `evt_<uuid4-hex>` format) achieves per-set determinism — **NOT insertion order, NOT causal order**, since UUID v4 hex is random.
- This is acceptable for DecisionLog because: (1) ADR-011 D1 sequential per-room dispatch makes same-ms ties rare in P1.6 scope; (2) consumers needing causal ordering query event_store directly via parent_id chains.

**Why lex-of-random-UUID tie-break is acceptable for P1.6 (not P1.5 R1's case)**:
- P1.5 R1 retro caught random-UUID tiebreak instability in `event_store.get_room_events()` queries where insertion-order preservation was load-bearing for downstream room state machine transitions. The fix was SQLite rowid (insertion-order-preserving).
- DecisionLog is a different consumer surface: decisions arriving at the same ms are conceptually unordered relative to each other; lex tie-break is acceptable representation. No downstream consumer in P1.6 scope requires insertion-order preservation across same-ms decisions.

**When this rationale breaks** (future-amendment hook):
- P1.5+ async-reshape introduces concurrent dispatch → multiple agents may emit decisions at the same ms. If causal/insertion ordering becomes load-bearing for DecisionLog consumers (e.g., dependency graphs across same-ms decisions), revisit via ADR-015 amendment toward rowid-based ordering.
- Cross-room memory promotion logic (P1.6.5/P1.7) may add insertion-order-dependent semantics; revisit at that ADR.
```

**Senior's verification path**:
- Verify `generate_event_id` is uuid4 (confirmed at `core/event.py:38-49`).
- Cite P1.5 R1 retro lesson via direct file reference (`docs/process/reviews/P1.5/R0-A.md` Y? on rowid).
- Decide: P1.6 scope = stay lex-tiebreak (no rowid migration); future async-reshape = revisit.

**Why α (not β/skip)**: senior parenthetical "UUIDs in lexicographic order" is misleading + costs nothing to fix. External R0-B probe #6 will likely catch this if α doesn't fire pre-dispatch. Pre-fixing prevents a routing round-trip + sharpens future-reader audit trail.

## Senior revision actions (derived)

1. **ADR-014 D2 amendment**: insert 5 subsections D2.1-D2.5 inscribing derivation predicates per Y1 sketch. Senior verifies predicate substance against runtime schema before pinning. ~150-200 added LoC across the 5 subsections.

2. **ADR-014 D1 + D6 reconciliation**: revise D1 to state clock-injection-restored purity; revise D6 to describe caller-frozen-time semantic. ~30 LoC change across both decisions.

3. **ADR-014 producer signature update**: add `snapshot_at: TimestampMs` keyword parameter; update plan §2 P1.6-1 + P1.6-3 acceptance to thread through caller. ~5 LoC at signature freeze.

4. **ADR-015 D4 amendment**: rewrite rationale paragraphs per Y3 sketch; cross-reference P1.5 R1 retro; decide P1.6 scope stays lex-tiebreak. ~80-100 LoC change.

5. **Plan §2 P1.6-1 acceptance update**: replace plan-text predicate gestures (lines 105-108) with ADR-014 D2.1-D2.5 references. Acceptance line 102 updates for clock-injection signature.

6. **Plan §2 P1.6-3 acceptance update**: `snapshot_dispatch.py` `produce_and_emit_snapshot` calls `now_ms()` then passes to `produce_snapshot(events, room, snapshot_at=...)` per clock-injection.

7. **Plan §5 amendment**: add senior pre-investigation results for Y1 predicates verification (against `HypothesisMeta` + `RetractionMeta` + `AutonomyDecisionMetadata` shapes) — per W-004-2 (a) verification-cite discipline.

8. **Verdict bump on `R0-A-on-plan.md` per RC-10 protocol**: senior edits frontmatter in place after revision lands. `needs_architect → clean`. `findings_count: {red: 0, yellow: 0, green: 11}` (3 Y reclassify as G9 + G10 + G11 documenting absorption). `verdict_history:` array gets a new entry. Add blockquoted preamble naming the bump.

## Status flips that follow

Once the senior revision pass lands on `claude/P1.6-plan`:

- **R0-A-on-plan verdict bumps `needs_architect → clean`** per RC-10 codified protocol (`reviews/README.md` post-`6365cce`; **10th project use; 4th codified**).
- **PR opens** for `claude/P1.6-plan`; merge brings senior plan + ADR-014 + ADR-015 + external-r0b-prompt + R0-A + this routing onto main.
- **Cross-family R0-B DISPATCH** per RC-15 dual-lens (architect-dispatched external session post-merge OR pre-merge per architect timing preference). **First true cross-family R0-B since P1.4.**
- **ADR-014 Accept + ADR-015 Accept** (multi-ADR W-002.5 aggregation; both must reach Accepted before state advances).
- **`workflow advance --task-id P1.6`** fires `awaiting_architect_accept → awaiting_junior_impl` (multi-ADR W-002.5 path β; **2nd project use** after W-002.5 own dogfood).
- **Junior dispatches** to `claude/P1.6-impl`; parallelism set `[P1.6-1 ‖ P1.6-2]` (2-parallel per senior plan §3) runs as 2 parallel agents per RC-17 codification.

## Pattern-recurrence note for future plans

**3 cumulative α-routings in P1.6 plan-stage** = 7 cumulative α-routings since the discipline gradient began climbing (P1.5 Y1 = α; W-003 Y1+Y2 = α α; P1.5.5 R0-A-on-plan Y1+Y2 = α α; P1.6 R0-A-on-plan Y1+Y2+Y3 = α α α). All same shape: senior pre-investigation discipline applied imperfectly at one boundary, caught by R0-A-on-plan, routed α at architect.

**New sub-pattern this cycle**: R0-A Y1+Y2+Y3 are all **ADR D-section precision** items (declared types without declared derivation algorithms; D1+D6 internal inconsistency; D-section parenthetical rationale precision). 1st instance of this sub-pattern as a class.

**Three 1-instance items now in W-005 codification queue**:
1. **ADR D-section precision rule** (this cycle Y1 — when ADR D declares vocabulary types, the derivation predicates / construction algorithms must be inscribed at ADR level, not delegated to plan-text).
2. Diagnose-before-fix codification (P1.5.5 RC-19 mislabel; joint retro §13).
3. Substrate-cleanup-cycles-need-dogfood codification (W-004-4 e2e dogfood; joint retro §13).
4. Brief-authorship-integrity discipline (P1.5.5 brief withdrawal precedent; joint retro §13).

All wait for 2nd-instance accumulation per 3-instance codification threshold (W-003 architect-routing.md line 70-71 precedent). W-005 brief dispatches when ≥1 of these accumulates a 2nd instance OR architect-partner judges enough pattern surface area exists.

## Out of scope for this routing

- Re-litigating any 🟢 finding from R0-A-on-plan (all 8 confirm plan + ADR structural soundness).
- Re-opening brief's 10 Architect-settled decisions.
- Cross-family R0-B for P1.6 — DISPATCHED per RC-15 + brief Architect-settled #8; external session is architect-driven post-senior-revision.
- Codifying the "ADR D-section precision" sub-pattern in `senior-planner.md` (1-instance; W-005 codification queue per pattern-recurrence note).
- ADR-013 (operator tool dispatch) — sibling ADR; not subject to this routing.

## Cross-references

- `docs/process/reviews/P1.6/R0-A-on-plan.md` — finding source for Y1+Y2+Y3.
- `docs/process/senior-plans/P1.6.md` — the file senior revises in absorption pass.
- `docs/decisions/ADR-014-snapshot-contract.md` — Y1 + Y2 amendment subjects (D2 + D1/D6 + producer signature).
- `docs/decisions/ADR-015-decision-log-shape.md` — Y3 amendment subject (D4).
- `docs/process/reviews/P1.6/external-r0b-prompt.md` — external R0-B dispatch artifact; probe #6 pre-empts Y3.
- `docs/process/reviews/W-003/architect-routing.md` + `docs/process/reviews/P1.5.5/architect-routing.md` — α-α-α routing precedent shape.
- `docs/process/reviews/README.md` § Post-resolution verdict-bump protocol — RC-10 mechanics for the `needs_architect → clean` bump.
- `docs/process/dual-lens-r0b.md` — RC-15 dual-lens dispatch path.
- `docs/process/senior-planner.md` § Pre-investigation discipline (W-004-2 codified) — claims-without-cites + promotion-impact-grep + architect-deferral literal-reading rules.
- `docs/process/reviews/P1.5/R0-A.md` — P1.5 R1 retro lesson on random-UUID tiebreak (Y3 cross-reference subject).
- `src/orchestrator/core/event.py:38-49` — generate_event_id uuid4 (verification cite for Y3 amendment).
