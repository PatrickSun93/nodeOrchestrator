"""File source reader — path-sandboxed bounded read (ADR-041 D4, ADR-028 D3)."""

from __future__ import annotations

from pathlib import Path

from orchestrator.sources.schema import Source, SourceReadError, SourceReadResult
from orchestrator.tools.local import LocalToolError, _check_path


def read_file_source(source: Source, *, sandbox_root: Path) -> SourceReadResult:
    """Read source.locator as a path sandboxed to sandbox_root.

    Reuses the _check_path containment check from tools/local.py:
    - Traversal and symlink-escape are rejected.
    - Read is bounded by source.options.max_bytes.

    Raises SourceReadError on sandbox rejection or read failure.
    """
    resolved_root = sandbox_root.resolve()
    try:
        resolved = _check_path(source.locator, resolved_root)
    except LocalToolError as exc:
        raise SourceReadError(f"sandbox_rejected: {exc}") from exc

    if not resolved.is_file():
        raise SourceReadError(f"not_a_file: {source.locator!r}")

    try:
        with resolved.open("rb") as fh:
            raw = fh.read(source.options.max_bytes + 1)
    except OSError as exc:
        raise SourceReadError(f"file_read_failed: {exc}") from exc

    truncated = len(raw) > source.options.max_bytes
    if truncated:
        raw = raw[: source.options.max_bytes]
    content = raw.decode("utf-8", errors="replace")
    return SourceReadResult(source=source, content=content, truncated=truncated)
