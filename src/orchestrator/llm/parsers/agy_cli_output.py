"""Parser for Agy CLI output.

Agy (Antigravity CLI) produces a JSON envelope when called with --json.
This module translates that envelope into our ``LLMResponse``.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from orchestrator.llm.exceptions import PermanentProviderError
from orchestrator.llm.types import (
    LLMResponse,
    ModelId,
    ProviderId,
    RequestId,
    ToolCall,
    Usage,
)

_STOP_REASON_MAP: dict[str, str] = {
    "stop": "stop",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "content_filter": "content_filter",
}


def parse_agy_cli_output(
    raw_stdout: str,
    request_id: RequestId,
    model_id_requested: ModelId,
    model_id_used: ModelId,
    provider_id: ProviderId,
    latency_ms: int,
) -> LLMResponse:
    """Parse ``agy --json`` stdout into an LLMResponse.

    The CLI emits a single JSON object per call. Expected fields:

    - ``content``: str or list of content blocks.
    - ``finish_reason``: stop, length, tool_calls, content_filter.
    - ``usage``: dict with prompt_tokens, completion_tokens.

    Raises:
        PermanentProviderError: JSON malformed, or structural errors.
    """
    try:
        data: Any = json.loads(raw_stdout)
    except json.JSONDecodeError as e:
        raise PermanentProviderError(f"agy cli output is not valid JSON: {e}") from e

    if not isinstance(data, dict):
        raise PermanentProviderError(
            f"agy cli output must be a JSON object, got {type(data).__name__}"
        )

    content = data.get("content", "")
    if isinstance(content, list):
        text_parts = [
            str(b.get("text", ""))
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        content = "\n".join(text_parts)
    elif not isinstance(content, str):
        content = str(content)

    tool_calls: list[ToolCall] = []
    tool_calls_data = data.get("tool_calls", [])
    if isinstance(tool_calls_data, list):
        for tc in tool_calls_data:
            if isinstance(tc, dict):
                try:
                    tool_calls.append(
                        ToolCall(
                            id=str(tc.get("id", "")),
                            name=str(tc.get("function", {}).get("name", "")),
                            arguments=tc.get("function", {}).get("arguments") or {},
                        )
                    )
                except ValidationError as e:
                    raise PermanentProviderError(f"malformed tool_call block: {e}") from e

    cli_stop = data.get("finish_reason", "stop")
    if not isinstance(cli_stop, str):
        cli_stop = "stop"
    finish_reason = _STOP_REASON_MAP.get(cli_stop, "stop")

    usage_data = data.get("usage", {})
    if not isinstance(usage_data, dict):
        usage_data = {}
    usage = Usage(
        input_tokens=int(usage_data.get("prompt_tokens", 0) or 0),
        output_tokens=int(usage_data.get("completion_tokens", 0) or 0),
        cache_read_tokens=0,
        cache_creation_tokens=0,
        cost_usd=None,
    )

    try:
        return LLMResponse(
            request_id=request_id,
            content=content,
            tool_calls=tool_calls,
            model_id_requested=model_id_requested,
            model_id_used=model_id_used,
            provider_id_used=provider_id,
            usage=usage,
            latency_ms=latency_ms,
            finish_reason=finish_reason,  # type: ignore[arg-type]
        )
    except ValidationError as e:
        raise PermanentProviderError(
            f"failed to construct LLMResponse from agy cli output: {e}"
        ) from e
