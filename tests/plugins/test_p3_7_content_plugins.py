"""Discriminating tests for P3.7-content new local plugins (P3.7-content-10..11).

Per plan §2 Common acceptance bar (mirror test_merge.py + test_failure_modes.py):
  - plugin loads + merges (contributed role/skill/tool/server in merged registries)
  - host-pre-classified tool gates to expected tier (AUTO_EXECUTE)
  - plugin-classify-only tool caps to rev 0 / HARD_CONFIRM (ADR-029 D5)
  - ≥1 fail-closed path per bundle (bad-manifest or name-collision → refused, host unchanged)
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from orchestrator.autonomy.scoring import AutonomyTier, ThresholdConfig, ToolMeta
from orchestrator.llm.router import ModelRegistry
from orchestrator.llm.types import (
    Capability,
    ModelId,
    ModelProfile,
    ProviderId,
)
from orchestrator.plugins.loader import PluginLoadResult, load_plugins
from orchestrator.plugins.schema import PLUGIN_HOST_CONTRACT_VERSION

_PROVIDER = ProviderId("test_provider")

_CAPS: dict[str, list[Capability]] = {
    "claude_code_haiku_45": [],
    "deepseek_v4_flash": [Capability.TOOLS],
}

_MODELS = ModelRegistry(
    {
        ModelId(mid): ModelProfile(
            id=ModelId(mid),
            provider=_PROVIDER,
            provider_model_id=mid,
            capabilities=_CAPS.get(mid, []),
            context_window=8192,
        )
        for mid in _CAPS
    }
)

_HOST_ROOM_TYPES: frozenset[str] = frozenset({"research", "free_chat"})

_PLUGINS_DIR = Path(__file__).parent.parent.parent / "plugins"

_THRESHOLDS = ThresholdConfig(threshold_auto=4, threshold_confirm=2, user_intent_modifier=0)


def _load_all_plugins(
    host_tools: dict[str, ToolMeta] | None = None,
    host_local_tool_names: frozenset[str] | None = None,
    host_mcp_server_names: frozenset[str] | None = None,
) -> PluginLoadResult:
    return load_plugins(
        _PLUGINS_DIR,
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
# P3.7-content-10: context plugin bundle (role + skill + tool)
# ---------------------------------------------------------------------------


class TestContextPlugin:
    """Discriminating tests for the context plugin bundle (P3.7-content-10)."""

    def test_context_plugin_agent_loads(self) -> None:
        """context plugin contributes context_analyst agent under namespaced key."""
        result = _load_all_plugins(
            host_tools={"context__context_summary": ToolMeta(reversibility=10)},
        )
        assert "context__context_analyst" in result.agents

    def test_context_plugin_skill_loads(self) -> None:
        """context plugin contributes context-tracking skill under namespaced key."""
        result = _load_all_plugins(
            host_tools={"context__context_summary": ToolMeta(reversibility=10)},
        )
        assert "context__context-tracking" in result.skills

    def test_context_plugin_tool_impl_loads(self) -> None:
        """context plugin contributes context__context_summary tool_impl (P4.4-3 rebind)."""
        result = _load_all_plugins(
            host_tools={"context__context_summary": ToolMeta(reversibility=10)},
        )
        assert "context__context_summary" in result.local_tools

    def test_host_preclassified_tool_auto_execute(self) -> None:
        """context__context_summary (host-pre-classify rev=10) gates AUTO_EXECUTE (ADR-038 D4)."""
        from orchestrator.autonomy.scoring import Operation, decide_tier, score

        result = _load_all_plugins(
            host_tools={"context__context_summary": ToolMeta(reversibility=10)},
        )
        # Build combined registry: host classification takes precedence
        host_tools = {"context__context_summary": ToolMeta(reversibility=10)}
        combined = {**host_tools, **result.tools}
        op = Operation(
            tool_id="context__context_summary", initiating_agent="a1", user_explicit_intent=False
        )
        gate_score = score(op, combined)
        autonomy = decide_tier(gate_score, _THRESHOLDS, False, tool_id="context__context_summary")
        assert autonomy.tier == AutonomyTier.AUTO_EXECUTE

    def test_plugin_classify_only_tool_caps_to_hard_confirm(self) -> None:
        """context__annotate_context (plugin-classify only) caps to rev 0 → HARD_CONFIRM."""
        from orchestrator.autonomy.scoring import Operation, decide_tier, score

        result = _load_all_plugins()
        assert "context__annotate_context" in result.tools
        # Plugin declared rev=4 but no host classification → capped to 0
        assert result.tools["context__annotate_context"].reversibility == 0
        op = Operation(
            tool_id="context__annotate_context", initiating_agent="a1", user_explicit_intent=False
        )
        gate_score = score(op, result.tools)
        autonomy = decide_tier(gate_score, _THRESHOLDS, False, tool_id="context__annotate_context")
        assert autonomy.tier == AutonomyTier.HARD_CONFIRM

    def test_context_plugin_fail_closed_bad_manifest(self, tmp_path: Path) -> None:
        """Bad manifest → refused, host unchanged (fail-closed, HR#5)."""
        plugins_dir = tmp_path / "plugins"
        pdir = plugins_dir / "bad_context"
        pdir.mkdir(parents=True)
        (pdir / "plugin.yaml").write_text("not: valid: yaml: at: all: [[[", encoding="utf-8")

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
        # No contributions from the bad plugin; host unchanged
        assert "context_analyst" not in result.agents
        assert result.agents == {}


# ---------------------------------------------------------------------------
# P3.7-content-11: insights plugin bundle (mcp_servers + skill)
# ---------------------------------------------------------------------------


class TestInsightsPlugin:
    """Discriminating tests for the insights plugin bundle (P3.7-content-11)."""

    def test_insights_plugin_skill_loads(self) -> None:
        """insights plugin contributes insights-synthesis skill under namespaced key."""
        result = _load_all_plugins()
        assert "insights__insights-synthesis" in result.skills

    def test_insights_plugin_mcp_server_declared_in_manifest(self) -> None:
        """insights plugin manifest declares insights_db as an mcp_server contribution."""
        import yaml

        manifest_path = Path(__file__).parent.parent.parent / "plugins" / "insights" / "plugin.yaml"
        manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        assert "insights_db" in manifest_data["contributions"]["mcp_servers"]

    def test_insights_plugin_mcp_servers_yaml_validates(self) -> None:
        """insights/mcp_servers.yaml validates against frozen MCPServerConfig schema."""
        from orchestrator.mcp.config import load_mcp_servers_config

        mcp_path = Path(__file__).parent.parent.parent / "plugins" / "insights" / "mcp_servers.yaml"
        cfg = load_mcp_servers_config(mcp_path)
        assert "insights_db" in cfg.servers
        assert cfg.servers["insights_db"].tools["query_insights"].reversibility == 10

    def test_insights_plugin_fail_closed_name_collision(self, tmp_path: Path) -> None:
        """MCP server name collision with host → refused, host unchanged (HR#5)."""
        plugins_dir = tmp_path / "plugins"
        pdir = plugins_dir / "mcpcoll"
        pdir.mkdir(parents=True)
        (pdir / "plugin.yaml").write_text(
            dedent("""\
                schema_version: 1
                id: mcpcoll
                name: 'collision test'
                version: '0.1.0'
                contributions:
                  mcp_servers: ['insights_db']
            """),
            encoding="utf-8",
        )

        # Host already owns insights_db → plugin refused
        result = load_plugins(
            plugins_dir,
            models=_MODELS,
            host_room_types=_HOST_ROOM_TYPES,
            host_contract_version=PLUGIN_HOST_CONTRACT_VERSION,
            host_agents={},
            host_skills={},
            host_tools={},
            host_local_tool_names=frozenset(),
            host_mcp_server_names=frozenset({"insights_db"}),
        )
        # Plugin refused due to collision; no MCP sessions contributed
        assert result.mcp_sessions == {}
