"""Container runtime detection + liveness abstraction (ADR-037 D1; P4.3-1).

Detects the available container runtime (podman → docker preference order, prefer
rootless/podman userns), probes daemon liveness with a bounded timeout, and exposes
a `SandboxRuntime` handle.

Key properties:
- `available() -> bool`: liveness (not CLI presence). present CLI + dead daemon → False.
- Probe has its own ~2s timeout; a hung `docker info` cannot block the writer.
- No exception escapes `available()` — daemon-down → False, silently.
- `run(spec)` / `kill(container_id)` are the only spawn primitives.
"""

from __future__ import annotations

import contextlib
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Literal

_log = logging.getLogger("orchestrator.sandbox.runtime")

# Probe timeout for `<runtime> info` (ADR-037 D1, R0-B Y3b).
LIVENESS_PROBE_TIMEOUT_S: float = 2.0

RuntimeKind = Literal["docker", "podman"]


class SandboxUnavailableError(Exception):
    """Raised when the sandbox runtime is required but unavailable.

    Posture resolver maps this to TOOL_FAILED (loud surfaced error).
    Never raised by available() — that returns False instead.
    """


@dataclass
class ContainerSpec:
    """Arguments to launch one sandbox container."""

    image: str
    argv: list[str]
    container_args: list[str] = field(default_factory=list)


@dataclass
class ContainerResult:
    """Result of a sandboxed container run (matches SubprocessResult shape)."""

    exit_code: int
    output: str
    truncated: bool


class SandboxRuntime:
    """Handle to a detected + liveness-probed container runtime.

    Constructed by `detect()`. Users should call `available()` before `run()`.
    """

    def __init__(self, kind: RuntimeKind, cli: str) -> None:
        self._kind = kind
        self._cli = cli

    @property
    def kind(self) -> RuntimeKind:
        return self._kind

    @property
    def cli(self) -> str:
        return self._cli

    def available(self) -> bool:
        """Return True iff the daemon is currently reachable.

        Probes `<runtime> info` with LIVENESS_PROBE_TIMEOUT_S.
        A hung probe is bounded by the timeout — never blocks the caller.
        Never raises; daemon-down → False.
        """
        return _probe_liveness(self._cli)

    def kill(self, container_id: str) -> None:
        """Send kill + rm to a running container (best-effort; swallows errors)."""
        with contextlib.suppress(Exception):
            subprocess.run(
                [self._cli, "kill", container_id],
                timeout=5.0,
                capture_output=True,
            )
        with contextlib.suppress(Exception):
            subprocess.run(
                [self._cli, "rm", "-f", container_id],
                timeout=5.0,
                capture_output=True,
            )


def _probe_liveness(cli: str) -> bool:
    """Run `<cli> info` with LIVENESS_PROBE_TIMEOUT_S; return False on any failure."""
    try:
        result = subprocess.run(
            [cli, "info"],
            timeout=LIVENESS_PROBE_TIMEOUT_S,
            capture_output=True,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        _log.debug("sandbox runtime probe timed out for %r", cli)
        return False
    except Exception as exc:
        _log.debug("sandbox runtime probe failed for %r: %s", cli, exc)
        return False


def detect() -> SandboxRuntime | None:
    """Detect the first available container runtime (podman → docker).

    Returns a `SandboxRuntime` if a runtime CLI is present AND its daemon is live,
    or None if neither is available. Prefers podman (rootless userns story).

    Liveness probe uses LIVENESS_PROBE_TIMEOUT_S per candidate.
    """
    for kind in ("podman", "docker"):
        kind_typed: RuntimeKind = kind
        cli = shutil.which(kind)
        if cli is None:
            _log.debug("sandbox: %r not found on PATH", kind)
            continue
        if _probe_liveness(cli):
            _log.info("sandbox: using runtime %r (%s)", kind, cli)
            return SandboxRuntime(kind=kind_typed, cli=cli)
        _log.debug("sandbox: %r CLI found but daemon not live", kind)
    return None
