---
task_id: P6.7
stage: architect-routing-on-impl
cycle: 1
actor: architect (orchestrator, under the P6 bug-fix-backlog delegation)
date: "2026-06-14"
routing: alpha
disposition:
  Y1-cron-horizon-feb29: alpha   # bump the never-match horizon to cover the century-boundary 8-year Feb-29 gap
inputs:
  - docs/process/reviews/P6.7/plan-vs-impl.md   # senior, clean
  - docs/process/reviews/P6.7/R0-A.md           # arch-partner, needs_architect (Y1)
  - docs/process/reviews/P6.7/R0-B.md           # r0b cross-family, clean — independently CONFIRMS Y1
---

# P6.7 impl-stage routing — α (one-line horizon bump), one rework cycle

The cron evaluator is **correct, gate-green, spine-clean, no new dependency, faithful to the ratified
hand-rolled-subset contract** (plan-vs-impl clean; R0-A Lens A/B clean; R0-B 3🟢 cron-correctness). Both
reviewers converge on a single fix:

| # | Sev | Source | Fix |
|---|---|---|---|
| **Y1** never-match horizon | 🟡 | R0-A + R0-B (independently confirmed) | `_CRON_SEARCH_HORIZON_MIN` (~4y / 2.1M min) under-covers the **century-boundary 8-year Feb-29 gap** (1896→1904, 2096→2104 skip the non-leap 1900/2100 → consecutive Feb-29s are ~8y apart = 2× the current horizon). A legitimate `0 0 29 2 *` schedule with `after_ms` in the wrong half of an 8-year gap would incorrectly raise the fail-closed never-match error instead of matching. **α fix:** bump the horizon to `8 * 366 * 24 * 60` (covers the max Feb-29 gap; only doubles the bound). Update the constant's comment **and** the ADR-042 D3 text — both currently say "~4 years … covers Feb-29", which is now factually inaccurate. Add a test: a Feb-29-only cron across a century-boundary 8-year gap → matches (not never-match); and confirm a genuinely-unsatisfiable cron (e.g. `0 0 30 2 *`) still fail-closes within the new horizon. |

Latent impact (~2100 is 74y out) but the contract claim must be true. No spine/dependency change; ADR-042
D3 stays an in-place amendment (no Accept gate). cycle-2 on `claude/P6.7-impl`. After it clears → merge →
P6.7 closes.

(Routed by the orchestrator under the delegated bug-fix-backlog authority: a one-line correctness bump +
doc-accuracy fix, both reviewers agree, no spine/contract/dependency touch.)
