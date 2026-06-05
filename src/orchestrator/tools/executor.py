"""Runtime tool-executor: post-dispatch stage (ADR-028 D1/D2/D4/D5/D6).

execute_pending_tool_calls() runs after run_turn returns, routes each
AUTO_EXECUTE TOOL_CALL event to MCP execution or the local tool registry,
appends TOOL_RESULT/TOOL_FAILED (+MCP OBSERVATION), and returns.
No re-dispatch in the MVP (ADR-028 D4).

Constitutional invariants (tested by tests/tools/test_constitution.py):
- tools/ is a downstream leaf: no upstream layer imports orchestrator.tools.
- No autonomy decision: no decide_tier/emit_gate_decision/score/gate calls.
- No new LLMPurpose: MCP interpret reuses TOOL_OUTPUT_INTERPRET only.
- Execution keys on TOOL_CALL events only (sole-appender + behavioral filter).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FutureTimeout
from typing import Any

from orchestrator.agents.dispatch import LLMRouterProtocol
from orchestrator.agents.mcp_interpret import get_mcp_tool_interpretation
from orchestrator.core.event import (
    Event,
    EventType,
    RoomId,
    ToolResultMeta,
    build_author,
    generate_event_id,
    now_ms,
)
from orchestrator.core.event_store import EventStore
from orchestrator.mcp.adapter import AdapterError, to_mcp_call
from orchestrator.mcp.client import MCPSession
from orchestrator.mcp.execution import execute_mcp_tool_call

_log = logging.getLogger("orchestrator.tools.executor")

# Per-turn MCP AUTO_EXECUTE cap (ADR-028 D5 / R0-B Y4).
# MCP calls beyond this in one turn → TOOL_FAILED(turn_mcp_cap_exceeded).
MAX_MCP_CALLS_PER_TURN: int = 10

# Per-pass subprocess fork cap (ADR-031 D1 / ADR-034 D5 / R0-B Y6 → alpha).
# Subprocess LocalToolFn calls beyond this per execute_pending_tool_calls invocation →
# TOOL_FAILED(turn_subprocess_cap_exceeded). Covers both plugin Posture-B forks AND B3
# subprocess tools (identified by _is_posture_b_subprocess marker).
# Posture-A in-process tools are exempt (identified by absence of _is_posture_b_subprocess).
# Name retained _PER_TURN (ADR-034 D5); resets per pass; true per-turn bound = this x (1+N).
MAX_SUBPROCESS_CALLS_PER_TURN: int = 10

# Bounded deadline for the advisory MCP interpret call (ADR-028 D5 / R1).
# On timeout: raw TOOL_RESULT stands; no OBSERVATION appended.
INTERPRET_TIMEOUT_S: float = 30.0

# Interpret pool: separate from the writer thread so the writer blocks for
# at most INTERPRET_TIMEOUT_S per call, never indefinitely (ADR-028 D5 R1).
_INTERPRET_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tools-interpret")

LocalToolFn = Callable[[dict[str, Any]], "LocalToolOutput"]
LocalToolRegistry = dict[str, LocalToolFn]


class LocalToolOutput:
    """Structured result from a local tool implementation."""

    __slots__ = ("content", "output_truncated_at")

    def __init__(self, content: str, output_truncated_at: int | None = None) -> None:
        self.content = content
        self.output_truncated_at = output_truncated_at


def execute_pending_tool_calls(
    *,
    window_events: list[Event],
    room_id: RoomId,
    event_store: EventStore,
    mcp_sessions: dict[str, MCPSession],
    local_tools: LocalToolRegistry,
    llm_router: LLMRouterProtocol,
) -> None:
    """Execute TOOL_CALL events in the current turn's window.

    MCP tools (mcp__*):
      execute_mcp_tool_call → TOOL_RESULT/TOOL_FAILED →
      bounded advisory interpret → OBSERVATION (if TOOL_RESULT present).

    Local tools (non-mcp__):
      local_tools registry → TOOL_RESULT/TOOL_FAILED; no interpret.

    Both paths:
      - Double-execution guard: full-room history scope (ADR-028 D2 / R0-B Y1).
      - Per-call fail-closed isolation: one failure → TOOL_FAILED, others continue.

    MCP only:
      - Per-turn cap MAX_MCP_CALLS_PER_TURN; excess → TOOL_FAILED (D5 / R0-B Y4).
    """
    # Behavioral filter: only TOOL_CALL events (t4, ADR-028 D6).
    tool_calls = [e for e in window_events if e.type == EventType.TOOL_CALL]
    if not tool_calls:
        return

    # Double-execution guard: full-room history, not just this window (D2 / R0-B Y1).
    # LLM-generated call_ids can collide cross-turn; window-only check would miss them.
    all_room_events = event_store.get_room_events(room_id)
    already_executed: set[str] = {
        str(e.metadata.get("call_id", ""))
        for e in all_room_events
        if e.type in (EventType.TOOL_RESULT, EventType.TOOL_FAILED) and e.metadata.get("call_id")
    }

    mcp_calls_this_turn = 0
    subprocess_calls_this_turn = 0

    for tc_event in tool_calls:
        meta = tc_event.metadata
        tool_name: str = str(meta.get("tool_name", ""))
        call_id: str = str(meta.get("call_id", ""))
        agent_id = _extract_agent_id(tc_event.author)

        # Double-execution guard: skip if already recorded in room history.
        if call_id in already_executed:
            _log.info(
                "executor: skip duplicate call_id=%r tool=%r (already executed in room)",
                call_id,
                tool_name,
            )
            continue

        try:
            if tool_name.startswith("mcp__"):
                if mcp_calls_this_turn >= MAX_MCP_CALLS_PER_TURN:
                    _log.warning(
                        "executor: per-turn MCP cap (%d) reached; call_id=%r tool=%r → TOOL_FAILED",
                        MAX_MCP_CALLS_PER_TURN,
                        call_id,
                        tool_name,
                    )
                    _append_tool_failed(
                        event_store,
                        room_id,
                        call_id,
                        agent_id,
                        f"turn_mcp_cap_exceeded: limit={MAX_MCP_CALLS_PER_TURN}",
                        error_class="turn_mcp_cap_exceeded",
                    )
                else:
                    mcp_calls_this_turn += 1
                    _execute_mcp_call(
                        tc_event=tc_event,
                        tool_name=tool_name,
                        call_id=call_id,
                        agent_id=agent_id,
                        room_id=room_id,
                        event_store=event_store,
                        mcp_sessions=mcp_sessions,
                        llm_router=llm_router,
                    )
            else:
                # Subprocess cap: applied before dispatch (mechanism, not decision —
                # _execute_local_call decision logic is unchanged; empty-decision-diff holds).
                # Covers both plugin Posture-B forks AND B3 subprocess tools
                # (_is_posture_b_subprocess marks any subprocess-launching local tool).
                _impl = local_tools.get(tool_name)
                _is_posture_b: bool = _impl is not None and bool(
                    getattr(_impl, "_is_posture_b_subprocess", False)
                )
                if _is_posture_b:
                    if subprocess_calls_this_turn >= MAX_SUBPROCESS_CALLS_PER_TURN:
                        _log.warning(
                            "executor: per-turn subprocess cap (%d) reached; "
                            "call_id=%r tool=%r → TOOL_FAILED",
                            MAX_SUBPROCESS_CALLS_PER_TURN,
                            call_id,
                            tool_name,
                        )
                        _append_tool_failed(
                            event_store,
                            room_id,
                            call_id,
                            agent_id,
                            f"turn_subprocess_cap_exceeded: limit={MAX_SUBPROCESS_CALLS_PER_TURN}",
                            error_class="turn_subprocess_cap_exceeded",
                        )
                    else:
                        subprocess_calls_this_turn += 1
                        _execute_local_call(
                            tc_event=tc_event,
                            tool_name=tool_name,
                            call_id=call_id,
                            agent_id=agent_id,
                            room_id=room_id,
                            event_store=event_store,
                            local_tools=local_tools,
                        )
                else:
                    _execute_local_call(
                        tc_event=tc_event,
                        tool_name=tool_name,
                        call_id=call_id,
                        agent_id=agent_id,
                        room_id=room_id,
                        event_store=event_store,
                        local_tools=local_tools,
                    )
        except Exception as exc:
            _log.exception("executor: unexpected error for call_id=%r tool=%r", call_id, tool_name)
            _append_tool_failed(event_store, room_id, call_id, agent_id, f"executor_bug: {exc}")

        # Update in-loop dedup set after any outcome (success or fail).
        already_executed.add(call_id)


# ---------------------------------------------------------------------------
# MCP path
# ---------------------------------------------------------------------------


def _execute_mcp_call(
    *,
    tc_event: Event,
    tool_name: str,
    call_id: str,
    agent_id: str,
    room_id: RoomId,
    event_store: EventStore,
    mcp_sessions: dict[str, MCPSession],
    llm_router: LLMRouterProtocol,
) -> None:
    """Dispatch one MCP TOOL_CALL: execute → bounded advisory interpret."""
    try:
        server_name, _ = to_mcp_call(tool_name)
    except AdapterError as exc:
        _append_tool_failed(event_store, room_id, call_id, agent_id, f"bad_mcp_name: {exc}")
        return

    session = mcp_sessions.get(server_name)
    if session is None:
        _log.warning(
            "executor: mcp server=%r not in mcp_sessions; call_id=%r → not_available",
            server_name,
            call_id,
        )
        _append_tool_failed(
            event_store,
            room_id,
            call_id,
            agent_id,
            f"server not available: {server_name}",
            error_class="not_available",
        )
        return

    # execute_mcp_tool_call appends TOOL_RESULT or TOOL_FAILED (fail-closed).
    execute_mcp_tool_call(
        tool_call_event=tc_event,
        session=session,
        event_store=event_store,
        room_id=room_id,
        agent_id=agent_id,
    )

    # Find the TOOL_RESULT just appended (None if execute_mcp_tool_call failed → TOOL_FAILED).
    all_events = event_store.get_room_events(room_id)
    tr_event = next(
        (
            e
            for e in reversed(all_events)
            if e.type == EventType.TOOL_RESULT and str(e.metadata.get("call_id", "")) == call_id
        ),
        None,
    )
    if tr_event is not None:
        # Bounded advisory interpret (D5 R1 / Y1): pool task = LLM call only;
        # OBSERVATION append stays on the writer thread.
        _interpret_bounded(call_id, agent_id, room_id, event_store, llm_router, tr_event)


def _interpret_bounded(
    call_id: str,
    agent_id: str,
    room_id: RoomId,
    event_store: EventStore,
    llm_router: LLMRouterProtocol,
    tr_event: Event,
) -> None:
    """Run MCP interpret LLM call under deadline; append OBSERVATION on writer thread.

    Single-writer invariant (ADR-028 D1/D5 Y1):
    - Pool task: get_mcp_tool_interpretation — LLM call ONLY, no event_store access.
    - Writer thread: OBSERVATION append AFTER future.result() returns (or not at all).
    - On timeout: future.cancel() + no OBSERVATION (raw TOOL_RESULT stands, writer unblocked).
    A timed-out or leaked pool thread cannot write to the store because the pool
    task never calls event_store.append.
    """
    try:
        future = _INTERPRET_EXECUTOR.submit(
            get_mcp_tool_interpretation,
            tool_result_event=tr_event,
            agent_id=agent_id,
            llm_router=llm_router,
        )
        interpretation = future.result(timeout=INTERPRET_TIMEOUT_S)
    except _FutureTimeout:
        future.cancel()
        _log.warning(
            "executor: interpret timeout (%.1fs) for call_id=%r; keeping raw TOOL_RESULT",
            INTERPRET_TIMEOUT_S,
            call_id,
        )
        return
    except Exception as exc:
        _log.warning(
            "executor: interpret error for call_id=%r: %s; keeping raw TOOL_RESULT",
            call_id,
            exc,
        )
        return

    if not interpretation:
        return

    # OBSERVATION append on the single writer thread (single-writer invariant — ADR-028 D1/D5).
    event_store.append(
        Event(
            id=generate_event_id(),
            room_id=room_id,
            type=EventType.OBSERVATION,
            author=build_author(agent_id),
            timestamp=now_ms(),
            content=f"[MCP tool result interpretation]\n{interpretation}",
        )
    )


# ---------------------------------------------------------------------------
# Local path
# ---------------------------------------------------------------------------


def _execute_local_call(
    *,
    tc_event: Event,
    tool_name: str,
    call_id: str,
    agent_id: str,
    room_id: RoomId,
    event_store: EventStore,
    local_tools: LocalToolRegistry,
) -> None:
    """Dispatch one local TOOL_CALL: registry → run → TOOL_RESULT/TOOL_FAILED."""
    impl = local_tools.get(tool_name)
    if impl is None:
        _log.warning(
            "executor: local tool=%r not implemented; call_id=%r → not_implemented",
            tool_name,
            call_id,
        )
        _append_tool_failed(
            event_store,
            room_id,
            call_id,
            agent_id,
            f"not implemented: {tool_name}",
            error_class="not_implemented",
        )
        return

    params: dict[str, Any] = dict(tc_event.metadata.get("params", {}))
    try:
        output = impl(params)
    except Exception as exc:
        _log.warning("executor: local tool=%r raised: %s", tool_name, exc)
        _append_tool_failed(event_store, room_id, call_id, agent_id, f"local_tool_error: {exc}")
        return

    event_store.append(
        Event(
            id=generate_event_id(),
            room_id=room_id,
            type=EventType.TOOL_RESULT,
            author=build_author(agent_id),
            timestamp=now_ms(),
            content=output.content,
            metadata=ToolResultMeta(
                call_id=call_id,
                success=True,
                output_truncated_at=output.output_truncated_at,
            ).model_dump(),
        )
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _append_tool_failed(
    event_store: EventStore,
    room_id: RoomId,
    call_id: str,
    agent_id: str,
    reason: str,
    error_class: str = "executor_error",
) -> None:
    event_store.append(
        Event(
            id=generate_event_id(),
            room_id=room_id,
            type=EventType.TOOL_FAILED,
            author=build_author(agent_id),
            timestamp=now_ms(),
            content=f"tool_failed: {reason}",
            metadata=ToolResultMeta(
                call_id=call_id,
                success=False,
                error_class=error_class,
            ).model_dump(),
        )
    )


def _extract_agent_id(author: str) -> str:
    if author.startswith("agent:"):
        return author[len("agent:") :]
    return author or "executor"
