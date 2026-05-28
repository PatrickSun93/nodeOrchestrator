---
task_id: P1.6
round: R0-A-on-plan
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 11
verdict_history:
  - verdict: needs_architect
    at_commit: cefed41
    findings_count: { red: 0, yellow: 3, green: 8 }
    note: Y1 (ADR-014 D2 derivation predicates underspecified) + Y2 (D1 purity vs D6 timestamp impurity inconsistency) + Y3 (ADR-015 D4 lex tiebreak rationale imprecise on UUID v4 randomness) — all "ADR D-section precision" sub-pattern (1st-instance class; W-005 codification queue).
  - verdict: clean
    at_commit: pending-this-revision
    findings_count: { red: 0, yellow: 0, green: 11 }
    note: Y1 + Y2 + Y3 absorbed per architect routing (all → α) at routing commit ca9c894. Senior verified all 5 D2.1-D2.5 derivation predicates against actual core/event.py typed-metadata schemas (HypothesisMeta + DecisionMeta + RejectionMeta + RetractionMeta + AutonomyDecisionMetadata + StateTransitionMeta); refined routing-artifact D2.1 sketch from `parent_id` walk to typed-metadata cite chains per "senior decides verification path" clause. 10th project use of RC-10 verdict-bump protocol; 4th codified.
---

> **Verdict bump 2026-05-28 (RC-10 codified protocol, 10th project use, 4th codified):**
> Senior absorbed architect routing at this revision commit (Y1 → α; Y2 → α;
> Y3 → α per `architect-routing.md` at `ca9c894`). Spot-check verified:
>
> - **Y1 absorbed**: ADR-014 D2 gains 5 derivation-predicate subsections
>   (D2.1-D2.5). Senior refined the routing-artifact D2.1 sketch — instead
>   of walking via universal `parent_id`, the predicate walks **typed-metadata
>   cite chains** (DecisionMeta.based_on / RejectionMeta.rejects /
>   RetractionMeta.retracts), per "senior decides verification path" clause.
>   Rationale: parent_id is universal Event-level (general reply); the typed
>   metadata fields are the load-bearing close-semantic. Plan §2 P1.6-1
>   acceptance updated to reference ADR-014 D2.1-D2.5 by section (no
>   plan-text predicate re-statement per Principle 9).
> - **Y2 absorbed**: ADR-014 D1 + D6 reconciled via clock-injection.
>   `produce_snapshot` signature gains `snapshot_at: TimestampMs` keyword
>   parameter. D1 stays "pure function" (now true: same `(events, room,
>   snapshot_at)` → same Snapshot). D6 reframed as caller-frozen-time
>   semantic. Plan §2 P1.6-1 + P1.6-3 acceptance updated; `snapshot_dispatch.py`
>   calls `now_ms()` once and threads through.
> - **Y3 absorbed**: ADR-015 D4 rewrite — verified `generate_event_id()`
>   returns `evt_<uuid4-hex>` at `core/event.py:38-49` (UUID v4 = random,
>   NOT time-sortable). Lex sort achieves per-set determinism but NOT
>   insertion/causal order. P1.5 R1 retro cross-referenced (commit `307a8fa`
>   rowid fix); P1.6 scope decision pinned (stay lex; semantic differs from
>   `get_room_events`); future-amendment hooks named.
>
> Y1 + Y2 + Y3 reclassified as 🟢 G9 + G10 + G11 (the absorption itself is
> the proof). Verdict bumps `needs_architect → clean` (0🔴 / 0🟡 / 11🟢;
> 8 prior 🟢 + 3 new 🟢 from absorption).
>
> **10th project use of frontmatter-as-live-signal pattern**; **4th under
> codified protocol** (`reviews/README.md` post-`6365cce`; W-003 R0-A-on-plan +
> P1.5.5 R0-A-on-plan + P1.5.5 R0-A + this P1.6 R0-A-on-plan).
>

# P1.6 R0-A-on-plan review (architect-partner lens)

| Field | Value |
|---|---|
| Round | R0-A-on-plan (plan-stage external review per RC-9 + brief Architect-settled decision 7; architect leans dispatch given ADR-014 + ADR-015 are load-bearing contract surfaces referenced by ≥5 future tasks) |
| Reviewer | architect-partner (Claude Opus 4.7, 1M context) in primary session |
| Date | 2026-05-28 |
| Artifacts reviewed | `claude/P1.6-plan` @ `841e8ed` — `docs/process/senior-plans/P1.6.md` (460 lines) + `docs/decisions/ADR-014-snapshot-contract.md` (186 lines, `Proposed`) + `docs/decisions/ADR-015-decision-log-shape.md` (158 lines, `Proposed`) + `docs/process/reviews/P1.6/external-r0b-prompt.md` (140 lines, RC-15 dual-lens dispatch artifact). Brief read on main @ `docs/process/architect-briefs/P1.6.md`. Cross-checked against runtime code: `core/event.py` (lines 33, 38-49, 88, 264, 272-282), `agents/schema.py:39-54`, `agents/speaking.py:105-129`, `agents/loader.py`, `rooms/state_machine.py:26`, `llm/purposes.py:46`, `config/agents/{skeptic,prober,operator,divergence_mapper,logger}.yaml`. |
| Workflow context | First substantive new-pattern cycle since P1.5.5 (operator + ADR-013); first cycle on fully-mature substrate (post-W-004 close); **first plan to apply all 3 W-004-2 codified rules from plan stage** (claims-without-cites verification cite + promotion-impact systematic grep + architect-deferral literal-reading). Multi-ADR cycle (2nd in project history; W-002.5 was 1st). |
| Distinct from plan-vs-impl | Plan-vs-impl will run post-impl on the impl branch. This R0-A-on-plan focuses on: **ADR-014 + ADR-015 contract precision** (where senior under-specifies derivation predicates relative to Principle 9 inscription discipline); **purity vs clock-read inconsistency in ADR-014 D1 vs D6**; **lex-tiebreak rationale precision in ADR-015 D4 relative to P1.5 R1 retro lesson**; independent verification of senior's 3 deviations from brief (combined `derived/` package, SummarySnapshotMeta addition, brief correction on divergence_mapper triggers); external R0-B prompt quality. |

---

## Findings

### 🟡 Y1 — ADR-014 D2 declares `Snapshot` field types but underspecifies 5 derivation predicates; plan §2 P1.6-1 acceptance gestures partially in plan-text not ADR-text

**Where:** `docs/decisions/ADR-014-snapshot-contract.md` D2 (lines 35-82) declares 11 Pydantic classes with field types but **does not specify the derivation predicates** for the 5 collection/reference fields. Plan §2 P1.6-1 acceptance (lines 105-108) gestures at some predicates in plan-text but Principle 9 (no orphan spec) requires ADR-level inscription.

**Specific underspecifications (5 sub-items):**

1. **`Snapshot.open_hypotheses`** — plan line 106: "hypothesis events without a subsequent `decision` event referencing them via `based_on` relation (or per `parent_id`; pin in ADR-014 D2 — see §3 ADR)." The plan **defers to ADR-014 D2** but ADR-014 D2 doesn't pin the predicate. Two candidates (parent_id-chain-walk vs metadata.based_on) are not equivalent — `HypothesisMeta` schema and what hypothesis-referencing events look like determine which. Future readers asking "what counts as open?" find a circular reference (plan defers to ADR; ADR silent).

2. **`Snapshot.closed_decisions`** — plan line 107: "decision event_ids (all decisions are 'closed' — they're terminal in their causality chain unless retracted)." But ADR-014 D2 doesn't specify the retraction-handling: are retracted decisions excluded from `closed_decisions`? Are decision_pivot events included? Currently silent.

3. **`Snapshot.tool_calls_pending_confirm`** — plan line 105: "filters tool_call events whose corresponding autonomy_decision event tier is countdown_confirm or hard_confirm." But the **correlation mechanism between tool_call and autonomy_decision events is not specified** anywhere. By `call_id`? By temporal proximity? By room_id + author + timestamp window? Per P1.5.5 `tool_dispatch.py:91-115` impl, `autonomy_decision` is appended BEFORE `tool_call`; correlation is implicit via emission order + author. ADR-014 should pin the correlation algorithm — otherwise future implementations diverge.

4. **`Snapshot.participants`** — plan line 104: "sorted alphabetically by agent_id" + "agents that emitted ≥1 utterance." But Logger (per P1.6-3 wiring) emits `summary_snapshot` events, NOT utterance events — so Logger would NEVER appear in `participants` even though it IS a participant in producing the snapshot. Is that the intended semantic? If broader inclusion is desired (≥1 utterance OR ≥1 summary_snapshot OR ≥1 tool_call), spec it. Currently ambiguous.

5. **`Snapshot.last_state_transition`** — ADR-014 D2 declares the field but doesn't specify the definition. Plan line 108: "most-recent `state_transition` event (by timestamp; None if no transition yet)." What if two state_transitions land at the same ms? ADR-015 D4 specifies lex tie-break for DecisionLog ordering — ADR-014 should mirror or explicitly diverge.

**Why this matters:** Principle 9 (no orphan spec) requires vocabulary + semantics inscribed before producers ship. Senior pre-investigation defended the 8-field choice well (plan §5 #1) but stopped at TYPE-declaration without going to DERIVATION-PREDICATE-declaration. Future readers asking "how does `produce_snapshot` decide which hypotheses are open?" find plan §2 (which says "see ADR-014") and ADR-014 (which is silent). The W-004-2 (a) claims-without-cites rule was applied to senior's claims about external surfaces; it wasn't extended to senior's own ADR D-decision precision.

**Architect-partner lean: α — senior amends ADR-014 D2 with 5 derivation-predicate subsections.** Each one ~3-5 lines defining the predicate operationally. Concrete sketch:

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

**Alternative routing β: skip + leave predicates as "junior decides at impl time".** Risk: junior implements one of the candidates senior didn't decide; R0-A catches; routing-revision overhead post-impl > 10-min ADR amendment now. Same shape as W-003 R0-A Y1+Y2 → α routing pattern (decision-deferred-to-impl is the failure mode the discipline gradient is closing).

**Recommendation: route α** — matches the discipline gradient + Principle 9 inscription requirement + W-004-2 (a) verification-cite rule applied to senior's own ADR decisions (not just claims about external surfaces).

### 🟡 Y2 — ADR-014 D1 (purity) vs D6 (snapshot_at captured at call time via now_ms) is internally inconsistent

**Where:** `docs/decisions/ADR-014-snapshot-contract.md`:
- **D1 (line 31):** "**The function does not call `event_store` internally** — caller is responsible for fetching events ... it does not append events; it does not invoke LLM." Plus "**purity**" framing + line 21: "**produce_snapshot is pure: same input events → same output Snapshot. No I/O, no LLM, no event_store.append inside the function.**"
- **D6 (line 108):** "**`Snapshot.snapshot_at` is captured AT `produce_snapshot` call time via `core.event.now_ms()`.**"

**What's missing:** D6 implies `produce_snapshot` calls `now_ms()` internally. Reading wall-clock time IS I/O (system call); strictly violates D1's "no I/O" purity claim. **Same input events at different call times produce different snapshots** (snapshot_at differs) — the "same input → same output" claim in D1's hard-requirements is FALSE under D6's clock-internal pattern.

Verified independently: `core/event.py:33` `now_ms() -> TimestampMs: return TimestampMs(int(time.time() * 1000))` — this IS a system clock read.

**Why this matters:** the purity contract is what makes `produce_snapshot` trivially testable + cacheable + reasonable-about (D1's stated benefits). With clock-internal pattern, the function is impure; same-input determinism is lost. Two failure modes:
- A consumer expecting `produce_snapshot(events, room) == produce_snapshot(events, room)` (e.g., for cache key derivation or test idempotence) gets surprised.
- The test in P1.6-1 acceptance "`produce_snapshot(events, room)` is pure: same input → same output" (line 102) is impossible to write as stated — calling it twice yields different snapshot_at values.

**Architect-partner lean: α — senior reconciles via clock-injection pattern.** Sketch:

```python
def produce_snapshot(events: list[Event], room: Room, *, snapshot_at: TimestampMs) -> Snapshot:
    """Pure derivation; caller provides snapshot_at (typically core.event.now_ms())."""
    ...
```

Caller (Logger's `produce_and_emit_snapshot` in `snapshot_dispatch.py` per P1.6-3) calls `now_ms()` and passes it in. D1 purity restored; D6 reframes to: "snapshot_at is set by caller at the moment of fetch + production; the function operates against caller-frozen time, not wall-clock."

**Alternative routing β: reframe D1 wording** to acknowledge clock-internal impurity. D1 changes from "pure" to "deterministic in business-logic outputs (event-derived fields); snapshot_at is wall-clock-stamped at call time." Less invasive but weakens the purity contract value.

**Alternative routing γ: skip — accept impurity as conventional.** Defensible but breaks discipline gradient + makes P1.6-1 acceptance test impossible-as-stated.

**Recommendation: route α (clock injection)** — preserves the purity contract semantically + makes the acceptance test feasible + adds 1 keyword parameter (trivial caller adjustment in `snapshot_dispatch.py`). The clock-injection pattern is well-known FP discipline; project precedent is light but additive.

### 🟡 Y3 — ADR-015 D4 lex-tiebreak rationale is misleading; UUIDs are NOT insertion-ordered; P1.5 R1 retro lesson partially missing

**Where:** `docs/decisions/ADR-015-decision-log-shape.md` D4 (lines 63-74):

> Sort key: `(entry.timestamp, entry.event_id)` ascending. ... Lexicographic event_id tie-break is deterministic regardless of insertion order (event_ids are generated per `generate_event_id` at `core/event.py` — **UUIDs in lexicographic order**). Caller-deterministic ordering for reproducibility.

**The bolded claim is misleading.** Verified independently at `core/event.py:38-49`:

```python
def generate_event_id() -> EventId:
    """Generate a new event id.
    Format: `evt_<32-hex>` (Stripe-style typed prefix + uuid4 hex).
    ...
    Chronological ordering is the responsibility of the timestamp
    column, not the id, so uuid4's lack of time-sortability is irrelevant.
    """
```

**UUID v4 hex is RANDOM, not insertion-ordered.** Lex-sorting random UUIDs gives **per-set determinism** (same set sorts to same order) but **not causal/temporal ordering**. Senior's defense in plan §5 #5 actually says "Caller-deterministic ordering for reproducibility" — which IS the right framing — but D4's "UUIDs in lexicographic order" parenthetical introduces the misleading claim.

**P1.5 R1 retro lesson partially missing:** the external R0-B prompt (probe #6) explicitly raises this: "P1.5 R1 retro caught random-UUID tiebreak instability; the fix was rowid (SQLite implicit auto-increment). DecisionLog uses lexicographic event_id; same family of bug?"

The lesson from P1.5 R1: when ties on (timestamp, random-UUID) occur, causal/insertion order is lost in the sort. P1.5 R1's fix was to use SQLite rowid (insertion-order preserving). ADR-015 D4 doesn't reference this precedent, doesn't decide whether rowid is needed, doesn't articulate why lex-of-random-UUIDs is "good enough" for DecisionLog despite being insufficient for P1.5's case.

**Risk severity:** for DecisionLog specifically, two same-ms decisions are rare in practice (single-room, sequential dispatch per ADR-011 D1). But the rationale being precise matters for future readers + future P1.x cycles that introduce concurrent dispatch (P1.5+ async-reshape watch). If concurrent dispatch lands with random-UUID lex-tiebreak as the only ordering, P1.5 R1's bug class returns.

**Architect-partner lean: α — senior amends ADR-015 D4 with precise rationale + P1.5 R1 cross-reference + decision on rowid.** Sketch:

```markdown
### 4. Chronological strict ordering; ties broken by event_id lexicographic

Sort key: (entry.timestamp, entry.event_id) ascending.

**Why lex-of-random-UUID tie-break is sufficient for P1.6 DecisionLog**:
- Per ADR-011 D1, dispatch is sequential per-room per-turn; same-ms ties are rare (single agent emits one decision per turn).
- The tie-break needs to be DETERMINISTIC across test runs (same set → same order); does NOT need to preserve causal/insertion order (which UUID v4 doesn't anyway).
- Per P1.5 R1 retro: SQLite rowid-based tie-break was needed when same-ms event ordering DID need to preserve insertion order (event_store query, not DecisionLog derivation).
  In DecisionLog's case, decisions arriving same-ms are conceptually unordered relative to each other; lex tie-break is acceptable representation.

**When this rationale breaks**: P1.5+ async-reshape introduces concurrent dispatch → multiple agents may emit decisions at the same ms. If causal ordering becomes load-bearing for DecisionLog consumers (e.g., dependency graphs across same-ms decisions), revisit via ADR-015 amendment toward rowid-based ordering.
```

**Alternative routing β: skip + leave as-is.** Risk: future readers carry "UUIDs in lex order" parenthetical as truth; P1.5 R1 lesson stays implicit. Same shape as P1.5.5 RC-19 mislabel (audit-trail tilt; routed δ).

**Recommendation: route α** — the misleading parenthetical is a real audit-trail tilt that costs nothing to fix; external R0-B will likely catch it anyway (probe #6 explicitly raises it); pre-fixing prevents a routing round-trip.

### 🟢 G1 — ADR-014 + ADR-015 substance is contract-locking + faithful to brief Architect-settled decisions

Each ADR decision maps to a brief Architect-settled decision or push-back resolution:

- **ADR-014 D1** (pure function over event stream) ← brief Architect-settled #1.
- **ADR-014 D2** (bounded 11-class vocabulary) ← brief Architect-settled #4 + plan §5 #1 field defense. (Note: precision gap surfaced as Y1 above; substance otherwise sound.)
- **ADR-014 D3** (state-machine-triggered Logger producer) ← brief Architect-settled #3 + plan §5 #2 defense.
- **ADR-014 D4** (persisted-via-event; no separate table) ← brief Architect-settled #1 + ADR-001 compliance.
- **ADR-014 D5** (deliberate duplication for `core/event` layering) ← ADR-013 D5 precedent + senior new self-discovery (SD-METADATA).
- **ADR-014 D6** (snapshot timestamp invariant) ← brief test-coverage §2 concurrency + Test §2 acceptance. (Internal inconsistency with D1 surfaced as Y2; otherwise the read-vs-write framing is correct.)
- **ADR-015 D1-D5** ← brief Architect-settled #2 + #5 + plan §5 #3 + #5.

The "Considered alternatives" sections in both ADRs mirror the brief's push-back invitations + senior's pre-investigation refutations. Future-reader audit trail is preserved.

### 🟢 G2 (major milestone — meta-circular) — First plan to apply all 3 W-004-2 codified rules from plan stage

Senior plan explicitly cites "FIRST PLAN TO APPLY ALL 3 W-004-2 CODIFIED RULES FROM PLAN STAGE" in the commit body. Independent verification:

- **(a) Claims-without-cites verification cite**: plan §5 has explicit `file:line` cites throughout (verified against `EventType.SUMMARY_SNAPSHOT` at `core/event.py:88`; `StateChangeTrigger.target_state` at `agents/schema.py:50`; `TYPED_METADATA` at `core/event.py:272-282`; `LLMPurpose.SNAPSHOT_SEMANTIC` at `llm/purposes.py:46`). All cites accurate.
- **(b) Promotion-impact systematic grep**: plan SD-PROMO bullet (line 418-424) lists symbol-collision grep for `Snapshot`, `DecisionLog`, `produce_snapshot`, `produce_decision_log`, `SummarySnapshotMeta`, `snapshot_dispatch`. All confirmed safe-to-add via independent grep.
- **(c) Architect-deferral literal-reading**: plan §5 #8 honors brief Out-of-scope #1 deferral verbatim ("Senior does NOT push back on this deferral"); no in-cycle stab on cross-room memory. Brief Out-of-scope #3 (LLM-augmented snapshot) also honored — ADR-014 Considered Alternative B explicitly rejects per W-004-2 (c) literal-reading discipline.

**The codifications work as designed under first-time application.** Discipline gradient holds.

### 🟢 G3 — 3 senior deviations from brief are each well-defended

1. **Combined `derived/` package** (plan §5 #4): senior pin deviates from brief's lean of split `snapshot/` + `decisions/`. Defense per `autonomy/{scoring,emission}.py` sibling-pattern precedent is sound; verified by reading `autonomy/emission.py:7-11` documentation. Reader-cognitive cost argument + constitutional-test consolidation argument both stand.

2. **`SummarySnapshotMeta` typed-metadata addition** (SD-METADATA + P1.6-2): brief said "no schema constraint" (true today); senior pins ADD `SummarySnapshotMeta` per ADR-013 D5 `ToolCallMeta` precedent. Defense via "every event type with a real producer has typed metadata" project-pattern is correct. Verified via `core/event.py:272-282` showing existing TYPED_METADATA entries.

3. **Brief correction (§5 #6)** on `divergence_mapper.yaml` having no triggers (brief said it had triggers; senior verified by reading the file). Independent re-verification confirms senior's correction:

```bash
$ git show origin/main:config/agents/divergence_mapper.yaml | grep speaking_triggers
# (empty — no speaking_triggers field)
```

**3 deviations all defensible; senior surfaced them explicitly per W-004-2 (a) discipline.**

### 🟢 G4 — 8 brief push-back resolutions verified independently

Push-back disposition table:

| # | Brief lean | Plan disposition | Concurrence |
|---|---|---|---|
| 1 | Keep 8-field snapshot vocabulary | Keep all 8; field-by-field defense | ✓ (subject to Y1 underspecification fix) |
| 2 | State-machine-triggered Logger | Confirmed; ADR-014 D3 locks | ✓ |
| 3 | Decision log shape minimal v1 | Confirmed; ADR-015 D2 locks | ✓ |
| 4 | Module location (split per brief lean) | Senior deviates — combined `derived/` | ✓ (G3 #1 defense; defensible) |
| 5 | ADR-014 + ADR-015 split | Confirmed split; W-002.5 multi-ADR routing | ✓ |
| 6 | Logger speaking_triggers extension | Pre-investigated; StateChangeTrigger accepts arbitrary; logger.yaml gets new trigger | ✓ |
| 7 | E2e test full state chain | Confirmed; senior tweak uses `next_room_state` directly (not RoomRuntime.run_turn) | ✓ (subject to e2e step 5 invocation-mechanism clarity in P1.6-4 acceptance) |
| 8 | Cross-room memory deferral | Honored per W-004-2 (c) literal-reading discipline | ✓ |

### 🟢 G5 — 6 brief predicted self-discoveries pre-resolved at plan-revision

Each SD bullet has a verification cite + resolution:

- **SD-TRIGGER**: `agents/schema.py:50` `target_state: str = Field(min_length=1)` — verified.
- **SD-METADATA**: brief correction via senior addition of `SummarySnapshotMeta`; closes the type-coverage gap.
- **SD-SERIALIZE**: round-trip invariant via Pydantic field-shape mirror; tested in P1.6-2 acceptance.
- **SD-LOGGER-AUTONOMY**: Logger `required_capabilities: []` per `logger.yaml:13` (verified); `process_tool_calls` gated by `if response.tool_calls`; clean skip.
- **SD-LOGGER-CONTEXT**: `build_agent_context` accepts any Agent shape (verified via `agents/selection.py` pattern).
- **SD-DERIVE-CONSUMER**: ADR-015 D4 pins consumer protocol — query event_store + derive on demand.

### 🟢 G6 — 3 NEW senior self-discoveries (S1-S3) sharpen the plan beyond brief

- **S1**: `snapshot_dispatch.py` sibling module per ADR-013 D1 precedent — second exercise of the separate-concern pattern P1.5.5 established. Clean reuse.
- **S2**: hardcoded `agent.id == "logger"` acceptable for P1.6 single-producer scope; future amendment hook clearly named. Honors Principle 9 (capture-now-or-amend-later).
- **S3**: constitutional test count corrected (1 new not 2 per brief Constraint #2) due to combined-package pin. Brief Constraint corrected by senior pin per W-004-2 (a) discipline.

### 🟢 G7 — External R0-B prompt is thorough + matches P1.4 precedent

Independent read of `docs/process/reviews/P1.6/external-r0b-prompt.md`:

- **System prompt** (lines 18-101) covers Claude-bias correction list + "specifically NOT in scope" exclusions (prevents external reviewer re-litigating already-resolved items) + 7 specific probes including the lex-tiebreak issue (probe #6) that aligns with this R0-A's Y3.
- **Artifact bundle** (lines 106-126) names the 5 documents + paste order; matches P1.4 external-r0b-prompt structure.
- **Notes for senior reviewing returned output** (lines 130-140) preserve the no-rephrase + verbatim-save discipline from P1.4 precedent.

**Observation**: external R0-B probe #6 (lex-tiebreak vs P1.5 R1 rowid lesson) overlaps with my Y3 — the external reviewer will likely confirm independently. If senior routes Y3 → α at architect-revision, the external R0-B may produce a clean finding on this point (verifies the pre-fix worked). If senior routes Y3 → β/γ, external R0-B may surface as 🟡 — confirming Y3 was real.

### 🟢 G8 — Multi-ADR W-002.5 aggregation routing (2nd project use) intact

Plan frontmatter declares `adr: [ADR-014, ADR-015]` → multi-ADR path β via W-002-1 + W-002.5 aggregation. Independent verification: `_read_adr_status` at `src/orchestrator/workflow/cli.py:118-138` handles list-shaped `adr` field; all-or-nothing Accept aggregation (`if "none" in statuses → none; if "proposed" in statuses → proposed; else accepted`). Second project use after W-002.5's own self-dogfood (ADR-010 + ADR-011). Routing should fire correctly.

---

## Cross-checks

- [x] ADR-014 D1-D6 substance reviewed independently; D2 underspecification surfaced as Y1; D1-D6 internal inconsistency surfaced as Y2.
- [x] ADR-015 D1-D5 substance reviewed independently; D4 misleading rationale surfaced as Y3.
- [x] 8 brief push-back resolutions verified against brief lean (G4).
- [x] 6 brief predicted self-discoveries pre-resolved with verification cites (G5).
- [x] 3 NEW senior self-discoveries reviewed (G6).
- [x] 3 senior deviations from brief verified + defended (G3).
- [x] First plan to apply all 3 W-004-2 codified rules from plan stage — meta-circular success (G2).
- [x] All cite-claims spot-checked via independent grep / `git show origin/main:<file>` reads.
- [x] External R0-B prompt artifact reviewed; quality matches P1.4 precedent (G7).
- [x] Multi-ADR aggregation routing path verified intact (G8).
- [x] Workflow state machine routing per ADR-008 D1 with `adr: [ADR-014, ADR-015]` will fire awaiting_architect_accept correctly.
- [x] Cross-family R0-B dual-lens dispatch per RC-15 (3 of 4 criteria) honored via external-r0b-prompt artifact.
- [x] Distance test honored: plan-stage same-day per RC-8; junior impl per substrate canon (calendar pause encouraged).
- [x] Constitutional invariant preserved: no LLM imports in `derived/` (new constitutional test `test_constitution_no_llm_calls_in_derived_module` planned per P1.6-1 acceptance).

---

## Net assessment

**Verdict: needs_architect.** Three 🟡 architect-routing-eligible findings; zero 🔴; eight 🟢.

All 3 Y findings are **same shape**: senior pre-investigation was thorough on **claims about external surfaces** (W-004-2 (a) discipline applied perfectly to grep-verifying brief claims) but **less thorough on the precision of senior's own ADR D-decisions**:

- **Y1**: ADR-014 D2 declares field types but not derivation predicates (5 sub-items).
- **Y2**: ADR-014 D1 (purity) vs D6 (clock-internal) internally inconsistent.
- **Y3**: ADR-015 D4 lex-tiebreak rationale parenthetical is misleading; P1.5 R1 retro lesson partially missing.

**Pattern observation**: W-004-2 (a) codified rule says "claims-without-cites against external surfaces need verification cite." This R0-A surfaces a **related-but-distinct** discipline gap: **claims-by-omission within own ADR D-sections** — senior inscribes "field X exists" without inscribing "derivation predicate for field X." Not the same as claims-without-cites (which is about external surfaces). Could be a codification candidate for W-005 brief — "ADR D-decision precision rule: when an ADR declares vocabulary types, the derivation predicates / construction algorithms must be inscribed at ADR level, not delegated to plan-text."

**1st instance of this new sub-pattern.** Not codified this cycle (1-instance threshold not met for hard codification; 3-instance threshold per W-003 architect-routing.md is the discipline gradient). Captured for future cycle retro.

**Recommendation: route α / α / α** (mirroring W-003 + P1.5.5 R0-A-on-plan α-α pattern). Three ADR D-section amendments at senior revision; ~30 min of edit time total (each one is a 3-5 line addition or rewording). Post-revision verdict bump per RC-10 protocol (`needs_architect → clean`; 10th project use; 4th codified).

**Forward implications:**
- P1.6 substantive impl substance is sound; the 3 Y findings are all ADR-precision items, NOT design errors. Senior's architectural decisions are correct; the inscriptions need precision tightening.
- Cross-family R0-B dispatch (external GPT-4-class or DeepSeek session) likely converges with Y3 (probe #6 in external prompt) — if senior routes Y3 → α at revision, external may produce clean finding on this point.
- The new "ADR D-decision precision" sub-pattern joins the W-005 codification queue alongside diagnose-before-fix (1-instance) + substrate-cleanup-cycles-need-dogfood (1-instance) + brief-authorship-integrity (1-instance). Per W-005-brief-deferral architecture (joint retro §13), all 1-instance items wait for 2nd-instance accumulation before codification.

## Captured for P1.6 retro

- **First plan to apply all 3 W-004-2 codified rules from plan stage** held cleanly on external-surface claims (G2); 1 new sub-pattern surfaced at ADR-D-section precision level (Y1). Codification effectiveness at first application: high for external claims; partial for ADR-D-section precision.
- **3 senior deviations from brief** all defensible + surfaced explicitly per W-004-2 (a). Discipline gradient maintained.
- **External R0-B probe #6 (lex-tiebreak)** overlaps with this R0-A's Y3 — first instance where external R0-B probe pre-empts an in-session R0-A finding. Worth noting in retro: if α-routing fires before external R0-B dispatches, external R0-B will likely return clean on probe #6.
- **Pattern recurrence ledger**: "Pre-investigation gap at plan-revision boundary" pattern (7 instances pre-P1.6) — Y1+Y2+Y3 are this cycle's instances at a NEW sub-level (ADR-D-section precision vs external-surface-claim). Watch for codification opportunity.

## Cross-references

- `docs/process/architect-briefs/P1.6.md` — brief Architect-settled decisions 1-10.
- `docs/process/senior-plans/P1.6.md` — plan under review.
- `docs/decisions/ADR-014-snapshot-contract.md` — Y1 + Y2 finding subjects.
- `docs/decisions/ADR-015-decision-log-shape.md` — Y3 finding subject.
- `docs/process/reviews/P1.6/external-r0b-prompt.md` — dual-lens R0-B dispatch artifact (G7).
- `src/orchestrator/core/event.py:33` (now_ms), `:38-49` (generate_event_id UUID v4), `:88` (SUMMARY_SNAPSHOT), `:272-282` (TYPED_METADATA dict).
- `src/orchestrator/agents/schema.py:39-54` — StateChangeTrigger.
- `src/orchestrator/agents/speaking.py:105-129` — StateChangeTrigger consumer.
- `src/orchestrator/autonomy/emission.py:7-11` — deliberate-duplication precedent.
- `docs/process/reviews/README.md` § Post-resolution verdict-bump protocol (RC-10) — applicable for post-α-α-α absorption verdict bump.
- `docs/process/dual-lens-r0b.md` § RC-15 codification — external R0-B dispatch path.
- `docs/process/senior-planner.md` § Pre-investigation discipline (W-004-2 codified) — claims-without-cites + promotion-impact-grep + architect-deferral literal-reading; first plan-stage application.
- `docs/process/reviews/P1.5/R0-A.md` — P1.5 R1 retro lesson on random-UUID tiebreak (subject of Y3 cross-reference).
- `docs/process/reviews/W-003/R0-A-on-plan.md` + `docs/process/reviews/P1.5.5/R0-A-on-plan.md` — α-α routing precedents for the recommended Y1+Y2+Y3 routing shape.
