"""Tests for reentry/render.py — render_reentry_prose + reenter.

Coverage standard:
  §1 cross-module — reenter composes assemble_reentry → render_reentry_prose
     → ReentryResult. The digest (code-selected) and the prose (LLM) are
     distinct outputs; source (assemble_reentry) ≠ sink (render result).
  §6 N/A — ReentryResult schema tested in test_schema.py.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

from orchestrator.core.event import (
    Event,
    EventType,
    TimestampMs,
    generate_event_id,
    generate_room_id,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.llm.purposes import LLMPurpose
from orchestrator.llm.types import LLMResponse, ModelId, ProviderId, Usage, generate_request_id
from orchestrator.memory.store import init_memory_schema
from orchestrator.reentry.render import LLMRouterProtocol, reenter, render_reentry_prose
from orchestrator.reentry.schema import ReentryDigest, ReentryResult
from orchestrator.reentry.store import init_reentry_schema

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_full_store() -> tuple[EventStore, sqlite3.Connection]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = EventStore(conn)
    store.init_schema()
    init_memory_schema(conn)
    init_reentry_schema(conn)
    return store, conn


def _mock_router(prose: str) -> MagicMock:
    router = MagicMock(spec=LLMRouterProtocol)
    router.call.return_value = LLMResponse(
        request_id=generate_request_id(),
        content=prose,
        model_id_requested=ModelId("m1"),
        model_id_used=ModelId("m1"),
        provider_id_used=ProviderId("mock"),
        usage=Usage(input_tokens=5, output_tokens=15),
        latency_ms=3,
        finish_reason="stop",
    )
    return router


def _bare_digest(room_id: None = None) -> ReentryDigest:
    return ReentryDigest(
        room_id=generate_room_id(),
        archive=None,
        recalled_knowledge=[],
        entities=[],
        preferences=[],
        new_since_leave=[],
        last_seen_ts=None,
        generated_at=TimestampMs(1000),
    )


def _seed_room(store: EventStore) -> tuple[Room, Event]:
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    evt = Event(
        id=generate_event_id(),
        room_id=room.id,
        type=EventType.UTTERANCE,
        author="user",
        timestamp=TimestampMs(1000),
        content="hello",
    )
    store.append(evt)
    return room, evt


# ---------------------------------------------------------------------------
# render_reentry_prose
# ---------------------------------------------------------------------------


def test_render_reentry_prose_uses_reentry_digest_render_purpose() -> None:
    """render_reentry_prose calls LLM with REENTRY_DIGEST_RENDER purpose.

    Discriminating: fails if wrong purpose or no LLM call.
    """
    digest = _bare_digest()
    router = _mock_router("Welcome back! Nothing new.")

    result = render_reentry_prose(digest, llm_router=router)

    router.call.assert_called_once()
    request = router.call.call_args[0][0]
    assert request.purpose == LLMPurpose.REENTRY_DIGEST_RENDER
    assert request.caller_agent_id is None
    assert result == "Welcome back! Nothing new."


def test_render_reentry_prose_returns_llm_content() -> None:
    """The return value is exactly the LLM response content (not hardcoded).

    Discriminating: uses a custom prose string and asserts exact match.
    """
    digest = _bare_digest()
    expected = "Custom prose from LLM render."
    router = _mock_router(expected)

    prose = render_reentry_prose(digest, llm_router=router)
    assert prose == expected


def test_render_reentry_prose_wording_not_asserted() -> None:
    """Any non-empty prose from the LLM is accepted (wording is LLM output).

    Per plan P2.5-5: the prose render is exercised but exact wording not asserted.
    """
    digest = _bare_digest()
    router = _mock_router("AI 记得你!")
    prose = render_reentry_prose(digest, llm_router=router)
    assert isinstance(prose, str)
    assert len(prose) > 0


def test_render_reentry_prose_digest_fed_to_llm() -> None:
    """The digest's facts are serialized into the LLM message payload.

    The digest is the only source for the LLM — it adds no facts.
    Discriminating: fails if the request messages list is empty.
    """
    digest = _bare_digest()
    router = _mock_router("ok")
    render_reentry_prose(digest, llm_router=router)

    request = router.call.call_args[0][0]
    assert len(request.messages) >= 1
    user_msg = next((m for m in request.messages if m.role == "user"), None)
    assert user_msg is not None, "LLM must receive the digest as a user message"


# ---------------------------------------------------------------------------
# reenter (top-level)
# ---------------------------------------------------------------------------


def test_reenter_returns_reentry_result() -> None:
    """reenter returns a ReentryResult with both digest and prose."""
    store, conn = _make_full_store()
    room, evt = _seed_room(store)
    router = _mock_router("Welcome back!")

    result = reenter(
        room.id,
        "user1",
        conn=conn,
        llm_router=router,
        events=[evt],
        room=room,
        now=TimestampMs(9999),
    )
    assert isinstance(result, ReentryResult)
    assert result.prose == "Welcome back!"
    assert isinstance(result.digest, ReentryDigest)


def test_reenter_digest_is_deterministic_prose_is_llm_output() -> None:
    """The digest (code-selected) is deterministic; prose (LLM) varies.

    §1 source ≠ sink: assemble_reentry (source, code, deterministic) ≠
    render_reentry_prose (sink, LLM content-gen).
    Discriminating: same digest inputs yield same digest; different mock
    responses yield different prose — confirming separation.
    """
    store, conn = _make_full_store()
    room, evt = _seed_room(store)

    router1 = _mock_router("Response A")
    router2 = _mock_router("Response B")

    result1 = reenter(
        room.id,
        "user1",
        conn=conn,
        llm_router=router1,
        events=[evt],
        room=room,
        now=TimestampMs(5000),
    )
    result2 = reenter(
        room.id,
        "user1",
        conn=conn,
        llm_router=router2,
        events=[evt],
        room=room,
        now=TimestampMs(5000),
    )

    # Digest is deterministic — same inputs.
    assert result1.digest.room_id == result2.digest.room_id
    assert result1.digest.recalled_knowledge == result2.digest.recalled_knowledge
    assert result1.digest.new_since_leave == result2.digest.new_since_leave

    # Prose differs — different mock responses.
    assert result1.prose == "Response A"
    assert result2.prose == "Response B"
    assert result1.prose != result2.prose
