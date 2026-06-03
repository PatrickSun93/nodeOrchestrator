"""Demo plugin executable tool: word_count (pure, no I/O, deterministic).

Posture A in-process import (ADR-029 D4 — loaded only after collision-check
cleared; call-time fail-closed inherited from executor ADR-028 D4).
"""

from __future__ import annotations

from typing import Any

from orchestrator.tools.executor import LocalToolOutput


def word_count(params: dict[str, Any]) -> LocalToolOutput:
    """Count whitespace-separated words in params["text"]."""
    text = str(params.get("text", ""))
    count = len(text.split())
    return LocalToolOutput(content=str(count))
