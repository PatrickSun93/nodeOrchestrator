"""Model routing: pick the right model + provider for an agent's request.

The router walks the agent's ``fallback_chain``, picking the first
model whose:

- profile satisfies the request's ``required_capabilities``,
- provider passes ``health_check()``,
- ``can_use_orchestrator_tools()`` matches the request's needs.

Returns the (model, provider) pair plus a ``decision_trace`` listing
each candidate considered and why each was accepted or rejected.
The trace is appended to the LLM call event for audit — analogous to
the autonomy gateway's ``decision_trace`` (per contributing.md Q2).

This module contains zero LLM calls. Routing is decision-path code.
"""

from __future__ import annotations

from dataclasses import dataclass

from orchestrator.llm.protocol import LLMProvider
from orchestrator.llm.types import (
    AgentLLMConfig,
    LLMRequest,
    ModelId,
    ModelProfile,
    ProviderId,
)


@dataclass(frozen=True)
class RouteCandidate:
    """One step of the routing decision trace.

    Records every model considered, accepted or not, with the reason.
    A successful route ends with one ``accepted=True`` candidate;
    failed routes have all-False candidates plus a
    ``NoSuitableModelError`` carrying the trace.
    """

    model_id: ModelId
    provider_id: ProviderId | None
    accepted: bool
    reason: str
    """Human-readable explanation, e.g.
    ``"missing capability tools"``,
    ``"provider deepseek health_check returned False"``,
    ``"matched"``."""


@dataclass(frozen=True)
class RouteResult:
    """Successful routing outcome."""

    model: ModelProfile
    provider: LLMProvider
    decision_trace: tuple[RouteCandidate, ...]


class ModelRegistry:
    """Read-only registry of ``ModelProfile`` loaded from
    ``llm_models.yaml``.

    Built by ``config_loader.load_models``. The registry validates at
    load time that every profile references an existing provider id.
    """

    def __init__(self, profiles: dict[ModelId, ModelProfile]) -> None:
        self._profiles = profiles

    def get(self, model_id: ModelId) -> ModelProfile | None:
        raise NotImplementedError

    def all(self) -> list[ModelProfile]:
        raise NotImplementedError


class ProviderRegistry:
    """Read-only registry of ``LLMProvider`` instances loaded from
    ``llm_providers.yaml``.

    Built by ``config_loader.load_providers``. Each ``ProviderType``
    maps to a concrete class registered in ``config_loader``.
    """

    def __init__(self, providers: dict[ProviderId, LLMProvider]) -> None:
        self._providers = providers

    def get(self, provider_id: ProviderId) -> LLMProvider | None:
        raise NotImplementedError

    def all(self) -> list[LLMProvider]:
        raise NotImplementedError


def select_model_and_provider(
    agent_config: AgentLLMConfig,
    request: LLMRequest,
    models: ModelRegistry,
    providers: ProviderRegistry,
) -> RouteResult:
    """Walk the agent's fallback chain; pick the first viable model.

    Algorithm::

        candidates = []
        for model_id in agent_config.fallback_chain:
            profile = models.get(model_id)
            if profile is None:
                candidates.append(reject "model not in registry")
                continue
            missing = required_capabilities - profile.capabilities
            if missing:
                candidates.append(reject f"missing capability {missing}")
                continue
            provider = providers.get(profile.provider)
            if provider is None:
                candidates.append(reject "provider not in registry")
                continue
            if request.tools and not provider.can_use_orchestrator_tools():
                candidates.append(reject "tools not supported")
                continue
            if not provider.health_check():
                candidates.append(reject "unhealthy")
                continue
            candidates.append(accept "matched")
            return RouteResult(profile, provider, tuple(candidates))
        raise NoSuitableModelError(decision_trace=candidates)

    Raises:
        NoSuitableModelError: every model was rejected. The
            ``decision_trace`` attached to the exception explains
            each rejection in order.
    """
    raise NotImplementedError
