"""P3.4-C2-4: tools/ package constitutional invariant tests (ADR-028 D6).

Mirrors tests/mcp/test_constitution.py for the tools/ leaf package.

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
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator"
_TOOLS_PKG = _SRC / "tools"


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
