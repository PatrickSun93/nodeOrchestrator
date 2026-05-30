---
task_id: P2.1
round: R0-A-on-plan
verdict: needs_architect
findings_count:
  red: 0
  yellow: 1
  green: 4
---

# P2.1 R0-A on plan (architect-dispatched pre-impl review) — registry

| Field | Value |
|---|---|
| Round | R0-A-on-plan (architect-dispatched per RC-9) — the **registry** slice (resequenced; matcher → P2.2) |
| Reviewer | architect-partner (doc / architecture / workflow-mechanics lens) |
| Stage | Plan + ADR-018 (Proposed), pre-impl. State `awaiting_architect_accept`. |
| Artifacts | `docs/process/senior-plans/P2.1.md`, `docs/decisions/ADR-018-cross-room-tag-registry.md` |
| Date | 2026-05-29 |
| Verdict | **needs_architect** — 0🔴 · 1🟡 (lookup D7/D8 consistency gap) · 4🟢 |

## Summary

Strong, careful plan + ADR. All five brief push-backs resolved with sound reasoning; the **honest ceiling** (registry is best-effort, not guaranteed consistency) is carried into ADR-018 §Context without over-claiming; the **transaction-neutral** composition into ADR-016 D11 is correct (verified); and the **RC-23 trap is heeded** — ADR-018 parses as `proposed`, not `accepted` (verified by running the parser), so the accept-gate is honest this time (contrast ADR-017, which tripped it).

One **🟡** is a genuine cross-decision gap: **D7 (normalize the lookup query) + D8 (no backfill) leave pre-P2.1 VK rows with non-canonical stored tags unfindable** — a lookup regression. The fix is cheap (normalize both sides at match-time) and the architect should rule on it. Everything else is affirmation. The design is accept-worthy once Y1 is routed.

## Findings

| # | Sev | Finding | Lean |
|---|---|---|---|
| Y1 | 🟡 | D7 normalizes only the query; with D8 (no backfill), pre-P2.1 VK rows with raw stored tags become unfindable by a normalized query | normalize **both** sides at match-time |
| G1 | 🟢 | Transaction-neutral composition into D11 is correct; atomicity preserved (verified `promotion.py` structure) | affirm + 1 precision note |
| G2 | 🟢 | RC-23 heeded — ADR-018 parses `proposed`, accept-gate honest (verified) | affirm |
| G3 | 🟢 | `normalize_tag` rules sound + conservative; one contract-tightening + test-coverage note | affirm + notes |
| G4 | 🟢 | All 5 push-backs resolved soundly; claims-with-cites verified | affirm |

---

### 🟡 Y1 — D7 (normalize query) + D8 (no backfill) make pre-P2.1 VK rows unfindable; normalize both sides at match-time

`lookup.py` matches the query tag-set against `row_tags = set(json.loads(row["topic_tags"]))` — the stored tags **raw**. D7 (P2.1-5) normalizes the *query* tags before the intersection, but **not** the stored tags. So matching is "normalized-query ∩ raw-stored":

- **Post-P2.1 VK rows**: stored tags are canonical (resolved at write via P2.1-5) → normalized query hits. ✓
- **Pre-P2.1 VK rows**: stored tags are **raw** (the old `promote_hypothesis` stored `topic_tags or []` un-normalized — verified `promotion.py:95,120`). D8 says **no backfill**. So a row stored with `["LLM Cost"]` is now matched against a normalized query `"llm-cost"` → `"llm-cost" ∉ {"LLM Cost"}` → **not found**. Worse, even a raw query `["LLM Cost"]` now normalizes to `"llm-cost"` and misses the raw-stored row. This is a **regression**: pre-P2.1, `lookup(["LLM Cost"])` exact-matched `"LLM Cost"` and found it.

D7 ("normalize the query so non-canonical queries hit canonical storage") silently **assumes stored tags are canonical** — which D8 (no backfill) guarantees they are *not* for legacy rows. The two decisions are in tension; the ADR's D7 worked example (`"LLM Cost"` query hits canonical `"llm-cost"` store) only holds for post-P2.1 rows.

**Real-world impact is currently low** (tests build fresh post-P2.1 rows; no production data) — which is why this is 🟡 not 🔴. But it's a genuine internal-consistency gap the architect should rule on, and the fix is strictly-better and cheap:

- **My lean: normalize BOTH sides at match-time** — `row_tags = {normalize_tag(t) for t in json.loads(row["topic_tags"])}`. Then raw-stored `"LLM Cost"` → `"llm-cost"` matches the normalized query, for **both** legacy and new rows, **no backfill needed**. Cost: normalize per stored tag per scanned row — negligible (ADR-016 D6 already assumes small per-scope row counts + a Python post-filter scan). It also makes D8's no-backfill genuinely safe rather than a latent edge.
- Alternatives the architect may prefer: **β** accept the edge (declare lookup only guaranteed for post-P2.1 rows; document it) — cheapest, leaves the latent regression; **γ** backfill existing rows (reverses D8) — more work, and normalize-both is simpler.

This belongs in ADR-018 D7 either way (state explicitly whether stored tags are normalized at read, or that lookup is post-P2.1-only).

### 🟢 G1 — Transaction-neutral composition into D11 is correct; atomicity preserved

Verified `promotion.py`: `with conn:` (100) → `UPDATE hypothesis` (103, DML-first, opens the txn) → `append_in_transaction` (108, guard satisfied) → `INSERT verified_knowledge` (112). The plan routes `resolve_tags` through `event_store.conn` **inside** this block; because `resolve_tags` is transaction-neutral (no commit, D4), its `INSERT OR IGNORE` joins the same txn and rolls back with a failed promotion. Atomicity holds — and the planned forced-failure rollback test (P2.1-5 AC#1) is the right guard, *necessary* because the safety depends on (a) `resolve_tags` never committing and (b) legacy autocommit mode (one txn until the `with` commits). For `record_hypothesis`, `resolve_tags` rides its `with conn:` (store.py:151) with no `append_in_transaction` guard to worry about — simpler. ✓

**Precision note for the junior**: put `resolve_tags` *inside* `with conn:` (after the UPDATE, before the VK INSERT). The plan's cite "replace `topic_tags_list = topic_tags or []`" points at `promotion.py:95`, which is **before** the `with conn:` block (line 100) — the call must move *into* the block, not be replaced in place. (Transaction-neutrality makes it robust either way, but inside is correct and unambiguous; the guard is satisfied by the existing UPDATE, not by `resolve_tags`.)

### 🟢 G2 — RC-23 heeded; accept-gate honest

I ran `_parse_adr_status`'s logic against ADR-018: result **`proposed`** (its only "accepted" mention is paraphrase — "ADR-016 is already accepted" — never the literal `Status: Accepted` substring). So the accept-gate will correctly require an architect status bump before advancing (unlike ADR-017, which the matcher slice tripped). The brief's RC-23 constraint worked as intended; the senior also grep-verified it (P2.1-1 AC). The D6-refinement-in-ADR-018 choice (not editing ADR-016, push-back #2) reinforces this by keeping edits away from ADR-016's status region. ✓

### 🟢 G3 — `normalize_tag` rules sound; two small notes

The rule (`strip` → `lower()` not `casefold()` → `re.sub(r"\s+","-",s)`; no punctuation strip, no NFC) is conservative and well-justified — it avoids distinct-concept collisions (`c++`≠`c`, `ß`≠`ss`) at the cost of near-misses not collapsing, a tradeoff the ADR owns. Two notes (non-blocking):

- **Contract tightening, make it explicit + tested**: routing VK tags through `resolve_tags` means `promote_hypothesis` now **raises `ValueError`** on a tag that normalizes to empty (whitespace-only), where pre-P2.1 it stored whatever it was given. That's a (reasonable, fail-loud) tightening of the promotion contract vs ADR-016 — worth one explicit line in D6/D7 + a test, so it's not a silent behavior change.
- **Determinism edge in tests**: hyphen-adjacent whitespace yields multi-hyphens (`"LLM - Cost"` → `"llm---cost"`) and they aren't collapsed; `"llm cost"`/`"llm-cost"` stay distinct. Deterministic (so consistency holds) but surprising — add these to the P2.1-3 boundary tests so the canonical form is pinned and the near-miss behavior is on the record.

### 🟢 G4 — Push-backs resolved soundly; claims-with-cites verified

All five push-backs land where the brief leaned, each with a real reason (esp. #2 record-D6-refinement-in-018 to avoid the RC-23 trap, and #4 canonical-string PK for free UNIQUE + natural `INSERT OR IGNORE` idempotency). Spot-verified the decision-bearing cites: `promotion.py:42` (`topic_tags` param exists), `:95/100/103/108/112/120` (transaction structure), `store.py:89` (`executescript`, CREATE-only → ALTER genuinely needed), `:151` (`record_hypothesis` `with conn:`), `lookup.py` (raw-stored match — grounds Y1), `schema.py:109` (VK mirror). All accurate. The "first ALTER-not-CREATE" premise and the migration template are correct.

## What the architect needs to route

1. **Y1 (🟡):** normalize both sides at match-time (lean — cheap, robust, no backfill) vs accept-the-edge (β) vs backfill (γ). Whichever, ADR-018 D7 should state the stored-tag treatment explicitly.
2. **Greens** are affirmations + optional hardenings (G1 precision note, G3 contract-tightening line + boundary tests) the junior can absorb without an architect call.

ADR-018 is accept-worthy once Y1 is routed. R0-A-on-plan does not change state (RC-9 manual dispatch); this review informs the accept-vs-route decision.
