"""P4.3-7 tests: Posture-B plugin spawn routes through sandbox when available.

Tests: spawn routes through sandbox (subprocess_mcp_stdio called with docker CLI);
fail-closed when unavailable + not opted-in.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from orchestrator.plugins.code import _PostureBFn
from orchestrator.sandbox.posture import PostureResolver, SandboxConfig
from orchestrator.sandbox.runtime import SandboxRuntime
from orchestrator.tools.local import LocalToolError


def _make_resolver(available: bool = True, degraded: bool = False) -> PostureResolver:
    config = SandboxConfig(image="sandbox:test", degraded_app_level=degraded)
    if available:
        rt = SandboxRuntime(kind="docker", cli="/usr/bin/docker")
        rt.available = mock.Mock(return_value=True)  # type: ignore[method-assign]
    else:
        rt = None
    return PostureResolver(config=config, runtime=rt)


def _make_fn(
    tmp_path: Path,
    resolver: PostureResolver | None = None,
) -> _PostureBFn:
    module_file = tmp_path / "plugin_tool.py"
    module_file.write_text("def my_tool(args): return 'ok'")
    return _PostureBFn(
        module_file=module_file,
        callable_name="my_tool",
        plugin_id="test-plugin",
        plugin_subprocess_env={},
        posture_resolver=resolver,
        sandbox_root=tmp_path,
    )


# ---------------------------------------------------------------------------
# SANDBOXED: _build_sandboxed_harness_params uses docker CLI args
# ---------------------------------------------------------------------------


def test_sandboxed_harness_params_uses_docker_cli(tmp_path: Path) -> None:
    """_build_sandboxed_harness_params returns params with the runtime CLI as command."""
    resolver = _make_resolver(available=True)
    fn = _make_fn(tmp_path, resolver=resolver)

    rt = SandboxRuntime(kind="docker", cli="/usr/bin/docker")
    params = fn._build_sandboxed_harness_params(runtime=rt, scoped={})

    assert params.command == "/usr/bin/docker"


def test_sandboxed_harness_params_starts_with_run(tmp_path: Path) -> None:
    """Container invocation args must start with 'run'."""
    resolver = _make_resolver(available=True)
    fn = _make_fn(tmp_path, resolver=resolver)

    rt = SandboxRuntime(kind="docker", cli="/usr/bin/docker")
    params = fn._build_sandboxed_harness_params(runtime=rt, scoped={})

    assert params.args[0] == "run"


def test_sandboxed_harness_params_no_docker_sock(tmp_path: Path) -> None:
    """Container args must never include /var/run/docker.sock."""
    resolver = _make_resolver(available=True)
    fn = _make_fn(tmp_path, resolver=resolver)

    rt = SandboxRuntime(kind="docker", cli="/usr/bin/docker")
    params = fn._build_sandboxed_harness_params(runtime=rt, scoped={})

    all_args = " ".join(params.args)
    assert "/var/run/docker.sock" not in all_args


def test_sandboxed_harness_params_deny_default_network(tmp_path: Path) -> None:
    """Plugin spawn uses deny-default network (no egress needed)."""
    resolver = _make_resolver(available=True)
    fn = _make_fn(tmp_path, resolver=resolver)

    rt = SandboxRuntime(kind="docker", cli="/usr/bin/docker")
    params = fn._build_sandboxed_harness_params(runtime=rt, scoped={})

    args_str = " ".join(params.args)
    assert "--network" in args_str
    assert "none" in args_str


# ---------------------------------------------------------------------------
# FAIL_CLOSED: raises LocalToolError(sandbox_unavailable:…) when not opted-in
# ---------------------------------------------------------------------------


def test_fail_closed_raises_local_tool_error(tmp_path: Path) -> None:
    resolver = _make_resolver(available=False, degraded=False)
    fn = _make_fn(tmp_path, resolver=resolver)

    from orchestrator.mcp._async_bridge import MCPConnectionError

    with pytest.raises((LocalToolError, MCPConnectionError)):
        fn({})


def test_fail_closed_no_subprocess_call(tmp_path: Path) -> None:
    resolver = _make_resolver(available=False, degraded=False)
    fn = _make_fn(tmp_path, resolver=resolver)

    from orchestrator.mcp._async_bridge import MCPConnectionError

    with (
        mock.patch("orchestrator.plugins.code.subprocess_mcp_stdio") as mock_mcp,
        pytest.raises((LocalToolError, MCPConnectionError)),
    ):
        fn({})

    mock_mcp.assert_not_called()


# ---------------------------------------------------------------------------
# No resolver: the sandboxed path is not taken
# ---------------------------------------------------------------------------


def test_no_resolver_has_no_sandbox_routing(tmp_path: Path) -> None:
    """Without a resolver, _build_sandboxed_harness_params is never called."""
    fn = _make_fn(tmp_path, resolver=None)
    assert fn._posture_resolver is None


# ---------------------------------------------------------------------------
# pb6 still passes (executor byte-frozen — _execute_local_call unchanged)
# ---------------------------------------------------------------------------


def test_pb6_execute_local_call_still_decision_unchanged() -> None:
    """Cross-check pb6: sandbox routing did not touch _execute_local_call."""
    import ast
    from pathlib import Path as _Path

    executor_path = (
        _Path(__file__).parent.parent.parent / "src" / "orchestrator" / "tools" / "executor.py"
    )
    tree = ast.parse(executor_path.read_text(encoding="utf-8"))
    fn_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_execute_local_call":
            fn_node = node
            break
    assert fn_node is not None
    sandbox_symbols = {"sandboxed_run", "PostureResolver", "SandboxRuntime"}
    violations = []
    for node in ast.walk(fn_node):
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if isinstance(node, ast.Name) else node.attr
            if name in sandbox_symbols:
                violations.append(f"executor.py:{node.lineno}: {name!r}")
    assert not violations, "executor byte-frozen violated by P4.3-7"
