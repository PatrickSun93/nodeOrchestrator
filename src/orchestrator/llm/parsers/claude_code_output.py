"""Parser for Claude Code CLI output.

Claude Code's ``--output-format json`` produces a structured envelope
with content, tool calls (if any — though we currently configure no
tools through this provider, see ADR-003), and usage. This module
translates that envelope into our ``LLMResponse``.

Why a dedicated module: the CLI's output schema may evolve faster
than its provider behavior. Isolating the parser lets us upgrade
the wire-format independently of routing/health logic, and keeps
the parser unit-testable against recorded fixture output.
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

# Map Claude's stop_reason vocabulary to LLMResponse.finish_reason.
# Unknown stop_reasons fall back to "stop" — defensive against CLI
# version drift; the alternative (raise on unknown) would be brittle
# for a parser whose output we want to keep working across CLI
# upgrades.
_STOP_REASON_MAP: dict[str, str] = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "max_tokens",
    "tool_use": "tool_use",
    "refusal": "content_filter",
}


def parse_claude_code_output(
    raw_stdout: str,
    request_id: RequestId,
    model_id_requested: ModelId,
    model_id_used: ModelId,
    provider_id: ProviderId,
    latency_ms: int,
) -> LLMResponse:
    """Parse ``claude --output-format json`` stdout into an LLMResponse.

    The CLI emits a single JSON object per call. Expected fields:

    - ``content``: list of content blocks (text and tool_use).
    - ``stop_reason``: one of end_turn, stop_sequence, max_tokens,
      tool_use, refusal. Unknown values fall back to ``"stop"``.
    - ``usage``: dict with input_tokens, output_tokens, and
      cache_*_input_tokens (Anthropic-shaped names).

    Cost is omitted (Max subscription quota is opaque to the API
    surface — see ADR-002).

    Raises:
        PermanentProviderError: JSON malformed, content not a list,
            or a tool_use block fails ToolCall validation. The CLI
            is internal infrastructure; format errors are bugs we
            want loud, not silent fallbacks.
    """
    try:
        data: Any = json.loads(raw_stdout)
    except json.JSONDecodeError as e:
        raise PermanentProviderError(f"claude code output is not valid JSON: {e}") from e

    if not isinstance(data, dict):
        raise PermanentProviderError(
            f"claude code output must be a JSON object, got {type(data).__name__}"
        )

    content_blocks = data.get("content", [])
    if not isinstance(content_blocks, list):
        raise PermanentProviderError(
            f"expected 'content' to be a list, got {type(content_blocks).__name__}"
        )

    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text", "")
            if isinstance(text, str):
                text_parts.append(text)
        elif block_type == "tool_use":
            try:
                tool_calls.append(
                    ToolCall(
                        id=str(block.get("id", "")),
                        name=str(block.get("name", "")),
                        arguments=block.get("input") or {},
                    )
                )
            except ValidationError as e:
                raise PermanentProviderError(f"malformed tool_use block: {e}") from e

    cli_stop = data.get("stop_reason", "end_turn")
    if not isinstance(cli_stop, str):
        cli_stop = "end_turn"
    finish_reason = _STOP_REASON_MAP.get(cli_stop, "stop")

    usage_data = data.get("usage", {})
    if not isinstance(usage_data, dict):
        usage_data = {}
    usage = Usage(
        input_tokens=int(usage_data.get("input_tokens", 0) or 0),
        output_tokens=int(usage_data.get("output_tokens", 0) or 0),
        cache_read_tokens=int(usage_data.get("cache_read_input_tokens", 0) or 0),
        cache_creation_tokens=int(usage_data.get("cache_creation_input_tokens", 0) or 0),
        cost_usd=None,
    )

    try:
        return LLMResponse(
            request_id=request_id,
            content="\n".join(text_parts),
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
            f"failed to construct LLMResponse from claude code output: {e}"
        ) from e
