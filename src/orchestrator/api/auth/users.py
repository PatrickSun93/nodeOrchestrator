"""User store + credential model (ADR-039 D2).

P4.5-1: users SQLite table co-located in the main DB (ADR-020/025 idiom).
Schema: user_id (PK, [a-zA-Z0-9_-]+), password_hash, password_salt,
        kdf_params (JSON), created_at, disabled (bool default false).

Credential = hashlib.scrypt (stdlib, memory-hard, no new dep).
Verify via hmac.compare_digest.

SECURITY: the hash and salt NEVER appear in logs / wire / events.
          verify_password() returns bool only — no credential escapes.
          Matches the api_key_env-never-inlined discipline (mcp/transport.py).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Schema (co-located — appended to the main DB on init_auth_schema())
# ---------------------------------------------------------------------------

AUTH_USER_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id    TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    kdf_params TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    disabled   INTEGER NOT NULL DEFAULT 0
);
"""

# user_id constraint: same charset as the author-embeddable id (ADR-039 D1)
_USER_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

# scrypt parameters (n=2^14, r=8, p=1, dklen=32 — memory-hard, stdlib, no new dep)
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_DKLEN = 32
_KDF_PARAMS: dict[str, object] = {
    "alg": "scrypt",
    "n": _SCRYPT_N,  # stored so future readers can re-derive
    "r": _SCRYPT_R,
    "p": _SCRYPT_P,
    "dklen": _SCRYPT_DKLEN,
}


def init_auth_schema(conn: sqlite3.Connection) -> None:
    """Create users (and later sessions/tokens) tables if not present.

    Safe to call on both writer and reader connections — IF NOT EXISTS is
    idempotent. Called by _build_context alongside EventStore.init_schema().
    """
    conn.executescript(AUTH_USER_SCHEMA)
    conn.commit()


# ---------------------------------------------------------------------------
# Frozen User model (ADR-039 D2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class User:
    """Immutable user record — never carries raw credentials."""

    user_id: str
    created_at: int
    disabled: bool


# ---------------------------------------------------------------------------
# Credential primitives (internal — hash/salt never escape)
# ---------------------------------------------------------------------------


def _hash_password(password: str) -> tuple[str, str]:
    """Return (password_hash_hex, password_salt_hex).

    Uses hashlib.scrypt with a cryptographically random per-user salt.
    The tuple is consumed immediately by create_user(); it MUST NOT be
    logged or returned to any caller outside this module.
    """
    salt_bytes = os.urandom(16)
    dk = hashlib.scrypt(
        password.encode(),
        salt=salt_bytes,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return dk.hex(), salt_bytes.hex()


def _verify_hash(password: str, stored_hash_hex: str, stored_salt_hex: str) -> bool:
    """Constant-time comparison of a candidate password against a stored hash."""
    salt_bytes = bytes.fromhex(stored_salt_hex)
    dk = hashlib.scrypt(
        password.encode(),
        salt=salt_bytes,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_DKLEN,
    )
    return hmac.compare_digest(dk.hex(), stored_hash_hex)


# ---------------------------------------------------------------------------
# Public API — storage and credential functions
# ---------------------------------------------------------------------------


def create_user(conn: sqlite3.Connection, user_id: str, password: str) -> User:
    """Create a new user with a hashed password.

    Args:
        conn: the writer connection (single-thread executor serialises this).
        user_id: must match [a-zA-Z0-9_-]+.
        password: plaintext; hashed here, never stored raw or returned.

    Returns the User record (no credentials).
    Raises ValueError on invalid user_id or duplicate user_id.
    """
    if not _USER_ID_RE.fullmatch(user_id):
        raise ValueError(f"user_id {user_id!r} must match [a-zA-Z0-9_-]+")

    # Hash inside create_user so the plaintext never leaves this call frame
    # before being discarded.
    pw_hash, pw_salt = _hash_password(password)
    created_at = int(time.time() * 1000)
    kdf_params_json = json.dumps(_KDF_PARAMS)

    try:
        conn.execute(
            "INSERT INTO users"
            " (user_id, password_hash, password_salt, kdf_params, created_at, disabled)"
            " VALUES (?, ?, ?, ?, ?, 0)",
            (user_id, pw_hash, pw_salt, kdf_params_json, created_at),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise ValueError(f"user_id {user_id!r} already exists") from exc

    # Clear local references before returning (defense-in-depth)
    del pw_hash, pw_salt
    return User(user_id=user_id, created_at=created_at, disabled=False)


def get_user(conn: sqlite3.Connection, user_id: str) -> User | None:
    """Retrieve a user by id (returns None if not found).

    Returns User (no credentials) — the hash/salt never leave the DB row.
    """
    row = conn.execute(
        "SELECT user_id, created_at, disabled FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    uid, created_at, disabled = row
    return User(user_id=uid, created_at=created_at, disabled=bool(disabled))


def verify_password(conn: sqlite3.Connection, user_id: str, password: str) -> bool:
    """Verify password for a user.

    Returns False if user not found, disabled, or password wrong.
    Uses constant-time comparison — timing leak is minimised even on miss
    (the scrypt call runs regardless when the row exists).

    The password hash is fetched from the DB row and discarded here;
    it NEVER appears in return values, logs, or exceptions.
    """
    row = conn.execute(
        "SELECT password_hash, password_salt, disabled FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return False
    stored_hash, stored_salt, disabled = row
    if disabled:
        return False
    result = _verify_hash(password, stored_hash, stored_salt)
    del stored_hash, stored_salt
    return result


def count_users(conn: sqlite3.Connection) -> int:
    """Return the count of non-disabled users (used by the remote-bind guard, P4.5-6)."""
    row = conn.execute("SELECT COUNT(*) FROM users WHERE disabled = 0").fetchone()
    return int(row[0]) if row else 0
