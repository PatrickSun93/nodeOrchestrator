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

import yaml
from pydantic import ValidationError

from orchestrator.autonomy.scoring import ToolMeta
from orchestrator.llm.exceptions import ConfigError
from orchestrator.llm.protocol import LLMProvider
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


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read a yaml file; raise ConfigError on missing file or non-dict root."""
    if not path.exists():
        raise ConfigError(f"yaml file does not exist: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"yaml parse error in {path}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top-level must be a mapping, got {type(raw).__name__}")
    return raw


def load_providers(path: Path) -> ProviderRegistry:
    """Parse ``llm_providers.yaml``, instantiate provider classes per
    ``type``, return a registry.

    Raises:
        ConfigError: malformed yaml, missing fields, unknown
            ``ProviderType``, or instantiation error.
    """
    raw = _read_yaml(path)
    entries = raw.get("providers")
    if not isinstance(entries, dict):
        raise ConfigError(f"{path}: missing or non-dict 'providers' top-level key")

    instances: dict[ProviderId, LLMProvider] = {}
    violations: list[str] = []

    for pid_str, entry in entries.items():
        if not isinstance(entry, dict):
            violations.append(
                f"provider {pid_str!r}: entry must be a mapping, got {type(entry).__name__}"
            )
            continue
        type_str = entry.get("type")
        if not isinstance(type_str, str):
            violations.append(f"provider {pid_str!r}: missing or non-string 'type'")
            continue
        try:
            ptype = ProviderType(type_str)
        except ValueError:
            violations.append(
                f"provider {pid_str!r}: unknown type {type_str!r} "
                f"(known: {[t.value for t in ProviderType]})"
            )
            continue

        cls = PROVIDER_TYPE_REGISTRY.get(ptype)
        if cls is None:
            violations.append(f"provider {pid_str!r}: type {type_str!r} has no registered class")
            continue

        params = entry.get("params") or {}
        if not isinstance(params, dict):
            violations.append(f"provider {pid_str!r}: 'params' must be a mapping")
            continue

        try:
            instance = cls(provider_id=ProviderId(pid_str), **params)
        except TypeError as e:
            violations.append(f"provider {pid_str!r}: instantiation failed — {e}")
            continue

        instances[ProviderId(pid_str)] = instance

    if violations:
        raise ConfigError(
            f"{path}: provider config has {len(violations)} violation(s)",
            violations=violations,
        )
    return ProviderRegistry(instances)


def load_models(path: Path, providers: ProviderRegistry) -> ModelRegistry:
    """Parse ``llm_models.yaml``. Validates each model's ``provider``
    exists in the given ``ProviderRegistry`` and that
    ``default_effort`` matches capabilities (the latter is enforced
    by ``ModelProfile``'s validator).

    Raises:
        ConfigError: dangling provider reference or capability /
            effort mismatch.
    """
    raw = _read_yaml(path)
    entries = raw.get("models")
    if not isinstance(entries, dict):
        raise ConfigError(f"{path}: missing or non-dict 'models' top-level key")

    profiles: dict[ModelId, ModelProfile] = {}
    violations: list[str] = []

    for mid_str, entry in entries.items():
        if not isinstance(entry, dict):
            violations.append(
                f"model {mid_str!r}: entry must be a mapping, got {type(entry).__name__}"
            )
            continue
        try:
            profile = ModelProfile(id=ModelId(mid_str), **entry)
        except ValidationError as e:
            violations.append(f"model {mid_str!r}: validation failed — {e}")
            continue
        except TypeError as e:
            violations.append(f"model {mid_str!r}: unexpected field — {e}")
            continue

        if providers.get(profile.provider) is None:
            violations.append(
                f"model {mid_str!r}: provider {profile.provider!r} not in providers registry"
            )
            continue

        profiles[profile.id] = profile

    if violations:
        raise ConfigError(
            f"{path}: model config has {len(violations)} violation(s)",
            violations=violations,
        )
    return ModelRegistry(profiles)


def load_agent_llm_config(path: Path, models: ModelRegistry) -> AgentLLMConfig:
    """Parse one agent's yaml; extract ``llm_config`` and
    ``autonomy_thresholds`` blocks; return an ``AgentLLMConfig``.

    Validates ``default_model`` and every id in ``fallback_chain``
    exists in the given ``ModelRegistry``.

    Raises:
        ConfigError: missing required key, validation failure, or
            dangling model ref.
    """
    raw = _read_yaml(path)
    llm_config_data = raw.get("llm_config")
    if not isinstance(llm_config_data, dict):
        raise ConfigError(f"{path}: missing or non-dict 'llm_config' key")

    autonomy_thresholds_data = raw.get("autonomy_thresholds")
    if not isinstance(autonomy_thresholds_data, dict):
        raise ConfigError(f"{path}: missing or non-dict 'autonomy_thresholds' key")

    try:
        thresholds = AgentAutonomyThresholds.model_validate(autonomy_thresholds_data)
        config = AgentLLMConfig(
            **llm_config_data,
            autonomy_thresholds=thresholds,
        )
    except ValidationError as e:
        raise ConfigError(
            f"{path}: agent config validation failed — {e}",
            violations=[str(e)],
        ) from e

    violations: list[str] = []
    for mid in [config.default_model, *config.fallback_chain]:
        if models.get(mid) is None:
            violations.append(f"{path}: references model {mid!r} not in models registry")

    if violations:
        raise ConfigError(
            f"{path}: agent llm_config has {len(violations)} violation(s)",
            violations=violations,
        )
    return config


def load_tools_config(path: Path) -> dict[str, ToolMeta]:
    """Load tools.yaml. Tools missing ``reversibility`` get
    the schema default (0; conservative-low per ADR-005
    Decision 2). Unknown fields raise ``ConfigError`` per the
    project's schema-enforcement preference.

    Loader placed in ``orchestrator.llm.config_loader`` (not
    ``orchestrator.autonomy``) so it can reuse ``ConfigError`` and
    ``_read_yaml`` without importing from ``orchestrator.llm`` in the
    autonomy module — which the constitutional test forbids.

    Raises:
        ConfigError: missing file, malformed yaml, or schema violation.
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
    violations: list[str] = []

    for profile in models.all():
        if providers.get(profile.provider) is None:
            violations.append(f"model {profile.id!r}: provider {profile.provider!r} not registered")

    for agent_name, config in agent_configs.items():
        for mid in [config.default_model, *config.fallback_chain]:
            if models.get(mid) is None:
                violations.append(f"agent {agent_name!r}: model {mid!r} not registered")

        if Capability.TOOLS not in config.required_capabilities:
            continue
        has_routable_with_tools = False
        for mid in [config.default_model, *config.fallback_chain]:
            candidate = models.get(mid)
            if candidate is None or Capability.TOOLS not in candidate.capabilities:
                continue
            candidate_provider = providers.get(candidate.provider)
            if candidate_provider is None or not candidate_provider.can_use_orchestrator_tools():
                continue
            has_routable_with_tools = True
            break
        if not has_routable_with_tools:
            violations.append(
                f"agent {agent_name!r} requires 'tools' capability but "
                f"no model in [default_model, *fallback_chain] resolves "
                f"to a provider that accepts orchestrator tools "
                f"(canonical case: agent pointed only at claude_code_cli, "
                f"see ADR-003)"
            )

    if violations:
        raise ConfigError(
            f"full config validation failed with {len(violations)} violation(s)",
            violations=violations,
        )
