"""Constitutional tests for the autonomy module.

These lock in the schema-level invariants the autonomy gate depends on.
If a future PR breaks one, do NOT "fix the test" — investigate whether
the invariant is still valid, and if it must change, write an ADR.

See ``tests/core/test_constitution.py`` for the precedent docstring.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.autonomy.scoring import ThresholdConfig
from orchestrator.llm.types import AgentAutonomyThresholds


@pytest.mark.parametrize(
    "cls",
    [ThresholdConfig, AgentAutonomyThresholds],
    ids=["ThresholdConfig", "AgentAutonomyThresholds"],
)
def test_constitution_threshold_auto_strictly_greater_than_confirm(
    cls: type[ThresholdConfig] | type[AgentAutonomyThresholds],
) -> None:
    """Both threshold-carrying classes must enforce
    ``threshold_auto > threshold_confirm`` at Pydantic-validation time.

    Why: ``decide_tier`` (autonomy gate) selects AUTO_EXECUTE vs
    COUNTDOWN_CONFIRM vs HARD_CONFIRM by ordered comparison on these
    two thresholds. ADR-005 Decision 4 specifies COUNTDOWN_CONFIRM as
    the band ``[confirm, auto)``; equal values collapse the band to
    zero-width, and inverted values reverse the rule into undefined
    behavior dependent on if/elif ordering rather than on a clean
    invariant.

    The invariant is parameterized over BOTH classes because the YAML
    load path uses ``AgentAutonomyThresholds`` while ``decide_tier``
    consumes ``ThresholdConfig`` — if either drops the validator, a
    construction site can produce an unsafe instance. This test fails
    on any such drift.

    Boundary cases exercised:

    - equal (auto == confirm): zero-width COUNTDOWN_CONFIRM band.
    - inverted (auto < confirm): rule order undefined.
    - valid (auto > confirm, minimal gap of 1): must accept.
    """
    with pytest.raises(ValidationError, match="strictly greater"):
        cls(threshold_auto=5, threshold_confirm=5, user_intent_modifier=0)

    with pytest.raises(ValidationError, match="strictly greater"):
        cls(threshold_auto=3, threshold_confirm=7, user_intent_modifier=0)

    instance = cls(threshold_auto=6, threshold_confirm=5, user_intent_modifier=0)
    assert instance.threshold_auto == 6
    assert instance.threshold_confirm == 5
