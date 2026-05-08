"""Load and validate the three-layer LLM YAML config.

Three files:

- ``config/llm_providers.yaml`` — physical provider connections.
- ``config/llm_models.yaml`` — model profiles, each referencing a provider.
- ``config/agents/<role>.yaml`` — per-agent ``llm_config`` block
  (plus persona/dissent/etc. in P1.3, ignored here).

Loading order (each step depends on the previous):

1. **Providers.** Parse yaml; map each ``type`` to its concrete
   class via ``PROVIDER_TYPE_REGISTRY``; instantiate with the entry's
   ``params``. Build a ``ProviderRegistry``.
2. **Models.** Parse yaml; validate each ``provider`` exists in the
   ``ProviderRegistry``; validate ``default_effort`` only set when
   capabilities include ``EFFORT``. Build a ``ModelRegistry``.
3. **Agents.** Parse each yaml; extract the ``llm_config`` block;
   validate ``default_model`` and every id in ``fallback_chain``
   exists in the ``ModelRegistry``.
4. **Cross-validate.** Run ``validate_full_config`` to catch logical
   inconsistencies (e.g., agent with ``required_capabilities: [tools]``
   resolves to zero providers that accept tools).

Failure raises ``ConfigError`` with a list of every violation
(don't fail-fast at first error during validation — the user wants
to fix all problems in one editing pass).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestrator.llm.providers.claude_code_cli import ClaudeCodeCliProvider
from orchestrator.llm.providers.mock import MockProvider
from orchestrator.llm.providers.openai_compatible import OpenAICompatibleProvider
from orchestrator.llm.router import ModelRegistry, ProviderRegistry
from orchestrator.llm.types import (
    AgentLLMConfig,
    ProviderType,
)

PROVIDER_TYPE_REGISTRY: dict[ProviderType, type[Any]] = {
    ProviderType.OPENAI_COMPATIBLE: OpenAICompatibleProvider,
    ProviderType.CLAUDE_CODE_CLI: ClaudeCodeCliProvider,
    ProviderType.MOCK: MockProvider,
}
"""Maps each ``ProviderType`` to its concrete class. Adding a new
provider type requires extending this map plus a new module under
``providers/``.

TODO(P1.1 commit 2): Currently typed as ``type[Any]``. If commit 2
finds it needs type-narrowing (static dispatch on type-specific
``params`` fields), upgrade to ``TypeVar`` bound to ``LLMProvider``.
Until then, ``type[Any]`` plus a runtime constitutional test —
``test_all_registered_types_implement_protocol``, committed for
P1.1 commit 2 alongside provider instantiation — suffices. The
Protocol's runtime_checkable decorator catches structural drift,
and the registry only ever instantiates these classes through one
code path (``load_providers``)."""


def load_providers(path: Path) -> ProviderRegistry:
    """Parse ``llm_providers.yaml``, instantiate provider classes per
    ``type``, return a registry.

    Raises:
        ConfigError: malformed yaml, missing fields, unknown
            ``ProviderType``, or instantiation error.
    """
    raise NotImplementedError


def load_models(path: Path, providers: ProviderRegistry) -> ModelRegistry:
    """Parse ``llm_models.yaml``. Validates each model's ``provider``
    exists in the given ``ProviderRegistry`` and that
    ``default_effort`` matches capabilities.

    Raises:
        ConfigError: dangling provider reference or capability /
            effort mismatch.
    """
    raise NotImplementedError


def load_agent_llm_config(path: Path, models: ModelRegistry) -> AgentLLMConfig:
    """Parse one agent's yaml, extract its ``llm_config`` block,
    return an ``AgentLLMConfig``.

    Validates ``default_model`` and every id in ``fallback_chain``
    exists in the given ``ModelRegistry``.

    Raises:
        ConfigError: missing ``llm_config`` key, dangling model ref.
    """
    raise NotImplementedError


def validate_full_config(
    providers: ProviderRegistry,
    models: ModelRegistry,
    agent_configs: dict[str, AgentLLMConfig],
) -> None:
    """Full cross-file consistency check, called once at startup.

    Checks:

    - Every model's ``provider`` exists in ``providers``.
    - Every agent's ``default_model`` and ``fallback_chain`` entries
      exist in ``models``.
    - Every agent with ``required_capabilities: [tools]`` resolves to
      at least one model whose provider returns
      ``can_use_orchestrator_tools() == True`` (catches the canonical
      "operator pointed at Claude Code" misconfiguration at startup,
      not at first call).

    Collects every violation; raises one ``ConfigError`` at the end.
    Does NOT call providers (no health checks here — those are
    inherently fallible at startup time and may transiently fail).
    """
    raise NotImplementedError
