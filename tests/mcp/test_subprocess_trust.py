"""P3.7-remote-4: subprocess_trust.py unit tests (ADR-031 D2).

Covers:
  - build_scoped_env: env scoping (c2 lesson)
  - _kill_watchdog: kills alive process; no-ops on dead process (discriminating)
  - subprocess_mcp_stdio: SIGTERM-ignoring child still killed (no orphan);
    pure refactor: existing MCP transport tests remain green
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
import textwrap
import time

import pytest

from orchestrator.mcp.config import MCPServerConfig, MCPTimeouts
from orchestrator.mcp.subprocess_trust import (
    _SAFE_ENV_KEYS,
    _kill_watchdog,
    build_scoped_env,
)
from orchestrator.mcp.transport import MCPTimeoutError, MCPTransport

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
