---
task_id: P6.2
stage: architect-routing-on-impl
cycle: 1
actor: architect
date: "2026-06-11"
routing: alpha-bundle
disposition:
  R0B-D1-1-duplication: alpha-factor
  R0A-Y1-ruff-format: alpha-fix-now
  R0B-D1-2-eager-healthcheck: accept-as-noted
  R0B-D1-3-trace-discarded: accept-as-noted
  R0A-O1-format-drift: separate-follow-on    # task #108
inputs:
  - docs/process/reviews/P6.2/plan-vs-impl.md   # senior, clean
  - docs/process/reviews/P6.2/R0-A.md           # arch-partner, needs_architect (Y1 + O1)
  - docs/process/reviews/P6.2/R0-B.md           # r0b cross-family, needs_architect (D1-1/D1-2/D1-3)
---

# P6.2 impl-stage routing — α bundle, one rework cycle (cycle 2)

C1 + D1 are **correct, in-scope, and empirically fail-on-revert** (R0-A + R0-B + plan-vs-impl all
confirm); 0🔴; gates green except the format items below; spine zero-diff, no new `LLMPurpose`; the
fallback-audit invariant (`model_id_requested(head) != model_id_used(fallback)`), no-double-actuation,
all-transient→`NoSuitableModelError`, and `select_model_and_provider` back-compat all hold.

| # | Sev | Source | Routing | Action |
|---|---|---|---|---|
| **R0B-D1-1** duplication | 🟡 | r0b | **α factor (this cycle)** | Factor the ~140 lines of per-candidate filter logic shared by `select_model_and_provider` and `select_viable_routes` into a private helper (e.g. `_evaluate_candidates(chain, …)`) used by both — or have `select_model_and_provider` delegate to `select_viable_routes(...)[0]`. The plan authorized either; do it now rather than ship verbatim duplication (a filter fix in one would silently miss the other). Keep the existing tests green; the factoring is behavior-preserving. |
| **R0A-Y1** ruff-format | 🟡 | R0-A | **α fix-now** | `ruff format tests/llm/test_openai_compatible_provider.py` (the C1 test file — 3 lines collapse under the lockfile-pinned ruff 0.15.12) + recommit on the impl branch. Format-only, zero behavior change; keep the slice net-neutral on format cleanliness. |
| **R0B-D1-2** eager health_check | 🟡 | r0b | **accept-as-noted** | D-mech-A consciously chose eager health-check of the chain; `health_check()` is a cheap in-memory/subprocess-alive boolean, so the O(N) cost is negligible. Accepted as the ratified mechanism. (If a future `health_check()` becomes an expensive network probe, revisit — note in the D1 docstring.) |
| **R0B-D1-3** trace discarded on fallback | 🟡 | r0b | **accept-as-noted** | The plan scoped enriching the non-exhaustion trace out. `LLMResponse` carries both ids (fallback is detectable); the *reason* (rate-limit/timeout/5xx) is not yet in the audit log. Accepted gap; a `fallback_reason` field is a future observability cycle, not P6.2. |
| **R0A-O1** 51-file format drift | 📋 | R0-A | **separate follow-on** | Pre-existing (P4/P5), **not P6.2** — `main` is `ruff format`-dirty under the bumped-but-not-reformatted ruff 0.15.12. Tracked as **task #108** (a dedicated `ruff format .` hygiene slice, like the #95 prettier follow-on). Not bundled into P6.2. |

cycle-2 = D1-1 factor + Y1 reformat, both on `claude/P6.2-impl`. No spine change, no ADR change, no new
`LLMPurpose`. The factored helper must keep all D1 + back-compat tests green. After cycle-2 clears →
merge → P6.2 closes. RC-3: architect routed; senior/junior do not self-route.
