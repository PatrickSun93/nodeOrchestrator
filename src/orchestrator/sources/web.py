"""Web source reader — SSRF-floored HTTP GET (ADR-041 D4, ADR-035/037)."""

from __future__ import annotations

import httpx

from orchestrator.sources.schema import Source, SourceReadError, SourceReadResult
from orchestrator.tools.net_trust import build_ssrf_client


def read_web_source(source: Source) -> SourceReadResult:
    """Fetch source.locator via the SSRF-validating client.

    Reuses the identical SSRF floor as web_fetch (build_ssrf_client / _resolve_and_validate).
    Bounded by source.options.max_bytes and source.options.timeout_s.
    Raises SourceReadError on SSRF block, network error, HTTP error, or timeout.
    """
    timeout = httpx.Timeout(
        connect=5.0,
        read=source.options.timeout_s,
        write=5.0,
        pool=5.0,
    )
    try:
        with build_ssrf_client(timeout=timeout) as client:
            response = client.get(source.locator)
            response.raise_for_status()
            raw = response.content
    except SourceReadError:
        raise
    except httpx.HTTPStatusError as exc:
        raise SourceReadError(
            f"web_http_error: HTTP {exc.response.status_code} for {source.locator!r}"
        ) from exc
    except Exception as exc:
        raise SourceReadError(f"web_fetch_failed: {exc}") from exc

    truncated = len(raw) > source.options.max_bytes
    content = raw[: source.options.max_bytes].decode("utf-8", errors="replace")
    return SourceReadResult(source=source, content=content, truncated=truncated)
