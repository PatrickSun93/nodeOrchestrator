"""Tests for orchestrator.workflow.io — _git_show and _read_plan_frontmatter.

Covers:
  §3 cleanup: subprocess timeout handled (test_git_show_timeout_returns_none)
  §4 exception payload: WorkflowError.path verified in transition tests
  _git_show: returncode 0 returns content; non-zero returns None; timeout returns None
  _read_plan_frontmatter: valid frontmatter parsed; no fence returns None;
    file not on origin/main (git_show None) returns None
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from orchestrator.workflow.io import (
    _git_branch_exists,
    _git_branch_merged,
    _git_log_ahead_of_main_since,
    _git_log_branch_since,
    _git_show,
    _read_plan_frontmatter,
)

# ---------------------------------------------------------------------------
# _git_show tests — mock subprocess.run
# ---------------------------------------------------------------------------


def test_git_show_existing_file_returns_content(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "content\n"

    monkeypatch.setattr("orchestrator.workflow.io.subprocess.run", lambda *a, **kw: mock_result)

    assert _git_show("some/file.md") == "content\n"


def test_git_show_missing_file_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""

    monkeypatch.setattr("orchestrator.workflow.io.subprocess.run", lambda *a, **kw: mock_result)

    assert _git_show("missing.md") is None


def test_git_show_timeout_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_timeout(*args: Any, **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired("git", 10)

    monkeypatch.setattr("orchestrator.workflow.io.subprocess.run", raise_timeout)

    assert _git_show("any.md") is None


# ---------------------------------------------------------------------------
# _read_plan_frontmatter tests — mock _git_show
# ---------------------------------------------------------------------------


def test_read_plan_frontmatter_valid_frontmatter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "orchestrator.workflow.io._git_show",
        lambda *a, **kw: "---\ntask_id: SYNTH\nadr: ADR-012\n---\n# body",
    )
    # path must be relative_to cwd; use a real path under cwd
    plan_path = Path.cwd() / "docs" / "process" / "senior-plans" / "SYNTH.md"

    result = _read_plan_frontmatter(plan_path)

    assert result == {"task_id": "SYNTH", "adr": "ADR-012"}


def test_read_plan_frontmatter_no_frontmatter_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "orchestrator.workflow.io._git_show",
        lambda *a, **kw: "# just a plain file\nno frontmatter",
    )
    plan_path = Path.cwd() / "docs" / "process" / "senior-plans" / "SYNTH.md"

    result = _read_plan_frontmatter(plan_path)

    assert result is None


def test_read_plan_frontmatter_file_not_on_origin_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "orchestrator.workflow.io._git_show",
        lambda *a, **kw: None,
    )
    plan_path = Path.cwd() / "docs" / "process" / "senior-plans" / "NONEXISTENT.md"

    result = _read_plan_frontmatter(plan_path)

    assert result is None


def test_read_plan_frontmatter_relative_path_resolves_against_cwd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression — `workflow advance --workflow-dir .workflow` passes a
    relative senior-plan path. Prior to the resolve fix, the path's
    `relative_to(Path.cwd())` raised ValueError (relative-vs-absolute),
    the silent None return masked an Accepted ADR as `none`, and
    `awaiting_architect_accept → awaiting_junior_impl` failed to fire.

    Surfaced 2026-05-27 during P1.5.5 ADR-Accept advance; this test pins
    the W-003 RC-16 fix-completion gap closed.
    """
    captured: dict[str, str] = {}

    def fake_git_show(rel_path: str, ref: str = "origin/main") -> str:
        captured["rel_path"] = rel_path
        return "---\ntask_id: SYNTH\nadr: ADR-099\n---\n# body"

    monkeypatch.setattr("orchestrator.workflow.io._git_show", fake_git_show)
    # Relative path that resolves to under cwd — the exact shape build_artifact_snapshot
    # produces when wdir is Path(".workflow") and repo_root is wdir.parent.
    plan_path = Path("docs") / "process" / "senior-plans" / "SYNTH.md"

    result = _read_plan_frontmatter(plan_path)

    assert result == {"task_id": "SYNTH", "adr": "ADR-099"}
    assert captured["rel_path"] == "docs/process/senior-plans/SYNTH.md"


# ---------------------------------------------------------------------------
# _git_branch_exists tests — W-004-1
# ---------------------------------------------------------------------------

_BRANCH_REF = "refs/remotes/origin/claude/W-004-impl"
_REPO_ROOT = Path("/fake/repo")


def test_git_branch_exists_present_returns_true(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0

    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        captured["cmd"] = cmd
        return mock_result

    monkeypatch.setattr("orchestrator.workflow.io.subprocess.run", fake_run)

    assert _git_branch_exists(_BRANCH_REF, _REPO_ROOT) is True
    assert captured["cmd"] == ["git", "rev-parse", "--verify", _BRANCH_REF]


def test_git_branch_exists_absent_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_result = MagicMock()
    mock_result.returncode = 1
    monkeypatch.setattr("orchestrator.workflow.io.subprocess.run", lambda *a, **kw: mock_result)
    assert _git_branch_exists(_BRANCH_REF, _REPO_ROOT) is False


def test_git_branch_exists_timeout_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_timeout(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired("git", 10)

    monkeypatch.setattr("orchestrator.workflow.io.subprocess.run", raise_timeout)
    assert _git_branch_exists(_BRANCH_REF, _REPO_ROOT) is False


def test_git_branch_exists_oserror_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_oserror(*args: object, **kwargs: object) -> None:
        raise OSError("git not found")

    monkeypatch.setattr("orchestrator.workflow.io.subprocess.run", raise_oserror)
    assert _git_branch_exists(_BRANCH_REF, _REPO_ROOT) is False


# ---------------------------------------------------------------------------
# _git_log_ahead_of_main_since tests — W-004-1
# ---------------------------------------------------------------------------

_SINCE = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)


def test_git_log_ahead_of_main_since_has_commits_returns_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "abc1234 commit msg\n"
    monkeypatch.setattr("orchestrator.workflow.io.subprocess.run", lambda *a, **kw: mock_result)
    assert _git_log_ahead_of_main_since(_BRANCH_REF, _SINCE, _REPO_ROOT) is True


def test_git_log_ahead_of_main_since_no_commits_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    monkeypatch.setattr("orchestrator.workflow.io.subprocess.run", lambda *a, **kw: mock_result)
    assert _git_log_ahead_of_main_since(_BRANCH_REF, _SINCE, _REPO_ROOT) is False


def test_git_log_ahead_of_main_since_timeout_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_timeout(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired("git", 10)

    monkeypatch.setattr("orchestrator.workflow.io.subprocess.run", raise_timeout)
    assert _git_log_ahead_of_main_since(_BRANCH_REF, _SINCE, _REPO_ROOT) is False


def test_git_log_ahead_of_main_since_oserror_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_oserror(*args: object, **kwargs: object) -> None:
        raise OSError("git not found")

    monkeypatch.setattr("orchestrator.workflow.io.subprocess.run", raise_oserror)
    assert _git_log_ahead_of_main_since(_BRANCH_REF, _SINCE, _REPO_ROOT) is False


# ---------------------------------------------------------------------------
# _git_branch_merged tests — RC-21 / ADR-008 Decision 15
# ---------------------------------------------------------------------------


def test_git_branch_merged_ancestor_returns_true(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0  # is-ancestor exits 0 → merged
    monkeypatch.setattr("orchestrator.workflow.io.subprocess.run", lambda *a, **kw: mock_result)
    assert _git_branch_merged(_BRANCH_REF, "origin/main", _REPO_ROOT) is True


def test_git_branch_merged_not_ancestor_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_result = MagicMock()
    mock_result.returncode = 1  # not an ancestor → not merged
    monkeypatch.setattr("orchestrator.workflow.io.subprocess.run", lambda *a, **kw: mock_result)
    assert _git_branch_merged(_BRANCH_REF, "origin/main", _REPO_ROOT) is False


def test_git_branch_merged_timeout_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_timeout(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired("git", 10)

    monkeypatch.setattr("orchestrator.workflow.io.subprocess.run", raise_timeout)
    assert _git_branch_merged(_BRANCH_REF, "origin/main", _REPO_ROOT) is False


# ---------------------------------------------------------------------------
# _git_log_branch_since tests — RC-21 / ADR-008 Decision 15
# ---------------------------------------------------------------------------


def test_git_log_branch_since_has_commits_returns_true(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "abc1234 impl commit\n"
    monkeypatch.setattr("orchestrator.workflow.io.subprocess.run", lambda *a, **kw: mock_result)
    assert _git_log_branch_since(_BRANCH_REF, _SINCE, _REPO_ROOT) is True


def test_git_log_branch_since_no_commits_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = ""
    monkeypatch.setattr("orchestrator.workflow.io.subprocess.run", lambda *a, **kw: mock_result)
    assert _git_log_branch_since(_BRANCH_REF, _SINCE, _REPO_ROOT) is False


def test_git_log_branch_since_oserror_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_oserror(*args: object, **kwargs: object) -> None:
        raise OSError("git not found")

    monkeypatch.setattr("orchestrator.workflow.io.subprocess.run", raise_oserror)
    assert _git_log_branch_since(_BRANCH_REF, _SINCE, _REPO_ROOT) is False
