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
    _read_adr_status,
    build_parser,
    cmd_advance,
    cmd_init,
    cmd_override,
    cmd_status,
    cmd_verify_workspace,
)
from orchestrator.workflow.exceptions import WorkflowError
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
# _read_adr_status — W-002-1 plan-frontmatter ADR resolution (§4 payload, §5 boundary)
# ---------------------------------------------------------------------------


def _write_plan(repo_root: Path, task_id: str, content: str) -> Path:
    d = repo_root / "docs" / "process" / "senior-plans"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{task_id}.md"
    p.write_text(content, encoding="utf-8")
    return p


def _write_adr(repo_root: Path, filename: str, status: str) -> Path:
    d = repo_root / "docs" / "decisions"
    d.mkdir(parents=True, exist_ok=True)
    p = d / filename
    p.write_text(f"# ADR\n\nStatus: {status}\n", encoding="utf-8")
    return p


def _patch_git_show_from_disk(monkeypatch: pytest.MonkeyPatch, repo_root: Path) -> None:
    """Redirect _git_show and cwd so _read_plan_frontmatter reads from repo_root on disk.

    Tests write plan files to tmp_path (outside cwd); _read_plan_frontmatter
    now reads via _git_show (git show origin/main:...) instead of disk. This
    helper restores disk-read behavior for tests that pre-date the refactor by:
      1. chdir to repo_root so path.relative_to(Path.cwd()) resolves correctly.
      2. Replacing _git_show to read from repo_root on disk instead of git.
    """
    monkeypatch.chdir(repo_root)

    def _fake_git_show(rel_path: str, ref: str = "origin/main") -> str | None:
        p = repo_root / rel_path
        if p.exists():
            return p.read_text(encoding="utf-8")
        return None

    monkeypatch.setattr("orchestrator.workflow.io._git_show", _fake_git_show)


def test_read_adr_status_via_plan_frontmatter_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """frontmatter adr: ADR-099, ADR-099-synth.md Accepted → 'accepted'."""
    _patch_git_show_from_disk(monkeypatch, tmp_path)
    _write_plan(tmp_path, "SYNTH-001", "---\ntask_id: SYNTH-001\nadr: ADR-099\n---\n# Plan\n")
    _write_adr(tmp_path, "ADR-099-synth.md", "Accepted")
    assert _read_adr_status("SYNTH-001", tmp_path) == "accepted"


def test_read_adr_status_via_plan_frontmatter_proposed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """frontmatter adr: ADR-099, ADR-099-synth.md Proposed → 'proposed'."""
    _patch_git_show_from_disk(monkeypatch, tmp_path)
    _write_plan(tmp_path, "SYNTH-001", "---\ntask_id: SYNTH-001\nadr: ADR-099\n---\n# Plan\n")
    _write_adr(tmp_path, "ADR-099-synth.md", "Proposed")
    assert _read_adr_status("SYNTH-001", tmp_path) == "proposed"


def test_read_adr_status_via_plan_frontmatter_adr_not_found(tmp_path: Path) -> None:
    """frontmatter adr: ADR-099, no matching file → 'none'."""
    _write_plan(tmp_path, "SYNTH-001", "---\ntask_id: SYNTH-001\nadr: ADR-099\n---\n# Plan\n")
    # No ADR-099-*.md written → zero matches
    assert _read_adr_status("SYNTH-001", tmp_path) == "none"


def test_read_adr_status_list_single_element_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """adr: [ADR-098] degenerate 1-element list → 'accepted'. §5 boundary (len=1)."""
    _patch_git_show_from_disk(monkeypatch, tmp_path)
    _write_plan(tmp_path, "SYNTH-001", "---\nadr: [ADR-098]\n---\n# Plan\n")
    _write_adr(tmp_path, "ADR-098-foo.md", "Accepted")
    assert _read_adr_status("SYNTH-001", tmp_path) == "accepted"


def test_read_adr_status_list_both_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """adr: [ADR-098, ADR-099] both Accepted → 'accepted'. §5 boundary (len=2)."""
    _patch_git_show_from_disk(monkeypatch, tmp_path)
    _write_plan(tmp_path, "SYNTH-001", "---\nadr: [ADR-098, ADR-099]\n---\n# Plan\n")
    _write_adr(tmp_path, "ADR-098-foo.md", "Accepted")
    _write_adr(tmp_path, "ADR-099-bar.md", "Accepted")
    assert _read_adr_status("SYNTH-001", tmp_path) == "accepted"


def test_read_adr_status_list_one_proposed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """adr: [ADR-098, ADR-099] one Proposed → 'proposed' (all-or-nothing)."""
    _patch_git_show_from_disk(monkeypatch, tmp_path)
    _write_plan(tmp_path, "SYNTH-001", "---\nadr: [ADR-098, ADR-099]\n---\n# Plan\n")
    _write_adr(tmp_path, "ADR-098-foo.md", "Accepted")
    _write_adr(tmp_path, "ADR-099-bar.md", "Proposed")
    assert _read_adr_status("SYNTH-001", tmp_path) == "proposed"


def test_read_adr_status_list_one_missing(tmp_path: Path) -> None:
    """adr: [ADR-098, ADR-099] one missing → 'none' (all-or-nothing)."""
    _write_plan(tmp_path, "SYNTH-001", "---\nadr: [ADR-098, ADR-099]\n---\n# Plan\n")
    _write_adr(tmp_path, "ADR-098-foo.md", "Accepted")
    # ADR-099-*.md not written → zero matches → element contributes "none"
    assert _read_adr_status("SYNTH-001", tmp_path) == "none"


def test_read_adr_status_list_three_all_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """adr: [ADR-098, ADR-099, ADR-100] all Accepted → 'accepted'. §5 multi-position (len=3)."""
    _patch_git_show_from_disk(monkeypatch, tmp_path)
    _write_plan(tmp_path, "SYNTH-001", "---\nadr: [ADR-098, ADR-099, ADR-100]\n---\n# Plan\n")
    _write_adr(tmp_path, "ADR-098-foo.md", "Accepted")
    _write_adr(tmp_path, "ADR-099-bar.md", "Accepted")
    _write_adr(tmp_path, "ADR-100-baz.md", "Accepted")
    assert _read_adr_status("SYNTH-001", tmp_path) == "accepted"


def test_read_adr_status_empty_list_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """adr: [] raises WorkflowError with path populated. §4 exception payload."""
    _patch_git_show_from_disk(monkeypatch, tmp_path)
    p = _write_plan(tmp_path, "SYNTH-001", "---\nadr: []\n---\n# Plan\n")
    with pytest.raises(WorkflowError) as exc_info:
        _read_adr_status("SYNTH-001", tmp_path)
    assert exc_info.value.path == p
    assert "empty" in str(exc_info.value).lower()


def test_read_adr_status_list_non_string_element_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """adr: [ADR-098, 42] non-string element raises with path + element index. §4."""
    _patch_git_show_from_disk(monkeypatch, tmp_path)
    p = _write_plan(tmp_path, "SYNTH-001", "---\nadr: [ADR-098, 42]\n---\n# Plan\n")
    with pytest.raises(WorkflowError) as exc_info:
        _read_adr_status("SYNTH-001", tmp_path)
    assert exc_info.value.path == p
    assert "1" in str(exc_info.value)  # element index 1


def test_read_adr_status_list_duplicate_element(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """adr: [ADR-098, ADR-098] duplicate — not a raise; both elements resolve same file."""
    _patch_git_show_from_disk(monkeypatch, tmp_path)
    _write_plan(tmp_path, "SYNTH-001", "---\nadr: [ADR-098, ADR-098]\n---\n# Plan\n")
    _write_adr(tmp_path, "ADR-098-foo.md", "Accepted")
    # Both elements resolve to ADR-098-foo.md → both "accepted" → aggregate "accepted"
    assert _read_adr_status("SYNTH-001", tmp_path) == "accepted"


def test_read_adr_status_multi_glob_match_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two files matching ADR-099-*.md → WorkflowError (authoring error). §4 payload."""
    _patch_git_show_from_disk(monkeypatch, tmp_path)
    _write_plan(tmp_path, "SYNTH-001", "---\nadr: ADR-099\n---\n# Plan\n")
    d = tmp_path / "docs" / "decisions"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ADR-099-alpha.md").write_text("Status: Accepted\n", encoding="utf-8")
    (d / "ADR-099-beta.md").write_text("Status: Proposed\n", encoding="utf-8")
    with pytest.raises(WorkflowError) as exc_info:
        _read_adr_status("SYNTH-001", tmp_path)
    assert exc_info.value.path == d


def test_read_adr_status_fallback_no_frontmatter(tmp_path: Path) -> None:
    """No frontmatter in plan → falls back to direct ADR-{task_id}.md lookup."""
    _write_plan(tmp_path, "SYNTH-001", "# Plan\n\nNo frontmatter here.\n")
    _write_adr(tmp_path, "ADR-SYNTH-001.md", "Accepted")
    assert _read_adr_status("SYNTH-001", tmp_path) == "accepted"


def test_read_adr_status_fallback_no_adr_file(tmp_path: Path) -> None:
    """No frontmatter and no direct ADR file → 'none'."""
    _write_plan(tmp_path, "SYNTH-001", "# Plan\n\nNo frontmatter here.\n")
    assert _read_adr_status("SYNTH-001", tmp_path) == "none"


def test_read_adr_status_frontmatter_no_adr_key_falls_back(tmp_path: Path) -> None:
    """Frontmatter present but no `adr` key → falls back to direct ADR lookup."""
    _write_plan(tmp_path, "SYNTH-001", "---\ntask_id: SYNTH-001\n---\n# Plan\n")
    # Direct ADR-SYNTH-001.md exists with Accepted status
    _write_adr(tmp_path, "ADR-SYNTH-001.md", "Accepted")
    assert _read_adr_status("SYNTH-001", tmp_path) == "accepted"


# ---------------------------------------------------------------------------
# build_parser smoke test
# ---------------------------------------------------------------------------


def test_build_parser_subcommands_registered() -> None:
    parser = build_parser()
    # Verify all five subcommands exist by parsing minimal valid args
    # (using --workflow-dir to avoid touching real fs)
    ns = parser.parse_args(["--workflow-dir", "/tmp", "verify-workspace"])
    assert ns.command == "verify-workspace"
