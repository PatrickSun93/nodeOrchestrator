"""Posture-B subprocess plugin harness — runs as an MCP stdio server child (ADR-031 D1/D2).

Spawned per call_tool() invocation by plugins/code.py's _PostureBFn closures.
  argv[1]: absolute path to the plugin module (.py file)
  argv[2]: callable name within that module

The subprocess boundary provides isolation: plugin code imports here, inside the
child process, never in the host.  Import-time side effects and call-time crashes
are confined to this process; the host process is unaffected.

Never imported by the host orchestrator (the import boundary IS the isolation contract).
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool


def _load_fn(module_path: str, callable_name: str) -> Any:
    """Import module from absolute path, return named callable.

    Runs inside the subprocess — import-time side effects stay confined here.
    """
    spec = importlib.util.spec_from_file_location("_plugin_module", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot create module spec from {module_path!r}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn = getattr(module, callable_name, None)
    if fn is None:
        raise RuntimeError(f"no attribute {callable_name!r} in module")
    if not callable(fn):
        raise RuntimeError(f"{callable_name!r} is not callable")
    return fn


def _serve(module_path: str, callable_name: str) -> None:
    fn = _load_fn(module_path, callable_name)
    app = Server("plugin-harness")

    @app.list_tools()  # type: ignore[untyped-decorator, no-untyped-call]
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="invoke",
                description="invoke plugin tool",
                inputSchema={"type": "object", "additionalProperties": True},
            )
        ]

    @app.call_tool()  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        from orchestrator.tools.executor import LocalToolOutput

        result = fn(dict(arguments))
        if isinstance(result, LocalToolOutput):
            return [TextContent(type="text", text=result.content)]
        return [TextContent(type="text", text=str(result))]

    async def _main() -> None:
        async with stdio_server() as (r, w):
            await app.run(r, w, app.create_initialization_options())

    asyncio.run(_main())


def main() -> None:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <module_path> <callable_name>", file=sys.stderr)
        sys.exit(1)
    try:
        _serve(sys.argv[1], sys.argv[2])
    except Exception as exc:
        print(f"harness error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
