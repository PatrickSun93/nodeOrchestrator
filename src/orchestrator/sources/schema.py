"""Source schema — typed Source model for pipeline fetch-stage (ADR-041 D4)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Safety ceiling on per-source fetch size (ADR-041 D4/D8 hardening, P6.11-A2).
# Hardcoded — not operator-tunable (safety floor, not config).
_SOURCE_MAX_BYTES_CEILING: int = 5 * 1024 * 1024  # 5 MiB


class SourceOptions(BaseModel):
    """Per-source fetch options."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_bytes: int = Field(default=512 * 1024, gt=0, le=_SOURCE_MAX_BYTES_CEILING)
    timeout_s: float = Field(default=15.0, gt=0.0)


class Source(BaseModel):
    """A single pipeline input source.

    kind  : "web" → SSRF-validated HTTP GET
            "rss" → SSRF-validated HTTP GET + XXE-safe RSS/Atom parse
            "file" → path-sandboxed bounded read
    locator: URL (web/rss) or relative path (file)
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["web", "rss", "file"]
    locator: str = Field(min_length=1)
    options: SourceOptions = Field(default_factory=SourceOptions)


class SourceReadResult(BaseModel):
    """Successful read result from a source."""

    model_config = ConfigDict(frozen=True)

    source: Source
    content: str
    truncated: bool = False


class SourceReadError(Exception):
    """A source could not be read (SSRF block, sandbox reject, parse fail, etc.)."""
