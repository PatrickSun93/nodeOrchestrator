# ADR-021: Room re-entry / 离开-回来追平 — the catch-up consumer (code selects, LLM phrases)

**Status:** Proposed — 2026-06-01 (senior-drafted per P2.5 brief; awaiting architect accept)

**Scope:** Builds the room re-entry / 离开-回来追平 experience ("AI 记得我") — the **first consumer** of the read-side memory surface (P2.1–2.4 were all write-side). Pins: the catch-up contract, the **code-decides / LLM-only-phrases** boundary (the constitutional crux), the consumer's placement (a new `orchestrator/reentry/` package outside `memory/`), the leave/return marker, the deterministic tag-derivation feeding `lookup_verified_knowledge`, the `ReentryDigest` return shape, and the new content-gen `LLMPurpose.REENTRY_DIGEST_RENDER`. **One slice** (re-entry assembly + leave-time generation), one ADR (architect-decided). Does NOT govern: LLM extraction producers (P2.6), forgetting/降级, knowledge-graph relations, team-scope, state-machine evolution (P2.7).

## Context — Principle 5 + Principle 11, a fourth time: code decides *what* and *in what order*; the LLM only *phrases*

P2.5 is the first place all the read-side memory surfaces are *consumed and composed* into a user-facing experience, which makes it the project's highest-risk Principle-5/11 surface so far — a catch-up "experience" is exactly where it is tempting to let an LLM decide what matters. The recurring rule (rules a/c relocation, P2.4 preference-confirm) applies a **fourth time**, and this ADR settles it as a hard boundary:

- **The catch-up's *decisions* are code.** *Which* VK to surface (`lookup_verified_knowledge`'s deterministic scope+tag filter, ADR-016 D6), *which* entities/preferences (`list_entities`/`list_preferences` with code filters, ADR-020), *what's new since you left* (a code diff against a persisted leave-marker), and **all selection / ranking / ordering** are pure code. **None may be an LLM judgment** — Principle 11 (no-ground-truth ranking is drift).
- **The LLM may only do content-gen.** It phrases an **already-selected, already-ordered** fact-set into natural-language prose ("Welcome back. Since you left, X was verified; your project Y has 2 open questions…"). It receives the assembled digest and renders it; it does **not** choose what is in it. The single LLM call uses a **content-gen `LLMPurpose`** (`REENTRY_DIGEST_RENDER`, D4) — never a routing/judgment purpose (there is no such purpose; CLAUDE.md "never LLM-judge a routing decision").

The clean structural expression of this boundary (D3/D4): **`assemble_reentry(...)` is pure code and makes no LLM call; `render_reentry_prose(...)` makes the only LLM call, over the frozen digest `assemble_reentry` already produced.** Selection and phrasing are separate functions; a constitutional AST guard enforces that the assembly path is LLM-free (D6).

This ADR governs: Principle 5 (no LLM in `memory/`; the consumer is outside `memory/` and its LLM use is content-gen render only), Principle 11 (no LLM selection/ranking/ordering — deterministic code), determinism (the code-assembled digest is deterministic; only the prose varies), and the dependency direction (`memory/`/`core/` MUST NOT import the consumer).

## Decisions

### 1. Placement — a new `orchestrator/reentry/` package (the consumer lives outside `memory/`)

The catch-up consumer composes `memory/` readers + `derived/` (snapshot) + `llm/` (the render), so it **cannot live in `memory/`** (the no-LLM rglob). It is a new top-level package `src/orchestrator/reentry/`:

- `reentry/digest.py` — `assemble_reentry` (the deterministic assembly, D3) + the tag-derivation + the marker diff.
- `reentry/render.py` — `render_reentry_prose` (the content-gen LLM call, D4).
- `reentry/leave.py` — leave-time generation (the marker upsert + the ProjectArchive composition, D5/D8).
- `reentry/schema.py` — `ReentryDigest` + sub-models (D7).
- `reentry/store.py` — the `reentry_marker` table + `init_reentry_schema` (D5).

**Dependency direction**: `reentry/` imports `memory/` + `derived/` + `core/` + `llm/`. **`memory/` and `core/` MUST NOT import `reentry/`** — a new constitutional import guard (`test_constitution_*_does_not_import_reentry`, AST/import check mirroring the existing `core`-no-import guards). `reentry/` is the consumer; nothing upstream depends on it.

### 2. One slice — re-entry assembly + leave-time generation together (architect-decided)

P2.5 ships **both halves** under one ADR-021 (architect ruled: no split): the milestone (2) re-entry assembly *and* (1) leave-time generation (the marker + the ProjectArchive the catch-up reads). They are coupled — you need an archive + a marker to catch up *against* — so shipping both makes the e2e end-to-end (leave → return) rather than test-inject-only.

### 3. The assembly contract — `assemble_reentry(...) -> ReentryDigest` (pure code, deterministic)

`reentry/digest.py`:

```python
def assemble_reentry(room_id: RoomId, user_id: str, *, conn, events: list[Event], room: Room,
                     now: TimestampMs) -> ReentryDigest:
    """Compose the deterministic catch-up fact-set. Pure code — NO LLM."""
```

It composes, all by code-driven selection/ordering:
- **Cross-room VK** — `lookup_verified_knowledge(derive_query_tags(room_id, conn), scope, conn=conn)` (the tags are code-derived, D6); if the derived tag-set is empty, the VK section is empty (the consumer does **not** pass `[]` to `lookup`, which raises — D9).
- **Entities + preferences** — `list_entities(...)` + `list_preferences(user_id=user_id, ...)` (code scope/type filters, ADR-020).
- **The room's archive** — `get_project_archive(room_id, conn)` (`None` on first visit).
- **What changed / what's new since leave** — `produce_snapshot(events, room, snapshot_at=now)` for current state + a **code diff against the leave-marker** (D5): facts with `timestamp`/`last_validated` > `last_seen_ts`.

All ordering is deterministic (the readers already order by `last_validated DESC, id ASC` / `id ASC`; the diff is timestamp-sorted). The output is a frozen `ReentryDigest` (D7). The e2e asserts the exact digest by stable labels (not count-only — RC-25 anti-pattern).

### 4. The render — `render_reentry_prose(digest, *, llm_router) -> str` (content-gen, the only LLM call)

`reentry/render.py`: a single LLM call that **phrases the frozen digest into welcome-back prose**. It builds an `LLMRequest` with the new **`LLMPurpose.REENTRY_DIGEST_RENDER`** (added to `llm/purposes.py` — content-gen, ADR-021-gated; adding a purpose requires an ADR per `purposes.py`), `caller_agent_id=None` (non-agent caller, like `SNAPSHOT_SEMANTIC`), a system prompt instructing the model to **render the given facts and add none**, and `messages=[the serialized digest]`; then `llm_router.call(request)`. The render receives the already-selected, already-ordered fact-set; it cannot select or reorder — it phrases. **The MVP ships this prose render** (architect-decided (c)) — the felt "AI 记得我" experience.

`REENTRY_DIGEST_RENDER` is content-gen (rendering, not judgment), distinct from `AGENT_RESPONSE`/`SNAPSHOT_SEMANTIC` for audit-greppability (a reviewer grepping `LLMPurpose` sees the re-entry render is content-gen and confined to `render.py`). A top-level `reenter(room_id, user_id, *, conn, llm_router, ...) -> ReentryResult` composes `assemble_reentry` then `render_reentry_prose`; the deterministic `ReentryDigest` is the tested core, the prose is exercised but its exact wording is not asserted (it is LLM output).

### 5. Leave/return marker — a persisted mutable `reentry_marker` table (snapshot is derived, not persisted)

"What's new since I left" needs a **persisted last-seen marker** — `produce_snapshot` is a *derived* pure function (ADR-014; state is persisted only in `summary_snapshot` events), so there is no stored snapshot to diff against. P2.5 adds a small mutable table:

```sql
CREATE TABLE IF NOT EXISTS reentry_marker (
    room_id TEXT NOT NULL, user_id TEXT NOT NULL, last_seen_ts INTEGER NOT NULL,
    PRIMARY KEY (room_id, user_id)
);
```

Upserted at leave-time (`record_leave_marker(room_id, user_id, ts, conn)` — one row per `(room_id, user_id)`, latest-wins, mirroring the P2.4 preference upsert posture), read at return for the diff. It lives in `reentry/store.py` (the consumer owns it; co-located in the same SQLite file via `init_reentry_schema`, per ADR-016 D5's same-file pattern) — **not** in `memory/` (the marker is consumer infrastructure, not a cross-room domain fact). A new event type for the marker was considered and rejected: an `EventType` is for canonical domain facts (Principle 1), and a per-user last-seen pointer is consumer state, not a domain event — a core-vocabulary expansion would be overkill here.

### 6. Tag-derivation — `derive_query_tags(room_id, *, conn) -> list[str]` (code; the Principle-11 boundary)

`lookup_verified_knowledge` *requires* a non-empty `topic_tags` set (ADR-016 D6 raises on empty). So the catch-up must **code-derive which tags to query** — it must NOT let an LLM guess "what's relevant to this user" (Principle 11). The rule: `derive_query_tags` returns the **union of canonical `topic_tags` from the room's recorded hypotheses** (a deterministic code function over `hypothesis WHERE room_id = ?` — via a thin `memory/` reader `list_room_topic_tags(room_id, *, conn)` so `memory/` stays the owner of its table). The room's own topic vocabulary determines which cross-room VK is relevant. If the union is empty (an untagged / first-visit room), `derive_query_tags` returns `[]` and the consumer **skips** the VK lookup (it does not pass `[]` to `lookup` — D9).

The structural guard that the assembly path is LLM-free (D1/D3): a constitutional **AST guard** asserts that `reentry/digest.py`'s assembly + selection functions (`assemble_reentry`, `derive_query_tags`, the diff) reference no `LLMRequest` / `llm_router` / `.call(` — the LLM is confined to `render.py::render_reentry_prose`. This is the Principle-11 "no LLM in selection" enforcement (real AST, not substring — RC-24; mirrors the matcher/validation/preference guards).

### 7. `ReentryDigest` — a new frozen return model (`extra="forbid"`)

`reentry/schema.py`:

```python
class ReentryDigest(BaseModel):               # frozen + extra="forbid"
    room_id: RoomId
    archive: ProjectArchive | None            # get_project_archive(room_id); None on first visit
    recalled_knowledge: list[VerifiedKnowledge]  # lookup result (ordered), [] if no tags
    entities: list[Entity]                    # relevant entities (code-filtered)
    preferences: list[Entity]                 # the user's preferences (type=PREFERENCE)
    new_since_leave: list[dict[str, Any]]     # code diff vs last_seen_ts (typed-light; structured)
    last_seen_ts: int | None                  # the leave-marker (None on first visit)
    generated_at: TimestampMs
```

Frozen + `extra="forbid"` (the schema-invariant pattern). It carries the **code-selected fact-set only**; the prose is the separate `render_reentry_prose` output (kept out of the deterministic model so the tested core is fully deterministic). `new_since_leave` is a structured list of new-fact descriptors (not free text — code-produced).

### 8. Empty / first-visit graceful

The consumer handles the empty cases without crashing (D9 / the cleanup tests): first visit (no `reentry_marker` → `last_seen_ts=None`, `new_since_leave` = everything-or-empty per the rule), no archive (`None`), no VK (skip lookup — do **not** pass `[]`), empty memory. The catch-up degrades to "Welcome — nothing recorded yet" rather than raising.

### 9. A new content-gen `LLMPurpose` (ADR-gated)

`LLMPurpose.REENTRY_DIGEST_RENDER = "reentry_digest_render"` is added to `llm/purposes.py` (the taxonomy says adding a purpose requires an ADR — this is that ADR). It is **content-gen** (prose rendering of a code-assembled fact-set), the only new LLM surface in P2.5, and confined to `reentry/render.py`. (Verify no `LLMPurpose`-exhaustiveness test breaks — add the value to any per-value test, mirror the P2.3 EventType-addition discipline.)

## Considered alternatives

- **Consumer in the rooms/agent layer** instead of a new `reentry/` package (D1). Rejected — the catch-up is a distinct read-side composition surface; a dedicated package keeps the dependency edges + the LLM-free-selection guard scoped and greppable.
- **A leave-marker `EventType`** (Principle-1-canonical) instead of a `reentry_marker` table (D5). Rejected — an `EventType` is for canonical domain facts; a per-user last-seen pointer is consumer state, and a core-vocabulary expansion (a 20th type, ADR-gated) is overkill for it. The table is the lighter, consumer-scoped choice.
- **LLM-derived query tags / LLM relevance selection** (D6). Rejected outright — Principle 11; the LLM choosing which VK is relevant is exactly the no-ground-truth ranking the boundary forbids. Tags are code-derived from the room's hypotheses.
- **Pure-code structured digest, defer the prose render** (architect decision (c)). The architect ruled the MVP **includes** the content-gen render — so the prose ships; the deterministic `ReentryDigest` remains the tested core (the render is exercised, not wording-asserted).
- **Reuse `SNAPSHOT_SEMANTIC` for the render** (D9). Rejected — semantically wrong (that purpose is snapshot free-text fields); a dedicated purpose is the audit-greppability point of the `LLMPurpose` taxonomy.

## Consequences

**Positive**:
- The P2 acceptance milestone — "AI 记得我" — lands as the first consumer of the entire read-side memory surface, exercising every reader (P2.1–2.4) for the first time.
- The code/LLM boundary is a clean function boundary (`assemble_reentry` LLM-free; `render_reentry_prose` the only LLM call), AST-guarded — the strongest Principle-11 expression yet (selection is structurally LLM-free).
- The dependency direction is explicit (`reentry/` consumes; nothing upstream imports it), guarded.

**Negative**:
- A new top-level package + a new persisted table + a new `LLMPurpose` — real surface for a milestone slice; mitigated by the clean module split.
- The prose render is non-deterministic (LLM) — the tested core is the deterministic digest; the prose is exercised but not wording-asserted (a known, accepted seam in the acceptance path — the architect ruled the render ships).
- The leave-marker is consumer state in the shared SQLite file (one more table); justified by the snapshot-is-derived gap.

**Reversibility**:
- Dropping the prose render (revert to pure-code digest): easy — `reenter` returns the digest only; `render.py` + the `LLMPurpose` value retire.
- Moving the marker to an event: an amendment + a new `EventType`; the diff logic is otherwise unchanged.

## Forward-amendment hooks

- **P2.6 extraction producers** feed the containers the catch-up reads; the re-entry contract (this ADR) is what they populate against.
- **Forgetting / 降级** — when memory expiry lands, the catch-up's selection composes the expiry filter (still code).
- **Knowledge-graph relations / richer tag-derivation** — if room-tag derivation proves too narrow, the derivation rule can compose entity relations (still code, Principle 11).
- **Multi-user / team-scope re-entry** — the marker PK already includes `user_id`; team-scope semantics defer.
- **A consumer-tailored read API on `memory/`** — if `assemble_reentry` reveals a missing reader shape, add it to `memory/` (the owner of its tables).

## Cross-references

- `handoff.md` §7 (P2.5 milestone / P2.1→P2.7 序; **note §7's P2.4 row reads stale "IMPL DONE awaiting review" — P2.4 is closed; flagged, not in this task's scope to fix**), §3.1 (code-decides, no LLM in `memory/`), §4.5 (memory data model), §6.1 (the snapshot structural-fields-code / free-text-LLM precedent the render mirrors).
- `chat-history.md` "跨房间记忆" (离开-回来追平 / "AI 记得我" 验收) + "用户偏好的特殊处理" (Principle 11).
- `docs/decisions/ADR-016-cross-room-memory-persistence.md` D6 (`lookup_verified_knowledge` — non-empty `topic_tags`, scope+tag filter, no LLM); `ADR-014-snapshot-contract.md` (`produce_snapshot` derived, persisted only in events — the leave-marker gap); `ADR-020-memory-data-model-completion.md` (the containers + the `assemble_reentry` forward hook + the preference upsert posture the marker mirrors).
- `src/orchestrator/memory/{lookup.py,entity.py,archive.py,store.py}` (the readers consumed; the thin `list_room_topic_tags` reader added), `src/orchestrator/derived/snapshot.py` (`produce_snapshot`), `src/orchestrator/llm/{purposes.py,types.py,protocol.py}` (`LLMPurpose` + `LLMRequest` + `LLMRouter.call` — the render call pattern, mirrors `agents/dispatch.py`).
- `tests/memory/test_constitution.py` (the no-LLM rglob + the AST-guard idiom the LLM-free-selection + no-import-`reentry` guards mirror).
- `docs/process/dual-lens-r0b.md` RC-15 (3/4 — dual-lens dispatched), RC-20; `docs/retrospectives/P2.2-candidates.md` RC-23/RC-24 (substring-scan — this ADR + the guards avoid), RC-25 (count-only-test anti-pattern — the e2e is discriminating).
