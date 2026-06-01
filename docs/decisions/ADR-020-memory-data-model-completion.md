# ADR-020: Memory data-model completion — Entity full + ProjectArchive + user preferences

**Status:** Accepted — 2026-06-01 (architect-accepted after plan-stage reviews clean: R0-A-on-plan + R0-B-cross-family both `clean`; Y1 → α + Y2 → α absorbed; ProjectArchive persist ratified)

**Scope:** Completes the `memory/` data model with the three structured cross-room memory *containers* that P2.5 (room re-entry) will consume: (A) `Entity` fleshed from schema-only stub into a deterministic create/read surface, (B) `ProjectArchive` (the per-room narrative 身份证), and (C) user preferences. Pins: the container shapes + their deterministic create/read APIs, the Principle-5 producer-relocation + Principle-11 no-inferred-preferences constraints, same-SQLite-file storage + the `entity`-column ALTER migration, and the deferral of the re-entry consumer + the LLM extraction producers. Does NOT govern: the P2.5 re-entry catch-up assembly (consumer), the LLM extraction/inference producers (out of `memory/`, deferred), knowledge-graph entity↔entity relations (forward hook), the forgetting/降级 mechanism (forward hook — fields reserved), or team-scope beyond reserving the enum value.

## Context — the promotion-triad pattern, a third time (Principle 5 + Principle 11)

This slice creates the project's first **entity / preference** memory. The architect ratified it as **one P2.4 slice** (no split — push-back #0 decided) covering all three subsystems, under **one ADR-020** (push-back #1).

The constitutional framing is the **same pattern the promotion triad established three times now**, generalized (`chat-history` category-4 + "用户偏好的特殊处理" pin it; the brief inherits, not decides):

- **Principle 5 — extraction is content-gen and stays OUT of `memory/`.** Pulling "the user mentioned project X / read paper Y / prefers concise answers" out of a room *is* LLM work — but, exactly as rule (a)'s tagging producer (ADR-017) and rule (c)'s validation connectors (ADR-019) are relocated, that extraction lives **outside `memory/`** (agent layer, deferred). `memory/` exposes **deterministic, code-only create/read APIs** the producer calls; `memory/` never calls an LLM (rglob-enforced, covers the new files).
- **Principle 11 — user preferences may NOT be LLM-inferred.** `chat-history` is verbatim: *❌ "agent 觉得用户喜欢具体例子"* is forbidden (no-ground-truth → drift). Allowed only: ✅ explicit user declaration; ✅ behavior patterns stored as metadata (which are **not** preferences); and the system may *propose* "set this habit as a preference?" — **the user decides**. So preference-*creation* is an explicit, user-confirmed code path — structurally the same discipline as promotion's D10 (no auto-promote) and rule (c)'s relocated judgment.

**The generalized rule this ADR applies to all three subsystems:** `memory/` owns typed containers + deterministic create/read APIs; LLM-driven extraction/inference is relocated to an out-of-`memory/` producer (deferred); anything *inferred* (not explicitly user-declared and not code-derived-from-canonical-facts) requires explicit user confirmation before it becomes durable memory. Crucially, `memory/` **structurally cannot** make the factual-vs-inferred judgment itself — that judgment needs the room's content, which is LLM work — so the confirm-gate necessarily lives in the producer, exactly as extraction does. Where Principle 11 is sharpest (preferences), this ADR adds a structural enforcement on top of the relocation (D3).

This ADR governs the constitutional invariants: Principle 5 (no LLM in `memory/`), Principle 11 (no inferred preferences become durable), the generalized-D10 no-auto-durable-inferred-memory discipline, same-file storage (ADR-016 D5), reserve-extension-fields-day-one (`chat-history`: "所有数据结构从第一天就预留 scope、evidence、entity_id"), and determinism (Principle 11) for all readers + the persisted archive.

## Decisions

### 1. Entity — full producer/consumer surface (off the schema-only stub)

`Entity` (`memory/schema.py`) is fleshed from the ADR-016 D1 stub. It gains two **reserved extension fields** (the day-one-reserve constraint): `scope: EntityScope` and `evidence: dict[str, Any]`. A new `EntityScope` enum carries the four `chat-history` scopes — `personal | team | project | global` (distinct from `VKScope`'s three values; entities need `project` scope, VK does not, so a separate enum rather than widening VK's). `EntityType` gains `PREFERENCE` (D3); other type values (knowledge-graph relation kinds) defer.

```python
class EntityScope(StrEnum):
    PERSONAL = "personal"; TEAM = "team"; PROJECT = "project"; GLOBAL = "global"

class Entity(BaseModel):                      # frozen + extra="forbid"
    id: EntityId
    type: EntityType                          # + PREFERENCE
    attributes: dict[str, Any] = {}           # name + free-form (e.g. {"name": "Project X"})
    scope: EntityScope = EntityScope.PERSONAL  # reserved (chat-history 作用域)
    evidence: dict[str, Any] = {}             # reserved provenance (chat-history 可解释性链条)
    created_at: TimestampMs
```

**Create API** (`memory/entity.py`): `record_entity(type, attributes, *, scope=PERSONAL, evidence=None, conn, now=None) -> Entity` — a deterministic, code-only create. It is the **sink for explicit/factual or code-derived entities** (e.g. "the user said their project is X", or an entity code-derived from a closed room's events). **It rejects `type == PREFERENCE`** (raises `ValueError`) — preferences may only be created via `record_preference` (D3), so the Principle-11 path cannot be bypassed.

**Create discipline (push-back #2)** — where the factual-vs-inferred line sits: `record_entity` does **not** itself gate on inferred-vs-factual, because that judgment requires reading the room (LLM work) and is therefore **structurally impossible inside `memory/`** (it would need an LLM, violating Principle 5). The judgment + the confirm-gate for *inferred* entities live in the **producer** (relocated, exactly like the extraction itself): the producer confirms an inferred entity (or derives it from canonical structure) and only then calls `record_entity`. `memory/` provides the deterministic sink + the `evidence` provenance field the producer populates (`chat-history` 可解释性链条) — not the inference. This is the generalized-D10 relocation, consistent with rules (a)/(c). The **strong structural enforcement** (a required confirming user) is reserved for preferences (D3), where Principle 11 is absolute.

**Readers**: `get_entity_by_id(entity_id, conn)` + `list_entities(*, type=None, scope=None, conn) -> list[Entity]` — deterministic (id ASC), Python-side attribute filtering if needed (no JSON1, mirroring ADR-016 D6 lookup). Entity↔Hypothesis/VK relations (the knowledge-graph "实体 + 关系") are a **forward hook** — no relation ships now; P2.5 re-entry needs the containers, not the edges (the "wait for a real consumer" discipline).

### 2. User preferences — Entity rows (`type=PREFERENCE`) created only via a user_id-required API

**Preferences are Entity rows** (push-back #4): `chat-history` is explicit — "用户偏好 = 实体记忆" (类别 3 实体记忆 umbrellas 用户偏好). So a preference is an `Entity` with `type == EntityType.PREFERENCE`, reusing the `entity` table + the entity reader (no parallel store). This honors the chat-history model and avoids a duplicate persistence surface.

But preference *creation* has a **stricter, dedicated API** that enforces Principle 11 structurally (`memory/entity.py`): `record_preference(key, value, user_id, *, scope=PERSONAL, conn, now=None) -> Entity`. It **requires `user_id`** (`min_length >= 1`) — the explicit declaring or confirming user — and writes an `Entity` row with `type=PREFERENCE`, `attributes={"key": key, "value": value}`, `evidence={"declared_by": user_id}`. Because the API has **no path to create a preference without a confirming user**, an **LLM-inferred preference with no user is un-representable** — Principle 11 enforced by construction, mirroring promotion's required `user_id` (ADR-016 D8). The general `record_entity` rejecting `type=PREFERENCE` (D1) closes the bypass.

**Preference data model — upsert by `(user_id, key, scope)`** (Y2 → α): a preference is a **key-value setting**, not an append-only fact, so `record_preference` **upserts** — there is **exactly one** preference row per `(user_id, key, scope)`, and a re-declaration updates that row's value in place. So the current value of a preference is **deterministic by construction** (latest-wins), with no dedup pushed onto consumers. Implementation is the impl's call (a `UNIQUE(user_id, key, scope)` projection + `INSERT … ON CONFLICT DO UPDATE`, or a read-modify-write within the existing transaction posture); the row keeps its `evidence.declared_by` = the most-recent declaring/confirming user. This **diverges deliberately from `record_entity`** (D1), which is **plain-insert / append-only** — general entities accumulate as a fact log; preferences are a settings map. The two duplicate-create semantics are pinned by tests (D2/D1 acceptance): a second `record_preference(same user_id, same key, new value)` yields **one** row (latest value); a second `record_entity(same data)` yields **two** rows.

- **Explicit-declaration** → the user states a preference → `record_preference(user_id=<the user>)`.
- **Propose-then-user-confirms** → the producer *proposes* (out of `memory/`); on the user's confirm it calls `record_preference(user_id=<confirming user>)`. The propose step never reaches `memory/`; only the confirmed result does (with `user_id`).
- **Behavior patterns as metadata** (`chat-history`: ✅ "行为模式作为 metadata — 不是偏好") are **not** preferences and out of scope here — they are a producer/observability concern, never written through `record_preference`.

**Reader**: preferences surface through the entity reader — `list_preferences(*, user_id=None, scope=None, conn) -> list[Entity]` is a thin wrapper over `list_entities(type=PREFERENCE, ...)` (reuses the entity surface, #4).

### 3. ProjectArchive — a persisted `project_archive` table (not a derived view)

**Decision: persist, don't derive** (push-back #3 — the headline fork). `ProjectArchive` (`memory/schema.py`, frozen + `extra="forbid"`) is the per-room narrative 身份证 (`chat-history` 类别 4): `room_id`, `title`, `duration_ms`, `one_line_summary`, `decision_log` (serialized), `spinoff_questions`, plus the reserved `scope` + `evidence` + `created_at`. It is stored in a new `project_archive` table (one row per room; `room_id` PK).

```python
class ProjectArchive(BaseModel):              # frozen + extra="forbid"
    room_id: RoomId
    title: str
    duration_ms: int = Field(ge=0)
    one_line_summary: str                     # content-gen, produced OUTSIDE memory/ (passed in)
    decision_log: list[dict[str, Any]] = []   # frozen serialized copy of the ADR-015 derivation at close
    spinoff_questions: list[str] = []         # content-gen, produced OUTSIDE memory/ (passed in)
    scope: EntityScope = EntityScope.PROJECT
    evidence: dict[str, Any] = {}
    created_at: TimestampMs
```

**Why persist over derive** (defending against the ADR-015 derive-don't-materialize tug): the archive is a **post-close, cross-room, human-browsing** artifact whose whole purpose is a **durable narrative identity that outlives the room's event lifecycle**. `chat-history`'s 遗忘机制 (超期降级) downgrades/compacts events over time; a view derived over the event stream (like `decision_log`, ADR-015 D5) would **degrade or break as events are compacted away** — but the archive must survive that. ADR-015's derive-discipline applies to a *live within-room* view, cheaply recomputed from current events; the archive is the opposite — a **frozen snapshot taken once at room close**, meant to persist independently. Plus re-entry (P2.5) wants a cheap durable read. So the archive persists.

**Don't duplicate-derive** (the self-discovery): the code-derivable fields (`decision_log`, `duration_ms`) are **composed at close from the existing derivations** — the caller runs `produce_decision_log(events, room)` (ADR-015) and passes the serialized result into `record_project_archive`; `memory/` stores a frozen copy and **never re-derives on read**. The archive does not reinvent the decision-log derivation.

**Principle 5** (the (B)-specific reconciliation): the **semantic** fields (`one_line_summary`, `spinoff_questions`) are LLM content-gen — produced **outside `memory/`** (the closer / Logger agent, exactly as `summary_snapshot` events carry the LLM-generated `current_focus`, ADR-014) and passed **into** `record_project_archive` as plain strings. `memory/` never generates them; it persists given data. So `memory/` calls no LLM. The archive is **auto-created at close** without a user-confirm gate — legitimate per the brief's settled constraint (`auto-created-from-structure` is code-derived from canonical facts, not LLM-inferred; the content-gen summary is content, not a durable-knowledge *decision*).

**API + reader** (`memory/archive.py`): `record_project_archive(room_id, title, duration_ms, one_line_summary, decision_log, spinoff_questions, *, scope=PROJECT, evidence=None, conn, now=None) -> ProjectArchive` (deterministic persist; one per room). Minimal readers `get_project_archive(room_id, conn) -> ProjectArchive | None` + `list_project_archives(*, scope=None, conn) -> list[ProjectArchive]` (room_id ASC). The **re-entry-shaped read contract waits for P2.5** — P2.4 ships a minimal reader, not a consumer-tailored API (the P1.6 "wait for a real consumer scenario" discipline).

### 4. Storage + migration — same SQLite file; `entity` ALTER + new `project_archive` table

Same SQLite file as the rest of `memory/` (ADR-016 D5). In `init_memory_schema`:
- The `entity` table gains `scope` + `evidence` columns via an idempotent **PRAGMA-guarded ALTER** (the ADR-018 D5 template — mirror `_ensure_hypothesis_topic_tags`): `PRAGMA table_info(entity)` → if absent, `ALTER TABLE entity ADD COLUMN scope TEXT NOT NULL DEFAULT 'personal'` and `... ADD COLUMN evidence TEXT NOT NULL DEFAULT '{}'`. The `CREATE TABLE entity` is updated for fresh DBs. Verified by an on-disk migration round-trip test (pre-P2.4 `entity` table → ALTER → old rows read `scope='personal'`/`evidence={}`, counts preserved — mirror ADR-018's test).
- `project_archive` is a new `CREATE TABLE IF NOT EXISTS` (a new table needs no ALTER; appears on fresh + migrated DBs). `room_id TEXT PRIMARY KEY`, fields per D3, FK `room_id REFERENCES rooms(id)`.

### 5. A structural AST guard for the Principle-11 no-inferred-preferences invariant (Y1 → α)

The no-LLM rglob (`tests/memory/test_constitution.py`) auto-covers the new `memory/` files (Principle 5), and the behavioral Principle-11 enforcement (`record_preference` requires `user_id`; `record_entity` rejects `type=PREFERENCE`) is tested directly (D2). But — per the Y1 → α routing — that behavioral pair rests on two functions; a **future third write path** (a P2.6 producer, or a new `memory/` module constructing `Entity(type=EntityType.PREFERENCE)`) would bypass it with the unit tests still green. Principle 11 is absolute and this is the project's first preference surface, so the invariant gets a **structural guard this cycle** (not deferred), consistent with the matcher/validation AST-guard precedent (`test_constitution.py`).

The guard (a real-AST check, **not** a whole-file substring scan — RC-24): walk every `memory/*.py` AST for `ast.Attribute` references to `EntityType.PREFERENCE` (attr `"PREFERENCE"` on a `Name` `EntityType`), and assert each occurs **only** inside `entity.py`'s preference-handling functions — `record_preference` (constructs the row, requiring `user_id`), `record_entity` (references it solely to *reject* it), and `list_preferences` (reads/filters). Any `EntityType.PREFERENCE` reference elsewhere in `memory/` is a potential unguarded preference-creation path and fails the guard. (The enum *definition* in `schema.py` is an assignment, not an `EntityType.PREFERENCE` attribute access, so it is not flagged; `_row_to_entity`'s `EntityType(row["type"])` is a `Call`, not the attribute, so not flagged.)

This is the **construction/usage backstop**: combined with the signature-level enforcement (D2), it forces all preference handling through `record_preference` (user_id-required), so no new typed code path can durably create a preference without a declaring user. Considered-and-not-chosen as the *primary*: a store-layer data assertion ("every `type='preference'` row carries `evidence.declared_by`") — sturdier against a raw-`INSERT` outcome but behavioral (only catches rows a test exercises) and not the AST idiom; the AST reference-guard catches the typed path statically (any future module), which is the routing's stated concern. (The reference-guard does not catch a raw-string `INSERT INTO entity … 'preference'` bypass — a deeper invariant break a future data-assertion could add; acknowledged.)

### 6. One slice, one ADR-020 (no split)

Push-back #0 is architect-decided: **one P2.4 slice** covering Entity + ProjectArchive + preferences, under **one ADR-020** (push-back #1). The three subsystems share the constitutional framing (D-Context) and the storage layer (D4); preferences are Entity rows (D2), so Entity + prefs are genuinely coupled, and ProjectArchive's persist decision (D3) fits as one decision section rather than a separate ADR-021. Fresh ADR-020 (016-019 taken); not an amendment.

## Considered alternatives

- **ProjectArchive as a derived view** `produce_project_archive(events, room, ...)` (push-back #3, ADR-015 derive-discipline). Rejected — a view over events would degrade/break as the 遗忘机制 compacts events, but the archive's purpose is a durable post-close identity that must outlive the event lifecycle; and re-entry wants a cheap durable read. Persist; compose the existing derivations at close rather than re-derive on read.
- **Preferences as a separate `preference` table** (push-back #4). Rejected — `chat-history` pins "用户偏好 = 实体记忆"; Entity rows reuse the table + reader. The stricter creation rule is satisfied by the dedicated `record_preference` (required `user_id`), not a separate store.
- **Splitting P2.4** into Entity+prefs (MVP) + ProjectArchive (push-back #0). Architect-decided: no split; one slice.
- **Widening `VKScope` to add `project`** (D1). Rejected — VK does not need `project` scope; a separate `EntityScope` avoids changing the VK contract.
- **Auto-create inferred entities without a confirm gate**. Rejected — generalized D10; inferred entities need a producer-side confirm. `memory/` cannot make the judgment (Principle 5), so the gate is relocated to the producer.
- **An AST orthogonality guard for the create APIs** (D5). Declined — no actuation invariant to guard; the no-LLM rglob + the directly-tested `user_id`/`PREFERENCE` enforcement cover the constitution.

## Consequences

**Positive**:
- Completes the `memory/` data model — the structured containers P2.5 re-entry reads back; closes the ADR-016 D1 Entity stub + the `ProjectArchive` placeholder.
- Principle 11 is enforced by construction for the highest-risk surface (preferences): no path creates an inferred preference without a confirming user.
- ProjectArchive persists durably past the event lifecycle while reusing (not duplicating) the existing decision-log derivation.
- Reserve-fields (`scope`, `evidence`) ship day one, so forgetting/team-scope/explainability need no later migration (`chat-history` discipline).

**Negative**:
- The fattest P2 slice — three subsystems, more surface; mitigated by the shared framing + storage and the unified entity/pref store.
- Dormant-until-fed: the entity/pref extraction producers and the P2.5 re-entry consumer are out of scope, so these containers surface only test-injected data until P2.5/P2.6 (accepted — Principle 9 inscribe-before-producer; the containers are the expensive-to-change contract).
- `EntityScope` is a second scope enum alongside `VKScope` (a small duplication; justified by VK not needing `project`).

**Reversibility**:
- Removing a subsystem: easy (delete the module + table/columns); the entity ALTER columns are harder to drop (SQLite table rebuild, ~1h, per ADR-018) but reserve-now is the cheaper bet.
- ProjectArchive persist → derive: a future amendment + a `produce_project_archive` over events (only viable while events are un-compacted) — the persist choice is the safer default.

## Forward-amendment hooks

- **The P2.5 re-entry consumer** — binds to these readers; may want a consumer-shaped `assemble_reentry(...)` over Entity + ProjectArchive + preferences. Its own slice.
- **LLM extraction producers** (entities/prefs from rooms; the archive's semantic fields) — agent-layer content-gen, deferred (P2.6 "feed the dormant mechanisms").
- **Knowledge-graph relations** (entity↔entity edges) — a relation table + `EntityType`/relation enum, when a consumer needs the graph.
- **Forgetting / 降级** — `scope` + `evidence` + a `last_validated`-style field are reserved; the expiry/downgrade policy is a later slice.
- **Team-scope** — the `team` `EntityScope` value is reserved; team-sharing semantics defer.
- **Behavior-pattern metadata → preference proposal** — the propose-then-confirm producer flow (out of `memory/`) that turns observed patterns into a `record_preference` call.

## Cross-references

- `handoff.md` §4.5 (memory data classes — Entity stub + ProjectArchive placeholder now materialized; preferences added), §3.1 (code-decides, no LLM in `memory/`).
- `chat-history.md` "跨房间记忆" 类别 3 (实体记忆 — 用户偏好/项目/paper) + 类别 4 (项目档案 fields) + "用户偏好的特殊处理" (Principle-11 no-inferred-prefs) + "渐进实施" (MVP-first) + "所有数据结构从第一天就预留 scope/evidence/entity_id" (reserve-fields).
- `docs/decisions/ADR-016-cross-room-memory-persistence.md` (closed/accepted) — D1 (Entity stub rationale — now fleshed), D5 (same-file schema-init + migration), D8 (promotion `user_id` — the required-confirming-user precedent D3 mirrors), D10 (no-auto-promote — the discipline generalized to inferred memory).
- `docs/decisions/ADR-017/ADR-019` (closed/accepted) — the producer-relocation / advisory pattern recurring here (entity/pref/archive extraction relocated out of `memory/`).
- `docs/decisions/ADR-018-cross-room-tag-registry.md` (closed/accepted) — the column-add ALTER migration template (the `entity` `scope`/`evidence` ALTER reuses it).
- `docs/decisions/ADR-014-snapshot-contract.md` + `ADR-015-decision-log-shape.md` — snapshot persists LLM `current_focus` in events (the precedent for the archive's content-gen fields passed-in); decision_log derive-don't-materialize (the tug D3 defends against, and the derivation D3 composes-not-duplicates).
- `src/orchestrator/memory/{schema.py,store.py}` — `Entity`/`EntityType`/`entity` table (stub → full), `init_memory_schema` (where the ALTER + new table go), `record_hypothesis`/readers (the create/read patterns mirrored).
- `src/orchestrator/derived/decision_log.py` (`produce_decision_log`) — composed into the archive at close.
- `tests/memory/test_constitution.py` — no-LLM rglob (covers the new `memory/` files).
- `docs/retrospectives/P2.2-candidates.md` RC-23/RC-24 (substring-scan fragility — this ADR's prose + any guard avoid). `docs/process/dual-lens-r0b.md` RC-15/RC-20.
