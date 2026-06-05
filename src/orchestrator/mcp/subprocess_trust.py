"""Subprocess-only trust machinery (ADR-031 D2-b).

Provides:
  (a) scoped_env / build_scoped_env — minimal-scoped subprocess env (c2 env-leak lesson).
  (b) subprocess_mcp_stdio — own the subprocess, expose MCP-compatible streams,
      add the orchestrator-level LAYER-1 kill watchdog (ADR-031 D2).
  (c) run_scoped_command — run a plain argv command, bounded capture of stdout+stderr,
      reuses kill-no-orphan + scoped-env (ADR-034 D4). Non-MCP plain-exec entrypoint
      on the one subprocess protocol. [Extended P4.2-B3 → ADR-034]

Reused by:
  mcp/transport.py  — stdio path
  plugins/          — Posture-B executor (P3.7-remote-5)
  tools/subprocess_tools.py — B3 subprocess local tools (P4.2-B3)

The watchdog: after SDK-equivalent teardown completes, check if the child PID is
still alive; if so, force SIGKILL + reap.  This is LAYER-1 (orchestrator) vs
the LAYER-2 SDK teardown (SIGTERM → PROCESS_TERMINATION_TIMEOUT → SIGKILL), so
a future SDK bug or SIGKILL-surviving zombie is caught before it orphans.
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import os
import signal
import subprocess as _subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
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

# Default output cap for run_scoped_command (64 KiB, reused from mcp/execution.py).
# Bounded read: stops accumulating at this limit as it reads.
MAX_RESULT_BYTES: int = 64 * 1024


# ---------------------------------------------------------------------------
# (a) Scoped env builder
# ---------------------------------------------------------------------------


def scoped_env(
    extra_env: dict[str, str] | None = None,
    api_key_env: str | None = None,
) -> dict[str, str]:
    """Core minimal-scoped env builder (HR#10 / c2 env-leak lesson).

    Three-step behaviour:
      1. Inherit only _SAFE_ENV_KEYS from os.environ.
      2. Overlay extra_env (if provided).
      3. Conditionally inject api_key_env secret (if provided and present in os.environ).
    """
    env: dict[str, str] = {}
    for key in _SAFE_ENV_KEYS:
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    if extra_env:
        env.update(extra_env)
    if api_key_env:
        secret = os.environ.get(api_key_env)
        if secret is not None:
            env[api_key_env] = secret
    return env


def build_scoped_env(server_cfg: MCPServerConfig) -> dict[str, str]:
    """Construct minimal scoped subprocess env (HR#10 / c2 env-leak lesson).

    Thin wrapper around scoped_env() for the MCP server config case.
    Never passes the orchestrator's full os.environ. Inherits only _SAFE_ENV_KEYS,
    then overlays server_cfg.env, then the api_key_env secret (if configured).
    """
    return scoped_env(server_cfg.env, server_cfg.api_key_env)


# ---------------------------------------------------------------------------
# (c) Plain-command runner — SubprocessResult + SubprocessTimeout + run_scoped_command
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class SubprocessResult:
    """Result from run_scoped_command."""

    exit_code: int
    output: str
    truncated: bool


class SubprocessTimeoutError(Exception):
    """Raised by run_scoped_command when the child exceeds its timeout."""


async def _run_scoped_command_async(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    max_bytes: int,
) -> SubprocessResult:
    """Async inner coroutine for run_scoped_command.

    The outer run_sync() supplies the timeout via asyncio.wait_for, which cancels
    this coro on expiry. The shielded finally ensures the child is killed even
    after cancellation (N3 / _terminate_subprocess wraps CancelScope(shield=True)).

    Combines stdout+stderr into one stream via subprocess.STDOUT so the bounded
    read captures all output.

    Same-pass coupling (B3-5 watch-point): both stdout pipe and process.wait() are
    issued in the same coroutine pass — the TOOL_CALL and its TOOL_RESULT are
    produced together (excerpt-exclusion keyed on TOOL_CALL call_ids is safe).
    """
    pid: int = -1
    process: anyio.abc.Process | None = None
    output_bytes = bytearray()
    truncated = False

    try:
        try:
            process = await anyio.open_process(
                argv,
                cwd=cwd,
                env=env,
                stderr=_subprocess.STDOUT,  # combine stderr into stdout stream
                start_new_session=True,
            )
        except OSError as exc:
            raise OSError(f"spawn failed: {exc}") from exc

        pid = process.pid

        # Bounded read: stop accumulating at max_bytes; don't buffer an unbounded log.
        if process.stdout is not None:
            while True:
                room = max_bytes - len(output_bytes)
                if room <= 0:
                    truncated = True
                    break
                try:
                    chunk = await process.stdout.receive(min(4096, room))
                except anyio.EndOfStream:
                    break
                output_bytes.extend(chunk)

        # Wait for natural exit; if truncated, finally kills the process (pipe may be full).
        if not truncated:
            await process.wait()

    finally:
        # Shielded kill (N3): _terminate_subprocess has its own CancelScope(shield=True),
        # so the kill completes even when asyncio.wait_for has cancelled this coroutine.
        if process is not None and pid > 0:
            with anyio.CancelScope(shield=True):
                await _terminate_subprocess(process, pid)
            _kill_watchdog(pid)

    rc = process.returncode if process is not None else None
    exit_code = rc if rc is not None else -1
    return SubprocessResult(
        exit_code=exit_code,
        output=output_bytes.decode("utf-8", errors="replace"),
        truncated=truncated,
    )


def run_scoped_command(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_s: float = 30.0,
    max_bytes: int = MAX_RESULT_BYTES,
) -> SubprocessResult:
    """Run an argv list, return bounded combined stdout+stderr + exit code.

    argv must be a list — never shell=True, never a shell string (ADR-034 D3-i / carry-forward #6).
    env is the caller's responsibility (use scoped_env() — never raw os.environ).
    On timeout: child is killed, SubprocessTimeout raised.
    On spawn failure: OSError propagated (caller maps to subprocess_spawn_failed).

    Reuses _terminate_subprocess + _kill_watchdog (ADR-031 D2 one-subprocess-protocol).
    Non-MCP plain-exec entrypoint on the one subprocess protocol. [Extended P4.2-B3 → ADR-034]
    """
    from orchestrator.mcp._async_bridge import MCPTimeoutError, run_sync

    try:
        return run_sync(
            _run_scoped_command_async(argv, cwd=cwd, env=env, max_bytes=max_bytes),
            timeout=timeout_s,
            timeout_msg=f"run_scoped_command: timed out after {timeout_s}s (argv={argv!r})",
            error_msg_prefix="run_scoped_command failed",
        )
    except MCPTimeoutError as exc:
        raise SubprocessTimeoutError(str(exc)) from exc


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
