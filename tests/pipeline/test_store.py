"""Tests for pipeline/store.py — schema, CRUD, round-trips (ADR-041 D8)."""

from __future__ import annotations

import sqlite3

from orchestrator.pipeline.schema import OutputConfig, PipelineDefinition
from orchestrator.pipeline.store import (
    PIPELINE_SCHEMA,
    create_pipeline,
    create_pipeline_run,
    get_pipeline,
    init_pipeline_schema,
    list_pipelines,
    update_pipeline_run_status,
)
from orchestrator.sources.schema import Source


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    init_pipeline_schema(conn)
    return conn


def _sample_definition() -> PipelineDefinition:
    return PipelineDefinition(
        sources=[Source(kind="web", locator="https://example.com/data")],
        analysis_prompts=["Summarize the content"],
        output_config=OutputConfig(),
    )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_init_pipeline_schema_idempotent() -> None:
    """init_pipeline_schema is idempotent (CREATE TABLE IF NOT EXISTS)."""
    conn = sqlite3.connect(":memory:")
    init_pipeline_schema(conn)
    init_pipeline_schema(conn)  # second call must not raise


def test_schema_has_no_schedule_columns() -> None:
    """Verify schema contains no cron/interval/next_fire columns (ADR-041 D10)."""
    assert "cron" not in PIPELINE_SCHEMA
    assert "interval" not in PIPELINE_SCHEMA
    assert "next_fire" not in PIPELINE_SCHEMA


def test_pipeline_table_has_owner_user_id() -> None:
    """owner_user_id column must be present (ADR-039 D1 attribution)."""
    assert "owner_user_id" in PIPELINE_SCHEMA


def test_pipeline_runs_table_has_required_columns() -> None:
    for col in ("run_id", "pipeline_id", "room_id", "owner_user_id", "started_at", "status"):
        assert col in PIPELINE_SCHEMA


# ---------------------------------------------------------------------------
# Pipeline CRUD round-trips
# ---------------------------------------------------------------------------


def test_create_and_get_pipeline() -> None:
    conn = _make_conn()
    defn = _sample_definition()
    record = create_pipeline(conn, owner_user_id="alice", definition=defn)

    assert record.pipeline_id.startswith("pipe_")
    assert record.owner_user_id == "alice"
    assert record.enabled is True
    assert record.created_at > 0

    fetched = get_pipeline(conn, record.pipeline_id)
    assert fetched is not None
    assert fetched.pipeline_id == record.pipeline_id
    assert fetched.owner_user_id == "alice"
    assert fetched.definition.analysis_prompts == ["Summarize the content"]
    assert fetched.definition.sources[0].kind == "web"


def test_get_pipeline_not_found() -> None:
    conn = _make_conn()
    assert get_pipeline(conn, "pipe_doesnotexist") is None


def test_list_pipelines_owner_only() -> None:
    conn = _make_conn()
    defn = _sample_definition()
    create_pipeline(conn, owner_user_id="alice", definition=defn)
    create_pipeline(conn, owner_user_id="alice", definition=defn)
    create_pipeline(conn, owner_user_id="bob", definition=defn)

    alice_list = list_pipelines(conn, "alice")
    bob_list = list_pipelines(conn, "bob")
    nobody_list = list_pipelines(conn, "nobody")

    assert len(alice_list) == 2
    assert len(bob_list) == 1
    assert len(nobody_list) == 0
    assert all(r.owner_user_id == "alice" for r in alice_list)


def test_pipeline_definition_round_trips_sources_and_prompts() -> None:
    conn = _make_conn()
    defn = PipelineDefinition(
        sources=[
            Source(kind="web", locator="https://example.com/page"),
            Source(kind="rss", locator="https://example.com/feed.xml"),
        ],
        analysis_prompts=["Prompt A", "Prompt B", "Prompt C"],
    )
    record = create_pipeline(conn, owner_user_id="carol", definition=defn)
    fetched = get_pipeline(conn, record.pipeline_id)
    assert fetched is not None
    assert len(fetched.definition.sources) == 2
    assert fetched.definition.sources[1].kind == "rss"
    assert fetched.definition.analysis_prompts == ["Prompt A", "Prompt B", "Prompt C"]


# ---------------------------------------------------------------------------
# Pipeline runs
# ---------------------------------------------------------------------------


def test_create_pipeline_run() -> None:
    conn = _make_conn()
    defn = _sample_definition()
    pipeline = create_pipeline(conn, owner_user_id="alice", definition=defn)
    run = create_pipeline_run(
        conn,
        pipeline_id=pipeline.pipeline_id,
        room_id="room_abc",
        owner_user_id="alice",
    )
    assert run.run_id.startswith("prun_")
    assert run.pipeline_id == pipeline.pipeline_id
    assert run.room_id == "room_abc"
    assert run.owner_user_id == "alice"
    assert run.status == "running"
    assert run.started_at > 0


def test_create_pipeline_run_with_caller_supplied_run_id() -> None:
    """F-runid: caller-supplied run_id is used as-is (store row id == runner's id)."""
    conn = _make_conn()
    defn = _sample_definition()
    pipeline = create_pipeline(conn, owner_user_id="alice", definition=defn)
    caller_run_id = "prun_abc123fixed"
    run = create_pipeline_run(
        conn,
        pipeline_id=pipeline.pipeline_id,
        room_id="room_xyz",
        owner_user_id="alice",
        run_id=caller_run_id,
    )
    assert run.run_id == caller_run_id
    row = conn.execute(
        "SELECT run_id FROM pipeline_runs WHERE run_id = ?", (caller_run_id,)
    ).fetchone()
    assert row is not None
    assert row[0] == caller_run_id


def test_update_pipeline_run_status() -> None:
    conn = _make_conn()
    defn = _sample_definition()
    pipeline = create_pipeline(conn, owner_user_id="alice", definition=defn)
    run = create_pipeline_run(
        conn,
        pipeline_id=pipeline.pipeline_id,
        room_id="room_abc",
        owner_user_id="alice",
    )
    update_pipeline_run_status(conn, run.run_id, "completed")
    row = conn.execute(
        "SELECT status FROM pipeline_runs WHERE run_id = ?", (run.run_id,)
    ).fetchone()
    assert row is not None
    assert row[0] == "completed"
