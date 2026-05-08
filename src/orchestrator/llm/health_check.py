"""Provider health checks.

The router invokes ``health_check()`` on each candidate provider
during routing. This module adds a startup-time helper that probes
every registered provider in one pass — useful for the operator
dashboard (P1.3+) to surface "your DeepSeek API key is missing" or
"the Claude CLI isn't on PATH" before the user starts a research
session.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

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

    checked_at_ms: int


def check_all_providers(
    registry: ProviderRegistry,
) -> list[ProviderHealth]:
    """Run ``health_check()`` on every provider in the registry.

    Used at startup to surface misconfiguration. Does NOT raise — the
    return list contains an entry per provider including any that
    failed; callers decide which failures are fatal (e.g., a missing
    DeepSeek key is fatal if any agent requires DeepSeek; a missing
    Ollama is only fatal if Ollama is in someone's fallback chain).
    """
    raise NotImplementedError


def _now_ms() -> int:
    """Wall-clock in epoch milliseconds. Internal helper kept here
    rather than imported from ``orchestrator.core.event`` to keep
    the LLM layer's dependency surface small."""
    return int(time.time() * 1000)
