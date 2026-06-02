"""In-process per-room pub/sub hub (ADR-025 D6, R0-B Y1).

subscribe() registers a bounded asyncio.Queue before the caller replays
events, guaranteeing no event is lost between replay and live stream.
A full queue or a send error causes the subscriber to be dropped silently
— never blocks the writer or other subscribers.
"""

from __future__ import annotations

import asyncio

from orchestrator.core.event import Event, RoomId

_QUEUE_MAX_SIZE = 512


class RoomEventBus:
    """Per-room event broadcast hub.

    All methods run on the event loop thread. publish() is called via
    loop.call_soon_threadsafe() from the writer executor thread.
    """

    def __init__(self) -> None:
        self._subscribers: dict[RoomId, list[asyncio.Queue[Event]]] = {}

    def subscribe(self, room_id: RoomId) -> asyncio.Queue[Event]:
        """Register a new bounded queue for room_id. Returns the queue.

        Must be called from the event loop (e.g., from an async handler).
        Register BEFORE replaying events to avoid a lost-event window.
        """
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=_QUEUE_MAX_SIZE)
        if room_id not in self._subscribers:
            self._subscribers[room_id] = []
        self._subscribers[room_id].append(q)
        return q

    def unsubscribe(self, room_id: RoomId, q: asyncio.Queue[Event]) -> None:
        """Remove a subscriber queue. Safe to call even if already removed."""
        import contextlib

        subs = self._subscribers.get(room_id)
        if subs is None:
            return
        with contextlib.suppress(ValueError):
            subs.remove(q)

    def publish(self, room_id: RoomId, events: list[Event]) -> None:
        """Fan out events to all subscribers of room_id (drop on full queue).

        Called from the event loop (via call_soon_threadsafe from writer thread).
        A subscriber whose queue is full is unsubscribed immediately — it never
        blocks the writer or other subscribers.
        """
        subs = self._subscribers.get(room_id)
        if not subs:
            return
        dead: list[asyncio.Queue[Event]] = []
        for q in list(subs):
            for event in events:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    dead.append(q)
                    break
        for q in dead:
            self.unsubscribe(room_id, q)
