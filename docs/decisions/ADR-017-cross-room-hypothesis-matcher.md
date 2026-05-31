# ADR-017: Cross-room hypothesis matcher — promotion rule (a), structural on the registry vocabulary, advisory-only

**Status:** Accepted — 2026-05-31 (architect sign-off after R0-A-on-plan + R0-B-cross-family clean, A→α/B→α/G2→α-small absorbed at d9003a7; Proposed 2026-05-30, senior-drafted per P2.2 brief)

**Scope:** Locks the cross-room hypothesis matcher for promotion rule (a): the `run_matcher` contract (grouping predicate over the registry's canonical tag vocabulary, distinct-room threshold, eligibility, determinism, idempotency, monotonicity), the normalize-at-read decision, the advisory-only orthogonality to promotion, and the `list_promotion_candidates` reader. Activates the `candidate_for_promotion` column + `idx_hypothesis_status_candidate` index (shipped unused by ADR-016) on top of the P2.1 tag registry (ADR-018). Governs every downstream memory-intelligence + UI promotion-candidate surface that consumes rule (a). Does NOT re-decide the tag schema/migration (inherited from ADR-018 — D7 below), promotion eligibility or the no-auto-promote invariant (ADR-016 D3/D10 — unchanged), semantic/embeddings matching (deferred), relaxed predicates / un-flagging / cluster-identity / auto-tagging (deferred forward hooks).

## Context

This is the matcher slice, resequenced out of the original P2.1 by the architect's B3 decision: the shared tag registry shipped first as P2.1 (ADR-018, now closed and merged on `main`); the matcher is its downstream consumer, P2.2. ADR-017's number was reserved for it across that resequence.

The substrate this rides on, **verified against `origin/main`** (not the superseded pre-registry matcher draft):

- `Hypothesis.topic_tags: list[str]` exists (`schema.py:94`, frozen + `extra="forbid"`); `VerifiedKnowledge.topic_tags` mirrors it (`:110`). The `topic_tags TEXT NOT NULL DEFAULT '[]'` column + the `_ensure_hypothesis_topic_tags` ALTER migration are on `main` (`store.py`). **There is no schema add and no migration to write in this slice** — it is inherited from ADR-018 (D7).
- `normalize_tag(raw) -> str` exists (`memory/tags.py:18`): `strip → lower → re.sub(r"\s+","-")`. `record_hypothesis` routes `topic_tags` through `resolve_tags`, so **stored Hypothesis tags are already canonical** (or `[]` for pre-registry / untagged rows).
- `candidate_for_promotion INTEGER NOT NULL DEFAULT 0` (`store.py:41`) + `idx_hypothesis_status_candidate ON hypothesis(status, candidate_for_promotion)` (`store.py:48`) ship unused (ADR-016 D7). The matcher is the first code to write the column; the reader is the first to use the index.

The matcher was deferred from ADR-016 for one reason: matching on tags only works if the same claim gets the same tags across rooms, and free-form tags paraphrase. The registry (ADR-018) resolved that by making consistency a **structural** property: tags are canonicalized through `normalize_tag` at record-time. The matcher consumes that — it groups hypotheses by **canonical tag-set equality** and, for groups spanning ≥N distinct rooms, flips `candidate_for_promotion = True` so the user is *shown* cross-room-corroborated candidates to (manually) promote.

**Advisory only.** The matcher never promotes; `promote_hypothesis` (ADR-016) remains the sole promotion path and stays user-confirm. A false positive costs a declined suggestion; a false negative costs a missed suggestion the user can still promote manually. This is materially different from the "misleadingly weak matcher" ADR-016 rejected: it matches on **deliberate, registry-canonical tags** (not paraphrase-prone raw content) and it is **advisory** (it surfaces a candidate, never gates the permanent promotion act).

This ADR governs three forces:
- **Principle 5 (code-driven decisions)** — matching is pure code over the registry vocabulary; no LLM, no embeddings in `memory/`. The existing constitutional rglob covers `matcher.py`; this slice adds a structural orthogonality guard.
- **Principle 11 (determinism)** — same hypothesis set → same flagged set regardless of SQLite scan order. The flagged id-set is a pure function of `{(id, room_id, canonical-tag-set, status)}`; the predicate is chosen partly *because* it yields a clean order-independent partition (D3).
- **Advisory orthogonality (ADR-016 D3/D10)** — the flag is derived advisory state, not a promotion precondition and not a user decision; it emits no canonical event.

## Decisions

### 1. Structural / code matching, reusing the registry's `normalize_tag`

The matcher groups hypotheses by their **canonical tag-set**, where canonical means the registry's `normalize_tag` — NOT an ad-hoc `.lower()`. The grouping key is:

```python
from orchestrator.memory.tags import normalize_tag
key = frozenset(normalize_tag(t) for t in hypothesis_topic_tags)
```

**Why reuse `normalize_tag` (the central rebase point):** the tags were registered under `normalize_tag`'s canonical form at record-time. If the matcher reinvented normalization (e.g. `t.lower()`), its canonical form would silently diverge from the vocabulary the tags were stored under — `"LLM Cost"` registers as `"llm-cost"` (whitespace → hyphen) but an ad-hoc `.lower()` key would be `"llm cost"`, so the matcher would group on a different key than the registry's, and two rooms recording the same claim via different surface forms would fail to corroborate. Reuse keeps the matcher's equivalence relation identical to the registry's. No LLM in `memory/`.

The empty canonical set (`frozenset()` — an untagged or `[]`-tagged hypothesis) is **excluded from grouping**: an untagged hypothesis is not corroboration and never matches.

### 2. Normalize at read (defense-in-depth; mirrors lookup's both-sides)

The matcher applies `normalize_tag` to each **stored** tag when building the group key, rather than trusting the stored value to already be canonical (push-back #1).

**Why re-normalize at read** even though `record_hypothesis` already canonicalizes at write:
- It is **cheap** — one `normalize_tag` per stored tag per scanned PENDING row, in a small in-process scan (same cost class the registry's lookup already pays).
- It is **robust against any raw-insert path** — a test fixture, a future bulk import, or any producer that writes `Hypothesis.topic_tags` without going through `record_hypothesis`/`resolve_tags` would store non-canonical tags; normalize-at-read keeps those correctly grouped.
- It is the **same defense `lookup_verified_knowledge` chose** (ADR-018 D7 / P2.1 Y1→α "both-sides normalization"): lookup normalizes both the query and the stored tags at match-time precisely so legacy raw-stored rows stay findable without backfill. The matcher is the read-side analogue; using the same posture keeps the two cross-room read paths consistent (a reader should not have to know whether a given row went through `resolve_tags`).

The considered alternative — trust-stored-canonical (one fewer normalize pass, relying on the registry's write-time guarantee) — is sound *today* (all `record_hypothesis`-written rows are canonical; pre-registry rows are `[]` and excluded). It is declined because the marginal cost of re-normalizing is negligible and the robustness against raw-insert paths is worth it, exactly as lookup judged. The parallel to lookup's both-sides decision is the deciding argument.

**Required property — `normalize_tag` idempotency** (G2, cross-family-surfaced): normalize-at-read is correct only because `normalize_tag` is **idempotent** — `normalize_tag(normalize_tag(x)) == normalize_tag(x)`. Re-normalizing an already-canonical stored tag must be a guaranteed no-op, or the matcher's group key would diverge from the registry's stored canonical form (the very divergence D1 exists to prevent). The property holds for the current rule (`strip → lower → re.sub(r"\s+","-")` produces output with no leading/trailing whitespace, all-lowercase, no whitespace runs — a second pass changes nothing) and is exercised by P2.1's `normalize_tag` tests. It is **load-bearing across the ADR-018→ADR-017 boundary**: a future `normalize_tag` amendment (ADR-018 D3's "richer normalization" forward hook — punctuation/Unicode/stemming) **must preserve idempotency**, or it silently breaks the matcher's normalize-at-read equivalence with the registry. Inscribed here so the cross-slice dependency is explicit (see the ADR-018 D3 cross-reference note).

### 3. Grouping predicate — exact canonical tag-set equality

Two PENDING hypotheses are in the same group iff their normalized tag-sets (D1/D2) are **identical** (`frozenset` equality).

**Why exact set-equality over Jaccard ≥ θ / ≥K-shared** (carried from the steered design, re-confirmed post-rebase): exact set-equality is the **only equivalence relation** of the candidates (reflexive, symmetric, *transitive*). A clean partition is what "a group spans ≥ N distinct rooms" requires to be well-defined and order-independent. Jaccard ≥ θ and ≥K-shared are pairwise-similarity predicates that are **not transitive** (A~B and B~C does not give A~C), so "groups" become connected components of a similarity graph — order-sensitive to construct, ambiguous in membership, and gated on a magic threshold with no principled P2.2 value. Precision (an advisory flag must not be noisy), Principle-11 determinism, and simplicity all converge on exact equality. The cost — brittleness (one differing canonical tag → no match) — is acceptable because the matcher is advisory and fail-safe (a missed near-match is promotable manually). Relaxation to a clustering predicate is a documented forward hook.

### 4. Matcher contract — `run_matcher(conn, *, min_rooms=2) -> MatcherResult`

`src/orchestrator/memory/matcher.py`. Single explicit, on-demand batch API (not auto-on-record — mirrors `lookup`/`promote`/registry explicit-API patterns):

```python
def run_matcher(conn: sqlite3.Connection, *, min_rooms: int = 2) -> MatcherResult:
    """Scan PENDING hypotheses; group by canonical tag-set equality (via
    normalize_tag); for any group spanning >= min_rooms DISTINCT room_ids, set
    candidate_for_promotion=True on those rows. Pure code, no LLM. Deterministic,
    idempotent, monotonic (False->True only)."""
```

- **Eligibility**: scans only `status == 'pending'` rows (matches promotion eligibility; verified/rejected/stale are out of the candidate pool).
- **Distinct-room threshold**: a group is flagged iff it contains ≥ `min_rooms` **distinct `room_id`s**. Same claim re-recorded in one room is NOT cross-room corroboration — count distinct rooms, not rows. `min_rooms` default 2; "distinct" = distinct `room_id`. `min_rooms < 1` raises `ValueError`.
- **Write**: `UPDATE hypothesis SET candidate_for_promotion = 1 WHERE id IN (<flagged ids>) AND status = 'pending'`. The `AND status = 'pending'` is defensive against a status change between scan and update (single-connection sequential in P2.2 per ADR-011 D1; the guard is cheap insurance, and the reader filters PENDING anyway).
- **Determinism (Principle 11)**: the flagged id-set is a pure function of the scanned rows' `{(id, room_id, canonical-tag-set, status)}` — it does **not** depend on scan order (set operations are order-independent). Hypotheses are sorted by `id` before grouping only for **stable `MatcherResult` reporting and a deterministic UPDATE id-list**, not for flag correctness. The e2e asserts the flagged set is stable across shuffled input.
- **Idempotency**: re-running is a no-op on already-flagged rows (the UPDATE only changes `candidate_for_promotion = 0` rows within a qualifying group; a second run finds them already `1`, and `rows_newly_flagged == 0`).
- **Monotonicity**: only `False → True`. Un-flagging (True → False when a cluster dissolves) and full recompute are deferred (forward hooks); the matcher never clears a flag.

### 5. `MatcherResult` shape

A small frozen result object (push-back #3): `groups_inspected: int` (canonical tag-set groups examined) + `rows_newly_flagged: int` (rows flipped False→True this run). Observable for callers/tests; **carries no promotion authority** — it is a report, not a gate. Minimal by intent; richer reporting (which clusters, which rooms) is a forward hook tied to cluster-identity persistence.

### 6. Reader — `list_promotion_candidates(conn) -> list[Hypothesis]`

So the flag is consumable end-to-end (without it, the matcher writes a flag nothing reads). Co-located with `run_matcher` in `matcher.py` (push-back #4). Returns `status == 'pending'` AND `candidate_for_promotion = True` rows as frozen `Hypothesis` models (reusing `store._row_to_hypothesis`), ordered by `id` ASC (deterministic) — covered by the existing `idx_hypothesis_status_candidate` index. **No scope argument** (`Hypothesis` has no scope field — `schema.py:87-95`).

### 7. Schema + migration inherited from ADR-018 / ADR-016 — NOT re-decided here

The matcher writes `candidate_for_promotion` and reads `topic_tags`; both columns, the `idx_hypothesis_status_candidate` index, and the `topic_tags` ALTER migration are **already on `main`** (ADR-016 D2/D7 for the candidate column + index; ADR-018 D2/D5 for `topic_tags` + the migration template). This ADR records that it **inherits** them and does not re-open or re-decide them. There is no DDL, no `ALTER TABLE`, and no schema atomic in this slice — a contributor who finds themselves writing one has misread the rebase.

### 8. Fresh ADR-017 (not an amendment to ADR-018 or ADR-016)

The matcher is a standalone decision (predicate, advisory semantic, normalize-at-read, the reader). It reuses the reserved ADR-017 number (held across the B3 resequence). It is **not** an amendment to ADR-018 or ADR-016 (push-back #5): both are closed/accepted, and amending an accepted ADR risks the RC-23 accept-gate trap (`_parse_adr_status` whole-file substring scan) near its status region — the same reasoning the registry used for not editing ADR-016's D6 in place. A fresh ADR-017 with a Proposed status gets a clean architect accept-gate. This ADR cites ADR-016 D3/D10 and ADR-018 D3/D4/D7 as unchanged dependencies; it activates ADR-016 D7's `candidate_for_promotion` as-shipped and supersedes the "matcher deferred" note.

## Considered alternatives

- **Reinvent normalization (`t.lower()`) instead of reusing `normalize_tag`** (D1). Rejected — the matcher's canonical form would diverge from the registry's (whitespace handling differs), so same-claim/different-surface-form rows across rooms would not corroborate. Reuse is the whole point of the rebase.
- **Trust stored-canonical; do NOT re-normalize at read** (push-back #1 / D2). Rejected as the default — sound today but not robust against raw-insert paths; the re-normalize pass is negligible and matches lookup's both-sides posture. Kept as a documented option if profiling ever shows the read-normalization material (it won't at expected scan sizes).
- **Jaccard ≥ θ / ≥K-shared predicate** (push-back #2 / D3). Rejected — non-transitive, so grouping degrades to order-sensitive similarity-graph components gated on a magic threshold. Forward hook.
- **Amend ADR-018 or ADR-016 instead of a fresh ADR-017** (push-back #5 / D8). Rejected — standalone decision; amending a closed/accepted ADR risks the RC-23 trap and scatters the decision.
- **Auto-run the matcher on `record_hypothesis`**. Rejected — couples persistence to a full PENDING scan on every record; the explicit batch API mirrors `lookup`/`promote`/registry. Forward hook.
- **Un-flag / recompute (True → False)**. Rejected for P2.2 — monotonic is simplest + idempotent; un-flagging has no consumer and only corrects a flag the user can already ignore. Forward hook.
- **Cluster-identity persistence (`cluster_id` column + grouped reader)**. Rejected — the boolean flip is the minimum that makes the flag consumable; persisting which cluster a candidate belongs to defers until a consumer needs to show clusters distinctly. Forward hook.
- **Make the flag a promotion precondition**. Rejected — would couple advisory detection to the user-confirm path, violating ADR-016 D3's flag-independent eligibility. A future architect call (ADR-016 forward hook), not this ADR.

## Consequences

**Positive**:
- First cross-room *decision function* — the first code that makes a cross-room determination (corroboration across rooms). Activates the `candidate_for_promotion` column + index that shipped unused since ADR-016.
- First cross-room memory *intelligence* surface; a concrete step toward the P2 acceptance feel ("第二次使用能看到'AI 记得我'") — cross-room corroboration surfaced as promotion candidates.
- Consistent with the registry: reusing `normalize_tag` + normalize-at-read keeps the matcher's equivalence relation identical to the vocabulary the tags were stored under, and its read posture identical to lookup's.
- Advisory-only orthogonality keeps the promotion path (ADR-016) untouched: the matcher is purely additive; removing it would not affect promotion.

**Negative**:
- Exact tag-set equality is brittle (one differing canonical tag → no match). Mitigated: advisory + fail-safe (manual promotion always available); relaxation is a forward hook.
- The matcher is dormant-until-fed — it only surfaces candidates for hypotheses that carry tags, and an auto-tagging producer is a later agent-layer slice. Acceptable: same inscribe-mechanism-before-producer posture as the registry.
- One more public surface in `memory/` (`run_matcher` + `list_promotion_candidates`); justified by activating rule (a).

**Reversibility**:
- Removing the matcher: easy — delete `matcher.py` + the orthogonality guard + the e2e; the `candidate_for_promotion` column reverts to dormant (as before P2.2). No promotion-path impact.
- Changing the predicate (exact-equality → clustering): an ADR-017 amendment; the `run_matcher` signature is stable, only the internal grouping changes (plus possibly a θ/K parameter).
- Switching normalize-at-read → trust-stored: trivial (drop the per-stored-tag `normalize_tag` call); only safe if every writer is guaranteed to go through `resolve_tags`.

## Forward-amendment hooks

- **Exact-equality too brittle in practice**: amend D3 toward a clustering predicate (Jaccard ≥ θ / ≥K-shared via connected components), accepting the order-stability + threshold-justification design then warranted.
- **Un-flagging / recompute**: when a consumer needs flags to retract as clusters dissolve, amend D4's monotonicity (add a recompute-from-scratch mode that flips True → False).
- **Cluster-identity persistence**: when a consumer must show which cluster a candidate belongs to, add a `cluster_id` column (ADR-018's column-add migration template applies) + grouped reader output + a richer `MatcherResult`.
- **Auto-tagging producer**: when an agent-layer tagging surface lands, it feeds `Hypothesis.topic_tags` upstream (content-gen, outside `memory/`); the matcher consumes it unchanged.
- **Flag-as-promotion-precondition**: if a future architect call couples advisory detection to promotion eligibility, amend ADR-016 D3 (not this ADR) — it changes the eligibility contract.
- **Auto-run trigger**: if a consumer needs flags kept fresh without an explicit call, add an opt-in trigger (still not on `record_hypothesis` by default).

## Cross-references

- `docs/decisions/ADR-018-cross-room-tag-registry.md` (closed/accepted) — the registry this consumes: `normalize_tag` (D3, **reused** by the matcher's grouping key), `resolve_tags` (D4, write-time canonicalization the matcher relies on), `topic_tags` on Hypothesis+VK (D2/D5/D6), both-sides lookup normalization (D7, the precedent for D2 normalize-at-read here).
- `docs/decisions/ADR-016-cross-room-memory-persistence.md` (closed/accepted) — D3 (promotion eligibility — UNCHANGED, flag-independent), D7 (`candidate_for_promotion` column + index — activated as-shipped; "deferred" note superseded), D10 (no auto-promote — UNCHANGED), `idx_hypothesis_status_candidate`.
- `src/orchestrator/memory/tags.py:18` (`normalize_tag` — reused); `store.py:41,48` (`candidate_for_promotion` column + `idx_hypothesis_status_candidate`), `store.py:236` (`_row_to_hypothesis` — reused by the reader); `schema.py:94` (`Hypothesis.topic_tags`), `:87-95` (Hypothesis has no scope field).
- `tests/memory/test_constitution.py` — no-LLM rglob (covers `matcher.py`); extended with a structural advisory-orthogonality guard. The guard checks **code, not comments** (an AST/import check, not a whole-file substring scan — B → α): the matcher's orthogonality docstring ("advisory only — never calls `promote_hypothesis`") is intentional and must survive the guard, so the guard must not trip on prose that *documents* the property it enforces (avoids the RC-23-family whole-file-substring fragility).
- `tests/integration/test_p2_1_e2e.py` / `test_p1_6_5_e2e.py` — Scenario template (`_make_store` / `_make_room`).
- `docs/process/reviews/P2.1/architect-routing-on-impl.md` — the Y1→α both-sides decision this D2 mirrors.
- `handoff.md` §3.1 (code-decides structure), §4.5 (rule (a) — materialized).
