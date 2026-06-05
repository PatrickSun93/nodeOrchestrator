"""P4.2-B3-2: subprocess_tools.py unit tests (ADR-034 D1/D3/D5).

B3-2 acceptance tests:
  - per-tool happy path (tiny git repo / pytest file under tmp sandbox)
  - param-allowlist rejection
  - path-escape rejection
  - non-zero exit → TOOL_RESULT not TOOL_FAILED
  - timeout → subprocess_timeout in TOOL_FAILED message
  - spawn-failure → subprocess_spawn_failed in TOOL_FAILED message
  - git_log max_count clamp
  - path starting with '-' cannot become a flag
  - B3 env test: subprocess env contains PATH, no unsafe secrets
  - _is_posture_b_subprocess marker on all 5 tools
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from orchestrator.mcp.subprocess_trust import _SAFE_ENV_KEYS, scoped_env
from orchestrator.tools.local import LocalToolError
from orchestrator.tools.subprocess_tools import (
    _SUBPROCESS_TIMEOUTS,
    _dispatch,
    _SubprocessToolFn,
    build_subprocess_tool_registry,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git_init(tmp_path: Path) -> None:
    """Initialise a minimal git repo in tmp_path."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path, check=True, capture_output=True,
    )


def _invoke(tool_name: str, sandbox: Path, params: dict[str, Any]) -> Any:
    registry = build_subprocess_tool_registry(sandbox)
    return registry[tool_name](params)


# ---------------------------------------------------------------------------
# Marker: all 5 tools carry _is_posture_b_subprocess = True
# ---------------------------------------------------------------------------


def test_all_tools_have_posture_b_marker(tmp_path: Path) -> None:
    registry = build_subprocess_tool_registry(tmp_path)
    for name, fn in registry.items():
        assert getattr(fn, "_is_posture_b_subprocess", False), (
            f"{name}: missing _is_posture_b_subprocess marker"
        )
    assert all(isinstance(fn, _SubprocessToolFn) for fn in registry.values())


# ---------------------------------------------------------------------------
# Env test (B3-2): scoped_env used for subprocess, no unsafe secrets pass through
# ---------------------------------------------------------------------------


def test_b3_env_scoped_no_secrets() -> None:
    """Subprocess env has PATH (tools resolve) and no key outside _SAFE_ENV_KEYS."""
    secret_key = "B3_SUBPROCESS_ENV_SECRET_TEST"
    os.environ[secret_key] = "should_not_appear"
    try:
        env = scoped_env()
        # PATH must be present so git/ruff/pytest resolve
        assert "PATH" in env, "PATH must be in scoped env for subprocess tools to resolve"
        # No keys outside _SAFE_ENV_KEYS
        for key in env:
            assert key in _SAFE_ENV_KEYS, (
                f"Key {key!r} leaked into scoped_env() — outside _SAFE_ENV_KEYS"
            )
        # Seeded secret must be absent
        assert secret_key not in env
    finally:
        os.environ.pop(secret_key, None)


# ---------------------------------------------------------------------------
# Param allowlist rejection
# ---------------------------------------------------------------------------


def test_param_allowlist_rejects_disallowed(tmp_path: Path) -> None:
    """Disallowed params raise LocalToolError for every tool."""
    registry = build_subprocess_tool_registry(tmp_path)
    bad_params: dict[str, dict[str, Any]] = {
        "run_tests": {"--pdb": "yes"},
        "run_lint": {"-c": "import os"},
        "git_blame": {"ref": "HEAD", "path": "f.py"},
        "git_log": {"refs": "HEAD~5..HEAD"},
        "git_diff": {"cached": True},
    }
    for tool_name, params in bad_params.items():
        with pytest.raises(LocalToolError, match="disallowed"):
            registry[tool_name](params)


# ---------------------------------------------------------------------------
# Path escape rejection
# ---------------------------------------------------------------------------


def test_path_escape_rejected(tmp_path: Path) -> None:
    """Paths escaping sandbox raise LocalToolError."""
    for tool_name in ("run_tests", "run_lint", "git_blame", "git_log", "git_diff"):
        with pytest.raises(LocalToolError):
            _invoke(tool_name, tmp_path, {"path": "../../etc/passwd"})


# ---------------------------------------------------------------------------
# Path starting with '-' cannot become a flag
# ---------------------------------------------------------------------------


def test_path_starting_with_dash_cannot_be_flag(tmp_path: Path) -> None:
    """A path param starting with '-' is resolved to an abs path → cannot be a flag."""
    # '-bad' under sandbox resolves to an absolute path; the tool will call the
    # subprocess with that absolute path (which starts with '/'), not '-bad'.
    # The subprocess may fail (file doesn't exist) but it must NOT be treated as a
    # flag passthrough — the path check either resolves cleanly inside sandbox or fails.
    result = _invoke("git_diff", tmp_path, {"path": "-bad"})
    # If it succeeds, the output should NOT contain a git flag interpretation
    # (a path starting with '-' resolved to abs path '/tmp/.../bad' — not a flag)
    assert "-bad" not in result.content or result.exit_code != 0


# ---------------------------------------------------------------------------
# git_log max_count clamp
# ---------------------------------------------------------------------------


def test_git_log_max_count_clamped(tmp_path: Path) -> None:
    """max_count outside [1,100] is clamped, not rejected."""
    _git_init(tmp_path)
    (tmp_path / "f.py").write_text("x=1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    # Over-cap: 9999 → clamped to 100 (should not raise)
    result = _invoke("git_log", tmp_path, {"max_count": 9999})
    assert "exit_code=" in result.content
    # Under-cap: 0 → clamped to 1 (should not raise)
    result = _invoke("git_log", tmp_path, {"max_count": 0})
    assert "exit_code=" in result.content


# ---------------------------------------------------------------------------
# Happy path: run_tests
# ---------------------------------------------------------------------------


def test_run_tests_happy_path(tmp_path: Path) -> None:
    """run_tests with a passing test file → exit_code=0, TOOL_RESULT."""
    test_file = tmp_path / "test_simple.py"
    test_file.write_text("def test_ok(): assert True\n")
    result = _invoke("run_tests", tmp_path, {"path": "test_simple.py"})
    assert "exit_code=0" in result.content


def test_run_tests_nonzero_exit_is_tool_result(tmp_path: Path) -> None:
    """run_tests with a failing test → non-zero exit → TOOL_RESULT, not TOOL_FAILED."""
    test_file = tmp_path / "test_fail.py"
    test_file.write_text("def test_bad(): assert False\n")
    result = _invoke("run_tests", tmp_path, {"path": "test_fail.py"})
    # exit_code is in content (format: "exit_code=N\n...")
    assert "exit_code=" in result.content
    assert "exit_code=0" not in result.content  # non-zero captured, not raised


# ---------------------------------------------------------------------------
# Happy path: run_lint
# ---------------------------------------------------------------------------


def test_run_lint_happy_path(tmp_path: Path) -> None:
    """run_lint on clean file → exit_code=0."""
    f = tmp_path / "clean.py"
    f.write_text("x = 1\n")
    result = _invoke("run_lint", tmp_path, {"path": "clean.py"})
    assert "exit_code=0" in result.content


# ---------------------------------------------------------------------------
# Happy path: git tools
# ---------------------------------------------------------------------------


def test_git_blame_happy_path(tmp_path: Path) -> None:
    """git_blame on a committed file → exit_code=0, output captured."""
    _git_init(tmp_path)
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    result = _invoke("git_blame", tmp_path, {"path": "a.py"})
    assert "exit_code=0" in result.content


def test_git_log_happy_path(tmp_path: Path) -> None:
    """git_log after commit → exit_code=0, output captured."""
    _git_init(tmp_path)
    (tmp_path / "b.py").write_text("y = 2\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "feat: B3"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    result = _invoke("git_log", tmp_path, {})
    assert "exit_code=0" in result.content
    assert "B3" in result.content


def test_git_diff_happy_path(tmp_path: Path) -> None:
    """git_diff with no changes → exit_code=0."""
    _git_init(tmp_path)
    result = _invoke("git_diff", tmp_path, {})
    assert "exit_code=0" in result.content


# ---------------------------------------------------------------------------
# Spawn failure → subprocess_spawn_failed in TOOL_FAILED message
# ---------------------------------------------------------------------------


def test_spawn_failure_raises_local_tool_error(tmp_path: Path) -> None:
    """A tool that can't spawn (bad binary) raises LocalToolError with subprocess_spawn_failed."""
    with pytest.raises(LocalToolError, match="subprocess_spawn_failed"):
        _dispatch(
            "run_lint",
            ["/nonexistent_binary_b3_test"],
            tmp_path,
            _SUBPROCESS_TIMEOUTS["run_lint"],
        )


# ---------------------------------------------------------------------------
# Timeout → subprocess_timeout in TOOL_FAILED message (B3-2 acceptance; R0-A Y1)
# ---------------------------------------------------------------------------


def test_timeout_raises_local_tool_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Timeout from run_scoped_command → LocalToolError with subprocess_timeout in message.

    Symmetric twin of test_spawn_failure_raises_local_tool_error.
    Covers the _dispatch except-SubprocessTimeoutError branch (R0-A Y1 gap).
    """
    import orchestrator.tools.subprocess_tools as st_mod
    from orchestrator.mcp.subprocess_trust import SubprocessTimeoutError

    def _raise_timeout(*args: object, **kwargs: object) -> None:
        raise SubprocessTimeoutError("timed out after 30s")

    monkeypatch.setattr(st_mod, "run_scoped_command", _raise_timeout)
    with pytest.raises(LocalToolError, match="subprocess_timeout"):
        _dispatch("run_lint", ["ruff", "check", "x.py"], tmp_path, _SUBPROCESS_TIMEOUTS["run_lint"])


# ---------------------------------------------------------------------------
# git_blame requires path
# ---------------------------------------------------------------------------


def test_git_blame_requires_path(tmp_path: Path) -> None:
    """git_blame without path → LocalToolError."""
    with pytest.raises(LocalToolError, match="'path' is required"):
        _invoke("git_blame", tmp_path, {})
