"""Mutation local tool closures (ADR-036 D1/D3-i/D4; P4.2-B5-1).

First tool surface that WRITES the workspace (apply_edit).

apply_edit — in-process sandboxed file write (no subprocess/network marker; no cap;
             rides the plain _execute_local_call branch like read_file).

Threat model (ADR-036 D3-i):
  Untrusted input: LLM-proposed path + content.
  Trusted: operator-configured sandbox root.

Write recipe (Y1-pinned, ONE coherent strategy):
  1. Check-time containment: _check_path resolves + rejects any path that escapes
     the sandbox root, INCLUDING an existing escaping final-component symlink
     (.resolve() follows all symlinks -> relative_to() raises -> LocalToolError).
     apply_edit REFUSES (read tools only skip).
  2. Atomic write via O_NOFOLLOW temp-create + os.replace:
     - Create temp file in the CONTAINED directory with os.open(O_CREAT|O_EXCL|O_NOFOLLOW).
       O_NOFOLLOW is on the TEMP CREATE (cannot be pre-planted/followed).
       O_EXCL rejects a pre-existing temp name.
     - Write content bytes, fsync, close.
     - os.replace(temp, dest) - atomic; mid-write failure leaves original intact.
       os.replace REPLACES an in-sandbox final symlink at dest (does not follow it);
       any escaping final symlink was already rejected at check time.
  3. Parent-component TOCTOU note: O_NOFOLLOW is final-component-only. A concurrent
     external FS writer planting a parent-directory symlink between _check_path and
     os.replace is the named RB-FS residual retired by P4.3 — NOT a B5 hole
     (no symlink-creation primitive in the B5 tool surface).

Output is TRUSTED (our own code) — NOT in any _*_TOOL_NAMES set, NOT excerpt-excluded.
"""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from orchestrator.mcp.execution import MAX_RESULT_BYTES
from orchestrator.tools.executor import LocalToolFn, LocalToolOutput
from orchestrator.tools.local import LocalToolError, _check_path

_log = logging.getLogger("orchestrator.tools.mutation")


# ---------------------------------------------------------------------------
# Shared helper (mirrors subprocess_tools / network_tools)
# ---------------------------------------------------------------------------


def _check_disallowed(
    params: dict[str, Any], allowed: frozenset[str], tool_name: str
) -> None:
    """Raise LocalToolError if any param key is outside the allowlist."""
    disallowed = set(params.keys()) - allowed
    if disallowed:
        raise LocalToolError(
            f"{tool_name}: disallowed param(s): {sorted(disallowed)!r} "
            f"(allowed: {sorted(allowed)!r})"
        )


# ---------------------------------------------------------------------------
# B5-1: apply_edit closure
# ---------------------------------------------------------------------------


def _make_apply_edit(sandbox_root: Path) -> LocalToolFn:
    """Build an apply_edit impl sandboxed to sandbox_root.

    In-process; no subprocess/network marker; no per-turn cap (like read_file).
    Output is TRUSTED — NOT in _SUBPROCESS_TOOL_NAMES / _NETWORK_TOOL_NAMES.
    """
    resolved_root = sandbox_root.resolve()
    allowed: frozenset[str] = frozenset({"path", "content"})

    def _apply_edit(params: dict[str, Any]) -> LocalToolOutput:
        _check_disallowed(params, allowed, "apply_edit")

        path_str = str(params.get("path", ""))
        content_str = str(params.get("content", ""))

        if not path_str:
            raise LocalToolError("apply_edit: 'path' is required")

        # Bounded content: reject oversize BEFORE any write (OOM/abuse guard on input).
        content_bytes = content_str.encode("utf-8")
        if len(content_bytes) > MAX_RESULT_BYTES:
            raise LocalToolError(
                f"apply_edit: content exceeds max allowed size "
                f"({len(content_bytes)} > {MAX_RESULT_BYTES} bytes)"
            )

        # Check-time containment: _check_path follows all symlinks via .resolve();
        # rejects traversal, absolute paths, parent-symlink escape, AND an existing
        # escaping final-component symlink. apply_edit REFUSES (read tools only skip).
        dest = _check_path(path_str, resolved_root)

        # Ensure parent directory exists (create if needed, still inside sandbox).
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write via O_NOFOLLOW temp-create + os.replace (ADR-036 D3-i pinned recipe).
        # Temp file in the same contained directory as the destination (same-filesystem
        # guarantee for os.replace; avoids cross-device rename).
        temp_path: Path | None = None
        try:
            # NamedTemporaryFile with delete=False to get a path; then reopen with os.open.
            # Use a temp name in dest.parent (same dir, same filesystem).
            tmp_fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=".apply_edit_tmp_")
            temp_path = Path(tmp_name)
            os.close(tmp_fd)
            # Remove the placeholder so O_EXCL can succeed.
            temp_path.unlink()

            # O_CREAT|O_EXCL|O_NOFOLLOW: create, fail if exists, no-follow on final component.
            # This is the pinned location of O_NOFOLLOW (on the TEMP create, not the dest).
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            # O_NOFOLLOW is POSIX; available on Linux/macOS (the target platforms).
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(tmp_name, flags, 0o600)
            try:
                os.write(fd, content_bytes)
                os.fsync(fd)
            finally:
                os.close(fd)

            # Atomic replace: dest may not exist (new file) or may exist (overwrite).
            # os.replace does NOT follow a final-component symlink at dest; it replaces
            # the symlink entry itself — any escaping symlink was refused at _check_path.
            os.replace(tmp_name, dest)
            temp_path = None  # successfully renamed; cleanup not needed

        except LocalToolError:
            raise
        except OSError as exc:
            raise LocalToolError(f"apply_edit: write failed: {exc}") from exc
        finally:
            # Mid-write failure cleanup: remove temp if it still exists.
            if temp_path is not None and temp_path.exists():
                with contextlib.suppress(OSError):
                    temp_path.unlink()

        rel = dest.relative_to(resolved_root)
        n_bytes = len(content_bytes)
        return LocalToolOutput(content=f"wrote {n_bytes} bytes to {rel}")

    return _apply_edit


# ---------------------------------------------------------------------------
# Registry builder
# ---------------------------------------------------------------------------


def build_mutation_tool_registry(sandbox_root: Path) -> dict[str, LocalToolFn]:
    """Build the mutation local tool registry for the given sandbox root.

    Returns a dict keyed by tool name (matches tools.yaml classification).
    apply_edit is in-process (no marker, no cap) — plain LocalToolFn like read_file.
    """
    return {
        "apply_edit": _make_apply_edit(sandbox_root),
    }
