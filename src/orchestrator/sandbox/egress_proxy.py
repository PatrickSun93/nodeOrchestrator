"""Host-side filtering CONNECT proxy for per-call container egress (ADR-037 A1-1; RW1).

Per-call lifecycle (started before docker run, stopped in the shielded finally):
  proxy = EgressProxy(hostname, pinned_ip, pinned_port)
  proxy.start()   # binds a port, starts the listener thread; returns bound port
  try:
      ... docker run with HTTP(S)_PROXY=http://host.docker.internal:<port> ...
  finally:
      proxy.stop()  # signals shutdown and joins the listener thread

The allowlist is exactly one (hostname, pinned_ip, port) entry per call.
CONNECT to any other host → 407/403 Forbidden.

Supported transports:
- https: urllib/httpx in-container honors HTTPS_PROXY → CONNECT <host>:<port> (tunnelled).
- plain http: NOT supported in-sandbox — urllib emits an absolute-form GET (no CONNECT)
  → proxy returns 405 → fail-closed (no exfil; ADR-037 D4). https is the web_fetch path.
- ssh git_push: ProxyCommand nc -X connect -x host.docker.internal:<port> %h %p

The proxy dials the PINNED IP (not the hostname), preserving SSRF end-to-end pinning.
TLS validation stays end-to-end against the original hostname (blind CONNECT tunnel).

Cross-platform: binds 0.0.0.0 so host.docker.internal (→ bridge gateway) can reach it.
Per-call lifetime bounds the reachable window. (D5 tail: briefly reachable by other
local processes within the call window, bounded by single-host allowlist.)
"""

from __future__ import annotations

import contextlib
import logging
import select
import socket
import threading

_log = logging.getLogger("orchestrator.sandbox.egress_proxy")

# Buffer size for tunnel relay.
_BUF = 4096

# Accept-loop poll interval (seconds) — how often the listener checks the stop flag.
_POLL_S = 0.5


class EgressProxy:
    """Per-call host-side filtering CONNECT proxy.

    Allowlist: exactly one (hostname, pinned_ip, port) — dials pinned_ip, not hostname.
    All other CONNECT targets receive a 407 response and the connection is closed.
    """

    def __init__(self, hostname: str, pinned_ip: str, pinned_port: int) -> None:
        self._hostname = hostname.lower()
        self._pinned_ip = pinned_ip
        self._pinned_port = pinned_port
        self._sock: socket.socket | None = None
        self._port: int = 0
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        """Bound listening port (set after start())."""
        return self._port

    def start(self) -> int:
        """Bind a port and start the proxy listener thread. Returns the bound port."""
        self._stop_event.clear()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("0.0.0.0", 0))
        self._sock.listen(16)
        self._sock.setblocking(False)
        self._port = self._sock.getsockname()[1]
        self._thread = threading.Thread(
            target=self._serve,
            daemon=True,
            name=f"egress-proxy-{self._port}",
        )
        self._thread.start()
        _log.debug(
            "egress_proxy: started on :%d allowlist=%s→%s:%d",
            self._port,
            self._hostname,
            self._pinned_ip,
            self._pinned_port,
        )
        return self._port

    def stop(self) -> None:
        """Signal the proxy to stop and wait for the listener thread to exit."""
        self._stop_event.set()
        if self._sock is not None:
            with contextlib.suppress(OSError):
                self._sock.close()
            self._sock = None
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        _log.debug("egress_proxy: stopped (port was %d)", self._port)

    def _serve(self) -> None:
        """Accept-loop: handle one CONNECT per accepted connection in a daemon thread."""
        sock = self._sock
        if sock is None:
            return
        while not self._stop_event.is_set():
            try:
                ready, _, _ = select.select([sock], [], [], _POLL_S)
            except OSError:
                break
            if not ready:
                continue
            try:
                client, addr = sock.accept()
            except OSError:
                break
            t = threading.Thread(
                target=self._handle,
                args=(client,),
                daemon=True,
                name=f"egress-proxy-conn-{addr[1]}",
            )
            t.start()

    def _handle(self, client: socket.socket) -> None:
        """Handle one inbound connection: read CONNECT request, tunnel or refuse."""
        try:
            client.settimeout(10.0)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = client.recv(_BUF)
                if not chunk:
                    return
                data += chunk
                if len(data) > 8192:
                    _send_response(client, b"400 Bad Request")
                    return

            first_line = data.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
            parts = first_line.split()
            if len(parts) < 2 or parts[0].upper() != "CONNECT":
                _send_response(client, b"405 Method Not Allowed")
                return

            target = parts[1]
            if ":" in target:
                req_host, port_str = target.rsplit(":", 1)
                try:
                    req_port = int(port_str)
                except ValueError:
                    _send_response(client, b"400 Bad Request")
                    return
            else:
                req_host = target
                req_port = 443

            req_host_lower = req_host.lower()

            # Allowlist check: only the one SSRF-pinned host:port is permitted.
            if req_host_lower != self._hostname or req_port != self._pinned_port:
                _log.warning(
                    "egress_proxy: CONNECT %s:%d refused (allowlist: %s:%d)",
                    req_host,
                    req_port,
                    self._hostname,
                    self._pinned_port,
                )
                _send_response(client, b"407 Proxy Authorization Required")
                return

            # Dial the PINNED IP, not the hostname (SSRF pinning preserved).
            try:
                upstream = socket.create_connection(
                    (self._pinned_ip, self._pinned_port), timeout=10.0
                )
            except OSError as exc:
                _log.debug("egress_proxy: upstream connect failed: %s", exc)
                _send_response(client, b"502 Bad Gateway")
                return

            try:
                client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                _relay(client, upstream)
            finally:
                with contextlib.suppress(OSError):
                    upstream.close()
        except OSError:
            pass
        finally:
            with contextlib.suppress(OSError):
                client.close()


def _send_response(sock: socket.socket, status: bytes) -> None:
    with contextlib.suppress(OSError):
        sock.sendall(b"HTTP/1.1 " + status + b"\r\nContent-Length: 0\r\n\r\n")


def _relay(a: socket.socket, b: socket.socket) -> None:
    """Bidirectional relay between two sockets until either closes."""
    socks = [a, b]
    while True:
        try:
            r, _, _ = select.select(socks, [], [], 60.0)
        except OSError:
            break
        if not r:
            break
        for src in r:
            dst = b if src is a else a
            try:
                data = src.recv(_BUF)
            except OSError:
                return
            if not data:
                return
            try:
                dst.sendall(data)
            except OSError:
                return
