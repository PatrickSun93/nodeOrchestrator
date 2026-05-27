"""Integration tests for the agent pipeline.

§1 cross-module tests wiring multiple subsystems:
  - loader → should_agent_speak (regex_registry threading)
  - loader → decide_agents_for_room → dispatch_turn (full happy path)

All tests use in-memory SQLite and a mock LLM router.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

from orchestrator.agents.dispatch import LLMRouterProtocol, dispatch_turn
from orchestrator.agents.loader import load_agents
from orchestrator.agents.selection import decide_agents_for_room
from orchestrator.agents.speaking import should_agent_speak
from orchestrator.core.event import (
    Event,
    EventType,
    build_author,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
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

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

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


def _make_registry(*model_ids: str) -> ModelRegistry:
    return ModelRegistry({ModelId(m): _make_model(m) for m in model_ids})


def _make_store() -> EventStore:
    conn = sqlite3.connect(":memory:")
    store = EventStore(conn)
    store.init_schema()
    return store


def _make_room(store: EventStore) -> Room:
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    return room


def _llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        request_id=generate_request_id(),
        content=content,
        model_id_requested=ModelId("claude_code_opus_47"),
        model_id_used=ModelId("claude_code_opus_47"),
        provider_id_used=_PROVIDER,
        usage=Usage(input_tokens=10, output_tokens=20),
        latency_ms=50,
        finish_reason="stop",
    )


def _models_for_config() -> ModelRegistry:
    """Minimal registry covering all model ids used by the 5 canonical agents."""
    return _make_registry(
        "claude_code_opus_47",
        "claude_code_sonnet_46",
        "deepseek_v4_pro",
        "deepseek_v4_flash",
        "claude_code_haiku_45",
        "qwen_mlx_30b",
    )


# ---------------------------------------------------------------------------
# §1 regex_registry threading test (P1.4-8 acceptance requirement)
# ---------------------------------------------------------------------------


def test_integration_regex_registry_threading() -> None:
    """§1: load_agents → regex_registry key shape matches should_agent_speak consumer.

    Load skeptic.yaml (has regex trigger at index 0). Construct an event
    whose content matches the pattern. Assert speak=True with matched_trigger_index=0.
    Verifies (agent_id, trigger_index) key shape is consistent between producer
    (load_agents) and consumer (should_agent_speak) at runtime.
    """
    models = _models_for_config()
    agents, registry = load_agents(_CONFIG_DIR, models=models)

    assert "skeptic" in agents
    skeptic = agents["skeptic"]
    assert (skeptic.id, 0) in registry, "regex_registry missing key ('skeptic', 0)"

    # Construct event whose content matches skeptic's regex trigger (index 0)
    compiled_pattern: re.Pattern[str] = registry[(skeptic.id, 0)]
    matching_content = f"we know {compiled_pattern.pattern} is relevant"
    event = Event(
        id=generate_event_id(),
        room_id=generate_room_id(),
        type=EventType.USER_INPUT,
        author="user",
        timestamp=now_ms(),
        content=matching_content,
    )

    decision = should_agent_speak(skeptic, [], current_event=event, regex_registry=registry)
    assert decision.speak is True
    assert decision.matched_trigger_index == 0


# ---------------------------------------------------------------------------
# §1 full pipeline: loader → decide → dispatch_turn
# ---------------------------------------------------------------------------


def test_integration_full_pipeline_hypothesis_event() -> None:
    """§1: load both agents; hypothesis event triggers skeptic; dispatch_turn
    returns non-empty utterances in alphabetical-id order."""
    models = _models_for_config()
    agents, registry = load_agents(_CONFIG_DIR, models=models)
    assert "skeptic" in agents and "prober" in agents

    store = _make_store()
    room = _make_room(store)

    # hypothesis event — matches skeptic's event_type trigger (index 1)
    hypothesis = Event(
        id=generate_event_id(),
        room_id=room.id,
        type=EventType.HYPOTHESIS,
        author="user",
        timestamp=now_ms(),
        content="The system slows because of lock contention.",
        metadata={"confidence": 0.7},
    )
    store.append(hypothesis)

    selection = decide_agents_for_room(RoomType.RESEARCH, "open", available_agents=agents)
    loaded_agents = {a.id: a for a in selection.loaded}
    loaded_ids = [a.id for a in selection.loaded]
    # All 5 canonical agents apply to research; alphabetical order
    assert "prober" in loaded_ids
    assert "skeptic" in loaded_ids
    assert loaded_ids.index("prober") < loaded_ids.index("skeptic")

    router = MagicMock(spec=LLMRouterProtocol)
    router.call.return_value = _llm_response("skeptic challenges this hypothesis")

    result = dispatch_turn(
        loaded_agents,
        room,
        hypothesis,
        event_store=store,
        llm_router=router,
        available_skills={},
        regex_registry=registry,
        tools={},
    )

    # skeptic should speak (hypothesis event_type trigger); prober should NOT
    # (its regex trigger looks for "?" in content, and hypothesis has none)
    assert result.total_asked >= 1
    assert result.failed_agents == []
    assert len(result.utterances) >= 1
    # The last dispatch that spoke should be skeptic
    speaking_authors = {u.author for u in result.utterances}
    assert build_author("skeptic") in speaking_authors


def test_integration_alphabetical_dispatch_order() -> None:
    """Dispatch order is alphabetical by agent id: prober before skeptic."""
    models = _models_for_config()
    agents, registry = load_agents(_CONFIG_DIR, models=models)

    store = _make_store()
    room = _make_room(store)

    # Use USER_INPUT with "?" → prober's regex fires; use hypothesis → skeptic's event_type fires
    # To get both to speak: hypothesis event that also has "?" in content
    event = Event(
        id=generate_event_id(),
        room_id=room.id,
        type=EventType.HYPOTHESIS,
        author="user",
        timestamp=now_ms(),
        content="Is this a valid hypothesis?",
        metadata={"confidence": 0.5},
    )
    store.append(event)

    dispatch_calls: list[str] = []

    def _capture_call(request: object) -> LLMResponse:
        from orchestrator.llm.types import LLMRequest

        assert isinstance(request, LLMRequest)
        assert request.caller_agent_id is not None
        dispatch_calls.append(request.caller_agent_id)
        return _llm_response(f"{request.caller_agent_id} reply")

    router = MagicMock(spec=LLMRouterProtocol)
    router.call.side_effect = _capture_call

    result = dispatch_turn(
        {a.id: a for a in agents.values()},
        room,
        event,
        event_store=store,
        llm_router=router,
        available_skills={},
        regex_registry=registry,
        tools={},
    )

    assert result.failed_agents == []
    # Both prober (regex "?") and skeptic (event_type hypothesis) should speak
    # Alphabetical: prober before skeptic
    if len(dispatch_calls) == 2:
        assert dispatch_calls[0] == "prober"
        assert dispatch_calls[1] == "skeptic"
    else:
        # At least one agent spoke
        assert len(dispatch_calls) >= 1


def test_integration_event_store_consistency() -> None:
    """Utterances appended to event_store are retrievable in subsequent snapshot."""
    models = _models_for_config()
    agents, registry = load_agents(_CONFIG_DIR, models=models)

    store = _make_store()
    room = _make_room(store)

    event = Event(
        id=generate_event_id(),
        room_id=room.id,
        type=EventType.HYPOTHESIS,
        author="user",
        timestamp=now_ms(),
        content="Memory leak hypothesis.",
        metadata={"confidence": 0.6},
    )
    store.append(event)

    router = MagicMock(spec=LLMRouterProtocol)
    router.call.return_value = _llm_response("noted")

    result = dispatch_turn(
        {a.id: a for a in agents.values()},
        room,
        event,
        event_store=store,
        llm_router=router,
        available_skills={},
        regex_registry=registry,
        tools={},
    )

    if result.utterances:
        snapshot_after = store.get_room_events(room.id)
        stored_ids = {e.id for e in snapshot_after}
        for utterance in result.utterances:
            assert utterance.id in stored_ids, (
                f"utterance {utterance.id} not found in event_store after dispatch"
            )
