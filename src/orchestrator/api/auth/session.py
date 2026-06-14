"""Session store + per-user static bearer token (ADR-039 D3).

P4.5-2: sessions SQLite table (co-located in the main DB).
Session create/revoke on the writer connection; validate on the reader.
Per-user static bearer token stored as SHA-256 hex (NOT scrypt — the
token is a 32-byte random value with 256-bit entropy; SHA-256 is
sufficient and fast for high-entropy tokens; scrypt is for passwords).

SECURITY: session_id is cryptographically random (secrets.token_urlsafe).
          Bearer token is stored SHA-256 hashed; raw token never persisted.
          session_id / raw token never logged / wired / evented.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from dataclasses import dataclass

from orchestrator.api.auth.principal import Principal

# ---------------------------------------------------------------------------
# Schema (co-located — appended by init_auth_schema in users.py caller)
# ---------------------------------------------------------------------------

AUTH_SESSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    created_at   INTEGER NOT NULL,
    expires_at   INTEGER NOT NULL,
    revoked      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    revoked    INTEGER NOT NULL DEFAULT 0
);
"""

# Session TTL: 24 hours (86400 s) in milliseconds
_SESSION_TTL_MS = 86_400 * 1000

# Token hash: SHA-256 (fast, adequate for a random high-entropy token)
# scrypt is intentional for passwords (low-entropy); for a 32-byte random
# token the entropy is already 256 bits — SHA-256 is sufficient.
_TOKEN_HASH_DKLEN = 32


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Frozen session record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Session:
    """Immutable session record (no session_id — never returned)."""

    user_id: str
    created_at: int
    expires_at: int
    revoked: bool


# ---------------------------------------------------------------------------
# Session CRUD (create/revoke on writer; validate on reader)
# ---------------------------------------------------------------------------


def create_session(conn: sqlite3.Connection, user_id: str) -> str:
    """Create a new session for user_id, return the opaque session_id.

    MUST run on the writer connection (ADR-025 D6 / ADR-039 D3).
    Returns the raw session_id — set in HttpOnly cookie by the caller.
    """
    session_id = secrets.token_urlsafe(32)
    now_ms = int(time.time() * 1000)
    expires_at = now_ms + _SESSION_TTL_MS
    conn.execute(
        "INSERT INTO sessions (session_id, user_id, created_at, expires_at, revoked)"
        " VALUES (?, ?, ?, ?, 0)",
        (session_id, user_id, now_ms, expires_at),
    )
    conn.commit()
    return session_id


def revoke_session(conn: sqlite3.Connection, session_id: str) -> None:
    """Revoke a session by id.

    MUST run on the writer connection.
    """
    conn.execute(
        "UPDATE sessions SET revoked = 1 WHERE session_id = ?",
        (session_id,),
    )
    conn.commit()


def revoke_sessions_for_user(conn: sqlite3.Connection, user_id: str) -> None:
    """Revoke all active sessions for a user (logout-all-sessions).

    MUST run on the writer connection.
    Used by /logout (protected route) so the authenticated principal's
    user_id drives revocation rather than a cookie value.
    """
    conn.execute(
        "UPDATE sessions SET revoked = 1 WHERE user_id = ?",
        (user_id,),
    )
    conn.commit()


def validate_session(conn: sqlite3.Connection, session_id: str) -> Principal | None:
    """Validate session_id and return Principal if valid, else None.

    Runs on the reader connection (non-blocking during run_turn writes,
    preserving ADR-025 D6 liveness).
    Returns None if not found / expired / revoked.
    """
    now_ms = int(time.time() * 1000)
    row = conn.execute(
        "SELECT user_id, expires_at, revoked FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    user_id, expires_at, revoked = row
    if revoked or now_ms > expires_at:
        return None
    return Principal(user_id=user_id)


# ---------------------------------------------------------------------------
# Per-user static bearer token (programmatic clients)
# ---------------------------------------------------------------------------


def create_token(conn: sqlite3.Connection, user_id: str) -> str:
    """Issue a new static bearer token for user_id.

    MUST run on the writer connection.
    Returns the raw token — the caller gives it to the user ONCE.
    Only the hash is stored; the raw token is never persisted.
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = _sha256_hex(raw_token)
    now_ms = int(time.time() * 1000)
    conn.execute(
        "INSERT INTO user_tokens (token_hash, user_id, created_at, revoked) VALUES (?, ?, ?, 0)",
        (token_hash, user_id, now_ms),
    )
    conn.commit()
    return raw_token


def revoke_token(conn: sqlite3.Connection, raw_token: str) -> None:
    """Revoke a bearer token by its raw value.

    MUST run on the writer connection.
    """
    token_hash = _sha256_hex(raw_token)
    conn.execute(
        "UPDATE user_tokens SET revoked = 1 WHERE token_hash = ?",
        (token_hash,),
    )
    conn.commit()


def validate_token(conn: sqlite3.Connection, raw_token: str) -> Principal | None:
    """Validate a raw bearer token, return Principal if valid, else None.

    Runs on the reader connection. Hash-then-lookup: raw token never stored.
    Returns None if not found or revoked.
    """
    token_hash = _sha256_hex(raw_token)
    row = conn.execute(
        "SELECT user_id, revoked FROM user_tokens WHERE token_hash = ?",
        (token_hash,),
    ).fetchone()
    if row is None:
        return None
    user_id, revoked = row
    if revoked:
        return None
    return Principal(user_id=user_id)
