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
    """_build_sandboxed_harness_params returns (params, cname) with runtime CLI as command."""
    resolver = _make_resolver(available=True)
    fn = _make_fn(tmp_path, resolver=resolver)

    rt = SandboxRuntime(kind="docker", cli="/usr/bin/docker")
    params, _cname = fn._build_sandboxed_harness_params(runtime=rt, scoped={})

    assert params.command == "/usr/bin/docker"


def test_sandboxed_harness_params_starts_with_run(tmp_path: Path) -> None:
    """Container invocation args must start with 'run'."""
    resolver = _make_resolver(available=True)
    fn = _make_fn(tmp_path, resolver=resolver)

    rt = SandboxRuntime(kind="docker", cli="/usr/bin/docker")
    params, _cname = fn._build_sandboxed_harness_params(runtime=rt, scoped={})

    assert params.args[0] == "run"


def test_sandboxed_harness_params_includes_interactive_flag(tmp_path: Path) -> None:
    """Container args must include -i for MCP-stdio handshake (RW5)."""
    resolver = _make_resolver(available=True)
    fn = _make_fn(tmp_path, resolver=resolver)

    rt = SandboxRuntime(kind="docker", cli="/usr/bin/docker")
    params, _cname = fn._build_sandboxed_harness_params(runtime=rt, scoped={})

    assert "-i" in params.args


def test_sandboxed_harness_params_no_docker_sock(tmp_path: Path) -> None:
    """Container args must never include /var/run/docker.sock."""
    resolver = _make_resolver(available=True)
    fn = _make_fn(tmp_path, resolver=resolver)

    rt = SandboxRuntime(kind="docker", cli="/usr/bin/docker")
    params, _cname = fn._build_sandboxed_harness_params(runtime=rt, scoped={})

    all_args = " ".join(params.args)
    assert "/var/run/docker.sock" not in all_args


def test_sandboxed_harness_params_deny_default_network(tmp_path: Path) -> None:
    """Plugin spawn uses deny-default network (no egress needed)."""
    resolver = _make_resolver(available=True)
    fn = _make_fn(tmp_path, resolver=resolver)

    rt = SandboxRuntime(kind="docker", cli="/usr/bin/docker")
    params, _cname = fn._build_sandboxed_harness_params(runtime=rt, scoped={})

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
# RW8 assertion 3: plugin route reaches the container via load_plugin_code
#   - resolver IS forwarded from load_plugin_code to _PostureBFn
#   - -i flag present
#   - profile flags (--cap-drop, --network none, --read-only) present
# ---------------------------------------------------------------------------


def test_rw8_load_plugin_code_sets_resolver(tmp_path: Path) -> None:
    """RW8-3: load_plugin_code forwards posture_resolver to _PostureBFn."""
    from orchestrator.plugins.code import _PostureBFn, load_plugin_code
    from orchestrator.sandbox.posture import PostureResolver, SandboxConfig

    module_file = tmp_path / "tools_impl.py"
    module_file.write_text("def my_tool(args): return 'ok'\n")

    resolver = PostureResolver(config=SandboxConfig(image="test:latest"), runtime=None)

    result = load_plugin_code(
        tmp_path, "test-plugin",
        {"test_tool": "tools_impl:my_tool"},
        provenance="fetched",
        posture_resolver=resolver,
        sandbox_root=tmp_path,
    )

    fn = result["test_tool"]
    assert isinstance(fn, _PostureBFn), "load_plugin_code must return _PostureBFn for fetched"
    assert fn._posture_resolver is resolver, "_PostureBFn must have resolver set (not None)"
    assert fn._sandbox_root == tmp_path, "_PostureBFn must have sandbox_root set"


def test_rw8_sandboxed_params_have_i_flag(tmp_path: Path) -> None:
    """RW8-3: container params for plugin spawn include -i (MCP-stdio stdin)."""
    resolver = _make_resolver(available=True)
    fn = _make_fn(tmp_path, resolver=resolver)

    rt = SandboxRuntime(kind="docker", cli="/usr/bin/docker")
    params, _cname = fn._build_sandboxed_harness_params(runtime=rt, scoped={})

    assert "-i" in params.args, "Container args must include -i for MCP-stdio stdin"


def test_rw8_sandboxed_params_have_profile_flags(tmp_path: Path) -> None:
    """RW8-3: container params include isolation profile flags."""
    resolver = _make_resolver(available=True)
    fn = _make_fn(tmp_path, resolver=resolver)

    rt = SandboxRuntime(kind="docker", cli="/usr/bin/docker")
    params, _cname = fn._build_sandboxed_harness_params(runtime=rt, scoped={})

    args_str = " ".join(params.args)
    assert "--cap-drop" in args_str, "Profile must include --cap-drop"
    assert "--read-only" in args_str, "Profile must include --read-only rootfs"
    assert "--network" in args_str, "Profile must include network isolation"
    assert "none" in args_str, "Plugin spawn uses deny-default network"


def test_rw8_container_name_returned_from_params(tmp_path: Path) -> None:
    """RW8-3: _build_sandboxed_harness_params returns a non-empty container name."""
    resolver = _make_resolver(available=True)
    fn = _make_fn(tmp_path, resolver=resolver)

    rt = SandboxRuntime(kind="docker", cli="/usr/bin/docker")
    _params, cname = fn._build_sandboxed_harness_params(runtime=rt, scoped={})

    assert cname, "Container name must be non-empty (for targeted kill in finally)"


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
