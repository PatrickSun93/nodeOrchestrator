"""Local tool implementations + the local trust boundary (ADR-028 D3).

MVP local-tool set: get_current_time (pure), read_file + list_files (sandboxed FS).
B2 code-intel set (ADR-033 D5): search_text, search_code, find_references,
find_definition (in-process os.walk; no subprocess/grep/rg).

Trust boundary (read_file / list_files / B2 search tools):
- Configured sandbox root (operator-trusted workspace directory).
- Path resolve + containment: reject if escapes root (traversal / symlink / absolute).
- read_file: bounded read ≤ MAX_RESULT_BYTES (+1) bytes — never full file (OOM guard).
- list_files: output byte-capped at MAX_RESULT_BYTES (consistent with read_file);
  over-cap: trim to last whole entry, set output_truncated_at (Y2 fix).
- B2 tools: MAX_SEARCH_FILES traversal cap + per-file bounded read + output byte-cap.
- Threat model: untrusted input = LLM-proposed path; sandbox root = trusted.
  TOCTOU out of MVP scope (ADR-028 D3 — deliberate stated posture).

Local tool results are trusted (our own code) — NOT interpreted (ADR-028 D2).
"""

from __future__ import annotations

import datetime
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from orchestrator.mcp.execution import MAX_RESULT_BYTES
from orchestrator.tools.executor import LocalToolFn, LocalToolOutput

_log = logging.getLogger("orchestrator.tools.local")

# B2: cap total files walked per search call (ADR-033 D5 bounded-traversal).
MAX_SEARCH_FILES: int = 500

# B2: per-file read cap during search (avoid loading multi-GB files fully).
_SEARCH_FILE_READ_BYTES: int = MAX_RESULT_BYTES


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
        output = "\n".join(entries)
        output_bytes = output.encode("utf-8")
        if len(output_bytes) > MAX_RESULT_BYTES:
            # Byte-cap output (consistent with read_file); trim to last whole entry.
            truncated = output_bytes[:MAX_RESULT_BYTES].decode("utf-8", errors="replace")
            last_nl = truncated.rfind("\n")
            if last_nl >= 0:
                truncated = truncated[:last_nl]
            return LocalToolOutput(content=truncated, output_truncated_at=MAX_RESULT_BYTES)
        return LocalToolOutput(content=output)

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
# B2 code-intel tools (ADR-033 D5): in-process, sandboxed, bounded traversal
# No subprocess/os.system/Popen — pure os.walk + re (ADR-033 ⭐⭐ carry-forward 6)
# ---------------------------------------------------------------------------


def _walk_sandbox(resolved_root: Path, scope_str: str | None) -> Path:
    """Resolve the walk root from scope (or sandbox root).

    Returns the resolved walk root. Raises LocalToolError on path escape.
    """
    if scope_str:
        walk_root = _check_path(scope_str, resolved_root)
        if not walk_root.exists():
            raise LocalToolError(f"scope path does not exist: {scope_str!r}")
    else:
        walk_root = resolved_root
    return walk_root


def _collect_hits(
    walk_root: Path,
    match_fn: Callable[[str, str], list[tuple[int, str]]],
    *,
    resolved_root: Path,
) -> tuple[list[str], int, bool]:
    """Walk walk_root, apply match_fn per file, collect file:line hits.

    Returns (hits_lines, files_scanned, truncated_by_cap).
    Stops after MAX_SEARCH_FILES files (ADR-033 D5 bounded traversal).
    Each file is read bounded at _SEARCH_FILE_READ_BYTES.

    Per-file containment (ADR-028 D3 / R0-A Y2): resolves each file path and
    rejects if it escapes resolved_root — mirrors _check_path for read_file so
    an in-sandbox symlinked file pointing outside is skipped, not read.
    """
    hits: list[str] = []
    output_bytes = 0
    files_scanned = 0
    truncated_by_cap = False

    for dirpath, _dirnames, filenames in os.walk(walk_root):
        for filename in sorted(filenames):
            if files_scanned >= MAX_SEARCH_FILES:
                truncated_by_cap = True
                return hits, files_scanned, truncated_by_cap
            files_scanned += 1
            fpath = Path(dirpath) / filename
            # Symlink-escape guard: reject files whose realpath escapes the sandbox root.
            try:
                fpath.resolve().relative_to(resolved_root)
            except ValueError:
                continue
            try:
                raw = fpath.read_bytes()[:_SEARCH_FILE_READ_BYTES]
                text = raw.decode("utf-8", errors="replace")
            except (OSError, PermissionError):
                continue
            for lineno, line in match_fn(text, str(fpath.relative_to(walk_root.parent))):
                entry = f"{fpath}:{lineno}: {line.rstrip()}"
                entry_bytes = len(entry.encode("utf-8")) + 1  # +1 for newline
                if output_bytes + entry_bytes > MAX_RESULT_BYTES:
                    return hits, files_scanned, True
                hits.append(entry)
                output_bytes += entry_bytes

    return hits, files_scanned, truncated_by_cap


def _make_search_text(sandbox_root: Path) -> LocalToolFn:
    """Literal/substring text search across the sandbox (or scope subdir)."""
    resolved_root = sandbox_root.resolve()

    def _search_text(params: dict[str, Any]) -> LocalToolOutput:
        query = str(params.get("query", ""))
        scope_str: str | None = params.get("scope") or None
        if not query:
            raise LocalToolError("search_text: 'query' param is required")
        walk_root = _walk_sandbox(resolved_root, scope_str)

        def match_fn(text: str, _rel: str) -> list[tuple[int, str]]:
            results = []
            for i, line in enumerate(text.splitlines(), 1):
                if query in line:
                    results.append((i, line))
            return results

        hits, files_scanned, truncated = _collect_hits(
            walk_root, match_fn, resolved_root=resolved_root
        )
        content = "\n".join(hits) if hits else "(no matches)"
        truncated_at = MAX_RESULT_BYTES if truncated else None
        _log.debug("search_text: %d files %d hits trunc=%s", files_scanned, len(hits), truncated)
        return LocalToolOutput(content=content, output_truncated_at=truncated_at)

    return _search_text


def _make_search_code(sandbox_root: Path) -> LocalToolFn:
    """Regex search across the sandbox (or scope subdir)."""
    resolved_root = sandbox_root.resolve()

    def _search_code(params: dict[str, Any]) -> LocalToolOutput:
        pattern_str = str(params.get("pattern", ""))
        scope_str: str | None = params.get("scope") or None
        if not pattern_str:
            raise LocalToolError("search_code: 'pattern' param is required")
        try:
            pattern = re.compile(pattern_str)
        except re.error as exc:
            raise LocalToolError(f"search_code: invalid regex {pattern_str!r}: {exc}") from exc
        walk_root = _walk_sandbox(resolved_root, scope_str)

        def match_fn(text: str, _rel: str) -> list[tuple[int, str]]:
            results = []
            for i, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    results.append((i, line))
            return results

        hits, files_scanned, truncated = _collect_hits(
            walk_root, match_fn, resolved_root=resolved_root
        )
        content = "\n".join(hits) if hits else "(no matches)"
        truncated_at = MAX_RESULT_BYTES if truncated else None
        _log.debug("search_code: %d files %d hits trunc=%s", files_scanned, len(hits), truncated)
        return LocalToolOutput(content=content, output_truncated_at=truncated_at)

    return _search_code


def _make_find_references(sandbox_root: Path) -> LocalToolFn:
    """Heuristic identifier-usage search (word-boundary regex; not a language server)."""
    resolved_root = sandbox_root.resolve()

    def _find_references(params: dict[str, Any]) -> LocalToolOutput:
        symbol = str(params.get("symbol", ""))
        scope_str: str | None = params.get("scope") or None
        if not symbol:
            raise LocalToolError("find_references: 'symbol' param is required")
        pattern = re.compile(r"\b" + re.escape(symbol) + r"\b")
        walk_root = _walk_sandbox(resolved_root, scope_str)

        def match_fn(text: str, _rel: str) -> list[tuple[int, str]]:
            results = []
            for i, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    results.append((i, line))
            return results

        hits, files_scanned, truncated = _collect_hits(
            walk_root, match_fn, resolved_root=resolved_root
        )
        content = "\n".join(hits) if hits else "(no matches)"
        truncated_at = MAX_RESULT_BYTES if truncated else None
        _log.debug("find_references: %d files %d hits trunc=%s", files_scanned, len(hits), truncated)  # noqa: E501
        return LocalToolOutput(content=content, output_truncated_at=truncated_at)

    return _find_references


def _make_find_definition(sandbox_root: Path) -> LocalToolFn:
    """Heuristic definition-site search: def/class/<symbol> = (not a language server)."""
    resolved_root = sandbox_root.resolve()

    def _find_definition(params: dict[str, Any]) -> LocalToolOutput:
        symbol = str(params.get("symbol", ""))
        scope_str: str | None = params.get("scope") or None
        if not symbol:
            raise LocalToolError("find_definition: 'symbol' param is required")
        # Match: def <symbol>, class <symbol>, or <symbol> = (assignment)
        pattern = re.compile(
            r"(?:def\s+|class\s+)" + re.escape(symbol) + r"\b"
            r"|"
            r"\b" + re.escape(symbol) + r"\s*="
        )
        walk_root = _walk_sandbox(resolved_root, scope_str)

        def match_fn(text: str, _rel: str) -> list[tuple[int, str]]:
            results = []
            for i, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    results.append((i, line))
            return results

        hits, files_scanned, truncated = _collect_hits(
            walk_root, match_fn, resolved_root=resolved_root
        )
        content = "\n".join(hits) if hits else "(no matches)"
        truncated_at = MAX_RESULT_BYTES if truncated else None
        _log.debug("find_definition: %d files %d hits trunc=%s", files_scanned, len(hits), truncated)  # noqa: E501
        return LocalToolOutput(content=content, output_truncated_at=truncated_at)

    return _find_definition


# ---------------------------------------------------------------------------
# log_event (ADR-033 D5): agent records a finding → TOOL_RESULT, no event_store handle
# ---------------------------------------------------------------------------


def _log_event_tool(params: dict[str, Any]) -> LocalToolOutput:
    """Record an investigation note; returns LocalToolOutput → lands as TOOL_RESULT.

    No event_store handle; no new EventType (ADR-033 D5).
    content is bounded to MAX_RESULT_BYTES on output.
    """
    content = str(params.get("content", ""))
    event_type = str(params.get("type", "note"))
    if not content:
        raise LocalToolError("log_event: 'content' param is required")
    # Bounded output: note + type metadata, capped at MAX_RESULT_BYTES.
    note = f"[{event_type}] {content}"
    note_bytes = note.encode("utf-8")
    truncated = len(note_bytes) > MAX_RESULT_BYTES
    if truncated:
        note = note_bytes[:MAX_RESULT_BYTES].decode("utf-8", errors="replace")
    return LocalToolOutput(
        content=note,
        output_truncated_at=MAX_RESULT_BYTES if truncated else None,
    )


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
        # B2 code-intel tools (ADR-033 D5)
        "search_text": _make_search_text(sandbox_root),
        "search_code": _make_search_code(sandbox_root),
        "find_references": _make_find_references(sandbox_root),
        "find_definition": _make_find_definition(sandbox_root),
        "log_event": _log_event_tool,
    }
