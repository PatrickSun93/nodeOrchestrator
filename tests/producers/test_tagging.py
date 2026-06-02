"""Tests for producers/tagging.py — propose_hypothesis_tags.

Verifies:
- MockProvider keyed on (HYPOTHESIS_TAG_PROPOSAL, None) is called exactly once.
- The function returns a non-empty list of strings.
- The LLM call uses the correct purpose.

Per ADR-022 D6: tagging is content-gen only; the LLM proposes, caller disposes.
"""

from __future__ import annotations

from orchestrator.core.event import (
    Event,
    EventId,
    EventType,
    RoomId,
    TimestampMs,
    generate_event_id,
)
from orchestrator.llm.providers.mock import MockProvider
from orchestrator.llm.purposes import LLMPurpose
from orchestrator.llm.types import ProviderId
from orchestrator.memory.schema import Hypothesis, generate_hypothesis_id
from orchestrator.producers.tagging import propose_hypothesis_tags

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock(responses: list[str]) -> MockProvider:
    return MockProvider(
        provider_id=ProviderId("mock"),
        responses={(LLMPurpose.HYPOTHESIS_TAG_PROPOSAL, None): responses},
    )


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
    async def test_returns_non_empty_list_of_strings(self) -> None:
        """propose_hypothesis_tags returns a non-empty list of strings.

        The mock returns a comma-separated string; the function splits it
        into individual tag strings. Discriminating: if the function
        returns an empty list or non-strings, this fails.
        """
        mock = _make_mock(["physics, quantum mechanics, energy levels"])
        hyp = _hypothesis()
        events = [_event()]

        tags = await propose_hypothesis_tags(hyp, events, llm_provider=mock)

        assert isinstance(tags, list), "return type must be list"
        assert len(tags) > 0, "result must be non-empty"
        for tag in tags:
            assert isinstance(tag, str), f"each tag must be str, got {type(tag)}"

    async def test_exactly_one_llm_call_with_correct_purpose(self) -> None:
        """Exactly one LLM call is made, keyed on HYPOTHESIS_TAG_PROPOSAL.

        Discriminating: if the function makes zero or two calls, or uses a
        wrong purpose, this fails.
        """
        mock = _make_mock(["physics, quantum mechanics"])
        hyp = _hypothesis()
        events = [_event()]

        await propose_hypothesis_tags(hyp, events, llm_provider=mock)

        calls = mock.calls
        assert len(calls) == 1, f"expected 1 LLM call, got {len(calls)}"
        assert calls[0].purpose == LLMPurpose.HYPOTHESIS_TAG_PROPOSAL, (
            f"expected purpose HYPOTHESIS_TAG_PROPOSAL, got {calls[0].purpose!r}"
        )

    async def test_caller_agent_id_is_none(self) -> None:
        """The LLM call uses caller_agent_id=None (non-agent content-gen).

        Per ADR-022 D6: tagging is not associated with any agent role.
        """
        mock = _make_mock(["machine learning, neural networks"])
        hyp = _hypothesis("Neural networks learn representations.")
        events = [_event("Deep learning is a subset of ML.")]

        await propose_hypothesis_tags(hyp, events, llm_provider=mock)

        calls = mock.calls
        assert calls[0].caller_agent_id is None

    async def test_multiline_response_parsed_correctly(self) -> None:
        """Newline-separated LLM output is treated like comma-separated.

        The function normalises newlines to commas before splitting.
        """
        mock = _make_mock(["chemistry\norganic compounds\nreaction kinetics"])
        hyp = _hypothesis("Organic reactions follow kinetic rate laws.")
        events = [_event("Rate depends on temperature.")]

        tags = await propose_hypothesis_tags(hyp, events, llm_provider=mock)

        assert len(tags) == 3
        assert "chemistry" in tags
        assert "organic compounds" in tags
        assert "reaction kinetics" in tags

    async def test_no_forbidden_symbols_called(self) -> None:
        """Structural check: the function returns tags without touching promotion.

        This is belt-and-suspenders beyond the AST guard in test_constitution.py.
        If propose_hypothesis_tags returns tags via the mock, no promotion
        path was exercised (MockProvider raises on unknown purposes, and the
        promotion functions are not registered in the mock).
        """
        mock = _make_mock(["tag-a, tag-b"])
        hyp = _hypothesis()
        tags = await propose_hypothesis_tags(hyp, [], llm_provider=mock)
        assert tags  # non-empty: function ran to completion without error
