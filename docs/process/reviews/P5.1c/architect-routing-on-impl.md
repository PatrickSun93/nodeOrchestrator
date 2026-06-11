---
task_id: P5.1c
stage: architect-routing-on-impl
cycle: 1
actor: architect
date: "2026-06-10"
routing: all-alpha
disposition:
  Y1-typed-meta-not-registered: alpha-doc      # amend ADR-043 D6 text (no code change)
  Y2-live-gate-both-non-empty: alpha
  Y3-live-branch-fail-open: alpha
  cross-pipeline-idor-test: alpha              # the plan-vs-impl 🟢 — add it (P5.1b A1 lesson)
  R0B-Y2-codegen-overshoot: accept-hygiene
inputs:
  - docs/process/reviews/P5.1c/plan-vs-impl.md   # senior, needs_architect (PvI-Y1 + 🟢)
  - docs/process/reviews/P5.1c/R0-A.md           # arch-partner, needs_architect (Y1 + Y2 + Y3)
  - docs/process/reviews/P5.1c/R0-B.md           # r0b cross-family, needs_architect (Y1 + Y2-codegen)
---

# P5.1c impl-stage routing — **all-α, one rework cycle (cycle 2)**

Three impl reviews `needs_architect`; **0🔴, gates green** (ruff + mypy --strict 305 + pytest exit 0),
**byte-frozen set zero-diff** (gate / `_execute_local_call` / COUNTDOWN spine / `run_pipeline`
`countdown_auto_fire=None` / the existing `human`+`auto_timer` callers — all confirmed by R0-A and R0-B),
no new routing `LLMPurpose`. The crossing's bounds (`send_email`-only literal allowlist + the HARD-never
constitutional test, owner-config-pinned recipient, 3-state opt-in default-OFF + dry-run-first, the
honestly-rewritten D1 isolation test) are all faithful. The findings are ADR-text fidelity + two small
fail-closed tightenings + a missing test — all α.

## Per-finding disposition

| # | Sev | Source | Routing | Fix |
|---|---|---|---|---|
| **Y1 TYPED_METADATA** | 🟡 | all 3 (PvI-Y1 / R0A-Y1 / R0B-Y1) | **α (doc-only)** | The impl is **correct** — `PipelineEmailDryRunMeta` is enforced at the callsite via `model_validate()`; registering `EventType.OBSERVATION → PipelineEmailDryRunMeta` in `TYPED_METADATA` would break every *other* free-form `OBSERVATION` event (runner output, MCP interpret). The **ADR-043 D6 text is infeasible-as-written.** Amend ADR-043 D6 to describe the **callsite-typed-enforcement pattern** + the shared-`OBSERVATION`-conflict rationale (the junior's code comment already cites D6 — make the ADR match the sound code). **No code change.** |
| **Y3 fail-open** | 🟡 | R0-A | **α** | The live branch is entered by negation (`email_mode != "dry_run"`) → **fail-OPEN on any unknown `email_mode`**, contra ADR-043 D5 ("live requires `email_mode` explicitly set"). Match **`== "live"` explicitly** so an unknown/garbage mode fails **closed** (no send). At the irreversible crossing, fail-closed-on-unknown is the only acceptable default. Add a test: an unknown `email_mode` does not actuate. |
| **Y2 both-non-empty** | 🟡 | R0-A | **α** | The live recipient-eligibility gate omits ADR-043 D3's "both non-empty" check that the dry-run path *does* apply — mirror the dry-run guard (pinned recipient and pending `to` both non-empty, then case-insensitive match) so the two paths cannot diverge. |
| 🟢→α **cross-pipeline IDOR test** | 🟢 | plan-vs-impl | **α** | The three new email endpoints (opt-in / promote / disable) have no cross-pipeline IDOR test (schedule-not-for-this-pipeline → 404). Add it — this is exactly the **P5.1b A1** cross-pipeline authorization gap; given the endpoints mutate the irreversible-email authorization state, the test is worth having now, not as a follow-on. (Confirm the endpoint code already binds `sched.pipeline_id == pipeline_id`; the gap flagged is the missing *test*, not necessarily the guard.) |
| R0B-Y2 codegen overshoot | 🟡 | R0-B | **accept (hygiene)** | The openapi/`ui-schema` codegen regenerated the whole `/pipelines` surface, not just the new email endpoints. **Zero runtime risk** (contract docs), and it matches the established P5.1b whole-app codegen-lock pattern. **Accept as-is**; no rework. (If a future slice can scope the codegen, fine — not P5.1c's job.) |

No spine change, no new `LLMPurpose`, no further ADR amendment beyond the Y1 D6 text fix. One junior rework
cycle on the existing branch `claude/P5.1c-impl`. After cycle-2 clears (R0-A + R0-B + plan-vs-impl), merge
→ closed — **P5.1 wave closes.** RC-3: architect routed; senior/junior do not self-route.
