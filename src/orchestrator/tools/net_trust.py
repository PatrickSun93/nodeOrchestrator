"""Network trust boundary: SSRF validator + resolve-then-pin transport (ADR-035 D2/D3).

The one app-level SSRF primitive: built once here, consumed by web_fetch and any
future agent-URL tool (ADR-035 carry-forward #4).

Do NOT add network code to tools/local.py (in-process-pristine, t6) or
tools/subprocess_tools.py (subprocess surface). net_trust.py is the network surface.
"""

from __future__ import annotations

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FutureTimeout
from typing import Any

import httpx

from orchestrator.tools.local import LocalToolError

# Bounded DNS resolution timeout (ADR-035 D2; R0-B 🔴 B1 — must wrap getaddrinfo).
# socket.getaddrinfo runs before httpx's timeout machinery; an unwrapped resolver
# would block the single writer indefinitely (ADR-028 D5).
DNS_RESOLVE_TIMEOUT_S: float = 5.0

# CGNAT shared address space (RFC 6598, 100.64.0.0/10).
# Python ipaddress.is_private does NOT cover this range — explicit check required (A1).
# Includes Alibaba Cloud metadata 100.100.100.200.
_CGNAT_NETWORK = ipaddress.IPv4Network("100.64.0.0/10")

# NAT64 well-known prefix (RFC 6052, 64:ff9b::/96).
# An IPv4 address embedded in NAT64 is the low 32 bits; extract + validate against floor.
# Python is_private does NOT cover this range — explicit check required (R6 / ADR-037 D2).
_NAT64_PREFIX = ipaddress.IPv6Network("64:ff9b::/96")

_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})

# Fixed 8-slot DNS pool — R5 head-of-line fix (ADR-035 impl-degradation ¶; P4.3-11).
# Raises the head-of-line threshold 1→8: a hung getaddrinfo consumes one slot but does
# not queue subsequent resolves in the other 7 slots. A permanently-hung getaddrinfo
# consumes a slot until the thread pool is GC'd (the abandonable-per-call-thread is the
# deferred-stronger tail, ADR-037 D5). max_workers=8 handles typical bursts; the
# DNS_RESOLVE_TIMEOUT_S per-call deadline still bounds each individual future.
_DNS_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="net-dns")


def is_denied_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if ip falls within any SSRF-floor denied range.

    Denied: loopback, private, CGNAT (100.64.0.0/10), link-local, unspecified,
    multicast, reserved, IPv4-mapped IPv6, or NAT64-wrapped internal IPv4 (R6 fold-in).
    """
    # Unwrap IPv4-mapped IPv6 first (::ffff:127.0.0.1 bypass class).
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return is_denied_ip(ip.ipv4_mapped)

    # Unwrap NAT64 (64:ff9b::/96 well-known prefix; R6 fold-in ADR-037 D2).
    # The embedded IPv4 is the low 32 bits of the IPv6 address.
    if isinstance(ip, ipaddress.IPv6Address) and ip in _NAT64_PREFIX:
        # Extract the embedded IPv4: last 4 bytes of the 16-byte address.
        packed = ip.packed
        embedded_ipv4 = ipaddress.IPv4Address(packed[12:])
        return is_denied_ip(embedded_ipv4)

    if ip.is_loopback:
        return True
    if ip.is_private:
        return True
    # CGNAT: Python's is_private does NOT cover 100.64.0.0/10 (A1).
    if isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT_NETWORK:
        return True
    if ip.is_link_local:
        return True
    if ip.is_unspecified:
        return True
    if ip.is_multicast:
        return True
    return bool(ip.is_reserved)


def _validate_scheme(scheme: str) -> None:
    """Raise LocalToolError(scheme_rejected:…) if scheme is not http or https."""
    if scheme not in _ALLOWED_SCHEMES:
        raise LocalToolError(
            f"scheme_rejected: scheme {scheme!r} not allowed (allowed: http, https)"
        )


def _get_addrs(hostname: str, port: int) -> list[Any]:
    """Call socket.getaddrinfo; separated so ThreadPoolExecutor can type it cleanly."""
    return socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)


def _resolve_and_validate(hostname: str, port: int) -> str:
    """Resolve hostname, validate ALL resolved IPs against the floor, return pinned IP.

    Raises LocalToolError with ssrf_blocked: / network_timeout: / fetch_failed: prefix.
    DNS resolution is bounded by DNS_RESOLVE_TIMEOUT_S (ADR-035 D2, R0-B 🔴 B1).
    getaddrinfo follows CNAMEs to final IPs — CNAME-chain-to-internal is denied (A2).
    """
    future = _DNS_EXECUTOR.submit(_get_addrs, hostname, port)
    try:
        results: list[Any] = future.result(timeout=DNS_RESOLVE_TIMEOUT_S)
    except _FutureTimeout:
        future.cancel()
        raise LocalToolError(
            f"network_timeout: DNS resolution exceeded {DNS_RESOLVE_TIMEOUT_S}s"
            f" for {hostname!r}"
        ) from None
    except OSError as exc:
        raise LocalToolError(
            f"fetch_failed: DNS resolution failed for {hostname!r}: {exc}"
        ) from exc

    if not results:
        raise LocalToolError(f"fetch_failed: no DNS results for {hostname!r}")

    pinned_ip: str | None = None
    for entry in results:
        # entry: (family, socktype, proto, canonname, sockaddr)
        # sockaddr: (address, port) for IPv4, (address, port, flowinfo, scope_id) for IPv6
        addr_str: str = entry[4][0]
        try:
            ip_obj = ipaddress.ip_address(addr_str)
        except ValueError:
            continue
        if is_denied_ip(ip_obj):
            raise LocalToolError(
                f"ssrf_blocked: {hostname!r} resolves to denied IP {addr_str!r}"
            )
        if pinned_ip is None:
            pinned_ip = addr_str

    if pinned_ip is None:
        raise LocalToolError(f"fetch_failed: no routable IP resolved for {hostname!r}")

    return pinned_ip


class _SSRFValidatingTransport(httpx.BaseTransport):
    """Custom httpx transport: resolve-then-pin + full SSRF validation on every hop.

    On each request:
      1. Validate scheme (http/https only).
      2. Resolve host via socket.getaddrinfo (bounded by DNS_RESOLVE_TIMEOUT_S).
      3. Validate ALL resolved IPs against the SSRF floor (deny-if-any).
      4. Connect to the pinned IP; pass original hostname as sni_hostname extension
         so httpcore uses it for TLS SNI + cert verification (verify=True).
      5. httpx calls handle_request for each redirect hop → every hop re-validated.

    retries=0 on the inner transport (no silent retry loop; ADR-035 D2 B3).
    """

    def __init__(self) -> None:
        # verify=True: ADR-032 precedent; retries=0: no silent retry (ADR-035 D2 B3).
        self._inner = httpx.HTTPTransport(verify=True, retries=0)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        _validate_scheme(request.url.scheme)

        hostname = request.url.host
        port = request.url.port or (443 if request.url.scheme == "https" else 80)

        pinned_ip = _resolve_and_validate(hostname, port)

        # Substitute pinned IP into URL; keep original hostname for Host header + TLS.
        pinned_url = request.url.copy_with(host=pinned_ip)

        # sni_hostname extension: httpcore uses this for TLS SNI + cert verification
        # so the certificate is validated against the original hostname, not the IP.
        new_extensions: dict[str, Any] = {
            **request.extensions,
            "sni_hostname": hostname.encode("ascii"),
        }

        # Rebuild the request with the pinned URL.
        # request.headers already has Host: <original hostname> from the original request;
        # httpx.Request only auto-sets Host if not already present, so it is preserved.
        new_request = httpx.Request(
            method=request.method,
            url=pinned_url,
            headers=list(request.headers.raw),
            extensions=new_extensions,
            content=b"",  # web_fetch is GET-only; no body
        )

        return self._inner.handle_request(new_request)

    def close(self) -> None:
        self._inner.close()


def build_ssrf_client(
    *,
    timeout: httpx.Timeout,
    max_redirects: int = 5,
) -> httpx.Client:
    """Build an anonymous, credential-stripped, SSRF-validating httpx client.

    Properties:
    - No Authorization, no cookies, no orchestrator secrets.
    - verify=True enforced inside _SSRFValidatingTransport (ADR-032 precedent).
    - retries=0 on the inner transport (no silent retry loop multiplying the write block).
    - follow_redirects=True: each redirect hop calls handle_request → re-validates SSRF.
    - max_redirects=5: bounded redirect chain.
    - Granular timeout (connect=5, read=15, write=5, pool=5): bounded on every term
      (ADR-035 D2 B2 — not a version-dependent scalar timeout).
    """
    transport = _SSRFValidatingTransport()
    return httpx.Client(
        transport=transport,
        follow_redirects=True,
        max_redirects=max_redirects,
        timeout=timeout,
        auth=None,
        cookies={},
        headers={},
    )
