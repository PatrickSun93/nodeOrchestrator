---
task_id: P2.1
kind: architect-routing-on-impl
date: 2026-05-30
stage: impl
impl_commit: 6d9cf7d
reviews_acked:
  - plan-vs-impl.md   # senior — 0🔴 1🟡 3🟢
  - R0-A.md           # architect-partner — 0🔴 1🟡 4🟢
  - R0-B.md           # cross-family (deepseek) — 0🔴 2🟡 3🟢
decisions:
  A: α (fix the vacuous promotion atomicity test — re-point the failure injection to fire at/after the VK INSERT; 1-test fix, no impl change)
  B: γ (dismissed on cross-family evidence — R0-A Y1 false positive; resolve_tags is inside the with conn: block from bc27e88; leak path unreachable)
---

# P2.1 architect routing — impl stage (A → α · B → γ)

**Architect decision (this session, chat 2026-05-30, architect = Peidong):** the impl-stage joint verdict carried 4 raw 🟡 across three reviews (senior plan-vs-impl 1, R0-A 1, R0-B 2), which the architect-partner synthesis collapsed to **2 distinct issues**. Architect routes: **A → α** (real; 1-test fix), **B → γ** (dismissed — false positive caught cross-family).

This file is the **signal artifact for the senior revision session** (impl stage). Senior picks P2.1, reads this + the three impl-stage reviews + the impl at `6d9cf7d`, applies the **single** routed action (A's test fix) + the optional green fold-ins, and pushes a revision commit on `claude/P2.1-impl`. **No impl/src change is routed** — the shipped code is atomically correct on every traced path (all three reviews concur); the only real defect is a test that gives false confidence.

## Issue map (4 raw 🟡 → 2 issues)

| Issue | Raised by | Confidence | Route |
|---|---|---|---|
| **A** — promotion tag-rollback atomicity test is vacuous | senior Y1 **+** R0-B Y2 | 2 reviewers (incl. cross-family) → high | **α** |
| **B** — `record_hypothesis` resolves tags outside its transaction | R0-A Y1 (architect-partner) — refuted by R0-B Y1 | single-lens, cross-family-refuted | **γ** |

## Per-issue routing

### A → α — fix the vacuous promotion tag-rollback atomicity test (test-only; no impl change)

**Finding (senior Y1 = R0-B Y2, independently confirmed):** `tests/memory/test_promotion.py::test_tag_registration_rolls_back_with_vk_insert_failure` patches `append_in_transaction` to raise at `promotion.py:109` — but `resolve_tags` runs at `promotion.py:114`, **after** the injection point. So no tag is ever registered on the test path; `tag_count == 0` is **trivially true**. The test does not exercise the "a tag WAS registered, then rolled back" invariant that plan P2.1-5 AC#1 requires. A future regression that broke promotion-integration tag atomicity (e.g. moving `resolve_tags` outside `with conn:`, or making it self-commit) would not be caught.

**Why α (not β-accept):** the new invariant P2.1 adds — tag registration rides the promotion transaction and rolls back with it — is exactly the one with no genuine guard. The impl IS atomically correct (R0-B G2 traced it; `resolve_tags` is inside `with conn:`, after the UPDATE, before the VK INSERT — promotion.py:114), so this is purely a test-confidence gap, but an unguarded load-bearing invariant is worth one cheap test. Two independent reviewers (one cross-family) flagged it → high confidence.

**Action (senior revision):**
- Re-point the failure injection in `test_tag_registration_rolls_back_with_vk_insert_failure` to fire **at or after the VK INSERT** (`promotion.py:118`), so `resolve_tags` (line 114) has already registered the tag before the failure. Two viable mechanisms:
  - patch `conn.execute` to raise on the VK INSERT specifically, **or**
  - seed a row with a duplicate `promoted_from_hypothesis_id` so the VK INSERT trips the `UNIQUE` `IntegrityError` (ADR-016 D2 Y9 backstop) naturally.
- Assert the tag registered at line 114 **is rolled back** (`tag_count == 0` after the failure) — now a *genuine* assertion, since the tag was actually written before the rollback.
- **Model: `tests/memory/test_store.py:504`** (`test_tag_registration_rolls_back_with_failed_insert`) — the `record_hypothesis` counterpart already does this correctly (FK violation on the hypothesis INSERT, which is after `resolve_tags`); mirror its shape for the promotion path.
- **No `src/` change.** Impl is correct; this is a 1-test fix.

### B → γ — dismissed on cross-family evidence (R0-A Y1 is a false positive)

**Finding (R0-A Y1, architect-partner):** claimed `record_hypothesis` calls `resolve_tags` *outside* its `with conn:` block, so a post-resolve `ValidationError` would leak an uncommitted tag, committed by the next write; cited an "empirical probe."

**Dismissed — the defect does not exist in the code** (R0-B Y1, cross-family code-trace, architect-partner re-verified against `store.py`):
- `record_hypothesis` constructs `Hypothesis(...)` at **store.py:149** — *before* the `with conn:` block — so a `ValidationError` (empty content, bad confidence) exits at line 149 and **`resolve_tags` (store.py:178, inside the block) is never reached**. The "validation fails after a tag is registered" path is **unreachable**.
- `resolve_tags` has been **inside** `with conn:` since the first P2.1-4 commit (`bc27e88`); this is not "fix already applied" — the code never had the defect.
- The R0-A "empirical probe" is **not reproducible**: re-running it showed the probe script crashed at `Event(...)` construction (missing `id`/`timestamp`) and never executed `record_hypothesis` — i.e. the cited probe result was never actually observed. Architect-partner acknowledges the code-reading + fabricated-probe error.
- The invariant is already genuinely covered by `test_store.py:504` (FK violation after `resolve_tags` → tag rolled back).

**Recorded as: dismissed-on-cross-family-evidence** (NOT silently dropped). A would-be "α — move inside block + add test" action on this finding would be a **no-op on already-correct code**; routing it would have churned the impl for nothing. No action.

## Non-routing fold-ins (optional greens — no α/β/γ; senior may fold in the A revision)

From senior plan-vs-impl G2 + R0-A G3 — affirmations/hardening, junior/senior may absorb without an architect call:
- **e2e ad-hoc constitution check is redundant** — `test_p2_1_e2e.py::test_p2_1_no_llm_constitution` re-implements a weaker no-LLM scan (near-always-true assertions). Plan P2.1-6 AC#3 only asked to confirm the canonical `tests/memory/test_constitution.py` rglob covers `tags.py` (it does). Recommend deleting the ad-hoc test (rely on the canonical guard) or strengthening to the canonical `forbidden_patterns`.
- **`promotion.py` module docstring mildly stale** — the ordering note (lines 14-15) omits the now-interleaved `resolve_tags` step; the inline comment (111-113) is correct. One-line docstring touch.
- **Fresh-vs-migrated `topic_tags` column order differs** (R0-A G3) — benign (all access is by-name); optional one-line comment so a future positional-access refactor doesn't trip.

## RC-20-family note — clean dual-lens payoff (cross-family caught a Claude-family false positive)

This cycle is a **clean datapoint for the RC-20 dual-lens economics line** ([[RC-20]] / `dual-lens-r0b.md`): the cross-family R0-B (deepseek) **refuted a Claude-family reviewer's false positive** — not just adding net-new findings, but *correcting* an in-family error. Specifically, R0-B's code-trace caught that R0-A's Y1 (a) described a code path that does not exist and (b) rested on an "empirical probe" that was never actually executed (fabricated result). This is the cross-family lens doing exactly what it is dispatched for, in a new mode: prior RC-20 measured cross-family *net-new* findings (operational/runtime the Claude family under-weights); P2.1 adds a **correction** mode — catching a same-family fabricated/mis-read finding before it churned the impl (the B→γ no-op would have been dispatched without it).

**Worth capturing at P2.1 retro** (do not graduate on one instance — RC-4 discipline): the dual-lens value is not only "external finds more" but "external corrects in-family error," including hallucinated evidence. Tentatively strengthens the case for cross-family R0-B on cycles where the in-family R0-A makes empirical/runtime claims (which are the claims most prone to un-verified assertion). Architect-partner will fold this into `P2.1-candidates.md` if it recurs or at retro; flagged here so the routing record carries the meta-observation.

**Self-note (architect-partner):** R0-A Y1 was my finding, and it was wrong — both the code-read and the probe citation. The cost was caught here (γ, no impl churn) only because R0-B ran. Reinforces: do not cite an "empirical probe" result without confirming the probe actually executed the path under test.

## Net

- **1 routed action:** A → α (fix the vacuous promotion atomicity test; test-only, model `test_store.py:504`).
- **1 dismissed:** B → γ (R0-A false positive; cross-family-caught; no action).
- **0 🔴; shipped code correct on every traced path.** After A's test fix lands + verdict bumps, P2.1 is merge-ready.

State: per ADR-008, this routing moves P2.1 to senior-revision territory; senior absorbs A on `claude/P2.1-impl`, bumps the verdicts, then architect judges merge.
