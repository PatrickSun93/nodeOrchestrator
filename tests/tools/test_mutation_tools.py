"""Tests for tools/mutation_tools.py — apply_edit (B5-1).

apply_edit: sandboxed in-process file write (no subprocess/network marker).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from orchestrator.mcp.execution import MAX_RESULT_BYTES
from orchestrator.tools.local import LocalToolError
from orchestrator.tools.mutation_tools import (
    _make_apply_edit,
    build_mutation_tool_registry,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sandbox(tmp_path: Path) -> Path:
    """Return a temporary sandbox root directory."""
    return tmp_path


@pytest.fixture()
def apply_edit(sandbox: Path) -> Any:
    """Return an apply_edit fn bound to the sandbox fixture."""
    return _make_apply_edit(sandbox)


# ---------------------------------------------------------------------------
# Section 1: Registry / marker
# ---------------------------------------------------------------------------


def test_build_mutation_tool_registry_keys(sandbox: Path) -> None:
    """build_mutation_tool_registry returns apply_edit."""
    reg = build_mutation_tool_registry(sandbox)
    assert "apply_edit" in reg


def test_apply_edit_no_network_marker(sandbox: Path) -> None:
    """apply_edit carries NO _is_network_tool marker (in-process, no cap)."""
    fn = _make_apply_edit(sandbox)
    assert not getattr(fn, "_is_network_tool", False)


def test_apply_edit_no_subprocess_marker(sandbox: Path) -> None:
    """apply_edit carries NO _is_posture_b_subprocess marker (in-process, no cap)."""
    fn = _make_apply_edit(sandbox)
    assert not getattr(fn, "_is_posture_b_subprocess", False)


# ---------------------------------------------------------------------------
# Section 2: Happy path — write new file + overwrite
# ---------------------------------------------------------------------------


def test_apply_edit_new_file(apply_edit: Any, sandbox: Path) -> None:
    """apply_edit creates a new file with the specified content."""
    result = apply_edit({"path": "new_file.txt", "content": "hello world"})
    assert (sandbox / "new_file.txt").read_text() == "hello world"
    assert "wrote" in result.content
    assert "new_file.txt" in result.content


def test_apply_edit_overwrite_existing(apply_edit: Any, sandbox: Path) -> None:
    """apply_edit overwrites an existing file atomically."""
    target = sandbox / "target.txt"
    target.write_text("old content")
    apply_edit({"path": "target.txt", "content": "new content"})
    assert target.read_text() == "new content"


def test_apply_edit_creates_parent_dirs(apply_edit: Any, sandbox: Path) -> None:
    """apply_edit creates intermediate parent directories inside the sandbox."""
    result = apply_edit({"path": "subdir/nested/file.py", "content": "x = 1"})
    assert (sandbox / "subdir" / "nested" / "file.py").read_text() == "x = 1"
    assert "nested/file.py" in result.content or "subdir" in result.content


def test_apply_edit_reports_byte_count(apply_edit: Any, sandbox: Path) -> None:
    """apply_edit reports the exact byte count written."""
    content = "abc"
    result = apply_edit({"path": "f.txt", "content": content})
    assert f"wrote {len(content.encode())} bytes" in result.content


def test_apply_edit_output_is_local_tool_output(apply_edit: Any, sandbox: Path) -> None:
    """apply_edit returns a LocalToolOutput (TRUSTED — no untrusted framing)."""
    from orchestrator.tools.executor import LocalToolOutput

    result = apply_edit({"path": "out.txt", "content": "data"})
    assert isinstance(result, LocalToolOutput)


# ---------------------------------------------------------------------------
# Section 3: Containment — path escapes refused
# ---------------------------------------------------------------------------


def test_apply_edit_traversal_refused(apply_edit: Any, sandbox: Path) -> None:
    """apply_edit refuses traversal paths that escape the sandbox root."""
    with pytest.raises(LocalToolError, match="escapes sandbox"):
        apply_edit({"path": "../escape.txt", "content": "bad"})


def test_apply_edit_absolute_path_refused(apply_edit: Any, sandbox: Path) -> None:
    """apply_edit refuses absolute paths outside the sandbox root."""
    with pytest.raises(LocalToolError):
        apply_edit({"path": "/etc/passwd", "content": "bad"})


def test_apply_edit_parent_symlink_escape_refused(apply_edit: Any, sandbox: Path) -> None:
    """apply_edit refuses a path whose parent is a symlink that escapes the sandbox."""
    # Create a symlink inside sandbox pointing outside
    outside = sandbox.parent / "outside_dir"
    outside.mkdir(exist_ok=True)
    link = sandbox / "link_to_outside"
    link.symlink_to(outside)
    with pytest.raises(LocalToolError):
        apply_edit({"path": "link_to_outside/../outside_dir/file.txt", "content": "bad"})


def test_apply_edit_existing_final_symlink_escape_refused(apply_edit: Any, sandbox: Path) -> None:
    """apply_edit refuses writing to an existing final-component symlink that escapes the sandbox.

    _check_path follows .resolve() which expands all symlinks; if the resolved path
    escapes the sandbox root, LocalToolError is raised BEFORE any write.
    """
    outside = sandbox.parent / "outside_target.txt"
    outside.write_text("original")
    # Create a symlink inside the sandbox pointing to an outside file
    link = sandbox / "escape_link.txt"
    link.symlink_to(outside)
    with pytest.raises(LocalToolError):
        apply_edit({"path": "escape_link.txt", "content": "injected"})
    # Original outside file must be untouched
    assert outside.read_text() == "original"


# ---------------------------------------------------------------------------
# Section 4: Bounded content — oversize refused before write
# ---------------------------------------------------------------------------


def test_apply_edit_oversize_content_refused(apply_edit: Any, sandbox: Path) -> None:
    """apply_edit refuses content larger than MAX_RESULT_BYTES before writing."""
    oversized = "x" * (MAX_RESULT_BYTES + 1)
    with pytest.raises(LocalToolError, match="exceeds max allowed size"):
        apply_edit({"path": "big.txt", "content": oversized})
    assert not (sandbox / "big.txt").exists()


# ---------------------------------------------------------------------------
# Section 5: Param allowlist
# ---------------------------------------------------------------------------


def test_apply_edit_disallowed_param(apply_edit: Any) -> None:
    """apply_edit raises LocalToolError for params outside {path, content}."""
    with pytest.raises(LocalToolError, match="disallowed param"):
        apply_edit({"path": "f.txt", "content": "ok", "extra": "bad"})


def test_apply_edit_missing_path(apply_edit: Any) -> None:
    """apply_edit raises LocalToolError when 'path' is missing."""
    with pytest.raises(LocalToolError, match="'path' is required"):
        apply_edit({"content": "no path"})


# ---------------------------------------------------------------------------
# Section 6: Atomic write — mid-write failure leaves no partial file
# ---------------------------------------------------------------------------


def test_apply_edit_atomic_no_partial_on_failure(sandbox: Path) -> None:
    """Mid-write failure leaves no partial file at the destination.

    We patch os.fsync to raise; the destination must remain absent (new file case)
    or unchanged (overwrite case).
    """
    import unittest.mock as mock

    apply_edit_fn = _make_apply_edit(sandbox)
    dest = sandbox / "atomic_test.txt"

    with (
        mock.patch("os.fsync", side_effect=OSError("simulated disk error")),
        pytest.raises(LocalToolError, match="write failed"),
    ):
        apply_edit_fn({"path": "atomic_test.txt", "content": "partial"})

    # New-file case: dest must not exist after the failure
    assert not dest.exists(), "Partial file left at destination after write failure"


def test_apply_edit_atomic_overwrite_no_partial(sandbox: Path) -> None:
    """Mid-write failure preserves the original file when overwriting."""
    import unittest.mock as mock

    apply_edit_fn = _make_apply_edit(sandbox)
    dest = sandbox / "existing.txt"
    dest.write_text("original content")

    with (
        mock.patch("os.fsync", side_effect=OSError("simulated disk error")),
        pytest.raises(LocalToolError, match="write failed"),
    ):
        apply_edit_fn({"path": "existing.txt", "content": "new content"})

    # Original file must be intact
    assert dest.read_text() == "original content"
