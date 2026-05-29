"""Constitutional tests for the skills module.

If a test here fails: do NOT fix the test. Investigate whether the
invariant is still valid. If it must change, write an ADR.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SKILLS_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator" / "skills"
_CORE_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator" / "core"


def test_constitution_no_llm_calls_in_skills_module() -> None:
    """src/orchestrator/skills/ must never import any LLM SDK or call into
    orchestrator.llm.

    Per ADR-009 Decision 7 + Principle 3.1: skill loading and matching are
    pure code; no LLM call anywhere in the skills package. This test is
    vacuously passing at directory creation; it becomes load-bearing the
    moment any code imports LLM dependencies.
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
    for py_path in _SKILLS_SRC.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        try:
            content = py_path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = py_path.relative_to(_SKILLS_SRC.parent.parent)
        for pattern in forbidden_imports:
            if pattern in content:
                violations.append(f"  {rel}: {pattern!r}")

    assert not violations, (
        "skills module has LLM dependencies (ADR-009 Decision 7 + Principle 3.1 — "
        "skill loading and matching must be pure code, no LLM calls):\n" + "\n".join(violations)
    )


def test_constitution_core_does_not_import_skills() -> None:
    """src/orchestrator/core/ must never import from orchestrator.skills.

    Per ADR-009 Decision 7: the allowed direction is skills → core (skills
    consumes RoomType). The reverse creates a circular dependency and violates
    the layering boundary. This test follows the test_constitution_core_does_not_import_autonomy
    precedent from tests/core/test_constitution.py (W-001-impl Y1 pattern).
    """
    violations: list[str] = []
    for py_path in _CORE_SRC.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        try:
            tree = ast.parse(py_path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        rel = py_path.relative_to(_CORE_SRC.parent.parent)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "orchestrator.skills" or module.startswith("orchestrator.skills."):
                    violations.append(f"  {rel}: from {module} import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "orchestrator.skills" or alias.name.startswith(
                        "orchestrator.skills."
                    ):
                        violations.append(f"  {rel}: import {alias.name}")

    assert not violations, (
        "orchestrator.core imports from orchestrator.skills — layering violation.\n"
        "core → skills direction is forbidden (ADR-009 Decision 7):\n" + "\n".join(violations)
    )


def test_constitution_skills_does_not_import_memory() -> None:
    """src/orchestrator/skills/ must never import from orchestrator.memory.

    Per ADR-016 Hard Requirements: skills are content-generation utilities.
    A skills → memory import would couple content generation to cross-room
    memory state, creating a hidden dependency that the architecture
    explicitly forbids.
    """
    forbidden_patterns = ["from orchestrator.memory", "import orchestrator.memory"]
    violations: list[str] = []
    for py_path in _SKILLS_SRC.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        try:
            content = py_path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = py_path.relative_to(_SKILLS_SRC.parent.parent)
        for pattern in forbidden_patterns:
            if pattern in content:
                violations.append(f"  {rel}: {pattern!r}")

    assert not violations, (
        "orchestrator.skills imports from orchestrator.memory — layering violation.\n"
        "skills → memory direction is forbidden (ADR-016 Hard Requirements):\n"
        + "\n".join(violations)
    )
