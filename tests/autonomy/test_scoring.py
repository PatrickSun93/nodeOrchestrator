"""Behavior tests for ``orchestrator.autonomy.scoring``.

Groups:
    (a) ``score()`` — reversibility lookup, registry-miss, default field.
    (b) ``decide_tier()`` — boundary cases x user_explicit_intent, modifier
        clamp, named pinning test.
    (c) ``gate()`` — happy path and error propagation.

``class TestSchemaInvariants`` covers ``docs/architecture/test-coverage-standard.md``
§6 for ``AutonomyScore`` and ``DecisionTrace`` (scorer direct-output classes).
The other four Pydantic classes in ``scoring.py`` (``ToolMeta``, ``ThresholdConfig``,
``Operation``, ``AutonomyTier``) are vacuously held by C2 freeze + ``d20ad0b``
constitutional test; explicit §6 tests for ``ToolMeta`` and ``ThresholdConfig``
are queued for C4 per senior plan §5 push-back #2.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.autonomy.scoring import (
    AutonomyScore,
    AutonomyTier,
    DecisionTrace,
    Operation,
    ThresholdConfig,
    ToolMeta,
    UnknownToolError,
    decide_tier,
    gate,
    score,
)

# ---------------------------------------------------------------------------
# Shared fixtures (ADR-005 §3 placeholder thresholds)
# ---------------------------------------------------------------------------

_PROBER = ThresholdConfig(threshold_auto=8, threshold_confirm=5, user_intent_modifier=2)
_OPERATOR = ThresholdConfig(threshold_auto=6, threshold_confirm=3, user_intent_modifier=3)


def _op(tool_id: str, *, user_explicit_intent: bool = False) -> Operation:
    return Operation(
        tool_id=tool_id,
        initiating_agent="test_agent",
        user_explicit_intent=user_explicit_intent,
    )


def _tools(*pairs: tuple[str, int]) -> dict[str, ToolMeta]:
    return {tool_id: ToolMeta(reversibility=rev) for tool_id, rev in pairs}


# ---------------------------------------------------------------------------
# (a) score()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rev", [0, 2, 5, 8, 10])
def test_score_returns_reversibility_value(rev: int) -> None:
    tools = _tools(("my_tool", rev))
    result = score(_op("my_tool"), tools)
    assert result == rev


def test_score_unknown_tool_raises_unknown_tool_error() -> None:
    """Registry-miss raises UnknownToolError with tool_id as structured attr.

    Per test-coverage-standard.md §4: exception payload must be structured
    (readable via e.tool_id), not stringly-encoded. This is the §4 canonical
    instance for the autonomy module.
    """
    tools = _tools(("other_tool", 5))
    op = _op("missing_tool")
    with pytest.raises(UnknownToolError) as exc_info:
        score(op, tools)
    assert exc_info.value.tool_id == "missing_tool"


def test_score_empty_tools_raises_unknown_tool_error() -> None:
    op = _op("any_tool")
    with pytest.raises(UnknownToolError) as exc_info:
        score(op, {})
    assert exc_info.value.tool_id == "any_tool"


def test_score_default_reversibility_returns_zero() -> None:
    """Tool in registry with no explicit reversibility uses Pydantic default=0."""
    tools = {"default_tool": ToolMeta()}
    result = score(_op("default_tool"), tools)
    assert result == 0


# ---------------------------------------------------------------------------
# (b) decide_tier()
# ---------------------------------------------------------------------------


def test_decide_tier_score_equal_to_auto_threshold_gives_auto_execute() -> None:
    result = decide_tier(8, _PROBER, False, tool_id="t")
    assert result.tier == AutonomyTier.AUTO_EXECUTE
    assert result.trace.rule == "score_ge_auto"


def test_decide_tier_score_one_below_auto_gives_countdown() -> None:
    result = decide_tier(7, _PROBER, False, tool_id="t")
    assert result.tier == AutonomyTier.COUNTDOWN_CONFIRM
    assert result.trace.rule == "score_between_confirm_and_auto"


def test_decide_tier_score_equal_to_confirm_threshold_gives_countdown() -> None:
    result = decide_tier(5, _PROBER, False, tool_id="t")
    assert result.tier == AutonomyTier.COUNTDOWN_CONFIRM
    assert result.trace.rule == "score_between_confirm_and_auto"


def test_decide_tier_score_one_below_confirm_gives_hard_confirm() -> None:
    result = decide_tier(4, _PROBER, False, tool_id="t")
    assert result.tier == AutonomyTier.HARD_CONFIRM
    assert result.trace.rule == "score_lt_confirm"


def test_decide_tier_user_intent_shifts_boundaries() -> None:
    # With user_intent: eff_auto=8-2=6, eff_confirm=max(0,5-2)=3
    result_no_intent = decide_tier(6, _PROBER, False, tool_id="t")
    result_with_intent = decide_tier(6, _PROBER, True, tool_id="t")
    assert result_no_intent.tier == AutonomyTier.COUNTDOWN_CONFIRM
    assert result_with_intent.tier == AutonomyTier.AUTO_EXECUTE


def test_decide_tier_user_intent_confirm_boundary_shifts() -> None:
    # With user_intent: eff_confirm=max(0,5-2)=3; score=3 → COUNTDOWN
    result = decide_tier(3, _PROBER, True, tool_id="t")
    assert result.tier == AutonomyTier.COUNTDOWN_CONFIRM
    assert result.trace.threshold_confirm_effective == 3


def test_decide_tier_modifier_clamps_effective_confirm_to_zero() -> None:
    """threshold_confirm=2, modifier=5 → eff_confirm=max(0,-3)=0."""
    thresholds = ThresholdConfig(threshold_auto=8, threshold_confirm=2, user_intent_modifier=5)
    result = decide_tier(0, thresholds, True, tool_id="t")
    assert result.trace.threshold_confirm_effective == 0
    assert result.tier == AutonomyTier.COUNTDOWN_CONFIRM


def test_decide_tier_trace_carries_raw_and_effective_thresholds() -> None:
    result = decide_tier(6, _PROBER, True, tool_id="probe_tool")
    assert result.trace.threshold_auto_raw == 8
    assert result.trace.threshold_confirm_raw == 5
    assert result.trace.threshold_auto_effective == 6
    assert result.trace.threshold_confirm_effective == 3
    assert result.trace.user_intent_modifier == 2
    assert result.trace.user_explicit_intent is True
    assert result.trace.tool_id == "probe_tool"


def test_decide_tier_tool_id_does_not_affect_tier_selection() -> None:
    """tool_id is for trace only; same score + thresholds must produce same
    tier regardless of tool_id value."""
    r1 = decide_tier(5, _PROBER, False, tool_id="tool_a")
    r2 = decide_tier(5, _PROBER, False, tool_id="tool_b")
    assert r1.tier == r2.tier
    assert r1.score == r2.score


def test_decide_tier_score_zero_without_intent_gives_hard_confirm() -> None:
    result = decide_tier(0, _PROBER, False, tool_id="t")
    assert result.tier == AutonomyTier.HARD_CONFIRM


def test_decide_tier_score_ten_gives_auto_execute() -> None:
    result = decide_tier(10, _PROBER, False, tool_id="t")
    assert result.tier == AutonomyTier.AUTO_EXECUTE


def test_git_push_with_user_intent_lands_on_countdown_not_hard() -> None:
    """Pinning test for ADR-005 §5(c) example (brief decision 2, Q2=ii).

    With operator thresholds (auto=6, confirm=3, modifier=3) and
    git_push reversibility=1, user_explicit_intent=True:
      eff_auto = 6 - 3 = 3
      eff_confirm = max(0, 3 - 3) = 0
      score=1 >= eff_auto=3? No. score=1 >= eff_confirm=0? Yes.
      → COUNTDOWN_CONFIRM.

    The intuition "user said push to main + irreversible action → strict
    prompt" is wrong: user_intent reduces the threshold band by design.
    Hard Guards (P1.3) is the destructive-action refusal layer, not the
    scorer's HARD_CONFIRM tier (see ADR-005 §5, ADR-006, config/tools.yaml.example:49).
    """
    git_push_rev = 1  # config/tools.yaml.example:50
    result = decide_tier(
        git_push_rev,
        _OPERATOR,
        user_explicit_intent=True,
        tool_id="git_push",
    )
    assert result.tier == AutonomyTier.COUNTDOWN_CONFIRM, (
        f"Expected COUNTDOWN_CONFIRM but got {result.tier}. trace={result.trace}"
    )


# ---------------------------------------------------------------------------
# (c) gate()
# ---------------------------------------------------------------------------


def test_gate_happy_path_returns_autonomy_score() -> None:
    """operator + propose_edit (reversibility=5) + no user intent → COUNTDOWN_CONFIRM
    (score=5 < eff_auto=6, score=5 >= eff_confirm=3 → COUNTDOWN_CONFIRM).
    """
    tools = _tools(("propose_edit", 5))
    op = _op("propose_edit", user_explicit_intent=False)
    result = gate(op, tools, _OPERATOR)
    assert isinstance(result, AutonomyScore)
    assert result.score == 5
    assert result.tier == AutonomyTier.COUNTDOWN_CONFIRM
    assert result.trace.tool_id == "propose_edit"


def test_gate_propagates_unknown_tool_error() -> None:
    """gate() must NOT catch UnknownToolError — propagates unwrapped per ADR-006 §3."""
    op = _op("nonexistent_tool")
    with pytest.raises(UnknownToolError) as exc_info:
        gate(op, {}, _PROBER)
    assert exc_info.value.tool_id == "nonexistent_tool"


# ---------------------------------------------------------------------------
# Schema invariant tests — test-coverage-standard.md §6
# Scope: AutonomyScore + DecisionTrace (scorer direct-output).
# Deferred: ToolMeta + ThresholdConfig (queued for C4 per senior plan §5 #2).
# ---------------------------------------------------------------------------


class TestSchemaInvariants:
    """test-coverage-standard.md §6 coverage for ``AutonomyScore`` and
    ``DecisionTrace``. These are the two Pydantic models directly produced
    by the scorer's public API; their invariants are most likely to drift
    when the scoring logic changes.

    Granularity rationale: C3 is P1.2-R1, the first canonical §6 example
    (the standard's P1.1-example field says "land alongside P1.2-R1").
    ``ToolMeta`` and ``ThresholdConfig`` §6 explicit tests are deferred to
    C4 per senior plan push-back #2 (see docs/process/senior-plans/P1.2-C3.md).
    """

    # --- Fixtures shared across tests ------------------------------------

    _VALID_TRACE = DecisionTrace(
        tool_id="read_file",
        reversibility_score=8,
        threshold_auto_raw=8,
        threshold_confirm_raw=5,
        user_intent_modifier=2,
        user_explicit_intent=False,
        threshold_auto_effective=8,
        threshold_confirm_effective=5,
        tier=AutonomyTier.AUTO_EXECUTE,
        rule="score_ge_auto",
    )

    # --- AutonomyScore ---------------------------------------------------

    def test_autonomy_score_frozen(self) -> None:
        result = AutonomyScore(score=8, tier=AutonomyTier.AUTO_EXECUTE, trace=self._VALID_TRACE)
        with pytest.raises(ValidationError):
            result.score = 5

    def test_autonomy_score_extra_forbid(self) -> None:
        with pytest.raises(ValidationError):
            AutonomyScore(  # type: ignore[call-arg]
                score=8,
                tier=AutonomyTier.AUTO_EXECUTE,
                trace=self._VALID_TRACE,
                unexpected_field="bad",
            )

    def test_autonomy_score_out_of_range_raises(self) -> None:
        with pytest.raises(ValidationError):
            AutonomyScore(score=-1, tier=AutonomyTier.AUTO_EXECUTE, trace=self._VALID_TRACE)

    # --- DecisionTrace --------------------------------------------------

    def test_decision_trace_frozen(self) -> None:
        with pytest.raises(ValidationError):
            self._VALID_TRACE.tool_id = "new_tool"

    def test_decision_trace_extra_forbid(self) -> None:
        with pytest.raises(ValidationError):
            DecisionTrace(  # type: ignore[call-arg]
                tool_id="t",
                reversibility_score=5,
                threshold_auto_raw=8,
                threshold_confirm_raw=5,
                user_intent_modifier=2,
                user_explicit_intent=False,
                threshold_auto_effective=8,
                threshold_confirm_effective=5,
                tier=AutonomyTier.COUNTDOWN_CONFIRM,
                rule="score_between_confirm_and_auto",
                bad_extra="nope",
            )

    def test_decision_trace_invalid_rule_raises(self) -> None:
        with pytest.raises(ValidationError):
            DecisionTrace(
                tool_id="t",
                reversibility_score=5,
                threshold_auto_raw=8,
                threshold_confirm_raw=5,
                user_intent_modifier=2,
                user_explicit_intent=False,
                threshold_auto_effective=8,
                threshold_confirm_effective=5,
                tier=AutonomyTier.COUNTDOWN_CONFIRM,
                rule="bogus_rule",  # type: ignore[arg-type]
            )
