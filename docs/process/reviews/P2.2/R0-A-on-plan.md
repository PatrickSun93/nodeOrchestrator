---
task_id: P2.2
round: R0-A-on-plan
verdict: clean
verdict_history:
  - needs_architect  # original (0🔴 2🟡 5🟢); Y1→A→α + Y2→B→α absorbed, bumped per RC-10
findings_count:
  red: 0
  yellow: 2
  green: 5
---

# P2.2 R0-A on plan (architect-dispatched pre-impl review) — cross-room hypothesis matcher

| Field | Value |
|---|---|
| Round | R0-A-on-plan (architect-dispatched per RC-9) |
| Reviewer | architect-partner (doc / architecture / invariant-correctness lens) |
| Stage | Plan + ADR-017 (Proposed), pre-impl. State `awaiting_architect_accept`. |
| Artifacts | `docs/process/senior-plans/P2.2.md`, `docs/decisions/ADR-017-cross-room-hypothesis-matcher.md` |
| Baseline | merged P2.1 registry (ADR-018 on `main`); ADR-016 |
| Date | 2026-05-30 |
| Verdict | **needs_architect** — 0🔴 · 2🟡 · 5🟢 |
| Note | R0-B (cross-family) runs after me on the shared tree; branch left checked out clean. ADR-017 NOT accepted (architect-only). |

## Summary

Strong plan + ADR, and the **rebase is handled correctly** — the single biggest risk (carrying the superseded pre-registry assumptions) is cleanly avoided: no schema/migration atomic (verified the field + column + ALTER are on `main`), `normalize_tag` reused not reinvented (D1 — the central rebase point, well-argued), normalize-at-read mirroring lookup's both-sides (D2). The load-bearing invariants the dispatch flagged are all *specified* correctly: equivalence-relation partition (D3), distinct-**room** counting (D4, guarded by the same-room-dup e2e case), structural determinism (D4), idempotency/monotonicity (D4), advisory orthogonality (D-various). RC-23 heeded (ADR-017 parses `proposed`).

Both 🟡 are **test-correctness gaps, not design defects** — the right severity for plan-stage R0-A. Y1: the **empty/`[]`-tag-set exclusion** — the highest-consequence false-positive path, and the *common* case since the matcher is "dormant-until-fed" — is specified in three places but has **no test**. Y2: the **new structural orthogonality guard**, "modeled on" the existing constitutional test, inherits that test's **whole-file substring** mechanism — which will false-positive on the matcher's own orthogonality docstring (the RC-23 substring-fragility family, verified). Both cheap; both the architect's to route.

## Findings

| # | Sev | Finding | Lean |
|---|---|---|---|
| Y1 | 🟡 | Empty/`[]`-tag-set exclusion (the dominant early-life case) is specified but **not test-guarded**; a regression flags every untagged hypothesis across rooms | α — add an explicit untagged-across-rooms→zero-flagged test |
| Y2 | 🟡 | New structural orthogonality guard inherits the constitutional test's whole-file substring scan → false-positives on the matcher's own orthogonality docstring (RC-23 family) | α — implement as real call/import check, or exclude comments/docstrings |
| G1 | 🟢 | Rebase correct: no schema atomic; `normalize_tag` reused (D1) — verified against `main` | affirm |
| G2 | 🟢 | Normalize-at-read (D2) mirrors lookup both-sides; sound + consistent | affirm |
| G3 | 🟢 | Exact-equality partition (D3) + distinct-room counting (D4) correct + e2e-guarded | affirm |
| G4 | 🟢 | Determinism structural (D4); idempotency/monotonicity correct | affirm + 1 test note |
| G5 | 🟢 | Advisory orthogonality (ADR-016 D3/D10 intact); RC-23 clean; claims cite-verified | affirm |

---

### 🟡 Y1 — the empty/`[]`-tag-set exclusion is the highest-consequence path and has no test

The matcher groups by `frozenset(normalize_tag(t) for t in topic_tags)`. A hypothesis with `topic_tags=[]` produces `frozenset()` (the empty set). The design **correctly** excludes it — D1 ("the empty canonical set… is excluded from grouping… never matches"), D3 (reiterates), and plan P2.2-2 AC#2 ("Empty canonical set excluded"). So the *specification* is right, in three places.

**But there is no test for it** — and this is the single most dangerous false-positive path, for two compounding reasons:

1. **It's the common case, not an edge.** ADR-017 itself states the matcher is "**dormant-until-fed** — it only surfaces candidates for hypotheses that carry tags," and no auto-tagging producer ships this slice. So in early life **most `Hypothesis` rows are untagged (`[]`)**. If the empty-set exclusion regresses (e.g. an impl that builds the group map first and filters empties *after* the distinct-room count, or forgets the guard), **every untagged hypothesis across ≥`min_rooms` rooms gets flagged `candidate_for_promotion=True`** — the matcher would be actively, loudly wrong in exactly the dominant case, not merely dormant. That's a false-positive flood on the user's promotion-candidate surface.
2. **The plan's e2e doesn't exercise it.** Scenario Y (P2.2-4) covers cluster / singleton / same-room-dup / determinism / orthogonality / idempotency / `min_rooms<1`. None of these has multiple `[]`-tagged PENDING hypotheses across rooms. The exclusion is asserted nowhere.

Verified the concern is well-defined: `normalize_tag` maps whitespace/empty → `""`, and `resolve_tags` *raises* on an empty-normalizing tag — so a stored row can only ever carry `[]` (never `[""]`). The empty-set case is exactly the `[]`-tagged rows, which is precisely the bulk of early data.

**Lean α (add the test):** an explicit case — N≥`min_rooms` PENDING hypotheses across N distinct rooms, all with `topic_tags=[]` → `run_matcher` flags **zero**, `list_promotion_candidates` returns empty. Ideally as a `matcher.py` unit test (P2.2-2) *and* a line in the e2e. No impl change if the impl is correct; this is the guard that proves it. Cheap, and it protects the matcher's entire dormant-until-fed contract.

### 🟡 Y2 — the new structural orthogonality guard inherits a whole-file substring scan → false-positives on its own docstring (RC-23 family)

Plan P2.2-4 adds a structural advisory-orthogonality guard: "assert `matcher.py` source does not reference `promote_hypothesis`, a `verified_knowledge` INSERT, or `event_store.append`," and says to model it on the existing constitutional test. I checked that test's mechanism (`tests/memory/test_constitution.py`): it is a **whole-file substring scan** — `source.lower()` then `if pattern_l in lowered: assert False`. A guard modeled on it would be `forbidden = ["promote_hypothesis", "verified_knowledge", "event_store.append"]` substring-checked over `matcher.py`.

That mechanism **false-positives on prose**: a conscientious junior documenting the orthogonality — the run_matcher docstring or a comment saying *"advisory only — never calls `promote_hypothesis`, never inserts a `verified_knowledge` row"* — would trip the guard that's *supposed to enforce* exactly that property. The guard meant to prove "the matcher can't promote" fails because the matcher *says* it can't promote. This is the **same whole-file-substring fragility as RC-23** (`_parse_adr_status` misreading prose that quotes a status line) — now recurring in a test this very plan introduces. The likely "fix" a junior reaches for under a red test is to *delete the explanatory docstring*, which is strictly worse (loses the human-readable orthogonality contract to satisfy a brittle check).

**Lean α (implement the guard robustly):** make it a real call/import check rather than a prose substring scan — e.g. AST-walk `matcher.py` for `Call`/`Attribute` nodes named `promote_hypothesis` / `append` / an INSERT into `verified_knowledge`, or assert `matcher.py` does not *import* `promotion`/`promote_hypothesis` and contains no `verified_knowledge` SQL string — i.e. check code, not comments. At minimum, scope the scan to strip comments/docstrings, and state in the ADR/plan that the orthogonality docstring is intentional and must survive the guard. (Bonus: this is a cleaner structural guarantee than the existing substring constitutional test, and could be noted as a small forcing-function improvement — though that's dev-harness-adjacent; keep it scoped to this guard for P2.2.)

### 🟢 G1 — the rebase is correct (the biggest risk, cleanly handled)

Verified against `origin/main`: `Hypothesis.topic_tags` (`schema.py:94`), the `topic_tags` column + `_ensure_hypothesis_topic_tags` ALTER (`store.py`), `candidate_for_promotion` + `idx_hypothesis_status_candidate` (`store.py:41,48`), `normalize_tag` (`tags.py`) — all present. The plan **drops the old schema atomic** (P2.2 is ~4 atomics, not 6) and the ADR D7 explicitly records the schema/migration as inherited-not-re-decided. D1's reuse-`normalize_tag`-not-`.lower()` argument is exactly right and is the load-bearing rebase point: a reinvented canonical form would silently diverge from the registered vocabulary (`"LLM Cost"`→`"llm-cost"` via whitespace→hyphen, vs an ad-hoc `.lower()`→`"llm cost"`), breaking cross-room corroboration. The "if you write an `ALTER TABLE`, stop" self-discovery is a good guardrail.

### 🟢 G2 — normalize-at-read (D2 / push-back #1) is sound and consistent

Re-normalizing stored tags at match-time (rather than trusting write-time canonicalization) is the right call for the reason given: it's the **same both-sides posture `lookup` chose** (ADR-018 D7 / P2.1 Y1→α), so the two cross-room read paths stay consistent (a reader needn't know whether a row went through `resolve_tags`), and it's robust against raw-insert paths (fixtures, future bulk import). Cost is negligible at expected scan sizes. The parallel-to-lookup framing is the deciding argument and it holds.

### 🟢 G3 — exact-equality partition + distinct-room counting correct and guarded

The equivalence-relation argument for exact set-equality (D3) is correct: it's the only transitive option, so "group spans ≥N rooms" is well-defined and order-independent; Jaccard/≥K would be non-transitive similarity-graph components. Distinct-**room** (not distinct-row) counting (D4) is the off-by-one trap the dispatch flagged, and it **is** e2e-guarded: the same-room-dup case (P2.2-4 AC#3 — two same-canonical hypotheses both in room1 → not flagged) directly proves distinct-room semantics. Good.

### 🟢 G4 — determinism structural; idempotency/monotonicity correct

D4's framing is precise and correct: the flagged id-set is a pure function of `{(id, room_id, canonical-tag-set, status)}` — order-independent by set construction; the sort-by-id is for stable `MatcherResult`/UPDATE-list only, *not* flag correctness. Idempotency (UPDATE only flips `0→1`; second run `rows_newly_flagged==0`) and monotonicity (never clears) are right, and the PENDING-scoped UPDATE (`AND status='pending'`) is a sound defensive touch. **One test note:** P2.2-4 AC#5 tests determinism by shuffling *record* order — that varies rowid/scan order, so it's a valid proxy, but state explicitly that it's exercising scan-order independence (insertion order → SELECT order) so the test's intent is unambiguous.

### 🟢 G5 — advisory orthogonality, RC-23, cite discipline

Advisory-only is well-preserved: ADR-016 D3/D10 cited unchanged, no canonical event on flag, e2e asserts no-VK-row + no-promotion-event + `promote_hypothesis` works on flagged *and* unflagged PENDING rows. RC-23 heeded — ADR-017 parses `proposed` (verified by running the parser logic); the new-ADR-017-not-amend-ADR-018 reasoning (D8) correctly invokes the same RC-23-avoidance the registry used. Spot-verified the decision-bearing cites (`tags.py` normalize_tag, `store.py:41/48` column+index, `schema.py:94` field, `_row_to_hypothesis` for reader reuse) — all accurate. Scope discipline clean (no §7-P1.2 bundling; all deferrals intact).

## What the architect needs to route

1. **Y1 (🟡):** α — add the untagged-across-rooms → zero-flagged test (unit + e2e line). Guards the matcher's dominant early-life case; no impl change if correct.
2. **Y2 (🟡):** α — implement the structural orthogonality guard as a real call/import check (or comment-stripped), not a whole-file substring scan, so it doesn't false-positive on the matcher's own orthogonality docstring (RC-23 family).
3. **Greens** are affirmations + two optional test-clarity notes (G4 determinism-test intent) the junior can fold without an architect call.

ADR-017 is accept-worthy once Y1/Y2 are routed (both are test-approach fixes; the design is sound). R0-A-on-plan does not change state (RC-9 manual dispatch). Branch left checked out clean for the R0-B pass.

---

## Verdict bump (RC-10) — needs_architect → clean

This review's two yellows were routed and absorbed in the senior revision (`architect-routing-on-plan.md`, 2026-05-31; both Y's were also raised by R0-B-cross-family — two-lens confirmation):
- **Y1 → A → α** (untagged-across-rooms exclusion untested): added a `matcher.py` unit test (plan P2.2-2 AC#11) + an e2e line (P2.2-4 AC#1/#3) asserting untagged `[]`-tag rows across ≥`min_rooms` rooms flag zero — guarding the dominant dormant-until-fed case. Test-only, no `src/` change.
- **Y2 → B → α** (orthogonality guard substring fragility): the guard is now spec'd as a real call/import **AST check** (code, not comments), not a whole-file substring scan (plan P2.2-4 Where; ADR-017 cross-ref) — closes the RC-23-family fragility.
- **G4 fold-in**: the determinism test's record-order shuffle is now stated as the scan-order-independence proxy (P2.2-4 AC#5).

No `src/` design change (the matcher design was sound on every traced invariant). RC-23 re-verified gate-safe (ADR-017 has no `status: accepted` substring). Verdict → **clean**.
