"""Tests for sandbox/egress.py (P4.3-3).

Verifies pinned-IP rule shape, DNS-disabled present, v6-blocked-when-v4-pinned,
and Docker-Desktop-ssh → fail-closed path.  Runtime is mocked.
"""

from __future__ import annotations

import pytest

from orchestrator.sandbox.egress import (
    EgressDenied,
    EgressMechanism,
    build_deny_default_spec,
    build_egress_spec,
    container_network_args,
)

# ---------------------------------------------------------------------------
# Native Linux: HOST_FIREWALL mechanism
# ---------------------------------------------------------------------------


def test_native_linux_uses_host_firewall() -> None:
    spec = build_egress_spec(
        "93.184.216.34", 443, runtime_kind="docker", tool_kind="web_fetch", call_id="c1"
    )
    assert spec.mechanism == EgressMechanism.HOST_FIREWALL


def test_native_linux_pinned_ip_and_port() -> None:
    spec = build_egress_spec(
        "93.184.216.34", 443, runtime_kind="docker", tool_kind="web_fetch", call_id="c1"
    )
    assert spec.pinned_ip == "93.184.216.34"
    assert spec.pinned_port == 443


def test_native_linux_dns_disabled() -> None:
    spec = build_egress_spec(
        "93.184.216.34", 80, runtime_kind="docker", tool_kind="web_fetch", call_id="c2"
    )
    assert spec.dns_disabled is True


def test_native_linux_v4_pin_blocks_v6() -> None:
    """IPv4 pinned address → ipv4_only=True, ipv6_only=False."""
    spec = build_egress_spec(
        "93.184.216.34", 443, runtime_kind="docker", tool_kind="web_fetch", call_id="c3"
    )
    assert spec.ipv4_only is True
    assert spec.ipv6_only is False


def test_native_linux_v6_pin_blocks_v4() -> None:
    """IPv6 pinned address → ipv6_only=True, ipv4_only=False."""
    spec = build_egress_spec(
        "2600:1408:ec00::17d3:8b86", 443,
        runtime_kind="docker", tool_kind="web_fetch", call_id="c4"
    )
    assert spec.ipv6_only is True
    assert spec.ipv4_only is False


def test_native_linux_firewall_rule_present() -> None:
    spec = build_egress_spec(
        "93.184.216.34", 443, runtime_kind="docker", tool_kind="web_fetch", call_id="c5"
    )
    assert spec.firewall_rule is not None
    assert "93.184.216.34" in spec.firewall_rule
    assert "443" in spec.firewall_rule


def test_native_linux_network_name_includes_call_id() -> None:
    spec = build_egress_spec(
        "1.2.3.4", 80, runtime_kind="docker", tool_kind="subprocess", call_id="abc"
    )
    assert spec.network_name is not None
    assert "abc" in spec.network_name


# ---------------------------------------------------------------------------
# Docker Desktop: PROXY for web_fetch, DENIED for git_push ssh
# ---------------------------------------------------------------------------


def test_docker_desktop_web_fetch_uses_proxy() -> None:
    spec = build_egress_spec(
        "93.184.216.34", 443,
        runtime_kind="docker", tool_kind="web_fetch",
        on_docker_desktop=True, call_id="dd1"
    )
    assert spec.mechanism == EgressMechanism.PROXY
    assert spec.proxy_addr is not None


def test_docker_desktop_web_fetch_proxy_dns_disabled() -> None:
    spec = build_egress_spec(
        "93.184.216.34", 443,
        runtime_kind="docker", tool_kind="web_fetch",
        on_docker_desktop=True, call_id="dd2"
    )
    assert spec.dns_disabled is True


def test_docker_desktop_ssh_subprocess_denied() -> None:
    """git_push over ssh on Docker Desktop → EgressDenied (fail-closed)."""
    with pytest.raises(EgressDenied):
        build_egress_spec(
            "1.2.3.4", 22,
            runtime_kind="docker", tool_kind="subprocess",
            on_docker_desktop=True, call_id="dd3"
        )


def test_docker_desktop_denied_is_not_unconstrained() -> None:
    """EgressDenied must be raised — caller must not silently fall back."""
    raised = False
    try:
        build_egress_spec(
            "1.2.3.4", 22,
            runtime_kind="docker", tool_kind="subprocess",
            on_docker_desktop=True, call_id="dd4"
        )
    except EgressDenied:
        raised = True
    assert raised, "EgressDenied must be raised for non-viable runtime x tool combos"


# ---------------------------------------------------------------------------
# Deny-default spec (--network none)
# ---------------------------------------------------------------------------


def test_deny_default_spec() -> None:
    spec = build_deny_default_spec()
    assert spec.mechanism == EgressMechanism.DENY_DEFAULT
    assert spec.pinned_ip == ""
    assert spec.pinned_port == 0


def test_deny_default_container_args() -> None:
    spec = build_deny_default_spec()
    args = container_network_args(spec)
    assert "--network" in args
    idx = args.index("--network")
    assert args[idx + 1] == "none"


# ---------------------------------------------------------------------------
# container_network_args: DNS disabled + sysctl family-block
# ---------------------------------------------------------------------------


def test_container_args_dns_disabled_present() -> None:
    spec = build_egress_spec(
        "93.184.216.34", 443, runtime_kind="docker", tool_kind="web_fetch", call_id="ca1"
    )
    args = container_network_args(spec)
    assert "--dns" in args
    idx = args.index("--dns")
    assert args[idx + 1] == "0.0.0.0"


def test_container_args_ipv6_disabled_when_ipv4_pinned() -> None:
    spec = build_egress_spec(
        "93.184.216.34", 443, runtime_kind="docker", tool_kind="web_fetch", call_id="ca2"
    )
    args = container_network_args(spec)
    assert any("disable_ipv6" in a for a in args), (
        "IPv6 should be disabled when IPv4 is pinned"
    )


def test_container_args_no_docker_sock() -> None:
    """container_network_args must never include docker.sock."""
    spec = build_egress_spec(
        "93.184.216.34", 443, runtime_kind="docker", tool_kind="web_fetch", call_id="ca3"
    )
    args = container_network_args(spec)
    assert not any("/var/run/docker.sock" in a for a in args)


# ---------------------------------------------------------------------------
# Invalid pinned_ip
# ---------------------------------------------------------------------------


def test_invalid_pinned_ip_raises_egress_denied() -> None:
    with pytest.raises(EgressDenied, match="invalid pinned_ip"):
        build_egress_spec(
            "not-an-ip", 443, runtime_kind="docker", tool_kind="web_fetch", call_id="inv"
        )
