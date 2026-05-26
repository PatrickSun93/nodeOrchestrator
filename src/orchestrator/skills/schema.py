from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from orchestrator.core.room import RoomType


class AppliesTo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    agents: list[str] = Field(min_length=1)
    room_types: list[RoomType] = Field(min_length=1)
    room_states: list[str] | None = None

    @field_validator("agents")
    @classmethod
    def _reject_mixed_star(cls, v: list[str]) -> list[str]:
        # ADR-009 Decision 3: ["*"] is the exclusive sentinel.
        # ["*", "prober"] is forbidden — if "*" is present, all other ids
        # are redundant and mixing them is an authoring error.
        if "*" in v and len(v) > 1:
            raise ValueError(
                '"*" cannot be mixed with concrete agent ids in applies_to.agents; '
                'use ["*"] alone or list specific agents without "*"'
            )
        return v

    @field_validator("room_states")
    @classmethod
    def _reject_empty_list(cls, v: list[str] | None) -> list[str] | None:
        # ADR-009 Decision 4: empty list is a likely authoring error.
        # Omit the key entirely (None) to mean "all states".
        if v is not None and len(v) == 0:
            raise ValueError(
                "applies_to.room_states must be None (omitted) or a non-empty list; "
                "use None to match all states"
            )
        return v


class Skill(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    category: Literal["general", "engineering", "business"]
    applies_to: AppliesTo
    priority: int = Field(ge=0, le=100)
    body: str = Field(min_length=1)  # markdown body; empty body rejected per R0-A-on-plan-4


class SkillMatchRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_id: str
    # Match-ness derives from rejection_reason == "matched".
    # No separate matched: bool — single source of truth per ADR-009 Decision 6
    # + R0-A-on-plan-1(a).
    rejection_reason: Literal[
        "agent_mismatch",
        "room_type_mismatch",
        "room_state_mismatch",
        "matched",
    ]


class SkillDecisionTrace(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    considered: list[SkillMatchRecord]
    selected_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)


class SkillSelection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    selected: list[Skill]  # ordered by priority desc, then id asc
    trace: SkillDecisionTrace
