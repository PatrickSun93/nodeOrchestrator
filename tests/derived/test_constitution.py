"""Constitutional test: derived/ must have no LLM imports.

Snapshot and decision-log derivations are code-decided per Principle 5.
ADR-014 D1 + ADR-015 D1 lock purity. If this test fails, do NOT fix the
test — investigate whether the invariant must change, then write an ADR.
"""

from __future__ import annotations

from pathlib import Path

_DERIVED_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator" / "derived"


def test_constitution_no_llm_calls_in_derived_module() -> None:
    """src/orchestrator/derived/ must never import an LLM SDK or LLMRouter.

    Per ADR-014 D1 + ADR-015 D1: derived views are pure code derivations.
    Importing anthropic/openai SDKs or LLMRouter would make them impure
    (LLM-calls are content-generation; snapshot/decision-log are code-decided).

    This test matches the agents constitutional test pattern.
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
    for py_path in _DERIVED_SRC.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        try:
            content = py_path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = py_path.relative_to(_DERIVED_SRC.parent.parent)
        for pattern in forbidden_patterns:
            if pattern in content:
                violations.append(f"  {rel}: {pattern!r}")

    assert not violations, (
        "orchestrator.derived imports LLM dependencies — constitutional violation.\n"
        "derived/ is code-decided (ADR-014 D1, ADR-015 D1, Principle 5);\n"
        "snapshot and decision-log must be pure code, no LLM:\n" + "\n".join(violations)
    )


def test_constitution_derived_does_not_import_memory() -> None:
    """src/orchestrator/derived/ must never import from orchestrator.memory.

    Per ADR-016 Hard Requirements: derived/ contains pure-function derivations
    over the event stream (ADR-014 D1, ADR-015 D1). Importing memory/
    would make derived views depend on memory state rather than pure event
    derivation, violating the derive-don't-materialize principle (ADR-015 D5).
    """
    forbidden_patterns = ["from orchestrator.memory", "import orchestrator.memory"]
    violations: list[str] = []
    for py_path in _DERIVED_SRC.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        try:
            content = py_path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = py_path.relative_to(_DERIVED_SRC.parent.parent)
        for pattern in forbidden_patterns:
            if pattern in content:
                violations.append(f"  {rel}: {pattern!r}")

    assert not violations, (
        "orchestrator.derived imports from orchestrator.memory — layering violation.\n"
        "derived → memory direction is forbidden (ADR-016 Hard Requirements):\n"
        + "\n".join(violations)
    )
