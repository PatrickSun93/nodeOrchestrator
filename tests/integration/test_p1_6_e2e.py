"""End-to-end persistence test for P1.6 snapshot mechanics.

Load-bearing acceptance per senior plan §2 P1.6-4 + brief architect-settled #6.

Exercises the full Research room state chain:
  setup → exploration → divergence → convergence → snapshot_pending → closed

Using next_room_state directly + manual transition-event appends (senior pin):
avoids re-exercising P1.5 room-runtime tests while exercising snapshot path end-to-end.

Source != sink invariant: event-stream → produce_snapshot → summary_snapshot.metadata
  → produce_decision_log → assertions.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from orchestrator.agents.dispatch import LLMRouterProtocol, dispatch_turn
from orchestrator.agents.loader import load_agents
from orchestrator.core.event import (
    Event,
    EventType,
    SummarySnapshotMeta,
    TimestampMs,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.derived.decision_log import produce_decision_log
from orchestrator.derived.snapshot import produce_snapshot
from orchestrator.llm.router import ModelRegistry
from orchestrator.llm.types import (
    Capability,
    LLMResponse,
    ModelId,
    ModelProfile,
    ProviderId,
    Usage,
    generate_request_id,
)
from orchestrator.rooms.state_machine import RoomStateTransition, next_room_state

_CONFIG_DIR = Path(__file__).parent.parent.parent / "config" / "agents"
_PROVIDER = ProviderId("test_provider")

_CAPS_BY_MODEL: dict[str, list[Capability]] = {
    "deepseek_v4_flash": [Capability.TOOLS],
    "qwen_mlx_30b": [Capability.TOOLS],
    "claude_code_opus_47": [Capability.EFFORT],
    "claude_code_sonnet_46": [Capability.EFFORT],
    "claude_code_haiku_45": [],
    "deepseek_v4_pro": [],
}


def _make_model(mid: str) -> ModelProfile:
    return ModelProfile(
        id=ModelId(mid),
        provider=_PROVIDER,
        provider_model_id=mid,
        capabilities=_CAPS_BY_MODEL.get(mid, []),
        context_window=8192,
    )


_MODELS = ModelRegistry({ModelId(m): _make_model(m) for m in _CAPS_BY_MODEL})


def _make_store() -> EventStore:
    conn = sqlite3.connect(":memory:")
    store = EventStore(conn)
    store.init_schema()
    return store


def _make_event(
    room_id: Any,
    *,
    event_type: EventType,
    author: str = "user",
    content: str = "",
    metadata: dict[str, Any] | None = None,
    timestamp: int | None = None,
) -> Event:
    return Event(
        id=generate_event_id(),
        room_id=room_id,
        type=event_type,
        author=author,
        timestamp=TimestampMs(timestamp if timestamp is not None else now_ms()),
        content=content,
        metadata=metadata or {},
    )


def _append_state_transition(
    store: EventStore,
    room: Room,
    transition: RoomStateTransition,
) -> Event:
    """Append a state_transition event from a RoomStateTransition result."""
    st_event = _make_event(
        room.id,
        event_type=EventType.STATE_TRANSITION,
        author="system",
        metadata={
            "prior_state": transition.prior_state,
            "new_state": transition.new_state,
        },
    )
    store.append(st_event)
    return st_event


def _llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        request_id=generate_request_id(),
        content=content,
        model_id_requested=ModelId("claude_code_haiku_45"),
        model_id_used=ModelId("claude_code_haiku_45"),
        provider_id_used=_PROVIDER,
        usage=Usage(input_tokens=5, output_tokens=10),
        latency_ms=20,
        finish_reason="stop",
    )


def test_p1_6_e2e_full_room_state_chain_through_snapshot_pending_to_closed() -> None:
    """Full Research room state chain → Logger triggers → summary_snapshot → closed.

    Steps (per senior plan §2 P1.6-4 acceptance):
      1. SQLite-backed EventStore.
      2. Research room in setup state; load Logger agent from config.
      3. Append user_input → utterance → hypotheses x 2 → decide user_input → decision events.
      4. Advance room state via next_room_state + manual transition-event appends.
      5. Logger triggers on state_transition(snapshot_pending) → summary_snapshot appended.
      6. next_room_state(summary_snapshot) → snapshot_pending → closed transition.
      7. produce_decision_log derives DecisionLog from same stream.
      8. Assertions (summary_snapshot present + metadata validates + DecisionLog ordered +
         closing transition + source!=sink invariant on event_id).
    """
    # --- Step 1: Store ---
    store = _make_store()

    # --- Step 2: Room + agents ---
    room_id = generate_room_id()
    room = Room(id=room_id, type=RoomType.RESEARCH, state="setup")
    store.append_room(room)

    agents, regex_registry = load_agents(_CONFIG_DIR, models=_MODELS)
    logger_agent = agents["logger"]

    # --- Step 3: Append event sequence ---
    # user_input
    ui1 = _make_event(
        room_id,
        event_type=EventType.USER_INPUT,
        author="user",
        content="Tell me about this system.",
        timestamp=1000,
    )
    store.append(ui1)

    # Advance: setup → exploration (trigger: utterance)
    utterance1 = _make_event(
        room_id,
        event_type=EventType.UTTERANCE,
        author="agent:skeptic",
        content="I'll analyze this.",
        timestamp=1001,
    )
    store.append(utterance1)
    snapshot_before = store.get_room_events(room_id)[:-1]  # before utterance1 appended
    transition = next_room_state(room, snapshot_before, current_event=utterance1)
    assert transition is not None, "setup→exploration should fire on utterance"
    assert transition.new_state == "exploration"
    _append_state_transition(store, room, transition)
    room = Room(id=room_id, type=RoomType.RESEARCH, state="exploration")

    # Append hypothesis 1 and 2 (build up snapshot; need ≥2 before current for divergence)
    hyp1 = _make_event(
        room_id,
        event_type=EventType.HYPOTHESIS,
        author="user",
        content="Maybe the system has a memory leak.",
        metadata={"confidence": 0.7},
        timestamp=2000,
    )
    store.append(hyp1)
    hyp2 = _make_event(
        room_id,
        event_type=EventType.HYPOTHESIS,
        author="user",
        content="Or maybe it's a CPU bottleneck.",
        metadata={"confidence": 0.6},
        timestamp=2100,
    )
    store.append(hyp2)

    # hyp3 as current_event; snapshot before hyp3 has hyp1+hyp2 (>=2) → divergence fires.
    hyp3 = _make_event(
        room_id,
        event_type=EventType.HYPOTHESIS,
        author="user",
        content="Or perhaps it's a network I/O issue.",
        metadata={"confidence": 0.5},
        timestamp=2200,
    )
    store.append(hyp3)
    snapshot_before_hyp3 = [e for e in store.get_room_events(room_id) if e.id != hyp3.id]
    transition2 = next_room_state(room, snapshot_before_hyp3, current_event=hyp3)
    assert transition2 is not None, (
        "exploration→divergence should fire with 2+ hypotheses in snapshot"
    )
    assert transition2.new_state == "divergence"
    _append_state_transition(store, room, transition2)
    room = Room(id=room_id, type=RoomType.RESEARCH, state="divergence")

    # user_input with decide intent: divergence → convergence
    decide_input = _make_event(
        room_id,
        event_type=EventType.USER_INPUT,
        author="user",
        content="Let's decide which hypothesis to pursue.",
        timestamp=3000,
    )
    store.append(decide_input)
    snapshot_before_decide = [e for e in store.get_room_events(room_id) if e.id != decide_input.id]
    transition3 = next_room_state(room, snapshot_before_decide, current_event=decide_input)
    assert transition3 is not None, "divergence→convergence should fire on decide intent"
    assert transition3.new_state == "convergence"
    _append_state_transition(store, room, transition3)
    room = Room(id=room_id, type=RoomType.RESEARCH, state="convergence")

    # Append decision event: convergence → snapshot_pending
    decision1 = _make_event(
        room_id,
        event_type=EventType.DECISION,
        author="user",
        content="We will pursue the memory leak hypothesis.",
        metadata={"based_on": [hyp1.id], "trade_offs": {"risk": "medium"}},
        timestamp=4000,
    )
    store.append(decision1)
    snapshot_before_decision = [e for e in store.get_room_events(room_id) if e.id != decision1.id]
    transition4 = next_room_state(room, snapshot_before_decision, current_event=decision1)
    assert transition4 is not None, "convergence→snapshot_pending should fire on decision"
    assert transition4.new_state == "snapshot_pending"
    st_snapshot_pending = _append_state_transition(store, room, transition4)
    room = Room(id=room_id, type=RoomType.RESEARCH, state="snapshot_pending")

    # --- Step 5: Logger triggers on state_transition(snapshot_pending) ---
    snapshot_events = store.get_room_events(room_id)

    mock_router = MagicMock(spec=LLMRouterProtocol)
    mock_router.call.return_value = _llm_response("Snapshot recorded.")

    result = dispatch_turn(
        {"logger": logger_agent},
        room,
        st_snapshot_pending,
        event_store=store,
        llm_router=mock_router,
        available_skills={},
        regex_registry=regex_registry,
        tools={},
    )

    assert result.total_asked == 1
    assert result.failed_agents == []

    # --- Step 8a: summary_snapshot event present ---
    all_events = store.get_room_events(room_id)
    ss_events = [e for e in all_events if e.type == EventType.SUMMARY_SNAPSHOT]
    assert len(ss_events) == 1, f"Expected 1 SUMMARY_SNAPSHOT, got {len(ss_events)}"
    ss_event = ss_events[0]
    assert ss_event.author == "agent:logger"

    # --- Step 8b: SummarySnapshotMeta validates ---
    meta = SummarySnapshotMeta.model_validate(ss_event.metadata)
    assert meta.room_id == str(room_id)
    assert meta.room_state == "snapshot_pending"
    assert meta.event_count > 0
    assert meta.decision_count > 0
    # snapshot_events captured before Logger's dispatch; only pre-snapshot participants appear
    assert "skeptic" in meta.participants  # agent:skeptic emitted utterance1

    # --- Step 8c: re-derivable from Snapshot.model_validate(meta) ---
    snap = produce_snapshot(snapshot_events, room, snapshot_at=TimestampMs(meta.snapshot_at))
    assert len(snap.closed_decisions) > 0, "decision1 should be in closed_decisions"
    assert snap.closed_decisions[0].event_id == decision1.id

    # --- Step 7: produce_decision_log from same stream ---
    dlog = produce_decision_log(all_events, room)
    decision_entries = dlog.entries
    assert len(decision_entries) >= 1
    # Chronological order invariant
    timestamps = [e.timestamp for e in decision_entries]
    assert timestamps == sorted(timestamps)

    # --- Source != sink invariant ---
    # decision1.id flows event-stream → produce_decision_log → DecisionEntry.event_id
    decision_entry_ids = {e.event_id for e in decision_entries}
    assert decision1.id in decision_entry_ids, (
        "decision1.id must flow event-stream → produce_decision_log → DecisionEntry.event_id"
    )

    # --- Step 6: next_room_state on summary_snapshot → snapshot_pending → closed ---
    snapshot_before_ss = [e for e in all_events if e.id != ss_event.id]
    closing_transition = next_room_state(room, snapshot_before_ss, current_event=ss_event)
    assert closing_transition is not None, "snapshot_pending→closed should fire on summary_snapshot"
    assert closing_transition.prior_state == "snapshot_pending"
    assert closing_transition.new_state == "closed"
    assert closing_transition.rule_matched == "summary_snapshot_triggers_closed"
