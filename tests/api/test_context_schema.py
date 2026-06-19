"""P8-2: assert the factory DB (ctx fixture) contains the full production schema set.

Regression guard: _build_context + ctx fixture must initialize memory + reentry
tables alongside the existing event/auth/pipeline tables (ADR-016 D5 / ADR-021 D5).
"""

from __future__ import annotations

import sqlite3

from orchestrator.api.app import AppContext


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


class TestContextSchema:
    def test_memory_tables_present(self, ctx: AppContext) -> None:
        """hypothesis + verified_knowledge tables are initialized by the ctx fixture."""
        tables = _table_names(ctx.writer_store.conn)
        assert "hypothesis" in tables, f"hypothesis missing; got {sorted(tables)}"
        assert "verified_knowledge" in tables, f"verified_knowledge missing; got {sorted(tables)}"

    def test_reentry_table_present(self, ctx: AppContext) -> None:
        """reentry_marker table is initialized by the ctx fixture."""
        tables = _table_names(ctx.writer_store.conn)
        assert "reentry_marker" in tables, f"reentry_marker missing; got {sorted(tables)}"

    def test_double_init_is_idempotent(self, ctx: AppContext) -> None:
        """A second call to init_memory_schema + init_reentry_schema does not raise."""
        from orchestrator.memory.store import init_memory_schema
        from orchestrator.reentry.store import init_reentry_schema

        init_memory_schema(ctx.writer_store.conn)
        init_reentry_schema(ctx.writer_store.conn)
        tables = _table_names(ctx.writer_store.conn)
        assert "hypothesis" in tables
        assert "reentry_marker" in tables
