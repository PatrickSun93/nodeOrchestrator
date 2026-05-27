"""Exception types for the agents package."""

from __future__ import annotations


class AgentLoadError(Exception):
    """Raised during agent yaml loading on any structural or validation failure.

    ``agent_id`` is the id string from the yaml (or the file stem if the
    yaml could not be parsed far enough to find ``id``).  ``field`` names
    the offending field when the error is field-specific (e.g. ``"id"``
    for a filename/id mismatch or a duplicate-id collision).
    """

    def __init__(
        self,
        message: str,
        *,
        agent_id: str | None = None,
        field: str | None = None,
    ) -> None:
        super().__init__(message)
        self.agent_id = agent_id
        self.field = field


class SpeakingTriggerError(Exception):
    """Raised when a speaking trigger cannot be compiled or evaluated.

    ``agent_id`` identifies the owning agent; ``trigger_index`` is the
    zero-based position of the trigger in ``agent.speaking_triggers``.
    """

    def __init__(
        self,
        message: str,
        *,
        agent_id: str | None = None,
        trigger_index: int | None = None,
    ) -> None:
        super().__init__(message)
        self.agent_id = agent_id
        self.trigger_index = trigger_index


class DispatchError(Exception):
    """Raised when the dispatch layer encounters an unrecoverable error.

    Per-agent LLM failures do NOT raise ``DispatchError`` — those are
    logged and skipped (ADR-011 D7).  ``DispatchError`` is reserved for
    failures that make the entire turn un-dispatchable (e.g. bad
    ``regex_registry`` shape).
    """

    def __init__(
        self,
        message: str,
        *,
        agent_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.agent_id = agent_id
