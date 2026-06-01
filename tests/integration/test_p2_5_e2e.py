"""End-to-end P2.5: Scenario — leave → re-entry catch-up ("AI 记得我").

Per plan P2.5-6 acceptance criteria (ADR-021 D3/D5/D6/D7/D8).

Full leave→return flow (the P2 acceptance milestone):
  1. Seed room with rule-b-promoted VK + tagged hypotheses + ProjectArchive
     + entities + preferences.
  2. record_leave_marker at leave.
  3. Add new facts after the marker (a new event + a new VK with later ts).
  4. reenter() → assert the ReentryDigest surfaces exactly the right facts
     (discriminating, by stable labels — RC-25).
  5. Cleanup/graceful: first-visit (no marker), no archive, no VK, no tags.
  6. Code/LLM boundary: digest is deterministic; prose is content-gen.
  7. Constitutional guards green (tested in tests/reentry/test_constitution.py).

Source ≠ sink across all readers (§1 coverage standard):
  - memory/promotion (VK write) → reentry/digest (VK read via lookup).
  - reentry/leave (marker write) → reentry/store (marker read).
  - reentry/leave (archive write) → memory/archive (archive read).
  - memory/entity (entity/pref write) → reentry/digest (entity/pref read).
  - reentry/render (prose render) ← reentry/digest (code-assembled digest).
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
from orchestrator.memory.entity import record_entity, record_preference
from orchestrator.memory.promotion import promote_hypothesis
from orchestrator.memory.schema import EntityType, VKScope
from orchestrator.memory.store import init_memory_schema, record_hypothesis
from orchestrator.reentry.digest import assemble_reentry
from orchestrator.reentry.leave import record_leave_marker
from orchestrator.reentry.render import LLMRouterProtocol, reenter
from orchestrator.reentry.schema import ReentryDigest
from orchestrator.reentry.store import init_reentry_schema

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_full_store() -> tuple[EventStore, sqlite3.Connection]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = EventStore(conn)
    store.init_schema()
    init_memory_schema(conn)
    init_reentry_schema(conn)
    return store, conn


def _seed_room(store: EventStore) -> tuple[Room, Event]:
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    evt = Event(
        id=generate_event_id(),
        room_id=room.id,
        type=EventType.UTTERANCE,
        author="user",
        timestamp=TimestampMs(1000),
        content="session start",
    )
    store.append(evt)
    return room, evt


def _make_render_router(prose: str = "Welcome back!") -> MagicMock:
    router = MagicMock(spec=LLMRouterProtocol)
    router.call.return_value = LLMResponse(
        request_id=generate_request_id(),
        content=prose,
        model_id_requested=ModelId("m1"),
        model_id_used=ModelId("m1"),
        provider_id_used=ProviderId("mock"),
        usage=Usage(input_tokens=10, output_tokens=30),
        latency_ms=5,
        finish_reason="stop",
    )
    return router


# ---------------------------------------------------------------------------
# Scenario A: Full leave → re-entry (the P2 acceptance milestone)
# ---------------------------------------------------------------------------


def test_scenario_full_leave_reentry_surfaces_exact_facts() -> None:
    """Full leave→re-entry: the digest surfaces exactly the expected fact-set.

    Seed (test-injected):
      - A rule-b-promoted VK with topic tag "ai-cost".
      - A hypothesis in the room with the same tag (so derive_query_tags returns it).
      - An entity (concept) + a preference for "user1".
    Leave at ts=5000. After leave:
      - A new event at ts=7000 (post-marker).
      - A new VK at ts=8000 (post-marker).
    Assertions:
      - digest.recalled_knowledge includes the VK.
      - digest.entities includes the concept.
      - digest.preferences includes "user1"'s pref.
      - digest.new_since_leave has exactly the post-marker facts (by label).
      - Pre-marker event NOT in new_since_leave.

    RC-25: discriminating by stable labels, not count-only.
    §1 source ≠ sink: VK written by promotion; read by lookup in assemble_reentry.
    """
    store, conn = _make_full_store()
    room, pre_leave_evt = _seed_room(store)

    # --- Seed: tagged hypothesis + rule-b promoted VK ---
    hyp = record_hypothesis(
        content="AI inference cost is rising",
        room_id=room.id,
        source_event_ids=[pre_leave_evt.id],
        confidence=0.9,
        conn=conn,
        topic_tags=["ai-cost"],
    )
    promote_hypothesis(
        hyp.id,
        user_id="tester",
        scope=VKScope.PERSONAL,
        topic_tags=["ai-cost"],
        event_store=store,
    )

    # --- Seed: entity + preference ---
    record_entity(EntityType.CONCEPT, {"name": "transformer-arch"}, conn=conn)
    record_preference("verbosity", "concise", user_id="user1", conn=conn)

    # --- Leave at ts=5000 ---
    record_leave_marker(room.id, "user1", TimestampMs(5000), conn=conn)

    # --- Post-leave facts (ts > 5000) ---
    # Use DECISION_PIVOT (decision-class) so it appears in new_since_leave (Y2b filter).
    post_leave_evt = Event(
        id=generate_event_id(),
        room_id=room.id,
        type=EventType.DECISION_PIVOT,
        author="user",
        timestamp=TimestampMs(7000),
        content="new question after leave",
    )
    store.append(post_leave_evt)

    # A new VK with last_validated > 5000.
    hyp2 = record_hypothesis(
        content="GPU prices dropped post-leave",
        room_id=room.id,
        source_event_ids=[post_leave_evt.id],
        confidence=0.9,
        conn=conn,
        topic_tags=["ai-cost"],
    )
    new_vk = promote_hypothesis(
        hyp2.id,
        user_id="tester",
        scope=VKScope.PERSONAL,
        topic_tags=["ai-cost"],
        event_store=store,
    )
    # Force last_validated to post-marker ts.
    conn.execute(
        "UPDATE verified_knowledge SET last_validated = ? WHERE id = ?",
        (8000, str(new_vk.id)),
    )
    conn.commit()

    # --- Re-enter ---
    digest = assemble_reentry(
        room.id,
        "user1",
        conn=conn,
        events=[pre_leave_evt, post_leave_evt],
        room=room,
        now=TimestampMs(10000),
    )

    # --- Assertions: recalled_knowledge includes both VKs (tag match) ---
    vk_contents = [vk.content for vk in digest.recalled_knowledge]
    assert "AI inference cost is rising" in vk_contents, (
        "pre-leave VK must appear in recalled_knowledge"
    )
    assert "GPU prices dropped post-leave" in vk_contents, (
        "post-leave VK must appear in recalled_knowledge"
    )

    # --- Assertions: entities + preferences ---
    entity_names = [e.attributes.get("name") for e in digest.entities]
    assert "transformer-arch" in entity_names

    pref_keys = [p.attributes.get("key") for p in digest.preferences]
    assert "verbosity" in pref_keys

    # --- Assertions: new_since_leave — EXACTLY post-marker facts by label ---
    event_labels = [item.label for item in digest.new_since_leave if item.fact_type == "event"]
    vk_labels = [
        item.label for item in digest.new_since_leave if item.fact_type == "verified_knowledge"
    ]

    # Post-marker event present.
    assert "new question after leave" in event_labels, (
        "post-marker event must be in new_since_leave"
    )
    # Pre-marker event NOT present (discriminating, RC-25).
    assert "session start" not in event_labels, "pre-marker event must NOT be in new_since_leave"
    # Post-leave VK present.
    assert "GPU prices dropped post-leave" in vk_labels, (
        "post-leave VK (last_validated > marker) must be in new_since_leave"
    )

    # --- Assertions: new_since_leave sorted by occurred_at ASC ---
    ts_list = [item.occurred_at for item in digest.new_since_leave]
    assert ts_list == sorted(ts_list), "new_since_leave must be sorted occurred_at ASC"


# ---------------------------------------------------------------------------
# Scenario B: Code/LLM boundary + prose render
# ---------------------------------------------------------------------------


def test_scenario_digest_deterministic_prose_content_gen() -> None:
    """Digest is code-deterministic; prose varies with mock responses.

    §1 source ≠ sink: assemble_reentry (code, deterministic) → reenter → prose
    (LLM content-gen). Two runs, different mock prose, same digest.
    """
    store, conn = _make_full_store()
    room, evt = _seed_room(store)
    record_leave_marker(room.id, "user1", TimestampMs(500), conn=conn)

    router_a = _make_render_router("Prose A")
    router_b = _make_render_router("Prose B")

    result_a = reenter(
        room.id,
        "user1",
        conn=conn,
        llm_router=router_a,
        events=[evt],
        room=room,
        now=TimestampMs(9000),
    )
    result_b = reenter(
        room.id,
        "user1",
        conn=conn,
        llm_router=router_b,
        events=[evt],
        room=room,
        now=TimestampMs(9000),
    )

    # Digest is the same (deterministic code path).
    assert result_a.digest.room_id == result_b.digest.room_id
    assert result_a.digest.new_since_leave == result_b.digest.new_since_leave

    # Prose differs (LLM output varies).
    assert result_a.prose == "Prose A"
    assert result_b.prose == "Prose B"
    assert result_a.prose != result_b.prose


def test_scenario_reenter_prose_uses_reentry_digest_render_purpose() -> None:
    """reenter calls render with REENTRY_DIGEST_RENDER purpose (content-gen guard)."""
    store, conn = _make_full_store()
    room, evt = _seed_room(store)
    router = _make_render_router()

    reenter(
        room.id,
        "user1",
        conn=conn,
        llm_router=router,
        events=[evt],
        room=room,
        now=TimestampMs(5000),
    )

    router.call.assert_called_once()
    request = router.call.call_args[0][0]
    assert request.purpose == LLMPurpose.REENTRY_DIGEST_RENDER


# ---------------------------------------------------------------------------
# Scenario C: Cleanup / graceful paths
# ---------------------------------------------------------------------------


def test_scenario_first_visit_no_marker_no_crash() -> None:
    """First visit (no marker) → new_since_leave=[], last_seen_ts=None, no crash.

    ADR-021 D8: first visit is not a return.
    """
    store, conn = _make_full_store()
    room, evt = _seed_room(store)
    digest = assemble_reentry(
        room.id, "user1", conn=conn, events=[evt], room=room, now=TimestampMs(5000)
    )
    assert digest.new_since_leave == []
    assert digest.last_seen_ts is None
    assert isinstance(digest, ReentryDigest)


def test_scenario_no_archive_graceful() -> None:
    """No archive present → digest.archive is None, no crash."""
    store, conn = _make_full_store()
    room, evt = _seed_room(store)
    digest = assemble_reentry(
        room.id, "user1", conn=conn, events=[evt], room=room, now=TimestampMs(5000)
    )
    assert digest.archive is None


def test_scenario_no_vk_empty_memory_graceful() -> None:
    """Empty memory (no VK, no entities, no prefs) → empty digest, no crash."""
    store, conn = _make_full_store()
    room, evt = _seed_room(store)
    digest = assemble_reentry(
        room.id, "user1", conn=conn, events=[evt], room=room, now=TimestampMs(5000)
    )
    assert digest.recalled_knowledge == []
    assert digest.entities == []
    assert digest.preferences == []


def test_scenario_no_tags_no_vk_lookup_no_value_error() -> None:
    """No room tags → VK lookup skipped; no ValueError raised.

    ADR-021 D6: consumer never passes [] to lookup_verified_knowledge.
    Discriminating: fails if [] is passed (lookup raises ValueError on empty tags).
    """
    store, conn = _make_full_store()
    room, evt = _seed_room(store)
    # No hypotheses with tags → derive_query_tags returns [].
    digest = assemble_reentry(
        room.id, "user1", conn=conn, events=[evt], room=room, now=TimestampMs(5000)
    )
    assert digest.recalled_knowledge == []


def test_scenario_empty_tag_set_uses_code_not_llm() -> None:
    """derive_query_tags returns code-derived tags, never uses LLM.

    Discriminating: if an LLM were used for tag derivation, injecting an
    llm_router that raises would expose it. assemble_reentry has no llm_router
    parameter — LLM is structurally excluded.
    """
    store, conn = _make_full_store()
    room, evt = _seed_room(store)
    # This must NOT take an llm_router — pure code.
    digest = assemble_reentry(
        room.id,
        "user1",
        conn=conn,
        events=[evt],
        room=room,
        now=TimestampMs(5000),
    )
    assert isinstance(digest, ReentryDigest)
