"""Shared fixtures for tests/llm/.

Built on top of the example yaml configs in ``config/`` — load the
real example files, substitute MockProvider for each provider id so
tests don't touch the network. Catches drift between the example
yamls and the loader (any time a yaml changes in a way that breaks
loading, fixtures fail to build).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.llm.config_loader import (
    load_agent_llm_config,
    load_models,
    load_providers,
)
from orchestrator.llm.providers.mock import MockProvider
from orchestrator.llm.router import ModelRegistry, ProviderRegistry
from orchestrator.llm.types import (
    AgentLLMConfig,
    ProviderId,
)

EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "config"


@pytest.fixture
def mock_provider() -> MockProvider:
    """Fresh MockProvider with no canned responses. Tests register
    responses via ``mock_provider.responses[(purpose, agent_id)] = [...]``.
    """
    return MockProvider(provider_id=ProviderId("mock"))


@pytest.fixture
def example_provider_registry() -> ProviderRegistry:
    """ProviderRegistry built from real example yaml. Every yaml
    provider id is mapped to a MockProvider so tests don't hit the
    network. Claude Code's ``can_use_orchestrator_tools=False`` is
    preserved because that is a structural fact about Claude Code
    (per ADR-003), and tests of routing/validation depend on it.
    """
    # Load real provider yaml just to validate it parses; we replace
    # the instances with mocks below to keep tests offline.
    real = load_providers(EXAMPLES_DIR / "llm_providers.yaml.example")
    instances: dict[ProviderId, MockProvider] = {}
    for provider in real.all():
        # Mirror Claude Code's tool-rejection in the mock so routing
        # behavior is exercised correctly.
        can_tools = provider.can_use_orchestrator_tools()
        instances[provider.provider_id] = MockProvider(
            provider_id=provider.provider_id,
            can_use_tools=can_tools,
        )
    return ProviderRegistry(dict(instances))


@pytest.fixture
def example_model_registry(
    example_provider_registry: ProviderRegistry,
) -> ModelRegistry:
    """ModelRegistry built from real example yaml. Validated against
    ``example_provider_registry`` (which has mocks substituted)."""
    return load_models(
        EXAMPLES_DIR / "llm_models.yaml.example",
        example_provider_registry,
    )


@pytest.fixture
def example_agent_configs(
    example_model_registry: ModelRegistry,
) -> dict[str, AgentLLMConfig]:
    """Dict of role-name → AgentLLMConfig parsed from each example
    agent yaml. Keys are the file stem (e.g. ``"prober"``)."""
    agents_dir = EXAMPLES_DIR / "agents"
    configs: dict[str, AgentLLMConfig] = {}
    for path in sorted(agents_dir.glob("*.yaml.example")):
        # Stem of "prober.yaml.example" is "prober.yaml"; strip the
        # trailing .yaml to get the role name.
        role = path.stem
        if role.endswith(".yaml"):
            role = role[: -len(".yaml")]
        configs[role] = load_agent_llm_config(path, example_model_registry)
    return configs
