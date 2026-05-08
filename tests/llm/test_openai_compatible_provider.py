"""Tests for OpenAICompatibleProvider — uses httpx.MockTransport
to intercept network calls."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from orchestrator.llm.exceptions import (
    PermanentProviderError,
    TransientProviderError,
)
from orchestrator.llm.providers.openai_compatible import OpenAICompatibleProvider
from orchestrator.llm.purposes import LLMPurpose
from orchestrator.llm.types import (
    Capability,
    LLMRequest,
    LLMResponse,
    Message,
    ModelId,
    ModelProfile,
    ProviderId,
    ToolDefinition,
    generate_request_id,
)


def _model(cost_in: float | None = None, cost_out: float | None = None) -> ModelProfile:
    return ModelProfile(
        id=ModelId("test_model"),
        provider=ProviderId("p"),
        provider_model_id="api-model-id",
        capabilities=[Capability.TOOLS],
        context_window=10_000,
        cost_per_1m_input=cost_in,
        cost_per_1m_output=cost_out,
    )


def _request(
    *,
    tools: list[ToolDefinition] | None = None,
    temperature: float | None = None,
    system: str | None = None,
) -> LLMRequest:
    return LLMRequest(
        request_id=generate_request_id(),
        purpose=LLMPurpose.AGENT_RESPONSE,
        messages=[Message(role="user", content="hi")],
        system=system,
        tools=tools or [],
        temperature=temperature,
    )


def _make_provider(handler: Any, api_key_env: str = "") -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        provider_id=ProviderId("p"),
        base_url="https://api.example.com/v1",
        api_key_env=api_key_env,
        transport=httpx.MockTransport(handler),
    )


async def _call(
    provider: OpenAICompatibleProvider,
    request: LLMRequest,
    model: ModelProfile,
) -> LLMResponse:
    """Test wrapper: defaults model_id_requested to model.id."""
    return await OpenAICompatibleProvider.call(
        provider, request, model, model_id_requested=model.id
    )


def _ok_response(content: str = "hello", **extras: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    base.update(extras)
    return base


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestHappyPath:
    async def test_basic_text_response(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=_ok_response("greetings"))

        provider = _make_provider(handler)
        resp = await _call(provider, _request(), _model())

        assert resp.content == "greetings"
        assert resp.finish_reason == "stop"
        assert resp.usage.input_tokens == 10
        assert resp.usage.output_tokens == 5
        assert resp.model_id_used == ModelId("test_model")
        assert captured["url"] == "https://api.example.com/v1/chat/completions"
        # Wire payload uses provider_model_id, not the internal id.
        assert captured["body"]["model"] == "api-model-id"

    async def test_temperature_passed_through(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=_ok_response())

        provider = _make_provider(handler)
        await _call(provider, _request(temperature=0.7), _model())
        assert captured["body"]["temperature"] == 0.7

    async def test_system_message_prepended(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=_ok_response())

        provider = _make_provider(handler)
        await _call(provider, _request(system="be helpful"), _model())
        msgs = captured["body"]["messages"]
        assert msgs[0] == {"role": "system", "content": "be helpful"}
        assert msgs[1]["role"] == "user"


class TestToolCalls:
    async def test_tools_serialized_as_functions(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json=_ok_response())

        tool = ToolDefinition(name="search", description="x", input_schema={"type": "object"})
        provider = _make_provider(handler)
        await _call(provider, _request(tools=[tool]), _model())
        sent_tools = captured["body"]["tools"]
        assert len(sent_tools) == 1
        assert sent_tools[0]["type"] == "function"
        assert sent_tools[0]["function"]["name"] == "search"

    async def test_tool_call_in_response_parsed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "calling tool",
                                "tool_calls": [
                                    {
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "search",
                                            "arguments": '{"q": "X"}',
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 5},
                },
            )

        provider = _make_provider(handler)
        resp = await _call(provider, _request(), _model())
        assert resp.content == "calling tool"
        assert resp.finish_reason == "tool_use"
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "search"
        assert resp.tool_calls[0].arguments == {"q": "X"}


class TestAuth:
    async def test_api_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_KEY", "sk-abc")
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["auth"] = request.headers.get("authorization")
            return httpx.Response(200, json=_ok_response())

        provider = _make_provider(handler, api_key_env="MY_KEY")
        await _call(provider, _request(), _model())
        assert captured["auth"] == "Bearer sk-abc"

    async def test_missing_api_key_raises_permanent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MISSING_KEY", raising=False)
        provider = _make_provider(
            lambda r: httpx.Response(200, json=_ok_response()),
            api_key_env="MISSING_KEY",
        )
        with pytest.raises(PermanentProviderError, match="empty or unset"):
            await _call(provider, _request(), _model())

    async def test_no_api_key_env_no_auth_header(self) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["auth"] = request.headers.get("authorization")
            return httpx.Response(200, json=_ok_response())

        provider = _make_provider(handler)  # api_key_env=""
        await _call(provider, _request(), _model())
        assert captured["auth"] is None


class TestErrorClassification:
    async def test_401_raises_permanent(self) -> None:
        provider = _make_provider(lambda r: httpx.Response(401, text="bad key"))
        with pytest.raises(PermanentProviderError, match="auth failed"):
            await _call(provider, _request(), _model())

    async def test_403_raises_permanent(self) -> None:
        provider = _make_provider(lambda r: httpx.Response(403, text="forbidden"))
        with pytest.raises(PermanentProviderError):
            await _call(provider, _request(), _model())

    async def test_429_raises_transient(self) -> None:
        provider = _make_provider(lambda r: httpx.Response(429, text="slow down"))
        with pytest.raises(TransientProviderError, match="rate limited"):
            await _call(provider, _request(), _model())

    async def test_500_raises_transient(self) -> None:
        provider = _make_provider(lambda r: httpx.Response(500, text="oops"))
        with pytest.raises(TransientProviderError, match="server error"):
            await _call(provider, _request(), _model())

    async def test_400_raises_permanent(self) -> None:
        provider = _make_provider(lambda r: httpx.Response(400, text="malformed"))
        with pytest.raises(PermanentProviderError, match="client error"):
            await _call(provider, _request(), _model())

    async def test_non_json_body_raises_permanent(self) -> None:
        provider = _make_provider(lambda r: httpx.Response(200, content=b"not json"))
        with pytest.raises(PermanentProviderError, match="non-JSON"):
            await _call(provider, _request(), _model())

    async def test_unexpected_shape_raises_permanent(self) -> None:
        """Response is JSON but missing 'choices'."""
        provider = _make_provider(lambda r: httpx.Response(200, json={"unexpected": "shape"}))
        with pytest.raises(PermanentProviderError, match="unexpected response shape"):
            await _call(provider, _request(), _model())


class TestCostComputation:
    async def test_cost_computed_from_model_pricing(self) -> None:
        provider = _make_provider(
            lambda r: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "x"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 500_000},
                },
            )
        )
        # $0.27 / 1M input, $1.10 / 1M output (deepseek-v4-pro pricing)
        resp = await _call(provider, _request(), _model(cost_in=0.27, cost_out=1.10))
        # 1M * 0.27 + 0.5M * 1.10 = 0.27 + 0.55 = 0.82
        assert resp.usage.cost_usd == pytest.approx(0.82, rel=1e-3)

    async def test_cost_none_when_pricing_missing(self) -> None:
        provider = _make_provider(lambda r: httpx.Response(200, json=_ok_response()))
        resp = await _call(provider, _request(), _model())  # no pricing on model
        assert resp.usage.cost_usd is None
