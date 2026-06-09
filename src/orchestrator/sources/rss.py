"""RSS/Atom source reader — SSRF-floored fetch + XXE-safe XML parse (ADR-041 D4)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from orchestrator.sources.schema import Source, SourceReadError, SourceReadResult
from orchestrator.tools.net_trust import build_ssrf_client

# ---------------------------------------------------------------------------
# XXE / billion-laughs guard
# ---------------------------------------------------------------------------

_ATOM_NS = "http://www.w3.org/2005/Atom"

# Byte budget for the DOCTYPE pre-scan (DOCTYPE must precede the root element).
_DOCTYPE_SCAN_BYTES = 8192


def _check_no_entity_declarations(xml_text: str) -> None:
    """Raise SourceReadError if xml_text contains DOCTYPE or ENTITY declarations.

    Scans the first _DOCTYPE_SCAN_BYTES characters for `<!DOCTYPE` or `<!ENTITY`.
    This pre-filter blocks both XXE (external entity injection) and billion-laughs
    (internal entity expansion) without relying on the expat C-extension's internal
    handler API (which is not portable across Python implementations).
    """
    head = xml_text[:_DOCTYPE_SCAN_BYTES].upper()
    if "<!DOCTYPE" in head or "<!ENTITY" in head:
        raise SourceReadError(
            "rss_parse_failed: XML entity declarations are forbidden (XXE/billion-laughs guard)"
        )


# ---------------------------------------------------------------------------
# Feed entry extraction (RSS 2.0 + Atom 1.0)
# ---------------------------------------------------------------------------


def _element_text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def _extract_entries_rss(channel: ET.Element) -> list[dict[str, str]]:
    entries = []
    for item in channel.findall("item"):
        entries.append(
            {
                "title": _element_text(item.find("title")),
                "link": _element_text(item.find("link")),
                "summary": _element_text(item.find("description")),
                "published": _element_text(item.find("pubDate")),
            }
        )
    return entries


def _extract_entries_atom(root: ET.Element) -> list[dict[str, str]]:
    entries = []
    for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
        link_el = entry.find(f"{{{_ATOM_NS}}}link")
        link = (link_el.get("href") or "").strip() if link_el is not None else ""
        summary = _element_text(entry.find(f"{{{_ATOM_NS}}}summary")) or _element_text(
            entry.find(f"{{{_ATOM_NS}}}content")
        )
        published = _element_text(entry.find(f"{{{_ATOM_NS}}}published")) or _element_text(
            entry.find(f"{{{_ATOM_NS}}}updated")
        )
        entries.append(
            {
                "title": _element_text(entry.find(f"{{{_ATOM_NS}}}title")),
                "link": link,
                "summary": summary,
                "published": published,
            }
        )
    return entries


def _parse_feed(xml_text: str) -> list[dict[str, str]]:
    """Parse RSS 2.0 or Atom 1.0 feed; raises SourceReadError on malformed XML."""
    _check_no_entity_declarations(xml_text)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise SourceReadError(f"rss_parse_failed: {exc}") from exc

    # Atom 1.0: root tag is {http://www.w3.org/2005/Atom}feed
    if root.tag == f"{{{_ATOM_NS}}}feed":
        return _extract_entries_atom(root)

    # RSS 2.0: root tag is "rss", channel is first child
    if root.tag == "rss":
        channel = root.find("channel")
        if channel is None:
            raise SourceReadError("rss_parse_failed: <rss> has no <channel>")
        return _extract_entries_rss(channel)

    raise SourceReadError(
        f"rss_parse_failed: unrecognised root tag {root.tag!r} (expected <rss> or <feed>)"
    )


# ---------------------------------------------------------------------------
# Public reader
# ---------------------------------------------------------------------------


def read_rss_source(source: Source) -> SourceReadResult:
    """Fetch source.locator via the SSRF-validating client, parse as RSS/Atom.

    Security:
    - Feed URL flows through the identical SSRF floor as web_fetch (no bypass).
    - XML parsing blocks entity declarations (XXE/billion-laughs).
    - Malformed feeds raise SourceReadError (fail-closed, no crash).

    Returns rendered text listing each entry on separate lines; truncated if
    the rendered text exceeds source.options.max_bytes.
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
            xml_bytes = response.content
    except SourceReadError:
        raise
    except httpx.HTTPStatusError as exc:
        raise SourceReadError(
            f"rss_http_error: HTTP {exc.response.status_code} for {source.locator!r}"
        ) from exc
    except Exception as exc:
        raise SourceReadError(f"rss_fetch_failed: {exc}") from exc

    xml_text = xml_bytes.decode("utf-8", errors="replace")
    entries = _parse_feed(xml_text)

    lines: list[str] = []
    for i, entry in enumerate(entries):
        parts = [f"[{i + 1}]"]
        if entry.get("title"):
            parts.append(f"title: {entry['title']}")
        if entry.get("link"):
            parts.append(f"link: {entry['link']}")
        if entry.get("summary"):
            parts.append(f"summary: {entry['summary']}")
        if entry.get("published"):
            parts.append(f"published: {entry['published']}")
        lines.append(" | ".join(parts))

    content = "\n".join(lines)
    encoded = content.encode("utf-8")
    truncated = len(encoded) > source.options.max_bytes
    if truncated:
        content = encoded[: source.options.max_bytes].decode("utf-8", errors="replace")
    return SourceReadResult(source=source, content=content, truncated=truncated)
