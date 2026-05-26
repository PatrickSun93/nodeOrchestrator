# W-001-impl plan stub

| Field | Value |
|---|---|
| Task ID | W-001-impl |
| For | senior planner (full task plan lands here after Accept); junior reads the full version only after that |
| Date | 2026-05-20 |
| Status | **Draft stub** — full atomic task list lands after ADR-008 Accept + distance-test pause |
| ADR | [`docs/decisions/ADR-008-workflow-state-machine.md`](../../decisions/ADR-008-workflow-state-machine.md) (Proposed; this stub assumes its eventual Accept) |
| Brief | [`docs/process/architect-briefs/W-001.md`](../architect-briefs/W-001.md) |
| Note | **No code work in W-001 itself.** This stub identifies the rough commit shape; acceptance criteria are NOT pinned until the ADR Accepts. |

## 1. Context

W-001 produces two artifacts: (a) ADR-008 (the design) and (b) this
stub (the rough impl shape). Implementation lands in a separate
post-Accept task (W-001-impl) — that task's full plan is written
once the ADR Accepts and architect signals readiness.

The reason for a stub now: identifying the rough commit cuts and
the cross-cutting risks lets architect-partner and architect see
the shape during ADR review. The full atomic task list with file
paths, line ranges, and per-task acceptance criteria waits until
the ADR Accepts because (i) those details depend on ADR Decisions
3-12 being final, (ii) the distance-test pause exists precisely so
those details don't lock in prematurely.

## 2. Rough cuts (NOT atomic tasks — full plan post-Accept)

| Cut | Description | Touches |
|---|---|---|
| **impl-1** Scaffolding | Create `.workflow/` dir; YAML schema (Pydantic); write `.workflow/README.md` documenting the file layout per ADR-008 Decision 5. | new `.workflow/`, new schema-validation module under `src/orchestrator/workflow/` (path TBD post-Accept; see §3 push-back #1) |
| **impl-2** Transition library | Pure-function `transition(current_state, artifacts, gates) → next_state` plus `verdict(review_file) → Literal["clean", "blocking", "needs_architect"]` plus `should_auto_advance(state_file) → bool` plus `record_override(state_file, override) → None`. All synchronous, no I/O outside the state file. Includes mypy-strict typing and the canonical state enum from ADR-008 Decision 6. | new `src/orchestrator/workflow/transitions.py` (or equivalent); tests at `tests/workflow/test_transitions.py` |
| **impl-3** Review frontmatter conventions | YAML frontmatter spec for `plan-vs-impl.md`, `R0-A.md`, `R0-B.md`, `R1-A.md`, etc. Update `docs/process/reviews/README.md` to document the spec. Update review templates (if any exist) to include the frontmatter block. | `docs/process/reviews/README.md`; possibly new `docs/process/reviews/_template.md` |
| **impl-4** Session-start integration | Hook / launcher logic that reads `.workflow/` on session launch and surfaces "what should this role do now?" Surface depends on architect's choice between Claude Code `SessionStart` hook (`.claude/settings.json`) and a framework-agnostic CLI tool. See §3 push-back #2. | `.claude/settings.json` OR a new `tools/workflow-status` CLI — both, possibly; architect decides |
| **impl-5** Auto-trigger glue | Wiring: on session start, detect that an artifact appeared in git for a state that auto-advances; perform the transition (write state file); commit. The atomic-commit semantic per ADR-008 Decision Consequence "Implicit error recovery" is the load-bearing invariant of this cut. | uses impl-2's library; lives alongside impl-4 |
| **impl-6** Constitutional + integration tests | Pure-function tests on the transition matrix (every (state, artifact, gate) tuple maps to an expected next state); integration tests with a tmp `.workflow/` against a tmp git repo for the auto-trigger path; constitutional test that `transitions.py` contains no LLM-SDK imports (Principle 3.1 + ADR-008 Decision 2). | `tests/workflow/test_transitions.py`, `tests/workflow/test_integration.py`, `tests/workflow/test_constitution.py` |
| **impl-7** Bootstrap script + initial state files | One-shot script that emits `.workflow/W-001-impl.yaml` with state `awaiting_brief` if no brief exists yet, OR `awaiting_senior_plan` if brief already exists at the locked path. Future tasks adopt by running this on task creation. No retroactive bootstrapping of P1.2 work per ADR-008 Decision 12. | new `tools/workflow-init` CLI; `.workflow/W-001-impl.yaml` |
| **impl-8** Doc updates | `handoff.md` §16 update describing the state machine + auto-triggers; `docs/process/senior-planner.md` cross-link to ADR-008 + state vocabulary; `docs/contributing.md` Q5 (new) "Did you update `.workflow/{task-id}.yaml`?" — or equivalent. | `handoff.md`, `docs/process/senior-planner.md`, `docs/contributing.md` |
| **impl-9** Landing commit + 5-surface scan | All four gates clean; 5-surface scan (Q3 contributing.md); tracking table per `feedback_review_followup_tracking.md`; freeze-vs-impl drift line (no signatures change in this PR — purely additive new module + new dotted directory). | project root |

Anticipated commit count: 9 atomic commits, possibly bundled into
fewer for related concerns (e.g., impl-4 + impl-5 may be one commit
if architect's choice on §3 push-back #2 lands cleanly).

## 3. Anticipated push-backs (preview; full set post-Accept)

1. **Module location**: `src/orchestrator/workflow/` (production code) vs `tools/` (tooling-only). Senior lean: production — Principle 3.1 decision-path code deserves the same gates as `autonomy/` and `core/`.
2. **Hook vs CLI**: Claude Code `SessionStart` hook vs standalone CLI vs both. Senior lean: both, decoupled — CLI is framework-agnostic; hook is Claude Code-specific automation on top.
3. **Frontmatter retrofit for closed work**: ADR-008 Decision 12 says no retrofit. Confirm during impl-3 that closed-task review files genuinely don't need it (state machine never reads them).
4. **Test-coverage-standard application** (preview): §1 applies to impl-5 (workflow → git → fs); §3 applies via atomic write-then-rename pattern; §4 applies via `WorkflowError` payloads; §6 applies to the state-file Pydantic model. §2 (concurrency) N/A — sessions are human-initiated; document explicitly.
5. **RC-1 interaction**: pre-edit grep sub-rule was graduating at P1.2 close-out; impl-8/-9 doc edits must apply RC-1 sub-rule. Verify RC-1 graduation status before impl-9 lands.

## 4. Dependencies

- **ADR-008 Accepted** (architect bumps `Proposed → Accepted` after distance-test pause; 24h+ minimum per W-001 brief).
- **RC-1 graduation** confirmed (P1.2 retrospective close-out item).
- **Architect choice on §3 push-back #1 (module location)** before impl-1 starts.
- **Architect choice on §3 push-back #2 (hook vs CLI vs both)** before impl-4 starts.

## 5. Where I'd push back on the brief itself

One concern with the brief + three self-discoveries beyond the architect's predicted set:

**5.1 Same-family R0 chain risk under auto-trigger** (concern with brief).
Auto-firing R0-A on plan-vs-impl posting removes any out-of-band interlude between two same-family Claude sessions (retro §6). ADR-008 Decision 13 declares orthogonal. Senior agrees with the framing but flags: if cross-family R0-B becomes a future requirement, the state-machine gate is the natural enforcement point. impl-1 schema should leave room for `requires_cross_family_review: bool` without forcing it now.

**5.2 Side-channel artifacts** (self-discovery).
Retrospective candidates files, architect-partner observation notes — written across cycles without firing transitions. State machine must treat these as no-ops. ADR-008 implicit; surface as a docstring invariant on `transition()`: only the recognized artifact set (review files, ADR status changes, PR-merge events) drives transitions.

**5.3 Brief amendment cycles** (self-discovery).
Recall `8b727c0` ("amend brief intro" mid-cycle). When architect amends a brief while task is in `awaiting_senior_plan_vs_impl`, two answers: (a) stay in current state; (b) explicit override. Senior lean: (a), with override available if the amendment is materially incompatible. impl-2 ignores brief amendments by default.

**5.4 ADR Accept timing race** (self-discovery).
If architect bumps ADR status on a branch before merge to main, the state machine sees inconsistent ground truth. Mitigation: state machine reads `origin/main` only (not local branches). Document in impl-2 docstring.

## 6. Distance test

W-001 doc-only — same-day writing acceptable. **W-001-impl commits land no earlier than 2026-05-22**: the W-001 brief says "ADR Accept gets the standard 24h+ pause; that's the inscribing moment." If ADR Accepts on 2026-05-21, impl-1 starts 2026-05-22 earliest.

## 7. Length budget

This stub is intentionally ~800 words excluding the rough-cuts table. Full plan post-Accept will be ~2500-3000 words (similar to W-001's ADR length budget) — 9 atomic tasks at ~250-300 words each plus §1-5 standard sections per `senior-planner.md`.
