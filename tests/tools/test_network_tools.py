"""Tests for tools/network_tools.py — web_fetch and web_search closures (B4-2/B4-3).

All tests use mocked transports or provider clients; no real network egress in CI.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from orchestrator.mcp.execution import MAX_RESULT_BYTES
from orchestrator.tools.executor import LocalToolOutput
from orchestrator.tools.local import LocalToolError
from orchestrator.tools.net_trust import _SSRFValidatingTransport
from orchestrator.tools.network_tools import (
    _NetworkToolFn,
    build_network_tool_registry,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(
    status_code: int = 200,
    content: bytes = b"hello world",
    url: str = "https://example.com/",
) -> MagicMock:
    """Build a mock httpx.Response with iter_bytes() returning content in one chunk."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.url = url
    resp.iter_bytes.return_value = iter([content])
    return resp


def _make_mock_ssrf_transport(response: MagicMock) -> MagicMock:
    """Return a mock _SSRFValidatingTransport.handle_request that returns response."""
    transport = MagicMock(spec=_SSRFValidatingTransport)
    transport.handle_request.return_value = response
    # Support context manager usage (with client: ...)
    transport.__enter__ = MagicMock(return_value=transport)
    transport.__exit__ = MagicMock(return_value=False)
    return transport


# ---------------------------------------------------------------------------
# Section 1: _NetworkToolFn marker
# ---------------------------------------------------------------------------


def test_network_tool_fn_marker() -> None:
    """_NetworkToolFn carries _is_network_tool = True (executor cap marker)."""
    fn = _NetworkToolFn(lambda params: LocalToolOutput(""))
    assert getattr(fn, "_is_network_tool", False) is True


def test_registry_returns_network_tool_fn() -> None:
    """build_network_tool_registry returns _NetworkToolFn for both tools."""
    registry = build_network_tool_registry()
    for name in ("web_fetch", "web_search"):
        fn = registry[name]
        assert isinstance(fn, _NetworkToolFn), f"{name} should be _NetworkToolFn"
        assert getattr(fn, "_is_network_tool", False) is True


# ---------------------------------------------------------------------------
# Section 2: web_fetch — param validation
# ---------------------------------------------------------------------------


def test_web_fetch_disallowed_param_rejected() -> None:
    """Disallowed params (headers, method, auth, body) → LocalToolError."""
    registry = build_network_tool_registry()
    web_fetch = registry["web_fetch"]
    with pytest.raises(LocalToolError, match="disallowed param"):
        web_fetch({"url": "https://example.com/", "headers": {}})


def test_web_fetch_missing_url_rejected() -> None:
    """Missing 'url' → LocalToolError."""
    registry = build_network_tool_registry()
    web_fetch = registry["web_fetch"]
    with pytest.raises(LocalToolError):
        web_fetch({})


def test_web_fetch_file_scheme_rejected() -> None:
    """file:// scheme → LocalToolError(fetch_failed:)."""
    registry = build_network_tool_registry()
    web_fetch = registry["web_fetch"]
    with pytest.raises(LocalToolError, match=r"(fetch_failed:|scheme_rejected:)"):
        web_fetch({"url": "file:///etc/passwd"})


# ---------------------------------------------------------------------------
# Section 3: web_fetch — happy path (mocked transport)
# ---------------------------------------------------------------------------


@patch("orchestrator.tools.network_tools.build_ssrf_client")
def test_web_fetch_happy_path(mock_build_client: MagicMock) -> None:
    """200 response → LocalToolOutput with status + body; TOOL_RESULT not TOOL_FAILED."""
    body = b"<html>hello</html>"
    mock_resp = _mock_response(status_code=200, content=body)

    mock_client = MagicMock()
    mock_client.build_request.return_value = MagicMock()
    mock_client.send.return_value = mock_resp
    mock_build_client.return_value = mock_client

    registry = build_network_tool_registry()
    result = registry["web_fetch"]({"url": "https://example.com/"})

    assert isinstance(result, LocalToolOutput)
    assert "200" in result.content
    assert "hello" in result.content
    assert result.output_truncated_at is None


@patch("orchestrator.tools.network_tools.build_ssrf_client")
def test_web_fetch_non_200_is_tool_result_not_failure(mock_build_client: MagicMock) -> None:
    """404/500 → LocalToolOutput (not TOOL_FAILED) — expected output the agent must see."""
    for status in (404, 500):
        mock_resp = _mock_response(status_code=status, content=b"not found")
        mock_client = MagicMock()
        mock_client.build_request.return_value = MagicMock()
        mock_client.send.return_value = mock_resp
        mock_build_client.return_value = mock_client

        registry = build_network_tool_registry()
        result = registry["web_fetch"]({"url": "https://example.com/"})
        assert isinstance(result, LocalToolOutput), f"HTTP {status} should be TOOL_RESULT"
        assert str(status) in result.content


@patch("orchestrator.tools.network_tools.build_ssrf_client")
def test_web_fetch_over_size_truncated(mock_build_client: MagicMock) -> None:
    """Response over MAX_RESULT_BYTES → truncated + output_truncated_at set."""
    oversized = b"x" * (MAX_RESULT_BYTES + 100)
    mock_resp = _mock_response(status_code=200, content=oversized)
    mock_client = MagicMock()
    mock_client.build_request.return_value = MagicMock()
    mock_client.send.return_value = mock_resp
    mock_build_client.return_value = mock_client

    registry = build_network_tool_registry()
    result = registry["web_fetch"]({"url": "https://example.com/"})

    assert result.output_truncated_at == MAX_RESULT_BYTES
    # Content should be truncated
    body_part = result.content.split("\n\n", 1)[1] if "\n\n" in result.content else result.content
    assert len(body_part.encode()) <= MAX_RESULT_BYTES + 10  # small tolerance for header lines


@patch("orchestrator.tools.network_tools.build_ssrf_client")
def test_web_fetch_internal_url_ssrf_blocked(mock_build_client: MagicMock) -> None:
    """Internal URL → LocalToolError(ssrf_blocked:) from the transport."""
    mock_client = MagicMock()
    mock_client.build_request.return_value = MagicMock()
    mock_client.send.side_effect = LocalToolError("ssrf_blocked: 10.0.0.1 is denied")
    mock_build_client.return_value = mock_client

    registry = build_network_tool_registry()
    with pytest.raises(LocalToolError, match="ssrf_blocked:"):
        registry["web_fetch"]({"url": "http://internal.corp/"})


@patch("orchestrator.tools.network_tools.build_ssrf_client")
def test_web_fetch_redirect_to_internal_ssrf_blocked(mock_build_client: MagicMock) -> None:
    """Redirect to internal URL → ssrf_blocked (transport re-validates each hop)."""
    mock_client = MagicMock()
    mock_client.build_request.return_value = MagicMock()
    mock_client.send.side_effect = LocalToolError(
        "ssrf_blocked: redirect target 169.254.169.254 is denied"
    )
    mock_build_client.return_value = mock_client

    registry = build_network_tool_registry()
    with pytest.raises(LocalToolError, match="ssrf_blocked:"):
        registry["web_fetch"]({"url": "https://public.example.com/redirect"})


# ---------------------------------------------------------------------------
# Section 4: web_search — param validation + fail-closed
# ---------------------------------------------------------------------------


def test_web_search_not_configured_fail_closed() -> None:
    """No provider config / missing BRAVE_API_KEY → LocalToolError(not configured)."""
    with patch.dict("os.environ", {}, clear=False):
        # Ensure BRAVE_API_KEY is not set
        import os

        os.environ.pop("BRAVE_API_KEY", None)
        registry = build_network_tool_registry()
    with pytest.raises(LocalToolError, match="not configured"):
        registry["web_search"]({"query": "test"})


def test_web_search_disallowed_param_rejected() -> None:
    """Disallowed params → LocalToolError."""

    with patch.dict("os.environ", {"BRAVE_API_KEY": "test-key"}):
        registry = build_network_tool_registry()
    with pytest.raises(LocalToolError, match="disallowed param"):
        registry["web_search"]({"query": "test", "sort": "date"})


def test_web_search_missing_query_rejected() -> None:
    """Missing 'query' → LocalToolError."""
    with patch.dict("os.environ", {"BRAVE_API_KEY": "test-key"}):
        registry = build_network_tool_registry()
    with pytest.raises(LocalToolError):
        registry["web_search"]({"max_results": 5})


def test_web_search_max_results_clamped() -> None:
    """max_results clamped to [1, 20]."""
    with patch.dict("os.environ", {"BRAVE_API_KEY": "test-key"}):
        registry = build_network_tool_registry()

    brave_response = {
        "web": {
            "results": [
                {"title": f"Result {i}", "url": f"https://example.com/{i}", "description": ""}
                for i in range(5)
            ]
        }
    }

    with patch("httpx.Client") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = brave_response
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client_instance

        # max_results=999 → clamped to 20
        registry["web_search"]({"query": "test", "max_results": 999})
        call_kwargs = mock_client_instance.get.call_args[1]
        assert call_kwargs["params"]["count"] == 20

        # max_results=0 → clamped to 1
        mock_client_instance.get.reset_mock()
        registry["web_search"]({"query": "test", "max_results": 0})
        call_kwargs = mock_client_instance.get.call_args[1]
        assert call_kwargs["params"]["count"] == 1


# ---------------------------------------------------------------------------
# Section 5: web_search — happy path (mocked Brave client)
# ---------------------------------------------------------------------------


def test_web_search_happy_path_formats_results() -> None:
    """Brave response web.results[] → formatted title + URL + snippet per hit."""
    brave_response = {
        "web": {
            "results": [
                {
                    "title": "Example Page",
                    "url": "https://example.com/page",
                    "description": "A test page.",
                },
                {
                    "title": "Other Page",
                    "url": "https://other.com/",
                    "description": "Another page.",
                },
            ]
        }
    }

    with patch.dict("os.environ", {"BRAVE_API_KEY": "test-key"}):
        registry = build_network_tool_registry()

    with patch("httpx.Client") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = brave_response
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client_instance

        result = registry["web_search"]({"query": "test"})

    assert isinstance(result, LocalToolOutput)
    assert "Example Page" in result.content
    assert "https://example.com/page" in result.content
    assert "A test page." in result.content
    assert result.output_truncated_at is None


def test_web_search_api_key_only_in_brave_header() -> None:
    """API key reaches ONLY the Brave endpoint's X-Subscription-Token header.

    The key must not appear in query params, URL, or response content.
    """
    secret_key = "super-secret-brave-key-12345"
    with patch.dict("os.environ", {"BRAVE_API_KEY": secret_key}):
        registry = build_network_tool_registry()

    with patch("httpx.Client") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"web": {"results": []}}
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client_instance

        result = registry["web_search"]({"query": "test"})

    # Key must appear in headers (X-Subscription-Token)
    get_call_kwargs = mock_client_instance.get.call_args[1]
    assert get_call_kwargs["headers"]["X-Subscription-Token"] == secret_key

    # Key must NOT be in query params
    params = get_call_kwargs["params"]
    param_str = json.dumps(params)
    assert secret_key not in param_str

    # Key must NOT appear in the output content
    assert secret_key not in result.content


def test_web_search_provider_5xx_raises() -> None:
    """Provider 5xx → LocalToolError(search_provider_error:)."""
    with patch.dict("os.environ", {"BRAVE_API_KEY": "key"}):
        registry = build_network_tool_registry()

    with patch("httpx.Client") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client_instance

        with pytest.raises(LocalToolError, match="search_provider_error:"):
            registry["web_search"]({"query": "test"})


# ---------------------------------------------------------------------------
# Section 6: web_search provider config from YAML
# ---------------------------------------------------------------------------


def test_web_search_config_from_yaml(tmp_path: Path) -> None:
    """Provider config loaded from YAML; api_key_env pattern used."""
    config = tmp_path / "web_search.yaml"
    config.write_text("provider: brave\napi_key_env: MY_BRAVE_KEY\n")

    with patch.dict("os.environ", {"MY_BRAVE_KEY": "yaml-configured-key"}):
        registry = build_network_tool_registry(web_search_config_path=config)

    with patch("httpx.Client") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"web": {"results": []}}
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client_instance

        registry["web_search"]({"query": "hello"})

    get_kwargs = mock_client_instance.get.call_args[1]
    assert get_kwargs["headers"]["X-Subscription-Token"] == "yaml-configured-key"


def test_web_search_missing_config_file_fail_closed(tmp_path: Path) -> None:
    """Missing config file → fail-closed (no key → not configured)."""
    absent = tmp_path / "nonexistent.yaml"
    with patch.dict("os.environ", {}, clear=False):
        import os

        os.environ.pop("BRAVE_API_KEY", None)
        registry = build_network_tool_registry(web_search_config_path=absent)
    with pytest.raises(LocalToolError, match="not configured"):
        registry["web_search"]({"query": "test"})
