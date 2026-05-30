"""Cross-room verified knowledge lookup.

Per ADR-016 D6: lookup_verified_knowledge filters by scope + topic_tags (OR-
semantics), ordered by last_validated DESC, id ASC. No LLM, no ranking.
"""

from __future__ import annotations

import json
import sqlite3

from orchestrator.memory.schema import VerifiedKnowledge, VKScope
from orchestrator.memory.store import _row_to_vk
from orchestrator.memory.tags import normalize_tag


def lookup_verified_knowledge(
    topic_tags: list[str],
    scope: VKScope,
    *,
    conn: sqlite3.Connection,
) -> list[VerifiedKnowledge]:
    """Cross-room verified knowledge lookup.

    Per ADR-016 D6:
      - scope: exact match on VKScope.
      - topic_tags: OR-semantics — any input tag matches any row tag.
      - Empty topic_tags raises ValueError (per Y4 alpha-(b) routing —
        fail-loud to distinguish "I want all" from a caller bug).
      - Ordering: last_validated DESC, id ASC (deterministic).
      - No LLM, no ranking, no similarity.
    """
    if not topic_tags:
        raise ValueError("topic_tags must be non-empty; pass at least one tag")

    rows = conn.execute(
        "SELECT * FROM verified_knowledge WHERE scope = ? ORDER BY last_validated DESC, id ASC",
        (scope.value,),
    ).fetchall()

    # Normalize BOTH query and stored tags at match-time (ADR-018 D7, refines ADR-016 D6).
    # Both sides normalization ensures legacy raw-stored rows (pre-P2.1, not backfilled)
    # are found by normalized queries — making no-backfill (ADR-018 D8) sound.
    query_set = {normalize_tag(t) for t in topic_tags}
    results: list[VerifiedKnowledge] = []
    for row in rows:
        row_tags = {normalize_tag(t) for t in json.loads(row["topic_tags"])}
        if query_set & row_tags:
            results.append(_row_to_vk(row))

    return results
