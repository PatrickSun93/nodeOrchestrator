"""Wired-whole test for _resolve_plugin_registry (P4.4-4, ADR-038 D2).

Drives the real _resolve_plugin_registry function (not a hand-built dict),
matching the wired-whole discipline (constitution RW8-2).

Acceptance (plan P4.4-4):
  rw1 — absent config/plugins.yaml → empty registry (today's defaults)
  rw2 — malformed plugins.yaml → REGISTRY_REFUSE_ALL sentinel + WARNING (no exception escapes)
  rw3 — valid plugins.yaml → entries applied
  rw4 — empty-disabled plugin + _resolve_plugin_registry: disabled plugin refused,
         load_plugins receives real PluginRegistry from helper
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from orchestrator.api.app import _resolve_plugin_registry
from orchestrator.plugins.provenance import REGISTRY_REFUSE_ALL

# ---------------------------------------------------------------------------
# rw1: absent config/plugins.yaml → empty registry
# ---------------------------------------------------------------------------


def test_rw1_absent_plugins_yaml_returns_empty(tmp_path: Path) -> None:
    """No config/plugins.yaml → empty PluginRegistry (today's shipped defaults)."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    result = _resolve_plugin_registry(config_dir)
    assert result == {}


# ---------------------------------------------------------------------------
# rw2: malformed plugins.yaml → empty + WARNING, no exception escapes
# ---------------------------------------------------------------------------


def test_rw2_malformed_plugins_yaml_returns_sentinel_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Malformed plugins.yaml → REGISTRY_REFUSE_ALL sentinel + WARNING (ADR-038 D2 refuse-all).

    The sentinel is distinct from an empty dict: absent config → empty {} (defaults);
    malformed config → sentinel (refuse-all, no presence resurrection).
    No exception propagates through _resolve_plugin_registry (graceful, app does not crash).
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "plugins.yaml").write_text(
        "plugins: not-a-list\n", encoding="utf-8"
    )
    with caplog.at_level(logging.WARNING, logger="orchestrator.api.app"):
        result = _resolve_plugin_registry(config_dir)
    assert result is REGISTRY_REFUSE_ALL
    assert any("parse failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# rw3: valid plugins.yaml → entries applied
# ---------------------------------------------------------------------------


def test_rw3_valid_plugins_yaml_entries_applied(tmp_path: Path) -> None:
    """Well-formed plugins.yaml → RegistryEntry entries available in returned dict."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "plugins.yaml").write_text(
        "plugins:\n"
        "  - plugin_id: my_plugin\n"
        "    enabled: true\n"
        "    version: '1.0.0'\n",
        encoding="utf-8",
    )
    result = _resolve_plugin_registry(config_dir)
    assert "my_plugin" in result
    assert result["my_plugin"].enabled is True
    assert result["my_plugin"].version == "1.0.0"


def test_rw3_disabled_entry_present(tmp_path: Path) -> None:
    """Disabled entry (enabled: false) is present in registry (gate enforced in load_plugins)."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "plugins.yaml").write_text(
        "plugins:\n  - plugin_id: disabled_plugin\n    enabled: false\n",
        encoding="utf-8",
    )
    result = _resolve_plugin_registry(config_dir)
    assert "disabled_plugin" in result
    assert result["disabled_plugin"].enabled is False


# ---------------------------------------------------------------------------
# rw4: wired-whole: load_plugins receives registry from _resolve_plugin_registry
# ---------------------------------------------------------------------------


def test_rw4_load_plugins_receives_real_registry(tmp_path: Path) -> None:
    """Disabled plugin: _resolve_plugin_registry + load_plugins integration."""
    from textwrap import dedent

    from orchestrator.llm.router import ModelRegistry
    from orchestrator.llm.types import ModelId, ModelProfile, ProviderId
    from orchestrator.plugins.loader import load_plugins
    from orchestrator.plugins.schema import PLUGIN_HOST_CONTRACT_VERSION

    # Create a plugin
    plugins_dir = tmp_path / "plugins"
    pdir = plugins_dir / "testplugin"
    pdir.mkdir(parents=True)
    (pdir / "plugin.yaml").write_text(
        dedent("""\
            schema_version: 1
            id: testplugin
            name: 'Test Plugin'
            version: '1.0.0'
            contributions:
              tool_impls:
                test_fn: 'tools_impl:fn'
        """),
        encoding="utf-8",
    )
    (pdir / "tools_impl.py").write_text(
        "from orchestrator.tools.executor import LocalToolOutput\n"
        "def fn(params): return LocalToolOutput(content='ok')\n",
        encoding="utf-8",
    )

    # config_dir with plugins.yaml that disables testplugin
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "plugins.yaml").write_text(
        "plugins:\n  - plugin_id: testplugin\n    enabled: false\n",
        encoding="utf-8",
    )

    # Drive the real _resolve_plugin_registry
    registry = _resolve_plugin_registry(config_dir)
    assert "testplugin" in registry
    assert registry["testplugin"].enabled is False

    models = ModelRegistry(
        {
            ModelId("m1"): ModelProfile(
                id=ModelId("m1"),
                provider=ProviderId("test"),
                provider_model_id="m1",
                capabilities=[],
                context_window=8192,
            )
        }
    )
    result = load_plugins(
        plugins_dir,
        models=models,
        host_room_types=frozenset({"free_chat"}),
        host_contract_version=PLUGIN_HOST_CONTRACT_VERSION,
        host_agents={},
        host_skills={},
        host_tools={},
        host_local_tool_names=frozenset(),
        host_mcp_server_names=frozenset(),
        plugin_registry=registry,
    )
    # Disabled plugin → no tools loaded
    assert result.local_tools == {}
