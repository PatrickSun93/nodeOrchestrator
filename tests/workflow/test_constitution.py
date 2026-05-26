"""Constitutional tests for the workflow module.

If a test here fails: do NOT fix the test. Investigate whether the
invariant is still valid. If it must change, write an ADR.
"""

from __future__ import annotations

from pathlib import Path

_WORKFLOW_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator" / "workflow"


def test_constitution_no_llm_calls_in_workflow_module() -> None:
    """src/orchestrator/workflow/ must never import any LLM SDK or call
    into orchestrator.llm.

    Per ADR-008 Decision 2 + Principle 3.1: state transitions are pure
    functions of (state, artifacts, gates). No LLM in the transition path.
    This test is vacuously passing today for new files; it becomes
    load-bearing the moment any code imports LLM dependencies.
    """
    forbidden_imports = {
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "from orchestrator.llm",
        "import orchestrator.llm",
    }

    violations: list[str] = []
    for py_path in _WORKFLOW_SRC.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        try:
            content = py_path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = py_path.relative_to(_WORKFLOW_SRC.parent.parent)
        for pattern in forbidden_imports:
            if pattern in content:
                violations.append(f"  {rel}: {pattern!r}")

    assert not violations, (
        "workflow module has LLM dependencies (ADR-008 Decision 2 + Principle 3.1 — "
        "state transitions must be pure code, no LLM calls):\n" + "\n".join(violations)
    )
