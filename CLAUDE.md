# Project context for all Claude Code sessions

This repo runs a **multi-role workflow** (architect / senior planner / junior implementer / reviewers). Each role runs in a **distinct Claude session** for cross-perspective independence. Role collapse is the single biggest project risk (see `docs/retrospectives/P1.2.md` §9).

If you don't know which role you are, **stop and identify before acting**.

---

# Identify your role

Your role is set via the env var `CLAUDE_ROLE`. On session start, check it:

```bash
echo "${CLAUDE_ROLE:-unset}"
```

| `CLAUDE_ROLE` value | Read this role doc | Matching states |
|---|---|---|
| `architect-partner` | `docs/process/architect-partner.md` | `awaiting_brief`, `awaiting_R0_A`, `awaiting_architect_decision` (synthesis); also manual dispatches for R0-A-on-plan + routing artifacts |
| `senior` | `docs/process/senior-planner.md` | `awaiting_senior_plan`, `awaiting_senior_plan_vs_impl` |
| `junior` | `docs/process/junior-implementer.md` | `awaiting_junior_impl` |
| `reviewer-r0b` | `docs/process/reviewer-r0b.md` | R0-B dispatched in current cycle (via notify-reviewers.sh or architect chat) |
| unset / empty | **stop + ask the user which role you are**, do not guess from context | — |

Each role doc has its own self-trigger flow (read on session start when the matching state is present in `.workflow/`).

---

# Scope: product vs dev harness

The repo contains two **functionally separate** code surfaces:

| Surface | What | Files |
|---|---|---|
| **Product** (orchestrator) | What end-users will run: multi-agent rooms running real conversations. Architecture documented in `docs/architecture/`. | `src/orchestrator/{agents,autonomy,core,llm,rooms,skills}/`, `tests/{agents,autonomy,core,llm,rooms,skills,integration,derived}/`, `config/agents/`, `config/skills/`, `config/tools.yaml`, `handoff.md`, `chat-history.md`, `docs/architecture/*`, `docs/decisions/ADR-001..014` (except ADR-008) |
| **Dev harness** | Tooling the architect uses to develop the product: workflow state machine, role docs, process docs, tmux launchers. Zero runtime coupling to product. | `src/orchestrator/workflow/` (standalone CLI, not imported by product), `tests/workflow/`, `.workflow/*.yaml`, `docs/process/*`, `docs/decisions/ADR-008-workflow-state-machine.md`, `scripts/` (gitignored), `pyproject.toml [project.scripts] workflow` entry |

**Why the distinction matters**: dev harness changes have **zero product runtime risk** (no product module imports `orchestrator.workflow`). The full brief → senior plan → ADR → junior → R0-A/R0-B/plan-vs-impl review chain exists to protect **product correctness**. Dev harness changes bypass most of it:

- **No senior plan** — architect (or arch-partner) writes a light design note; junior implements.
- **No R0-A / R0-B / plan-vs-impl** — dev harness has no product-correctness invariant for them to protect.
- **ADR amendment IS still required when changing `docs/decisions/ADR-008-*`** — that ADR is the dev harness contract; amendments must be inscribed.
- **Tests + gates still mandatory** — `tests/workflow/*` + ruff + mypy + pytest all run; the CI/quality bar is the same.
- **Architect Accept is still required for any ADR-008 amendment** — same audit-trail discipline.

If you're unsure whether a change is product or dev harness: ask the architect. The default is "product"; opt-in to dev harness only when the architect confirms.

---

# Project-wide rules (apply to every role)

These rules hold regardless of role. Role docs may add stricter constraints; they do not override these.

## Workflow state is the ground truth

`.workflow/{task-id}.yaml` (per ADR-008) is the source of truth for "where is this task now". The state file IS the truth — not chat history, not session memory, not your recollection.

**State machine self-check**: if `.workflow/{task-id}.yaml` state and reality contradict (e.g., state says `awaiting_senior_plan` but `senior-plans/{task-id}.md` already exists), **halt + surface to architect**. Do NOT auto-fix.

Use `uv run workflow advance` / `uv run workflow override` (per `.workflow/README.md`). NEVER hand-edit state files — the override-history audit record exists for a reason.

## Stale-workspace guard (RC-7 mitigation)

SessionStart hook reports `.workflow/` status + workspace freshness. If the hook shows untracked / modified files not in your expected scope → **halt + `git status` to see clearly + pull / stash → then act**. Do not work on a stale checkout.

## Architect-deferral literal-reading

When architect comments include "queued for W-N brief" / "defer to W-N" / "capture for retro" / "address later" — these phrases mean **substantive deferral**, NOT a green light to opportunistically fix in the current cycle.

- Deferred items stay untouched this cycle.
- Do not bundle a partial implementation or "defensive hardening" under deferral language.
- If you think in-cycle action is correct despite the deferral language → halt + surface to architect for explicit dispatch.

Failure precedent: P1.5.5 RC-19 (defensive Z-suffix bundled under δ deferral, surfaced as Y finding at R0-A).

## Never LLM-judge a routing decision

Grep `LLMPurpose` usage for the allowed surfaces — only `content-gen` purposes are valid. Routing decisions (α / β / γ) are **architect** decisions, not LLM judgments. The architect-partner surfaces; the architect routes. No role re-routes via "I think this finding doesn't apply".

## Never amend pushed commits

Audit trail must remain intact. Exceptions require explicit architect dispatch. If a pre-commit hook fails locally on an unpushed commit, fix-and-recommit is fine. Once pushed, never amend / force-push without architect go-ahead.

## Surface, don't improvise

If anything in your role's input artifacts (plan, brief, ADR, routing) looks wrong, impossible, or contradicts reality:
- **halt + surface** with specific evidence (file path, line, expected vs actual)
- do NOT silently improvise a "best-guess" fix
- do NOT silently re-interpret architect intent

The cost of pausing to ask is low; the cost of silent improvisation is high (P1.5.5 RC-19, multiple other instances).

---

# Reference

| Topic | Source |
|---|---|
| Workflow overview (roles, lifecycle, file path map) | `docs/process/workflow-overview.md` |
| Project framing, principles, P1 plan | `handoff.md` |
| Design reasoning history | `chat-history.md` |
| State machine vocabulary | `docs/decisions/ADR-008-workflow-state-machine.md` |
| State files (per-task ground truth) | `.workflow/{task-id}.yaml` + `.workflow/README.md` |
| PR template, 5-surface scan, Q1–Q4 | `docs/contributing.md` |
| Distance test (architect inscription pacing) | `docs/process/distance-test.md` |
| Dual-lens R0-B dispatch criteria | `docs/process/dual-lens-r0b.md` |
