"""Local tool implementations + the local trust boundary (ADR-028 D3).

MVP local-tool set: get_current_time (pure), read_file + list_files (sandboxed FS).

Trust boundary (read_file / list_files):
- Configured sandbox root (operator-trusted workspace directory).
- Path resolve + containment: reject if escapes root (traversal / symlink / absolute).
- read_file: bounded read ≤ MAX_RESULT_BYTES (+1) bytes — never full file (OOM guard).
- Threat model: untrusted input = LLM-proposed path; sandbox root = trusted.
  TOCTOU out of MVP scope (ADR-028 D3 — deliberate stated posture).

Local tool results are trusted (our own code) — NOT interpreted (ADR-028 D2).
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any

from orchestrator.mcp.execution import MAX_RESULT_BYTES
from orchestrator.tools.executor import LocalToolFn, LocalToolOutput

_log = logging.getLogger("orchestrator.tools.local")


class LocalToolError(Exception):
    """Raised by a local tool when execution fails (path escape, I/O error, etc.)."""


# ---------------------------------------------------------------------------
# get_current_time (pure — no I/O)
# ---------------------------------------------------------------------------


def _get_current_time(params: dict[str, Any]) -> LocalToolOutput:
    """Return current UTC time as ISO 8601 string."""
    ts = datetime.datetime.now(tz=datetime.UTC).isoformat()
    return LocalToolOutput(content=ts)


# ---------------------------------------------------------------------------
# read_file (sandboxed FS, bounded read)
# ---------------------------------------------------------------------------


def _make_read_file(sandbox_root: Path) -> LocalToolFn:
    """Build a read_file impl sandboxed to sandbox_root."""
    resolved_root = sandbox_root.resolve()

    def _read_file(params: dict[str, Any]) -> LocalToolOutput:
        path_str = str(params.get("path", ""))
        resolved = _check_path(path_str, resolved_root)
        if not resolved.is_file():
            raise LocalToolError(f"not a file: {path_str!r}")
        # Bounded read: MAX_RESULT_BYTES + 1 to detect truncation without loading full file.
        with resolved.open("rb") as fh:
            raw = fh.read(MAX_RESULT_BYTES + 1)
        truncated = len(raw) > MAX_RESULT_BYTES
        if truncated:
            raw = raw[:MAX_RESULT_BYTES]
        text = raw.decode("utf-8", errors="replace")
        return LocalToolOutput(
            content=text,
            output_truncated_at=MAX_RESULT_BYTES if truncated else None,
        )

    return _read_file


# ---------------------------------------------------------------------------
# list_files (sandboxed FS)
# ---------------------------------------------------------------------------


def _make_list_files(sandbox_root: Path) -> LocalToolFn:
    """Build a list_files impl sandboxed to sandbox_root."""
    resolved_root = sandbox_root.resolve()

    def _list_files(params: dict[str, Any]) -> LocalToolOutput:
        path_str = str(params.get("path", "."))
        resolved = _check_path(path_str, resolved_root)
        if not resolved.is_dir():
            raise LocalToolError(f"not a directory: {path_str!r}")
        entries = sorted(e.name for e in resolved.iterdir())
        return LocalToolOutput(content="\n".join(entries))

    return _list_files


# ---------------------------------------------------------------------------
# Path containment check
# ---------------------------------------------------------------------------


def _check_path(path_str: str, resolved_root: Path) -> Path:
    """Resolve path_str and reject if it escapes resolved_root.

    resolved_root is trusted (operator-configured sandbox).
    path_str is untrusted (LLM-proposed).
    Raises LocalToolError on escape (traversal / absolute / symlink-escape).
    """
    candidate = (resolved_root / path_str).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise LocalToolError(
            f"path escapes sandbox root: {path_str!r} resolves to {candidate}, "
            f"outside root {resolved_root}"
        ) from exc
    return candidate


# ---------------------------------------------------------------------------
# Registry builder
# ---------------------------------------------------------------------------


def build_local_tool_registry(sandbox_root: Path) -> dict[str, LocalToolFn]:
    """Build the MVP local tool registry for the given sandbox root.

    Returns a dict keyed by tool name (matches tools.yaml classification).
    The sandbox root is operator-configured; path resolution is relative to it.
    """
    return {
        "get_current_time": _get_current_time,
        "read_file": _make_read_file(sandbox_root),
        "list_files": _make_list_files(sandbox_root),
    }
