"""Tests for config_loader: yaml load + validation."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from orchestrator.autonomy.scoring import ToolMeta
from orchestrator.llm.config_loader import (
    load_agent_llm_config,
    load_models,
    load_providers,
    load_tools_config,
    validate_full_config,
)
from orchestrator.llm.exceptions import ConfigError
from orchestrator.llm.providers.claude_code_cli import ClaudeCodeCliProvider
from orchestrator.llm.providers.mock import MockProvider
from orchestrator.llm.providers.openai_compatible import OpenAICompatibleProvider
from orchestrator.llm.router import ModelRegistry, ProviderRegistry
from orchestrator.llm.types import (
    AgentAutonomyThresholds,
    AgentLLMConfig,
    Capability,
    ModelId,
    ModelProfile,
    ProviderId,
)

# Path to the project's example configs (used by integration tests below).
EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "config"


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(dedent(content), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# load_providers
# ---------------------------------------------------------------------------


class TestLoadProviders:
    def test_load_three_provider_types(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "providers.yaml",
            """
            providers:
              cli:
                type: claude_code_cli
                params:
                  cli_path: claude
                  timeout_s: 600
              api:
                type: openai_compatible
                params:
                  base_url: https://api.example.com/v1
                  api_key_env: API_KEY
              mock_provider:
                type: mock
                params: {}
            """,
        )
        registry = load_providers(path)

        cli = registry.get(ProviderId("cli"))
        api = registry.get(ProviderId("api"))
        mock_p = registry.get(ProviderId("mock_provider"))
        assert isinstance(cli, ClaudeCodeCliProvider)
        assert isinstance(api, OpenAICompatibleProvider)
        assert isinstance(mock_p, MockProvider)
        assert api.base_url == "https://api.example.com/v1"
        assert api.api_key_env == "API_KEY"

    def test_unknown_type_raises_with_violations(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "providers.yaml",
            """
            providers:
              bad:
                type: nonexistent_type
                params: {}
            """,
        )
        with pytest.raises(ConfigError) as exc:
            load_providers(path)
        assert any("unknown type" in v for v in exc.value.violations)

    def test_missing_providers_key_raises(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "providers.yaml", "other_key: {}\n")
        with pytest.raises(ConfigError, match="missing or non-dict 'providers'"):
            load_providers(path)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="does not exist"):
            load_providers(tmp_path / "nope.yaml")

    def test_malformed_yaml_raises(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "providers.yaml", "providers:\n  - not a mapping")
        with pytest.raises(ConfigError):
            load_providers(path)

    def test_collects_multiple_violations(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "providers.yaml",
            """
            providers:
              bad1:
                type: nonexistent_a
              bad2:
                type: nonexistent_b
            """,
        )
        with pytest.raises(ConfigError) as exc:
            load_providers(path)
        assert len(exc.value.violations) == 2


# ---------------------------------------------------------------------------
# load_models
# ---------------------------------------------------------------------------


class TestLoadModels:
    def _providers(self, ids: list[str]) -> ProviderRegistry:
        return ProviderRegistry(
            {ProviderId(i): MockProvider(provider_id=ProviderId(i)) for i in ids}
        )

    def test_load_models_with_known_provider(self, tmp_path: Path) -> None:
        providers = self._providers(["api"])
        path = _write(
            tmp_path,
            "models.yaml",
            """
            models:
              ds_pro:
                provider: api
                provider_model_id: deepseek-v4-pro
                capabilities: [tools]
                context_window: 128000
            """,
        )
        registry = load_models(path, providers)
        m = registry.get(ModelId("ds_pro"))
        assert m is not None
        assert m.provider == ProviderId("api")
        assert m.capabilities == [Capability.TOOLS]

    def test_unknown_provider_reference_raises(self, tmp_path: Path) -> None:
        providers = self._providers(["api"])
        path = _write(
            tmp_path,
            "models.yaml",
            """
            models:
              orphan:
                provider: nonexistent
                provider_model_id: x
                context_window: 1000
            """,
        )
        with pytest.raises(ConfigError) as exc:
            load_models(path, providers)
        assert any("not in providers" in v for v in exc.value.violations)

    def test_default_effort_without_capability_raises(self, tmp_path: Path) -> None:
        """ModelProfile validator catches default_effort set without
        EFFORT capability."""
        providers = self._providers(["api"])
        path = _write(
            tmp_path,
            "models.yaml",
            """
            models:
              wrong:
                provider: api
                provider_model_id: x
                capabilities: []  # no effort!
                default_effort: high
                context_window: 1000
            """,
        )
        with pytest.raises(ConfigError):
            load_models(path, providers)


# ---------------------------------------------------------------------------
# load_agent_llm_config
# ---------------------------------------------------------------------------


class TestLoadAgentLLMConfig:
    def _models(self, ids: list[str]) -> ModelRegistry:
        return ModelRegistry(
            {
                ModelId(i): ModelProfile(
                    id=ModelId(i),
                    provider=ProviderId("p"),
                    provider_model_id=i,
                    context_window=1000,
                )
                for i in ids
            }
        )

    def test_load_basic_agent_config(self, tmp_path: Path) -> None:
        models = self._models(["a", "b"])
        path = _write(
            tmp_path,
            "prober.yaml",
            """
            llm_config:
              default_model: a
              fallback_chain: [b]
              temperature: 0.5
            autonomy_thresholds:
              threshold_auto: 8
              threshold_confirm: 5
              user_intent_modifier: 2
            """,
        )
        config = load_agent_llm_config(path, models)
        assert config.default_model == ModelId("a")
        assert config.fallback_chain == [ModelId("b")]
        assert config.temperature == 0.5

    def test_unknown_model_in_chain_raises(self, tmp_path: Path) -> None:
        models = self._models(["a"])
        path = _write(
            tmp_path,
            "agent.yaml",
            """
            llm_config:
              default_model: a
              fallback_chain: [ghost]
            autonomy_thresholds:
              threshold_auto: 8
              threshold_confirm: 5
              user_intent_modifier: 2
            """,
        )
        with pytest.raises(ConfigError) as exc:
            load_agent_llm_config(path, models)
        assert any("not in models registry" in v for v in exc.value.violations)

    def test_missing_llm_config_raises(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "agent.yaml", "other_key: x\n")
        with pytest.raises(ConfigError, match="missing or non-dict 'llm_config'"):
            load_agent_llm_config(path, self._models([]))

    def test_default_in_fallback_chain_raises(self, tmp_path: Path) -> None:
        """The validator added in P1.1 commit 1 review fix
        (Principle 9 — no two names for one concept)."""
        models = self._models(["a", "b"])
        path = _write(
            tmp_path,
            "bad.yaml",
            """
            llm_config:
              default_model: a
              fallback_chain: [a, b]
            autonomy_thresholds:
              threshold_auto: 8
              threshold_confirm: 5
              user_intent_modifier: 2
            """,
        )
        with pytest.raises(ConfigError):
            load_agent_llm_config(path, models)

    def test_default_at_non_zero_index_in_chain_raises(self, tmp_path: Path) -> None:
        """The validator must catch the default model even when it's not
        at index 0 — a future refactor that replaces ``in`` with ``[0] ==``
        would pass the position-0 test but fail here."""
        models = self._models(["a", "b"])
        path = _write(
            tmp_path,
            "bad.yaml",
            """
            llm_config:
              default_model: a
              fallback_chain: [b, a]
            autonomy_thresholds:
              threshold_auto: 8
              threshold_confirm: 5
              user_intent_modifier: 2
            """,
        )
        with pytest.raises(ConfigError):
            load_agent_llm_config(path, models)

    def test_default_at_last_index_in_chain_raises(self, tmp_path: Path) -> None:
        models = self._models(["a", "b", "c"])
        path = _write(
            tmp_path,
            "bad.yaml",
            """
            llm_config:
              default_model: a
              fallback_chain: [b, c, a]
            autonomy_thresholds:
              threshold_auto: 8
              threshold_confirm: 5
              user_intent_modifier: 2
            """,
        )
        with pytest.raises(ConfigError):
            load_agent_llm_config(path, models)

    def test_config_error_violations_locate_offending_yaml_field(self, tmp_path: Path) -> None:
        """ConfigError must carry enough context to locate the root cause
        from logs alone: the offending field name AND the file identifier."""
        path = _write(
            tmp_path,
            "bad.yaml",
            """
            llm_config:
              fallback_chain: [a]
            autonomy_thresholds:
              threshold_auto: 8
              threshold_confirm: 5
              user_intent_modifier: 2
            """,
        )
        with pytest.raises(ConfigError) as exc:
            load_agent_llm_config(path, self._models(["a"]))
        msg = str(exc.value)
        assert "default_model" in msg
        assert path.stem in msg


# ---------------------------------------------------------------------------
# validate_full_config
# ---------------------------------------------------------------------------


class TestValidateFullConfig:
    def _setup(
        self,
        provider_can_tools: bool = True,
    ) -> tuple[ProviderRegistry, ModelRegistry, dict[str, AgentLLMConfig]]:
        prov = MockProvider(
            provider_id=ProviderId("p"),
            can_use_tools=provider_can_tools,
        )
        providers = ProviderRegistry({ProviderId("p"): prov})
        models = ModelRegistry(
            {
                ModelId("with_tools"): ModelProfile(
                    id=ModelId("with_tools"),
                    provider=ProviderId("p"),
                    provider_model_id="x",
                    capabilities=[Capability.TOOLS],
                    context_window=1000,
                ),
            }
        )
        agents = {
            "tool_user": AgentLLMConfig(
                default_model=ModelId("with_tools"),
                fallback_chain=[],
                required_capabilities=[Capability.TOOLS],
                autonomy_thresholds=AgentAutonomyThresholds(
                    threshold_auto=8,
                    threshold_confirm=5,
                    user_intent_modifier=2,
                ),
            ),
        }
        return providers, models, agents

    def test_clean_config_passes(self) -> None:
        providers, models, agents = self._setup()
        validate_full_config(providers, models, agents)  # no raise

    def test_tools_required_but_no_tool_provider_raises(self) -> None:
        """The canonical 'operator pointed at Claude Code' bug —
        agent requires tools, but only model resolves to a provider
        that returns can_use_orchestrator_tools()=False."""
        providers, models, agents = self._setup(provider_can_tools=False)
        with pytest.raises(ConfigError) as exc:
            validate_full_config(providers, models, agents)
        assert any("tools" in v for v in exc.value.violations)
        assert any("ADR-003" in v for v in exc.value.violations)

    def test_collects_all_violations(self) -> None:
        prov = MockProvider(provider_id=ProviderId("p"))
        providers = ProviderRegistry({ProviderId("p"): prov})
        models = ModelRegistry(
            {
                ModelId("orphan"): ModelProfile(
                    id=ModelId("orphan"),
                    provider=ProviderId("nonexistent"),  # dangling
                    provider_model_id="x",
                    context_window=1000,
                ),
            }
        )
        agents = {
            "ghost_user": AgentLLMConfig(
                default_model=ModelId("ghost_model"),  # dangling
                fallback_chain=[],
                autonomy_thresholds=AgentAutonomyThresholds(
                    threshold_auto=8,
                    threshold_confirm=5,
                    user_intent_modifier=2,
                ),
            ),
        }
        with pytest.raises(ConfigError) as exc:
            validate_full_config(providers, models, agents)
        # Both the orphan model and the ghost agent reference get reported.
        assert len(exc.value.violations) >= 2


# ---------------------------------------------------------------------------
# End-to-end: load actual project example configs
# ---------------------------------------------------------------------------


class TestExampleConfigs:
    """Load the real config/*.yaml.example files. Catches any drift
    between the example yamls and the loader's expectations."""

    def test_load_example_providers(self) -> None:
        registry = load_providers(EXAMPLES_DIR / "llm_providers.yaml.example")
        # 5 providers in the example: anthropic_via_claude_code,
        # deepseek, ollama_local, mlx_local, mock.
        assert len(registry.all()) == 5

    def test_load_example_models(self) -> None:
        providers = load_providers(EXAMPLES_DIR / "llm_providers.yaml.example")
        models = load_models(EXAMPLES_DIR / "llm_models.yaml.example", providers)
        # 6 models in the example.
        assert len(models.all()) == 6

    def test_load_all_example_agents(self) -> None:
        providers = load_providers(EXAMPLES_DIR / "llm_providers.yaml.example")
        models = load_models(EXAMPLES_DIR / "llm_models.yaml.example", providers)
        agents_dir = EXAMPLES_DIR / "agents"
        agent_configs = {
            yaml_path.stem: load_agent_llm_config(yaml_path, models)
            for yaml_path in sorted(agents_dir.glob("*.yaml"))
        }
        assert set(agent_configs.keys()) == {
            "prober",
            "skeptic",
            "divergence_mapper",
            "logger",
            "operator",
        }

    def test_validate_full_example_config(self) -> None:
        """End-to-end: providers + models + 5 agent configs all load
        and pass validate_full_config. Catches doc-spec drift between
        canonical agent yamls and validation rules."""
        providers = load_providers(EXAMPLES_DIR / "llm_providers.yaml.example")
        models = load_models(EXAMPLES_DIR / "llm_models.yaml.example", providers)
        agents_dir = EXAMPLES_DIR / "agents"
        agent_configs = {
            yaml_path.stem: load_agent_llm_config(yaml_path, models)
            for yaml_path in sorted(agents_dir.glob("*.yaml"))
        }
        validate_full_config(providers, models, agent_configs)  # no raise

    def test_operator_default_routes_through_tool_capable_provider(self) -> None:
        """Operator requires tools; default_model must be deepseek_v4_flash
        (which goes through the openai_compatible provider that returns
        can_use_orchestrator_tools()=True)."""
        providers = load_providers(EXAMPLES_DIR / "llm_providers.yaml.example")
        models = load_models(EXAMPLES_DIR / "llm_models.yaml.example", providers)
        operator = load_agent_llm_config(EXAMPLES_DIR / "agents" / "operator.yaml", models)
        default_profile = models.get(operator.default_model)
        assert default_profile is not None
        assert Capability.TOOLS in default_profile.capabilities
        provider = providers.get(default_profile.provider)
        assert provider is not None
        assert provider.can_use_orchestrator_tools()


# ---------------------------------------------------------------------------
# load_tools_config
# ---------------------------------------------------------------------------


class TestLoadToolsConfig:
    """Tests for ``load_tools_config(path) -> dict[str, ToolMeta]``."""

    def test_happy_path_returns_tool_meta_dict(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "tools.yaml",
            """
            tools:
              read_file:
                reversibility: 10
              git_push:
                reversibility: 1
              default_tool: {}
            """,
        )
        result = load_tools_config(path)
        assert set(result.keys()) == {"read_file", "git_push", "default_tool"}
        assert isinstance(result["read_file"], ToolMeta)
        assert result["read_file"].reversibility == 10
        assert result["git_push"].reversibility == 1
        assert result["default_tool"].reversibility == 0  # Pydantic default

    def test_missing_file_raises_config_error(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="does not exist"):
            load_tools_config(tmp_path / "nonexistent.yaml")

    def test_malformed_yaml_raises_config_error(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "bad.yaml", "tools: [this: is: not: valid\n")
        with pytest.raises(ConfigError, match="yaml parse error"):
            load_tools_config(path)

    def test_config_error_violations_locate_offending_field_and_stem(self, tmp_path: Path) -> None:
        """ConfigError payload must carry the offending field name AND the
        yaml file stem so log-based diagnosis requires no extra lookups.

        Mirrors the P1.1 pattern in ``test_config_error_violations_locate_offending_yaml_field``
        for ``load_agent_llm_config``. Per ``test-coverage-standard.md`` §4.
        """
        path = _write(
            tmp_path,
            "mytoolsfile.yaml",
            """
            tools:
              bad_tool:
                reversibility: -1
            """,
        )
        with pytest.raises(ConfigError) as exc:
            load_tools_config(path)
        msg = str(exc.value)
        assert "reversibility" in msg
        assert path.stem in msg

    def test_cleanup_path_file_not_held_after_parse_failure(self, tmp_path: Path) -> None:
        """File handle must be released after a parse/validation error.

        ``load_tools_config`` uses ``Path.read_text()`` which opens and closes
        the file atomically — no persistent handle. This test verifies that
        assumption holds: after a ConfigError, we can still rename the file
        (which would fail on Windows if a handle were open).

        Note: outer-cancellation (§3b) is N/A because ``load_tools_config``
        is synchronous and holds no long-lived resource.
        """
        path = _write(
            tmp_path,
            "tools.yaml",
            """
            tools:
              bad_tool:
                reversibility: -99
            """,
        )
        with pytest.raises(ConfigError):
            load_tools_config(path)
        # If file handle were held, rename would raise PermissionError on Windows.
        renamed = path.with_name("tools_renamed.yaml")
        path.rename(renamed)
        assert renamed.exists()
        assert not path.exists()

    def test_load_canonical_tools_yaml(self) -> None:
        """Load the project's real tools.yaml — catches doc-spec drift."""
        result = load_tools_config(EXAMPLES_DIR / "tools.yaml")
        assert len(result) > 0
        for tool_id, meta in result.items():
            assert isinstance(meta, ToolMeta), f"tool {tool_id!r}: expected ToolMeta"
            assert 0 <= meta.reversibility <= 10, (
                f"tool {tool_id!r}: reversibility {meta.reversibility} out of [0, 10]"
            )
