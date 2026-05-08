"""Parser for Claude Code CLI output.

Claude Code's ``--output-format json`` produces a structured envelope
with content, tool calls (if any — though we currently configure no
tools through this provider), and usage. This module translates that
envelope into our ``LLMResponse``.

Why a dedicated module: the CLI's output schema may evolve faster
than its provider behavior. Isolating the parser lets us upgrade
the wire-format independently of routing/health logic, and keeps
the parser unit-testable against recorded fixture output.
"""

from __future__ import annotations

from orchestrator.llm.types import (
    LLMResponse,
    ModelId,
    ProviderId,
    RequestId,
)


def parse_claude_code_output(
    raw_stdout: str,
    request_id: RequestId,
    model_id_requested: ModelId,
    model_id_used: ModelId,
    provider_id: ProviderId,
    latency_ms: int,
) -> LLMResponse:
    """Parse ``claude --output-format json`` stdout into an LLMResponse.

    The CLI emits a single JSON object per call. Expected fields
    (subject to upgrade — see fixtures in ``tests/llm/recordings/``):

    - ``content``: the assistant's text.
    - ``model``: which model actually ran (may differ from request).
    - ``stop_reason``: one of stop, max_tokens, tool_use, error.
    - ``usage.input_tokens``, ``usage.output_tokens``,
      ``usage.cache_read_input_tokens``,
      ``usage.cache_creation_input_tokens``.

    Cost is omitted (Max subscription quota is opaque).

    Raises:
        PermanentProviderError: JSON malformed or missing required
            fields. The CLI is internal infrastructure; format errors
            are bugs we want loud, not silent fallbacks.
    """
    raise NotImplementedError
