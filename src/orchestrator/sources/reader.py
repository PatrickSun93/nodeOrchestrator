"""Source dispatcher — routes Source to the correct kind-specific reader (ADR-041 D4)."""

from __future__ import annotations

from pathlib import Path

from orchestrator.sources.file import read_file_source
from orchestrator.sources.rss import read_rss_source
from orchestrator.sources.schema import Source, SourceReadResult
from orchestrator.sources.web import read_web_source


def read_source(source: Source, *, sandbox_root: Path | None = None) -> SourceReadResult:
    """Dispatch a Source to the appropriate kind-specific reader.

    web/rss: SSRF-validated; sandbox_root ignored.
    file:    sandbox_root required; path-sandboxed bounded read.

    Raises SourceReadError on any read failure.
    Raises ValueError if kind=="file" and sandbox_root is None.
    """
    if source.kind == "web":
        return read_web_source(source)
    if source.kind == "rss":
        return read_rss_source(source)
    if source.kind == "file":
        if sandbox_root is None:
            raise ValueError("sandbox_root is required for file sources")
        return read_file_source(source, sandbox_root=sandbox_root)
    # Unreachable: Pydantic enforces the Literal — kept for exhaustiveness.
    raise ValueError(f"unknown source kind: {source.kind!r}")
