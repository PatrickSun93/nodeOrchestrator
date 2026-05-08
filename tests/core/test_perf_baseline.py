"""Performance baseline tests.

These are NOT optimization targets — they are regression guards. If
``get_thread`` is ever reimplemented as N+1 queries (a common, easy
mistake), this test fails immediately. Baselines are intentionally
generous to absorb CI variation; the goal is to catch order-of-magnitude
regressions, not micro-optimizations.

If a baseline fails: the most likely cause is a regression. Look at
the function under test before relaxing the threshold.
"""

from __future__ import annotations

import time

from orchestrator.core.event import (
    Event,
    EventId,
    EventType,
    TimestampMs,
    generate_event_id,
    generate_room_id,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType


def test_perf_baseline_get_thread_depth_100(
    in_memory_event_store: EventStore,
) -> None:
    """``get_thread`` on a 100-deep chain must finish under 50ms.

    With the recursive CTE, this is sub-millisecond on modern hardware.
    A regression to N+1 (one ``SELECT`` per ancestor) would land
    around 5-20ms for depth 100 on SQLite, with high variance — well
    below 50ms but with a strong trend toward ``O(depth)`` linear.

    The 50ms ceiling is generous to absorb cold-start, GC pauses, and
    CI noise. If you find this test failing on local machines but
    passing in CI (or vice versa), suspect the impl, not the threshold.
    """
    store = in_memory_event_store
    room = Room(id=generate_room_id(), type=RoomType.FREE_CHAT)
    store.append_room(room)

    parent_id: EventId | None = None
    last_id: EventId | None = None
    for i in range(100):
        e = Event(
            id=generate_event_id(),
            parent_id=parent_id,
            room_id=room.id,
            type=EventType.UTTERANCE,
            author="user",
            timestamp=TimestampMs(1_000_000 + i),
            content=f"event {i}",
        )
        store.append(e)
        parent_id = e.id
        last_id = e.id

    assert last_id is not None

    start = time.perf_counter()
    thread = store.get_thread(last_id)
    elapsed = time.perf_counter() - start

    assert len(thread) == 100, f"expected depth 100, got {len(thread)}"
    assert elapsed < 0.050, (
        f"get_thread depth-100 took {elapsed * 1000:.1f}ms, "
        f"exceeds 50ms baseline. Likely a regression from the recursive CTE "
        f"to an N+1 query — check EventStore.get_thread."
    )
