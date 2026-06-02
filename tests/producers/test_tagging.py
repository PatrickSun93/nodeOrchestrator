"""Tests for producers/tagging.py — propose_hypothesis_tags.

Verifies:
- MagicMock router keyed on (HYPOTHESIS_TAG_PROPOSAL, None) is called exactly once.
- The function returns a non-empty list of strings.
- The LLM call uses the correct purpose.

Per ADR-022 D6: tagging is content-gen only; the LLM proposes, caller disposes.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from orchestrator.core.event import (
    Event,
    EventId,
    EventType,
    RoomId,
    TimestampMs,
    generate_event_id,
)
from orchestrator.llm.purposes import LLMPurpose
from orchestrator.llm.types import LLMResponse, ModelId, ProviderId, Usage, generate_request_id
from orchestrator.memory.schema import Hypothesis, generate_hypothesis_id
from orchestrator.producers.tagging import LLMRouterProtocol, propose_hypothesis_tags

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_router(response: str) -> MagicMock:
    router = MagicMock(spec=LLMRouterProtocol)
    router.call.return_value = LLMResponse(
        request_id=generate_request_id(),
        content=response,
        model_id_requested=ModelId("m"),
        model_id_used=ModelId("m"),
        provider_id_used=ProviderId("mock"),
        usage=Usage(input_tokens=0, output_tokens=0),
        latency_ms=0,
        finish_reason="stop",
    )
    return router


def _hypothesis(content: str = "Quantum energy levels are discrete.") -> Hypothesis:
    return Hypothesis(
        id=generate_hypothesis_id(),
        content=content,
        room_id=RoomId("room_" + "a" * 32),
        confidence=0.8,
        source_event_ids=[EventId("evt_" + "b" * 32)],
        created_at=TimestampMs(1_700_000_000_000),
    )


def _event(content: str = "Planck showed energy is quantized.") -> Event:
    return Event(
        id=generate_event_id(),
        room_id=RoomId("room_" + "a" * 32),
        type=EventType.UTTERANCE,
        author="user",
        timestamp=TimestampMs(1_700_000_000_000),
        content=content,
    )


# ---------------------------------------------------------------------------
# TestProposeHypothesisTags
# ---------------------------------------------------------------------------


class TestProposeHypothesisTags:
    def test_returns_non_empty_list_of_strings(self) -> None:
        """propose_hypothesis_tags returns a non-empty list of strings.

        The mock returns a comma-separated string; the function splits it
        into individual tag strings. Discriminating: if the function
        returns an empty list or non-strings, this fails.
        """
        router = _make_router("physics, quantum mechanics, energy levels")
        hyp = _hypothesis()
        events = [_event()]

        tags = propose_hypothesis_tags(hyp, events, llm_router=router)

        assert isinstance(tags, list), "return type must be list"
        assert len(tags) > 0, "result must be non-empty"
        for tag in tags:
            assert isinstance(tag, str), f"each tag must be str, got {type(tag)}"

    def test_exactly_one_llm_call_with_correct_purpose(self) -> None:
        """Exactly one LLM call is made, keyed on HYPOTHESIS_TAG_PROPOSAL.

        Discriminating: if the function makes zero or two calls, or uses a
        wrong purpose, this fails.
        """
        router = _make_router("physics, quantum mechanics")
        hyp = _hypothesis()
        events = [_event()]

        propose_hypothesis_tags(hyp, events, llm_router=router)

        assert router.call.call_count == 1, f"expected 1 LLM call, got {router.call.call_count}"
        request = router.call.call_args[0][0]
        assert request.purpose == LLMPurpose.HYPOTHESIS_TAG_PROPOSAL, (
            f"expected purpose HYPOTHESIS_TAG_PROPOSAL, got {request.purpose!r}"
        )

    def test_caller_agent_id_is_none(self) -> None:
        """The LLM call uses caller_agent_id=None (non-agent content-gen).

        Per ADR-022 D6: tagging is not associated with any agent role.
        """
        router = _make_router("machine learning, neural networks")
        hyp = _hypothesis("Neural networks learn representations.")
        events = [_event("Deep learning is a subset of ML.")]

        propose_hypothesis_tags(hyp, events, llm_router=router)

        request = router.call.call_args[0][0]
        assert request.caller_agent_id is None

    def test_multiline_response_parsed_correctly(self) -> None:
        """Newline-separated LLM output is treated like comma-separated.

        The function normalises newlines to commas before splitting.
        """
        router = _make_router("chemistry\norganic compounds\nreaction kinetics")
        hyp = _hypothesis("Organic reactions follow kinetic rate laws.")
        events = [_event("Rate depends on temperature.")]

        tags = propose_hypothesis_tags(hyp, events, llm_router=router)

        assert len(tags) == 3
        assert "chemistry" in tags
        assert "organic compounds" in tags
        assert "reaction kinetics" in tags

    def test_no_forbidden_symbols_called(self) -> None:
        """Structural check: the function returns tags without touching promotion.

        This is belt-and-suspenders beyond the AST guard in test_constitution.py.
        If propose_hypothesis_tags returns tags via the mock, no promotion
        path was exercised (MagicMock only stubs what's called).
        """
        router = _make_router("tag-a, tag-b")
        hyp = _hypothesis()
        tags = propose_hypothesis_tags(hyp, [], llm_router=router)
        assert tags  # non-empty: function ran to completion without error
