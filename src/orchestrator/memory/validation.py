"""Rule-(c) external ground-truth validation reader (ADR-019 D2).

Pure-derivation reader over the event log — no LLM, no writes.
Returns PENDING hypotheses that have ≥1 confirmed external_validation event.

Per ADR-019 D2: the event itself is the surface (no flag, no table).
Per Principle 5 / ADR-016 Hard Requirements: memory/ calls no LLM.
"""

from __future__ import annotations

import json
import sqlite3

from orchestrator.memory.schema import Hypothesis
from orchestrator.memory.store import _row_to_hypothesis


def list_externally_validated_candidates(conn: sqlite3.Connection) -> list[Hypothesis]:
    """PENDING hypotheses with >=1 confirmed external_validation event. Pure code, no LLM.

    Scans external_validation events, Python-parses each metadata (no JSON1
    assumption — mirrors ADR-016 D6 posture), collects validated_hypothesis_id
    where verdict == 'confirmed', then returns the subset that are extant +
    status == 'pending' Hypothesis rows, ordered by id ASC.

    Writes nothing. Calling twice changes nothing.

    Per ADR-019 D2: the reader trusts that every stored external_validation
    event is well-formed (guaranteed by append-time validate_metadata +
    ExternalValidationMeta extra="forbid"). A malformed row is unreachable
    through the sanctioned path; any belt-and-suspenders guard must raise,
    never silently skip (ADR-018 D4 fail-loud posture).
    """
    rows = conn.execute("SELECT metadata FROM events WHERE type = 'external_validation'").fetchall()

    confirmed_ids: set[str] = set()
    for row in rows:
        meta = json.loads(row[0])
        if meta.get("verdict") == "confirmed":
            hyp_id = meta.get("validated_hypothesis_id")
            if hyp_id:
                confirmed_ids.add(hyp_id)

    if not confirmed_ids:
        return []

    placeholders = ",".join("?" * len(confirmed_ids))
    hyp_rows = conn.execute(
        f"SELECT * FROM hypothesis WHERE id IN ({placeholders}) AND status = 'pending'"
        " ORDER BY id ASC",
        tuple(sorted(confirmed_ids)),
    ).fetchall()

    return [_row_to_hypothesis(r) for r in hyp_rows]
