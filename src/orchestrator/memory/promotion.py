"""User-confirm promotion of a Hypothesis row to VerifiedKnowledge.

Per ADR-016 D3: promote_hypothesis is the ONLY promotion path. No automatic
promotion. No LLM judgment. Eligibility = status == PENDING (code check).

Transaction sequence (ADR-016 D11):
  All three writes (decision event append + VK INSERT + Hypothesis UPDATE)
  execute inside a single SQLite transaction on event_store.conn.

NOTE on transaction ordering (P1.6.5-2 implementation note):
  Python sqlite3 only sets conn.in_transaction=True after the first DML
  statement. append_in_transaction checks this guard. Therefore, the
  Hypothesis status UPDATE runs FIRST inside with-conn to start the
  transaction; only then is append_in_transaction called. Order:
  UPDATE hypothesis → append_in_transaction → INSERT VK.
  All atomicity guarantees are preserved.
"""

from __future__ import annotations

import json
from typing import Any

from orchestrator.core.event import Event, EventType, generate_event_id, now_ms
from orchestrator.core.event_store import EventStore
from orchestrator.memory.exceptions import HypothesisNotFoundError, PromotionEligibilityError
from orchestrator.memory.schema import (
    HypothesisId,
    HypothesisStatus,
    VerifiedKnowledge,
    VKScope,
    generate_vk_id,
)
from orchestrator.memory.store import _row_to_vk, get_hypothesis_by_id


def promote_hypothesis(
    hyp_id: HypothesisId,
    user_id: str,
    *,
    scope: VKScope,
    topic_tags: list[str] | None = None,
    evidence: dict[str, Any] | None = None,
    event_store: EventStore,
) -> VerifiedKnowledge:
    """User-confirm promotion of a Hypothesis row to VerifiedKnowledge.

    Per ADR-016 D3. Atomic over: VK insert + Hypothesis.status='verified'
    update + decision event append. All writes use event_store.conn.

    NOTE (external Y7 alpha-(b)): no `conn` parameter. All three writes use
    event_store.conn, making the same-connection atomicity invariant
    unrepresentable-by-construction.

    Raises:
        HypothesisNotFoundError: hyp_id not in hypothesis table.
        PromotionEligibilityError: hypothesis.status != PENDING.
        sqlite3.IntegrityError: double-promotion (UNIQUE constraint on
            promoted_from_hypothesis_id — schema-level defense-in-depth
            per external Y9, independent of status check).
    """
    conn = event_store.conn

    # Step 1: load hypothesis (outside transaction — SELECT only).
    hyp = get_hypothesis_by_id(hyp_id, conn=conn)
    if hyp is None:
        raise HypothesisNotFoundError(hyp_id)

    # Step 2: eligibility check.
    if hyp.status != HypothesisStatus.PENDING:
        raise PromotionEligibilityError(hyp_id, reason="not_pending")

    # Step 3: prepare promotion artifacts.
    vk_id = generate_vk_id()
    promotion_event_id = generate_event_id()
    ts = now_ms()

    decision_event = Event(
        id=promotion_event_id,
        room_id=hyp.room_id,  # originating room (ADR-016 D3 + Y5 alpha-(a))
        type=EventType.DECISION,
        author="system",
        timestamp=ts,
        content=f"Promoted hypothesis {hyp_id!r} to verified knowledge {vk_id!r}.",
        metadata={
            "based_on": list(hyp.source_event_ids),
            "trade_offs": {},
            "promotion": True,
            "hypothesis_id": str(hyp_id),
            "vk_id": str(vk_id),
        },
    )

    topic_tags_list = topic_tags or []
    evidence_dict = evidence or {}

    # Step 4: atomic transaction (ordering: UPDATE first to start transaction
    # so append_in_transaction's in_transaction guard passes).
    with conn:
        # 4c first (UPDATE hypothesis status) — starts the transaction.
        conn.execute(
            "UPDATE hypothesis SET status = ? WHERE id = ?",
            (HypothesisStatus.VERIFIED.value, str(hyp_id)),
        )

        # 4a: append decision event (in_transaction=True now).
        event_store.append_in_transaction(decision_event)

        # 4b: INSERT VK row (UNIQUE on promoted_from_hypothesis_id — Y9 backstop).
        conn.execute(
            """INSERT INTO verified_knowledge
                   (id, content, topic_tags, evidence, last_validated,
                    contradictions, scope, promoted_from_hypothesis_id,
                    promoted_by_user_id, promotion_event_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(vk_id),
                hyp.content,
                json.dumps(topic_tags_list),
                json.dumps(evidence_dict),
                ts,
                json.dumps([]),
                scope.value,
                str(hyp_id),
                user_id,
                str(promotion_event_id),
            ),
        )

    # Load and return the committed VK row.
    row = conn.execute(
        "SELECT * FROM verified_knowledge WHERE id = ?", (str(vk_id),)
    ).fetchone()
    return _row_to_vk(row)
