---
task_id: P5.1b
stage: architect-routing-on-impl
cycle: 1
actor: architect
date: "2026-06-09"
routing: all-alpha
disposition:
  A1-PVI1-IDOR: alpha          # must-fix
  A2-Y1-docstring: alpha
  A3-Y2-PVI3-orphan-logloop: alpha
  Y3-audit-gap: alpha          # split try (fix, not accept-as-noted)
  A4-ast-test-coverage: alpha
  A5-PVI4-get-verb-404: alpha
  A6-PVI2-partial-index: alpha # already in-spirit/additive — confirm, no behavioural change
rework_to: junior (cycle 2)
pr: 68
inputs:
  - docs/process/reviews/P5.1b/plan-vs-impl.md   # senior, needs_architect (PVI-1 + 🟢 PVI-2/3/4)
  - docs/process/reviews/P5.1b/R0-A.md           # arch-partner, needs_architect (A1 must-fix + A2/A3 🟡 + A4/A5/A6 🟢)
  - docs/process/reviews/P5.1b/R0-B.md           # r0b cross-family, needs_architect (Y1/Y2/Y3 🟡)
---

# P5.1b impl-stage routing — **all-α, one rework cycle (cycle 2)**

Three impl reviews returned `needs_architect`; **gates green** (ruff + mypy 304 + pytest 2418),
**spine byte-frozen** (independently confirmed by R0-A *and* R0-B — `_countdown_sweeper` /
`_writer_approve_helper` / gate / `_execute_local_call` / `run_pipeline` all zero-diff), no new
`LLMPurpose`, RB-PIPELINE-SCHED faithfully implemented, cron correctly deferred, opt-in default-OFF.
The impl is **constitutionally clean**; the findings are an authz-correctness must-fix plus a cluster
of robustness/honesty edges. Architect routes **α on every finding** (incl. the 🟢 A5/A6) — one junior
rework cycle on the existing branch `claude/P5.1b-impl` (**PR #68**, already open; pushing updates it).

## Dual-lens note

A1 (the material finding) was caught by **senior + R0-A (2-of-3); r0b missed it** (its lens was
runtime/failure-mode) — the independent confirmation raises confidence. Symmetric to P5.1a where R0-A
caught what r0b missed: weight the corroborated authz finding and fix it before merge.

## Per-finding disposition (all α)

| # | Sev | Source | Fix |
|---|---|---|---|
| **A1 / PVI-1** | 🟡 **must-fix** | senior + R0-A (r0b missed) | Cross-pipeline IDOR on DELETE/PATCH: add `if sched.pipeline_id != pipeline_id: raise HTTPException(404)` in **both** `_delete_schedule` and `_patch_schedule` (after the `get_schedule` fetch), so the mutation is bound to the schedule's **actual parent**, not the URL pipeline. Add a **cross-pipeline 404 test** (owner of `P_self` gets 404 on `…/pipelines/{P_self}/schedules/{S_other}`) for both verbs. |
| A2 / Y1 | 🟡 | r0b + R0-A | Fix the `_schedule_act_on_writer` docstring to match the code: "skip if pipeline **missing** (no advance); skip run if pipeline **disabled** (advance `next_fire` so re-enable resumes cleanly)." |
| A3 / Y2 / PVI-3 | 🟡 | all 3 | Orphan-schedule warn-log loop: **advance `next_fire` even on the missing-pipeline path** (consistent with the disabled-pipeline path), so a deleted-pipeline schedule is re-discovered only after the next interval, not every tick. Add a test asserting `next_fire` advances on missing-pipeline. |
| Y3 | 🟡 | r0b | Audit gap: **split the try** — `run_pipeline` in one try; `create_pipeline_run` in a nested try/except that logs but does not lose the successful run. (Fix, not accept-as-noted.) Test the create-fails-after-run path if cheaply mockable. |
| A4 | 🟢→α | R0-A (novel) | Extend the spine-isolation AST/grep test to also cover **`_schedule_act_on_writer`** (the higher-risk act fn), not just `_schedule_sweeper` — asserts it imports/calls none of the countdown-actuation spine. |
| A5 / PVI-4 | 🟢→α | senior + R0-A | Verb consistency: make **GET on a missing pipeline return 404** (like POST/DELETE/PATCH), instead of `[]`. |
| A6 / PVI-2 | 🟢→α | senior + R0-A | The partial index `idx_pipeline_schedules_due` already realizes the ADR-042 D2 "indexable" intent — **additive, in-spirit; confirm/keep, no behavioural change** (the α here is "ratified as correct," nothing to rewrite). |

No product-code change to the spine, no new `LLMPurpose`, no ADR-042 amendment (the fixes are within
the inscribed contract; A3's advance-on-missing matches ADR-042 D4's re-arm intent). Senior did not
self-accept the ADR (RC-3); architect routed (no role re-routed a finding).
