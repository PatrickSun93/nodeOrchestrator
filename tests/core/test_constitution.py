"""Constitutional tests: invariants the system depends on at the deepest level.

These tests are guardrails. If a future PR breaks one, the test fails
and forces the contributor to think about whether they're really
violating an architectural invariant — or whether the invariant itself
needs an ADR to change.

Each test name starts with ``test_constitution_`` to flag it as
load-bearing. Test names should describe the invariant in plain words.

This file establishes the precedent. Future constitutional tests
(persona immutability, agent cannot create tools, etc.) follow the
same naming and live alongside this one.

If a constitutional test fails: do NOT "fix the test". Investigate
whether the invariant is still valid. If it must change, write an
ADR documenting why.
"""

from __future__ import annotations

import ast
import sqlite3
import typing
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from orchestrator.autonomy.scoring import DecisionTrace
from orchestrator.core.event import AutonomyDecisionMetadata, AutonomyRefusalMetadata

if TYPE_CHECKING:
    from .conftest import PopulatedFixture


def test_constitution_autonomy_decision_event_carries_trace() -> None:
    """``AutonomyDecisionMetadata`` field set must stay in sync with
    ``DecisionTrace``: every ``DecisionTrace`` field appears in the
    metadata (with ``tool_id`` renamed to ``operation_tool_id``), plus
    exactly two event-only additions (``operation_initiating_agent``
    and ``score``).

    Why: the event log is the audit record of every gate decision.
    If ``DecisionTrace`` gains a field but the metadata schema does
    not, that field is permanently absent from every future event
    record — unreplayable. The sync relationship is enforced here
    rather than by runtime code so that drift cannot accumulate
    silently across commits.

    Fails loudly on missing OR extra fields so a reader can locate
    the exact discrepancy without re-running the scorer.
    """
    trace_fields = set(DecisionTrace.model_fields)

    # Rename tool_id → operation_tool_id (event-layer naming convention).
    expected = (trace_fields - {"tool_id"}) | {"operation_tool_id"}

    # Two event-only additions; tier and user_explicit_intent are
    # already present from DecisionTrace so union is idempotent for them.
    expected |= {"operation_initiating_agent", "score", "tier", "user_explicit_intent"}

    actual = set(AutonomyDecisionMetadata.model_fields)

    missing = expected - actual
    extra = actual - expected

    assert not missing and not extra, (
        "AutonomyDecisionMetadata is out of sync with DecisionTrace.\n"
        f"Fields missing from AutonomyDecisionMetadata: {sorted(missing)}\n"
        f"Fields in AutonomyDecisionMetadata not in expected set: {sorted(extra)}\n"
        "Fix: update AutonomyDecisionMetadata in orchestrator/core/event.py to "
        "match the DecisionTrace shape in orchestrator/autonomy/scoring.py."
    )

    # R0-A item #4: the `rule` Literal annotation must stay in sync across
    # both classes. A divergence would mean the event log accepts rule values
    # the scorer never produces, or vice versa — silent spec drift.
    trace_rule_hint = typing.get_type_hints(DecisionTrace)["rule"]
    meta_rule_hint = typing.get_type_hints(AutonomyDecisionMetadata)["rule"]
    assert trace_rule_hint == meta_rule_hint, (
        "rule Literal annotation mismatch between DecisionTrace and AutonomyDecisionMetadata.\n"
        f"DecisionTrace.rule: {trace_rule_hint}\n"
        f"AutonomyDecisionMetadata.rule: {meta_rule_hint}\n"
        "Fix: update the rule Literal in one of the two classes so both share the same values."
    )


def test_constitution_autonomy_refusal_metadata_field_set() -> None:
    """``AutonomyRefusalMetadata`` field set must stay exactly four fields.

    The four fields are: ``operation_tool_id``, ``operation_initiating_agent``,
    ``user_explicit_intent``, ``refusal_reason``. Adding or removing a field
    changes the audit contract for every future ``autonomy_refusal`` event.

    The ``refusal_reason`` Literal currently accepts only ``"unknown_tool"``.
    P1.3 Hard Guards will extend it via ADR amendment; this test asserts
    the amendment is made explicitly rather than by accident (any change
    to the Literal will require updating the expected set below).

    Fails loudly on missing OR extra fields so a reader can locate the
    exact discrepancy without querying the event log.
    """
    expected = {
        "operation_tool_id",
        "operation_initiating_agent",
        "user_explicit_intent",
        "refusal_reason",
    }
    actual = set(AutonomyRefusalMetadata.model_fields)

    missing = expected - actual
    extra = actual - expected

    assert not missing and not extra, (
        "AutonomyRefusalMetadata field set has drifted.\n"
        f"Missing fields: {sorted(missing)}\n"
        f"Extra fields: {sorted(extra)}\n"
        "Fix: update AutonomyRefusalMetadata in orchestrator/core/event.py "
        "and update this test's expected set to match. "
        "Any field change is an ADR-007 amendment."
    )

    # Negative-case: refusal_reason rejects values that are not in the
    # Literal. A future Literal extension (P1.3 Hard Guards) will need
    # to update this assertion explicitly, ensuring the change is
    # deliberate and traceable.
    with pytest.raises(ValidationError):
        AutonomyRefusalMetadata(
            operation_tool_id="t",
            operation_initiating_agent="agent:x",
            user_explicit_intent=False,
            refusal_reason="not_a_valid_reason",  # type: ignore[arg-type]
        )


def test_constitution_append_only_at_schema_level(
    populated_event_store: PopulatedFixture,
) -> None:
    """Direct SQL UPDATE/DELETE against ``events`` must raise IntegrityError.

    This guarantees that even if a future contributor bypasses the
    EventStore API to issue raw SQL (e.g. for "just this one fix"),
    the schema-level TRIGGERs catch them. Three layers of defense
    (TRIGGER, Pydantic frozen, no-update API) — this test verifies
    the deepest layer.

    The test exercises every shape of mutation we can think of:

    - UPDATE on the column most likely to be tampered with (``content``).
    - UPDATE on a non-content column (``timestamp``) — append-only is
      field-level, not just row-level.
    - Single-row DELETE.
    - Bulk UPDATE without WHERE (mass tampering).
    - Bulk DELETE without WHERE (table wipe).
    """
    store, ids = populated_event_store

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.conn.execute(
            "UPDATE events SET content = 'tampered' WHERE id = ?",
            (ids["utterance"],),
        )

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.conn.execute(
            "UPDATE events SET timestamp = 0 WHERE id = ?",
            (ids["utterance"],),
        )

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.conn.execute(
            "DELETE FROM events WHERE id = ?",
            (ids["utterance"],),
        )

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.conn.execute("UPDATE events SET content = 'mass tamper'")

    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store.conn.execute("DELETE FROM events")


_CORE_SRC = Path(__file__).resolve().parent.parent.parent / "src" / "orchestrator" / "core"


def test_constitution_core_does_not_import_autonomy() -> None:
    """``src/orchestrator/core/`` must never import from ``orchestrator.autonomy``.

    Why: the autonomy module imports from core (first sanctioned edge, C4-5).
    The reverse direction creates a circular dependency and violates the
    deliberate-duplication layering rule documented in
    ``orchestrator/core/event.py:209-211``. If core ever imports autonomy,
    the layering boundary collapses silently.

    Uses AST-level import walking so string-matching can't be fooled by
    comments or docstrings.
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
                if module == "orchestrator.autonomy" or module.startswith("orchestrator.autonomy."):
                    violations.append(f"  {rel}: from {module} import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "orchestrator.autonomy" or alias.name.startswith(
                        "orchestrator.autonomy."
                    ):
                        violations.append(f"  {rel}: import {alias.name}")

    assert not violations, (
        "orchestrator.core imports from orchestrator.autonomy — layering violation.\n"
        "core → autonomy direction is forbidden (see event.py:209-211):\n" + "\n".join(violations)
    )


def test_constitution_core_does_not_import_memory() -> None:
    """``src/orchestrator/core/`` must never import from ``orchestrator.memory``.

    Per ADR-016 D8 deliberate-duplication rule (ADR-014 D5 precedent):
    core/event.py uses ``str | None`` for hypothesis_id/vk_id instead of
    HypothesisId/VKId NewTypes, precisely to avoid this import. If core
    ever imports memory, the layering boundary collapses and the
    constitutional no-auto-promote invariant is weakened.
    """
    forbidden_patterns = ["from orchestrator.memory", "import orchestrator.memory"]
    violations: list[str] = []
    for py_path in _CORE_SRC.rglob("*.py"):
        if "__pycache__" in py_path.parts:
            continue
        try:
            content = py_path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = py_path.relative_to(_CORE_SRC.parent.parent)
        for pattern in forbidden_patterns:
            if pattern in content:
                violations.append(f"  {rel}: {pattern!r}")

    assert not violations, (
        "orchestrator.core imports from orchestrator.memory — layering violation.\n"
        "core → memory direction is forbidden (ADR-016 D8 deliberate-duplication):\n"
        + "\n".join(violations)
    )
