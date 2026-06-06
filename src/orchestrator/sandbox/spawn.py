"""The one sandboxed-spawn interface (ADR-037 D3; P4.3-4).

sandboxed_run(argv, *, cwd, env, timeout_s, max_bytes, profile, egress_spec)
  -> SubprocessResult

Builds the container invocation (runtime + profile.build_container_args + egress
network args), spawns reusing the existing bounded-read + run_sync timeout +
shielded-kill machinery, re-homes the kill to container kill (retires R3), measures
setup/teardown latency against the 3s p95 target, and creates/tears down the per-call
egress network.

Key properties:
- Timeout wraps the whole `docker run` incl. container startup (setup inside deadline).
- Teardown is shielded so a timeout-cancel still reaps the container (no leaks).
- Runtime unavailable OR daemon-dies-at-spawn → SandboxUnavailableError (never raw spawn).
- Setup/teardown latency logged against 3s p95 target (plan-vs-impl gate).
"""

from __future__ import annotations

import logging
import subprocess
import time
import uuid
from pathlib import Path

from orchestrator.mcp.subprocess_trust import SubprocessResult, SubprocessTimeoutError
from orchestrator.sandbox.egress import EgressSpec, container_network_args
from orchestrator.sandbox.profile import SandboxProfile, build_container_args
from orchestrator.sandbox.runtime import SandboxRuntime, SandboxUnavailableError

_log = logging.getLogger("orchestrator.sandbox.spawn")

# p95 target for per-call container setup+teardown (ADR-037 D3; plan-vs-impl gate).
SETUP_TEARDOWN_P95_TARGET_S: float = 3.0

# Bounded output cap (matches run_scoped_command default).
DEFAULT_MAX_BYTES: int = 64 * 1024


def sandboxed_run(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_s: float = 30.0,
    max_bytes: int = DEFAULT_MAX_BYTES,
    profile: SandboxProfile,
    egress_spec: EgressSpec | None = None,
    runtime: SandboxRuntime,
) -> SubprocessResult:
    """Run argv in a sandboxed container and return bounded stdout+stderr + exit code.

    Raises SandboxUnavailableError when:
    - runtime.available() returned False (caller should have checked).
    - runtime is available at probe time but the `docker run` spawn itself fails
      (daemon-dies-at-spawn path).

    Teardown (container kill + rm) is shielded so it completes even on timeout.
    Setup/teardown latency is measured and logged against SETUP_TEARDOWN_P95_TARGET_S.
    """
    if not runtime.available():
        raise SandboxUnavailableError(
            f"sandbox runtime {runtime.kind!r} is unavailable (daemon not reachable)"
        )

    call_id = str(uuid.uuid4())[:8]
    container_name = f"sandbox-{call_id}"

    profile_with_name = SandboxProfile(
        sandbox_root=profile.sandbox_root,
        image=profile.image,
        network=profile.network,
        memory=profile.memory,
        cpus=profile.cpus,
        pids=profile.pids,
        env={**profile.env, **env},
        container_name=container_name,
    )

    container_args = build_container_args(profile_with_name, argv)

    net_args: list[str] = []
    if egress_spec is not None:
        net_args = container_network_args(egress_spec)
        if egress_spec.network_name:
            profile_with_name = SandboxProfile(
                sandbox_root=profile.sandbox_root,
                image=profile.image,
                network=egress_spec.network_name,
                memory=profile.memory,
                cpus=profile.cpus,
                pids=profile.pids,
                env={**profile.env, **env},
                container_name=container_name,
            )
            container_args = build_container_args(profile_with_name, argv)

    # Merge DNS/sysctl args from egress into container_args (before image position).
    if net_args:
        img_idx = _find_image_idx(container_args, profile.image)
        if img_idx is not None:
            container_args = container_args[:img_idx] + net_args + container_args[img_idx:]

    full_argv = [runtime.cli, *container_args]

    t_setup_start = time.monotonic()
    network_created = False

    try:
        if egress_spec is not None and egress_spec.network_name:
            _create_network(runtime, egress_spec.network_name)
            network_created = True

        # setup_s = host-side setup overhead (network create; proxy start added by RW1).
        # The in-container startup is NOT separable in the subprocess.run blocking shape.
        setup_s = time.monotonic() - t_setup_start
        if setup_s > SETUP_TEARDOWN_P95_TARGET_S:
            _log.warning(
                "sandbox: setup overhead exceeded p95 target: %.2fs > %.2fs (call_id=%s)",
                setup_s,
                SETUP_TEARDOWN_P95_TARGET_S,
                call_id,
            )

        result = _run_container(full_argv, cwd=cwd, timeout_s=timeout_s, max_bytes=max_bytes)

    except (OSError, FileNotFoundError) as exc:
        raise SandboxUnavailableError(
            f"sandbox: spawn failed (daemon-dies-at-spawn?): {exc}"
        ) from exc
    finally:
        t_teardown_start = time.monotonic()
        _safe_kill(runtime, container_name)
        if network_created and egress_spec is not None and egress_spec.network_name:
            _remove_network(runtime, egress_spec.network_name)
        # teardown_s = host-side teardown overhead (kill + rm + net rm; proxy stop added by RW1).
        teardown_s = time.monotonic() - t_teardown_start
        overhead_s = setup_s + teardown_s
        _log.debug(
            "sandbox: call_id=%s overhead=%.3fs (setup=%.3fs teardown=%.3fs) p95_target=%.1fs",
            call_id,
            overhead_s,
            setup_s,
            teardown_s,
            SETUP_TEARDOWN_P95_TARGET_S,
        )
        if overhead_s > SETUP_TEARDOWN_P95_TARGET_S:
            _log.warning(
                "sandbox: host-side overhead %.2fs exceeds p95 target %.2fs (call_id=%s)",
                overhead_s,
                SETUP_TEARDOWN_P95_TARGET_S,
                call_id,
            )

    return result


def _run_container(
    full_argv: list[str],
    *,
    cwd: Path,
    timeout_s: float,
    max_bytes: int,
) -> SubprocessResult:
    """Run the container via subprocess.run with bounded output + timeout.

    Raises OSError on spawn failure (daemon-dies-at-spawn).
    Raises SubprocessTimeoutError on timeout.
    """
    try:
        completed = subprocess.run(
            full_argv,
            cwd=cwd,
            capture_output=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise SubprocessTimeoutError(
            f"sandboxed_run: container exceeded timeout {timeout_s}s"
        ) from exc

    raw_output = completed.stdout + completed.stderr
    truncated = len(raw_output) > max_bytes
    output = raw_output[:max_bytes].decode("utf-8", errors="replace")

    return SubprocessResult(
        exit_code=completed.returncode,
        output=output,
        truncated=truncated,
    )


def _find_image_idx(args: list[str], image: str) -> int | None:
    """Find the index of the image name in the container args list."""
    try:
        return args.index(image)
    except ValueError:
        return None


def _create_network(runtime: SandboxRuntime, network_name: str) -> None:
    """Create a per-call ephemeral Docker network (best-effort; swallows errors)."""
    try:
        subprocess.run(
            [runtime.cli, "network", "create", "--driver", "bridge", network_name],
            capture_output=True,
            timeout=5.0,
        )
    except Exception as exc:
        _log.debug("sandbox: network create %r failed: %s", network_name, exc)


def _remove_network(runtime: SandboxRuntime, network_name: str) -> None:
    """Remove a per-call ephemeral Docker network (best-effort; swallows errors)."""
    try:
        subprocess.run(
            [runtime.cli, "network", "rm", network_name],
            capture_output=True,
            timeout=5.0,
        )
    except Exception as exc:
        _log.debug("sandbox: network rm %r failed: %s", network_name, exc)


def _safe_kill(runtime: SandboxRuntime, container_name: str) -> None:
    """Kill + rm container (shielded teardown; swallows all errors)."""
    runtime.kill(container_name)
