# Workflow Overview

This doc is the **single entry point** for the Orchestrator project's multi-role workflow. It is a **map**, not the source of truth. Authoritative details live elsewhere — see § "Canonical references" at the bottom.

If you are a new session (senior, junior, reviewer, or architect-partner), read this doc first, then drill into the specific surface you need.

If you are the architect, you already know this. This doc is for everyone else.

---

## 1. Roles

The project runs with five distinct roles, each backed by a separate LLM session for cross-perspective independence. Role collapse is the single biggest project risk (see `docs/retrospectives/P1.2.md` §9).

| Role | Session | Writes | Does NOT write |
|---|---|---|---|
| **Architect** | The human (project owner) | Decisions, ADR acceptance, high-level docs (handoff, chat-history, contributing.md), task scope | Task plans, code, reviews |
| **Architect-partner** | One Claude session | Briefs (`architect-briefs/`), R0-A reviews, high-level doc edits, retrospective candidate captures | Task plans, code, **architectural decisions** (only surfaces; doesn't decide) |
| **Senior planner** | Independent Claude session | Task plans (`senior-plans/`), plan-vs-impl verifications, **ADR drafts** | Code, test execution, architectural decisions (only drafts; architect accepts) |
| **Junior implementer** | Independent session (often DeepSeek or other family) | Code, tests, commit body tracking tables | Task plans, ADRs, architectural decisions |
| **Reviewer** | R0-A (often architect-partner) + optional R0-B (cross-family for higher signal) | Review files (`reviews/{task-id}/R0-A.md` etc.) with 🔴/🟡/🟢 findings | Any fix (only surfaces; architect routes) |

**Core principle**: each role is a distinct lens. The error-correction signal in the project comes from cross-role review, not from any single perspective. Self-loop has no error correction.

See `handoff.md` §16 for the full role definitions and rationale.

---

## 2. Lifecycle (closed loop)

A typical task flows through these phases:

```
1. Architect decides scope of task X
        ↓
2. Architect-partner writes brief
        → docs/process/architect-briefs/{task-id}.md
        ↓
3. Senior reads brief, writes plan (+ drafts ADR if needed)
        → docs/process/senior-plans/{task-id}.md
        → docs/decisions/ADR-NNN-slug.md (Proposed)
        ↓
4. Architect-partner R0-A reviews the plan + ADR
   — **architect-dispatched (gated transition)**; architect decides per case whether to dispatch.
   When new ADR is co-posted with plan, R0-A naturally covers both.
   When plan is post-Accept-only (no new ADR), architect decides whether
   to R0-A the plan or skip directly to junior dispatch. Path:
   `docs/process/reviews/{task-id}/R0-A-on-plan.md` to disambiguate from
   post-impl `R0-A.md`. See RC-9 for resolution context.
        ↓
5. Architect accepts ADR (Proposed → Accepted)
   — distance test pause between draft and accept —
        ↓
6. Junior reads plan, implements, commits to feature branch
        ↓
7. Senior runs plan-vs-impl verification
        → docs/process/reviews/{task-id}/plan-vs-impl.md
        ↓
   [Any 🟡 → trivial-fix routing back to junior, single commit]
        ↓
8. Architect-partner R0-A
        → docs/process/reviews/{task-id}/R0-A.md
   [Optional: cross-family R0-B → same path, different reviewer]
        ↓
   [Any 🟡 → architect routes resolution; 🟢 → defer or accept]
        ↓
9. Architect merges PR to main
        ↓
10. Module close-out (when applicable)
        → docs/retrospectives/{cycle}.md
```

**Gated transitions** (require architect decision): brief publish, ADR accept, 🟡 routing, PR merge.
**Verification transitions** (advance on artifact appearance, no architect decision): plan-vs-impl appearing → R0-A fires, clean R0-A → PR opens.

The full state machine governing these transitions is `docs/decisions/ADR-008-workflow-state-machine.md`.

---

## 3. File path map

All workflow artifacts live at fixed paths. The locked-path convention is enforced by `docs/process/senior-planner.md` § "Where your outputs go".

```
.workflow/
└── {task-id}.yaml                          # state machine ground truth (per ADR-008)

docs/
├── decisions/
│   └── ADR-NNN-slug.md                     # architectural decisions (senior drafts, architect accepts)
├── architecture/
│   └── *.md                                # module-level specs (event-model, llm-layer, test-coverage-standard)
├── retrospectives/
│   ├── P*.md                               # per-module retrospectives (close-out)
│   └── *-candidates.md                     # per-cycle candidate accumulation
└── process/
    ├── workflow-overview.md                # this file
    ├── senior-planner.md                   # senior role doc + output-paths table
    ├── architect-briefs/
    │   ├── README.md
    │   └── {task-id}.md                    # architect → senior briefs
    ├── senior-plans/
    │   ├── README.md
    │   └── {task-id}.md                    # senior → junior task plans
    └── reviews/
        ├── README.md
        └── {task-id}/
            ├── plan-vs-impl.md             # senior self-verify (frontmatter: verdict)
            ├── R0-A.md                     # external reviewer (Claude family; frontmatter)
            ├── R0-B.md                     # cross-family reviewer (DeepSeek/Gemini/etc.; if dispatched)
            ├── R1-A.md / R1-B.md / …       # later rounds if rework needed
            └── meta.md                     # close-out meta-review

handoff.md                                  # project framing + §16 workflow doc
chat-history.md                             # design reasoning history (versioned)
contributing.md                             # PR template (Q1–Q4 + 5-surface scan)
```

**Naming convention**:

- Task IDs are case-preserved: `P1.2-C3`, `W-001`, etc.
- Files for one task share the task ID across folders: `architect-briefs/P1.2-C3.md`, `senior-plans/P1.2-C3.md`, `reviews/P1.2-C3/R0-A.md`.
- Review file `-A` / `-B` suffix is mandatory: `-A` = Claude family, `-B` = cross-family.
- **Absence of `R0-B.md` is the evidence** that no cross-family reviewer was dispatched that round. Do not create empty placeholder files.

---

## 4. Forcing functions

Forcing functions are project-level rules that survive across sessions, codified in docs or constitutional tests. Current set:

| Function | What it catches | Where codified |
|---|---|---|
| Tracking table in commit message | Reverse drift (silently re-deriving rejected positions) | `feedback_review_followup_tracking.md` (memory) |
| 5-surface scan | Schema changes missed in code / yaml / ADR / arch doc / narrative | `contributing.md` Q3 |
| **Pre-edit grep sub-rule** | "Surface edited" ≠ "consistent post-edit"; old values lingering | `contributing.md` Q3 (RC-1 — graduated W-001-impl-8) |
| Layer-crossing field-plumbing | Fields added but not threaded source→sink | `contributing.md` Q3 "Layer-crossing field plumbing" |
| Constitutional tests | Invariants the type system cannot check (string content, structural conformance, data-flow source ≠ sink) | `tests/**/test_constitution_*.py` (15 tests as of W-001) |
| 6-category test-coverage standard | Coverage gaps across cross-module / concurrency / cleanup / exception payload / boundary validators / schema invariants | `docs/architecture/test-coverage-standard.md` |
| **Senior-drafts-ADR rule** | Architect self-draft + self-review = self-loop, no external review surface | `docs/process/senior-planner.md` § "ADR drafting" (graduated and tested — ADR-006, ADR-007, ADR-008) |
| Distance test | Same-session inscription of architecturally-consequential decisions | **Disputed substrate** — see RC-8; W-001 close-out will codify α/β/γ |

---

## 5. Automation (ADR-008)

The workflow is automated with a per-task state machine. ADR-008 Accepted (2026-05-21); implementation at `src/orchestrator/workflow/`; CLI entry-point: `workflow` (see `pyproject.toml [project.scripts]`); SessionStart hook in `.claude/settings.json`.

Key points:

- **Per-task state files** at `.workflow/{task-id}.yaml`, treated as ground truth (Principle 11 — state file IS the truth, not chat history or session memory).
- **9-state vocabulary** (closed set): `awaiting_brief`, `awaiting_senior_plan`, `awaiting_architect_accept`, `awaiting_junior_impl`, `awaiting_senior_plan_vs_impl`, `awaiting_R0_A`, `awaiting_architect_decision`, `awaiting_PR_merge`, `closed`.
- **Session-start trigger**: each Claude Code session reads `.workflow/` on launch, identifies which task states match its role, and acts. No GitHub Actions; no cron.
- **Auto-trigger conditions**: review files carry YAML frontmatter `verdict: clean | blocking | needs_architect`. Auto-advance reads `verdict`. Any `blocking` or `needs_architect` routes to `awaiting_architect_decision`.
- **Override**: architect (or architect-partner with architect authorization) can force-advance, force-revert, or halt any task; all overrides recorded in `override_history` with `reason`.
- **Bootstrapping**: existing P1.x closed work does NOT get retroactive state files. W-001-impl is the first task with a state file.

Full design: `docs/decisions/ADR-008-workflow-state-machine.md`. Implementation: `src/orchestrator/workflow/` (landed W-001-impl). Senior plan: `docs/process/senior-plans/W-001-impl.md`.

---

## 6. Open meta-questions (retrospective candidates)

These are not yet codified. Status as of W-001 design close:

| Candidate | Status | Resolution moment |
|---|---|---|
| **RC-1** (pre-edit grep sub-rule) | ✅ Graduated — W-001-impl-8 landed `contributing.md` Q3 sub-bullet | — |
| **RC-2** (cross-family R0-B sufficiency) | ⏸ Empirically deferred — 4 consecutive P1.2+ skips, no contract bug surfaced | P1.3 freeze should dispatch R0-B given new work shape |
| **RC-3** (senior-drafts-ADR) | ✅ Graduated + tested via ADR-006/007/008 | — |
| **RC-4** (test-coverage reversal pattern) | ⏸ Defer until second instance observed | P1.3+ |
| **RC-5** (architect-partner role boundary) | ✅ Internalized via role-prompt self-check | — |
| **RC-6** (frozen-schema evolution policy) | ⏸ Architect decision pending | First P1.3 schema-evolution moment |
| **RC-7** (stale-workspace-as-truth pattern) | Open — 2 instances in W-001 cycle | W-001-impl session-start git-verify; W-001 close evaluates |
| **RC-8** (distance-test letter vs spirit) | Open — strongest graduate-now case (2 instances within ~12h) | W-001 close picks α / β / γ; **do not defer to third instance** |

---

## 7. Distance test (current state — disputed)

The distance test rule has two interpretable substrates that have diverged twice in the W-001 cycle:

- **(X) Strict elapsed time**: 24h+ from a reference timestamp. Auditable by clock.
- **(Y) Sleep cycle + fresh-eye revisit**: cognitive break between architectural inscription and action. Honors the principle directly; requires self-report or proxy detection.

Architect has chosen (Y) over (X) twice (C4 junior same-day impl, W-001 ADR-008 same-day status flip). Codification deferred to W-001 close, but RC-8 is on the explicit graduate-at-W-001-close list.

Until codified, use the architect's stated interpretation case-by-case. If you are surfacing a distance-test concern (architect-partner role), be explicit about which substrate (X / Y) you mean.

---

## 8. Canonical references

This overview is a **map**. When details diverge between this doc and the sources below, the sources are authoritative.

| Topic | Canonical source |
|---|---|
| Role definitions, project framing | `handoff.md` §16 + §1-§13 |
| Senior planner role + ADR drafting + output paths | `docs/process/senior-planner.md` |
| State machine vocabulary + transitions | `docs/decisions/ADR-008-workflow-state-machine.md` |
| PR template + 5-surface scan + layer-crossing | `docs/contributing.md` |
| Test-coverage 6-category standard | `docs/architecture/test-coverage-standard.md` |
| Event model + EventType vocabulary | `docs/architecture/event-model.md` |
| LLM layer three-tier config | `docs/architecture/llm-layer.md` + ADR-002/003 |
| Autonomy gate scoring | ADR-005, ADR-006, ADR-007 |
| Design reasoning history (why decisions were made) | `chat-history.md` |
| Past module retrospectives | `docs/retrospectives/P*.md` |
| Per-cycle candidate captures | `docs/retrospectives/*-candidates.md` |

---

## 9. How to onboard

If you are a **new senior** session:

1. Read this overview.
2. Read `docs/process/senior-planner.md` (your role doc).
3. Find the brief for your task at `docs/process/architect-briefs/{task-id}.md`.
4. Read the latest ADRs and the relevant module retrospective.
5. Write the plan. If no brief exists, stop and ask the architect.

If you are a **new junior** session:

1. Read this overview.
2. Find the plan at `docs/process/senior-plans/{task-id}.md`.
3. Read the relevant ADRs cited in the plan.
4. Implement per plan acceptance criteria. Track deviations in commit body.
5. Do not write your own plan or ADR.

If you are a **new reviewer** (R0-A or R0-B):

1. Read this overview.
2. Read the brief, plan, and senior plan-vs-impl review for the task.
3. Read the diff being reviewed.
4. Write your review with `verdict` frontmatter (clean / blocking / needs_architect) to `docs/process/reviews/{task-id}/R{n}-{A|B}.md`.
5. Do not fix anything. Only surface.

If you are the **architect-partner**:

1. Read this overview.
2. Read the latest entries in `docs/retrospectives/*-candidates.md` and the most recent retrospective.
3. Read the active brief and any active reviews.
4. Push back on architect decisions where the data warrants; surface findings; do not decide.
5. Honor the role boundary — modify only high-level docs and reviews; do not write code or full plans.
