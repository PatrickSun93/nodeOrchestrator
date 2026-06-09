---
task_id: P5.1b
stage: architect-routing-on-plan
actor: architect
date: "2026-06-09"
inputs:
  - docs/process/reviews/P5.1b/R0-A-on-plan.md   # arch-partner, needs_architect (Y1 cron + Y2 endpoints)
  - docs/process/reviews/P5.1b/R0-B-on-plan.md   # r0b cross-family, clean
disposition:
  Y1-cron: interval-only-defer-cron     # option (c)
  Y2-endpoints: keep                    # ADR-042 D9 stays
  N3-room-growth: ack-deferred-gc       # one-line in ADR-042 Consequences
---

# P5.1b plan-stage routing

R0-B-on-plan **clean**. R0-A-on-plan **needs_architect** — plan + ADR-042 faithful to all
ratified B0–B6, seam correctly read, atomic split clean; the two open items were **decisions
outside the ratified surface that the senior correctly surfaced** (surface-don't-improvise held).
Architect routing:

## Y1 — cron-parser mechanism → **(c) interval-only, defer cron**

B2 named `kind ∈ {interval, cron}`, but *how* to evaluate cron was never in the decision surface.
Route **(c)**: P5.1b ships **interval-only**. The `kind` column stays (forward-compat); cron lands
in a focused follow-on with its own scrutiny.

**Why (c) over (a) hand-rolled / (b) croniter:** a hand-rolled cron evaluator is exactly the
greenfield-correctness class that P5.1a cyc1 shipped as the RSS billion-laughs hole — keep that
risk **out** of the scheduler dual-lens (which exists to scrutinize the *scheduler*, not a parser).
This mirrors B0's own discipline (defer incrementality to keep the slice tight). The scheduler crux
(sibling sweeper + persistence + re-arm + residual + opt-in) is fully exercisable with interval-only.
(a) was the strong runner-up and is defensible; (b) rejected (cuts against the 4-runtime-dep posture,
ADR-040 D1).

**Senior absorption (Y1):**
- **P5.1b-1** (`pipeline/schedule.py`): implement **interval-only** `next_fire` arithmetic; **drop** the
  hand-rolled 5-field cron subset + its cron adversarial-test list. Keep the interval boundary/overflow
  tests. UTC-only stands.
- **ADR-042 D3**: rewrite to "interval-only in P5.1b; `kind` column retained for forward-compat; cron
  evaluation deferred to a focused follow-on (its own greenfield-correctness review)." Note explicitly
  that schema (P5.1b-2), sweeper (P5.1b-4), endpoints (P5.1b-5) are **unchanged** by this — only the
  arithmetic module narrows.
- Schedule-create validation (P5.1b-5): reject `kind=cron` at create (422) until the follow-on lands,
  so the column's presence never implies a working cron path.

## Y2 — schedule-management endpoints (P5.1b-5 / ADR-042 D9) → **keep**

A scheduler with no create path is inert + non-demoable. D9 is a faithful application of the ADR-041
D7 precedent (minimal owner-private CRUD ships so there is something to run), reuses owner-private +
fail-closed correctly (owner inherited from parent pipeline, 403 non-owner, server-derived principal
per ADR-039 D1). **No change** — keep P5.1b-5 + ADR-042 D9 as planned.

## N3 — unbounded FREE_CHAT room growth under automation → **acknowledge as deferred GC**

Each run creates a fresh `FREE_CHAT` room; automation makes this unbounded (hourly ≈ 720 rooms/month).
Output stays reversible (ADR-041 D5) — resource/retention, not safety. **Senior adds one line to
ADR-042's Consequences** naming it a conscious deferred concern (room/run retention + GC is a later
slice, like incrementality) — so it is an explicit defer, not a gap.

## Minor (no action)
N1 (config home `config/pipeline.yaml` vs `autonomy.yaml`) is within the ratified B5 options — keep
the senior's choice. N2 (interval drift = correct price of skip-to-next) — the senior should add the
one-line doc-comment in `schedule.py` already noted. N4 — no action.

RC-3: senior absorbs this routing (RC-10 verdict bump) then the architect Accepts ADR-042; senior does
not self-accept. No product code exists yet — absorption is plan + ADR-042 edits on main.
