"""Subprocess-only trust machinery (ADR-031 D2-b).

Provides:
  (a) build_scoped_env    — minimal-scoped subprocess env (c2 env-leak lesson).
  (b) subprocess_mcp_stdio — own the subprocess, expose MCP-compatible streams,
      add the orchestrator-level LAYER-1 kill watchdog (ADR-031 D2).

Reused by:
  mcp/transport.py  — stdio path
  plugins/          — Posture-B executor (P3.7-remote-5)

The watchdog: after SDK-equivalent teardown completes, check if the child PID is
still alive; if so, force SIGKILL + reap.  This is LAYER-1 (orchestrator) vs
the LAYER-2 SDK teardown (SIGTERM → PROCESS_TERMINATION_TIMEOUT → SIGKILL), so
a future SDK bug or SIGKILL-surviving zombie is caught before it orphans.
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import anyio
import anyio.lowlevel
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from anyio.streams.text import TextReceiveStream
from mcp.client.stdio import StdioServerParameters
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage

from orchestrator.mcp.config import MCPServerConfig

_log = logging.getLogger("orchestrator.mcp.subprocess_trust")

# Safe env keys to inherit in the subprocess (HR#10 minimal-scoped env).
_SAFE_ENV_KEYS: tuple[str, ...] = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "TERM",
    "TMPDIR",
    "TEMP",
    "TMP",
)

# Match SDK's PROCESS_TERMINATION_TIMEOUT (seconds before escalating kill).
_TERMINATION_TIMEOUT: float = 2.0


# ---------------------------------------------------------------------------
# (a) Scoped env builder
# ---------------------------------------------------------------------------


def build_scoped_env(server_cfg: MCPServerConfig) -> dict[str, str]:
    """Construct minimal scoped subprocess env (HR#10 / c2 env-leak lesson).

    Never passes the orchestrator's full os.environ. Inherits only _SAFE_ENV_KEYS,
    then overlays server_cfg.env, then the api_key_env secret (if configured).
    """
    env: dict[str, str] = {}
    for key in _SAFE_ENV_KEYS:
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    env.update(server_cfg.env)
    if server_cfg.api_key_env:
        secret = os.environ.get(server_cfg.api_key_env)
        if secret is not None:
            env[server_cfg.api_key_env] = secret
    return env


# ---------------------------------------------------------------------------
# (b) Orchestrator-level kill watchdog
# ---------------------------------------------------------------------------


def _kill_watchdog(pid: int) -> None:
    """LAYER-1 kill watchdog: check PID; if alive, force SIGKILL + reap.

    Runs AFTER SDK-equivalent teardown (SIGTERM/SIGKILL escalation).  Catches:
    - SDK bugs where the process was not killed despite SIGKILL escalation.
    - SIGKILL-surviving zombie / reap races.
    Silently no-ops if the process is already dead (the expected common case).
    """
    try:
        os.kill(pid, 0)  # Signal 0: check existence only, no-op
    except ProcessLookupError:
        return  # Already dead — expected normal case
    except PermissionError:
        return  # Not our child; ignore

    _log.warning("subprocess watchdog: PID %d alive after teardown — forcing SIGKILL", pid)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return  # Died between check and kill

    # Reap the zombie so it does not linger in the process table.
    with contextlib.suppress(ChildProcessError):
        os.waitpid(pid, 0)


# ---------------------------------------------------------------------------
# Subprocess termination helpers
# ---------------------------------------------------------------------------


def _pgid_kill(pid: int, sig: int) -> None:
    """Send sig to the process group of pid (Unix only; start_new_session=True → pgid==pid)."""
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        pass


async def _terminate_subprocess(process: anyio.abc.Process, pid: int) -> None:
    """Platform-compatible subprocess termination with SIGTERM → SIGKILL escalation.

    Mirrors SDK's PROCESS_TERMINATION_TIMEOUT + _terminate_process_tree logic.
    Uses anyio.CancelScope(shield=True) to survive outer cancellation (asyncio.wait_for).
    """
    with anyio.CancelScope(shield=True):
        # Wait for graceful exit after stdin close
        try:
            with anyio.fail_after(_TERMINATION_TIMEOUT):
                await process.wait()
            return  # Exited gracefully
        except TimeoutError:
            pass
        except ProcessLookupError:
            return  # Already dead

        # SIGTERM via process group (start_new_session → pgid == pid on Unix)
        if sys.platform != "win32":
            _pgid_kill(pid, signal.SIGTERM)
        else:
            try:
                process.terminate()  # type: ignore[attr-defined]
            except ProcessLookupError:
                return

        try:
            with anyio.fail_after(_TERMINATION_TIMEOUT):
                await process.wait()
            return
        except TimeoutError:
            pass
        except ProcessLookupError:
            return

        # SIGKILL escalation
        if sys.platform != "win32":
            _pgid_kill(pid, signal.SIGKILL)
        else:
            try:
                process.kill()  # type: ignore[attr-defined]
            except ProcessLookupError:
                return

        try:
            with anyio.fail_after(_TERMINATION_TIMEOUT):
                await process.wait()
        except (TimeoutError, ProcessLookupError):
            pass


# ---------------------------------------------------------------------------
# (b) subprocess_mcp_stdio context manager
# ---------------------------------------------------------------------------


@asynccontextmanager
async def subprocess_mcp_stdio(
    params: StdioServerParameters,
) -> AsyncIterator[
    tuple[
        MemoryObjectReceiveStream[SessionMessage | Exception],
        MemoryObjectSendStream[SessionMessage],
    ]
]:
    """Spawn subprocess, expose MCP-compatible streams, add orchestrator kill watchdog.

    Replicates mcp.client.stdio.stdio_client behaviour with two additions:
      1. Explicit PID tracking (via anyio.open_process instead of stdio_client).
      2. LAYER-1 watchdog: _kill_watchdog(pid) after all SDK-equivalent teardown.

    Yields (read_stream, write_stream) compatible with mcp.ClientSession.
    """
    read_stream_writer, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](
        0
    )
    write_stream, write_stream_reader = anyio.create_memory_object_stream[SessionMessage](0)

    pid: int = -1

    try:
        process = await anyio.open_process(
            [params.command, *params.args],
            env=params.env,
            stderr=None,  # Inherit parent stderr for MCP server debug output
            start_new_session=True,
        )
        pid = process.pid
    except OSError as exc:
        for s in (read_stream, write_stream, read_stream_writer, write_stream_reader):
            await s.aclose()
        from orchestrator.mcp._async_bridge import MCPConnectionError

        raise MCPConnectionError(f"subprocess spawn failed: {exc}") from exc

    async def _stdout_reader() -> None:
        assert process.stdout is not None, "anyio.open_process: stdout is None"
        try:
            async with read_stream_writer:
                buf = ""
                async for chunk in TextReceiveStream(
                    process.stdout, encoding="utf-8", errors="replace"
                ):
                    lines = (buf + chunk).split("\n")
                    buf = lines.pop()
                    for line in lines:
                        try:
                            msg: Any = JSONRPCMessage.model_validate_json(line)
                        except Exception as exc_parse:
                            await read_stream_writer.send(exc_parse)
                            continue
                        await read_stream_writer.send(SessionMessage(msg))
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()

    async def _stdin_writer() -> None:
        assert process.stdin is not None, "anyio.open_process: stdin is None"
        try:
            async with write_stream_reader:
                async for sm in write_stream_reader:
                    data = sm.message.model_dump_json(by_alias=True, exclude_none=True)
                    await process.stdin.send((data + "\n").encode("utf-8"))
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(_stdout_reader)
            tg.start_soon(_stdin_writer)
            try:
                yield read_stream, write_stream
            finally:
                # Close stdin → signal EOF / graceful shutdown to child
                if process.stdin is not None:
                    with contextlib.suppress(Exception):
                        await process.stdin.aclose()
                # Terminate (shielded — survives asyncio.wait_for cancellation)
                await _terminate_subprocess(process, pid)
                # Close streams → reader/writer tasks exit naturally
                for s in (
                    read_stream,
                    write_stream,
                    read_stream_writer,
                    write_stream_reader,
                ):
                    with contextlib.suppress(Exception):
                        await s.aclose()
    finally:
        # LAYER-1 orchestrator watchdog: runs after task group + all SDK teardown
        if pid > 0:
            _kill_watchdog(pid)
