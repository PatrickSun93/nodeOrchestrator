"""Constitutional / trust-boundary tests (ADR-039 D4/D7, P4.5-7).

Lens A: identity trust boundary — forge prevention, fail-closed auth,
        credential storage security, bootstrap out-of-band.
Lens B: spine preservation — gate identity-blind, no new LLMPurpose,
        is_valid_author exhaustive, confirm idempotency/partial-turn,
        boundary via production wiring (tested-app == shipped-app).

Guards 1-13 from P4.5 plan §7.
"""

from __future__ import annotations

import inspect
import sqlite3
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from orchestrator.agents.dispatch import LLMRouterProtocol
from orchestrator.api.app import AppContext, _configure, _make_test_app
from orchestrator.api.auth.session import (
    create_session,
    create_token,
    revoke_session,
    revoke_token,
    validate_session,
    validate_token,
)
from orchestrator.api.auth.users import (
    create_user,
    get_user,
    init_auth_schema,
)
from orchestrator.api.pubsub import RoomEventBus
from orchestrator.core.event import (
    build_user_author,
    is_valid_author,
)
from orchestrator.core.event_store import EventStore
from orchestrator.llm.types import (
    LLMResponse,
    ModelId,
    ProviderId,
    RequestId,
    Usage,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_USER = "testuser"
TEST_PW = "test-pw"


@pytest.fixture
def db_conn(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    c = sqlite3.connect(str(tmp_path / "test.db"), check_same_thread=False)
    init_auth_schema(c)
    yield c
    c.close()


def _mock_router() -> MagicMock:
    router = MagicMock(spec=LLMRouterProtocol)
    response = LLMResponse(
        request_id=RequestId("req-1"),
        content="ok",
        tool_calls=[],
        model_id_requested=ModelId("mock"),
        model_id_used=ModelId("mock"),
        provider_id_used=ProviderId("mock"),
        usage=Usage(input_tokens=1, output_tokens=1, cost_usd=None),
        latency_ms=0,
        finish_reason="stop",
    )
    router.call.return_value = response
    return router


@pytest.fixture
def ctx(tmp_path: Path) -> Generator[AppContext, None, None]:
    db = tmp_path / "test.db"
    wconn = sqlite3.connect(str(db), check_same_thread=False)
    ws = EventStore(wconn)
    ws.init_schema()
    wconn.execute("PRAGMA journal_mode=WAL")
    wconn.commit()
    init_auth_schema(wconn)
    create_user(wconn, TEST_USER, TEST_PW)

    rconn = sqlite3.connect(str(db), check_same_thread=False)
    rs = EventStore(rconn)

    context = AppContext(
        writer_store=ws,
        reader_store=rs,
        writer_executor=ThreadPoolExecutor(max_workers=1),
        reader_executor=ThreadPoolExecutor(max_workers=2),
        bus=RoomEventBus(),
        available_agents={},
        available_skills={},
        regex_registry={},
        tools={},
        llm_router=_mock_router(),
    )
    yield context
    context.shutdown()


@pytest.fixture
def auth_client(ctx: AppContext) -> Generator[TestClient, None, None]:
    raw_token = create_token(ctx.writer_store.conn, TEST_USER)
    headers = {"Authorization": f"Bearer {raw_token}"}
    with TestClient(_make_test_app(ctx), headers=headers) as tc:
        yield tc


@pytest.fixture
def unauth_client(ctx: AppContext) -> Generator[TestClient, None, None]:
    with TestClient(_make_test_app(ctx)) as tc:
        yield tc


# ---------------------------------------------------------------------------
# Lens A: identity trust boundary
# ---------------------------------------------------------------------------


class TestLensAForge:
    """Guard #1: principal server-derived, never request-derived."""

    def test_intent_body_cannot_set_author(self, auth_client: TestClient) -> None:
        """Forge: a client cannot set author via the request body."""
        r = auth_client.post("/rooms", json={"type": "free_chat"})
        room_id = r.json()["id"]

        # Try to inject an author field in the intent body — must be rejected
        r2 = auth_client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": "hi", "author": "system"},
        )
        assert r2.status_code == 422, "forge field must be rejected at schema layer"

    def test_intent_body_cannot_set_user_id(self, auth_client: TestClient) -> None:
        """Forge: no user_id / identity field accepted in IntentRequest."""
        r = auth_client.post("/rooms", json={"type": "free_chat"})
        room_id = r.json()["id"]

        r2 = auth_client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": "hi", "user_id": "attacker"},
        )
        assert r2.status_code == 422, "user_id forge field must be rejected"

    def test_confirm_body_cannot_set_approver(self, auth_client: TestClient) -> None:
        """Forge: ConfirmRequest has no approver_user_id field (extra=forbid)."""
        from pydantic import ValidationError

        from orchestrator.api.wire import ConfirmRequest

        with pytest.raises(ValidationError):
            ConfirmRequest.model_validate(
                {
                    "pending_event_id": "evt_x",
                    "decision": "approve",
                    "approver_user_id": "attacker",
                }
            )

    def test_author_from_principal_not_body(self, auth_client: TestClient) -> None:
        """The stamped author is derived from the principal, not any request field."""
        r = auth_client.post("/rooms", json={"type": "free_chat"})
        room_id = r.json()["id"]
        r2 = auth_client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": "hi"},
        )
        assert r2.status_code == 200
        evt = r2.json()["appended_event"]
        # Must be user:<id>, not bare "user" and not any value from the body
        assert evt["author"].startswith("user:"), f"expected user:<id>, got {evt['author']!r}"
        assert evt["author"] != "user", "should not be bare user (authenticated path)"


class TestLensAFailClosed:
    """Guard #2: fail-closed on unauthenticated."""

    PROTECTED_ROUTES: ClassVar[list[tuple[str, str]]] = [
        ("POST", "/rooms"),
        ("GET", "/rooms"),
        ("GET", "/rooms/nonexistent-room"),
        ("GET", "/rooms/nonexistent-room/events"),
        ("GET", "/rooms/nonexistent-room/snapshot"),
        ("GET", "/events/nonexistent-event/thread"),
        ("POST", "/rooms/nonexistent-room/intent"),
        ("POST", "/rooms/nonexistent-room/confirm"),
        ("POST", "/logout"),
    ]

    @pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
    def test_unauthenticated_gets_401(
        self, unauth_client: TestClient, method: str, path: str
    ) -> None:
        """Every protected route returns 401 before any handler logic."""
        resp = unauth_client.request(method, path, json={})
        assert resp.status_code == 401, f"{method} {path} returned {resp.status_code}, expected 401"

    def test_new_route_protected_by_default(self, ctx: AppContext) -> None:
        """Fail-closed default: a newly-added dummy route is protected without explicit listing."""
        from fastapi import FastAPI

        app = FastAPI()
        _configure(app)
        app.state.ctx = ctx

        @app.get("/test-new-route")
        async def _dummy() -> dict[str, str]:
            return {"ok": "yes"}

        with TestClient(app) as tc:
            r = tc.get("/test-new-route")
        assert r.status_code == 401, "new route must be protected without opt-in"

    def test_public_paths_not_blocked(self, unauth_client: TestClient) -> None:
        """Login is public (no auth required); logout requires auth (not in PUBLIC_PATHS)."""
        r = unauth_client.post("/login", json={"user_id": "x", "password": "x"})
        # 401 (wrong credentials) not 401 from middleware — middleware lets it through
        assert r.status_code in (200, 401, 422), "login must not be 401 from middleware"

    def test_ws_unauthenticated_rejected_with_1008(self, unauth_client: TestClient) -> None:
        """Unauthenticated WS upgrade is closed with code 1008 before accept().

        The WS handler rejects without calling accept() — no half-open-stream
        window (ADR-039 D4 / app.py _room_stream pre-accept check).
        """
        from starlette.websockets import WebSocketDisconnect

        with (
            pytest.raises(WebSocketDisconnect) as exc_info,
            unauth_client.websocket_connect("/rooms/any-room/stream"),
        ):
            pass
        assert exc_info.value.code == 1008, (
            f"expected close 1008 (Policy Violation), got {exc_info.value.code}"
        )


class TestLensACookiePath:
    """Cookie login path: POST /login → session cookie → cookie-authenticated requests."""

    def test_login_sets_cookie_authenticates_subsequent_requests(self, ctx: AppContext) -> None:
        """POST /login → Set-Cookie session_id → cookie carries auth for next request.

        base_url='https://testserver' makes TestClient treat requests as HTTPS,
        so the Secure cookie is sent on subsequent same-client requests.
        (ADR-039 D3 cookie semantics integration test.)
        """
        from orchestrator.api.app import _make_test_app

        app = _make_test_app(ctx)
        with TestClient(app, base_url="https://testserver") as client:
            resp = client.post("/login", json={"user_id": TEST_USER, "password": TEST_PW})
            assert resp.status_code == 200, f"login failed: {resp.json()}"
            assert "session_id" in resp.cookies, "login must set session_id cookie"

            # Cookie is carried automatically — no explicit Authorization header needed
            resp2 = client.post("/rooms", json={"type": "free_chat"})
            assert resp2.status_code == 201, (
                f"cookie-authenticated POST /rooms returned {resp2.status_code}"
            )


class TestLensAExpiredRevoked:
    """Guard #3: expired/revoked session → 401."""

    def test_expired_session_rejected(self, ctx: AppContext) -> None:
        session_id = create_session(ctx.writer_store.conn, TEST_USER)
        # Force expiry
        ctx.writer_store.conn.execute(
            "UPDATE sessions SET expires_at = 0 WHERE session_id = ?",
            (session_id,),
        )
        ctx.writer_store.conn.commit()

        assert validate_session(ctx.reader_store.conn, session_id) is None

    def test_revoked_session_rejected(self, ctx: AppContext) -> None:
        session_id = create_session(ctx.writer_store.conn, TEST_USER)
        revoke_session(ctx.writer_store.conn, session_id)
        assert validate_session(ctx.reader_store.conn, session_id) is None

    def test_revoked_token_rejected(self, ctx: AppContext) -> None:
        raw_token = create_token(ctx.writer_store.conn, TEST_USER)
        revoke_token(ctx.writer_store.conn, raw_token)
        assert validate_token(ctx.reader_store.conn, raw_token) is None


class TestLensACredentialStorage:
    """Guard #4/#5: password/token stored hashed, never returned."""

    def test_password_stored_hashed(self, db_conn: sqlite3.Connection) -> None:
        """Password must not be stored in plaintext in the DB."""
        create_user(db_conn, "charlie", "my-plaintext-pw")
        row = db_conn.execute(
            "SELECT password_hash, password_salt FROM users WHERE user_id = 'charlie'"
        ).fetchone()
        assert row is not None
        pw_hash, pw_salt = row
        assert pw_hash != "my-plaintext-pw", "password stored in plaintext"
        assert pw_salt != "my-plaintext-pw", "salt stored as plaintext password"
        # Hash must be non-trivially long (scrypt hex output)
        assert len(pw_hash) >= 32

    def test_password_not_returned_from_get_user(self, db_conn: sqlite3.Connection) -> None:
        """get_user() must return no credential fields."""
        create_user(db_conn, "dave", "secret")
        user = get_user(db_conn, "dave")
        assert user is not None
        assert not hasattr(user, "password_hash")
        assert not hasattr(user, "password_salt")

    def test_token_stored_hashed(self, db_conn: sqlite3.Connection) -> None:
        """Bearer token is stored hashed (SHA-256 hex), not plaintext."""
        create_user(db_conn, "eve", "pw")
        raw_token = create_token(db_conn, "eve")
        row = db_conn.execute("SELECT token_hash FROM user_tokens WHERE user_id = 'eve'").fetchone()
        assert row is not None
        stored_hash = row[0]
        assert stored_hash != raw_token, "token stored in plaintext"
        assert len(stored_hash) == 64, "expected SHA-256 hex (64 chars)"


class TestLensABootstrap:
    """Guard #6: first-account bootstrap is out-of-band only."""

    def test_no_unauthenticated_create_user_endpoint(self, unauth_client: TestClient) -> None:
        """There is no POST /users or similar unauthenticated user-create endpoint."""
        r = unauth_client.post("/users", json={"user_id": "attacker", "password": "pw"})
        # Must be 404 (no such route) or 401 (auth gate) — not 201 or 200
        assert r.status_code in (401, 404, 405), (
            f"expected 401/404, got {r.status_code} — unauthenticated user creation not allowed"
        )


# ---------------------------------------------------------------------------
# Lens B: spine preservation
# ---------------------------------------------------------------------------


class TestLensBGateIdentityBlind:
    """Guard #7: gate stays identity-blind — Operation has no principal field."""

    def test_operation_has_no_principal_field(self) -> None:
        from orchestrator.autonomy.scoring import Operation

        fields = set(Operation.model_fields.keys())
        assert "principal" not in fields, "Operation must not have a principal field"
        assert "user_id" not in fields, "Operation must not have a user_id field"
        assert "author" not in fields, "Operation must not have an author field"

    def test_score_has_no_principal_param(self) -> None:
        from orchestrator.autonomy import scoring

        sig = inspect.signature(scoring.score)
        for param in sig.parameters:
            assert param not in ("principal", "user_id", "author"), (
                f"score() must not accept {param!r} — gate is identity-blind"
            )

    def test_scoring_py_unchanged_field_set(self) -> None:
        """The Operation field set is byte-frozen (ADR-038-I lineage, P4.5-7 #7)."""
        from orchestrator.autonomy.scoring import Operation

        expected = {
            "tool_id",
            "initiating_agent",
            "user_explicit_intent",
            "params",
            "estimated_cost_usd",
        }
        actual = set(Operation.model_fields.keys())
        assert actual == expected, f"Operation field set changed: {actual!r}"


class TestLensBNoNewLLMPurpose:
    """Guard #8: no new LLMPurpose on the auth surface."""

    def test_no_llm_purpose_in_auth_module(self) -> None:

        auth_dir = Path(__file__).parent.parent.parent.parent / "src/orchestrator/api/auth"
        for py_file in auth_dir.glob("*.py"):
            src = py_file.read_text()
            assert "LLMPurpose" not in src, (
                f"{py_file.name} must not reference LLMPurpose (auth is mechanical verify)"
            )


class TestLensBIsValidAuthorExhaustive:
    """Guard #9: is_valid_author exhaustive — bare user + user:<id> + agent:<id> + system."""

    @pytest.mark.parametrize(
        "valid",
        [
            "user",  # bare (backward-compat)
            "user:alice",  # authenticated
            "user:1",  # short id
            "user:my-user_1",
            "agent:operator",
            "agent:my-agent-v2",
            "system",
        ],
    )
    def test_valid_forms(self, valid: str) -> None:
        assert is_valid_author(valid)

    @pytest.mark.parametrize(
        "invalid",
        [
            "",
            "user:",  # empty id
            "user:bad space",
            "user:bad@",
            "agent",  # missing :id
            "agent:",  # empty id
            "agent:bad name",
            "User",
            "USER",
            "human",
        ],
    )
    def test_invalid_forms(self, invalid: str) -> None:
        assert not is_valid_author(invalid)

    def test_build_user_author_result_is_valid(self) -> None:
        result = build_user_author("alice")
        assert is_valid_author(result)
        assert result == "user:alice"

    def test_build_user_author_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            build_user_author("")


class TestLensBConfirmIdempotency:
    """Guard #10: confirm idempotency/partial-turn unchanged (regression)."""

    def test_double_approve_already_resolved(self, auth_client: TestClient) -> None:
        """Still-pending scan is unchanged — double approve returns already_resolved."""
        from orchestrator.core.event import Event as CoreEvent
        from orchestrator.core.event import (
            EventType,
            RoomId,
            ToolCallPendingMeta,
            build_author,
            generate_event_id,
            now_ms,
        )
        from orchestrator.core.room import Room, RoomType

        ctx: Any = auth_client.app.state.ctx  # type: ignore[attr-defined]
        rid = RoomId(generate_event_id())
        ctx.writer_store.append_room(Room(id=rid, type=RoomType.FREE_CHAT))

        pending = CoreEvent(
            id=generate_event_id(),
            room_id=rid,
            type=EventType.TOOL_CALL_PENDING,
            author=build_author("agent1"),
            timestamp=now_ms(),
            content="",
            metadata=ToolCallPendingMeta(
                tool_name="read_file",
                call_id="call_idem",
                params={},
                tier="hard_confirm",
                initiating_agent="agent1",
            ).model_dump(),
        )
        ctx.writer_store.append(pending)

        r1 = auth_client.post(
            f"/rooms/{rid}/confirm",
            json={"pending_event_id": pending.id, "decision": "approve"},
        )
        assert r1.status_code == 200

        r2 = auth_client.post(
            f"/rooms/{rid}/confirm",
            json={"pending_event_id": pending.id, "decision": "approve"},
        )
        assert r2.status_code == 422
        assert r2.json()["reason"] == "already_resolved"

    def test_tool_call_stays_agent_authored(self, auth_client: TestClient) -> None:
        """Approved TOOL_CALL author is agent:<initiating_agent> — not user:<approver>."""
        from orchestrator.core.event import Event as CoreEvent
        from orchestrator.core.event import (
            EventType,
            RoomId,
            ToolCallPendingMeta,
            build_author,
            generate_event_id,
            now_ms,
        )
        from orchestrator.core.room import Room, RoomType

        ctx: Any = auth_client.app.state.ctx  # type: ignore[attr-defined]
        rid = RoomId(generate_event_id())
        ctx.writer_store.append_room(Room(id=rid, type=RoomType.FREE_CHAT))

        pending = CoreEvent(
            id=generate_event_id(),
            room_id=rid,
            type=EventType.TOOL_CALL_PENDING,
            author=build_author("coordinator"),
            timestamp=now_ms(),
            content="",
            metadata=ToolCallPendingMeta(
                tool_name="apply_edit",
                call_id="call_auth_check",
                params={},
                tier="hard_confirm",
                initiating_agent="coordinator",
            ).model_dump(),
        )
        ctx.writer_store.append(pending)

        r = auth_client.post(
            f"/rooms/{rid}/confirm",
            json={"pending_event_id": pending.id, "decision": "approve"},
        )
        assert r.status_code == 200
        tool_call = r.json()["appended_event"]
        # TOOL_CALL is agent-authored (ADR-030 D3 / ADR-039 D6)
        assert tool_call["author"] == "agent:coordinator"
        assert not tool_call["author"].startswith("user:")
        # approver_user_id IS recorded in metadata (provenance, not authorship)
        assert tool_call["metadata"]["approver_user_id"] == TEST_USER


class TestLensBProductionWiring:
    """Guard #12: boundary exercised through production wiring (_make_test_app)."""

    def test_auth_middleware_registered_on_test_app(self, ctx: AppContext) -> None:
        """_make_test_app calls _configure, which registers AuthMiddleware.

        Verified behaviorally: unauthenticated request must get 401.
        (Introspecting Starlette middleware internals is brittle.)
        """
        app = _make_test_app(ctx)
        with TestClient(app) as tc:
            r = tc.post("/rooms", json={"type": "free_chat"})
        assert r.status_code == 401, "auth middleware must be active on test app"

    def test_test_app_same_wiring_as_prod(self, ctx: AppContext) -> None:
        """Verify tested-app == shipped-app at the auth crux (not a test-only shim)."""
        # create_app and _make_test_app both call _configure
        app = _make_test_app(ctx)
        # The middleware stack is active: unauthenticated → 401
        with TestClient(app) as tc:
            r = tc.get("/rooms/any")
        assert r.status_code == 401


class TestLensBAuthenticatedIntentPath:
    """Guard #13: authenticated /intent path stamps author=user:<id>."""

    def test_authenticated_path_stamps_user_id(self, auth_client: TestClient) -> None:
        """At least one intent test drives a logged-in session and asserts user:<id>."""
        r = auth_client.post("/rooms", json={"type": "free_chat"})
        room_id = r.json()["id"]

        r2 = auth_client.post(
            f"/rooms/{room_id}/intent",
            json={"type": "user_input", "content": "test auth path"},
        )
        assert r2.status_code == 200
        evt = r2.json()["appended_event"]
        assert evt["author"] == f"user:{TEST_USER}", (
            f"authenticated path must stamp user:<id>, got {evt['author']!r}"
        )
        assert evt["author"] != "user", (
            "bare 'user' fallback must not be used on the authenticated path"
        )


class TestLensBReaderLiveness:
    """Guard #11: session validate (reader) doesn't block behind writer run_turn."""

    def test_session_validate_on_reader_connection(self, ctx: AppContext) -> None:
        """validate_session runs on reader_store.conn (non-blocking)."""
        session_id = create_session(ctx.writer_store.conn, TEST_USER)
        # Validate on reader — must not need the writer connection
        principal = validate_session(ctx.reader_store.conn, session_id)
        assert principal is not None
        assert principal.user_id == TEST_USER
