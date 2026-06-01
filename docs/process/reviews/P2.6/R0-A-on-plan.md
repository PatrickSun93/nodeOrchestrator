---
task_id: P2.6
round: R0-A-on-plan
verdict: needs_architect
findings_count:
  red: 0
  yellow: 2
  green: 10
verdict_history:
  - verdict: needs_architect
    at_commit: 25d7cb3
    findings_count: { red: 0, yellow: 2, green: 10 }
    note: initial R0-A-on-plan (in-family). The c1/c2 boundary *chains* are conceptually clean + the parallel structure is genuinely disjoint (verified incl. the memory/__init__ non-coupling). Y1 (architect-relevant) — c1/c2 are enforced by helper + code-review + import-guard but lack a structural AST guard against in-package bypass, vs the matcher/validation/reentry precedent. Y2 low. Nothing blocking.
---

# P2.6 R0-A on plan (architect-dispatched pre-impl review, in-family)

| Field | Value |
|---|---|
| Round | R0-A-on-plan (architect-dispatched per RC-9; in-family) |
| Artifacts | `senior-plans/P2.6.md` + `ADR-022-promotion-rule-producers.md` (Proposed) vs `origin/main` substrate + brief P2.6 |
| ADR status | ADR-022 left **Proposed** — this review informs accept; I did not accept (architect-only). |
| Cross-family | `requires_cross_family_review: true` — r0b R0-B runs after me on the shared tree; I leave it clean. |

## Verdict: needs_architect

**The plan is strong and the constitutional boundary *chains* are conceptually clean.** c1: the LLM tags one hypothesis at a time (descriptive content-gen) → deterministic `resolve_tags` → `run_matcher`'s deterministic grouping → advisory `candidate_for_promotion` → rule-b user-confirm — and because the producer tags *per-hypothesis*, the LLM structurally cannot do cross-hypothesis selection. c2: the verdict is `evidence_ref`-anchored (the emit helper raises on empty), the demo connector is deterministic (no LLM), and append goes through `EventStore.append`. I verified the key substrate claim — `ExternalValidationMeta.evidence_ref` is `str | None` and existing tests rely on that (`test_schema.py:631`), so the ADR's connector-contract-not-schema enforcement is correctly reasoned. The parallel structure is **genuinely disjoint** (incl. a hidden-coupling check that came back clean — see below).

**Two 🟡, one architect-relevant (Y1).** Y1 — c1 **and** c2 are enforced by a helper + code-review + the import-direction guard, but **neither has a structural guard against in-package bypass** (a producer also calling `run_matcher`/`promote_hypothesis`; a connector constructing `ExternalValidationMeta` directly, skipping the `evidence_ref` check) — which is exactly the class the matcher/validation (P2.2/P2.3) + reentry (P2.5 Y1→α) precedent guards structurally. Y2 (low) — `update_hypothesis_tags` overwrite-vs-merge is unspecified. Nothing blocking.

## The five named checks

| # | Check | Verdict | Evidence |
|---|---|---|---|
| 1 | c1: LLM emits only descriptive tags (content-gen), never select/rank/gate; new `LLMPurpose` content-gen; the tags→`resolve_tags`→`run_matcher`→advisory→rule-b chain has no LLM overreach | **chain clean (G1); Y1 (guard)** | `propose_hypothesis_tags` is per-hypothesis content-gen (`HYPOTHESIS_TAG_PROPOSAL`, ADR-022 D3/D6); verified `purposes.py` has **no routing/judgment** purpose (8 values, all content-gen/candidate/proposal) and the new one fits. Per-hypothesis tagging structurally prevents cross-hypothesis selection. **Y1: no guard that `producers/` references no `run_matcher`/`promote_hypothesis`.** |
| 2 | c2: connector verdict `evidence_ref`-anchored (required+non-empty+external); `EventStore.append` not raw-INSERT; LLM-if-used interprets evidence not the bare hypothesis | **chain clean (G2); Y1 (guard)** | `emit_external_validation` raises on empty `evidence_ref` (ADR-022 D4); verified `evidence_ref: str\|None` (event.py:340) → connector-contract enforcement is correct (schema-tighten would break ADR-019's `assert evidence_ref is None` tests); demo connector deterministic (no LLM); append-only + fail-loud canary. **Y1: no guard that `connectors/` go through the emit helper (vs constructing `ExternalValidationMeta` directly with empty `evidence_ref` — the schema allows it; ADR Consequences-negative acknowledges it).** |
| 3 | parallel structure: B1/B2/B3 files disjoint; prelude packs all `llm/purposes.py` edits; no hidden coupling (B1 retro-update + B3 reader both in `memory/`) | **clean (G3)** | B1→`producers/tagging.py`+`memory/store.py`; B2→`connectors/*`; B3→`memory/validation.py`. The two `memory/` touches are **different files** (store vs validation). Prelude (P2.6-2) is the sole `purposes.py` edit. **Hidden-coupling check (verified): `memory/__init__.py` does NOT re-export `store`/`validation` (import-on-demand) — so B1+B3 don't co-edit `__init__`.** Genuinely parallel. |
| 4 | B3 advisory, no status mutation (ADR-019 push-back #4) | **clean (G4)** | `list_refuted_candidates` pure code, no LLM, **no status mutation** (ADR-022 D5); discriminating AC (assert status still PENDING; confirmed-only excluded). User-confirm reject actuator deferred (forward hook). |
| 5 | contributing Q1–Q5 | **clean (G5)** | Q1 (B1 tag-proposal content-gen; B2 demo deterministic — decisions code/human); Q2 N/A stated (producers feed deterministic rules; producer LLM is content-gen, not scored); Q3 5-surface; Q4 6-cat at PR; Q5 discriminating per block (tags→matcher-flips, evidence_ref-empty-raises, status-unchanged). |

## Findings

### Y1 🟡 — c1 + c2 boundaries lack a structural guard against in-package bypass (architect-relevant; P2.4/P2.5 precedent)

The two boundary *chains* are conceptually correct, but their *structural enforcement* relies on a helper + code-review + the import-direction guard — not a guard against bypass **inside** `producers/`/`connectors/`:

- **c1:** nothing structurally prevents `producers/tagging.py` (or a future `producers/` module) from **also** calling `run_matcher` / `promote_hypothesis` / flipping `candidate_for_promotion` — i.e., the producer reaching past tag-proposal into selection/promotion. The senior **considered** an AST guard (P2.6-3 AC#3) and declined it, but the cited reason — *"the producer legitimately calls the LLM for content-gen, so an LLM-free guard doesn't fit"* — answers the wrong question: the risk isn't legit-LLM-use, it's the producer **actuating promotion**, which is exactly what the matcher/validation guards forbid (a module that proposes must not actuate).
- **c2:** nothing structurally forces `connectors/` to go **through** `emit_external_validation`. A connector that constructs `ExternalValidationMeta(...)` directly (with `evidence_ref=None`/empty — the schema allows it, verified) and appends would produce an **ungrounded** verdict, bypassing the required-check. The ADR acknowledges this (Consequences-negative: "connector-contract-enforced, not schema-enforced; a future raw constructor could omit it"); the fail-loud canary catches raw-INSERT but **not** a correctly-appended event with empty `evidence_ref`.

**The precedent cuts toward a guard.** The project guards exactly this class structurally: matcher/validation (P2.2/P2.3 — "advisory must not promote/append") and reentry (P2.5 Y1→α — "selection must be LLM-free", routed α by you). The c1/c2 boundaries are the *reason this slice exists*; relying on code-review for them is lighter than the established bar.

**Lean (surface, not decide):** **α** — add two lightweight AST guards (mirror the matcher/validation/reentry idiom): (i) `producers/` references no `run_matcher`/`promote_hypothesis`/`candidate_for_promotion`-write; (ii) `connectors/` construct no `ExternalValidationMeta` directly (the emit helper is the sole construction site) — so empty-`evidence_ref` is unreachable. **Or β** — accept helper+review+import-guard for this slice (low residual risk: the demo connector is deterministic, and the LLM-connector + schema-tightening are forward hooks anyway). **Architect: α (structural guards now, consistent with P2.4/P2.5) / β (accept + document the bypass as a known limitation, like P2.5's render-output seam) / γ (drop)?**

### Y2 🟡 (low) — `update_hypothesis_tags` overwrite-vs-merge unspecified

B1's new `memory/store.py::update_hypothesis_tags` (the retro-tag path that actually feeds the dormant untagged rows) doesn't specify whether re-tagging an *already-tagged* hypothesis **overwrites** or **merges** `topic_tags`. Moot for the dormant-untagged case the e2e tests (untagged→tagged), but a real semantic for re-tagging. **Lean:** α — junior pins it (overwrite is the simplest, matches "update the row's tags"); add a discriminating test if re-tagging is in scope. Low; senior/junior-absorbable.

## What holds — verified clean (G1–G10)

- **G1 — c1 chain clean:** per-hypothesis descriptive tagging → `resolve_tags` → `run_matcher` grouping → advisory candidacy → rule-b user-confirm; the per-hypothesis scope structurally blocks cross-hypothesis selection; `HYPOTHESIS_TAG_PROPOSAL` is content-gen.
- **G2 — c2 chain clean:** `evidence_ref`-anchored emit helper (raises on empty); verified `evidence_ref: str\|None` so the connector-contract enforcement is correctly reasoned (schema-tighten would break ADR-019 tests); deterministic demo connector; `EventStore.append`-only + fail-loud canary.
- **G3 — parallel structure genuinely disjoint:** B1/B2/B3 touch disjoint files (the two `memory/` touches are different files); prelude resolves the sole shared file; **verified `memory/__init__` doesn't re-export `store`/`validation`** so B1/B3 don't co-edit it (the hidden-coupling concern came back clean — confirm the junior keeps import-on-demand, not adding the new fns to `__init__`).
- **G4 — B3 advisory, no status mutation** (ADR-019 push-back #4 honored; reject actuator deferred).
- **G5 — Q1–Q5 addressed** (Q2 N/A stated; Q5 discriminating per block).
- **G6 — `LLMPurpose` clean:** no routing/judgment value; exactly one content-gen added (`HYPOTHESIS_TAG_PROPOSAL`); the deterministic demo connector adds none.
- **G7 — `EventStore.append`-only** + the `validation.py` fail-loud canary respected (the emit helper is the single append path).
- **G8 — import guard** covers all four upstream layers (`core/memory/derived/llm`) for **both** `producers/` and `connectors/` (mirrors the reentry guard; discriminating self-test planned).
- **G9 — ADR shape sound:** one ADR-022, no closed-ADR edit; B3 additive (not an ADR-019 amendment); RC-23-safe.
- **G10 — the architect rulings faithfully implemented:** (a) one-slice parallel-atomics, (b) dual-lens dispatched, (c1) descriptive-content-gen tagging, (c2) `evidence_ref`-anchored verdict, B3 no-status-mutation — all recorded in §5 + carried by ADR-022.

## What I did NOT do

- Did not accept ADR-022 (architect-only).
- Did not decide Y1 — surfaced with a lean (α structural guards / β accept+document / γ) for you to route; it's the structural-enforcement-strength call for the two boundaries the slice turns on.
- Did not touch the tree beyond this review file (r0b R0-B runs next on the shared tree).
