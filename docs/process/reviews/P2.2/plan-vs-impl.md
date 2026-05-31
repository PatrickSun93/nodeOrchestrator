---
task_id: P2.2
round: plan-vs-impl
reviewer: senior
impl_commit: a7f529d
verdict: needs_architect
findings_count:
  red: 0
  yellow: 1
  green: 3
---

# P2.2 plan-vs-impl (senior) — cross-room hypothesis matcher

| Field | Value |
|---|---|
| Reviewer | senior (plan-vs-deliverable lens) |
| Plan | `docs/process/senior-plans/P2.2.md` (incl. plan-stage A→α/B→α/G2/G4 revision) |
| ADR | `docs/decisions/ADR-017-cross-room-hypothesis-matcher.md` (Accepted) |
| Impl | `claude/P2.2-impl` @ `a7f529d` (atomics P2.2-2..4 at `d68b61b`, `5a763b3`, `a7f529d`) |
| Verdict | **needs_architect** — 0🔴 · 1🟡 · 3🟢 |

## Summary

Faithful, high-quality implementation. The three impl atomics map 1:1 to the plan (one commit per atomic), every acceptance criterion is met, and the matcher is correct on every ADR-017 invariant: `normalize_tag` reuse (D1; not ad-hoc `.lower()`), normalize-at-read (D2), empty-canonical-set exclusion (D1), distinct-room (not distinct-row) counting (D4), monotonic `False→True` with idempotent re-runs, `min_rooms<1`→`ValueError`, and the scoped `UPDATE ... AND status='pending'` guard. The three plan-stage routing items are correctly absorbed: **A** (untagged-across-rooms→zero-flagged, `test_matcher.py::test_untagged_across_rooms_zero_flagged` + the e2e untagged rows), **B** (the orthogonality guard is a real AST call/import check that correctly does **not** trip on the matcher's own orthogonality docstring — verified), **G2** (`normalize_tag` idempotency inscribed in ADR-017 D2 + ADR-018 D3 — documentation, no test required). The load-bearing orthogonality is genuinely tested end-to-end (`vk_count==0` + `decision_count==0` after `run_matcher`; `promote_hypothesis` works on flagged *and* un-flagged PENDING rows). handoff §4.5 + the schema docstring are accurate and light-touch; **no §7-P1.2-stale bundling, no scope creep** (no schema/ALTER work — correctly inherited from ADR-018).

One **🟡** is the senior-lens catch: the **determinism test (AC#5 / G4) is non-discriminating** — it asserts only count-equality across two independent random-id stores in a single-cluster scenario, so it cannot fail on an order-dependent flagged-*set* regression and does not assert the "same flagged id-set" AC#5 specified. The impl *is* deterministic by construction (explicit `ORDER BY id ASC` + frozenset grouping), so this is a test-strength gap, not a correctness defect — but it gives false confidence on exactly the invariant the cross-family lens cared about. Cheap to strengthen.

## Per-atomic verification

| Atomic | Delivered | Plan match | Notes |
|---|---|---|---|
| P2.2-2 `run_matcher` + `MatcherResult` | ✓ `d68b61b` | ✓ (1🟡 on a test) | D1 `normalize_tag` reuse (matcher.py:21,70); D2 normalize-at-read; empty-set exclusion (`if not canonical_set: continue`, :72); PENDING-only (:63); distinct-room (:83-84); scoped UPDATE (:101); `min_rooms<1`→`ValueError` (:59); idempotent via pre-count (:94-105); monotonic. Untagged test (AC#11) present. Determinism test weak — see Y1. |
| P2.2-3 `list_promotion_candidates` | ✓ `5a763b3` | ✓ | PENDING + `candidate_for_promotion=1`, `id ASC`, `_row_to_hypothesis` (matcher.py:113-126); no scope arg; index-covered. Full reader test class (empty / flagged / excludes-non-flagged / excludes-verified / id-ASC / returns-models). |
| P2.2-4 e2e + AST guard + handoff + landing | ✓ `a7f529d` | ✓ (1🟡 on AC#5) | Scenario Y covers cluster (different surface forms) / singleton / same-room-dup / untagged-across-rooms, orthogonality (vk+decision counts, flagged+unflagged promote), idempotency, `min_rooms<1`. AST orthogonality guard correct. handoff light-touch, no §7. |

ADR-017 accept-gate was honest (Accepted; RC-23 clear). Constitution: `matcher.py` has no forbidden LLM imports — the canonical no-LLM rglob still covers it.

## Findings

### 🟡 Y1 — the determinism test (AC#5 / G4) is non-discriminating: count-only, single-cluster, cross-store

Both determinism tests assert only that the *count* of flagged rows matches across two **separate** stores (different random ids), in scenarios where the outcome is all-or-nothing:

- `tests/memory/test_matcher.py::test_determinism_scan_order_independence` — seeds 3 hypotheses across 3 rooms, **all with the same tag** (`["cluster-tag"]`), in two insert orders; asserts `len(flagged1) == len(flagged2) == 3`.
- `tests/integration/test_p2_2_e2e.py` AC#5 — a 2-room single-cluster store in reversed insert order; asserts `result2.rows_newly_flagged == result.rows_newly_flagged`.

In both, **every** seeded row is in one qualifying cluster, so the flagged count is trivially the total regardless of order — the test cannot distinguish an order-independent matcher from an order-dependent one. And because the two stores use independent random ids, the test asserts *count*-equality, not the "same flagged **id-set**" that plan AC#5 (post-G4) specified. A regression that flagged the *same number but different rows* depending on scan order would pass.

**Why it matters (plan-implied invariant):** AC#5 / G4 exist to guard determinism — the cross-family R0-B's load-bearing concern. The current tests are a non-discriminating proxy: a green "determinism" test that can't fail on a determinism bug. This is the same class as the P2.1 vacuous-atomicity-test finding (a test named for an invariant it doesn't exercise).

**Severity is low — the invariant is guaranteed by construction**, two ways: the matcher scans `ORDER BY id ASC` (matcher.py:63 — scan order is fixed, not SQLite-dependent) and groups by `frozenset` keys + a `set` of distinct rooms (order-independent). So the practical regression risk is near-zero; this is test confidence, not shipped correctness — hence 🟡 not 🔴.

**Lean — α** (cheap, ~one test): make at least one determinism test **discriminating** — within a *single* store, seed a mix (a cross-room cluster + a singleton + a same-room dup), run the matcher, and assert the **exact flagged set** equals the expected cluster rows (identified by stable `content` labels, not random id); then assert that re-seeding the same logical structure in a different insert order yields the same flag *decision* (cluster flagged, others not), not merely the same count. Alternatively the architect may route **β** (accept) on the by-construction guarantee (`ORDER BY id ASC` + set grouping) and record that the determinism test is a smoke check, not a discriminating guard.

### 🟢 G1 — plan-stage routing (A / B / G2 / G4) absorbed correctly

- **A (untagged-across-rooms)**: `test_matcher.py::test_untagged_across_rooms_zero_flagged` (3 rooms, all `[]` → `groups_inspected==0`, zero flagged) + the e2e's `h_untagged_r2`/`h_untagged_r3` asserted False. The dominant dormant-until-fed case is genuinely guarded. ✓
- **B (AST orthogonality guard)**: `test_constitution.py::test_matcher_advisory_orthogonality_ast_guard` is a real `ast.parse` + walk — (a) forbidden `promotion`/`promote_hypothesis` imports, (b) `Name`/`Attribute` nodes `promote_hypothesis`/`append_in_transaction` and `event_store.append`/`store.append`, (c) `INSERT INTO verified_knowledge` only in `ast.Constant` strings. It correctly does **not** trip on `matcher.py`'s own orthogonality docstring (the docstring is an `ast.Constant`, so its mention of `promote_hypothesis` creates no `Name`/`Attribute` node; the `.append` check is scoped to `event_store`/`store` Name-receivers, so `groups[...].append(...)` on a Subscript receiver and `.extend(...)` don't false-trip). Closes the RC-23-family fragility. ✓
- **G2 (idempotency inscription)**: documentation only (ADR-017 D2 + ADR-018 D3) — no test required by the routing; present in the accepted ADR. ✓
- **G4 (determinism framing)**: the test states the record-order-shuffle-as-scan-order-proxy intent (but see Y1 on its strength). ✓

### 🟢 G2 — orthogonality is genuinely tested (not just guarded structurally)

Beyond the AST guard, the e2e asserts the runtime orthogonality the plan called load-bearing: after `run_matcher`, `SELECT COUNT(*) FROM verified_knowledge == 0` and `... events WHERE type='decision' == 0` (the matcher created no VK row and emitted no promotion event), and `promote_hypothesis` succeeds on **both** a flagged row (`h_cluster_r1`) and an un-flagged row (`h_singleton`) — proving the flag is not a promotion precondition (ADR-016 D3/D10 hold). This is the non-vacuous orthogonality proof P2.2-4 AC#6 required. ✓

### 🟢 G3 — scope discipline + matcher faithful to ADR-017; claims verified

No schema/ALTER work (correctly inherited from ADR-018 — the biggest rebase delta, honored). `schema.py` change is a one-spot docstring update (`candidate_for_promotion` written by `run_matcher`, P1.7+ → P2.2); handoff §4.5 materializes rule (a) accurately; **no §7-P1.2-stale bundling**. Spot-verified cites: matcher.py:21,63,70,72,83-84,101 (normalize_tag reuse / PENDING scan / empty-set exclusion / distinct-room / scoped UPDATE); test_constitution.py:63-131 (AST guard). One-atomic-one-commit honored. Optional minor (non-blocking): the AST guard's `.append` check matches only a `Name` receiver containing `event_store`/`store` — a hypothetical `self.event_store.append` (Attribute receiver) would slip; matcher.py has no such pattern, so it's a guard-completeness nuance, not a gap this slice.

## What the architect needs to route

1. **Y1 (🟡):** the determinism test is non-discriminating (count-only, single-cluster, cross-store) — it can't fail on an order-dependent flagged-set bug and doesn't assert AC#5's "same flagged id-set." Lean **α** — one discriminating test (mixed scenario, assert exact flag decision by stable content labels). Or **β** — accept on the by-construction guarantee (`ORDER BY id ASC` + frozenset grouping) and record the test as a smoke check.
2. **Greens** are affirmations; the G3 AST-guard `.append`-receiver nuance is an optional hardening the junior can absorb without an architect call.

Per ADR-008 Amendment 1 (Route B), state auto-advances to `awaiting_R0_A` regardless of this verdict; R0-A (+ R0-B, dual-lens dispatched) fire, then joint-verdict evaluation. This 🟡 makes the joint verdict non-clean → `awaiting_architect_decision` for routing.
