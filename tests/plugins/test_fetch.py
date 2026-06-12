"""Minimal remote-fetch mechanism tests (ADR-031 D5; P3.7-remote-7).

Acceptance criteria:
  ft1  — pinned source + matching digest → staged + loadable (provenance 'fetched').
  ft2  — digest mismatch → FetchError; temp staging cleaned up; fetched_plugins_dir untouched.
  ft3  — non-https:// source → FetchError; no download attempted.
  ft4  — unreachable / TLS failure → FetchError; temp staging cleaned up.
  ft5  — path-traversal bundle → FetchError BEFORE extraction (digest-before-extract enforced).
  ft6  — tampered/oversized bundle → FetchError; staging untouched.
  ft7  — atomic staging: on failure, no partial state left in fetched_plugins_dir.
  ft8  — digest-before-extract ordering: a bundle with a bad digest is rejected even if
         it would extract cleanly (ordering IS the security property).
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from collections.abc import Generator
from pathlib import Path

import httpx
import pytest

from orchestrator.plugins.fetch import FetchError, fetch_plugin_bundle

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _make_zip_bundle(files: dict[str, bytes]) -> bytes:
    """Create an in-memory zip bundle from a dict of {member_path: content}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _minimal_plugin_zip() -> bytes:
    """A minimal valid plugin zip with plugin.yaml."""
    return _make_zip_bundle(
        {
            "plugin.yaml": (b"schema_version: 1\nid: test_fetch\nname: 'test'\nversion: '0.1.0'\n"),
            "tools_impl.py": (
                b"from orchestrator.tools.executor import LocalToolOutput\n"
                b"def echo(params): return LocalToolOutput(content='fetched-echo')\n"
            ),
        }
    )


def _mock_client(bundle_bytes: bytes, status_code: int = 200) -> httpx.Client:
    """Create a mock httpx.Client that returns the given bytes."""
    import httpx

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=bundle_bytes)

    transport = httpx.MockTransport(_handler)
    return httpx.Client(transport=transport)


# ---------------------------------------------------------------------------
# ft3: non-https:// source → FetchError immediately
# ---------------------------------------------------------------------------


def test_ft3_http_url_refused(tmp_path: Path) -> None:
    """Non-https:// source_url is refused before any download."""
    fetched_dir = tmp_path / "fetched"
    with pytest.raises(FetchError, match="https://"):
        fetch_plugin_bundle(
            source_url="http://example.com/plugin.zip",
            expected_digest="sha256:" + "a" * 64,
            plugin_id="x",
            fetched_plugins_dir=fetched_dir,
        )
    # fetched_dir is created by fetch_plugin_bundle but is empty (no download)
    assert not (fetched_dir / "x").exists()


# ---------------------------------------------------------------------------
# ft1: matching digest → staged correctly
# ---------------------------------------------------------------------------


def test_ft1_valid_bundle_staged(tmp_path: Path) -> None:
    """Pinned source + matching digest → plugin staged in fetched_plugins_dir."""
    bundle = _minimal_plugin_zip()
    digest = _sha256(bundle)
    fetched_dir = tmp_path / "fetched"

    client = _mock_client(bundle)
    result = fetch_plugin_bundle(
        source_url="https://example.com/test_fetch.zip",
        expected_digest=digest,
        plugin_id="test_fetch",
        fetched_plugins_dir=fetched_dir,
        http_client=client,
    )

    assert result == fetched_dir / "test_fetch"
    assert (result / "plugin.yaml").exists()
    assert (result / "tools_impl.py").exists()


# ---------------------------------------------------------------------------
# ft2: digest mismatch → FetchError; staging untouched
# ---------------------------------------------------------------------------


def test_ft2_digest_mismatch_refused(tmp_path: Path) -> None:
    """A bundle with a wrong digest is rejected; fetched_plugins_dir is NOT touched."""
    bundle = _minimal_plugin_zip()
    wrong_digest = "sha256:" + "b" * 64  # wrong hex
    fetched_dir = tmp_path / "fetched"

    client = _mock_client(bundle)
    with pytest.raises(FetchError, match="digest mismatch"):
        fetch_plugin_bundle(
            source_url="https://example.com/plugin.zip",
            expected_digest=wrong_digest,
            plugin_id="my_plugin",
            fetched_plugins_dir=fetched_dir,
            http_client=client,
        )

    # The dest dir must NOT exist after failure
    assert not (fetched_dir / "my_plugin").exists()
    # No temp files left in fetched_dir (cleanup happened)
    leftover = (
        [f for f in fetched_dir.iterdir() if not f.name.startswith(".")]
        if fetched_dir.exists()
        else []
    )
    assert leftover == [], f"leftover temp files: {leftover}"


# ---------------------------------------------------------------------------
# ft4: unreachable / HTTP error → FetchError
# ---------------------------------------------------------------------------


def test_ft4_http_error_raises_fetch_error(tmp_path: Path) -> None:
    """HTTP error (e.g. 404) → FetchError; staging untouched."""
    fetched_dir = tmp_path / "fetched"
    client = _mock_client(b"", status_code=404)

    with pytest.raises(FetchError, match="download failed"):
        fetch_plugin_bundle(
            source_url="https://example.com/missing.zip",
            expected_digest="sha256:" + "a" * 64,
            plugin_id="missing",
            fetched_plugins_dir=fetched_dir,
            http_client=client,
        )

    assert not (fetched_dir / "missing").exists()


# ---------------------------------------------------------------------------
# ft5/ft8: digest-before-extract ordering
# ---------------------------------------------------------------------------


def test_ft8_bad_digest_rejected_before_extraction(tmp_path: Path) -> None:
    """A bundle with a bad digest is rejected BEFORE extraction — ordering property.

    The traversal bundle below would extract cleanly if not for the digest check.
    This test verifies the digest check runs before extract (not after).
    """
    # A valid-looking zip but with wrong digest
    bundle = _make_zip_bundle({"plugin.yaml": b"schema_version: 1\nid: x\nname: x\nversion: 0\n"})
    wrong_digest = "sha256:" + "c" * 64
    fetched_dir = tmp_path / "fetched"

    sentinel = tmp_path / "extracted_sentinel"

    # Patch _detect_and_extract to write a sentinel if called (should NOT be called)
    import orchestrator.plugins.fetch as fetch_mod

    original_extract = fetch_mod._detect_and_extract

    def sentinel_extract(bundle_bytes: bytes, staging_dir: Path, url: str) -> None:
        sentinel.write_bytes(b"extracted")
        original_extract(bundle_bytes, staging_dir, url)

    fetch_mod._detect_and_extract = sentinel_extract  # type: ignore[assignment]
    try:
        client = _mock_client(bundle)
        with pytest.raises(FetchError, match="digest mismatch"):
            fetch_plugin_bundle(
                source_url="https://example.com/x.zip",
                expected_digest=wrong_digest,
                plugin_id="x",
                fetched_plugins_dir=fetched_dir,
                http_client=client,
            )
        # sentinel must NOT exist: extraction was not attempted before digest check
        assert not sentinel.exists(), (
            "ft8: extraction happened before digest check — ordering violated"
        )
    finally:
        fetch_mod._detect_and_extract = original_extract


def test_ft5_path_traversal_in_zip_refused(tmp_path: Path) -> None:
    """A zip bundle with a path-traversal member is rejected (even after digest passes)."""
    # Craft a zip with a traversal path — must be refused at extraction time (after digest)
    traversal_bundle = _make_zip_bundle({"../evil.py": b"evil code"})
    digest = _sha256(traversal_bundle)
    fetched_dir = tmp_path / "fetched"

    client = _mock_client(traversal_bundle)
    with pytest.raises(FetchError, match="path traversal"):
        fetch_plugin_bundle(
            source_url="https://example.com/traversal.zip",
            expected_digest=digest,
            plugin_id="traversal_plugin",
            fetched_plugins_dir=fetched_dir,
            http_client=client,
        )

    # Staging untouched
    assert not (fetched_dir / "traversal_plugin").exists()


# ---------------------------------------------------------------------------
# ft6: oversized bundle → FetchError before extraction
# ---------------------------------------------------------------------------


def test_ft6_oversized_bundle_refused(tmp_path: Path) -> None:
    """A bundle exceeding _MAX_BUNDLE_BYTES is refused before extraction."""
    from orchestrator.plugins.fetch import _MAX_BUNDLE_BYTES

    # Create a bundle slightly bigger than the limit
    large_bundle = b"x" * (_MAX_BUNDLE_BYTES + 1)
    digest = _sha256(large_bundle)
    fetched_dir = tmp_path / "fetched"

    client = _mock_client(large_bundle)
    with pytest.raises(FetchError, match="too large"):
        fetch_plugin_bundle(
            source_url="https://example.com/large.zip",
            expected_digest=digest,
            plugin_id="large",
            fetched_plugins_dir=fetched_dir,
            http_client=client,
        )

    assert not (fetched_dir / "large").exists()


# ---------------------------------------------------------------------------
# ft7: atomic staging cleanup on failure
# ---------------------------------------------------------------------------


def test_ft7_atomic_staging_cleanup_on_failure(tmp_path: Path) -> None:
    """On any failure during extraction, temp dirs are cleaned up atomically."""
    # Valid digest but extraction will fail (no plugin.yaml in archive)
    bundle = _make_zip_bundle({"some_file.txt": b"content"})  # no plugin.yaml
    digest = _sha256(bundle)
    fetched_dir = tmp_path / "fetched"

    client = _mock_client(bundle)
    with pytest.raises(FetchError, match=r"plugin\.yaml"):
        fetch_plugin_bundle(
            source_url="https://example.com/no_manifest.zip",
            expected_digest=digest,
            plugin_id="no_manifest",
            fetched_plugins_dir=fetched_dir,
            http_client=client,
        )

    # No partial state in fetched_plugins_dir
    assert not (fetched_dir / "no_manifest").exists()
    leftover_temps = (
        [f for f in fetched_dir.iterdir() if f.name.startswith("plugin_")]
        if fetched_dir.exists()
        else []
    )
    assert leftover_temps == [], f"leftover temp dirs: {leftover_temps}"


# ---------------------------------------------------------------------------
# ft9: oversized bundle — cap enforced DURING stream (bounded consumption)
# ---------------------------------------------------------------------------


def test_ft9_oversized_bundle_capped_during_stream_bounded(tmp_path: Path) -> None:
    """A body >> cap is aborted DURING the stream — consumption bounded, not the full N (OOM fix).

    Discriminating (fail-on-revert): revert to response.content (buffer-all) → httpx pulls
    the entire generator → pulled["bytes"] == total_n → both bounded asserts fail.
    """
    from orchestrator.plugins.fetch import _MAX_BUNDLE_BYTES

    chunk = 1024 * 1024  # 1 MB chunks
    total_n = _MAX_BUNDLE_BYTES + 20 * chunk  # N >> cap
    pulled: dict[str, int] = {"bytes": 0}

    def _gen() -> Generator[bytes, None, None]:
        produced = 0
        while produced < total_n:
            n = min(chunk, total_n - produced)
            produced += n
            pulled["bytes"] += n
            yield b"x" * n

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_gen())

    client = httpx.Client(transport=httpx.MockTransport(_handler))
    fetched_dir = tmp_path / "fetched"
    with pytest.raises(FetchError, match="too large"):
        fetch_plugin_bundle(
            source_url="https://example.com/huge.zip",
            expected_digest="sha256:" + "a" * 64,
            plugin_id="huge",
            fetched_plugins_dir=fetched_dir,
            http_client=client,
        )

    # bounded: stopped within one chunk of the cap, did NOT pull the whole N
    assert pulled["bytes"] <= _MAX_BUNDLE_BYTES + chunk
    assert pulled["bytes"] < total_n
    assert not (fetched_dir / "huge").exists()  # fetched_plugins_dir untouched (ft7 parallel)


# ---------------------------------------------------------------------------
# ft10: valid multi-chunk bundle — incremental hash gives correct digest
# ---------------------------------------------------------------------------


def test_ft10_valid_multichunk_streamed_stages(tmp_path: Path) -> None:
    """Multi-chunk streaming still computes the correct sha256 and stages successfully.

    Proves incremental hashing over a chunked response gives the same final
    digest as a single-shot hash of the complete bytes.
    """
    bundle = _minimal_plugin_zip()
    digest = _sha256(bundle)

    chunk_size = 16  # very small chunks to exercise multi-chunk incremental hashing

    def _chunked_handler(request: httpx.Request) -> httpx.Response:
        def _chunks() -> Generator[bytes, None, None]:
            offset = 0
            while offset < len(bundle):
                yield bundle[offset : offset + chunk_size]
                offset += chunk_size

        return httpx.Response(200, content=_chunks())

    client = httpx.Client(transport=httpx.MockTransport(_chunked_handler))
    fetched_dir = tmp_path / "fetched"

    result = fetch_plugin_bundle(
        source_url="https://example.com/multichunk.zip",
        expected_digest=digest,
        plugin_id="multichunk",
        fetched_plugins_dir=fetched_dir,
        http_client=client,
    )

    assert result == fetched_dir / "multichunk"
    assert (result / "plugin.yaml").exists()
