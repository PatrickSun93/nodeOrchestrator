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
identify fetched (Posture-B) tools for the per-turn cap (MAX_SUBPROCESS_CALLS_PER_TURN).
Operator-placed (Posture-A) tools lack the marker and are exempt from the cap.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from mcp.client.stdio import StdioServerParameters

from mcp import ClientSession
from orchestrator.mcp._async_bridge import run_sync
from orchestrator.mcp.config import MCPServerConfig
from orchestrator.mcp.subprocess_trust import build_scoped_env, subprocess_mcp_stdio
from orchestrator.plugins.provenance import PluginProvenance
from orchestrator.tools.executor import LocalToolFn, LocalToolOutput

if TYPE_CHECKING:
    from orchestrator.sandbox.posture import PostureResolver
    from orchestrator.sandbox.runtime import SandboxRuntime as _SandboxRuntime

# Absolute path to the harness script — launched once per call_tool (Posture B only).
_HARNESS_PATH: Path = Path(__file__).parent / "_harness.py"

# Bounded per-call timeout: matches MCPTimeouts.call_tool default (ADR-027 D1).
_CALL_TIMEOUT: float = 30.0


class PluginCodeLoadError(Exception):
    """Raised when a plugin's executable tool code cannot be loaded."""


class _PostureBFn:
    """Subprocess-launching Posture-B LocalToolFn (ADR-031 D1/D2; ADR-037 D2/D3 P4.3-7).

    Each instance is created at load time (not at call time) and reused across calls.
    Per-call invocation spawns a fresh child subprocess (per-op connection pattern,
    same as stdio MCPTransport), communicates via the MCP stdio protocol, then tears
    down.  The child executes the plugin callable; the host never imports plugin code.

    When posture_resolver is set and sandbox is available, the harness runs inside a
    container (FS/net/syscall isolated) via a sandboxed subprocess_mcp_stdio call.
    FAIL_CLOSED: raises LocalToolError(sandbox_unavailable:…) when unavailable + no opt-in.
    DEGRADED opt-in: falls through to app-level subprocess_mcp_stdio (warning logged).

    The _is_posture_b_subprocess ClassVar marker lets executor.py identify this as
    a subprocess-launching local tool for the per-turn cap (MAX_SUBPROCESS_CALLS_PER_TURN).
    Now marks both plugin Posture-B tools AND B3 subprocess tools (ADR-034 D5).
    """

    _is_posture_b_subprocess: ClassVar[bool] = True

    def __init__(
        self,
        module_file: Path,
        callable_name: str,
        plugin_id: str,
        plugin_subprocess_env: dict[str, str],
        posture_resolver: PostureResolver | None = None,
        sandbox_root: Path | None = None,
    ) -> None:
        self._module_file = module_file
        self._callable_name = callable_name
        self._plugin_id = plugin_id
        self._plugin_subprocess_env = plugin_subprocess_env
        self._posture_resolver = posture_resolver
        self._sandbox_root = sandbox_root

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
        from orchestrator.tools.local import LocalToolError

        harness_cfg = MCPServerConfig(
            transport="stdio",
            command=sys.executable,
            env=self._plugin_subprocess_env,
        )
        scoped = build_scoped_env(harness_cfg)

        # Sandbox routing (ADR-037 D2/D3; P4.3-7).
        if self._posture_resolver is not None:
            from orchestrator.sandbox.runtime import SandboxUnavailableError

            try:
                runtime = self._posture_resolver.assert_sandboxed_or_raise(
                    f"plugin:{self._plugin_id}"
                )
            except SandboxUnavailableError as exc:
                if self._posture_resolver.is_degraded_opted_in():
                    # DEGRADED: fall through to app-level subprocess_mcp_stdio.
                    pass
                else:
                    raise LocalToolError(
                        f"sandbox_unavailable: plugin:{self._plugin_id}: {exc}"
                    ) from exc
            else:
                # SANDBOXED: run harness inside a container.
                harness_params, cname = self._build_sandboxed_harness_params(runtime, scoped)
                return await self._run_mcp_session(
                    harness_params,
                    tool_args,
                    runtime=runtime,
                    container_name=cname,
                )

        harness_params = StdioServerParameters(
            command=sys.executable,
            args=[str(_HARNESS_PATH), str(self._module_file), self._callable_name],
            env=scoped,
        )
        return await self._run_mcp_session(harness_params, tool_args)

    def _build_sandboxed_harness_params(
        self,
        runtime: object,
        scoped: dict[str, str],
    ) -> tuple[StdioServerParameters, str]:
        """Build StdioServerParameters that launch the harness inside a container.

        Returns (params, container_name) so the caller can kill on teardown.
        Uses shared profile + deny-default egress (no egress needed for plugin execution).
        Adds -i for MCP-stdio handshake (stdin must be held open).
        """
        import uuid

        from orchestrator.sandbox.egress import build_deny_default_spec
        from orchestrator.sandbox.profile import SandboxProfile, build_container_args

        sandbox_root = self._sandbox_root or _HARNESS_PATH.parent
        image = getattr(getattr(self._posture_resolver, "_config", None), "image", "sandbox:latest")
        container_name = f"plugin-{self._plugin_id}-{str(uuid.uuid4())[:8]}"

        profile = SandboxProfile(
            sandbox_root=sandbox_root,
            image=image,
            container_name=container_name,
        )
        # Plugin spawn: deny-default network (no egress needed for plugin execution).
        build_deny_default_spec()  # validate path; args added separately
        container_args = build_container_args(
            profile,
            [sys.executable, str(_HARNESS_PATH), str(self._module_file), self._callable_name],
        )

        # Inject -i (MCP-stdio needs stdin held open) right after "run".
        # container_args = ["run", "--rm", ..., image, *argv]
        if container_args and container_args[0] == "run":
            container_args = ["run", "-i", *container_args[1:]]

        # Add --network none (deny-default) explicitly.
        img_idx = next((i for i, a in enumerate(container_args) if a == image), None)
        if img_idx is not None:
            container_args = [
                *container_args[:img_idx],
                "--network",
                "none",
                *container_args[img_idx:],
            ]

        cli: str = getattr(runtime, "cli", "docker")

        return StdioServerParameters(
            command=cli,
            args=container_args,
            env=scoped,
        ), container_name

    async def _run_mcp_session(
        self,
        params: StdioServerParameters,
        tool_args: dict[str, Any],
        *,
        runtime: _SandboxRuntime | None = None,
        container_name: str | None = None,
    ) -> LocalToolOutput:
        """Run the MCP session against the given subprocess parameters.

        When runtime + container_name are set (sandboxed path), guarantees
        runtime.kill(container_name) in a finally so a hung plugin container is reaped.
        """
        import contextlib

        from mcp.types import TextContent as _TextContent

        try:
            async with (
                subprocess_mcp_stdio(params) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool("invoke", dict(tool_args))
                if result.isError:
                    error_parts = [
                        c.text if isinstance(c, _TextContent) else repr(c) for c in result.content
                    ]
                    raise RuntimeError(f"plugin callable raised: {'; '.join(error_parts)}")
                parts = [c.text if isinstance(c, _TextContent) else repr(c) for c in result.content]
                return LocalToolOutput(content="\n".join(parts))
        finally:
            if runtime is not None and container_name is not None:
                with contextlib.suppress(Exception):
                    runtime.kill(container_name)


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
    *,
    posture_resolver: PostureResolver | None = None,
    sandbox_root: Path | None = None,
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
            posture_resolver=posture_resolver,
            sandbox_root=sandbox_root,
        )
    return result


def load_plugin_code(
    plugin_dir: Path,
    plugin_id: str,
    tool_impls: dict[str, str],
    plugin_subprocess_env: dict[str, str] | None = None,
    *,
    provenance: PluginProvenance = "operator_placed",
    posture_resolver: PostureResolver | None = None,
    sandbox_root: Path | None = None,
) -> dict[str, LocalToolFn]:
    """Load tool_impls per provenance: Posture A (in-process) for operator-placed,
    Posture B (subprocess) for fetched (ADR-029 D4 / ADR-031 D1/D2/D3).

    operator_placed → in-process importlib (Posture A, curation=trust, ADR-029 D4).
    fetched → subprocess-launching _PostureBFn (Posture B, ADR-031 D1/D2).

    Fail-closed: missing module file → PluginCodeLoadError → caller refuses the plugin.
    """
    if provenance == "fetched":
        return _load_posture_b_fns(
            plugin_dir,
            plugin_id,
            tool_impls,
            plugin_subprocess_env or {},
            posture_resolver=posture_resolver,
            sandbox_root=sandbox_root,
        )
    return _load_posture_a_fns(plugin_dir, plugin_id, tool_impls)
