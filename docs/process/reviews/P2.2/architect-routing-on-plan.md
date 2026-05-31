---
task_id: P2.2
kind: architect-routing-on-plan
date: 2026-05-31
stage: plan
adr: ADR-017
reviews_acked:
  - R0-A-on-plan.md          # architect-partner — 0🔴 2🟡 5🟢
  - R0-B-cross-family.md     # cross-family (deepseek) — 0🔴 2🟡 5🟢
decisions:
  A: α (add untagged-across-rooms→zero-flagged test; unit + e2e; no impl change)
  B: α (orthogonality guard as real call/import AST check, not whole-file substring scan)
  G2: α-small (inscribe normalize_tag idempotency as a required property in ADR-017 D2 + ADR-018 D3 cross-ref note)
---

# P2.2 architect routing — plan stage (A → α · B → α · G2 → α-small)

**Architect decision (this session, chat 2026-05-31, architect = Peidong):** the plan-stage joint verdict carried 4 raw 🟡 across two reviews (R0-A 2, R0-B cross-family 2), which the architect-partner synthesis collapsed to **2 issues — both flagged by both lenses (high confidence), zero divergence, zero false positives**. Both are test-approach gaps, not design defects; the matcher design is sound on every invariant both lenses traced. Architect routes **A → α**, **B → α**, plus the cross-family green **G2 → α-small** (an Accept-optional inscription worth taking).

This file is the **signal artifact for the senior revision session** (plan stage). Senior picks P2.2, reads this + the two plan-stage reviews + the current plan + ADR-017, applies the three routed actions, and pushes a revision commit on `claude/P2.2-matcher-plan`. Then the architect accepts ADR-017 (status bump) — the gate is honest (ADR-017 parses `proposed`; RC-23 clear), so the bump genuinely gates `awaiting_architect_accept → awaiting_junior_impl`. **No `src/` design change is routed** — A and B are test-approach, G2 is an ADR inscription.

## Issue map (4 raw 🟡 → 2 issues + 1 cross-family green)

| Issue | Raised by | Confidence | Route |
|---|---|---|---|
| **A** — empty/`[]`-tag-set exclusion untested (dominant early-life case) | R0-A Y1 **+** R0-B Y1 | both lenses (incl. cross-family) → high | **α** |
| **B** — orthogonality guard inherits whole-file substring fragility (RC-23 family) | R0-A Y2 **+** R0-B Y2 | both lenses (incl. cross-family) → high | **α** |
| **G2** — `normalize_tag` idempotency load-bearing but unnamed | R0-B green (cross-family) | single-lens (cross-family structural contribution) | **α-small** |

## Per-issue routing

### A → α — add the untagged-across-rooms → zero-flagged test (test-only; no impl change)

**Finding (R0-A Y1 = R0-B Y1, both lenses independently code-traced):** the matcher correctly excludes the empty canonical tag-set (`frozenset()`) from grouping — specified in ADR-017 D1, D3, and plan P2.2-2 AC#2 — but **no test exercises it**. This is the **dominant early-life case**: ADR-017 calls the matcher "dormant-until-fed," and no auto-tagging producer ships this slice, so most `Hypothesis` rows are untagged (`[]`) until a tagging producer lands. If the empty-set exclusion regresses (e.g. the group map is built before the empty-set filter, or the empty `frozenset` accidentally groups across rooms), **every untagged hypothesis across ≥`min_rooms` rooms gets flagged `candidate_for_promotion=True`** — a false-positive flood in exactly the common case. Scenario Y (P2.2-4) has no multiple-`[]`-tagged-across-rooms case.

**Why α (not β-accept):** maximal early-life blast radius (every untagged row) + near-zero test cost. The exclusion is the matcher's whole dormant-until-fed contract; it must be guarded.

**Action (senior revision):**
- Add a `matcher.py` unit test (P2.2-2): N ≥ `min_rooms` PENDING hypotheses across N distinct rooms, all `topic_tags=[]` → `run_matcher` flags **zero**; `list_promotion_candidates` returns empty.
- Add a line in the Scenario Y e2e (P2.2-4) covering the same (untagged rows across rooms are not flagged), so the dominant case is exercised end-to-end.
- **No `src/` change** if the impl is correct; this is the guard that proves it.

### B → α — implement the orthogonality guard as a real call/import check, not a substring scan

**Finding (R0-A Y2 = R0-B Y2, both lenses; verified):** plan P2.2-4 adds a structural advisory-orthogonality guard ("assert `matcher.py` does not reference `promote_hypothesis` / a `verified_knowledge` INSERT / `event_store.append`"), modeled on `tests/memory/test_constitution.py` — which is a **whole-file substring scan** (`if pattern in content`, verified `test_constitution.py:46`). A matcher docstring or comment documenting the orthogonality ("advisory only — never calls `promote_hypothesis`") would **trip the guard meant to enforce that property**, and the path-of-least-resistance "fix" is to delete the explanatory docstring — strictly worse (loses the human-readable orthogonality contract for a mechanical pass). This is the **same whole-file-substring fragility as RC-23** (`_parse_adr_status` misreading prose that quotes a status line), now recurring in a test this plan introduces.

**Why α:** the guard is supposed to *strengthen* the orthogonality guarantee; implemented as a prose substring scan it actively penalizes documenting that guarantee. Fix the mechanism so the test checks **code, not comments**.

**Action (senior revision):**
- Implement the guard as a **real call/import check** — e.g. AST-walk `matcher.py` for `Call`/`Attribute` nodes named `promote_hypothesis` / `append`, and for a `verified_knowledge` INSERT; or assert `matcher.py` does not import `promotion`/`promote_hypothesis` and contains no `verified_knowledge` DML in code (not comments).
- **At minimum**, strip comments/docstrings before any substring scan, and state in ADR-017/plan that the orthogonality docstring is intentional and must survive the guard.
- This makes the guard a genuine structural guarantee (cleaner than the existing substring constitutional test), without re-introducing the RC-23 fragility. (Widening the audit to the existing substring scans is captured as a retro candidate — RC-24 — not bundled into this product slice.)

### G2 → α-small — inscribe `normalize_tag` idempotency as a required property

**Finding (R0-B green, cross-family structural contribution):** the matcher's normalize-at-read (D2) re-normalizes already-canonical stored tags, which is safe only because `normalize_tag(normalize_tag(x)) == normalize_tag(x)` (idempotent). The property holds today (the output has no leading/trailing whitespace, is all-lowercase, has no whitespace runs) and is P2.1-tested, but it is **not named** as a required invariant. A future `normalize_tag` amendment (ADR-018's own "richer normalization" forward hook — punctuation/Unicode/stemming) could break idempotency and silently diverge the matcher's group key from the registry's stored canonical — a cross-slice invariant with no explicit guardrail.

**Why α-small (take it, but not Accept-blocking):** the property is already true and tested, so this is documentation/forcing-function hygiene, not a correctness fix. But it's the cross-family lens doing exactly its job — "what must hold for this reuse to stay correct under future amendment?" — and a one-sentence inscription is cheap insurance against a future silent cross-slice break.

**Action (senior revision):**
- ADR-017 D2: add one sentence inscribing the dependency — e.g. *"normalize-at-read is safe because `normalize_tag` is idempotent (`normalize_tag(normalize_tag(x)) == normalize_tag(x)`); a future `normalize_tag` amendment must preserve idempotency or the matcher's group key diverges from the registry's stored canonical."*
- ADR-018 D3: a cross-reference note that idempotency is a load-bearing property consumed by ADR-017's normalize-at-read (so a future D3 amendment sees the downstream dependency). **Note:** ADR-018 is closed/accepted — adding a cross-ref note is a light touch; heed RC-23 (do not introduce a literal `Status: …` substring near its status region; this is a body-note only, well away from the status line). If the architect prefers not to touch a closed ADR at all, the ADR-017 D2 sentence alone suffices and the ADR-018 note can be dropped — architect-partner flags this as the one judgment call inside G2.

## Non-routing fold-ins (affirmations — no α/β/γ)

Optional test-clarity note from R0-A G4 (senior may fold): the determinism test (P2.2-4 AC#5) shuffles *record* order as a proxy for scan-order independence — state that intent explicitly so the test's purpose is unambiguous.

## RC-24 (surfaced, not decided) — RC-23 widening

B is the **third** whole-file-substring-scan instance in the harness (RC-23 `_parse_adr_status`; the `test_constitution.py` pattern B is modeled on; the new guard B would have introduced). Captured as a retro candidate (`docs/retrospectives/P2.2-candidates.md`, RC-24) to consider widening RC-23 from "fix `_parse_adr_status`" to "audit whole-file substring scans across the harness." **Surface only — not a routing decision this cycle; not bundled into P2.2's product scope** (dev-harness; architect-deferral literal-reading).

## Net

- **3 routed actions:** A → α (untagged-tagset test), B → α (AST/import orthogonality guard), G2 → α-small (idempotency inscription).
- **0 `src/` design changes** — A/B are test-approach, G2 is ADR documentation.
- **0 🔴; design sound on every invariant both lenses traced.** After the revision lands + verdicts bump, architect accepts ADR-017 (honest gate) → `awaiting_junior_impl`.

State: per ADR-008, this routing moves P2.2 to senior-revision territory; senior absorbs A/B/G2 on `claude/P2.2-matcher-plan`, bumps verdicts, then architect accepts ADR-017.
