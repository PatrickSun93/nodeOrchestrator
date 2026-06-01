---
task_id: P2.6
kind: architect-routing
stage: plan
date: 2026-06-01
reviews_acked:
  - R0-A-on-plan.md
  - R0-B-cross-family.md
joint_verdict: needs_architect (R0-A 0🔴/2🟡/10🟢 + R0-B 0🔴/2🟡/6🟢; no present leak — both lenses confirm the c1/c2 boundary chains are code-enforced; the routed items are guard-strength)
decisions:
  c2: α (structural AST guard — ExternalValidationMeta constructable only in connectors/_emit.py(+tests); keep schema evidence_ref str|None; schema-tighten = forward hook; no closed-ADR-019 edit)
  c1: α-lite (symmetric belt-and-suspenders — lightweight AST guard that the tagging producer does no selection/rank/gate; mirror the reentry/preference idiom; c1 is already fail-safe)
  Y2: senior design fork (update_hypothesis_tags overwrite-vs-merge — NOT an architect ruling; lean overwrite)
---

# P2.6 architect routing — plan stage (c2 → α, c1 → α-lite; Y2 = senior fork)

**Architect decision (this session):** joint verdict **needs_architect**; **no present constitutional leak** — both lenses confirmed the c1/c2 boundary *chains* are code-enforced (content-gen → deterministic code → advisory → user-confirm; verdict `evidence_ref`-anchored, deterministic demo connector). The routed items are **enforcement-strength** (structural guards against future bypass), consistent with the P2.4 Principle-11 / P2.5 reentry / matcher-validation AST-guard pattern. Both → **α**; Y2 is the senior's design call.

This file is the **signal artifact for the senior revision session.** Senior picks P2.6, reads this + `R0-A-on-plan.md` + `R0-B-cross-family.md` + the current plan + ADR-022, adds the two guard specs (and resolves Y2), and bumps the review verdicts per RC-10. Then the architect accepts ADR-022.

## Per-finding routing

### c2 → α — structural AST guard for the evidence-grounding boundary (the convergent finding)

**Convergence:** R0-A Y1(c2-part) + R0-B Y1 + R0-B Y2 are **one finding hit by both lenses** — c2's evidence-grounding is opt-in via the `emit_external_validation` helper, but `ExternalValidationMeta.evidence_ref` is `str|None` (verified `event.py:340`), so a future connector constructing `ExternalValidationMeta(…, evidence_ref=None)` directly + appending via `EventStore.append` produces an **ungrounded durable verdict** that passes `validate_metadata`, the fail-loud canary (checks `verdict`, not `evidence_ref`), and the import guard — and rule-c surfaces it. Inconsistent with the project's structural-enforcement pattern.

**Action (senior absorb):**
- Add a **structural AST guard** (real AST, RC-24 idiom; mirror `tests/reentry/test_constitution.py` / the `EntityType.PREFERENCE` guard): **`ExternalValidationMeta(` is constructed only in `connectors/_emit.py`** (+ test files). This makes the emit helper the **sole construction site** → its `evidence_ref` required+non-empty check becomes **unbypassable**.
- **Keep the schema `evidence_ref: str|None`** — do **not** touch the closed ADR-019 / `core/event.py` (it would break ADR-019's `assert evidence_ref is None` tests). Schema-level tightening stays a **forward hook** (ADR-022 Consequences).
- Reflect the guard in ADR-022 D4 + the relevant atomic's acceptance (P2.6-4) + the §4 forcing-functions.

### c1 → α-lite — symmetric belt-and-suspenders guard (the tagging producer does not select/gate)

**Context:** R0-B G1 showed c1 is already **structurally fail-safe** (per-hypothesis tagging can't force a grouping; `run_matcher` needs ≥2 independent rooms; candidacy is advisory; `promote_hypothesis` requires a `user_id` — a producer can't auto-promote). So this guard is **belt-and-suspenders, not load-bearing** — the architect chose the symmetric option for consistency with c2 + the reentry/preference precedent.

**Action (senior absorb):**
- Add a **lightweight AST guard** that the tagging producer (`producers/tagging.py` / `producers/`) **references no selection/promotion symbols** — e.g. `run_matcher` / `promote_hypothesis` / `list_promotion_candidates` / a `candidate_for_promotion` write — mirroring the matcher/validation "advisory must not actuate" + reentry "selection must be LLM-free" idiom. The producer **proposes descriptive tags only**; matching/candidacy/promotion stay downstream code/user.
- Reflect in ADR-022 D3 + P2.6-3 acceptance. (Senior picks the exact forbidden-symbol set + guard placement.)

### Y2 → senior design fork (not an architect ruling)

`update_hypothesis_tags` overwrite-vs-merge (re-tagging an already-tagged hypothesis) is an impl/design detail, not a constitutional boundary or cross-cutting contract — **the senior pins it** (architect-lean: **overwrite** — simplest, matches "update the row's tags"; moot for the dormant-untagged case the e2e exercises). No architect ruling needed; recorded for completeness.

## Constitutional note (no action — for the record)

Both lenses confirmed the c1/c2 boundary *chains* are code-enforced and **no LLM crosses into selection/judgment** in the planned design (R0-A G1/G2, R0-B G1/G6). The c2 bypass is a *reachable future* hole (the `str|None` schema) → the guard; c1's worst case is a declined advisory suggestion (fail-safe) → the guard is belt-and-suspenders. These are enforcement-strength, not a present leak. The LLM-interprets-evidence connector path (`EXTERNAL_EVIDENCE_INTERPRET`) + schema-level `evidence_ref` tightening remain forward hooks — do NOT bundle (architect-deferral literal-reading).

## Senior absorb scope (literal-reading)

Two guard specs land in ADR-022 (D3 c1, D4 c2) + the plan (P2.6-2/-3/-4 acceptance + §4 forcing-functions) + the constitution-test plan (the two new AST guards, with discriminating self-tests, mirroring the reentry idiom). Y2 is a one-line plan clarification (overwrite). **No `core/event.py` / ADR-019 edit** (schema stays `str|None`). No code (senior absorbs the plan/ADR; junior implements the guards in the impl cycle). The forward hooks (LLM connector, schema tightening, reject actuator, multi-source) stay deferred.
