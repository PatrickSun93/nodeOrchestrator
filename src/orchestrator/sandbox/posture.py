"""Posture resolver: default-on where available; fail-closed default (ADR-037 D4; P4.3-5).

Posture modes:
- SANDBOXED: runtime available → all execs go through sandboxed_run.
- FAIL_CLOSED: runtime unavailable + no opt-in → TOOL_FAILED (SandboxUnavailableError).
- DEGRADED: runtime unavailable + explicit operator opt-in → today's app-level posture
  (raw run_scoped_command / in-process SSRF / current apply_edit), loudly warned.

Key invariants (ADR-037 D4):
- Config-parse failure → FAIL_CLOSED (never a fail-open default).
- available() cached per turn (short TTL) so a wedged daemon fails fast.
- Degraded path: WARNING logged on EVERY call, never silent.
- No path reaches a raw host spawn when unavailable-and-not-opted-in.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from orchestrator.sandbox.runtime import SandboxRuntime, SandboxUnavailableError, detect

_log = logging.getLogger("orchestrator.sandbox.posture")

# TTL for caching the liveness result per turn (seconds).
_LIVENESS_CACHE_TTL_S: float = 30.0


class SandboxPosture(Enum):
    SANDBOXED = "sandboxed"
    FAIL_CLOSED = "fail_closed"
    DEGRADED = "degraded"


@dataclass
class SandboxConfig:
    """Parsed operator configuration for the sandbox.

    Fields map to config/sandbox.yaml:
    - runtime: "auto", "docker", or "podman".
    - image: container image with toolchain.
    - egress_allowlist: list of allowed hosts (informational).
    - degraded_app_level: opt-in to degraded posture when runtime unavailable.
    """

    runtime: str = "auto"
    image: str = "sandbox:latest"
    egress_allowlist: list[str] = field(default_factory=list)
    degraded_app_level: bool = False


class PostureResolver:
    """Resolves and caches the sandbox posture for the current turn.

    Usage:
        resolver = PostureResolver(config)
        posture = resolver.resolve()

    Caches the liveness check result for _LIVENESS_CACHE_TTL_S seconds so a wedged
    daemon doesn't stack up probe timeouts on every call within a turn.
    """

    def __init__(self, config: SandboxConfig, runtime: SandboxRuntime | None = None) -> None:
        self._config = config
        self._runtime = runtime
        self._cached_available: bool | None = None
        self._cache_ts: float = 0.0

    @classmethod
    def from_config(cls, config: SandboxConfig) -> PostureResolver:
        """Build a PostureResolver, detecting the runtime from config."""
        runtime = _detect_runtime(config)
        return cls(config=config, runtime=runtime)

    @classmethod
    def fail_closed(cls) -> PostureResolver:
        """Build a FAIL_CLOSED resolver (no runtime, no opt-in).

        Used by the composition root when config is absent or unparseable.
        Resolves FAIL_CLOSED on every call — no subprocess/egress executes.
        """
        return cls(config=SandboxConfig(degraded_app_level=False), runtime=None)

    def resolve(self) -> SandboxPosture:
        """Return the current posture (cached; re-probes after TTL expiry).

        SANDBOXED if runtime is available.
        FAIL_CLOSED if unavailable + not opted-in (config-parse failure = fail-closed).
        DEGRADED if unavailable + operator opted-in (loudly warned per call).
        """
        available = self._check_available()
        if available:
            return SandboxPosture.SANDBOXED
        if self._config.degraded_app_level:
            return SandboxPosture.DEGRADED
        return SandboxPosture.FAIL_CLOSED

    def get_runtime(self) -> SandboxRuntime | None:
        return self._runtime

    def _check_available(self) -> bool:
        """Check daemon liveness; cached per turn with TTL."""
        now = time.monotonic()
        if self._cached_available is not None and (now - self._cache_ts) < _LIVENESS_CACHE_TTL_S:
            return self._cached_available
        result = False if self._runtime is None else self._runtime.available()
        self._cached_available = result
        self._cache_ts = now
        return result

    def assert_sandboxed_or_raise(self, tool_name: str = "") -> SandboxRuntime:
        """Return runtime if SANDBOXED; raise SandboxUnavailableError if FAIL_CLOSED;
        warn loudly and raise SandboxUnavailableError if DEGRADED is not opted-in.

        For the DEGRADED path (opted-in), the caller must handle the degraded run itself —
        this method only validates the posture and raises when execution must be blocked.
        """
        posture = self.resolve()
        if posture == SandboxPosture.SANDBOXED:
            assert self._runtime is not None
            return self._runtime
        if posture == SandboxPosture.DEGRADED:
            _log.warning(
                "sandbox: DEGRADED posture for %r — running unsandboxed "
                "(operator degraded_app_level opt-in; RB-FS/NET residual re-exposed)",
                tool_name,
            )
            raise SandboxUnavailableError(
                f"sandbox: DEGRADED posture — {tool_name!r} running unsandboxed "
                "(degraded_app_level opt-in active; caller must use app-level fallback)"
            )
        raise SandboxUnavailableError(
            f"sandbox: FAIL_CLOSED — runtime unavailable, no opt-in; "
            f"{tool_name!r} blocked (no host spawn without working sandbox)"
        )

    def is_degraded_opted_in(self) -> bool:
        """Return True if the operator opted into degraded-app-level posture."""
        return self._config.degraded_app_level


def load_sandbox_config(config_path: Path) -> SandboxConfig:
    """Parse sandbox.yaml; config-parse failure → raises SandboxConfigError (caller fails closed).

    Raises SandboxConfigError on:
    - file not found / unreadable
    - invalid YAML
    - unknown runtime value
    - missing required fields
    """
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SandboxConfigError(f"cannot read sandbox config {config_path}: {exc}") from exc

    try:
        data: Any = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SandboxConfigError(f"invalid YAML in sandbox config {config_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise SandboxConfigError(
            f"sandbox config {config_path}: expected a YAML mapping, got {type(data).__name__}"
        )

    runtime = data.get("runtime", "auto")
    if runtime not in ("auto", "docker", "podman"):
        raise SandboxConfigError(
            f"sandbox config: invalid runtime {runtime!r} (allowed: auto, docker, podman)"
        )

    image = data.get("image", "sandbox:latest")
    if not isinstance(image, str) or not image:
        raise SandboxConfigError(
            f"sandbox config: 'image' must be a non-empty string, got {image!r}"
        )

    egress_allowlist = data.get("egress_allowlist", [])
    if not isinstance(egress_allowlist, list):
        raise SandboxConfigError("sandbox config: 'egress_allowlist' must be a list")

    degraded_app_level = bool(data.get("degraded_app_level", False))

    return SandboxConfig(
        runtime=runtime,
        image=image,
        egress_allowlist=[str(h) for h in egress_allowlist],
        degraded_app_level=degraded_app_level,
    )


class SandboxConfigError(Exception):
    """Raised when sandbox configuration is invalid or unparseable.

    Callers must treat this as FAIL_CLOSED (never fail-open on config error).
    """


def _detect_runtime(config: SandboxConfig) -> SandboxRuntime | None:
    """Detect the runtime based on config.runtime preference."""
    import shutil

    if config.runtime == "auto":
        return detect()

    cli = shutil.which(config.runtime)
    if cli is None:
        return None
    rt = SandboxRuntime(kind=config.runtime, cli=cli)  # type: ignore[arg-type]
    if not rt.available():
        return None
    return rt
