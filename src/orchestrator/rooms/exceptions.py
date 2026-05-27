"""Exceptions raised by the rooms package.

`RoomStateError` is raised on internal contract violations in
`next_room_state` — e.g., a transition rule fires but the resulting
state value is not in the per-RoomType Literal (defensive invariant).
"""

from __future__ import annotations


class RoomStateError(Exception):
    """Raised on internal state-machine contract violations.

    Carries the full context needed to diagnose the issue: which room
    (``room_id``), what state the room was in (``current_state``), and
    which transition rule misfired (``attempted_transition_rule``).

    Per ``test-coverage-standard.md`` §4: callers that want to react
    differently per violation should discriminate on the structured
    fields, not parse ``str(e)``.
    """

    room_id: str
    current_state: str
    attempted_transition_rule: str

    def __init__(
        self,
        room_id: str,
        current_state: str,
        attempted_transition_rule: str,
        message: str = "",
    ) -> None:
        self.room_id = room_id
        self.current_state = current_state
        self.attempted_transition_rule = attempted_transition_rule
        super().__init__(
            message
            or (
                f"Room {room_id!r} in state {current_state!r}: "
                f"transition rule {attempted_transition_rule!r} fired but "
                f"produced an invalid or unexpected result"
            )
        )
