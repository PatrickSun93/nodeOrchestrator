"""Fail-closed auth boundary middleware (ADR-039 D4).

P4.5-3: HTTP auth gate registered at construction time via _configure()
in app.py. Protects all routes not in PUBLIC_PATHS.

Design note (Y1 absorption):
- Middleware is registered at construction (not in lifespan) so BOTH
  _make_test_app and create_app share the same wiring.
- ctx is stowed on app.state at lifespan startup (or directly in
  _make_test_app); middleware reads request.app.state.ctx at request time.
- BaseHTTPMiddleware does NOT see WebSocket scopes — WS auth is an
  explicit in-handler pre-accept() check (see app.py _room_stream).
  This is not redundant: the HTTP middleware and the WS check are
  complementary, each covering a scope the other cannot.

SECURITY: gate makes no LLM call / no routing decision (HR#3); it only
verifies a credential and resolves a Principal. Fail-closed by default:
a route not in PUBLIC_PATHS is protected without any per-route opt-in.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from orchestrator.api.auth.session import validate_session, validate_token

# Public paths exempt from auth (explicit allowlist — fail-closed by default).
# A new route is protected unless added here.
PUBLIC_PATHS: frozenset[str] = frozenset({
    "/login",
    "/logout",
    "/health",
})


def _is_public(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith("/health")


class AuthMiddleware(BaseHTTPMiddleware):
    """Fail-closed HTTP auth gate (ADR-039 D4).

    Runs before every handler. Resolves Principal from session cookie or
    Bearer token; attaches it to request.state.principal. Returns 401
    before any handler logic if no valid credential is present.

    WebSocket scopes are NOT seen here — the WS handler checks auth
    explicitly before websocket.accept() (app.py _room_stream).
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        if _is_public(request.url.path):
            return await call_next(request)  # type: ignore[no-any-return]

        principal = await _resolve_principal(request)
        if principal is None:
            return Response(
                content=json.dumps({"detail": "Unauthorized"}),
                status_code=401,
                media_type="application/json",
            )

        request.state.principal = principal
        return await call_next(request)  # type: ignore[no-any-return]


async def _resolve_principal(request: Request) -> Any:
    """Resolve Principal from session cookie or Bearer token.

    Reads ctx from request.app.state (set at lifespan startup or in
    _make_test_app). Uses the reader connection for non-blocking auth.
    Returns Principal or None.
    """
    ctx = getattr(request.app.state, "ctx", None)
    if ctx is None:
        return None

    loop = asyncio.get_running_loop()
    reader_conn = ctx.reader_store.conn

    # 1. Try session cookie first (GUI path)
    session_id = request.cookies.get("session_id")
    if session_id:
        principal = await loop.run_in_executor(
            ctx.reader_executor,
            lambda: validate_session(reader_conn, session_id),
        )
        if principal is not None:
            return principal

    # 2. Try Bearer token (programmatic path)
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        raw_token = auth[7:]
        principal = await loop.run_in_executor(
            ctx.reader_executor,
            lambda: validate_token(reader_conn, raw_token),
        )
        if principal is not None:
            return principal

    return None
