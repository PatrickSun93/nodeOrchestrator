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
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from orchestrator.workflow.io import _git_show, _read_plan_frontmatter

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
