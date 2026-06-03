"""P3.5-6: plugins/ package constitutional invariant tests (ADR-029 D3 / HR#3-4).

Models tests/tools/test_constitution.py and tests/mcp/test_constitution.py.

p1 — plugins/ does not reference autonomy decision symbols:
     No decide_tier / emit_gate_decision / score / gate / select_model_and_provider.
     Plugin loading is discovery + validation + registration — code, not judgment
     (ADR-029 D3 / HR#3).

p2 — plugins/ makes no llm/ provider call:
     No import from orchestrator.llm.providers.* (no LLM calls in the loader).

p3 — No new LLMPurpose values:
     The frozen LLMPurpose set is unchanged (ADR-029 D3 / HR#4; no new purpose).

p4 — select_model_and_provider absent:
     Routing remains code-only (ADR-002/023); plugins/ never invokes the model
     selector (confirmed by AST scan).
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator"
_PLUGINS_PKG = _SRC / "plugins"


# ---------------------------------------------------------------------------
# p1: No autonomy decision symbols in plugins/
# ---------------------------------------------------------------------------

_FORBIDDEN_DECISION_SYMBOLS = frozenset(
    {
        "decide_tier",
        "emit_gate_decision",
        "score",
        "select_model_and_provider",
    }
)
_GATE_NAME = "gate"


def test_p1_no_autonomy_decision_in_plugins() -> None:
    """plugins/ must not reference decide_tier/emit_gate_decision/score/gate/
    select_model_and_provider — plugin loading is code, not judgment (ADR-029 D3)."""
    violations: list[str] = []
    for py_path in _PLUGINS_PKG.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        source = py_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Name, ast.Attribute)):
                continue
            name = node.id if isinstance(node, ast.Name) else node.attr
            if name in _FORBIDDEN_DECISION_SYMBOLS:
                violations.append(f"  {py_path}: line {node.lineno}: {name!r} referenced")
            if name == _GATE_NAME and isinstance(node, ast.Name):
                violations.append(f"  {py_path}: line {node.lineno}: {name!r} referenced as Name")
    assert not violations, "p1 guard: plugins/ references autonomy decision symbols:\n" + "\n".join(
        violations
    )


# ---------------------------------------------------------------------------
# p2: No llm/ provider imports in plugins/
# ---------------------------------------------------------------------------


def test_p2_no_llm_provider_import_in_plugins() -> None:
    """plugins/ must not import from orchestrator.llm.providers.* (no LLM calls)."""
    violations: list[str] = []
    for py_path in _PLUGINS_PKG.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        source = py_path.read_text(encoding="utf-8")
        if "orchestrator.llm.providers" not in source:
            continue
        tree = ast.parse(source, filename=str(py_path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            module = ""
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module = alias.name
            elif node.module:
                module = node.module
            if module.startswith("orchestrator.llm.providers"):
                violations.append(f"  {py_path}: line {node.lineno}: imports {module!r}")
    assert not violations, "p2 guard: plugins/ imports llm providers:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# p3: No new LLMPurpose values (frozen set)
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


def test_p3_no_new_llm_purpose() -> None:
    """LLMPurpose enum must not gain new values beyond the frozen set (ADR-029 D3 / HR#4)."""
    from orchestrator.llm.purposes import LLMPurpose

    actual = frozenset(p.name for p in LLMPurpose)
    new_values = actual - _KNOWN_PURPOSES
    assert not new_values, (
        "p3 guard: new LLMPurpose values detected (require ADR + frozen-set update): "
        f"{sorted(new_values)}"
    )


# ---------------------------------------------------------------------------
# p4: select_model_and_provider absent from plugins/ (non-vacuous assert)
# ---------------------------------------------------------------------------


def test_p4_select_model_and_provider_absent() -> None:
    """plugins/ must not invoke select_model_and_provider (routing is code, ADR-002/023)."""
    symbol = "select_model_and_provider"
    found_in: list[str] = []
    for py_path in _PLUGINS_PKG.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        source = py_path.read_text(encoding="utf-8")
        if symbol in source:
            found_in.append(str(py_path))
    assert not found_in, f"p4 guard: {symbol!r} referenced in plugins/:\n" + "\n".join(
        f"  {p}" for p in found_in
    )
    # Non-vacuous: assert the symbol IS referenced in the codebase (agents/dispatch.py)
    # so the check has something to detect if it were introduced.
    router_py = _SRC / "llm" / "router.py"
    assert router_py.exists() and symbol in router_py.read_text(encoding="utf-8"), (
        f"p4 non-vacuous: {symbol!r} should exist in llm/router.py"
    )
