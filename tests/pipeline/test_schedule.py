"""Tests for pipeline/schedule.py — interval-only arithmetic (ADR-042 D3 / P5.1b-1).

Lens A invariants (each test must FAIL if the guard it asserts is removed):
- boundary: interval=1 fires exactly 1s later
- large-interval: no integer overflow
- non-positive expr rejected by validate_schedule_expr
- non-integer expr rejected
- empty-string expr rejected
- unknown kind rejected by both validate and compute
- cron: validate raises ValueError, compute raises NotImplementedError

All tests pass ``after_ms`` explicitly — wall clock never read.
"""

from __future__ import annotations

import pytest

from orchestrator.pipeline.schedule import compute_next_fire, validate_schedule_expr

# ---------------------------------------------------------------------------
# validate_schedule_expr — interval
# ---------------------------------------------------------------------------


def test_validate_interval_boundary_one() -> None:
    """interval=1 is the minimum valid value — must not raise."""
    validate_schedule_expr("interval", "1")


def test_validate_interval_typical() -> None:
    validate_schedule_expr("interval", "3600")


def test_validate_interval_non_positive_zero() -> None:
    with pytest.raises(ValueError, match="positive"):
        validate_schedule_expr("interval", "0")


def test_validate_interval_non_positive_negative() -> None:
    with pytest.raises(ValueError, match="positive"):
        validate_schedule_expr("interval", "-1")


def test_validate_interval_non_integer_float() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        validate_schedule_expr("interval", "1.5")


def test_validate_interval_non_integer_alpha() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        validate_schedule_expr("interval", "abc")


def test_validate_interval_empty_string() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        validate_schedule_expr("interval", "")


# ---------------------------------------------------------------------------
# validate_schedule_expr — cron deferred
# ---------------------------------------------------------------------------


def test_validate_cron_raises_valueerror() -> None:
    """Cron is deferred — validate must raise ValueError for any expr."""
    with pytest.raises(ValueError, match="deferred"):
        validate_schedule_expr("cron", "*/5 * * * *")


def test_validate_cron_raises_even_empty_expr() -> None:
    with pytest.raises(ValueError, match="deferred"):
        validate_schedule_expr("cron", "")


# ---------------------------------------------------------------------------
# validate_schedule_expr — unknown kind
# ---------------------------------------------------------------------------


def test_validate_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unknown schedule kind"):
        validate_schedule_expr("monthly", "1")


# ---------------------------------------------------------------------------
# compute_next_fire — interval
# ---------------------------------------------------------------------------


def test_compute_interval_boundary_one() -> None:
    """interval=1s: next_fire = after_ms + 1000."""
    result = compute_next_fire("interval", "1", after_ms=0)
    assert result == 1000


def test_compute_interval_typical() -> None:
    result = compute_next_fire("interval", "60", after_ms=1_000_000)
    assert result == 1_060_000


def test_compute_interval_large_no_overflow() -> None:
    """Large interval (10 years in seconds) plus a realistic epoch-ms should not overflow."""
    ten_years_s = 10 * 365 * 24 * 3600  # ~315_360_000
    after = 1_700_000_000_000  # epoch-ms circa 2023
    result = compute_next_fire("interval", str(ten_years_s), after_ms=after)
    assert result == after + ten_years_s * 1000
    assert isinstance(result, int)


# ---------------------------------------------------------------------------
# compute_next_fire — cron deferred → NotImplementedError
# ---------------------------------------------------------------------------


def test_compute_cron_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError, match="deferred"):
        compute_next_fire("cron", "*/5 * * * *", after_ms=0)


# ---------------------------------------------------------------------------
# compute_next_fire — unknown kind
# ---------------------------------------------------------------------------


def test_compute_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unknown schedule kind"):
        compute_next_fire("daily", "1", after_ms=0)
