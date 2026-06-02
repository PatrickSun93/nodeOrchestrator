"""Tagging producer — propose descriptive topic_tags for a hypothesis via LLM.

Per ADR-022 D3 + D6: this is a content-gen leaf consumer. It proposes
*raw descriptive* tags; it never selects, ranks, gates, or actuates
promotion. resolve_tags normalization and run_matcher grouping are the
caller's responsibility.

The c1 structural guard (tests/producers/test_constitution.py) verifies at
CI that this file contains no selection/promotion/gate symbols:
run_matcher, promote_hypothesis, list_promotion_candidates,
candidate_for_promotion.
"""

from __future__ import annotations

import json
from typing import Protocol

from orchestrator.core.event import Event
from orchestrator.llm.purposes import LLMPurpose
from orchestrator.llm.types import (
    LLMRequest,
    LLMResponse,
    Message,
    generate_request_id,
)
from orchestrator.memory.schema import Hypothesis


class LLMRouterProtocol(Protocol):
    """Synchronous LLM call interface for the tagging producer."""

    def call(self, request: LLMRequest) -> LLMResponse: ...


def propose_hypothesis_tags(
    hypothesis: Hypothesis,
    source_events: list[Event],
    *,
    llm_router: LLMRouterProtocol,
) -> list[str]:
    """Propose descriptive topic_tags for *hypothesis* via LLM content-gen.

    Content-gen only (ADR-022 D6, LLMPurpose.HYPOTHESIS_TAG_PROPOSAL).
    The LLM describes; it never selects, ranks, gates, or actuates promotion.
    Sync + typed LLMRouterProtocol per the project-wide convention
    (agents/dispatch + reentry/render).

    Args:
        hypothesis: The hypothesis to tag.
        source_events: The events that contributed to this hypothesis.
        llm_router: A synchronous LLMRouterProtocol implementation.
            Model selection and fallback are handled by the router.

    Returns:
        A non-empty list of raw descriptive tag strings as proposed by
        the LLM. Caller is responsible for normalize + resolve_tags.
        The list is split on commas/newlines and stripped.

    Note:
        This function is a leaf content-gen consumer. It MUST NOT reference
        run_matcher, promote_hypothesis, list_promotion_candidates, or
        candidate_for_promotion. The c1 structural guard in
        tests/producers/test_constitution.py enforces this at CI.
    """
    payload = {
        "hypothesis": hypothesis.content,
        "source_event_excerpts": [
            {"author": evt.author, "content": evt.content[:300]} for evt in source_events
        ],
    }
    user_content = json.dumps(payload, ensure_ascii=False)

    request = LLMRequest(
        request_id=generate_request_id(),
        purpose=LLMPurpose.HYPOTHESIS_TAG_PROPOSAL,
        caller_agent_id=None,
        system=(
            "You are a tagger. Given a hypothesis and its supporting events, "
            "output a comma-separated list of concise descriptive topic tags "
            "(2-6 tags). Tags should be short noun phrases or keywords "
            "(e.g., 'quantum mechanics', 'energy levels', 'physics'). "
            "Output ONLY the comma-separated list - no explanation, "
            "no numbering, no bullet points."
        ),
        messages=[Message(role="user", content=user_content)],
    )

    response = llm_router.call(request)

    raw_output = response.content
    parts = [part.strip() for part in raw_output.replace("\n", ",").split(",") if part.strip()]
    return parts
