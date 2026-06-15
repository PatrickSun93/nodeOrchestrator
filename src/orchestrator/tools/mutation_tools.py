"""Mutation local tool closures (ADR-036 D1/D3-i/D4; P4.2-B5-1; ADR-037 D3 P4.3-9).

First tool surface that WRITES the workspace (apply_edit).

apply_edit — in-process sandboxed file write (no subprocess/network marker; no cap;
             rides the plain _execute_local_call branch like read_file).

Threat model (ADR-036 D3-i):
  Untrusted input: LLM-proposed path + content.
  Trusted: operator-configured sandbox root.

Write recipe (Y1-pinned, ONE coherent strategy; P4.3-9 adds openat2 hardening):
  1. Check-time containment: _check_path resolves + rejects any path that escapes
     the sandbox root, INCLUDING an existing escaping final-component symlink
     (.resolve() follows all symlinks -> relative_to() raises -> LocalToolError).
     apply_edit REFUSES (read tools only skip).
  2. Atomic write via hardened open + os.replace:
     - Create temp file via _hardened_open():
         Linux 5.6+: openat2(RESOLVE_NO_SYMLINKS) — rejects parent-component symlinks.
         macOS: O_NOFOLLOW on the temp create (best-effort; dir-fd walk deferred).
         Windows: O_NOFOLLOW where available (final-component residual — ADR-037 D5).
     - Write content bytes, fsync, close.
     - os.replace(temp, dest) - atomic; mid-write failure leaves original intact.
  3. R7 retirement: openat2(RESOLVE_NO_SYMLINKS) on Linux 5.6+ closes the TOCTOU window
     between _check_path and the write — a parent-dir symlink planted by a concurrent
     external writer is rejected by the kernel at open time (not just at check time).
     Cross-platform residual inscribed in ADR-037 D5.

Output is TRUSTED (our own code) — NOT in any _*_TOOL_NAMES set, NOT excerpt-excluded.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from orchestrator.mcp.execution import MAX_RESULT_BYTES
from orchestrator.tools.executor import LocalToolFn, LocalToolOutput
from orchestrator.tools.local import LocalToolError, _check_path

_log = logging.getLogger("orchestrator.tools.mutation")

# ---------------------------------------------------------------------------
# P4.3-9: openat2(RESOLVE_NO_SYMLINKS) hardening (R7 retirement, ADR-037 D3)
# ---------------------------------------------------------------------------

# openat2 is Linux 5.6+. Syscall number on x86_64 = 437.
_SYS_OPENAT2 = 437
_RESOLVE_NO_SYMLINKS = 0x04
_OPEN_HOW_SIZE = 24  # sizeof(struct open_how) = u64 flags + u64 mode + u64 resolve


def _try_openat2(path: str, flags: int, mode: int) -> int | None:
    """Try to open `path` via openat2(RESOLVE_NO_SYMLINKS) on Linux 5.6+.

    Returns the opened fd on success, or None if openat2 is unavailable / not Linux.
    A parent-component symlink → OSError (ELOOP/ENOENT) propagated to caller.
    """
    if sys.platform != "linux":
        return None
    try:
        import ctypes
        import ctypes.util

        libc_name = ctypes.util.find_library("c")
        if libc_name is None:
            return None
        libc = ctypes.CDLL(libc_name, use_errno=True)

        # struct open_how: { u64 flags; u64 mode; u64 resolve; }
        class _OpenHow(ctypes.Structure):
            _fields_ = [
                ("flags", ctypes.c_uint64),
                ("mode", ctypes.c_uint64),
                ("resolve", ctypes.c_uint64),
            ]

        how = _OpenHow(flags=flags, mode=mode, resolve=_RESOLVE_NO_SYMLINKS)
        at_fdcwd = -100  # AT_FDCWD

        fd: int = libc.syscall(
            _SYS_OPENAT2,
            ctypes.c_int(at_fdcwd),
            path.encode(),
            ctypes.byref(how),
            ctypes.c_size_t(_OPEN_HOW_SIZE),
        )
        if fd < 0:
            errno = ctypes.get_errno()
            raise OSError(errno, os.strerror(errno), path)
        return fd
    except OSError:
        raise
    except Exception:
        return None


def _hardened_open(path: str, flags: int, mode: int) -> int:
    """Open `path` with parent-symlink protection.

    Linux 5.6+: openat2(RESOLVE_NO_SYMLINKS) — rejects symlinks in any component.
    Other / older: os.open with O_NOFOLLOW on the final component (existing recipe).
    """
    result = _try_openat2(path, flags, mode)
    if result is not None:
        return result
    # Fallback: O_NOFOLLOW on final component (pre-existing recipe).
    o_nofollow = getattr(os, "O_NOFOLLOW", 0)
    return os.open(path, flags | o_nofollow, mode)


# ---------------------------------------------------------------------------
# Shared helper (mirrors subprocess_tools / network_tools)
# ---------------------------------------------------------------------------


def _check_disallowed(params: dict[str, Any], allowed: frozenset[str], tool_name: str) -> None:
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

        # Control-plane denylist: deny writes under .git/ (ADR-036 D3-i, P6.9-#109).
        # .git/ is owned by git porcelain; agent edits of .git/config could inject
        # attacker-controlled remotes and reopen the P6.5-G1 exfil vector.
        # Check is apply_edit-local (not in _check_path) to leave read tools unaffected.
        parts = dest.relative_to(resolved_root).parts
        if parts and parts[0] == ".git":
            raise LocalToolError(
                "apply_edit: writes under .git/ are denied (control-plane path protection; "
                "ADR-036 D3-i)"
            )

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

            # P4.3-9: _hardened_open() uses openat2(RESOLVE_NO_SYMLINKS) on Linux 5.6+
            # (rejects parent-component symlinks planted between _check_path and write);
            # falls back to O_CREAT|O_EXCL|O_NOFOLLOW on macOS/Windows (final-component only).
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            fd = _hardened_open(tmp_name, flags, 0o600)
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
