---
task_id: P5.1c
stage: architect-routing-on-plan
actor: architect
date: "2026-06-10"
routing: all-alpha-absorb
disposition:
  R0A-Y1-d1-test-vacuous: alpha
  R0A-Y2-approval-source-fieldset: alpha
  R0A-Y3-signature-blast-radius: alpha
  R0B-Y1-recipient-case: case-insensitive
  R0B-Y2-dryrun-typed-meta: typed-meta
inputs:
  - docs/process/reviews/P5.1c/R0-A-on-plan.md   # arch-partner, needs_architect (Y1 headline + Y2/Y3 minor)
  - docs/process/reviews/P5.1c/R0-B-on-plan.md   # r0b cross-family, needs_architect (Y1 case + Y2 dry-run meta)
---

# P5.1c plan-stage routing — **all-α absorb into the plan, then Accept ADR-043**

Both plan-stage reviews: **design sound, faithful to ratified C0–C8, no 🔴.** R0-B-on-plan held against
all six architect concerns; R0-A-on-plan verified every seam faithful + the boundary guard structurally
tight. The findings are honesty-completeness + two edge decisions — all **α, absorbed by the senior before
junior dispatch.**

## Disposition (all α)

| # | Source | Routing | Senior absorption |
|---|---|---|---|
| **R0A-Y1** (headline) | arch-partner | **α** | The ADR-042 D1 isolation test (`test_schedule_act_on_writer_does_not_call_countdown_spine`) goes silently vacuous because the email actuator reaches `_writer_approve_helper` via the separate `_actuate_pipeline_emails` fn (the one-hop AST test keeps passing while the invariant it names is deliberately violated). At the honesty crux this is exactly the must-not-ship failure (P5.1b cyc3 theme). Revise the plan: **(P5.1c-5/-3)** rewrite the test honestly — **drop `_writer_approve_helper` from forbidden_calls** (now legitimately reachable, but *only* via the narrow `_actuate_pipeline_emails` email path), **keep `_countdown_sweeper` + `_discover_expired_pendings` forbidden** (COUNTDOWN spine untouched — Lens B), and add a **positive pin** that the sole new actuation reach is `_actuate_pipeline_emails`; **(P5.1c-3)** fix the `app.py:618-619` docstring to state the crossing truthfully; **(P5.1c-6)** the ADR-042 amendment text must **explicitly name** that D1's "never calls `_writer_approve_helper`" isolation is **deliberately lifted for the email actuator** (not silently bypassed). |
| **R0A-Y2** (minor) | arch-partner | **α** | The `approval_source` change is value-set, not field-set. `test_constitution.py:281-287` pins `ToolCallMeta` to exactly five field **names** — P5.1c adds no field, only widens the Literal value set. The field-set pin stays **byte-unchanged**. Reword P5.1c-3/-5: the only production change is the two type annotations (`event.py:224`, `app.py:383`); the new `auto_pipeline` value is exercised by the P5.1c-3 actuator tests. |
| **R0A-Y3** (minor) | arch-partner | **α** | Threading `loop` into `_schedule_act_on_writer` breaks **6** existing positional call-sites in `test_schedule_sweeper.py` (`:273,301,328,333,385,428`). Either enumerate them in the blast-radius list **or make `loop` a keyword param** (preferred — existing dry-run/`email_enabled=0` call-sites need no change). |
| **R0B-Y1** | r0b | **case-insensitive** | Recipient-pin comparison is **case-insensitive**: lowercase both the pinned recipient and the pending `to` before matching (RFC 5321 / practical email semantics), so `Alice@corp.com` vs `alice@corp.com` does not silently fail-closed after promote-to-live. Update ADR-043 D3 text "exact match" → "case-insensitive match (both sides lowercased)". |
| **R0B-Y2** | r0b | **typed-meta** | The dry-run preview record is the owner's load-bearing promote-to-live evidence — give it a **typed metadata class** `PipelineEmailDryRunMeta` (recipient, subject, would_actuate, owner_user_id, approval_source) registered in `TYPED_METADATA`, structurally enforced rather than convention. **Reuse the existing `OBSERVATION` event type** (no new EventType — that part of the scope-narrowing stands); only the metadata gains a schema. Update ADR-043 D6 to specify the typed record. |

No design change — the crossing (C1a reuse-helper, C2b config-pinned recipient, C3 single-tool guard, C5 dry-run-first) is ratified and faithful. This is honesty-completeness + two edge tightenings. After the senior absorbs (RC-10) the architect Accepts ADR-043 (RC-3: senior does not self-accept). No impl branch yet — absorption is plan + ADR-043 edits on main.
