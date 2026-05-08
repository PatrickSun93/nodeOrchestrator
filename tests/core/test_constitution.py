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

import sqlite3
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from .conftest import PopulatedFixture


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
