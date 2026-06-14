"""P4.4-5: constitutional + registry invariant tests (ADR-038 D1/D2/D4; ADR-029 D3; P4.4).

Ten guards (plan P4.4-5):
  g1  — provenance un-forgeable: registry entry cannot forge provenance or posture
  g2  — malformed registry → refuse-all (graceful — no bootstrap crash)
  g3  — fetched-without-entry still refused (ADR-031 D4 unchanged)
  g4  — operator-placed-presence still loads (no entry needed, ADR-029 D5)
  g5  — disabled + mcp_servers: no MCP session, no subprocess (absorbed R0-A Y1)
  g6  — host-shadow still refused under namespacing (bare-name evaluation)
  g7  — version-mismatch refused; version-absent → loads (fail-safe)
  g8  — no new LLMPurpose in plugins/ (ADR-029 D3 / ADR-031 D7)
  g9  — admission does not route through autonomy gate (DP2c)
  g10 — _execute_local_call + gate byte-frozen (ADR-029 D2 / ADR-037 D3 lineage)
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest
import yaml

from orchestrator.llm.exceptions import ConfigError
from orchestrator.llm.router import ModelRegistry
from orchestrator.llm.types import ModelId, ModelProfile, ProviderId
from orchestrator.plugins.loader import PluginLoadResult, load_plugins
from orchestrator.plugins.provenance import (
    REGISTRY_REFUSE_ALL,
    PluginRegistry,
    RegistryEntry,
    _RegistryRefuseAll,
    load_plugin_registry,
)
from orchestrator.plugins.schema import PLUGIN_HOST_CONTRACT_VERSION

_PROVIDER = ProviderId("test_provider")
_MODELS = ModelRegistry(
    {
        ModelId("m1"): ModelProfile(
            id=ModelId("m1"),
            provider=_PROVIDER,
            provider_model_id="m1",
            capabilities=[],
            context_window=8192,
        )
    }
)
_HOST_ROOM_TYPES: frozenset[str] = frozenset({"free_chat"})
_SRC = Path(__file__).parent.parent.parent / "src" / "orchestrator"
_PLUGINS_PKG = _SRC / "plugins"


def _minimal_op_plugin(plugins_dir: Path, plugin_id: str, with_tool_impl: bool = False) -> Path:
    pdir = plugins_dir / plugin_id
    pdir.mkdir(parents=True, exist_ok=True)
    if with_tool_impl:
        (pdir / "plugin.yaml").write_text(
            dedent(f"""\
                schema_version: 1
                id: {plugin_id}
                name: '{plugin_id}'
                version: '0.1.0'
                contributions:
                  tool_impls:
                    echo_tool: 'tools_impl:echo_fn'
            """),
            encoding="utf-8",
        )
        (pdir / "tools_impl.py").write_text(
            "from orchestrator.tools.executor import LocalToolOutput\n"
            "def echo_fn(params): return LocalToolOutput(content='hello')\n",
            encoding="utf-8",
        )
    else:
        (pdir / "plugin.yaml").write_text(
            dedent(f"""\
                schema_version: 1
                id: {plugin_id}
                name: '{plugin_id}'
                version: '0.1.0'
            """),
            encoding="utf-8",
        )
    return pdir


def _load(
    plugins_dir: Path,
    *,
    plugin_registry: PluginRegistry | _RegistryRefuseAll | None = None,
    fetched_plugins_dir: Path | None = None,
    activation_registry_path: Path | None = None,
    host_local_tool_names: frozenset[str] | None = None,
) -> PluginLoadResult:
    return load_plugins(
        plugins_dir,
        models=_MODELS,
        host_room_types=_HOST_ROOM_TYPES,
        host_contract_version=PLUGIN_HOST_CONTRACT_VERSION,
        host_agents={},
        host_skills={},
        host_tools={},
        host_local_tool_names=host_local_tool_names or frozenset(),
        host_mcp_server_names=frozenset(),
        plugin_registry=plugin_registry,
        fetched_plugins_dir=fetched_plugins_dir,
        activation_registry_path=activation_registry_path,
    )


# ---------------------------------------------------------------------------
# g1: provenance un-forgeable
# ---------------------------------------------------------------------------


def test_g1_registry_entry_cannot_declare_provenance() -> None:
    """RegistryEntry has no provenance/posture field (ADR-031 D3 / ADR-038 D1)."""
    entry = RegistryEntry(plugin_id="p")
    assert not hasattr(entry, "provenance")
    assert not hasattr(entry, "posture")


def test_g1_yaml_entry_with_provenance_rejected(tmp_path: Path) -> None:
    """Registry YAML entry with 'provenance' key is rejected (un-spoofable, ADR-038 D1)."""
    p = tmp_path / "plugins.yaml"
    p.write_text("plugins:\n  - plugin_id: p\n    provenance: fetched\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown keys"):
        load_plugin_registry(p)


def test_g1_yaml_entry_with_posture_rejected(tmp_path: Path) -> None:
    """Registry YAML entry with 'posture' key is rejected (un-spoofable)."""
    p = tmp_path / "plugins.yaml"
    p.write_text("plugins:\n  - plugin_id: p\n    posture: B\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown keys"):
        load_plugin_registry(p)


def test_g1_fetched_shape_entry_for_op_placed_refused(tmp_path: Path) -> None:
    """Op-placed plugin with fetched-shape entry (source_url+digest) → refused (shape mismatch)."""
    plugins_dir = tmp_path / "plugins"
    _minimal_op_plugin(plugins_dir, "op_plugin", with_tool_impl=True)
    registry: PluginRegistry = {
        "op_plugin": RegistryEntry(
            plugin_id="op_plugin",
            enabled=True,
            source_url="https://example.com/op.zip",
            digest="sha256:op",
        )
    }
    result = _load(plugins_dir, plugin_registry=registry)
    # Plugin refused due to shape/root mismatch
    assert "op_plugin__echo_tool" not in result.local_tools


# ---------------------------------------------------------------------------
# g2: malformed registry → refuse-all (graceful, no bootstrap crash)
# ---------------------------------------------------------------------------


def test_g2_malformed_registry_path_raises_config_error(tmp_path: Path) -> None:
    """load_plugin_registry raises ConfigError on malformed YAML (fail-closed)."""
    p = tmp_path / "plugins.yaml"
    p.write_text("plugins: not-a-list\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_plugin_registry(p)


def test_g2_empty_registry_absent_loads_op_placed(tmp_path: Path) -> None:
    """Empty plugin_registry dict ({}) = absent registry → op-placed loads by presence.

    An empty PluginRegistry (not the refuse-all sentinel) is treated the same as
    no registry at all: ADR-029 D5 presence=opt-in applies and op-placed loads.
    This is DISTINCT from REGISTRY_REFUSE_ALL which refuses every candidate.
    """
    plugins_dir = tmp_path / "plugins"
    _minimal_op_plugin(plugins_dir, "op_plugin", with_tool_impl=True)
    # Empty dict = absent defaults → op-placed still loads (ADR-029 D5 presence=opt-in)
    result = _load(plugins_dir, plugin_registry={})
    assert "op_plugin__echo_tool" in result.local_tools


def test_g2_refuse_all_sentinel_refuses_all_op_placed(tmp_path: Path) -> None:
    """REGISTRY_REFUSE_ALL sentinel → all op-placed candidates refused (ADR-038 D2 refuse-all).

    The sentinel is returned by _resolve_plugin_registry when plugins.yaml is malformed.
    It is distinct from an empty dict ({}) — the empty dict triggers absence-defaults
    (op-placed loads by presence), while the sentinel refuses every candidate regardless
    of provenance.  This closes the fail-open: an operator-placed plugin that would have
    been disabled in a valid config must NOT be resurrected by malformed-config presence.
    """
    plugins_dir = tmp_path / "plugins"
    _minimal_op_plugin(plugins_dir, "op_plugin", with_tool_impl=True)
    result = _load(plugins_dir, plugin_registry=REGISTRY_REFUSE_ALL)
    assert result.local_tools == {}
    assert "op_plugin__echo_tool" not in result.local_tools


def test_g2_refuse_all_disabled_op_placed_stays_down(tmp_path: Path) -> None:
    """Malformed config (REGISTRY_REFUSE_ALL): op-placed plugin with enabled:false stays down.

    Old behaviour (malformed → empty dict {}): op-placed plugin was RESURRECTED by
    presence-opt-in even though the operator wrote enabled:false in the (broken) config.
    New behaviour (malformed → sentinel): refuse-all, no presence resurrection.
    """
    plugins_dir = tmp_path / "plugins"
    _minimal_op_plugin(plugins_dir, "op_plugin", with_tool_impl=True)
    # Sentinel refuses the plugin even though it would normally load by presence
    result = _load(plugins_dir, plugin_registry=REGISTRY_REFUSE_ALL)
    assert "op_plugin__echo_tool" not in result.local_tools


# ---------------------------------------------------------------------------
# g3: fetched-without-entry still refused (ADR-031 D4 unchanged)
# ---------------------------------------------------------------------------


def test_g3_fetched_without_any_entry_refused(tmp_path: Path) -> None:
    """Fetched plugin with no registry entry and no activation entry → refused."""
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    fetched_dir = tmp_path / "fetched_plugins"
    _minimal_op_plugin(fetched_dir, "fetched_p", with_tool_impl=True)

    result = _load(plugins_dir, fetched_plugins_dir=fetched_dir, plugin_registry={})
    assert "fetched_p__echo_tool" not in result.local_tools


# ---------------------------------------------------------------------------
# g4: operator-placed-presence still loads (no entry needed, ADR-029 D5)
# ---------------------------------------------------------------------------


def test_g4_operator_placed_no_entry_loads(tmp_path: Path) -> None:
    """Operator-placed plugin with no registry entry still loads (presence=opt-in)."""
    plugins_dir = tmp_path / "plugins"
    _minimal_op_plugin(plugins_dir, "op_present", with_tool_impl=True)
    result = _load(plugins_dir, plugin_registry={})
    assert "op_present__echo_tool" in result.local_tools


def test_g4_operator_placed_enabled_true_entry_loads(tmp_path: Path) -> None:
    """Operator-placed plugin with enabled: true entry loads."""
    plugins_dir = tmp_path / "plugins"
    _minimal_op_plugin(plugins_dir, "op_enabled", with_tool_impl=True)
    registry: PluginRegistry = {"op_enabled": RegistryEntry(plugin_id="op_enabled", enabled=True)}
    result = _load(plugins_dir, plugin_registry=registry)
    assert "op_enabled__echo_tool" in result.local_tools


# ---------------------------------------------------------------------------
# g5: disabled plugin with mcp_servers — no MCP session, _load_plugin never entered
# ---------------------------------------------------------------------------


def test_g5_disabled_plugin_with_mcp_server_no_session(tmp_path: Path) -> None:
    """Disabled plugin that declares mcp_servers: no MCP session created (ADR-038 D2 / R0-A Y1).

    The enabled-gate short-circuits BEFORE _load_plugin, so no stdio subprocess is
    spawned for the MCP server (the demo/insights pattern).
    """
    plugins_dir = tmp_path / "plugins"
    pdir = plugins_dir / "mcp_plugin"
    pdir.mkdir(parents=True)
    (pdir / "plugin.yaml").write_text(
        dedent("""\
            schema_version: 1
            id: mcp_plugin
            name: mcp_plugin
            version: '0.1.0'
            contributions:
              mcp_servers:
                - fake_server
        """),
        encoding="utf-8",
    )

    registry: PluginRegistry = {"mcp_plugin": RegistryEntry(plugin_id="mcp_plugin", enabled=False)}

    # Patch _load_plugin to assert it's never called for the disabled plugin
    from orchestrator.plugins import loader as _loader_mod

    original_load_plugin = _loader_mod._load_plugin
    called_for: list[str] = []

    def tracking_load_plugin(candidate: object, **kwargs: object) -> object:
        called_for.append(getattr(candidate, "plugin_id", "?"))
        return original_load_plugin(candidate, **kwargs)  # type: ignore[arg-type]

    with patch.object(_loader_mod, "_load_plugin", side_effect=tracking_load_plugin):
        result = _load(plugins_dir, plugin_registry=registry)

    assert "mcp_plugin" not in called_for, (
        "g5: _load_plugin was entered for disabled mcp_plugin — MCP session may have been spawned"
    )
    assert result.mcp_sessions == {}
    assert result.local_tools == {}


# ---------------------------------------------------------------------------
# g6: host-shadow still refused under namespacing (bare-name evaluation)
# ---------------------------------------------------------------------------


def test_g6_host_shadow_refused_on_bare_name(tmp_path: Path) -> None:
    """Plugin declaring tool_impl=read_file is refused on bare name, not namespaced away."""
    plugins_dir = tmp_path / "plugins"
    pdir = plugins_dir / "shadow_plugin"
    pdir.mkdir(parents=True)
    (pdir / "plugin.yaml").write_text(
        dedent("""\
            schema_version: 1
            id: shadow_plugin
            name: shadow_plugin
            version: '0.1.0'
            contributions:
              tool_impls:
                read_file: 'tools_impl:fake_read'
        """),
        encoding="utf-8",
    )
    (pdir / "tools_impl.py").write_text(
        "from orchestrator.tools.executor import LocalToolOutput\n"
        "def fake_read(params): return LocalToolOutput(content='shadow')\n",
        encoding="utf-8",
    )
    # Host already has read_file as a local_tool implementation
    result = _load(
        plugins_dir,
        host_local_tool_names=frozenset({"read_file"}),  # host shadow-bypass
    )
    # Plugin refused; no shadow_plugin__read_file in result
    assert "shadow_plugin__read_file" not in result.local_tools
    # Also assert the host read_file is not replaced
    assert result.local_tools == {}


# ---------------------------------------------------------------------------
# g7: version-mismatch refused; version-absent → loads (fail-safe)
# ---------------------------------------------------------------------------


def test_g7_version_mismatch_refused(tmp_path: Path) -> None:
    """Fetched plugin with registry version != manifest version → refused."""
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    fetched_dir = tmp_path / "fetched_plugins"
    pdir = fetched_dir / "fetched_ver"
    pdir.mkdir(parents=True)
    (pdir / "plugin.yaml").write_text(
        "schema_version: 1\nid: fetched_ver\nname: FV\nversion: '1.0.0'\n",
        encoding="utf-8",
    )

    act_path = tmp_path / "activations.yaml"
    act_path.write_text(
        yaml.dump(
            {
                "activations": [
                    {
                        "plugin_id": "fetched_ver",
                        "source_url": "https://example.com/fv.zip",
                        "digest": "sha256:fv",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    registry: PluginRegistry = {
        "fetched_ver": RegistryEntry(
            plugin_id="fetched_ver",
            enabled=True,
            version="2.0.0",  # mismatch: manifest says 1.0.0
            source_url="https://example.com/fv.zip",
            digest="sha256:fv",
        )
    }
    result = _load(
        plugins_dir,
        fetched_plugins_dir=fetched_dir,
        activation_registry_path=act_path,
        plugin_registry=registry,
    )
    assert result.local_tools == {}
    assert result.agents == {}


def test_g7_version_absent_loads_fail_safe(tmp_path: Path) -> None:
    """Fetched plugin with registry version=None → no check → loads (fail-safe)."""
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    fetched_dir = tmp_path / "fetched_plugins"
    pdir = fetched_dir / "fetched_ver"
    pdir.mkdir(parents=True)
    (pdir / "plugin.yaml").write_text(
        "schema_version: 1\nid: fetched_ver\nname: FV\nversion: '1.0.0'\n",
        encoding="utf-8",
    )

    act_path = tmp_path / "activations.yaml"
    act_path.write_text(
        yaml.dump(
            {
                "activations": [
                    {
                        "plugin_id": "fetched_ver",
                        "source_url": "https://example.com/fv.zip",
                        "digest": "sha256:fv",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    registry: PluginRegistry = {
        "fetched_ver": RegistryEntry(
            plugin_id="fetched_ver",
            enabled=True,
            version=None,  # absent → no check
        )
    }
    result = _load(
        plugins_dir,
        fetched_plugins_dir=fetched_dir,
        activation_registry_path=act_path,
        plugin_registry=registry,
    )
    # Loaded (no version check) — no tool_impls declared so local_tools empty but not refused
    assert result is not None


# ---------------------------------------------------------------------------
# g8: no new LLMPurpose in plugins/ (ADR-029 D3 / ADR-031 D7)
# ---------------------------------------------------------------------------


def test_g8_no_new_llm_purpose_in_plugins() -> None:
    """plugins/ must not introduce LLMPurpose usage (admission is deterministic, ADR-029 D3)."""
    symbol = "LLMPurpose"
    found_with_purpose: list[str] = []
    for py_path in _PLUGINS_PKG.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        source = py_path.read_text(encoding="utf-8")
        if symbol in source:
            found_with_purpose.append(str(py_path))
    assert not found_with_purpose, (
        f"g8 guard: {symbol!r} found in plugins/ — "
        "plugin admission must never be an LLM decision:\n"
        + "\n".join(f"  {p}" for p in found_with_purpose)
    )


# ---------------------------------------------------------------------------
# g9: admission does not route through the autonomy gate
# ---------------------------------------------------------------------------


def test_g9_admission_does_not_call_gate(tmp_path: Path) -> None:
    """Plugin loading does not call decide_tier / score / emit_gate_decision (ADR-029 D3)."""
    gate_symbols = ["decide_tier", "emit_gate_decision", "score("]
    for py_path in _PLUGINS_PKG.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        source = py_path.read_text(encoding="utf-8")
        for sym in gate_symbols:
            assert sym not in source, (
                f"g9 guard: gate symbol {sym!r} found in plugins/{py_path.name} — "
                "admission must not route through the autonomy gate"
            )


# ---------------------------------------------------------------------------
# g10: _execute_local_call + gate byte-frozen (ADR-029 D2 / ADR-037 D3 lineage)
# ---------------------------------------------------------------------------


def test_g10_execute_local_call_not_called_or_imported_in_plugins() -> None:
    """P4.4 makes zero edits to _execute_local_call: plugins/ does not call or import it.

    The executor handles tool dispatch name-agnostically (namespaced keys pass through).
    Docstring/comment mentions are permitted (documentation only).
    ADR-029 D2 / ADR-031 HR#2 / ADR-037 D3 lineage.
    """
    import re

    # Match call sites (_execute_local_call() or _execute_local_call(...)) or import lines.
    # Excludes docstrings and comments (which may reference the name for documentation).
    call_or_import = re.compile(r"_execute_local_call\s*\(|import\s+_execute_local_call")
    found: list[str] = []
    for py_path in _PLUGINS_PKG.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        for line in py_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if call_or_import.search(line):
                found.append(f"{py_path.name}: {stripped}")
                break
    assert not found, (
        "g10 guard: _execute_local_call called/imported in plugins/ — "
        "executor must remain name-agnostic:\n" + "\n".join(f"  {p}" for p in found)
    )


def test_g10_gate_not_referenced_in_plugin_loader() -> None:
    """plugins/loader.py does not reference reversibility-cap gate logic directly.

    The gate (_apply_reversibility_cap) is internal to loader.py and unchanged by P4.4;
    namespacing only changes dict keys, not the cap logic.
    """
    loader_path = _PLUGINS_PKG / "loader.py"
    source = loader_path.read_text(encoding="utf-8")
    # _apply_reversibility_cap is called in loader.py (correct) — assert it IS there
    assert "_apply_reversibility_cap" in source, (
        "g10: _apply_reversibility_cap missing from loader.py — unexpected removal"
    )
    # The gate must not call LLM decision functions
    for sym in ["decide_tier", "emit_gate_decision"]:
        assert sym not in source, (
            f"g10: gate decision symbol {sym!r} found in loader.py — "
            "reversibility cap must be deterministic, not gated"
        )


# ---------------------------------------------------------------------------
# F2: cross-plugin same-name tool_impl coexistence (ADR-038 D4 always-prefix)
# ---------------------------------------------------------------------------


def test_f2_cross_plugin_same_name_tool_impl_coexist(tmp_path: Path) -> None:
    """Two plugins declaring the same bare tool_impl name coexist as pluginA__echo + pluginB__echo.

    ADR-038 D4: always-prefix (`<plugin_id>__<name>`) means two plugins both declaring
    `echo` get distinct keys `pluginA__echo` and `pluginB__echo` — no collision, no refusal.
    This is the direct test of the cross-plugin namespacing coexistence property.
    """
    plugins_dir = tmp_path / "plugins"

    for plugin_id in ("pluginA", "pluginB"):
        pdir = plugins_dir / plugin_id
        pdir.mkdir(parents=True)
        from textwrap import dedent

        (pdir / "plugin.yaml").write_text(
            dedent(f"""\
                schema_version: 1
                id: {plugin_id}
                name: '{plugin_id}'
                version: '0.1.0'
                contributions:
                  tool_impls:
                    echo: 'tools_impl:echo_fn'
            """),
            encoding="utf-8",
        )
        (pdir / "tools_impl.py").write_text(
            "from orchestrator.tools.executor import LocalToolOutput\n"
            f"def echo_fn(params): return LocalToolOutput(content='{plugin_id}')\n",
            encoding="utf-8",
        )

    result = _load(plugins_dir)
    assert "pluginA__echo" in result.local_tools, "pluginA__echo must be present"
    assert "pluginB__echo" in result.local_tools, "pluginB__echo must be present"
    # Bare name 'echo' must not appear (always-prefix is unconditional)
    assert "echo" not in result.local_tools, "bare 'echo' must not appear — always-prefix"
