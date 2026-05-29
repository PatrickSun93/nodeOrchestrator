"""End-to-end integration tests for the workflow harness.

Covers: full state traversal (all 7 transitions), blocking-path routing,
merge-conflict-path routing, rework-path cycle increment.

§1 cross-module: advance wires cli → transitions → io → filesystem.
§3 cleanup: state files written atomically (write_state uses .replace).
Source ≠ sink: task_id written into state file is asserted to equal
"SYNTH-001" and differ from any internal default.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from unittest.mock import patch

import pytest

from orchestrator.workflow.cli import build_artifact_snapshot, cmd_advance
from orchestrator.workflow.io import read_state, write_state
from orchestrator.workflow.schema import TaskState, WorkflowState

_PAST = datetime(2020, 1, 1, 0, 0, 0, tzinfo=UTC)
_TASK = "SYNTH-001"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Initialize a bare git repo in tmp_path. Returns tmp_path."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "commit.gpgsign", "false"],
        check=True,
        capture_output=True,
    )
    return tmp_path


def _wdir(repo: Path) -> Path:
    d = repo / ".workflow"
    d.mkdir(exist_ok=True)
    return d


def _advance(repo: Path, task_id: str = _TASK) -> int:
    """Call cmd_advance for task_id in repo."""
    import argparse

    args = argparse.Namespace(
        workflow_dir=str(repo / ".workflow"),
        task_id=task_id,
    )
    return cmd_advance(args)


def _init_state(
    wdir: Path,
    task_id: str = _TASK,
    state: WorkflowState = WorkflowState.AWAITING_BRIEF,
    last_transition_at: datetime = _PAST,
) -> None:
    """Write a state file with a known past last_transition_at."""
    s = TaskState(
        task_id=task_id,
        state=state,
        cycle=1,
        last_transition_at=last_transition_at,
    )
    write_state(s, wdir / f"{task_id}.yaml")


def _make_brief(repo: Path, task_id: str = _TASK) -> None:
    d = repo / "docs" / "process" / "architect-briefs"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{task_id}.md").write_text(f"# Brief for {task_id}\n", encoding="utf-8")


def _make_senior_plan(repo: Path, task_id: str = _TASK) -> None:
    d = repo / "docs" / "process" / "senior-plans"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{task_id}.md").write_text(f"# Plan for {task_id}\n", encoding="utf-8")


def _make_adr(
    repo: Path,
    task_id: str = _TASK,
    status: Literal["Proposed", "Accepted"] = "Accepted",
) -> None:
    d = repo / "docs" / "decisions"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"ADR-{task_id}.md").write_text(f"# ADR\n\nStatus: {status}\n", encoding="utf-8")


def _git_commit(repo: Path, msg: str = "junior impl commit") -> None:
    """Make an empty git commit in repo."""
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-m", msg],
        check=True,
        capture_output=True,
    )


def _make_review(
    repo: Path,
    filename: str,
    verdict: Literal["clean", "blocking", "needs_architect"],
    task_id: str = _TASK,
) -> None:
    d = repo / "docs" / "process" / "reviews" / task_id
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_text(
        f"---\ntask_id: {task_id}\nround: {filename.removesuffix('.md')}\n"
        f"verdict: {verdict}\nfindings_count:\n  red: 0\n  yellow: 0\n  green: 1\n---\nbody\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# E2E: full traversal of all states
# ---------------------------------------------------------------------------


def test_e2e_synthetic_task_traverses_all_states(git_repo: Path) -> None:
    """Synthetic SYNTH-001 traverses all 7 ADR-008 Decision 1 transitions.

    Source ≠ sink: task_id written is verified to equal 'SYNTH-001',
    not an internal default (ADR-008 Decision 12 invariant check).
    """
    wdir = _wdir(git_repo)

    # --- awaiting_brief → awaiting_senior_plan (gated: brief published) ---
    _init_state(wdir, state=WorkflowState.AWAITING_BRIEF)
    # No brief yet → no transition
    with (
        patch("orchestrator.workflow.cli._is_pr_merged", return_value=False),
        patch("orchestrator.workflow.cli.evaluate_merge_clean", return_value=True),
    ):
        rc = _advance(git_repo)
    assert rc == 0
    assert read_state(wdir / f"{_TASK}.yaml").state == WorkflowState.AWAITING_BRIEF

    _make_brief(git_repo)
    with (
        patch("orchestrator.workflow.cli._is_pr_merged", return_value=False),
        patch("orchestrator.workflow.cli.evaluate_merge_clean", return_value=True),
    ):
        rc = _advance(git_repo)
    assert rc == 0
    s = read_state(wdir / f"{_TASK}.yaml")
    assert s.state == WorkflowState.AWAITING_SENIOR_PLAN
    assert s.task_id == _TASK  # source ≠ sink: not a hard-coded default

    # --- awaiting_senior_plan → awaiting_architect_accept ---
    _make_senior_plan(git_repo)
    with (
        patch("orchestrator.workflow.cli._is_pr_merged", return_value=False),
        patch("orchestrator.workflow.cli.evaluate_merge_clean", return_value=True),
    ):
        rc = _advance(git_repo)
    assert rc == 0
    assert read_state(wdir / f"{_TASK}.yaml").state == WorkflowState.AWAITING_ARCHITECT_ACCEPT

    # --- awaiting_architect_accept → awaiting_junior_impl (ADR accepted) ---
    _make_adr(git_repo, status="Accepted")
    with (
        patch("orchestrator.workflow.cli._is_pr_merged", return_value=False),
        patch("orchestrator.workflow.cli.evaluate_merge_clean", return_value=True),
    ):
        rc = _advance(git_repo)
    assert rc == 0
    s = read_state(wdir / f"{_TASK}.yaml")
    assert s.state == WorkflowState.AWAITING_JUNIOR_IMPL
    # Reset last_transition_at to past so the next commit counts as "after"
    write_state(s.model_copy(update={"last_transition_at": _PAST}), wdir / f"{_TASK}.yaml")

    # --- awaiting_junior_impl → awaiting_senior_plan_vs_impl (junior commit) ---
    # No commit yet → no transition
    with (
        patch("orchestrator.workflow.cli._is_pr_merged", return_value=False),
        patch("orchestrator.workflow.cli.evaluate_merge_clean", return_value=True),
        patch("orchestrator.workflow.cli._has_junior_impl_commits", return_value=False),
    ):
        rc = _advance(git_repo)
    assert rc == 0
    assert read_state(wdir / f"{_TASK}.yaml").state == WorkflowState.AWAITING_JUNIOR_IMPL

    _git_commit(git_repo)
    with (
        patch("orchestrator.workflow.cli._is_pr_merged", return_value=False),
        patch("orchestrator.workflow.cli.evaluate_merge_clean", return_value=True),
        patch("orchestrator.workflow.cli._has_junior_impl_commits", return_value=True),
    ):
        rc = _advance(git_repo)
    assert rc == 0
    assert read_state(wdir / f"{_TASK}.yaml").state == WorkflowState.AWAITING_SENIOR_PLAN_VS_IMPL

    # --- awaiting_senior_plan_vs_impl → awaiting_R0_A (plan-vs-impl clean) ---
    _make_review(git_repo, "plan-vs-impl.md", "clean")
    with (
        patch("orchestrator.workflow.cli._is_pr_merged", return_value=False),
        patch("orchestrator.workflow.cli.evaluate_merge_clean", return_value=True),
    ):
        rc = _advance(git_repo)
    assert rc == 0
    assert read_state(wdir / f"{_TASK}.yaml").state == WorkflowState.AWAITING_R0_A

    # --- awaiting_R0_A → awaiting_PR_merge (R0-A clean + merge-clean) ---
    _make_review(git_repo, "R0-A.md", "clean")
    with (
        patch("orchestrator.workflow.cli._is_pr_merged", return_value=False),
        patch("orchestrator.workflow.cli.evaluate_merge_clean", return_value=True),
    ):
        rc = _advance(git_repo)
    assert rc == 0
    assert read_state(wdir / f"{_TASK}.yaml").state == WorkflowState.AWAITING_PR_MERGE

    # --- awaiting_PR_merge → closed (PR merged) ---
    with (
        patch("orchestrator.workflow.cli._is_pr_merged", return_value=True),
        patch("orchestrator.workflow.cli.evaluate_merge_clean", return_value=True),
    ):
        rc = _advance(git_repo)
    assert rc == 0
    final = read_state(wdir / f"{_TASK}.yaml")
    assert final.state == WorkflowState.CLOSED
    assert final.task_id == _TASK  # final source ≠ sink check


# ---------------------------------------------------------------------------
# Blocking path: R0-A blocking → awaiting_architect_decision
# ---------------------------------------------------------------------------


def test_blocking_path_r0a_routes_to_architect_decision(git_repo: Path) -> None:
    wdir = _wdir(git_repo)
    _init_state(wdir, state=WorkflowState.AWAITING_R0_A)
    _make_review(git_repo, "R0-A.md", "blocking")

    with (
        patch("orchestrator.workflow.cli._is_pr_merged", return_value=False),
        patch("orchestrator.workflow.cli.evaluate_merge_clean", return_value=True),
    ):
        rc = _advance(git_repo)
    assert rc == 0
    assert read_state(wdir / f"{_TASK}.yaml").state == WorkflowState.AWAITING_ARCHITECT_DECISION


# ---------------------------------------------------------------------------
# Merge-conflict path: R0-A clean but conflicts → awaiting_architect_decision
# ---------------------------------------------------------------------------


def test_merge_conflict_path_routes_to_architect_decision(git_repo: Path) -> None:
    wdir = _wdir(git_repo)
    _init_state(wdir, state=WorkflowState.AWAITING_R0_A)
    _make_review(git_repo, "R0-A.md", "clean")

    with (
        patch("orchestrator.workflow.cli._is_pr_merged", return_value=False),
        patch("orchestrator.workflow.cli.evaluate_merge_clean", return_value=False),
    ):
        rc = _advance(git_repo)
    assert rc == 0
    assert read_state(wdir / f"{_TASK}.yaml").state == WorkflowState.AWAITING_ARCHITECT_DECISION


# ---------------------------------------------------------------------------
# Cycle-boundary artifact filter (ADR-008 Decision 14 / W-005 Amendment)
# Prevents cycle-2 advance from cascading through cycle-1 review files.
# ---------------------------------------------------------------------------


def test_cycle_boundary_filter_stale_review_treated_as_absent(git_repo: Path) -> None:
    """P1.6 cycle-2 scenario: review file committed in cycle 1 must not
    trigger transitions when state is in cycle 2 (last_transition_at is
    after the review's last commit)."""
    wdir = _wdir(git_repo)

    # Cycle 1: write + commit a clean R0-A.
    _make_review(git_repo, "plan-vs-impl.md", "clean")
    _make_review(git_repo, "R0-A.md", "clean")
    subprocess.run(
        ["git", "-C", str(git_repo), "add", "."],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(git_repo), "commit", "-m", "cycle-1 reviews"],
        check=True,
        capture_output=True,
    )

    # State is in cycle 2: last_transition_at AFTER the cycle-1 commit.
    future = datetime.now(UTC) + timedelta(hours=1)
    _init_state(wdir, state=WorkflowState.AWAITING_R0_A, last_transition_at=future)

    # advance must NOT see the cycle-1 reviews; no transition fires.
    with patch("orchestrator.workflow.cli._is_pr_merged", return_value=False):
        rc = _advance(git_repo)
    assert rc == 0
    # State unchanged (no transition because both verdicts filtered to 'absent').
    assert read_state(wdir / f"{_TASK}.yaml").state == WorkflowState.AWAITING_R0_A


def test_cycle_boundary_filter_fresh_review_counts(git_repo: Path) -> None:
    """Inverse: review committed AFTER last_transition_at IS in cycle."""
    wdir = _wdir(git_repo)

    # State first (with last_transition_at = past).
    _init_state(
        wdir,
        state=WorkflowState.AWAITING_SENIOR_PLAN_VS_IMPL,
        last_transition_at=_PAST,
    )

    # Now commit the review AFTER last_transition_at.
    _make_review(git_repo, "plan-vs-impl.md", "clean")
    subprocess.run(
        ["git", "-C", str(git_repo), "add", "."],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(git_repo), "commit", "-m", "fresh plan-vs-impl"],
        check=True,
        capture_output=True,
    )

    # Route B: clean plan-vs-impl always → AWAITING_R0_A.
    rc = _advance(git_repo)
    assert rc == 0
    assert read_state(wdir / f"{_TASK}.yaml").state == WorkflowState.AWAITING_R0_A


# ---------------------------------------------------------------------------
# Rework path: override to awaiting_junior_impl increments cycle (Decision 11)
# ---------------------------------------------------------------------------


def test_rework_path_cycle_increments(git_repo: Path) -> None:
    wdir = _wdir(git_repo)
    _init_state(wdir, state=WorkflowState.AWAITING_ARCHITECT_DECISION)

    import argparse

    from orchestrator.workflow.cli import cmd_override

    args = argparse.Namespace(
        workflow_dir=str(wdir),
        task_id=_TASK,
        to_state="awaiting_junior_impl",
        reason="rework: R0-A finding resolved",
        actor="architect",
    )
    rc = cmd_override(args)
    assert rc == 0
    result = read_state(wdir / f"{_TASK}.yaml")
    assert result.cycle == 2
    assert result.state == WorkflowState.AWAITING_JUNIOR_IMPL


# ---------------------------------------------------------------------------
# build_artifact_snapshot: side-channel filter (stub §5.2)
# ---------------------------------------------------------------------------


def test_side_channel_file_does_not_reach_parse_verdict(git_repo: Path) -> None:
    """A README.md in the reviews dir must NOT be parsed as a review verdict.

    The artifact-snapshot builder only checks plan-vs-impl.md and R0-A.md
    (hard-coded paths). Other files are silently ignored.
    """
    wdir = _wdir(git_repo)
    task_state = TaskState(
        task_id=_TASK,
        state=WorkflowState.AWAITING_R0_A,
        cycle=1,
        last_transition_at=_PAST,
    )
    reviews_dir = git_repo / "docs" / "process" / "reviews" / _TASK
    reviews_dir.mkdir(parents=True, exist_ok=True)
    # Write a README without frontmatter — should NOT raise
    (reviews_dir / "README.md").write_text("no frontmatter here\n", encoding="utf-8")

    with (
        patch("orchestrator.workflow.cli._has_junior_impl_commits", return_value=False),
        patch("orchestrator.workflow.cli._is_pr_merged", return_value=False),
    ):
        snapshot = build_artifact_snapshot(_TASK, task_state, wdir)
    # README was ignored; r0_a_verdict is absent (R0-A.md doesn't exist)
    assert snapshot.r0_a_verdict == "absent"


# ---------------------------------------------------------------------------
# §1 cross-module: path-β task with plan-frontmatter ADR reference (W-002-1)
# ---------------------------------------------------------------------------


def test_e2e_path_beta_task_with_adr_advances(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§1 cross-module: SYNTH-002 plan declares `adr: ADR-099` in frontmatter.
    ADR-099-synth.md exists and is Accepted. State starts at
    awaiting_architect_accept; advance fires to awaiting_junior_impl.
    Source ≠ sink: task_id='SYNTH-002'; ADR filename='ADR-099-synth.md'.
    """
    task_id = "SYNTH-002"
    wdir = _wdir(git_repo)
    _init_state(wdir, task_id=task_id, state=WorkflowState.AWAITING_ARCHITECT_ACCEPT)

    # Write plan with adr frontmatter
    plans_dir = git_repo / "docs" / "process" / "senior-plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / f"{task_id}.md").write_text(
        "---\ntask_id: SYNTH-002\nadr: ADR-099\n---\n\n# Synth Plan\n",
        encoding="utf-8",
    )

    # Write ADR-099-synth.md — filename differs from task_id (source ≠ sink)
    decisions_dir = git_repo / "docs" / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    (decisions_dir / "ADR-099-synth.md").write_text(
        "# ADR-099 Synth\n\nStatus: Accepted\n",
        encoding="utf-8",
    )

    # _read_plan_frontmatter reads via _git_show (origin/main); mock to read from disk.
    # chdir so path.relative_to(Path.cwd()) resolves against git_repo root.
    monkeypatch.chdir(git_repo)

    def _fake_git_show(rel_path: str, ref: str = "origin/main") -> str | None:
        p = git_repo / rel_path
        return p.read_text(encoding="utf-8") if p.exists() else None

    monkeypatch.setattr("orchestrator.workflow.io._git_show", _fake_git_show)

    with (
        patch("orchestrator.workflow.cli._is_pr_merged", return_value=False),
        patch("orchestrator.workflow.cli.evaluate_merge_clean", return_value=True),
        patch("orchestrator.workflow.cli._has_junior_impl_commits", return_value=False),
    ):
        rc = _advance(git_repo, task_id)
    assert rc == 0

    s = read_state(wdir / f"{task_id}.yaml")
    assert s.state == WorkflowState.AWAITING_JUNIOR_IMPL
    assert s.task_id == task_id  # task_id differs from ADR filename 'ADR-099-synth.md'


# ---------------------------------------------------------------------------
# §1 cross-module: multi-ADR plan (W-002.5)
# ---------------------------------------------------------------------------


def test_e2e_multi_adr_plan_advances_when_all_accepted(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§1 cross-module: SYNTH-002.5 plan declares `adr: [ADR-098, ADR-099]`.
    Both Proposed → state stays at awaiting_architect_accept.
    Both Accepted → state advances to awaiting_junior_impl.
    Source ≠ sink: task_id='SYNTH-002.5'; ADR filenames differ from task_id.
    """
    task_id = "SYNTH-002.5"
    wdir = _wdir(git_repo)
    _init_state(wdir, task_id=task_id, state=WorkflowState.AWAITING_ARCHITECT_ACCEPT)

    plans_dir = git_repo / "docs" / "process" / "senior-plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / f"{task_id}.md").write_text(
        "---\ntask_id: SYNTH-002.5\nadr: [ADR-098, ADR-099]\n---\n\n# Synth Plan\n",
        encoding="utf-8",
    )

    decisions_dir = git_repo / "docs" / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    adr098 = decisions_dir / "ADR-098-foo.md"
    adr099 = decisions_dir / "ADR-099-bar.md"

    # _read_plan_frontmatter reads via _git_show (origin/main); mock to read from disk.
    # chdir so path.relative_to(Path.cwd()) resolves against git_repo root.
    monkeypatch.chdir(git_repo)

    def _fake_git_show(rel_path: str, ref: str = "origin/main") -> str | None:
        p = git_repo / rel_path
        return p.read_text(encoding="utf-8") if p.exists() else None

    monkeypatch.setattr("orchestrator.workflow.io._git_show", _fake_git_show)

    # Both Proposed → state stays
    adr098.write_text("# ADR-098\n\nStatus: Proposed\n", encoding="utf-8")
    adr099.write_text("# ADR-099\n\nStatus: Proposed\n", encoding="utf-8")

    with (
        patch("orchestrator.workflow.cli._is_pr_merged", return_value=False),
        patch("orchestrator.workflow.cli.evaluate_merge_clean", return_value=True),
        patch("orchestrator.workflow.cli._has_junior_impl_commits", return_value=False),
    ):
        rc = _advance(git_repo, task_id)
    assert rc == 0
    assert read_state(wdir / f"{task_id}.yaml").state == WorkflowState.AWAITING_ARCHITECT_ACCEPT

    # Both Accepted → state advances
    adr098.write_text("# ADR-098\n\nStatus: Accepted\n", encoding="utf-8")
    adr099.write_text("# ADR-099\n\nStatus: Accepted\n", encoding="utf-8")

    with (
        patch("orchestrator.workflow.cli._is_pr_merged", return_value=False),
        patch("orchestrator.workflow.cli.evaluate_merge_clean", return_value=True),
        patch("orchestrator.workflow.cli._has_junior_impl_commits", return_value=False),
    ):
        rc = _advance(git_repo, task_id)
    assert rc == 0
    s = read_state(wdir / f"{task_id}.yaml")
    assert s.state == WorkflowState.AWAITING_JUNIOR_IMPL
    assert s.task_id == task_id  # source ≠ sink: task_id ≠ 'ADR-098-foo.md' / 'ADR-099-bar.md'


# ---------------------------------------------------------------------------
# §3 atomic write: partial write never lands
# ---------------------------------------------------------------------------


def test_advance_atomic_write(git_repo: Path) -> None:
    """State file must not exist as a partial write after a successful advance."""
    wdir = _wdir(git_repo)
    _init_state(wdir, state=WorkflowState.AWAITING_BRIEF)
    _make_brief(git_repo)

    with (
        patch("orchestrator.workflow.cli._is_pr_merged", return_value=False),
        patch("orchestrator.workflow.cli.evaluate_merge_clean", return_value=True),
    ):
        rc = _advance(git_repo)
    assert rc == 0
    # Temp file must not exist (was replaced)
    assert not (wdir / f"{_TASK}.yaml.tmp").exists()
    # Real file must exist and be valid
    s = read_state(wdir / f"{_TASK}.yaml")
    assert s.state == WorkflowState.AWAITING_SENIOR_PLAN
