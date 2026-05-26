from __future__ import annotations

from pathlib import Path


class SkillError(Exception):
    """Raised when a skill file fails to load or validate."""

    def __init__(
        self,
        message: str,
        *,
        path: Path | None = None,
        field: str | None = None,
    ) -> None:
        super().__init__(message)
        self.path = path
        self.field = field
