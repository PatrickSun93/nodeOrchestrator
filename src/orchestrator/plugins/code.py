"""Plugin code loader — Posture A (in-process, operator-placed) and
Posture B (subprocess, fetched) (ADR-029 D4 / ADR-031 D1/D2/D3).

Posture A (operator_placed, ADR-029 D4):
  Plugin code runs in the host process via importlib.  The operator curates
  the plugins_dir; curation IS the trust basis (ADR-029 D4).  Fast, stateful,
  no child-process overhead.

Posture B (fetched, ADR-031 D1/D2):
  Fetched plugin code runs in a CHILD process (_harness.py MCP stdio server);
  the host NEVER imports fetched plugin code (import boundary = isolation contract).
  - No in-process import: fetched plugin code never enters the host address space.
  - Scoped env: child inherits only safe keys; orchestrator secrets never reach it
    (build_scoped_env, HR#10 / c2 env-leak lesson).
  - kill-no-orphan + watchdog: bounded SIGTERM→SIGKILL→watchdog-SIGKILL (ADR-028 D5
    liveness-bound restoration; ADR-031 D2 LAYER-1 kill).
  - Fail-closed: timeout → MCPTimeoutError → TOOL_FAILED; crash / isError →
    RuntimeError → MCPConnectionError → TOOL_FAILED.

load_plugin_code() returns LocalToolFn closures for the SAME local_tools registry;
_execute_local_call runs them UNCHANGED (empty-decision-diff).

The _is_posture_b_subprocess ClassVar marker on _PostureBFn lets executor.py
identify fetched (Posture-B) tools for the per-turn cap (MAX_POSTURE_B_CALLS_PER_TURN).
Operator-placed (Posture-A) tools lack the marker and are exempt from the cap.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, ClassVar

from mcp.client.stdio import StdioServerParameters
from mcp.types import TextContent

from mcp import ClientSession
from orchestrator.mcp._async_bridge import run_sync
from orchestrator.mcp.config import MCPServerConfig
from orchestrator.mcp.subprocess_trust import build_scoped_env, subprocess_mcp_stdio
from orchestrator.plugins.provenance import PluginProvenance
from orchestrator.tools.executor import LocalToolFn, LocalToolOutput

# Absolute path to the harness script — launched once per call_tool (Posture B only).
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


def _load_posture_a_fns(
    plugin_dir: Path,
    plugin_id: str,
    tool_impls: dict[str, str],
) -> dict[str, LocalToolFn]:
    """Load tool_impls in-process via importlib (operator-placed Posture A, ADR-029 D4)."""
    result: dict[str, LocalToolFn] = {}
    for tool_name, ref in tool_impls.items():
        module_name, callable_name = ref.split(":", 1)
        module_file = plugin_dir / f"{module_name}.py"
        if not module_file.exists():
            raise PluginCodeLoadError(
                f"plugin {plugin_id!r}: module file {module_file} does not exist"
            )
        spec = importlib.util.spec_from_file_location(
            f"plugin_{plugin_id}_{module_name}", module_file
        )
        if spec is None or spec.loader is None:
            raise PluginCodeLoadError(
                f"plugin {plugin_id!r}: cannot create module spec for {module_file}"
            )
        try:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception as exc:
            raise PluginCodeLoadError(
                f"plugin {plugin_id!r}: failed to import module {module_file}: {exc}"
            ) from exc
        fn = getattr(module, callable_name, None)
        if fn is None:
            raise PluginCodeLoadError(
                f"plugin {plugin_id!r}: callable {callable_name!r} not found in {module_file}"
            )
        result[tool_name] = fn
    return result


def _load_posture_b_fns(
    plugin_dir: Path,
    plugin_id: str,
    tool_impls: dict[str, str],
    subprocess_env: dict[str, str],
) -> dict[str, LocalToolFn]:
    """Create subprocess-launching Posture-B closures (fetched plugins, ADR-031 D1/D2)."""
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
            plugin_subprocess_env=subprocess_env,
        )
    return result


def load_plugin_code(
    plugin_dir: Path,
    plugin_id: str,
    tool_impls: dict[str, str],
    plugin_subprocess_env: dict[str, str] | None = None,
    *,
    provenance: PluginProvenance = "operator_placed",
) -> dict[str, LocalToolFn]:
    """Load tool_impls per provenance: Posture A (in-process) for operator-placed,
    Posture B (subprocess) for fetched (ADR-029 D4 / ADR-031 D1/D2/D3).

    operator_placed → in-process importlib (Posture A, curation=trust, ADR-029 D4).
    fetched → subprocess-launching _PostureBFn (Posture B, ADR-031 D1/D2).

    Fail-closed: missing module file → PluginCodeLoadError → caller refuses the plugin.
    """
    if provenance == "fetched":
        return _load_posture_b_fns(plugin_dir, plugin_id, tool_impls, plugin_subprocess_env or {})
    return _load_posture_a_fns(plugin_dir, plugin_id, tool_impls)
