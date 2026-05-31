"""Cross-room hypothesis matcher — promotion rule (a), structural.

Per ADR-017 D1-D5. Pure code, no LLM.

Advisory only — this module NEVER calls promote_hypothesis, inserts into
verified_knowledge, or calls event_store.append / append_in_transaction.
The matcher's only write is the candidate_for_promotion flag UPDATE on the
hypothesis table. Orthogonality to the promotion path is load-bearing per
ADR-016 D3/D10; the structural guard in test_constitution.py enforces it
via an AST call/import check, not a docstring scan.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from orchestrator.memory.schema import Hypothesis
from orchestrator.memory.store import _row_to_hypothesis
from orchestrator.memory.tags import normalize_tag


@dataclass(frozen=True)
class MatcherResult:
    """Advisory-only result from run_matcher. Per ADR-017 D5.

    Carries no promotion authority — it is a report, not a gate.
    """

    groups_inspected: int
    rows_newly_flagged: int


def run_matcher(
    conn: sqlite3.Connection,
    *,
    min_rooms: int = 2,
) -> MatcherResult:
    """Scan PENDING hypotheses; flag cross-room corroborated clusters.

    Groups hypotheses by canonical tag-set equality (via normalize_tag from
    the registry — NOT ad-hoc .lower()). For any group spanning >= min_rooms
    DISTINCT room_ids, sets candidate_for_promotion=True on those rows.

    Per ADR-017 D1-D5:
    - Normalize at read (D2): re-applies normalize_tag to each stored tag.
    - Empty canonical set excluded (D1): untagged hypotheses never grouped.
    - Distinct-room threshold (D4): counts distinct room_ids, not rows.
    - Deterministic (Principle 11): flagged id-set is a pure function of
      {(id, room_id, canonical-tagset, status)}; sort-by-id is for stable
      MatcherResult + UPDATE ordering only, not flag correctness.
    - Idempotent: re-running returns rows_newly_flagged == 0.
    - Monotonic: only False->True; never clears a flag (D4).

    Raises:
        ValueError: if min_rooms < 1.
    """
    if min_rooms < 1:
        raise ValueError(f"min_rooms must be >= 1, got {min_rooms}")

    rows = conn.execute(
        "SELECT * FROM hypothesis WHERE status = 'pending' ORDER BY id ASC"
    ).fetchall()

    # Group by canonical tag-set (normalize at read, per ADR-017 D2).
    groups: dict[frozenset[str], list[tuple[str, str]]] = {}  # key → [(id, room_id)]
    for row in rows:
        stored_tags: list[str] = json.loads(row["topic_tags"])
        canonical_set = frozenset(normalize_tag(t) for t in stored_tags)
        # Exclude empty canonical set (untagged hypotheses — ADR-017 D1).
        if not canonical_set:
            continue
        if canonical_set not in groups:
            groups[canonical_set] = []
        groups[canonical_set].append((row["id"], row["room_id"]))

    groups_inspected = len(groups)

    # Find qualifying groups: >= min_rooms DISTINCT room_ids.
    ids_to_flag: list[str] = []
    for entries in groups.values():
        distinct_rooms = {room_id for _, room_id in entries}
        if len(distinct_rooms) >= min_rooms:
            ids_to_flag.extend(id_ for id_, _ in entries)

    # Sort for stable UPDATE ordering (determinism of side effects, not flag correctness).
    ids_to_flag.sort()

    rows_newly_flagged = 0
    if ids_to_flag:
        # Defensive AND status='pending' guard (ADR-017 D4).
        placeholders = ",".join("?" * len(ids_to_flag))
        before = conn.execute(
            f"SELECT COUNT(*) FROM hypothesis WHERE id IN ({placeholders})"
            f" AND candidate_for_promotion = 0 AND status = 'pending'",
            ids_to_flag,
        ).fetchone()[0]
        conn.execute(
            f"UPDATE hypothesis SET candidate_for_promotion = 1"
            f" WHERE id IN ({placeholders}) AND status = 'pending'",
            ids_to_flag,
        )
        conn.commit()
        rows_newly_flagged = before

    return MatcherResult(
        groups_inspected=groups_inspected,
        rows_newly_flagged=rows_newly_flagged,
    )


def list_promotion_candidates(conn: sqlite3.Connection) -> list[Hypothesis]:
    """Return PENDING hypotheses flagged as cross-room corroborated.

    Per ADR-017 D6. Returns status='pending' AND candidate_for_promotion=True
    rows as frozen Hypothesis models, ordered by id ASC (deterministic).
    Covered by idx_hypothesis_status_candidate (store.py:48).
    No scope argument (Hypothesis has no scope field — schema.py:87-95).
    """
    rows = conn.execute(
        "SELECT * FROM hypothesis"
        " WHERE status = 'pending' AND candidate_for_promotion = 1"
        " ORDER BY id ASC"
    ).fetchall()
    return [_row_to_hypothesis(row) for row in rows]
