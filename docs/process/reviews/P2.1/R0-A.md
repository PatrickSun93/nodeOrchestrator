---
task_id: P2.1
round: R0-A
verdict: clean
verdict_history:
  - needs_architect  # original (0🔴 1🟡 4🟢); Y1 → B → γ dismissed (cross-family-caught false positive), bumped per RC-10
findings_count:
  red: 0
  yellow: 1
  green: 4
---

# P2.1 R0-A (post-impl, architect-partner lens) — shared tag registry

| Field | Value |
|---|---|
| Round | R0-A (post-impl; architect-dispatched) |
| Reviewer | architect-partner (Claude family; doc / architecture / correctness lens) |
| Commit | `6d9cf7d` on `claude/P2.1-impl` (atomics P2.1-1..-6) |
| Baseline | `main` (ADR-018 Accepted; plan P2.1.md) |
| Date | 2026-05-30 |
| Gates | ruff ✓ · mypy ✓ (31 files) · pytest **981 passed** · constitutional no-LLM (covers `tags.py`) ✓ |
| Verdict | **needs_architect** — 0🔴 · 1🟡 · 4🟢 |

> **Dispatch note:** the dispatch message was garbled (concatenated a stale "R0-A-on-plan → `claude/P2.1-plan`" with this one). Reconciled against reality: the plan-stage R0-A-on-plan is already done + merged (PR #27); `claude/P2.1-plan` no longer exists (renamed → `claude/P2.2-plan`). The live task is this **post-impl R0-A** at `6d9cf7d`. Proceeded on that (no ambiguity). **R0-B (cross-family) is still required this cycle** (architect call) and is a separate dispatch — not covered here. Senior `plan-vs-impl.md` not yet present (runs parallel; not my artifact).

## Summary

Clean, faithful implementation. The plan's 5 atomics land 1:1 as 5 commits; the routed plan-stage items are all implemented **and tested** — Y1→α both-sides lookup normalization (legacy-raw-row findability, 3 tests incl. e2e), G3 empty-tag `ValueError` + hyphen near-miss pinning, the first ALTER-not-CREATE migration. Gates fully green. `normalize_tag`/`resolve_tags` are pure + transaction-neutral as specified, and the high-stakes promotion path (ADR-016 D11 atomicity) is implemented **correctly** with a rollback test.

One **🟡**, empirically confirmed: **`record_hypothesis` calls `resolve_tags` *outside* its `with conn:` block** — the one place the impl deviates from its own accepted plan (P2.1-4 says "inside") + ADR-018 D6 + the G1 routing note. This opens a real tag-registration atomicity leak on the validation-failure path. `promotion.py` got the identical pattern *right* (inside the block), so this is an inconsistency, not a misunderstanding — and the fix is a 3-line move. Low blast radius (a spurious descriptive registry row, no P2.1 consumer), hence 🟡 not 🔴, but it contradicts an accepted contract + explicit routing, so it's the architect's to route.

## Findings

| # | Sev | Finding | Lean |
|---|---|---|---|
| Y1 | 🟡 | `record_hypothesis` runs `resolve_tags` *before* `with conn:` → tag-registration leak on a post-resolve validation failure (empirically confirmed). Deviates from plan P2.1-4 + ADR-018 D6 + G1; `promotion.py` does it right | α — move inside the block (match `promotion.py`) + add the symmetric atomicity test |
| G1 | 🟢 | `promotion.py` D11 atomicity correct — `resolve_tags` inside `with conn:`, after UPDATE / before VK INSERT; rollback tested | affirm |
| G2 | 🟢 | Y1→α both-sides lookup normalization implemented + tested (legacy raw-stored VK found) | affirm |
| G3 | 🟢 | ALTER migration + G3 fold-ins (empty-tag raise, hyphen near-miss) implemented + tested; fresh-vs-migrated column-order benign | affirm + 1 note |
| G4 | 🟢 | Gates green; constitution clean; handoff §4.5 updated; atomic-commit discipline 1:1 with plan | affirm |

---

### 🟡 Y1 — `record_hypothesis` resolves tags *outside* its transaction → confirmed registry-leak on validation failure

**The deviation.** `store.py record_hypothesis` (full body read) runs, in order: `source_event_ids` existence check (SELECT) → `resolve_tags(topic_tags or [], conn)` → `hyp = Hypothesis(...)` → `with conn: INSERT hypothesis`. The `resolve_tags` call — which does `INSERT OR IGNORE INTO tag` (DML) — is **before** the `with conn:` block. But `Hypothesis(...)` (Pydantic: `content` min_length=1, `confidence` ∈[0,1]) is constructed **after** `resolve_tags` and **can raise**. The plan (P2.1-4: *"inside the existing `with conn:` block, call `resolve_tags`"*), ADR-018 D6, and the routed G1 note all say resolve_tags must be **inside** the transaction. `promotion.py` follows that (G1); `record_hypothesis` does not.

**Empirically confirmed** (throwaway probe, not committed):

```
record_hypothesis(content="", topic_tags=["leaked-tag"])  → ValidationError
  registry after failed call: ['leaked-tag']   in_transaction: True   ← orphaned, uncommitted
record_hypothesis(content="ok", topic_tags=["legit"])     → succeeds (commits)
  registry: ['leaked-tag', 'legit']            ← the later write committed the orphan too
  survives rollback                            ← durably committed
```

So a failed `record_hypothesis` (caller passes empty/invalid content with a *new* tag) leaks that tag into the registry, committed by the next unrelated successful write. This violates ADR-018 D4/D6's stated contract — *"transaction-neutral … rides the caller's transaction, so a failed record rolls back the tags too."* It also leaves the connection with an open transaction after the failure (a surprising side effect for callers).

**Why 🟡, not 🔴:** trigger needs a caller bug (invalid `content`/`confidence`) **and** a genuinely-new tag in the same call; blast radius is one spurious *descriptive* tag in a registry that has **no consumer in P2.1** (the matcher is P2.2). It is not hypothesis/VK data corruption, and the high-stakes multi-write path (promotion, D11) is correct. So it's a contract/consistency defect, not a correctness-critical break.

**Why it still needs routing:** it contradicts (a) the **accepted** ADR-018 D6, (b) the **routed** G1 note, and (c) the impl's **own plan** P2.1-4 — an impl-deviates-from-accepted-plan item shouldn't land silently regardless of blast radius (that's what R0-A exists to catch). And it's asymmetric with `promotion.py`, which a future reader will find confusing.

**Lean α (fix now):** move `resolve_tags` + the `Hypothesis(...)` construction **inside** the `with conn:` block (mirror `promotion.py`), so a post-resolve validation failure triggers the `with conn:` rollback and discards the tag. Trivial. **Plus** add the missing symmetric test — `test_record_hypothesis_atomicity_tag_rolls_back_on_failure` (the analogue of the existing `test_promote_atomicity_tag_rolls_back_on_failure`, which is exactly why promotion's path was gotten right and this one wasn't — there was no test pulling on it).

### 🟢 G1 — `promotion.py` D11 atomicity is correct

Verified: `resolve_tags(topic_tags or [], conn)` sits **inside** the `with conn:` promotion block, after the `UPDATE hypothesis` (which opens the txn, satisfying the `append_in_transaction` DML-first guard) and before the VK `INSERT`. Transaction-neutral resolve joins the single D11 transaction; a failed promotion rolls back the VK row, the decision event, **and** the tag registration together. Covered by `test_promote_atomicity_tag_rolls_back_on_failure`. This is the load-bearing path and it's right — which is what makes Y1 a fixable inconsistency rather than a design miss.

### 🟢 G2 — Y1→α both-sides lookup normalization landed faithfully

`lookup.py` normalizes **both** `query_set = {normalize_tag(t) for t in topic_tags}` **and** `row_tags = {normalize_tag(t) for t in json.loads(row["topic_tags"])}` before the OR-intersection — exactly the routed Y1→α resolution. ADR-016 D6 semantics preserved (empty-query `ValueError`, `last_validated DESC, id ASC`, no-LLM). Tested three ways: `test_lookup_normalizes_both_query_and_stored_tags`, `test_lookup_legacy_raw_row_found_by_normalized_query`, and e2e `test_p2_1_lookup_finds_legacy_raw_stored_vk` — the legacy raw-stored-tag case the first plan draft missed is now explicitly covered. No-backfill (D8) is sound because of this.

### 🟢 G3 — migration + G3 fold-ins implemented + tested

`_ensure_hypothesis_topic_tags` is the PRAGMA-guarded idempotent `ALTER TABLE … ADD COLUMN … NOT NULL DEFAULT '[]'` (ADR-018 D5), called after `executescript`; `tag` table is a plain CREATE. G3 fold-ins present: `resolve_tags`/`record`/`promote` raise `ValueError` on empty-normalizing tags (`test_resolve_empty_normalizing_tag_raises`, `test_promote_empty_normalizing_tag_raises`), and the hyphen near-miss is pinned (`test_normalize_hyphen_near_miss_not_collapsed`). **One note:** fresh-DB CREATE places `topic_tags` before `created_at`, while the migrated-DB ALTER appends it last → column-order differs between fresh and migrated DBs. **Benign** — every access is by name (`row["topic_tags"]`, named INSERT columns), never positional — but worth a one-line comment so a future positional-access refactor doesn't trip. The migration round-trip test should assert named read-back on a *migrated* DB (confirm it does).

### 🟢 G4 — gates, constitution, narrative, discipline

ruff ✓ · mypy ✓ (31 files) · **981 passed** · `tests/memory/test_constitution.py` (no-LLM rglob) covers the new `tags.py` and is green. `handoff.md` §4.5 updated (the `topic_tags` field + the P2.1 registry note; §7-P1.2-stale correctly **not** bundled — architect-deferral honored). Six atomic commits map 1:1 to the plan's six atomics (RC-17 discipline). Constitution clean: `tags.py` is pure code, no LLM.

## Incidental (not a P2.1 finding — on record, not charged to this cycle)

`promotion.py`'s VK INSERT carries `hyp.last_validated if False else _now_ms()` — a dead `if False` branch (`Hypothesis` has no `last_validated` field; the branch would `AttributeError` if ever taken, but can't be). It is **pre-existing from P1.6.5** (a context line in the diff, not a P2.1 change), so out of scope here — flagging only so a future cleanup (or a P1.6.5 retro note) can simplify it to `_now_ms()`.

## What the architect needs to route

1. **Y1 (🟡):** α (move `resolve_tags` inside `record_hypothesis`'s `with conn:` + add the symmetric atomicity test — matches `promotion.py`, the plan, and the accepted ADR) vs β (accept the narrow window; document that `record_hypothesis` tag-registration is not atomic w.r.t. construction-validation). My lean: **α** — trivial, and it closes an impl-vs-accepted-plan gap.
2. **Greens** are affirmations; G3's column-order comment is an optional one-liner the junior can fold with the Y1 fix.

R0-A does not change state. **R0-B (cross-family) is still owed this cycle** (architect dispatch); I'll synthesize R0-A + R0-B + senior plan-vs-impl for routing once they land. ADR-018's contract is well-served by this impl modulo Y1.

---

## Verdict bump (RC-10) — needs_architect → clean

This review's Y1 (`record_hypothesis` resolves tags *outside* its `with conn:` block → tag-registration leak on a post-resolve validation failure) was routed **B → γ — dismissed** (`architect-routing-on-impl.md`, 2026-05-30): a **false positive caught cross-family** (R0-B Y1). The code-trace refutes it — `resolve_tags` has been *inside* `record_hypothesis`'s `with conn:` block since the first P2.1-4 commit (`bc27e88`; store.py:178), and the validation-failure path is unreachable (`Hypothesis(...)` constructs at store.py:149, *before* the block, so a `ValidationError` exits before `resolve_tags` is ever reached). The cited "empirical probe" was not reproducible (it crashed at `Event(...)` construction and never executed `record_hypothesis`). No action — a fix would be a no-op on already-correct code; the invariant is genuinely covered by `test_store.py:504`. **Recorded as dismissed-on-cross-family-evidence, not silently dropped.** Verdict → **clean**. (Meta: a clean RC-20 dual-lens datapoint — cross-family *corrected* an in-family false positive before it churned the impl; flagged for P2.1 retro.)
