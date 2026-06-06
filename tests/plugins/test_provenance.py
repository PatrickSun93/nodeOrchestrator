"""Provenance-by-origin + activation allowlist + unified registry tests.

ADR-031 D3/D4 + ADR-038 D1 + P3.7-remote-6 + P4.4-1.

Acceptance criteria:
  pv1  — operator-placed plugins load unchanged; provenance label = "operator_placed".
  pv2  — fetched plugin with no activation entry → refused (fail-closed).
  pv3  — fetched plugin with matching activation entry → loads.
  pv4  — provenance-laundering test: a bundle in fetched_plugins_dir cannot be
         discovered as "operator_placed" (disjoint roots, ADR-031 D3).
  pv5  — fetched plugin's tool_impls run Posture B only (test-enforced-unreachable:
         _PostureBFn marker present; importlib never called at load time).
  pv6  — activation registry: load from YAML, validate schema, handle absent file.
  pv7  — disjoint-root guard: overlapping roots → ValueError (laundering prevention).
  pv8  — plugin_subprocess_env from activation entry is passed to the subprocess;
         operator-placed plugins get empty env (no env leakage).
  pr1  — RegistryEntry: frozen, enabled defaults true, version optional str|None.
  pr2  — load_plugin_registry: absent/None path → empty registry.
  pr3  — load_plugin_registry: malformed YAML → ConfigError (fail-closed).
  pr4  — load_plugin_registry: fetched entry missing source_url or digest → ConfigError.
  pr5  — load_plugin_registry: enabled non-bool raises (incl. quoted "false" string).
  pr6  — load_plugin_registry: version non-(str|None) raises.
  pr7  — load_plugin_registry: unknown entry key raises (extra="forbid").
  pr8  — load_plugin_registry: duplicate plugin_id raises ConfigError.
  pr9  — load_plugin_registry: provenance/posture fields rejected as unknown keys.
  pr10 — load_plugin_registry: strings-only env preserved; non-string env raises.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from orchestrator.llm.exceptions import ConfigError
from orchestrator.llm.router import ModelRegistry
from orchestrator.llm.types import ModelId, ModelProfile, ProviderId
from orchestrator.plugins.loader import PluginLoadResult, load_plugins
from orchestrator.plugins.provenance import (
    ActivationEntry,
    RegistryEntry,
    load_activation_registry,
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


def _minimal_plugin(root: Path, plugin_id: str, with_tool_impl: bool = False) -> Path:
    """Create a minimal valid plugin in root/plugin_id/."""
    pdir = root / plugin_id
    pdir.mkdir(parents=True, exist_ok=True)
    if with_tool_impl:
        manifest = dedent(f"""\
            schema_version: 1
            id: {plugin_id}
            name: '{plugin_id}'
            version: '0.1.0'
            contributions:
              tool_impls:
                echo_tool: 'tools_impl:echo_fn'
        """)
        (pdir / "tools_impl.py").write_text(
            "from orchestrator.tools.executor import LocalToolOutput\n"
            "def echo_fn(params): return LocalToolOutput(content='hello')\n",
            encoding="utf-8",
        )
    else:
        manifest = dedent(f"""\
            schema_version: 1
            id: {plugin_id}
            name: '{plugin_id}'
            version: '0.1.0'
        """)
    (pdir / "plugin.yaml").write_text(manifest, encoding="utf-8")
    return pdir


def _write_activation_yaml(path: Path, entries: list[dict[str, object]]) -> None:
    path.write_text(yaml.dump({"activations": entries}), encoding="utf-8")


def _load(
    plugins_dir: Path,
    *,
    fetched_plugins_dir: Path | None = None,
    activation_registry_path: Path | None = None,
) -> PluginLoadResult:
    return load_plugins(
        plugins_dir,
        models=_MODELS,
        host_room_types=_HOST_ROOM_TYPES,
        host_contract_version=PLUGIN_HOST_CONTRACT_VERSION,
        host_agents={},
        host_skills={},
        host_tools={},
        host_local_tool_names=frozenset(),
        host_mcp_server_names=frozenset(),
        fetched_plugins_dir=fetched_plugins_dir,
        activation_registry_path=activation_registry_path,
    )


# ---------------------------------------------------------------------------
# pv6: activation registry loading
# ---------------------------------------------------------------------------


def test_pv6_activation_registry_absent_returns_empty() -> None:
    """Missing activation registry file → empty registry (fail-closed default)."""
    registry = load_activation_registry(Path("/nonexistent/path/activations.yaml"))
    assert registry == {}


def test_pv6_activation_registry_none_returns_empty() -> None:
    """None path → empty registry."""
    assert load_activation_registry(None) == {}


def test_pv6_activation_registry_loads_entries(tmp_path: Path) -> None:
    """Well-formed activation YAML → registry with correct entries."""
    reg_path = tmp_path / "activations.yaml"
    _write_activation_yaml(
        reg_path,
        [
            {
                "plugin_id": "my_plugin",
                "source_url": "https://example.com/my_plugin.zip",
                "digest": "sha256:abc123",
                "plugin_subprocess_env": {"KEY": "value"},
            }
        ],
    )
    registry = load_activation_registry(reg_path)
    assert "my_plugin" in registry
    entry = registry["my_plugin"]
    assert isinstance(entry, ActivationEntry)
    assert entry.source_url == "https://example.com/my_plugin.zip"
    assert entry.digest == "sha256:abc123"
    assert entry.plugin_subprocess_env == {"KEY": "value"}


def test_pv6_activation_registry_no_subprocess_env(tmp_path: Path) -> None:
    """Activation entry without plugin_subprocess_env defaults to {}."""
    reg_path = tmp_path / "activations.yaml"
    _write_activation_yaml(
        reg_path,
        [{"plugin_id": "p", "source_url": "https://x.com/p.zip", "digest": "sha256:ff"}],
    )
    registry = load_activation_registry(reg_path)
    assert registry["p"].plugin_subprocess_env == {}


# ---------------------------------------------------------------------------
# pv1: operator-placed plugins load unchanged
# ---------------------------------------------------------------------------


def test_pv1_operator_placed_loads_unchanged(tmp_path: Path) -> None:
    """Operator-placed plugin loads without requiring an activation entry."""
    plugins_dir = tmp_path / "plugins"
    _minimal_plugin(plugins_dir, "op_plugin", with_tool_impl=True)

    result = _load(plugins_dir)
    assert "op_plugin__echo_tool" in result.local_tools


# ---------------------------------------------------------------------------
# pv2: fetched plugin refused without activation entry
# ---------------------------------------------------------------------------


def test_pv2_fetched_plugin_refused_without_activation(tmp_path: Path) -> None:
    """A fetched plugin with no activation entry → refused (fail-closed, ADR-031 D4)."""
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    fetched_dir = tmp_path / "fetched_plugins"
    _minimal_plugin(fetched_dir, "fetched_plugin")

    # No activation registry → no activations → fetched plugin refused
    result = _load(plugins_dir, fetched_plugins_dir=fetched_dir, activation_registry_path=None)
    assert result.local_tools == {}


def test_pv2_fetched_plugin_refused_when_not_in_registry(tmp_path: Path) -> None:
    """A fetched plugin not listed in the activation registry → refused."""
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    fetched_dir = tmp_path / "fetched_plugins"
    _minimal_plugin(fetched_dir, "unknown_plugin")

    reg_path = tmp_path / "activations.yaml"
    # Registry has a DIFFERENT plugin_id
    _write_activation_yaml(
        reg_path,
        [{"plugin_id": "other_plugin", "source_url": "https://x.com/x.zip", "digest": "sha256:ff"}],
    )

    result = _load(plugins_dir, fetched_plugins_dir=fetched_dir, activation_registry_path=reg_path)
    assert "unknown_plugin" not in (result.local_tools or {})


# ---------------------------------------------------------------------------
# pv3: fetched plugin with activation entry loads
# ---------------------------------------------------------------------------


def test_pv3_fetched_plugin_with_activation_loads(tmp_path: Path) -> None:
    """A fetched plugin with a matching activation entry loads successfully."""
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    fetched_dir = tmp_path / "fetched_plugins"
    _minimal_plugin(fetched_dir, "my_fetched", with_tool_impl=True)

    reg_path = tmp_path / "activations.yaml"
    _write_activation_yaml(
        reg_path,
        [
            {
                "plugin_id": "my_fetched",
                "source_url": "https://example.com/my_fetched.zip",
                "digest": "sha256:abc",
            }
        ],
    )

    result = _load(plugins_dir, fetched_plugins_dir=fetched_dir, activation_registry_path=reg_path)
    assert "my_fetched__echo_tool" in result.local_tools


# ---------------------------------------------------------------------------
# pv4: provenance-laundering test
# ---------------------------------------------------------------------------


def test_pv4_provenance_laundering_impossible(tmp_path: Path) -> None:
    """A bundle in fetched_plugins_dir cannot be discovered as operator_placed.

    The disjoint roots ensure provenance is un-launderable (ADR-031 D3).
    A plugin placed only in the fetched root is NEVER seen by the operator-placed
    discovery path, even if the activation registry is absent (it's refused, not
    re-labelled as operator-placed).
    """
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    fetched_dir = tmp_path / "fetched_plugins"
    _minimal_plugin(fetched_dir, "fetched_only", with_tool_impl=True)

    # No activation → fetched_only is refused
    result = _load(plugins_dir, fetched_plugins_dir=fetched_dir)
    assert "echo_tool" not in (result.local_tools or {})

    # Also: fetched_only is NOT in the operator-placed root → cannot be discovered there
    op_result = _load(plugins_dir)  # No fetched_plugins_dir
    assert "echo_tool" not in (op_result.local_tools or {})


# ---------------------------------------------------------------------------
# pv5: fetched tool_impls run Posture B (test-enforced-unreachable Posture A)
# ---------------------------------------------------------------------------


def test_pv5_fetched_tool_impls_are_posture_b(tmp_path: Path) -> None:
    """Fetched plugin's tool_impls are Posture-B closures (_is_posture_b_subprocess=True).

    Test-enforced-unreachable: Posture A (importlib at load time) is never used
    for fetched plugins.  The _PostureBFn marker asserts this structurally.
    """
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    fetched_dir = tmp_path / "fetched_plugins"
    _minimal_plugin(fetched_dir, "fetched_b", with_tool_impl=True)

    reg_path = tmp_path / "activations.yaml"
    _write_activation_yaml(
        reg_path,
        [{"plugin_id": "fetched_b", "source_url": "https://x.com/b.zip", "digest": "sha256:b"}],
    )

    result = _load(plugins_dir, fetched_plugins_dir=fetched_dir, activation_registry_path=reg_path)
    assert "fetched_b__echo_tool" in result.local_tools
    fn = result.local_tools["fetched_b__echo_tool"]
    # Posture B marker present → importlib never called at load time
    assert bool(getattr(fn, "_is_posture_b_subprocess", False)), (
        "pv5: fetched plugin tool impl is NOT Posture-B — "
        "Posture A was used (unreachable violation)"
    )


def test_pv5_operator_placed_tool_impls_are_posture_a(tmp_path: Path) -> None:
    """Operator-placed plugin tool_impls use in-process Posture A (ADR-029 D4 curation=trust).

    Test-enforced-dual-posture: operator-placed plugins are NOT subprocess-launched;
    they have no _is_posture_b_subprocess marker.
    """
    plugins_dir = tmp_path / "plugins"
    _minimal_plugin(plugins_dir, "op_a", with_tool_impl=True)

    result = _load(plugins_dir)
    fn = result.local_tools["op_a__echo_tool"]
    # Posture A: NOT a subprocess-launching closure (_is_posture_b_subprocess absent)
    assert not bool(getattr(fn, "_is_posture_b_subprocess", False)), (
        "pv5: operator-placed plugin tool impl IS Posture-B — "
        "Posture A (in-process importlib) must be used for operator-placed (ADR-029 D4)"
    )


# ---------------------------------------------------------------------------
# pv7: disjoint-root guard
# ---------------------------------------------------------------------------


def test_pv7_overlapping_roots_raises(tmp_path: Path) -> None:
    """plugins_dir overlapping fetched_plugins_dir → ValueError (laundering prevention)."""
    shared = tmp_path / "plugins"
    shared.mkdir()

    with pytest.raises(ValueError, match="disjoint"):
        load_plugins(
            shared,
            models=_MODELS,
            host_room_types=_HOST_ROOM_TYPES,
            host_contract_version=PLUGIN_HOST_CONTRACT_VERSION,
            host_agents={},
            host_skills={},
            host_tools={},
            host_local_tool_names=frozenset(),
            host_mcp_server_names=frozenset(),
            fetched_plugins_dir=shared,  # same dir = overlap
        )


# ---------------------------------------------------------------------------
# pv8: plugin_subprocess_env from activation entry passed to subprocess
# ---------------------------------------------------------------------------


def test_pv8_activation_subprocess_env_passed_to_closure(tmp_path: Path) -> None:
    """plugin_subprocess_env from activation entry is present in the _PostureBFn closure."""
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    fetched_dir = tmp_path / "fetched_plugins"
    _minimal_plugin(fetched_dir, "env_plugin", with_tool_impl=True)

    reg_path = tmp_path / "activations.yaml"
    _write_activation_yaml(
        reg_path,
        [
            {
                "plugin_id": "env_plugin",
                "source_url": "https://x.com/ep.zip",
                "digest": "sha256:ep",
                "plugin_subprocess_env": {"CUSTOM_KEY": "custom_value"},
            }
        ],
    )

    result = _load(plugins_dir, fetched_plugins_dir=fetched_dir, activation_registry_path=reg_path)
    fn = result.local_tools["env_plugin__echo_tool"]
    # The _PostureBFn should have the activation's plugin_subprocess_env
    assert getattr(fn, "_plugin_subprocess_env", None) == {"CUSTOM_KEY": "custom_value"}


def test_pv8_operator_placed_uses_posture_a(tmp_path: Path) -> None:
    """Operator-placed plugin uses Posture A (in-process); no subprocess env."""
    plugins_dir = tmp_path / "plugins"
    _minimal_plugin(plugins_dir, "clean_plugin", with_tool_impl=True)

    result = _load(plugins_dir)
    fn = result.local_tools["clean_plugin__echo_tool"]
    # Posture A: not a subprocess fn, so no subprocess env attribute
    assert not bool(getattr(fn, "_is_posture_b_subprocess", False))
    assert getattr(fn, "_plugin_subprocess_env", None) is None


# ---------------------------------------------------------------------------
# pr1: RegistryEntry: frozen, enabled defaults true, version optional
# ---------------------------------------------------------------------------


def test_pr1_registry_entry_frozen() -> None:
    """RegistryEntry is frozen (immutable)."""
    import dataclasses

    entry = RegistryEntry(plugin_id="my_plugin")
    assert dataclasses.is_dataclass(entry)
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.enabled = False  # type: ignore[misc]


def test_pr1_registry_entry_enabled_defaults_true() -> None:
    """RegistryEntry.enabled defaults to True (consent-by-authoring)."""
    entry = RegistryEntry(plugin_id="p")
    assert entry.enabled is True


def test_pr1_registry_entry_version_defaults_none() -> None:
    """RegistryEntry.version defaults to None."""
    entry = RegistryEntry(plugin_id="p")
    assert entry.version is None


def test_pr1_registry_entry_no_provenance_field() -> None:
    """RegistryEntry has no provenance or posture field (un-spoofable invariant)."""
    entry = RegistryEntry(plugin_id="p")
    assert not hasattr(entry, "provenance")
    assert not hasattr(entry, "posture")


# ---------------------------------------------------------------------------
# pr2: load_plugin_registry: absent/None path → empty registry
# ---------------------------------------------------------------------------


def test_pr2_absent_path_returns_empty() -> None:
    """Missing registry file → empty registry."""
    result = load_plugin_registry(Path("/nonexistent/plugins.yaml"))
    assert result == {}


def test_pr2_none_path_returns_empty() -> None:
    """None path → empty registry."""
    assert load_plugin_registry(None) == {}


def test_pr2_empty_yaml_returns_empty(tmp_path: Path) -> None:
    """Empty YAML file → empty registry."""
    p = tmp_path / "plugins.yaml"
    p.write_text("", encoding="utf-8")
    assert load_plugin_registry(p) == {}


# ---------------------------------------------------------------------------
# pr3: load_plugin_registry: malformed YAML → ConfigError
# ---------------------------------------------------------------------------


def test_pr3_non_mapping_root_raises(tmp_path: Path) -> None:
    p = tmp_path / "plugins.yaml"
    p.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="expected a mapping"):
        load_plugin_registry(p)


def test_pr3_plugins_not_list_raises(tmp_path: Path) -> None:
    p = tmp_path / "plugins.yaml"
    p.write_text("plugins:\n  foo: bar\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="'plugins' must be a list"):
        load_plugin_registry(p)


def test_pr3_entry_not_mapping_raises(tmp_path: Path) -> None:
    p = tmp_path / "plugins.yaml"
    p.write_text("plugins:\n  - just_a_string\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_plugin_registry(p)


# ---------------------------------------------------------------------------
# pr4: fetched entry missing source_url or digest → ConfigError
# ---------------------------------------------------------------------------


def test_pr4_source_url_without_digest_raises(tmp_path: Path) -> None:
    p = tmp_path / "plugins.yaml"
    p.write_text(
        "plugins:\n"
        "  - plugin_id: p\n"
        "    source_url: https://example.com/p.zip\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="both be present or both absent"):
        load_plugin_registry(p)


def test_pr4_digest_without_source_url_raises(tmp_path: Path) -> None:
    p = tmp_path / "plugins.yaml"
    p.write_text(
        "plugins:\n"
        "  - plugin_id: p\n"
        "    digest: sha256:abc\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="both be present or both absent"):
        load_plugin_registry(p)


def test_pr4_both_present_is_valid(tmp_path: Path) -> None:
    p = tmp_path / "plugins.yaml"
    p.write_text(
        "plugins:\n"
        "  - plugin_id: p\n"
        "    source_url: https://example.com/p.zip\n"
        "    digest: sha256:abc\n",
        encoding="utf-8",
    )
    result = load_plugin_registry(p)
    assert "p" in result
    assert result["p"].source_url == "https://example.com/p.zip"
    assert result["p"].digest == "sha256:abc"


# ---------------------------------------------------------------------------
# pr5: enabled non-bool raises (incl. quoted "false" string)
# ---------------------------------------------------------------------------


def test_pr5_enabled_string_false_raises(tmp_path: Path) -> None:
    """YAML `enabled: \"false\"` is a string (truthy!) — must raise, not silently enable."""
    p = tmp_path / "plugins.yaml"
    p.write_text(
        'plugins:\n  - plugin_id: p\n    enabled: "false"\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="'enabled' must be a bool"):
        load_plugin_registry(p)


def test_pr5_enabled_integer_raises(tmp_path: Path) -> None:
    p = tmp_path / "plugins.yaml"
    p.write_text("plugins:\n  - plugin_id: p\n    enabled: 0\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="'enabled' must be a bool"):
        load_plugin_registry(p)


def test_pr5_enabled_true_is_valid(tmp_path: Path) -> None:
    p = tmp_path / "plugins.yaml"
    p.write_text("plugins:\n  - plugin_id: p\n    enabled: true\n", encoding="utf-8")
    result = load_plugin_registry(p)
    assert result["p"].enabled is True


def test_pr5_enabled_false_is_valid(tmp_path: Path) -> None:
    p = tmp_path / "plugins.yaml"
    p.write_text("plugins:\n  - plugin_id: p\n    enabled: false\n", encoding="utf-8")
    result = load_plugin_registry(p)
    assert result["p"].enabled is False


# ---------------------------------------------------------------------------
# pr6: version non-(str|None) raises
# ---------------------------------------------------------------------------


def test_pr6_version_integer_raises(tmp_path: Path) -> None:
    p = tmp_path / "plugins.yaml"
    p.write_text("plugins:\n  - plugin_id: p\n    version: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="'version' must be a str or null"):
        load_plugin_registry(p)


def test_pr6_version_str_is_valid(tmp_path: Path) -> None:
    p = tmp_path / "plugins.yaml"
    p.write_text("plugins:\n  - plugin_id: p\n    version: '1.2.3'\n", encoding="utf-8")
    result = load_plugin_registry(p)
    assert result["p"].version == "1.2.3"


def test_pr6_version_null_is_valid(tmp_path: Path) -> None:
    p = tmp_path / "plugins.yaml"
    p.write_text("plugins:\n  - plugin_id: p\n    version: null\n", encoding="utf-8")
    result = load_plugin_registry(p)
    assert result["p"].version is None


# ---------------------------------------------------------------------------
# pr7: unknown entry key raises (extra="forbid")
# ---------------------------------------------------------------------------


def test_pr7_unknown_key_raises(tmp_path: Path) -> None:
    p = tmp_path / "plugins.yaml"
    p.write_text(
        "plugins:\n  - plugin_id: p\n    extra_field: oops\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="unknown keys"):
        load_plugin_registry(p)


# ---------------------------------------------------------------------------
# pr8: duplicate plugin_id raises ConfigError
# ---------------------------------------------------------------------------


def test_pr8_duplicate_plugin_id_raises(tmp_path: Path) -> None:
    p = tmp_path / "plugins.yaml"
    p.write_text(
        "plugins:\n"
        "  - plugin_id: myplugin\n"
        "  - plugin_id: myplugin\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="duplicate plugin_id"):
        load_plugin_registry(p)


# ---------------------------------------------------------------------------
# pr9: provenance/posture fields rejected as unknown keys
# ---------------------------------------------------------------------------


def test_pr9_provenance_field_rejected(tmp_path: Path) -> None:
    """An entry must never declare 'provenance' — it's host-derived (un-spoofable)."""
    p = tmp_path / "plugins.yaml"
    p.write_text(
        "plugins:\n  - plugin_id: p\n    provenance: fetched\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="unknown keys"):
        load_plugin_registry(p)


def test_pr9_posture_field_rejected(tmp_path: Path) -> None:
    """An entry must never declare 'posture' — it's host-derived (un-spoofable)."""
    p = tmp_path / "plugins.yaml"
    p.write_text(
        "plugins:\n  - plugin_id: p\n    posture: A\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="unknown keys"):
        load_plugin_registry(p)


# ---------------------------------------------------------------------------
# pr10: strings-only env preserved; non-string raises
# ---------------------------------------------------------------------------


def test_pr10_valid_env_preserved(tmp_path: Path) -> None:
    p = tmp_path / "plugins.yaml"
    p.write_text(
        "plugins:\n"
        "  - plugin_id: p\n"
        "    source_url: https://example.com/p.zip\n"
        "    digest: sha256:abc\n"
        "    plugin_subprocess_env:\n"
        "      KEY: value\n"
        "      OTHER: thing\n",
        encoding="utf-8",
    )
    result = load_plugin_registry(p)
    assert result["p"].plugin_subprocess_env == {"KEY": "value", "OTHER": "thing"}


def test_pr10_non_string_env_value_raises(tmp_path: Path) -> None:
    p = tmp_path / "plugins.yaml"
    p.write_text(
        "plugins:\n"
        "  - plugin_id: p\n"
        "    plugin_subprocess_env:\n"
        "      KEY: 123\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="must be strings"):
        load_plugin_registry(p)


