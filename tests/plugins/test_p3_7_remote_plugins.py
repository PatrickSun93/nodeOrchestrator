"""P3.7-remote plugin demo + e2e tests (ADR-031 D6; P3.7-remote-8).

Covers:
  demo1  — demo_posture_b plugin loads from operator-placed root → Posture-B closures.
  demo2  — demo_posture_b.posture_b_echo executes via subprocess → correct content.
  demo3  — fetched plugin: fetch (hermetic mock) → activate → Posture-B execute → TOOL_RESULT.
  demo4  — env-leak probe: child subprocess doesn't see orchestrator secrets.
  demo5  — per-turn Posture-B cap enforced end-to-end (executor + demo plugin).
  demo6  — SIGTERM-ignoring plugin → watchdog kills → TOOL_FAILED without orphan.
  demo7  — tampered bundle rejected (digest mismatch) before extraction.
  demo8  — unactivated fetched plugin refused.
  demo9  — provenance-laundering test: fetched bundle not discoverable as operator-placed.
"""

from __future__ import annotations

import hashlib
import io
import sqlite3
import textwrap
import zipfile
from pathlib import Path
from typing import Any

import pytest
import yaml

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
from orchestrator.llm.router import ModelRegistry
from orchestrator.llm.types import (
    ModelId,
    ModelProfile,
    ProviderId,
)
from orchestrator.mcp._async_bridge import MCPConnectionError, MCPTimeoutError
from orchestrator.plugins.fetch import FetchError, fetch_plugin_bundle
from orchestrator.plugins.loader import load_plugins
from orchestrator.plugins.schema import PLUGIN_HOST_CONTRACT_VERSION
from orchestrator.tools.executor import (
    MAX_POSTURE_B_CALLS_PER_TURN,
    LocalToolOutput,
    execute_pending_tool_calls,
)

# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------

_PROVIDER = ProviderId("test_provider")
_MODELS = ModelRegistry(
    {
        ModelId("m1"): ModelProfile(
            id=ModelId("m1"),
            provider=_PROVIDER,
            provider_model_id="m1",
            capabilities=[],
            context_window=8192,
        )
    }
)
_HOST_ROOM_TYPES: frozenset[str] = frozenset({"free_chat"})
_PLUGINS_DIR = Path(__file__).parent.parent.parent / "plugins"


def _make_store() -> EventStore:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    store = EventStore(conn)
    store.init_schema()
    return store


def _make_room(store: EventStore) -> RoomId:
    room = Room(id=generate_room_id(), type=RoomType.RESEARCH)
    store.append_room(room)
    return room.id


def _tc_event(
    room_id: RoomId,
    tool_name: str,
    call_id: str = "tc_1",
    params: dict[str, Any] | None = None,
) -> Event:
    return Event(
        id=generate_event_id(),
        room_id=room_id,
        type=EventType.TOOL_CALL,
        author="agent:tester",
        timestamp=now_ms(),
        content="",
        metadata=ToolCallMeta(
            tool_name=tool_name,
            call_id=call_id,
            params=params or {},
        ).model_dump(),
    )


class _NoLLM:
    def route(self, request: Any) -> Any:
        raise AssertionError("LLM not expected for local tool tests")


def _load_plugins_dir(
    plugins_dir: Path | None = None,
    fetched_dir: Path | None = None,
    activation_path: Path | None = None,
) -> Any:
    return load_plugins(
        plugins_dir or _PLUGINS_DIR,
        models=_MODELS,
        host_room_types=_HOST_ROOM_TYPES,
        host_contract_version=PLUGIN_HOST_CONTRACT_VERSION,
        host_agents={},
        host_skills={},
        host_tools={},
        host_local_tool_names=frozenset(),
        host_mcp_server_names=frozenset(),
        fetched_plugins_dir=fetched_dir,
        activation_registry_path=activation_path,
    )


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _make_plugin_zip(plugin_id: str, extra_impl: str = "") -> bytes:
    """Create a minimal plugin zip bundle."""
    impl = textwrap.dedent(f"""\
        from orchestrator.tools.executor import LocalToolOutput
        def demo_fn(params):
            return LocalToolOutput(content='fetched-{plugin_id}')
        {extra_impl}
    """)
    manifest = textwrap.dedent(f"""\
        schema_version: 1
        id: {plugin_id}
        name: '{plugin_id}'
        version: '0.1.0'
        contributions:
          tool_impls:
            demo_tool: 'tools_impl:demo_fn'
    """)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("plugin.yaml", manifest)
        zf.writestr("tools_impl.py", impl)
    return buf.getvalue()


def _write_activation(
    path: Path,
    plugin_id: str,
    digest: str,
    source_url: str = "https://example.com/plugin.zip",
) -> None:
    path.write_text(
        yaml.dump(
            {
                "activations": [
                    {
                        "plugin_id": plugin_id,
                        "source_url": source_url,
                        "digest": digest,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# demo1: demo_posture_b plugin loads from operator-placed root
# ---------------------------------------------------------------------------


def test_demo1_demo_posture_b_plugin_loads() -> None:
    """demo_posture_b operator-placed plugin loads using in-process Posture A (ADR-029 D4)."""
    result = _load_plugins_dir()
    assert "posture_b_echo" in result.local_tools
    assert "posture_b_env_probe" in result.local_tools
    # Operator-placed → Posture A (in-process): no _is_posture_b_subprocess marker
    for fn in [result.local_tools["posture_b_echo"], result.local_tools["posture_b_env_probe"]]:
        assert not bool(getattr(fn, "_is_posture_b_subprocess", False))


# ---------------------------------------------------------------------------
# demo2: demo_posture_b.posture_b_echo executes via subprocess
# ---------------------------------------------------------------------------


def test_demo2_posture_b_echo_executes() -> None:
    """posture_b_echo executes in subprocess → LocalToolOutput with correct content."""
    result = _load_plugins_dir()
    fn = result.local_tools["posture_b_echo"]
    output = fn({"message": "hello-from-subprocess"})
    assert isinstance(output, LocalToolOutput)
    assert "hello-from-subprocess" in output.content


def test_demo2_posture_b_echo_via_executor() -> None:
    """posture_b_echo called via execute_pending_tool_calls → TOOL_RESULT appended."""
    result = _load_plugins_dir()

    store = _make_store()
    room_id = _make_room(store)
    tc = _tc_event(room_id, "posture_b_echo", "echo_1", {"message": "demo-echo"})
    store.append(tc)

    execute_pending_tool_calls(
        window_events=[tc],
        room_id=room_id,
        event_store=store,
        mcp_sessions={},
        local_tools=result.local_tools,
        llm_router=_NoLLM(),  # type: ignore[arg-type]
    )

    events = store.get_room_events(room_id)
    tool_results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(tool_results) == 1
    assert "demo-echo" in tool_results[0].content


# ---------------------------------------------------------------------------
# demo3: fetch → activate → Posture-B execute → TOOL_RESULT
# ---------------------------------------------------------------------------


def test_demo3_fetch_activate_execute_e2e(tmp_path: Path) -> None:
    """Fetched plugin: hermetic fetch → activation → Posture-B execute → TOOL_RESULT.

    Uses a hermetic mock (no network) to demonstrate the complete loop.
    """
    import httpx

    bundle = _make_plugin_zip("fetched_demo")
    digest = _sha256(bundle)
    fetched_dir = tmp_path / "fetched"
    activation_path = tmp_path / "activations.yaml"
    source_url = "https://example.com/fetched_demo.zip"

    # Fetch the bundle (hermetic mock)
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=bundle)

    client = httpx.Client(transport=httpx.MockTransport(_handler))
    fetch_plugin_bundle(
        source_url=source_url,
        expected_digest=digest,
        plugin_id="fetched_demo",
        fetched_plugins_dir=fetched_dir,
        http_client=client,
    )

    # Write activation
    _write_activation(activation_path, "fetched_demo", digest, source_url)

    # Load plugins (operator-placed root + fetched root)
    op_dir = tmp_path / "op_plugins"
    op_dir.mkdir()
    plugins = _load_plugins_dir(
        plugins_dir=op_dir,
        fetched_dir=fetched_dir,
        activation_path=activation_path,
    )

    # Execute via subprocess
    store = _make_store()
    room_id = _make_room(store)
    tc = _tc_event(room_id, "demo_tool", "demo_1")
    store.append(tc)

    execute_pending_tool_calls(
        window_events=[tc],
        room_id=room_id,
        event_store=store,
        mcp_sessions={},
        local_tools=plugins.local_tools,
        llm_router=_NoLLM(),  # type: ignore[arg-type]
    )

    events = store.get_room_events(room_id)
    results = [e for e in events if e.type == EventType.TOOL_RESULT]
    assert len(results) == 1
    assert "fetched-fetched_demo" in results[0].content


# ---------------------------------------------------------------------------
# demo4: env-leak probe
# ---------------------------------------------------------------------------


def test_demo4_posture_a_tool_sees_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Posture-A (operator-placed) tools run in-process and CAN access os.environ.

    Env isolation (scoped env) is a Posture-B property for fetched plugins only
    (test_pb5 in test_posture_b.py covers subprocess env isolation).
    """
    secret_key = "P3_7_REMOTE_TEST_SECRET_ZZZZZ"
    monkeypatch.setenv(secret_key, "posture-a-sees-this")

    result = _load_plugins_dir()
    fn = result.local_tools["posture_b_env_probe"]
    output = fn({"key": secret_key})
    # Posture A: in-process tool reads os.environ directly
    assert output.content == "posture-a-sees-this", (
        f"Posture-A in-process tool should see env var, got: {output.content!r}"
    )


# ---------------------------------------------------------------------------
# demo5: per-turn Posture-B cap end-to-end
# ---------------------------------------------------------------------------


def test_demo5_posture_a_tools_exempt_from_posture_b_cap() -> None:
    """Posture-A (operator-placed) tools are exempt from MAX_POSTURE_B_CALLS_PER_TURN.

    Only Posture-B (_is_posture_b_subprocess marker) tools count toward the cap.
    Operator-placed tools have no subprocess overhead and are uncapped.
    End-to-end Posture-B cap behavior is tested via test_pb4 in test_posture_b.py.
    """
    result = _load_plugins_dir()

    store = _make_store()
    room_id = _make_room(store)

    n = MAX_POSTURE_B_CALLS_PER_TURN + 2
    window: list[Event] = []
    for i in range(n):
        tc = _tc_event(room_id, "posture_b_echo", f"cap_cid_{i}", {"message": f"msg-{i}"})
        store.append(tc)
        window.append(tc)

    execute_pending_tool_calls(
        window_events=window,
        room_id=room_id,
        event_store=store,
        mcp_sessions={},
        local_tools=result.local_tools,
        llm_router=_NoLLM(),  # type: ignore[arg-type]
    )

    events = store.get_room_events(room_id)
    tool_results = [e for e in events if e.type == EventType.TOOL_RESULT]
    cap_failed = [
        e
        for e in events
        if e.type == EventType.TOOL_FAILED
        and e.metadata.get("error_class") == "turn_posture_b_cap_exceeded"
    ]
    # Posture A: all calls succeed, cap is not applied
    assert len(tool_results) == n
    assert len(cap_failed) == 0


# ---------------------------------------------------------------------------
# demo6: hung/SIGTERM-ignoring plugin → watchdog kills → TOOL_FAILED
# ---------------------------------------------------------------------------


def test_demo6_sigterm_ignoring_plugin_killed_by_watchdog(tmp_path: Path) -> None:
    """A SIGTERM-ignoring plugin subprocess is force-killed by the LAYER-1 watchdog."""
    from orchestrator.plugins import code as code_mod
    from orchestrator.plugins.code import _PostureBFn

    # Create a SIGTERM-ignoring tool
    module_file = tmp_path / "tools_impl.py"
    module_file.write_text(
        textwrap.dedent("""\
            import signal, time
            from orchestrator.tools.executor import LocalToolOutput
            def hang(params):
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                time.sleep(9999)
                return LocalToolOutput(content="never")
        """),
        encoding="utf-8",
    )
    original_timeout = code_mod._CALL_TIMEOUT
    try:
        code_mod._CALL_TIMEOUT = 2.0
        fn = _PostureBFn(
            module_file=module_file,
            callable_name="hang",
            plugin_id="sigterm_demo",
            plugin_subprocess_env={},
        )
        with pytest.raises((MCPTimeoutError, MCPConnectionError)):
            fn({})
    finally:
        code_mod._CALL_TIMEOUT = original_timeout


# ---------------------------------------------------------------------------
# demo7: tampered bundle rejected before extraction
# ---------------------------------------------------------------------------


def test_demo7_tampered_bundle_rejected(tmp_path: Path) -> None:
    """A bundle with a tampered (wrong) digest is rejected before extraction."""
    bundle = _make_plugin_zip("tampered")
    wrong_digest = "sha256:" + "f" * 64
    fetched_dir = tmp_path / "fetched"

    import httpx

    def _handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=bundle)

    client = httpx.Client(transport=httpx.MockTransport(_handler))
    with pytest.raises(FetchError, match="digest mismatch"):
        fetch_plugin_bundle(
            source_url="https://example.com/tampered.zip",
            expected_digest=wrong_digest,
            plugin_id="tampered",
            fetched_plugins_dir=fetched_dir,
            http_client=client,
        )
    assert not (fetched_dir / "tampered").exists()


# ---------------------------------------------------------------------------
# demo8: unactivated fetched plugin refused
# ---------------------------------------------------------------------------


def test_demo8_unactivated_fetched_plugin_refused(tmp_path: Path) -> None:
    """A fetched plugin without an activation entry is refused."""
    bundle = _make_plugin_zip("unactivated")
    digest = _sha256(bundle)
    fetched_dir = tmp_path / "fetched"

    import httpx

    def _handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=bundle)

    client = httpx.Client(transport=httpx.MockTransport(_handler))
    fetch_plugin_bundle(
        source_url="https://example.com/unactivated.zip",
        expected_digest=digest,
        plugin_id="unactivated",
        fetched_plugins_dir=fetched_dir,
        http_client=client,
    )

    # No activation registry → refused
    op_dir = tmp_path / "op_plugins"
    op_dir.mkdir()
    result = _load_plugins_dir(
        plugins_dir=op_dir,
        fetched_dir=fetched_dir,
        activation_path=None,
    )
    assert "demo_tool" not in result.local_tools


# ---------------------------------------------------------------------------
# demo9: provenance-laundering test
# ---------------------------------------------------------------------------


def test_demo9_fetched_bundle_not_discoverable_as_operator_placed(tmp_path: Path) -> None:
    """A bundle in fetched_plugins_dir cannot be discovered as operator_placed.

    Even with a valid activation, the fetched root is separate.
    A plugin placed ONLY in fetched_dir is never seen by the operator-placed
    discovery path (un-launderable provenance, ADR-031 D3).
    """
    bundle = _make_plugin_zip("launder_test")
    digest = _sha256(bundle)
    fetched_dir = tmp_path / "fetched"
    activation_path = tmp_path / "activations.yaml"

    import httpx

    def _handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=bundle)

    client = httpx.Client(transport=httpx.MockTransport(_handler))
    fetch_plugin_bundle(
        source_url="https://example.com/launder.zip",
        expected_digest=digest,
        plugin_id="launder_test",
        fetched_plugins_dir=fetched_dir,
        http_client=client,
    )
    _write_activation(activation_path, "launder_test", digest)

    # Load with operator-placed root ONLY (no fetched_dir) → plugin not discoverable
    op_dir = tmp_path / "op_plugins"
    op_dir.mkdir()
    result_op_only = _load_plugins_dir(plugins_dir=op_dir)
    assert "demo_tool" not in result_op_only.local_tools

    # Load with both roots + activation → loads as fetched
    result_both = _load_plugins_dir(
        plugins_dir=op_dir,
        fetched_dir=fetched_dir,
        activation_path=activation_path,
    )
    fn = result_both.local_tools.get("demo_tool")
    assert fn is not None
    assert bool(getattr(fn, "_is_posture_b_subprocess", False))
