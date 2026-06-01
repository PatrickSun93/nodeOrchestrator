"""Content-gen LLM render + top-level reenter() entry point. Per ADR-021 D4.

render_reentry_prose: the ONLY LLM call in re-entry assembly.
  Receives the frozen ReentryDigest (already-selected, already-ordered by code)
  and phrases it into natural-language prose. It adds no facts.
  Uses LLMPurpose.REENTRY_DIGEST_RENDER (content-gen, ADR-021 D4/D9).

reenter: top-level entry point composing assemble_reentry → render_reentry_prose
  into a ReentryResult. Per ADR-021 D4.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Protocol

from orchestrator.core.event import Event, RoomId, TimestampMs
from orchestrator.core.room import Room
from orchestrator.llm.purposes import LLMPurpose
from orchestrator.llm.types import LLMRequest, LLMResponse, Message, generate_request_id
from orchestrator.reentry.digest import assemble_reentry
from orchestrator.reentry.schema import ReentryDigest, ReentryResult


class LLMRouterProtocol(Protocol):
    """Synchronous LLM call interface for the re-entry render surface."""

    def call(self, request: LLMRequest) -> LLMResponse: ...


def render_reentry_prose(
    digest: ReentryDigest,
    *,
    llm_router: LLMRouterProtocol,
) -> str:
    """Phrase the frozen ReentryDigest into a welcome-back prose string.

    Content-gen only — the digest's selection/ordering was done by
    assemble_reentry. This function phrases; it does not choose.
    Uses LLMPurpose.REENTRY_DIGEST_RENDER, caller_agent_id=None.
    Per ADR-021 D4.
    """
    digest_payload = json.dumps(
        {
            "room_id": str(digest.room_id),
            "archive_title": digest.archive.title if digest.archive else None,
            "recalled_knowledge": [vk.content for vk in digest.recalled_knowledge],
            "entities": [e.attributes for e in digest.entities],
            "preferences": [p.attributes for p in digest.preferences],
            "new_since_leave": [
                {"fact_type": item.fact_type, "label": item.label}
                for item in digest.new_since_leave
            ],
            "last_seen_ts": digest.last_seen_ts,
        },
        ensure_ascii=False,
    )
    request = LLMRequest(
        request_id=generate_request_id(),
        purpose=LLMPurpose.REENTRY_DIGEST_RENDER,
        caller_agent_id=None,
        system=(
            "You are writing a warm welcome-back message for a user returning to a room. "
            "Phrase ONLY the facts provided in the user message into natural-language prose. "
            "Do NOT add any facts, inferences, or advice not present in the input. "
            "Keep it concise (2-4 sentences) and conversational."
        ),
        messages=[Message(role="user", content=digest_payload)],
    )
    response = llm_router.call(request)
    return response.content


def reenter(
    room_id: RoomId,
    user_id: str,
    *,
    conn: sqlite3.Connection,
    llm_router: LLMRouterProtocol,
    events: list[Event],
    room: Room,
    now: TimestampMs,
) -> ReentryResult:
    """Full re-entry: assemble deterministic digest → render prose. Per ADR-021 D4."""
    digest = assemble_reentry(
        room_id,
        user_id,
        conn=conn,
        events=events,
        room=room,
        now=now,
    )
    prose = render_reentry_prose(digest, llm_router=llm_router)
    return ReentryResult(digest=digest, prose=prose)
