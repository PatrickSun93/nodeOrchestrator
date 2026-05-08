"""``MockProvider`` — deterministic LLM responses for tests.

Behavior: round-robin a list of canned responses, keyed on
``(purpose, caller_agent_id)``. If no responses are registered for a
specific key, falls back to ``(purpose, None)`` (purpose-only key).
If neither matches, raises ``MockResponseExhaustedError`` — tests should
register exactly the keys they exercise.

Why the tuple key (deviation from the original ``dict[LLMPurpose,
list[str]]`` proposal): with a single ``AGENT_RESPONSE`` purpose
covering all agent roles, tests for prober vs skeptic vs operator
need to inject different mock replies. The tuple key lets each test
specify ``(AGENT_RESPONSE, "agent:prober")`` and
``(AGENT_RESPONSE, "agent:skeptic")`` independently while
``(SNAPSHOT_SEMANTIC, None)`` works for non-agent calls.

Captured calls are kept on ``.calls`` for assertions
(prompt content, tool definitions sent, etc.).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from orchestrator.llm.exceptions import LLMError
from orchestrator.llm.purposes import LLMPurpose
from orchestrator.llm.types import (
    LLMRequest,
    LLMResponse,
    ModelProfile,
    ProviderId,
    Usage,
)

MockKey = tuple[LLMPurpose, str | None]
"""``(purpose, caller_agent_id)``. ``caller_agent_id == None`` is the
purpose-only fallback key."""


class MockResponseExhaustedError(LLMError):
    """No response was configured for this purpose/agent combination,
    or the registered list was used up. Tests should register enough
    responses for the call sequence they exercise."""


@dataclass
class MockProvider:
    """A test-only ``LLMProvider``.

    Construct with a mapping from ``(purpose, caller_agent_id)`` to a
    list of canned response strings. Each ``call()`` advances the
    round-robin cursor for the matched key.

    The class is a dataclass for trivial test setup; the protocol
    surface (``provider_id``, ``can_use_orchestrator_tools``,
    ``health_check``, ``call``) matches ``LLMProvider``.
    """

    provider_id: ProviderId
    responses: dict[MockKey, list[str]] = field(default_factory=dict)

    can_use_tools: bool = True
    """Tests can flip this to assert behavior when a provider rejects
    tools (e.g., simulating Claude Code routing)."""

    healthy: bool = True
    """Flip to False to test the router skipping unhealthy providers."""

    _cursors: dict[MockKey, int] = field(
        default_factory=lambda: defaultdict(int), init=False, repr=False
    )
    _calls: list[LLMRequest] = field(default_factory=list, init=False, repr=False)

    def can_use_orchestrator_tools(self) -> bool:
        return self.can_use_tools

    def health_check(self) -> bool:
        return self.healthy

    async def call(self, request: LLMRequest, model: ModelProfile) -> LLMResponse:
        """Record the call, look up a canned response, and return.

        Lookup order:
        1. ``(request.purpose, request.caller_agent_id)`` exact match.
        2. ``(request.purpose, None)`` purpose-only fallback.
        3. Raise ``MockResponseExhaustedError``.

        Round-robin cursor is per matched key — once exact match is
        chosen, cursor advances on that key, never falling through to
        the fallback. Per-agent stories don't bleed into each other.

        Exhausting the list raises ``MockResponseExhaustedError`` —
        registered list length is the test's stated expectation, so
        going past it indicates a test that hasn't fully thought
        through the call sequence.
        """
        self._calls.append(request)

        exact = (request.purpose, request.caller_agent_id)
        fallback = (request.purpose, None)

        matched_key: MockKey | None = None
        if exact in self.responses:
            matched_key = exact
        elif fallback in self.responses:
            matched_key = fallback

        if matched_key is None:
            raise MockResponseExhaustedError(
                f"no canned responses registered for "
                f"purpose={request.purpose.value!r} "
                f"caller_agent_id={request.caller_agent_id!r}"
            )

        response_list = self.responses[matched_key]
        cursor = self._cursors[matched_key]
        if cursor >= len(response_list):
            raise MockResponseExhaustedError(
                f"canned responses exhausted for matched_key={matched_key}: "
                f"{len(response_list)} response(s) registered, "
                f"this would be call #{cursor + 1}"
            )

        content = response_list[cursor]
        self._cursors[matched_key] = cursor + 1

        return LLMResponse(
            request_id=request.request_id,
            content=content,
            tool_calls=[],
            model_id_requested=model.id,
            model_id_used=model.id,
            provider_id_used=self.provider_id,
            usage=Usage(input_tokens=0, output_tokens=0),
            latency_ms=0,
            finish_reason="stop",
        )

    @property
    def calls(self) -> list[LLMRequest]:
        """Captured request log for test assertions."""
        return list(self._calls)
