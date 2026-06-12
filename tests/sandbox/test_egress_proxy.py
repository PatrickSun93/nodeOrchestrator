"""Tests for sandbox/egress_proxy.py (RW1 / RW8 assertion 5).

Tests the EgressProxy allowlist semantics: permits pinned host:port; refuses all other
targets including redirect-hosts. No live Docker needed — tests the proxy object directly.
"""

from __future__ import annotations

import socket
import threading
import time


def _start_upstream() -> tuple[socket.socket, int]:
    """Start a TCP listener that accepts one connection (acts as a mock upstream)."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    srv.settimeout(3.0)
    port = srv.getsockname()[1]

    def _accept_loop() -> None:
        try:
            while True:
                try:
                    conn, _ = srv.accept()
                    conn.close()
                except OSError:
                    break
        except Exception:
            pass

    t = threading.Thread(target=_accept_loop, daemon=True)
    t.start()
    return srv, port


def _send_connect(proxy_port: int, host: str, port: int) -> bytes:
    """Send a CONNECT request to the proxy and return the response line."""
    with socket.create_connection(("127.0.0.1", proxy_port), timeout=5.0) as client:
        req = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n"
        client.sendall(req.encode())
        client.settimeout(3.0)
        data = b""
        while b"\r\n" not in data:
            chunk = client.recv(256)
            if not chunk:
                break
            data += chunk
    return data


# ---------------------------------------------------------------------------
# RW8-5: proxy permits the pinned host:port
# ---------------------------------------------------------------------------


def test_rw8_proxy_allows_pinned_host() -> None:
    """RW8-5: EgressProxy returns 200 for CONNECT to the allowlisted host:port."""
    from orchestrator.sandbox.egress_proxy import EgressProxy

    upstream_srv, upstream_port = _start_upstream()
    try:
        proxy = EgressProxy(
            hostname="allowedhost.internal",
            pinned_ip="127.0.0.1",
            pinned_port=upstream_port,
        )
        proxy_port = proxy.start()
        try:
            time.sleep(0.05)  # let the proxy thread start
            response = _send_connect(proxy_port, "allowedhost.internal", upstream_port)
            assert b"200" in response, f"Expected 200 for allowlisted host, got: {response!r}"
        finally:
            proxy.stop()
    finally:
        upstream_srv.close()


def test_rw8_proxy_allows_ssh_port_connect() -> None:
    """RW8-5: proxy permits CONNECT to the allowlisted host on port 22 (ssh git_push)."""
    from orchestrator.sandbox.egress_proxy import EgressProxy

    upstream_srv, upstream_port = _start_upstream()
    try:
        proxy = EgressProxy(
            hostname="githost.internal",
            pinned_ip="127.0.0.1",
            pinned_port=upstream_port,
        )
        proxy_port = proxy.start()
        try:
            time.sleep(0.05)
            # Allowlist uses pinned_port; CONNECT must use the same port
            response = _send_connect(proxy_port, "githost.internal", upstream_port)
            assert b"200" in response, "Expected 200 for ssh CONNECT to allowlisted host"
        finally:
            proxy.stop()
    finally:
        upstream_srv.close()


# ---------------------------------------------------------------------------
# RW8-5: proxy refuses non-allowlisted hosts
# ---------------------------------------------------------------------------


def test_rw8_proxy_refuses_different_host() -> None:
    """RW8-5: EgressProxy returns 407 for CONNECT to a non-allowlisted host."""
    from orchestrator.sandbox.egress_proxy import EgressProxy

    proxy = EgressProxy(
        hostname="allowed.internal",
        pinned_ip="127.0.0.1",
        pinned_port=443,
    )
    proxy_port = proxy.start()
    try:
        time.sleep(0.05)
        response = _send_connect(proxy_port, "evil.com", 443)
        assert b"407" in response, f"Expected 407 for non-allowlisted host, got: {response!r}"
    finally:
        proxy.stop()


def test_rw8_proxy_refuses_redirect_host() -> None:
    """RW8-5: a redirect-host CONNECT is refused (per-hop host filtering, R0B-6)."""
    from orchestrator.sandbox.egress_proxy import EgressProxy

    proxy = EgressProxy(
        hostname="original.internal",
        pinned_ip="127.0.0.1",
        pinned_port=443,
    )
    proxy_port = proxy.start()
    try:
        time.sleep(0.05)
        # A server redirect would issue a new CONNECT to the redirect target
        response = _send_connect(proxy_port, "redirect.example.com", 443)
        assert b"407" in response, f"Expected 407 for redirect-host CONNECT, got: {response!r}"
    finally:
        proxy.stop()


def test_rw8_proxy_refuses_wrong_port() -> None:
    """RW8-5: correct hostname but wrong port → refused (single-port allowlist)."""
    from orchestrator.sandbox.egress_proxy import EgressProxy

    proxy = EgressProxy(
        hostname="allowed.internal",
        pinned_ip="127.0.0.1",
        pinned_port=443,
    )
    proxy_port = proxy.start()
    try:
        time.sleep(0.05)
        response = _send_connect(proxy_port, "allowed.internal", 80)  # wrong port
        assert b"407" in response, (
            f"Expected 407 for correct host but wrong port, got: {response!r}"
        )
    finally:
        proxy.stop()


# ---------------------------------------------------------------------------
# Lifecycle: start + stop work correctly
# ---------------------------------------------------------------------------


def test_rw8_proxy_start_returns_nonzero_port() -> None:
    """Proxy binds an ephemeral port and returns it from start()."""
    from orchestrator.sandbox.egress_proxy import EgressProxy

    proxy = EgressProxy(hostname="h", pinned_ip="127.0.0.1", pinned_port=443)
    port = proxy.start()
    try:
        assert port > 0
    finally:
        proxy.stop()


def test_rw8_proxy_stop_is_idempotent() -> None:
    """Calling stop() twice does not raise."""
    from orchestrator.sandbox.egress_proxy import EgressProxy

    proxy = EgressProxy(hostname="h", pinned_ip="127.0.0.1", pinned_port=443)
    proxy.start()
    proxy.stop()
    proxy.stop()  # second stop must not raise


def _send_raw(proxy_port: int, request: str) -> bytes:
    """Send a raw HTTP request to the proxy and return the response line."""
    with socket.create_connection(("127.0.0.1", proxy_port), timeout=5.0) as client:
        client.sendall(request.encode("latin-1"))
        client.settimeout(3.0)
        data = b""
        while b"\r\n" not in data:
            chunk = client.recv(256)
            if not chunk:
                break
            data += chunk
    return data


# ---------------------------------------------------------------------------
# F-residual pin (ADR-037 D5 inscription): plain-http → 405 fail-closed
# ---------------------------------------------------------------------------


def test_f_plain_http_fails_closed_405() -> None:
    """F-residual pin: plain-http absolute-form GET → 405 (fail-closed, no exfil).

    In-container urllib sends an absolute-form GET for plain http:// URLs (no CONNECT).
    The CONNECT-only proxy returns 405; the fetch fails closed (TOOL_FAILED, no exfil).
    https is unaffected — it uses CONNECT (see test_rw8_proxy_allows_pinned_host).

    ADR-037 D4 / D5 inscription: this pin MUST FAIL if the proxy is ever loosened to
    forward non-CONNECT methods (absolute-form GET → tunnel = fail-open-for-http).
    That change requires an explicit ADR-037 D2 amendment + architect dispatch.
    """
    from orchestrator.sandbox.egress_proxy import EgressProxy

    proxy = EgressProxy(
        hostname="allowed.internal",
        pinned_ip="127.0.0.1",
        pinned_port=80,
    )
    proxy_port = proxy.start()
    try:
        time.sleep(0.05)
        # Exactly what urllib emits for a plain http:// URL routed through HTTP_PROXY
        raw_request = "GET http://allowed.internal/ HTTP/1.1\r\nHost: allowed.internal\r\n\r\n"
        response = _send_raw(proxy_port, raw_request)
        assert b"405" in response, (
            f"Expected 405 for plain-http absolute-form GET (fail-closed), got: {response!r}"
        )
    finally:
        proxy.stop()
