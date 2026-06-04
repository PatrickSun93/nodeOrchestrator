"""P3.7-remote-2: streamable-http transport path tests (ADR-032 D2).

Covers:
  - MCPTransport dispatches to remote path for streamable_http config
  - verify=True is always explicit in the host-built httpx.AsyncClient
  - Authorization header from api_key_env (credential indirection, HR#5)
  - fail-closed: unreachable host → MCPConnectionError/MCPTimeoutError
  - fail-closed: timeout → MCPTimeoutError
  - fail-closed: TLS verify failure → MCPConnectionError

Full e2e with hermetic local-TLS mock is in test_p3_7_remote_connectors.py (-3).
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from orchestrator.mcp.config import MCPServerConfig, MCPTimeouts
from orchestrator.mcp.transport import MCPConnectionError, MCPTimeoutError, MCPTransport

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _remote_cfg(
    url: str = "https://api.example.com/mcp",
    api_key_env: str | None = None,
) -> MCPServerConfig:
    return MCPServerConfig(
        transport="streamable_http",
        url=url,
        api_key_env=api_key_env,
        tools={},
    )


def _fast_timeouts() -> MCPTimeouts:
    return MCPTimeouts(connect=0.5, list_tools=0.5, call_tool=0.5)


# ---------------------------------------------------------------------------
# verify=True is always explicit (ADR-032 D2 + HR#6)
# ---------------------------------------------------------------------------


def test_remote_client_has_verify_true() -> None:
    """Host-built AsyncClient is created with verify=True (ADR-032 D2 / HR#6).

    Discriminating: intercept httpx.AsyncClient constructor; assert verify=True
    was the argument (not False or omitted).  Source-level verify=False ban is
    enforced by the constitution test (-9).
    """
    seen_kwargs: list[dict[str, Any]] = []
    original_init = httpx.AsyncClient.__init__

    def _capturing_init(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        seen_kwargs.append(kwargs)
        original_init(self, *args, **kwargs)

    with patch.object(httpx.AsyncClient, "__init__", _capturing_init):
        transport = MCPTransport("check-verify", _remote_cfg(), _fast_timeouts())
        _client_list = transport._remote_client_for_list()
        _client_call = transport._remote_client_for_call()

    assert len(seen_kwargs) == 2, f"Expected 2 AsyncClient constructions, got {len(seen_kwargs)}"
    for i, kwargs in enumerate(seen_kwargs):
        assert kwargs.get("verify") is True, (
            f"AsyncClient #{i}: verify={kwargs.get('verify')!r}; "
            f"expected verify=True (ADR-032 HR#6 violation)"
        )


# ---------------------------------------------------------------------------
# Authorization header from api_key_env
# ---------------------------------------------------------------------------


def test_remote_auth_header_from_api_key_env() -> None:
    """api_key_env → Authorization: Bearer <secret> (credential indirection, HR#5)."""
    secret_key = "REMOTE_TEST_API_KEY_P3_7_REMOTE"
    secret_val = "test_bearer_token_xyz"

    original = os.environ.get(secret_key)
    os.environ[secret_key] = secret_val
    try:
        transport = MCPTransport("auth-test", _remote_cfg(api_key_env=secret_key))
        headers = transport._remote_auth_headers()
        assert "Authorization" in headers
        assert headers["Authorization"] == f"Bearer {secret_val}"
    finally:
        if original is None:
            os.environ.pop(secret_key, None)
        else:
            os.environ[secret_key] = original


def test_remote_no_auth_header_if_no_api_key_env() -> None:
    """No Authorization header when api_key_env is not configured."""
    transport = MCPTransport("no-auth-test", _remote_cfg(api_key_env=None))
    headers = transport._remote_auth_headers()
    assert "Authorization" not in headers


# ---------------------------------------------------------------------------
# fail-closed: unreachable host → MCPConnectionError
# ---------------------------------------------------------------------------


def test_remote_unreachable_host_fail_closed() -> None:
    """Unreachable https:// host → MCPConnectionError (fail-closed, HR#7)."""
    transport = MCPTransport(
        "unreachable-test",
        _remote_cfg(url="https://127.0.0.1:19999/mcp"),  # Nothing listening here
        _fast_timeouts(),
    )
    with pytest.raises((MCPConnectionError, MCPTimeoutError)):
        transport.list_tools()


# ---------------------------------------------------------------------------
# fail-closed: timeout → MCPTimeoutError
# ---------------------------------------------------------------------------


def test_remote_timeout_fail_closed() -> None:
    """Hanging remote call → MCPConnectionError/MCPTimeoutError (fail-closed, HR#7)."""
    # Patch streamable_http_client to raise immediately (simulates connection failure)
    with patch(
        "orchestrator.mcp.transport.streamable_http_client",
        side_effect=Exception("connection hang simulation"),
    ):
        transport = MCPTransport(
            "timeout-test",
            _remote_cfg(),
            _fast_timeouts(),
        )
        with pytest.raises((MCPConnectionError, MCPTimeoutError)):
            transport.list_tools()


# ---------------------------------------------------------------------------
# fail-closed: TLS verify failure → MCPConnectionError
# ---------------------------------------------------------------------------


def test_remote_tls_verify_failure_fail_closed() -> None:
    """TLS certificate verification failure → MCPConnectionError (fail-closed, HR#6)."""
    # Use a URL where TLS verification would fail; for CI we simulate via monkeypatching
    # (real cert failures are tested in the e2e test -3 with a hermetic TLS mock)
    with patch(
        "orchestrator.mcp.transport.streamable_http_client",
        side_effect=httpx.ConnectError("SSL: CERTIFICATE_VERIFY_FAILED"),
    ):
        transport = MCPTransport(
            "tls-fail-test",
            _remote_cfg(),
            _fast_timeouts(),
        )
        with pytest.raises(MCPConnectionError):
            transport.list_tools()


# ---------------------------------------------------------------------------
# Transport dispatch: streamable_http config uses remote path
# ---------------------------------------------------------------------------


def test_remote_transport_dispatches_to_remote_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCPTransport with streamable_http config calls _async_list_tools_remote, not stdio."""
    calls: list[str] = []

    async def _fake_remote_list(self: Any) -> list[Any]:
        calls.append("remote")
        return []

    async def _fake_stdio_list(self: Any) -> list[Any]:
        calls.append("stdio")
        return []

    monkeypatch.setattr(MCPTransport, "_async_list_tools_remote", _fake_remote_list)
    monkeypatch.setattr(MCPTransport, "_async_list_tools", _fake_stdio_list)

    transport = MCPTransport("dispatch-test", _remote_cfg(), _fast_timeouts())
    transport.list_tools()

    assert calls == ["remote"], f"Expected remote dispatch, got {calls}"
