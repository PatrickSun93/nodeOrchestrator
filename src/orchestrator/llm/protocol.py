"""LLMProvider Protocol.

Each provider implementation (``openai_compatible``, ``claude_code_cli``,
``mock``) satisfies this protocol structurally. The router uses the
Protocol type; concrete classes are instantiated by ``config_loader``
based on each ``ProviderConnection.type``.

Sync interface — see ``llm-layer.md`` §"Why sync, not async". Briefly:
P1's call sites are sequential within an agent's turn; concurrent
calls (when needed) can run providers in a thread pool without
contaminating the rest of the codebase with async.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from orchestrator.llm.types import (
    LLMRequest,
    LLMResponse,
    ModelProfile,
    ProviderId,
)


@runtime_checkable
class LLMProvider(Protocol):
    """A provider implementation. See module docstring."""

    @property
    def provider_id(self) -> ProviderId:
        """The id from ``llm_providers.yaml`` this instance was built
        for. Used in ``LLMResponse.provider_id_used`` for audit."""
        ...

    def can_use_orchestrator_tools(self) -> bool:
        """Whether this provider accepts ``LLMRequest.tools``.

        - ``openai_compatible``: returns True (tool-aware models like
          DeepSeek, certain Ollama/MLX setups).
        - ``claude_code_cli``: returns False — the CLI ships with its
          own tool ecosystem and cannot accept third-party tool
          definitions; see ADR-003.
        - ``mock``: configurable per instance, defaults True.

        The router uses this to skip incompatible (model, provider)
        combinations and ``config_loader.validate_full_config``
        catches mismatches at startup.
        """
        ...

    def health_check(self) -> bool:
        """Quick availability probe. Should be cheap (sub-second).

        - ``openai_compatible``: HTTP HEAD or short GET to ``/v1/models``.
        - ``claude_code_cli``: ``claude --version`` subprocess.
        - ``mock``: configurable; defaults True.

        A False return causes the router to skip this provider in the
        fallback chain. Implementations should NOT raise — wrap their
        own exceptions and return False.
        """
        ...

    def call(self, request: LLMRequest, model: ModelProfile) -> LLMResponse:
        """Execute one LLM request against ``model`` via this provider.

        Provider responsibilities:

        - Translate ``LLMRequest`` into the provider's wire format.
        - Call the provider API/CLI.
        - Translate the response back to ``LLMResponse``, including
          ``model_id_used``, ``provider_id_used``, ``usage``,
          ``latency_ms``, and ``finish_reason``.
        - Categorize errors as ``Transient``/``Permanent``/``Unhealthy``
          via the exceptions in ``orchestrator.llm.exceptions``.

        Provider non-responsibilities (these belong elsewhere):

        - Routing/fallback (``router.py`` handles).
        - Tool execution (agent runtime, P1.3).
        - Recording the call in the event log (agent runtime).
        - Cost accounting beyond reporting ``Usage``.

        Should not raise out-of-band exceptions; only the LLM layer's
        ``ProviderError`` subclasses are expected to escape.
        """
        ...
