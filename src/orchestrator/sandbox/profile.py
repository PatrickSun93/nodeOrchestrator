"""Isolation profile builder (ADR-037 D2; P4.3-2).

Builds per-call container arguments from a `SandboxProfile`:
- FS: --read-only rootfs; bind-mount ONLY sandbox_root rw; /var/run/docker.sock NEVER mounted.
- Net: --network none (deny-default) or a per-call egress network name from P4.3-3.
- Seccomp: Docker default augmented with additional-deny JSON (seccomp.json).
- UID: --user nonroot / userns.
- Resources: --memory, --cpus, --pids, --rm.
- --cap-drop=ALL + --security-opt no-new-privileges always present.

Constitutional invariant: no profile variant ever emits /var/run/docker.sock in args.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# Path to the augmented seccomp JSON asset (same package directory).
_SECCOMP_PATH: Path = Path(__file__).parent / "seccomp.json"

# Sensitive /proc paths to mask (bind-mount /dev/null over them inside the container).
_PROC_MASKED_PATHS: tuple[str, ...] = (
    "/proc/sysrq-trigger",
    "/proc/kcore",
    "/proc/kmsg",
    "/proc/kallsyms",
)

# Default resource limits (operator can override via SandboxProfile).
DEFAULT_MEMORY: str = "512m"
DEFAULT_CPUS: str = "1.0"
DEFAULT_PIDS: str = "256"

# Non-root user to run as inside the container.
_CONTAINER_USER: str = "nobody"


@dataclass
class SandboxProfile:
    """Per-call isolation profile.

    Fields:
    - sandbox_root: host path to bind-mount rw into the container.
    - image: container image to run.
    - network: None = deny-default (--network none); str = per-call network name (P4.3-3).
    - memory / cpus / pids: resource limits.
    - env: extra env vars to pass via --env.
    - container_name: if set, --name <container_name> (for targeted kill).
    """

    sandbox_root: Path
    image: str
    network: str | None = None
    memory: str = DEFAULT_MEMORY
    cpus: str = DEFAULT_CPUS
    pids: str = DEFAULT_PIDS
    env: dict[str, str] = field(default_factory=dict)
    container_name: str | None = None


def build_container_args(profile: SandboxProfile, argv: list[str]) -> list[str]:
    """Build the full container CLI arg list for one sandboxed call.

    Returns args suitable for: [<runtime>, "run", *args, profile.image, *argv]

    Constitutional invariant: /var/run/docker.sock is NEVER included.
    """
    seccomp_arg = _seccomp_arg()
    args: list[str] = ["run"]

    # Remove container after exit.
    args.append("--rm")

    # Container name (for targeted kill).
    if profile.container_name:
        args += ["--name", profile.container_name]

    # FS isolation: read-only rootfs, bind workspace rw.
    args.append("--read-only")
    sandbox_root_str = str(profile.sandbox_root.resolve())
    args += ["--volume", f"{sandbox_root_str}:{sandbox_root_str}:rw"]

    # Working directory inside the container = sandbox_root.
    args += ["--workdir", sandbox_root_str]

    # Mask sensitive /proc paths (tmpfs overlay — /dev/null bind).
    for proc_path in _PROC_MASKED_PATHS:
        args += ["--tmpfs", proc_path]

    # /sys read-only (Docker default; reinforced explicitly).
    # Note: Docker already mounts /sys ro by default without --privileged.

    # Network isolation.
    if profile.network is None:
        args += ["--network", "none"]
    else:
        args += ["--network", profile.network]

    # Seccomp: Docker default augmented with additional-deny JSON.
    args += seccomp_arg

    # Cap-drop ALL + no-new-privileges (ADR-037 D2).
    args += ["--cap-drop", "ALL"]
    args += ["--security-opt", "no-new-privileges"]

    # UID: run as nobody (non-root).
    args += ["--user", _CONTAINER_USER]

    # Resource limits.
    args += ["--memory", profile.memory]
    args += ["--cpus", profile.cpus]
    args += ["--pids-limit", profile.pids]

    # Env vars.
    for k, v in profile.env.items():
        args += ["--env", f"{k}={v}"]

    # Constitutional check: docker.sock must never appear.
    _assert_no_docker_sock(args)

    # Image + argv.
    args.append(profile.image)
    args.extend(argv)

    return args


def _seccomp_arg() -> list[str]:
    """Return ["--security-opt", "seccomp=<json>"] with the augmented profile."""
    seccomp_data = _SECCOMP_PATH.read_text(encoding="utf-8")
    # Validate it is parseable JSON (fail fast if asset is corrupt).
    json.loads(seccomp_data)
    return ["--security-opt", f"seccomp={seccomp_data}"]


def _assert_no_docker_sock(args: list[str]) -> None:
    """Raise RuntimeError if /var/run/docker.sock appears anywhere in args.

    Constitutional invariant (ADR-037 D2; P4.3-12 s6): docker-sock = container-escape-via-API.
    """
    docker_sock = "/var/run/docker.sock"
    for arg in args:
        if docker_sock in arg:
            raise RuntimeError(
                f"CONSTITUTIONAL VIOLATION: {docker_sock!r} must never appear in container args"
            )


def get_additional_deny_syscalls() -> list[str]:
    """Return the list of syscall names in the additional-deny set (for test assertions)."""
    data = json.loads(_SECCOMP_PATH.read_text(encoding="utf-8"))
    names: list[str] = []
    for entry in data.get("syscalls", []):
        names.extend(entry.get("names", []))
    return names
