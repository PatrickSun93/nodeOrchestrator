"""Tests for parse_agy_cli_output."""

from __future__ import annotations

import json

import pytest

from orchestrator.llm.exceptions import PermanentProviderError
from orchestrator.llm.parsers.agy_cli_output import parse_agy_cli_output
from orchestrator.llm.types import LLMResponse, ModelId, ProviderId, RequestId

REQ = RequestId("llmreq_agy_test")
MODEL_REQ = ModelId("agy_gemini_flash")
MODEL_USED = ModelId("agy_gemini_flash")
PROV = ProviderId("agy")


def _envelope(**overrides: object) -> str:
    base: dict[str, object] = {
        "content": "hello",
        "finish_reason": "stop",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    base.update(overrides)
    return json.dumps(base)


def _parse(raw: str) -> LLMResponse:
    return parse_agy_cli_output(
        raw,
        request_id=REQ,
        model_id_requested=MODEL_REQ,
        model_id_used=MODEL_USED,
        provider_id=PROV,
        latency_ms=100,
    )


class TestHappyPath:
    def test_minimal_str_content(self) -> None:
        resp = _parse(_envelope())
        assert resp.content == "hello"
        assert resp.tool_calls == []
        assert resp.usage.input_tokens == 10
        assert resp.usage.output_tokens == 5
        assert resp.finish_reason == "stop"
        assert resp.latency_ms == 100
        assert resp.request_id == REQ

    def test_content_as_list_of_blocks(self) -> None:
        raw = json.dumps(
            {
                "content": [
                    {"type": "text", "text": "first"},
                    {"type": "text", "text": "second"},
                ],
                "finish_reason": "stop",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }
        )
        resp = _parse(raw)
        assert resp.content == "first\nsecond"

    def test_non_text_blocks_skipped(self) -> None:
        raw = json.dumps(
            {
                "content": [
                    {"type": "text", "text": "keep"},
                    {"type": "image", "url": "http://example.com/img.png"},
                ],
                "finish_reason": "stop",
                "usage": {},
            }
        )
        resp = _parse(raw)
        assert resp.content == "keep"

    def test_non_str_content_coerced(self) -> None:
        resp = _parse(_envelope(content=42))
        assert resp.content == "42"

    def test_missing_content_defaults_empty(self) -> None:
        raw = json.dumps({"finish_reason": "stop", "usage": {}})
        resp = _parse(raw)
        assert resp.content == ""

    def test_missing_usage_defaults_zero(self) -> None:
        raw = json.dumps({"content": "x", "finish_reason": "stop"})
        resp = _parse(raw)
        assert resp.usage.input_tokens == 0
        assert resp.usage.output_tokens == 0

    def test_non_dict_usage_defaults_zero(self) -> None:
        resp = _parse(_envelope(usage="bad"))
        assert resp.usage.input_tokens == 0
        assert resp.usage.output_tokens == 0


class TestStopReasonMapping:
    @pytest.mark.parametrize(
        "cli_stop,expected",
        [
            ("stop", "stop"),
            ("length", "max_tokens"),
            ("tool_calls", "tool_use"),
            ("content_filter", "content_filter"),
            ("unknown_future_value", "stop"),
            ("", "stop"),
        ],
    )
    def test_mapping(self, cli_stop: str, expected: str) -> None:
        resp = _parse(_envelope(finish_reason=cli_stop))
        assert resp.finish_reason == expected

    def test_non_str_finish_reason_defaults_stop(self) -> None:
        resp = _parse(_envelope(finish_reason=None))
        assert resp.finish_reason == "stop"


class TestErrorHandling:
    def test_malformed_json_raises_permanent(self) -> None:
        with pytest.raises(PermanentProviderError, match="not valid JSON"):
            _parse("{not json")

    def test_top_level_array_raises_permanent(self) -> None:
        with pytest.raises(PermanentProviderError, match="must be a JSON object"):
            _parse("[]")

    def test_top_level_string_raises_permanent(self) -> None:
        with pytest.raises(PermanentProviderError, match="must be a JSON object"):
            _parse('"just a string"')

    def test_malformed_tool_call_raises_permanent(self) -> None:
        """A tool_call with an empty name fails ToolCall validation → PermanentProviderError."""
        raw = json.dumps(
            {
                "content": "",
                "finish_reason": "tool_calls",
                "usage": {},
                "tool_calls": [
                    {
                        "id": "tc_1",
                        "function": {"name": "", "arguments": {}},
                    }
                ],
            }
        )
        with pytest.raises(PermanentProviderError, match="malformed tool_call"):
            _parse(raw)


class TestToolCalls:
    def test_valid_tool_call_extracted(self) -> None:
        raw = json.dumps(
            {
                "content": "",
                "finish_reason": "tool_calls",
                "usage": {},
                "tool_calls": [
                    {
                        "id": "tc_1",
                        "function": {"name": "search", "arguments": {"q": "hello"}},
                    }
                ],
            }
        )
        resp = _parse(raw)
        assert len(resp.tool_calls) == 1
        tc = resp.tool_calls[0]
        assert tc.id == "tc_1"
        assert tc.name == "search"
        assert tc.arguments == {"q": "hello"}

    def test_empty_tool_calls_list_is_fine(self) -> None:
        resp = _parse(_envelope(tool_calls=[]))
        assert resp.tool_calls == []

    def test_non_dict_tool_call_entry_skipped(self) -> None:
        raw = json.dumps(
            {
                "content": "ok",
                "finish_reason": "stop",
                "usage": {},
                "tool_calls": ["not a dict", None, 42],
            }
        )
        resp = _parse(raw)
        assert resp.tool_calls == []
