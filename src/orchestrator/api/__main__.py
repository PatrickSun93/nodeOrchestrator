"""Uvicorn entry point for the Orchestrator API server (ADR-025 D7).

Usage:
    uv run python -m orchestrator.api --config config/ --db data/rooms.db

Binds to 127.0.0.1 (localhost only) — MVP trust boundary per ADR-025 D7.
Production deployment must add authentication/TLS before exposing externally.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Orchestrator API server")
    p.add_argument("--config", type=Path, default=Path("config"), help="Config directory")
    p.add_argument("--db", type=Path, default=Path("data/rooms.db"), help="SQLite DB path")
    p.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    return p.parse_args()


def main() -> None:
    import uvicorn

    from orchestrator.api.app import create_app

    args = _parse_args()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    app = create_app(config_dir=args.config, db_path=args.db)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
