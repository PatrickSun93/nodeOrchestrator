---
task_id: P1.6.5
round: R0-A-on-plan
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 17
verdict_history:
  - verdict: needs_architect
    at_commit: f9fac11
    findings_count: { red: 0, yellow: 6, green: 11 }
    note: original — 6 Y findings surfaced by architect-partner R0-A-on-plan (Y1 ADR D8 layering contradiction; Y2 source_event_ids integrity; Y3 DecisionMeta co-presence; Y4 lookup empty-tags semantic; Y5 promotion event room_id pin; Y6 record_hypothesis non-atomicity hook).
  - verdict: clean
    at_commit: HEAD
    findings_count: { red: 0, yellow: 0, green: 17 }
    note: senior revision absorbed all 6 α routings on this branch — ADR-016 amendments (D2 line 155 / D3 promotion room_id / D6 empty-tags ValueError / D8 str|None + @model_validator co-presence / forward-amendment hooks +2) + plan amendments (P1.6.5-1 EventNotFoundError / P1.6.5-2 existence-check + 2 tests / P1.6.5-3 @model_validator + 4 co-presence combination tests / P1.6.5-4 lookup empty-tags ValueError / P1.6.5-6 test delta updated). All 6 Y reclassified as 🟢 (Y1→🟢 / Y2→🟢 / Y3→🟢 / Y4→🟢 / Y5→🟢 / Y6→🟢) per RC-10. Cross-reference `docs/process/reviews/P1.6.5/architect-routing.md`.
---

> **RC-10 verdict bump (post-routing-revision)** — frontmatter as live signal. Bump applied after senior absorbed all 6 α routings from `architect-routing.md` (`be43650`) into this branch's revision commit. Per RC-10 codification (`docs/process/reviews/README.md` §RC-10), original findings preserved as audit trail below; verdict + findings_count + verdict_history updated; 11th project use of RC-10 verdict-bump; 5th under codified protocol.
>
> Absorption per finding:
> - **Y1 → 🟢 absorbed** — ADR-016 D8 code block updated to `str | None` with deliberate-duplication-per-ADR-014-D5 rationale.
> - **Y2 → 🟢 absorbed** — `record_hypothesis` gains producer-time `SELECT 1 FROM events` existence check raising `EventNotFoundError`; ADR-016 D2 line 155 amended to inscribe enforcement mechanism.
> - **Y3 → 🟢 absorbed** — `DecisionMeta` gains schema-level `@model_validator` enforcing `promotion=True ⇒ hypothesis_id + vk_id both set`; plan P1.6.5-3 acceptance reversed (schema-level enforcement replaces "promotion.py's responsibility").
> - **Y4 → 🟢 absorbed** — ADR-016 D6 empty-`topic_tags` semantic flips from "matches zero rows" to "raises `ValueError`"; plan P1.6.5-4 acceptance + lookup module-surface docstring updated.
> - **Y5 → 🟢 absorbed** — ADR-016 D3 gains explicit paragraph naming `room_id = originating Hypothesis's room_id` (architect-confirmed); forward-amendment hook added for cross-N-rooms attribution.
> - **Y6 → 🟢 absorbed** — ADR-016 forward-amendment hooks gain entry naming `record_hypothesis` ↔ `hypothesis` event atomicity revisit trigger.

# P1.6.5 R0-A-on-plan review (architect-partner lens)

| Field | Value |
|---|---|
| Round | R0-A-on-plan (plan-stage external review per RC-9 + brief architect-settled #9; load-bearing because ADR-016 governs every future cross-room agent + UI surface + matcher impl) |
| Reviewer | architect-partner (Claude Opus 4.7, 1M context) in primary session |
| Date | 2026-05-28 |
| Artifacts reviewed | `claude/P1.6.5-plan` @ `0ec0b86` — `docs/process/senior-plans/P1.6.5.md` (543 lines) + `docs/decisions/ADR-016-cross-room-memory-persistence.md` (459 lines, `Proposed`) + `docs/process/reviews/P1.6.5/external-r0b-prompt.md` (RC-15 dispatch artifact). Brief read on main @ `docs/process/architect-briefs/P1.6.5.md`. Cross-checked against runtime code: `core/event_store.py:40-272` (SCHEMA constant + `append` body + `with self.conn:` at :211), `core/event.py:60-145` (`EventType` 18-value vocabulary + `_BaseMeta` `extra="forbid"` + `DecisionMeta` fields), plus 5 `event_store.append` caller sites (`agents/dispatch.py:135`, `agents/snapshot_dispatch.py:62`, `agents/tool_dispatch.py:101`, `autonomy/emission.py:68 + :86`). |
| Workflow context | 13th task through the post-W-001 harness; first task post-P1.6 close; first cycle to share a SQLite file with the event store. Single-ADR cycle (simpler than P1.6's multi-ADR). Second plan to apply all 3 W-004-2 codified rules from plan stage. |
| Distinct from plan-vs-impl | Plan-vs-impl runs post-impl on the impl branch. This R0-A-on-plan focuses on: **ADR-016 D8 layering contradiction** (uses memory-layer ID NewTypes in core/event.py — violates the constitutional dep-direction guard P1.6.5-1 itself adds); **integrity model for `source_event_ids`** (Pydantic-only validation; no producer-time existence check); **`DecisionMeta` co-presence not enforced**; **lookup empty-tags semantic surprise**; **promotion event `room_id` pin** (borderline architect-level); independent verification of S1/S2 senior self-discoveries and the D11 transaction-atomicity mechanism. |

---

## Findings

### 🟡 Y1 — ADR-016 D8 violates the dep-direction layering rule it defends in plan §5 S1 + P1.6.5-1 constitutional guard

**Where:** `docs/decisions/ADR-016-cross-room-memory-persistence.md` D8 lines 309-313:

```python
class DecisionMeta(_BaseMeta):
    based_on: list[EventId] = Field(min_length=1)
    trade_offs: dict[str, str] = Field(default_factory=dict)
    promotion: bool = False
    hypothesis_id: HypothesisId | None = None   # set iff promotion=True
    vk_id: VKId | None = None                    # set iff promotion=True
```

vs. plan P1.6.5-3 lines 228-235 (which the senior themselves wrote and defended in §5 S1):

```python
class DecisionMeta(_BaseMeta):
    based_on: list[EventId] = Field(min_length=1)
    trade_offs: dict[str, str] = Field(default_factory=dict)
    promotion: bool = False
    hypothesis_id: str | None = None    # type: HypothesisId at memory layer
    vk_id: str | None = None            # type: VKId at memory layer
```

**Why it's a finding:**

ADR-016 D2 (line 56-58) places `HypothesisId` and `VKId` NewType aliases in `memory/schema.py`. ADR-016 D8 then writes `DecisionMeta` (in `core/event.py`) as `hypothesis_id: HypothesisId | None`. That requires `core/event.py` to `from orchestrator.memory.schema import HypothesisId, VKId`, which directly violates:

- The dep-direction rule the **senior themselves invokes in §5 S1** ("`core/event.py` MUST NOT import from `memory/schema.py` — same rule that yields `SummarySnapshotMeta` storing serialized dict[str, str] rather than `HypothesisRef`").
- The constitutional test `test_constitution_core_does_not_import_memory` that **P1.6.5-1 itself ships** (plan line 36, `tests/core/test_constitution.py` extension).
- The deliberate-duplication precedent the ADR cites (ADR-014 D5).

This is an **internal contradiction** inside the senior's own work — the plan code is correct (`str | None` with the typed-at-memory-layer comment), the ADR code is wrong. Cycle-2-during-impl risk: junior could implement either shape; whichever lands first prevents the other from being added.

**Fix:** ADR-016 D8 code block should use `str | None` matching the plan, with a one-line "deliberate-duplication per D5 / ADR-014 D5 precedent" rationale inscribed.

**Lean: α** (absorb — clean internal-consistency fix; senior already chose the right shape in the plan).

### 🟡 Y2 — `record_hypothesis` integrity model for `source_event_ids` unpinned; Pydantic only validates non-empty list

**Where:** ADR-016 D2 (lines 84-85) declares `source_event_ids: list[EventId] = Field(min_length=1)`. Plan P1.6.5-2 acceptance (lines 206-208) covers `confidence` boundary, `source_event_ids` min-length, empty `content`, and `room_id` FK enforcement — but **no producer-time existence check** for each `event_id` in `source_event_ids`. Brief pre-investigation note (cycle context) flagged "Pydantic validators reject non-existent event_ids at producer time via lookup"; the plan doesn't include this acceptance criterion.

**Why it's a finding:**

The schema-level FK can only reference single columns; `source_event_ids` is a JSON-stored list, so SQLite FK enforcement is out. Senior defended (ADR-016 D2 line 155): "integrity guarantee is at the Pydantic layer (validators reject non-existent event_ids at producer time via lookup)." But the actual code shape in plan P1.6.5-2 doesn't include this validator — `Hypothesis` only enforces `min_length=1` + type. A caller can pass `["evt_made_up"]` and the row persists with broken refs.

For P1.6.5 this is not load-bearing for any consumer (lookup doesn't traverse source_event_ids). For P1.7+ matcher or future cross-N-rooms reasoning, broken source-event refs would surface as silent data-integrity bugs.

**Architect call needed**: which integrity model?

- **(i) Document best-effort**: ADR-016 D2 explicitly says "no existence check at record time; caller's responsibility; broken refs are caller's data integrity bug." Cheapest; matches actual code shape.
- **(ii) Add producer-time existence check**: `record_hypothesis` runs `SELECT 1 FROM events WHERE id IN (...)` and raises if any missing. One extra query per record_hypothesis call. Honors the ADR D2 line 155 claim.
- **(iii) Defer to P1.7+ when matcher needs it**: ship as-is; revisit when consumer materializes.

**Lean: α toward (i) or (ii)** — either is a small ADR-016 D2 amendment + plan P1.6.5-2 acceptance update. Most defensible is (ii) since ADR D2 line 155 already asserts the guarantee; current code doesn't honor it.

### 🟡 Y3 — `DecisionMeta` co-presence `promotion=True ⇒ hypothesis_id + vk_id set` not enforced at any layer

**Where:** ADR-016 D8 (lines 311-312) doc-comments say "set iff promotion=True." Plan P1.6.5-3 acceptance line 243 explicitly says: "No co-presence constraint at schema level: `DecisionMeta(based_on=[evt_id], promotion=True)` (without hypothesis_id/vk_id) validates per schema; runtime enforcement of co-presence is `memory/promotion.py`'s responsibility (P1.6.5-4 acceptance)."

But `memory/promotion.py` is the only **producer**; the runtime enforcement is "promotion.py won't emit malformed events." There's no **consumer-side validator** that catches a malformed event after the fact. A future producer (e.g., a hypothetical "promotion-from-LLM" path or a script writing directly into the event_store SQLite) could emit `promotion=True` with `hypothesis_id=None`, and:

- ADR-015 decision_log consumer would silently include the event.
- A future cross-room agent reading promotion events would crash on `None.lookup(...)` or yield wrong results.

**Architect call needed**: which enforcement model?

- **(a) Schema-level Pydantic `@model_validator`** in `DecisionMeta` — enforces co-presence at validation time. Cost: ~5 LoC. Catches malformed producers at append time (via `validate_metadata` step 0 in `EventStore.append`).
- **(b) Consumer-side validator** in `derived/decision_log.py` (ADR-015 D2 filter) — skip / raise on malformed promotion entries. Doesn't catch producers; just protects consumers.
- **(c) Leave as-is** — accept "promotion.py is the only producer" as the de-facto invariant; document the producer monopoly in ADR-016 D10.

**Lean: α toward (a)** — schema-level enforcement is cheapest and most robust; aligns with the project's broader frozen-extra-forbid Pydantic discipline.

### 🟡 Y4 — `lookup_verified_knowledge(topic_tags=[], scope)` returns empty list — semantic surprise

**Where:** ADR-016 D6 line 279: "topic_tags=[] is a valid input — matches **zero rows** (empty OR matches nothing, deliberately; callers wanting 'all rows in scope' pass a sentinel or use a separate API in a future cycle — keeps lookup intent explicit)."

**Why it's a finding:**

Common consumer intuition: "I want all VKs in scope" → call `lookup_verified_knowledge([], VKScope.PERSONAL)` → expect all personal-scope rows. Senior pin: empty result. This is a defensible "explicit intent" semantic but:

1. The brief D6 architect-settled #6 doesn't pin empty-tags behavior — this is a new senior design choice not flagged for architect awareness.
2. The "future cycle adds a separate API for all-in-scope" lean creates a known sharp edge for first consumers.
3. Alternative: raise `ValueError("empty topic_tags")` to make the intent-mismatch fail loudly rather than silently return [].

**Architect call needed**:

- **(a) Keep as senior pinned**: empty tags = empty result (silent). Document the gotcha prominently in ADR-016 D6.
- **(b) Raise on empty**: `ValueError` — makes mistake loud.
- **(c) "All in scope"**: empty tags = match all rows in scope (the intuitive default; matches typical filter APIs).

**Lean: α toward (b) or (c)** — silent-empty (a) is the surprise mode; both (b) and (c) are clearer-intent alternatives. (b) protects against typos; (c) matches common-filter intuition.

### 🟡 Y5 — Promotion event `room_id` pin (Plan P1.6.5-5 "Promotion event room_id pin" section) — borderline architect-level decision

**Where:** Plan P1.6.5-5 lines 349-354 surface that the promotion `decision` event needs a `room_id` (event-stream invariant per `core/event_store.py:213`). Brief architect-settled #7 (reuse `decision` event) doesn't pin which room. Senior pin: `room_id = room1.id` (originating Hypothesis's `room_id`).

**Why it's a finding:**

The choice affects:
- Which room's **decision_log derived view** (ADR-015) surfaces the promotion. With `room1.id`, room1's decision_log lists the promotion; rooms 2 and 3 don't (even though they have a cross-room connection via the promoted VK).
- Cross-room reasoning narrative — is the promotion a fact about room1, room1+room2 (the rooms where the hypothesis was independently derived), or a user-level / global act?
- The `decision` event's `parent_id` (if set) and `based_on` references.

Senior frames this as "implementation-detail-implicit; e2e test pins the choice." But the choice is semantic — it determines what each room's decision history looks like.

**Architect call needed**:

- **(a) `room1.id` (originating room)** — senior lean. Causal narrative; decision_log naturally shows promotion.
- **(b) A dedicated cross-room / user / system pseudo-room** — would require a `RoomType.CROSS_ROOM` (senior considered, rejected as over-engineering for P1.6.5).
- **(c) Multiple events** — one decision event per source-room (writes 2 events in cross-N-rooms cases). Higher fidelity to "multiple rooms participated"; more events to consume.

**Lean: α toward (a)** — senior pin is reasonable for slice B (single-source-room is the common case); revisit if cross-N-rooms matcher materializes. Surface for architect confirmation rather than absorbing silently.

### 🟡 Y6 — `record_hypothesis` non-atomicity with `hypothesis` event emission — missing forward-amendment hook

**Where:** ADR-016 D4 lines 219-222: "`record_hypothesis` does NOT call `event_store.append`. If the caller wants a parallel `hypothesis` event in the canonical stream, they emit it separately; the two writes are NOT atomic in P1.6.5 (no consumer requires them to be)."

ADR-016 "Forward-amendment hooks" section (lines 432-442) lists 7 conditions for revisit; **none** cover the `record_hypothesis` ↔ `hypothesis-event` atomicity question.

**Why it's a finding:**

D4 is defensible for P1.6.5's consumer set (no consumer joins memory.hypothesis rows with event_store hypothesis events). But the lack of atomicity is a forward-compat hazard: any future consumer that does join the two would observe inconsistent state if a producer crashes between the two writes. The forward-amendment hook should name this scenario so future cycles know to revisit.

**Lean: α (small)** — add to forward-amendment hooks: "If a consumer materializes that requires `record_hypothesis` + `hypothesis` event atomicity, D4 revisits toward an atomic producer API (mirroring D11's `append_in_transaction` pattern)."

---

### 🟢 G1 — Slice B scope (ADR-016 D1) — matches brief architect-settled #1 verbatim

Hypothesis + VK primary, Entity schema-only stub, ProjectArchive deferred. Rationale (consumer-driven trigger for ProjectArchive; forward-compat win for Entity stub) is sound. Inscribed in D1 with explicit deferral language matching W-004-2 (c) literal-reading discipline.

### 🟢 G2 — D11 transaction-atomicity mechanism (option A `append_in_transaction` split) — well-considered, minimal API growth

ADR-016 D11 considers 4 options (A split, B inline-INSERT bypass, C SAVEPOINT, D direct conn access) and lands on A with clear rationale per alternative. Verified against `core/event_store.py:211` — `with self.conn:` wraps body, validation step 0 is outside, so the split point is clean. Existing 5 callers (verified: `agents/dispatch.py:135`, `snapshot_dispatch.py:62`, `tool_dispatch.py:101`, `autonomy/emission.py:68 + :86`) all go through the thin wrapper `append()` → unchanged behavior. The new public method `append_in_transaction` is one API-surface-area cost, acknowledged in Consequences.

### 🟢 G3 — D5 schema-init placement deviation from brief D5 wording — well-surfaced and well-defended

Brief D5 wording read literally would place memory DDL in `core/event_store.py` SCHEMA constant. Senior caught this in pre-investigation (S1) and pinned a clean `memory.store.init_memory_schema(conn)` separate function, preserving the `core/`-no-import-from-`memory/` layering invariant + ADR-014 D5 deliberate-duplication precedent. Implementation-level pin that doesn't contradict any architect-settled scope.

### 🟢 G4 — D7 candidate-flag column ships without matcher — strong push-back-#3 defense

Schema migration tooling doesn't exist (verified by senior pre-investigation: no `migrations/`, no alembic). Ship-now cost is 1 INTEGER column with default 0; defer-cost is a future migration project. No defensive thin matcher (exact-string match would create false confidence per push-back #8 rejection). Clean stay-untouched-this-cycle discipline.

### 🟢 G5 — D9 `VK.contradictions: list[VKId]` (VK-to-VK refs) — clean pin where handoff §4.5 was opaque

Senior considered 3 candidates (Hypothesis IDs, source event IDs, VK IDs); landed on VK-to-VK with sound rationale (VKs are the verified-and-cross-room-addressable layer; hypothesis-rejection lifecycle is via `status` enum; event-stream contradictions are handled by metadata cite chains per ADR-014 D2.1). Field ships with default `[]`; no producer this cycle (acknowledged); future contradiction-detector writes it.

### 🟢 G6 — D8 reuse `decision` event type instead of new `EventType.PROMOTION` — defended per push-back #6 + constitutional-vocabulary minimalism

Reuse-via-`DecisionMeta`-extension defended per: (i) promotion IS a user decision per `handoff.md` §4.5 (b); (ii) constitutional 18-type vocabulary at `core/event.py:69-75` treats type-set as load-bearing; (iii) ADR-015 D2 decision_log filter includes promotion events for free. Optional-defaulted fields preserve backward-compat for existing decision producers and consumers. Cost (slight DecisionMeta pollution) is acknowledged + bounded with explicit "revisit toward dedicated EventType if 3+ more conditional flags accumulate" forward-amendment hook.

### 🟢 G7 — Execution order parallel set (P1.6.5-1 ‖ P1.6.5-3) — file-disjoint per careful reading

P1.6.5-1 touches `src/orchestrator/memory/` (new package) + `tests/memory/` (new) + `tests/{core,agents,rooms,derived}/test_constitution.py` (extensions). P1.6.5-3 touches `src/orchestrator/core/event.py` + `tests/core/test_event.py`. Different test files in `tests/core/`; no source file overlap. Deliberate-duplication invariant (P1.6.5-3 doesn't import from `memory/schema.py`) makes P1.6.5-3 implementable from ADR-016 D8 spec alone. RC-17 parallelism discipline holds.

### 🟢 G8 — W-004-2 codified rules applied at plan stage — (a) verification cites concrete + (b) promotion-impact grep concrete + (c) literal-reading enumerated

§5 verification cites resolve to specific Read / grep locations (verified: `core/event.py:69-95` ✓, `core/event.py:135-145` ✓, `core/event_store.py:185-272` ✓, `core/event_store.py:211` ✓). Promotion-impact grep on `EventStore.append` callers (5 sites) verified independently — all 5 match (no false positives). Literal-reading deferrals enumerated explicitly (Entity stub, ProjectArchive, matcher, external ground-truth, UI, Hypothesis auto-mirror, tool execution).

### 🟢 G9 — 6 atomic tasks with clean per-atomic boundaries; tracking-table → commit-subject mapping per RC-17

6 atomics → 6 commits (P1.6.5-1 through P1.6.5-6); per-atomic commit subjects pinned in plan §3. No bundling. Each atomic has its own out-of-scope section enumerating what stays untouched. Sequential rationale (P1.6.5-2 → -4 → -5 → -6) holds: each step has a concrete prior-step dependency.

### 🟢 G10 — Push-back resolutions §5 close all 8 brief invitations with concrete reasoning

Each push-back gets a senior position + rationale + "no push-back" or "implementation pin" verdict. No push-backs are silently dropped. #6 (promotion event type) resolves via implementation pin (DecisionMeta extension D8) rather than override — proper RC-9 pattern (senior addresses the technical gap without re-routing the architect-settled scope).

### 🟢 G11 — S1 + S2 senior self-discoveries — well-surfaced as implementation-level pins (not architect-decisions)

Both are flagged in plan §5 with explicit "implementation-level pin; does not contradict any architect-settled decision" framing. S1 (schema-init placement) and S2 (transaction-atomicity mechanism) are the right places for a senior to surface gaps the brief didn't pin without silent improvisation. Verification cites accompany each (`core/event_store.py:48-102` + `:185-272` + `:211` + 5 caller sites + ADR-014 D5 precedent). Matches the post-W-004-2 (a) discipline.

---

## Verdict

**`needs_architect`** — 0🔴 / 6🟡 / 11🟢.

### Routing surface for architect

- **Y1 (ADR D8 layering contradiction)** — clean catch; senior already wrote the right shape in plan §233 + §5 S1. Lean **α (absorb)**: ADR-016 D8 code block updates to `str | None` with deliberate-duplication rationale (mirror ADR-014 D5).
- **Y2 (`source_event_ids` integrity model)** — Lean **α** toward (ii) producer-time existence check (honors the ADR D2 line 155 claim) **or** (i) document best-effort. Architect call between the two.
- **Y3 (DecisionMeta co-presence)** — Lean **α** toward (a) schema-level `@model_validator` (cheapest; aligns with project's frozen-extra-forbid discipline).
- **Y4 (lookup empty-tags semantic)** — Lean **α** toward (b) raise on empty **or** (c) match all in scope; current (a) silent-empty is the surprise mode.
- **Y5 (promotion event `room_id` pin)** — Lean **α** toward (a) senior's pin (`room1.id`); surface confirmation rather than absorb silently because the choice is semantic-level not pure implementation.
- **Y6 (forward-amendment hook for `record_hypothesis` non-atomicity)** — Lean **α (small)**; one-line addition to D4 forward-amendment hooks.

**No 🔴 blockers**. The plan + ADR are otherwise high-quality: D11 atomicity mechanism is well-considered (G2), S1+S2 self-discoveries are correctly framed as implementation-level pins (G11), W-004-2 codified rules applied throughout (G8), execution-order parallelism is file-disjoint (G7), and the 8 brief push-backs are all addressed with concrete reasoning (G10).

Per ADR-008 Amendment 2 (W-005 Route B): state advances to `awaiting_senior_revision` after architect routing artifact commits.

## Cross-references

- `docs/process/architect-briefs/P1.6.5.md` — settled-decisions source (5 architect-partner ↔ architect forks accepted 2026-05-28).
- `docs/process/senior-plans/P1.6.5.md` §5 — push-back resolutions + S1 + S2 (all reviewed against brief + runtime code).
- `docs/decisions/ADR-016-cross-room-memory-persistence.md` — 11 decisions reviewed (D1-D11); Y1 + Y2 + Y6 are ADR-text findings; Y3 + Y4 are ADR contract findings; Y5 is plan-only finding.
- `docs/decisions/ADR-014-snapshot-contract.md` D5 — deliberate-duplication precedent (cited by senior §5 S1; ADR-016 D8 should follow same shape per Y1).
- `docs/decisions/ADR-015-decision-log-shape.md` D2 — decision_log filter set (promotions appear automatically via D8 reuse).
- `docs/process/dual-lens-r0b.md` RC-15 — dual-lens dispatch criteria (3 of 4 met per brief #10; external R0-B prompt artifact present).
- `docs/process/senior-planner.md` § Pre-investigation discipline (W-004-2 codified) — (a) + (b) + (c) all applied at plan stage; second plan after P1.6.
- `src/orchestrator/core/event_store.py:48-102 + :185-272 + :211` — runtime cites verified for S1 + S2 + G2.
- `src/orchestrator/core/event.py:69-95 + :135-145` — runtime cites verified for D8 reuse rationale + DecisionMeta extension shape.
- 5 `event_store.append` caller sites verified: `agents/dispatch.py:135`, `agents/snapshot_dispatch.py:62`, `agents/tool_dispatch.py:101`, `autonomy/emission.py:68 + :86` (G2).
