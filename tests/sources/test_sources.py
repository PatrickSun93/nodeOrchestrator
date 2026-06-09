"""Tests for sources/ — schema, SSRF/sandbox floors, RSS parsing (ADR-041 D4).

Security tests (Lens A):
- denied-IP feed URL raises (SSRF floor tested, not just asserted in prose).
- path traversal rejected (sandbox floor tested).
- XXE/billion-laughs XML rejected.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orchestrator.sources.reader import read_source
from orchestrator.sources.rss import _parse_feed
from orchestrator.sources.schema import Source, SourceOptions, SourceReadError, SourceReadResult

# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


def test_source_valid_kinds() -> None:
    for kind in ("web", "rss", "file"):
        s = Source(kind=kind, locator="http://example.com")
        assert s.kind == kind


def test_source_unknown_kind_rejected() -> None:
    with pytest.raises(Exception):  # noqa: B017
        Source(kind="ftp", locator="ftp://example.com")  # type: ignore[arg-type]


def test_source_options_defaults() -> None:
    opts = SourceOptions()
    assert opts.max_bytes == 512 * 1024
    assert opts.timeout_s == 15.0


def test_source_empty_locator_rejected() -> None:
    with pytest.raises(Exception):  # noqa: B017
        Source(kind="web", locator="")


# ---------------------------------------------------------------------------
# SSRF floor: denied-IP feed URL raises SourceReadError (Lens A)
# ---------------------------------------------------------------------------


def test_web_source_denied_ip_raises() -> None:
    """SSRF floor: localhost resolves to denied IP → SourceReadError."""
    s = Source(kind="web", locator="http://127.0.0.1/feed")
    with pytest.raises(SourceReadError, match=r"ssrf_blocked|web_fetch_failed"):
        read_source(s)


def test_rss_source_denied_ip_raises() -> None:
    """SSRF floor: loopback address in feed URL is SSRF-blocked."""
    s = Source(kind="rss", locator="http://127.0.0.1/rss.xml")
    with pytest.raises(SourceReadError, match=r"ssrf_blocked|rss_fetch_failed"):
        read_source(s)


def test_web_source_private_ip_raises() -> None:
    """SSRF floor: private-range IP is denied."""
    s = Source(kind="web", locator="http://192.168.1.1/secret")
    with pytest.raises(SourceReadError):
        read_source(s)


# ---------------------------------------------------------------------------
# Sandbox floor: traversal + symlink escape → SourceReadError (Lens A)
# ---------------------------------------------------------------------------


def test_file_source_traversal_rejected(tmp_path: Path) -> None:
    """Sandbox: ../etc/passwd-style traversal is rejected."""
    s = Source(kind="file", locator="../etc/passwd")
    with pytest.raises(SourceReadError, match="sandbox_rejected"):
        read_source(s, sandbox_root=tmp_path)


def test_file_source_absolute_path_rejected(tmp_path: Path) -> None:
    """Sandbox: absolute path that escapes sandbox_root is rejected."""
    s = Source(kind="file", locator="/etc/passwd")
    with pytest.raises(SourceReadError, match="sandbox_rejected"):
        read_source(s, sandbox_root=tmp_path)


def test_file_source_reads_allowed_file(tmp_path: Path) -> None:
    """Sandbox: file within sandbox_root is read successfully."""
    target = tmp_path / "data.txt"
    target.write_text("hello world", encoding="utf-8")
    s = Source(kind="file", locator="data.txt")
    result = read_source(s, sandbox_root=tmp_path)
    assert result.content == "hello world"
    assert not result.truncated


def test_file_source_truncates_large_file(tmp_path: Path) -> None:
    """File bounded read: oversized file is truncated."""
    target = tmp_path / "big.txt"
    target.write_bytes(b"x" * 200)
    s = Source(kind="file", locator="big.txt", options=SourceOptions(max_bytes=100))
    result = read_source(s, sandbox_root=tmp_path)
    assert result.truncated
    assert len(result.content.encode("utf-8")) <= 100


def test_file_source_missing_file_raises(tmp_path: Path) -> None:
    s = Source(kind="file", locator="nonexistent.txt")
    with pytest.raises(SourceReadError, match="not_a_file"):
        read_source(s, sandbox_root=tmp_path)


def test_file_source_requires_sandbox_root() -> None:
    s = Source(kind="file", locator="data.txt")
    with pytest.raises(ValueError, match="sandbox_root"):
        read_source(s)


# ---------------------------------------------------------------------------
# RSS/Atom parsing — XXE/billion-laughs safety (Lens A)
# ---------------------------------------------------------------------------


def test_rss_parse_valid_rss2() -> None:
    """RSS 2.0 feed parses to entry list."""
    xml = textwrap.dedent("""\
        <?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <title>Test</title>
            <item>
              <title>Item 1</title>
              <link>https://example.com/1</link>
              <description>First item</description>
              <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
            </item>
          </channel>
        </rss>
    """)
    entries = _parse_feed(xml)
    assert len(entries) == 1
    assert entries[0]["title"] == "Item 1"
    assert entries[0]["link"] == "https://example.com/1"
    assert entries[0]["summary"] == "First item"


def test_rss_parse_valid_atom() -> None:
    """Atom 1.0 feed parses to entry list."""
    xml = textwrap.dedent("""\
        <?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <title>Atom Test</title>
          <entry>
            <title>Atom Entry</title>
            <link href="https://example.com/atom/1"/>
            <summary>Atom summary</summary>
            <published>2024-01-01T00:00:00Z</published>
          </entry>
        </feed>
    """)
    entries = _parse_feed(xml)
    assert len(entries) == 1
    assert entries[0]["title"] == "Atom Entry"
    assert entries[0]["link"] == "https://example.com/atom/1"


def test_rss_parse_xxe_entity_blocked() -> None:
    """XXE guard: external entity declaration in DOCTYPE raises SourceReadError."""
    xml = textwrap.dedent("""\
        <?xml version="1.0"?>
        <!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
        <rss version="2.0"><channel><item><title>&xxe;</title></item></channel></rss>
    """)
    with pytest.raises(SourceReadError, match=r"rss_parse_failed|entity"):
        _parse_feed(xml)


def test_rss_parse_billion_laughs_blocked() -> None:
    """Billion-laughs guard: internal entity expansion is blocked."""
    xml = textwrap.dedent("""\
        <?xml version="1.0"?>
        <!DOCTYPE lol [
          <!ENTITY lol "lol">
          <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
        ]>
        <rss version="2.0"><channel><item><title>&lol2;</title></item></channel></rss>
    """)
    with pytest.raises(SourceReadError, match=r"rss_parse_failed|entity"):
        _parse_feed(xml)


def test_rss_parse_malformed_xml_raises() -> None:
    """Malformed XML fails closed (no crash)."""
    with pytest.raises(SourceReadError, match="rss_parse_failed"):
        _parse_feed("this is not xml at all <<<<")


def test_rss_parse_unknown_root_raises() -> None:
    """Unknown root element fails with SourceReadError."""
    xml = "<?xml version='1.0'?><atom><entry/></atom>"
    with pytest.raises(SourceReadError, match="rss_parse_failed"):
        _parse_feed(xml)


# ---------------------------------------------------------------------------
# Web source mocked success
# ---------------------------------------------------------------------------


def test_web_source_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Web source reads HTTP response and returns content."""
    mock_response = MagicMock()
    mock_response.content = b"Hello, web!"
    mock_response.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get = MagicMock(return_value=mock_response)

    with patch("orchestrator.sources.web.build_ssrf_client", return_value=mock_client):
        s = Source(kind="web", locator="https://example.com/page")
        result = read_source(s)

    assert result.content == "Hello, web!"
    assert not result.truncated


def test_web_source_truncates_oversized(monkeypatch: pytest.MonkeyPatch) -> None:
    """Web source truncates response exceeding max_bytes."""
    mock_response = MagicMock()
    mock_response.content = b"X" * 200
    mock_response.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get = MagicMock(return_value=mock_response)

    with patch("orchestrator.sources.web.build_ssrf_client", return_value=mock_client):
        s = Source(
            kind="web",
            locator="https://example.com/big",
            options=SourceOptions(max_bytes=100),
        )
        result = read_source(s)

    assert result.truncated
    assert len(result.content.encode("utf-8")) <= 100


def test_read_source_result_is_immutable() -> None:
    s = Source(kind="web", locator="http://example.com")
    r = SourceReadResult(source=s, content="data")
    with pytest.raises(Exception):  # noqa: B017
        r.content = "mutated"
