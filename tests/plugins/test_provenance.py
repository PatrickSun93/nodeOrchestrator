"""Provenance-by-origin + activation allowlist tests (ADR-031 D3/D4; P3.7-remote-6).

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
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from orchestrator.llm.router import ModelRegistry
from orchestrator.llm.types import ModelId, ModelProfile, ProviderId
from orchestrator.plugins.loader import PluginLoadResult, load_plugins
from orchestrator.plugins.provenance import (
    ActivationEntry,
    load_activation_registry,
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
    assert "echo_tool" in result.local_tools


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
    assert "echo_tool" in result.local_tools


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
    assert "echo_tool" in result.local_tools
    fn = result.local_tools["echo_tool"]
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
    fn = result.local_tools["echo_tool"]
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
    fn = result.local_tools["echo_tool"]
    # The _PostureBFn should have the activation's plugin_subprocess_env
    assert getattr(fn, "_plugin_subprocess_env", None) == {"CUSTOM_KEY": "custom_value"}


def test_pv8_operator_placed_uses_posture_a(tmp_path: Path) -> None:
    """Operator-placed plugin uses Posture A (in-process); no subprocess env."""
    plugins_dir = tmp_path / "plugins"
    _minimal_plugin(plugins_dir, "clean_plugin", with_tool_impl=True)

    result = _load(plugins_dir)
    fn = result.local_tools["echo_tool"]
    # Posture A: not a subprocess fn, so no subprocess env attribute
    assert not bool(getattr(fn, "_is_posture_b_subprocess", False))
    assert getattr(fn, "_plugin_subprocess_env", None) is None
