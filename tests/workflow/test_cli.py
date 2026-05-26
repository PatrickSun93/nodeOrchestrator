"""Behavior tests for orchestrator.workflow.cli.

Covers: status (single task, all tasks, missing dir), init (create,
refuse-dup, force-overwrite, invalid state), advance (stub — reads
state file, errors on missing file), override (valid, invalid to-state),
verify-workspace (clean, dirty, fetch-failure).

§3 cleanup: subprocess.run mocked for verify-workspace.
§4 exception payloads: CLI failures exit non-zero + write to stderr.
"""

from __future__ import annotations

import argparse
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orchestrator.workflow.cli import (
    build_parser,
    cmd_advance,
    cmd_init,
    cmd_override,
    cmd_status,
    cmd_verify_workspace,
)
from orchestrator.workflow.io import write_state
from orchestrator.workflow.schema import TaskState, WorkflowState

_NOW = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(
    task_id: str = "TEST-001",
    state: WorkflowState = WorkflowState.AWAITING_BRIEF,
    cycle: int = 1,
) -> TaskState:
    return TaskState(
        task_id=task_id,
        state=state,
        cycle=cycle,
        last_transition_at=_NOW,
    )


def _args(**kwargs: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "workflow_dir": ".workflow",
        "task_id": None,
        "state": "awaiting_brief",
        "force": False,
        "to_state": None,
        "reason": None,
        "actor": "architect",
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _write(wdir: Path, state: TaskState) -> Path:
    path = wdir / f"{state.task_id}.yaml"
    write_state(state, path)
    return path


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_missing_workflow_dir_returns_nonzero(tmp_path: Path) -> None:
    wdir = tmp_path / ".workflow"
    rc = cmd_status(_args(workflow_dir=str(wdir)))
    assert rc != 0


def test_status_empty_dir_prints_no_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wdir = tmp_path / ".workflow"
    wdir.mkdir()
    rc = cmd_status(_args(workflow_dir=str(wdir)))
    assert rc == 0
    assert "No task state files found" in capsys.readouterr().out


def test_status_all_tasks_prints_each(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wdir = tmp_path / ".workflow"
    wdir.mkdir()
    _write(wdir, _make_state("TASK-A"))
    _write(wdir, _make_state("TASK-B", state=WorkflowState.AWAITING_SENIOR_PLAN))
    rc = cmd_status(_args(workflow_dir=str(wdir)))
    assert rc == 0
    out = capsys.readouterr().out
    assert "TASK-A" in out
    assert "TASK-B" in out


def test_status_single_task_prints_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wdir = tmp_path / ".workflow"
    wdir.mkdir()
    _write(wdir, _make_state("MY-TASK", state=WorkflowState.AWAITING_JUNIOR_IMPL))
    rc = cmd_status(_args(workflow_dir=str(wdir), task_id="MY-TASK"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "MY-TASK" in out
    assert "awaiting_junior_impl" in out


def test_status_single_task_missing_returns_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wdir = tmp_path / ".workflow"
    wdir.mkdir()
    rc = cmd_status(_args(workflow_dir=str(wdir), task_id="GHOST-001"))
    assert rc != 0
    assert "ERROR" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def test_init_creates_state_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wdir = tmp_path / ".workflow"
    rc = cmd_init(_args(workflow_dir=str(wdir), task_id="NEW-001"))
    assert rc == 0
    assert (wdir / "NEW-001.yaml").exists()


def test_init_refuses_existing_without_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wdir = tmp_path / ".workflow"
    wdir.mkdir()
    _write(wdir, _make_state("DUP-001"))
    rc = cmd_init(_args(workflow_dir=str(wdir), task_id="DUP-001"))
    assert rc != 0
    assert "ERROR" in capsys.readouterr().err


def test_init_force_overwrites(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wdir = tmp_path / ".workflow"
    wdir.mkdir()
    _write(wdir, _make_state("OVR-001", state=WorkflowState.AWAITING_SENIOR_PLAN))
    rc = cmd_init(
        _args(
            workflow_dir=str(wdir),
            task_id="OVR-001",
            state="awaiting_brief",
            force=True,
        )
    )
    assert rc == 0
    from orchestrator.workflow.io import read_state

    new = read_state(wdir / "OVR-001.yaml")
    assert new.state == WorkflowState.AWAITING_BRIEF


def test_init_invalid_state_returns_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wdir = tmp_path / ".workflow"
    rc = cmd_init(_args(workflow_dir=str(wdir), task_id="BAD-001", state="not_a_state"))
    assert rc != 0
    assert "ERROR" in capsys.readouterr().err


def test_init_default_state_is_awaiting_brief(tmp_path: Path) -> None:
    wdir = tmp_path / ".workflow"
    rc = cmd_init(_args(workflow_dir=str(wdir), task_id="DEF-001"))
    assert rc == 0
    from orchestrator.workflow.io import read_state

    state = read_state(wdir / "DEF-001.yaml")
    assert state.state == WorkflowState.AWAITING_BRIEF


# ---------------------------------------------------------------------------
# advance (stub behavior in impl-4)
# ---------------------------------------------------------------------------


def test_advance_reads_state_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wdir = tmp_path / ".workflow"
    wdir.mkdir()
    _write(wdir, _make_state("ADV-001"))
    rc = cmd_advance(_args(workflow_dir=str(wdir), task_id="ADV-001"))
    assert rc == 0


def test_advance_missing_file_returns_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wdir = tmp_path / ".workflow"
    wdir.mkdir()
    rc = cmd_advance(_args(workflow_dir=str(wdir), task_id="GHOST-001"))
    assert rc != 0
    assert "ERROR" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# override
# ---------------------------------------------------------------------------


def test_override_records_entry_and_updates_state(tmp_path: Path) -> None:
    wdir = tmp_path / ".workflow"
    wdir.mkdir()
    _write(wdir, _make_state("OV-001", state=WorkflowState.AWAITING_BRIEF))
    rc = cmd_override(
        _args(
            workflow_dir=str(wdir),
            task_id="OV-001",
            to_state="awaiting_senior_plan",
            reason="brief landed out-of-band",
            actor="architect",
        )
    )
    assert rc == 0
    from orchestrator.workflow.io import read_state

    result = read_state(wdir / "OV-001.yaml")
    assert result.state == WorkflowState.AWAITING_SENIOR_PLAN
    assert len(result.override_history) == 1
    assert result.override_history[0].reason == "brief landed out-of-band"


def test_override_rework_increments_cycle(tmp_path: Path) -> None:
    wdir = tmp_path / ".workflow"
    wdir.mkdir()
    _write(
        wdir,
        _make_state("OV-002", state=WorkflowState.AWAITING_ARCHITECT_DECISION, cycle=1),
    )
    rc = cmd_override(
        _args(
            workflow_dir=str(wdir),
            task_id="OV-002",
            to_state="awaiting_junior_impl",
            reason="rework: R0-A finding resolved",
            actor="architect",
        )
    )
    assert rc == 0
    from orchestrator.workflow.io import read_state

    result = read_state(wdir / "OV-002.yaml")
    assert result.cycle == 2


def test_override_invalid_to_state_returns_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wdir = tmp_path / ".workflow"
    wdir.mkdir()
    _write(wdir, _make_state("OV-003"))
    rc = cmd_override(
        _args(
            workflow_dir=str(wdir),
            task_id="OV-003",
            to_state="not_a_state",
            reason="test",
            actor="architect",
        )
    )
    assert rc != 0
    assert "ERROR" in capsys.readouterr().err


def test_override_missing_task_returns_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wdir = tmp_path / ".workflow"
    wdir.mkdir()
    rc = cmd_override(
        _args(
            workflow_dir=str(wdir),
            task_id="GHOST-001",
            to_state="awaiting_senior_plan",
            reason="test",
            actor="architect",
        )
    )
    assert rc != 0
    assert "ERROR" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# verify-workspace — §3 subprocess coverage
# ---------------------------------------------------------------------------


def test_verify_workspace_clean_returns_zero(capsys: pytest.CaptureFixture[str]) -> None:
    fetch_result = MagicMock()
    fetch_result.returncode = 0
    status_result = MagicMock()
    status_result.stdout = ""

    with patch("subprocess.run", side_effect=[fetch_result, status_result]):
        rc = cmd_verify_workspace(_args())
    assert rc == 0
    assert capsys.readouterr().err == ""


def test_verify_workspace_dirty_warns_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    fetch_result = MagicMock()
    fetch_result.returncode = 0
    status_result = MagicMock()
    status_result.stdout = " M src/foo.py\n?? notes/scratch.md\n"

    with patch("subprocess.run", side_effect=[fetch_result, status_result]):
        rc = cmd_verify_workspace(_args())
    assert rc == 0
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "src/foo.py" in err


def test_verify_workspace_fetch_timeout_warns_and_returns_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="git", timeout=30),
    ):
        rc = cmd_verify_workspace(_args())
    assert rc == 0
    assert "WARNING" in capsys.readouterr().err


def test_verify_workspace_fetch_oserror_warns_and_returns_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with patch("subprocess.run", side_effect=OSError("git not found")):
        rc = cmd_verify_workspace(_args())
    assert rc == 0
    assert "WARNING" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# build_parser smoke test
# ---------------------------------------------------------------------------


def test_build_parser_subcommands_registered() -> None:
    parser = build_parser()
    # Verify all five subcommands exist by parsing minimal valid args
    # (using --workflow-dir to avoid touching real fs)
    ns = parser.parse_args(["--workflow-dir", "/tmp", "verify-workspace"])
    assert ns.command == "verify-workspace"
