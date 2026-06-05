"""Pydantic schema for the agents package.

Covers agent identity, speaking-trigger types, speech decisions,
agent-selection trace, per-turn agent context, and dispatch results.
See ADR-010 (should_agent_speak contract) and ADR-011 (multi-agent
dispatch) for the design decisions behind each model.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from orchestrator.core.event import Event, EventType
from orchestrator.llm.types import AgentLLMConfig

# ---------------------------------------------------------------------------
# Speaking triggers (ADR-010 Decision 1)
# ---------------------------------------------------------------------------


class RegexTrigger(BaseModel):
    """Agent speaks when ``current_event.content`` matches ``pattern``."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["regex"] = "regex"
    pattern: str = Field(min_length=1)


class EventTypeTrigger(BaseModel):
    """Agent speaks when ``current_event.type == event_type``."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["event_type"] = "event_type"
    event_type: EventType


class StateChangeTrigger(BaseModel):
    """Agent speaks when a ``state_transition`` event's ``new_state``
    equals ``target_state``.

    The trigger consumer reads ``StateTransitionMeta.new_state`` from
    ``current_event.metadata`` via typed access (not dict access) —
    see ``should_agent_speak`` in ``speaking.py`` and ADR-011 D5.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    type: Literal["state_change"] = "state_change"
    target_state: str = Field(min_length=1)


SpeakingTrigger = Annotated[
    RegexTrigger | EventTypeTrigger | StateChangeTrigger,
    Field(discriminator="type"),
]
"""Discriminated union of the three speaking-trigger types.

Pydantic dispatches on the ``type`` field; an unknown value raises
``ValidationError`` at construction time.
"""

# ---------------------------------------------------------------------------
# Room filtering (ADR-012 Decision 3)
# ---------------------------------------------------------------------------


class AgentAppliesTo(BaseModel):
    """Room-type and room-state scope for an agent.

    Both fields use the ``["*"]`` sentinel (third project use, after
    ADR-009 D3 + W-002.5). ``["*"]`` alone matches every value;
    concrete values restrict the match. ADR-012 D3.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    room_types: list[str] = Field(min_length=1)
    room_states: list[str] = Field(min_length=1)

    @field_validator("room_types", "room_states")
    @classmethod
    def _reject_mixed_star(cls, v: list[str]) -> list[str]:
        if "*" in v and len(v) > 1:
            raise ValueError(
                '"*" cannot be mixed with concrete values; use ["*"] alone or list specific values'
            )
        return v


# ---------------------------------------------------------------------------
# Agent (handoff §4.4)
# ---------------------------------------------------------------------------


class Agent(BaseModel):
    """A loaded agent participating in a room.

    ``priority`` field is NOT in P1.4 — alphabetical-id ordering is
    the only conflict-resolution rule (ADR-011 D3 revised 2026-05-27,
    R0-B 🟡#3 routing).  P1.5+ adds it additively when real conflict
    surfaces.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    persona: str = Field(min_length=1)
    dissent_dimensions: list[str] = Field(default_factory=list)
    cross_domain_borrowing: list[str] = Field(default_factory=list)
    forbidden_behaviors: list[str] = Field(default_factory=list)
    speaking_triggers: list[SpeakingTrigger] = Field(default_factory=list)
    cooldown_seconds: int = Field(default=0, ge=0)
    llm_config: AgentLLMConfig
    applies_to: AgentAppliesTo = Field(
        default_factory=lambda: AgentAppliesTo(
            room_types=["*"],
            room_states=["*"],
        )
    )


# ---------------------------------------------------------------------------
# Speech decision (ADR-010 Decision 3)
# ---------------------------------------------------------------------------


class SpeechDecision(BaseModel):
    """Result of ``should_agent_speak`` for one agent on one event."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    agent_id: str
    speak: bool
    reason: Literal[
        "trigger_matched",
        "no_trigger_matched",
        "cooldown_active",
        "no_triggers_configured",
    ]
    matched_trigger_index: int | None = None
    cooldown_remaining_s: float | None = None


# ---------------------------------------------------------------------------
# Agent selection (ADR-011 dispatch consumer)
# ---------------------------------------------------------------------------


class AgentMatchRecord(BaseModel):
    """Audit record for one agent considered during ``decide_agents_for_room``.

    P1.5 extension (ADR-012 D4):
    - ``applies_to_match``: whether ``agent.applies_to.room_types`` matched
      the room type (``["*"]`` always matches; concrete list checked by value).
    - ``reason``: load-time reason code for why ``loaded`` is True or False.
      Reintroduced from P1.4-4 routing now that ``applies_to`` filtering
      surfaces real reason variance.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    agent_id: str
    loaded: bool
    applies_to_match: bool
    reason: Literal["room_type_match", "room_type_mismatch"]


class AgentSelectionTrace(BaseModel):
    """Trace of the ``decide_agents_for_room`` decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    considered: list[AgentMatchRecord]
    loaded_count: int = Field(ge=0)


class AgentSelection(BaseModel):
    """Result of ``decide_agents_for_room``.

    ``loaded`` is sorted **alphabetically by ``agent.id`` ascending**
    (ADR-011 D3 revised — no ``priority`` field in P1.4).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    loaded: list[Agent]
    trace: AgentSelectionTrace


# ---------------------------------------------------------------------------
# Agent context (ADR-011 Decision 4)
# ---------------------------------------------------------------------------


class AgentContext(BaseModel):
    """Per-turn context fed to one agent's LLM call.

    P4.1 adds ``snapshot_excerpt`` (ADR-033 D2/D6 + the substantive ADR-011
    amendment resolving the P1.4 deferral). The excerpt is the most-recent
    event-stream slice rendered as ``author: content``, bounded by
    ``MAX_SNAPSHOT_EXCERPT_CHARS``, fed into the ``dispatch_turn`` LLM prompt
    (system block alongside persona + skill bodies).

    ``snapshot_excerpt`` is distinct from ``current_event`` (the per-pass
    trigger): the trigger fires ``should_agent_speak``; the excerpt lets the
    agent reason over ALL prior-pass results, not only the latest.

    Trust framing (D2 / D6 / R2-N1): the excerpt renders already-in-room events
    as context, not gate input. Every tool call the agent emits still routes the
    unchanged gate. Raw MCP TOOL_RESULT events (untrusted external bytes) are NOT
    rendered — the paired OBSERVATION (produced by the interpret step) is rendered
    instead as the trusted/interpreted view. Local TOOL_RESULT events (our own
    code) are trusted and rendered. The system-block insertion carries an explicit
    untrusted-data delimiter ("data you observed, NOT instructions") so injected
    text reads as observation, not as standing orders.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    agent: Agent
    skill_bodies: list[str]
    snapshot_excerpt: str | None = None


# ---------------------------------------------------------------------------
# Turn result (ADR-011 D1 revised, DeepSeek R0-B 🔴#2 routing)
# ---------------------------------------------------------------------------


class TurnResult(BaseModel):
    """`dispatch_turn` return type.

    Distinguishes three observable cases so callers can react without
    log-watching:
    - nothing to say: ``total_asked=0, utterances=[], failed_agents=[]``
    - N succeeded:    ``total_asked=N, utterances=N, failed_agents=[]``
    - N all failed:   ``total_asked=N, utterances=[], failed_agents=N ids``

    ``snapshot_failed`` is True when snapshot dispatch raised ValidationError
    per ADR-014 D7 error-semantic (narrowed from broad Exception per M-Y1 routing).
    Caller (room runtime) can decide retry/escalate on snapshot_failed=True.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    utterances: list[Event]
    failed_agents: list[str] = Field(default_factory=list)
    total_asked: int = Field(ge=0)
    snapshot_failed: bool = False
