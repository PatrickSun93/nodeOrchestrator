"""Tests for parse_claude_code_output."""

from __future__ import annotations

import json

import pytest

from orchestrator.llm.exceptions import PermanentProviderError
from orchestrator.llm.parsers.claude_code_output import parse_claude_code_output
from orchestrator.llm.types import ModelId, ProviderId, RequestId

REQ = RequestId("llmreq_test")
MODEL_REQ = ModelId("claude_code_opus_47")
MODEL_USED = ModelId("claude_code_opus_47")
PROV = ProviderId("anthropic_via_claude_code")


def _envelope(**overrides: object) -> str:
    """Build a minimally valid CLI envelope JSON string."""
    base: dict[str, object] = {
        "content": [{"type": "text", "text": "hi"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    base.update(overrides)
    return json.dumps(base)


class TestHappyPath:
    def test_minimal_text_response(self) -> None:
        resp = parse_claude_code_output(
            _envelope(),
            request_id=REQ,
            model_id_requested=MODEL_REQ,
            model_id_used=MODEL_USED,
            provider_id=PROV,
            latency_ms=100,
        )
        assert resp.content == "hi"
        assert resp.tool_calls == []
        assert resp.usage.input_tokens == 10
        assert resp.usage.output_tokens == 5
        assert resp.usage.cost_usd is None  # Max subscription opaque
        assert resp.finish_reason == "stop"
        assert resp.latency_ms == 100
        assert resp.request_id == REQ

    def test_multiple_text_blocks_concatenated(self) -> None:
        envelope = json.dumps(
            {
                "content": [
                    {"type": "text", "text": "first"},
                    {"type": "text", "text": "second"},
                ],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        )
        resp = parse_claude_code_output(envelope, REQ, MODEL_REQ, MODEL_USED, PROV, 0)
        assert resp.content == "first\nsecond"

    def test_tool_use_block_extracted(self) -> None:
        envelope = json.dumps(
            {
                "content": [
                    {"type": "text", "text": "let me search"},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "web_search",
                        "input": {"query": "X"},
                    },
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        )
        resp = parse_claude_code_output(envelope, REQ, MODEL_REQ, MODEL_USED, PROV, 0)
        assert resp.content == "let me search"
        assert len(resp.tool_calls) == 1
        tc = resp.tool_calls[0]
        assert tc.id == "toolu_1"
        assert tc.name == "web_search"
        assert tc.arguments == {"query": "X"}
        assert resp.finish_reason == "tool_use"

    def test_empty_content_array(self) -> None:
        envelope = json.dumps(
            {
                "content": [],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 0, "output_tokens": 0},
            }
        )
        resp = parse_claude_code_output(envelope, REQ, MODEL_REQ, MODEL_USED, PROV, 0)
        assert resp.content == ""
        assert resp.tool_calls == []

    def test_cache_tokens_passthrough(self) -> None:
        envelope = json.dumps(
            {
                "content": [{"type": "text", "text": "x"}],
                "stop_reason": "end_turn",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "cache_read_input_tokens": 80,
                    "cache_creation_input_tokens": 200,
                },
            }
        )
        resp = parse_claude_code_output(envelope, REQ, MODEL_REQ, MODEL_USED, PROV, 0)
        assert resp.usage.cache_read_tokens == 80
        assert resp.usage.cache_creation_tokens == 200


class TestStopReasonMapping:
    @pytest.mark.parametrize(
        "cli_stop,expected",
        [
            ("end_turn", "stop"),
            ("stop_sequence", "stop"),
            ("max_tokens", "max_tokens"),
            ("tool_use", "tool_use"),
            ("refusal", "content_filter"),
            ("unknown_future_value", "stop"),  # defensive default
            ("", "stop"),
        ],
    )
    def test_mapping(self, cli_stop: str, expected: str) -> None:
        envelope = _envelope(stop_reason=cli_stop)
        resp = parse_claude_code_output(envelope, REQ, MODEL_REQ, MODEL_USED, PROV, 0)
        assert resp.finish_reason == expected


class TestErrorHandling:
    def test_malformed_json_raises_permanent(self) -> None:
        with pytest.raises(PermanentProviderError, match="not valid JSON"):
            parse_claude_code_output("{not json", REQ, MODEL_REQ, MODEL_USED, PROV, 0)

    def test_top_level_array_raises_permanent(self) -> None:
        with pytest.raises(PermanentProviderError, match="must be a JSON object"):
            parse_claude_code_output("[]", REQ, MODEL_REQ, MODEL_USED, PROV, 0)

    def test_content_not_a_list_raises(self) -> None:
        envelope = json.dumps({"content": "not a list", "stop_reason": "end_turn", "usage": {}})
        with pytest.raises(PermanentProviderError, match="'content' to be a list"):
            parse_claude_code_output(envelope, REQ, MODEL_REQ, MODEL_USED, PROV, 0)

    def test_tool_use_with_empty_name_raises_permanent(self) -> None:
        """ToolCall requires non-empty name; Pydantic ValidationError
        is wrapped as PermanentProviderError."""
        envelope = json.dumps(
            {
                "content": [{"type": "tool_use", "id": "abc", "name": "", "input": {}}],
                "stop_reason": "tool_use",
                "usage": {},
            }
        )
        with pytest.raises(PermanentProviderError, match="malformed tool_use"):
            parse_claude_code_output(envelope, REQ, MODEL_REQ, MODEL_USED, PROV, 0)


class TestRobustness:
    def test_unknown_block_types_ignored(self) -> None:
        """A future block type we don't recognize should be skipped, not crash."""
        envelope = json.dumps(
            {
                "content": [
                    {"type": "text", "text": "hello"},
                    {"type": "future_unknown_block", "data": {"x": 1}},
                ],
                "stop_reason": "end_turn",
                "usage": {},
            }
        )
        resp = parse_claude_code_output(envelope, REQ, MODEL_REQ, MODEL_USED, PROV, 0)
        assert resp.content == "hello"

    def test_missing_usage_defaults_zero(self) -> None:
        envelope = json.dumps(
            {"content": [{"type": "text", "text": "x"}], "stop_reason": "end_turn"}
        )
        resp = parse_claude_code_output(envelope, REQ, MODEL_REQ, MODEL_USED, PROV, 0)
        assert resp.usage.input_tokens == 0
        assert resp.usage.output_tokens == 0

    def test_non_string_text_skipped(self) -> None:
        """Defensive: a text block with non-string text doesn't blow up."""
        envelope = json.dumps(
            {
                "content": [
                    {"type": "text", "text": "first"},
                    {"type": "text", "text": 123},  # non-string
                    {"type": "text", "text": "third"},
                ],
                "stop_reason": "end_turn",
                "usage": {},
            }
        )
        resp = parse_claude_code_output(envelope, REQ, MODEL_REQ, MODEL_USED, PROV, 0)
        assert resp.content == "first\nthird"
