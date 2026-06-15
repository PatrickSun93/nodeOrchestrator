"""Pipeline schedule arithmetic — interval + cron (ADR-042 D3, amended by P6.7).

``compute_next_fire`` and ``validate_schedule_expr`` are **pure deterministic
code**: no LLM, no I/O.  Scheduling timing is orchestration, not a model
judgment (ADR-041 §9 / ADR-042 D3).

Supported kinds:

- ``kind='interval'``: ``expr`` is a positive integer seconds string.
- ``kind='cron'``: 5-field UTC-only subset (ADR-042 D3 — implemented in P6.7).

Cron subset contract (ADR-042 D3, P6.7 implementation):
  Fields (whitespace-separated): ``minute hour DOM month DOW``
  Domains:  minute 0-59, hour 0-23, DOM 1-31, month 1-12, DOW 0-6 (0=Sun).
  DOW ``7`` accepted as a Sunday alias (Vixie convention), normalised to 0.
  Tokens per field (compositional, comma-list of terms):
    ``*`` (full domain), ``a`` (single), ``a-b`` (range), ``*/n`` (step),
    ``a-b/n`` (stepped range). ``n >= 1``.  No name tokens (``JAN``/``MON``).
  DOM-vs-DOW: when both fields are restricted (not literal ``*``), a minute
    matches if ``DOM matches OR DOW matches`` (standard Vixie union).
  Bounded never-match guard: forward search capped at ~4 years of minutes;
    raises ``ValueError`` if no match found within the horizon.
  All calendar arithmetic delegated to stdlib ``datetime`` / ``timezone.utc``.

N2 — drift note:
  The sweeper act recomputes ``next_fire = compute_next_fire(kind, expr, now)``
  at **claim time** (P5.1b-4 step 3), not from the previous ``next_fire``
  value.  This means an ``interval`` schedule drifts by up to
  ``sweep_interval_s`` (plus writer-queue latency) per fire.  That is the
  **correct price of the skip-to-next posture** ratified in B3 / ADR-042
  D4/D5: computing from the old ``next_fire`` would re-introduce the
  backfill-storm hazard that B3 explicitly rejects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

_SUPPORTED_KINDS = frozenset({"interval", "cron"})

# Forward-search cap: ≥ 8*366*24*60 minutes to cover the century-boundary Feb-29 gap
# (1896→1904, 2096→2104 skip non-leap 1900/2100 → worst case ~8 years between consecutive
# Feb-29 occurrences).  Fail-closed on exhaustion.
_CRON_SEARCH_HORIZON_MIN: int = 8 * 366 * 24 * 60  # 4_216_320


@dataclass(frozen=True)
class _CronFields:
    """Parsed cron expression: five frozen sets of allowed values + restriction flags."""

    minutes: frozenset[int]  # 0-59
    hours: frozenset[int]  # 0-23
    doms: frozenset[int]  # 1-31
    months: frozenset[int]  # 1-12
    dows: frozenset[int]  # 0-6 (0=Sun)
    dom_restricted: bool  # True when DOM field is NOT literal "*"
    dow_restricted: bool  # True when DOW field is NOT literal "*"


def _expand_field(raw: str, lo: int, hi: int) -> frozenset[int]:
    """Expand a single cron field token (or comma-list) into a frozenset of ints.

    Supported terms (compositional, comma-separated):
      *        → full domain [lo, hi]
      */n      → stepped full domain, step n >= 1
      a        → single value
      a-b      → inclusive range, a <= b
      a-b/n    → stepped range, step n >= 1

    Raises ValueError on any malformed token, out-of-range value, or step <= 0.
    """
    result: set[int] = set()
    for term in raw.split(","):
        term = term.strip()
        if not term:
            raise ValueError(f"empty term in cron field {raw!r}")

        if "/" in term:
            base_part, step_part = term.split("/", 1)
            try:
                step = int(step_part)
            except ValueError as exc:
                raise ValueError(f"non-integer step in cron term {term!r}") from exc
            if step < 1:
                raise ValueError(f"step must be >= 1, got {step} in {term!r}")

            if base_part == "*":
                start, end = lo, hi
            elif "-" in base_part:
                start, end = _parse_range(base_part, lo, hi)
            else:
                try:
                    start = int(base_part)
                except ValueError as exc:
                    raise ValueError(f"non-integer value in cron term {term!r}") from exc
                if not (lo <= start <= hi):
                    raise ValueError(f"value {start} out of range [{lo},{hi}] in {term!r}")
                end = hi

            result.update(range(start, end + 1, step))

        elif term == "*":
            result.update(range(lo, hi + 1))

        elif "-" in term:
            start, end = _parse_range(term, lo, hi)
            result.update(range(start, end + 1))

        else:
            try:
                v = int(term)
            except ValueError as exc:
                raise ValueError(f"non-integer value in cron term {term!r}") from exc
            if not (lo <= v <= hi):
                raise ValueError(f"value {v} out of range [{lo},{hi}] in {term!r}")
            result.add(v)

    return frozenset(result)


def _parse_range(raw: str, lo: int, hi: int) -> tuple[int, int]:
    """Parse 'a-b', validate bounds, return (a, b)."""
    parts = raw.split("-", 1)
    if len(parts) != 2:
        raise ValueError(f"invalid range {raw!r}")
    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise ValueError(f"non-integer in range {raw!r}") from exc
    if not (lo <= a <= hi):
        raise ValueError(f"range start {a} out of [{lo},{hi}] in {raw!r}")
    if not (lo <= b <= hi):
        raise ValueError(f"range end {b} out of [{lo},{hi}] in {raw!r}")
    if a > b:
        raise ValueError(f"inverted range {a}>{b} in {raw!r}")
    return a, b


def _parse_cron(expr: str) -> _CronFields:
    """Parse a 5-field cron expression; raise ValueError on any malformed input.

    Returns a _CronFields with pre-expanded value sets and restriction flags.
    """
    if not expr or not expr.strip():
        raise ValueError("cron expr is empty or whitespace-only")

    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"cron expr must have exactly 5 fields, got {len(fields)}: {expr!r}")

    min_raw, hr_raw, dom_raw, mon_raw, dow_raw = fields

    minutes = _expand_field(min_raw, 0, 59)
    hours = _expand_field(hr_raw, 0, 23)
    doms = _expand_field(dom_raw, 1, 31)
    months = _expand_field(mon_raw, 1, 12)

    # Expand DOW allowing 0-7 (7 = Sunday alias), then normalise 7 → 0
    dows_raw_set = _expand_field_dow(dow_raw, 0, 7)
    dows = frozenset(0 if v == 7 else v for v in dows_raw_set)

    dom_restricted = dom_raw.strip() != "*"
    dow_restricted = dow_raw.strip() != "*"

    return _CronFields(
        minutes=minutes,
        hours=hours,
        doms=doms,
        months=months,
        dows=dows,
        dom_restricted=dom_restricted,
        dow_restricted=dow_restricted,
    )


def _expand_field_dow(raw: str, lo: int, hi: int) -> frozenset[int]:
    """Expand DOW field allowing values 0-7 (7 = Sunday alias for 0)."""
    result: set[int] = set()
    for term in raw.split(","):
        term = term.strip()
        if not term:
            raise ValueError(f"empty term in cron DOW field {raw!r}")

        if "/" in term:
            base_part, step_part = term.split("/", 1)
            try:
                step = int(step_part)
            except ValueError as exc:
                raise ValueError(f"non-integer step in cron term {term!r}") from exc
            if step < 1:
                raise ValueError(f"step must be >= 1, got {step} in {term!r}")

            if base_part == "*":
                start, end = lo, 6  # DOW wildcard spans 0-6 (not 7)
            elif "-" in base_part:
                start, end = _parse_range(base_part, lo, hi)
            else:
                try:
                    start = int(base_part)
                except ValueError as exc:
                    raise ValueError(f"non-integer value in cron term {term!r}") from exc
                if not (lo <= start <= hi):
                    raise ValueError(f"value {start} out of range [{lo},{hi}] in {term!r}")
                end = hi

            result.update(range(start, end + 1, step))

        elif term == "*":
            result.update(range(lo, 7))  # 0-6 inclusive

        elif "-" in term:
            start, end = _parse_range(term, lo, hi)
            result.update(range(start, end + 1))

        else:
            try:
                v = int(term)
            except ValueError as exc:
                raise ValueError(f"non-integer value in cron term {term!r}") from exc
            if not (lo <= v <= hi):
                raise ValueError(f"value {v} out of range [{lo},{hi}] in {term!r}")
            result.add(v)

    return frozenset(result)


def _cron_day_matches(dt: datetime, fields: _CronFields) -> bool:
    """Return True if dt's day satisfies the DOM/DOW union rule.

    DOM-vs-DOW (standard Vixie union):
      - both unrestricted (*) → True
      - only DOM restricted   → DOM must match
      - only DOW restricted   → DOW must match
      - both restricted       → DOM OR DOW must match (union, never intersection)

    Python weekday(): Mon=0..Sun=6.  Cron DOW: Sun=0..Sat=6.
    Conversion: cron_dow = (dt.weekday() + 1) % 7.
    """
    cron_dow = (dt.weekday() + 1) % 7

    if not fields.dom_restricted and not fields.dow_restricted:
        return True
    if fields.dom_restricted and not fields.dow_restricted:
        return dt.day in fields.doms
    if not fields.dom_restricted and fields.dow_restricted:
        return cron_dow in fields.dows
    # Both restricted → OR-union (Vixie)
    return dt.day in fields.doms or cron_dow in fields.dows


def validate_schedule_expr(kind: str, expr: str) -> None:
    """Validate a (kind, expr) pair; raise ValueError if invalid.

    ``kind='interval'``: ``expr`` must be a positive integer string (seconds).
    ``kind='cron'``:     ``expr`` must be a valid 5-field UTC cron expression
                         (subset per ADR-042 D3 / P6.7); malformed cron raises
                         ``ValueError``.
    Unknown ``kind``:    raises ``ValueError``.
    """
    if kind not in _SUPPORTED_KINDS:
        raise ValueError(f"unknown schedule kind {kind!r}; supported: {sorted(_SUPPORTED_KINDS)}")
    if kind == "cron":
        _parse_cron(expr)  # raises ValueError on any malformed input
        return
    # interval validation
    try:
        interval_s = int(expr)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"interval expr must be a positive integer seconds string, got {expr!r}"
        ) from exc
    if interval_s <= 0:
        raise ValueError(f"interval expr must be positive, got {interval_s!r}")


def compute_next_fire(kind: str, expr: str, after_ms: int) -> int:
    """Compute the next fire timestamp (epoch-ms) after ``after_ms``.

    ``kind='interval'``: returns ``after_ms + int(expr) * 1000``.
    ``kind='cron'``:     returns the epoch-ms of the first whole UTC minute
                         strictly after ``after_ms`` that matches the cron expr.
                         Raises ``ValueError`` if no match found within the
                         search horizon (~4 years).
    Unknown ``kind``:    raises ``ValueError``.
    """
    if kind not in _SUPPORTED_KINDS:
        raise ValueError(f"unknown schedule kind {kind!r}; supported: {sorted(_SUPPORTED_KINDS)}")
    if kind == "cron":
        return _compute_cron_next_fire(expr, after_ms)
    # interval: validate first so callers get a clear ValueError, not an int() traceback
    validate_schedule_expr(kind, expr)
    return after_ms + int(expr) * 1000


def _compute_cron_next_fire(expr: str, after_ms: int) -> int:
    """Bounded forward-search for the next UTC minute matching a cron expression.

    Raises ValueError if no match is found within _CRON_SEARCH_HORIZON_MIN minutes.
    All calendar arithmetic is delegated to stdlib datetime + timezone.utc.
    """
    fields = _parse_cron(expr)

    # Start at the first whole minute strictly greater than after_ms
    after_dt = datetime.fromtimestamp(after_ms / 1000, tz=UTC)
    # Floor to current minute, then advance by one minute to be strictly after
    candidate = after_dt.replace(second=0, microsecond=0) + timedelta(minutes=1)

    for _ in range(_CRON_SEARCH_HORIZON_MIN):
        if (
            candidate.minute in fields.minutes
            and candidate.hour in fields.hours
            and candidate.month in fields.months
            and _cron_day_matches(candidate, fields)
        ):
            return int(candidate.timestamp() * 1000)
        candidate += timedelta(minutes=1)

    raise ValueError(
        f"cron expr {expr!r} has no match within {_CRON_SEARCH_HORIZON_MIN} minutes "
        f"(~{_CRON_SEARCH_HORIZON_MIN // (60 * 24 * 365)} years); expr may be unsatisfiable"
    )
