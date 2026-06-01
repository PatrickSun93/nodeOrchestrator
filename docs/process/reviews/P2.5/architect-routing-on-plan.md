---
task_id: P2.5
kind: architect-routing
stage: plan
date: 2026-06-01
reviews_acked:
  - R0-A-on-plan.md
  - R0-B-cross-family.md
joint_verdict: needs_architect (R0-A 0🔴/4🟡/9🟢 + R0-B 0🔴/1🟡/6🟢; all 4 findings → α-absorb)
decisions:
  Y1: α (leave-time archive summary's REAL LLM generation IS in P2.5 — new content-gen LLMPurpose; + fix derive_query_tags canonical location + re-scope the LLM-free-selection AST guard by named functions, not by file)
  Y2: α (extend the no-import-reentry guard to all upstream layers — derived/ + llm/, not just memory/+core/)
  Y3: α (new_since_leave first-visit rule = [] — dual-lens ≡ r0b Y1; pin fact-types + a typed descriptor)
  Y4: α (one-line Q2 decision_trace=N/A statement + Q4 6-category walk into the PR commit; hygiene)
---

# P2.5 architect routing — plan stage (all 4 findings → α)

**Architect decision (this session):** joint verdict **needs_architect**; all four plan-stage 🟡 resolve to **α (absorb)**. The constitutional core is confirmed — *both* lenses independently verified the selection/ranking/ordering boundary is code-enforced + AST-guarded (no LLM leak into the assembly path); the routed items are refinements, the design does not change.

This file is the **signal artifact for the senior absorb session.** Senior picks P2.5, reads this + `R0-A-on-plan.md` + `R0-B-cross-family.md` + the current plan + ADR-021, applies the four routed actions, and bumps the review verdicts per RC-10. Then the architect accepts ADR-021.

## Per-finding routing (all α)

### Y1 → α — leave-time summary is a real, in-scope second content-gen surface; fix the tangle

**Scope ruled:** the leave-time archive summary's **real LLM generation is IN P2.5** (not deferred to P2.6). The senior:
- **Adds a new content-gen `LLMPurpose`** (e.g. `ARCHIVE_SUMMARY_RENDER`) to **ADR-021 + `llm/purposes.py`** — this is the **second** content-gen surface, **distinct** from the re-entry `REENTRY_DIGEST_RENDER`. At leave-time, **genuinely generate** the archive's `one_line_summary` / `spinoff_questions` via this purpose (then `record_project_archive`). Do **not** reuse `REENTRY_DIGEST_RENDER` (the SNAPSHOT_SEMANTIC-style semantic mismatch the ADR itself warns against).
- **Fixes `derive_query_tags`' canonical location** (plan P2.5-3 `leave.py` vs ADR-D6/guard `digest.py` — pick one).
- **Re-scopes the LLM-free-selection AST guard by named selection *functions*** — `assemble_reentry` / `derive_query_tags` / the diff are LLM-free *wherever they live* — **not** a blanket "`digest.py` is LLM-free" (because `leave.py` now legitimately hosts the archive-summary content-gen call). The guard must still confine LLM use to the two render purposes and forbid it in the selection functions.

*Why this stays constitutional:* the LLM-free guard *is* the structural enforcement of "selection is code"; the second content-gen purpose keeps the leave-summary on a content-gen (not judgment) purpose. Both must land cleanly.

### Y2 → α — extend the dependency-direction guard to all upstream layers

The no-import-`reentry` AST guard must assert **`core/` + `memory/` + `derived/` + `llm/`** do not import `reentry/` (the consumer is downstream-only) — not just `memory/`+`core/` as the plan currently scopes it.

### Y3 → α — new_since_leave first-visit = [] (dual-lens; high-confidence)

**Both lenses** (R0-A Y3 ≡ R0-B Y1) independently hit the undefined "everything-or-empty per the rule." **Ruled: first visit → `new_since_leave = []`** ("new since you left" on a visit where the user never left is `[]`; the "what's here" is carried by the other digest fields; `[all facts]` would make the render prose misleading). Senior: pin this in **one sentence in ADR-021 D8** + the plan; **pin which fact-types** `new_since_leave` includes; and change it from `list[dict[str,Any]]` to a **typed descriptor** sub-model.

### Y4 → α — hygiene

Add a **one-line Q2 `decision_trace` = N/A** statement (the catch-up's selection is deterministic *composition* — fetch+filter+timestamp-diff — not a scored/ranked/gated decision; the trace is the query itself). The **Q4** 6-category walk goes in the PR commit ("Coverage standard compliance:").

## Non-routed — for awareness (no cycle action)

**r0b G2 (🟢, accepted seam):** the render's "phrasing-only" constraint is **prompt-enforced, not code-enforced** — the LLM could drop/reorder/omit facts in the prose (a de-facto selection the AST guard can't catch, since it protects the assembly path, not the render output). This is the **weakest link in the Principle-11 chain** — the only constitutional invariant enforced by an NL instruction. **Accepted for the MVP** (the deterministic `ReentryDigest` is the audited truth; the prose is a non-asserted UX layer; ADR-021 acknowledges it). Not routed; recorded as a **forward-hardening hook** (a future render-output validation that all digest facts appear in the prose) if the seam ever matters.

## Senior absorb scope (literal-reading)

Edits land in `senior-plans/P2.5.md` + `ADR-021` + `llm/purposes.py` (the new `LLMPurpose`) + the test-constitution guards (Y1 re-scope, Y2 coverage). Y3 is an ADR-D8 + schema change (typed descriptor). Y4 is a one-line plan note + a PR-time walk. All four are α-absorb this cycle — **no deferral**; architect-deferral literal-reading: the r0b-G2 render-output validation is the *only* deferred item (forward hook), do not bundle it.

## Note (filename convention)

This artifact uses `architect-routing-on-plan.md` (architect-specified) — prior plan-stage routings used the bare `architect-routing.md` (role-doc convention); `-on-plan` is symmetric with the impl-stage `-on-impl.md`. Both match the `architect-routing*.md` state-machine glob. Flagged for the architect to standardize the convention if desired.
