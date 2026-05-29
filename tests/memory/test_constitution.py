"""Constitutional test: memory/ must have no LLM imports.

Per ADR-016 Hard Requirements + handoff.md §3.1 (Principle 5):
promotion eligibility is code, not LLM judgment. No LLM SDK or
LLMRouter may be imported in src/orchestrator/memory/.

If this test fails: do NOT fix the test. Investigate whether the
invariant must change, then write an ADR.
"""

from __future__ import annotations

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
