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


def test_rss_parse_comment_padded_prolog_doctype_blocked() -> None:
    """B1: comment padding pushes DOCTYPE past any byte-window — defusedxml still blocks."""
    # 9000-char comment pushes <!DOCTYPE past a hypothetical 8192-byte scan window.
    padding = "x" * 9000
    xml = f"<!-- {padding} --><!DOCTYPE foo [<!ENTITY x 'y'>]><rss version='2.0'><channel/></rss>"
    with pytest.raises(SourceReadError, match=r"rss_parse_failed|entity|forbidden"):
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
# Web source mocked success (streaming path — P6.11-A1)
# ---------------------------------------------------------------------------


def _mock_streaming_client(chunks: list[bytes]) -> MagicMock:
    """Build a mock SSRF client that streams the given chunks via send(stream=True)."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.iter_bytes = MagicMock(return_value=iter(chunks))
    mock_request = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.build_request = MagicMock(return_value=mock_request)
    mock_client.send = MagicMock(return_value=mock_response)
    return mock_client


def test_web_source_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Web source reads HTTP response via streaming path and returns content."""
    mock_client = _mock_streaming_client([b"Hello, web!"])
    with patch("orchestrator.sources.web.build_ssrf_client", return_value=mock_client):
        s = Source(kind="web", locator="https://example.com/page")
        result = read_source(s)

    assert result.content == "Hello, web!"
    assert not result.truncated
    # Structural assertion: send(stream=True) called, not .get()
    mock_client.send.assert_called_once()
    assert mock_client.send.call_args[1].get("stream") is True


def test_web_source_truncates_oversized(monkeypatch: pytest.MonkeyPatch) -> None:
    """Web source truncates response exceeding max_bytes via stream-bound (P6.11-A1)."""
    mock_client = _mock_streaming_client([b"X" * 200])
    with patch("orchestrator.sources.web.build_ssrf_client", return_value=mock_client):
        s = Source(
            kind="web",
            locator="https://example.com/big",
            options=SourceOptions(max_bytes=100),
        )
        result = read_source(s)

    assert result.truncated
    assert len(result.content.encode("utf-8")) <= 100


def _make_rss_xml(n_items: int) -> str:
    """Build an RSS 2.0 feed with n_items items."""
    items = "".join(
        f"<item><title>Item {i}</title><link>https://example.com/{i}</link></item>"
        for i in range(n_items)
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>Test</title>{items}</channel></rss>'


# ---------------------------------------------------------------------------
# A3: H2 RSS entry cap (P6.11-A3)
# ---------------------------------------------------------------------------


def test_rss_entry_cap_applied() -> None:
    """H2-b revert-gate: feed with 300 entries renders exactly 256 (cap applied).

    Revert the _MAX_FEED_ENTRIES slice → all 300 entries rendered.
    """
    from orchestrator.sources.rss import _MAX_FEED_ENTRIES

    xml = _make_rss_xml(300)
    xml_bytes = xml.encode("utf-8")
    mock_client = _mock_streaming_client([xml_bytes])

    with patch("orchestrator.sources.rss.build_ssrf_client", return_value=mock_client):
        s = Source(kind="rss", locator="https://example.com/feed.xml")
        result = read_source(s)

    lines = [ln for ln in result.content.splitlines() if ln.strip()]
    assert len(lines) == _MAX_FEED_ENTRIES, f"Expected {_MAX_FEED_ENTRIES} entries, got {len(lines)}"


def test_rss_entry_cap_under_limit_unaffected() -> None:
    """Feed with fewer than _MAX_FEED_ENTRIES entries is not truncated."""
    from orchestrator.sources.rss import _MAX_FEED_ENTRIES

    n = _MAX_FEED_ENTRIES - 1
    xml = _make_rss_xml(n)
    xml_bytes = xml.encode("utf-8")
    mock_client = _mock_streaming_client([xml_bytes])

    with patch("orchestrator.sources.rss.build_ssrf_client", return_value=mock_client):
        s = Source(kind="rss", locator="https://example.com/feed.xml")
        result = read_source(s)

    lines = [ln for ln in result.content.splitlines() if ln.strip()]
    assert len(lines) == n


def test_read_source_result_is_immutable() -> None:
    s = Source(kind="web", locator="http://example.com")
    r = SourceReadResult(source=s, content="data")
    with pytest.raises(Exception):  # noqa: B017
        r.content = "mutated"


# ---------------------------------------------------------------------------
# A1: H1 🔴 revert-gates (P6.11-A1)
# ---------------------------------------------------------------------------


def test_web_source_stream_stops_at_cap() -> None:
    """OOM/stream revert-gate: reader stops iterating at cap, never drains beyond it.

    A generator that raises if fully drained past max_bytes proves the reader stopped.
    Revert to .content → full drain → generator raises AssertionError.
    """
    max_bytes = 50
    chunks_yielded: list[int] = []

    def _raise_if_drained() -> bytes:
        raise AssertionError("iter_bytes drained past cap — full-buffer regression")

    def _chunks_gen() -> bytes:
        # First chunk: exactly at cap
        chunks_yielded.append(max_bytes)
        yield b"A" * max_bytes
        # If the reader asks for more, the test fails
        _raise_if_drained()

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.iter_bytes = MagicMock(return_value=_chunks_gen())
    mock_request = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.build_request = MagicMock(return_value=mock_request)
    mock_client.send = MagicMock(return_value=mock_response)

    with patch("orchestrator.sources.web.build_ssrf_client", return_value=mock_client):
        s = Source(kind="web", locator="https://example.com/big", options=SourceOptions(max_bytes=max_bytes))
        result = read_source(s)

    assert len(result.content.encode("utf-8")) <= max_bytes


def test_web_source_300k_not_truncated_with_default_options() -> None:
    """Cap-honoured revert-gate: 300 KiB body with default 512 KiB options is not truncated.

    Proves param carries source.options.max_bytes (512 KiB), not the 64 KiB web_fetch default.
    Revert the parametrization → truncates at 64 KiB → result.truncated = True.
    """
    body = b"B" * (300 * 1024)  # 300 KiB
    mock_client = _mock_streaming_client([body])
    with patch("orchestrator.sources.web.build_ssrf_client", return_value=mock_client):
        s = Source(kind="web", locator="https://example.com/page")  # default 512 KiB
        result = read_source(s)

    assert not result.truncated
    assert len(result.content.encode("utf-8")) == 300 * 1024


def test_rss_source_over_cap_fails_closed() -> None:
    """RSS over-cap fail-closed revert-gate: truncated XML → SourceReadError, no OOM.

    Revert to .content → full buffer + full parse, no size fail-close.
    """
    import textwrap

    # Build a valid RSS prefix then cut it mid-document so it's malformed XML
    valid_prefix = textwrap.dedent("""\
        <?xml version="1.0"?>
        <rss version="2.0"><channel><title>Test</title>
    """).encode("utf-8")
    # max_bytes smaller than even the valid prefix → XML is truncated mid-document
    max_bytes = 20

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.iter_bytes = MagicMock(return_value=iter([valid_prefix]))
    mock_request = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.build_request = MagicMock(return_value=mock_request)
    mock_client.send = MagicMock(return_value=mock_response)

    with patch("orchestrator.sources.rss.build_ssrf_client", return_value=mock_client):
        s = Source(kind="rss", locator="https://example.com/feed.xml", options=SourceOptions(max_bytes=max_bytes))
        with pytest.raises(SourceReadError, match="rss_parse_failed"):
            read_source(s)


def test_rss_source_stream_stops_at_cap() -> None:
    """OOM/stream revert-gate for RSS: reader stops iterating at cap.

    Revert to .content → full drain → generator raises.
    """
    max_bytes = 30
    sentinel_hit: list[bool] = []

    def _chunks_gen() -> bytes:
        yield b"X" * max_bytes
        sentinel_hit.append(True)
        yield b"EXTRA_BYTES_MUST_NOT_BE_READ"

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.iter_bytes = MagicMock(return_value=_chunks_gen())
    mock_request = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.build_request = MagicMock(return_value=mock_request)
    mock_client.send = MagicMock(return_value=mock_response)

    with patch("orchestrator.sources.rss.build_ssrf_client", return_value=mock_client):
        s = Source(kind="rss", locator="https://example.com/feed.xml", options=SourceOptions(max_bytes=max_bytes))
        # Will raise SourceReadError because truncated XML is invalid — that's expected (fail-closed)
        with pytest.raises(SourceReadError):
            read_source(s)

    # The sentinel chunk must NOT have been yielded
    assert not sentinel_hit, "iter_bytes was drained past cap — OOM regression"


# ---------------------------------------------------------------------------
# A2: H2 schema ceilings (P6.11-A2)
# ---------------------------------------------------------------------------


def test_source_options_default_still_valid() -> None:
    """Migration witness: default SourceOptions() validates under the new ceiling."""
    opts = SourceOptions()
    assert opts.max_bytes == 512 * 1024  # 512 KiB default unchanged


def test_source_options_max_bytes_at_ceiling_accepted() -> None:
    """Boundary: max_bytes == 5 MiB ceiling is accepted."""
    from orchestrator.sources.schema import _SOURCE_MAX_BYTES_CEILING

    opts = SourceOptions(max_bytes=_SOURCE_MAX_BYTES_CEILING)
    assert opts.max_bytes == _SOURCE_MAX_BYTES_CEILING


def test_source_options_max_bytes_above_ceiling_rejected() -> None:
    """H2-c revert-gate: max_bytes > 5 MiB ceiling raises ValidationError."""
    import pydantic

    from orchestrator.sources.schema import _SOURCE_MAX_BYTES_CEILING

    with pytest.raises(pydantic.ValidationError):
        SourceOptions(max_bytes=_SOURCE_MAX_BYTES_CEILING + 1)
