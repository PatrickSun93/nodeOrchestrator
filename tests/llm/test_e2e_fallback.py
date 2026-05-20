"""E2E fallback integration test: router + provider end-to-end with
source != sink assertion. Verifies that when the default model's provider
is unhealthy, the chain falls through to a healthy provider, and
model_id_requested (original) is distinct from model_id_used (fallback).
"""

from __future__ import annotations

from orchestrator.llm.protocol import LLMProvider
from orchestrator.llm.providers.mock import MockProvider
from orchestrator.llm.purposes import LLMPurpose
from orchestrator.llm.router import (
    ModelRegistry,
    ProviderRegistry,
    select_model_and_provider,
)
from orchestrator.llm.types import (
    AgentAutonomyThresholds,
    AgentLLMConfig,
    Capability,
    LLMRequest,
    Message,
    ModelId,
    ModelProfile,
    ProviderId,
    generate_request_id,
)

OPUS_ID = ModelId("claude_code_opus_47")
SONNET_ID = ModelId("claude_code_sonnet_46")
DEEPSEEK_ID = ModelId("deepseek_v4_pro")

ANTHROPIC_PID = ProviderId("anthropic_via_claude_code")
DEEPSEEK_PID = ProviderId("deepseek")


def _make_model(model_id: ModelId, provider_id: ProviderId) -> ModelProfile:
    return ModelProfile(
        id=model_id,
        provider=provider_id,
        provider_model_id=f"{model_id}-backend",
        capabilities=[Capability.TOOLS],
        context_window=128000,
    )


async def test_e2e_fallback_model_id_requested_distinct_from_used() -> None:
    """Router picks deepseek after both claude models skip on unhealthy
    anthropic provider. Response carries requested != used."""
    opus = _make_model(OPUS_ID, ANTHROPIC_PID)
    sonnet = _make_model(SONNET_ID, ANTHROPIC_PID)
    deepseek_model = _make_model(DEEPSEEK_ID, DEEPSEEK_PID)

    models = ModelRegistry(
        {
            OPUS_ID: opus,
            SONNET_ID: sonnet,
            DEEPSEEK_ID: deepseek_model,
        }
    )

    unhealthy_anthropic: LLMProvider = MockProvider(provider_id=ANTHROPIC_PID, healthy=False)
    deepseek_response = "fallback response from deepseek"
    healthy_deepseek: LLMProvider = MockProvider(
        provider_id=DEEPSEEK_PID,
        responses={(LLMPurpose.AGENT_RESPONSE, None): [deepseek_response]},
    )
    providers = ProviderRegistry(
        {
            ANTHROPIC_PID: unhealthy_anthropic,
            DEEPSEEK_PID: healthy_deepseek,
        }
    )

    agent_config = AgentLLMConfig(
        default_model=OPUS_ID,
        fallback_chain=[SONNET_ID, DEEPSEEK_ID],
        autonomy_thresholds=AgentAutonomyThresholds(
            threshold_auto=8,
            threshold_confirm=5,
            user_intent_modifier=2,
        ),
    )

    request = LLMRequest(
        request_id=generate_request_id(),
        purpose=LLMPurpose.AGENT_RESPONSE,
        messages=[Message(role="user", content="hello")],
        caller_agent_id="agent:skeptic",
    )

    route = await select_model_and_provider(agent_config, request, models, providers)

    assert route.model_id_requested == OPUS_ID
    assert route.model.id != OPUS_ID
    assert route.model.id == DEEPSEEK_ID
    assert len(route.decision_trace) == 3
    # opus: unhealthy → rejected
    assert not route.decision_trace[0].accepted
    assert "health_check" in route.decision_trace[0].reason.lower()
    # sonnet: unhealthy → rejected
    assert not route.decision_trace[1].accepted
    assert "health_check" in route.decision_trace[1].reason.lower()
    # deepseek: healthy → accepted
    assert route.decision_trace[2].accepted
    assert route.decision_trace[2].reason == "matched"

    response = await route.provider.call(
        request,
        route.model,
        model_id_requested=route.model_id_requested,
    )

    assert response.model_id_requested == OPUS_ID
    assert response.model_id_used == DEEPSEEK_ID
    assert response.model_id_requested != response.model_id_used
    assert response.content == deepseek_response
