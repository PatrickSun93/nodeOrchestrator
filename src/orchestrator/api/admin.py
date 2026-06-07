"""Out-of-band admin CLI for the Orchestrator API (ADR-039 D2).

Usage:
    python -m orchestrator.api.admin create-user <user_id>

Reads the password from stdin (or ORCHESTRATOR_ADMIN_PASSWORD env var).
Writes directly to the users table — out-of-band first-account bootstrap.
The operator who can run the server already has filesystem + DB access;
this CLI does not widen that trust root.

P4.5-1: the only way to create the first operator account before the auth
boundary is armed (D2: chicken-and-egg bootstrap, no unauthenticated
user-create HTTP endpoint).
"""

from __future__ import annotations

import argparse
import getpass
import os
import sqlite3
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Orchestrator admin CLI",
        prog="python -m orchestrator.api.admin",
    )
    sub = p.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-user", help="Create a new user account")
    create.add_argument("user_id", help="User identifier ([a-zA-Z0-9_-]+)")
    create.add_argument(
        "--db",
        type=Path,
        default=Path("data/rooms.db"),
        help="SQLite DB path (default: data/rooms.db)",
    )
    return p.parse_args()


def _cmd_create_user(user_id: str, db_path: Path) -> None:
    from orchestrator.api.auth.users import create_user, init_auth_schema

    # Read password from env (for scripting) or stdin (interactive)
    password = os.environ.get("ORCHESTRATOR_ADMIN_PASSWORD") or getpass.getpass(
        f"Password for {user_id!r}: "
    )
    if not password:
        print("Error: password must not be empty", file=sys.stderr)
        sys.exit(1)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        init_auth_schema(conn)
        user = create_user(conn, user_id, password)
        print(f"Created user {user.user_id!r} (created_at={user.created_at})")
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()
        del password


def main() -> None:
    args = _parse_args()
    if args.command == "create-user":
        _cmd_create_user(args.user_id, args.db)


if __name__ == "__main__":
    main()
