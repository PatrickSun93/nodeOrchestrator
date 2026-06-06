"""Subprocess local tool closures (ADR-034 D1/D3/D5; P4.2-B3-2; ADR-036 D3-iii B5-3).

Each closure is a LocalToolFn that:
  - Validates its param allowlist (no flag passthrough).
  - Resolves path via _check_path → absolute path into argv (never the raw LLM string).
  - Routes through sandboxed_run (ADR-037 D2/D3; P4.3-6) when a PostureResolver is
    injected and the sandbox runtime is available; falls back to run_scoped_command on
    DEGRADED opt-in; raises LocalToolError(sandbox_unavailable:…) on FAIL_CLOSED.
  - Returns LocalToolOutput at any exit code (non-zero = TOOL_RESULT, not TOOL_FAILED).
  - Carries _is_posture_b_subprocess = True for the per-turn cap.

Do NOT add to tools/local.py (constitution t6 forbids subprocess there — local.py
is in-process-pristine; subprocess surface lives here only).

B3 tools env: scoped_env() with no extra_env, no api_key_env — B3 tools need no secrets.
git_push env: scoped_env(extra_env={SSH_AUTH_SOCK: ...}) for ssh-agent (ADR-036 D3-iii).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from orchestrator.mcp.execution import MAX_RESULT_BYTES
from orchestrator.mcp.subprocess_trust import (
    SubprocessTimeoutError,
    run_scoped_command,
    scoped_env,
)
from orchestrator.tools.executor import LocalToolFn, LocalToolOutput
from orchestrator.tools.local import LocalToolError, _check_path

if TYPE_CHECKING:
    from orchestrator.sandbox.posture import PostureResolver

# Per-tool timeouts (R0-B B1 — closes the unbound term in the single-writer bound).
_SUBPROCESS_TIMEOUTS: dict[str, float] = {
    "run_tests": 120.0,
    "run_lint": 30.0,
    "git_blame": 10.0,
    "git_log": 10.0,
    "git_diff": 10.0,
    "git_push": 30.0,
}

# Named non-secret env keys to passthrough for git_push (ADR-036 D3-iii).
# SSH_AUTH_SOCK is a unix-socket PATH (not a credential value); allows ssh-agent auth.
# HOME is already in _SAFE_ENV_KEYS (credential.helper + on-disk SSH keys work).
# No api_key_env passed -> no secret value injected (scoped_env secret-injection off).
_GIT_PUSH_ENV_PASSTHROUGH: frozenset[str] = frozenset({"SSH_AUTH_SOCK"})

# Destructive git flags banned from git_push argv (ADR-036 D3-iii; rev 1 = most irreversible).
_GIT_PUSH_BANNED_FLAGS: frozenset[str] = frozenset(
    {"--force", "--force-with-lease", "-f", "--mirror", "--delete"}
)

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


def _dispatch(
    tool_name: str,
    argv: list[str],
    cwd: Path,
    timeout_s: float,
    extra_env: dict[str, str] | None = None,
) -> LocalToolOutput:
    """Call run_scoped_command and format result as LocalToolOutput.

    Non-zero exit → TOOL_RESULT (expected output; failing tests/lint is not an error).
    Timeout → raise LocalToolError with subprocess_timeout class encoded in message.
    Spawn failure → raise LocalToolError with subprocess_spawn_failed class encoded.
    extra_env: overlay non-secret env vars (e.g. SSH_AUTH_SOCK for git_push).
    """
    env = scoped_env(extra_env=extra_env or {})  # no api_key_env — no secret injection
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


def _sandbox_dispatch(
    tool_name: str,
    argv: list[str],
    cwd: Path,
    timeout_s: float,
    posture_resolver: PostureResolver,
    image: str,
    extra_env: dict[str, str] | None = None,
    needs_egress: bool = False,
    egress_hostname: str | None = None,
    egress_port: int = 443,
) -> LocalToolOutput:
    """Sandbox-aware dispatch (ADR-037 D2/D3; P4.3-6).

    SANDBOXED  → sandboxed_run with deny-default (or pinned-IP for egress tools).
    DEGRADED   → fall through to app-level run_scoped_command (warning already emitted).
    FAIL_CLOSED → LocalToolError(sandbox_unavailable:…).

    The wrap lives below _execute_local_call (executor byte-frozen; ADR-037 constitutional).
    """
    from orchestrator.sandbox.egress import (
        EgressDenied,
        build_deny_default_spec,
        build_egress_spec,
    )
    from orchestrator.sandbox.profile import SandboxProfile
    from orchestrator.sandbox.runtime import SandboxUnavailableError
    from orchestrator.sandbox.spawn import sandboxed_run

    env = scoped_env(extra_env=extra_env or {})

    try:
        runtime = posture_resolver.assert_sandboxed_or_raise(tool_name)
    except SandboxUnavailableError as exc:
        if posture_resolver.is_degraded_opted_in():
            # DEGRADED: fall back to app-level run_scoped_command (warning already logged).
            return _dispatch(tool_name, argv, cwd, timeout_s, extra_env)
        raise LocalToolError(f"sandbox_unavailable: {tool_name}: {exc}") from exc

    # Build egress spec.
    if needs_egress and egress_hostname is not None:
        try:
            from orchestrator.tools.net_trust import _resolve_and_validate

            pinned_ip = _resolve_and_validate(egress_hostname, egress_port)
            egress_spec = build_egress_spec(
                pinned_ip,
                egress_port,
                runtime_kind=runtime.kind,
                tool_kind="subprocess",
                hostname=egress_hostname,
                call_id=tool_name,
            )
        except (EgressDenied, LocalToolError) as exc:
            raise LocalToolError(
                f"sandbox_egress_denied: {tool_name}: {exc}"
            ) from exc
    else:
        egress_spec = build_deny_default_spec()

    profile = SandboxProfile(sandbox_root=cwd, image=image)

    try:
        result = sandboxed_run(
            argv,
            cwd=cwd,
            env=env,
            timeout_s=timeout_s,
            max_bytes=MAX_RESULT_BYTES,
            profile=profile,
            egress_spec=egress_spec,
            runtime=runtime,
        )
    except SandboxUnavailableError as exc:
        raise LocalToolError(f"sandbox_unavailable: {tool_name}: {exc}") from exc
    except SubprocessTimeoutError as exc:
        raise LocalToolError(
            f"subprocess_timeout: {tool_name} exceeded timeout ({timeout_s}s): {exc}"
        ) from exc

    content = f"exit_code={result.exit_code}\n{result.output}"
    truncated_at = MAX_RESULT_BYTES if result.truncated else None
    return LocalToolOutput(content=content, output_truncated_at=truncated_at)


# ---------------------------------------------------------------------------
# Individual tool factories
# ---------------------------------------------------------------------------


def _make_run_tests(
    sandbox_root: Path,
    posture_resolver: PostureResolver | None = None,
) -> _SubprocessToolFn:
    resolved_root = sandbox_root.resolve()
    allowed: frozenset[str] = frozenset({"path"})
    image = posture_resolver._config.image if posture_resolver is not None else ""

    def _impl(params: dict[str, Any]) -> LocalToolOutput:
        _check_disallowed(params, allowed, "run_tests")
        path_str: str | None = params.get("path") or None
        argv: list[str] = [sys.executable, "-m", "pytest", "-q"]
        if path_str:
            abs_path = _check_path(path_str, resolved_root)
            argv.append(str(abs_path))
        if posture_resolver is not None:
            return _sandbox_dispatch(
                "run_tests", argv, resolved_root, _SUBPROCESS_TIMEOUTS["run_tests"],
                posture_resolver, image,
            )
        return _dispatch("run_tests", argv, resolved_root, _SUBPROCESS_TIMEOUTS["run_tests"])

    return _SubprocessToolFn(_impl)


def _make_run_lint(
    sandbox_root: Path,
    posture_resolver: PostureResolver | None = None,
) -> _SubprocessToolFn:
    resolved_root = sandbox_root.resolve()
    allowed: frozenset[str] = frozenset({"path"})
    image = posture_resolver._config.image if posture_resolver is not None else ""

    def _impl(params: dict[str, Any]) -> LocalToolOutput:
        _check_disallowed(params, allowed, "run_lint")
        path_str: str | None = params.get("path") or None
        abs_path = _check_path(path_str, resolved_root) if path_str else resolved_root
        argv: list[str] = ["ruff", "check", "--", str(abs_path)]
        if posture_resolver is not None:
            return _sandbox_dispatch(
                "run_lint", argv, resolved_root, _SUBPROCESS_TIMEOUTS["run_lint"],
                posture_resolver, image,
            )
        return _dispatch("run_lint", argv, resolved_root, _SUBPROCESS_TIMEOUTS["run_lint"])

    return _SubprocessToolFn(_impl)


def _make_git_blame(
    sandbox_root: Path,
    posture_resolver: PostureResolver | None = None,
) -> _SubprocessToolFn:
    resolved_root = sandbox_root.resolve()
    allowed: frozenset[str] = frozenset({"path"})
    image = posture_resolver._config.image if posture_resolver is not None else ""

    def _impl(params: dict[str, Any]) -> LocalToolOutput:
        _check_disallowed(params, allowed, "git_blame")
        path_str = str(params.get("path", ""))
        if not path_str:
            raise LocalToolError("git_blame: 'path' is required")
        abs_path = _check_path(path_str, resolved_root)
        argv: list[str] = ["git", "blame", "--", str(abs_path)]
        if posture_resolver is not None:
            return _sandbox_dispatch(
                "git_blame", argv, resolved_root, _SUBPROCESS_TIMEOUTS["git_blame"],
                posture_resolver, image,
            )
        return _dispatch("git_blame", argv, resolved_root, _SUBPROCESS_TIMEOUTS["git_blame"])

    return _SubprocessToolFn(_impl)


def _make_git_log(
    sandbox_root: Path,
    posture_resolver: PostureResolver | None = None,
) -> _SubprocessToolFn:
    resolved_root = sandbox_root.resolve()
    allowed: frozenset[str] = frozenset({"path", "max_count"})
    image = posture_resolver._config.image if posture_resolver is not None else ""

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
        if posture_resolver is not None:
            return _sandbox_dispatch(
                "git_log", argv, resolved_root, _SUBPROCESS_TIMEOUTS["git_log"],
                posture_resolver, image,
            )
        return _dispatch("git_log", argv, resolved_root, _SUBPROCESS_TIMEOUTS["git_log"])

    return _SubprocessToolFn(_impl)


def _make_git_diff(
    sandbox_root: Path,
    posture_resolver: PostureResolver | None = None,
) -> _SubprocessToolFn:
    resolved_root = sandbox_root.resolve()
    allowed: frozenset[str] = frozenset({"path"})
    image = posture_resolver._config.image if posture_resolver is not None else ""

    def _impl(params: dict[str, Any]) -> LocalToolOutput:
        _check_disallowed(params, allowed, "git_diff")
        path_str: str | None = params.get("path") or None
        argv: list[str] = ["git", "diff", "--"]
        if path_str:
            abs_path = _check_path(path_str, resolved_root)
            argv.append(str(abs_path))
        if posture_resolver is not None:
            return _sandbox_dispatch(
                "git_diff", argv, resolved_root, _SUBPROCESS_TIMEOUTS["git_diff"],
                posture_resolver, image,
            )
        return _dispatch("git_diff", argv, resolved_root, _SUBPROCESS_TIMEOUTS["git_diff"])

    return _SubprocessToolFn(_impl)


def _make_git_push(
    sandbox_root: Path,
    posture_resolver: PostureResolver | None = None,
) -> _SubprocessToolFn:
    """Build a git_push impl for the sandbox root (ADR-036 D3-iii; P4.3-6).

    argv: fixed ["git", "push", <remote>, <branch>] — never shell-string (t9 covers this).
    env: scoped_env with SSH_AUTH_SOCK overlay for ssh-agent (named non-secret passthrough).
         HOME already in _SAFE_ENV_KEYS (credential.helper + on-disk SSH keys work).
         No api_key_env -> no secret value injected.
    Output: remote push status as raw TOOL_RESULT (remote text = attacker-authorable).
    Destructive flags banned: --force/--force-with-lease/-f/--mirror/--delete (t12 guards).
    Sandbox: when posture_resolver available, routes through sandboxed_run with pinned-IP
    egress for the resolved remote host (ADR-037 D2; deny-default for non-egress tools).
    """
    resolved_root = sandbox_root.resolve()
    allowed: frozenset[str] = frozenset({"remote", "branch"})
    image = posture_resolver._config.image if posture_resolver is not None else ""

    def _impl(params: dict[str, Any]) -> LocalToolOutput:
        _check_disallowed(params, allowed, "git_push")

        remote = str(params.get("remote", "origin"))
        branch_raw: str | None = params.get("branch") or None

        # Resolve current branch if not specified.
        if branch_raw is None:
            # Read current HEAD branch from git (scoped_env, no network).
            head_env = scoped_env()
            try:
                head_result = run_scoped_command(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=resolved_root,
                    env=head_env,
                    timeout_s=5.0,
                    max_bytes=256,
                )
                branch_raw = head_result.output.strip() or "HEAD"
            except (SubprocessTimeoutError, OSError):
                branch_raw = "HEAD"

        branch = branch_raw

        # Reject flag-shaped remote/branch (values starting with "-").
        if remote.startswith("-"):
            raise LocalToolError(
                f"git_push: remote {remote!r} looks like a flag (starts with '-'); "
                "rejected to prevent argv injection"
            )
        if branch.startswith("-"):
            raise LocalToolError(
                f"git_push: branch {branch!r} looks like a flag (starts with '-'); "
                "rejected to prevent argv injection"
            )

        # Validate no banned destructive flags appear in remote/branch (defense-in-depth).
        for val, label in [(remote, "remote"), (branch, "branch")]:
            if val in _GIT_PUSH_BANNED_FLAGS:
                raise LocalToolError(
                    f"git_push: {label} {val!r} is a banned destructive flag"
                )

        # Fixed argv — no shell, no interpolation (t9 + t12 guard).
        argv: list[str] = ["git", "push", remote, branch]

        # Named SSH_AUTH_SOCK overlay: passthrough unix-socket PATH (not a secret value).
        extra_env: dict[str, str] = {
            k: os.environ[k] for k in _GIT_PUSH_ENV_PASSTHROUGH if k in os.environ
        }

        if posture_resolver is not None:
            # Sandbox path: pinned-IP egress for git_push (ADR-037 D2; P4.3-6).
            # The egress hostname is resolved from the remote name via git.
            egress_hostname, egress_port = _resolve_git_remote_host(remote, resolved_root)
            return _sandbox_dispatch(
                "git_push", argv, resolved_root, _SUBPROCESS_TIMEOUTS["git_push"],
                posture_resolver, image, extra_env=extra_env,
                needs_egress=egress_hostname is not None,
                egress_hostname=egress_hostname,
                egress_port=egress_port,
            )
        return _dispatch(
            "git_push", argv, resolved_root, _SUBPROCESS_TIMEOUTS["git_push"], extra_env=extra_env
        )

    return _SubprocessToolFn(_impl)


def _resolve_git_remote_host(remote: str, cwd: Path) -> tuple[str | None, int]:
    """Resolve a git remote name to (hostname, port) for egress pinning.

    Returns (None, 22) if resolution fails (caller uses deny-default).
    Supports https:// and git@host:path SSH remotes.
    """
    try:
        result = run_scoped_command(
            ["git", "remote", "get-url", remote],
            cwd=cwd,
            env=scoped_env(),
            timeout_s=5.0,
            max_bytes=512,
        )
        url = result.output.strip()
    except (SubprocessTimeoutError, OSError):
        return None, 22

    if not url:
        return None, 22

    # https:// or http:// remote
    if url.startswith("https://") or url.startswith("http://"):
        from urllib.parse import urlparse

        parsed = urlparse(url)
        hostname = parsed.hostname or None
        port = parsed.port or (443 if url.startswith("https://") else 80)
        return hostname, port

    # git@host:path or ssh://user@host/path
    if url.startswith("ssh://"):
        from urllib.parse import urlparse

        parsed = urlparse(url)
        return parsed.hostname or None, parsed.port or 22

    if "@" in url and ":" in url:
        # git@github.com:user/repo.git format
        host_part = url.split("@", 1)[1].split(":")[0]
        return host_part or None, 22

    return None, 22


# ---------------------------------------------------------------------------
# Registry builder
# ---------------------------------------------------------------------------


def build_subprocess_tool_registry(
    sandbox_root: Path,
    posture_resolver: PostureResolver | None = None,
) -> dict[str, LocalToolFn]:
    """Build the subprocess local tools for the given sandbox root.

    Returns a dict keyed by tool name (matching tools.yaml classifications).
    Each value is a _SubprocessToolFn carrying _is_posture_b_subprocess = True.

    posture_resolver: if provided, each tool routes through sandboxed_run (ADR-037 D2/D3;
    P4.3-6). None = today's app-level posture (no sandbox wiring; degraded path).
    """
    return {
        "run_tests": _make_run_tests(sandbox_root, posture_resolver),
        "run_lint": _make_run_lint(sandbox_root, posture_resolver),
        "git_blame": _make_git_blame(sandbox_root, posture_resolver),
        "git_log": _make_git_log(sandbox_root, posture_resolver),
        "git_diff": _make_git_diff(sandbox_root, posture_resolver),
        "git_push": _make_git_push(sandbox_root, posture_resolver),
    }
