"""P3.4-C2-2 acceptance tests for tools/local.py (local tool implementations).

Tests the MVP local tool set through the executor's local-dispatch hook:
  - get_current_time: pure clock read, no I/O
  - read_file: sandboxed FS, bounded read, path-traversal rejection
  - list_files: sandboxed FS, path-traversal rejection, byte-cap (Y2 fix)
  - not_implemented fail-closed seam
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from orchestrator.agents.dispatch import LLMRouterProtocol
from orchestrator.core.event import (
    Event,
    EventType,
    RoomId,
    ToolCallMeta,
    generate_event_id,
    generate_room_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.core.room import Room, RoomType
from orchestrator.llm.types import LLMRequest, LLMResponse, ModelId, ProviderId, Usage
from orchestrator.mcp.execution import MAX_RESULT_BYTES
from orchestrator.tools.executor import execute_pending_tool_calls
from orchestrator.tools.local import build_local_tool_registry

# ---------------------------------------------------------------------------
# Helpers (duplicated from test_executor.py helpers for standalone isolation)
# ---------------------------------------------------------------------------

_MOCK_MODEL = ModelId("mock-model")
_MOCK_PROVIDER = ProviderId("mock-provider")


def _make_store() -> EventStore:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    store = EventStore(conn)
    store.init_schema()
    return store


def _make_room(store: EventStore) -> RoomId:
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    return room.id


def _tc_event(room_id: RoomId, tool_name: str, call_id: str = "tc_1") -> Event:
    return Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.TOOL_CALL,
        author="agent:tester",
        timestamp=now_ms(),
        content="",
        metadata=ToolCallMeta(tool_name=tool_name, call_id=call_id, params={}).model_dump(),
    )


def _tc_event_params(
    room_id: RoomId, tool_name: str, call_id: str, params: dict[str, Any]
) -> Event:
    return Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.TOOL_CALL,
        author="agent:tester",
        timestamp=now_ms(),
        content="",
        metadata=ToolCallMeta(tool_name=tool_name, call_id=call_id, params=params).model_dump(),
    )


def _noop_llm_router() -> LLMRouterProtocol:
    mock = MagicMock(spec=LLMRouterProtocol)

    def _call(req: LLMRequest) -> LLMResponse:
        from orchestrator.llm.types import RequestId

        return LLMResponse(
            request_id=RequestId("req_noop"),
            content="",
            model_id_requested=_MOCK_MODEL,
            model_id_used=_MOCK_MODEL,
            provider_id_used=_MOCK_PROVIDER,
            usage=Usage(input_tokens=0, output_tokens=0),
            latency_ms=0,
            finish_reason="stop",
        )

    mock.call.side_effect = _call
    return mock


# ---------------------------------------------------------------------------
# §5 Local tools: get_current_time
# ---------------------------------------------------------------------------


def test_get_current_time_returns_time_string(tmp_path: Path) -> None:
    """get_current_time → TOOL_RESULT with a time string; no I/O."""
    store = _make_store()
    room_id = _make_room(store)
    tc = _tc_event(room_id, "get_current_time")
    store.append(tc)

    registry = build_local_tool_registry(tmp_path)

    execute_pending_tool_calls(
        window_events=[tc],
        room_id=room_id,
        event_store=store,
        mcp_sessions={},
        local_tools=registry,
        llm_router=_noop_llm_router(),
    )

    events = store.get_room_events(room_id)
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(results) == 1
    assert results[0].metadata["success"] is True
    assert len(results[0].content) > 0  # non-empty time string


# ---------------------------------------------------------------------------
# §5 Local tools: read_file (sandboxed FS + bounded read)
# ---------------------------------------------------------------------------


def test_read_file_inside_sandbox(tmp_path: Path) -> None:
    """read_file inside sandbox root → TOOL_RESULT with file content."""
    (tmp_path / "hello.txt").write_text("hello world", encoding="utf-8")
    store = _make_store()
    room_id = _make_room(store)
    tc = _tc_event_params(room_id, "read_file", "tc_rf", {"path": "hello.txt"})
    store.append(tc)

    registry = build_local_tool_registry(tmp_path)

    execute_pending_tool_calls(
        window_events=[tc],
        room_id=room_id,
        event_store=store,
        mcp_sessions={},
        local_tools=registry,
        llm_router=_noop_llm_router(),
    )

    events = store.get_room_events(room_id)
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(results) == 1
    assert "hello world" in results[0].content
    assert results[0].metadata["success"] is True


def test_read_file_path_traversal_rejected(tmp_path: Path) -> None:
    """read_file with path escaping sandbox root → TOOL_FAILED."""
    store = _make_store()
    room_id = _make_room(store)
    tc = _tc_event_params(room_id, "read_file", "tc_escape", {"path": "../../etc/passwd"})
    store.append(tc)

    execute_pending_tool_calls(
        window_events=[tc],
        room_id=room_id,
        event_store=store,
        mcp_sessions={},
        local_tools=build_local_tool_registry(tmp_path),
        llm_router=_noop_llm_router(),
    )

    events = store.get_room_events(room_id)
    assert len([e for e in events if e.type == EventType.TOOL_FAILED]) == 1
    assert not any(e.type == EventType.TOOL_RESULT for e in events)


def test_read_file_absolute_path_outside_rejected(tmp_path: Path) -> None:
    """read_file with absolute path outside sandbox → TOOL_FAILED."""
    store = _make_store()
    room_id = _make_room(store)
    tc = _tc_event_params(room_id, "read_file", "tc_abs", {"path": "/etc/passwd"})
    store.append(tc)

    execute_pending_tool_calls(
        window_events=[tc],
        room_id=room_id,
        event_store=store,
        mcp_sessions={},
        local_tools=build_local_tool_registry(tmp_path),
        llm_router=_noop_llm_router(),
    )

    events = store.get_room_events(room_id)
    assert len([e for e in events if e.type == EventType.TOOL_FAILED]) == 1
    assert not any(e.type == EventType.TOOL_RESULT for e in events)


def test_read_file_symlink_escape_rejected(tmp_path: Path) -> None:
    """read_file with symlink pointing outside sandbox → TOOL_FAILED."""
    outside = tmp_path.parent / "outside_sym.txt"
    outside.write_text("secret", encoding="utf-8")
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "link.txt").symlink_to(outside)

    store = _make_store()
    room_id = _make_room(store)
    tc = _tc_event_params(room_id, "read_file", "tc_sym", {"path": "link.txt"})
    store.append(tc)

    execute_pending_tool_calls(
        window_events=[tc],
        room_id=room_id,
        event_store=store,
        mcp_sessions={},
        local_tools=build_local_tool_registry(sandbox),
        llm_router=_noop_llm_router(),
    )

    events = store.get_room_events(room_id)
    assert len([e for e in events if e.type == EventType.TOOL_FAILED]) == 1
    assert not any(e.type == EventType.TOOL_RESULT for e in events)


def test_read_file_oversized_bounded_read(tmp_path: Path) -> None:
    """read_file of oversized file → bounded read (MAX_RESULT_BYTES+1), output_truncated_at set."""
    (tmp_path / "big.txt").write_bytes(b"b" * (MAX_RESULT_BYTES + 1000))
    store = _make_store()
    room_id = _make_room(store)
    tc = _tc_event_params(room_id, "read_file", "tc_big", {"path": "big.txt"})
    store.append(tc)

    execute_pending_tool_calls(
        window_events=[tc],
        room_id=room_id,
        event_store=store,
        mcp_sessions={},
        local_tools=build_local_tool_registry(tmp_path),
        llm_router=_noop_llm_router(),
    )

    events = store.get_room_events(room_id)
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(results) == 1
    r = results[0]
    assert r.metadata["output_truncated_at"] == MAX_RESULT_BYTES
    assert len(r.content.encode("utf-8")) <= MAX_RESULT_BYTES


# ---------------------------------------------------------------------------
# §5 Local tools: list_files (sandboxed FS)
# ---------------------------------------------------------------------------


def test_list_files_inside_sandbox(tmp_path: Path) -> None:
    """list_files inside sandbox root → TOOL_RESULT with directory listing."""
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    store = _make_store()
    room_id = _make_room(store)
    tc = _tc_event_params(room_id, "list_files", "tc_ls", {"path": "."})
    store.append(tc)

    execute_pending_tool_calls(
        window_events=[tc],
        room_id=room_id,
        event_store=store,
        mcp_sessions={},
        local_tools=build_local_tool_registry(tmp_path),
        llm_router=_noop_llm_router(),
    )

    events = store.get_room_events(room_id)
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(results) == 1
    listing = results[0].content
    assert "a.txt" in listing
    assert "b.txt" in listing


def test_list_files_path_escape_rejected(tmp_path: Path) -> None:
    """list_files with path escaping sandbox → TOOL_FAILED."""
    store = _make_store()
    room_id = _make_room(store)
    tc = _tc_event_params(room_id, "list_files", "tc_ls_esc", {"path": "../.."})
    store.append(tc)

    execute_pending_tool_calls(
        window_events=[tc],
        room_id=room_id,
        event_store=store,
        mcp_sessions={},
        local_tools=build_local_tool_registry(tmp_path),
        llm_router=_noop_llm_router(),
    )

    events = store.get_room_events(room_id)
    assert len([e for e in events if e.type == EventType.TOOL_FAILED]) == 1
    assert not any(e.type == EventType.TOOL_RESULT for e in events)


def test_list_files_output_byte_cap_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """list_files output exceeding MAX_RESULT_BYTES → capped + output_truncated_at set (Y2 fix)."""
    import orchestrator.tools.local as _local_mod

    # Small cap so a handful of files suffices; avoids creating thousands.
    monkeypatch.setattr(_local_mod, "MAX_RESULT_BYTES", 50)

    # Create files whose combined listing exceeds 50 bytes.
    # E.g. "alpha_file.txt\nbeta_file.txt\n..." ≈ 15 bytes/entry → 4+ entries exceed 50 bytes.
    for name in ["alpha_file.txt", "beta_file.txt", "gamma_file.txt", "delta_file.txt"]:
        (tmp_path / name).touch()

    store = _make_store()
    room_id = _make_room(store)
    tc = _tc_event_params(room_id, "list_files", "tc_ls_big", {"path": "."})
    store.append(tc)

    execute_pending_tool_calls(
        window_events=[tc],
        room_id=room_id,
        event_store=store,
        mcp_sessions={},
        local_tools=build_local_tool_registry(tmp_path),
        llm_router=_noop_llm_router(),
    )

    events = store.get_room_events(room_id)
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(results) == 1
    r = results[0]
    assert r.metadata["output_truncated_at"] == 50
    assert len(r.content.encode("utf-8")) <= 50
    # Output must contain only whole entry names (no partial names at truncation boundary).
    for name in r.content.split("\n"):
        assert name.strip() == name  # no partial UTF-8 corruption


# ---------------------------------------------------------------------------
# §5 not_implemented fail-closed seam
# ---------------------------------------------------------------------------


def test_classified_but_unimplemented_tool_fails_closed(tmp_path: Path) -> None:
    """Tool in tools.yaml (AUTO) but not in local_tools registry → TOOL_FAILED(not_implemented)."""
    store = _make_store()
    room_id = _make_room(store)
    tc = _tc_event(room_id, "web_search")  # AUTO in tools.yaml, not in MVP registry
    store.append(tc)

    execute_pending_tool_calls(
        window_events=[tc],
        room_id=room_id,
        event_store=store,
        mcp_sessions={},
        local_tools=build_local_tool_registry(tmp_path),  # only has time/read/list
        llm_router=_noop_llm_router(),
    )

    events = store.get_room_events(room_id)
    failed = [e for e in events if e.type == EventType.TOOL_FAILED]
    assert len(failed) == 1
    assert failed[0].metadata["error_class"] == "not_implemented"
    assert not any(e.type == EventType.TOOL_RESULT for e in events)
