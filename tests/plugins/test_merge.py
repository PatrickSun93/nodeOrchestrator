"""P3.5-8 §1/§3: Atomic merge + multi-plugin isolation tests (ADR-029 D2 step 7 / R0-B Y4).

Covers:
- Two valid plugins load and merge (no cross-plugin collision).
- A plugin failing mid-load leaves NO trace in host registries (atomic merge).
- A valid sibling plugin loads even when another plugin fails (per-plugin isolation).
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from orchestrator.autonomy.scoring import ToolMeta
from orchestrator.llm.router import ModelRegistry
from orchestrator.llm.types import ModelId, ModelProfile, ProviderId
from orchestrator.plugins.loader import load_plugins
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


def _minimal_plugin(plugins_dir: Path, plugin_id: str, skill_id: str) -> None:
    pdir = plugins_dir / plugin_id
    (pdir / "skills").mkdir(parents=True)
    (pdir / "plugin.yaml").write_text(
        f"schema_version: 1\nid: {plugin_id}\nname: 'p'\nversion: '0.1.0'\n"
        f"contributions:\n  skills: ['{skill_id}']\n",
        encoding="utf-8",
    )
    (pdir / "skills" / f"{skill_id}.md").write_text(
        _SKILL_MD.format(stem=skill_id), encoding="utf-8"
    )


def _call(
    plugins_dir: Path,
    *,
    host_tools: dict[str, ToolMeta] | None = None,
    host_local_tool_names: frozenset[str] | None = None,
    host_mcp_server_names: frozenset[str] | None = None,
) -> None:
    return load_plugins(  # type: ignore[return-value]
        plugins_dir,
        models=_MODELS,
        host_room_types=_HOST_ROOM_TYPES,
        host_contract_version=PLUGIN_HOST_CONTRACT_VERSION,
        host_agents={},
        host_skills={},
        host_tools=host_tools or {},
        host_local_tool_names=host_local_tool_names or frozenset(),
        host_mcp_server_names=host_mcp_server_names or frozenset(),
    )


# ---------------------------------------------------------------------------
# Two valid plugins merge
# ---------------------------------------------------------------------------


def test_two_plugins_merge_without_collision(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    _minimal_plugin(plugins_dir, "plugin_a", "skill_a")
    _minimal_plugin(plugins_dir, "plugin_b", "skill_b")

    result = load_plugins(
        plugins_dir,
        models=_MODELS,
        host_room_types=_HOST_ROOM_TYPES,
        host_contract_version=PLUGIN_HOST_CONTRACT_VERSION,
        host_agents={},
        host_skills={},
        host_tools={},
        host_local_tool_names=frozenset(),
        host_mcp_server_names=frozenset(),
    )
    assert "skill_a" in result.skills
    assert "skill_b" in result.skills


# ---------------------------------------------------------------------------
# Atomic merge: failed plugin leaves no trace (HR#5 / R0-B Y4)
# ---------------------------------------------------------------------------


def test_partial_plugin_leaves_no_trace(tmp_path: Path) -> None:
    """Non-code surfaces load but code-load failure leaves zero trace (HR#5 / Y4 atomicity).

    bad_tool is in tool_impls only (NOT in contributions.tools or host_tools) — the
    collision-check passes, non-code surfaces (bad_role agent) load into the per-plugin
    intermediate, then code-load fails (broken import) → PluginCodeLoadError → return None
    → entire intermediate discarded.  bad_role was loaded into the intermediate and then
    atomically discarded — this genuinely exercises the HR#5 atomicity guarantee.

    Previous version had bad_tool in contributions.tools + host_tools, causing
    collision-refusal before any non-code surface loaded — bad_role never entered the
    intermediate, so the atomicity guarantee was never exercised (short-circuit).
    """
    plugins_dir = tmp_path / "plugins"
    pdir = plugins_dir / "badcode"
    (pdir / "agents").mkdir(parents=True)
    (pdir / "plugin.yaml").write_text(
        dedent("""\
            schema_version: 1
            id: badcode
            name: 'bad'
            version: '0.1.0'
            contributions:
              roles: ['bad_role']
              tool_impls:
                bad_tool: 'tools_impl:bad_fn'
        """),
        encoding="utf-8",
    )
    # Agent file (valid) — loads into per-plugin intermediate before code-load fails
    (pdir / "agents" / "bad_role.yaml").write_text(
        dedent("""\
            id: bad_role
            role: bad_role
            persona: test
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
        """),
        encoding="utf-8",
    )
    # tools_impl.py with a broken import — triggers PluginCodeLoadError at step 5
    (pdir / "tools_impl.py").write_text(
        "import nonexistent_module_xyz_12345\ndef bad_fn(params): pass\n", encoding="utf-8"
    )

    result = load_plugins(
        plugins_dir,
        models=_MODELS,
        host_room_types=_HOST_ROOM_TYPES,
        host_contract_version=PLUGIN_HOST_CONTRACT_VERSION,
        host_agents={},
        host_skills={},
        host_tools={},
        host_local_tool_names=frozenset(),
        host_mcp_server_names=frozenset(),
    )
    # Atomic merge: the whole per-plugin intermediate is discarded on code-load failure
    # bad_role was loaded into the intermediate (step 4 succeeded) then atomically dropped
    assert "bad_role" not in result.agents
    assert "bad_tool" not in result.local_tools


# ---------------------------------------------------------------------------
# Per-plugin isolation: valid sibling survives a failing plugin
# ---------------------------------------------------------------------------


def test_valid_sibling_survives_failing_plugin(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"

    # plugin_a is valid
    _minimal_plugin(plugins_dir, "plugin_a", "skill_a")

    # plugin_b has an invalid manifest
    pdir_b = plugins_dir / "plugin_b"
    pdir_b.mkdir()
    (pdir_b / "plugin.yaml").write_text("not: valid: yaml: at: all: [[[", encoding="utf-8")

    result = load_plugins(
        plugins_dir,
        models=_MODELS,
        host_room_types=_HOST_ROOM_TYPES,
        host_contract_version=PLUGIN_HOST_CONTRACT_VERSION,
        host_agents={},
        host_skills={},
        host_tools={},
        host_local_tool_names=frozenset(),
        host_mcp_server_names=frozenset(),
    )
    # plugin_a loaded successfully despite plugin_b failing
    assert "skill_a" in result.skills
