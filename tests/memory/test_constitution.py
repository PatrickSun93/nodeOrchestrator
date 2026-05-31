"""Constitutional tests for memory/: no-LLM + matcher advisory orthogonality.

Per ADR-016 Hard Requirements + handoff.md §3.1 (Principle 5):
promotion eligibility is code, not LLM judgment. No LLM SDK or
LLMRouter may be imported in src/orchestrator/memory/.

Per ADR-017: the matcher is advisory-only — it must NOT call
promote_hypothesis, insert into verified_knowledge, or append events.
The orthogonality guard uses a real AST call/import check (B routing,
plan P2.2-4) rather than a whole-file substring scan, so the matcher's
own orthogonality docstring does NOT trip the guard.

If either test fails: do NOT fix the test. Investigate whether the
invariant must change, then write an ADR.
"""

from __future__ import annotations

import ast
from pathlib import Path

_MEMORY_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator" / "memory"


def test_constitution_no_llm_calls_in_memory_module() -> None:
    """src/orchestrator/memory/ must never import an LLM SDK or LLMRouter.

    Per ADR-016 Hard Requirements + handoff.md §3.1: memory/ is code-decided.
    Importing anthropic/openai SDKs or LLMRouter would make promotion
    eligibility LLM-dependent (violation of Principle 5 — code-driven decisions).

    Mirrors tests/derived/test_constitution.py shape verbatim.
    """
    forbidden_patterns = [
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "LLMRouter",
        "llm_router",
    ]

    violations: list[str] = []
    for py_path in _MEMORY_SRC.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        try:
            content = py_path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = py_path.relative_to(_MEMORY_SRC.parent.parent)
        for pattern in forbidden_patterns:
            if pattern in content:
                violations.append(f"  {rel}: {pattern!r}")

    assert not violations, (
        "orchestrator.memory imports LLM dependencies — constitutional violation.\n"
        "memory/ is code-decided (ADR-016 Hard Requirements, Principle 5);\n"
        "promotion eligibility must be pure code, no LLM:\n" + "\n".join(violations)
    )


def test_matcher_advisory_orthogonality_ast_guard() -> None:
    """matcher.py must NOT call promote_hypothesis, insert VK rows, or append events.

    Per ADR-017: the matcher is advisory-only. This guard checks the actual
    AST (call/import nodes), NOT the whole-file text — so the matcher's own
    orthogonality docstring does not trip it (B routing, plan P2.2-4).

    Forbidden in matcher.py:
      (a) import/from of 'promotion' module or 'promote_hypothesis'
      (b) Call/Attribute nodes named 'promote_hypothesis', 'append',
          'append_in_transaction'
      (c) String-literal SQL containing 'INSERT INTO verified_knowledge'
          (AST Constant nodes only — excludes comments and docstrings)
    """
    matcher_path = _MEMORY_SRC / "matcher.py"
    source = matcher_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(matcher_path))

    violations: list[str] = []

    for node in ast.walk(tree):
        # (a) forbidden imports.
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "promotion" in alias.name or alias.name == "promote_hypothesis":
                    violations.append(f"line {node.lineno}: forbidden import {alias.name!r}")
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if "promotion" in module:
                violations.append(f"line {node.lineno}: forbidden from-import from {module!r}")
            for alias in node.names:
                if alias.name == "promote_hypothesis":
                    violations.append(
                        f"line {node.lineno}: forbidden import of 'promote_hypothesis'"
                    )

        # (b) forbidden call/attribute names.
        if isinstance(node, ast.Name) and node.id in {
            "promote_hypothesis",
            "append_in_transaction",
        }:
            violations.append(f"line {node.lineno}: forbidden name reference {node.id!r}")
        if isinstance(node, ast.Attribute):
            # promote_hypothesis or append_in_transaction as any attribute.
            if node.attr in {"promote_hypothesis", "append_in_transaction"}:
                violations.append(f"line {node.lineno}: forbidden attribute .{node.attr}()")
            # event_store.append — specific EventStore append call.
            if (
                node.attr == "append"
                and isinstance(node.value, ast.Name)
                and ("event_store" in node.value.id or node.value.id == "store")
            ):
                violations.append(f"line {node.lineno}: forbidden event_store.append() call")

        # (c) string-literal SQL INSERT INTO verified_knowledge.
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "INSERT INTO verified_knowledge" in node.value
        ):
            violations.append(
                f"line {node.lineno}: forbidden SQL literal "
                f"'INSERT INTO verified_knowledge' in string constant"
            )

    assert not violations, (
        "matcher.py contains forbidden promotion/event-append references "
        "(ADR-017 advisory orthogonality violated):\n" + "\n".join(violations)
    )
