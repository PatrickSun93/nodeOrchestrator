"""Thin YAML read/write wrapper for .workflow/{task-id}.yaml state files.

Concurrency note: sessions are human-initiated; concurrent writes to the
same state file within one session are not an expected scenario. No file
locking is implemented. (test-coverage-standard.md §2 N/A rationale.)
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import yaml

from orchestrator.workflow.exceptions import WorkflowError
from orchestrator.workflow.schema import TaskState


def _git_show(rel_path: str, ref: str = "origin/main") -> str | None:
    """Return file content from a git ref via subprocess. None if not found.

    Centralizes subprocess error handling (timeout; non-zero exit;
    missing-file return-None semantic) for git-show callers.
    """
    try:
        result = subprocess.run(
            ["git", "show", f"{ref}:{rel_path}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _read_plan_frontmatter(path: Path) -> dict[str, Any] | None:
    """Parse the YAML frontmatter of a senior-plan markdown file.

    Reads the file content from origin/main via _git_show so that plan
    detection reflects the published state rather than the local working tree.

    Returns the parsed frontmatter dict if the file is present on origin/main,
    starts with '---', has a closing '---' fence, and parses as a mapping.

    Returns None if: file is not on origin/main, has no opening '---' fence,
    or the YAML content parses to a non-dict value.

    Raises WorkflowError if the opening fence is present but no closing
    fence is found (malformed file, not an absent one).
    """
    try:
        rel_path_str = path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return None
    content = _git_show(rel_path_str)
    if content is None:
        return None
    if not content.startswith("---"):
        return None
    end = content.find("\n---", 3)
    if end == -1:
        raise WorkflowError(
            f"{path}: unclosed YAML frontmatter block",
            path=path,
        )
    frontmatter_text = content[3:end]
    try:
        raw = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError:
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def read_state(path: Path) -> TaskState:
    """Read and validate a .workflow/{task-id}.yaml file.

    Raises:
        WorkflowError: file not found, YAML parse error, or validation failure.
    """
    if not path.exists():
        raise WorkflowError(f"{path}: state file not found", path=path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise WorkflowError(f"{path}: yaml parse error — {exc}", path=path) from exc
    try:
        return TaskState.model_validate(raw)
    except Exception as exc:
        raise WorkflowError(f"{path}: state file validation failed — {exc}", path=path) from exc


def write_state(state: TaskState, path: Path) -> None:
    """Write a TaskState to path atomically (write-then-rename).

    Uses Path.replace so partial writes never land.
    (test-coverage-standard.md §3 cleanup obligation.)
    """
    tmp = path.with_suffix(".yaml.tmp")
    payload = state.model_dump(mode="json")
    tmp.write_text(yaml.dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    tmp.replace(path)
