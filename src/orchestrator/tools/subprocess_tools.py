"""Subprocess local tool closures (ADR-034 D1/D3/D5; P4.2-B3-2).

Each closure is a LocalToolFn that:
  - Validates its param allowlist (no flag passthrough).
  - Resolves path via _check_path → absolute path into argv (never the raw LLM string).
  - Calls run_scoped_command with scoped_env() and a per-tool timeout.
  - Returns LocalToolOutput at any exit code (non-zero = TOOL_RESULT, not TOOL_FAILED).
  - Carries _is_posture_b_subprocess = True for the per-turn cap.

Do NOT add to tools/local.py (constitution t6 forbids subprocess there — local.py
is in-process-pristine; subprocess surface lives here only).

Env: scoped_env() with no extra_env, no api_key_env — B3 tools need no secrets.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, ClassVar

from orchestrator.mcp.execution import MAX_RESULT_BYTES
from orchestrator.mcp.subprocess_trust import (
    SubprocessTimeoutError,
    run_scoped_command,
    scoped_env,
)
from orchestrator.tools.executor import LocalToolFn, LocalToolOutput
from orchestrator.tools.local import LocalToolError, _check_path

# Per-tool timeouts (R0-B B1 — closes the unbound term in the single-writer bound).
_SUBPROCESS_TIMEOUTS: dict[str, float] = {
    "run_tests": 120.0,
    "run_lint": 30.0,
    "git_blame": 10.0,
    "git_log": 10.0,
    "git_diff": 10.0,
}

_GIT_LOG_MAX_COUNT_MIN = 1
_GIT_LOG_MAX_COUNT_MAX = 100
_GIT_LOG_DEFAULT_COUNT = 50


# ---------------------------------------------------------------------------
# Callable class wrapper: _is_posture_b_subprocess marker (ClassVar, mypy-safe)
# ---------------------------------------------------------------------------


class _SubprocessToolFn:
    """Callable class wrapping a subprocess tool impl with the Posture-B marker.

    The ClassVar marker lets executor.py identify subprocess-launching local tools
    for the per-turn cap (MAX_SUBPROCESS_CALLS_PER_TURN). Mirrors _PostureBFn in
    plugins/code.py; now marks both plugin tools AND B3 subprocess tools.
    """

    _is_posture_b_subprocess: ClassVar[bool] = True

    def __init__(self, impl: LocalToolFn) -> None:
        self._impl = impl

    def __call__(self, params: dict[str, Any]) -> LocalToolOutput:
        return self._impl(params)


# ---------------------------------------------------------------------------
# Shared helpers
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


def _dispatch(tool_name: str, argv: list[str], cwd: Path, timeout_s: float) -> LocalToolOutput:
    """Call run_scoped_command and format result as LocalToolOutput.

    Non-zero exit → TOOL_RESULT (expected output; failing tests/lint is not an error).
    Timeout → raise LocalToolError with subprocess_timeout class encoded in message.
    Spawn failure → raise LocalToolError with subprocess_spawn_failed class encoded.
    """
    env = scoped_env()  # no extra_env, no api_key_env — B3 tools need no secrets
    try:
        result = run_scoped_command(
            argv, cwd=cwd, env=env, timeout_s=timeout_s, max_bytes=MAX_RESULT_BYTES
        )
    except SubprocessTimeoutError as exc:
        raise LocalToolError(
            f"subprocess_timeout: {tool_name} exceeded timeout ({timeout_s}s): {exc}"
        ) from exc
    except OSError as exc:
        raise LocalToolError(
            f"subprocess_spawn_failed: {tool_name} could not start: {exc}"
        ) from exc

    content = f"exit_code={result.exit_code}\n{result.output}"
    truncated_at = MAX_RESULT_BYTES if result.truncated else None
    return LocalToolOutput(content=content, output_truncated_at=truncated_at)


# ---------------------------------------------------------------------------
# Individual tool factories
# ---------------------------------------------------------------------------


def _make_run_tests(sandbox_root: Path) -> _SubprocessToolFn:
    resolved_root = sandbox_root.resolve()
    allowed: frozenset[str] = frozenset({"path"})

    def _impl(params: dict[str, Any]) -> LocalToolOutput:
        _check_disallowed(params, allowed, "run_tests")
        path_str: str | None = params.get("path") or None
        argv: list[str] = [sys.executable, "-m", "pytest", "-q"]
        if path_str:
            abs_path = _check_path(path_str, resolved_root)
            argv.append(str(abs_path))
        return _dispatch("run_tests", argv, resolved_root, _SUBPROCESS_TIMEOUTS["run_tests"])

    return _SubprocessToolFn(_impl)


def _make_run_lint(sandbox_root: Path) -> _SubprocessToolFn:
    resolved_root = sandbox_root.resolve()
    allowed: frozenset[str] = frozenset({"path"})

    def _impl(params: dict[str, Any]) -> LocalToolOutput:
        _check_disallowed(params, allowed, "run_lint")
        path_str: str | None = params.get("path") or None
        abs_path = _check_path(path_str, resolved_root) if path_str else resolved_root
        argv: list[str] = ["ruff", "check", "--", str(abs_path)]
        return _dispatch("run_lint", argv, resolved_root, _SUBPROCESS_TIMEOUTS["run_lint"])

    return _SubprocessToolFn(_impl)


def _make_git_blame(sandbox_root: Path) -> _SubprocessToolFn:
    resolved_root = sandbox_root.resolve()
    allowed: frozenset[str] = frozenset({"path"})

    def _impl(params: dict[str, Any]) -> LocalToolOutput:
        _check_disallowed(params, allowed, "git_blame")
        path_str = str(params.get("path", ""))
        if not path_str:
            raise LocalToolError("git_blame: 'path' is required")
        abs_path = _check_path(path_str, resolved_root)
        argv: list[str] = ["git", "blame", "--", str(abs_path)]
        return _dispatch("git_blame", argv, resolved_root, _SUBPROCESS_TIMEOUTS["git_blame"])

    return _SubprocessToolFn(_impl)


def _make_git_log(sandbox_root: Path) -> _SubprocessToolFn:
    resolved_root = sandbox_root.resolve()
    allowed: frozenset[str] = frozenset({"path", "max_count"})

    def _impl(params: dict[str, Any]) -> LocalToolOutput:
        _check_disallowed(params, allowed, "git_log")
        path_str: str | None = params.get("path") or None

        raw_count = params.get("max_count")
        if raw_count is not None:
            try:
                count = int(raw_count)
            except (TypeError, ValueError) as exc:
                raise LocalToolError(
                    f"git_log: max_count must be an integer: {exc}"
                ) from exc
            count = max(_GIT_LOG_MAX_COUNT_MIN, min(_GIT_LOG_MAX_COUNT_MAX, count))
        else:
            count = _GIT_LOG_DEFAULT_COUNT

        argv: list[str] = ["git", "log", "-n", str(count), "--"]
        if path_str:
            abs_path = _check_path(path_str, resolved_root)
            argv.append(str(abs_path))
        return _dispatch("git_log", argv, resolved_root, _SUBPROCESS_TIMEOUTS["git_log"])

    return _SubprocessToolFn(_impl)


def _make_git_diff(sandbox_root: Path) -> _SubprocessToolFn:
    resolved_root = sandbox_root.resolve()
    allowed: frozenset[str] = frozenset({"path"})

    def _impl(params: dict[str, Any]) -> LocalToolOutput:
        _check_disallowed(params, allowed, "git_diff")
        path_str: str | None = params.get("path") or None
        argv: list[str] = ["git", "diff", "--"]
        if path_str:
            abs_path = _check_path(path_str, resolved_root)
            argv.append(str(abs_path))
        return _dispatch("git_diff", argv, resolved_root, _SUBPROCESS_TIMEOUTS["git_diff"])

    return _SubprocessToolFn(_impl)


# ---------------------------------------------------------------------------
# Registry builder
# ---------------------------------------------------------------------------


def build_subprocess_tool_registry(sandbox_root: Path) -> dict[str, LocalToolFn]:
    """Build the 5 subprocess local tools for the given sandbox root.

    Returns a dict keyed by tool name (matching tools.yaml classifications).
    Each value is a _SubprocessToolFn carrying _is_posture_b_subprocess = True.
    """
    return {
        "run_tests": _make_run_tests(sandbox_root),
        "run_lint": _make_run_lint(sandbox_root),
        "git_blame": _make_git_blame(sandbox_root),
        "git_log": _make_git_log(sandbox_root),
        "git_diff": _make_git_diff(sandbox_root),
    }
