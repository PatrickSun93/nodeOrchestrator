"""Deterministic re-entry assembly. Pure code — NO LLM. Per ADR-021 D3/D6.

derive_query_tags: code-derives topic_tags for lookup_verified_knowledge from
  the room's hypothesis vocabulary (ADR-021 D6).

assemble_reentry: composes all memory readers + derive_query_tags + new_since_leave
  diff into a frozen ReentryDigest. All selection/ordering is code (Principle 11).

The LLM-free-selection AST guard (P2.5-5) enforces that these functions reference
no LLMRequest/llm_router — any accidental LLM use in this file trips the guard.
"""

from __future__ import annotations

import sqlite3

from orchestrator.core.event import Event, EventType, RoomId, TimestampMs
from orchestrator.core.room import Room
from orchestrator.memory.archive import get_project_archive
from orchestrator.memory.entity import list_entities, list_preferences
from orchestrator.memory.lookup import list_room_topic_tags, lookup_verified_knowledge
from orchestrator.memory.schema import EntityType, VKScope
from orchestrator.reentry.schema import NewSinceLeaveItem, ReentryDigest
from orchestrator.reentry.store import get_leave_marker

# Decision-class events surfaced in new_since_leave (mirrors decision_log.py filter).
_DECISION_EVENT_TYPES: frozenset[EventType] = frozenset(
    {EventType.DECISION, EventType.DECISION_PIVOT, EventType.REJECTION, EventType.RETRACTION}
)


def derive_query_tags(
    room_id: RoomId,
    *,
    conn: sqlite3.Connection,
) -> list[str]:
    """Return the canonical topic_tags union for a room's hypotheses.

    Deterministic code function — NO LLM (Principle 11). If the union is empty
    (untagged / first-visit room), returns [] and the caller skips the VK lookup
    rather than passing [] to lookup_verified_knowledge (which raises). Per ADR-021 D6.
    """
    return list_room_topic_tags(room_id, conn=conn)


def assemble_reentry(
    room_id: RoomId,
    user_id: str,
    *,
    conn: sqlite3.Connection,
    events: list[Event],
    room: Room,
    now: TimestampMs,
) -> ReentryDigest:
    """Assemble the deterministic catch-up fact-set. Pure code — NO LLM.

    Composes:
    - Cross-room VK via lookup_verified_knowledge (only if derive_query_tags non-empty).
    - Entities + user preferences via list_entities / list_preferences.
    - Room's ProjectArchive (None on first visit).
    - new_since_leave: code diff against the leave-marker (first visit → []).
    Per ADR-021 D3/D8.
    """
    # --- Tag-derivation (ADR-021 D6) ---
    tags = derive_query_tags(room_id, conn=conn)

    # --- Cross-room VK (skip if no tags — lookup raises on empty, ADR-016 D6) ---
    recalled = lookup_verified_knowledge(tags, VKScope.PERSONAL, conn=conn) if tags else []

    # --- Entities + preferences (code-filtered) ---
    entities = [e for e in list_entities(conn=conn) if e.type != EntityType.PREFERENCE]
    preferences = list_preferences(user_id=user_id, conn=conn)

    # --- ProjectArchive ---
    archive = get_project_archive(room_id, conn)

    # --- Leave-marker + new_since_leave diff (ADR-021 D5/D8) ---
    last_seen_ts = get_leave_marker(room_id, user_id, conn)

    new_since_leave: list[NewSinceLeaveItem] = []
    if last_seen_ts is not None:
        # VK newly validated since leave.
        for vk in recalled:
            if vk.last_validated > last_seen_ts:
                new_since_leave.append(
                    NewSinceLeaveItem(
                        fact_type="verified_knowledge",
                        ref_id=str(vk.id),
                        label=vk.content[:80],
                        occurred_at=TimestampMs(vk.last_validated),
                    )
                )
        # Decision-class room events since leave (mirrors produce_decision_log filter).
        for evt in events:
            if evt.timestamp > last_seen_ts and evt.type in _DECISION_EVENT_TYPES:
                new_since_leave.append(
                    NewSinceLeaveItem(
                        fact_type="event",
                        ref_id=str(evt.id),
                        label=(evt.content or "")[:80],
                        occurred_at=TimestampMs(evt.timestamp),
                    )
                )
        # Order by occurred_at ASC, ref_id as tie-breaker for determinism (ADR-021 D8).
        new_since_leave.sort(key=lambda x: (x.occurred_at, x.ref_id))

    return ReentryDigest(
        room_id=room_id,
        archive=archive,
        recalled_knowledge=recalled,
        entities=entities,
        preferences=preferences,
        new_since_leave=new_since_leave,
        last_seen_ts=int(last_seen_ts) if last_seen_ts is not None else None,
        generated_at=now,
    )
