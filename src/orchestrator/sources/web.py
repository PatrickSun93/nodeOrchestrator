"""Web source reader — SSRF-floored HTTP GET (ADR-041 D4, ADR-035/037)."""

from __future__ import annotations

import httpx

from orchestrator.sources.schema import Source, SourceReadError, SourceReadResult, _SOURCE_MAX_BYTES_CEILING
from orchestrator.tools.net_trust import build_ssrf_client
from orchestrator.tools.network_tools import _stream_bounded


def read_web_source(source: Source) -> SourceReadResult:
    """Fetch source.locator via the SSRF-validating client, stream-bounded (P6.11-A1).

    Mirrors _inprocess_web_fetch: client.send(stream=True) → _stream_bounded(max_bytes).
    Reuses the identical SSRF floor as web_fetch (build_ssrf_client / _resolve_and_validate).
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
            response = client.send(
                client.build_request("GET", source.locator),
                stream=True,
            )
            response.raise_for_status()
            content, truncated_at = _stream_bounded(
                response,
                max_bytes=min(source.options.max_bytes, _SOURCE_MAX_BYTES_CEILING),
            )
    except SourceReadError:
        raise
    except httpx.HTTPStatusError as exc:
        raise SourceReadError(
            f"web_http_error: HTTP {exc.response.status_code} for {source.locator!r}"
        ) from exc
    except Exception as exc:
        raise SourceReadError(f"web_fetch_failed: {exc}") from exc

    return SourceReadResult(source=source, content=content, truncated=truncated_at is not None)
