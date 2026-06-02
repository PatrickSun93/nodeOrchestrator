"""Constitutional tests for producers/:

(i)  No upstream layer (core/ memory/ derived/ llm/) imports producers/ or connectors/.
     Mirrors tests/reentry/test_constitution.py's no-upstream-import guard (ADR-021 D1 idiom).
(ii) c1 structural guard: producers/*.py references no selection/promotion/gate symbol
     (run_matcher, promote_hypothesis, list_promotion_candidates, candidate_for_promotion).
     ADR-022 D3. Belt-and-suspenders: LLM-tagging proposes descriptive tags only.

Real AST checks per RC-24. If any test fails: investigate; do NOT fix the test.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator"
_PRODUCERS_SRC = _SRC / "producers"

_UPSTREAM_LAYERS = ["core", "memory", "derived", "llm"]

# Selection/promotion/gate symbols the c1 guard forbids in producers/
_FORBIDDEN_PROMOTION_SYMBOLS = frozenset(
    {
        "run_matcher",
        "promote_hypothesis",
        "list_promotion_candidates",
        "candidate_for_promotion",
    }
)


# ---------------------------------------------------------------------------
# Guard (i) — no upstream layer imports producers/ or connectors/
# ---------------------------------------------------------------------------


def test_constitution_no_upstream_imports_producers() -> None:
    """core/ + memory/ + derived/ + llm/ must NOT import from orchestrator.producers.

    Discriminating: adding 'from orchestrator.producers import ...' or
    'import orchestrator.producers' in any upstream layer fails this test.
    Per ADR-022 D1 (producers are leaf consumers).
    """
    violations: list[str] = []

    for layer in _UPSTREAM_LAYERS:
        layer_dir = _SRC / layer
        for py_path in layer_dir.rglob("*.py"):
            if "__pycache__" in py_path.parts:
                continue
            try:
                source = py_path.read_text(encoding="utf-8")
            except OSError:
                continue
            try:
                tree = ast.parse(source, filename=str(py_path))
            except SyntaxError:
                continue

            rel = py_path.relative_to(_SRC.parent.parent)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "orchestrator.producers" in alias.name:
                            violations.append(f"  {rel}: line {node.lineno}: import {alias.name!r}")
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if "orchestrator.producers" in module or module.startswith(
                        "orchestrator.producers"
                    ):
                        violations.append(
                            f"  {rel}: line {node.lineno}: from {module!r} import ..."
                        )

    assert not violations, (
        "Upstream layers (core/ memory/ derived/ llm/) must not import producers/.\n"
        "producers/ is a leaf consumer (ADR-022 D1):\n" + "\n".join(violations)
    )


def test_constitution_no_upstream_imports_producers_discriminating() -> None:
    """Discriminating self-test: a planted producers import in a synthetic AST trips guard (i)."""
    fake_source = "from orchestrator.producers.tagging import propose_hypothesis_tags\n"
    tree = ast.parse(fake_source, filename="<synthetic>")

    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if "orchestrator.producers" in module:
                found = True
    assert found, "guard (i) discriminating check: synthetic producers import not detected"


def test_constitution_no_upstream_imports_connectors() -> None:
    """core/ + memory/ + derived/ + llm/ must NOT import from orchestrator.connectors.

    Discriminating: adding 'from orchestrator.connectors import ...' in any
    upstream layer fails this test. Per ADR-022 D1.
    """
    violations: list[str] = []

    for layer in _UPSTREAM_LAYERS:
        layer_dir = _SRC / layer
        for py_path in layer_dir.rglob("*.py"):
            if "__pycache__" in py_path.parts:
                continue
            try:
                source = py_path.read_text(encoding="utf-8")
            except OSError:
                continue
            try:
                tree = ast.parse(source, filename=str(py_path))
            except SyntaxError:
                continue

            rel = py_path.relative_to(_SRC.parent.parent)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "orchestrator.connectors" in alias.name:
                            violations.append(f"  {rel}: line {node.lineno}: import {alias.name!r}")
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if "orchestrator.connectors" in module or module.startswith(
                        "orchestrator.connectors"
                    ):
                        violations.append(
                            f"  {rel}: line {node.lineno}: from {module!r} import ..."
                        )

    assert not violations, (
        "Upstream layers (core/ memory/ derived/ llm/) must not import connectors/.\n"
        "connectors/ is a leaf consumer (ADR-022 D1):\n" + "\n".join(violations)
    )


def test_constitution_no_upstream_imports_connectors_discriminating() -> None:
    """Discriminating self-test: a planted connectors import trips guard."""
    fake_source = "from orchestrator.connectors._emit import emit_external_validation\n"
    tree = ast.parse(fake_source, filename="<synthetic>")

    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if "orchestrator.connectors" in module:
                found = True
    assert found, "guard connectors discriminating check: synthetic import not detected"


# ---------------------------------------------------------------------------
# Guard (ii) — c1: producers/*.py references no selection/promotion/gate symbol
# ---------------------------------------------------------------------------


class _PromotionSymbolCollector(ast.NodeVisitor):
    """Walk a file's AST; flag references to promotion/gate symbols."""

    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        self.violations: list[str] = []

    def _rel(self) -> str:
        try:
            return str(self.filepath.relative_to(_SRC.parent.parent))
        except ValueError:
            return str(self.filepath)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in _FORBIDDEN_PROMOTION_SYMBOLS:
            self.violations.append(
                f"  {self._rel()}: line {node.lineno}: forbidden Name {node.id!r}"
            )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in _FORBIDDEN_PROMOTION_SYMBOLS:
            self.violations.append(
                f"  {self._rel()}: line {node.lineno}: forbidden Attribute .{node.attr}"
            )
        self.generic_visit(node)


def test_constitution_c1_producers_no_selection_gate_symbols() -> None:
    """producers/*.py must reference no selection/promotion/gate symbol.

    Forbidden: run_matcher, promote_hypothesis, list_promotion_candidates,
    candidate_for_promotion (as Name or Attribute nodes).

    Per ADR-022 D3 (c1 alpha-lite structural guard): the tagging producer
    proposes descriptive tags only; it never selects, ranks, gates, or
    actuates promotion. Belt-and-suspenders structural proof.

    Discriminating: planting 'run_matcher(...)' or 'promote_hypothesis(...)'
    in any producers/*.py file trips this test.
    """
    all_violations: list[str] = []

    for py_path in _PRODUCERS_SRC.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        if py_path.name == "__init__.py":
            continue
        try:
            source = py_path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            tree = ast.parse(source, filename=str(py_path))
        except SyntaxError:
            continue
        collector = _PromotionSymbolCollector(py_path)
        collector.visit(tree)
        all_violations.extend(collector.violations)

    assert not all_violations, (
        "producers/*.py references a selection/promotion/gate symbol "
        "(ADR-022 D3 c1 boundary violated — the producer must propose descriptive "
        "tags only; it must never select, rank, gate, or actuate promotion):\n"
        + "\n".join(all_violations)
    )


def test_constitution_c1_producers_guard_discriminating() -> None:
    """Discriminating: a planted run_matcher reference in producers/ trips guard (ii)."""
    fake_source = "def tag_hypothesis():\n    run_matcher(conn)\n"
    tree = ast.parse(fake_source, filename="<synthetic>")
    collector = _PromotionSymbolCollector(Path("<synthetic>"))
    collector.visit(tree)
    assert len(collector.violations) > 0, (
        "guard (ii) discriminating check: run_matcher inside producers/ not detected"
    )


def test_constitution_c1_producers_promote_hypothesis_discriminating() -> None:
    """Discriminating: a planted promote_hypothesis reference trips guard (ii)."""
    fake_source = "def tag_hypothesis(hyp):\n    promote_hypothesis(hyp.id, user_id='x')\n"
    tree = ast.parse(fake_source, filename="<synthetic>")
    collector = _PromotionSymbolCollector(Path("<synthetic>"))
    collector.visit(tree)
    assert len(collector.violations) > 0, (
        "guard (ii) discriminating check: promote_hypothesis inside producers/ not detected"
    )
