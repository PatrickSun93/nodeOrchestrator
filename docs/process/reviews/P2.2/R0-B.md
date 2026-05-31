---
task_id: P2.2
round: R0-B
reviewer_family: deepseek
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 6
---

# P2.2 R0-B (cross-family, impl-stage) — cross-room hypothesis matcher

| Field | Value |
|---|---|
| Round | R0-B (cross-family, impl-stage; dual-lens-r0b.md — runtime/concurrency/failure-mode lens) |
| Reviewer family | deepseek |
| Impl branch | `claude/P2.2-impl` @ `a7f529d` (atomics P2.2-2..4 at `d68b61b`, `5a763b3`, `a7f529d`) |
| Baseline | `main` (merged P2.1 registry, ADR-018 closed); ADR-017 (Accepted); senior-plans/P2.2.md |
| Prior reviews | R0-A-on-plan (0🔴 2🟡 5🟢); R0-B-cross-family plan-stage (0🔴 2🟡 5🟢); architect-routing-on-plan (A→α, B→α, G2→α-small) |
| Plan-stage absorption | A (untagged-across-rooms test): ✓ absorbed; B (AST orthogonality guard): ✓ absorbed; G2 (idempotency inscription): ADR-level, not impl-relevant |
| Date | 2026-05-31 |
| Verdict | **clean** — 0🔴 · 0🟡 · 6🟢 |

## Lens preamble

Cross-family impl-stage runtime/failure-mode lens per `dual-lens-r0b.md` §contrarian. The plan-stage R0-B already traced the matcher's invariants at the design level (equivalence-relation partition, distinct-room counting, determinism, idempotency/monotonicity, normalize-at-read correctness, advisory orthogonality) and both yellows (untagged-exclusion untested, substring-scan fragility) were confirmed and absorbed. This pass traces the **actual execution** — what happens at each line of `matcher.py` when specific inputs land, when the UPDATE fires, when `conn.commit()` is called, when the AST guard walks the tree. The cross-family lens over-corrects for Claude biases: trusting that "types-are-right means runtime-is-right" and sycophancy toward prior-reviewer consensus. Code-traced against `a7f529d`.

## Findings

| # | Sev | Finding | Evidence |
|---|---|---|---|
| G1 | 🟢 | **Plan-stage A routing absorbed — untagged-across-rooms guard present and correct.** Unit test `test_untagged_across_rooms_zero_flagged` (test_matcher.py:257) covers N=3 rooms, all with `topic_tags=[]`, `min_rooms=2` → zero flagged, zero groups inspected. Explicitly marked "AC#11 (A routing)." Scenario Y e2e (test_p2_2_e2e.py:146-161, 176-178) covers the same: 2 untagged rows across room2+room3, asserted not flagged. The empty-set exclusion at matcher.py:72 (`if not canonical_set: continue`) is now guarded against regression — the matcher's dominant early-life case is test-protected. | matcher.py:72-73; test_matcher.py:257-284; test_p2_2_e2e.py:146-178 |
| G2 | 🟢 | **Plan-stage B routing absorbed — AST orthogonality guard is robust, not a substring scan.** `test_matcher_advisory_orthogonality_ast_guard` (test_constitution.py:63-131) uses `ast.parse` to walk the matcher's AST: checks imports (Import/ImportFrom for `promotion`/`promote_hypothesis`), call/attribute nodes (Name/Attribute for `promote_hypothesis`/`append_in_transaction`/`event_store.append`), and string constants for `INSERT INTO verified_knowledge`. The matcher's own orthogonality docstring (matcher.py:5-10: "Advisory only — this module NEVER calls promote_hypothesis...") does NOT trip the guard: the docstring is an `Expr` node, the (c) check only fires on `ast.Constant` with `"INSERT INTO verified_knowledge"` (UPPERCASE SQL), and the docstring uses lowercase prose ("inserts into"). The RC-23 family fragility is closed for this guard. | test_constitution.py:63-131; matcher.py:1-11 (docstring); AST walk confirmed check-c (Constant) skips docstring prose |
| G3 | 🟢 | **`run_matcher` runtime trace — all invariants hold.** Execution path traced line-by-line against the plan/ADR: (1) `min_rooms < 1` guard at line 59 → ValueError ✓; (2) SELECT PENDING ORDER BY id ASC at line 62 → returns only `status='pending'` ✓; (3) Group by `frozenset(normalize_tag(t) for t in json.loads(...))` at line 70 → correct reuse, normalize-at-read ✓; (4) Empty canonical set excluded at line 72 (`if not canonical_set: continue`) ✓; (5) Distinct-room count via `{room_id for _, room_id in entries}` at line 83 → set dedup = distinct rooms ✓; (6) Flagged ids sorted at line 88 → stable UPDATE ordering only, not flag correctness ✓; (7) Defensive `AND status='pending'` guard on both COUNT and UPDATE (lines 96, 101) ✓; (8) `conn.commit()` at line 104 commits the UPDATE ✓; (9) `rows_newly_flagged = before` (COUNT result) correctly reports rows flipped ✓. No path where a wrong row gets flagged; no path where a correct row is missed. Determinism holds: flagged id-set is computed via set operations (lines 83-85), independent of scan order — confirmed by `test_determinism_scan_order_independence` (test_matcher.py:384) with shuffled insert order. | matcher.py:59-110; test_matcher.py:69-284 (15 tests); test_matcher.py:328-432 (invariants) |
| G4 | 🟢 | **`list_promotion_candidates` reader correct.** SELECT `status='pending' AND candidate_for_promotion=1 ORDER BY id ASC` at line 121-125 — index-covered by `idx_hypothesis_status_candidate` (store.py:48). Excludes VERIFIED rows even if flagged (test_matcher.py:514-543). Returns `[]` before any flagging (test_matcher.py:441-446). Returns frozen `Hypothesis` models via `_row_to_hypothesis` (line 126). No scope argument — correct (Hypothesis has no scope field, schema.py:87-95). | matcher.py:113-126; test_matcher.py:440-594 (6 tests) |
| G5 | 🟢 | **E2e Scenario Y covers all AC#1-9 + A/B routing guards.** Cross-family trace confirms each acceptance criterion from plan P2.2-4 is exercised: cluster flagged (AC#3, lines 167-170), singleton + same-room-dup + untagged NOT flagged (AC#3, lines 172-183), `list_promotion_candidates` surfaces only cluster in id-ASC order (AC#4, lines 186-193), determinism via shuffled record order (AC#5, lines 196-217), orthogonality — no VK rows + no decision events + `promote_hypothesis` works on flagged AND unflagged rows (AC#6, lines 220-245), idempotency — second run `rows_newly_flagged==0` (AC#7, lines 248-249), `min_rooms<1` → ValueError (AC#8, lines 253-255). Source ≠ sink across record→match→read→promote. | test_p2_2_e2e.py:88-260 |
| G6 | 🟢 | **Three impl-level operational notes (forward-compatibility, not defects).** (a) `run_matcher` calls `conn.commit()` at line 104 — self-committing, unlike `resolve_tags` (transaction-neutral). Makes sense for a standalone batch API, but is not documented in ADR-017 D4. If composed inside a larger caller transaction, it would prematurely commit the caller's writes. Low risk (matcher is always called standalone in current usage). (b) The COUNT-then-UPDATE at lines 94-103 are separate implicit transactions in autocommit mode — a concurrent writer could change rows between them. Moot for P2.2 (single-connection, ADR-011 D1); the defensive `AND candidate_for_promotion=0 AND status='pending'` guard provides insurance. (c) `list_promotion_candidates` imports `store._row_to_hypothesis` (private function) at line 20 — forward-coupling to the internal helper's signature. Plan explicitly accepts this reuse (P2.2-3); a `_row_to_hypothesis` signature change would require a matcher update. All three are 🟢 forward-notes, not current-cycle defects. | matcher.py:20 (`_row_to_hypothesis`), :94-103 (COUNT+UPDATE), :104 (`conn.commit()`) |

## Synthesis

The impl is clean and faithful to the plan + ADR-017. Both plan-stage yellows (A: untagged-exclusion untested, B: substring-scan fragility) are correctly absorbed — the unit test + e2e guard the dormant-until-fed case, and the AST-based orthogonality guard closes the RC-23 recurrence without penalizing documentation.

The cross-family impl-stage lens traces the actual execution through every line of `matcher.py` and finds no 🔴, no 🟡. The grouping logic (frozenset-equality via normalize_tag, empty-set exclusion, distinct-room set-dedup) is structurally correct. The UPDATE is defensively scoped. The reader is index-covered. The e2e exercises every acceptance criterion and the A-routing guard. The AST orthogonality check correctly skips docstrings (confirmed by AST-walk verification) while catching real code references. The three forward-notes (G6) are compat notes, not defects — none affect P2.2 correctness under the current single-connection sequential model.

The plan-stage cross-family R0-B surfaced one structural contribution (normalize_tag idempotency must be explicit) that the in-family R0-A didn't catch. The impl-stage cross-family lens confirms that contribution was properly routed and absorbed, and finds no net-new issues in the code itself. This is a high-trust `clean` — the impl genuinely checks out across all invariants both lenses traced.

## For the architect

No routing needed. The impl is accept-worthy as-is. The three G6 notes are forward-compatibility observations, not action items — the architect may capture them as retro candidates or fold into a future ADR-017 amendment if the operational model changes (multi-connection, caller-transaction nesting, or `_row_to_hypothesis` signature change).
