---
task_id: P5.1b
stage: architect-routing-on-impl
cycle: 2
actor: architect
date: "2026-06-10"
routing: all-alpha
disposition:
  B1-vacuous-Y3-test: alpha
  B2-adr042-d4-text-sync: alpha
rework_to: junior (cycle 3)
pr: 68
inputs:
  - docs/process/reviews/P5.1b/plan-vs-impl.md   # senior cycle-2, clean
  - docs/process/reviews/P5.1b/R0-A.md           # arch-partner cycle-2, needs_architect (B1 + B2)
  - docs/process/reviews/P5.1b/R0-B.md           # r0b cross-family cycle-2, clean
---

# P5.1b cycle-2 routing — **α (close-out: fix the vacuous Y3 test + sync ADR-042 D4 text), cycle 3**

The all-α cycle-2 rework **resolved every cycle-1 finding** — A1 cross-pipeline IDOR (guard in both
verbs, **fail-on-revert empirically confirmed**), A2 docstring, A3 orphan-loop (advance-on-missing,
fail-on-revert confirmed), A4 AST coverage of `_schedule_act_on_writer`, A5 GET→404, A6 index. **plan-vs-impl
= clean, R0-B = clean** (r0b correctly re-reviewed the authz surface it missed in cycle-1). Gates green
(ruff + mypy 304 + pytest 2424). Spine + `run_pipeline` byte-frozen throughout. Only two close-out items
remain, both α:

| # | Sev | Fix |
|---|---|---|
| **B1** | 🟡 | The Y3 split-try is **correct in production**, but `test_act_create_run_fails_after_successful_run_does_not_raise` does **not fail-on-revert** (the cycle-1 single-try block still passes it). Rewrite the test so it **fails on the reverted single-try** and **passes on the split-try** — i.e. assert the run is not lost / the success path survives a `create_pipeline_run` failure in a way the single combined try could not satisfy. Same test-honesty close-out as P5.1a cyc3 (a guard that passes on both fixed and reverted code does not guard). |
| **B2** | 🟢→α | ADR-042 **D4 step-2 literal text** still reads "missing (deleted) → log + skip" (no advance), which now **contradicts the ratified advance-on-missing code** (A3). This is a code-vs-inscribed-text consistency gap, **not a decision change** — sync the one line of D4 text to "missing pipeline → log + **advance `next_fire`** + skip the run (breaks the orphan re-discovery loop; A3 routing)". |

No product-code change (the runner + endpoints are verified correct); spine stays byte-frozen; this is a
**test + ADR-text** cycle. After cycle-3 clears (R0-A + plan-vs-impl; R0-B already clean and the delta is
test/doc only — no product surface for cross-family to re-scrutinize), merge **PR #68** → closed.

RC-3: architect routed; senior/junior do not self-route.
