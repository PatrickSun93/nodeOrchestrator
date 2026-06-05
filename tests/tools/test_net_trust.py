"""Tests for tools/net_trust.py — SSRF validator + resolve-then-pin transport (B4-1).

All tests use stubbed resolvers or mocked transports; no real network egress in CI.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from orchestrator.tools.local import LocalToolError
from orchestrator.tools.net_trust import (
    _CGNAT_NETWORK,
    DNS_RESOLVE_TIMEOUT_S,
    _resolve_and_validate,
    _SSRFValidatingTransport,
    build_ssrf_client,
    is_denied_ip,
)

# ---------------------------------------------------------------------------
# Section 1: is_denied_ip classifier — SSRF floor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "addr,expected",
    [
        # Loopback
        ("127.0.0.1", True),
        ("127.0.0.2", True),
        ("::1", True),
        # Private
        ("10.0.0.5", True),
        ("10.255.255.255", True),
        ("172.16.0.1", True),
        ("172.31.255.255", True),
        ("192.168.1.1", True),
        ("192.168.255.255", True),
        # CGNAT / shared address space (RFC 6598 — 100.64.0.0/10; A1)
        ("100.64.0.1", True),
        ("100.100.100.200", True),  # Alibaba Cloud metadata — must be denied (A1)
        ("100.127.255.255", True),
        # Link-local (incl. cloud-metadata 169.254.169.254)
        ("169.254.169.254", True),  # cloud metadata — must be denied
        ("169.254.0.1", True),
        ("fe80::1", True),
        # Unspecified
        ("0.0.0.0", True),
        ("::", True),
        # Multicast
        ("224.0.0.1", True),
        ("239.255.255.255", True),
        ("ff02::1", True),
        # IPv4-mapped IPv6 — loopback via mapping (bypass class)
        ("::ffff:127.0.0.1", True),
        ("::ffff:10.0.0.1", True),
        ("::ffff:192.168.1.1", True),
        # fc00::/7 (private IPv6)
        ("fc00::1", True),
        ("fdff::1", True),
        # Public — must be ALLOWED
        ("93.184.216.34", False),  # example.com
        ("8.8.8.8", False),
        ("1.1.1.1", False),
        ("2606:2800:220:1:248:1893:25c8:1946", False),  # example.com IPv6
    ],
)
def test_is_denied_ip_floor(addr: str, expected: bool) -> None:
    ip = ipaddress.ip_address(addr)
    assert is_denied_ip(ip) == expected, (
        f"is_denied_ip({addr!r}) expected {expected}, got {not expected}"
    )


def test_cgnat_network_constant() -> None:
    """100.64.0.0/10 covers 100.64.0.0 - 100.127.255.255 inclusive."""
    assert ipaddress.IPv4Address("100.64.0.0") in _CGNAT_NETWORK
    assert ipaddress.IPv4Address("100.100.100.200") in _CGNAT_NETWORK  # Alibaba
    assert ipaddress.IPv4Address("100.127.255.255") in _CGNAT_NETWORK
    # Just outside the range
    assert ipaddress.IPv4Address("100.63.255.255") not in _CGNAT_NETWORK
    assert ipaddress.IPv4Address("100.128.0.0") not in _CGNAT_NETWORK


# ---------------------------------------------------------------------------
# Section 2: scheme allowlist
# ---------------------------------------------------------------------------


def test_scheme_file_rejected() -> None:
    transport = _SSRFValidatingTransport()
    request = httpx.Request("GET", "file:///etc/passwd")
    with pytest.raises(LocalToolError, match="scheme_rejected:"):
        transport.handle_request(request)


def test_scheme_ftp_rejected() -> None:
    transport = _SSRFValidatingTransport()
    request = httpx.Request("GET", "ftp://example.com/")
    with pytest.raises(LocalToolError, match="scheme_rejected:"):
        transport.handle_request(request)


def test_scheme_gopher_rejected() -> None:
    transport = _SSRFValidatingTransport()
    request = httpx.Request("GET", "gopher://example.com/")
    with pytest.raises(LocalToolError, match="scheme_rejected:"):
        transport.handle_request(request)


# ---------------------------------------------------------------------------
# Section 3: DNS-based SSRF blocking
# ---------------------------------------------------------------------------


def _fake_getaddrs_internal(hostname: str, port: int) -> list[Any]:
    """Stub resolver: any hostname → 127.0.0.1 (simulates DNS rebind)."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]


def _fake_getaddrs_metadata(hostname: str, port: int) -> list[Any]:
    """Stub resolver: → cloud-metadata IP 169.254.169.254."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port))]


def _fake_getaddrs_public(hostname: str, port: int) -> list[Any]:
    """Stub resolver: → public IP 93.184.216.34 (example.com)."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


def _make_mock_exec(addrs: list[Any]) -> MagicMock:
    """Return a mock executor whose submit() returns a future resolving to addrs."""
    mock_future: MagicMock = MagicMock()
    mock_future.result.return_value = addrs
    mock_exec: MagicMock = MagicMock()
    mock_exec.submit.return_value = mock_future
    return mock_exec


def test_dns_rebind_loopback_blocked() -> None:
    """Stub resolver returning 127.0.0.1 → ssrf_blocked even if hostname looks public."""
    addrs = _fake_getaddrs_internal("public-looking.example.com", 80)
    with (
        patch("orchestrator.tools.net_trust._DNS_EXECUTOR", _make_mock_exec(addrs)),
        pytest.raises(LocalToolError, match="ssrf_blocked:"),
    ):
        _resolve_and_validate("public-looking.example.com", 80)


def test_dns_rebind_metadata_blocked() -> None:
    """Stub resolver returning 169.254.169.254 → ssrf_blocked."""
    addrs = _fake_getaddrs_metadata("public-looking.example.com", 80)
    with (
        patch("orchestrator.tools.net_trust._DNS_EXECUTOR", _make_mock_exec(addrs)),
        pytest.raises(LocalToolError, match="ssrf_blocked:"),
    ):
        _resolve_and_validate("public-looking.example.com", 80)


def test_multi_a_record_one_internal_blocked() -> None:
    """Multi-A-record where ANY IP is internal → ssrf_blocked (deny-if-any)."""
    addrs = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 80)),  # private
    ]
    with (
        patch("orchestrator.tools.net_trust._DNS_EXECUTOR", _make_mock_exec(addrs)),
        pytest.raises(LocalToolError, match="ssrf_blocked:"),
    ):
        _resolve_and_validate("mixed.example.com", 80)


def test_public_ip_allowed() -> None:
    """Public IP resolves without error; returns pinned IP string."""
    addrs = _fake_getaddrs_public("example.com", 80)
    with patch("orchestrator.tools.net_trust._DNS_EXECUTOR", _make_mock_exec(addrs)):
        pinned = _resolve_and_validate("example.com", 80)
    assert pinned == "93.184.216.34"


# ---------------------------------------------------------------------------
# Section 4: CNAME-chain-to-internal (A2)
# ---------------------------------------------------------------------------


def test_cname_chain_to_internal_blocked() -> None:
    """CNAME chain: evil.example.com → 169.254.169.254 → ssrf_blocked.

    getaddrinfo follows CNAMEs to final IPs; we validate the final resolved IP,
    so the CNAME-chain bypass is denied (A2 — permanent CNAME, distinct from
    TOCTOU rebind which is also covered).
    """
    addrs = [
        # getaddrinfo resolves the CNAME chain and returns the final IP
        (socket.AF_INET, socket.SOCK_STREAM, 6, "169.254.169.254", ("169.254.169.254", 443)),
    ]
    with (
        patch("orchestrator.tools.net_trust._DNS_EXECUTOR", _make_mock_exec(addrs)),
        pytest.raises(LocalToolError, match="ssrf_blocked:"),
    ):
        _resolve_and_validate("evil.example.com", 443)


# ---------------------------------------------------------------------------
# Section 5: IP-literal-encoding — via the REAL resolver (A3/Y3)
#
# These tests call socket.getaddrinfo directly (no mock) to prove the
# resolve-then-classify path normalises-then-denies on the implementation
# resolver. stubbed TRANSPORT so no actual HTTP connection is attempted.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://2130706433/",  # decimal: 127.0.0.1
        "http://0x7f.0.0.1/",  # hex octet: 127.0.0.1
        "http://0177.0.0.1/",  # octal octet: 127.0.0.1 (httpx may reject URL itself)
    ],
)
def test_ip_literal_encoding_blocked_via_resolver(url: str) -> None:
    """IP-literal-encoded loopback URLs are blocked via the real resolver path (A3/Y3).

    Uses the REAL socket.getaddrinfo (no mock); the resolver normalises decimal/hex/octal
    to 127.0.0.1 and the SSRF classifier denies it. Some encodings are also rejected by
    httpx's URL parser (InvalidURL) — both outcomes mean "blocked, no HTTP connection".
    """
    transport = _SSRFValidatingTransport()
    try:
        request = httpx.Request("GET", url)
    except httpx.InvalidURL:
        # httpx's RFC-3986 parser itself rejects the encoding — also "blocked".
        return
    # Either ssrf_blocked (resolver normalises to 127.0.0.1) or fetch_failed
    # (resolver rejects the representation) — in both cases, no HTTP connection.
    with pytest.raises(LocalToolError, match=r"(ssrf_blocked:|fetch_failed:)"):
        transport.handle_request(request)


# ---------------------------------------------------------------------------
# Section 6: Bounded DNS resolution timeout (🔴 B1)
# ---------------------------------------------------------------------------


def test_bounded_dns_timeout() -> None:
    """Hung resolver → network_timeout: LocalToolError within DNS_RESOLVE_TIMEOUT_S.

    Mocks the future directly to raise concurrent.futures.TimeoutError so no real
    thread is hung (avoids leaving executor threads stuck for subsequent tests).
    """
    from concurrent.futures import TimeoutError as _CFTimeout

    mock_future: MagicMock = MagicMock()
    mock_future.result.side_effect = _CFTimeout()

    with patch("orchestrator.tools.net_trust._DNS_EXECUTOR") as mock_exec:
        mock_exec.submit.return_value = mock_future
        with pytest.raises(LocalToolError, match="network_timeout:"):
            _resolve_and_validate("slow.example.com", 80)


def test_dns_resolve_timeout_constant_defined() -> None:
    """DNS_RESOLVE_TIMEOUT_S must exist and be positive."""
    assert DNS_RESOLVE_TIMEOUT_S > 0


# ---------------------------------------------------------------------------
# Section 7: Redirect re-validation
# ---------------------------------------------------------------------------


def test_redirect_to_internal_blocked() -> None:
    """302 → http://169.254.169.254 is re-validated and ssrf_blocked.

    We simulate by calling handle_request with a metadata URL whose mock resolver
    returns the metadata IP — exactly what happens when httpx follows a redirect hop
    through our transport and we're re-invoked for the new hop's URL.
    """
    mock_future: MagicMock = MagicMock()
    mock_future.result.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80)),
    ]
    with patch("orchestrator.tools.net_trust._DNS_EXECUTOR") as mock_exec:
        mock_exec.submit.return_value = mock_future
        transport = _SSRFValidatingTransport()
        redirect_request = httpx.Request("GET", "http://169.254.169.254/latest/meta-data/")
        with pytest.raises(LocalToolError, match="ssrf_blocked:"):
            transport.handle_request(redirect_request)


# ---------------------------------------------------------------------------
# Section 8: build_ssrf_client properties
# ---------------------------------------------------------------------------


def test_build_ssrf_client_returns_httpx_client() -> None:
    timeout = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)
    client = build_ssrf_client(timeout=timeout)
    assert isinstance(client, httpx.Client)
    client.close()


def test_build_ssrf_client_uses_ssrf_transport() -> None:
    timeout = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)
    client = build_ssrf_client(timeout=timeout)
    assert isinstance(client._transport, _SSRFValidatingTransport)
    client.close()


def test_ssrf_client_blocks_internal_url() -> None:
    """build_ssrf_client blocks a request to an internal URL end-to-end."""
    mock_future: MagicMock = MagicMock()
    mock_future.result.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80)),
    ]
    with patch("orchestrator.tools.net_trust._DNS_EXECUTOR") as mock_exec:
        mock_exec.submit.return_value = mock_future
        timeout = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)
        client = build_ssrf_client(timeout=timeout)
        with pytest.raises(LocalToolError, match="ssrf_blocked:"):
            client.get("http://internal.example.com/")
        client.close()
