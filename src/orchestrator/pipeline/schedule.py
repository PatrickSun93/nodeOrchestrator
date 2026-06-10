"""Pipeline schedule arithmetic — interval-only (ADR-042 D3).

``compute_next_fire`` and ``validate_schedule_expr`` are **pure deterministic
code**: no LLM, no I/O.  Scheduling timing is orchestration, not a model
judgment (ADR-041 §9 / ADR-042 D3).

Supported in P5.1b: ``kind='interval'`` only.  ``kind='cron'`` is explicitly
deferred to a focused follow-on slice with its own greenfield-correctness
review (architect-routed Y1 = (c), ADR-042 D3).

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

_SUPPORTED_KINDS = frozenset({"interval", "cron"})


def validate_schedule_expr(kind: str, expr: str) -> None:
    """Validate a (kind, expr) pair; raise ValueError if invalid or deferred.

    ``kind='interval'``: ``expr`` must be a positive integer string (seconds).
    ``kind='cron'``:     deferred — raises ``ValueError`` unconditionally until
                         the cron follow-on slice lands.
    Unknown ``kind``:    raises ``ValueError``.
    """
    if kind not in _SUPPORTED_KINDS:
        raise ValueError(f"unknown schedule kind {kind!r}; supported: {sorted(_SUPPORTED_KINDS)}")
    if kind == "cron":
        raise ValueError(
            "cron scheduling is deferred to a follow-on slice; "
            "use kind='interval' in P5.1b"
        )
    # interval validation
    try:
        interval_s = int(expr)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"interval expr must be a positive integer seconds string, got {expr!r}"
        ) from exc
    if interval_s <= 0:
        raise ValueError(
            f"interval expr must be positive, got {interval_s!r}"
        )


def compute_next_fire(kind: str, expr: str, after_ms: int) -> int:
    """Compute the next fire timestamp (epoch-ms) after ``after_ms``.

    ``kind='interval'``: returns ``after_ms + int(expr) * 1000``.
    ``kind='cron'``:     raises ``NotImplementedError`` (deferred — see module
                         docstring; ``validate_schedule_expr`` rejects cron at
                         create time so the sweeper never sees a cron schedule).
    Unknown ``kind``:    raises ``ValueError``.
    """
    if kind not in _SUPPORTED_KINDS:
        raise ValueError(f"unknown schedule kind {kind!r}; supported: {sorted(_SUPPORTED_KINDS)}")
    if kind == "cron":
        raise NotImplementedError(
            "cron scheduling is deferred to a follow-on slice; "
            "use kind='interval' in P5.1b"
        )
    # interval: validate first so callers get a clear ValueError, not an int() traceback
    validate_schedule_expr(kind, expr)
    return after_ms + int(expr) * 1000
