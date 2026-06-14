"""Tests for pipeline/schedule.py — interval + cron arithmetic (ADR-042 D3 / P5.1b + P6.7).

Lens A invariants (each test must FAIL if the guard it asserts is removed):
- boundary: interval=1 fires exactly 1s later
- large-interval: no integer overflow
- non-positive expr rejected by validate_schedule_expr
- non-integer expr rejected
- empty-string expr rejected
- unknown kind rejected by both validate and compute
- cron: validate accepts well-formed, raises ValueError for malformed
- cron: compute_next_fire returns correct UTC epoch-ms for all classes below

Cron adversarial suite (P6.7 — each test FAILS if its specific guard is removed):
C5.1  Boundary rollover — minute/hour/day/month/year
C5.2  Month-end / leap-day
C5.3  */n alignment (aligned to 0, not arbitrary start; ragged; step>range)
C5.4  DOM-vs-DOW union (both restricted = OR, not AND)
C5.5  Year-wrap (Dec → next Jan)
C5.6  Malformed-reject (≥6 classes) + never-match horizon raise
C5.7  DST-irrelevance (UTC-only arithmetic; no hour skip)

All tests pass ``after_ms`` explicitly — wall clock never read.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from orchestrator.pipeline.schedule import compute_next_fire, validate_schedule_expr

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ms(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    """Return UTC epoch-ms for a given calendar minute (second=0)."""
    dt = datetime(year, month, day, hour, minute, 0, tzinfo=UTC)
    return int(dt.timestamp() * 1000)


def _dt(ms: int) -> datetime:
    """Convert epoch-ms back to a UTC datetime for assertions."""
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


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
# validate_schedule_expr — cron well-formed (replaces deferred tests)
# ---------------------------------------------------------------------------


def test_validate_cron_wellformed_every5min() -> None:
    """Well-formed cron must NOT raise after P6.7 implementation."""
    validate_schedule_expr("cron", "*/5 * * * *")


def test_validate_cron_wellformed_specific() -> None:
    validate_schedule_expr("cron", "0 12 * * 1")


def test_validate_cron_wellformed_complex() -> None:
    validate_schedule_expr("cron", "0,30 8-17 1,15 * 1-5")


def test_validate_cron_dow_7_alias_accepted() -> None:
    """DOW value 7 is accepted as a Sunday alias (Vixie convention)."""
    validate_schedule_expr("cron", "0 0 * * 7")


# ---------------------------------------------------------------------------
# validate_schedule_expr — unknown kind
# ---------------------------------------------------------------------------


def test_validate_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unknown schedule kind"):
        validate_schedule_expr("monthly", "1")


# ---------------------------------------------------------------------------
# C5.6 — Malformed cron: ≥6 reject classes (fail-on-revert: removing parser
#         guards turns these from ValueError-raises to silent accepts)
# ---------------------------------------------------------------------------


def test_validate_cron_rejects_4_fields() -> None:
    """Wrong field count (4) must be rejected."""
    with pytest.raises(ValueError, match="5 fields"):
        validate_schedule_expr("cron", "0 * * *")


def test_validate_cron_rejects_6_fields() -> None:
    """Wrong field count (6) must be rejected."""
    with pytest.raises(ValueError, match="5 fields"):
        validate_schedule_expr("cron", "0 0 * * * *")


def test_validate_cron_rejects_minute_out_of_range() -> None:
    """Minute 60 is out of range [0,59]."""
    with pytest.raises(ValueError):
        validate_schedule_expr("cron", "60 * * * *")


def test_validate_cron_rejects_hour_out_of_range() -> None:
    """Hour 24 is out of range [0,23]."""
    with pytest.raises(ValueError):
        validate_schedule_expr("cron", "0 24 * * *")


def test_validate_cron_rejects_dom_out_of_range() -> None:
    """DOM 32 is out of range [1,31]."""
    with pytest.raises(ValueError):
        validate_schedule_expr("cron", "0 0 32 * *")


def test_validate_cron_rejects_month_zero() -> None:
    """Month 0 is out of range [1,12]."""
    with pytest.raises(ValueError):
        validate_schedule_expr("cron", "0 0 * 0 *")


def test_validate_cron_rejects_month_13() -> None:
    """Month 13 is out of range [1,12]."""
    with pytest.raises(ValueError):
        validate_schedule_expr("cron", "0 0 * 13 *")


def test_validate_cron_rejects_dow_8() -> None:
    """DOW 8 is out of range [0,7]."""
    with pytest.raises(ValueError):
        validate_schedule_expr("cron", "0 0 * * 8")


def test_validate_cron_rejects_step_zero() -> None:
    """*/0 step-zero must be rejected."""
    with pytest.raises(ValueError, match="step"):
        validate_schedule_expr("cron", "*/0 * * * *")


def test_validate_cron_rejects_inverted_range() -> None:
    """Inverted range 5-2 must be rejected."""
    with pytest.raises(ValueError, match="inverted"):
        validate_schedule_expr("cron", "5-2 * * * *")


def test_validate_cron_rejects_non_numeric_step() -> None:
    """Non-numeric step */x must be rejected."""
    with pytest.raises(ValueError):
        validate_schedule_expr("cron", "*/x * * * *")


def test_validate_cron_rejects_non_numeric_value() -> None:
    """Non-numeric value in field must be rejected."""
    with pytest.raises(ValueError):
        validate_schedule_expr("cron", "a * * * *")


def test_validate_cron_rejects_empty_expr() -> None:
    """Empty expr must be rejected."""
    with pytest.raises(ValueError, match="empty"):
        validate_schedule_expr("cron", "")


def test_validate_cron_rejects_whitespace_only() -> None:
    """Whitespace-only expr must be rejected."""
    with pytest.raises(ValueError, match="empty"):
        validate_schedule_expr("cron", "   ")


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
# compute_next_fire — unknown kind
# ---------------------------------------------------------------------------


def test_compute_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unknown schedule kind"):
        compute_next_fire("daily", "1", after_ms=0)


# ---------------------------------------------------------------------------
# C5.1 — Boundary rollover
# ---------------------------------------------------------------------------


def test_cron_rollover_minute_to_hour() -> None:
    """59 23 * * * from 23:58 → lands at 23:59 same day."""
    after = _ms(2024, 3, 15, 23, 58)
    result = compute_next_fire("cron", "59 23 * * *", after_ms=after)
    dt = _dt(result)
    assert dt.minute == 59
    assert dt.hour == 23
    assert dt.day == 15


def test_cron_rollover_crosses_midnight() -> None:
    """59 23 * * * from 23:59 → lands at 23:59 on the NEXT day (crosses midnight+day)."""
    after = _ms(2024, 3, 15, 23, 59)
    result = compute_next_fire("cron", "59 23 * * *", after_ms=after)
    dt = _dt(result)
    assert dt.minute == 59
    assert dt.hour == 23
    assert dt.day == 16
    assert dt.month == 3


def test_cron_rollover_year_boundary() -> None:
    """59 23 31 12 * from Dec 31 23:59 → next fire is Dec 31 23:59 next year.

    Fail-on-revert: removing year-rollover from stdlib datetime breaks this.
    """
    # after = Dec 31 23:59 UTC 2024 (a Wednesday)
    after = _ms(2024, 12, 31, 23, 59)
    result = compute_next_fire("cron", "59 23 31 12 *", after_ms=after)
    dt = _dt(result)
    assert dt.year == 2025
    assert dt.month == 12
    assert dt.day == 31
    assert dt.hour == 23
    assert dt.minute == 59


# ---------------------------------------------------------------------------
# C5.2 — Month-end + leap-day
# ---------------------------------------------------------------------------


def test_cron_dom31_skips_short_months() -> None:
    """0 0 31 * * must skip months that don't have a 31st (Apr, Jun, Sep, Nov, Feb).

    Fail-on-revert: removing the day-of-month match check breaks this.
    """
    # after = March 31 00:00 UTC 2024
    after = _ms(2024, 3, 31, 0, 0)
    result = compute_next_fire("cron", "0 0 31 * *", after_ms=after)
    dt = _dt(result)
    # Apr has 30 days → skip; next 31 is May 31
    assert dt.month == 5
    assert dt.day == 31
    assert dt.year == 2024


def test_cron_feb29_only_on_leap_year() -> None:
    """0 0 29 2 * must fire only on Feb 29 — a leap-year-only date.

    Exercises the ~4-year horizon cap; must resolve (not raise).
    Fail-on-revert: removing the bounded search or month check breaks this.
    """
    # after = Feb 29 2024 00:00 UTC (2024 is a leap year)
    after = _ms(2024, 2, 29, 0, 0)
    result = compute_next_fire("cron", "0 0 29 2 *", after_ms=after)
    dt = _dt(result)
    # Next leap year after 2024 is 2028
    assert dt.year == 2028
    assert dt.month == 2
    assert dt.day == 29
    assert dt.hour == 0
    assert dt.minute == 0


def test_cron_feb29_not_leap_searches_forward() -> None:
    """0 0 29 2 * from a non-leap year must skip forward to next leap year."""
    after = _ms(2025, 1, 1, 0, 0)
    result = compute_next_fire("cron", "0 0 29 2 *", after_ms=after)
    dt = _dt(result)
    assert dt.year == 2028
    assert dt.month == 2
    assert dt.day == 29


# ---------------------------------------------------------------------------
# C5.3 — */n alignment (aligned to 0, NOT "n from arbitrary start")
# ---------------------------------------------------------------------------


def test_cron_step15_fires_at_aligned_minutes() -> None:
    """*/15 must fire at :00, :15, :30, :45 — aligned to 0, not start+15.

    Fail-on-revert: if step is not aligned to 0, :00/:30 assertions fail.
    """
    # after = 2024-06-01 00:01 UTC
    after = _ms(2024, 6, 1, 0, 1)
    r1 = compute_next_fire("cron", "*/15 * * * *", after_ms=after)
    assert _dt(r1).minute == 15

    after2 = _ms(2024, 6, 1, 0, 16)
    r2 = compute_next_fire("cron", "*/15 * * * *", after_ms=after2)
    assert _dt(r2).minute == 30

    after3 = _ms(2024, 6, 1, 0, 31)
    r3 = compute_next_fire("cron", "*/15 * * * *", after_ms=after3)
    assert _dt(r3).minute == 45

    # Wrap to next hour
    after4 = _ms(2024, 6, 1, 0, 46)
    r4 = compute_next_fire("cron", "*/15 * * * *", after_ms=after4)
    assert _dt(r4).minute == 0
    assert _dt(r4).hour == 1


def test_cron_step7_ragged_resets_at_zero() -> None:
    """*/7 for minutes gives 0,7,14,21,28,35,42,49,56 then resets to 0 next hour.

    Fail-on-revert: a non-zero-aligned step would not produce :00 as the first value.
    """
    after = _ms(2024, 6, 1, 0, 56)
    result = compute_next_fire("cron", "*/7 * * * *", after_ms=after)
    dt = _dt(result)
    assert dt.minute == 0
    assert dt.hour == 1


def test_cron_step_larger_than_range() -> None:
    """*/90 for minutes (0-59): only value is 0 (range(0,60,90) = [0]).

    Fail-on-revert: if step > range collapses incorrectly, wrong minute fires.
    """
    after = _ms(2024, 6, 1, 5, 1)
    result = compute_next_fire("cron", "*/90 * * * *", after_ms=after)
    dt = _dt(result)
    assert dt.minute == 0
    assert dt.hour == 6


# ---------------------------------------------------------------------------
# C5.4 — DOM-vs-DOW union
# ---------------------------------------------------------------------------


def test_cron_dow_only_restriction() -> None:
    """0 0 * * 1 fires only on Mondays (DOW-only restriction)."""
    # 2024-06-01 is a Saturday
    after = _ms(2024, 6, 1, 0, 0)
    result = compute_next_fire("cron", "0 0 * * 1", after_ms=after)
    dt = _dt(result)
    # Next Monday from 2024-06-01 is 2024-06-03
    assert dt.weekday() == 0  # Python Monday=0
    assert dt.year == 2024
    assert dt.month == 6
    assert dt.day == 3


def test_cron_dom_only_restriction() -> None:
    """0 0 1 * * fires only on the 1st of each month (DOM-only restriction)."""
    after = _ms(2024, 6, 1, 0, 0)
    result = compute_next_fire("cron", "0 0 1 * *", after_ms=after)
    dt = _dt(result)
    assert dt.day == 1
    assert dt.month == 7
    assert dt.year == 2024


def test_cron_dom_dow_both_restricted_union_friday_not_13th() -> None:
    """0 0 13 * 5 (13th OR Friday) fires on a Friday that is NOT the 13th.

    This asserts OR-union — if intersection were used, it would NOT fire.
    Fail-on-revert: changing OR to AND makes this test fail.
    """
    # Find a Friday that is not the 13th in 2024
    # 2024-01-05 is a Friday and NOT the 13th
    after = _ms(2024, 1, 4, 0, 0)
    result = compute_next_fire("cron", "0 0 13 * 5", after_ms=after)
    dt = _dt(result)
    cron_dow = (dt.weekday() + 1) % 7  # cron Sunday=0, ..., Saturday=6
    # Should fire on Jan 5 (Friday=5 in cron) OR Jan 13 (the 13th)
    # 2024-01-05 00:00 is the next fire
    assert dt.year == 2024
    assert dt.month == 1
    assert dt.day == 5
    assert cron_dow == 5  # Friday in cron convention


def test_cron_dom_dow_both_restricted_union_13th_not_friday() -> None:
    """0 0 13 * 5 fires on the 13th even if it's not a Friday.

    2024-02-13 is a Tuesday — should still fire (DOM match in union).
    Fail-on-revert: intersection would skip this date.
    """
    # after = Feb 12 2024
    after = _ms(2024, 2, 12, 0, 0)
    result = compute_next_fire("cron", "0 0 13 * 5", after_ms=after)
    dt = _dt(result)
    # Should fire on Feb 13 (13th, even though it's Tuesday not Friday)
    assert dt.year == 2024
    assert dt.month == 2
    assert dt.day == 13


def test_cron_weekday_conversion_sunday_is_0() -> None:
    """0 0 * * 0 fires on Sundays.  Pins the Python weekday()+1)%7 conversion.

    Python Mon=0..Sun=6; cron Sun=0..Sat=6; cron_dow = (weekday()+1)%7.
    Fail-on-revert: removing the +1 offset makes Sunday land on Monday.
    """
    # 2024-06-02 is a Sunday
    after = _ms(2024, 6, 1, 23, 59)
    result = compute_next_fire("cron", "0 0 * * 0", after_ms=after)
    dt = _dt(result)
    assert dt.weekday() == 6  # Python Sunday=6
    assert dt.year == 2024
    assert dt.month == 6
    assert dt.day == 2


def test_cron_dow_7_alias_treated_as_sunday() -> None:
    """DOW 7 is treated identically to DOW 0 (both = Sunday).

    Fail-on-revert: if 7 is not normalised to 0, the Sunday match is missed.
    """
    # 2024-06-02 is a Sunday
    after = _ms(2024, 6, 1, 23, 59)
    result_0 = compute_next_fire("cron", "0 0 * * 0", after_ms=after)
    result_7 = compute_next_fire("cron", "0 0 * * 7", after_ms=after)
    assert result_0 == result_7


# ---------------------------------------------------------------------------
# C5.5 — Year-wrap
# ---------------------------------------------------------------------------


def test_cron_year_wrap_jan1() -> None:
    """0 0 1 1 * from mid-December advances year by 1.

    Fail-on-revert: if year rollover is not handled by stdlib datetime, this breaks.
    """
    after = _ms(2024, 12, 15, 0, 0)
    result = compute_next_fire("cron", "0 0 1 1 *", after_ms=after)
    dt = _dt(result)
    assert dt.year == 2025
    assert dt.month == 1
    assert dt.day == 1
    assert dt.hour == 0
    assert dt.minute == 0


# ---------------------------------------------------------------------------
# C5.6 — never-match horizon raise
# ---------------------------------------------------------------------------


def test_cron_feb31_never_matches_raises() -> None:
    """0 0 31 2 * (Feb 31) never exists — must raise ValueError via horizon cap.

    Fail-on-revert: removing the horizon cap makes this loop forever.
    """
    after = _ms(2024, 1, 1, 0, 0)
    with pytest.raises(ValueError):
        compute_next_fire("cron", "0 0 31 2 *", after_ms=after)


def test_cron_feb30_never_matches_raises() -> None:
    """0 0 30 2 * (Feb 30) never exists — must raise ValueError."""
    after = _ms(2024, 1, 1, 0, 0)
    with pytest.raises(ValueError):
        compute_next_fire("cron", "0 0 30 2 *", after_ms=after)


# ---------------------------------------------------------------------------
# C5.7 — DST-irrelevance (UTC-only)
# ---------------------------------------------------------------------------


def test_cron_dst_spring_forward_no_skip() -> None:
    """A cron firing at 02:30 UTC during a US spring-forward DST instant computes
    normally in UTC — no hour skip or repeat.

    US Eastern spring-forward 2024: clocks jump from 02:00 to 03:00 on 2024-03-10
    (local time).  In UTC this is 07:00 → 08:00.  A cron '30 2 10 3 *' fires at
    02:30 UTC on 2024-03-10, which is a perfectly valid UTC minute.

    Fail-on-revert: if the evaluator used local time, 02:30 local would not exist
    during spring-forward and the assertion would fail or raise.
    """
    after = _ms(2024, 3, 10, 2, 29)  # UTC 02:29 on spring-forward day
    result = compute_next_fire("cron", "30 2 10 3 *", after_ms=after)
    dt = _dt(result)
    # Must fire at UTC 02:30 — unaffected by US local DST
    assert dt.year == 2024
    assert dt.month == 3
    assert dt.day == 10
    assert dt.hour == 2
    assert dt.minute == 30
