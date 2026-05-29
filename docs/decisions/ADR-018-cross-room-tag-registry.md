# ADR-018: Shared cross-room tag registry — canonical tag vocabulary for memory/

**Status:** Proposed — 2026-05-29 (senior-drafted per P2.1 brief; awaiting architect accept)

**Scope:** Locks the shared, canonical tag vocabulary for `memory/`: the `tag` table, the `normalize_tag` canonicalization contract, the `resolve_tags` auto-register semantic, the Hypothesis/VerifiedKnowledge shared-vocabulary decision (both resolve their `topic_tags` through one registry), the `Hypothesis.topic_tags` schema addition + the first ALTER-TABLE column-add migration template for `memory/`, and the refinement of cross-room lookup to normalized-exact matching. Governs the vocabulary substrate that the P2.2 matcher (cross-room rule (a)) and `lookup_verified_knowledge` both ride on. Does NOT govern matching/consumption (P2.2), agent-side tag-proposal wiring (a later content-gen slice), promotion eligibility or the no-auto-promote invariant (ADR-016 D3/D10 — unchanged), or FK-normalized tag storage (deferred).

## Context

ADR-016 (already accepted; P1.6.5 closed) shipped the cross-room memory substrate: `Hypothesis` + `VerifiedKnowledge` persisted, `record_hypothesis`, `promote_hypothesis`, and `lookup_verified_knowledge`. `VerifiedKnowledge.topic_tags` exists (`schema.py:109`); `Hypothesis` has no tags yet. The cross-room matcher (promotion rule (a)) was deferred — its blocking problem was tag *consistency*: matching on tags only works if the same claim gets the same tags across rooms, and free-form (especially LLM-assigned) tags paraphrase and never match.

The architect resequenced P2 (decision B3, 2026-05-29): the tag registry is the real foundation and ships first as its own slice; the matcher is its downstream consumer (re-briefed as P2.2, reserving ADR-017). This ADR is the registry slice.

The structural/code matching path (architect-settled) needs a **shared canonical vocabulary** so consistency is a structural property, not a semantic guess. The registry follows the project's standing "controlled vocabulary" instinct (event types, room types, scopes, skill ids): **LLM stays in content-gen** (an agent proposes tags — a later slice), **code owns structure** (normalization + registry membership + matching). `memory/` never calls an LLM (Principle 5; `tests/memory/test_constitution.py`).

**Honest ceiling** (load-bearing — do not over-claim): pure-code matching cannot *guarantee* open-domain tag consistency — that needs either a rigid closed vocabulary or semantics (embeddings, the deferred path). This registry is **best-effort**: it makes consistency *possible and cheap* (a producer can reuse an existing canonical tag) but does not *force* it. The reuse-pressure — showing an agent the existing tags and prompting reuse — is a later agent-wiring slice. P2.1 ships the mechanism; the intelligence that drives reuse comes later. Without that later slice, two producers can still coin divergent tags for the same concept; the registry only guarantees that *identical-after-normalization* tags collapse to one canonical form.

This ADR governs three forces:
- **Principle 5 (code-driven structure, LLM-generated content)** — `normalize_tag` / `resolve_tags` are pure code; tag *content* may originate from an LLM but only via the agent layer, never inside `memory/`. The existing constitutional rglob guard covers the new files.
- **Principle 11 (determinism)** — `normalize_tag` and `resolve_tags` are deterministic: same inputs → same canonical output + same registry effect, independent of scan order.
- **ADR-016 honored** — D3/D10 untouched; D6 (lookup) is *refined* to normalized-exact and the refinement is documented here (not silently changed); D11 promotion atomicity is preserved (registry writes ride the existing transaction).

## Decisions

### 1. One shared canonical tag registry; descriptive (auto-register), not curated

A single `tag` vocabulary in `memory/`. Both `Hypothesis` and `VerifiedKnowledge` resolve their `topic_tags` through it (`resolve_tags`), so the two draw from one vocabulary across the record → promote lifecycle and across rooms. The registry is **descriptive** (it records what tags have been used), **not curated** (no human/LLM gate decides membership). New normalized tags **auto-register** (D4). Rationale: the registry's job is consistency-by-reuse, not access control; a gating step adds friction with no consistency benefit at this slice (and any "should this tag exist" judgment would be semantic — out of `memory/`).

### 2. `tag` table — canonical-string primary key + `created_at`

In the event_store SQLite file (same placement as ADR-016 D5; DDL owned by `init_memory_schema`, NOT `core/`):

```sql
CREATE TABLE IF NOT EXISTS tag (
    canonical TEXT PRIMARY KEY,      -- the normalized canonical form (D3)
    created_at INTEGER NOT NULL      -- TimestampMs of first registration
);
```

- **PK = canonical string** (push-back #4, lean confirmed): the canonical form *is* the identity; a `TEXT PRIMARY KEY` gives the UNIQUE constraint for free and makes `INSERT OR IGNORE` the natural idempotent auto-register (D4). No surrogate id — `Hypothesis.topic_tags` / `VK.topic_tags` store canonical **strings** (D6), so a surrogate would add a join with no consumer this cycle.
- **`created_at`** records first registration (descriptive provenance). **No `usage_count`** this cycle — no consumer needs it; incrementing it on every resolve would add a write + a contention point for zero current benefit (forward hook if a "popular tags" surface materializes).
- **Concurrency** (test-coverage §2): two concurrent resolves of the same new tag must not double-insert. `INSERT OR IGNORE` against the PK is the guard — the second insert is a silent no-op; no error, no duplicate. (P2.1 is single-connection sequential per ADR-011 D1; this is defense for any future writer, the same posture as ADR-016 D2's UNIQUE.)

### 3. `normalize_tag(raw: str) -> str` — deterministic canonicalization

Pure function in `memory/tags.py`. The canonical form is:

1. `strip()` leading/trailing whitespace,
2. `lower()` (simple ASCII-and-Unicode lowercasing — deterministic; **not** `casefold()`, which over-normalizes, e.g. `ß→ss`, risking distinct-concept collisions),
3. collapse internal whitespace runs and replace whitespace with a single hyphen `-` (i.e. `re.sub(r"\s+", "-", s)` after strip).

No punctuation stripping and no Unicode NFC normalization (push-back #1, lean = minimal + conservative): stripping punctuation would collide distinct concepts (`c++` vs `c`, `f#` vs `f`); aggressive Unicode folding is unjustified without a use case. The rule is the floor that makes the brief's worked example hold — `"LLM Cost"` → `"llm-cost"`, `"  ML "` → `"ml"`, `"Foo  Bar"` → `"foo-bar"`, `"llm-cost"` → `"llm-cost"` (idempotent on already-canonical input). Whitespace-only or empty input → `""` (the empty string; `resolve_tags` is where the empty-tag *policy* lives, D4 — `normalize_tag` itself is policy-free).

**Known near-miss edge — hyphens are not collapsed** (G3, pinned): whitespace adjacent to a literal hyphen yields multiple hyphens — `"LLM - Cost"` → `"llm---cost"` (each whitespace run becomes its own `-`, and the literal `-` survives) — and `"llm cost"` / `"llm-cost"` stay distinct. This is deterministic (so cross-room consistency still holds for identical inputs) but does not collapse near-misses. It is the conservative-rule tradeoff (D3 owns it); these cases are pinned in the boundary tests so the canonical form is on the record rather than discovered later.

Determinism: the function is a pure string transform with no I/O, no locale dependence beyond `str.lower()` (which is deterministic per the Unicode default casing), no randomness. Same input → same output, always.

### 4. `resolve_tags(proposed, conn) -> TagResolution` — normalize, dedup, auto-register; transaction-neutral

Pure-code function in `memory/tags.py`:

- Normalize each proposed tag via `normalize_tag`.
- **Reject empty-normalized tags**: if any proposed tag normalizes to `""` (whitespace-only / empty), raise `ValueError` (fail-loud — a tag that vanishes under normalization is a producer bug, not a silently-droppable input; symmetric with `lookup_verified_knowledge`'s empty-tags `ValueError`, ADR-016 D6).
- **Dedup** after normalization, **preserving first-occurrence order** (two proposed tags normalizing to the same canonical collapse to one; order is deterministic given input).
- Split into {already in `tag` table} vs {new}; **auto-register the new** via `INSERT OR IGNORE INTO tag (canonical, created_at) VALUES (?, ?)` (D2; D1 auto-register).
- Return a small frozen `TagResolution` result: `canonical: list[str]` (the deduped canonical list to store) + `newly_registered: list[str]` (which were new this call — observable for tests/callers; carries no authority). Exact field names are an impl detail; the two pieces of information are fixed by this decision (push-back #5).

**Transaction-neutral** (the load-bearing composition decision): `resolve_tags` executes its SELECT + `INSERT OR IGNORE` on the passed `conn` and **does not commit** — the caller owns the transaction. This is what lets it compose inside the existing write transactions without breaking atomicity: `record_hypothesis`'s `with conn:` block (store.py:151) and `promote_hypothesis`'s `with conn:` promotion transaction (promotion.py:100; ADR-016 D11) host the registry writes, so a failed record/promotion rolls back the auto-registered tags too. Mirrors `EventStore.append_in_transaction`'s caller-managed posture (ADR-016 D11). Pure code, no LLM.

### 5. `Hypothesis.topic_tags` + first ALTER-TABLE column-add migration

`Hypothesis` (`schema.py:88-94`) gains `topic_tags: list[str] = Field(default_factory=list)` — frozen + `extra="forbid"` preserved, mirroring `VerifiedKnowledge.topic_tags` (`:109`). Optional / default-empty (architect-settled #4): an untagged hypothesis is valid; it simply contributes nothing to future matching.

The `hypothesis` table gains `topic_tags TEXT NOT NULL DEFAULT '[]'` (JSON list, §5.8 pattern; **with** a default so existing rows backfill). This is the **first ALTER-not-CREATE migration in `memory/`** — `CREATE TABLE IF NOT EXISTS` (store.py:89, `executescript`) will not add a column to a pre-existing `hypothesis` table. `init_memory_schema` adds, after the `executescript`, an idempotent guarded ALTER:

```python
def _ensure_hypothesis_topic_tags(conn: sqlite3.Connection) -> None:
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(hypothesis)")}
    if "topic_tags" not in cols:
        conn.execute(
            "ALTER TABLE hypothesis ADD COLUMN topic_tags TEXT NOT NULL DEFAULT '[]'"
        )
```

This pins the **column-add migration template** the project lacked: `PRAGMA table_info` guard + `ALTER TABLE ... ADD COLUMN ... NOT NULL DEFAULT <const>` (SQLite backfills the constant default into existing rows), idempotent, verified by an on-disk round-trip test (mirror ADR-016 D5 / external-Y11: pre-P2.1 hypothesis table → reopen → `init_memory_schema` → old rows read `topic_tags == []`, row counts preserved). The `tag` table itself is a plain `CREATE TABLE IF NOT EXISTS` (a new table needs no ALTER; it appears on both fresh and migrated DBs).

### 6. Write-path shares the vocabulary; tags stored as canonical denormalized strings

Both producers route their tags through `resolve_tags` and store the canonical strings:

- `record_hypothesis(..., topic_tags=None)` (new keyword-only param, optional, default empty — preserves existing callers): inside its existing `with conn:` block, call `resolve_tags(topic_tags or [], conn)` and store `TagResolution.canonical` as the JSON `topic_tags`.
- `promote_hypothesis(..., topic_tags=None)` (param already exists, promotion.py:42): route the VK `topic_tags` through `resolve_tags(..., conn=event_store.conn)` **inside** the existing `with conn:` promotion block (promotion.py:100) — placed **after** the `UPDATE hypothesis` (line 103) and **before** the VK `INSERT` (line 112). Because `resolve_tags` is transaction-neutral (D4), its `INSERT OR IGNORE` joins the single D11 transaction and rolls back with a failed promotion — atomicity preserved. The `append_in_transaction` `in_transaction` guard is already satisfied by the existing DML-first `UPDATE`, so `resolve_tags`'s placement after it is unambiguous (it does not need to be the transaction-opening statement). NB: this is the *inside-the-block* location, not the pre-block `topic_tags or []` site at promotion.py:95.

**Contract tightening — `promote_hypothesis` / `record_hypothesis` now raise `ValueError` on an empty-normalizing tag** (G3, made explicit): routing tags through `resolve_tags` (D4) means a whitespace-only / empty tag now raises `ValueError` at write, where pre-P2.1 `promote_hypothesis` stored whatever it was given. This is a deliberate fail-loud tightening of the producer contract vs ADR-016 (a tag that vanishes under normalization is a producer bug). Tested explicitly so it is not a silent behavior change.

**Storage form = canonical strings, denormalized** (push-back #5, lean confirmed): `Hypothesis.topic_tags` / `VK.topic_tags` keep storing JSON string lists of canonical tags — minimal change, no schema reshape. FK-to-`tag`-id storage is heavier and has no query needing it this cycle (deferred; forward hook).

### 7. Cross-room lookup refined to normalized-exact — normalize BOTH query and stored tags at match-time (refines ADR-016 D6; ADR-016 not edited)

`lookup_verified_knowledge` (lookup.py) normalizes **both** the query `topic_tags` **and** each row's stored `topic_tags` through `normalize_tag` at match-time, before the set-intersection:

```python
query_set = {normalize_tag(t) for t in topic_tags}          # query side
row_tags  = {normalize_tag(t) for t in json.loads(row["topic_tags"])}  # stored side
if query_set & row_tags: ...
```

So a non-canonical query (`"LLM Cost"`) hits a canonical stored tag (`"llm-cost"`) **and** a legacy raw-stored tag (`"LLM Cost"`) — both normalize to `"llm-cost"` at read time. This **refines** ADR-016 D6's "exact match" to "normalized-exact match on both sides".

**Why both sides, not just the query** (Y1 → α, plan-stage R0-A routing): normalizing only the query silently assumes stored tags are already canonical — but D8 (no backfill) guarantees that pre-P2.1 VK rows are **not** (the old `promote_hypothesis` stored `topic_tags or []` un-normalized; `promotion.py:120`). Query-only normalization would make `lookup(["LLM Cost"])` miss a row stored raw as `["LLM Cost"]` — a regression vs pre-P2.1 exact-match. Normalizing **both** sides makes legacy raw rows and new canonical rows both findable, so D8's no-backfill is sound rather than a latent edge. Cost: one `normalize_tag` per stored tag per scanned row — negligible (ADR-016 D6 already assumes small per-scope row counts + a Python post-filter scan).

**The refinement is recorded here and cross-links ADR-016 D6; ADR-016 is NOT edited in place** (push-back #2, lean confirmed). Two reasons: (a) ADR-016 is already accepted and closed — recording the refinement in the active ADR keeps the audit trail where the change is decided; (b) editing ADR-016's prose risks the RC-23 accept-gate trap (`_parse_adr_status` whole-file substring scan) near its status region. ADR-016 D6's other semantics are unchanged: empty query `topic_tags` still raises `ValueError`; OR-semantics, `last_validated DESC, id ASC` ordering, no-LLM all hold. Only the match-time normalization (both sides) is added.

### 8. Emergent-only; no backfill; no synonym/alias merging

The registry grows only from new `resolve_tags` calls (push-back #3, lean confirmed). Existing pre-P2.1 hypothesis/VK rows are **not** back-filled into the `tag` table — no consumer needs the registry to contain historical tags this cycle (the matcher, P2.2, scans `topic_tags` on rows directly, not the `tag` table). Synonym-merging / alias resolution / curated closed vocabulary are **out** — they are semantic judgments that would reopen the LLM line (Principle 5). Forward hook.

## Considered alternatives

- **FK-normalized tag storage** (`topic_tags` as tag-ids referencing `tag`). Rejected this cycle — heavier (join on every read), no query needs it; canonical-string denormalized storage is the minimal change. Forward hook if a query requires tag-id joins.
- **Curated / closed vocabulary with candidate-gating** (new tags require confirmation). Rejected — architect-settled auto-register; gating adds friction with no consistency benefit, and "should this tag exist" is a semantic judgment (out of `memory/`).
- **`casefold()` instead of `lower()` in `normalize_tag`**. Rejected — over-normalizes (`ß→ss`, etc.), risking distinct-concept collisions; `lower()` is the conservative floor.
- **Strip punctuation / NFC-normalize Unicode in `normalize_tag`**. Rejected — collides distinct concepts (`c++`/`c`); unjustified without a use case. Forward hook.
- **Amend ADR-016 D6 in place** (push-back #2). Rejected — touching the closed, accepted ADR-016 risks the RC-23 accept-gate trap and scatters the decision; recording the refinement in ADR-018 + cross-linking keeps the audit trail coherent.
- **`resolve_tags` commits its own transaction**. Rejected — would break the composition into `promote_hypothesis`'s D11 atomic transaction (auto-registered tags would persist even if the promotion rolled back). Transaction-neutral is required for atomicity.
- **`usage_count` column on `tag`**. Rejected this cycle — a write + contention point on every resolve for zero current consumer. Forward hook.
- **Backfill the registry from existing rows** (push-back #3). Rejected — emergent-only; no consumer needs historical tags; the matcher reads row `topic_tags` directly.

## Consequences

**Positive**:
- The vocabulary foundation the P2.2 matcher needs — tag consistency becomes a structural property (identical-after-normalization tags collapse) rather than a semantic guess.
- Pins the column-add ALTER-TABLE migration template (`PRAGMA table_info` guard + `ADD COLUMN ... DEFAULT`) that the project lacked — inherited by every future `memory/` column addition.
- `Hypothesis` and `VK` share one vocabulary across the record → promote lifecycle, so a hypothesis's tags carry into its promoted VK and into cross-room lookup consistently.
- Constitution-clean (pure code, no LLM) and deterministic.

**Negative**:
- Best-effort only: without the later agent reuse-wiring slice, producers can still coin divergent tags for the same concept; the registry guarantees only normalization-collapse, not semantic consistency. (Honest ceiling, Context.)
- `normalize_tag`'s conservative rules mean near-misses don't collapse (`"llm cost"` and `"llm-costs"` stay distinct) — acceptable; aggressive normalization risks worse (distinct-concept collisions).
- `record_hypothesis` gains a parameter (keyword-only, optional — backward-compatible); a 5-surface touch.
- ADR-016 D6's contract is now split across two ADRs (D6 + this D7). Mitigated by the explicit cross-link; a reader of D6 must follow it to ADR-018 for the normalized-query refinement.

**Reversibility**:
- Removing the registry: moderate — drop `tag` table + `tags.py`, revert the write-path routing to store raw tags. `Hypothesis.topic_tags` and lookup normalization could stay independently.
- Removing `Hypothesis.topic_tags`: harder (SQLite column drop needs a table rebuild; no migration tooling) — ~1 hour, same cost class as ADR-016's `candidate_for_promotion` note.
- Reverting the D6 lookup refinement: trivial — drop the query `normalize_tag` call; exact-match returns.

## Forward-amendment hooks

- **Agent-side tag-proposal / reuse wiring**: when an agent-layer surface proposes tags and is shown the existing registry to drive reuse (content-gen), it sinks into `resolve_tags`. Stays outside `memory/`.
- **FK-normalized tag storage**: when a query needs tag-id joins (e.g. rename-a-tag-everywhere, or tag-cardinality analytics), reshape `topic_tags` storage to FK ids referencing `tag`.
- **Richer normalization** (punctuation, Unicode NFC, stemming): if real tag data shows the conservative rule misses obvious matches, amend D3 — accepting the collision-risk analysis then warranted.
- **Synonym / alias merging, curated vocabulary**: a semantic layer (likely LLM-assisted, agent-side) that maps distinct canonical tags to a shared concept — out of `memory/`; its own ADR.
- **`usage_count` / popularity surface**: if a "most-used tags" consumer materializes, add the column + increment-on-resolve.

## Cross-references

- `docs/decisions/ADR-016-cross-room-memory-persistence.md` — D2 (`Hypothesis`/`VK` schema; `Hypothesis` gains `topic_tags`), D3/D10 (UNCHANGED), **D6** (lookup — *refined* to normalized-exact by D7 here; ADR-016 not edited), D5 / external-Y11 (on-disk migration template), D11 (promotion transaction — `resolve_tags` writes on the same connection, transaction-neutral). ADR-016 is already accepted and closed.
- `docs/decisions/ADR-017-*` — reserved for the deferred cross-room matcher (P2.2), the downstream consumer of this registry. Not created by this slice.
- `src/orchestrator/memory/schema.py:88-94` (`Hypothesis` — gains `topic_tags`), `:109` (`VerifiedKnowledge.topic_tags` — the mirror).
- `src/orchestrator/memory/store.py:33-47,80-90` (`_MEMORY_SCHEMA` — gains `tag` table; `init_memory_schema` — gains the guarded ALTER), `record_hypothesis` (gains `topic_tags` param + `resolve_tags` routing), `_row_to_hypothesis` (reads `topic_tags`).
- `src/orchestrator/memory/promotion.py:42,100-129` (VK write path — routes `topic_tags` through `resolve_tags` inside the D11 transaction).
- `src/orchestrator/memory/lookup.py` (query normalization — the D6 refinement).
- `tests/memory/test_constitution.py` (no-LLM rglob — covers the new `tags.py`).
- `docs/retrospectives/P2.1-candidates.md` RC-23 — the accept-gate parser trap this ADR's prose avoids (paraphrase other ADRs' acceptance, never quote their status line verbatim).
- `handoff.md` §3.1 (code-decides structure), §4.5 (cross-room memory), §5.8 (persistence / migration).
