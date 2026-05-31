---
task_id: P2.2
kind: architect-routing-on-impl
date: 2026-05-31
stage: impl
impl_commit: a7f529d
reviews_acked:
  - plan-vs-impl.md   # senior — 0🔴 1🟡 3🟢
  - R0-A.md           # architect-partner — clean 0🔴 0🟡 5🟢 (after self-correction)
  - R0-B.md           # cross-family (deepseek) — clean 0🔴 0🟡 6🟢
decisions:
  Y1: α (strengthen the determinism test into a discriminating single-store mixed-scenario assertion; ~1 test, no impl change)
---

# P2.2 architect routing — impl stage (Y1 → α)

**Architect decision (this session, chat 2026-05-31, architect = Peidong):** the impl-stage joint verdict carried **one** 🟡 — the senior's plan-vs-impl Y1 (R0-A and R0-B-cross-family both **clean**). Architect routes **Y1 → α**. The matcher implementation is correct on every invariant both lenses traced; the single finding is a test-strength gap, not a shipped-correctness defect. No `src/` change is routed.

This file is the **signal artifact for the senior revision session** (impl stage). Senior picks P2.2, reads this + the three impl-stage reviews + the impl at `a7f529d`, applies the single routed test fix, and pushes a revision commit on `claude/P2.2-impl`. Then architect judges merge.

## Review picture (1 real issue; both external lenses clean)

| Review | Verdict | Note |
|---|---|---|
| senior plan-vs-impl | needs_architect (0🔴 1🟡 3🟢) | the lone finding — Y1 below |
| R0-A (architect-partner) | **clean** (0🔴 0🟡 5🟢) | after self-correction (the first push's Y1 was a fabricated false positive; withdrawn — see R0-A correction record) |
| R0-B (cross-family, deepseek) | **clean** (0🔴 0🟡 6🟢) | high-trust clean; line-by-line execution trace; 3 forward-notes (G6) captured below as surface-only |

Single-lens finding (senior only), but **verified real** by architect-partner against source before routing.

## Per-issue routing

### Y1 → α — strengthen the determinism test into a discriminating assertion (test-only; no impl change)

**Finding (senior plan-vs-impl Y1; architect-partner-verified):** the determinism tests assert only flagged-**count** equality across two **separate** random-id stores in an **all-one-cluster** scenario:
- `tests/memory/test_matcher.py::test_determinism_scan_order_independence` — 3 hypotheses across 3 rooms, all the same tag, two insert orders, asserts `len(flagged) == 3` both times.
- `tests/integration/test_p2_2_e2e.py` AC#5 — a 2-room single-cluster store in reversed order, asserts `rows_newly_flagged` count-equality.

Because every seeded row is in the one qualifying cluster, the flagged count is trivially the total regardless of scan order — the test **cannot fail on an order-dependent flagged-set regression**, and (separate random-id stores) it asserts count-equality, not the "same flagged **id-set**" plan AC#5 (post-G4) specified. A regression that flagged the same *number* but different *rows* by scan order would pass green.

**Verified, with the by-construction reframing:** confirmed `matcher.py:63` scans `ORDER BY id ASC` (fixed scan order, not SQLite-dependent) and groups by `frozenset` keys + a `set` of distinct rooms (order-independent). So the determinism invariant **is guaranteed by construction** — practical regression risk is near-zero; this is test confidence, not shipped correctness (hence 🟡, correctly). Note the weak test also gave R0-B's clean verdict its determinism evidence (R0-B G3 cites this very test) — so strengthening it closes a false-confidence path that spanned two reviews.

**Why α (not β-accept):** the test is named for an invariant it cannot fail on — the same "test that can't fail" anti-pattern the project keeps catching (P2.1 vacuous-atomicity-test). The invariant being by-construction-safe makes this low-severity, but closing a non-discriminating guard costs ~one test and removes a green light that means nothing. (β — accept on the `ORDER BY id ASC` + set-grouping guarantee, recording the test as a smoke check — was the considered alternative; architect routed α for the cheap real guard.)

**Action (senior revision):**
- Strengthen `test_determinism_scan_order_independence` (and/or the e2e AC#5) into a **discriminating** test: within a **single** store, seed a **mix** — a cross-room cluster (≥`min_rooms` distinct rooms, same canonical tag-set) **+** a singleton (1 room) **+** a same-room dup (two rows, one room, same tag-set) — run `run_matcher`, and assert the **exact flagged set == the cluster rows**, identified by **stable `content` labels, not random id** (so the assertion is on identity, not count).
- Add the order-independence half within that single store: re-seed the same logical structure in a **different insert order** and assert the **same flag decision** (cluster flagged; singleton + same-room-dup not) — not merely the same count.
- **No `src/` change** — the matcher is already deterministic by construction; this makes the test able to fail if that ever regresses.

## Surfaced — not routed (R0-B G6 forward-notes → future ADR-017-amendment candidates)

R0-B's three impl-level operational notes are **forward-compatibility observations, not current-cycle defects** (all 🟢; none affect P2.2 correctness under the single-connection sequential model, ADR-011 D1). Captured in `docs/retrospectives/P2.2-candidates.md` (RC-25, surface-only) so they aren't lost; **no action this cycle**:
- **(a) `run_matcher` self-commits** (`matcher.py:104` `conn.commit()`) — unlike the registry's transaction-neutral `resolve_tags`; not documented in ADR-017 D4. Fine standalone; would prematurely commit a caller's writes if ever composed inside a larger transaction.
- **(b) COUNT-then-UPDATE** (`matcher.py:94-103`) are separate implicit autocommit statements — a concurrent writer could change rows between them. Moot single-connection; the defensive `AND candidate_for_promotion=0 AND status='pending'` guard is insurance.
- **(c) Reader imports private `store._row_to_hypothesis`** — forward-coupling to an internal helper's signature (the plan explicitly accepted this reuse, P2.2-3).

These graduate to an ADR-017 amendment only **if** the concurrency model changes (multi-connection, caller-transaction nesting, or a `_row_to_hypothesis` signature change). Recorded, deferred.

## Non-routing fold-in (optional, no α/β/γ)

Senior plan-vs-impl G3 noted an AST-guard completeness nuance: the `.append` check matches only a `Name` receiver containing `event_store`/`store` — a hypothetical `self.event_store.append` (Attribute receiver) would slip. `matcher.py` has no such pattern, so it's a guard-completeness nuance, not a gap this slice. Senior may harden the guard while in the file; optional.

## Net

- **1 routed action:** Y1 → α (strengthen the determinism test; test-only, no impl/design change).
- **0 `src/` changes**, **0 🔴**; R0-A + R0-B both clean; the matcher impl is correct on every traced invariant.
- **3 forward-notes** (R0-B G6) recorded as surface-only (RC-25), deferred to a possible future ADR-017 amendment.

After the test strengthening lands + the senior bumps the plan-vs-impl verdict, P2.2 is merge-ready (modulo the orthogonal RC-22 state-position artifact noted by the architect — handled at merge/advance time, not a review-content item).
