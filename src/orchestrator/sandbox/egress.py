"""Egress-constraint mechanism: parent-pinned-IP per-call container egress (ADR-037 D2/D3; P4.3-3).

The load-bearing network-isolation boundary (R0-B R1 resolved).

Per call, constrains container egress to exactly the parent-validated pinned IP:port:
1. Parent resolves+validates via _resolve_and_validate (net_trust.py:79-122).
2. Container gets --dns 0.0.0.0 (internal DNS disabled — DNS would bypass the pin).
3. Egress permitted ONLY to the pinned IP:port via per-call ephemeral network +
   daemon-side nftables/iptables egress rule on the bridge forward chain.
4. Single-family pin: the resolved family is allowed; the other is blocked.

Cross-platform honesty (ADR-037 D2 ratified §5.1(d)):
- Native Linux: host-side per-call firewall is fully viable.
- Docker Desktop (mac/win): host cannot reach VM firewall.
  - web_fetch (http/https): routes through host-side filtering proxy pinned to the IP.
  - git_push over ssh on Docker Desktop: non-viable → EgressDenied (fail-closed, loud).
"""

from __future__ import annotations

import ipaddress
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
    """Which egress-constraint mechanism applies for this runtime x tool combination."""

    DENY_DEFAULT = "deny_default"
    HOST_FIREWALL = "host_firewall"
    PROXY = "proxy"
    DENIED = "denied"


RuntimeKind = Literal["docker", "podman"]
ToolKind = Literal["subprocess", "web_fetch"]


@dataclass(frozen=True)
class EgressSpec:
    """Per-call egress specification produced by build_egress_spec().

    Fields:
    - mechanism: how egress is constrained.
    - pinned_ip: the single validated IP the container may reach.
    - pinned_port: the port the container may reach.
    - network_name: ephemeral Docker network name (HOST_FIREWALL / PROXY mechanisms).
    - dns_disabled: True = --dns 0.0.0.0 must appear in container args.
    - ipv4_only / ipv6_only: single-family pin (other family blocked).
    - firewall_rule: nftables/iptables rule to install (HOST_FIREWALL, informational).
    - proxy_addr: host proxy address for PROXY mechanism (web_fetch on Docker Desktop).
    """

    mechanism: EgressMechanism
    pinned_ip: str
    pinned_port: int
    network_name: str | None = None
    dns_disabled: bool = True
    ipv4_only: bool = False
    ipv6_only: bool = False
    firewall_rule: str | None = None
    proxy_addr: str | None = None


def build_egress_spec(
    pinned_ip: str,
    pinned_port: int,
    *,
    runtime_kind: RuntimeKind,
    tool_kind: ToolKind,
    on_docker_desktop: bool = False,
    call_id: str = "",
) -> EgressSpec:
    """Build the per-call egress specification for a given pinned IP:port.

    Args:
    - pinned_ip: the single IP validated by the parent's SSRF floor.
    - pinned_port: the target port (80/443/22/etc).
    - runtime_kind: "docker" or "podman".
    - tool_kind: "subprocess" (git_push) or "web_fetch".
    - on_docker_desktop: True when the runtime is Docker Desktop (mac/win VM).
    - call_id: for log correlation.

    Returns an EgressSpec; raises EgressDenied if no viable constrained path exists.
    The caller MUST NOT fall back to an unconstrained network — EgressDenied is fail-closed.
    """
    try:
        ip_obj = ipaddress.ip_address(pinned_ip)
    except ValueError as exc:
        raise EgressDenied(f"invalid pinned_ip {pinned_ip!r}: {exc}") from exc

    is_v4 = isinstance(ip_obj, ipaddress.IPv4Address)
    ipv4_only = is_v4
    ipv6_only = not is_v4

    network_name = f"sandbox-egress-{call_id}" if call_id else "sandbox-egress"

    if not on_docker_desktop:
        # Native Linux: host-side per-call firewall fully viable.
        firewall_rule = _build_firewall_rule(pinned_ip, pinned_port, network_name, is_v4)
        return EgressSpec(
            mechanism=EgressMechanism.HOST_FIREWALL,
            pinned_ip=pinned_ip,
            pinned_port=pinned_port,
            network_name=network_name,
            dns_disabled=True,
            ipv4_only=ipv4_only,
            ipv6_only=ipv6_only,
            firewall_rule=firewall_rule,
        )

    # Docker Desktop (mac/win): host cannot reach VM firewall.
    if tool_kind == "web_fetch":
        # web_fetch over http/https: route through host-side filtering proxy.
        proxy_port = _proxy_port_for(pinned_port)
        proxy_addr = f"http://host.docker.internal:{proxy_port}"
        _log.info(
            "egress: Docker Desktop web_fetch → host-proxy %s (pinned to %s:%s)",
            proxy_addr,
            pinned_ip,
            pinned_port,
        )
        return EgressSpec(
            mechanism=EgressMechanism.PROXY,
            pinned_ip=pinned_ip,
            pinned_port=pinned_port,
            network_name=network_name,
            dns_disabled=True,
            ipv4_only=ipv4_only,
            ipv6_only=ipv6_only,
            proxy_addr=proxy_addr,
        )

    # git_push over ssh on Docker Desktop: non-viable → fail-closed.
    raise EgressDenied(
        f"egress: (runtime=docker-desktop, tool={tool_kind!r}) has no viable "
        "constrained-egress path — failing closed (ADR-037 D2 cross-platform honesty; "
        "ssh-over-ssh on Docker Desktop VM cannot be pinned via host firewall). "
        "Use a native Linux runtime or disable the sandbox (degraded-opt-in)."
    )


def build_deny_default_spec() -> EgressSpec:
    """Return a deny-default (--network none) egress spec for tools that need no net."""
    return EgressSpec(
        mechanism=EgressMechanism.DENY_DEFAULT,
        pinned_ip="",
        pinned_port=0,
        network_name=None,
        dns_disabled=False,
    )


def container_network_args(spec: EgressSpec) -> list[str]:
    """Convert an EgressSpec to the --network / --dns container CLI args.

    Returns the list to extend the container's arg list with.
    docker.sock is never included (constitutional invariant lives in profile.py).
    """
    args: list[str] = []

    if spec.mechanism == EgressMechanism.DENY_DEFAULT:
        args += ["--network", "none"]
        return args

    # For HOST_FIREWALL, PROXY, or DENIED — network is the per-call ephemeral net.
    if spec.network_name:
        args += ["--network", spec.network_name]

    # Disable container-internal DNS (DNS would bypass the pinned-IP constraint).
    if spec.dns_disabled:
        args += ["--dns", "0.0.0.0"]

    # Block the non-pinned address family via sysctl (best-effort; the firewall rule
    # is the primary enforcement).
    if spec.ipv4_only:
        args += ["--sysctl", "net.ipv6.conf.all.disable_ipv6=1"]

    return args


def _build_firewall_rule(
    pinned_ip: str, pinned_port: int, network_name: str, is_v4: bool
) -> str:
    """Build the informational nftables/iptables rule for host-side enforcement.

    This is the rule the sandbox-run caller should install before launching the container
    and remove after. The rule is informational (a string descriptor); actual installation
    is the caller's responsibility (P4.3-4 spawn.py).
    """
    if is_v4:
        return (
            f"iptables -I FORWARD -o br-{network_name[:12]} "
            f"-d {pinned_ip} -p tcp --dport {pinned_port} -j ACCEPT; "
            f"iptables -I FORWARD -o br-{network_name[:12]} ! -d {pinned_ip} -j DROP"
        )
    return (
        f"ip6tables -I FORWARD -o br-{network_name[:12]} "
        f"-d {pinned_ip} -p tcp --dport {pinned_port} -j ACCEPT; "
        f"ip6tables -I FORWARD -o br-{network_name[:12]} ! -d {pinned_ip} -j DROP"
    )


def _proxy_port_for(target_port: int) -> int:
    """Map target port to the local filtering proxy port (Docker Desktop path)."""
    if target_port == 443:
        return 8443
    return 8080
