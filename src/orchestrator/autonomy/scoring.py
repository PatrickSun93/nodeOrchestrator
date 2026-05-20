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


# ---- Exceptions -----------------------------------------------


class UnknownToolError(Exception):
    """Raised by ``score()`` when ``operation.tool_id`` is not in the
    tools registry. See ADR-006 Decision 1.

    ``tool_id`` is a structured attribute for log-based diagnosis and
    downstream handling; do not parse ``str(e)`` — read ``e.tool_id``
    directly. The message string format is not part of the contract.
    """

    def __init__(self, tool_id: str) -> None:
        self.tool_id = tool_id
        super().__init__(f"tool_id {tool_id!r} not found in tools registry")


# ---- Public functions -----------------------------------------


def score(
    operation: Operation,
    tools: dict[str, ToolMeta],
) -> int:
    """Compute the reversibility-only score for the operation.
    Returns 0..10. Pure function: no I/O, no LLM, no event emission.

    Raises:
        UnknownToolError: if ``operation.tool_id`` is not in ``tools``.
            See ADR-006 Decision 1. The missing-field case (tool in
            registry, ``reversibility`` absent) is handled by the Pydantic
            ``Field(default=0, …)`` on ``ToolMeta`` per ADR-005 Decision 2.
    """
    if operation.tool_id not in tools:
        raise UnknownToolError(operation.tool_id)
    return tools[operation.tool_id].reversibility


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
    if user_explicit_intent:
        eff_auto = thresholds.threshold_auto - thresholds.user_intent_modifier
        eff_confirm = max(0, thresholds.threshold_confirm - thresholds.user_intent_modifier)
    else:
        eff_auto = thresholds.threshold_auto
        eff_confirm = thresholds.threshold_confirm

    tier: AutonomyTier
    rule: Literal["score_ge_auto", "score_between_confirm_and_auto", "score_lt_confirm"]
    if score_value >= eff_auto:
        tier = AutonomyTier.AUTO_EXECUTE
        rule = "score_ge_auto"
    elif score_value >= eff_confirm:
        tier = AutonomyTier.COUNTDOWN_CONFIRM
        rule = "score_between_confirm_and_auto"
    else:
        tier = AutonomyTier.HARD_CONFIRM
        rule = "score_lt_confirm"

    trace = DecisionTrace(
        tool_id=tool_id,
        reversibility_score=score_value,
        threshold_auto_raw=thresholds.threshold_auto,
        threshold_confirm_raw=thresholds.threshold_confirm,
        user_intent_modifier=thresholds.user_intent_modifier,
        user_explicit_intent=user_explicit_intent,
        threshold_auto_effective=eff_auto,
        threshold_confirm_effective=eff_confirm,
        tier=tier,
        rule=rule,
    )
    return AutonomyScore(score=score_value, tier=tier, trace=trace)


def gate(
    operation: Operation,
    tools: dict[str, ToolMeta],
    thresholds: ThresholdConfig,
) -> AutonomyScore:
    """End-to-end gate: score + decide. Pure function; event
    emission lives in the caller, not here, so the gate stays
    testable without an event store."""
    return decide_tier(
        score(operation, tools),
        thresholds,
        operation.user_explicit_intent,
        tool_id=operation.tool_id,
    )
