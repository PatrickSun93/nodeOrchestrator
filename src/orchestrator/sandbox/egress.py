"""Egress-constraint mechanism: host-side filtering CONNECT proxy (ADR-037 A1-1; RW1).

Per call, constrains container egress to exactly the parent-validated pinned IP:port:
1. Parent resolves+validates via _resolve_and_validate (net_trust.py:79-122).
2. A per-call EgressProxy is started on the host, allowlisted to (hostname→pinned_ip, port).
3. Container runs with no direct egress; DNS disabled (--dns 0.0.0.0).
4. Container pointed at the proxy via HTTP_PROXY/HTTPS_PROXY env +
   --add-host host.docker.internal:host-gateway (portable across Docker Desktop + native).
5. Proxy dials the pinned IP (SSRF pinning preserved end-to-end); refuses all else → 407.

Cross-platform (ADR-037 A1-1): host-side proxy is root-free and works in both the
Docker Desktop VM and native Linux — unlike the withdrawn nftables-on-bridge approach.

ssh git_push: ProxyCommand nc -X connect -x host.docker.internal:<port> %h %p in
GIT_SSH_COMMAND routes ssh CONNECT through the same proxy → ssh reaches only the
SSRF-pinned IP:port (proxy allowlist enforces it).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Literal

_log = logging.getLogger("orchestrator.sandbox.egress")


class EgressDenied(Exception):  # noqa: N818
    """Raised when a (runtime x tool) combo has no viable constrained-egress path.

    The posture resolver surfaces this as a loud TOOL_FAILED — never silently
    unconstrained egress. Callers must NOT proceed with an unconstrained network.
    """


class EgressMechanism(Enum):
    """Which egress-constraint mechanism applies for this call."""

    DENY_DEFAULT = "deny_default"
    PROXY = "proxy"
    DENIED = "denied"


RuntimeKind = Literal["docker", "podman"]
ToolKind = Literal["subprocess", "web_fetch"]


@dataclass(frozen=True)
class EgressSpec:
    """Per-call egress specification produced by build_egress_spec().

    Fields:
    - mechanism: DENY_DEFAULT (--network none) or PROXY (host-side filtering proxy).
    - hostname: the original hostname for the proxy allowlist (empty for DENY_DEFAULT).
    - pinned_ip: the single validated IP the proxy dials.
    - pinned_port: the port the proxy dials.
    - network_name: ephemeral Docker network name (PROXY mechanism).
    - dns_disabled: True = --dns 0.0.0.0 must appear in container args.
    - ipv4_only / ipv6_only: single-family pin (other family blocked).
    """

    mechanism: EgressMechanism
    pinned_ip: str
    pinned_port: int
    hostname: str = ""
    network_name: str | None = None
    dns_disabled: bool = True
    ipv4_only: bool = False
    ipv6_only: bool = False


def build_egress_spec(
    pinned_ip: str,
    pinned_port: int,
    *,
    runtime_kind: RuntimeKind,
    tool_kind: ToolKind,
    hostname: str = "",
    on_docker_desktop: bool = False,
    call_id: str = "",
) -> EgressSpec:
    """Build the per-call egress specification for a given pinned IP:port.

    Args:
    - pinned_ip: the single IP validated by the parent's SSRF floor.
    - pinned_port: the target port (80/443/22/etc).
    - runtime_kind: "docker" or "podman".
    - tool_kind: "subprocess" (git_push) or "web_fetch".
    - hostname: the original hostname (for proxy allowlist and Host header).
    - on_docker_desktop: unused (kept for call-site compat); proxy works cross-platform.
    - call_id: for network name and log correlation.

    Returns an EgressSpec with PROXY mechanism; raises EgressDenied on invalid inputs.
    The caller MUST NOT fall back to an unconstrained network — EgressDenied is fail-closed.
    """
    import ipaddress

    try:
        ip_obj = ipaddress.ip_address(pinned_ip)
    except ValueError as exc:
        raise EgressDenied(f"invalid pinned_ip {pinned_ip!r}: {exc}") from exc

    is_v4 = isinstance(ip_obj, ipaddress.IPv4Address)
    ipv4_only = is_v4
    ipv6_only = not is_v4

    network_name = f"sandbox-egress-{call_id}" if call_id else "sandbox-egress"

    return EgressSpec(
        mechanism=EgressMechanism.PROXY,
        pinned_ip=pinned_ip,
        pinned_port=pinned_port,
        hostname=hostname or pinned_ip,
        network_name=network_name,
        dns_disabled=True,
        ipv4_only=ipv4_only,
        ipv6_only=ipv6_only,
    )


def build_deny_default_spec() -> EgressSpec:
    """Return a deny-default (--network none) egress spec for tools that need no net."""
    return EgressSpec(
        mechanism=EgressMechanism.DENY_DEFAULT,
        pinned_ip="",
        pinned_port=0,
        hostname="",
        network_name=None,
        dns_disabled=False,
    )


def container_network_args(spec: EgressSpec, proxy_port: int = 0) -> list[str]:
    """Convert an EgressSpec to the --network / --dns / --add-host / --env container args.

    For PROXY mechanism, proxy_port must be the bound port of the EgressProxy.
    Returns the list to extend the container's arg list with.
    docker.sock is never included (constitutional invariant lives in profile.py).
    """
    args: list[str] = []

    if spec.mechanism == EgressMechanism.DENY_DEFAULT:
        args += ["--network", "none"]
        return args

    # PROXY mechanism: per-call ephemeral network.
    if spec.network_name:
        args += ["--network", spec.network_name]

    # Disable container-internal DNS (DNS is resolved by the proxy, not the container).
    if spec.dns_disabled:
        args += ["--dns", "0.0.0.0"]

    # host.docker.internal → host-gateway: portable across Docker Desktop + native 20.10+.
    args += ["--add-host", "host.docker.internal:host-gateway"]

    # Block the non-pinned address family via sysctl (defense-in-depth).
    if spec.ipv4_only:
        args += ["--sysctl", "net.ipv6.conf.all.disable_ipv6=1"]

    # Proxy env: container routes outbound http(s) through the host-side filtering proxy.
    # GIT_SSH_COMMAND: ssh ProxyCommand routes ssh through the same proxy (ADR-037 A1-1;
    # the sandbox image must ship nc or socat for the ProxyCommand — D5 tail).
    if proxy_port:
        proxy_url = f"http://host.docker.internal:{proxy_port}"
        args += ["--env", f"HTTP_PROXY={proxy_url}"]
        args += ["--env", f"HTTPS_PROXY={proxy_url}"]
        args += ["--env", "NO_PROXY="]
        # ssh git_push: route through the same CONNECT proxy via ProxyCommand.
        # nc -X connect = CONNECT proxy mode; -x = proxy address.
        ssh_cmd = (
            f"ssh -o StrictHostKeyChecking=no "
            f"-o ProxyCommand='nc -X connect -x host.docker.internal:{proxy_port} %h %p'"
        )
        args += ["--env", f"GIT_SSH_COMMAND={ssh_cmd}"]

    return args
