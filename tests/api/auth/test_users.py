"""Tests for user store + credential model (ADR-039 D2, P4.5-1)."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest

from orchestrator.api.auth.users import (
    User,
    count_users,
    create_user,
    get_user,
    init_auth_schema,
    verify_password,
)


@pytest.fixture
def conn(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    db = tmp_path / "test_auth.db"
    c = sqlite3.connect(str(db), check_same_thread=False)
    init_auth_schema(c)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Basic round-trip
# ---------------------------------------------------------------------------


def test_create_and_get_user(conn: sqlite3.Connection) -> None:
    user = create_user(conn, "alice", "s3cret!")
    assert isinstance(user, User)
    assert user.user_id == "alice"
    assert not user.disabled

    fetched = get_user(conn, "alice")
    assert fetched is not None
    assert fetched.user_id == "alice"
    assert not fetched.disabled


def test_get_user_not_found(conn: sqlite3.Connection) -> None:
    assert get_user(conn, "nobody") is None


def test_verify_password_correct(conn: sqlite3.Connection) -> None:
    create_user(conn, "bob", "pass123")
    assert verify_password(conn, "bob", "pass123") is True


def test_verify_password_wrong(conn: sqlite3.Connection) -> None:
    create_user(conn, "charlie", "right")
    assert verify_password(conn, "charlie", "wrong") is False


def test_verify_password_user_not_found(conn: sqlite3.Connection) -> None:
    assert verify_password(conn, "ghost", "any") is False


def test_duplicate_user_raises(conn: sqlite3.Connection) -> None:
    create_user(conn, "dave", "pw")
    with pytest.raises(ValueError, match="already exists"):
        create_user(conn, "dave", "pw2")


# ---------------------------------------------------------------------------
# Disabled account
# ---------------------------------------------------------------------------


def test_disabled_user_fails_verify(conn: sqlite3.Connection) -> None:
    create_user(conn, "eve", "pw")
    conn.execute("UPDATE users SET disabled = 1 WHERE user_id = 'eve'")
    conn.commit()
    assert verify_password(conn, "eve", "pw") is False


def test_disabled_user_readable(conn: sqlite3.Connection) -> None:
    create_user(conn, "frank", "pw")
    conn.execute("UPDATE users SET disabled = 1 WHERE user_id = 'frank'")
    conn.commit()
    user = get_user(conn, "frank")
    assert user is not None
    assert user.disabled is True


# ---------------------------------------------------------------------------
# Invalid user_id formats
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_id", ["", "has space", "has@symbol", "has/slash"])
def test_invalid_user_id_rejected(conn: sqlite3.Connection, bad_id: str) -> None:
    with pytest.raises(ValueError):
        create_user(conn, bad_id, "pw")


def test_valid_user_id_chars(conn: sqlite3.Connection) -> None:
    create_user(conn, "user-1_OK", "pw")
    assert get_user(conn, "user-1_OK") is not None


# ---------------------------------------------------------------------------
# Security: hash never escapes
# ---------------------------------------------------------------------------


def test_create_user_returns_no_credentials(conn: sqlite3.Connection) -> None:
    user = create_user(conn, "harry", "super_secret")
    # User model has no hash/salt field
    assert not hasattr(user, "password_hash")
    assert not hasattr(user, "password_salt")


def test_get_user_returns_no_credentials(conn: sqlite3.Connection) -> None:
    create_user(conn, "iris", "pw")
    user = get_user(conn, "iris")
    assert user is not None
    assert not hasattr(user, "password_hash")
    assert not hasattr(user, "password_salt")


def test_verify_returns_bool_only(conn: sqlite3.Connection) -> None:
    create_user(conn, "jane", "pw")
    result = verify_password(conn, "jane", "pw")
    assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# count_users (used by remote-bind guard)
# ---------------------------------------------------------------------------


def test_count_users_empty(conn: sqlite3.Connection) -> None:
    assert count_users(conn) == 0


def test_count_users_excludes_disabled(conn: sqlite3.Connection) -> None:
    create_user(conn, "k1", "pw")
    create_user(conn, "k2", "pw")
    conn.execute("UPDATE users SET disabled = 1 WHERE user_id = 'k1'")
    conn.commit()
    assert count_users(conn) == 1


# ---------------------------------------------------------------------------
# Persistence across re-open
# ---------------------------------------------------------------------------


def test_user_survives_reopen(tmp_path: Path) -> None:
    db = tmp_path / "persist.db"
    c1 = sqlite3.connect(str(db), check_same_thread=False)
    init_auth_schema(c1)
    create_user(c1, "leo", "pw")
    c1.close()

    c2 = sqlite3.connect(str(db), check_same_thread=False)
    init_auth_schema(c2)
    assert verify_password(c2, "leo", "pw") is True
    c2.close()
