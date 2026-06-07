"""Tests for session store + per-user token + Principal (ADR-039 D3, P4.5-2)."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Generator
from pathlib import Path

import pytest

from orchestrator.api.auth.principal import Principal
from orchestrator.api.auth.session import (
    create_session,
    create_token,
    revoke_session,
    revoke_token,
    validate_session,
    validate_token,
)
from orchestrator.api.auth.users import init_auth_schema


@pytest.fixture
def conn(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    db = tmp_path / "test_auth.db"
    c = sqlite3.connect(str(db), check_same_thread=False)
    init_auth_schema(c)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Session create → validate → revoke round-trip
# ---------------------------------------------------------------------------


def test_session_create_validate(conn: sqlite3.Connection) -> None:
    session_id = create_session(conn, "alice")
    principal = validate_session(conn, session_id)
    assert principal is not None
    assert isinstance(principal, Principal)
    assert principal.user_id == "alice"


def test_session_revoke(conn: sqlite3.Connection) -> None:
    session_id = create_session(conn, "bob")
    revoke_session(conn, session_id)
    assert validate_session(conn, session_id) is None


def test_session_not_found(conn: sqlite3.Connection) -> None:
    assert validate_session(conn, "nonexistent-id") is None


def test_session_is_random(conn: sqlite3.Connection) -> None:
    s1 = create_session(conn, "charlie")
    s2 = create_session(conn, "charlie")
    assert s1 != s2


def test_expired_session(conn: sqlite3.Connection) -> None:
    session_id = create_session(conn, "dave")
    # Force expiry by setting expires_at to the past
    conn.execute(
        "UPDATE sessions SET expires_at = ? WHERE session_id = ?",
        (int(time.time() * 1000) - 1000, session_id),
    )
    conn.commit()
    assert validate_session(conn, session_id) is None


# ---------------------------------------------------------------------------
# Both paths return the same Principal shape
# ---------------------------------------------------------------------------


def test_session_and_token_same_principal_shape(conn: sqlite3.Connection) -> None:
    session_id = create_session(conn, "eve")
    raw_token = create_token(conn, "eve")

    p_session = validate_session(conn, session_id)
    p_token = validate_token(conn, raw_token)

    assert p_session is not None
    assert p_token is not None
    assert type(p_session) is type(p_token)
    assert p_session.user_id == p_token.user_id == "eve"


# ---------------------------------------------------------------------------
# Bearer token create → validate → revoke
# ---------------------------------------------------------------------------


def test_token_create_validate(conn: sqlite3.Connection) -> None:
    raw_token = create_token(conn, "frank")
    principal = validate_token(conn, raw_token)
    assert principal is not None
    assert principal.user_id == "frank"


def test_token_revoke(conn: sqlite3.Connection) -> None:
    raw_token = create_token(conn, "grace")
    revoke_token(conn, raw_token)
    assert validate_token(conn, raw_token) is None


def test_token_not_found(conn: sqlite3.Connection) -> None:
    assert validate_token(conn, "nonexistent-raw-token") is None


def test_token_is_random(conn: sqlite3.Connection) -> None:
    t1 = create_token(conn, "harry")
    t2 = create_token(conn, "harry")
    assert t1 != t2


def test_token_stored_hashed_not_plaintext(conn: sqlite3.Connection) -> None:
    raw_token = create_token(conn, "iris")
    # The raw token must NOT appear in the DB
    row = conn.execute(
        "SELECT token_hash FROM user_tokens WHERE user_id = 'iris'"
    ).fetchone()
    assert row is not None
    token_hash = row[0]
    assert token_hash != raw_token
    # Hash is hex (SHA-256 = 64 hex chars)
    assert len(token_hash) == 64


# ---------------------------------------------------------------------------
# Persistence across re-open
# ---------------------------------------------------------------------------


def test_session_survives_reopen(tmp_path: Path) -> None:
    db = tmp_path / "persist.db"
    c1 = sqlite3.connect(str(db), check_same_thread=False)
    init_auth_schema(c1)
    sid = create_session(c1, "jane")
    c1.close()

    c2 = sqlite3.connect(str(db), check_same_thread=False)
    init_auth_schema(c2)
    assert validate_session(c2, sid) is not None
    c2.close()
