"""§3 failure modes + §2 concurrency (transport-level) tests.

§3 failure modes:
  - Hanging mock server → asyncio.wait_for fires → MCPTimeoutError (fail-closed)
    AND subprocess killed (no orphan; R0-B Y1 MUST-FIX)
  - Server crash (immediate exit) → MCPConnectionError (fail-closed)
  - call_tool with no TOOL_CALL gate event → execution.py never called
    (structural: execution only wired downstream of TOOL_CALL events)
§2 concurrency:
  - Concurrent calls to independent transports → sync-bridge loop isolation
  - Each call_tool spawns its own event loop (no loop sharing between threads)
§4 boundary (transport):
  - Scoped subprocess env: subprocess does NOT receive orchestrator secrets
  - Credential indirection via api_key_env
"""

from __future__ import annotations

import os
import sys
import tempfile
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from orchestrator.mcp.config import MCPServerConfig, MCPTimeouts
from orchestrator.mcp.transport import (
    MCPConnectionError,
    MCPTimeoutError,
    MCPTransport,
    _build_scoped_env,
)

# ---------------------------------------------------------------------------
# §3 failure: hanging server → timeout → fail-closed + subprocess killed
# ---------------------------------------------------------------------------


def _hanging_server_cfg(
    call_timeout: float = 2.0,
    pid_file: str | None = None,
) -> tuple[MCPServerConfig, MCPTimeouts]:
    """Server script that hangs forever (never speaks MCP protocol)."""
    pid_write = f"open({pid_file!r}, 'w').write(str(os.getpid()))\n" if pid_file else ""
    script = textwrap.dedent(
        f"""
        import os, time, sys
        {pid_write}
        sys.stdout.flush()
        time.sleep(99999)
        """
    ).strip()

    server_cfg = MCPServerConfig(
        transport="stdio",
        command=sys.executable,
        args=["-c", script],
        api_key_env=None,
        env={},
        tools={},
    )
    timeouts = MCPTimeouts(connect=10.0, list_tools=10.0, call_tool=call_timeout)
    return server_cfg, timeouts


def test_transport_hanging_server_timeout_fail_closed() -> None:
    """R0-B Y1 MUST-FIX: hanging server → MCPTimeoutError (fail-closed, not blocked)."""
    server_cfg, timeouts = _hanging_server_cfg(call_timeout=1.5)
    transport = MCPTransport("hang-test", server_cfg, timeouts)

    t0 = time.monotonic()
    with pytest.raises(MCPTimeoutError):
        transport.call_tool("any_tool", {})
    elapsed = time.monotonic() - t0

    # Must complete within a generous bound (timeout + SDK cleanup overhead)
    assert elapsed < 15.0, f"call_tool blocked for {elapsed:.1f}s — timeout mechanism may be broken"


def test_transport_hanging_server_subprocess_killed_no_orphan() -> None:
    """R0-B Y1 MUST-FIX: hanging server subprocess is killed (no orphan) after timeout."""
    pid_file = tempfile.mktemp(suffix=".hang_pid")
    server_cfg, timeouts = _hanging_server_cfg(call_timeout=2.0, pid_file=pid_file)
    transport = MCPTransport("hang-orphan-test", server_cfg, timeouts)

    try:
        with pytest.raises(MCPTimeoutError):
            transport.call_tool("any_tool", {})

        # Allow stdio_client cleanup to complete
        time.sleep(2.0)

        # Verify subprocess is dead (no orphan)
        if os.path.exists(pid_file):
            with open(pid_file) as _f:
                pid = int(_f.read().strip())
            try:
                os.kill(pid, 0)  # Signal 0 = check existence
                pytest.fail(f"Subprocess PID {pid} still alive after timeout (orphan leak)")
            except ProcessLookupError:
                pass  # Expected: process is dead
    finally:
        if os.path.exists(pid_file):
            os.unlink(pid_file)


def test_transport_list_tools_timeout_fail_closed() -> None:
    """Hanging server on list_tools → MCPTimeoutError."""
    server_cfg, _timeouts = _hanging_server_cfg(call_timeout=1.0)
    # Use short list_tools timeout
    short_timeouts = MCPTimeouts(connect=1.0, list_tools=1.0, call_tool=1.0)
    transport = MCPTransport("hang-lt-test", server_cfg, short_timeouts)

    t0 = time.monotonic()
    with pytest.raises(MCPTimeoutError):
        transport.list_tools()
    elapsed = time.monotonic() - t0
    assert elapsed < 15.0


# ---------------------------------------------------------------------------
# §3 failure: server crash → MCPConnectionError (fail-closed)
# ---------------------------------------------------------------------------


def _crash_server_cfg() -> MCPServerConfig:
    """Server that immediately exits (crash on startup)."""
    script = "import sys; sys.exit(1)"
    return MCPServerConfig(
        transport="stdio",
        command=sys.executable,
        args=["-c", script],
        env={},
        tools={},
    )


def test_transport_crash_server_fail_closed() -> None:
    """Server crash → MCPConnectionError (orchestrator does not crash)."""
    server_cfg = _crash_server_cfg()
    transport = MCPTransport("crash-test", server_cfg)

    with pytest.raises((MCPConnectionError, MCPTimeoutError)):
        transport.list_tools()


def test_transport_crash_mid_call_fail_closed() -> None:
    """Server that crashes after writing nothing → fail-closed."""
    # Script exits immediately without any output
    script = textwrap.dedent("""
        import sys, time
        time.sleep(0.1)
        sys.exit(0)
    """).strip()
    server_cfg = MCPServerConfig(
        transport="stdio",
        command=sys.executable,
        args=["-c", script],
        env={},
        tools={},
    )
    transport = MCPTransport("crash-mid-test", server_cfg)
    with pytest.raises((MCPConnectionError, MCPTimeoutError)):
        transport.call_tool("any_tool", {})


# ---------------------------------------------------------------------------
# §2 concurrency: independent transport event loops
# ---------------------------------------------------------------------------


def test_transport_concurrent_independent_loops() -> None:
    """Concurrent calls to independent transports use isolated event loops."""
    # Each transport uses its own asyncio.new_event_loop() → no sharing.
    # We verify by calling two hanging transports concurrently and checking
    # that both fail independently (no interference).
    server_cfg, timeouts = _hanging_server_cfg(call_timeout=1.0)

    t1 = MCPTransport("loop-test-1", server_cfg, timeouts)
    t2 = MCPTransport("loop-test-2", server_cfg, timeouts)

    errors: list[Exception] = []

    def run_call(transport: MCPTransport) -> None:
        try:
            transport.call_tool("any_tool", {})
        except (MCPTimeoutError, MCPConnectionError) as exc:
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(run_call, t1)
        f2 = pool.submit(run_call, t2)
        f1.result(timeout=20)
        f2.result(timeout=20)

    # Both should fail independently (not one blocking the other)
    assert len(errors) == 2
    assert all(isinstance(e, (MCPTimeoutError, MCPConnectionError)) for e in errors)


# ---------------------------------------------------------------------------
# §4 boundary: scoped env — subprocess does NOT receive orchestrator secrets
# ---------------------------------------------------------------------------


def test_transport_scoped_env_excludes_orchestrator_secrets() -> None:
    """Subprocess env is minimal-scoped; orchestrator secrets are not leaked (HR#10)."""
    secret_key = "ORCHESTRATOR_SUPER_SECRET_TEST_KEY_XYZ"
    secret_val = "secret_value_that_must_not_leak"

    # Inject a fake secret into the orchestrator's env
    original = os.environ.get(secret_key)
    os.environ[secret_key] = secret_val

    try:
        server_cfg = MCPServerConfig(
            command="npx",
            env={},
            tools={},
        )
        scoped = _build_scoped_env(server_cfg)
        assert secret_key not in scoped, (
            f"Secret {secret_key!r} leaked into subprocess env (HR#10 violation)"
        )
    finally:
        if original is None:
            del os.environ[secret_key]
        else:
            os.environ[secret_key] = original


def test_transport_api_key_env_credential_indirection() -> None:
    """api_key_env secret is injected into scoped env under its var name (HR#8)."""
    secret_key = "MY_MCP_API_KEY_TEST_456"
    secret_val = "my_secret_token"

    original = os.environ.get(secret_key)
    os.environ[secret_key] = secret_val

    try:
        server_cfg = MCPServerConfig(
            command="npx",
            api_key_env=secret_key,
            env={},
            tools={},
        )
        scoped = _build_scoped_env(server_cfg)
        # The api_key_env var must be present in the scoped env (credential indirection)
        assert secret_key in scoped
        assert scoped[secret_key] == secret_val
        # But other orchestrator-only keys should still be absent
        other_secret = "OTHER_ORCHESTRATOR_SECRET_TEST"
        assert other_secret not in scoped
    finally:
        if original is None:
            if secret_key in os.environ:
                del os.environ[secret_key]
        else:
            os.environ[secret_key] = original


def test_transport_scoped_env_no_full_os_environ() -> None:
    """Subprocess env has fewer keys than os.environ (not full env inheritance)."""
    server_cfg = MCPServerConfig(
        command="npx",
        env={},
        tools={},
    )
    scoped = _build_scoped_env(server_cfg)
    # Scoped env should be much smaller than the full orchestrator env
    assert len(scoped) < len(os.environ), (
        "Scoped env has as many keys as os.environ — likely inheriting full env (HR#10)"
    )


# ---------------------------------------------------------------------------
# §3: call_tool without TOOL_CALL event → execution.py not called (structural)
# ---------------------------------------------------------------------------


def test_execution_never_contacts_server_without_tool_call_event() -> None:
    """execute_mcp_tool_call requires a TOOL_CALL event (structural HR#4 guard)."""
    import sqlite3

    from orchestrator.core.event import (
        Event,
        EventType,
        generate_event_id,
        generate_room_id,
        now_ms,
    )
    from orchestrator.core.event_store import EventStore
    from orchestrator.core.room import Room, RoomType
    from orchestrator.mcp.client import MCPSession
    from orchestrator.mcp.config import MCPServerConfig, MCPTimeouts
    from orchestrator.mcp.execution import execute_mcp_tool_call
    from orchestrator.mcp.transport import MCPTransport

    conn = sqlite3.connect(":memory:")
    store = EventStore(conn)
    store.init_schema()
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)

    # Pass a NON TOOL_CALL event — should raise ValueError (structural guard)
    wrong_event = Event(
        id=generate_event_id(),
        room_id=room.id,
        type=EventType.USER_INPUT,
        author="user",
        timestamp=now_ms(),
        content="hello",
    )

    transport = MCPTransport(
        "test-server",
        MCPServerConfig(command="echo", tools={}),
        MCPTimeouts(connect=1, list_tools=1, call_tool=1),
    )
    session = MCPSession(
        server_name="test-server",
        tools=[],
        transport=transport,
    )

    with pytest.raises(ValueError, match="TOOL_CALL"):
        execute_mcp_tool_call(
            tool_call_event=wrong_event,
            session=session,
            event_store=store,
            room_id=room.id,
            agent_id="test",
        )
