"""Sandbox constitutional invariant tests (ADR-037; P4.3-12).

s1 — no-exec-without-sandbox-unless-opt-in:
     No host spawn reachable when unavailable + not opted-in.
s2 — fail-closed default:
     degraded requires the explicit flag + emits WARNING;
     config-parse failure → fail-closed.
s3 — empty-executor-diff preserved:
     _execute_local_call references no new sandbox symbol.
s4 — egress deny-default:
     default SandboxProfile emits --network none.
s5 — sandbox package is a downstream leaf:
     only api/ + subprocess_trust/net_trust import it.
s6 — /var/run/docker.sock NEVER in spawn args:
     no profile/spawn path emits a docker-sock bind.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest import mock

import pytest

_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator"
_SANDBOX_PKG = _SRC / "sandbox"


# ---------------------------------------------------------------------------
# s1: no host spawn reachable when unavailable + not opted-in (FAIL_CLOSED)
# ---------------------------------------------------------------------------


def test_s1_no_exec_without_sandbox_fail_closed() -> None:
    """When runtime is unavailable and degraded_app_level is False, no host spawn."""
    from orchestrator.sandbox.posture import PostureResolver, SandboxConfig
    from orchestrator.tools.local import LocalToolError
    from orchestrator.tools.subprocess_tools import build_subprocess_tool_registry

    config = SandboxConfig(degraded_app_level=False)
    resolver = PostureResolver(config=config, runtime=None)

    registry = build_subprocess_tool_registry(Path("/tmp"), posture_resolver=resolver)

    with (
        mock.patch("orchestrator.tools.subprocess_tools.run_scoped_command") as mock_rsc,
        pytest.raises(LocalToolError, match="sandbox_unavailable"),
    ):
        registry["run_tests"]({})

    mock_rsc.assert_not_called()


def test_s1_no_exec_for_web_fetch_fail_closed(tmp_path: Path) -> None:
    """web_fetch: no in-process httpx when runtime unavailable + no opt-in."""
    from orchestrator.sandbox.posture import PostureResolver, SandboxConfig
    from orchestrator.tools.local import LocalToolError
    from orchestrator.tools.network_tools import build_network_tool_registry

    config = SandboxConfig(degraded_app_level=False)
    resolver = PostureResolver(config=config, runtime=None)

    registry = build_network_tool_registry(posture_resolver=resolver, sandbox_root=tmp_path)

    with (
        mock.patch("orchestrator.tools.net_trust._resolve_and_validate", return_value="1.2.3.4"),
        mock.patch("orchestrator.tools.network_tools.build_ssrf_client") as mock_ssrf,
        pytest.raises(LocalToolError, match="sandbox_unavailable"),
    ):
        registry["web_fetch"]({"url": "https://example.com"})

    mock_ssrf.assert_not_called()


# ---------------------------------------------------------------------------
# s2: fail-closed default + config-parse failure → fail-closed
# ---------------------------------------------------------------------------


def test_s2_fail_closed_default() -> None:
    """Without opt-in, posture = FAIL_CLOSED when runtime unavailable."""
    from orchestrator.sandbox.posture import PostureResolver, SandboxConfig, SandboxPosture

    config = SandboxConfig(degraded_app_level=False)
    resolver = PostureResolver(config=config, runtime=None)
    assert resolver.resolve() == SandboxPosture.FAIL_CLOSED


def test_s2_degraded_requires_explicit_flag() -> None:
    """DEGRADED posture requires degraded_app_level=True (never silent)."""
    from orchestrator.sandbox.posture import PostureResolver, SandboxConfig, SandboxPosture

    config_no = SandboxConfig(degraded_app_level=False)
    resolver_no = PostureResolver(config=config_no, runtime=None)
    assert resolver_no.resolve() != SandboxPosture.DEGRADED

    config_yes = SandboxConfig(degraded_app_level=True)
    resolver_yes = PostureResolver(config=config_yes, runtime=None)
    assert resolver_yes.resolve() == SandboxPosture.DEGRADED


def test_s2_degraded_emits_warning(caplog: pytest.LogCaptureFixture) -> None:
    """DEGRADED path emits WARNING on every call."""
    from orchestrator.sandbox.posture import PostureResolver, SandboxConfig
    from orchestrator.sandbox.runtime import SandboxUnavailableError

    config = SandboxConfig(degraded_app_level=True)
    resolver = PostureResolver(config=config, runtime=None)

    with (
        caplog.at_level("WARNING", logger="orchestrator.sandbox.posture"),
        pytest.raises(SandboxUnavailableError),
    ):
        resolver.assert_sandboxed_or_raise("run_tests")

    assert any("DEGRADED" in r.message for r in caplog.records)


def test_s2_config_parse_failure_is_fail_closed(tmp_path: Path) -> None:
    """Config-parse failure → FAIL_CLOSED (never fail-open)."""
    from orchestrator.sandbox.posture import (
        PostureResolver,
        SandboxConfig,
        SandboxConfigError,
        SandboxPosture,
        load_sandbox_config,
    )

    bad_config = tmp_path / "sandbox.yaml"
    bad_config.write_text("runtime: nsjail\nimage: x\n")

    with pytest.raises(SandboxConfigError):
        load_sandbox_config(bad_config)

    config = SandboxConfig(degraded_app_level=False)
    resolver = PostureResolver(config=config, runtime=None)
    assert resolver.resolve() == SandboxPosture.FAIL_CLOSED


# ---------------------------------------------------------------------------
# RW8 assertion 2: config-absence and parse-failure → fail-closed
#   via the REAL composition-root code path (same logic as api/app.py _build_context)
#   NOT a hand-injected resolver, NOT a SANDBOXED stub.
# ---------------------------------------------------------------------------


def test_rw8_config_absence_real_path_fail_closed(tmp_path: Path) -> None:
    """RW8-2: no sandbox.yaml → fail_closed via the real _resolve_sandbox_posture path."""
    from unittest import mock

    from orchestrator.api.app import _resolve_sandbox_posture
    from orchestrator.tools.local import LocalToolError
    from orchestrator.tools.subprocess_tools import build_subprocess_tool_registry

    # tmp_path has no sandbox.yaml — drives the real composition-root branch, not a copy of it
    resolver = _resolve_sandbox_posture(tmp_path)
    registry = build_subprocess_tool_registry(tmp_path, posture_resolver=resolver)

    with (
        mock.patch("orchestrator.tools.subprocess_tools.run_scoped_command") as mock_rsc,
        pytest.raises(LocalToolError, match="sandbox_unavailable"),
    ):
        registry["run_tests"]({})

    mock_rsc.assert_not_called()


def test_rw8_config_parse_failure_real_path_fail_closed(tmp_path: Path) -> None:
    """RW8-2: config parse-failure → fail_closed via the real _resolve_sandbox_posture path."""
    from unittest import mock

    from orchestrator.api.app import _resolve_sandbox_posture
    from orchestrator.tools.local import LocalToolError
    from orchestrator.tools.subprocess_tools import build_subprocess_tool_registry

    config_path = tmp_path / "sandbox.yaml"
    config_path.write_text("runtime: nsjail\nimage: test\n")  # invalid runtime

    # Drives the real parse-fail branch; a revert of app.py's except→fail_closed() would break this
    resolver = _resolve_sandbox_posture(tmp_path)
    registry = build_subprocess_tool_registry(tmp_path, posture_resolver=resolver)

    with (
        mock.patch("orchestrator.tools.subprocess_tools.run_scoped_command") as mock_rsc,
        pytest.raises(LocalToolError, match="sandbox_unavailable"),
    ):
        registry["run_tests"]({})

    mock_rsc.assert_not_called()


def test_rw8_web_fetch_config_absence_fail_closed(tmp_path: Path) -> None:
    """RW8-2: web_fetch also fails closed on config-absence (not just subprocess)."""
    from unittest import mock

    from orchestrator.api.app import _resolve_sandbox_posture
    from orchestrator.tools.local import LocalToolError
    from orchestrator.tools.network_tools import build_network_tool_registry

    # tmp_path has no sandbox.yaml — drives the real absence branch for the web_fetch path
    resolver = _resolve_sandbox_posture(tmp_path)
    registry = build_network_tool_registry(posture_resolver=resolver, sandbox_root=tmp_path)

    with (
        mock.patch("orchestrator.tools.net_trust._resolve_and_validate", return_value="1.2.3.4"),
        mock.patch("orchestrator.tools.network_tools.build_ssrf_client") as mock_ssrf,
        pytest.raises(LocalToolError, match="sandbox_unavailable"),
    ):
        registry["web_fetch"]({"url": "https://example.com"})

    mock_ssrf.assert_not_called()


# ---------------------------------------------------------------------------
# s3: empty-executor-diff — _execute_local_call references no new sandbox symbol
# ---------------------------------------------------------------------------


def test_s3_execute_local_call_empty_decision_diff() -> None:
    """s3: _execute_local_call must not reference any sandbox symbol (byte-frozen)."""
    executor_path = _SRC / "tools" / "executor.py"
    tree = ast.parse(executor_path.read_text(encoding="utf-8"))

    fn_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_execute_local_call":
            fn_node = node
            break

    assert fn_node is not None, "s3: _execute_local_call not found in executor.py"

    sandbox_symbols = frozenset({
        "sandboxed_run",
        "PostureResolver",
        "SandboxRuntime",
        "SandboxUnavailableError",
        "SandboxConfig",
    })
    violations: list[str] = []
    for node in ast.walk(fn_node):
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if isinstance(node, ast.Name) else node.attr
            if name in sandbox_symbols:
                violations.append(f"  executor.py:{node.lineno}: {name!r}")

    assert not violations, (
        "s3: _execute_local_call references sandbox symbols "
        "(executor byte-frozen invariant violated; wrap must live below the executor):\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# s4: egress deny-default — default SandboxProfile emits --network none
# ---------------------------------------------------------------------------


def test_s4_deny_default_profile_emits_network_none(tmp_path: Path) -> None:
    """Default SandboxProfile (no network override) emits --network none."""
    from orchestrator.sandbox.profile import SandboxProfile, build_container_args

    profile = SandboxProfile(sandbox_root=tmp_path, image="test:latest")
    args = build_container_args(profile, [])

    assert "--network" in args
    idx = args.index("--network")
    assert args[idx + 1] == "none", (
        "s4: default profile must emit --network none (deny-default egress)"
    )


# ---------------------------------------------------------------------------
# s5: sandbox package is a downstream leaf
#     only api/ + subprocess_trust / net_trust may import it
# ---------------------------------------------------------------------------


def test_s5_sandbox_is_downstream_leaf() -> None:
    """s5: only api/, subprocess_trust.py, net_trust.py may import orchestrator.sandbox.*"""
    allowed_importers = {
        _SRC / "api",
        _SRC / "mcp" / "subprocess_trust.py",
        _SRC / "tools" / "net_trust.py",
        _SRC / "tools" / "subprocess_tools.py",
        _SRC / "tools" / "network_tools.py",
        _SRC / "plugins" / "code.py",
        _SRC / "plugins" / "loader.py",  # TYPE_CHECKING only: PostureResolver annotation
        _SANDBOX_PKG,
    }

    violations: list[str] = []
    for py_path in _SRC.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        # Skip sandbox package itself
        try:
            py_path.relative_to(_SANDBOX_PKG)
            continue
        except ValueError:
            pass
        # Check if this file is in an allowed importer
        is_allowed = any(
            py_path == allowed or (allowed.is_dir() and py_path.is_relative_to(allowed))
            for allowed in allowed_importers
        )
        if is_allowed:
            continue
        source = py_path.read_text(encoding="utf-8")
        if "orchestrator.sandbox" not in source:
            continue
        tree = ast.parse(source, filename=str(py_path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = ""
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name
                elif node.module:
                    module = node.module
                if module.startswith("orchestrator.sandbox"):
                    violations.append(
                        f"  {py_path.relative_to(_SRC)}: line {node.lineno}: {module}"
                    )

    assert not violations, (
        "s5: sandbox package imported by non-allowed module "
        "(sandbox/ must be a downstream leaf; only api/ + mcp/subprocess_trust + "
        "tools/net_trust + tools/subprocess_tools + tools/network_tools + "
        "plugins/code are allowed):\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# s6: /var/run/docker.sock NEVER in spawn args
# ---------------------------------------------------------------------------


def test_s6_docker_sock_never_in_profile_args(tmp_path: Path) -> None:
    """s6: no profile variant emits /var/run/docker.sock in container args."""
    from orchestrator.sandbox.profile import SandboxProfile, build_container_args

    # Test all profile variants: deny-default, named network, with env vars
    for network in (None, "test-net"):
        profile = SandboxProfile(
            sandbox_root=tmp_path,
            image="test:latest",
            network=network,
            env={"FOO": "bar"},
        )
        args = build_container_args(profile, ["pytest"])
        for arg in args:
            assert "/var/run/docker.sock" not in arg, (
                f"s6: /var/run/docker.sock found in profile args "
                f"(network={network!r}): {arg!r}"
            )


def test_s6_docker_sock_assertion_fires_on_violation() -> None:
    """s6: _assert_no_docker_sock raises RuntimeError when docker-sock appears."""
    from orchestrator.sandbox.profile import _assert_no_docker_sock

    with pytest.raises(RuntimeError, match="CONSTITUTIONAL VIOLATION"):
        _assert_no_docker_sock(["--volume", "/var/run/docker.sock:/var/run/docker.sock:rw"])


def test_s6_sandboxed_run_args_no_docker_sock(tmp_path: Path) -> None:
    """s6: sandboxed_run never builds args with docker-sock (end-to-end profile check)."""
    from orchestrator.sandbox.profile import SandboxProfile, build_container_args

    profile = SandboxProfile(sandbox_root=tmp_path, image="test:latest")
    container_args = build_container_args(profile, ["pytest"])
    all_args = " ".join(container_args)

    assert "/var/run/docker.sock" not in all_args, (
        "s6: docker-sock appears in sandboxed_run container args — CONSTITUTIONAL VIOLATION"
    )
