"""P3.7-remote-4: subprocess_trust.py unit tests (ADR-031 D2).

Covers:
  - scoped_env / build_scoped_env: env scoping (c2 lesson)
  - _kill_watchdog: kills alive process; no-ops on dead process (discriminating)
  - subprocess_mcp_stdio: SIGTERM-ignoring child still killed (no orphan);
    pure refactor: existing MCP transport tests remain green
  - run_scoped_command (B3-1): echo round-trip, non-zero exit, truncation,
    timeout → kill-no-orphan (B3-1 acceptance tests)
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import pytest

from orchestrator.mcp.config import MCPServerConfig, MCPTimeouts
from orchestrator.mcp.subprocess_trust import (
    _SAFE_ENV_KEYS,
    SubprocessTimeoutError,
    _kill_watchdog,
    build_scoped_env,
    run_scoped_command,
    scoped_env,
)
from orchestrator.mcp.transport import MCPTimeoutError, MCPTransport

# ---------------------------------------------------------------------------
# scoped_env (B3-1: factored core)
# ---------------------------------------------------------------------------


def test_scoped_env_excludes_secrets() -> None:
    """scoped_env() core excludes keys outside _SAFE_ENV_KEYS."""
    secret_key = "ORCH_SCOPED_ENV_SECRET_B3_1"
    os.environ[secret_key] = "should_not_appear"
    try:
        result = scoped_env()
        assert secret_key not in result
        for key in result:
            assert key in _SAFE_ENV_KEYS, f"Unexpected key {key!r} in scoped_env() result"
    finally:
        os.environ.pop(secret_key, None)


def test_scoped_env_overlay_and_api_key() -> None:
    """scoped_env() overlays extra_env and injects api_key_env."""
    secret_key = "SCOPED_ENV_API_B3_1"
    os.environ[secret_key] = "tok_xyz"
    try:
        result = scoped_env(extra_env={"EXTRA_KEY": "extra_val"}, api_key_env=secret_key)
        assert result["EXTRA_KEY"] == "extra_val"
        assert result[secret_key] == "tok_xyz"
    finally:
        os.environ.pop(secret_key, None)


def test_build_scoped_env_delegates_to_scoped_env() -> None:
    """build_scoped_env is a thin wrapper: same behaviour as scoped_env."""
    cfg = MCPServerConfig(command="echo", env={"MY_KEY": "my_val"}, tools={})
    via_build = build_scoped_env(cfg)
    via_core = scoped_env({"MY_KEY": "my_val"})
    assert via_build == via_core


# ---------------------------------------------------------------------------
# build_scoped_env
# ---------------------------------------------------------------------------


def test_build_scoped_env_excludes_orchestrator_secrets() -> None:
    """Subprocess env is minimal-scoped; orchestrator secrets are not passed (HR#10)."""
    secret_key = "ORCH_SECRET_TEST_KEY_P3_7_REMOTE_XYZ"
    secret_val = "should_not_appear"

    original = os.environ.get(secret_key)
    os.environ[secret_key] = secret_val
    try:
        cfg = MCPServerConfig(command="echo", env={}, tools={})
        scoped = build_scoped_env(cfg)
        assert secret_key not in scoped, (
            f"Secret {secret_key!r} leaked into scoped env (HR#10 violation)"
        )
        # Scoped env must be smaller than full environ
        assert len(scoped) < len(os.environ)
    finally:
        if original is None:
            os.environ.pop(secret_key, None)
        else:
            os.environ[secret_key] = original


def test_build_scoped_env_only_safe_keys() -> None:
    """Only _SAFE_ENV_KEYS (plus server.env) appear in the scoped env."""
    cfg = MCPServerConfig(command="echo", env={"MY_CUSTOM_KEY": "my_value"}, tools={})
    scoped = build_scoped_env(cfg)
    for key in scoped:
        assert key in _SAFE_ENV_KEYS or key == "MY_CUSTOM_KEY", (
            f"Unexpected key {key!r} in scoped env (should only be safe keys + server.env)"
        )
    assert scoped.get("MY_CUSTOM_KEY") == "my_value"


def test_build_scoped_env_api_key_env_injected() -> None:
    """api_key_env secret is injected under its var name (credential indirection, HR#5)."""
    secret_key = "MCP_TEST_API_KEY_P3_7_REMOTE"
    secret_val = "token_abc123"
    original = os.environ.get(secret_key)
    os.environ[secret_key] = secret_val
    try:
        cfg = MCPServerConfig(command="echo", api_key_env=secret_key, env={}, tools={})
        scoped = build_scoped_env(cfg)
        assert secret_key in scoped, "api_key_env not injected into scoped env"
        assert scoped[secret_key] == secret_val
    finally:
        if original is None:
            os.environ.pop(secret_key, None)
        else:
            os.environ[secret_key] = original


# ---------------------------------------------------------------------------
# _kill_watchdog (discriminating tests)
# ---------------------------------------------------------------------------


def test_kill_watchdog_kills_alive_process() -> None:
    """_kill_watchdog SIGKILLs an alive process (discriminating: proves kill path works)."""
    import subprocess as _sp

    proc = _sp.Popen([sys.executable, "-c", "import time; time.sleep(9999)"])
    pid = proc.pid
    try:
        # Verify the process IS alive before the watchdog
        os.kill(pid, 0)  # Raises ProcessLookupError if dead

        _kill_watchdog(pid)

        # After watchdog, process should be dead
        time.sleep(0.05)  # Brief settle
        try:
            os.kill(pid, 0)
            pytest.fail(f"Process {pid} still alive after _kill_watchdog (watchdog failed)")
        except ProcessLookupError:
            pass  # Expected: process is dead
    finally:
        with contextlib.suppress(Exception):
            proc.kill()
        proc.wait()


def test_kill_watchdog_noop_on_dead_process() -> None:
    """_kill_watchdog is a no-op when the process is already dead."""
    import subprocess as _sp

    proc = _sp.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
    proc.wait()  # Wait for it to die
    pid = proc.pid
    # Should not raise; just returns silently
    _kill_watchdog(pid)  # No exception expected


# ---------------------------------------------------------------------------
# subprocess_mcp_stdio via MCPTransport: SIGTERM-ignoring child killed (no orphan)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM signal semantics are Unix-only")
def test_sigterm_ignoring_child_killed_no_orphan() -> None:
    """SIGTERM-ignoring child subprocess is killed (no orphan) after timeout.

    Discriminating: the child explicitly ignores SIGTERM.  The combined
    SDK-equivalent teardown (SIGKILL escalation) + watchdog must ensure no orphan.
    """
    pid_file = tempfile.mktemp(suffix=".watchdog_pid")
    script = textwrap.dedent(
        f"""
        import signal, os, time, sys

        # Write our PID so the test can check it
        with open({pid_file!r}, "w") as f:
            f.write(str(os.getpid()))

        # Ignore SIGTERM — tests that the system escalates past SIGTERM
        signal.signal(signal.SIGTERM, signal.SIG_IGN)

        sys.stdout.flush()
        time.sleep(99999)
        """
    ).strip()

    server_cfg = MCPServerConfig(
        transport="stdio",
        command=sys.executable,
        args=["-c", script],
        env={},
        tools={},
    )
    timeouts = MCPTimeouts(connect=1.0, list_tools=1.0, call_tool=1.5)
    transport = MCPTransport("sigterm-test", server_cfg, timeouts)

    try:
        with pytest.raises(MCPTimeoutError):
            transport.call_tool("any_tool", {})

        # Allow teardown + watchdog to complete
        time.sleep(3.0)

        if os.path.exists(pid_file):
            with open(pid_file) as f:
                child_pid = int(f.read().strip())
            try:
                os.kill(child_pid, 0)
                pytest.fail(
                    f"SIGTERM-ignoring subprocess PID {child_pid} still alive "
                    f"after teardown — orphan leak detected"
                )
            except ProcessLookupError:
                pass  # Expected: process is dead (watchdog or SIGKILL escalation)
    finally:
        if os.path.exists(pid_file):
            os.unlink(pid_file)


# ---------------------------------------------------------------------------
# run_scoped_command (B3-1 acceptance tests)
# ---------------------------------------------------------------------------


def test_run_scoped_command_echo_round_trip(tmp_path: Path) -> None:
    """Echo round-trip: exit 0, output captured correctly."""
    env = scoped_env()
    result = run_scoped_command(
        [sys.executable, "-c", "import sys; print('hello B3-1'); sys.exit(0)"],
        cwd=tmp_path,
        env=env,
    )
    assert result.exit_code == 0
    assert "hello B3-1" in result.output
    assert not result.truncated


def test_run_scoped_command_nonzero_exit_no_raise(tmp_path: Path) -> None:
    """Non-zero exit code is captured; run_scoped_command does NOT raise."""
    env = scoped_env()
    result = run_scoped_command(
        [sys.executable, "-c", "import sys; sys.exit(42)"],
        cwd=tmp_path,
        env=env,
    )
    assert result.exit_code == 42
    assert not result.truncated


def test_run_scoped_command_truncation(tmp_path: Path) -> None:
    """Output > max_bytes → output is truncated, truncated flag set."""
    env = scoped_env()
    small_cap = 64
    # Write 200 bytes of output
    script = "print('x' * 200)"
    result = run_scoped_command(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        max_bytes=small_cap,
    )
    assert result.truncated
    assert len(result.output.encode("utf-8")) <= small_cap + 10  # allow decode rounding


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM signal semantics are Unix-only")
def test_run_scoped_command_timeout_kills_no_orphan(tmp_path: Path) -> None:
    """Timeout kills the child process; no orphan left behind.

    Tests the common case: grandchild in the same process group (pytest-worker /
    git-subcommand shape). Does NOT assert the adversarial setpgid(0,0) escape,
    which is the Accepted kill residual inscribed in ADR-034 D4 (retired by P4.3).
    """
    pid_file = tmp_path / "child.pid"
    script = textwrap.dedent(
        f"""
        import os, time
        with open({str(pid_file)!r}, "w") as f:
            f.write(str(os.getpid()))
        time.sleep(9999)
        """
    ).strip()
    env = scoped_env()

    with pytest.raises(SubprocessTimeoutError):
        run_scoped_command(
            [sys.executable, "-c", script],
            cwd=tmp_path,
            env=env,
            timeout_s=1.0,
        )

    # Allow teardown to complete
    time.sleep(1.5)

    if pid_file.exists():
        child_pid = int(pid_file.read_text().strip())
        try:
            os.kill(child_pid, 0)
            pytest.fail(f"Child PID {child_pid} still alive after timeout — orphan detected")
        except ProcessLookupError:
            pass  # Expected: killed by _terminate_subprocess + _kill_watchdog


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM signal semantics are Unix-only")
def test_run_scoped_command_timeout_watchdog_called(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_kill_watchdog is called on the timeout-cancel path (B2 fix: inside shielded scope).

    Verifies the fix: _kill_watchdog must execute even when asyncio.wait_for cancels the
    coroutine on timeout.  Prior to the fix it was placed after the CancelScope block and
    was skipped when cancellation was pending at scope exit.
    """
    import orchestrator.mcp.subprocess_trust as trust_mod

    watchdog_calls: list[int] = []
    original = trust_mod._kill_watchdog

    def _spy(pid: int) -> None:
        watchdog_calls.append(pid)
        original(pid)

    monkeypatch.setattr(trust_mod, "_kill_watchdog", _spy)
    env = scoped_env()

    with pytest.raises(SubprocessTimeoutError):
        run_scoped_command(
            [sys.executable, "-c", "import time; time.sleep(9999)"],
            cwd=tmp_path,
            env=env,
            timeout_s=1.0,
        )

    assert watchdog_calls, "_kill_watchdog was not called on the timeout-cancel path (B2 fix)"
