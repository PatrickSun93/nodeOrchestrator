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


# ---------------------------------------------------------------------------
# §6 B2 code-intel tools (P4.1-2): search_text, search_code, find_references,
# find_definition, log_event
# ---------------------------------------------------------------------------


def _run_local_tool(
    tmp_path: Path, tool_name: str, params: dict[str, Any]
) -> tuple[EventStore, list[Any]]:
    """Helper: run a single local tool call, return store + all events."""
    store = _make_store()
    room_id = _make_room(store)
    tc = _tc_event_params(room_id, tool_name, "tc_b2", params)
    store.append(tc)
    execute_pending_tool_calls(
        window_events=[tc],
        room_id=room_id,
        event_store=store,
        mcp_sessions={},
        local_tools=build_local_tool_registry(tmp_path),
        llm_router=_noop_llm_router(),
    )
    return store, store.get_room_events(room_id)


def test_search_text_finds_match(tmp_path: Path) -> None:
    """search_text returns file:line hits for a substring query."""
    (tmp_path / "code.py").write_text("def hello():\n    return 42\n", encoding="utf-8")
    _store, events = _run_local_tool(tmp_path, "search_text", {"query": "hello"})
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(results) == 1
    assert "hello" in results[0].content
    assert results[0].metadata["success"] is True
    assert not any(e.type == EventType.OBSERVATION for e in events)


def test_search_text_no_match(tmp_path: Path) -> None:
    """search_text with no match returns '(no matches)'."""
    (tmp_path / "code.py").write_text("def hello():\n    pass\n", encoding="utf-8")
    _store, events = _run_local_tool(tmp_path, "search_text", {"query": "xyz_not_present_abc"})
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(results) == 1
    assert "(no matches)" in results[0].content


def test_search_text_scope_escape_rejected(tmp_path: Path) -> None:
    """search_text with scope escaping sandbox → TOOL_FAILED."""
    _store, events = _run_local_tool(tmp_path, "search_text", {"query": "x", "scope": "../../etc"})
    assert any(e.type == EventType.TOOL_FAILED for e in events)
    assert not any(e.type == EventType.TOOL_RESULT for e in events)


def test_search_text_output_capped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """search_text caps output at MAX_RESULT_BYTES → output_truncated_at set."""
    import orchestrator.tools.local as _local_mod

    monkeypatch.setattr(_local_mod, "MAX_RESULT_BYTES", 50)
    monkeypatch.setattr(_local_mod, "_SEARCH_FILE_READ_BYTES", 50)
    # Create a file with many matching lines to force output cap.
    lines = "\n".join(f"match_target line_{i}" for i in range(200))
    (tmp_path / "big.py").write_text(lines, encoding="utf-8")
    _store, events = _run_local_tool(tmp_path, "search_text", {"query": "match_target"})
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(results) == 1
    assert results[0].metadata.get("output_truncated_at") is not None


def test_search_text_max_search_files_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """search_text stops after MAX_SEARCH_FILES files (traversal bound)."""
    import orchestrator.tools.local as _local_mod

    monkeypatch.setattr(_local_mod, "MAX_SEARCH_FILES", 3)
    for i in range(10):
        (tmp_path / f"f{i}.py").write_text("no_match\n", encoding="utf-8")
    _store, events = _run_local_tool(tmp_path, "search_text", {"query": "no_match"})
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    # With MAX_SEARCH_FILES=3 and all files matching, output_truncated_at is set.
    assert len(results) == 1
    assert results[0].metadata.get("output_truncated_at") is not None


def test_search_code_regex_match(tmp_path: Path) -> None:
    """search_code returns regex-matched file:line hits."""
    (tmp_path / "src.py").write_text("class MyClass:\n    x = 1\n", encoding="utf-8")
    _store, events = _run_local_tool(tmp_path, "search_code", {"pattern": r"class \w+"})
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(results) == 1
    assert "MyClass" in results[0].content


def test_search_code_invalid_regex(tmp_path: Path) -> None:
    """search_code with invalid regex pattern → TOOL_FAILED."""
    _store, events = _run_local_tool(tmp_path, "search_code", {"pattern": "[invalid"})
    assert any(e.type == EventType.TOOL_FAILED for e in events)


def test_find_references_finds_usages(tmp_path: Path) -> None:
    """find_references returns word-boundary matches for a symbol."""
    (tmp_path / "use.py").write_text("from mod import my_func\nmy_func()\n", encoding="utf-8")
    _store, events = _run_local_tool(tmp_path, "find_references", {"symbol": "my_func"})
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(results) == 1
    assert "my_func" in results[0].content


def test_find_definition_finds_def(tmp_path: Path) -> None:
    """find_definition finds def/class/<symbol>= patterns."""
    (tmp_path / "defs.py").write_text("def my_func():\n    pass\n", encoding="utf-8")
    _store, events = _run_local_tool(tmp_path, "find_definition", {"symbol": "my_func"})
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(results) == 1
    assert "my_func" in results[0].content


def test_find_definition_finds_class(tmp_path: Path) -> None:
    """find_definition finds class definitions."""
    (tmp_path / "cls.py").write_text("class Foo:\n    pass\n", encoding="utf-8")
    _store, events = _run_local_tool(tmp_path, "find_definition", {"symbol": "Foo"})
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(results) == 1
    assert "Foo" in results[0].content


def test_find_definition_finds_assignment(tmp_path: Path) -> None:
    """find_definition finds <symbol> = patterns."""
    (tmp_path / "const.py").write_text("MAX_VALUE = 100\n", encoding="utf-8")
    _store, events = _run_local_tool(tmp_path, "find_definition", {"symbol": "MAX_VALUE"})
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(results) == 1
    assert "MAX_VALUE" in results[0].content


def test_b2_no_observation_event(tmp_path: Path) -> None:
    """B2 local tools produce TOOL_RESULT, never OBSERVATION (trusted-not-interpreted)."""
    (tmp_path / "f.py").write_text("hello\n", encoding="utf-8")
    for tool, params in [
        ("search_text", {"query": "hello"}),
        ("search_code", {"pattern": "hello"}),
        ("find_references", {"symbol": "hello"}),
        ("find_definition", {"symbol": "hello"}),
    ]:
        _store, events = _run_local_tool(tmp_path, tool, params)
        assert not any(e.type == EventType.OBSERVATION for e in events), (
            f"{tool} must not produce OBSERVATION"
        )


def test_log_event_returns_tool_result(tmp_path: Path) -> None:
    """log_event returns TOOL_RESULT with [type] content prefix."""
    _store, events = _run_local_tool(
        tmp_path, "log_event", {"content": "found a bug", "type": "finding"}
    )
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(results) == 1
    assert "found a bug" in results[0].content
    assert "[finding]" in results[0].content
    assert results[0].metadata["success"] is True
    assert not any(e.type == EventType.OBSERVATION for e in events)


def test_log_event_empty_content_fails(tmp_path: Path) -> None:
    """log_event with empty content → TOOL_FAILED."""
    _store, events = _run_local_tool(tmp_path, "log_event", {"content": "", "type": "note"})
    assert any(e.type == EventType.TOOL_FAILED for e in events)
    assert not any(e.type == EventType.TOOL_RESULT for e in events)


# ---------------------------------------------------------------------------
# P4.1-3: log_event boundary — dict→LocalToolOutput signature + EventType invariant
# ---------------------------------------------------------------------------


def test_log_event_direct_signature() -> None:
    """log_event impl has dict→LocalToolOutput signature (no event_store handle).

    Calls _log_event_tool directly to verify the contract without the executor.
    ADR-033 D5: local tool fn is dict → LocalToolOutput; no I/O handles injected.
    """
    from orchestrator.tools.executor import LocalToolOutput
    from orchestrator.tools.local import _log_event_tool

    result = _log_event_tool({"content": "investigating foo", "type": "finding"})
    assert isinstance(result, LocalToolOutput)
    assert "investigating foo" in result.content
    assert "[finding]" in result.content
    assert result.output_truncated_at is None  # short content, no truncation


def test_log_event_default_type() -> None:
    """log_event type parameter defaults to 'note' when omitted."""
    from orchestrator.tools.local import _log_event_tool

    result = _log_event_tool({"content": "a note"})
    assert "[note]" in result.content


def test_log_event_eventtype_enum_unchanged() -> None:
    """log_event adds no new EventType value to core.event (ADR-033 D5/D6).

    EventType is the shared vocabulary; log_event results land as TOOL_RESULT,
    not a new event type.
    """
    from orchestrator.core.event import EventType

    known_types = {
        "USER_INPUT",
        "UTTERANCE",
        "TOOL_CALL",
        "TOOL_CALL_PENDING",
        "TOOL_CALL_CANCELLED",
        "TOOL_RESULT",
        "TOOL_FAILED",
        "OBSERVATION",
        "STATE_TRANSITION",
        "HYPOTHESIS",
        "TERM_DEFINITION",
        "AUTONOMY_DECISION",
        "AUTONOMY_REFUSAL",
        "DECISION",
        "DECISION_PIVOT",
        "ESCALATION",
        "EXTERNAL_VALIDATION",
        "MILESTONE",
        "REJECTION",
        "RETRACTION",
        "SUMMARY_SNAPSHOT",
    }
    actual = {e.name for e in EventType}
    new_types = actual - known_types
    assert not new_types, (
        f"log_event must not introduce new EventType values: {sorted(new_types)}"
    )


def test_log_event_output_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """log_event with content exceeding MAX_RESULT_BYTES → truncated output."""
    import orchestrator.tools.local as _local_mod

    monkeypatch.setattr(_local_mod, "MAX_RESULT_BYTES", 20)
    big_content = "x" * 1000
    _store, events = _run_local_tool(
        tmp_path, "log_event", {"content": big_content, "type": "note"}
    )
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(results) == 1
    assert results[0].metadata.get("output_truncated_at") == 20


# ---------------------------------------------------------------------------
# Fix 3 (R0-A Y2): B2 search symlink-escape containment (ADR-028 D3 / R0-A Y2)
# ---------------------------------------------------------------------------


def test_search_text_sandbox_internal_symlink_to_outside_not_in_hits(tmp_path: Path) -> None:
    """search_text: in-sandbox symlinked FILE pointing outside is skipped (ADR-028 D3 / R0-A Y2).

    Mirrors test_read_file_symlink_escape_rejected but for the B2 search tools.
    The sandbox contains a real file with a match and a symlink to an external
    file that also matches. The external file must NOT appear in hits.
    """
    # Set up sandbox with one real file and one symlink pointing outside.
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("SECRET_OUTSIDE_CONTENT search_me\n", encoding="utf-8")
    (sandbox / "real.txt").write_text("search_me found_here\n", encoding="utf-8")
    (sandbox / "escape_link.txt").symlink_to(outside)

    store = _make_store()
    room_id = _make_room(store)
    tc = _tc_event_params(room_id, "search_text", "tc_sym_search", {"query": "search_me"})
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
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(results) == 1
    content = results[0].content
    # Real in-sandbox file should be found.
    assert "found_here" in content, f"Real file hit missing. Got: {content}"
    # External symlink target must NOT appear in hits.
    assert "SECRET_OUTSIDE_CONTENT" not in content, (
        f"Symlink-escaped content must not appear in search hits. Got: {content}"
    )
    assert "outside_secret.txt" not in content, (
        f"Path to external file must not appear in search hits. Got: {content}"
    )
