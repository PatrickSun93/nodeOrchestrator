"""Tests for sandbox/posture.py (P4.3-5).

Verifies: available→sandboxed; unavailable+no-opt-in→fail-closed;
unavailable+opt-in→degraded+WARNING; config-parse-failure→fail-closed;
available() cached per turn (repeated unavailable calls fail fast).
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest import mock

import pytest

from orchestrator.sandbox.posture import (
    PostureResolver,
    SandboxConfig,
    SandboxConfigError,
    SandboxPosture,
    load_sandbox_config,
)
from orchestrator.sandbox.runtime import SandboxRuntime, SandboxUnavailableError


def _make_resolver(
    available: bool = True,
    degraded_app_level: bool = False,
) -> PostureResolver:
    config = SandboxConfig(degraded_app_level=degraded_app_level)
    rt: SandboxRuntime | None = None
    if available:
        rt = SandboxRuntime(kind="docker", cli="/usr/bin/docker")
        rt.available = mock.Mock(return_value=True)  # type: ignore[method-assign]
    resolver = PostureResolver(config=config, runtime=rt)
    return resolver


# ---------------------------------------------------------------------------
# Posture resolution
# ---------------------------------------------------------------------------


def test_available_resolves_sandboxed() -> None:
    resolver = _make_resolver(available=True)
    assert resolver.resolve() == SandboxPosture.SANDBOXED


def test_unavailable_no_optin_resolves_fail_closed() -> None:
    resolver = _make_resolver(available=False, degraded_app_level=False)
    assert resolver.resolve() == SandboxPosture.FAIL_CLOSED


def test_unavailable_with_optin_resolves_degraded() -> None:
    resolver = _make_resolver(available=False, degraded_app_level=True)
    assert resolver.resolve() == SandboxPosture.DEGRADED


# ---------------------------------------------------------------------------
# assert_sandboxed_or_raise
# ---------------------------------------------------------------------------


def test_sandboxed_returns_runtime() -> None:
    resolver = _make_resolver(available=True)
    rt = resolver.assert_sandboxed_or_raise("run_tests")
    assert isinstance(rt, SandboxRuntime)


def test_fail_closed_raises_unavailable() -> None:
    resolver = _make_resolver(available=False, degraded_app_level=False)
    with pytest.raises(SandboxUnavailableError, match="FAIL_CLOSED"):
        resolver.assert_sandboxed_or_raise("run_tests")


def test_degraded_raises_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    resolver = _make_resolver(available=False, degraded_app_level=True)
    with (
        caplog.at_level("WARNING", logger="orchestrator.sandbox.posture"),
        pytest.raises(SandboxUnavailableError, match="DEGRADED"),
    ):
        resolver.assert_sandboxed_or_raise("run_tests")

    assert any("DEGRADED" in r.message for r in caplog.records), (
        "DEGRADED path must emit a WARNING log on every call"
    )


def test_no_host_spawn_when_fail_closed() -> None:
    """No path reaches a raw host spawn when unavailable-and-not-opted-in."""
    resolver = _make_resolver(available=False, degraded_app_level=False)
    raised = False
    try:
        resolver.assert_sandboxed_or_raise("run_tests")
    except SandboxUnavailableError:
        raised = True
    assert raised, "FAIL_CLOSED must raise SandboxUnavailableError — no silent host exec"


# ---------------------------------------------------------------------------
# Liveness cache: repeated unavailable calls fail fast (no per-call probe stack-up)
# ---------------------------------------------------------------------------


def test_liveness_cached_per_turn() -> None:
    rt = SandboxRuntime(kind="docker", cli="/usr/bin/docker")
    rt.available = mock.Mock(return_value=False)  # type: ignore[method-assign]
    resolver = PostureResolver(config=SandboxConfig(), runtime=rt)

    # Call resolve() three times.
    for _ in range(3):
        resolver.resolve()

    # available() should only be called ONCE (cached after first call within TTL).
    rt.available.assert_called_once()


# ---------------------------------------------------------------------------
# Config-parse failure → fail-closed
# ---------------------------------------------------------------------------


def test_load_config_valid(tmp_path: Path) -> None:
    cfg_file = tmp_path / "sandbox.yaml"
    cfg_file.write_text(
        textwrap.dedent("""
            runtime: docker
            image: my-sandbox:1.0
            egress_allowlist:
              - example.com
            degraded_app_level: false
        """)
    )
    config = load_sandbox_config(cfg_file)
    assert config.runtime == "docker"
    assert config.image == "my-sandbox:1.0"
    assert "example.com" in config.egress_allowlist
    assert config.degraded_app_level is False


def test_load_config_file_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(SandboxConfigError, match="cannot read"):
        load_sandbox_config(tmp_path / "nonexistent.yaml")


def test_load_config_invalid_yaml_raises(tmp_path: Path) -> None:
    cfg_file = tmp_path / "sandbox.yaml"
    cfg_file.write_text("runtime: [unclosed\n")
    with pytest.raises(SandboxConfigError, match="invalid YAML"):
        load_sandbox_config(cfg_file)


def test_load_config_invalid_runtime_raises(tmp_path: Path) -> None:
    cfg_file = tmp_path / "sandbox.yaml"
    cfg_file.write_text("runtime: nsjail\nimage: x\n")
    with pytest.raises(SandboxConfigError, match="invalid runtime"):
        load_sandbox_config(cfg_file)


def test_load_config_not_mapping_raises(tmp_path: Path) -> None:
    cfg_file = tmp_path / "sandbox.yaml"
    cfg_file.write_text("- foo\n- bar\n")
    with pytest.raises(SandboxConfigError, match="expected a YAML mapping"):
        load_sandbox_config(cfg_file)


def test_load_config_empty_image_raises(tmp_path: Path) -> None:
    cfg_file = tmp_path / "sandbox.yaml"
    cfg_file.write_text("runtime: auto\nimage: ''\n")
    with pytest.raises(SandboxConfigError, match="'image' must be"):
        load_sandbox_config(cfg_file)


def test_config_parse_failure_resolver_is_fail_closed() -> None:
    """A config-parse failure must produce fail-closed posture (no runtime = no opt-in possible)."""
    config = SandboxConfig(degraded_app_level=False)
    resolver = PostureResolver(config=config, runtime=None)
    assert resolver.resolve() == SandboxPosture.FAIL_CLOSED


def test_degraded_opt_in_flag() -> None:
    config = SandboxConfig(degraded_app_level=True)
    resolver = PostureResolver(config=config, runtime=None)
    assert resolver.is_degraded_opted_in() is True
