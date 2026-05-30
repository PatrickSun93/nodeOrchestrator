---
task_id: P2.1
round: plan-vs-impl
reviewer: senior
impl_commit: 6d9cf7d
verdict: clean
verdict_history:
  - needs_architect  # original (0🔴 1🟡 3🟢); Y1 → A → α absorbed, bumped per RC-10
findings_count:
  red: 0
  yellow: 1
  green: 3
---

# P2.1 plan-vs-impl (senior) — shared tag registry

| Field | Value |
|---|---|
| Reviewer | senior (plan-vs-deliverable lens) |
| Plan | `docs/process/senior-plans/P2.1.md` (incl. R0-A-on-plan Y1→α revision) |
| ADR | `docs/decisions/ADR-018-cross-room-tag-registry.md` (Accepted) |
| Impl | `claude/P2.1-impl` @ `6d9cf7d` (atomics P2.1-2…6 at `4a2db94`, `dc6adf0`, `bc27e88`, `b1c9b73`, `6d9cf7d`) |
| Verdict | **needs_architect** — 0🔴 · 1🟡 · 3🟢 |

## Summary

Faithful, high-quality implementation. All five impl atomics map 1:1 to the plan (one commit per atomic per RC-17), every acceptance criterion is met, and the three R0-A-on-plan routing items are correctly absorbed in code: **Y1** (lookup normalizes **both** sides — lookup.py:44,47), **G1** (`resolve_tags` placed *inside* `promote_hypothesis`'s `with conn:` block, after the UPDATE, before the VK INSERT — promotion.py:114), **G3** (`ValueError`-on-empty-tag contract tightening + the hyphen near-miss boundary cases, both tested). The load-bearing plan-implied invariants are genuinely exercised: the column-add migration round-trip (test_store.py), determinism + transaction-neutrality of `resolve_tags` (test_tags.py), the **Y1 legacy-row** case (test_lookup.py — a raw-stored VK found by a normalized query), and cross-room canonical consistency (test_p2_1_e2e.py). handoff §4.5/§5.8 updates are light-touch and accurate; **no §7-P1.2-stale bundling, no out-of-scope creep** (matcher, agent-wiring, FK storage, backfill all correctly untouched).

One **🟡** is the senior-lens catch external reviewers may miss: the new **atomicity test for tag-registration rollback is vacuous** — it injects the failure *before* `resolve_tags` runs, so the "tag rolls back" assertion is trivially satisfied without ever exercising the path. The impl is atomically correct; the *test* gives false confidence on the one new invariant P2.1-5 AC#1 added. Cheap to fix (re-point the injection). Everything else is affirmation.

## Per-atomic verification

| Atomic | Delivered | Plan match | Notes |
|---|---|---|---|
| P2.1-2 tag table + `Hypothesis.topic_tags` + ALTER | ✓ `4a2db94` | ✓ | `tag(canonical PK, created_at)` (store.py:75); `topic_tags` column + frozen Pydantic field; `_ensure_hypothesis_topic_tags` PRAGMA-guarded ALTER (store.py:87); migration round-trip + idempotency tested (test_store.py) |
| P2.1-3 `normalize_tag` + `resolve_tags` | ✓ `dc6adf0` | ✓ | `strip().lower()`+`re.sub(r"\s+","-")` (tags.py:29); transaction-neutral, dedup-order, `ValueError`-on-empty, `INSERT OR IGNORE`; full boundary + determinism + hyphen-edge tests |
| P2.1-4 `record_hypothesis` wiring | ✓ `bc27e88` | ✓ | keyword-only `topic_tags`; `resolve_tags` inside `with conn:` before INSERT; returns `model_copy` with canonical tags; existing callers unaffected |
| P2.1-5 VK write-path + lookup both-sides | ✓ `b1c9b73` | ✓ (1🟡 on a test) | G1 placement correct; Y1 both-sides (lookup.py:44,47); D6 canonical + **legacy-row** + ValueError-contract tested; see Y1 below on the atomicity test |
| P2.1-6 e2e + handoff + landing | ✓ `6d9cf7d` | ✓ | record→register→promote→lookup e2e + cross-room dedup; handoff light-touch, no §7 bundling |

ADR-018 accept gate honest (Accepted; RC-23 clear). Constitution: `tags.py` has no forbidden LLM imports — the canonical `tests/memory/test_constitution.py` rglob still covers it.

## Findings

### 🟡 Y1 — the tag-registration-rollback atomicity test is vacuous (injects before `resolve_tags` runs)

`tests/memory/test_promotion.py::TestPromoteHypothesisTopicTagsWiring::test_tag_registration_rolls_back_with_vk_insert_failure` patches `append_in_transaction` with `side_effect=RuntimeError` and asserts `tag_count == 0` after rollback. But the promotion transaction ordering is:

```
promotion.py:101  with conn:
           :104      UPDATE hypothesis            (4c — opens txn)
           :109      append_in_transaction(...)   (4a — INJECTED FAILURE HERE)
           :114      resolve_tags(...)            (4d — NEVER REACHED)
           :118      INSERT verified_knowledge    (4b)
```

The injected `RuntimeError` fires at line 109, **before** `resolve_tags` (line 114) ever executes. So no tag is registered on this path, and `tag_count == 0` is **trivially true** — the test does not exercise the "tag was registered, then rolled back" path it is named for.

**Why this matters (plan-implied invariant):** plan P2.1-5 AC#1 explicitly requires the forced-failure to roll back "the VK row, the decision event, **AND the tag registration**." The VK-row + decision-event rollback is covered by the pre-existing `TestPromoteHypothesisAtomicity`; the *new* invariant P2.1 adds is the tag-registration rollback, and that is the one this test fails to genuinely verify. A future regression that breaks tag atomicity inside promotion (e.g. moving `resolve_tags` outside the `with conn:` block, or making it self-commit) would **not** be caught by this test. The standalone transaction-neutrality of `resolve_tags` *is* covered (test_tags.py::test_transaction_neutral_no_implicit_commit), so the impl is correct — but the promotion-integration atomicity has no real guard.

**Lean — α:** re-point the injection to fire *after* `resolve_tags`, at the VK INSERT (promotion.py:118) — e.g. patch `conn.execute` to raise on the VK insert, or seed a duplicate `promoted_from_hypothesis_id` to trigger the `UNIQUE` `IntegrityError` on insert — and assert the tag registered at line 114 is rolled back. This is a 1-test fix; no impl change (the impl is already atomic).

### 🟢 G1 — Y1/G1/G3 routing absorbed correctly (verified)

- **Y1 both-sides**: `query_set = {normalize_tag(t) ...}` AND `row_tags = {normalize_tag(t) ...}` (lookup.py:44,47). The **legacy-row test** (test_lookup.py::test_legacy_raw_stored_row_found_by_normalized_query) genuinely inserts a raw `["LLM Cost"]` VK row and finds it via `lookup(["llm cost"])` — the exact case the first plan draft missed. ✓
- **G1 placement**: `resolve_tags` is inside the `with conn:` block, after the UPDATE (open txn), before the VK INSERT (promotion.py:114) — the corrected location. ✓
- **G3**: `promote_hypothesis(topic_tags=["   "])` raises `ValueError` (test_promotion.py); `normalize_tag("LLM - Cost") == "llm---cost"` and `"llm cost" != "llm-costs"` pinned (test_tags.py). ✓

### 🟢 G2 — two minor cleanliness notes (non-blocking)

- **e2e ad-hoc constitution check is weaker than the canonical guard**: `test_p2_1_e2e.py::test_p2_1_no_llm_constitution` re-implements a no-LLM scan with near-always-true assertions (`"anthropic" not in source.lower() or "ADR" in source`). Plan P2.1-6 AC#3 only asked to confirm the existing `tests/memory/test_constitution.py` rglob covers `tags.py` (it does — verified). The ad-hoc test is redundant and misleading; recommend deleting it (rely on the canonical guard) or strengthening it to the canonical `forbidden_patterns`. Harmless — the real guard holds.
- **`promotion.py` module docstring is mildly stale**: the ordering note (lines 14-15) reads "UPDATE hypothesis → append_in_transaction → INSERT VK" and omits the now-interleaved `resolve_tags` step (line 114). The inline comment at 111-113 is correct; only the top docstring lags.

### 🟢 G3 — scope discipline + claims verified

All six push-backs land where the plan/ADR said; spot-verified cites (promotion.py:101/104/109/114/118 transaction structure; store.py:75/87 tag table + ALTER guard; schema.py:94 field; lookup.py:44/47 both-sides). handoff §4.5/§5.8 light-touch, accurate (`candidate_for_promotion` P1.7+ → P2.2 corrected; migration template inscribed); **no §7-P1.2-stale fix bundled**; all deferrals (matcher, agent-wiring, FK storage, backfill, synonym-merging) untouched. One-atomic-one-commit honored.

## What the architect needs to route

1. **Y1 (🟡):** the tag-rollback atomicity test is vacuous (injects before `resolve_tags`). Lean **α** — re-point the injection to the VK INSERT so the registered-tag rollback is actually exercised (1-test fix, no impl change). Alternatives: **β** accept (the invariant is transitively covered by test_tags.py transaction-neutrality + the impl is correct) — leaves the promotion-integration atomicity unguarded against regression.
2. **Greens** are affirmations + optional hardenings (G2 e2e-constitution cleanup, docstring) the junior can absorb without an architect call.

Per ADR-008 Amendment 1 (Route B), state auto-advances to `awaiting_R0_A` regardless of this verdict; R0-A fires, then joint-verdict evaluation. This 🟡 makes the joint verdict non-clean → `awaiting_architect_decision` for routing.

---

## Verdict bump (RC-10) — needs_architect → clean

Architect routed this review's Y1 as **A → α** (`architect-routing-on-impl.md`, 2026-05-30; A = senior Y1 = R0-B Y2, two-reviewer confirmation incl. cross-family). Absorbed in the senior revision: `test_promotion.py::test_tag_registration_rolls_back_with_vk_insert_failure` is re-pointed to trip the `UNIQUE` on `verified_knowledge.promoted_from_hypothesis_id` at the VK INSERT (promotion.py:118) — which runs **after** `resolve_tags` (promotion.py:114) — so a tag is genuinely registered then rolled back (mirrors the `record_hypothesis` counterpart `test_store.py:504`). The test now fails if the tag survives; the false-confidence gap is closed. **Test-only; no `src/` change** (the impl was atomically correct on every traced path — all three reviews concur). Gates green: ruff ✓ · mypy --strict ✓ (18 files) · pytest ✓ (memory + integration). Verdict → **clean**.
