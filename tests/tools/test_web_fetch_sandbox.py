"""P4.3-8 tests: web_fetch egress routes through sandbox when available.

Tests: egress routes through sandbox; SSRF floor still rejects denied IPs;
fail-closed/degraded per posture.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from orchestrator.sandbox.posture import PostureResolver, SandboxConfig
from orchestrator.sandbox.runtime import SandboxRuntime
from orchestrator.tools.local import LocalToolError
from orchestrator.tools.network_tools import build_network_tool_registry


def _make_resolver(available: bool = True, degraded: bool = False) -> PostureResolver:
    config = SandboxConfig(image="sandbox:test", degraded_app_level=degraded)
    if available:
        rt = SandboxRuntime(kind="docker", cli="/usr/bin/docker")
        rt.available = mock.Mock(return_value=True)  # type: ignore[method-assign]
    else:
        rt = None
    return PostureResolver(config=config, runtime=rt)


# ---------------------------------------------------------------------------
# SANDBOXED: web_fetch routes through sandboxed_run
# ---------------------------------------------------------------------------


def test_web_fetch_calls_sandboxed_run_when_available(tmp_path: Path) -> None:
    resolver = _make_resolver(available=True)
    registry = build_network_tool_registry(posture_resolver=resolver, sandbox_root=tmp_path)
    fn = registry["web_fetch"]

    with (
        mock.patch("orchestrator.tools.net_trust._resolve_and_validate", return_value="1.2.3.4"),
        mock.patch("orchestrator.sandbox.spawn.sandboxed_run") as mock_sr,
    ):
        mock_sr.return_value = mock.Mock(
            exit_code=0, output="status=200\nurl=https://example.com\n\nhello", truncated=False
        )
        result = fn({"url": "https://example.com"})

    mock_sr.assert_called_once()
    assert result is not None


def test_web_fetch_sandboxed_result_preserved(tmp_path: Path) -> None:
    resolver = _make_resolver(available=True)
    registry = build_network_tool_registry(posture_resolver=resolver, sandbox_root=tmp_path)
    fn = registry["web_fetch"]

    with (
        mock.patch("orchestrator.tools.net_trust._resolve_and_validate", return_value="1.2.3.4"),
        mock.patch("orchestrator.sandbox.spawn.sandboxed_run") as mock_sr,
    ):
        mock_sr.return_value = mock.Mock(
            exit_code=0, output="status=200\nurl=https://example.com\n\nhello", truncated=False
        )
        result = fn({"url": "https://example.com"})

    assert "200" in result.content or "hello" in result.content


# ---------------------------------------------------------------------------
# SSRF floor still rejects denied IPs (defense-in-depth, not removed)
# ---------------------------------------------------------------------------


def test_ssrf_floor_still_rejects_loopback(tmp_path: Path) -> None:
    resolver = _make_resolver(available=True)
    registry = build_network_tool_registry(posture_resolver=resolver, sandbox_root=tmp_path)
    fn = registry["web_fetch"]

    with pytest.raises(LocalToolError, match="ssrf_blocked"):
        fn({"url": "http://127.0.0.1/"})


def test_ssrf_floor_still_rejects_private(tmp_path: Path) -> None:
    resolver = _make_resolver(available=True)
    registry = build_network_tool_registry(posture_resolver=resolver, sandbox_root=tmp_path)
    fn = registry["web_fetch"]

    with pytest.raises(LocalToolError, match="ssrf_blocked"):
        fn({"url": "http://192.168.1.1/"})


# ---------------------------------------------------------------------------
# FAIL_CLOSED: LocalToolError(sandbox_unavailable:…) when not opted-in
# ---------------------------------------------------------------------------


def test_web_fetch_fail_closed_when_unavailable(tmp_path: Path) -> None:
    resolver = _make_resolver(available=False, degraded=False)
    registry = build_network_tool_registry(posture_resolver=resolver, sandbox_root=tmp_path)
    fn = registry["web_fetch"]

    with (
        mock.patch("orchestrator.tools.net_trust._resolve_and_validate", return_value="1.2.3.4"),
        pytest.raises(LocalToolError, match="sandbox_unavailable"),
    ):
        fn({"url": "https://example.com"})


# ---------------------------------------------------------------------------
# DEGRADED: falls back to in-process SSRF httpx
# ---------------------------------------------------------------------------


def test_web_fetch_degraded_uses_inprocess_ssrf(tmp_path: Path) -> None:
    resolver = _make_resolver(available=False, degraded=True)
    registry = build_network_tool_registry(posture_resolver=resolver, sandbox_root=tmp_path)
    fn = registry["web_fetch"]

    with (
        mock.patch("orchestrator.tools.net_trust._resolve_and_validate", return_value="1.2.3.4"),
        mock.patch("orchestrator.tools.network_tools.build_ssrf_client") as mock_client,
    ):
        fake_resp = mock.Mock()
        fake_resp.status_code = 200
        fake_resp.url = "https://example.com"
        fake_resp.iter_bytes.return_value = [b"hello"]
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = mock.Mock(return_value=False)

        mock_client.return_value.__enter__ = lambda s: s
        mock_client.return_value.__exit__ = mock.Mock(return_value=False)
        mock_client.return_value.send.return_value = fake_resp
        mock_client.return_value.build_request.return_value = mock.Mock()

        # Degraded falls through to in-process; sandboxed_run is NOT called.
        with mock.patch("orchestrator.sandbox.spawn.sandboxed_run") as mock_sr:
            fn({"url": "https://example.com"})

        mock_sr.assert_not_called()


# ---------------------------------------------------------------------------
# No resolver: original in-process behavior
# ---------------------------------------------------------------------------


def test_web_fetch_no_resolver_uses_inprocess(tmp_path: Path) -> None:
    registry = build_network_tool_registry()
    fn = registry["web_fetch"]

    with mock.patch("orchestrator.tools.network_tools.build_ssrf_client") as mock_client:
        fake_resp = mock.Mock()
        fake_resp.status_code = 200
        fake_resp.url = "https://example.com"
        fake_resp.iter_bytes.return_value = [b"ok"]
        mock_client.return_value.__enter__ = lambda s: s
        mock_client.return_value.__exit__ = mock.Mock(return_value=False)
        mock_client.return_value.send.return_value = fake_resp
        mock_client.return_value.build_request.return_value = mock.Mock()
        fn({"url": "https://example.com"})

    mock_client.assert_called()
