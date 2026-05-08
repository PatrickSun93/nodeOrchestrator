"""Provider health checks.

The router invokes ``health_check()`` on each candidate provider
during routing. This module adds a startup-time helper that probes
every registered provider in one pass — useful for the operator
dashboard (P1.3+) to surface "your DeepSeek API key is missing" or
"the Claude CLI isn't on PATH" before the user starts a research
session.
"""

from __future__ import annotations

from dataclasses import dataclass

from orchestrator.core.event import TimestampMs, now_ms
from orchestrator.llm.router import ProviderRegistry
from orchestrator.llm.types import ProviderId


@dataclass(frozen=True)
class ProviderHealth:
    """Result of one provider's health check."""

    provider_id: ProviderId
    healthy: bool
    error: str | None
    """Set when ``healthy=False``. Captures whatever the provider's
    health_check() recorded (provider exception or "down")."""

    checked_at_ms: TimestampMs


def check_all_providers(
    registry: ProviderRegistry,
) -> list[ProviderHealth]:
    """Run ``health_check()`` on every provider in the registry.

    Used at startup to surface misconfiguration. Does NOT raise — the
    return list contains an entry per provider including any that
    failed; callers decide which failures are fatal (e.g., a missing
    DeepSeek key is fatal if any agent requires DeepSeek; a missing
    Ollama is only fatal if Ollama is in someone's fallback chain).

    Uses :func:`orchestrator.core.event.now_ms` for ``checked_at_ms``
    so all timestamps in the system come from one source.

    Note on ``checked_at_ms`` semantics: a single timestamp is captured
    at the start of the pass and shared across every ``ProviderHealth``
    in the result. It is NOT per-provider completion time. If one
    provider's ``health_check()`` takes 3 seconds, its row still
    reports the timestamp from when the pass began. Per-provider
    completion timestamps would require a per-provider variant; they
    are not needed for current callers (startup probe, dashboard
    staleness) where pass-level granularity is sufficient.
    """
    timestamp = now_ms()
    results: list[ProviderHealth] = []
    for provider in registry.all():
        try:
            healthy = provider.health_check()
            error: str | None = None
        except Exception as e:
            healthy = False
            error = f"{type(e).__name__}: {e}"
        results.append(
            ProviderHealth(
                provider_id=provider.provider_id,
                healthy=healthy,
                error=error,
                checked_at_ms=timestamp,
            )
        )
    return results
