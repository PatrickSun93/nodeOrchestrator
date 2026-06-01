"""Constitutional tests for reentry/:
  (i) No upstream layer (core/ memory/ derived/ llm/) imports reentry/.
  (ii) Named selection functions (assemble_reentry, derive_query_tags, and the
       new_since_leave diff) reference no LLMRequest/llm_router/.call(
       — wherever they live. Per ADR-021 D1/D3/D6 (Y2 + Y1-fix absorbed).

Real AST checks (not substring scans) per RC-24. Mirror the idiom in
tests/memory/test_constitution.py and tests/derived/test_constitution.py.

If any test fails: do NOT fix the test. Investigate whether the invariant
must change, then write an ADR.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator"
_REENTRY_SRC = _SRC / "reentry"

# Upstream layers that must NOT import reentry/ (ADR-021 D1, Y2 absorbed).
_UPSTREAM_LAYERS = ["core", "memory", "derived", "llm"]

# Named selection functions guarded by (ii) (ADR-021 D6, Y1-fix absorbed).
# The diff loop is inside assemble_reentry, so it is covered by that name.
_SELECTION_FUNS = frozenset({"assemble_reentry", "derive_query_tags"})

# LLM-related symbols that must NOT appear inside the selection functions.
_FORBIDDEN_LLM_SYMBOLS = frozenset({"LLMRequest", "llm_router", "LLMRouterProtocol"})


# ---------------------------------------------------------------------------
# Guard (i) — no upstream layer imports reentry/
# ---------------------------------------------------------------------------


def test_constitution_no_upstream_imports_reentry() -> None:
    """core/ + memory/ + derived/ + llm/ must NOT import from orchestrator.reentry.

    Discriminating: adding 'from orchestrator.reentry import ...' or
    'import orchestrator.reentry' in any of those layers fails this test.
    Per ADR-021 D1 (Y2 absorbed — all four upstream layers covered).
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
                        if "orchestrator.reentry" in alias.name:
                            violations.append(
                                f"  {rel}: line {node.lineno}: "
                                f"import {alias.name!r}"
                            )
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if "orchestrator.reentry" in module or module.startswith(
                        "orchestrator.reentry"
                    ):
                        violations.append(
                            f"  {rel}: line {node.lineno}: "
                            f"from {module!r} import ..."
                        )

    assert not violations, (
        "Upstream layers (core/ memory/ derived/ llm/) must not import reentry/.\n"
        "reentry/ is the leaf consumer (ADR-021 D1, Y2 absorbed):\n"
        + "\n".join(violations)
    )


def test_constitution_no_upstream_imports_reentry_discriminating() -> None:
    """Discriminating self-test: planting a reentry import in a temp file would trip guard (i).

    This test verifies the guard logic by running it on a synthetic AST containing
    a forbidden import, confirming the violation is detected.
    """
    fake_source = "from orchestrator.reentry.digest import assemble_reentry\n"
    tree = ast.parse(fake_source, filename="<synthetic>")

    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if "orchestrator.reentry" in module:
                found = True
    assert found, "guard (i) discriminating check: synthetic reentry import not detected"


# ---------------------------------------------------------------------------
# Guard (ii) — named selection functions are LLM-free (ADR-021 D6, Y1-fix)
# ---------------------------------------------------------------------------


class _SelectionFunLLMCollector(ast.NodeVisitor):
    """Walk a file's AST; for each named selection function, flag LLM references."""

    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        self._fn_stack: list[str] = []
        self.violations: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._fn_stack.append(node.name)
        self.generic_visit(node)
        self._fn_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._fn_stack.append(node.name)
        self.generic_visit(node)
        self._fn_stack.pop()

    def _in_selection_fn(self) -> bool:
        return bool(self._fn_stack) and self._fn_stack[-1] in _SELECTION_FUNS

    def _rel(self) -> str:
        try:
            return str(self.filepath.relative_to(_SRC.parent.parent))
        except ValueError:
            return str(self.filepath)

    def visit_Name(self, node: ast.Name) -> None:
        if self._in_selection_fn() and node.id in _FORBIDDEN_LLM_SYMBOLS:
            self.violations.append(
                f"  {self._rel()}: "
                f"line {node.lineno}: forbidden Name {node.id!r} in "
                f"selection fn {self._fn_stack[-1]!r}"
            )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if self._in_selection_fn() and node.attr in _FORBIDDEN_LLM_SYMBOLS:
            self.violations.append(
                f"  {self._rel()}: "
                f"line {node.lineno}: forbidden Attribute .{node.attr} in "
                f"selection fn {self._fn_stack[-1]!r}"
            )
        self.generic_visit(node)


def test_constitution_selection_functions_are_llm_free() -> None:
    """assemble_reentry + derive_query_tags must reference no LLMRequest/llm_router.

    Keyed by named function (not by file), so leave.py's legitimate
    ARCHIVE_SUMMARY_RENDER call is not false-tripped, and derive_query_tags
    stays protected if it moves. Per ADR-021 D6 (Y1-fix absorbed).

    Discriminating: planting 'llm_router.call(...)' inside assemble_reentry
    or derive_query_tags in any reentry/ file would fail this test.
    """
    all_violations: list[str] = []
    for py_path in _REENTRY_SRC.rglob("*.py"):
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
        collector = _SelectionFunLLMCollector(py_path)
        collector.visit(tree)
        all_violations.extend(collector.violations)

    assert not all_violations, (
        "Selection functions (assemble_reentry, derive_query_tags) must be LLM-free "
        "(ADR-021 D6, Principle 11). LLM use is confined to render_reentry_prose "
        "and the leave-time archive-summary render:\n" + "\n".join(all_violations)
    )


def test_constitution_selection_functions_llm_free_discriminating() -> None:
    """Discriminating: a planted LLMRequest reference inside assemble_reentry trips guard (ii).

    Verifies the visitor logic catches a forbidden symbol inside the named function.
    """
    fake_source = (
        "def assemble_reentry():\n"
        "    req = LLMRequest(purpose='x')\n"
        "    return req\n"
    )
    tree = ast.parse(fake_source, filename="<synthetic>")
    collector = _SelectionFunLLMCollector(Path("<synthetic>"))
    collector.visit(tree)
    assert len(collector.violations) > 0, (
        "guard (ii) discriminating check: LLMRequest inside assemble_reentry not detected"
    )


def test_constitution_legitimate_render_calls_not_tripped() -> None:
    """leave.py's ARCHIVE_SUMMARY_RENDER call and render.py's REENTRY_DIGEST_RENDER
    call are NOT inside assemble_reentry or derive_query_tags — they must NOT trip guard (ii).

    Verifies the guard is function-scoped, not file-scoped.
    """
    fake_source = (
        "def assemble_reentry():\n"
        "    return 42\n"
        "\n"
        "def render_reentry_prose(digest, *, llm_router):\n"
        "    req = LLMRequest(purpose='render')\n"
        "    return llm_router.call(req)\n"
    )
    tree = ast.parse(fake_source, filename="<synthetic>")
    collector = _SelectionFunLLMCollector(Path("<synthetic>"))
    collector.visit(tree)
    assert len(collector.violations) == 0, (
        "guard (ii) must not trip legitimate render calls outside selection functions: "
        + str(collector.violations)
    )
