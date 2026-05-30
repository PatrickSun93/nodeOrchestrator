"""Tests for memory/tags.py — normalize_tag, resolve_tags, TagResolution.

Per plan P2.1-3 acceptance criteria (ADR-018 D3 + D4).
"""

from __future__ import annotations

import sqlite3

import pytest

from orchestrator.memory.store import init_memory_schema
from orchestrator.memory.tags import normalize_tag, resolve_tags

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


def _make_store_conn() -> sqlite3.Connection:
    """Connection with full memory schema (includes tag table)."""
    from orchestrator.core.event_store import EventStore

    conn = _make_conn()
    store = EventStore(conn)
    store.init_schema()
    init_memory_schema(conn)
    return conn


# ---------------------------------------------------------------------------
# normalize_tag — boundary tests (ADR-018 D3 AC#1)
# ---------------------------------------------------------------------------


class TestNormalizeTag:
    def test_llm_cost_becomes_llm_cost_canonical(self) -> None:
        assert normalize_tag("LLM Cost") == "llm-cost"

    def test_leading_trailing_whitespace_stripped(self) -> None:
        assert normalize_tag("  ML ") == "ml"

    def test_multiple_internal_spaces_collapsed_to_hyphen(self) -> None:
        assert normalize_tag("Foo  Bar") == "foo-bar"

    def test_already_canonical_is_idempotent(self) -> None:
        assert normalize_tag("llm-cost") == "llm-cost"

    def test_whitespace_only_becomes_empty(self) -> None:
        assert normalize_tag("   ") == ""

    def test_empty_string_becomes_empty(self) -> None:
        assert normalize_tag("") == ""

    def test_punctuation_preserved(self) -> None:
        # c++ must not collapse to c (ADR-018 D3 conservative rule).
        assert normalize_tag("C++") == "c++"

    def test_unicode_lower_not_casefold(self) -> None:
        # lower() keeps ß as ß; casefold() would turn it to ss.
        assert normalize_tag("HELLO") == "hello"
        # Verify we use lower(), not casefold() — normalize_tag("ß") must be "ß", not "ss".
        assert normalize_tag("ß") == "ß"

    # G3 near-miss edge cases — pinned so the canonical form is on the record.
    def test_hyphen_near_miss_whitespace_adjacent_to_hyphen(self) -> None:
        # "LLM - Cost" → strip → lower → whitespace runs become hyphens
        # each whitespace run becomes one hyphen, literal hyphen stays → "llm---cost"
        assert normalize_tag("LLM - Cost") == "llm---cost"

    def test_hyphen_near_miss_distinct_from_hyphenated(self) -> None:
        # "llm cost" and "llm-cost" are distinct canonical forms (not collapsed).
        assert normalize_tag("llm cost") == "llm-cost"
        # Note: "llm cost" → "llm-cost" and "llm-cost" → "llm-cost" are the SAME.
        # The near-miss is "llm cost" vs "llm-costs" (different normalization, different canonical).
        assert normalize_tag("llm-costs") == "llm-costs"
        assert normalize_tag("llm cost") != normalize_tag("llm-costs")


# ---------------------------------------------------------------------------
# resolve_tags — boundary and contract tests (ADR-018 D4 AC#2-6)
# ---------------------------------------------------------------------------


class TestResolveTags:
    def test_empty_proposed_returns_empty_resolution(self) -> None:
        conn = _make_store_conn()
        result = resolve_tags([], conn)
        assert result.canonical == []
        assert result.newly_registered == []

    def test_empty_normalizing_tag_raises_value_error(self) -> None:
        conn = _make_store_conn()
        with pytest.raises(ValueError, match="normalizes to empty string"):
            resolve_tags(["   "], conn)

    def test_empty_string_tag_raises_value_error(self) -> None:
        conn = _make_store_conn()
        with pytest.raises(ValueError, match="normalizes to empty string"):
            resolve_tags([""], conn)

    def test_new_tags_auto_registered(self) -> None:
        conn = _make_store_conn()
        with conn:
            result = resolve_tags(["LLM Cost", "ml"], conn)
        registered = {
            row["canonical"]
            for row in conn.execute("SELECT canonical FROM tag").fetchall()
        }
        assert "llm-cost" in registered
        assert "ml" in registered
        assert result.canonical == ["llm-cost", "ml"]
        assert set(result.newly_registered) == {"llm-cost", "ml"}

    def test_existing_tags_not_in_newly_registered(self) -> None:
        conn = _make_store_conn()
        with conn:
            resolve_tags(["llm-cost"], conn, now=1000)
        # Second call: tag already exists.
        with conn:
            result = resolve_tags(["llm-cost"], conn, now=2000)
        assert result.canonical == ["llm-cost"]
        assert result.newly_registered == []
        # created_at preserved from first registration.
        row = conn.execute("SELECT created_at FROM tag WHERE canonical = 'llm-cost'").fetchone()
        assert row["created_at"] == 1000

    def test_dedup_preserves_first_occurrence_order(self) -> None:
        conn = _make_store_conn()
        with conn:
            result = resolve_tags(["B tag", "A tag", "B tag", "C tag", "A tag"], conn)
        # Deduped: first occurrences in input order.
        assert result.canonical == ["b-tag", "a-tag", "c-tag"]

    def test_mixed_existing_and_new(self) -> None:
        conn = _make_store_conn()
        with conn:
            resolve_tags(["existing-tag"], conn, now=100)
        with conn:
            result = resolve_tags(["existing-tag", "new-tag"], conn)
        assert result.canonical == ["existing-tag", "new-tag"]
        assert result.newly_registered == ["new-tag"]

    def test_transaction_neutral_no_implicit_commit(self) -> None:
        """resolve_tags does NOT commit — caller owns the transaction (ADR-018 D4)."""
        conn = _make_store_conn()
        # Run resolve_tags WITHOUT committing.
        resolve_tags(["should-rollback"], conn)
        conn.rollback()
        count = conn.execute("SELECT COUNT(*) FROM tag").fetchone()[0]
        assert count == 0, "tag registration must roll back when caller rolls back"

    def test_idempotent_insert_same_tag_twice(self) -> None:
        """Concurrent-insert simulation: INSERT OR IGNORE for same tag is idempotent."""
        conn = _make_store_conn()
        with conn:
            r1 = resolve_tags(["llm-cost"], conn, now=1)
        with conn:
            r2 = resolve_tags(["llm-cost"], conn, now=2)
        assert r1.canonical == ["llm-cost"]
        assert r1.newly_registered == ["llm-cost"]
        assert r2.canonical == ["llm-cost"]
        assert r2.newly_registered == []
        rows = conn.execute("SELECT * FROM tag WHERE canonical = 'llm-cost'").fetchall()
        assert len(rows) == 1
        assert rows[0]["created_at"] == 1

    def test_determinism_same_input_same_output(self) -> None:
        """Same proposed list + same registry state → same canonical order (Principle 11)."""
        conn1 = _make_store_conn()
        conn2 = _make_store_conn()
        proposed = ["Tag C", "Tag A", "Tag B"]
        with conn1:
            r1 = resolve_tags(proposed, conn1)
        with conn2:
            r2 = resolve_tags(proposed, conn2)
        assert r1.canonical == r2.canonical
        assert r1.newly_registered == r2.newly_registered

    def test_normalizes_before_registering(self) -> None:
        """Tags are stored in canonical form, not raw form."""
        conn = _make_store_conn()
        with conn:
            result = resolve_tags(["  LLM Cost  ", "ML"], conn)
        assert result.canonical == ["llm-cost", "ml"]
        canonicals = {
            row["canonical"]
            for row in conn.execute("SELECT canonical FROM tag").fetchall()
        }
        assert "llm-cost" in canonicals
        assert "ml" in canonicals
        assert "LLM Cost" not in canonicals
