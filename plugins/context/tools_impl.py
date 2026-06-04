"""Context plugin executable tool: context_summary (pure, no I/O, deterministic).

Posture A in-process import (ADR-029 D4 — loaded only after collision-check
cleared; call-time fail-closed inherited from executor ADR-028 D4).
"""

from __future__ import annotations

from typing import Any

from orchestrator.tools.executor import LocalToolOutput


def context_summary(params: dict[str, Any]) -> LocalToolOutput:
    """Return a one-line summary of the context text in params["text"]."""
    text = str(params.get("text", ""))
    word_count = len(text.split())
    return LocalToolOutput(content=f"[context: {word_count} words]")
