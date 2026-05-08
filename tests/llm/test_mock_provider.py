"""Tests for MockProvider — deterministic test-only LLM provider."""

from __future__ import annotations

import pytest

from orchestrator.llm.providers.mock import MockProvider, MockResponseExhaustedError
from orchestrator.llm.purposes import LLMPurpose
from orchestrator.llm.types import (
    Capability,
    LLMRequest,
    Message,
    ModelId,
    ModelProfile,
    ProviderId,
    generate_request_id,
)

MOCK_PROVIDER_ID = ProviderId("mock")
TEST_MODEL_ID = ModelId("test_model")


def _model() -> ModelProfile:
    return ModelProfile(
        id=TEST_MODEL_ID,
        provider=MOCK_PROVIDER_ID,
        provider_model_id="mock-model",
        capabilities=[Capability.TOOLS],
        context_window=10000,
    )


def _request(
    purpose: LLMPurpose = LLMPurpose.AGENT_RESPONSE,
    caller_agent_id: str | None = None,
) -> LLMRequest:
    return LLMRequest(
        request_id=generate_request_id(),
        purpose=purpose,
        messages=[Message(role="user", content="hi")],
        caller_agent_id=caller_agent_id,
    )


class TestProviderProtocolBasics:
    def test_provider_id(self) -> None:
        p = MockProvider(provider_id=MOCK_PROVIDER_ID)
        assert p.provider_id == MOCK_PROVIDER_ID

    def test_can_use_orchestrator_tools_default_true(self) -> None:
        p = MockProvider(provider_id=MOCK_PROVIDER_ID)
        assert p.can_use_orchestrator_tools() is True

    def test_can_use_orchestrator_tools_overridable(self) -> None:
        p = MockProvider(provider_id=MOCK_PROVIDER_ID, can_use_tools=False)
        assert p.can_use_orchestrator_tools() is False

    def test_health_check_default_true(self) -> None:
        p = MockProvider(provider_id=MOCK_PROVIDER_ID)
        assert p.health_check() is True

    def test_health_check_overridable(self) -> None:
        p = MockProvider(provider_id=MOCK_PROVIDER_ID, healthy=False)
        assert p.health_check() is False


class TestExactMatch:
    async def test_exact_key_match_returns_first_response(self) -> None:
        p = MockProvider(
            provider_id=MOCK_PROVIDER_ID,
            responses={
                (LLMPurpose.AGENT_RESPONSE, "agent:prober"): ["what about X?"],
            },
        )
        req = _request(caller_agent_id="agent:prober")
        resp = await p.call(req, _model())
        assert resp.content == "what about X?"
        assert resp.request_id == req.request_id
        assert resp.model_id_used == TEST_MODEL_ID
        assert resp.provider_id_used == MOCK_PROVIDER_ID
        assert resp.finish_reason == "stop"


class TestRoundRobin:
    async def test_advances_through_list(self) -> None:
        p = MockProvider(
            provider_id=MOCK_PROVIDER_ID,
            responses={
                (LLMPurpose.AGENT_RESPONSE, "agent:prober"): ["one", "two", "three"],
            },
        )
        contents: list[str] = []
        for _ in range(3):
            resp = await p.call(_request(caller_agent_id="agent:prober"), _model())
            contents.append(resp.content)
        assert contents == ["one", "two", "three"]

    async def test_cursor_per_key(self) -> None:
        """Each key has its own cursor — prober advances independently of skeptic."""
        p = MockProvider(
            provider_id=MOCK_PROVIDER_ID,
            responses={
                (LLMPurpose.AGENT_RESPONSE, "agent:prober"): ["P1", "P2"],
                (LLMPurpose.AGENT_RESPONSE, "agent:skeptic"): ["S1", "S2"],
            },
        )
        # Interleave prober/skeptic calls
        r1 = await p.call(_request(caller_agent_id="agent:prober"), _model())
        r2 = await p.call(_request(caller_agent_id="agent:skeptic"), _model())
        r3 = await p.call(_request(caller_agent_id="agent:prober"), _model())
        r4 = await p.call(_request(caller_agent_id="agent:skeptic"), _model())
        assert [r.content for r in (r1, r2, r3, r4)] == ["P1", "S1", "P2", "S2"]


class TestFallbackKey:
    async def test_purpose_only_key_when_exact_missing(self) -> None:
        """When (purpose, agent_id) is not registered but (purpose, None) is,
        the fallback key is used."""
        p = MockProvider(
            provider_id=MOCK_PROVIDER_ID,
            responses={
                (LLMPurpose.SNAPSHOT_SEMANTIC, None): ["focus: X"],
            },
        )
        req = _request(
            purpose=LLMPurpose.SNAPSHOT_SEMANTIC,
            caller_agent_id="agent:logger",
        )
        resp = await p.call(req, _model())
        assert resp.content == "focus: X"

    async def test_exact_preferred_over_fallback(self) -> None:
        """When both keys registered, exact match wins."""
        p = MockProvider(
            provider_id=MOCK_PROVIDER_ID,
            responses={
                (LLMPurpose.AGENT_RESPONSE, "agent:prober"): ["specific"],
                (LLMPurpose.AGENT_RESPONSE, None): ["generic"],
            },
        )
        req = _request(caller_agent_id="agent:prober")
        resp = await p.call(req, _model())
        assert resp.content == "specific"


class TestExhaustion:
    async def test_unknown_purpose_raises(self) -> None:
        p = MockProvider(provider_id=MOCK_PROVIDER_ID, responses={})
        with pytest.raises(MockResponseExhaustedError, match="no canned responses"):
            await p.call(_request(), _model())

    async def test_exhausted_list_raises(self) -> None:
        p = MockProvider(
            provider_id=MOCK_PROVIDER_ID,
            responses={(LLMPurpose.AGENT_RESPONSE, None): ["only one"]},
        )
        await p.call(_request(), _model())  # consumes "only one"
        with pytest.raises(MockResponseExhaustedError, match="exhausted"):
            await p.call(_request(), _model())

    async def test_exhaustion_message_includes_call_number(self) -> None:
        p = MockProvider(
            provider_id=MOCK_PROVIDER_ID,
            responses={(LLMPurpose.AGENT_RESPONSE, None): ["a"]},
        )
        await p.call(_request(), _model())
        with pytest.raises(MockResponseExhaustedError, match="call #2"):
            await p.call(_request(), _model())


class TestCallsCapture:
    async def test_calls_recorded_for_assertion(self) -> None:
        p = MockProvider(
            provider_id=MOCK_PROVIDER_ID,
            responses={(LLMPurpose.AGENT_RESPONSE, None): ["a", "b"]},
        )
        req1 = _request(caller_agent_id="agent:prober")
        req2 = _request(caller_agent_id="agent:skeptic")
        await p.call(req1, _model())
        await p.call(req2, _model())
        captured = p.calls
        assert len(captured) == 2
        assert captured[0].caller_agent_id == "agent:prober"
        assert captured[1].caller_agent_id == "agent:skeptic"

    async def test_calls_recorded_even_on_exhaustion(self) -> None:
        """Failed lookups still appear in .calls — useful for debugging
        a test that calls more than registered."""
        p = MockProvider(provider_id=MOCK_PROVIDER_ID, responses={})
        with pytest.raises(MockResponseExhaustedError):
            await p.call(_request(), _model())
        assert len(p.calls) == 1


class TestConstitution:
    """Locks the docstring contract about matched-key semantics so
    future refactors don't quietly change it."""

    async def test_constitution_round_robin_uses_matched_key(self) -> None:
        """Once a key is matched, its cursor advances. Subsequent calls
        with the same matched key consume sequentially.

        This locks the docstring's "Round-robin cursor is per matched
        key" claim. If a future refactor changes lookup to (e.g.)
        global cursor or fall-through-on-exhaust, this test fails.
        """
        p = MockProvider(
            provider_id=MOCK_PROVIDER_ID,
            responses={
                (LLMPurpose.AGENT_RESPONSE, "agent:prober"): ["P1", "P2"],
                (LLMPurpose.AGENT_RESPONSE, None): ["G1", "G2", "G3"],
            },
        )
        # 3 prober calls: 1st and 2nd hit the per-agent key (P1, P2),
        # 3rd would also hit the per-agent key but exhausted -> raise.
        # It does NOT fall through to the (purpose, None) fallback —
        # exhaustion of a matched key is a test bug, not a fall-through.
        r1 = await p.call(_request(caller_agent_id="agent:prober"), _model())
        r2 = await p.call(_request(caller_agent_id="agent:prober"), _model())
        assert [r1.content, r2.content] == ["P1", "P2"]
        with pytest.raises(MockResponseExhaustedError, match="exhausted"):
            await p.call(_request(caller_agent_id="agent:prober"), _model())

        # The fallback key cursor should NOT have advanced during the
        # prober calls — it's a separate matched key.
        # Using a different agent (whose exact key is unregistered)
        # routes to the fallback for the first time:
        r4 = await p.call(_request(caller_agent_id="agent:other"), _model())
        assert r4.content == "G1"  # fallback cursor at 0, not 2 or 3
