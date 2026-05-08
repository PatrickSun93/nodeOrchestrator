"""Tests for router: ModelRegistry, ProviderRegistry,
select_model_and_provider."""

from __future__ import annotations

import pytest

from orchestrator.llm.exceptions import NoSuitableModelError
from orchestrator.llm.providers.mock import MockProvider
from orchestrator.llm.purposes import LLMPurpose
from orchestrator.llm.router import (
    ModelRegistry,
    ProviderRegistry,
    RouteCandidate,
    RouteResult,
    select_model_and_provider,
)
from orchestrator.llm.types import (
    AgentLLMConfig,
    Capability,
    LLMRequest,
    Message,
    ModelId,
    ModelProfile,
    ProviderId,
    ToolDefinition,
    generate_request_id,
)

# ---------------------------------------------------------------------------
# Test scaffold
# ---------------------------------------------------------------------------


def _profile(
    id_: str,
    provider: str,
    capabilities: list[Capability] | None = None,
) -> ModelProfile:
    return ModelProfile(
        id=ModelId(id_),
        provider=ProviderId(provider),
        provider_model_id=id_,
        capabilities=capabilities or [],
        context_window=10_000,
    )


def _request(tools: list[ToolDefinition] | None = None) -> LLMRequest:
    return LLMRequest(
        request_id=generate_request_id(),
        purpose=LLMPurpose.AGENT_RESPONSE,
        messages=[Message(role="user", content="hi")],
        tools=tools or [],
    )


def _agent(
    default: str,
    fallbacks: list[str] | None = None,
    required: list[Capability] | None = None,
) -> AgentLLMConfig:
    return AgentLLMConfig(
        default_model=ModelId(default),
        fallback_chain=[ModelId(m) for m in (fallbacks or [])],
        required_capabilities=required or [],
    )


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestModelRegistry:
    def test_get_existing_model(self) -> None:
        p = _profile("opus", "anthropic")
        reg = ModelRegistry({ModelId("opus"): p})
        assert reg.get(ModelId("opus")) is p

    def test_get_unknown_returns_none(self) -> None:
        reg = ModelRegistry({})
        assert reg.get(ModelId("missing")) is None

    def test_all_returns_all_profiles(self) -> None:
        p1 = _profile("opus", "anthropic")
        p2 = _profile("sonnet", "anthropic")
        reg = ModelRegistry({ModelId("opus"): p1, ModelId("sonnet"): p2})
        # Pydantic models with list fields are unhashable; compare ids
        # instead of using a set.
        all_profiles = reg.all()
        assert len(all_profiles) == 2
        assert {p.id for p in all_profiles} == {ModelId("opus"), ModelId("sonnet")}


class TestProviderRegistry:
    def test_get_and_all(self) -> None:
        p1 = MockProvider(provider_id=ProviderId("a"))
        p2 = MockProvider(provider_id=ProviderId("b"))
        reg = ProviderRegistry({ProviderId("a"): p1, ProviderId("b"): p2})
        assert reg.get(ProviderId("a")) is p1
        assert reg.get(ProviderId("missing")) is None
        assert len(reg.all()) == 2


# ---------------------------------------------------------------------------
# Routing — happy paths
# ---------------------------------------------------------------------------


class TestRoutingHappyPath:
    async def test_default_model_resolved_when_healthy(self) -> None:
        prov = MockProvider(provider_id=ProviderId("anthropic"))
        models = ModelRegistry({ModelId("opus"): _profile("opus", "anthropic")})
        providers = ProviderRegistry({ProviderId("anthropic"): prov})
        agent = _agent("opus")

        result = await select_model_and_provider(agent, _request(), models, providers)
        assert result.model.id == "opus"
        assert result.provider is prov
        assert result.model_id_requested == ModelId("opus")
        # decision_trace contains exactly the matched candidate.
        assert len(result.decision_trace) == 1
        assert result.decision_trace[0].accepted
        assert result.decision_trace[0].reason == "matched"

    async def test_model_id_requested_preserved_on_fallback(self) -> None:
        """When fallback fires, model_id_requested still reports the
        original default — fallback events stay visible in audit."""
        unhealthy = MockProvider(provider_id=ProviderId("ds"), healthy=False)
        healthy = MockProvider(provider_id=ProviderId("anthropic"))
        models = ModelRegistry(
            {
                ModelId("primary"): _profile("primary", "ds"),
                ModelId("backup"): _profile("backup", "anthropic"),
            }
        )
        providers = ProviderRegistry(
            {ProviderId("ds"): unhealthy, ProviderId("anthropic"): healthy}
        )
        agent = _agent("primary", fallbacks=["backup"])

        result = await select_model_and_provider(agent, _request(), models, providers)
        assert result.model.id == "backup"  # used the fallback
        assert result.model_id_requested == ModelId("primary")  # but tracks original


# ---------------------------------------------------------------------------
# Routing — fallback triggers
# ---------------------------------------------------------------------------


class TestFallbackOnUnhealthy:
    async def test_skips_unhealthy_provider(self) -> None:
        bad = MockProvider(provider_id=ProviderId("p1"), healthy=False)
        good = MockProvider(provider_id=ProviderId("p2"))
        models = ModelRegistry(
            {
                ModelId("m1"): _profile("m1", "p1"),
                ModelId("m2"): _profile("m2", "p2"),
            }
        )
        providers = ProviderRegistry({ProviderId("p1"): bad, ProviderId("p2"): good})
        agent = _agent("m1", fallbacks=["m2"])

        result = await select_model_and_provider(agent, _request(), models, providers)
        assert result.model.id == "m2"
        # Trace records the rejection
        rejected = result.decision_trace[0]
        assert not rejected.accepted
        assert "health_check" in rejected.reason


class TestFallbackOnToolsUnsupported:
    async def test_skips_tools_unsupported_when_request_has_tools(self) -> None:
        no_tools = MockProvider(provider_id=ProviderId("cli"), can_use_tools=False)
        with_tools = MockProvider(provider_id=ProviderId("api"))
        models = ModelRegistry(
            {
                ModelId("opus"): _profile("opus", "cli"),
                ModelId("ds"): _profile("ds", "api", [Capability.TOOLS]),
            }
        )
        providers = ProviderRegistry({ProviderId("cli"): no_tools, ProviderId("api"): with_tools})
        agent = _agent("opus", fallbacks=["ds"])

        tool = ToolDefinition(name="search", description="x", input_schema={"type": "object"})
        result = await select_model_and_provider(agent, _request(tools=[tool]), models, providers)
        assert result.model.id == "ds"
        assert "tools" in result.decision_trace[0].reason

    async def test_no_tool_skip_when_request_has_no_tools(self) -> None:
        """Provider that rejects tools is fine for tool-less requests."""
        no_tools = MockProvider(provider_id=ProviderId("cli"), can_use_tools=False)
        models = ModelRegistry({ModelId("opus"): _profile("opus", "cli")})
        providers = ProviderRegistry({ProviderId("cli"): no_tools})
        agent = _agent("opus")

        result = await select_model_and_provider(
            agent,
            _request(),
            models,
            providers,  # no tools
        )
        assert result.model.id == "opus"


class TestCapabilityFilter:
    async def test_skips_model_missing_required_capability(self) -> None:
        prov = MockProvider(provider_id=ProviderId("p"))
        models = ModelRegistry(
            {
                ModelId("no_tools"): _profile("no_tools", "p"),  # no capabilities
                ModelId("with_tools"): _profile("with_tools", "p", [Capability.TOOLS]),
            }
        )
        providers = ProviderRegistry({ProviderId("p"): prov})
        agent = _agent(
            "no_tools",
            fallbacks=["with_tools"],
            required=[Capability.TOOLS],
        )

        result = await select_model_and_provider(agent, _request(), models, providers)
        assert result.model.id == "with_tools"
        assert "missing capability" in result.decision_trace[0].reason


# ---------------------------------------------------------------------------
# Routing — missing-from-registry
# ---------------------------------------------------------------------------


class TestRegistryDrift:
    async def test_unknown_model_skipped(self) -> None:
        prov = MockProvider(provider_id=ProviderId("p"))
        models = ModelRegistry({ModelId("real"): _profile("real", "p")})
        providers = ProviderRegistry({ProviderId("p"): prov})
        agent = _agent("ghost", fallbacks=["real"])

        result = await select_model_and_provider(agent, _request(), models, providers)
        assert result.model.id == "real"
        assert result.decision_trace[0].reason == "model not in registry"

    async def test_unknown_provider_skipped(self) -> None:
        models = ModelRegistry({ModelId("m1"): _profile("m1", "ghost_provider")})
        providers = ProviderRegistry({})  # empty
        agent = _agent("m1")

        with pytest.raises(NoSuitableModelError):
            await select_model_and_provider(agent, _request(), models, providers)


# ---------------------------------------------------------------------------
# Routing — exhaustion
# ---------------------------------------------------------------------------


class TestExhaustion:
    async def test_no_suitable_model_raises_with_trace(self) -> None:
        bad = MockProvider(provider_id=ProviderId("p"), healthy=False)
        models = ModelRegistry(
            {
                ModelId("m1"): _profile("m1", "p"),
                ModelId("m2"): _profile("m2", "p"),
            }
        )
        providers = ProviderRegistry({ProviderId("p"): bad})
        agent = _agent("m1", fallbacks=["m2"])

        with pytest.raises(NoSuitableModelError) as exc:
            await select_model_and_provider(agent, _request(), models, providers)
        # Trace contains both rejections, in chain order.
        trace = exc.value.decision_trace
        assert len(trace) == 2
        assert trace[0]["model_id"] == "m1"
        assert trace[1]["model_id"] == "m2"
        assert all(not c["accepted"] for c in trace)

    async def test_exception_message_lists_chain(self) -> None:
        models = ModelRegistry({})
        providers = ProviderRegistry({})
        agent = _agent("a", fallbacks=["b", "c"])

        with pytest.raises(NoSuitableModelError, match=r"chain.*\['a', 'b', 'c'\]"):
            await select_model_and_provider(agent, _request(), models, providers)


class TestTraceShape:
    async def test_trace_is_tuple_of_route_candidates(self) -> None:
        prov = MockProvider(provider_id=ProviderId("p"))
        models = ModelRegistry({ModelId("m"): _profile("m", "p")})
        providers = ProviderRegistry({ProviderId("p"): prov})
        agent = _agent("m")

        result = await select_model_and_provider(agent, _request(), models, providers)
        assert isinstance(result.decision_trace, tuple)
        for c in result.decision_trace:
            assert isinstance(c, RouteCandidate)


class TestRouteResultShape:
    async def test_route_result_has_required_fields(self) -> None:
        prov = MockProvider(provider_id=ProviderId("p"))
        models = ModelRegistry({ModelId("m"): _profile("m", "p")})
        providers = ProviderRegistry({ProviderId("p"): prov})
        agent = _agent("m")

        import dataclasses

        result = await select_model_and_provider(agent, _request(), models, providers)
        # Frozen dataclass — attributes are read-only.
        assert isinstance(result, RouteResult)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.model = None  # type: ignore[misc,assignment]
