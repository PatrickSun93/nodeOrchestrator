# ADR-016: Cross-room memory persistence — Hypothesis + VerifiedKnowledge tables + user-confirm promotion + cross-room lookup (slice B)

**Status:** Proposed — 2026-05-28 · Amended — 2026-05-28 (plan-stage R0-A-on-plan routing absorption: D2 `source_event_ids` producer-time existence-check inscription [Y2 → α (ii)], D3 promotion-event `room_id` inscription [Y5 → α (a)], D6 empty-`topic_tags` `ValueError` semantic [Y4 → α (b)], D8 code block `str | None` deliberate-duplication + `@model_validator` co-presence enforcement [Y1 → α + Y3 → α (a)], forward-amendment hooks +2 entries [Y5 cross-N-rooms attribution + Y6 record_hypothesis ↔ event atomicity] — per `docs/process/reviews/P1.6.5/architect-routing.md`).
**Scope:** Locks the schema vocabulary, producer contract, promotion contract, transaction-atomicity model, storage placement, candidate-flag column semantic, cross-room lookup contract, and VK cross-reference semantic for the `memory/` package — slice B (Hypothesis + VerifiedKnowledge primary; Entity schema-only stub; ProjectArchive deferred). Governs every future cross-room agent + UI surface consuming memory + every future producer that writes a Hypothesis row or invokes promotion. Does not govern Snapshot (ADR-014) or DecisionLog (ADR-015) derived views; those remain pure-function code-decided derivations over the event stream.

## Context

`handoff.md` §4.5 declared four cross-room memory data classes at P0 — `Hypothesis`, `VerifiedKnowledge`, `Entity`, `ProjectArchive` — as schema-only sketches. No persistence layer, no producer, no consumer has materialized since: the schemas have been the project's longest-running "no orphan spec" debt (Principle 9 inverse — vocabulary that has been declared but never inscribed in code), 5+ months old by P1.6.5 dispatch time.

P1.6 closed the room-internal derived view layer (ADR-014 snapshot, ADR-015 decision log) — both pure-function derivations over the event stream, no persistence beyond `summary_snapshot` events. P1.6.5 opens the cross-room layer: persistence tables that survive room close, addressable across room boundaries, with a promotion path from candidate Hypothesis → VerifiedKnowledge.

**Three forces shape this ADR:**

1. **Principle 1 (event log is truth)** — memory tables are **derived-but-persisted** convenience indexes; the canonical authority is the event stream. Promotion writes a `decision` event into the event stream (so the act is in the canonical log); the VK row is a queryable cache enabling cross-room reads without re-scanning every event in every closed room.
2. **Principle 5 (code-driven decisions, LLM-generated content)** — promotion eligibility is code per `handoff.md` §3.1 ("晋升资格判定 = 代码"). No LLM judgment may live in `memory/`. Constitutional test extends.
3. **Principle 9 (no orphan spec)** — three of the four schemas materialize this cycle (Hypothesis + VK in full; Entity as forward-compat stub). ProjectArchive defers because its consumer (room re-entry per chat-history "离开/回来对称") has no surface yet.

The architect-partner brief settled 11 design decisions (slice B scope, promotion subset, producer pattern, storage placement, lookup contract, event-type reuse, e2e scope, dispatch criteria) via a 2026-05-28 architect-partner ↔ architect discussion (5 forks surfaced, 5 leans accepted without architect override). Senior pre-investigation per W-004-2 (a) claims-without-cites + (b) promotion-impact grep + (c) architect-deferral literal-reading surfaced three implementation-level gaps in the architect-settled set:

- **Transaction-atomicity mechanism (architect-settled #4 + brief pre-investigation "Promotion transaction boundaries")**: `EventStore.append` uses `with self.conn:` internally (`src/orchestrator/core/event_store.py:211`), which on Python sqlite3's default isolation level begins-and-commits its own transaction. A naive `with conn: ... event_store.append(...) ... INSERT VK ...` wrapper from `memory/promotion.py` would either nest-commit incorrectly OR silently drop atomicity. ADR-016 D11 pins the resolution.
- **Schema-init placement (architect-settled #4 + brief D5 "extend event-store init SQL")**: the architect-settled invariant is "same SQLite file" (atomicity + operational simplicity); the brief's wording "extend event-store init SQL" reads as "add the 3 memory tables to the SCHEMA constant in `core/event_store.py`." But `core/` MUST NOT know about `memory/` per layering (same rule that yields ADR-014 D5 deliberate-duplication). ADR-016 D5 pins `memory.store.init_memory_schema(conn)` as a separately-callable init function in `memory/`; callers run it alongside `EventStore.init_schema(conn)` on the same connection.
- **`DecisionMeta` schema accommodates promotion (architect-settled #7 + push-back #6)**: `DecisionMeta` at `src/orchestrator/core/event.py:135-145` has `extra="forbid"`. A `promotion: True` metadata flag (brief architect-settled #7 wording) would fail validation. ADR-016 D8 pins the resolution: extend `DecisionMeta` with three optional defaulted fields (`promotion: bool = False`, `hypothesis_id: EventId | None = None`, `vk_id: str | None = None`); existing decision producers and consumers are unaffected (defaults preserve current shape).

Touches Principle 1 (event log remains canonical; promotion writes a decision event), Principle 5 (memory module has no LLM imports — constitutional test enforces), Principle 9 (3 of 4 §4.5 schemas inscribed; Entity stub captures-now to avoid future migration; ProjectArchive defers with consumer-driven rationale).

**Hard requirements**:
- Promotion is **atomic**: VK insert + Hypothesis row update + `decision` event append succeed together or none; partial-state outcomes forbidden.
- Promotion is **explicit-only**: no path exists where an event triggers automatic promotion. `handoff.md` §4.5 "不自动晋升" invariant — code enforces.
- `core/` MUST NOT import from `memory/`; `memory/` MAY import from `core/`. Constitutional tests guard both directions.
- `memory/` MUST NOT import any LLM dependency (anthropic SDK, openai SDK, `LLMRouter`, `llm_router`). Constitutional test extends.
- VK + Hypothesis + Entity Pydantic models: frozen + `extra="forbid"` per project schema-invariant pattern.
- Lookup is **deterministic**: same inputs → same output ordering; `last_validated` descending; ties broken by `id` lex.
- Storage co-locates memory tables in the event_store SQLite file (D5). Same connection enables single-transaction atomicity (D11).

## Decisions

### 1. Slice B scope: Hypothesis + VerifiedKnowledge primary; Entity schema-only stub; ProjectArchive defer

P1.6.5 ships:
- `Hypothesis` Pydantic model + `hypothesis` SQLite table + `record_hypothesis(...)` producer API + status lifecycle (`pending → verified | rejected | stale`).
- `VerifiedKnowledge` (VK) Pydantic model + `verified_knowledge` SQLite table + creation only via promotion (no standalone constructor API in P1.6.5).
- `Entity` Pydantic model + `entity` SQLite table — **schema-only stub**. No producer API, no consumer API beyond the schema; the table + model ship to avoid future migration when an Entity producer/consumer surface materializes (forward-compat rationale, mirrors ADR-014 D2 vocabulary capture-now).

P1.6.5 does NOT ship:
- `ProjectArchive` model + table. Per-room semantic; cross-room search not applicable; consumer (room re-entry experience per chat-history "离开/回来对称") has no surface. Defer until a re-entry consumer materializes.
- Full Entity lifecycle (creation API, references from Hypothesis/VK evidence fields). Defer until producer/consumer surfaces materialize.

**Why slice B**: Hypothesis + VK is the **canonical promotion path** (`handoff.md` §4.5 "待验证 pool" → "已验证(参与跨房间检索)") and the e2e validation target. ProjectArchive's deferral has a clean consumer-driven trigger; Entity's stub is a tiny migration-cost-now investment. The fourth class (ProjectArchive) ships when its time comes; defer-with-rationale beats ship-with-no-consumer (Principle 9 inverse-risk).

### 2. Schema vocabulary — 3 Pydantic models + 3 SQLite tables; frozen + `extra="forbid"`

`src/orchestrator/memory/schema.py`:

```python
# --- IDs ---
HypothesisId = NewType("HypothesisId", str)  # format: "hyp_<32-hex>"
VKId = NewType("VKId", str)                  # format: "vk_<32-hex>"
EntityId = NewType("EntityId", str)          # format: "ent_<32-hex>"

# --- Status enums ---
class HypothesisStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    STALE = "stale"

class VKScope(StrEnum):
    PERSONAL = "personal"
    TEAM = "team"
    GLOBAL = "global"

class EntityType(StrEnum):
    PERSON = "person"
    PROJECT = "project"
    CONCEPT = "concept"
    PAPER = "paper"

# --- Models ---
class Hypothesis(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: HypothesisId
    content: str = Field(min_length=1)
    room_id: RoomId
    confidence: float = Field(ge=0.0, le=1.0)
    source_event_ids: list[EventId] = Field(min_length=1)
    status: HypothesisStatus = HypothesisStatus.PENDING
    candidate_for_promotion: bool = False     # D7 — matcher deferred
    created_at: TimestampMs

class VerifiedKnowledge(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: VKId
    content: str = Field(min_length=1)
    topic_tags: list[str] = Field(default_factory=list)   # OR-semantics filter; D6
    evidence: dict[str, Any] = Field(default_factory=dict)
    last_validated: TimestampMs
    contradictions: list[VKId] = Field(default_factory=list)  # D9 — VK-to-VK refs
    scope: VKScope
    promoted_from_hypothesis_id: HypothesisId
    promoted_by_user_id: str = Field(min_length=1)
    promotion_event_id: EventId        # the `decision` event id; D3

class Entity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: EntityId
    type: EntityType
    attributes: dict[str, Any] = Field(default_factory=dict)
    created_at: TimestampMs
```

`memory/store.py` SQLite tables (TEXT-stored JSON for dict/list fields per `handoff.md` §5.8 SQLite-stdlib pattern):

```sql
CREATE TABLE IF NOT EXISTS hypothesis (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    room_id TEXT NOT NULL,
    confidence REAL NOT NULL,
    source_event_ids TEXT NOT NULL,          -- JSON list[str]
    status TEXT NOT NULL DEFAULT 'pending',
    candidate_for_promotion INTEGER NOT NULL DEFAULT 0,  -- bool
    created_at INTEGER NOT NULL,
    FOREIGN KEY (room_id) REFERENCES rooms(id)
);
CREATE INDEX IF NOT EXISTS idx_hypothesis_room
    ON hypothesis(room_id);
CREATE INDEX IF NOT EXISTS idx_hypothesis_status_candidate
    ON hypothesis(status, candidate_for_promotion);

CREATE TABLE IF NOT EXISTS verified_knowledge (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    topic_tags TEXT NOT NULL,                -- JSON list[str]
    evidence TEXT NOT NULL DEFAULT '{}',     -- JSON dict
    last_validated INTEGER NOT NULL,
    contradictions TEXT NOT NULL DEFAULT '[]',  -- JSON list[str]
    scope TEXT NOT NULL,
    promoted_from_hypothesis_id TEXT NOT NULL,
    promoted_by_user_id TEXT NOT NULL,
    promotion_event_id TEXT NOT NULL,
    FOREIGN KEY (promoted_from_hypothesis_id) REFERENCES hypothesis(id),
    FOREIGN KEY (promotion_event_id) REFERENCES events(id)
);
CREATE INDEX IF NOT EXISTS idx_vk_scope_last_validated
    ON verified_knowledge(scope, last_validated DESC);

CREATE TABLE IF NOT EXISTS entity (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    attributes TEXT NOT NULL DEFAULT '{}',   -- JSON dict
    created_at INTEGER NOT NULL
);
```

**Why no relations to event log foreign-keyed beyond `promotion_event_id` and `source_event_ids`**: Hypothesis.source_event_ids stores a JSON list, not a FK, because SQLite FKs target single columns. The integrity guarantee is at the Pydantic layer (validators reject non-existent event_ids at producer time via lookup). **`record_hypothesis` enforces this via per-event-id `SELECT 1 FROM events WHERE id IN (...)` existence check before INSERT (P1.6.5-2 acceptance per Y2 → α (ii) routing); missing event raises `EventNotFoundError(LookupError)` from `memory/exceptions.py` and no row is written.** `promotion_event_id` IS FK-enforceable (single column) and gets the FK constraint to make orphan promotions impossible at the schema level.

**Why no `topic_tags` table normalization**: tags are denormalized as a JSON list per VK row. P1.6.5 has 1 query pattern (`scope` filter + `topic_tags` OR-match); join overhead is not justified by the single consumer. Reshape to normalized form when ≥2 distinct query patterns emerge.

### 3. Promotion contract — `promote_hypothesis(hyp_id, user_id, *, evidence=None, scope, conn) -> VerifiedKnowledge`

Single function in `src/orchestrator/memory/promotion.py`. Atomic 3-step transaction (D11 pins atomicity mechanism):

```python
def promote_hypothesis(
    hyp_id: HypothesisId,
    user_id: str,
    *,
    scope: VKScope,
    topic_tags: list[str] | None = None,
    evidence: dict[str, Any] | None = None,
    conn: sqlite3.Connection,
    event_store: EventStore,
) -> VerifiedKnowledge:
    """User-confirm promotion of a Hypothesis row → VerifiedKnowledge row.

    Atomic over: VK insert + Hypothesis.status='verified' update + decision
    event append. See D11 for the transaction-atomicity mechanism. Raises
    HypothesisNotFoundError, PromotionEligibilityError, or propagates
    EventStore errors per D7-style propagation.
    """
```

Transaction sequence (per D11):
1. Load Hypothesis row by `hyp_id`. Raise `HypothesisNotFoundError` if absent.
2. Check eligibility: `Hypothesis.status == PENDING`. Raise `PromotionEligibilityError(reason="not_pending")` otherwise. **No other gate** — user-confirm is the eligibility. (Cross-N-rooms candidate flag (D7) is NOT a precondition in P1.6.5 — the matcher defers; user can promote any pending hypothesis.)
3. Construct `DecisionMeta` with `based_on=hypothesis.source_event_ids`, `promotion=True`, `hypothesis_id=hyp_id`, `vk_id=<generated>` (D8).
4. Append `decision` event via `event_store.append(...)`. The `decision` event's `based_on` cites the original source events (≥1 per `DecisionMeta` constraint at `core/event.py:144`).
5. INSERT VK row.
6. UPDATE Hypothesis row: `status='verified'`.

All steps land in a single SQLite transaction per D11 (no partial state on any failure).

**Promotion event `room_id` = originating Hypothesis's `room_id`** (architect-confirmed 2026-05-28 via Y5 → α (a) routing). The `decision` event constructed at step 4 uses `room_id = hypothesis.room_id` — i.e., the room where the hypothesis was first recorded. Rationale: preserves causal narrative — the room where the hypothesis was first recorded is also the room that surfaces the promotion event in its `decision_log` derived view (ADR-015 D2 filter). For future cross-N-rooms matcher promotion (deferred per D7), the originating room of the first hypothesis row in the cluster carries the promotion event; alternative shapes (dedicated `RoomType.CROSS_ROOM` pseudo-room; multiple promotion events one per source room) are forward-amendment hooks should the cross-N-rooms case need richer attribution.

**Why `based_on=hypothesis.source_event_ids`**: `DecisionMeta.based_on: list[EventId] = Field(min_length=1)`. Promotion IS a decision based on the original observations; reusing the hypothesis's source events as the decision's `based_on` is semantically clean and satisfies the ≥1 constraint. For future cross-N-rooms promotion (matcher deferred), the union of source_event_ids across N hypothesis rows is the natural `based_on`.

**Why no LLM eligibility gate**: `handoff.md` §3.1 "晋升资格判定 = 代码"; eligibility is `status == PENDING` (a column read), enforced by code, not LLM judgment. Constitutional test extends.

### 4. Producer contract — `record_hypothesis` is the explicit producer; no auto-mirror from `hypothesis` events

Single function in `src/orchestrator/memory/store.py`:

```python
def record_hypothesis(
    content: str,
    room_id: RoomId,
    source_event_ids: list[EventId],
    confidence: float,
    *,
    conn: sqlite3.Connection,
    now: TimestampMs | None = None,
) -> Hypothesis:
    """Record a new Hypothesis row. Pure producer — no event_store side effect.

    Caller chooses when to also emit a `hypothesis` event into the event stream
    (if at all). Memory table and event stream are NOT auto-synced.
    """
```

**No automatic event-stream → memory-table sync**. The `hypothesis` event type at `core/event.py:79` may continue to be emitted by agents as a transient/low-confidence cognitive signal; only the calls to `record_hypothesis(...)` create memory-table rows. Producer's choice.

**Why explicit**: same intuition as ADR-014 D3 ("snapshot is producer-triggered, not event-triggered"). Auto-mirroring would couple persistence semantics to every `hypothesis` event (transient candidates, mid-discussion edits, low-confidence probes — all of which would clutter the memory table). Explicit API keeps producer choice with the caller.

`record_hypothesis` does NOT call `event_store.append`. If the caller wants a parallel `hypothesis` event in the canonical stream, they emit it separately; the two writes are NOT atomic in P1.6.5 (no consumer requires them to be).

**Confidence default**: required field (no default); caller specifies. Per pre-investigation: `handoff.md` §4.5 has no default; making it required forces producers to choose deliberately rather than ship a hidden 0.5 (which would distort downstream confidence-weighted queries that may materialize in P1.7+).

### 5. Storage — same SQLite file as event_store; `memory.store.init_memory_schema(conn)` owns memory table DDL (NOT `core/event_store.py`)

Memory tables co-locate with the event_store tables in the same SQLite database file. Same connection (`sqlite3.Connection`) wraps both. **Architect-settled #4 invariant preserved**: atomicity + operational simplicity + single migration path.

**Schema-init placement — senior pin deviates from brief D5 wording**:

The brief says "extend the event-store init SQL with `CREATE TABLE IF NOT EXISTS` for the 3 new tables." Read literally, this places memory-table DDL in the `SCHEMA` constant at `core/event_store.py:48-102`, which would mean `core/` knows about `memory/` table shapes — violating the layering invariant that yields ADR-014 D5 deliberate-duplication and the constitutional `test_constitution_core_does_not_import_agents` / `_autonomy` / `_rooms` / `_skills` / `_derived` / (new) `_memory` pattern.

ADR-016 D5 pins the cleaner shape:

- `core/event_store.py` SCHEMA constant is unchanged. `EventStore.init_schema(conn)` runs only the event-stream + relations tables/indexes/triggers.
- `memory/store.py` exports `init_memory_schema(conn: sqlite3.Connection) -> None` that runs the 3 memory tables' `CREATE TABLE IF NOT EXISTS` + indexes on the **same connection**.
- Callers (tests, future runtime) init both schemas on one connection:

  ```python
  conn = sqlite3.connect(db_path)
  event_store = EventStore(conn)
  event_store.init_schema()        # events, rooms, relations
  init_memory_schema(conn)         # hypothesis, verified_knowledge, entity
  ```

- Both schema-init functions are idempotent (`CREATE TABLE IF NOT EXISTS`). Calling order is `event_store.init_schema` first (memory tables FK-reference `events` and `rooms` per D2). The FK enforcement requires the referenced tables to exist; init order matters.

**Architect-settled #4 atomicity invariant preserved**: same connection, single SQLite file, single transaction possible across event + memory writes (D11). The migration story for existing event_store DBs (e.g., from P1.6 tests on disk): on first `init_memory_schema(conn)` call against a pre-P1.6.5 DB, `CREATE TABLE IF NOT EXISTS` for the 3 memory tables succeeds; existing events/rooms/relations tables are untouched. Forward-compat clean.

**Why not place memory DDL in core/event_store.py SCHEMA**:
- `core/` already enforces no-import-from-{agents, autonomy, derived, rooms, skills} (constitutional tests). Adding `_memory` to that set is the natural extension.
- `core/event_store.py` is the event-stream contract (ADR-001). Adding memory-table DDL conflates two concerns: events vs derived persistence.
- ADR-014 D5 set the precedent: typed event metadata DUPLICATES derived classes rather than importing — same logic applies to memory schema DDL placement.

### 6. Cross-room lookup contract — `lookup_verified_knowledge(topic_tags, scope, *, conn) -> list[VerifiedKnowledge]`

Single function in `src/orchestrator/memory/lookup.py`:

```python
def lookup_verified_knowledge(
    topic_tags: list[str],
    scope: VKScope,
    *,
    conn: sqlite3.Connection,
) -> list[VerifiedKnowledge]:
    """Cross-room lookup of verified knowledge.

    Filters:
      - scope: exact match on VKScope.
      - topic_tags: OR-semantics ("any input tag matches any row tag").
    Ordering: last_validated DESC; ties broken by id lex ASC.
    No ranking / similarity / LLM augmentation in P1.6.5.
    """
```

Semantics:
- `scope` is filtered first (covered by `idx_vk_scope_last_validated`).
- `topic_tags=[]` raises `ValueError("topic_tags must be non-empty")` (per Y4 → α (b) routing). Rationale: empty-tags is ambiguous between "I want all rows in scope" and "I haven't built my query yet"; raising makes the intent-mismatch fail loudly rather than silently return `[]`. Consumers wanting "all rows in scope" use a separate API in a future cycle (no such consumer exists in P1.6.5; defer the API until one materializes). Replaces the prior "empty OR matches nothing, deliberately" semantic.
- `topic_tags=["a","b"]` matches any VK row where `"a" in row.topic_tags OR "b" in row.topic_tags`. Implementation: scan the rows in scope, JSON-parse `topic_tags`, set-intersection check. (SQLite has no native list-overlap operator; JSON1 functions are not assumed. Row count per scope is expected small at P1.6.5; reshape to JSON1 / normalized-tag-table when row count crosses a threshold to be defined at amendment time.)
- Result ordering: `last_validated DESC, id ASC`. Deterministic across runs given a fixed input row set.
- **No ranking, no similarity, no LLM**. Pure code per Principle 5.

**Why OR-semantics for `topic_tags`**: the brief lean. Consumer intent — "I'm asking about X or Y; show me VKs touching either" — favors OR over AND. AND-semantics would yield too-narrow results in early use; OR is the recoverable default (consumers can post-filter for AND if needed).

**Why `last_validated DESC`**: most-recently-validated knowledge is the most-likely-still-correct knowledge; ranking by recency satisfies the consumer mental model without introducing similarity scoring (which would require LLM).

**Why scope is filtered first**: index-aligned (`idx_vk_scope_last_validated` is `(scope, last_validated DESC)`); the query plan is `WHERE scope = ? ORDER BY last_validated DESC` + post-filter in Python for `topic_tags` overlap.

### 7. Candidate-flag column — `Hypothesis.candidate_for_promotion: bool` ships; matcher defers

Column ships in P1.6.5 schema (D2). No matcher impl in P1.6.5: no code writes the column to True (test fixtures bypass via direct UPDATE for e2e Scenario X).

**Why ship the column**:
- Forward-compat: P1.7+ matcher will need the column to record cross-N-rooms hypothesis-similarity findings. Adding it now (cheap; no rows yet) avoids schema migration when the matcher lands.
- Migration tooling does not exist (per pre-investigation: no alembic, no `migrations/` directory). Schema additions later would require either a migration tool or a manual DB rebuild; ship-now is cheaper.
- Promotion does NOT use the flag as a precondition in P1.6.5 (D3 step 2): the matcher's deferral means the flag is purely write-target for future code. User-confirm promotion (the only producer this cycle) ignores it.

**Why no matcher this cycle**: brief Out-of-scope rationale — code-only similarity matching is weak (exact-string match would pass tests but fail in practice); LLM semantic matching potentially violates Principle 5. Architect-deferral literal-reading per W-004-2 (c): the matcher stays untouched this cycle; no defensive thin matcher in P1.6.5.

### 8. Promotion event type — reuse `decision` with extended `DecisionMeta` optional fields (push-back #6 defended)

`DecisionMeta` at `core/event.py:135-145` is extended with three **optional defaulted** fields:

```python
from pydantic import model_validator

class DecisionMeta(_BaseMeta):
    based_on: list[EventId] = Field(min_length=1)
    trade_offs: dict[str, str] = Field(default_factory=dict)
    # P1.6.5 / ADR-016 D8 — promotion-flavored decisions.
    # hypothesis_id + vk_id are `str | None` (not HypothesisId | VKId) per
    # deliberate-duplication rule (ADR-014 D5 precedent + the constitutional
    # test_constitution_core_does_not_import_memory guard P1.6.5-1 ships):
    # core/event.py MUST NOT import from memory/schema.py. memory/promotion.py
    # constructs typed HypothesisId / VKId, calls str(hyp_id) at metadata
    # emit time.
    promotion: bool = False
    hypothesis_id: str | None = None    # semantic: HypothesisId at memory layer
    vk_id: str | None = None            # semantic: VKId at memory layer

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

Promotion events have `promotion=True` + `hypothesis_id` + `vk_id` populated. Non-promotion decisions retain `promotion=False` + None for the two IDs (defaults match the pre-ADR-016 shape; existing producers and consumers unaffected).

**Deliberate-duplication rationale for `str | None` ID fields** (per Y1 → α routing):

`HypothesisId` and `VKId` are `NewType` aliases in `memory/schema.py` (D2). Using them in `DecisionMeta` (which lives in `core/event.py`) would require `from orchestrator.memory.schema import HypothesisId, VKId` — violating the dep-direction layering invariant + the constitutional guard `test_constitution_core_does_not_import_memory` that P1.6.5-1 itself ships. ADR-014 D5 set the precedent (`SummarySnapshotMeta` stores serialized `dict[str, str]` instead of importing `HypothesisRef` from `derived/`); ADR-016 D8 follows it. The typed identity lives at the memory layer (`memory/promotion.py` constructs `HypothesisId` / `VKId` from the row reads); the event-layer metadata serializes them as plain strings via `str(hyp_id)` at emit time.

**Co-presence enforcement** (per Y3 → α (a) routing): schema-enforced via `@model_validator(mode="after")` — `promotion=True ⇒ hypothesis_id + vk_id both set`; `promotion=False ⇒ both None`. This closes the forward-compat hazard from future producers emitting malformed promotion events (catches at `validate_metadata` step 0 inside `EventStore.append`, the earliest possible point in the writing path). Replaces the prior "runtime enforcement is `memory/promotion.py`'s responsibility" boundary — co-presence is now schema-enforced, no consumer-side defensive check needed.

**Why reuse `decision` instead of new EventType.PROMOTION** (push-back #6 lean):

The brief's architect-settled #7 reuses `decision`. Senior considered pushing for a dedicated `EventType.PROMOTION` because:
- Promotion has structurally distinct metadata (`hypothesis_id`, `vk_id`) that doesn't cleanly fit decision semantics.
- New EventType is allowed via ADR per `core/event.py:69-75` ("Adding a type requires an ADR; renaming or merging types is a breaking change") — and this is the ADR.
- Cleaner discrimination: consumers can filter `event.type == PROMOTION` rather than `event.type == DECISION AND event.metadata['promotion'] == True`.

Senior pin **reuses `decision`** per architect-settled #7, with the implementation detail nailed:

- **Semantic fit**: Promotion IS a user decision (`handoff.md` §4.5 promotion rule (b) "用户显式确认"). Reusing `decision` matches the cognitive model and the existing `decision_log` derived view (ADR-015 D2 filter set — promotions appear in decision log automatically).
- **Constitutional-type minimalism**: ADR-001 + `core/event.py:69-75` treat the 18-type vocabulary as load-bearing. Adding a 19th type for one shape that fits inside `decision` semantics increases the vocabulary maintenance burden — every consumer that filters on event types now has one more case to consider.
- **Optional-defaulted-fields backward compat**: existing decision producers pass no extra fields; their metadata still validates. Existing decision consumers ignore the new fields by default. The schema extension is the minimum viable change.

The cost of reuse: `DecisionMeta` is slightly polluted by promotion-specific optional fields. Senior judgment: acceptable. If a future cycle finds the pollution untenable (e.g., 3 more conditional flags accumulate), revisit via ADR-016 amendment toward a dedicated EventType.

### 9. `VerifiedKnowledge.contradictions` semantic — list of VK IDs (VK-to-VK cross-reference)

`VerifiedKnowledge.contradictions: list[VKId]`. Each element is a VK id of a verified knowledge claim that contradicts the current row.

**Why VK-to-VK** (not hypothesis IDs, not event IDs, not source URLs):

The pre-investigation surfaced that `handoff.md` §4.5 leaves `contradictions: list[str]` opaque. Senior considered three candidates:
- Hypothesis IDs (pre-promotion candidates that contradict).
- Source event IDs (event-stream cites that conflict).
- VK IDs (verified knowledge that contradicts).

Lean: VK-to-VK. Reasoning:
- VKs are the **verified-and-cross-room-addressable** layer. Contradictions among them are the load-bearing signal for cross-room reasoning ("knowledge X claims A; knowledge Y claims not-A — flag both").
- Hypotheses get rejected (lifecycle status `rejected`) or stale, not "contradicted by a VK"; their relationship to truth is handled by the status enum.
- Source event IDs would push contradiction-tracking into the event stream, which is already canonical truth. Contradictions among events are detected by walking metadata cite chains (ADR-014 D2.1 pattern). VK contradictions are a different signal: two verifications that disagree.

P1.6.5 ships the field with the VK-ID semantic pinned; **no producer writes contradictions in P1.6.5** (promotion's only act is verification, not contradiction-detection). Field is present, defaults to `[]`, and is queryable; a future cycle (cross-room contradiction-detector — code or LLM-assisted, undetermined) writes to it.

### 10. "No auto-promote" invariant — code-enforced via API shape; not test-enforced

`handoff.md` §4.5: "不自动晋升". The invariant: no path exists where the system promotes a Hypothesis without an explicit user call to `promote_hypothesis(...)`.

P1.6.5 enforcement:
- `promote_hypothesis(hyp_id, user_id, ...)` is the **only** API in `memory/` that creates a VK row. There is no `create_verified_knowledge(...)` standalone constructor.
- `user_id: str = Field(min_length=1)` is required — caller cannot pass empty. A "system" caller is theoretically possible (string `"system"` is a valid `user_id`), but the architect-partner ↔ architect discussion ruled the invariant is "user_id is whoever the caller says it is; per-caller eligibility is downstream code's choice." P1.6.5 does not gate `user_id == "system"`.

**Why no test asserts "no auto-promote anywhere in the codebase"**: senior pre-investigation considered a constitutional test along the lines of "grep all callsites of `promote_hypothesis`; assert none are from event-stream consumer modules" — finding it impractical (false positives on test fixtures; brittle across future cycles). The architect-deferral literal-reading per W-004-2 (c): the invariant stays code-enforced (only via the API shape: explicit caller, explicit user_id), supplemented by ADR-016 D10 inscription. Future cycles add stricter enforcement if a regression risk materializes.

### 11. Transaction-atomicity mechanism — `EventStore.append_in_transaction(event, conn)` extension or savepoint pattern

**The implementation gap** surfaced by pre-investigation: `EventStore.append` at `src/orchestrator/core/event_store.py:185-272` wraps its body in `with self.conn:` (line 211). Python sqlite3's `Connection.__exit__` issues `COMMIT` (or `ROLLBACK` on exception). Nesting `with conn: ... event_store.append(...) ...` from `memory/promotion.py` either:

- Commits the inner-most transaction first (breaking the outer atomicity), OR
- On modern Python + connections in autocommit-off mode, raises `OperationalError: cannot start a transaction within a transaction` if memory tries to `BEGIN` while EventStore.append's `with` is implicitly transactional.

ADR-016 D11 pins **option A — extend EventStore with a transaction-aware append**:

`EventStore.append_in_transaction(event: Event) -> EventId` — same validation, same INSERT, same relations extraction, but **omits** the outer `with self.conn:` wrapper. Caller is responsible for transaction lifecycle. The existing `EventStore.append(event)` becomes a thin wrapper: open `with self.conn:` + call `append_in_transaction(event)`.

`memory/promotion.py` uses `append_in_transaction(...)` inside its own `with conn:`:

```python
def promote_hypothesis(...) -> VerifiedKnowledge:
    # ... load hypothesis, eligibility check (outside transaction) ...
    with conn:                                            # single outer transaction
        event_id = event_store.append_in_transaction(decision_event)
        conn.execute("INSERT INTO verified_knowledge ...")
        conn.execute("UPDATE hypothesis SET status='verified' WHERE id=?", ...)
    # commit on context exit; rollback on any exception inside
```

Atomicity guaranteed: all three SQLite writes land or none does.

**Why option A over alternatives considered**:

- **Option B — inline the events-table INSERT in `memory/promotion.py`** (skip `EventStore` entirely for the promotion's decision event): breaks the EventStore-is-the-only-writer invariant. Future EventStore changes (e.g., trigger additions, validation logic) would silently miss promotion's events. Rejected.
- **Option C — SAVEPOINT** (`conn.execute("SAVEPOINT promo")` + `... append ...` + `RELEASE` / `ROLLBACK TO`): viable but fights Python sqlite3's autocommit semantics. SAVEPOINTs work but `with self.conn:` inside the savepoint scope still commits the savepoint's containing transaction unexpectedly. Higher complexity, easier to get wrong. Rejected.
- **Option D — single inline transaction in promotion.py that bypasses `EventStore.append`'s `with self.conn:` via reaching into `EventStore.conn` directly**: ugly encapsulation break. Rejected.

**Refactor scope (lands in P1.6.5-2)**: `EventStore.append` body is split into `append_in_transaction(event)` (no `with self.conn:`) + the existing public `append(event)` which becomes `with self.conn: return self.append_in_transaction(event)`. All existing callers of `EventStore.append` are unaffected (same behavior). Tests verify the split is behavior-preserving (existing test suite green) and that `promote_hypothesis` uses `append_in_transaction` correctly under both success and failure paths.

**Test for atomicity**: e2e Scenario X (P1.6.5-5) includes a forced-failure case where the VK insert raises (e.g., a NOT NULL violation injected via a mocked Pydantic-passing-but-DB-rejecting row); assert the `decision` event is NOT in `event_store` post-rollback (canonical evidence that atomicity holds).

## Considered alternatives

**Separate SQLite file for memory tables** (push-back #2 from brief). Considered: cleaner module isolation; promotion would use 2-phase coordination across 2 files. Rejected: 2-phase doesn't exist in stdlib `sqlite3`; promotion atomicity would either require XA-style coordination (overkill) or accept non-atomic writes (violates the load-bearing invariant). Architect-settled #4 + ADR-016 D5/D11 settle the question.

**Defer the candidate-flag column** (push-back #3). Considered: YAGNI — don't ship the column without a producer. Rejected: schema migration tooling doesn't exist; adding the column later would require manual DB rebuild for any persisted state. Ship-now cost is one INTEGER column with default 0; defer-cost is a future migration project.

**Auto-mirror `hypothesis` events to memory rows** (push-back #4). Considered: zero producer-wiring cost; every `hypothesis` event becomes a Hypothesis row. Rejected: couples persistence semantic to every event (transient, low-confidence, mid-discussion edits all become memory clutter). Same intuition as ADR-014 D3 producer-trigger choice.

**Defer Entity entirely** (push-back #5). Considered: no producer/consumer in P1.6.5; ship nothing. Rejected: future Entity producer (P1.7+ or P2) requires schema migration to add the table. Trivial ship-now cost (one model + one table + zero API surface) vs deferred migration cost.

**New `EventType.PROMOTION` instead of reusing `decision`** (push-back #6). Considered: cleaner type discrimination + dedicated promotion-specific metadata schema (no DecisionMeta pollution). Rejected: promotion semantically IS a user decision; new EventType inflates the constitutional 18-type vocabulary; existing decision_log derived view (ADR-015) already includes promotions for free under reuse. Optional-defaulted DecisionMeta field extension is the minimum viable change.

**Narrower e2e scope (2 rooms or synthetic bypass)** (push-back #7). Considered: faster test; less setup. Rejected: cross-room semantic IS what P1.6.5 ships; narrower scope fails to exercise the load-bearing semantic. Full 3-room Scenario X per architect-settled #8.

**Ship a thin matcher (exact-string match) for cross-N-rooms candidate flag** (push-back #8). Considered: write column → True semantic gets exercised. Rejected: exact-string matching is misleadingly weak (passes tests, fails in practice — hypothesis content is paraphrased across rooms even when semantically equivalent). False confidence is worse than no matcher. Defer per brief.

**Split into two ADRs (ADR-016 schema + ADR-017 promotion)** (push-back #1). Considered: tighter ADR scope per Principle 9. Rejected: the 11 decisions are tightly coupled (D2 schema references D3 promotion event; D5 storage references D11 atomicity; D7 candidate flag references D3 eligibility). Splitting would require cross-ADR references for invariants that are one decision space. Architect-partner lean: single ADR; senior concurs.

## Consequences

**Positive**:
- P0 §4.5 schema-only debt closes for 3 of 4 classes; the longest-running spec/code gap in the project shrinks. ProjectArchive's deferral has a clean consumer-driven trigger.
- First persistence layer beyond the event store; the pattern (same-file co-location + per-module `init_*_schema(conn)` + transaction-atomic cross-module writes via `append_in_transaction`) becomes the template for any future derived-but-persisted cache (e.g., embedding indexes, cross-room indexes, observability metrics).
- Cross-room reasoning gains a concrete substrate: a Research room consumer in any future agent or UI surface can `lookup_verified_knowledge(...)` without re-walking the event stream of every closed room.
- `EventStore.append_in_transaction` extension generalizes beyond memory promotion: any future module needing transaction-atomic event-stream + own-table writes uses the same shape.

**Negative**:
- `EventStore` public surface grows by one method (`append_in_transaction`); maintainers must understand the split (existing `append` = wrapped variant; new `append_in_transaction` = caller-managed). Defensible per D11's atomicity rationale, but a real API-surface-area cost.
- `DecisionMeta` carries three optional promotion-specific fields. Slight pollution. Defensible per D8 reuse-rationale, but `decision` events now have a sub-shape (promotion-flavored) that consumers must be aware of when filtering.
- Entity ships as a stub with zero API surface. Forward-compat win; possible "what is this for?" question for a near-term reader. Mitigated by D1 explicit rationale in this ADR.
- Memory tables and event_store tables share a connection. Operational complexity is single-file (one DB to backup, one migration), but failure modes are also shared (a corrupted SQLite file loses everything). Per architect-settled #4.

**Reversibility**:
- Splitting memory into its own DB file: reversible. Move tables + adjust caller schema-init. Promotion atomicity loses the single-transaction guarantee; D11 would need amendment to a 2-phase or accept-eventual-consistency model.
- Adding `EventType.PROMOTION` (reversing D8): reversible. ADR amendment adds the EventType; promotion events migrate by author-time logic (newly produced events use new type; existing decision-with-promotion events stay decision; consumers filter both during transition).
- Removing `candidate_for_promotion` column: harder. SQLite supports column drop via newer versions; for safety would require a table rebuild. Cost: ~1 hour migration. Acceptable.

## Forward-amendment hooks

Conditions under which this ADR should be revisited via amendment:

- **Cross-N-rooms matcher lands** (P1.7+): D7 candidate-flag write path activates. D3 promotion eligibility may need to incorporate the flag (or not, per architect call at that time). Amendment captures the matcher's design + eligibility integration.
- **Entity full impl lands**: D1 stub-rationale evolves into full producer/consumer contract. Likely a separate ADR for Entity-specific design; D1 in ADR-016 marks as superseded for the Entity portion.
- **ProjectArchive lands**: D1 deferred-rationale closes; per-room archive vs cross-room VK becomes a documented distinction.
- **External ground-truth promotion (rule (c))** materializes: D3 promotion eligibility expands; potentially a new event type for "verification-by-external-source." Likely a separate ADR.
- **Concurrent dispatch / async-reshape** (deferred per ADR-011 D1): D11 atomicity assumes single-connection sequential writes. Multi-connection concurrent promotions would need either connection-per-promotion + retry-on-conflict OR a queueing layer. Revisit at that ADR.
- **`DecisionMeta` field pollution** crosses the senior tolerance threshold (e.g., 3+ additional optional flags accumulate from future cycles): D8 reuse-of-`decision` revisits toward dedicated `EventType.PROMOTION`.
- **`memory/` table row counts** cross a scale threshold (e.g., 100k+ rows per scope): D6 lookup's Python post-filter for `topic_tags` overlap becomes too slow; reshape to SQLite JSON1 functions OR normalized tag table. Threshold to be defined empirically at amendment time.
- **Cross-N-rooms matcher promotion attribution** (per Y5 → α (a) routing): when D7 candidate-flag matcher lands, D3 promotion-event `room_id` choice may need amendment toward (i) multi-event promotion (one per source room), (ii) dedicated `RoomType.CROSS_ROOM` pseudo-room, or (iii) accept-loss-of-fidelity by keeping originating-room semantic. P1.6.5 ships (iii) by default (single-source-room is the common case); revisit at matcher ADR.
- **`record_hypothesis` ↔ `hypothesis` event atomicity** (per Y6 → α routing; deferred per D4 — no consumer requires it in P1.6.5): if a future consumer materializes that joins `memory.hypothesis` rows with event_store `hypothesis` events (e.g., a query that requires both writes to have landed or neither), D4 revisits toward an atomic producer API mirroring D11's `append_in_transaction` pattern (e.g., `record_hypothesis_with_event(content, ..., conn, event_store)` calling `event_store.append_in_transaction(...)` inside the same `with conn:` block). Until then, callers emit `hypothesis` events separately + accept eventual consistency.

## Cross-references

- `handoff.md` §3.1 — code-driven decisions (promotion eligibility); §4.5 — cross-room memory data classes (slice B materialized; deferrals named); §5.8 — persistence (memory tables co-locate with event store); §10 — `memory/` package now real.
- `docs/decisions/ADR-001-event-store-foundation.md` — event log canonical (memory tables are derived-but-persisted convenience); informs D5 storage + D8 promotion-event-type reuse.
- `docs/decisions/ADR-008-workflow-state-machine.md` — single-ADR path per D2.
- `docs/decisions/ADR-014-snapshot-contract.md` — D1+D3 producer-trigger pattern; D5 deliberate-duplication for cross-layer schema (informs D5+D8).
- `docs/decisions/ADR-015-decision-log-shape.md` — D2 filter set (promotions appear in decision log via D8 reuse); D5 derive-don't-materialize (contrast with ADR-016 which DOES persist).
- `src/orchestrator/core/event.py:69-75` — constitutional 18-type vocabulary (informs D8 reuse-vs-new-type).
- `src/orchestrator/core/event.py:135-145` — `DecisionMeta` extended per D8.
- `src/orchestrator/core/event_store.py:185-272` — `EventStore.append` to be split per D11.
- `docs/process/architect-briefs/P1.6.5.md` — settled-decisions source (decisions 1-11 in brief map to D1-D11 here with senior implementation-level pins).
- `chat-history.md` "跨房间记忆" — design reasoning context.
- `docs/process/distance-test.md` RC-8 — substantive new-pattern cycle.
- `docs/process/dual-lens-r0b.md` RC-15 — cross-family dispatch criteria (3 of 4 met per brief architect-settled #10).
- `docs/process/senior-planner.md` § Pre-investigation discipline — W-004-2 codified rules applied at plan stage (claims verified against source; promotion-impact grep for `EventStore.append` callers; architect-deferral literal-reading for Entity / ProjectArchive / matcher).
