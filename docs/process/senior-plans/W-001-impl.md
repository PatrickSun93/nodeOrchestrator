# W-001-impl senior plan

| Field | Value |
|---|---|
| Task ID | W-001-impl |
| For | junior implementer (architect-partner Claude session or DeepSeek; senior plan is implementer-agnostic) |
| Date | 2026-05-26 |
| Status | Full plan (replaces 2026-05-20 stub) |
| ADR | [`docs/decisions/ADR-008-workflow-state-machine.md`](../../decisions/ADR-008-workflow-state-machine.md) (Accepted 2026-05-21) |
| Brief | [`docs/process/architect-briefs/W-001.md`](../architect-briefs/W-001.md) (W-001 parent task; this impl was scope-deferred there) |
| R0-A context (W-001) | [`docs/process/reviews/W-001/R0-A.md`](../reviews/W-001/R0-A.md) — gate items R0-A-7 #1/#2 resolved; watch items R0-A-4/5/8 routed into impl tasks below |
| Predecessors | W-001 ADR-008 land (`819d8f5` merge of `claude/w-001-plan`); RC-7 capture (`6afff9d`); RC-8 capture (`759e2cc`); workflow-overview.md (`1d6e3e6`) |

## 1. Context

W-001-impl is **the first task that exercises ADR-008's state machine end-to-end**. The harness must scaffold itself: the very first `.workflow/{task-id}.yaml` written is `.workflow/W-001-impl.yaml` (Decision 12). The implementation is a small library plus a CLI plus a Claude Code hook plus six docs touches plus eight to twelve tests — comparable in shape to P1.2-C4 (7 commits, ~460 insertions) but doc-heavier and code-lighter.

Three architect-settled inputs shape the plan:

- **Module location lock (R0-A-7 #1):** `src/orchestrator/workflow/` is production code, gated by the same constitutional tests as `autonomy/` and `core/`. Not `tools/`.
- **Trigger mechanism lock (R0-A-7 #2):** **both CLI and Claude Code SessionStart hook, decoupled**. The CLI is the framework-agnostic primitive (scriptable, testable, runnable outside Claude Code); the hook is Claude-Code-specific automation that calls the CLI on session launch. Decoupled means: hook depends on CLI, CLI does not depend on hook.
- **Distance-test floor:** ADR-008 Accepted 2026-05-21; per W-001 brief Decision 8, impl-1 commits land no earlier than 2026-05-22. (Today is 2026-05-26 — well past the floor.) Same-day impl-1 → impl-9 is acceptable since the inscribing moment (Accept) has already absorbed the pause.

The plan absorbs four R0-A watch items and four self-discoveries from the stub §5, listed inline at the task they belong to. RC-7 (stale-workspace-as-truth) gets a concrete mitigation in impl-4 (the `git fetch + git status` divergence check). RC-8 (distance-test substrate) is process-meta, not impl-material — out of scope for W-001-impl.

## 2. Tasks

### W-001-impl-1 — Schema scaffolding + `.workflow/` directory + §6 invariants

- **What**: Create `.workflow/` as a git-tracked directory at repo root. Define the canonical state-file Pydantic model and the state enum. Write `.workflow/README.md` documenting the file format. Add schema-invariant tests per `test-coverage-standard.md` §6.
- **Where**:
  - New: `.workflow/README.md`.
  - New: `src/orchestrator/workflow/__init__.py` (empty re-export module).
  - New: `src/orchestrator/workflow/schema.py` — `WorkflowState` StrEnum + `TaskState` Pydantic model + `OverrideEntry` Pydantic model.
  - New: `tests/workflow/__init__.py` (empty).
  - New: `tests/workflow/test_schema.py` — §6 invariants tests.
- **Why**: ADR-008 Decisions 4 (location), 5 (YAML shape), 6 (9-state vocabulary). The scaffolding cut is the freeze-shaped first commit: signatures land for impl-2/3/4 to consume.
- **Acceptance** — `schema.py` must declare exactly:

  ```python
  # src/orchestrator/workflow/schema.py
  from __future__ import annotations

  from datetime import datetime
  from enum import StrEnum
  from typing import Literal

  from pydantic import BaseModel, ConfigDict, Field

  class WorkflowState(StrEnum):
      """The 9 canonical workflow states. See ADR-008 Decision 6."""
      AWAITING_BRIEF = "awaiting_brief"
      AWAITING_SENIOR_PLAN = "awaiting_senior_plan"
      AWAITING_ARCHITECT_ACCEPT = "awaiting_architect_accept"
      AWAITING_JUNIOR_IMPL = "awaiting_junior_impl"
      AWAITING_SENIOR_PLAN_VS_IMPL = "awaiting_senior_plan_vs_impl"
      AWAITING_R0_A = "awaiting_R0_A"
      AWAITING_ARCHITECT_DECISION = "awaiting_architect_decision"
      AWAITING_PR_MERGE = "awaiting_PR_merge"
      CLOSED = "closed"

  class OverrideEntry(BaseModel):
      """One entry in TaskState.override_history. See ADR-008 Decision 10."""
      model_config = ConfigDict(frozen=True, extra="forbid")
      timestamp: datetime
      actor: Literal["architect", "architect-partner"]
      from_state: WorkflowState
      to_state: WorkflowState
      reason: str = Field(min_length=1)

  class TaskState(BaseModel):
      """The shape of one `.workflow/{task-id}.yaml` file.
      See ADR-008 Decisions 5 + 6."""
      model_config = ConfigDict(frozen=True, extra="forbid")
      task_id: str = Field(min_length=1)
      state: WorkflowState
      cycle: int = Field(default=1, ge=1)  # rework counter; see Decision 11
      last_transition_at: datetime
      override_history: list[OverrideEntry] = Field(default_factory=list)
      # Schema hook for stub §5.1 — leaves room for future cross-family
      # R0-B gate without forcing it now. Default False = current behavior.
      requires_cross_family_review: bool = False
  ```

  `.workflow/README.md` must include: pointer to ADR-008; the 9-state vocabulary; "git-tracked, not gitignored"; a one-paragraph "what to do if you find a state file out of sync with reality" pointing at Decision 10 overrides.

  `tests/workflow/test_schema.py` must contain at minimum:
  - `frozen=True` mutation test for `TaskState` and `OverrideEntry`.
  - `extra="forbid"` unknown-field test for both models.
  - `cycle >= 1` boundary test (cycle=0 raises).
  - `task_id` min-length test (empty string raises).
  - `OverrideEntry.actor` Literal test (an invalid actor raises).
  - `WorkflowState` enum value test confirming the exact 9 string values.

  All tests green; mypy strict; ruff clean.

- **Out of scope**: any transition logic (impl-2); any CLI (impl-4); any state file content beyond the README (the first real state file is impl-7).

### W-001-impl-2 — Transition library + constitutional test

- **What**: Pure-function library implementing the state-transition rules from ADR-008 Decision 1. No I/O outside read/write of state-file YAML; no LLM imports. Plus the analogue of `test_constitution_no_llm_calls_in_autonomy_module` for this new module.
- **Where**:
  - New: `src/orchestrator/workflow/transitions.py`.
  - New: `src/orchestrator/workflow/exceptions.py` (`WorkflowError`).
  - New: `src/orchestrator/workflow/io.py` (read/write/parse YAML state files; thin wrapper).
  - New: `tests/workflow/test_transitions.py`.
  - New: `tests/workflow/test_constitution.py`.
- **Why**: ADR-008 Decisions 1 (transition table), 2 (code-only), 7 (verdict frontmatter), 8 (merge-clean precondition), 10 (override write), 11 (rework cycle counter).
- **Acceptance** — `transitions.py` must declare:

  ```python
  def parse_verdict(review_file: Path) -> Literal["clean", "blocking", "needs_architect"]:
      """Read the YAML frontmatter from a review markdown file and
      return the `verdict` field. Missing or malformed frontmatter
      raises WorkflowError naming the file path and the missing key.

      Side-channel artifacts (retrospective candidate files, observation
      notes, the `architect-briefs/README.md`) are NOT review files and
      will raise here if accidentally parsed — by design. The auto-
      trigger glue (impl-6) filters to recognized review-file basenames
      before calling this function. See stub §5.2."""

  def next_state(
      current: WorkflowState,
      artifacts: ArtifactSnapshot,
      gates: GateSnapshot,
  ) -> WorkflowState | None:
      """Pure function. Returns the next state if the current
      (state, artifacts, gates) tuple matches a transition rule,
      else None (no auto-advance applicable). Never reads files;
      caller passes snapshots.

      Brief amendments while task is past `awaiting_senior_plan` are
      no-ops: the artifact list does not include "brief modified"
      as an advancing event. Brief amendments while still in
      `awaiting_brief` are also no-ops (senior reads latest content
      at plan-write time). See stub §5.3 + R0-A-8."""

  def record_override(
      state: TaskState,
      override: OverrideEntry,
  ) -> TaskState:
      """Return a new TaskState with the override appended to
      override_history and `state` set to override.to_state. The
      input state is not mutated (Pydantic frozen). The caller
      writes the result. See ADR-008 Decision 10."""

  def evaluate_merge_clean(branch: str, base: str = "origin/main") -> bool:
      """Run `git merge-tree {base} {branch}` (subprocess). Return
      True if no conflict markers in output, False otherwise. See
      ADR-008 Decision 8. Reads `origin/main` only — never local
      `main` — to avoid the ADR-Accept-timing-race stub §5.4
      describes."""
  ```

  `ArtifactSnapshot` and `GateSnapshot` are frozen Pydantic dataclasses also declared in this file or in `schema.py`; concrete fields below the surface but must include:
  - `ArtifactSnapshot`: `brief_exists: bool`, `senior_plan_exists: bool`, `adr_status: Literal["proposed", "accepted", "none"]`, `junior_impl_commit_present: bool`, `plan_vs_impl_verdict: Literal["clean", "blocking", "needs_architect", "absent"]`, `r0_a_verdict: Literal["clean", "blocking", "needs_architect", "absent"]`, `pr_merged: bool`.
  - `GateSnapshot`: `merge_clean: bool`, `tests_pass: bool` (treated as True for impl-2; future ADRs may gate on real test status).

  `next_state` must implement every row of ADR-008 Decision 1's two tables. The transition matrix is exhaustively covered in `tests/workflow/test_transitions.py` (one test per row of each table, plus negative tests where an unmatched tuple returns None). Cycle-counter semantics for the rework path (Decision 11) are tested: the rework transition increments `cycle` by 1; the test asserts both the new state AND the new cycle.

  Per stub §5.2 the docstring above MUST explicitly state side-channel artifacts (`*-candidates.md`, observation files, README files) are no-ops. The auto-trigger glue (impl-6) is the gatekeeper that filters which artifacts reach `parse_verdict`.

  R0-A-4 (max-cycle-count surfacing): `record_override`'s docstring notes that if `state.cycle >= 4`, the harness should surface a warning to the operator that scope is likely wrong (ADR-008 Decision 11 narrative). Implementation: emit a stderr warning when the override would result in `cycle >= 4`. This is impl-2's design choice per R0-A-4 routing; no test required beyond the docstring example.

  `tests/workflow/test_constitution.py` contains:
  - `test_constitution_no_llm_calls_in_workflow_module` — grep test, same shape as the autonomy-module analogue. Forbids `import anthropic`, `from anthropic`, `import openai`, `from openai`, `from orchestrator.llm`, `import orchestrator.llm` anywhere under `src/orchestrator/workflow/`. Vacuously passes today; becomes load-bearing the moment any code in the module imports LLM dependencies.

  Coverage standard application this commit:
  - §1 (cross-module): N/A in impl-2 (no cross-module data flow yet; impl-6 will exercise transitions → io → fs).
  - §2 (concurrency): N/A (sessions are human-initiated; document explicitly in module docstring).
  - §3 (cleanup): subprocess (`git merge-tree`) — `evaluate_merge_clean` must use `subprocess.run` with timeout + context manager; one test covers timeout-raises behavior, one covers `CalledProcessError` payload propagation.
  - §4 (exception payloads): `WorkflowError` carries `task_id: str | None` and `path: Path | None`; test asserts both populated on `parse_verdict` failure.
  - §5 (boundary validators): `parse_verdict` rejects `verdict: invalid_value`; test covers `verdict: ""` and `verdict: "almost_clean"`.
  - §6 (schema): impl-1 landed schema tests; impl-2 introduces no new Pydantic surface beyond `ArtifactSnapshot`/`GateSnapshot` — add §6 tests for those.

- **Out of scope**: CLI (impl-4); auto-trigger end-to-end (impl-6); any actual `.workflow/` file write (impl-7).

### W-001-impl-3 — Review frontmatter conventions + retrofit doc

- **What**: Update `docs/process/reviews/README.md` to document the YAML frontmatter contract from ADR-008 Decision 7. Add a template file. Explicitly document that closed P1.x review files predate this convention and remain in their existing format per Decision 12.
- **Where**:
  - Modify: `docs/process/reviews/README.md`.
  - New: `docs/process/reviews/_template-review.md`.
- **Why**: ADR-008 Decision 7 + R0-A-5 (frontmatter retrofit doc routing).
- **Acceptance**:
  - `README.md` updates:
    1. New section "Frontmatter contract (post-ADR-008)" listing the required keys (`task_id`, `round`, `verdict`, `reviewer`, `date`) and the three allowed `verdict` values with their auto-trigger semantics.
    2. New section "Pre-ADR-008 review files" explicitly listing `P1.2-C3/`, `P1.2-C4/` as pre-frontmatter; "the state machine never reads closed-task review files; no retroactive edit needed" (Decision 12 reasoning).
    3. Cross-link to ADR-008 Decision 7.
  - `_template-review.md` contains a valid frontmatter block + section skeleton (findings table, cross-checks, verdict summary). One copy-paste away from a new review file.
  - RC-1 pre-edit grep sub-rule (P1.2 RC-1 → contributing.md Q3) is **not** landed in this commit — that lives in impl-8 (doc updates).
- **Out of scope**: any code changes; any edit to pre-ADR-008 review files (intentionally not touched); the contributing.md Q3 sub-rule edit (impl-8).

### W-001-impl-4 — CLI primitive + RC-7 divergence check

- **What**: Framework-agnostic CLI exposing the state machine. Subcommands: `status`, `init`, `advance`, `override`, `verify-workspace`. The `verify-workspace` subcommand (RC-7 mitigation) does `git fetch origin && git status --short` and warns on divergence.
- **Where**:
  - New: `src/orchestrator/workflow/cli.py`.
  - New: `pyproject.toml` entry — add `[project.scripts] workflow = "orchestrator.workflow.cli:main"` (verify exact key name matches existing `pyproject.toml` shape).
  - New: `tests/workflow/test_cli.py`.
- **Why**: R0-A-7 #2 lock — CLI is the framework-agnostic primitive; the hook (impl-5) calls into this. RC-7 (stale-workspace-as-truth) needs a concrete forcing function at session launch; the CLI is where it lives.
- **Acceptance**:
  - CLI uses stdlib `argparse` (project convention; no Click/Typer).
  - Subcommands:
    - `workflow status [--task-id TASK]` — print current state of one task or all tasks if no flag; reads `.workflow/`.
    - `workflow init --task-id TASK [--state STATE]` — create `.workflow/TASK.yaml`. Refuses if file exists (unless `--force`).
    - `workflow advance --task-id TASK` — read the current state file, evaluate `next_state` against current git artifacts + gates, write the new state file if a transition fires.
    - `workflow override --task-id TASK --to-state STATE --reason TEXT --actor ARCHITECT_OR_PARTNER` — record an `OverrideEntry` per Decision 10.
    - `workflow verify-workspace [--strict]` — run `git fetch origin` + `git status --short`; if any modified or untracked files in tracked paths exist, write a warning to stderr listing them and exit 0 (or exit 1 if `--strict`). The RC-7 forcing function.
  - `tests/workflow/test_cli.py` exercises each subcommand against a tmp `.workflow/` directory. The `verify-workspace` test creates a tmp git repo, adds an untracked file in a tracked path, asserts the CLI surfaces the warning. (See `test-coverage-standard.md` §3 + §4 for subprocess + exception payload obligations.)
  - All CLI failures exit with a non-zero code and write a `WorkflowError`-class message to stderr including the offending field/file (§4 payload obligation).
  - The CLI module docstring must explicitly state the RC-7 link: "`verify-workspace` exists because two W-001-cycle instances of stale-workspace-as-truth (RC-7) surfaced the failure mode."

- **Out of scope**: Claude Code hook configuration (impl-5); the auto-trigger glue that calls `workflow advance` on session start (impl-6).

### W-001-impl-5 — Claude Code SessionStart hook

- **What**: `.claude/settings.json` integration that calls `workflow status` + `workflow verify-workspace` on every Claude Code session start. The hook is Claude-Code-specific automation on top of the CLI primitive; it does not duplicate logic.
- **Where**:
  - Modify (or create if absent): `.claude/settings.json`.
  - New: `docs/process/session-start-hook.md` — short doc describing what the hook does, the dependency on the CLI, and how to disable for sessions that explicitly opt out.
- **Why**: R0-A-7 #2 lock — hook layer atop the CLI. Decoupled means: hook never reads `.workflow/` directly; it shells out to `workflow status` and `workflow verify-workspace` and surfaces output.
- **Acceptance**:
  - `.claude/settings.json` `hooks` section gains one `SessionStart` entry running the CLI (use `uv run workflow status` + `uv run workflow verify-workspace` or an inlined shell command — choose what matches existing repo precedent).
  - The hook's exit code does NOT block session startup even on warnings — session-start is informational only. (A blocking forcing function would be wrong here: senior may legitimately work on multiple tasks in one session.)
  - `docs/process/session-start-hook.md` cross-links ADR-008 Decision 9 (session-start trigger) and the CLI module.
  - The hook itself contains no logic beyond the CLI invocation — verified by reading the settings.json diff.

- **Out of scope**: any logic that isn't a CLI shell-out (decoupling is the design); CI integration (Decision 9 forbids that path).

### W-001-impl-6 — Auto-trigger glue + end-to-end integration test

- **What**: Wire the transition library, CLI, and io module together so that `workflow advance` (impl-4) correctly fires the two auto-trigger transitions (Decision 1 auto table) when the right artifacts appear. Plus one end-to-end test exercising a synthetic task through every state.
- **Where**:
  - Modify: `src/orchestrator/workflow/cli.py` (the `advance` subcommand was a stub in impl-4; this commit fills its body).
  - New: `tests/workflow/test_integration.py`.
- **Why**: ADR-008 Decision 1 (transition rules) + Decision 9 (session-start trigger) — this commit is the moment the harness becomes alive. End-to-end test is `test-coverage-standard.md` §1 (cross-module integration).
- **Acceptance**:
  - `workflow advance` reads `.workflow/{task-id}.yaml`, builds `ArtifactSnapshot` from git (file existence checks + frontmatter parsing of any review files present) and `GateSnapshot` from `evaluate_merge_clean`, calls `next_state`, and either writes the new state file or exits with "no transition fires" if `next_state` returned None.
  - The artifact-snapshot builder filters to recognized review filenames (`plan-vs-impl.md`, `R0-A.md`, `R0-B.md`, `R1-A.md`, `R1-B.md`, …) before calling `parse_verdict` — stub §5.2's side-channel-no-op invariant lives at this filter.
  - State-file writes use a write-and-rename pattern (`pathlib.Path.replace`) so partial writes never land. §3 cleanup coverage.
  - `test_integration.py` test `test_e2e_synthetic_task_traverses_all_states`:
    - Set up a tmp git repo + tmp `.workflow/` directory.
    - Create `.workflow/SYNTH-001.yaml` at `state: awaiting_brief`.
    - Sequentially: create brief → `workflow advance` → assert `awaiting_senior_plan`; create senior plan → advance → assert `awaiting_architect_accept`; flip ADR status (synthetic) → advance → `awaiting_junior_impl`; create junior commit → advance → `awaiting_senior_plan_vs_impl`; create `plan-vs-impl.md` with `verdict: clean` → advance → `awaiting_R0_A`; create `R0-A.md` with `verdict: clean` AND merge-clean → advance → `awaiting_PR_merge`; record PR merge → advance → `closed`.
    - Source ≠ sink assertion: the `task_id` written into `SYNTH-001.yaml` must equal `"SYNTH-001"` AND must differ from the test's fixture default (catch the case where the harness silently uses a hard-coded id).
  - One blocking-path test: create `R0-A.md` with `verdict: blocking` → `workflow advance` → state transitions to `awaiting_architect_decision`, not `awaiting_PR_merge`.
  - One merge-conflict-path test: create `R0-A.md` with `verdict: clean` BUT make `evaluate_merge_clean` return False (mock subprocess) → state transitions to `awaiting_architect_decision`, not `awaiting_PR_merge` (Decision 8 enforcement).
  - One rework-path test: `awaiting_architect_decision` + override to `awaiting_junior_impl` → `cycle` increments by 1 (Decision 11).
  - All tests green; mypy strict; ruff clean.

- **Out of scope**: state-machine warnings on cycle >= 4 (impl-2's design choice — already in `record_override`); bootstrap of W-001-impl.yaml (impl-7); the contributing.md Q3 sub-rule edit (impl-8).

### W-001-impl-7 — Bootstrap `.workflow/W-001-impl.yaml`

- **What**: Create `.workflow/W-001-impl.yaml` — the **first real state file** the harness has ever produced. Its initial state at this commit is the state W-001-impl itself is in at this commit; choose precisely.
- **Where**:
  - New: `.workflow/W-001-impl.yaml`.
- **Why**: ADR-008 Decision 12 — "the very first `.workflow/{task-id}.yaml` written will be `.workflow/W-001-impl.yaml`, created when the impl task starts." This commit is the moment.
- **Acceptance**:
  - File contents:
    ```yaml
    task_id: W-001-impl
    state: awaiting_senior_plan_vs_impl
    cycle: 1
    last_transition_at: <ISO-8601 UTC at commit time>
    override_history: []
    requires_cross_family_review: false
    ```
  - `state` is `awaiting_senior_plan_vs_impl` because at this commit junior has pushed impl-1 through impl-6 (the impl work) and the next gated artifact is the senior plan-vs-impl review. (At impl-9 land, the state advances; that's impl-9's responsibility.)
  - The file validates against the `TaskState` Pydantic model from impl-1. The commit body includes one line: "Validated locally via `uv run python -c 'from orchestrator.workflow.schema import TaskState; import yaml; TaskState.model_validate(yaml.safe_load(open(\".workflow/W-001-impl.yaml\")))'`".
  - No `.workflow/P0.yaml`, `.workflow/P1.1.yaml`, `.workflow/P1.2.yaml` retroactive bootstrapping — Decision 12 explicitly says no.

- **Out of scope**: any additional `.workflow/*.yaml` file; `workflow-init` CLI usage (this commit hand-writes the file because the bootstrap is the only-once event).

### W-001-impl-8 — Doc updates + RC-1 graduation

- **What**: Touch the four non-code surfaces that ADR-008 + the new harness imply per `contributing.md` Q3, and land the RC-1 forcing function (pre-edit grep sub-rule).
- **Where**:
  - Modify: `handoff.md` — new §17 or extend §16 covering the state machine surface and the CLI entry point.
  - Modify: `docs/process/senior-planner.md` — add a row to "Where your outputs go" table for `.workflow/{task-id}.yaml`; cross-link ADR-008 in the role description.
  - Modify: `docs/contributing.md` — add the RC-1 pre-edit grep sub-bullet under Q3 (per workflow-overview.md §6 graduation status).
  - Modify: `docs/process/workflow-overview.md` §5 to reflect implementation landed (status updates the implementation references from "lives in W-001-impl" to "lives at `src/orchestrator/workflow/`").
- **Why**: `contributing.md` Q3 5-surface scan obligation; RC-1 graduation per P1.2 retro + workflow-overview.md §6 "Ready to graduate — W-001-impl lands `contributing.md` Q3 sub-bullet."
- **Acceptance**:
  - RC-1 edit in `contributing.md` Q3: add a sub-bullet (precise wording from P1.2 retro §3 RC-1): *"For each surface listed in the scan, grep the file for pre-edit values that the schema change rendered obsolete and confirm they are absent. A `Status: Done` row in the followup tracking table is not legitimately checked until this grep is clean."*
  - `handoff.md` change cross-links ADR-008 and explains briefly that workflow sequencing now lives in `.workflow/` rather than chat memory.
  - `senior-planner.md` output-paths table gains the `.workflow/{task-id}.yaml` row.
  - `workflow-overview.md` §5 status line flips from "implementation lives in W-001-impl" to "implementation at `src/orchestrator/workflow/`; CLI: `workflow` entry-point; SessionStart hook in `.claude/settings.json`".
  - 5-surface scan **applied to this commit** by junior in the commit message tracking table.
  - **Apply the RC-1 pre-edit grep sub-rule to this commit's own edits.** For each surface (`handoff.md`, `senior-planner.md`, `contributing.md`, `workflow-overview.md`), grep for any pre-edit phrasing the impl renders stale (e.g., "implementation lives in W-001-impl" should not appear elsewhere after impl-8 lands). This is the first commit that *uses* RC-1, not just *codifies* it.

- **Out of scope**: edits to chat-history.md (process history doc, not spec); edits to README.md (explicitly excluded by Q3); edits to ADR-008 itself (source surface).

### W-001-impl-9 — Landing commit + 5-surface scan + state advance

- **What**: The closing commit. Tracking table covering all nine impl-* tasks. Full 5-surface scan report. Advance `.workflow/W-001-impl.yaml` to `awaiting_R0_A` (junior is done pushing) — and/or `closed` if the architect merges this PR directly without separate R0-A. Whichever, the file MUST end in a state consistent with project reality at merge.
- **Where**:
  - Modify: `.workflow/W-001-impl.yaml` — advance `state` from `awaiting_senior_plan_vs_impl` (impl-7's initial value) to whatever the operational reality is at the moment of impl-9 commit. Document the choice in the commit body.
  - Possible touches: any final 5-surface scan companion edits surfaced during scan execution.
- **Why**: `contributing.md` Q3 5-surface scan + `feedback_review_followup_tracking.md` tracking table + ADR-008 Decision 12 (the W-001-impl state file evolves through real states, not artificially preserved).
- **Acceptance**:
  - Tracking table in commit body lists all 9 W-001-impl-* tasks with explicit `Done | Skipped (reason) | Disagreed (proposing X)` status.
  - 5-surface scan report enumerates every surface touched across the whole PR (src, yaml/state-file, ADR cross-links, architecture docs, narrative); RC-1 sub-rule applied to each surface (pre-edit grep clean).
  - State-file advance: senior recommends `state: awaiting_senior_plan_vs_impl` remains (junior pushed; senior runs plan-vs-impl next per `senior-planner.md`). At PR merge time, architect or a separate state-advance commit moves to `closed`. **Junior does NOT pre-advance to `closed` in this commit** — premature inscription violates the auto-trigger gating from Decision 1 (PR merge is architect-gated).
  - `pytest` green; `ruff check` clean; `ruff format --check` clean; `mypy --strict src tests` clean.
  - Commit body explicitly notes whether `workflow verify-workspace` was run before push; if it surfaced any divergence, name it.

- **Out of scope**: writing the senior plan-vs-impl review (that's a different session entirely); the architect merge action (architect-gated per Decision 1).

## 3. Execution order

Strictly sequential 1 → 9. No parallelism; each impl-* commit depends on the prior ones:

- impl-1 (schema) gates impl-2 (transitions consume the schema types) and impl-7 (bootstrap validates against schema).
- impl-2 (transitions) gates impl-4 (CLI calls transition functions) and impl-6 (integration glues CLI to transitions).
- impl-3 (frontmatter convention doc) can in principle land in parallel with impl-4/5/6 but lands before impl-6 so the integration test references the canonical contract.
- impl-4 (CLI) gates impl-5 (hook shells out to CLI) and impl-6 (advance subcommand fills its body).
- impl-5 (hook) and impl-6 (auto-trigger glue) are independent siblings of impl-4 — either order works; recommend impl-5 first (smaller) then impl-6 (test-heavy).
- impl-7 (bootstrap state file) depends on impl-1 (schema validates the file) and is conceptually independent of impl-2/3/4/5/6 — but lands after all of them so the first state file reflects accurate current state.
- impl-8 (doc updates) can in principle land at any time but should land late so the doc edits reflect implemented reality.
- impl-9 (landing) is always last.

Single atomic PR per project convention (P1.2-C2/C3/C4 precedent). 9 commits in one PR; reviewer reads the full series.

## 4. Forcing functions to apply

- **5-surface scan** (`contributing.md` Q3): fires hard in impl-8 (doc updates touch 4 surfaces); fires also in impl-9 (full PR-level scan). The new sub-rule (impl-8 graduates RC-1 to `contributing.md`) is **applied for the first time in impl-8 itself** — RC-1 is both codified and exercised in the same commit.
- **Tracking table in commit message** (`feedback_review_followup_tracking.md`): every impl-* commit body leads with a single-row table; impl-9's commit body contains the full 9-row composite table.
- **Constitutional tests**:
  - `test_constitution_no_llm_calls_in_workflow_module` — new, lands in impl-2; load-bearing from that commit forward.
  - `test_constitution_no_llm_calls_in_autonomy_module` — must remain green throughout; nothing in W-001-impl touches autonomy module.
  - All other constitutional tests (15 as of W-001 close per workflow-overview.md §4) remain green every commit.
- **Test coverage standard 6 categories** (`docs/architecture/test-coverage-standard.md`): applied per impl-* task per the per-task acceptance criteria. Summary:
  - §1 cross-module: impl-6 (integration test, source ≠ sink on `task_id`).
  - §2 concurrency: N/A across the whole PR (sessions are human-initiated); explicitly stated in impl-2's module docstring.
  - §3 cleanup: impl-2 (subprocess `git merge-tree` timeout + context manager); impl-6 (write-and-rename for state files).
  - §4 exception payloads: impl-2 (`WorkflowError` carries `task_id` + `path`); impl-4 (CLI failures stderr payloads).
  - §5 boundary validators: impl-2 (`parse_verdict` rejects invalid values); impl-1 (`OverrideEntry.actor` Literal).
  - §6 schema invariants: impl-1 (`TaskState`, `OverrideEntry`); impl-2 (`ArtifactSnapshot`, `GateSnapshot`).
- **PR template Q1–Q4** (`contributing.md`): every commit body answers Q1 ("No LLM calls — verified by constitutional test"), Q2 (decision-trace obligations — N/A for workflow harness; sessions write traces in their natural artifacts, the state machine does not invent new decision functions that need traces beyond the override `reason` field which is enforced at impl-1 schema level), Q3 (5-surface scan — most commits N/A until impl-8/9), Q4 (coverage standard).

No new forcing function proposed by senior beyond RC-1 graduation in impl-8.

## 5. Where I'd push back

Four items not pinned by the brief / ADR / architect locks that senior is calling now; flag any of these in R0-A if you disagree.

1. **Side-channel artifact filtering at impl-6, not impl-2** (stub §5.2). I'm pushing the side-channel-no-op responsibility to the artifact-snapshot builder (impl-6's auto-trigger glue) rather than to `parse_verdict` (impl-2's transition library). Reason: `parse_verdict` is a pure parser; it should raise on garbage input, not silently no-op. The filter belongs at the boundary that decides what to feed it. If you'd rather have `parse_verdict` also be a silent no-op on non-review filenames, flag — impl-2 changes.

2. **`cycle >= 4` as warning, not error** (R0-A-4). I'm implementing this as a stderr warning in `record_override`, not a `WorkflowError` raise. Reason: cycle-count semantics are architect-judgement-driven per Decision 11; the harness's job is to surface, not to block. If you want it as a blocking error, impl-2 changes — but I judge architect-block is more appropriate than harness-block.

3. **impl-7's initial state choice = `awaiting_senior_plan_vs_impl`** (not `awaiting_brief` or `awaiting_senior_plan` or `closed`). At impl-7 commit time, junior has pushed impl-1 through impl-6; the next artifact owed by anyone is senior's plan-vs-impl review (this very document is the plan; impl-7 is junior's push commit; plan-vs-impl is what comes next). I considered `awaiting_junior_impl` (still pushing) but that's untrue at the moment of impl-7 land — junior IS pushing right now, the next state-pinning artifact is the review. Architect can override at merge time per Decision 10. Flag if you want a different initial state.

4. **No retroactive `.workflow/` for W-001 (the parent task)**. ADR-008 Decision 12 says no retroactive bootstrapping for closed P1.x; by symmetry, the parent W-001 (which closed via PR #4 / `819d8f5`) does not get a state file. The plan honors this implicitly. If you want a retroactive `.workflow/W-001.yaml` (state: closed) for narrative completeness, flag — it's a one-line addition in impl-7 but conceptually inconsistent with Decision 12.

If none of these need challenge, junior proceeds. Senior plan-vs-impl review fires after impl-9 push.

## 6. Distance test

ADR-008 was Accepted 2026-05-21; the impl-1 floor was 2026-05-22. Today (2026-05-26) is 5 days past the floor — the inscribing-moment distance test (Y substrate per RC-8) has been honored. Impl-1 through impl-9 land in sequence in one session is acceptable: the architectural inscription happened five days ago; the impl is mechanical given the accepted ADR.

If the architect's interpretation of RC-8 substrate evolves between W-001-impl land and W-001 close, this plan does not pre-commit to either α/β/γ — the choice is W-001 close-out scope, not W-001-impl scope.

## 7. Length budget

This plan is ~3000 words excluding the per-task code blocks. Within the senior-planner.md calibration: P1.2-C4 senior plan (7 commits) was ~3200 words; W-001-impl is one commit longer (9) and similarly dense.
