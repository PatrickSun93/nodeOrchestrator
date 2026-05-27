"""Constitutional tests for the rooms package (ADR-012 Decision 7).

Four layering invariants locked by ADR-012 D7:
  1. No LLM SDK import inside src/orchestrator/rooms/.
  2. orchestrator.core must not import from orchestrator.rooms.
  3. orchestrator.agents must not import from orchestrator.rooms.
  4. orchestrator.skills must not import from orchestrator.rooms.

If a test here fails: do NOT fix the test. Investigate whether the
invariant is still valid. If it must change, write an ADR amendment.
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOMS_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator" / "rooms"
_CORE_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator" / "core"
_AGENTS_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator" / "agents"
_SKILLS_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator" / "skills"


def test_constitution_no_llm_calls_in_rooms_module() -> None:
    """src/orchestrator/rooms/ must never import an LLM SDK directly.

    Per ADR-012 D7 + Principle 3.1: room state transitions are
    code-driven, not LLM-driven. Vacuously passing at directory
    creation; becomes load-bearing immediately on first rooms code.
    """
    forbidden_imports = {
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
    }

    violations: list[str] = []
    for py_path in _ROOMS_SRC.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        try:
            content = py_path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = py_path.relative_to(_ROOMS_SRC.parent.parent)
        for pattern in forbidden_imports:
            if pattern in content:
                violations.append(f"  {rel}: {pattern!r}")

    assert not violations, (
        "rooms module has direct LLM SDK imports (ADR-012 D7 + Principle 3.1 — "
        "state transitions must be code-driven, not LLM):\n" + "\n".join(violations)
    )


def _check_rooms_import(src_path: Path) -> list[str]:
    """Return import violations where files under src_path import orchestrator.rooms."""
    violations: list[str] = []
    for py_path in src_path.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        try:
            tree = ast.parse(py_path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        rel = py_path.relative_to(src_path.parent.parent)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "orchestrator.rooms" or module.startswith("orchestrator.rooms."):
                    violations.append(f"  {rel}: from {module} import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "orchestrator.rooms" or alias.name.startswith(
                        "orchestrator.rooms."
                    ):
                        violations.append(f"  {rel}: import {alias.name}")
    return violations


def test_constitution_core_does_not_import_rooms() -> None:
    """src/orchestrator/core/ must never import from orchestrator.rooms.

    Per ADR-012 D7: core stays agent-/room-/skill-agnostic.
    The allowed direction is rooms → core; the reverse is forbidden.
    """
    violations = _check_rooms_import(_CORE_SRC)
    assert not violations, (
        "orchestrator.core imports from orchestrator.rooms — layering violation.\n"
        "core → rooms direction is forbidden (ADR-012 D7):\n" + "\n".join(violations)
    )


def test_constitution_agents_does_not_import_rooms() -> None:
    """src/orchestrator/agents/ must never import from orchestrator.rooms.

    Per ADR-012 D7: rooms → agents is the allowed direction; the
    reverse would invert the layering boundary.
    """
    violations = _check_rooms_import(_AGENTS_SRC)
    assert not violations, (
        "orchestrator.agents imports from orchestrator.rooms — layering violation.\n"
        "agents → rooms direction is forbidden (ADR-012 D7):\n" + "\n".join(violations)
    )


def test_constitution_skills_does_not_import_rooms() -> None:
    """src/orchestrator/skills/ must never import from orchestrator.rooms.

    Per ADR-012 D7: skills are content; rooms are orchestration.
    The wire flows rooms → agents → skills, never rooms ← skills.
    """
    violations = _check_rooms_import(_SKILLS_SRC)
    assert not violations, (
        "orchestrator.skills imports from orchestrator.rooms — layering violation.\n"
        "skills → rooms direction is forbidden (ADR-012 D7):\n" + "\n".join(violations)
    )
