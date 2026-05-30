---
task_id: P2.1
kind: architect-routing
date: 2026-05-29
reviews_acked:
  - R0-A-on-plan.md
decisions:
  Y1: α (lookup normalizes BOTH query AND stored tags at match-time; ADR-018 D7 states the stored-tag treatment explicitly; closes the D7/D8 tension without backfill)
---

# P2.1 architect routing — Y1 → α

**Architect decision (this session):** the registry slice's single plan-stage Y finding resolves to the reviewer's lean **α (absorb)**. (P2.1's earlier matcher-framing R0-A was never routed — resequenced to P2.2 before routing; this is the registry slice's first routed finding.)

This file is the **signal artifact for the senior revision session.** Senior picks P2.1, reads this + `R0-A-on-plan.md` + the current plan + ADR-018, applies the routed action + the non-routing fold-ins below, and pushes a revision commit on `claude/P2.1-registry-plan`. Then the architect accepts ADR-018 (status bump) — the accept-gate is honest (ADR-018 parses `proposed`), so the bump genuinely gates `awaiting_architect_accept → awaiting_junior_impl`.

## Per-finding routing

### Y1 → α — lookup normalizes both query and stored tags (close the D7/D8 tension; no backfill)

**Problem (R0-A-on-plan Y1):** D7 normalizes only the lookup *query*; `lookup.py` matches it against **raw** stored tags; D8 says no backfill. So pre-P2.1 VK rows (non-canonical stored tags) become unfindable by a normalized query.

**Action:**
- `lookup.py`: normalize the **stored** tags too, at match-time — `row_tags = {normalize_tag(t) for t in json.loads(row["topic_tags"])}` — in addition to normalizing the query set. Both sides normalized → raw-stored legacy rows *and* canonical new rows both match; D8's no-backfill becomes safe. Cost is per-row normalization on a small scanned set (ADR-016 D6 already assumes small per-scope row counts) — negligible.
- **ADR-018 D7**: state explicitly that lookup normalizes **both** the query and the stored tags at match-time (so D7 and D8 are consistent and no-backfill is sound). Adjust the D7 worked example/rationale accordingly.
- **Plan P2.1-5**: extend the D6-refinement acceptance with a **legacy-row test** — a VK row written with a *raw* (pre-P2.1-style, non-canonical) `topic_tags` is found by a normalized query. This is the case the current plan misses.

## Non-routing fold-ins (affirmations / hardening — no α/β/γ; fold during the same revision)

These are R0-A-on-plan greens, not routed findings; natural to absorb in the Y1 revision:

- **G1 (precision):** put `resolve_tags` **inside** `promote_hypothesis`'s `with conn:` block (after the `UPDATE hypothesis`, before the VK INSERT) — **not** at the old `promotion.py:95` location (which is *before* the block). Transaction-neutrality makes it robust either way, but inside is unambiguous; the `append_in_transaction` guard is satisfied by the existing UPDATE, not by `resolve_tags`.
- **G3 (make explicit + test):** routing VK tags through `resolve_tags` means `promote_hypothesis` now **raises `ValueError`** on a whitespace-only / empty-normalizing tag — a reasonable fail-loud contract tightening vs ADR-016; state it in ADR-018 D6/D7 + add a test. Also add `normalize_tag` boundary tests for whitespace-adjacent hyphens (`"LLM - Cost"` → `"llm---cost"`) so the canonical form + near-miss behavior are pinned.

No other findings. ADR-018 is accept-worthy once the Y1 revision lands.
