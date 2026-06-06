"""Tests for sandbox/egress.py (P4.3-3 / RW1).

Verifies: PROXY mechanism is always used for egress tools; pinned-IP + hostname carried;
DNS-disabled; v6-blocked-when-v4-pinned; deny-default spec; proxy env injected in args.
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
# build_egress_spec: always PROXY mechanism (RW1 — nftables withdrawn)
# ---------------------------------------------------------------------------


def test_always_uses_proxy_mechanism() -> None:
    spec = build_egress_spec(
        "93.184.216.34", 443, runtime_kind="docker", tool_kind="web_fetch", call_id="c1"
    )
    assert spec.mechanism == EgressMechanism.PROXY


def test_hostname_carried_in_spec() -> None:
    spec = build_egress_spec(
        "93.184.216.34", 443,
        runtime_kind="docker", tool_kind="web_fetch",
        hostname="example.com", call_id="c1"
    )
    assert spec.hostname == "example.com"


def test_hostname_defaults_to_pinned_ip_when_omitted() -> None:
    spec = build_egress_spec(
        "93.184.216.34", 443, runtime_kind="docker", tool_kind="web_fetch", call_id="c1"
    )
    assert spec.hostname == "93.184.216.34"


def test_pinned_ip_and_port() -> None:
    spec = build_egress_spec(
        "93.184.216.34", 443, runtime_kind="docker", tool_kind="web_fetch", call_id="c1"
    )
    assert spec.pinned_ip == "93.184.216.34"
    assert spec.pinned_port == 443


def test_dns_disabled() -> None:
    spec = build_egress_spec(
        "93.184.216.34", 80, runtime_kind="docker", tool_kind="web_fetch", call_id="c2"
    )
    assert spec.dns_disabled is True


def test_v4_pin_blocks_v6() -> None:
    """IPv4 pinned address → ipv4_only=True, ipv6_only=False."""
    spec = build_egress_spec(
        "93.184.216.34", 443, runtime_kind="docker", tool_kind="web_fetch", call_id="c3"
    )
    assert spec.ipv4_only is True
    assert spec.ipv6_only is False


def test_v6_pin_blocks_v4() -> None:
    """IPv6 pinned address → ipv6_only=True, ipv4_only=False."""
    spec = build_egress_spec(
        "2600:1408:ec00::17d3:8b86", 443,
        runtime_kind="docker", tool_kind="web_fetch", call_id="c4"
    )
    assert spec.ipv6_only is True
    assert spec.ipv4_only is False


def test_network_name_includes_call_id() -> None:
    spec = build_egress_spec(
        "1.2.3.4", 80, runtime_kind="docker", tool_kind="subprocess", call_id="abc"
    )
    assert spec.network_name is not None
    assert "abc" in spec.network_name


def test_subprocess_ssh_uses_proxy_not_denied() -> None:
    """git_push ssh uses PROXY mechanism (RW1 — ssh-via-ProxyCommand enabled)."""
    spec = build_egress_spec(
        "1.2.3.4", 22,
        runtime_kind="docker", tool_kind="subprocess",
        hostname="github.com", call_id="ssh1"
    )
    assert spec.mechanism == EgressMechanism.PROXY
    assert spec.pinned_port == 22


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
# container_network_args: DNS disabled + sysctl family-block + proxy env
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


def test_container_args_add_host_docker_internal() -> None:
    """PROXY spec must include --add-host host.docker.internal:host-gateway."""
    spec = build_egress_spec(
        "93.184.216.34", 443, runtime_kind="docker", tool_kind="web_fetch", call_id="ca3"
    )
    args = container_network_args(spec, proxy_port=8080)
    assert "--add-host" in args
    idx = args.index("--add-host")
    assert "host.docker.internal" in args[idx + 1]


def test_container_args_proxy_env_injected() -> None:
    """When proxy_port is set, HTTP_PROXY/HTTPS_PROXY env are in the args."""
    spec = build_egress_spec(
        "93.184.216.34", 443, runtime_kind="docker", tool_kind="web_fetch", call_id="ca4"
    )
    args = container_network_args(spec, proxy_port=12345)
    joined = " ".join(args)
    assert "HTTP_PROXY=http://host.docker.internal:12345" in joined
    assert "HTTPS_PROXY=http://host.docker.internal:12345" in joined


def test_container_args_git_ssh_command_injected() -> None:
    """When proxy_port is set, GIT_SSH_COMMAND with ProxyCommand is in the args."""
    spec = build_egress_spec(
        "1.2.3.4", 22, runtime_kind="docker", tool_kind="subprocess",
        hostname="github.com", call_id="ca5"
    )
    args = container_network_args(spec, proxy_port=12345)
    joined = " ".join(args)
    assert "GIT_SSH_COMMAND" in joined
    assert "ProxyCommand" in joined
    assert "12345" in joined


def test_container_args_no_docker_sock() -> None:
    """container_network_args must never include docker.sock."""
    spec = build_egress_spec(
        "93.184.216.34", 443, runtime_kind="docker", tool_kind="web_fetch", call_id="ca6"
    )
    args = container_network_args(spec, proxy_port=8080)
    assert not any("/var/run/docker.sock" in a for a in args)


def test_container_args_no_proxy_env_without_port() -> None:
    """Without proxy_port, no HTTP_PROXY/HTTPS_PROXY/GIT_SSH_COMMAND env vars."""
    spec = build_egress_spec(
        "93.184.216.34", 443, runtime_kind="docker", tool_kind="web_fetch", call_id="ca7"
    )
    args = container_network_args(spec, proxy_port=0)
    joined = " ".join(args)
    assert "HTTP_PROXY" not in joined
    assert "HTTPS_PROXY" not in joined
    assert "GIT_SSH_COMMAND" not in joined


# ---------------------------------------------------------------------------
# Invalid pinned_ip
# ---------------------------------------------------------------------------


def test_invalid_pinned_ip_raises_egress_denied() -> None:
    with pytest.raises(EgressDenied, match="invalid pinned_ip"):
        build_egress_spec(
            "not-an-ip", 443, runtime_kind="docker", tool_kind="web_fetch", call_id="inv"
        )
