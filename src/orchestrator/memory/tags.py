"""Shared canonical tag registry for cross-room memory vocabulary.

Per ADR-018 D3 (normalize_tag) + D4 (resolve_tags). Pure code, no LLM.
memory/ never calls an LLM (Principle 5); normalize_tag is a pure string
transform; resolve_tags executes DB reads/writes but does NOT commit
(transaction-neutral — caller owns the transaction).
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from orchestrator.core.event import TimestampMs, now_ms


def normalize_tag(raw: str) -> str:
    """Deterministic canonicalization per ADR-018 D3.

    strip → lower (not casefold) → collapse whitespace runs to single hyphen.
    No punctuation stripping, no Unicode NFC — conservative floor that avoids
    distinct-concept collisions (c++ vs c, f# vs f).

    Known near-miss edge (G3, pinned): whitespace adjacent to a literal hyphen
    yields multiple hyphens — "LLM - Cost" → "llm---cost". Deterministic;
    does not collapse near-misses. See ADR-018 D3.
    """
    s = raw.strip().lower()
    return re.sub(r"\s+", "-", s)


@dataclass(frozen=True)
class TagResolution:
    """Result of resolve_tags. Per ADR-018 D4."""

    canonical: list[str] = field(default_factory=list)
    newly_registered: list[str] = field(default_factory=list)


def resolve_tags(
    proposed: list[str],
    conn: sqlite3.Connection,
    *,
    now: TimestampMs | None = None,
) -> TagResolution:
    """Normalize, dedup, auto-register tags. Transaction-neutral per ADR-018 D4.

    Does NOT commit — caller owns the transaction. Runs SELECT +
    INSERT OR IGNORE on the passed conn; the writes join whatever
    transaction the caller has open and roll back with it on failure.

    Raises:
        ValueError: if any proposed tag normalizes to "" (whitespace-only /
            empty input — producer bug; fail-loud per ADR-018 D4).
    """
    if not proposed:
        return TagResolution()

    ts = now if now is not None else now_ms()

    # Normalize and dedup, preserving first-occurrence order.
    seen: dict[str, None] = {}
    for raw in proposed:
        canonical = normalize_tag(raw)
        if canonical == "":
            raise ValueError(
                f"tag {raw!r} normalizes to empty string — producer bug (ADR-018 D4)"
            )
        seen[canonical] = None

    canonical_list = list(seen)

    # Split existing vs new.
    placeholders = ",".join("?" * len(canonical_list))
    existing = {
        row["canonical"]
        for row in conn.execute(
            f"SELECT canonical FROM tag WHERE canonical IN ({placeholders})",
            canonical_list,
        ).fetchall()
    }

    newly_registered: list[str] = []
    for c in canonical_list:
        if c not in existing:
            conn.execute(
                "INSERT OR IGNORE INTO tag (canonical, created_at) VALUES (?, ?)",
                (c, ts),
            )
            newly_registered.append(c)

    return TagResolution(canonical=canonical_list, newly_registered=newly_registered)
