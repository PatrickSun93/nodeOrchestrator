"""Tests for the remote-bind fail-closed guard (ADR-039 D8, P4.5-6)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from orchestrator.api.__main__ import _check_remote_bind_guard, _is_loopback
from orchestrator.api.auth.users import create_user, init_auth_schema

# ---------------------------------------------------------------------------
# _is_loopback — loopback detection (ADR-039 D8 M1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "127.0.0.1",
        "127.0.0.2",
        "127.1.2.3",
        "::1",
    ],
)
def test_loopback_hosts_accepted(host: str) -> None:
    assert _is_loopback(host) is True


@pytest.mark.parametrize(
    "host",
    [
        "0.0.0.0",
        "192.168.1.1",
        "10.0.0.1",
        "203.0.113.5",
        "example.com",
        "::",
    ],
)
def test_non_loopback_hosts_rejected(host: str) -> None:
    assert _is_loopback(host) is False


# ---------------------------------------------------------------------------
# _check_remote_bind_guard
# ---------------------------------------------------------------------------


def test_localhost_bind_always_permitted(tmp_path: Path) -> None:
    """Loopback bind never triggers the guard — even with no DB."""
    # Should not raise regardless of DB state
    _check_remote_bind_guard("127.0.0.1", tmp_path / "nonexistent.db")
    _check_remote_bind_guard("localhost", tmp_path / "nonexistent.db")
    _check_remote_bind_guard("::1", tmp_path / "nonexistent.db")


def test_remote_bind_no_db_exits(tmp_path: Path) -> None:
    """Remote bind with missing DB exits at startup (ADR-039 D8)."""
    with pytest.raises(SystemExit) as exc_info:
        _check_remote_bind_guard("0.0.0.0", tmp_path / "missing.db")
    assert exc_info.value.code == 1


def test_remote_bind_zero_users_exits(tmp_path: Path) -> None:
    """Remote bind with DB but zero users exits (auth boundary not armed)."""
    db = tmp_path / "empty.db"
    conn = sqlite3.connect(str(db), check_same_thread=False)
    init_auth_schema(conn)
    conn.close()

    with pytest.raises(SystemExit) as exc_info:
        _check_remote_bind_guard("0.0.0.0", db)
    assert exc_info.value.code == 1


def test_remote_bind_with_users_permitted(tmp_path: Path) -> None:
    """Remote bind with at least one user passes the guard."""
    db = tmp_path / "with_user.db"
    conn = sqlite3.connect(str(db), check_same_thread=False)
    init_auth_schema(conn)
    create_user(conn, "operator", "secret123")
    conn.close()

    # Should NOT raise — auth boundary is armed
    _check_remote_bind_guard("0.0.0.0", db)
    _check_remote_bind_guard("192.168.1.100", db)


def test_remote_bind_only_disabled_users_exits(tmp_path: Path) -> None:
    """Remote bind where all users are disabled exits (count_users excludes disabled)."""
    db = tmp_path / "disabled.db"
    conn = sqlite3.connect(str(db), check_same_thread=False)
    init_auth_schema(conn)
    create_user(conn, "operator", "secret123")
    conn.execute("UPDATE users SET disabled = 1 WHERE user_id = 'operator'")
    conn.commit()
    conn.close()

    with pytest.raises(SystemExit) as exc_info:
        _check_remote_bind_guard("0.0.0.0", db)
    assert exc_info.value.code == 1
