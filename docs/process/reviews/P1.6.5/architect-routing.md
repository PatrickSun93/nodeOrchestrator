---
task_id: P1.6.5
kind: architect-routing
date: 2026-05-28
reviews_acked:
  - R0-A-on-plan.md
decisions:
  Y1: α (ADR-016 D8 code block updates to str | None with deliberate-duplication rationale per ADR-014 D5)
  Y2: α (ii) (record_hypothesis adds producer-time existence check for source_event_ids; honors ADR-016 D2:155 claim)
  Y3: α (a) (DecisionMeta gains schema-level @model_validator enforcing promotion-co-presence)
  Y4: α (b) (lookup_verified_knowledge raises ValueError on empty topic_tags; fail-loud intent)
  Y5: α (a) (promotion event room_id = room1.id originating-hypothesis pin confirmed)
  Y6: α (small) (D4 non-atomicity record_hypothesis ↔ hypothesis-event added to forward-amendment hooks)
---

# P1.6.5 architect routing — "ack α / α / α / α / α / α"

**Architect decisions (this session):** all six Y findings resolve to reviewer's lean α. Y2 + Y4 sub-options explicitly chosen by architect via architect-partner AskUserQuestion (Y2 → (ii) producer-time check; Y4 → (b) raise on empty). **Pattern-recurrence note**: this is the **4th consecutive cycle** to route α on every plan-stage Y finding (W-003 = α α; P1.5.5 = α α; P1.6 = α α α; P1.6.5 = α α α α α α). **13 cumulative plan-stage α routings**; α-discipline gradient continues to hold across cycles with growing finding counts (P1.6.5 has 6 Y findings vs P1.6's 3 — first plan-stage cycle to exceed 3 Y).

This file is the **signal artifact for the senior revision session**. Senior picks P1.6.5 next, reads this file + `R0-A-on-plan.md` + the current plan + ADR-016, applies the routed actions, pushes a revision commit on `claude/P1.6.5-plan`.

## Per-finding routing

### Y1 → α — ADR-016 D8 code block updates to `str | None` (deliberate-duplication per ADR-014 D5)

**Action:** rewrite the `DecisionMeta` code block in ADR-016 D8 to use `str | None` for `hypothesis_id` and `vk_id`, matching plan P1.6.5-3 §228-235. Add a one-paragraph deliberate-duplication rationale citing ADR-014 D5 + the constitutional `test_constitution_core_does_not_import_memory` guard P1.6.5-1 ships. The `# type: HypothesisId at memory layer` comment style from the plan is the right shape — preserve it in the ADR.

**Sketch:**

```python
class DecisionMeta(_BaseMeta):
    based_on: list[EventId] = Field(min_length=1)
    trade_offs: dict[str, str] = Field(default_factory=dict)
    # P1.6.5 / ADR-016 D8 — promotion-flavored decisions.
    # hypothesis_id + vk_id are `str | None` (not HypothesisId | VKId) per
    # deliberate-duplication rule (ADR-014 D5 precedent + constitutional
    # test_constitution_core_does_not_import_memory): core/event.py MUST NOT
    # import from memory/schema.py. memory/promotion.py constructs typed
    # HypothesisId/VKId, calls str(hyp_id) at metadata emit time.
    promotion: bool = False
    hypothesis_id: str | None = None    # semantic: HypothesisId
    vk_id: str | None = None            # semantic: VKId
```

**Why α (not β/γ)**: trivial absorb; ADR text → plan-correct shape. β (leave + add a note "ADR D8 specifies HypothesisId but impl uses str per layering") creates a known doc-vs-code drift that R0-A would catch again later. γ would re-open the layering question already settled in §5 S1.

### Y2 → α (ii) — `record_hypothesis` adds producer-time existence check for `source_event_ids`

**Action:** plan P1.6.5-2 `record_hypothesis` acceptance gains a new criterion: existence check on each `event_id` in `source_event_ids` before INSERT; raises (likely `MemoryStoreError` or new `EventNotFoundError`) if any missing. ADR-016 D2 line 155 ("integrity guarantee is at the Pydantic layer (validators reject non-existent event_ids at producer time via lookup)") is now honored by the impl rather than being a false claim.

**Sketch (plan P1.6.5-2 acceptance addition):**

> `record_hypothesis` runs `SELECT 1 FROM events WHERE id = ?` for each `event_id` in `source_event_ids` (or a batched `SELECT id FROM events WHERE id IN (...)` if list ≥3); raises `EventNotFoundError(event_id=<first-missing-id>)` if any are absent. No SQLite writes occur on missing-event failure. Test exercise: ≥2 tests covering (a) all event_ids exist → row inserted; (b) one event_id missing → exception raised + no row in `hypothesis` table.

**ADR-016 D2 amendment:**

Line 155 stays as written (the integrity guarantee is real per impl). Add one sentence: "`record_hypothesis` enforces this via per-event-id SELECT-existence check before INSERT (P1.6.5-2 acceptance)."

**Exception class choice (senior pin):** either `EventNotFoundError` in `memory/exceptions.py` (new; specific) or reuse a `MemoryStoreError` variant. Lean: new `EventNotFoundError(LookupError)` for specificity — mirrors `HypothesisNotFoundError` shape from P1.6.5-1.

**Why α(ii) over α(i)**: D2:155 already asserts the guarantee; current code shape doesn't honor it. (ii) is the minimum work to make D2:155 true rather than retract it. Architect picked (ii) explicitly.

### Y3 → α (a) — `DecisionMeta` gains schema-level `@model_validator` enforcing promotion-co-presence

**Action:** P1.6.5-3 `DecisionMeta` extension gains a `@model_validator(mode="after")` checking `promotion=True ⇒ hypothesis_id is not None AND vk_id is not None`; equivalently `(promotion, hypothesis_id is not None, vk_id is not None)` must be `(False, False, False)` OR `(True, True, True)`. Plan P1.6.5-3 acceptance §243 reverses: schema-level enforcement replaces "promotion.py's responsibility."

**Sketch:**

```python
from pydantic import model_validator

class DecisionMeta(_BaseMeta):
    based_on: list[EventId] = Field(min_length=1)
    trade_offs: dict[str, str] = Field(default_factory=dict)
    promotion: bool = False
    hypothesis_id: str | None = None
    vk_id: str | None = None

    @model_validator(mode="after")
    def _promotion_co_presence(self) -> "DecisionMeta":
        if self.promotion and (self.hypothesis_id is None or self.vk_id is None):
            raise ValueError(
                "promotion=True requires both hypothesis_id and vk_id"
            )
        if not self.promotion and (self.hypothesis_id is not None or self.vk_id is not None):
            raise ValueError(
                "hypothesis_id/vk_id forbidden when promotion=False"
            )
        return self
```

**Plan P1.6.5-3 acceptance updates:**

- Acceptance line 241-243 becomes: "`DecisionMeta(based_on=[evt_id], promotion=True, hypothesis_id=None, vk_id=None)` raises ValidationError at the `@model_validator` step. `DecisionMeta(based_on=[evt_id], promotion=False, hypothesis_id='hyp_xxx', vk_id=None)` also raises (forbidden non-None when not promotion). Co-presence is schema-enforced — no consumer-side defensive check needed."
- Test count addition: 4 new tests covering the 4 combinations (no-promo-with-IDs / no-promo-without-IDs / promo-with-IDs / promo-without-IDs).

**ADR-016 D8 amendment:**

Add a paragraph after the optional-defaulted-field rationale: "Co-presence is schema-enforced via `@model_validator`: `promotion=True ⇒ hypothesis_id + vk_id both set`; `promotion=False ⇒ both None`. This closes the forward-compat hazard from future producers emitting malformed promotion events."

**Why α(a) over α(b)/α(c)**: cheapest enforcement at the right layer; aligns with project's broader frozen-extra-forbid Pydantic discipline; catches malformed producers at `validate_metadata` step 0 inside `EventStore.append` (the earliest possible point in the writing path).

### Y4 → α (b) — `lookup_verified_knowledge` raises `ValueError` on empty `topic_tags`

**Action:** ADR-016 D6 changes empty-tags semantic from "matches zero rows" to "raises `ValueError`." Plan P1.6.5-4 `lookup.py` acceptance updates accordingly.

**Sketch — ADR-016 D6 updated paragraph:**

> `topic_tags=[]` raises `ValueError("topic_tags must be non-empty")`. Rationale: empty-tags is ambiguous between "I want all rows in scope" and "I haven't built my query yet"; raising makes the intent-mismatch fail loudly rather than silently return []. Consumers wanting "all rows in scope" use a separate API in a future cycle (no such consumer exists in P1.6.5; defer the API until one materializes). Replaces the prior "empty OR matches nothing, deliberately" semantic.

**Plan P1.6.5-4 acceptance updates:**

- Test line 315 becomes: "`lookup_verified_knowledge([], scope)`: raises `ValueError`; no SQLite reads occur."
- Add: "`lookup_verified_knowledge(topic_tags=[''], scope)`: empty-string in list — still raises if normalization detects (lean: not detected; empty-string is a valid tag at schema level)." (Senior decides edge-case handling at impl time.)

**Why α(b) over α(c)**: (b) protects against accidental empty-input typos; (c) matches filter-intuition but conflates "no filter" with "explicit lookup" — losing the explicit-intent signal. (b) is also smaller code surface (no separate "all in scope" branch). Architect picked (b) explicitly.

### Y5 → α (a) — Promotion event `room_id = room1.id` (originating-hypothesis room) confirmed

**Action:** ADR-016 D3 promotion contract gains an explicit paragraph naming the `room_id` choice. Plan P1.6.5-5 §349-354 "Promotion event room_id pin" stays as written. No code change.

**Sketch — ADR-016 D3 amendment (insert after the step 4 description):**

> **Promotion event `room_id` = originating Hypothesis's `room_id`** (architect-confirmed 2026-05-28 via routing). Rationale: preserves causal narrative — the room where the hypothesis was first recorded is also the room that surfaces the promotion event in its decision_log (ADR-015 D2 filter). For future cross-N-rooms matcher promotion (deferred per D7), the originating room of the first hypothesis row in the cluster carries the promotion event; alternative shapes (dedicated cross-room pseudo-room; multiple promotion events) are forward-amendment hooks should the cross-N-rooms case need richer attribution.

**Forward-amendment hook addition (ADR-016 hooks section):**

> **Cross-N-rooms matcher promotion attribution**: when D7 candidate-flag matcher lands, D3 promotion-event-`room_id` may need amendment toward (i) multi-event promotion (one per source room), (ii) dedicated `RoomType.CROSS_ROOM` pseudo-room, or (iii) accept-loss-of-fidelity by picking originating-room. Revisit at matcher ADR.

**Why α(a) over α(b)/(c)**: (b) over-engineers a new RoomType for a single use case that may not materialize; (c) writes 2 events per promotion (one per source room) — more event_store rows + decision_log clutter. (a) honors the single-source-room common case + names the forward-amendment hook for cross-N-rooms. Architect-confirmed.

### Y6 → α (small) — D4 non-atomicity `record_hypothesis` ↔ `hypothesis`-event added to forward-amendment hooks

**Action:** ADR-016 forward-amendment hooks section (lines 432-442) gains a new entry. No D4 code change; only inscription.

**Sketch (new bullet to add to forward-amendment hooks):**

> - **`record_hypothesis` ↔ `hypothesis` event atomicity** (deferred per D4 — no consumer requires it in P1.6.5): if a future consumer materializes that joins `memory.hypothesis` rows with event_store `hypothesis` events (e.g., a query that requires both writes to have landed or neither), D4 revisits toward an atomic producer API mirroring D11's `append_in_transaction` pattern (`record_hypothesis_with_event(content, ..., conn, event_store)` calling `event_store.append_in_transaction(...)` inside the same `with conn:` block). Until then, callers emit `hypothesis` events separately + accept eventual consistency.

**Why α (not β/γ)**: one-line inscription; closes the forward-compat naming gap; consistent with the other 7 forward-amendment hooks already in the section (each names a future condition + the revisit direction).

---

## Combined senior revision shape

Senior absorbs all 6 routings on `claude/P1.6.5-plan` in a single revision commit. Expected changes:

**ADR-016 amendments** (5 of 6 findings touch ADR text):
- D2 line 155: clarify integrity-guarantee enforcement (Y2 sub-text).
- D3: insert promotion-event-`room_id` paragraph (Y5).
- D6: rewrite empty-tags semantic from "matches zero rows" to "raises ValueError" (Y4).
- D8: code block → `str | None` + add `@model_validator` (Y1 + Y3) + co-presence rationale.
- Forward-amendment hooks: add 2 new entries (Y5 cross-N-rooms attribution hook + Y6 record_hypothesis atomicity hook).

**Plan P1.6.5 amendments** (4 of 6 findings touch plan text):
- P1.6.5-1 (`exceptions.py`): add `EventNotFoundError(LookupError)` class per Y2 sub-text.
- P1.6.5-2 (`store.py`): `record_hypothesis` acceptance gains existence-check criterion + 2 new tests per Y2.
- P1.6.5-3 (`core/event.py`): `DecisionMeta` gains `@model_validator` per Y3 + 4 new tests covering 4 (promotion, hyp_id, vk_id) combinations.
- P1.6.5-4 (`lookup.py`): acceptance line 315 → raises ValueError per Y4.
- P1.6.5-5 (e2e): step 5 + step 8 unchanged (Y5 confirmed senior pin; no test addition needed).
- P1.6.5-6 (landing): test delta expectation bumps by ~6-8 tests across atomics (Y2 + Y3 additions).

**Senior verifies on the revision commit**:
- ADR-016 D8 code block consistent with plan P1.6.5-3 (no `HypothesisId | None` anywhere in `core/event.py` text).
- `@model_validator` covers both directions (promo-without-IDs raises; no-promo-with-IDs raises).
- `record_hypothesis` existence-check tests cover happy + sad path.
- Forward-amendment hooks section reads coherent post-additions (Y5 + Y6 don't duplicate existing hooks).

**Verdict bump RC-10 protocol** (per `reviews/README.md` post-`6365cce` codification): senior bumps R0-A-on-plan frontmatter `needs_architect → clean` at revision commit via `verdict_history` append. Same protocol as P1.6 R0-A-on-plan absorption (5512749 era). **11th project use of RC-10 verdict-bump**; **5th under codified protocol**.

## Workflow state machine

Per ADR-008 Amendment 2 (W-005 Route B): state auto-advances `awaiting_architect_decision → awaiting_senior_revision` on commit of this routing file. Senior dispatches per CLAUDE.md self-organization on session start (matching state = `awaiting_senior_revision`).

## Pattern-recurrence notes

- **4 consecutive cycles of plan-stage α-only routing** (W-003 / P1.5.5 / P1.6 / P1.6.5 = 2 + 2 + 3 + 6 = 13 cumulative). The discipline gradient holds even as finding-count scales (P1.6.5's 6 Y is the largest plan-stage Y count to date).
- **First cycle with explicit sub-option AskUserQuestion**: Y2 + Y4 each had 2-3 sub-options under α; architect-partner asked architect to pick rather than silently default to reviewer lean. New pattern for "α with sub-option" cycles; consider codification if recurs in next 1-2 cycles.
- **ADR-text-finding density**: 5 of 6 findings touch ADR-016 text (Y1, Y2 sub-text, Y3, Y4, Y5, Y6). 1 finding (Y2 main fix) is plan-only. Senior revision is concentrated on the ADR (single revision focal point).
- **Internal-consistency catch** (Y1) is the kind of finding only an R0-A-on-plan with cross-artifact lens catches — plan and ADR contradicted each other within the same senior submission. Forward-implication: cross-artifact consistency check is a stable value-add of plan-stage R0-A; reinforces RC-9 dispatch discipline.

## Cross-references

- `docs/process/reviews/P1.6.5/R0-A-on-plan.md` — findings detail + verification cites.
- `docs/process/architect-briefs/P1.6.5.md` — architect-settled scope; deferrals; #7 (reuse decision EventType) informs Y5 confirmation.
- `docs/process/senior-plans/P1.6.5.md` §5 S1 + S2 — senior self-discoveries; §5 S1 layering rationale (Y1 absorption matches the rationale senior themselves wrote).
- `docs/decisions/ADR-016-cross-room-memory-persistence.md` — D2 + D3 + D6 + D8 + forward-amendment hooks all amended per routing.
- `docs/decisions/ADR-014-snapshot-contract.md` D5 — deliberate-duplication precedent cited by Y1 fix.
- `docs/decisions/ADR-008-workflow-state-machine.md` Amendment 2 (W-005 Route B) — state auto-advance on routing-file commit.
- `docs/process/reviews/README.md` § RC-10 verdict-bump protocol — senior bumps R0-A-on-plan verdict on absorption.
- `docs/process/reviews/P1.6/architect-routing.md` — most-recent precedent (P1.6 plan-stage routing 3α).
