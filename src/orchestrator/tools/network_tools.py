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
from typing import TYPE_CHECKING, Any, ClassVar

import httpx
import yaml

from orchestrator.mcp.execution import MAX_RESULT_BYTES
from orchestrator.tools.executor import LocalToolFn, LocalToolOutput
from orchestrator.tools.local import LocalToolError
from orchestrator.tools.net_trust import build_ssrf_client

if TYPE_CHECKING:
    from orchestrator.sandbox.posture import PostureResolver

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

# send_email: timeout mirrors web_search (fixed endpoint, no SSRF overhead).
_SEND_EMAIL_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)


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


def _check_disallowed(params: dict[str, Any], allowed: frozenset[str], tool_name: str) -> None:
    """Raise LocalToolError if any param key is outside the allowlist."""
    disallowed = set(params.keys()) - allowed
    if disallowed:
        raise LocalToolError(
            f"{tool_name}: disallowed param(s): {sorted(disallowed)!r} "
            f"(allowed: {sorted(allowed)!r})"
        )


def _stream_bounded(
    response: httpx.Response, max_bytes: int = MAX_RESULT_BYTES
) -> tuple[str, int | None]:
    """Stream the response body up to max_bytes; return (content, truncated_at).

    Never buffers an unbounded response into memory (ADR-028 D3 / ADR-035 D2 OOM guard).
    Decodes as utf-8 with errors='replace'.
    Default max_bytes=MAX_RESULT_BYTES preserves web_fetch byte-identity (P6.11-A1 seam).
    """
    chunks: list[bytes] = []
    total = 0
    truncated_at: int | None = None
    for chunk in response.iter_bytes():
        remaining = max_bytes - total
        if len(chunk) > remaining:
            chunks.append(chunk[:remaining])
            total += remaining
            truncated_at = max_bytes
            break
        chunks.append(chunk)
        total += len(chunk)
    raw = b"".join(chunks)
    return raw.decode("utf-8", errors="replace"), truncated_at


# ---------------------------------------------------------------------------
# B4-2: web_fetch closure
# ---------------------------------------------------------------------------


def _make_web_fetch(
    posture_resolver: PostureResolver | None = None,
    sandbox_root: Path | None = None,
) -> _NetworkToolFn:
    """Build a web_fetch impl.

    When posture_resolver is provided (ADR-037 D3; P4.3-8):
    - SANDBOXED: SSRF floor validates + pins the URL; egress container constrained to
      the pinned IP; sandboxed_run executes a Python fetcher inside the container.
    - FAIL_CLOSED: LocalToolError(sandbox_unavailable:…).
    - DEGRADED: in-process httpx with SSRF floor (loudly warned by posture resolver).
    """
    allowed: frozenset[str] = frozenset({"url"})

    def _impl(params: dict[str, Any]) -> LocalToolOutput:
        _check_disallowed(params, allowed, "web_fetch")
        url_str = str(params.get("url", ""))
        if not url_str:
            raise LocalToolError("web_fetch: 'url' is required")

        if posture_resolver is not None:
            return _sandbox_web_fetch(url_str, posture_resolver, sandbox_root)

        return _inprocess_web_fetch(url_str)

    return _NetworkToolFn(_impl)


def _sandbox_web_fetch(
    url_str: str,
    posture_resolver: PostureResolver,
    sandbox_root: Path | None,
) -> LocalToolOutput:
    """web_fetch routed through a per-call egress container (ADR-037 D3; P4.3-8).

    SSRF floor validates + pins the URL (parent-side, defense-in-depth).
    The container's egress is constrained to the pinned IP only.
    """
    from orchestrator.sandbox.egress import EgressDenied, build_egress_spec
    from orchestrator.sandbox.profile import SandboxProfile
    from orchestrator.sandbox.runtime import SandboxUnavailableError
    from orchestrator.sandbox.spawn import sandboxed_run
    from orchestrator.tools.net_trust import _resolve_and_validate

    # SSRF floor: validate + pin (parent-side, every redirect would be validated here
    # if we were doing in-process multi-hop; for sandbox, the egress constraint is the
    # primary enforcement per ADR-037 D3 / ADR-035 D2 re-homed).
    try:
        import urllib.parse

        parsed = urllib.parse.urlparse(url_str)
        hostname = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if not hostname:
            raise LocalToolError(f"fetch_failed: could not parse hostname from {url_str!r}")
        pinned_ip = _resolve_and_validate(hostname, port)
    except LocalToolError:
        raise

    try:
        runtime = posture_resolver.assert_sandboxed_or_raise("web_fetch")
    except SandboxUnavailableError as exc:
        if posture_resolver.is_degraded_opted_in():
            return _inprocess_web_fetch(url_str)
        raise LocalToolError(f"sandbox_unavailable: web_fetch: {exc}") from exc

    try:
        egress_spec = build_egress_spec(
            pinned_ip,
            port,
            runtime_kind=runtime.kind,
            tool_kind="web_fetch",
            hostname=hostname,
            call_id="web_fetch",
        )
    except EgressDenied as exc:
        raise LocalToolError(f"sandbox_egress_denied: web_fetch: {exc}") from exc

    image = getattr(getattr(posture_resolver, "_config", None), "image", "sandbox:latest")
    cwd = sandbox_root or Path("/tmp")

    # Python fetcher: runs inside the container, fetches the URL via urllib stdlib.
    fetcher_argv = [
        "python3",
        "-c",
        _SANDBOX_FETCHER_SCRIPT,
        url_str,
        str(MAX_RESULT_BYTES),
    ]

    profile = SandboxProfile(sandbox_root=cwd, image=image)
    try:
        result = sandboxed_run(
            fetcher_argv,
            cwd=cwd,
            env={},
            timeout_s=float(_WEB_FETCH_TIMEOUT.read or 15.0)
            + float(_WEB_FETCH_TIMEOUT.connect or 5.0)
            + 5.0,
            max_bytes=MAX_RESULT_BYTES + 512,
            profile=profile,
            egress_spec=egress_spec,
            runtime=runtime,
        )
    except SandboxUnavailableError as exc:
        raise LocalToolError(f"sandbox_unavailable: web_fetch: {exc}") from exc

    if result.exit_code != 0:
        raise LocalToolError(f"fetch_failed: sandboxed web_fetch failed: {result.output[:200]}")

    truncated_at = MAX_RESULT_BYTES if result.truncated else None
    return LocalToolOutput(content=result.output, output_truncated_at=truncated_at)


def _inprocess_web_fetch(url_str: str) -> LocalToolOutput:
    """Original in-process httpx web_fetch (app-level SSRF floor; ADR-035 D2)."""
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


# Minimal Python fetcher script that runs inside the sandbox container.
# Uses only stdlib (urllib) — no external deps required in the container.
_SANDBOX_FETCHER_SCRIPT = """
import sys, urllib.request, urllib.error
url, max_bytes = sys.argv[1], int(sys.argv[2])
try:
    req = urllib.request.Request(url, headers={"User-Agent": "orchestrator-sandbox/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        code = resp.status
        final_url = resp.url
        body = resp.read(max_bytes).decode("utf-8", errors="replace")
        print(f"status={code}\\nurl={final_url}\\n\\n{body}", end="")
except urllib.error.HTTPError as e:
    body = e.read(max_bytes).decode('utf-8', 'replace')
    print(f"status={e.code}\\nurl={url}\\n\\n{body}", end="")
except Exception as e:
    print(f"fetch_failed: {e}", file=sys.stderr)
    sys.exit(1)
"""


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
                raise LocalToolError(f"web_search: max_results must be an integer: {exc}") from exc
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
# B5-2: send_email closure + provider config
# ---------------------------------------------------------------------------


def _load_email_config(config_path: Path | None) -> dict[str, Any] | None:
    """Load send_email provider config from YAML; return None if absent or missing.

    Mirrors _load_web_search_config. Required keys: endpoint, api_key_env,
    from_addr, allowed_domains. absent/malformed -> fail-closed (not configured).
    """
    if config_path is None or not config_path.exists():
        return None
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        return None


def _make_send_email(
    provider_config: dict[str, Any] | None,
    posture_resolver: PostureResolver | None = None,
) -> _NetworkToolFn:
    """Build a send_email impl using config-driven HTTP (ADR-036 D3-ii).

    Reads endpoint + api_key_env + from_addr + allowed_domains from provider_config.
    Fail-closed when unconfigured. Key only in provider auth header (never logged/echoed).
    Domain-allowlist (primary) + optional explicit recipient list.
    Unconfigured allowlist -> fail-closed (cannot send to unbounded recipient set).
    SSRF N/A: endpoint is operator-trusted config, NOT in the param allowlist.
    When posture_resolver is set, logs a per-call WARNING that send_email runs unsandboxed
    by design (R9 DLP tail, ADR-037 D5) — execution unchanged, warning is the transparency.
    """
    allowed: frozenset[str] = frozenset({"to", "subject", "body"})

    # Extract config values once at closure build time (mirrors web_search).
    if provider_config is None:
        endpoint: str | None = None
        api_key: str | None = None
        from_addr: str | None = None
        allowed_domains: list[str] = []
        explicit_recipients: list[str] = []
    else:
        endpoint = str(provider_config.get("endpoint", "")) or None
        key_env = str(provider_config.get("api_key_env", ""))
        api_key = (os.environ.get(key_env) or None) if key_env else None
        from_addr = str(provider_config.get("from_addr", "")) or None
        raw_domains = provider_config.get("allowed_domains") or []
        allowed_domains = [str(d) for d in raw_domains] if isinstance(raw_domains, list) else []
        raw_recipients = provider_config.get("recipients") or []
        explicit_recipients = (
            [str(r) for r in raw_recipients] if isinstance(raw_recipients, list) else []
        )

    def _impl(params: dict[str, Any]) -> LocalToolOutput:
        _check_disallowed(params, allowed, "send_email")

        # Transparency warning: send_email runs unsandboxed by design (R9 DLP tail,
        # ADR-037 D5). Log on every call when a sandbox posture is configured so the
        # operator knows the container boundary does not cover the recipient field.
        if posture_resolver is not None:
            _log.warning(
                "sandbox: send_email is running UNSANDBOXED by design — "
                "R9 (recipient-exfil DLP tail) is NOT retired by ADR-037 D5. "
                "Within-allowed-domain exfil persists. Sandbox posture: %s",
                posture_resolver.resolve().value,
            )

        to_addr = str(params.get("to", ""))
        subject = str(params.get("subject", ""))
        body = str(params.get("body", ""))

        if not to_addr:
            raise LocalToolError("send_email: 'to' is required")

        # Fail-closed: unconfigured provider
        if endpoint is None or api_key is None or from_addr is None:
            raise LocalToolError(
                "send_email not configured: endpoint/api_key_env/from_addr missing in email.yaml"
            )

        # Fail-closed: unconfigured allowlist (no send to unbounded recipient set).
        if not allowed_domains and not explicit_recipients:
            raise LocalToolError(
                "send_email not configured: allowed_domains not set in email.yaml "
                "(recipient allowlist is mandatory)"
            )

        # Recipient allowlist check (ADR-036 D3-ii).
        # First check explicit list (if configured), then domain allowlist.
        recipient_ok = False
        if explicit_recipients and to_addr in explicit_recipients:
            recipient_ok = True
        if not recipient_ok and allowed_domains:
            to_domain = to_addr.split("@", 1)[-1].lower() if "@" in to_addr else ""
            if to_domain and any(
                to_domain == d.lower() or to_domain.endswith("." + d.lower())
                for d in allowed_domains
            ):
                recipient_ok = True

        if not recipient_ok:
            raise LocalToolError(
                f"send_email: recipient {to_addr!r} not in operator allowlist "
                f"(allowed domains: {allowed_domains!r})"
            )

        # Plain httpx POST to operator-configured endpoint (SSRF N/A — operator-trusted).
        # API key ONLY in the Authorization header; never in logs, body, or result.
        payload: dict[str, str] = {
            "from": from_addr,
            "to": to_addr,
            "subject": subject,
            "text": body,
        }
        headers: dict[str, str] = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=_SEND_EMAIL_TIMEOUT) as client:
                response = client.post(endpoint, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise LocalToolError(f"network_timeout: send_email timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise LocalToolError(f"send_failed: {exc}") from exc

        if response.status_code >= 500:
            raise LocalToolError(f"send_failed: provider returned HTTP {response.status_code}")

        # Return provider send-status as raw output (untrusted; framed by caller).
        status_text = f"status={response.status_code}\n{response.text}"
        truncated_at: int | None = None
        if len(status_text.encode()) > MAX_RESULT_BYTES:
            raw = status_text.encode()[:MAX_RESULT_BYTES]
            status_text = raw.decode("utf-8", errors="replace")
            truncated_at = MAX_RESULT_BYTES

        return LocalToolOutput(content=status_text, output_truncated_at=truncated_at)

    return _NetworkToolFn(_impl)


# ---------------------------------------------------------------------------
# Registry builder
# ---------------------------------------------------------------------------


def build_network_tool_registry(
    *,
    web_search_config_path: Path | None = None,
    email_config_path: Path | None = None,
    posture_resolver: PostureResolver | None = None,
    sandbox_root: Path | None = None,
) -> dict[str, LocalToolFn]:
    """Build the network local tools registry.

    Returns a dict keyed by tool name (matching tools.yaml classifications).
    Each value is a _NetworkToolFn carrying _is_network_tool = True.

    web_fetch: SSRF-validating HTTPS/HTTP fetch; when posture_resolver is provided,
    routes through a per-call egress container (ADR-037 D3; P4.3-8). App-level SSRF
    floor stays as defense-in-depth. DEGRADED opt-in falls through to in-process SSRF.
    web_search: Brave Search API query; api_key from env (fail-closed if absent).
    send_email: config-driven HTTP email send (ADR-036 D3-ii); fail-closed if unconfigured.
    """
    provider_config = _load_web_search_config(web_search_config_path)
    email_config = _load_email_config(email_config_path)
    return {
        "web_fetch": _make_web_fetch(posture_resolver=posture_resolver, sandbox_root=sandbox_root),
        "web_search": _make_web_search(provider_config),
        "send_email": _make_send_email(email_config, posture_resolver=posture_resolver),
    }
