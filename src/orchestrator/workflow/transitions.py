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
    # None = legacy plan (no frontmatter) → route through awaiting_architect_accept.
    # False = frontmatter present, no `adr` key → skip awaiting_architect_accept.
    # True = frontmatter present with `adr` key → route through awaiting_architect_accept.
    plan_has_adr: bool | None = None
    # W-005 Amendment 2: presence of any architect-routing*.md in
    # docs/process/reviews/{task-id}/ — triggers
    # awaiting_architect_decision → awaiting_senior_revision.
    architect_routing_exists: bool = False


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
        # plan_has_adr=False: frontmatter present, no `adr` key → no-ADR task, skip
        # accept gate (W-002-2b). plan_has_adr=None (legacy) or True → accept gate.
        if artifacts.plan_has_adr is False:
            return WorkflowState.AWAITING_JUNIOR_IMPL
        return WorkflowState.AWAITING_ARCHITECT_ACCEPT

    if current == WorkflowState.AWAITING_ARCHITECT_ACCEPT and artifacts.adr_status == "accepted":
        return WorkflowState.AWAITING_JUNIOR_IMPL

    if current == WorkflowState.AWAITING_JUNIOR_IMPL and artifacts.junior_impl_commit_present:
        return WorkflowState.AWAITING_SENIOR_PLAN_VS_IMPL

    if current == WorkflowState.AWAITING_PR_MERGE and artifacts.pr_merged:
        return WorkflowState.CLOSED

    # --- Auto-triggered transitions ----------------------------------------

    # Route B (ADR-008 Amendment 1, W-005): R0-A fires regardless of plan-vs-impl
    # verdict. The verdict is captured in the snapshot for joint-verdict evaluation
    # at AWAITING_R0_A; it does not short-circuit this transition.
    if (
        current == WorkflowState.AWAITING_SENIOR_PLAN_VS_IMPL
        and artifacts.plan_vs_impl_verdict != "absent"
    ):
        return WorkflowState.AWAITING_R0_A

    # Joint-verdict evaluation (ADR-008 Amendment 1, W-005): both plan_vs_impl
    # AND r0_a verdicts must be clean (plus merge_clean) to advance to PR_MERGE.
    # Any non-clean from either review routes to architect_decision.
    if current == WorkflowState.AWAITING_R0_A:
        if artifacts.r0_a_verdict == "absent":
            return None  # R0-A not yet pushed
        both_clean = artifacts.plan_vs_impl_verdict == "clean" and artifacts.r0_a_verdict == "clean"
        if both_clean and gates.merge_clean:
            return WorkflowState.AWAITING_PR_MERGE
        # Any non-clean OR merge-conflict → architect must rule.
        return WorkflowState.AWAITING_ARCHITECT_DECISION

    # AWAITING_ARCHITECT_DECISION → AWAITING_SENIOR_REVISION (ADR-008 Amendment 2,
    # W-005): when architect-routing*.md is committed, the architect's
    # alpha/beta/gamma routing decision is captured; senior begins routing
    # absorption (RC-10 verdict bump). Auto-triggered on artifact appearance.
    if current == WorkflowState.AWAITING_ARCHITECT_DECISION and artifacts.architect_routing_exists:
        return WorkflowState.AWAITING_SENIOR_REVISION

    # AWAITING_SENIOR_REVISION → next (ADR-008 Amendment 2, W-005): senior has
    # absorbed routing and bumped review verdicts. If both verdicts now clean,
    # re-enter AWAITING_R0_A (which will then evaluate joint-verdict + merge
    # for PR_MERGE). If still non-clean, second routing round needed.
    if current == WorkflowState.AWAITING_SENIOR_REVISION:
        if artifacts.r0_a_verdict == "absent" or artifacts.plan_vs_impl_verdict == "absent":
            return None  # Senior hasn't re-committed reviews yet
        both_clean = artifacts.plan_vs_impl_verdict == "clean" and artifacts.r0_a_verdict == "clean"
        if both_clean:
            return WorkflowState.AWAITING_R0_A
        # Still non-clean → architect rules a second time.
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
    is_rework = (
        override.from_state == WorkflowState.AWAITING_ARCHITECT_DECISION
        and override.to_state == WorkflowState.AWAITING_JUNIOR_IMPL
    )
    update: dict[str, object] = {
        "state": override.to_state,
        "last_transition_at": override.timestamp,
        "override_history": [*state.override_history, override],
    }
    if is_rework:
        new_cycle = state.cycle + 1
        update["cycle"] = new_cycle
        # ADR-008 Decision 16 (W-006): a rework starts a NEW cycle, so re-stamp
        # the cycle-relative boundary. This is the ONLY override that re-stamps
        # it (init is the other stamp site); all other overrides + every advance
        # leave cycle_started_at untouched.
        update["cycle_started_at"] = override.timestamp
        if new_cycle >= 4:
            print(
                f"WARNING: task {state.task_id!r} is entering cycle {new_cycle}. "
                "High cycle count often indicates wrong task scope — "
                "consider halting and re-briefing (ADR-008 Decision 11).",
                file=sys.stderr,
            )

    return state.model_copy(update=update)


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
