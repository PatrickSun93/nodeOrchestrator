"""OpenAI-compatible provider for DeepSeek, Ollama, MLX, OpenAI itself.

Many providers implement the OpenAI Chat Completions API or close
variants. This single class handles all of them, parameterized by
``base_url`` and ``api_key_env`` from the ProviderConnection.

Quirks per backend (Ollama's ``/api/chat`` vs OpenAI's
``/v1/chat/completions``, DeepSeek's strict mode flags, MLX's
trimmed feature set) are handled inside ``call()``'s wire-format
translation. The intent is one provider class for everything that
speaks "Chat Completions-shaped"; new backends usually just need an
``llm_providers.yaml`` entry.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import ValidationError

from orchestrator.llm.exceptions import (
    PermanentProviderError,
    TransientProviderError,
)
from orchestrator.llm.types import (
    LLMRequest,
    LLMResponse,
    ModelId,
    ModelProfile,
    ProviderId,
    ToolCall,
    Usage,
)

_FINISH_REASON_MAP: dict[str, str] = {
    "stop": "stop",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "content_filter": "content_filter",
    "function_call": "tool_use",
}


@dataclass
class OpenAICompatibleProvider:
    """An OpenAI Chat-Completions-shaped provider.

    Constructed by ``config_loader`` from one ``ProviderConnection``
    entry. ``api_key_env`` is the env var name to read the key from;
    empty string means no auth header (e.g., local Ollama).

    The ``transport`` field is a test-only injection point — pass
    ``httpx.MockTransport(handler)`` from tests to intercept network
    calls without contacting a real endpoint. Production yaml does
    not (and should not) set this field.
    """

    provider_id: ProviderId
    base_url: str
    api_key_env: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)
    timeout_s: float = 60.0
    transport: Any = None

    def __post_init__(self) -> None:
        # Construction-time validation, narrow scope: this guards the
        # ``Any``-typed ``transport`` backdoor specifically. The other
        # dataclass fields rely on Python's type-erasure-at-runtime
        # convention; mistyped strings or numbers in those fields will
        # surface at first use, not at construction. That trade-off is
        # accepted because (a) yaml loading goes through Pydantic via
        # other paths in the loader, (b) full-field __post_init__ would
        # duplicate Pydantic-style validation here without justification.
        # The ``transport`` field is the exception because its ``Any``
        # type silently accepts anything — including a yaml literal.
        if self.transport is not None and not isinstance(self.transport, httpx.BaseTransport):
            raise TypeError(
                f"OpenAICompatibleProvider.transport must be httpx.BaseTransport "
                f"or None; got {type(self.transport).__name__}"
            )

    def can_use_orchestrator_tools(self) -> bool:
        return True

    def health_check(self) -> bool:
        """Short GET to ``{base_url}/models``. Returns False on
        connection errors, 4xx, or 5xx — does NOT raise.

        Some endpoints (Ollama) don't always implement ``/models``;
        treating any 4xx as unhealthy may be too strict. We accept
        2xx as healthy and treat everything else as unhealthy. If
        a backend turns out to need looser semantics, override per
        instance.
        """
        headers: dict[str, str] = dict(self.extra_headers)
        if self.api_key_env:
            api_key = os.environ.get(self.api_key_env, "")
            if not api_key:
                return False
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            with httpx.Client(timeout=5.0, transport=self.transport) as client:
                response = client.get(
                    f"{self.base_url.rstrip('/')}/models",
                    headers=headers,
                )
        except (httpx.HTTPError, OSError):
            return False
        return 200 <= response.status_code < 300

    async def call(
        self,
        request: LLMRequest,
        model: ModelProfile,
        *,
        model_id_requested: ModelId,
    ) -> LLMResponse:
        """Translate ``LLMRequest`` into Chat Completions format,
        POST to ``{base_url}/chat/completions`` via
        ``httpx.AsyncClient``, parse response.

        Maps:
        - ``messages`` and ``system`` → OpenAI ``messages`` array.
        - ``tools`` → top-level ``tools`` (ignored if model lacks
          the capability — but capability filtering happens at the
          router, not here).
        - ``temperature``, ``max_tokens``, ``extra_params`` →
          top-level params.

        ``extra_params`` is an escape hatch for backend-specific knobs
        (e.g., a vendor's ``response_format`` flag). Reserved fields —
        ``model``, ``messages``, ``tools`` — should NOT be overridden
        via ``extra_params``; doing so produces **unspecified
        behavior** (current implementation may overwrite, future
        implementations may reject or ignore). Most callers should
        leave this empty.
        - Response ``choices[0].message.content`` → ``content``.
        - Response ``choices[0].message.tool_calls`` → ``tool_calls``.
        - Response ``usage.prompt_tokens / completion_tokens`` →
          ``Usage.input_tokens / output_tokens``.

        ``effort_level`` is silently dropped — OpenAI-Chat-Completions-
        shaped backends don't honor it. Use ``claude_code_cli`` for
        effort-honoring routes.

        Errors:
        - 401/403 → ``PermanentProviderError`` (auth bug; do not fall
          back).
        - 429 → ``TransientProviderError`` (rate-limited; router may
          try fallback).
        - 5xx, timeouts, network errors → ``TransientProviderError``.
        - 4xx (other) → ``PermanentProviderError`` (malformed
          request).
        """
        start = time.perf_counter()

        # Build messages
        messages: list[dict[str, Any]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        for msg in request.messages:
            entry: dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            messages.append(entry)

        payload: dict[str, Any] = {
            "model": model.provider_model_id,
            "messages": messages,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    },
                }
                for t in request.tools
            ]
        for key, value in request.extra_params.items():
            payload[key] = value

        headers: dict[str, str] = dict(self.extra_headers)
        headers["Content-Type"] = "application/json"
        if self.api_key_env:
            api_key = os.environ.get(self.api_key_env, "")
            if not api_key:
                raise PermanentProviderError(f"env var {self.api_key_env!r} is empty or unset")
            headers["Authorization"] = f"Bearer {api_key}"

        url = f"{self.base_url.rstrip('/')}/chat/completions"

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_s,
                transport=self.transport,
            ) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as e:
            raise TransientProviderError(f"timeout calling {url}: {e}") from e
        except (httpx.NetworkError, OSError) as e:
            raise TransientProviderError(f"network error: {e}") from e

        latency_ms = int((time.perf_counter() - start) * 1000)

        if response.status_code in (401, 403):
            raise PermanentProviderError(
                f"auth failed ({response.status_code}): {response.text[:500]}"
            )
        if response.status_code == 429:
            raise TransientProviderError(f"rate limited (429): {response.text[:500]}")
        if response.status_code >= 500:
            raise TransientProviderError(
                f"server error ({response.status_code}): {response.text[:500]}"
            )
        if response.status_code >= 400:
            raise PermanentProviderError(
                f"client error ({response.status_code}): {response.text[:500]}"
            )

        try:
            data = response.json()
        except ValueError as e:
            raise PermanentProviderError(f"non-JSON response from {url}: {e}") from e

        return _parse_chat_completion(
            data,
            request,
            model,
            self.provider_id,
            latency_ms,
            model_id_requested=model_id_requested,
        )


def _parse_chat_completion(
    data: dict[str, Any],
    request: LLMRequest,
    model: ModelProfile,
    provider_id: ProviderId,
    latency_ms: int,
    *,
    model_id_requested: ModelId,
) -> LLMResponse:
    """Translate one OpenAI Chat Completions response to LLMResponse."""
    try:
        choices = data["choices"]
        if not choices:
            raise PermanentProviderError("response 'choices' is empty")
        message = choices[0]["message"]
    except (KeyError, IndexError, TypeError) as e:
        raise PermanentProviderError(
            f"unexpected response shape: {e}; data keys: "
            f"{list(data.keys()) if isinstance(data, dict) else type(data).__name__}"
        ) from e

    content = message.get("content") or ""
    tool_calls: list[ToolCall] = []
    for tc in message.get("tool_calls") or []:
        try:
            args_raw = tc["function"]["arguments"]
            # Empty/blank string means "no parameters" (OpenAI-compat no-arg convention).
            # Only run json.loads on a non-blank string; empty/blank str → {}; non-str falsy → {}.
            if isinstance(args_raw, str):
                arguments = json.loads(args_raw) if args_raw.strip() else {}
            else:
                arguments = args_raw or {}
            tool_calls.append(
                ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=arguments,
                )
            )
        except (KeyError, json.JSONDecodeError, ValidationError) as e:
            raise PermanentProviderError(f"malformed tool_call: {e}") from e

    finish_reason_raw = choices[0].get("finish_reason", "stop")
    finish_reason = _FINISH_REASON_MAP.get(finish_reason_raw, "stop")

    usage_data = data.get("usage") or {}
    input_tokens = int(usage_data.get("prompt_tokens", 0))
    output_tokens = int(usage_data.get("completion_tokens", 0))
    cost: float | None = None
    if model.cost_per_1m_input is not None and model.cost_per_1m_output is not None:
        cost = (
            input_tokens * model.cost_per_1m_input / 1_000_000.0
            + output_tokens * model.cost_per_1m_output / 1_000_000.0
        )

    usage = Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
    )

    try:
        return LLMResponse(
            request_id=request.request_id,
            content=content,
            tool_calls=tool_calls,
            model_id_requested=model_id_requested,
            model_id_used=model.id,
            provider_id_used=provider_id,
            usage=usage,
            latency_ms=latency_ms,
            finish_reason=finish_reason,  # type: ignore[arg-type]
        )
    except ValidationError as e:
        raise PermanentProviderError(f"failed to construct LLMResponse: {e}") from e
