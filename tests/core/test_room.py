"""Direct tests for Room dataclass — locks fields, defaults, frozen
semantics, and RoomType enum values."""

from __future__ import annotations

import time as time_module

import pytest
from pydantic import ValidationError

from orchestrator.core.event import RoomId
from orchestrator.core.room import Room, RoomType


class TestRoomDefaults:
    def test_state_defaults_to_open(self) -> None:
        room = Room(id=RoomId("r1"), type=RoomType.FREE_CHAT)
        assert room.state == "open"

    def test_created_at_advances_between_constructions(self) -> None:
        """Locks ``default_factory=now_ms`` semantic: two constructions
        produce increasing timestamps, not the same cached value."""
        r1 = Room(id=RoomId("r1"), type=RoomType.FREE_CHAT)
        time_module.sleep(0.01)
        r2 = Room(id=RoomId("r2"), type=RoomType.FREE_CHAT)
        assert r2.created_at > r1.created_at


class TestRoomFrozen:
    def test_attribute_reassignment_raises(self) -> None:
        room = Room(id=RoomId("r1"), type=RoomType.FREE_CHAT)
        with pytest.raises(ValidationError):
            room.state = "closed"

    def test_unknown_field_at_construction_raises(self) -> None:
        with pytest.raises(ValidationError):
            Room(
                id=RoomId("r1"),
                type=RoomType.FREE_CHAT,
                unknown_field=42,  # type: ignore[call-arg]
            )


class TestRoomTypeEnum:
    def test_room_type_values_are_exactly_five(self) -> None:
        expected = {
            "free_chat",
            "bug_fix",
            "research",
            "code_review",
            "idea_validation",
        }
        actual = {m.value for m in RoomType}
        assert actual == expected
