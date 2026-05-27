"""Constitutional tests for the agents package.

If a test here fails: do NOT fix the test.  Investigate whether the
invariant is still valid.  If it must change, write an ADR.

Three invariants locked by ADR-011 Decision 5:
  1. No LLM SDK import inside src/orchestrator/agents/ — LLM calls go
     through LLMRouter, never direct SDK (anthropic / openai).
  2. orchestrator.core must not import from orchestrator.agents.
  3. orchestrator.skills must not import from orchestrator.agents.
"""

from __future__ import annotations

import ast
from pathlib import Path

_AGENTS_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator" / "agents"
_CORE_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator" / "core"
_SKILLS_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator" / "skills"


def test_constitution_no_llm_calls_in_agents_module() -> None:
    """src/orchestrator/agents/ must never import an LLM SDK directly.

    Per ADR-011 Decision 5 + Principle 3.1: agent dispatch decisions
    are code; LLM calls go through LLMRouter, not direct SDK.
    Importing ``orchestrator.llm.types`` / ``orchestrator.llm.purposes``
    / ``orchestrator.llm.router`` for type annotations and routing is
    allowed; importing the external anthropic or openai SDK packages
    directly is not.

    This test is vacuously passing at directory creation; it becomes
    load-bearing the moment any code imports the SDK directly.
    """
    forbidden_imports = {
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
    }

    violations: list[str] = []
    for py_path in _AGENTS_SRC.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        try:
            content = py_path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = py_path.relative_to(_AGENTS_SRC.parent.parent)
        for pattern in forbidden_imports:
            if pattern in content:
                violations.append(f"  {rel}: {pattern!r}")

    assert not violations, (
        "agents module has direct LLM SDK dependencies (ADR-011 Decision 5 + "
        "Principle 3.1 — LLM calls must go through LLMRouter, not direct SDK):\n"
        + "\n".join(violations)
    )


def test_constitution_core_does_not_import_agents() -> None:
    """src/orchestrator/core/ must never import from orchestrator.agents.

    Per ADR-011 Decision 5: the allowed direction is agents → core
    (agents consume EventType, RoomType, Event).  The reverse creates
    a circular dependency and violates the layering boundary.
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
                if module == "orchestrator.agents" or module.startswith("orchestrator.agents."):
                    violations.append(f"  {rel}: from {module} import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "orchestrator.agents" or alias.name.startswith(
                        "orchestrator.agents."
                    ):
                        violations.append(f"  {rel}: import {alias.name}")

    assert not violations, (
        "orchestrator.core imports from orchestrator.agents — layering violation.\n"
        "core → agents direction is forbidden (ADR-011 Decision 5):\n" + "\n".join(violations)
    )


def test_constitution_skills_does_not_import_agents() -> None:
    """src/orchestrator/skills/ must never import from orchestrator.agents.

    Per ADR-011 Decision 5: the allowed direction is agents → skills
    (agents call ``decide_skills_for_context``).  The reverse violates
    the layering boundary — skills are about content; agents are about
    gating; the wire is agents → skills, never reverse.
    """
    violations: list[str] = []
    for py_path in _SKILLS_SRC.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        try:
            tree = ast.parse(py_path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        rel = py_path.relative_to(_SKILLS_SRC.parent.parent)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "orchestrator.agents" or module.startswith("orchestrator.agents."):
                    violations.append(f"  {rel}: from {module} import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "orchestrator.agents" or alias.name.startswith(
                        "orchestrator.agents."
                    ):
                        violations.append(f"  {rel}: import {alias.name}")

    assert not violations, (
        "orchestrator.skills imports from orchestrator.agents — layering violation.\n"
        "skills → agents direction is forbidden (ADR-011 Decision 5):\n" + "\n".join(violations)
    )
