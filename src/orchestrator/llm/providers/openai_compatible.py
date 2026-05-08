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

from dataclasses import dataclass, field

from orchestrator.llm.types import (
    LLMRequest,
    LLMResponse,
    ModelProfile,
    ProviderId,
)


@dataclass
class OpenAICompatibleProvider:
    """An OpenAI Chat-Completions-shaped provider.

    Constructed by ``config_loader`` from one ``ProviderConnection``
    entry. ``api_key_env`` is the env var name to read the key from;
    empty string means no auth header (e.g., local Ollama).
    """

    provider_id: ProviderId
    base_url: str
    api_key_env: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)
    timeout_s: float = 60.0

    def can_use_orchestrator_tools(self) -> bool:
        return True

    def health_check(self) -> bool:
        """HEAD or short GET to ``{base_url}/models``. Returns False
        on connection errors, 4xx, or 5xx — does NOT raise."""
        raise NotImplementedError

    def call(self, request: LLMRequest, model: ModelProfile) -> LLMResponse:
        """Translate ``LLMRequest`` into Chat Completions format,
        POST to ``{base_url}/chat/completions``, parse response.

        Maps:
        - ``messages`` and ``system`` → OpenAI ``messages``.
        - ``tools`` → ``tools`` (ignored if model lacks the capability).
        - ``temperature``, ``max_tokens``, ``extra_params`` →
          top-level params.
        - Response ``choices[0].message.content`` → ``content``.
        - Response ``choices[0].message.tool_calls`` → ``tool_calls``.
        - Response ``usage`` → ``Usage`` (cost computed from model
          profile pricing if available).

        ``effort_level`` is silently dropped (only Claude Code honors it).

        Errors:
        - 401/403 → ``PermanentProviderError``.
        - 429 → ``TransientProviderError``.
        - 5xx, timeouts, connection errors → ``TransientProviderError``.
        - 400 with non-recoverable body → ``PermanentProviderError``.
        """
        raise NotImplementedError
