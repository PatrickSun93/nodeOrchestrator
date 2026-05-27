---
task_id: W-002
kind: architect-routing
date: 2026-05-27
reviews_acked:
  - R0-A-on-plan.md
decision: ack_all_leans
---

# W-002 architect routing — "ack all leans"

**Architect decision (this session):** `ack all leans` — every finding
in `docs/process/reviews/W-002/R0-A-on-plan.md` resolves to the
review-author's own recommended lean. No item-by-item override; no
deferrals beyond what the review itself recommends.

This file is a **signal artifact for the senior revision session**.
The senior session that picks W-002 next reads this file alongside
the review and applies each finding's routed action without further
architect intervention.

## Reviews acked

- `R0-A-on-plan.md` — 0 🔴 / 2 🟡 / 5 🟢 (verdict: `needs_architect`).

R0-B for W-002 was not dispatched (W-002 is mechanical bug-fix
scope, not categorical shape change; brief lean explicitly accepted
single-reviewer per RC-2 + RC-9 precedent).

## Per-finding routing

| Finding | Severity | Routed resolution | Source |
|---|---|---|---|
| R0-A Y1 | 🟡 | **(β)** Move the ADR-008 clarification entirely to `docs/process/senior-plans/README.md`'s post-W-002 frontmatter section (already in W-002-1 scope). ADR-008 body stays untouched. Preserves the "ADRs as audit snapshots" semantic; senior-plans/README is the natural home for the plan-frontmatter convention. Cost: one missed cross-link from ADR-008 → senior-plans/README is a 5-surface-scan concern not an ADR-content concern. | R0-A-on-plan Y1, lean stated as "(β)". |
| R0-A Y2 | 🟡 | **(β)** Extend W-002 scope to include the no-ADR routing fix. Add a new sub-task (or extend W-002-1 acceptance) so `next_state` consults the plan frontmatter and skips `awaiting_architect_accept` when no `adr` key is declared. ~20 LoC + 2 tests. Lands W-002 without architect override on its own state file; closes the RC-11 sub-finding pattern in the same cycle the bug was caught. | R0-A-on-plan Y2, lean stated as "(β)". |

## Senior revision actions (derived)

The senior revision session executes the following plan edits on `docs/process/senior-plans/W-002.md`:

1. **Y1 routing (β)**: revise W-002-1 acceptance — remove the ADR-008 inline-clarification edit; replace with an addition to `docs/process/senior-plans/README.md` (in W-002-1's existing scope) carrying the plan-frontmatter convention. Add a one-line note in 5-surface-scan section pointing at senior-plans/README as the new home for this convention.
2. **Y2 routing (β)**: add new atomic task **W-002-2b** (or extend W-002-1 acceptance — senior judges placement) covering the `next_state` no-ADR routing fix. Acceptance: `next_state` reads the plan frontmatter; if no `adr` key, advance `awaiting_senior_plan → awaiting_junior_impl` directly (skip `awaiting_architect_accept`); 2 tests (one happy-path no-ADR transition; one explicit-ADR-key still routes through accept). Update §3 execution order to insert W-002-2b in the appropriate sequential slot. Update §4 forcing-functions table coverage references if needed.
3. **Tracking-table impact**: W-002-* numbering may grow by one if W-002-2b is a new atomic (vs an extension to W-002-1). Senior picks the cleaner cut and reflects in landing-commit composite tracking table.
4. **W-002 .workflow file impact**: with the no-ADR routing fix landed, W-002's own state file now advances cleanly `awaiting_senior_plan → awaiting_junior_impl` on the revised plan push (no `awaiting_architect_accept` stall). Senior should re-verify the .workflow/W-002.yaml advance path in the landing commit and remove any prior assumption of architect override.

## Status flips that follow

Once the senior revision pass lands on `claude/W-002-plan` (clean R0-A re-verdict expected as `clean`):

- `.workflow/W-002.yaml` advances `awaiting_senior_plan → awaiting_junior_impl` per the new Y2-routed `next_state` behavior (no `awaiting_architect_accept` intermediate).
- W-002 architect-Accept gate is **not** invoked (no ADR drafted for W-002; this was the senior's path-β decision in the plan and remains correct).
- Junior dispatches to `claude/W-002-impl` per the revised plan; impl-stage proceeds.

## Out of scope for this routing

- R0-B (cross-family) dispatch for W-002: not warranted per brief + RC-2 (mechanical bug-fix scope; no shape change).
- New ADR drafts: W-002 remains a no-ADR cycle; the path-β decision in the plan is preserved.
- Any plan structural redesign beyond Y1+Y2 absorption: 5 🟢 findings confirm the plan is structurally sound.

## Cross-references

- `docs/process/reviews/W-002/R0-A-on-plan.md` — source of leans.
- `docs/process/senior-plans/W-002.md` — file the senior revision session edits.
- `docs/decisions/ADR-008-workflow-state-machine.md` — referenced (and now NOT amended per Y1 routing β).
- `docs/process/senior-planner.md` § "Self-organization on session start / resume" — the rule that auto-routes the senior revision session to this routing artifact.
