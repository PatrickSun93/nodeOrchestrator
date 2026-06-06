"""P4.3-6 tests: subprocess tools route through sandboxed_run when available.

Tests (runtime mocked): subprocess path calls sandboxed_run (not raw spawn) when
available; fail-closed when not.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from orchestrator.sandbox.posture import PostureResolver, SandboxConfig
from orchestrator.sandbox.runtime import SandboxRuntime
from orchestrator.tools.local import LocalToolError
from orchestrator.tools.subprocess_tools import build_subprocess_tool_registry


def _make_resolver(available: bool = True, degraded: bool = False) -> PostureResolver:
    config = SandboxConfig(image="sandbox:test", degraded_app_level=degraded)
    if available:
        rt = SandboxRuntime(kind="docker", cli="/usr/bin/docker")
        rt.available = mock.Mock(return_value=True)  # type: ignore[method-assign]
    else:
        rt = None
    resolver = PostureResolver(config=config, runtime=rt)
    return resolver


# ---------------------------------------------------------------------------
# SANDBOXED: subprocess path calls sandboxed_run when available
# ---------------------------------------------------------------------------


def test_run_tests_calls_sandboxed_run_when_available(tmp_path: Path) -> None:
    resolver = _make_resolver(available=True)
    registry = build_subprocess_tool_registry(tmp_path, posture_resolver=resolver)
    fn = registry["run_tests"]

    with mock.patch("orchestrator.sandbox.spawn.sandboxed_run") as mock_sr:
        mock_sr.return_value = mock.Mock(exit_code=0, output="", truncated=False)
        fn({"path": None})

    mock_sr.assert_called_once()


def test_run_lint_calls_sandboxed_run_when_available(tmp_path: Path) -> None:
    resolver = _make_resolver(available=True)
    registry = build_subprocess_tool_registry(tmp_path, posture_resolver=resolver)
    fn = registry["run_lint"]

    with mock.patch("orchestrator.sandbox.spawn.sandboxed_run") as mock_sr:
        mock_sr.return_value = mock.Mock(exit_code=0, output="", truncated=False)
        fn({})

    mock_sr.assert_called_once()


def test_git_diff_calls_sandboxed_run_when_available(tmp_path: Path) -> None:
    resolver = _make_resolver(available=True)
    registry = build_subprocess_tool_registry(tmp_path, posture_resolver=resolver)
    fn = registry["git_diff"]

    with mock.patch("orchestrator.sandbox.spawn.sandboxed_run") as mock_sr:
        mock_sr.return_value = mock.Mock(exit_code=0, output="", truncated=False)
        fn({})

    mock_sr.assert_called_once()


# ---------------------------------------------------------------------------
# FAIL_CLOSED: raises LocalToolError(sandbox_unavailable:…) when not opted-in
# ---------------------------------------------------------------------------


def test_run_tests_fail_closed_when_unavailable(tmp_path: Path) -> None:
    resolver = _make_resolver(available=False, degraded=False)
    registry = build_subprocess_tool_registry(tmp_path, posture_resolver=resolver)
    fn = registry["run_tests"]

    with pytest.raises(LocalToolError, match="sandbox_unavailable"):
        fn({})


def test_git_diff_fail_closed_when_unavailable(tmp_path: Path) -> None:
    resolver = _make_resolver(available=False, degraded=False)
    registry = build_subprocess_tool_registry(tmp_path, posture_resolver=resolver)
    fn = registry["git_diff"]

    with pytest.raises(LocalToolError, match="sandbox_unavailable"):
        fn({})


# ---------------------------------------------------------------------------
# DEGRADED: falls back to app-level run_scoped_command (not sandboxed_run)
# ---------------------------------------------------------------------------


def test_run_tests_degraded_falls_back_to_app_level(tmp_path: Path) -> None:
    resolver = _make_resolver(available=False, degraded=True)
    registry = build_subprocess_tool_registry(tmp_path, posture_resolver=resolver)
    fn = registry["run_tests"]

    with mock.patch("orchestrator.tools.subprocess_tools.run_scoped_command") as mock_rsc:
        mock_rsc.return_value = mock.Mock(exit_code=0, output="ok", truncated=False)
        result = fn({})

    mock_rsc.assert_called()
    assert result is not None


# ---------------------------------------------------------------------------
# No resolver: original app-level behavior preserved
# ---------------------------------------------------------------------------


def test_no_resolver_uses_run_scoped_command(tmp_path: Path) -> None:
    registry = build_subprocess_tool_registry(tmp_path)
    fn = registry["run_tests"]

    with mock.patch("orchestrator.tools.subprocess_tools.run_scoped_command") as mock_rsc:
        mock_rsc.return_value = mock.Mock(exit_code=0, output="ok", truncated=False)
        fn({})

    mock_rsc.assert_called()


# ---------------------------------------------------------------------------
# _execute_local_call is byte-frozen (structural check via the constitution test)
# ---------------------------------------------------------------------------


def test_execute_local_call_not_referencing_sandbox(tmp_path: Path) -> None:
    """No sandbox symbols should appear in _execute_local_call (executor byte-frozen)."""
    import ast
    from pathlib import Path as _Path

    executor_path = (
        _Path(__file__).parent.parent.parent / "src" / "orchestrator" / "tools" / "executor.py"
    )
    tree = ast.parse(executor_path.read_text(encoding="utf-8"))

    fn_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_execute_local_call":
            fn_node = node
            break

    assert fn_node is not None, "_execute_local_call not found"

    sandbox_symbols = {"sandboxed_run", "PostureResolver", "SandboxRuntime", "sandbox"}
    violations = []
    for node in ast.walk(fn_node):
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if isinstance(node, ast.Name) else node.attr
            if name in sandbox_symbols:
                violations.append(f"executor.py:{node.lineno}: {name!r}")

    assert not violations, (
        "executor byte-frozen: _execute_local_call references sandbox symbols "
        "(wrap must live in subprocess_tools/sandbox, NOT in _execute_local_call):\n"
        + "\n".join(violations)
    )
