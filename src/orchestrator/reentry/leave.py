"""Leave-time generation: marker upsert + ProjectArchive composition.

record_leave_marker: persists the last-seen timestamp for (room_id, user_id).
generate_and_record_archive: composes code-derived archive fields + genuinely
  generates one_line_summary/spinoff_questions via ARCHIVE_SUMMARY_RENDER LLM
  call (content-gen, ADR-021 D5/D9), then persists via record_project_archive.

LLM is ONLY used for the semantic fields (content-gen render of facts already
code-assembled). Selection/ordering/decision_log derivation are pure code.
Per ADR-021 D5.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Protocol

from orchestrator.core.event import Event, RoomId, TimestampMs
from orchestrator.core.room import Room
from orchestrator.derived.decision_log import produce_decision_log
from orchestrator.llm.purposes import LLMPurpose
from orchestrator.llm.types import LLMRequest, LLMResponse, Message, generate_request_id
from orchestrator.memory.archive import record_project_archive
from orchestrator.memory.schema import ProjectArchive


class LLMRouterProtocol(Protocol):
    """Synchronous LLM call interface for the reentry leave surface."""

    def call(self, request: LLMRequest) -> LLMResponse: ...


def record_leave_marker(
    room_id: RoomId,
    user_id: str,
    ts: TimestampMs,
    *,
    conn: sqlite3.Connection,
) -> None:
    """Upsert the leave-marker for (room_id, user_id). Latest-wins semantics.

    One row per (room_id, user_id) — a second call for the same pair updates
    last_seen_ts in place. Mirrors the P2.4 preference upsert posture.
    Per ADR-021 D5.
    """
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO reentry_marker (room_id, user_id, last_seen_ts)
               VALUES (?, ?, ?)""",
            (str(room_id), user_id, int(ts)),
        )


def generate_and_record_archive(
    room_id: RoomId,
    title: str,
    events: list[Event],
    room: Room,
    *,
    start_ts: TimestampMs,
    end_ts: TimestampMs,
    llm_router: LLMRouterProtocol,
    conn: sqlite3.Connection,
) -> ProjectArchive:
    """Compose a ProjectArchive from room facts and persist it.

    Code-derived fields: decision_log (via produce_decision_log), duration_ms.
    Semantic fields: one_line_summary + spinoff_questions are genuinely generated
    via ARCHIVE_SUMMARY_RENDER LLM call (content-gen — ADR-021 D5/D9).

    The generation happens here in reentry/ (outside memory/); memory/ only
    persists (never generates). Principle-5-clean.
    """
    decision_log_obj = produce_decision_log(events, room)
    decision_log: list[dict[str, Any]] = [e.model_dump() for e in decision_log_obj.entries]
    duration_ms = int(end_ts) - int(start_ts)

    # Content-gen LLM call: generate semantic fields from room facts.
    summary_context = json.dumps(
        {
            "room_id": str(room_id),
            "title": title,
            "event_count": len(events),
            "decision_log": decision_log,
        },
        ensure_ascii=False,
    )
    request = LLMRequest(
        request_id=generate_request_id(),
        purpose=LLMPurpose.ARCHIVE_SUMMARY_RENDER,
        caller_agent_id=None,
        system=(
            "You are generating a project archive summary. "
            "Return ONLY valid JSON with keys: "
            '"one_line_summary" (string, ≤120 chars) and '
            '"spinoff_questions" (list of strings, 1-5 items). '
            "Do not include any other text outside the JSON object."
        ),
        messages=[Message(role="user", content=summary_context)],
    )
    response = llm_router.call(request)
    semantic = _parse_archive_summary(response.content)

    return record_project_archive(
        room_id=room_id,
        title=title,
        duration_ms=duration_ms,
        one_line_summary=semantic["one_line_summary"],
        decision_log=decision_log,
        spinoff_questions=semantic["spinoff_questions"],
        conn=conn,
    )


def _parse_archive_summary(content: str) -> dict[str, Any]:
    """Parse LLM-generated archive summary JSON. Graceful fallback on bad output."""
    content = content.strip()
    # strip markdown code fences if present
    if content.startswith("```"):
        lines = content.splitlines()
        content = "\n".join(
            line for line in lines if not line.startswith("```")
        ).strip()
    try:
        parsed = json.loads(content)
        summary = str(parsed.get("one_line_summary", "")) or "Summary unavailable."
        questions = parsed.get("spinoff_questions", [])
        if not isinstance(questions, list):
            questions = []
        return {"one_line_summary": summary, "spinoff_questions": [str(q) for q in questions]}
    except (json.JSONDecodeError, AttributeError):
        fallback = content[:120] or "Summary unavailable."
        return {"one_line_summary": fallback, "spinoff_questions": []}
