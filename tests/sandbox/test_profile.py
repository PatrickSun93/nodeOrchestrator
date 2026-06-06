"""Tests for sandbox/profile.py (P4.3-2).

Verifies arg-list shape per profile variant, docker-sock invariant, and seccomp asset.
No live container needed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.sandbox.profile import (
    _SECCOMP_PATH,
    SandboxProfile,
    build_container_args,
    get_additional_deny_syscalls,
)


def _profile(
    sandbox_root: Path,
    image: str = "test-image:latest",
    network: str | None = None,
    container_name: str | None = None,
) -> SandboxProfile:
    return SandboxProfile(
        sandbox_root=sandbox_root,
        image=image,
        network=network,
        container_name=container_name,
    )


# ---------------------------------------------------------------------------
# Basic arg-list shape
# ---------------------------------------------------------------------------


def test_build_args_deny_default_network(tmp_path: Path) -> None:
    args = build_container_args(_profile(tmp_path), argv=["pytest", "-q"])
    assert "--network" in args
    idx = args.index("--network")
    assert args[idx + 1] == "none"


def test_build_args_named_network(tmp_path: Path) -> None:
    args = build_container_args(_profile(tmp_path, network="sandbox-net-abc"), argv=[])
    idx = args.index("--network")
    assert args[idx + 1] == "sandbox-net-abc"


def test_build_args_read_only_rootfs(tmp_path: Path) -> None:
    args = build_container_args(_profile(tmp_path), argv=[])
    assert "--read-only" in args


def test_build_args_workspace_rw_mount(tmp_path: Path) -> None:
    args = build_container_args(_profile(tmp_path), argv=[])
    root_str = str(tmp_path.resolve())
    volume_args = [args[i + 1] for i, a in enumerate(args) if a == "--volume"]
    assert any(root_str in v and v.endswith(":rw") for v in volume_args), (
        f"workspace rw bind not found; volume args: {volume_args}"
    )


def test_build_args_cap_drop_all(tmp_path: Path) -> None:
    args = build_container_args(_profile(tmp_path), argv=[])
    assert "--cap-drop" in args
    idx = args.index("--cap-drop")
    assert args[idx + 1] == "ALL"


def test_build_args_no_new_privileges(tmp_path: Path) -> None:
    args = build_container_args(_profile(tmp_path), argv=[])
    assert "no-new-privileges" in " ".join(args)


def test_build_args_nonroot_user(tmp_path: Path) -> None:
    args = build_container_args(_profile(tmp_path), argv=[])
    assert "--user" in args


def test_build_args_resource_limits_present(tmp_path: Path) -> None:
    args = build_container_args(_profile(tmp_path), argv=[])
    assert "--memory" in args
    assert "--cpus" in args
    assert "--pids-limit" in args


def test_build_args_rm_present(tmp_path: Path) -> None:
    args = build_container_args(_profile(tmp_path), argv=[])
    assert "--rm" in args


def test_build_args_image_and_argv_last(tmp_path: Path) -> None:
    argv = ["pytest", "-q", "tests/"]
    args = build_container_args(_profile(tmp_path, image="myimage:1.0"), argv=argv)
    img_idx = args.index("myimage:1.0")
    assert args[img_idx + 1 :] == argv


def test_build_args_container_name(tmp_path: Path) -> None:
    args = build_container_args(_profile(tmp_path, container_name="sandbox-1234"), argv=[])
    assert "--name" in args
    idx = args.index("--name")
    assert args[idx + 1] == "sandbox-1234"


def test_build_args_env_vars(tmp_path: Path) -> None:
    profile = SandboxProfile(
        sandbox_root=tmp_path,
        image="img",
        env={"FOO": "bar", "BAZ": "qux"},
    )
    args = build_container_args(profile, argv=[])
    env_vals = [args[i + 1] for i, a in enumerate(args) if a == "--env"]
    assert "FOO=bar" in env_vals
    assert "BAZ=qux" in env_vals


# ---------------------------------------------------------------------------
# Docker-sock constitutional invariant
# ---------------------------------------------------------------------------


def test_no_docker_sock_in_deny_default_profile(tmp_path: Path) -> None:
    args = build_container_args(_profile(tmp_path), argv=[])
    assert not any("/var/run/docker.sock" in a for a in args), (
        "docker-sock appeared in deny-default profile args"
    )


def test_no_docker_sock_in_egress_profile(tmp_path: Path) -> None:
    args = build_container_args(_profile(tmp_path, network="net123"), argv=[])
    assert not any("/var/run/docker.sock" in a for a in args)


def test_docker_sock_injection_raises() -> None:
    """A profile that somehow injects docker.sock via image name raises RuntimeError."""
    from orchestrator.sandbox.profile import _assert_no_docker_sock

    with pytest.raises(RuntimeError, match="CONSTITUTIONAL VIOLATION"):
        _assert_no_docker_sock(["--volume", "/var/run/docker.sock:/var/run/docker.sock"])


# ---------------------------------------------------------------------------
# Seccomp asset: denies enumerated syscalls
# ---------------------------------------------------------------------------


def test_seccomp_asset_is_valid_json() -> None:
    data = json.loads(_SECCOMP_PATH.read_text(encoding="utf-8"))
    assert "syscalls" in data


ENUMERATED_ADDITIONAL_DENY = {
    "unshare",
    "clone",
    "bpf",
    "io_uring_setup",
    "add_key",
    "request_key",
    "keyctl",
    "ptrace",
    "mount",
}


def test_seccomp_asset_denies_enumerated_syscalls() -> None:
    syscalls = set(get_additional_deny_syscalls())
    missing = ENUMERATED_ADDITIONAL_DENY - syscalls
    assert not missing, (
        f"Seccomp asset missing enumerated syscall denials: {sorted(missing)}"
    )


def test_seccomp_arg_present_in_build_args(tmp_path: Path) -> None:
    args = build_container_args(_profile(tmp_path), argv=[])
    seccomp_present = any("seccomp=" in a for a in args)
    assert seccomp_present, "seccomp profile not injected via --security-opt"


# ---------------------------------------------------------------------------
# RW3 / RW8 assertion 4: seccomp asset is ALLOW-default (not ERRNO-default)
# ---------------------------------------------------------------------------


def test_rw8_seccomp_default_action_is_allow() -> None:
    """RW8-4: defaultAction must be SCMP_ACT_ALLOW (not SCMP_ACT_ERRNO which bricks container)."""
    import json
    from pathlib import Path as _Path

    seccomp_path = (
        _Path(__file__).parent.parent.parent
        / "src" / "orchestrator" / "sandbox" / "seccomp.json"
    )
    data = json.loads(seccomp_path.read_text(encoding="utf-8"))
    assert data["defaultAction"] == "SCMP_ACT_ALLOW", (
        "seccomp.json defaultAction must be SCMP_ACT_ALLOW (not ERRNO — that bricks the "
        "container via --security-opt seccomp= which replaces, not merges)"
    )


def test_rw8_seccomp_no_errno_default_action() -> None:
    """RW8-4: ensure the OLD broken defaultAction=SCMP_ACT_ERRNO is absent."""
    import json
    from pathlib import Path as _Path

    seccomp_path = (
        _Path(__file__).parent.parent.parent
        / "src" / "orchestrator" / "sandbox" / "seccomp.json"
    )
    data = json.loads(seccomp_path.read_text(encoding="utf-8"))
    assert data.get("defaultAction") != "SCMP_ACT_ERRNO", (
        "defaultAction must not be SCMP_ACT_ERRNO (bricks all syscalls in container)"
    )


def test_rw8_seccomp_denylist_superset_of_p4_3_set() -> None:
    """RW8-4: denylist ⊇ the P4.3 enumerated additional denials."""
    syscalls = set(get_additional_deny_syscalls())
    p4_3_required = {
        "unshare", "clone", "bpf", "io_uring_setup",
        "add_key", "request_key", "keyctl", "ptrace", "mount",
    }
    # Also check Docker default-blocked set is represented
    docker_default_sample = {
        "acct", "kexec_load", "pivot_root", "reboot", "settimeofday", "sysfs",
    }
    missing_p4_3 = p4_3_required - syscalls
    missing_docker = docker_default_sample - syscalls
    assert not missing_p4_3, f"Seccomp missing P4.3 enumerated denials: {sorted(missing_p4_3)}"
    assert not missing_docker, f"Seccomp missing Docker default sample: {sorted(missing_docker)}"


# ---------------------------------------------------------------------------
# Proc masking
# ---------------------------------------------------------------------------


def test_proc_sysrq_masked(tmp_path: Path) -> None:
    args = build_container_args(_profile(tmp_path), argv=[])
    assert "/proc/sysrq-trigger" in " ".join(args)
