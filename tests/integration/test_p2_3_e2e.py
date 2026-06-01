"""End-to-end P2.3: Scenario Z — inject external_validation → surface → promote.

Per plan P2.3-4 acceptance criteria (ADR-019 D1-D3).

Exercises the external ground-truth validation flow:
  record_hypothesis (≥2 Research rooms) →
  inject external_validation events via event_store.append (test-injected;
    no connector exists — this is the dormant-until-fed pattern) →
  list_externally_validated_candidates → exactly the confirmed candidates surfaced →
  assertions on orthogonality (no VK, no decision event), idempotency,
  determinism, and status-untouched.

Scenario structure:
  - hyp-A: confirmed external_validation event  → surfaced as candidate
  - hyp-B: refuted external_validation event    → NOT surfaced (rule-c ignores non-confirmed)
  - hyp-C: no external_validation event         → NOT surfaced
  - orthogonality: promote_hypothesis works on hyp-A AND hyp-C (signal does not gate)
  - status untouched: hyp-B.status == PENDING after reader call (rule-c never mutates status)

Source ≠ sink (§1 coverage standard): EventStore.append(external_validation) → events table →
               list_externally_validated_candidates reads events + hypothesis tables →
               promote_hypothesis → verified_knowledge row
"""

from __future__ import annotations

import json
import sqlite3

from orchestrator.core.event import (
    Event,
    EventId,
    EventType,
    RoomId,
    TimestampMs,
    generate_event_id,
    generate_room_id,
    now_ms,
    validate_metadata,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.memory.promotion import promote_hypothesis
from orchestrator.memory.schema import HypothesisId, VKScope
from orchestrator.memory.store import (
    get_hypothesis_by_id,
    init_memory_schema,
    record_hypothesis,
)
from orchestrator.memory.validation import list_externally_validated_candidates

# ---------------------------------------------------------------------------
# Fixtures (modeled on test_p2_2_e2e.py)
# ---------------------------------------------------------------------------


def _make_store() -> tuple[EventStore, sqlite3.Connection]:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    store = EventStore(conn)
    store.init_schema()
    init_memory_schema(conn)
    return store, conn


def _make_room(store: EventStore, *, n_events: int = 2) -> tuple[Room, list[EventId]]:
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    ids: list[EventId] = []
    base = now_ms()
    for i in range(n_events):
        evt = Event(
            id=generate_event_id(),
            room_id=room.id,
            type=EventType.UTTERANCE,
            author="user",
            timestamp=TimestampMs(base + i),
            content=f"room {room.id[-4:]} event {i}",
        )
        store.append(evt)
        ids.append(evt.id)
    return room, ids


def _inject_validation(
    store: EventStore,
    room_id: RoomId,
    verdict: str,
    hyp_id: str,
    *,
    source: str = "ci",
    ts_offset: int = 0,
) -> EventId:
    """Append a test-injected external_validation event into the event log."""
    meta = validate_metadata(
        EventType.EXTERNAL_VALIDATION,
        {"source": source, "verdict": verdict, "validated_hypothesis_id": hyp_id},
    )
    evt = Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.EXTERNAL_VALIDATION,
        author="system",
        timestamp=TimestampMs(now_ms() + ts_offset),
        content=f"external validation: {verdict}",
        metadata=meta,
    )
    store.append(evt)
    return evt.id


# ---------------------------------------------------------------------------
# Scenario Z
# ---------------------------------------------------------------------------


def test_scenario_z_external_validation_full_pipeline() -> None:
    """Scenario Z: inject external_validation → surface candidates → promote.

    AC#1-7 per plan P2.3-4.
    """
    store, conn = _make_store()

    room1, r1evts = _make_room(store, n_events=3)
    room2, r2evts = _make_room(store, n_events=3)

    # AC#1: ≥2 rooms, three hypotheses with distinct validation states.
    hyp_a = record_hypothesis(
        content="hypothesis A — will be confirmed by external validator",
        room_id=room1.id,
        source_event_ids=[r1evts[0]],
        confidence=0.80,
        conn=conn,
    )
    hyp_b = record_hypothesis(
        content="hypothesis B — will be refuted by external validator",
        room_id=room2.id,
        source_event_ids=[r2evts[0]],
        confidence=0.75,
        conn=conn,
    )
    hyp_c = record_hypothesis(
        content="hypothesis C — no external validation event",
        room_id=room1.id,
        source_event_ids=[r1evts[1]],
        confidence=0.60,
        conn=conn,
    )

    # Inject validation events — confirmed for A, refuted for B, none for C.
    _inject_validation(store, room1.id, "confirmed", hyp_a.id, ts_offset=1)
    _inject_validation(store, room2.id, "refuted", hyp_b.id, ts_offset=2)

    # AC#2: list_externally_validated_candidates returns exactly [hyp_a].
    candidates = list_externally_validated_candidates(conn)
    candidate_ids = [c.id for c in candidates]
    assert candidates, "expected hyp_a as candidate"
    assert len(candidates) == 1, f"expected 1 candidate, got {len(candidates)}: {candidate_ids}"
    assert candidates[0].id == hyp_a.id, f"expected hyp_a, got {candidates[0].id}"
    # Ordered id ASC (single-candidate degenerate case — trivially sorted).
    assert candidate_ids == sorted(candidate_ids)

    # AC#3 orthogonality: no VK rows and no promotion decision events from rule-(c).
    vk_count = conn.execute("SELECT COUNT(*) FROM verified_knowledge").fetchone()[0]
    assert vk_count == 0, "rule-(c) must not insert VK rows"
    decision_count = conn.execute("SELECT COUNT(*) FROM events WHERE type = 'decision'").fetchone()[
        0
    ]
    assert decision_count == 0, "rule-(c) must not emit decision events"

    # AC#3 cont: promote_hypothesis works on externally-validated hyp-A AND un-validated hyp-C
    # — the signal does NOT gate promotion (ADR-016 D3/D10).
    vk_a = promote_hypothesis(
        hyp_a.id,
        user_id="peidong",
        scope=VKScope.PERSONAL,
        topic_tags=[],
        event_store=store,
    )
    assert vk_a.content == hyp_a.content

    vk_c = promote_hypothesis(
        hyp_c.id,
        user_id="peidong",
        scope=VKScope.PERSONAL,
        topic_tags=[],
        event_store=store,
    )
    assert vk_c.content == hyp_c.content

    # AC#5: hyp-B status still PENDING after reader call — rule-(c) never mutates status.
    hyp_b_reloaded = get_hypothesis_by_id(HypothesisId(hyp_b.id), conn=conn)
    assert hyp_b_reloaded is not None
    assert hyp_b_reloaded.status.value == "pending", (
        f"rule-(c) must not mutate hyp-B status; got {hyp_b_reloaded.status.value!r}"
    )


def test_scenario_z_determinism_scan_order_independent() -> None:
    """AC#4: same confirmed events + rows → same candidate set regardless of insertion order.

    Seeded in different orders → same content labels surface.
    Discriminating: two stores differ only in insertion order; we assert the
    same hypothesis content is returned, not a count-only proxy (P2.2 Y1-to-alpha precedent).
    """
    # Store 1: insert hyp-X then hyp-Y, confirm hyp-X.
    store1, conn1 = _make_store()
    room1a, r1a = _make_room(store1, n_events=2)
    room2a, r2a = _make_room(store1, n_events=2)
    hyp_x = record_hypothesis(
        content="claim X",
        room_id=room1a.id,
        source_event_ids=[r1a[0]],
        confidence=0.9,
        conn=conn1,
    )
    record_hypothesis(
        content="claim Y",
        room_id=room2a.id,
        source_event_ids=[r2a[0]],
        confidence=0.9,
        conn=conn1,
    )
    _inject_validation(store1, room1a.id, "confirmed", hyp_x.id)
    cands1 = list_externally_validated_candidates(conn1)

    # Store 2: insert hyp-Y then hyp-X (reversed), confirm hyp-X.
    store2, conn2 = _make_store()
    room1b, r1b = _make_room(store2, n_events=2)
    room2b, r2b = _make_room(store2, n_events=2)
    record_hypothesis(
        content="claim Y",
        room_id=room2b.id,
        source_event_ids=[r2b[0]],
        confidence=0.9,
        conn=conn2,
    )
    hyp_x2 = record_hypothesis(
        content="claim X",
        room_id=room1b.id,
        source_event_ids=[r1b[0]],
        confidence=0.9,
        conn=conn2,
    )
    _inject_validation(store2, room1b.id, "confirmed", hyp_x2.id)
    cands2 = list_externally_validated_candidates(conn2)

    # Both stores surface exactly one candidate with content "claim X".
    assert len(cands1) == 1 and len(cands2) == 1
    assert cands1[0].content == cands2[0].content == "claim X"


def test_scenario_z_inconclusive_not_surfaced() -> None:
    """Inconclusive verdict is ignored by rule-(c) — only 'confirmed' surfaces."""
    store, conn = _make_store()
    room, evts = _make_room(store, n_events=2)

    hyp = record_hypothesis(
        content="inconclusive claim",
        room_id=room.id,
        source_event_ids=[evts[0]],
        confidence=0.5,
        conn=conn,
    )
    _inject_validation(store, room.id, "inconclusive", hyp.id)
    assert list_externally_validated_candidates(conn) == []


def test_scenario_z_multiple_confirmed_events_same_hyp_deduped() -> None:
    """Multiple confirmed events referencing the same hypothesis → one candidate row."""
    store, conn = _make_store()
    room, evts = _make_room(store, n_events=3)

    hyp = record_hypothesis(
        content="doubly confirmed claim",
        room_id=room.id,
        source_event_ids=[evts[0]],
        confidence=0.9,
        conn=conn,
    )
    _inject_validation(store, room.id, "confirmed", hyp.id, source="ci", ts_offset=1)
    _inject_validation(store, room.id, "confirmed", hyp.id, source="doi-resolver", ts_offset=2)

    cands = list_externally_validated_candidates(conn)
    assert len(cands) == 1
    assert cands[0].id == hyp.id


def test_scenario_z_dangling_confirmed_event_no_error() -> None:
    """Confirmed event referencing a non-existent hypothesis_id → no candidate, no error.

    The join filters it; no existence check needed (ADR-019 D2).
    """
    store, conn = _make_store()
    room, _evts = _make_room(store, n_events=2)

    phantom_id = "hyp_" + "0" * 32  # valid pattern but no row in hypothesis table
    meta = validate_metadata(
        EventType.EXTERNAL_VALIDATION,
        {"source": "ci", "verdict": "confirmed", "validated_hypothesis_id": phantom_id},
    )
    evt = Event(
        id=generate_event_id(),
        room_id=room.id,
        type=EventType.EXTERNAL_VALIDATION,
        author="system",
        timestamp=now_ms(),
        content="validation of missing hyp",
        metadata=meta,
    )
    store.append(evt)

    assert list_externally_validated_candidates(conn) == []


def test_scenario_z_no_events_returns_empty() -> None:
    """No external_validation events → empty candidate list."""
    store, conn = _make_store()
    room, evts = _make_room(store, n_events=2)
    record_hypothesis(
        content="unvalidated claim",
        room_id=room.id,
        source_event_ids=[evts[0]],
        confidence=0.6,
        conn=conn,
    )
    assert list_externally_validated_candidates(conn) == []


def test_scenario_z_only_refuted_returns_empty() -> None:
    """Only refuted events → empty candidate list."""
    store, conn = _make_store()
    room, evts = _make_room(store, n_events=2)
    hyp = record_hypothesis(
        content="refuted claim",
        room_id=room.id,
        source_event_ids=[evts[0]],
        confidence=0.7,
        conn=conn,
    )
    _inject_validation(store, room.id, "refuted", hyp.id)
    assert list_externally_validated_candidates(conn) == []


def test_scenario_z_promoted_hyp_not_surfaced() -> None:
    """VERIFIED (promoted) hypothesis is not surfaced even if confirmed — status filter."""
    store, conn = _make_store()
    room, evts = _make_room(store, n_events=3)

    hyp = record_hypothesis(
        content="already promoted",
        room_id=room.id,
        source_event_ids=[evts[0]],
        confidence=0.9,
        conn=conn,
    )
    # Promote first, then inject confirmation — VERIFIED row must not surface.
    promote_hypothesis(
        hyp.id,
        user_id="peidong",
        scope=VKScope.PERSONAL,
        topic_tags=[],
        event_store=store,
    )
    _inject_validation(store, room.id, "confirmed", hyp.id)

    cands = list_externally_validated_candidates(conn)
    assert all(c.id != hyp.id for c in cands), "promoted hypothesis must not re-surface"


def test_scenario_z_event_round_trip_via_event_store() -> None:
    """ExternalValidationMeta round-trips through EventStore.append + get_event (AC#2 of P2.3-2)."""
    store, conn = _make_store()
    room, _evts = _make_room(store, n_events=2)

    hyp_id = "hyp_" + "b" * 32
    meta_in = validate_metadata(
        EventType.EXTERNAL_VALIDATION,
        {
            "source": "benchmark-runner",
            "verdict": "confirmed",
            "validated_hypothesis_id": hyp_id,
            "evidence_ref": "https://example.com/result/99",
        },
    )
    evt = Event(
        id=generate_event_id(),
        room_id=room.id,
        type=EventType.EXTERNAL_VALIDATION,
        author="system",
        timestamp=now_ms(),
        content="external validation result",
        metadata=meta_in,
    )
    store.append(evt)

    fetched = store.get_event(evt.id)
    assert fetched is not None
    assert fetched.type == EventType.EXTERNAL_VALIDATION
    assert fetched.metadata["verdict"] == "confirmed"
    assert fetched.metadata["source"] == "benchmark-runner"
    assert fetched.metadata["evidence_ref"] == "https://example.com/result/99"
    assert fetched.metadata["validated_hypothesis_id"] == hyp_id

    # Validate metadata from the stored JSON round-trips cleanly.
    stored_meta_raw = conn.execute(
        "SELECT metadata FROM events WHERE id = ?", (evt.id,)
    ).fetchone()[0]
    rt = validate_metadata(EventType.EXTERNAL_VALIDATION, json.loads(stored_meta_raw))
    assert rt["verdict"] == "confirmed"
    assert rt["evidence_ref"] == "https://example.com/result/99"
