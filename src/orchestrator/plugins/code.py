"""Posture-B subprocess plugin executor (ADR-031 D1/D2).

A plugin tool callable runs in a CHILD process (the _harness.py MCP stdio server);
the host NEVER imports plugin code.  The subprocess provides the isolation boundary:

  Posture B guarantees (ADR-031 D1):
  - No in-process import: plugin code never runs in the host address space.
  - Scoped env: child inherits only safe keys; orchestrator secrets never reach it
    (build_scoped_env, HR#10 / c2 env-leak lesson).
  - kill-no-orphan + watchdog: bounded SIGTERM→SIGKILL→watchdog-SIGKILL (ADR-028 D5
    liveness-bound restoration; ADR-031 D2 LAYER-1 kill).
  - Fail-closed: timeout → MCPTimeoutError → TOOL_FAILED; crash / isError →
    RuntimeError → MCPConnectionError → TOOL_FAILED.

load_plugin_code() now returns _PostureBFn closures that drop into the SAME
local_tools registry; _execute_local_call runs them UNCHANGED (empty-decision-diff).

The per-turn subprocess cap (MAX_POSTURE_B_CALLS_PER_TURN) is enforced by
executor.py, which identifies Posture-B fns via the _is_posture_b_subprocess
ClassVar marker (analogous to the MCP per-turn cap, ADR-028 D5).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, ClassVar

from mcp.client.stdio import StdioServerParameters
from mcp.types import TextContent

from mcp import ClientSession
from orchestrator.mcp._async_bridge import run_sync
from orchestrator.mcp.config import MCPServerConfig
from orchestrator.mcp.subprocess_trust import build_scoped_env, subprocess_mcp_stdio
from orchestrator.tools.executor import LocalToolFn, LocalToolOutput

# Absolute path to the harness script — launched once per call_tool.
_HARNESS_PATH: Path = Path(__file__).parent / "_harness.py"

# Bounded per-call timeout: matches MCPTimeouts.call_tool default (ADR-027 D1).
_CALL_TIMEOUT: float = 30.0


class PluginCodeLoadError(Exception):
    """Raised when a plugin's executable tool code cannot be loaded."""


class _PostureBFn:
    """Subprocess-launching Posture-B LocalToolFn (ADR-031 D1/D2).

    Each instance is created at load time (not at call time) and reused across calls.
    Per-call invocation spawns a fresh child subprocess (per-op connection pattern,
    same as stdio MCPTransport), communicates via the MCP stdio protocol, then tears
    down.  The child executes the plugin callable; the host never imports plugin code.

    The _is_posture_b_subprocess ClassVar marker lets executor.py identify this as
    a Posture-B subprocess fn for the per-turn cap (MAX_POSTURE_B_CALLS_PER_TURN).
    """

    _is_posture_b_subprocess: ClassVar[bool] = True

    def __init__(
        self,
        module_file: Path,
        callable_name: str,
        plugin_id: str,
        plugin_subprocess_env: dict[str, str],
    ) -> None:
        self._module_file = module_file
        self._callable_name = callable_name
        self._plugin_id = plugin_id
        self._plugin_subprocess_env = plugin_subprocess_env

    def __call__(self, tool_args: dict[str, Any]) -> LocalToolOutput:
        return run_sync(
            self._async_call(tool_args),
            timeout=_CALL_TIMEOUT,
            timeout_msg=(
                f"plugin {self._plugin_id!r}: call_tool timed out after {_CALL_TIMEOUT:.0f}s"
            ),
            error_msg_prefix=f"plugin {self._plugin_id!r}: call_tool failed",
        )

    async def _async_call(self, tool_args: dict[str, Any]) -> LocalToolOutput:
        harness_cfg = MCPServerConfig(
            transport="stdio",
            command=sys.executable,
            env=self._plugin_subprocess_env,
        )
        harness_params = StdioServerParameters(
            command=sys.executable,
            args=[str(_HARNESS_PATH), str(self._module_file), self._callable_name],
            env=build_scoped_env(harness_cfg),
        )
        async with (
            subprocess_mcp_stdio(harness_params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool("invoke", dict(tool_args))
            if result.isError:
                error_parts = [
                    c.text if isinstance(c, TextContent) else repr(c) for c in result.content
                ]
                raise RuntimeError(f"plugin callable raised: {'; '.join(error_parts)}")
            parts = [c.text if isinstance(c, TextContent) else repr(c) for c in result.content]
            return LocalToolOutput(content="\n".join(parts))


def load_plugin_code(
    plugin_dir: Path,
    plugin_id: str,
    tool_impls: dict[str, str],
    plugin_subprocess_env: dict[str, str] | None = None,
) -> dict[str, LocalToolFn]:
    """Create subprocess-launching Posture-B closures for each tool_impl (ADR-031 D1/D2).

    Each entry in tool_impls maps a tool name to "<module>:<callable>" where
    <module> is a .py file relative to plugin_dir (no extension).

    The parent never imports plugin code — each call spawns a fresh child that runs
    the plugin callable via the MCP stdio protocol (the harness).  Fail-closed on
    missing module file (raises PluginCodeLoadError → caller refuses plugin).
    """
    extra_env = plugin_subprocess_env or {}
    result: dict[str, LocalToolFn] = {}

    for tool_name, ref in tool_impls.items():
        module_name, callable_name = ref.split(":", 1)
        module_file = plugin_dir / f"{module_name}.py"

        if not module_file.exists():
            raise PluginCodeLoadError(
                f"plugin {plugin_id!r}: module file {module_file} does not exist"
            )

        result[tool_name] = _PostureBFn(
            module_file=module_file,
            callable_name=callable_name,
            plugin_id=plugin_id,
            plugin_subprocess_env=extra_env,
        )

    return result
