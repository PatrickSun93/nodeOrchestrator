"""P3.4-C2-4: tools/ package constitutional invariant tests (ADR-028 D6).

Mirrors tests/mcp/test_constitution.py for the tools/ leaf package.
P4.1-8 extends with t5-t8 (ADR-033 D6).

t1 — tools/ is a downstream leaf:
     No upstream layer (core/autonomy/agents/llm/rooms/skills/connectors/
     memory/producers/reentry/derived/workflow) imports orchestrator.tools.
     Only api/ (the composition root) is allowed to import it.

t2 — no autonomy decision in the executor:
     tools/ does not reference decide_tier/emit_gate_decision/score/gate.
     The executor consumes the gate's TOOL_CALL record; it never re-gates.

t3 — no new LLMPurpose:
     The frozen LLMPurpose set is unchanged; the MCP interpret reuses
     TOOL_OUTPUT_INTERPRET (carry-forward #2, ADR-028 D6).

t4 — execution keys on TOOL_CALL only (input-boundary structural + behavioral):
     ADR-030 D1 amendment (P3.6-B3, architect-ratified Y1): EventType.TOOL_CALL
     now has EXACTLY TWO appenders in src/, both downstream-of-gate:
       (a) agents/tool_dispatch.py::process_tool_calls (AUTO_EXECUTE branch).
       (b) api/app.py::_post_confirm (confirm-approve path -- reconstructs from
           the gate-produced TOOL_CALL_PENDING record; never from request fields).
     No third appender is permitted. The confirm appender's downstream-of-gate
     property is a behavioral trust surface (not grep-verifiable), pinned by the
     named behavioral guard and the no-forge acceptance test in tests/api/.
     (behavioral) No TOOL_CALL in window -> zero server/impl calls
       (tested in test_executor.py section 7; verified here via AST).

t5 — driver loop (_write_and_turn) invokes no autonomy-decision symbol (ADR-033 D6):
     The re-dispatch loop in api/app.py does not reference decide_tier /
     emit_gate_decision / score / gate / select_model_and_provider.
     Autonomy decisions happen inside dispatch_turn (agents/ layer); the loop
     only calls dispatch_turn + execute_pending_tool_calls — both unchanged.

t6 — B2 code-intel tools are in-process (ADR-033 D5 carry-forward #6):
     tools/local.py does not import subprocess / use Popen / call os.system.
     All code-intel tools (search_text, search_code, find_references,
     find_definition) use os.walk + re in-process.

t7 — TOOL_CALL guard exists before execute_pending_tool_calls in driver loop:
     The re-dispatch loop checks for new TOOL_CALL events and breaks if zero
     before calling execute_pending_tool_calls — execute-on-TOOL_CALL-only
     structural guard (ADR-033 D3 condition 1 / D1).

t8 — B2 / log_event trusted-not-interpreted: tools/local.py never references
     EventType.OBSERVATION (local tools emit TOOL_RESULT, never OBSERVATION).
     Combined with the executor's behavioral tests in test_local.py §6 +
     test_b2_no_observation_event.

t9 (B3-7) — no shell=True / os.system / shell-string in subprocess builder:
     subprocess_tools.py + subprocess_trust.run_scoped_command must not use
     shell=True, shell-string argv, or os.system. ADR-034 D3-i / carry-forward #6.
     t6 (local.py in-process) still passes — this test covers the NEW subprocess surface.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator"
_TOOLS_PKG = _SRC / "tools"
_API_PKG = _SRC / "api"


# ---------------------------------------------------------------------------
# t1: No upstream layer imports orchestrator.tools
# ---------------------------------------------------------------------------


def test_t1_no_upstream_layer_imports_tools() -> None:
    """Upstream layers must NOT import orchestrator.tools.* (tools/ is a leaf consumer)."""
    upstream_roots = [
        _SRC / "core",
        _SRC / "autonomy",
        _SRC / "agents",
        _SRC / "llm",
        _SRC / "rooms",
        _SRC / "skills",
        _SRC / "connectors",
        _SRC / "memory",
        _SRC / "producers",
        _SRC / "reentry",
        _SRC / "derived",
        _SRC / "workflow",
    ]
    violations: list[str] = []
    for root in upstream_roots:
        if not root.exists():
            continue
        for py_path in root.rglob("*.py"):
            if "__pycache__" in py_path.parts:
                continue
            source = py_path.read_text(encoding="utf-8")
            if "orchestrator.tools" not in source:
                continue
            tree = ast.parse(source, filename=str(py_path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    module = ""
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            module = alias.name
                    elif node.module:
                        module = node.module
                    if module.startswith("orchestrator.tools"):
                        violations.append(f"  {py_path}: line {node.lineno}: {module}")
    assert not violations, "t1 guard: upstream layer imports orchestrator.tools.*:\n" + "\n".join(
        violations
    )


# ---------------------------------------------------------------------------
# t2: tools/ does not reference autonomy decision symbols
# ---------------------------------------------------------------------------


_FORBIDDEN_IN_TOOLS = frozenset(
    {
        "decide_tier",
        "emit_gate_decision",
        "score",
    }
)
_GATE_FORBIDDEN = "gate"


def test_t2_no_autonomy_decision_in_tools() -> None:
    """tools/ must not call decide_tier/emit_gate_decision/score/gate."""
    violations: list[str] = []
    for py_path in _TOOLS_PKG.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        source = py_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Name, ast.Attribute)):
                continue
            name = node.id if isinstance(node, ast.Name) else node.attr
            if name in _FORBIDDEN_IN_TOOLS:
                violations.append(f"  {py_path}: line {node.lineno}: {name!r} referenced")
            if name == _GATE_FORBIDDEN and isinstance(node, ast.Name):
                violations.append(f"  {py_path}: line {node.lineno}: {name!r} referenced as Name")
    assert not violations, "t2 guard: tools/ references autonomy decision symbols:\n" + "\n".join(
        violations
    )


# ---------------------------------------------------------------------------
# t3: No new LLMPurpose values (frozen set, ADR-028 D6 carry-forward)
# ---------------------------------------------------------------------------


_KNOWN_PURPOSES = frozenset(
    {
        "AGENT_RESPONSE",
        "SNAPSHOT_SEMANTIC",
        "HYPOTHESIS_CANDIDATE",
        "KEY_NODE_CANDIDATE",
        "TOOL_OUTPUT_INTERPRET",
        "TERM_DEFINITION_PROPOSAL",
        "REENTRY_DIGEST_RENDER",
        "ARCHIVE_SUMMARY_RENDER",
        "HYPOTHESIS_TAG_PROPOSAL",
    }
)


def test_t3_no_new_llm_purpose() -> None:
    """LLMPurpose enum must not gain new values beyond the frozen set (ADR-028 D6)."""
    from orchestrator.llm.purposes import LLMPurpose

    actual = frozenset(p.name for p in LLMPurpose)
    new_values = actual - _KNOWN_PURPOSES
    assert not new_values, (
        f"t3 guard: new LLMPurpose values detected (require ADR + frozen-set update): "
        f"{sorted(new_values)}"
    )


# ---------------------------------------------------------------------------
# t4: TOOL_CALL has exactly one appender in src/ (the sole-appender invariant)
# ---------------------------------------------------------------------------


def test_t3b_executor_empty_decision_diff() -> None:
    """Empty-decision-diff invariant (ADR-031 D1 / P3.7-remote-5): _execute_local_call
    must NOT reference decide_tier/emit_gate_decision/score/gate/select_model_and_provider.

    The Posture-B subprocess cap is an executor MECHANISM addition (in execute_pending_tool_calls),
    NOT a decision-logic change.  _execute_local_call's decision path is unchanged.

    This is the canonical location for the empty-diff guard; test_posture_b.py pb6 tests the
    same invariant at component level.
    """
    executor_path = _SRC / "tools" / "executor.py"
    tree = ast.parse(executor_path.read_text(encoding="utf-8"))

    decision_symbols = frozenset(
        {
            "decide_tier",
            "emit_gate_decision",
            "score",
            "select_model_and_provider",
        }
    )

    fn_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_execute_local_call":
            fn_node = node
            break

    assert fn_node is not None, "t3b: _execute_local_call not found in executor.py"

    violations: list[str] = []
    for node in ast.walk(fn_node):
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if isinstance(node, ast.Name) else node.attr
            if name in decision_symbols:
                violations.append(f"  executor.py:{node.lineno}: {name!r}")

    assert not violations, (
        "t3b empty-decision-diff: _execute_local_call references decision symbols "
        "(Posture-B cap must be in execute_pending_tool_calls, NOT in _execute_local_call):\n"
        + "\n".join(violations)
    )


def test_t4_tool_call_sole_appender_in_src() -> None:
    """EventType.TOOL_CALL has exactly TWO appenders (ADR-030 D1 amendment / P3.6-B3 Y1).

    Both are downstream-of-gate:
      (a) agents/tool_dispatch.py -- AUTO_EXECUTE branch in process_tool_calls.
      (b) api/app.py -- confirm-approve path in _post_confirm.
    No third appender is permitted.

    All other src/ files may READ EventType.TOOL_CALL (comparisons, filter,
    isinstance checks) but must NOT call event_store.append(...) with
    type=EventType.TOOL_CALL or type='tool_call'.
    """
    tool_dispatch_path = _SRC / "agents" / "tool_dispatch.py"
    confirm_endpoint_path = _SRC / "api" / "app.py"

    # Files allowed to contain TOOL_CALL appends: exactly the two legitimate appenders.
    allowed_appenders = frozenset({tool_dispatch_path, confirm_endpoint_path})

    append_violations: list[str] = []

    for py_path in _SRC.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        if py_path in allowed_appenders:
            continue
        source = py_path.read_text(encoding="utf-8")
        if "TOOL_CALL" not in source and "tool_call" not in source:
            continue
        # Check for .append( patterns containing TOOL_CALL as the type argument.
        # Heuristic: look for "EventType.TOOL_CALL" near ".append(" in the same expression.
        tree = ast.parse(source, filename=str(py_path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # Looking for event_store.append(Event(..., type=EventType.TOOL_CALL, ...))
            if not (isinstance(node.func, ast.Attribute) and node.func.attr == "append"):
                continue
            for arg in node.args + [kw.value for kw in node.keywords]:
                if not isinstance(arg, ast.Call):
                    continue
                for kw in arg.keywords:
                    if kw.arg == "type" and isinstance(kw.value, ast.Attribute):
                        if kw.value.attr == "TOOL_CALL":
                            append_violations.append(
                                f"  {py_path}: line {node.lineno}: "
                                f"append with type=EventType.TOOL_CALL outside the two "
                                f"allowed appenders (tool_dispatch.py + app.py confirm)"
                            )
                    elif (
                        kw.arg == "type"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value == "tool_call"
                    ):
                        append_violations.append(
                            f"  {py_path}: line {node.lineno}: "
                            f"append with type='tool_call' outside the two "
                            f"allowed appenders (tool_dispatch.py + app.py confirm)"
                        )

    assert not append_violations, (
        "t4 guard: TOOL_CALL event appended outside the two legitimate appenders "
        "(ADR-030 D1 two-appender invariant violated):\n" + "\n".join(append_violations)
    )


# ---------------------------------------------------------------------------
# t5: Driver loop (_write_and_turn) invokes no autonomy-decision symbol (ADR-033 D6)
# ---------------------------------------------------------------------------

_DRIVER_LOOP_FORBIDDEN = frozenset(
    {"decide_tier", "emit_gate_decision", "score", "select_model_and_provider"}
)


def test_t5_driver_loop_no_autonomy_decision_symbols() -> None:
    """_write_and_turn in api/app.py must not reference autonomy-decision symbols.

    The re-dispatch loop calls dispatch_turn + execute_pending_tool_calls only.
    All autonomy decisions happen inside dispatch_turn (agents/ layer).
    ADR-033 D6.
    """
    app_path = _API_PKG / "app.py"
    tree = ast.parse(app_path.read_text(encoding="utf-8"))

    fn_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_write_and_turn":
            fn_node = node
            break

    assert fn_node is not None, "t5: _write_and_turn not found in api/app.py"

    violations: list[str] = []
    for node in ast.walk(fn_node):
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if isinstance(node, ast.Name) else node.attr
            if name in _DRIVER_LOOP_FORBIDDEN:
                violations.append(f"  app.py:{node.lineno}: {name!r} referenced in _write_and_turn")

    assert not violations, (
        "t5 guard: _write_and_turn references autonomy-decision symbols "
        "(loop must not re-gate; ADR-033 D6):\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# t6: B2 code-intel tools are in-process (no subprocess / Popen / os.system)
# ---------------------------------------------------------------------------


def test_t6_b2_no_subprocess_in_local_tools() -> None:
    """tools/local.py must not import subprocess or use Popen / os.system.

    All B2 code-intel tools (search_text, search_code, find_references,
    find_definition) use os.walk + re in-process. ADR-033 D5 carry-forward #6.
    """
    local_path = _TOOLS_PKG / "local.py"
    tree = ast.parse(local_path.read_text(encoding="utf-8"))

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess" or alias.name.startswith("subprocess."):
                    violations.append(f"  local.py:{node.lineno}: imports {alias.name!r}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and (
                node.module == "subprocess" or node.module.startswith("subprocess.")
            ):
                violations.append(f"  local.py:{node.lineno}: from {node.module!r} import ...")
        elif isinstance(node, ast.Name) and node.id == "Popen":
            violations.append(f"  local.py:{node.lineno}: references Popen as Name")
        elif isinstance(node, ast.Attribute):
            if node.attr == "Popen":
                violations.append(f"  local.py:{node.lineno}: references .Popen")
            if (
                node.attr == "system"
                and isinstance(node.value, ast.Name)
                and node.value.id == "os"
            ):
                violations.append(f"  local.py:{node.lineno}: calls os.system")

    assert not violations, (
        "t6 guard: tools/local.py uses subprocess/Popen/os.system "
        "(B2 tools must be in-process; ADR-033 D5 carry-forward #6):\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# t7: TOOL_CALL guard exists before execute_pending_tool_calls in driver loop
# ---------------------------------------------------------------------------


def test_t7_loop_tool_call_guard_before_execute() -> None:
    """Driver loop has a TOOL_CALL guard that can break before execute_pending_tool_calls.

    Structural check: the re-dispatch For loop in _write_and_turn contains
    both (a) an If node whose test involves EventType.TOOL_CALL and (b) an
    execute_pending_tool_calls call — confirming execute-on-TOOL_CALL-only
    per pass (ADR-033 D3 C1 / D1).
    """
    app_path = _API_PKG / "app.py"
    tree = ast.parse(app_path.read_text(encoding="utf-8"))

    fn_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_write_and_turn":
            fn_node = node
            break

    assert fn_node is not None, "t7: _write_and_turn not found in api/app.py"

    # Find the re-dispatch For loop (iterating over range(MAX_TURN_LOOP_PASSES)).
    loop_node = None
    for node in ast.walk(fn_node):
        if isinstance(node, ast.For):
            loop_node = node
            break

    assert loop_node is not None, "t7: no For loop found in _write_and_turn"

    # The loop body must reference EventType.TOOL_CALL (guard check).
    has_tool_call_check = False
    has_execute_call = False
    for node in ast.walk(loop_node):
        if isinstance(node, ast.Attribute) and node.attr == "TOOL_CALL":
            has_tool_call_check = True
        if isinstance(node, ast.Call) and (
            (isinstance(node.func, ast.Name) and node.func.id == "execute_pending_tool_calls")
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "execute_pending_tool_calls"
            )
        ):
            has_execute_call = True

    assert has_tool_call_check, (
        "t7 guard: re-dispatch loop has no EventType.TOOL_CALL guard — "
        "execute-on-TOOL_CALL-only structural invariant missing (ADR-033 D3 C1)"
    )
    assert has_execute_call, (
        "t7 guard: re-dispatch loop has no execute_pending_tool_calls call — "
        "loop body structure unexpected"
    )


# ---------------------------------------------------------------------------
# t8: B2 / log_event trusted-not-interpreted — no OBSERVATION in tools/local.py
# ---------------------------------------------------------------------------


def test_t8_b2_no_observation_in_local_tools() -> None:
    """tools/local.py must not reference EventType.OBSERVATION or the string 'OBSERVATION'.

    Local tools emit TOOL_RESULT (via LocalToolOutput → executor); they are
    trusted (our own code) and never routed through the interpret step
    (ADR-033 D5 / ADR-028 D2). Behavioral verification: test_local.py
    test_b2_no_observation_event + test_log_event_returns_tool_result.
    """
    local_path = _TOOLS_PKG / "local.py"
    source = local_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "OBSERVATION":
            violations.append(f"  local.py:{node.lineno}: references .OBSERVATION")
        elif isinstance(node, ast.Constant) and node.value == "OBSERVATION":
            violations.append(f"  local.py:{node.lineno}: string literal 'OBSERVATION'")

    assert not violations, (
        "t8 guard: tools/local.py references OBSERVATION — local tools must emit "
        "TOOL_RESULT only (trusted-not-interpreted; ADR-033 D5 / ADR-028 D2):\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# t9 (B3-7): No shell=True / shell-string / os.system in subprocess builder
# ---------------------------------------------------------------------------


def test_t9_no_shell_in_subprocess_surface() -> None:
    """B3-7: subprocess_tools.py and run_scoped_command must not use shell=True.

    AST check mirrors t6 (local.py in-process) for the B3 subprocess surface.
    ADR-034 D3-i / carry-forward #6: argv must be a list; shell=True / shell-string
    / os.system are forbidden. Mirrors the ADR-032 verify=False constitution precedent.

    t6 (local.py) must still pass — local.py is in-process-pristine; this test
    covers the NEW subprocess surface only.
    """
    subprocess_tools_path = _TOOLS_PKG / "subprocess_tools.py"
    subprocess_trust_path = _SRC / "mcp" / "subprocess_trust.py"

    violations: list[str] = []

    for path, scope in [
        (subprocess_tools_path, "subprocess_tools.py"),
        (subprocess_trust_path, "subprocess_trust.py (run_scoped_command context)"),
    ]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            # Forbidden: shell=True as keyword argument
            if (
                isinstance(node, ast.keyword)
                and node.arg == "shell"
                and isinstance(node.value, ast.Constant)
                and node.value.value is True
            ):
                violations.append(
                    f"  {scope}:{node.value.col_offset}: shell=True found"
                )
            # Forbidden: os.system(...)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "system"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "os"
            ):
                violations.append(
                    f"  {scope}:{node.lineno}: os.system() call found"
                )

    # Verify argv to open_process/run_scoped_command is always a list (not a single string)
    # in subprocess_tools.py AND subprocess_trust.py — symmetric with the shell=True/os.system
    # checks above (defense-in-depth; no live gap but asymmetry is fragile).
    for path, scope in [
        (subprocess_tools_path, "subprocess_tools.py"),
        (subprocess_trust_path, "subprocess_trust.py"),
    ]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                fname = ""
                if isinstance(func, ast.Attribute):
                    fname = func.attr
                elif isinstance(func, ast.Name):
                    fname = func.id
                if fname in ("open_process", "run_scoped_command") and node.args:
                    first_arg = node.args[0]
                    if isinstance(first_arg, ast.Constant) and isinstance(
                        first_arg.value, str
                    ):
                        violations.append(
                            f"  {scope}:{node.lineno}: "
                            f"{fname}() called with shell-string (not list argv)"
                        )

    assert not violations, (
        "t9 guard: shell=True / os.system / shell-string found in subprocess surface "
        "(ADR-034 D3-i carry-forward #6 — argv must be a list, never shell=True):\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# B3-5 drift sync-test: _SUBPROCESS_TOOL_NAMES == build_subprocess_tool_registry keys
# ---------------------------------------------------------------------------


def test_b35_subprocess_tool_names_drift_guard() -> None:
    """Drift guard: selection._SUBPROCESS_TOOL_NAMES must equal the registry keys.

    A tool added to build_subprocess_tool_registry without updating
    _SUBPROCESS_TOOL_NAMES would silently escape the excerpt-exclusion filter.
    This test fails the build in that case.

    The test crosses the agents→tools layer boundary, but only in test code
    (never at runtime) — by design per B3-5 acceptance criteria.
    """
    import tempfile
    from pathlib import Path as _Path

    from orchestrator.agents.selection import _SUBPROCESS_TOOL_NAMES
    from orchestrator.tools.subprocess_tools import build_subprocess_tool_registry

    with tempfile.TemporaryDirectory() as td:
        registry_keys = set(build_subprocess_tool_registry(_Path(td)).keys())

    assert registry_keys == set(_SUBPROCESS_TOOL_NAMES), (
        "Drift: build_subprocess_tool_registry keys != selection._SUBPROCESS_TOOL_NAMES.\n"
        f"Registry has: {sorted(registry_keys)}\n"
        f"selection has: {sorted(_SUBPROCESS_TOOL_NAMES)}\n"
        "Update _SUBPROCESS_TOOL_NAMES in agents/selection.py to match."
    )


def test_b35_subprocess_result_excluded_from_excerpt() -> None:
    """Subprocess TOOL_RESULT is absent from excerpt; reaches agent as current_event (B3-5).

    Two-channel split: injection string in run_tests TOOL_RESULT must NOT appear in
    snapshot_excerpt (system block), confirming excerpt exclusion works correctly.
    """
    from orchestrator.agents.selection import _render_snapshot_excerpt
    from orchestrator.core.event import (
        Event,
        EventType,
        generate_event_id,
        generate_room_id,
        now_ms,
    )

    injection = "INJECTED_SUBPROCESS_CANARY_STRING_DO_NOT_RENDER"
    rid = generate_room_id()

    # TOOL_CALL for run_tests
    tc = Event(
        id=generate_event_id(),
        room_id=rid,
        type=EventType.TOOL_CALL,
        author="agent:tester",
        timestamp=now_ms(),
        content="",
        metadata={"tool_name": "run_tests", "call_id": "cid_sub_1", "params": {}},
    )
    # TOOL_RESULT for run_tests containing injection
    tr = Event(
        id=generate_event_id(),
        room_id=rid,
        type=EventType.TOOL_RESULT,
        author="agent:tester",
        timestamp=now_ms(),
        content=injection,
        metadata={"call_id": "cid_sub_1", "success": True},
    )
    # In-process local TOOL_RESULT (trusted — should still appear)
    safe_tr = Event(
        id=generate_event_id(),
        room_id=rid,
        type=EventType.TOOL_RESULT,
        author="agent:tester",
        timestamp=now_ms(),
        content="safe_local_result",
        metadata={"call_id": "cid_safe_1", "success": True},
    )

    snapshot = [tc, tr, safe_tr]
    excerpt = _render_snapshot_excerpt(snapshot)

    # Subprocess TOOL_RESULT must be absent from excerpt
    assert excerpt is None or injection not in excerpt, (
        f"Subprocess TOOL_RESULT injection string appeared in snapshot_excerpt: {excerpt!r}"
    )
    # In-process local TOOL_RESULT must still appear
    assert excerpt is not None and "safe_local_result" in excerpt, (
        f"Trusted local TOOL_RESULT missing from snapshot_excerpt: {excerpt!r}"
    )


# ---------------------------------------------------------------------------
# B4-6 drift sync-test: _NETWORK_TOOL_NAMES == build_network_tool_registry keys
# ---------------------------------------------------------------------------


def test_b46_network_tool_names_drift_guard() -> None:
    """Drift guard: selection._NETWORK_TOOL_NAMES must equal the registry keys.

    A tool added to build_network_tool_registry without updating
    _NETWORK_TOOL_NAMES would silently escape the excerpt-exclusion filter.
    This test fails the build in that case.

    Crosses the agents→tools layer boundary in test code only (not at runtime).
    """
    from orchestrator.agents.selection import _NETWORK_TOOL_NAMES
    from orchestrator.tools.network_tools import build_network_tool_registry

    registry_keys = set(build_network_tool_registry().keys())

    assert registry_keys == set(_NETWORK_TOOL_NAMES), (
        "Drift: build_network_tool_registry keys != selection._NETWORK_TOOL_NAMES.\n"
        f"Registry has: {sorted(registry_keys)}\n"
        f"selection has: {sorted(_NETWORK_TOOL_NAMES)}\n"
        "Update _NETWORK_TOOL_NAMES in agents/selection.py to match."
    )


def test_b46_network_result_excluded_from_excerpt() -> None:
    """Network TOOL_RESULT is absent from excerpt; reaches agent as current_event (B4-6).

    Two-channel split: injection string in web_fetch TOOL_RESULT must NOT appear in
    snapshot_excerpt (system block), confirming excerpt exclusion works correctly.
    Same-pass coupling watch-point (ADR-034 D3-iv / ADR-035 D3-iii).
    """
    from orchestrator.agents.selection import _render_snapshot_excerpt
    from orchestrator.core.event import (
        Event,
        EventType,
        generate_event_id,
        generate_room_id,
        now_ms,
    )

    injection = "INJECTED_NETWORK_CANARY_STRING_DO_NOT_RENDER"
    rid = generate_room_id()

    # TOOL_CALL for web_fetch
    tc = Event(
        id=generate_event_id(),
        room_id=rid,
        type=EventType.TOOL_CALL,
        author="agent:tester",
        timestamp=now_ms(),
        content="",
        metadata={"tool_name": "web_fetch", "call_id": "cid_net_1", "params": {}},
    )
    # TOOL_RESULT for web_fetch containing injection
    tr = Event(
        id=generate_event_id(),
        room_id=rid,
        type=EventType.TOOL_RESULT,
        author="agent:tester",
        timestamp=now_ms(),
        content=injection,
        metadata={"call_id": "cid_net_1", "success": True},
    )
    # In-process local TOOL_RESULT (trusted — should still appear)
    safe_tr = Event(
        id=generate_event_id(),
        room_id=rid,
        type=EventType.TOOL_RESULT,
        author="agent:tester",
        timestamp=now_ms(),
        content="safe_local_result",
        metadata={"call_id": "cid_safe_1", "success": True},
    )

    snapshot = [tc, tr, safe_tr]
    excerpt = _render_snapshot_excerpt(snapshot)

    # Network TOOL_RESULT must be absent from excerpt
    assert excerpt is None or injection not in excerpt, (
        f"Network TOOL_RESULT injection string appeared in snapshot_excerpt: {excerpt!r}"
    )
    # In-process local TOOL_RESULT must still appear
    assert excerpt is not None and "safe_local_result" in excerpt, (
        f"Trusted local TOOL_RESULT missing from snapshot_excerpt: {excerpt!r}"
    )
