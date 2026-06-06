"""Uvicorn entry point for the Orchestrator API server (ADR-025 D7).

Usage:
    uv run python -m orchestrator.api --config config/ --db data/rooms.db

Binds to 127.0.0.1 (localhost only) by default.

P4.5-6 (ADR-039 D8): remote-bind is now fail-closed. Binding beyond
localhost with no users provisioned (or auth-off) is refused at startup
with a loud error. This prevents accidental unauthenticated remote exposure.

TLS: handled at the deployment/reverse-proxy layer (not in-app).
The session cookie is Secure — TLS is REQUIRED for any remote deployment.
See docs/architecture/ for the recommended deployment topology.

CORS: not required for the same-origin GUI+API deployment (ADR-039 D3/D8).
CORS middleware, if added, must restrict origins to a configured allowlist
and never use *-with-credentials. Residual named in ADR-039 D10.
"""

from __future__ import annotations

import argparse
import ipaddress
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Orchestrator API server")
    p.add_argument("--config", type=Path, default=Path("config"), help="Config directory")
    p.add_argument("--db", type=Path, default=Path("data/rooms.db"), help="SQLite DB path")
    p.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    return p.parse_args()


def _is_loopback(host: str) -> bool:
    """Return True if host is a loopback address (ADR-039 D8 M1).

    Loopback = 127.0.0.0/8 + ::1 + the literal "localhost".
    NOT limited to the string "127.0.0.1" (a ::1 bind would be falsely
    refused, and a specific LAN-IP bind could slip the guard).
    """
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _check_remote_bind_guard(host: str, db_path: Path) -> None:
    """Refuse a non-loopback bind when no users are provisioned (ADR-039 D8).

    A remote bind must have the auth boundary armed. If the DB has no users,
    an unauthenticated remote bind would expose the API without auth protection.
    Fail-closed: refuse LOUDLY at startup rather than silently exposing the API.
    """
    if _is_loopback(host):
        return  # localhost binds are always permissive

    import sqlite3

    from orchestrator.api.auth.users import count_users, init_auth_schema

    if not db_path.exists():
        print(
            f"ERROR: remote bind to {host!r} refused — no database found at {db_path}.\n"
            "Create at least one user first:\n"
            f"  python -m orchestrator.api.admin create-user <id> --db {db_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        init_auth_schema(conn)
        n = count_users(conn)
    finally:
        conn.close()

    if n == 0:
        print(
            f"ERROR: remote bind to {host!r} refused — no users provisioned in {db_path}.\n"
            "Create at least one user first (the auth boundary must be armed):\n"
            f"  python -m orchestrator.api.admin create-user <id> --db {db_path}\n"
            "TLS-at-deployment is also required for remote access (ADR-039 D8).",
            file=sys.stderr,
        )
        sys.exit(1)


def main() -> None:
    import uvicorn

    from orchestrator.api.app import create_app

    args = _parse_args()
    args.db.parent.mkdir(parents=True, exist_ok=True)

    # Fail-closed remote-bind guard (ADR-039 D8)
    _check_remote_bind_guard(args.host, args.db)

    app = create_app(config_dir=args.config, db_path=args.db)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
