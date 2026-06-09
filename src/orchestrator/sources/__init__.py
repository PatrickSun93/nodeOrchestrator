"""Multi-source read abstraction for the deterministic analysis pipeline (ADR-041 D4).

Sources are READ INPUT producers (web/rss/file → fetched text).
NOT connectors/ — that is ADR-019 ground-truth OUTPUT producers (opposite direction).
"""

from orchestrator.sources.reader import read_source
from orchestrator.sources.schema import Source, SourceOptions, SourceReadError, SourceReadResult

__all__ = ["Source", "SourceOptions", "SourceReadError", "SourceReadResult", "read_source"]
