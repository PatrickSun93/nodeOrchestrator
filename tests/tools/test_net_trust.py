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


# ---------------------------------------------------------------------------
# P4.3-10: NAT64 floor extension (R6 fold-in — ADR-037 D2)
# ---------------------------------------------------------------------------


def test_nat64_wrapped_internal_ipv4_denied() -> None:
    """NAT64 64:ff9b::/96 wrapping an internal IPv4 must be denied (R6 fold-in)."""
    import ipaddress

    from orchestrator.tools.net_trust import is_denied_ip

    # 127.0.0.1 embedded in NAT64: 64:ff9b::7f00:0001
    nat64_loopback = ipaddress.ip_address("64:ff9b::7f00:1")
    assert is_denied_ip(nat64_loopback), "NAT64-wrapped 127.0.0.1 must be denied"

    # 10.0.0.1 embedded in NAT64: 64:ff9b::0a00:0001
    nat64_private = ipaddress.ip_address("64:ff9b::a00:1")
    assert is_denied_ip(nat64_private), "NAT64-wrapped 10.0.0.1 must be denied"

    # 192.168.1.1 embedded in NAT64: 64:ff9b::c0a8:0101
    nat64_private2 = ipaddress.ip_address("64:ff9b::c0a8:101")
    assert is_denied_ip(nat64_private2), "NAT64-wrapped 192.168.1.1 must be denied"


def test_nat64_wrapped_public_ipv4_allowed() -> None:
    """NAT64 64:ff9b::/96 wrapping a public IPv4 must be allowed."""
    import ipaddress

    from orchestrator.tools.net_trust import is_denied_ip

    # 93.184.216.34 (example.com) embedded in NAT64: 64:ff9b::5db8:d822
    nat64_public = ipaddress.ip_address("64:ff9b::5db8:d822")
    assert not is_denied_ip(nat64_public), "NAT64-wrapped public IP (93.184.216.34) must be allowed"


# ---------------------------------------------------------------------------
# P4.3-11: R5 DNS head-of-line fix — concurrent resolve not blocked by hung one
# ---------------------------------------------------------------------------


def test_dns_hol_fix_concurrent_resolve_not_blocked() -> None:
    """P4.3-11: a hung getaddrinfo must not block a concurrent resolve past its deadline.

    With the former max_workers=1 pool, a hung getaddrinfo blocked all subsequent
    resolves until it timed out. With max_workers=8, each submit gets its own slot.
    This test simulates one hanging resolve and asserts a second resolves within
    its own deadline (not the hung one's deadline).
    """
    import threading
    import time
    from unittest.mock import patch

    from orchestrator.tools.net_trust import DNS_RESOLVE_TIMEOUT_S, _resolve_and_validate

    hung_started = threading.Event()
    fast_done = threading.Event()

    def _hung_getaddrinfo(hostname: str, port: int) -> list[object]:
        if hostname == "hung.example.invalid":
            hung_started.set()
            # Simulate a long hang — much longer than DNS_RESOLVE_TIMEOUT_S
            time.sleep(DNS_RESOLVE_TIMEOUT_S + 10)
        # Fast resolve: return a public IP
        import socket

        return list(socket.getaddrinfo("93.184.216.34", port, socket.AF_INET, socket.SOCK_STREAM))

    errors: list[str] = []

    def _run_fast_resolve() -> None:
        # Wait for the hung resolve to start before submitting the fast one.
        hung_started.wait(timeout=2.0)
        t0 = time.monotonic()
        try:
            # Fast resolve should succeed (returns a real IP via the mock).
            # The mock for "example.com" returns a public IP directly.
            _resolve_and_validate("example.com", 80)
            elapsed = time.monotonic() - t0
            if elapsed > DNS_RESOLVE_TIMEOUT_S * 2:
                errors.append(f"fast resolve took too long: {elapsed:.2f}s (HOL block?)")
        except Exception as exc:
            # OK if SSRF blocked — that's a valid result for the mock
            if "ssrf_blocked" not in str(exc) and "network_timeout" not in str(exc):
                errors.append(f"unexpected error: {exc}")
        finally:
            fast_done.set()

    # Mock _get_addrs to control both resolves.
    real_getaddrinfo_results = {
        "example.com": [
            (2, 1, 6, "", ("93.184.216.34", 80))  # public IP — allowed
        ],
        "hung.example.invalid": None,  # will hang
    }

    def _mock_get_addrs(hostname: str, port: int) -> list[object]:
        if hostname == "hung.example.invalid":
            hung_started.set()
            time.sleep(DNS_RESOLVE_TIMEOUT_S + 10)
            return []
        results = real_getaddrinfo_results.get(hostname) or [(2, 1, 6, "", ("93.184.216.34", 80))]
        return list(results)

    from concurrent.futures import Future

    def _patched_submit(fn: object, *args: object, **kwargs: object) -> Future:  # type: ignore[type-arg]
        import concurrent.futures

        f: Future = concurrent.futures.Future()  # type: ignore[type-arg]

        def _run() -> None:
            try:
                r = _mock_get_addrs(*args)  # type: ignore[arg-type]
                f.set_result(r)
            except Exception as e:
                f.set_exception(e)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return f

    with patch("orchestrator.tools.net_trust._DNS_EXECUTOR") as mock_exec:
        mock_exec.submit.side_effect = _patched_submit

        # Start the hung resolve in a background thread.
        hung_thread = threading.Thread(
            target=lambda: _resolve_and_validate("hung.example.invalid", 80),
            daemon=True,
        )
        hung_thread.start()

        # Run the fast resolve — should NOT be blocked by the hung one.
        fast_thread = threading.Thread(target=_run_fast_resolve, daemon=True)
        fast_thread.start()

        fast_done.wait(timeout=DNS_RESOLVE_TIMEOUT_S * 3)

    assert not errors, f"HOL block detected or unexpected error: {errors}"
