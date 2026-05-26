"""Workflow-module exceptions.

WorkflowError is the structured exception for all harness failures.
It carries optional task_id and path fields so callers can locate
the offending resource without parsing the message string.
(test-coverage-standard.md §4 exception-payload obligation.)
"""

from __future__ import annotations

from pathlib import Path


class WorkflowError(Exception):
    """Raised by the workflow harness on any operational failure.

    Attributes:
        task_id: The task identifier involved, if known.
        path:    The file path involved, if known.
    """

    def __init__(
        self,
        message: str,
        *,
        task_id: str | None = None,
        path: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.task_id = task_id
        self.path = path
