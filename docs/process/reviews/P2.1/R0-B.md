---
task_id: P2.1
round: R0-B
reviewer_family: deepseek
verdict: clean
verdict_history:
  - needs_architect  # original (0🔴 2🟡 3🟢); Y1 → B → γ dismissed, Y2 → A → α absorbed, bumped per RC-10
findings_count:
  red: 0
  yellow: 2
  green: 3
---

# P2.1 R0-B (cross-family, impl-stage) — shared tag registry

| Field | Value |
|---|---|
| Round | R0-B (cross-family; dual-lens-r0b.md — runtime/concurrency/failure-mode lens) |
| Reviewer family | deepseek |
| Impl branch | `claude/P2.1-impl` @ `6d9cf7d` (atomics P2.1-2..6 at `4a2db94`..`6d9cf7d`) |
| Baseline | `main`; ADR-018 (Accepted); `senior-plans/P2.1.md` (R0-A-on-plan Y1→α absorbed) |
| Prior reviews | R0-A (`a0b7b6a`, 0🔴 1🟡 4🟢); senior plan-vs-impl (`3b521c8`, 0🔴 1🟡 3🟢); architect-routing (`architect-routing.md`, Y1→α) |
| Date | 2026-05-29 |
| Verdict | **needs_architect** — 0🔴 · 2🟡 · 3🟢 |

## Lens preamble

Cross-family runtime/failure-mode lens per `dual-lens-r0b.md` §contrarian. Over-correcting for Claude biases: operational concerns under-weighted, sycophancy (agreeing with prior-reviewer consensus), and assuming types-are-right-means-runtime-is-right. This pass traces **actual execution order** through `record_hypothesis` and `promote_hypothesis` — what happens at each line when a failure fires, not what the plan says should happen. Specific focus: `resolve_tags` transaction-neutrality, `INSERT OR IGNORE` behavior under rollback, normalize both-sides edge correctness, and test coverage of the new atomicity invariants.

## Findings

| # | Sev | Finding | Evidence |
|---|---|---|---|
| Y1 | 🟡 | **R0-A Y1 is a false positive — `resolve_tags` IS inside `record_hypothesis`'s `with conn:` block from the initial impl commit.** The R0-A review claims `resolve_tags` runs *before* `with conn:`, describes an empirical probe showing a leaked tag after `ValidationError`. Code ordering at `bc27e88` (the P2.1-4 commit, verified via `git show bc27e88:src/orchestrator/memory/store.py`): `Hypothesis(...)` at line 151 (can raise `ValidationError` — BEFORE the block), `with conn:` at line 179, `resolve_tags(...)` at line 180 (INSIDE the block), INSERT at line 181. If `Hypothesis(content="")` raises `ValidationError`, the function exits at line 151-156 — `resolve_tags` is never reached. No tag leak is possible on this path. The R0-A's empirical probe result (`in_transaction: True` + orphaned tag committed by next write) cannot be reproduced against this code. The `record_hypothesis` tag-rollback test (`test_store.py:504`) confirms the correct path: it triggers an FK violation on the hypothesis INSERT (AFTER `resolve_tags` inside `with conn:`) and asserts `tag_count == 0` — genuinely exercising rollback. The impl is structurally correct; the R0-A review contains a code-reading error. | `store.py:149-199` (verified at `bc27e88` and `6d9cf7d`); `git show bc27e88:src/orchestrator/memory/store.py` lines 151, 179-180 |
| Y2 | 🟡 | **Promotion tag-rollback atomicity test is vacuous (senior Y1 confirmed).** `test_tag_registration_rolls_back_with_vk_insert_failure` patches `append_in_transaction` to raise at `promotion.py:109` — but `resolve_tags` runs at line 114, **after** the injection point. No tag is ever registered in the test path; `tag_count == 0` is trivially true. The test does not exercise the "tag was registered, then rolled back" invariant that P2.1-5 AC#1 requires. Independent confirmation of the senior's finding. The corresponding `record_hypothesis` test (`test_store.py:504`) IS genuine — the FK violation fires on the hypothesis INSERT which is AFTER `resolve_tags`, so the tag IS registered and then rolled back. That test is the model for the fix. | `test_promotion.py:340-360`; `promotion.py:101-114` (execution order confirmed) |
| G1 | 🟢 | **`record_hypothesis` tag-registration atomicity is correct** — `resolve_tags` inside `with conn:`, after `Hypothesis(...)` construction and source-event check (both pre-block, cannot leak tags). If hypothesis INSERT fails, the `with conn:` context manager rolls back the tag INSERTs. If `resolve_tags` itself raises `ValueError` (empty-normalizing tag), the `with conn:` rolls back (the error propagates past the `except sqlite3.Error` handler, but `__exit__` still fires). Confirmed via code-trace: no path where a tag INSERT survives a failed `record_hypothesis` call. | `store.py:149-199` |
| G2 | 🟢 | **`promote_hypothesis` D11 atomicity preserved** — `resolve_tags` is placed after the UPDATE (which opens the transaction and satisfies `append_in_transaction`'s `in_transaction` guard) and before the VK INSERT. All three write classes (UPDATE hypothesis, append decision event, INSERT VK + tag INSERTs from `resolve_tags`) share one transaction. Transaction-neutral `resolve_tags` does not commit. Rollback covers all writes. | `promotion.py:101-135` |
| G3 | 🟢 | **Both-sides normalization correctly implemented; legacy raw-stored rows findable without backfill.** `lookup.py:44` normalizes query set, `lookup.py:47` normalizes stored tags — both via `normalize_tag`. The legacy-row test (`test_lookup.py:154`) directly inserts a VK row with raw `["LLM Cost"]` and confirms it is found by `lookup(["llm cost"])`. No-backfill (ADR-018 D8) is sound. | `lookup.py:44-49`; `test_lookup.py:154-237` |

## Synthesis

Both prior reviews identified one 🟡 each, but from opposite directions: R0-A said the `record_hypothesis` path was *wrong* (outside-transaction); senior said the `promotion` *test* was vacuous. The cross-family code-trace confirms:

- **R0-A's Y1 does not exist in the code.** The impl dev placed `resolve_tags` inside `with conn:` from the first commit (`bc27e88`). The R0-A empirical probe result is not reproducible. This is not a "fix already applied" situation — the code never had the defect. The architect's pending Y1 routing (α — move inside block + add test) would be a no-op on code that is already correct.
- **Senior's Y1 is real** — the promotion tag-rollback test injects failure too early. The fix is a one-line injection-point change (patch the VK INSERT, not `append_in_transaction`), modeled on the already-working `record_hypothesis` counterpart test.

No 🔴 findings. The implementation is structurally correct across all runtime/failure-mode paths traced. Both 🟡 findings are about review accuracy and test coverage, not about shipped code correctness. The tag-registry atomicity invariants hold: `record_hypothesis` and `promote_hypothesis` both compose `resolve_tags` correctly inside their transactions; `lookup` normalizes both sides; `normalize_tag` is deterministic; `INSERT OR IGNORE` with PK is the correct idempotent auto-register under the project's single-connection constraint (ADR-011 D1).

## What the architect needs to route

1. **Y1 (🟡):** R0-A Y1 is a false positive — the code at `bc27e88` onward has `resolve_tags` inside `with conn:`. The architect should close (not route α/β) this finding. The `record_hypothesis` tag-rollback test (`test_store.py:504`) already genuinely covers the invariant.
2. **Y2 (🟡):** Senior Y1 confirmed — the promotion tag-rollback test is vacuous. Lean mirrors the senior's: re-point the injection to fire after `resolve_tags` (at the VK INSERT), modeled on `test_store.py:504`.
3. **Greens** are affirmations; no action needed.

---

## Verdict bump (RC-10) — needs_architect → clean

Both yellows resolved per `architect-routing-on-impl.md` (2026-05-30):

- **Y1 (B → γ — dismissed):** R0-B correctly identified R0-A Y1 as a false positive (`resolve_tags` is inside `record_hypothesis`'s `with conn:` from `bc27e88`); the architect dismissed R0-A Y1 on this cross-family evidence. No action.
- **Y2 (A → α — absorbed):** the vacuous promotion tag-rollback test is fixed — re-pointed to trip the `UNIQUE` on `promoted_from_hypothesis_id` at the VK INSERT (after `resolve_tags`), so a tag is genuinely registered then rolled back, mirroring `test_store.py:504`. Test-only, no `src/` change.

Gates green: ruff ✓ · mypy --strict ✓ · pytest ✓. Verdict → **clean**.
