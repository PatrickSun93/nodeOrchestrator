from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---- Public types ---------------------------------------------


class AutonomyTier(StrEnum):
    """Three-tier output. See ADR-005 Decision 4."""

    AUTO_EXECUTE = "auto_execute"
    COUNTDOWN_CONFIRM = "countdown_confirm"
    HARD_CONFIRM = "hard_confirm"


class Operation(BaseModel):
    """The input to the autonomy gate. P1.2 reads `tool_id` and
    `user_explicit_intent` only; the remaining fields are
    consumed by P1.3 Hard Guards (see ADR-005 Decision 5 and
    handoff §4.3 comment)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_id: str
    initiating_agent: str
    user_explicit_intent: bool
    # P1.3-reserved (kept on the dataclass per architect's
    # Option B; not read by the P1.2 scorer):
    params: dict[str, Any] = Field(default_factory=dict)
    estimated_cost_usd: float = 0.0


class ToolMeta(BaseModel):
    """Per-tool metadata from tools.yaml. P1.2 reads
    `reversibility` only; future fields land in P1.3."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reversibility: int = Field(
        default=0,
        ge=0,
        le=10,
        description=(
            "0 = irreversible, 10 = fully reversible. "
            "Default 0 enforces conservative-low per ADR-005 "
            "Decision 2. Per-tool, per-type; no per-parameter."
        ),
    )


class ThresholdConfig(BaseModel):
    """Per-agent thresholds consumed by ``decide_tier``. See
    ADR-005 Decision 3 for placeholder values.

    The cross-field invariant ``threshold_auto > threshold_confirm``
    is enforced here at Pydantic validation time. Equal values are
    rejected because they collapse COUNTDOWN_CONFIRM to a zero-width
    band (ADR-005 Decision 4); inverted values put ``decide_tier``'s
    if/elif branching into undefined behavior.

    This validator duplicates the one on
    ``orchestrator.llm.types.AgentAutonomyThresholds``: the YAML load
    path runs through ``AgentAutonomyThresholds`` (validator fires),
    but ``decide_tier`` consumes ``ThresholdConfig`` directly and
    tests/code may construct it without going through the loader.
    Schema-level enforcement on both classes is the deliberate
    defense; deduplicating the pair into a single class crosses
    the autonomy ↔ llm module boundary and needs its own ADR.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    threshold_auto: int = Field(ge=0, le=10)
    threshold_confirm: int = Field(ge=0, le=10)
    user_intent_modifier: int = Field(ge=0, le=10)

    @model_validator(mode="after")
    def _check_auto_gt_confirm(self) -> ThresholdConfig:
        if self.threshold_auto <= self.threshold_confirm:
            raise ValueError(
                f"threshold_auto ({self.threshold_auto}) must be strictly greater than "
                f"threshold_confirm ({self.threshold_confirm}). "
                f"Equal values collapse COUNTDOWN_CONFIRM to a zero-width band "
                f"(ADR-005 Decision 4). Increase threshold_auto or decrease "
                f"threshold_confirm."
            )
        return self


class DecisionTrace(BaseModel):
    """Why the gate returned the tier it did. Required on
    every decision per contributing.md Q2. Locked by the
    autonomy_decision event metadata schema; see ADR-005
    Decision 6."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_id: str
    reversibility_score: int
    threshold_auto_raw: int
    threshold_confirm_raw: int
    user_intent_modifier: int
    user_explicit_intent: bool
    threshold_auto_effective: int
    threshold_confirm_effective: int
    tier: AutonomyTier
    rule: Literal[
        "score_ge_auto",
        "score_between_confirm_and_auto",
        "score_lt_confirm",
    ]


class AutonomyScore(BaseModel):
    """Combined score + tier + trace, returned by the gate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    score: int = Field(ge=0, le=10)
    tier: AutonomyTier
    trace: DecisionTrace


# ---- Public functions -----------------------------------------


def score(
    operation: Operation,
    tools: dict[str, ToolMeta],
) -> int:
    """Compute the reversibility-only score for the operation.
    Returns 0..10. If the tool is not in `tools`, returns 0
    (conservative-low; ADR-005 Decision 2). Pure function: no
    I/O, no LLM, no event emission."""
    raise NotImplementedError


def decide_tier(
    score_value: int,
    thresholds: ThresholdConfig,
    user_explicit_intent: bool,
    *,
    tool_id: str,
) -> AutonomyScore:
    """Map score + thresholds + intent to a tier, returning the
    full AutonomyScore (score, tier, trace). Pure function. The
    `tool_id` keyword arg is for the trace only; tier selection
    does not depend on it. See ADR-005 Decisions 4 and 5."""
    raise NotImplementedError


def gate(
    operation: Operation,
    tools: dict[str, ToolMeta],
    thresholds: ThresholdConfig,
) -> AutonomyScore:
    """End-to-end gate: score + decide. Pure function; event
    emission lives in the caller, not here, so the gate stays
    testable without an event store."""
    raise NotImplementedError
