"""Pure-function state transition library for the workflow harness.

Implements ADR-008 Decisions 1 (transition table), 7 (frontmatter verdict),
8 (merge-clean precondition), 10 (override), 11 (rework cycle counter).

Concurrency note: sessions are human-initiated; the state machine is not
expected to be called concurrently within a single session. No locking is
implemented or needed. (test-coverage-standard.md §2 N/A — documented here.)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Literal, cast

import yaml
from pydantic import BaseModel, ConfigDict

from orchestrator.workflow.exceptions import WorkflowError
from orchestrator.workflow.schema import OverrideEntry, TaskState, WorkflowState


class ArtifactSnapshot(BaseModel):
    """Git-artifact view fed to next_state. Never reads files; caller builds."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    brief_exists: bool
    senior_plan_exists: bool
    adr_status: Literal["proposed", "accepted", "none"]
    junior_impl_commit_present: bool
    plan_vs_impl_verdict: Literal["clean", "blocking", "needs_architect", "absent"]
    r0_a_verdict: Literal["clean", "blocking", "needs_architect", "absent"]
    pr_merged: bool


class GateSnapshot(BaseModel):
    """Gate-status view fed to next_state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    merge_clean: bool
    tests_pass: bool = True  # treated as True for now; future ADRs may gate on real status


# ---------------------------------------------------------------------------
# parse_verdict
# ---------------------------------------------------------------------------

_VALID_VERDICTS = {"clean", "blocking", "needs_architect"}


def parse_verdict(
    review_file: Path,
) -> Literal["clean", "blocking", "needs_architect"]:
    """Read the YAML frontmatter from a review markdown file and return
    the `verdict` field.

    Missing or malformed frontmatter raises WorkflowError naming the file
    path and the missing key.

    Side-channel artifacts (retrospective candidate files, observation
    notes, the `architect-briefs/README.md`) are NOT review files and
    will raise here if accidentally parsed — by design. The auto-trigger
    glue (impl-6) filters to recognized review-file basenames before
    calling this function. See W-001-impl senior plan stub §5.2.
    """
    if not review_file.exists():
        raise WorkflowError(
            f"{review_file}: review file not found",
            path=review_file,
        )
    content = review_file.read_text(encoding="utf-8")
    if not content.startswith("---"):
        raise WorkflowError(
            f"{review_file}: missing YAML frontmatter (file must start with '---')",
            path=review_file,
        )
    end = content.find("\n---", 3)
    if end == -1:
        raise WorkflowError(
            f"{review_file}: unclosed YAML frontmatter block",
            path=review_file,
        )
    frontmatter_text = content[3:end]
    try:
        meta = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as exc:
        raise WorkflowError(
            f"{review_file}: YAML frontmatter parse error — {exc}",
            path=review_file,
        ) from exc
    if not isinstance(meta, dict) or "verdict" not in meta:
        raise WorkflowError(
            f"{review_file}: frontmatter missing required key 'verdict'",
            path=review_file,
        )
    verdict = meta["verdict"]
    if verdict not in _VALID_VERDICTS:
        raise WorkflowError(
            f"{review_file}: frontmatter verdict {verdict!r} is not one of "
            f"{sorted(_VALID_VERDICTS)}",
            path=review_file,
        )
    return cast("Literal['clean', 'blocking', 'needs_architect']", verdict)


# ---------------------------------------------------------------------------
# next_state
# ---------------------------------------------------------------------------


def next_state(
    current: WorkflowState,
    artifacts: ArtifactSnapshot,
    gates: GateSnapshot,
) -> WorkflowState | None:
    """Pure function. Returns the next state if the current
    (state, artifacts, gates) tuple matches a transition rule, else
    None (no auto-advance applicable). Never reads files; caller passes
    snapshots.

    Implements ADR-008 Decision 1 gated-transition table (all five rows)
    and two auto-trigger rows.

    Brief amendments while the task is past `awaiting_senior_plan` are
    no-ops: the artifact list does not include "brief modified" as an
    advancing event. Brief amendments while still in `awaiting_brief` are
    also no-ops (senior reads latest content at plan-write time).
    See W-001-impl senior plan stub §5.3 + R0-A-8.
    """
    # --- Gated transitions (architect must act) ----------------------------

    if current == WorkflowState.AWAITING_BRIEF and artifacts.brief_exists:
        return WorkflowState.AWAITING_SENIOR_PLAN

    if current == WorkflowState.AWAITING_SENIOR_PLAN and artifacts.senior_plan_exists:
        return WorkflowState.AWAITING_ARCHITECT_ACCEPT

    if current == WorkflowState.AWAITING_ARCHITECT_ACCEPT and artifacts.adr_status == "accepted":
        return WorkflowState.AWAITING_JUNIOR_IMPL

    if current == WorkflowState.AWAITING_JUNIOR_IMPL and artifacts.junior_impl_commit_present:
        return WorkflowState.AWAITING_SENIOR_PLAN_VS_IMPL

    if current == WorkflowState.AWAITING_PR_MERGE and artifacts.pr_merged:
        return WorkflowState.CLOSED

    # --- Auto-triggered transitions ----------------------------------------

    if current == WorkflowState.AWAITING_SENIOR_PLAN_VS_IMPL:
        if artifacts.plan_vs_impl_verdict == "clean":
            return WorkflowState.AWAITING_R0_A
        if artifacts.plan_vs_impl_verdict in ("blocking", "needs_architect"):
            return WorkflowState.AWAITING_ARCHITECT_DECISION

    if current == WorkflowState.AWAITING_R0_A:
        if artifacts.r0_a_verdict in ("blocking", "needs_architect"):
            return WorkflowState.AWAITING_ARCHITECT_DECISION
        if artifacts.r0_a_verdict == "clean" and gates.merge_clean:
            return WorkflowState.AWAITING_PR_MERGE
        if artifacts.r0_a_verdict == "clean" and not gates.merge_clean:
            # ADR-008 Decision 8: merge conflict detected
            return WorkflowState.AWAITING_ARCHITECT_DECISION

    return None


# ---------------------------------------------------------------------------
# record_override
# ---------------------------------------------------------------------------


def record_override(state: TaskState, override: OverrideEntry) -> TaskState:
    """Return a new TaskState with the override appended to override_history
    and `state` set to override.to_state. The input state is not mutated
    (Pydantic frozen). The caller writes the result.

    See ADR-008 Decision 10.

    Note: if state.cycle >= 4, a warning is emitted to stderr indicating
    that the task may have wrong scope (ADR-008 Decision 11 narrative).
    This is a surface signal, not a harness block — architect judgement
    governs.
    """
    new_cycle = state.cycle
    # Rework path: awaiting_architect_decision → awaiting_junior_impl increments cycle.
    # Both from_state AND to_state must match — the P1.3 bug was gating on to_state only
    # (ADR-008 Decision 11: cycle increments only on rework transitions).
    if (
        override.from_state == WorkflowState.AWAITING_ARCHITECT_DECISION
        and override.to_state == WorkflowState.AWAITING_JUNIOR_IMPL
    ):
        new_cycle = state.cycle + 1
        if new_cycle >= 4:
            print(
                f"WARNING: task {state.task_id!r} is entering cycle {new_cycle}. "
                "High cycle count often indicates wrong task scope — "
                "consider halting and re-briefing (ADR-008 Decision 11).",
                file=sys.stderr,
            )

    return state.model_copy(
        update={
            "state": override.to_state,
            "cycle": new_cycle,
            "last_transition_at": override.timestamp,
            "override_history": [*state.override_history, override],
        }
    )


# ---------------------------------------------------------------------------
# evaluate_merge_clean
# ---------------------------------------------------------------------------


def evaluate_merge_clean(branch: str, base: str = "origin/main") -> bool:
    """Run `git merge-tree {base} {branch}` (subprocess). Return True if
    no conflict markers in output, False otherwise.

    See ADR-008 Decision 8. Reads `origin/main` only — never local `main`
    — to avoid the ADR-Accept-timing-race described in W-001-impl stub §5.4.

    Raises:
        WorkflowError: if the subprocess call fails or times out.
    """
    try:
        result = subprocess.run(
            ["git", "merge-tree", base, branch],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkflowError(f"git merge-tree timed out after 30s for branch {branch!r}") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkflowError(f"git merge-tree failed for branch {branch!r}: {exc}") from exc
    return "<<<<<<<" not in result.stdout
