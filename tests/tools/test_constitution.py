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
     (structural) EventType.TOOL_CALL has exactly ONE appender in src/:
       agents/tool_dispatch.py::process_tool_calls (inside AUTO_EXECUTE block).
       No other non-read site appends a TOOL_CALL event.
     (behavioral) No TOOL_CALL in window → zero server/impl calls
       (tested in test_executor.py §7; verified here via AST).
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


def test_t4_tool_call_sole_appender_in_src() -> None:
    """EventType.TOOL_CALL has exactly one appender: agents/tool_dispatch.py.

    All other src/ files may READ EventType.TOOL_CALL (comparisons, filter,
    isinstance checks) but must NOT call event_store.append(...) with
    type=EventType.TOOL_CALL or type='tool_call'.

    This is the structural half of the t4 downstream-of-gate guarantee
    (ADR-028 D6): TOOL_CALL records can only come from the gate-approved
    process_tool_calls path, so the executor's input window can only contain
    gate-approved records.
    """
    tool_dispatch_path = _SRC / "agents" / "tool_dispatch.py"

    # Files allowed to contain TOOL_CALL appends: only tool_dispatch.py.
    append_violations: list[str] = []

    for py_path in _SRC.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        if py_path == tool_dispatch_path:
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
                                f"append with type=EventType.TOOL_CALL outside tool_dispatch.py"
                            )
                    elif (
                        kw.arg == "type"
                        and isinstance(kw.value, ast.Constant)
                        and kw.value.value == "tool_call"
                    ):
                        append_violations.append(
                            f"  {py_path}: line {node.lineno}: "
                            f"append with type='tool_call' outside tool_dispatch.py"
                        )

    assert not append_violations, (
        "t4 guard: TOOL_CALL event appended outside tool_dispatch.py (sole-appender violated):\n"
        + "\n".join(append_violations)
    )
