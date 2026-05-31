"""Pydantic models for the .workflow/{task-id}.yaml state file shape.

See ADR-008 Decisions 4 (location), 5 (YAML shape), 6 (9-state vocabulary).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkflowState(StrEnum):
    """The 10 canonical workflow states. See ADR-008 Decision 6 + Amendment 2 (W-005)."""

    AWAITING_BRIEF = "awaiting_brief"
    AWAITING_SENIOR_PLAN = "awaiting_senior_plan"
    AWAITING_ARCHITECT_ACCEPT = "awaiting_architect_accept"
    AWAITING_JUNIOR_IMPL = "awaiting_junior_impl"
    AWAITING_SENIOR_PLAN_VS_IMPL = "awaiting_senior_plan_vs_impl"
    AWAITING_R0_A = "awaiting_R0_A"
    AWAITING_ARCHITECT_DECISION = "awaiting_architect_decision"
    AWAITING_SENIOR_REVISION = "awaiting_senior_revision"  # W-005 Amendment 2
    AWAITING_PR_MERGE = "awaiting_PR_merge"
    CLOSED = "closed"


class OverrideEntry(BaseModel):
    """One entry in TaskState.override_history. See ADR-008 Decision 10."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime
    actor: Literal["architect", "architect-partner"]
    from_state: WorkflowState
    to_state: WorkflowState
    reason: str = Field(min_length=1)


class TaskState(BaseModel):
    """The shape of one .workflow/{task-id}.yaml file.

    See ADR-008 Decisions 5 + 6.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str = Field(min_length=1)
    state: WorkflowState
    cycle: int = Field(default=1, ge=1)  # rework counter; see Decision 11
    last_transition_at: datetime
    # ADR-008 Decision 16 (W-006, RC-22): the cycle-relative boundary for the
    # cycle artifact filter (Decision 14) + merge-durable impl detection
    # (Decision 15). Stamped ONLY at cycle-boundary events — `init` and a
    # rework override → awaiting_junior_impl — NEVER on a normal advance. This
    # is the load-bearing invariant: stamping it per-advance (like
    # last_transition_at) would reincarnate RC-22. None = legacy state file
    # written before W-006; callers fall back to last_transition_at (the old,
    # RC-22-buggy boundary) for those — documented migration tradeoff.
    cycle_started_at: datetime | None = None
    override_history: list[OverrideEntry] = Field(default_factory=list)
    # Schema hook for stub §5.1 — leaves room for future cross-family
    # R0-B gate without forcing it now. Default False = current behavior.
    requires_cross_family_review: bool = False
