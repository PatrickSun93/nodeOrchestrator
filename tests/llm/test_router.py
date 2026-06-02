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
    AgentAutonomyThresholds,
    AgentLLMConfig,
    Capability,
    GlobalLLMOverride,
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
    cost_per_1m_output: float | None = None,
) -> ModelProfile:
    return ModelProfile(
        id=ModelId(id_),
        provider=ProviderId(provider),
        provider_model_id=id_,
        capabilities=capabilities or [],
        context_window=10_000,
        cost_per_1m_output=cost_per_1m_output,
    )


def _request(tools: list[ToolDefinition] | None = None) -> LLMRequest:
    return LLMRequest(
        request_id=generate_request_id(),
        purpose=LLMPurpose.AGENT_RESPONSE,
        messages=[Message(role="user", content="hi")],
        tools=tools or [],
    )


_DEFAULT_THRESHOLDS = AgentAutonomyThresholds(
    threshold_auto=8,
    threshold_confirm=5,
    user_intent_modifier=2,
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
        autonomy_thresholds=_DEFAULT_THRESHOLDS,
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

    async def test_no_suitable_model_error_decision_trace_complete(self) -> None:
        """Three-model chain failing for three distinct reasons: each
        trace entry must carry model_id + reason, all reasons distinct."""
        good_provider = MockProvider(provider_id=ProviderId("p_good"))
        bad_provider = MockProvider(provider_id=ProviderId("p_bad"), healthy=False)
        models = ModelRegistry(
            {
                ModelId("m2"): _profile("m2", "p_bad", [Capability.TOOLS]),
                ModelId("m3"): _profile("m3", "p_good"),  # no TOOLS
            }
        )
        # m1 not in registry
        providers = ProviderRegistry(
            {
                ProviderId("p_bad"): bad_provider,
                ProviderId("p_good"): good_provider,
            }
        )
        agent = _agent("m1", fallbacks=["m2", "m3"], required=[Capability.TOOLS])

        with pytest.raises(NoSuitableModelError) as exc:
            await select_model_and_provider(agent, _request(), models, providers)

        trace = exc.value.decision_trace
        assert len(trace) == 3
        reasons: set[str] = set()
        for entry in trace:
            assert "model_id" in entry
            assert "reason" in entry
            assert isinstance(entry["reason"], str)
            assert entry["reason"]  # non-empty
            reasons.add(entry["reason"])
        assert len(reasons) == 3  # all distinct


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


# ---------------------------------------------------------------------------
# Layer-4 global override tests
# ---------------------------------------------------------------------------


class TestOverrideNone:
    async def test_override_none_returns_unchanged_chain(self) -> None:
        """With override=None, routing is byte-identical to pre-S2 behavior."""
        prov = MockProvider(provider_id=ProviderId("p"))
        models = ModelRegistry(
            {
                ModelId("cheap"): _profile("cheap", "p", cost_per_1m_output=1.0),
                ModelId("expensive"): _profile("expensive", "p", cost_per_1m_output=50.0),
            }
        )
        providers = ProviderRegistry({ProviderId("p"): prov})
        agent = _agent("expensive", fallbacks=["cheap"])

        # With override=None, expensive model is selected (no filtering).
        result = await select_model_and_provider(agent, _request(), models, providers)
        assert result.model.id == ModelId("expensive")
        assert result.model_id_requested == ModelId("expensive")


class TestCostCeilingFilter:
    async def test_cost_ceiling_drops_expensive_model(self) -> None:
        """DISCRIMINATING: without override, expensive model is selected;
        with ceiling, it is dropped and cheaper fallback is used instead."""
        prov = MockProvider(provider_id=ProviderId("p"))
        models = ModelRegistry(
            {
                ModelId("expensive"): _profile("expensive", "p", cost_per_1m_output=20.0),
                ModelId("cheap"): _profile("cheap", "p", cost_per_1m_output=2.0),
            }
        )
        providers = ProviderRegistry({ProviderId("p"): prov})
        agent = _agent("expensive", fallbacks=["cheap"])

        # Without override: expensive is selected.
        result_no_override = await select_model_and_provider(agent, _request(), models, providers)
        assert result_no_override.model.id == ModelId("expensive")

        # With ceiling=10.0: expensive (20.0) is dropped; cheap (2.0) selected.
        override = GlobalLLMOverride(cost_ceiling_per_1m_output=10.0)
        result = await select_model_and_provider(
            agent, _request(), models, providers, override=override
        )
        assert result.model.id == ModelId("cheap")

        # The trace must contain a pre-filter entry for the expensive model.
        trace = result.decision_trace
        model_ids_in_trace = [c.model_id for c in trace]
        assert ModelId("expensive") in model_ids_in_trace
        expensive_entry = next(c for c in trace if c.model_id == ModelId("expensive"))
        assert not expensive_entry.accepted
        assert "ceiling" in expensive_entry.reason

    async def test_cost_ceiling_keeps_cheap_model(self) -> None:
        """Model at or below ceiling passes through."""
        prov = MockProvider(provider_id=ProviderId("p"))
        models = ModelRegistry({ModelId("cheap"): _profile("cheap", "p", cost_per_1m_output=2.0)})
        providers = ProviderRegistry({ProviderId("p"): prov})
        agent = _agent("cheap")

        override = GlobalLLMOverride(cost_ceiling_per_1m_output=10.0)
        result = await select_model_and_provider(
            agent, _request(), models, providers, override=override
        )
        assert result.model.id == ModelId("cheap")


class TestQualityTierReorder:
    async def test_quality_tier_economy_reorders_cheapest_first(self) -> None:
        """DISCRIMINATING: economy reorders cheapest to front (vs balanced identity)."""
        prov = MockProvider(provider_id=ProviderId("p"))
        models = ModelRegistry(
            {
                ModelId("expensive"): _profile("expensive", "p", cost_per_1m_output=20.0),
                ModelId("cheap"): _profile("cheap", "p", cost_per_1m_output=2.0),
            }
        )
        providers = ProviderRegistry({ProviderId("p"): prov})
        # Default chain: expensive first, cheap fallback.
        agent = _agent("expensive", fallbacks=["cheap"])

        # With economy tier: chain reorders to cheap first → cheap is selected.
        override = GlobalLLMOverride(quality_tier="economy")
        result = await select_model_and_provider(
            agent, _request(), models, providers, override=override
        )
        assert result.model.id == ModelId("cheap")

    async def test_quality_tier_premium_reorders_most_capable_first(self) -> None:
        """premium reorders most-capable to front."""
        prov = MockProvider(provider_id=ProviderId("p"))
        models = ModelRegistry(
            {
                ModelId("basic"): _profile("basic", "p", capabilities=[]),
                ModelId("full"): _profile(
                    "full", "p", capabilities=[Capability.TOOLS, Capability.VISION]
                ),
            }
        )
        providers = ProviderRegistry({ProviderId("p"): prov})
        # Default chain: basic first, full fallback.
        agent = _agent("basic", fallbacks=["full"])

        # With premium tier: full (2 caps) moves to front → full selected.
        override = GlobalLLMOverride(quality_tier="premium")
        result = await select_model_and_provider(
            agent, _request(), models, providers, override=override
        )
        assert result.model.id == ModelId("full")

    async def test_quality_tier_balanced_no_reorder(self) -> None:
        """balanced = identity: chain order unchanged."""
        prov = MockProvider(provider_id=ProviderId("p"))
        models = ModelRegistry(
            {
                ModelId("expensive"): _profile("expensive", "p", cost_per_1m_output=20.0),
                ModelId("cheap"): _profile("cheap", "p", cost_per_1m_output=2.0),
            }
        )
        providers = ProviderRegistry({ProviderId("p"): prov})
        agent = _agent("expensive", fallbacks=["cheap"])

        override = GlobalLLMOverride(quality_tier="balanced")
        result = await select_model_and_provider(
            agent, _request(), models, providers, override=override
        )
        # balanced does not reorder: expensive is still first and selected.
        assert result.model.id == ModelId("expensive")


class TestOnUnknownCost:
    async def test_on_unknown_cost_keep_keeps_unpriced_model(self) -> None:
        """on_unknown_cost='keep' + ceiling set: unpriced model stays in chain."""
        prov = MockProvider(provider_id=ProviderId("p"))
        models = ModelRegistry(
            {ModelId("unpriced"): _profile("unpriced", "p", cost_per_1m_output=None)}
        )
        providers = ProviderRegistry({ProviderId("p"): prov})
        agent = _agent("unpriced")

        override = GlobalLLMOverride(cost_ceiling_per_1m_output=10.0, on_unknown_cost="keep")
        result = await select_model_and_provider(
            agent, _request(), models, providers, override=override
        )
        assert result.model.id == ModelId("unpriced")

    async def test_on_unknown_cost_drop_drops_unpriced_model(self) -> None:
        """on_unknown_cost='drop' + ceiling set: unpriced model is dropped."""
        prov = MockProvider(provider_id=ProviderId("p"))
        models = ModelRegistry(
            {
                ModelId("unpriced"): _profile("unpriced", "p", cost_per_1m_output=None),
                ModelId("cheap"): _profile("cheap", "p", cost_per_1m_output=1.0),
            }
        )
        providers = ProviderRegistry({ProviderId("p"): prov})
        agent = _agent("unpriced", fallbacks=["cheap"])

        override = GlobalLLMOverride(cost_ceiling_per_1m_output=10.0, on_unknown_cost="drop")
        result = await select_model_and_provider(
            agent, _request(), models, providers, override=override
        )
        assert result.model.id == ModelId("cheap")

    async def test_unknown_cost_trace_entry_present_in_drop_mode(self) -> None:
        """Ceiling + unpriced model + drop: decision_trace has an entry about
        the unknown-cost model being dropped (never silent)."""
        prov = MockProvider(provider_id=ProviderId("p"))
        models = ModelRegistry(
            {
                ModelId("unpriced"): _profile("unpriced", "p", cost_per_1m_output=None),
                ModelId("cheap"): _profile("cheap", "p", cost_per_1m_output=1.0),
            }
        )
        providers = ProviderRegistry({ProviderId("p"): prov})
        agent = _agent("unpriced", fallbacks=["cheap"])

        override = GlobalLLMOverride(cost_ceiling_per_1m_output=10.0, on_unknown_cost="drop")
        result = await select_model_and_provider(
            agent, _request(), models, providers, override=override
        )
        # The unpriced model must appear in the trace as rejected.
        trace = result.decision_trace
        unpriced_entries = [c for c in trace if c.model_id == ModelId("unpriced")]
        assert len(unpriced_entries) >= 1
        assert not unpriced_entries[0].accepted
        assert "unknown" in unpriced_entries[0].reason.lower()

    async def test_unknown_cost_trace_entry_present_in_keep_mode(self) -> None:
        """Ceiling + unpriced model + keep: unpriced model is still selected
        (not silently dropped), proving the keep behavior is active."""
        prov = MockProvider(provider_id=ProviderId("p"))
        models = ModelRegistry(
            {ModelId("unpriced"): _profile("unpriced", "p", cost_per_1m_output=None)}
        )
        providers = ProviderRegistry({ProviderId("p"): prov})
        agent = _agent("unpriced")

        override = GlobalLLMOverride(cost_ceiling_per_1m_output=10.0, on_unknown_cost="keep")
        result = await select_model_and_provider(
            agent, _request(), models, providers, override=override
        )
        # Model is kept and accepted — it appears in trace as accepted.
        trace = result.decision_trace
        unpriced_entries = [c for c in trace if c.model_id == ModelId("unpriced")]
        assert len(unpriced_entries) >= 1
        # The accepted entry exists (model was kept and routed to).
        assert any(c.accepted for c in unpriced_entries)


class TestOverrideEmptyChain:
    async def test_override_empty_chain_raises_no_suitable_model(self) -> None:
        """Override filters all candidates → NoSuitableModelError."""
        prov = MockProvider(provider_id=ProviderId("p"))
        models = ModelRegistry(
            {
                ModelId("expensive"): _profile("expensive", "p", cost_per_1m_output=50.0),
                ModelId("also_expensive"): _profile("also_expensive", "p", cost_per_1m_output=30.0),
            }
        )
        providers = ProviderRegistry({ProviderId("p"): prov})
        agent = _agent("expensive", fallbacks=["also_expensive"])

        # Ceiling drops both models.
        override = GlobalLLMOverride(cost_ceiling_per_1m_output=10.0)
        with pytest.raises(NoSuitableModelError):
            await select_model_and_provider(agent, _request(), models, providers, override=override)


class TestOverrideComposesWithLayer3:
    async def test_override_does_not_bypass_layer3_capability_filter(self) -> None:
        """Model passes override but fails required_capabilities → still rejected."""
        prov = MockProvider(provider_id=ProviderId("p"))
        models = ModelRegistry(
            {
                ModelId("no_tools"): _profile("no_tools", "p", cost_per_1m_output=1.0),
            }
        )
        providers = ProviderRegistry({ProviderId("p"): prov})
        # Agent requires TOOLS; model doesn't have it.
        agent = _agent("no_tools", required=[Capability.TOOLS])

        # Override keeps the model in chain (below ceiling).
        override = GlobalLLMOverride(cost_ceiling_per_1m_output=10.0)
        with pytest.raises(NoSuitableModelError) as exc:
            await select_model_and_provider(agent, _request(), models, providers, override=override)
        trace = exc.value.decision_trace
        # The model was not accepted (Layer-3 capability check still ran).
        assert any("missing capability" in c["reason"] for c in trace)

    async def test_override_does_not_bypass_layer3_health_check(self) -> None:
        """Model passes override but fails health → still rejected by router."""
        unhealthy = MockProvider(provider_id=ProviderId("p"), healthy=False)
        models = ModelRegistry({ModelId("m"): _profile("m", "p", cost_per_1m_output=1.0)})
        providers = ProviderRegistry({ProviderId("p"): unhealthy})
        agent = _agent("m")

        # Override keeps the model in chain.
        override = GlobalLLMOverride(cost_ceiling_per_1m_output=10.0)
        with pytest.raises(NoSuitableModelError) as exc:
            await select_model_and_provider(agent, _request(), models, providers, override=override)
        trace = exc.value.decision_trace
        assert any("health_check" in c["reason"] for c in trace)
