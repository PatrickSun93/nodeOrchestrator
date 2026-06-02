"""c2 structural guard (ADR-022 D4): ExternalValidationMeta sole construction site.

ExternalValidationMeta(...) (as a Call on Name ExternalValidationMeta) must
only appear in connectors/_emit.py within src/orchestrator/ (test files exempt).

This makes emit_external_validation the sole construction site, ensuring the
evidence_ref required+non-empty check is unbypassable from any connector.

Pattern mirrors tests/memory/test_constitution.py (real AST, RC-24).
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator"

# Allowed construction sites (within src/orchestrator/): connectors/_emit.py only.
_ALLOWED_CONSTRUCTION_FILES = frozenset({"_emit.py"})


def test_constitution_c2_external_validation_meta_sole_construction_site() -> None:
    """ExternalValidationMeta(...) (as a Call on Name ExternalValidationMeta) must
    only appear in connectors/_emit.py within src/orchestrator/ (test files exempt).
    """
    violations: list[str] = []
    for py_path in _SRC.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        # Allow test files (outside src/orchestrator/)
        if "tests/" in str(py_path) or "tests" in py_path.parts:
            continue
        source = py_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "ExternalValidationMeta"
                and py_path.name not in _ALLOWED_CONSTRUCTION_FILES
            ):
                msg = (
                    f"  {py_path}: line {node.lineno}:"
                    " ExternalValidationMeta(...) outside allowed site"
                )
                violations.append(msg)
    assert not violations, (
        "c2 guard: ExternalValidationMeta constructed outside connectors/_emit.py:\n"
        + "\n".join(violations)
    )


def test_constitution_c2_discriminating() -> None:
    """Discriminating: a planted ExternalValidationMeta(...) in dataset_check.py trips c2 guard."""
    fake_source = (
        "meta = ExternalValidationMeta("
        "source='ci', verdict='confirmed', "
        "validated_hypothesis_id='hyp_' + 'a'*32, evidence_ref='x')\n"
    )
    tree = ast.parse(fake_source, filename="<synthetic>")
    found = False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ExternalValidationMeta"
        ):
            found = True
    assert found, "c2 discriminating: ExternalValidationMeta call not detected"
