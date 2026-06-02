"""Room templates: per-RoomType default agent lists and initial states.

Implements the ``RoomTemplate`` model and the ``ROOM_TEMPLATES`` registry
(ADR-012 §5.2 handoff lean; P1.5-6 plan acceptance criteria).

Design invariants:
- ``templates.py`` is pure data — no I/O, no LLM calls, no yaml loading.
  The ``load_room`` helper takes an already-loaded ``dict[str, Agent]`` and
  does not read files itself.
- ``declared_agents`` lists are alphabetical (plan §P1.5-6 requirement).
- The Research template declares 5 agents.  The 4 scaffold templates declare
  their P3.1 rosters per ADR-024 + P3.1 plan §2a.
- ``default_initial_state`` is ``"setup"`` for all 5 RoomTypes — the Research
  state machine starts in ``setup`` (ADR-012 D2); scaffold types also open
  in ``setup`` (their only non-closed state).

No LLM imports — enforced by
``test_constitution_no_llm_calls_in_rooms_module`` (ADR-012 D7).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from orchestrator.agents.schema import Agent
from orchestrator.core.event import generate_room_id
from orchestrator.core.room import Room, RoomType

# ---------------------------------------------------------------------------
# RoomTemplate model (plan §P1.5-6 acceptance criteria)
# ---------------------------------------------------------------------------


class RoomTemplate(BaseModel):
    """Immutable template describing a room's default configuration.

    ``declared_agents`` — agent ids that *should* be loaded for this room
    type.  The ids are alphabetical (convention; plan requirement).  Not all
    declared agents may be present at runtime — ``load_room`` returns a
    ``missing`` list for graceful degradation.

    ``default_initial_state`` — the state string the ``Room`` starts in.
    Must be a valid state for the ``room_type`` per ADR-012 D2 (enforced
    by the state-machine layer; not re-validated here to avoid coupling).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    room_type: RoomType
    declared_agents: list[str]  # agent ids, alphabetical
    default_initial_state: str  # must be valid for the per-RoomType Literal


# ---------------------------------------------------------------------------
# ROOM_TEMPLATES registry (plan §P1.5-6 acceptance criteria)
# ---------------------------------------------------------------------------

ROOM_TEMPLATES: dict[RoomType, RoomTemplate] = {
    # Research: fully implemented template (ADR-012 D1 + handoff §5.2).
    # 5 declared agents — alphabetical order.
    RoomType.RESEARCH: RoomTemplate(
        room_type=RoomType.RESEARCH,
        declared_agents=[
            "divergence_mapper",
            "logger",
            "operator",
            "prober",
            "skeptic",
        ],
        default_initial_state="setup",
    ),
    # Scaffold templates: rosters populated per ADR-024 + P3.1 plan §2a.
    # bug_fix: prober surfaces assumptions, skeptic challenges, operator acts, logger records.
    # code_review: skeptic challenges, operator acts, logger records (no assumption-surfacing).
    # idea_validation: full analytical roster — prober + skeptic + divergence_mapper + operator +
    #   logger.
    # free_chat: facilitator (ADR-024 new role) + logger.
    RoomType.BUG_FIX: RoomTemplate(
        room_type=RoomType.BUG_FIX,
        declared_agents=["logger", "operator", "prober", "skeptic"],
        default_initial_state="setup",
    ),
    RoomType.CODE_REVIEW: RoomTemplate(
        room_type=RoomType.CODE_REVIEW,
        declared_agents=["logger", "operator", "skeptic"],
        default_initial_state="setup",
    ),
    RoomType.IDEA_VALIDATION: RoomTemplate(
        room_type=RoomType.IDEA_VALIDATION,
        declared_agents=["divergence_mapper", "logger", "operator", "prober", "skeptic"],
        default_initial_state="setup",
    ),
    RoomType.FREE_CHAT: RoomTemplate(
        room_type=RoomType.FREE_CHAT,
        declared_agents=["facilitator", "logger"],
        default_initial_state="setup",
    ),
}


# ---------------------------------------------------------------------------
# load_room helper (plan §P1.5-6 acceptance criteria)
# ---------------------------------------------------------------------------


def load_room(
    room_type: RoomType,
    available_agents: dict[str, Agent],
) -> tuple[Room, list[str]]:
    """Construct a ``Room`` from a template with the given available agents.

    Pure function — no I/O.  ``available_agents`` is a pre-loaded mapping
    (e.g. the output of ``load_agents``).

    Logic:
    1. Look up ``ROOM_TEMPLATES[room_type]``.
    2. Partition ``template.declared_agents`` into *present* (keys in
       ``available_agents``) and *missing* (absent keys).
    3. Construct and return ``(Room, list_of_missing_agent_ids)``.

    The returned ``Room`` is initialised with:
    - A fresh id via ``generate_room_id()``.
    - ``type=room_type``.
    - ``state=template.default_initial_state``.

    Missing agents are NOT an error — graceful degradation per brief lean.
    The caller decides whether missing agents are fatal for the use case.

    Args:
        room_type: The ``RoomType`` to instantiate.
        available_agents: Mapping of agent id → ``Agent`` (already loaded;
            this function does not read files).

    Returns:
        A ``(Room, missing_agent_ids)`` tuple.  ``missing_agent_ids`` is
        the list of declared-but-absent agent ids, in declaration order
        (alphabetical, per ``ROOM_TEMPLATES``).
    """
    template = ROOM_TEMPLATES[room_type]

    missing: list[str] = [
        agent_id for agent_id in template.declared_agents if agent_id not in available_agents
    ]

    room = Room(
        id=generate_room_id(),
        type=room_type,
        state=template.default_initial_state,
    )

    return room, missing
