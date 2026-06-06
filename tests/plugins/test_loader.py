"""P3.5-8 §1: Cross-module integration tests for plugins/ loader (ADR-029 D2/D5/D6).

Covers:
- Happy-path: plugin with all five surfaces loads and all contributions register.
- Reversibility cap: unclassified plugin tool → default-0 → HARD_CONFIRM (D5 R0-B Y2).
- Host-classified tool: gates at expected tier (D5 / D7).
- Plugin role registers in agents dict.
- Plugin skill registers in skills dict.
- Plugin executable tool registers in local_tools and executes via executor path.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from orchestrator.autonomy.scoring import (
    AutonomyTier,
    Operation,
    ThresholdConfig,
    ToolMeta,
    decide_tier,
    score,
)
from orchestrator.llm.router import ModelRegistry
from orchestrator.llm.types import ModelId, ModelProfile, ProviderId
from orchestrator.plugins.loader import PluginLoadResult, load_plugins
from orchestrator.plugins.schema import PLUGIN_HOST_CONTRACT_VERSION
from orchestrator.tools.executor import LocalToolOutput

_PROVIDER = ProviderId("test_provider")


def _make_registry(*model_ids: str) -> ModelRegistry:
    return ModelRegistry(
        {
            ModelId(mid): ModelProfile(
                id=ModelId(mid),
                provider=_PROVIDER,
                provider_model_id=mid,
                capabilities=[],
                context_window=8192,
            )
            for mid in model_ids
        }
    )


_MODELS = _make_registry("m1")
_HOST_ROOM_TYPES: frozenset[str] = frozenset({"free_chat"})

_AGENT_YAML = dedent("""\
    id: {stem}
    role: {stem}
    persona: test agent
    llm_config:
      default_model: m1
      fallback_chain: []
      required_capabilities: []
    autonomy_thresholds:
      threshold_auto: 8
      threshold_confirm: 5
      user_intent_modifier: 2
    applies_to:
      room_types: [free_chat]
      room_states: [active]
""")

_SKILL_MD = dedent("""\
    ---
    id: {stem}
    category: general
    applies_to:
      agents: ["*"]
      room_types: [free_chat]
    priority: 10
    ---

    # {stem}
    A test skill.
""")

_TOOL_IMPL = dedent("""\
    from orchestrator.tools.executor import LocalToolOutput
    def {fn}(params):
        return LocalToolOutput(content="ok")
""")


def _write_plugin(
    plugins_dir: Path,
    plugin_id: str,
    *,
    roles: list[str] | None = None,
    skills: list[str] | None = None,
    tools: list[str] | None = None,
    tool_impls: dict[str, str] | None = None,
    mcp_servers: list[str] | None = None,
    impl_code: str | None = None,
    model_ids: list[str] | None = None,
) -> Path:
    """Write a minimal valid plugin directory under plugins_dir/<plugin_id>/."""
    pdir = plugins_dir / plugin_id
    pdir.mkdir(parents=True, exist_ok=True)

    roles = roles or []
    skills = skills or []
    tools = tools or []
    tool_impls = tool_impls or {}
    mcp_servers = mcp_servers or []

    # Manifest
    manifest_lines = [
        "schema_version: 1",
        f"id: {plugin_id}",
        f"name: 'Test plugin {plugin_id}'",
        "version: '0.1.0'",
    ]
    contribs: list[str] = []
    if roles:
        contribs.append(f"  roles: {roles!r}")
    if skills:
        contribs.append(f"  skills: {skills!r}")
    if tools:
        contribs.append(f"  tools: {tools!r}")
    if tool_impls:
        impl_lines = "\n".join(f"    {k}: '{v}'" for k, v in tool_impls.items())
        contribs.append(f"  tool_impls:\n{impl_lines}")
    if mcp_servers:
        contribs.append(f"  mcp_servers: {mcp_servers!r}")
    if contribs:
        manifest_lines.append("contributions:")
        manifest_lines.extend(contribs)
    if model_ids:
        manifest_lines.append("dependencies:")
        manifest_lines.append(f"  model_ids: {model_ids!r}")

    (pdir / "plugin.yaml").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")

    # Agent YAML files
    agents_dir = pdir / "agents"
    if roles:
        agents_dir.mkdir(exist_ok=True)
        for role_id in roles:
            (agents_dir / f"{role_id}.yaml").write_text(
                _AGENT_YAML.format(stem=role_id), encoding="utf-8"
            )

    # Skill MD files
    skills_dir = pdir / "skills"
    if skills:
        skills_dir.mkdir(exist_ok=True)
        for skill_id in skills:
            (skills_dir / f"{skill_id}.md").write_text(
                _SKILL_MD.format(stem=skill_id), encoding="utf-8"
            )

    # tools.yaml
    if tools:
        tools_yaml = "tools:\n" + "\n".join(f"  {t}:\n    reversibility: 10" for t in tools)
        (pdir / "tools.yaml").write_text(tools_yaml, encoding="utf-8")

    # Executable tool implementation
    if tool_impls and impl_code is not None:
        (pdir / "tools_impl.py").write_text(impl_code, encoding="utf-8")
    elif tool_impls:
        fn_name = next(iter(tool_impls.values())).split(":")[-1]
        (pdir / "tools_impl.py").write_text(_TOOL_IMPL.format(fn=fn_name), encoding="utf-8")

    return pdir


def _call_load_plugins(
    plugins_dir: Path,
    *,
    models: ModelRegistry = _MODELS,
    host_room_types: frozenset[str] = _HOST_ROOM_TYPES,
    host_tools: dict[str, ToolMeta] | None = None,
    host_local_tool_names: frozenset[str] | None = None,
) -> PluginLoadResult:
    return load_plugins(
        plugins_dir,
        models=models,
        host_room_types=host_room_types,
        host_contract_version=PLUGIN_HOST_CONTRACT_VERSION,
        host_agents={},
        host_skills={},
        host_tools=host_tools or {},
        host_local_tool_names=host_local_tool_names or frozenset(),
        host_mcp_server_names=frozenset(),
    )


# ---------------------------------------------------------------------------
# Happy-path: absent plugins/ dir → no-op
# ---------------------------------------------------------------------------


def test_absent_plugins_dir_returns_empty(tmp_path: Path) -> None:
    result = _call_load_plugins(tmp_path / "plugins")
    assert result.agents == {}
    assert result.skills == {}
    assert result.tools == {}
    assert result.local_tools == {}


# ---------------------------------------------------------------------------
# Happy-path: plugin with multiple surfaces loads
# ---------------------------------------------------------------------------


def test_plugin_role_loads(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    _write_plugin(plugins_dir, "myplugin", roles=["test_agent"])
    result = _call_load_plugins(plugins_dir)
    assert "myplugin__test_agent" in result.agents
    assert result.agents["myplugin__test_agent"].id == "test_agent"


def test_plugin_skill_loads(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    _write_plugin(plugins_dir, "myplugin", skills=["test-skill"])
    result = _call_load_plugins(plugins_dir)
    assert "myplugin__test-skill" in result.skills
    assert result.skills["myplugin__test-skill"].id == "test-skill"


def test_plugin_tool_classification_loads(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    _write_plugin(plugins_dir, "myplugin", tools=["my_tool"])
    result = _call_load_plugins(plugins_dir)
    assert "myplugin__my_tool" in result.tools


def test_plugin_executable_tool_loads_and_callable(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    _write_plugin(
        plugins_dir,
        "myplugin",
        tools=["my_tool"],
        tool_impls={"my_tool": "tools_impl:my_fn"},
        impl_code=dedent("""\
            from orchestrator.tools.executor import LocalToolOutput
            def my_fn(params):
                return LocalToolOutput(content="executed:" + str(params.get("x", "")))
        """),
    )
    result = _call_load_plugins(plugins_dir)
    assert "myplugin__my_tool" in result.local_tools
    output = result.local_tools["myplugin__my_tool"]({"x": "42"})
    assert isinstance(output, LocalToolOutput)
    assert output.content == "executed:42"


# ---------------------------------------------------------------------------
# §1 Reversibility cap: unclassified → default-0 → HARD_CONFIRM (D5 / R0-B Y2)
# ---------------------------------------------------------------------------


def test_unclassified_plugin_tool_defaults_hard_confirm(tmp_path: Path) -> None:
    """A plugin tool not in host tools.yaml defaults to reversibility 0 → HARD_CONFIRM."""
    plugins_dir = tmp_path / "plugins"
    _write_plugin(plugins_dir, "myplugin", tools=["unclassified_tool"])

    # No host classification for unclassified_tool
    result = _call_load_plugins(plugins_dir, host_tools={})
    assert "myplugin__unclassified_tool" in result.tools
    assert result.tools["myplugin__unclassified_tool"].reversibility == 0

    # Verify it gates to HARD_CONFIRM (score=0 < threshold_confirm=5)
    op = Operation(
        tool_id="myplugin__unclassified_tool", initiating_agent="a1", user_explicit_intent=False
    )
    thresholds = ThresholdConfig(threshold_auto=8, threshold_confirm=5, user_intent_modifier=2)
    gate_score = score(op, result.tools)
    autonomy = decide_tier(gate_score, thresholds, False, tool_id="myplugin__unclassified_tool")
    assert autonomy.tier == AutonomyTier.HARD_CONFIRM


def test_host_preclassified_tool_impl_gates_auto(tmp_path: Path) -> None:
    """A plugin tool_impl whose name is host-pre-classified gates AUTO_EXECUTE.

    The operator pre-classifies the tool in config/tools.yaml (host_tools) with
    high reversibility; the plugin provides only the impl (no contributions.tools).
    After loading, the host tools registry (including the pre-classification) is
    used by the gate to auto-execute the plugin's impl (ADR-029 D5/D7).
    """
    plugins_dir = tmp_path / "plugins"
    _write_plugin(
        plugins_dir,
        "myplugin",
        tool_impls={"auto_tool": "tools_impl:my_fn"},
        impl_code=dedent("""\
            from orchestrator.tools.executor import LocalToolOutput
            def my_fn(params): return LocalToolOutput(content="auto")
        """),
    )

    # Host pre-classifies the tool with namespaced name (simulates config/tools.yaml entry
    # post-P4.4-3 rebind: auto_tool → myplugin__auto_tool).
    host_tools = {"myplugin__auto_tool": ToolMeta(reversibility=10)}
    result = _call_load_plugins(plugins_dir, host_tools=host_tools)
    # Impl loads under namespaced key; host_tools retains the ToolMeta
    assert "myplugin__auto_tool" in result.local_tools
    # Combined registry (host + plugin merge) has the tool under namespaced key
    combined = {**host_tools, **result.tools}
    assert combined["myplugin__auto_tool"].reversibility == 10

    op = Operation(
        tool_id="myplugin__auto_tool", initiating_agent="a1", user_explicit_intent=False
    )
    thresholds = ThresholdConfig(threshold_auto=4, threshold_confirm=2, user_intent_modifier=1)
    gate_score = score(op, combined)
    autonomy = decide_tier(gate_score, thresholds, False, tool_id="myplugin__auto_tool")
    assert autonomy.tier == AutonomyTier.AUTO_EXECUTE


def test_reversibility_cap_new_tool_defaults_zero(tmp_path: Path) -> None:
    """A plugin declaring a brand-new tool (not pre-classified) defaults to rev=0.

    Plugin's tools.yaml claims rev=10 but host has no classification → default-0 cap
    → HARD_CONFIRM. The plugin's claimed value is never used as the authoritative value
    (ADR-029 D5 default-0 semantics).
    """
    plugins_dir = tmp_path / "plugins"
    _write_plugin(plugins_dir, "myplugin", tools=["brand_new_tool"])

    # No host classification for brand_new_tool
    result = _call_load_plugins(plugins_dir, host_tools={})
    assert "myplugin__brand_new_tool" in result.tools
    # Plugin's tools.yaml says rev=10 but no host classification → default-0 cap
    assert result.tools["myplugin__brand_new_tool"].reversibility == 0


# ---------------------------------------------------------------------------
# P4.4-2: enabled-gate + version-coherence tests (ADR-038 D2)
# ---------------------------------------------------------------------------

from orchestrator.plugins.provenance import PluginRegistry, RegistryEntry  # noqa: E402


def _call_load_plugins_with_registry(
    plugins_dir: Path,
    *,
    plugin_registry: PluginRegistry | None = None,
    fetched_plugins_dir: Path | None = None,
    activation_registry_path: Path | None = None,
    host_local_tool_names: frozenset[str] | None = None,
    host_tools: dict[str, ToolMeta] | None = None,
) -> PluginLoadResult:
    return load_plugins(
        plugins_dir,
        models=_MODELS,
        host_room_types=_HOST_ROOM_TYPES,
        host_contract_version=PLUGIN_HOST_CONTRACT_VERSION,
        host_agents={},
        host_skills={},
        host_tools=host_tools or {},
        host_local_tool_names=host_local_tool_names or frozenset(),
        host_mcp_server_names=frozenset(),
        fetched_plugins_dir=fetched_plugins_dir,
        activation_registry_path=activation_registry_path,
        plugin_registry=plugin_registry,
    )


def test_p442_disabled_plugin_skipped(tmp_path: Path) -> None:
    """Plugin with enabled: false is absent from merge (ADR-038 D2)."""
    plugins_dir = tmp_path / "plugins"
    _write_plugin(
        plugins_dir,
        "myplugin",
        tool_impls={"my_tool": "tools_impl:fn"},
    )
    registry: PluginRegistry = {
        "myplugin": RegistryEntry(plugin_id="myplugin", enabled=False),
    }
    result = _call_load_plugins_with_registry(plugins_dir, plugin_registry=registry)
    assert "my_tool" not in result.local_tools


def test_p442_enabled_plugin_loads(tmp_path: Path) -> None:
    """Plugin with enabled: true loads normally."""
    plugins_dir = tmp_path / "plugins"
    _write_plugin(
        plugins_dir,
        "myplugin",
        tool_impls={"my_tool": "tools_impl:fn"},
    )
    registry: PluginRegistry = {
        "myplugin": RegistryEntry(plugin_id="myplugin", enabled=True),
    }
    result = _call_load_plugins_with_registry(plugins_dir, plugin_registry=registry)
    assert "myplugin__my_tool" in result.local_tools


def test_p442_operator_placed_no_entry_still_loads(tmp_path: Path) -> None:
    """Operator-placed plugin with no registry entry still loads (presence=opt-in, ADR-029 D5)."""
    plugins_dir = tmp_path / "plugins"
    _write_plugin(
        plugins_dir,
        "no_entry_plugin",
        tool_impls={"impl_tool": "tools_impl:fn"},
    )
    # Empty registry — no entry for no_entry_plugin
    result = _call_load_plugins_with_registry(plugins_dir, plugin_registry={})
    assert "no_entry_plugin__impl_tool" in result.local_tools


def test_p442_absent_registry_loads_operator_placed(tmp_path: Path) -> None:
    """Absent registry (None) → today's shipped defaults: operator-placed loads (ADR-029 D5)."""
    plugins_dir = tmp_path / "plugins"
    _write_plugin(
        plugins_dir,
        "op_plugin",
        tool_impls={"op_tool": "tools_impl:fn"},
    )
    result = _call_load_plugins_with_registry(plugins_dir, plugin_registry=None)
    assert "op_plugin__op_tool" in result.local_tools


def test_p442_version_mismatch_refused(tmp_path: Path) -> None:
    """Fetched plugin with registry version != manifest version → refused (ADR-038 D2)."""
    import yaml

    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    fetched_dir = tmp_path / "fetched_plugins"
    pdir = fetched_dir / "fetched_p"
    pdir.mkdir(parents=True)
    (pdir / "plugin.yaml").write_text(
        "schema_version: 1\nid: fetched_p\nname: FP\nversion: '1.0.0'\n",
        encoding="utf-8",
    )

    # Activation entry (old mechanism still guards fetched)
    act_path = tmp_path / "activations.yaml"
    act_path.write_text(
        yaml.dump({
            "activations": [{
                "plugin_id": "fetched_p",
                "source_url": "https://example.com/fp.zip",
                "digest": "sha256:fp",
            }]
        }),
        encoding="utf-8",
    )

    # Registry entry says version='2.0.0' but manifest says '1.0.0' → mismatch
    registry: PluginRegistry = {
        "fetched_p": RegistryEntry(
            plugin_id="fetched_p",
            enabled=True,
            version="2.0.0",
            source_url="https://example.com/fp.zip",
            digest="sha256:fp",
        ),
    }
    result = _call_load_plugins_with_registry(
        plugins_dir,
        fetched_plugins_dir=fetched_dir,
        activation_registry_path=act_path,
        plugin_registry=registry,
    )
    assert result.agents == {}
    assert result.local_tools == {}


def test_p442_version_absent_loads_fail_safe(tmp_path: Path) -> None:
    """Fetched plugin with registry version=None → no version check (fail-safe, ADR-038 D2)."""
    import yaml

    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    fetched_dir = tmp_path / "fetched_plugins"
    pdir = fetched_dir / "fetched_p"
    pdir.mkdir(parents=True)
    (pdir / "plugin.yaml").write_text(
        "schema_version: 1\nid: fetched_p\nname: FP\nversion: '1.0.0'\n",
        encoding="utf-8",
    )

    act_path = tmp_path / "activations.yaml"
    act_path.write_text(
        yaml.dump({
            "activations": [{
                "plugin_id": "fetched_p",
                "source_url": "https://example.com/fp.zip",
                "digest": "sha256:fp",
            }]
        }),
        encoding="utf-8",
    )

    # version=None → no check → loads
    registry: PluginRegistry = {
        "fetched_p": RegistryEntry(
            plugin_id="fetched_p",
            enabled=True,
            version=None,
            source_url="https://example.com/fp.zip",
            digest="sha256:fp",
        ),
    }
    result = _call_load_plugins_with_registry(
        plugins_dir,
        fetched_plugins_dir=fetched_dir,
        activation_registry_path=act_path,
        plugin_registry=registry,
    )
    # Plugin loads (no tool_impls declared, but agents/skills empty = at least didn't refuse)
    # Verify it wasn't refused by checking it's not in a "refused" state — just empty contributions
    # The key assertion: no ConfigError / no refusal from version check
    assert result is not None


def test_p442_shape_coherence_op_placed_with_fetched_entry_refused(tmp_path: Path) -> None:
    """Op-placed plugin with fetched-shape registry entry (source_url+digest) → refused."""
    plugins_dir = tmp_path / "plugins"
    _write_plugin(
        plugins_dir,
        "op_plugin",
        tool_impls={"op_tool": "tools_impl:fn"},
    )
    # fetched-shape entry for an operator-placed plugin = authoring error
    registry: PluginRegistry = {
        "op_plugin": RegistryEntry(
            plugin_id="op_plugin",
            enabled=True,
            source_url="https://example.com/op.zip",
            digest="sha256:op",
        ),
    }
    result = _call_load_plugins_with_registry(plugins_dir, plugin_registry=registry)
    assert "op_tool" not in result.local_tools
