"""Thin YAML read/write wrapper for .workflow/{task-id}.yaml state files.

Concurrency note: sessions are human-initiated; concurrent writes to the
same state file within one session are not an expected scenario. No file
locking is implemented. (test-coverage-standard.md §2 N/A rationale.)
"""

from __future__ import annotations

from pathlib import Path

import yaml

from orchestrator.workflow.exceptions import WorkflowError
from orchestrator.workflow.schema import TaskState


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
