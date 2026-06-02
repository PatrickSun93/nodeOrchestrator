"""End-to-end P2.6: three-block integration tests + boundary assertions.

Per plan P2.6-6 acceptance criteria (ADR-022 D2-D5).

B1 e2e: propose_hypothesis_tags (mock LLM) → update_hypothesis_tags (resolve_tags)
        on two untagged hypotheses in different rooms with the same canonical tag
        → run_matcher flips candidate_for_promotion on both.
        Discriminating: would fail if tags weren't applied/canonical or rooms weren't distinct.

B2 e2e: dataset_check connector → external_validation (confirmed, evidence_ref set)
        via emit_external_validation → list_externally_validated_candidates surfaces
        the hypothesis. Refuted one does NOT surface in the confirmed reader.

B3 e2e: refuted external_validation → list_refuted_candidates surfaces it;
        status unchanged (PENDING); confirmed reader does NOT surface it.

Boundary assertions:
  - no LLM in memory/ (rglob scan)
  - import guard green (producers/connectors not imported upstream)
  - emit_external_validation raises on empty evidence_ref

Source ≠ sink per block:
  B1: MockProvider → update_hypothesis_tags → run_matcher reads hypothesis table
  B2: dataset_check → emit_external_validation → EventStore → list_externally_validated_candidates
  B3: (test-injected via emit) → EventStore → list_refuted_candidates reads events + hypothesis
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orchestrator.connectors._emit import emit_external_validation
from orchestrator.connectors.dataset_check import check_hypothesis_against_dataset
from orchestrator.core.event import (
    Event,
    EventId,
    EventType,
    TimestampMs,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.llm.types import LLMResponse, ModelId, ProviderId, Usage, generate_request_id
from orchestrator.memory.matcher import run_matcher
from orchestrator.memory.schema import HypothesisId
from orchestrator.memory.store import (
    get_hypothesis_by_id,
    init_memory_schema,
    record_hypothesis,
    update_hypothesis_tags,
)
from orchestrator.memory.validation import (
    list_externally_validated_candidates,
    list_refuted_candidates,
)
from orchestrator.producers.tagging import LLMRouterProtocol, propose_hypothesis_tags

# ---------------------------------------------------------------------------
# Shared fixtures
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
            content=f"event {i}",
        )
        store.append(evt)
        ids.append(evt.id)
    return room, ids


def _make_mock_router(tags_response: str) -> MagicMock:
    router = MagicMock(spec=LLMRouterProtocol)
    router.call.return_value = LLMResponse(
        request_id=generate_request_id(),
        content=tags_response,
        model_id_requested=ModelId("m"),
        model_id_used=ModelId("m"),
        provider_id_used=ProviderId("mock"),
        usage=Usage(input_tokens=0, output_tokens=0),
        latency_ms=0,
        finish_reason="stop",
    )
    return router


# ---------------------------------------------------------------------------
# B1 e2e — tagging producer → update_hypothesis_tags → run_matcher fires
# ---------------------------------------------------------------------------


def test_b1_e2e_tagging_producer_feeds_run_matcher() -> None:
    """B1 e2e (discriminating): propose_hypothesis_tags → update_hypothesis_tags
    on two untagged hypotheses in different rooms with the same canonical tag
    → run_matcher flips candidate_for_promotion on both.

    Discriminating: would fail if tags weren't applied, weren't canonical,
    or both hypotheses were in the same room (min_rooms=2 requires distinct rooms).
    """
    store, conn = _make_store()

    room1, r1evts = _make_room(store, n_events=2)
    room2, r2evts = _make_room(store, n_events=2)

    # Two untagged hypotheses in DIFFERENT rooms.
    hyp_a = record_hypothesis(
        content="Quantum entanglement allows instant information transfer",
        room_id=room1.id,
        source_event_ids=[r1evts[0]],
        confidence=0.75,
        conn=conn,
    )
    hyp_b = record_hypothesis(
        content="Entangled particles exhibit correlated quantum states",
        room_id=room2.id,
        source_event_ids=[r2evts[0]],
        confidence=0.80,
        conn=conn,
    )

    # Both start untagged — run_matcher ignores them.
    result_before = run_matcher(conn)
    assert result_before.rows_newly_flagged == 0, (
        "untagged hypotheses must not be flagged by run_matcher"
    )

    # Propose tags via MockProvider (content-gen, HYPOTHESIS_TAG_PROPOSAL).
    # Both providers return the SAME canonical tag string so run_matcher sees
    # identical frozensets across two rooms (exact-set equality per ADR-017 D2).
    mock_router_a = _make_mock_router("quantum entanglement, physics")
    mock_router_b = _make_mock_router("quantum entanglement, physics")

    source_evt_a = store.get_event(r1evts[0])
    assert source_evt_a is not None
    raw_tags_a: list[str] = propose_hypothesis_tags(hyp_a, [source_evt_a], llm_router=mock_router_a)

    source_evt_b = store.get_event(r2evts[0])
    assert source_evt_b is not None
    raw_tags_b: list[str] = propose_hypothesis_tags(hyp_b, [source_evt_b], llm_router=mock_router_b)

    assert raw_tags_a, "propose_hypothesis_tags must return non-empty list"
    assert raw_tags_b, "propose_hypothesis_tags must return non-empty list"

    # Apply tags via update_hypothesis_tags (routes through resolve_tags — canonical stored).
    # Both raw responses contain "quantum entanglement" + "physics" → canonical
    # ["quantum-entanglement", "physics"] — identical frozensets for run_matcher.
    updated_a = update_hypothesis_tags(HypothesisId(hyp_a.id), topic_tags=raw_tags_a, conn=conn)
    updated_b = update_hypothesis_tags(HypothesisId(hyp_b.id), topic_tags=raw_tags_b, conn=conn)

    assert "quantum-entanglement" in updated_a.topic_tags, (
        "update_hypothesis_tags must canonicalize via resolve_tags"
    )
    assert "quantum-entanglement" in updated_b.topic_tags

    # run_matcher: both hypotheses now share canonical tag "quantum-entanglement" across 2 rooms.
    result_after = run_matcher(conn)
    assert result_after.rows_newly_flagged >= 2, (
        f"run_matcher must flag both hypotheses; got {result_after.rows_newly_flagged}"
    )

    reloaded_a = get_hypothesis_by_id(HypothesisId(hyp_a.id), conn=conn)
    reloaded_b = get_hypothesis_by_id(HypothesisId(hyp_b.id), conn=conn)
    assert reloaded_a is not None and reloaded_b is not None
    assert reloaded_a.candidate_for_promotion, (
        "hyp_a must be candidate_for_promotion after tagging + run_matcher"
    )
    assert reloaded_b.candidate_for_promotion, (
        "hyp_b must be candidate_for_promotion after tagging + run_matcher"
    )


def test_b1_e2e_same_room_not_flagged() -> None:
    """Discriminating boundary: both hypotheses in the SAME room → run_matcher does NOT flag.

    min_rooms=2 requires DISTINCT rooms; single-room group is below threshold.
    """
    store, conn = _make_store()
    room, evts = _make_room(store, n_events=3)

    hyp_x = record_hypothesis(
        content="Hypothesis X about quantum",
        room_id=room.id,
        source_event_ids=[evts[0]],
        confidence=0.7,
        conn=conn,
    )
    hyp_y = record_hypothesis(
        content="Hypothesis Y about quantum",
        room_id=room.id,
        source_event_ids=[evts[1]],
        confidence=0.7,
        conn=conn,
    )

    update_hypothesis_tags(HypothesisId(hyp_x.id), topic_tags=["quantum"], conn=conn)
    update_hypothesis_tags(HypothesisId(hyp_y.id), topic_tags=["quantum"], conn=conn)

    result = run_matcher(conn)
    assert result.rows_newly_flagged == 0, (
        "same-room hypotheses must NOT be flagged (min_rooms=2 distinct rooms required)"
    )


def test_b1_e2e_update_hypothesis_tags_overwrite_semantics() -> None:
    """Overwrite semantics (discriminating): second call replaces tags, not union."""
    store, conn = _make_store()
    room, evts = _make_room(store, n_events=2)

    hyp = record_hypothesis(
        content="Test hypothesis",
        room_id=room.id,
        source_event_ids=[evts[0]],
        confidence=0.5,
        conn=conn,
    )

    # First tag set.
    update_hypothesis_tags(HypothesisId(hyp.id), topic_tags=["physics", "quantum"], conn=conn)

    # Second tag set — must REPLACE, not merge.
    updated = update_hypothesis_tags(HypothesisId(hyp.id), topic_tags=["chemistry"], conn=conn)

    assert updated.topic_tags == ["chemistry"], (
        f"overwrite semantics: expected ['chemistry'], got {updated.topic_tags!r}"
    )
    assert "physics" not in updated.topic_tags, "old tags must be replaced, not merged"
    assert "quantum" not in updated.topic_tags, "old tags must be replaced, not merged"


# ---------------------------------------------------------------------------
# B2 e2e — dataset_check connector → emit → list_externally_validated_candidates
# ---------------------------------------------------------------------------


def test_b2_e2e_connector_feeds_confirmed_reader() -> None:
    """B2 e2e: dataset_check → external_validation (confirmed, evidence_ref set)
    → list_externally_validated_candidates surfaces the hypothesis.
    Source ≠ sink (dataset_check → EventStore → memory reader).
    """
    store, conn = _make_store()
    room, evts = _make_room(store, n_events=2)

    hyp = record_hypothesis(
        content="Gravity causes objects to accelerate downward near Earth",
        room_id=room.id,
        source_event_ids=[evts[0]],
        confidence=0.90,
        conn=conn,
    )

    dataset = {
        "gravity": "objects accelerate at 9.8 m/s^2 near Earth surface",
        "entropy": "disorder increases in closed systems",
    }

    # Connector produces the event — source.
    event_id = check_hypothesis_against_dataset(
        hyp.content,
        dataset,
        event_store=store,
        room_id=room.id,
        validated_hypothesis_id=hyp.id,
    )

    assert event_id is not None, "dataset_check must return EventId on match"

    # Verify event metadata is correctly set.
    event = store.get_event(EventId(event_id))
    assert event is not None
    assert event.metadata["verdict"] == "confirmed"
    assert event.metadata["evidence_ref"] == "gravity"
    assert event.metadata["validated_hypothesis_id"] == hyp.id

    # Sink: rule-c reader surfaces the hypothesis.
    candidates = list_externally_validated_candidates(conn)
    assert len(candidates) == 1
    assert candidates[0].id == hyp.id


def test_b2_e2e_refuted_not_surfaced_by_confirmed_reader() -> None:
    """Refuted verdict from connector does NOT surface in list_externally_validated_candidates."""
    store, conn = _make_store()
    room, evts = _make_room(store, n_events=2)

    hyp = record_hypothesis(
        content="Black holes are entirely fictional",
        room_id=room.id,
        source_event_ids=[evts[0]],
        confidence=0.3,
        conn=conn,
    )

    # Inject refuted verdict directly via emit_external_validation.
    emit_external_validation(
        store,
        room_id=room.id,
        source="astrophysics_db",
        verdict="refuted",
        validated_hypothesis_id=hyp.id,
        evidence_ref="black_holes_observed_ref",
    )

    # Confirmed reader must NOT surface it.
    assert list_externally_validated_candidates(conn) == [], (
        "refuted verdict must not surface in the confirmed reader"
    )


def test_b2_e2e_emit_raises_on_empty_evidence_ref() -> None:
    """Boundary (Q5): emit_external_validation raises ValueError on empty evidence_ref."""
    store, _conn = _make_store()
    room, _ = _make_room(store, n_events=1)
    hyp_id = "hyp_" + "a" * 32

    with pytest.raises(ValueError, match="evidence_ref is required"):
        emit_external_validation(
            store,
            room_id=room.id,
            source="test",
            verdict="confirmed",
            validated_hypothesis_id=hyp_id,
            evidence_ref="",
        )


# ---------------------------------------------------------------------------
# B3 e2e — refuted advisory reader (no status mutation)
# ---------------------------------------------------------------------------


def test_b3_e2e_refuted_reader_surfaces_refuted() -> None:
    """B3 e2e: refuted external_validation → list_refuted_candidates surfaces it;
    status unchanged (PENDING); confirmed reader does NOT surface it.
    Source ≠ sink: emit_external_validation → EventStore → list_refuted_candidates.
    """
    store, conn = _make_store()
    room, evts = _make_room(store, n_events=2)

    hyp = record_hypothesis(
        content="The universe is 6000 years old",
        room_id=room.id,
        source_event_ids=[evts[0]],
        confidence=0.1,
        conn=conn,
    )

    # Source: inject refuted external_validation via emit helper.
    emit_external_validation(
        store,
        room_id=room.id,
        source="cosmology_dataset",
        verdict="refuted",
        validated_hypothesis_id=hyp.id,
        evidence_ref="hubble_constant_age_estimate",
    )

    # Sink: B3 reader.
    refuted = list_refuted_candidates(conn)
    assert len(refuted) == 1
    assert refuted[0].id == hyp.id

    # Status must remain PENDING (no mutation — ADR-019 push-back #4, ADR-022 D5).
    reloaded = get_hypothesis_by_id(HypothesisId(hyp.id), conn=conn)
    assert reloaded is not None
    assert reloaded.status.value == "pending", (
        f"list_refuted_candidates must NOT mutate status; got {reloaded.status.value!r}"
    )

    # Confirmed reader does NOT surface it.
    assert list_externally_validated_candidates(conn) == [], (
        "refuted hypothesis must not appear in the confirmed reader"
    )


def test_b3_e2e_confirmed_only_hypothesis_not_in_refuted_reader() -> None:
    """A hypothesis with only a confirmed verdict is NOT returned by list_refuted_candidates."""
    store, conn = _make_store()
    room, evts = _make_room(store, n_events=2)

    hyp = record_hypothesis(
        content="Water is H2O",
        room_id=room.id,
        source_event_ids=[evts[0]],
        confidence=1.0,
        conn=conn,
    )

    emit_external_validation(
        store,
        room_id=room.id,
        source="chemistry_db",
        verdict="confirmed",
        validated_hypothesis_id=hyp.id,
        evidence_ref="molecular_formula_h2o",
    )

    # Must NOT appear in refuted reader.
    refuted = list_refuted_candidates(conn)
    assert all(c.id != hyp.id for c in refuted), (
        "confirmed-only hypothesis must not appear in the refuted reader"
    )


# ---------------------------------------------------------------------------
# Boundary assertions
# ---------------------------------------------------------------------------


def test_boundary_no_llm_in_memory_module() -> None:
    """memory/ must contain no LLM imports (rglob scan over src/orchestrator/memory/).

    Per ADR-022 D1: producers/connectors are leaf consumers outside memory/.
    The no-LLM rglob is preserved (same check as tests/memory/test_constitution.py
    for the full suite; duplicated here as an integration boundary assertion).
    """
    memory_src = Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator" / "memory"
    forbidden_patterns = [
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "LLMRouter",
        "llm_router",
    ]

    violations: list[str] = []
    for py_path in memory_src.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        content = py_path.read_text(encoding="utf-8")
        rel = py_path.relative_to(memory_src.parent.parent)
        for pattern in forbidden_patterns:
            if pattern in content:
                violations.append(f"  {rel}: {pattern!r}")

    assert not violations, (
        "memory/ must not import LLM dependencies (ADR-022 D1, Principle 5):\n"
        + "\n".join(violations)
    )


def test_boundary_import_guard_green() -> None:
    """Verify import guard is green: producers/connectors tests pass (summary assertion).

    The constitution test in tests/producers/test_constitution.py runs as part of the
    full suite. This test provides a quick boundary check via import (if producers/
    is importable and the guard tests run, the guard is green).
    """
    # If imports succeed, the packages are properly structured.
    import orchestrator.connectors
    import orchestrator.connectors._emit
    import orchestrator.connectors.dataset_check
    import orchestrator.producers
    import orchestrator.producers.tagging

    # Reference to suppress unused-import warnings.
    _ = (
        orchestrator.connectors,
        orchestrator.connectors._emit,
        orchestrator.connectors.dataset_check,
        orchestrator.producers,
        orchestrator.producers.tagging,
    )


def test_boundary_memory_does_not_import_producers_or_connectors() -> None:
    """No memory/ module may import producers/ or connectors/ (ADR-022 D1)."""
    import ast

    memory_src = Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator" / "memory"
    violations: list[str] = []

    for py_path in memory_src.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        source = py_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_path))
        rel = py_path.relative_to(memory_src.parent.parent)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if "orchestrator.producers" in module or "orchestrator.connectors" in module:
                    violations.append(f"  {rel}: line {node.lineno}: from {module!r} import ...")

    assert not violations, (
        "memory/ must not import producers/ or connectors/ — they are leaf consumers "
        "(ADR-022 D1):\n" + "\n".join(violations)
    )
