"""API acceptance tests for plugin management endpoints (P4.7-BE-T4).

ADR-038 D5 + ADR-039 D5/D9 — boot-only plugin management routes.

pm1  — happy admit → entry in config/plugins.yaml; GET lists it.
pm2  — enable/disable flips enabled field; GET reflects change.
pm3  — DELETE removes entry; subsequent GET omits it; DELETE again → 404.
pm4  — first write: config/plugins.yaml absent → authored on first admit.
pm5  — boot-only: after write, ctx agent/tool registries unchanged (next-restart signal).
pm6  — unauth → 401 on every route (GET + all writes).
pm7  — refuse-all-rejected: write that would fail round-trip → rejected, file unchanged.
pm8  — forge: admit extra body field → 422; no body-supplied principal.
pm9  — provenance fallback G3: admitted entry not on disk → declared-not-yet-on-disk.
pm10 — provenance operator-placed (pending): no source_url/digest + not on disk.
pm11 — provenance operator_placed: entry with id dir under sandbox_root/plugins/.
pm12 — provenance fetched: entry with id dir under sandbox_root/fetched_plugins/.
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from orchestrator.agents.dispatch import LLMRouterProtocol
from orchestrator.api.app import AppContext, _make_test_app
from orchestrator.api.auth.session import create_token
from orchestrator.api.auth.users import create_user, init_auth_schema
from orchestrator.api.pubsub import RoomEventBus
from orchestrator.core.event_store import EventStore
from orchestrator.llm.types import (
    LLMResponse,
    ModelId,
    ProviderId,
    RequestId,
    Usage,
)
from orchestrator.plugins.provenance import load_plugin_registry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEST_USER = "testuser"
_TEST_PW = "test-pw"


def _mock_router() -> MagicMock:
    router = MagicMock(spec=LLMRouterProtocol)
    router.call.return_value = LLMResponse(
        request_id=RequestId("mock-req-1"),
        content="ok",
        tool_calls=[],
        model_id_requested=ModelId("mock-model"),
        model_id_used=ModelId("mock-model"),
        provider_id_used=ProviderId("mock"),
        usage=Usage(input_tokens=1, output_tokens=1, cost_usd=None),
        latency_ms=0,
        finish_reason="stop",
    )
    return router


def _make_store(db_path: Any) -> EventStore:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    store = EventStore(conn)
    store.init_schema()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.commit()
    init_auth_schema(conn)
    create_user(conn, _TEST_USER, _TEST_PW)
    return store


def _make_ctx(db_path: Any, config_dir: Path) -> AppContext:
    writer_store = _make_store(db_path)
    reader_conn = sqlite3.connect(str(db_path), check_same_thread=False)
    reader_store = EventStore(reader_conn)
    return AppContext(
        writer_store=writer_store,
        reader_store=reader_store,
        writer_executor=ThreadPoolExecutor(max_workers=1, thread_name_prefix="test-writer"),
        reader_executor=ThreadPoolExecutor(max_workers=2, thread_name_prefix="test-reader"),
        bus=RoomEventBus(),
        available_agents={},
        available_skills={},
        regex_registry={},
        tools={},
        llm_router=_mock_router(),
        config_dir=config_dir,
        sandbox_root=config_dir.parent,  # tmp_path — isolated per test
    )


def _auth_headers(ctx: AppContext) -> dict[str, str]:
    raw_token = create_token(ctx.writer_store.conn, _TEST_USER)
    return {"Authorization": f"Bearer {raw_token}"}


# ---------------------------------------------------------------------------
# pm1 — happy admit → entry persisted; GET lists it
# ---------------------------------------------------------------------------


def test_pm1_admit_and_get(tmp_path: pytest.TempPathFactory) -> None:
    config_dir = Path(str(tmp_path)) / "config"
    config_dir.mkdir()
    db = config_dir / "test.db"
    ctx = _make_ctx(db, config_dir)
    app = _make_test_app(ctx)
    headers = _auth_headers(ctx)

    with TestClient(app, raise_server_exceptions=True) as client:
        r = client.post(
            "/plugins/my_plugin/admit",
            json={
                "source_url": "https://example.com/p.zip",
                "digest": "sha256:abc",
                "version": "1.0",
            },
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["effect"] == "next_restart"

        registry = load_plugin_registry(config_dir / "plugins.yaml")
        assert "my_plugin" in registry
        assert registry["my_plugin"].source_url == "https://example.com/p.zip"

        r2 = client.get("/plugins", headers=headers)
        assert r2.status_code == 200
        items = {item["plugin_id"]: item for item in r2.json()}
        assert "my_plugin" in items
        assert items["my_plugin"]["fetched"] is True
        assert items["my_plugin"]["version"] == "1.0"


# ---------------------------------------------------------------------------
# pm2 — enable/disable flips enabled; GET reflects change
# ---------------------------------------------------------------------------


def test_pm2_enable_disable(tmp_path: pytest.TempPathFactory) -> None:
    config_dir = Path(str(tmp_path)) / "config"
    config_dir.mkdir()
    db = config_dir / "test.db"
    ctx = _make_ctx(db, config_dir)
    app = _make_test_app(ctx)
    headers = _auth_headers(ctx)

    with TestClient(app, raise_server_exceptions=True) as client:
        # Admit first
        client.post(
            "/plugins/p/admit",
            json={"source_url": "https://x.com/p.zip", "digest": "sha256:111"},
            headers=headers,
        )

        r = client.post("/plugins/p/disable", headers=headers)
        assert r.status_code == 200
        assert r.json()["effect"] == "next_restart"

        r2 = client.get("/plugins", headers=headers)
        items = {x["plugin_id"]: x for x in r2.json()}
        assert items["p"]["enabled"] is False

        client.post("/plugins/p/enable", headers=headers)
        r3 = client.get("/plugins", headers=headers)
        items3 = {x["plugin_id"]: x for x in r3.json()}
        assert items3["p"]["enabled"] is True


# ---------------------------------------------------------------------------
# pm3 — DELETE removes entry; DELETE absent → 404
# ---------------------------------------------------------------------------


def test_pm3_delete(tmp_path: pytest.TempPathFactory) -> None:
    config_dir = Path(str(tmp_path)) / "config"
    config_dir.mkdir()
    db = config_dir / "test.db"
    ctx = _make_ctx(db, config_dir)
    app = _make_test_app(ctx)
    headers = _auth_headers(ctx)

    with TestClient(app, raise_server_exceptions=False) as client:
        client.post(
            "/plugins/todelete/admit",
            json={"source_url": "https://x.com/x.zip", "digest": "sha256:xyz"},
            headers=headers,
        )

        r = client.delete("/plugins/todelete", headers=headers)
        assert r.status_code == 200
        assert r.json()["effect"] == "next_restart"

        r2 = client.get("/plugins", headers=headers)
        assert not any(x["plugin_id"] == "todelete" for x in r2.json())

        # Second delete → 404
        r3 = client.delete("/plugins/todelete", headers=headers)
        assert r3.status_code == 404


# ---------------------------------------------------------------------------
# pm4 — first write creates config/plugins.yaml
# ---------------------------------------------------------------------------


def test_pm4_first_write_creates_file(tmp_path: pytest.TempPathFactory) -> None:
    config_dir = Path(str(tmp_path)) / "config"
    config_dir.mkdir()
    db = config_dir / "test.db"
    ctx = _make_ctx(db, config_dir)
    app = _make_test_app(ctx)
    headers = _auth_headers(ctx)

    plugins_yaml = config_dir / "plugins.yaml"
    assert not plugins_yaml.exists()

    with TestClient(app, raise_server_exceptions=True) as client:
        r = client.post(
            "/plugins/newplugin/admit",
            json={"source_url": "https://s.com/n.zip", "digest": "sha256:n"},
            headers=headers,
        )
        assert r.status_code == 200

    assert plugins_yaml.exists()
    assert "newplugin" in load_plugin_registry(plugins_yaml)


# ---------------------------------------------------------------------------
# pm5 — boot-only: running ctx unchanged after write; response is next_restart
# ---------------------------------------------------------------------------


def test_pm5_boot_only_no_live_mutation(tmp_path: pytest.TempPathFactory) -> None:
    config_dir = Path(str(tmp_path)) / "config"
    config_dir.mkdir()
    db = config_dir / "test.db"
    ctx = _make_ctx(db, config_dir)
    app = _make_test_app(ctx)
    headers = _auth_headers(ctx)

    agents_before = dict(ctx.available_agents)
    tools_before = dict(ctx.tools)

    with TestClient(app, raise_server_exceptions=True) as client:
        r = client.post(
            "/plugins/bootonly/admit",
            json={"source_url": "https://b.com/b.zip", "digest": "sha256:b"},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json() == {"effect": "next_restart"}

    # Live AppContext unchanged — no load_plugins re-run
    assert ctx.available_agents == agents_before
    assert ctx.tools == tools_before


# ---------------------------------------------------------------------------
# pm6 — unauth → 401 on every route (GET + all four write routes)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/plugins", None),
        ("POST", "/plugins/p/enable", None),
        ("POST", "/plugins/p/disable", None),
        (
            "POST",
            "/plugins/p/admit",
            {"source_url": "https://x.com/x.zip", "digest": "sha256:x"},
        ),
        ("DELETE", "/plugins/p", None),
    ],
)
def test_pm6_unauth_401(
    tmp_path: pytest.TempPathFactory,
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    config_dir = Path(str(tmp_path)) / "config"
    config_dir.mkdir()
    db = config_dir / "test.db"
    ctx = _make_ctx(db, config_dir)
    app = _make_test_app(ctx)

    with TestClient(app, raise_server_exceptions=False) as client:
        fn = getattr(client, method.lower())
        kwargs: dict[str, Any] = {}
        if body is not None:
            kwargs["json"] = body
        r = fn(path, **kwargs)  # no auth headers
        assert r.status_code == 401, f"{method} {path} → {r.status_code}"


# ---------------------------------------------------------------------------
# pm7 — refuse-all-rejected: round-trip failure → rejected, file unchanged
# ---------------------------------------------------------------------------


def test_pm7_refuse_all_rejected(tmp_path: pytest.TempPathFactory) -> None:
    config_dir = Path(str(tmp_path)) / "config"
    config_dir.mkdir()
    db = config_dir / "test.db"
    ctx = _make_ctx(db, config_dir)
    app = _make_test_app(ctx)
    headers = _auth_headers(ctx)

    # Seed an existing valid registry
    from orchestrator.plugins.provenance import PluginRegistry, RegistryEntry, write_plugin_registry

    original: PluginRegistry = {
        "existing": RegistryEntry(plugin_id="existing", enabled=True)
    }
    write_plugin_registry(config_dir / "plugins.yaml", original)
    original_text = (config_dir / "plugins.yaml").read_text()

    from orchestrator.llm.exceptions import ConfigError

    with TestClient(app, raise_server_exceptions=False) as client:
        with patch(
            "orchestrator.plugins.provenance.load_plugin_registry",
            side_effect=ConfigError("simulated bad round-trip"),
        ):
            r = client.post(
                "/plugins/bad/admit",
                json={"source_url": "https://b.com/b.zip", "digest": "sha256:b"},
                headers=headers,
            )
        assert r.status_code >= 400

    assert (config_dir / "plugins.yaml").read_text() == original_text


# ---------------------------------------------------------------------------
# pm8 — forge: admit extra field → 422; principal never from body
# ---------------------------------------------------------------------------


def test_pm8_forge_extra_field_rejected(tmp_path: pytest.TempPathFactory) -> None:
    config_dir = Path(str(tmp_path)) / "config"
    config_dir.mkdir()
    db = config_dir / "test.db"
    ctx = _make_ctx(db, config_dir)
    app = _make_test_app(ctx)
    headers = _auth_headers(ctx)

    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.post(
            "/plugins/p/admit",
            json={
                "source_url": "https://x.com/x.zip",
                "digest": "sha256:x",
                "evil_extra": "injected",
            },
            headers=headers,
        )
        assert r.status_code == 422


def test_pm8_admit_no_digest_rejected(tmp_path: pytest.TempPathFactory) -> None:
    config_dir = Path(str(tmp_path)) / "config"
    config_dir.mkdir()
    db = config_dir / "test.db"
    ctx = _make_ctx(db, config_dir)
    app = _make_test_app(ctx)
    headers = _auth_headers(ctx)

    with TestClient(app, raise_server_exceptions=False) as client:
        # Missing digest — Pydantic will reject; also writer round-trip would reject a
        # partial source_url-only entry (source_url+digest must come as a pair).
        r = client.post(
            "/plugins/p/admit",
            json={"source_url": "https://x.com/x.zip"},
            headers=headers,
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# pm9 — provenance fallback G3: fetched intent, not yet on disk
# ---------------------------------------------------------------------------


def test_pm9_provenance_fallback_fetched_pending(tmp_path: pytest.TempPathFactory) -> None:
    config_dir = Path(str(tmp_path)) / "config"
    config_dir.mkdir()
    db = config_dir / "test.db"
    # sandbox_root = config_dir.parent (tmp_path), so plugins/ and fetched_plugins/ live there
    ctx = _make_ctx(db, config_dir)
    app = _make_test_app(ctx)
    headers = _auth_headers(ctx)

    with TestClient(app, raise_server_exceptions=True) as client:
        client.post(
            "/plugins/fetched_p/admit",
            json={"source_url": "https://x.com/f.zip", "digest": "sha256:f"},
            headers=headers,
        )
        # Do NOT place bytes under sandbox_root/fetched_plugins/fetched_p
        r = client.get("/plugins", headers=headers)
        assert r.status_code == 200
        items = {x["plugin_id"]: x for x in r.json()}
        assert "fetched_p" in items
        assert items["fetched_p"]["provenance"] == "declared-not-yet-on-disk"
        assert items["fetched_p"]["provenance_kind"] == "fetched (pending)"


# ---------------------------------------------------------------------------
# pm10 — provenance fallback: operator-placed intent, not on disk
# ---------------------------------------------------------------------------


def test_pm10_provenance_fallback_opplaced_pending(tmp_path: pytest.TempPathFactory) -> None:
    config_dir = Path(str(tmp_path)) / "config"
    config_dir.mkdir()
    db = config_dir / "test.db"
    ctx = _make_ctx(db, config_dir)
    app = _make_test_app(ctx)
    headers = _auth_headers(ctx)

    with TestClient(app, raise_server_exceptions=True) as client:
        # Enable a plugin with no source_url/digest (operator-placed intent)
        client.post("/plugins/op_p/enable", headers=headers)
        r = client.get("/plugins", headers=headers)
        assert r.status_code == 200
        items = {x["plugin_id"]: x for x in r.json()}
        assert "op_p" in items
        assert items["op_p"]["provenance"] == "declared-not-yet-on-disk"
        assert items["op_p"]["provenance_kind"] == "operator-placed (pending)"
        assert items["op_p"]["fetched"] is False


# ---------------------------------------------------------------------------
# pm11 — provenance operator_placed: id dir under sandbox_root/plugins/
# ---------------------------------------------------------------------------


def test_pm11_provenance_operator_placed(tmp_path: pytest.TempPathFactory) -> None:
    config_dir = Path(str(tmp_path)) / "config"
    config_dir.mkdir()
    db = config_dir / "test.db"
    ctx = _make_ctx(db, config_dir)
    # sandbox_root = config_dir.parent (tmp_path); place plugin dir there
    (ctx.sandbox_root / "plugins" / "placed_p").mkdir(parents=True)
    app = _make_test_app(ctx)
    headers = _auth_headers(ctx)

    with TestClient(app, raise_server_exceptions=True) as client:
        client.post("/plugins/placed_p/enable", headers=headers)
        r = client.get("/plugins", headers=headers)
        items = {x["plugin_id"]: x for x in r.json()}
        assert items["placed_p"]["provenance"] == "operator_placed"
        assert items["placed_p"]["provenance_kind"] is None


# ---------------------------------------------------------------------------
# pm12 — provenance fetched: id dir under sandbox_root/fetched_plugins/
# ---------------------------------------------------------------------------


def test_pm12_provenance_fetched(tmp_path: pytest.TempPathFactory) -> None:
    config_dir = Path(str(tmp_path)) / "config"
    config_dir.mkdir()
    db = config_dir / "test.db"
    ctx = _make_ctx(db, config_dir)
    (ctx.sandbox_root / "fetched_plugins" / "fetched_q").mkdir(parents=True)
    app = _make_test_app(ctx)
    headers = _auth_headers(ctx)

    with TestClient(app, raise_server_exceptions=True) as client:
        client.post(
            "/plugins/fetched_q/admit",
            json={"source_url": "https://y.com/q.zip", "digest": "sha256:q"},
            headers=headers,
        )
        r = client.get("/plugins", headers=headers)
        items = {x["plugin_id"]: x for x in r.json()}
        assert items["fetched_q"]["provenance"] == "fetched"
        assert items["fetched_q"]["provenance_kind"] is None
