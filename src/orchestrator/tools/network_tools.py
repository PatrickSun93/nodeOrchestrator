"""Network local tool closures (ADR-035 D1/D3/D4; P4.2-B4-2/B4-3).

Each closure is a LocalToolFn that:
  - Validates its param allowlist (no passthrough of unauthorized params).
  - Runs in-process via httpx (not subprocess — resolve-then-pin is cleanest in-process).
  - Returns LocalToolOutput at any HTTP status (non-200 = TOOL_RESULT, not TOOL_FAILED).
  - Carries _is_network_tool = True for the per-turn network cap.

web_fetch  — fetch an agent-chosen URL through the SSRF-validating transport (ADR-035 D2).
web_search — query through the Brave Search API fixed endpoint (operator-configured, ADR-035 D1).

Do NOT add to tools/local.py (constitution t6 keeps local.py in-process-pristine;
network surface lives here only).

Provider config: config/web_search.yaml(.example) — api_key_env pattern (llm/types.py:248).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, ClassVar

import httpx
import yaml

from orchestrator.mcp.execution import MAX_RESULT_BYTES
from orchestrator.tools.executor import LocalToolFn, LocalToolOutput
from orchestrator.tools.local import LocalToolError
from orchestrator.tools.net_trust import build_ssrf_client

_log = logging.getLogger("orchestrator.tools.network")

# --- Liveness constants (ADR-035 Reversibility; tunable without design change) ---

# web_fetch: 20s total realised as granular timeout (ADR-035 D2 B2 — not a scalar).
# Bounded on every term: connect (5s), read (15s), write (5s), pool (5s).
_WEB_FETCH_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)

# web_search: 15s total (fixed endpoint, no SSRF overhead).
_WEB_SEARCH_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)

# Per-tool fetch redirect bound (re-validated on every hop — ADR-035 D2).
_MAX_REDIRECTS = 5

# Brave Search API endpoint (Y1 ratified; operator-configured; SSRF N/A — fixed endpoint).
_BRAVE_SEARCH_BASE_URL = "https://api.search.brave.com/res/v1/web/search"

_WEB_SEARCH_MAX_RESULTS_MIN = 1
_WEB_SEARCH_MAX_RESULTS_MAX = 20
_WEB_SEARCH_MAX_RESULTS_DEFAULT = 10


# ---------------------------------------------------------------------------
# _NetworkToolFn: callable class with _is_network_tool marker
# ---------------------------------------------------------------------------


class _NetworkToolFn:
    """Callable class wrapping a network tool impl with the network marker.

    The ClassVar marker lets executor.py identify network-IO-launching local tools
    for the per-turn network cap (MAX_NETWORK_CALLS_PER_TURN). Mirrors
    _SubprocessToolFn in subprocess_tools.py.
    """

    _is_network_tool: ClassVar[bool] = True

    def __init__(self, impl: LocalToolFn) -> None:
        self._impl = impl

    def __call__(self, params: dict[str, Any]) -> LocalToolOutput:
        return self._impl(params)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _check_disallowed(
    params: dict[str, Any], allowed: frozenset[str], tool_name: str
) -> None:
    """Raise LocalToolError if any param key is outside the allowlist."""
    disallowed = set(params.keys()) - allowed
    if disallowed:
        raise LocalToolError(
            f"{tool_name}: disallowed param(s): {sorted(disallowed)!r} "
            f"(allowed: {sorted(allowed)!r})"
        )


def _stream_bounded(response: httpx.Response) -> tuple[str, int | None]:
    """Stream the response body up to MAX_RESULT_BYTES; return (content, truncated_at).

    Never buffers an unbounded response into memory (ADR-028 D3 / ADR-035 D2 OOM guard).
    Decodes as utf-8 with errors='replace'.
    """
    chunks: list[bytes] = []
    total = 0
    truncated_at: int | None = None
    for chunk in response.iter_bytes():
        remaining = MAX_RESULT_BYTES - total
        if len(chunk) > remaining:
            chunks.append(chunk[:remaining])
            total += remaining
            truncated_at = MAX_RESULT_BYTES
            break
        chunks.append(chunk)
        total += len(chunk)
    raw = b"".join(chunks)
    return raw.decode("utf-8", errors="replace"), truncated_at


# ---------------------------------------------------------------------------
# B4-2: web_fetch closure
# ---------------------------------------------------------------------------


def _make_web_fetch() -> _NetworkToolFn:
    allowed: frozenset[str] = frozenset({"url"})

    def _impl(params: dict[str, Any]) -> LocalToolOutput:
        _check_disallowed(params, allowed, "web_fetch")
        url_str = str(params.get("url", ""))
        if not url_str:
            raise LocalToolError("web_fetch: 'url' is required")

        # Build a fresh anonymous SSRF-validating client per call (no cross-call cookie state).
        client = build_ssrf_client(timeout=_WEB_FETCH_TIMEOUT, max_redirects=_MAX_REDIRECTS)
        try:
            with client:
                response = client.send(
                    client.build_request("GET", url_str),
                    stream=True,
                )
                content, truncated_at = _stream_bounded(response)
        except LocalToolError:
            raise
        except httpx.InvalidURL as exc:
            raise LocalToolError(f"fetch_failed: invalid URL {url_str!r}: {exc}") from exc
        except httpx.TooManyRedirects as exc:
            raise LocalToolError(
                f"fetch_failed: too many redirects (max {_MAX_REDIRECTS}): {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise LocalToolError(f"network_timeout: {exc}") from exc
        except httpx.RequestError as exc:
            raise LocalToolError(f"fetch_failed: {exc}") from exc

        body = f"status={response.status_code}\nurl={response.url}\n\n{content}"
        return LocalToolOutput(content=body, output_truncated_at=truncated_at)

    return _NetworkToolFn(_impl)


# ---------------------------------------------------------------------------
# B4-3: web_search closure + provider config
# ---------------------------------------------------------------------------


def _load_web_search_config(config_path: Path | None) -> dict[str, Any] | None:
    """Load web_search provider config from YAML; return None if absent or missing."""
    if config_path is None or not config_path.exists():
        return None
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        return None


def _make_web_search(provider_config: dict[str, Any] | None) -> _NetworkToolFn:
    allowed: frozenset[str] = frozenset({"query", "max_results"})

    # Resolve api_key_env: from config if present, else default to BRAVE_API_KEY.
    # The key is captured in the closure; it is NEVER placed onto fetched URLs.
    key_env = "BRAVE_API_KEY"
    if provider_config is not None:
        key_env = str(provider_config.get("api_key_env", "BRAVE_API_KEY"))
    api_key: str | None = os.environ.get(key_env) or None

    def _impl(params: dict[str, Any]) -> LocalToolOutput:
        _check_disallowed(params, allowed, "web_search")
        query = str(params.get("query", ""))
        if not query:
            raise LocalToolError("web_search: 'query' is required")
        if api_key is None:
            raise LocalToolError("web_search not configured: BRAVE_API_KEY not set")

        raw_max = params.get("max_results")
        if raw_max is not None:
            try:
                max_results = int(raw_max)
            except (TypeError, ValueError) as exc:
                raise LocalToolError(
                    f"web_search: max_results must be an integer: {exc}"
                ) from exc
            max_results = max(
                _WEB_SEARCH_MAX_RESULTS_MIN,
                min(_WEB_SEARCH_MAX_RESULTS_MAX, max_results),
            )
        else:
            max_results = _WEB_SEARCH_MAX_RESULTS_DEFAULT

        # Standard httpx (fixed endpoint — SSRF N/A; API key sent ONLY to Brave header).
        req_params: dict[str, str | int] = {"q": query, "count": max_results}
        headers = {"X-Subscription-Token": api_key, "Accept": "application/json"}
        try:
            with httpx.Client(timeout=_WEB_SEARCH_TIMEOUT) as client:
                response = client.get(
                    _BRAVE_SEARCH_BASE_URL,
                    params=req_params,
                    headers=headers,
                )
        except httpx.TimeoutException as exc:
            raise LocalToolError(f"network_timeout: web_search timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise LocalToolError(f"search_provider_error: {exc}") from exc

        if response.status_code >= 500:
            raise LocalToolError(
                f"search_provider_error: provider returned HTTP {response.status_code}"
            )

        try:
            data: dict[str, Any] = response.json()
        except Exception as exc:
            raise LocalToolError(
                f"search_provider_error: could not parse provider response: {exc}"
            ) from exc

        results: list[dict[str, Any]] = data.get("web", {}).get("results", [])
        lines: list[str] = []
        for item in results[:max_results]:
            title = str(item.get("title", ""))
            url = str(item.get("url", ""))
            desc = str(item.get("description", ""))
            lines.append(f"- {title}\n  {url}\n  {desc}")

        content = "\n\n".join(lines) if lines else "(no results)"
        truncated_at: int | None = None
        if len(content.encode()) > MAX_RESULT_BYTES:
            raw = content.encode()[:MAX_RESULT_BYTES]
            content = raw.decode("utf-8", errors="replace")
            truncated_at = MAX_RESULT_BYTES

        return LocalToolOutput(content=content, output_truncated_at=truncated_at)

    return _NetworkToolFn(_impl)


# ---------------------------------------------------------------------------
# Registry builder
# ---------------------------------------------------------------------------


def build_network_tool_registry(
    *,
    web_search_config_path: Path | None = None,
) -> dict[str, LocalToolFn]:
    """Build the network local tools registry.

    Returns a dict keyed by tool name (matching tools.yaml classifications).
    Each value is a _NetworkToolFn carrying _is_network_tool = True.

    web_fetch: SSRF-validating HTTPS/HTTP fetch; no auth/cookies; raw TOOL_RESULT.
    web_search: Brave Search API query; api_key from env (fail-closed if absent).
    """
    provider_config = _load_web_search_config(web_search_config_path)
    return {
        "web_fetch": _make_web_fetch(),
        "web_search": _make_web_search(provider_config),
    }
