"""D1 (P6.2): call-time transient fallback in RealLLMRouter._async_call.

Fail-on-revert: reverting the loop in _async_call (back to a single call) causes
test_transient_primary_falls_to_fallback to fail — the primary's TransientProviderError
propagates instead of the fallback answering.

These tests exercise the call-time half of ADR-002 D4 (previously dead code-path).
The health_check half is covered by tests/llm/test_e2e_fallback.py.
"""

from __future__ import annotations

import pytest

from orchestrator.api.llm_adapter import RealLLMRouter
from orchestrator.llm.exceptions import (
    NoSuitableModelError,
    PermanentProviderError,
    TransientProviderError,
)
from orchestrator.llm.protocol import LLMProvider
from orchestrator.llm.providers.mock import MockProvider
from orchestrator.llm.purposes import LLMPurpose
from orchestrator.llm.router import ModelRegistry, ProviderRegistry
from orchestrator.llm.types import (
    AgentAutonomyThresholds,
    AgentLLMConfig,
    Capability,
    LLMRequest,
    LLMResponse,
    Message,
    ModelId,
    ModelProfile,
    ProviderId,
    generate_request_id,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

PRIMARY_ID = ModelId("primary_model")
FALLBACK_ID = ModelId("fallback_model")
PRIMARY_PID = ProviderId("primary_provider")
FALLBACK_PID = ProviderId("fallback_provider")

_THRESHOLDS = AgentAutonomyThresholds(
    threshold_auto=8,
    threshold_confirm=5,
    user_intent_modifier=2,
)


class _ErrorOnCallProvider:
    """Test double: always health-passes, raises a specified ProviderError on call()."""

    def __init__(self, provider_id: ProviderId, error: Exception) -> None:
        self.provider_id = provider_id
        self._error = error
        self.call_count = 0

    def can_use_orchestrator_tools(self) -> bool:
        return True

    def health_check(self) -> bool:
        return True

    async def call(
        self,
        request: LLMRequest,
        model: ModelProfile,
        *,
        model_id_requested: ModelId,
    ) -> LLMResponse:
        self.call_count += 1
        raise self._error


def _make_model(model_id: ModelId, provider_id: ProviderId) -> ModelProfile:
    return ModelProfile(
        id=model_id,
        provider=provider_id,
        provider_model_id=f"{model_id}-backend",
        capabilities=[Capability.TOOLS],
        context_window=128_000,
    )


def _make_agent_config(
    default: ModelId = PRIMARY_ID,
    chain: list[ModelId] | None = None,
) -> AgentLLMConfig:
    return AgentLLMConfig(
        default_model=default,
        fallback_chain=chain or [FALLBACK_ID],
        autonomy_thresholds=_THRESHOLDS,
    )


def _make_request() -> LLMRequest:
    return LLMRequest(
        request_id=generate_request_id(),
        purpose=LLMPurpose.AGENT_RESPONSE,
        messages=[Message(role="user", content="hello")],
        caller_agent_id="agent:test",
    )


def _make_router(
    primary_provider: LLMProvider,
    fallback_provider: LLMProvider,
    agent_config: AgentLLMConfig | None = None,
) -> tuple[RealLLMRouter, AgentLLMConfig]:
    cfg = agent_config or _make_agent_config()
    models = ModelRegistry(
        {
            PRIMARY_ID: _make_model(PRIMARY_ID, PRIMARY_PID),
            FALLBACK_ID: _make_model(FALLBACK_ID, FALLBACK_PID),
        }
    )
    providers = ProviderRegistry(
        {
            PRIMARY_PID: primary_provider,
            FALLBACK_PID: fallback_provider,
        }
    )
    router = RealLLMRouter(
        agent_configs={"agent:test": cfg},
        models=models,
        providers=providers,
        override=None,
    )
    return router, cfg


# ---------------------------------------------------------------------------
# D1 tests
# ---------------------------------------------------------------------------


async def test_transient_primary_falls_to_fallback() -> None:
    """Chain [primary, fallback], both health-pass; primary.call() raises
    TransientProviderError → response comes from fallback.

    Fail-on-revert: reverting the loop makes primary's transient propagate
    instead of the fallback answering — this assertion fails.
    """
    primary = _ErrorOnCallProvider(PRIMARY_PID, TransientProviderError("rate limited"))
    fallback = MockProvider(
        provider_id=FALLBACK_PID,
        responses={(LLMPurpose.AGENT_RESPONSE, None): ["fallback reply"]},
    )

    router, agent_config = _make_router(primary, fallback)
    request = _make_request()
    response = await router._async_call(request, agent_config)

    assert response.content == "fallback reply"
    assert response.model_id_requested == PRIMARY_ID
    assert response.model_id_used == FALLBACK_ID
    assert response.model_id_requested != response.model_id_used


async def test_permanent_primary_propagates_no_fallback() -> None:
    """primary.call() raises PermanentProviderError → propagates; fallback is NOT called."""
    primary = _ErrorOnCallProvider(PRIMARY_PID, PermanentProviderError("auth failed"))
    fallback = MockProvider(
        provider_id=FALLBACK_PID,
        responses={(LLMPurpose.AGENT_RESPONSE, None): ["should not be called"]},
    )

    router, agent_config = _make_router(primary, fallback)
    request = _make_request()

    with pytest.raises(PermanentProviderError, match="auth failed"):
        await router._async_call(request, agent_config)

    assert fallback.calls == [], "fallback must not be called on PermanentProviderError"


async def test_all_transient_raises_no_suitable_model_error() -> None:
    """All viable providers raise TransientProviderError → NoSuitableModelError with trace."""
    primary = _ErrorOnCallProvider(PRIMARY_PID, TransientProviderError("rate limited"))
    fallback = _ErrorOnCallProvider(FALLBACK_PID, TransientProviderError("timeout"))

    router, agent_config = _make_router(primary, fallback)
    request = _make_request()

    with pytest.raises(NoSuitableModelError) as exc_info:
        await router._async_call(request, agent_config)

    err = exc_info.value
    assert len(err.decision_trace) == 2
    assert all(not entry["accepted"] for entry in err.decision_trace)
    assert "call-time transient" in err.decision_trace[0]["reason"]
    assert "call-time transient" in err.decision_trace[1]["reason"]
