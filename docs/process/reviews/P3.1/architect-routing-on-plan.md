---
task_id: P3.1
kind: architect-routing
stage: plan
date: 2026-06-02
reviews_acked:
  - R0-A-on-plan.md   # single-lens (dual-lens R0-B skipped, architect-ruled — low-risk content)
joint_verdict: needs_architect (R0-A 0🔴/1🟡/11🟢; single-lens) → one α-fold, rest clean
decisions:
  Y1: α-fold (senior adds the NET per-(room,state) activation spec to the plan + e2e asserts the net activation + verify no unintended over-activation from inherited triggers)
---

# P3.1 architect routing — plan stage (Y1 → α-fold; rest clean)

**Architect decision (this session):** the plan is **clean** but for one low precision point. The constitutional split is preserved, the 2b backward-compat design is verified safe (scaffold-state-name uniqueness), ADR-024 is RC-23-safe, no new `LLMPurpose`. **Y1 → α-fold** (the senior folds it into the plan during revision — no ADR change, no design change).

This is the **signal artifact for the senior revision session.** Senior reads this + `R0-A-on-plan.md` + the current plan, folds Y1 into plan §2b + §P3.1-2, and bumps the R0-A verdict per RC-10. Then the architect accepts ADR-024.

## Per-finding routing

### Y1 → α-fold — specify + test the NET per-(room, state) activation

**Finding (R0-A Y1, low):** the plan §2b matrix specifies the *new* `state_change`-trigger layer, but the reused agents' **existing** triggers (skeptic's regex + `hypothesis`; operator's `user_input` + `hypothesis`; prober/divergence_mapper's own) **also fire** in the scaffold rooms now that those agents are in-roster + `applies_to`-covered. The plan calls them "additive" (acknowledged) but doesn't enumerate the **net** activation, and the e2e's "speak=True for *exactly* the matrix agents per state" can be confounded (e.g. `bug_fix → diagnosed` is a `HYPOTHESIS` event, on which skeptic's existing `hypothesis` trigger also fires alongside its new `state_change→diagnosed`).

**Action (senior absorb — plan only, no ADR/design change):**
- **Add a NET per-(room, state) activation spec** to plan §2b — for each scaffold room × state, list which agent(s) speak and via **which** trigger (the existing regex/`hypothesis`/`user_input` triggers **and** the new `state_change` triggers). The §2b matrix becomes the *net* picture, not just the state_change layer.
- **e2e asserts the net activation** (plan §P3.1-2) — `should_agent_speak` returns `True` for **exactly** the net set per state (existing + state_change triggers), `False` for the others — discriminating over the full picture (RC-25), not just the state_change layer.
- **Verify no unintended over-activation** from inherited Research-era triggers in scaffold rooms — e.g. confirm skeptic-on-`hypothesis` is intended in `bug_fix`; check whether skeptic/operator's existing triggers fire sensibly (or noisily) in `code_review` (which has no `HYPOTHESIS` arc). Specify-don't-assume; if an inherited trigger is unwanted in a scaffold room, the senior pins the fix (the per-state spec makes any over-activation visible).

No ADR-024 change (Y1 is about the *reused* agents' net activation, not the facilitator — which is clean). No new infra. Folds into the plan's §2b table + the §P3.1-2 e2e.

## The rest — clean (no action)

R0-A's other 11🟢 stand: rosters match the ruling; the 2b backward-compat design is **verified safe** (scaffold state names unique vs Research's `setup/exploration/divergence/convergence/snapshot_pending/closed`); facilitator preserves the code-activation/LLM-content split (ADR-024 D2) with no new `LLMPurpose`; ADR-024 RC-23-safe; `templates.py` pure data; Q1–Q5; the backward-compat test sweep + the logger→closed deferral are sound. The scope-clarity note (stub personas now; fleshed personas = P3.7 content) is recorded — not a finding.

## Senior absorb scope (literal-reading)

The single edit is the **net-activation spec in plan §2b + the e2e in §P3.1-2** (assert the net, verify no over-activation). No ADR-024 change; no design change; no new infra. Bump the R0-A verdict per RC-10. Then the architect accepts ADR-024 → P3.1 impl. (Stub-persona depth + new skills stay deferred to P3.7 — architect-deferral literal-reading.)
