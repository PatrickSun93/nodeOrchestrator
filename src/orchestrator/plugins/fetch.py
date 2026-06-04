"""Minimal remote-fetch mechanism for fetched plugin bundles (ADR-031 D5).

Fetches one plugin bundle (a single .zip or .tar.gz archive) from a pinned
https:// source into the segregated fetched_plugins_dir.

Security properties (ADR-031 D5):
  - Digest-before-extract ordering: compute sha256 of compressed bundle bytes
    BEFORE any extraction — the ordering IS the security property (R0-B Y5).
    Only a digest-matching bundle is then extracted.
  - Path-traversal guard: reject member paths containing '..', absolute paths,
    and symlinks that escape the staging directory.
  - Atomic staging + cleanup (R0-B Y7): download → temp-file → verify-digest
    → extract → temp-dir → validate-members → rename → fetched_plugins_dir.
    On ANY failure: delete the temp file / rmtree the temp dir.
    fetched_plugins_dir is NEVER touched by a failed fetch.
  - TLS mandatory: only https:// source URLs accepted; http:// refused.
  - No registry/marketplace/version/upgrade lifecycle (deferred P4).
"""

from __future__ import annotations

import hashlib
import io
import logging
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path

import httpx

_log = logging.getLogger("orchestrator.plugins.fetch")

# Maximum bundle size accepted (50 MB) — oversized bundles refused before extraction.
_MAX_BUNDLE_BYTES: int = 50 * 1024 * 1024


class FetchError(Exception):
    """Raised when a plugin bundle fetch or validation fails."""


def _parse_digest(digest_spec: str) -> tuple[str, str]:
    """Parse '<alg>:<hex>' digest spec, returning (alg, hex).

    Only 'sha256' is supported.
    """
    if ":" not in digest_spec:
        raise FetchError(f"digest must be '<alg>:<hex>', got {digest_spec!r}")
    alg, _, hex_val = digest_spec.partition(":")
    if alg != "sha256":
        raise FetchError(f"unsupported digest algorithm {alg!r}; only 'sha256' is supported")
    if len(hex_val) != 64 or not all(c in "0123456789abcdef" for c in hex_val.lower()):
        raise FetchError(f"invalid sha256 hex value: {hex_val!r}")
    return alg, hex_val.lower()


def _compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_member_path(member_path: str, staging_dir: Path) -> Path:
    """Validate member path is safe (no traversal, no absolute, no symlink escape).

    Returns the resolved target path under staging_dir.
    Raises FetchError if the member path is unsafe.
    """
    if member_path.startswith("/") or member_path.startswith("\\"):
        raise FetchError(f"path traversal: absolute member path {member_path!r}")
    resolved = (staging_dir / member_path).resolve()
    try:
        resolved.relative_to(staging_dir.resolve())
    except ValueError:
        raise FetchError(f"path traversal: member {member_path!r} escapes staging dir") from None
    return resolved


def _extract_zip(bundle_bytes: bytes, staging_dir: Path) -> None:
    """Extract zip bundle to staging_dir with path-traversal guards."""
    with zipfile.ZipFile(io.BytesIO(bundle_bytes)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if ".." in info.filename:
                raise FetchError(f"path traversal in zip member: {info.filename!r}")
            target = _safe_member_path(info.filename, staging_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info.filename))


def _extract_tar(bundle_bytes: bytes, staging_dir: Path) -> None:
    """Extract tar/tar.gz bundle to staging_dir with path-traversal guards."""
    with tarfile.open(fileobj=io.BytesIO(bundle_bytes)) as tf:
        for member in tf.getmembers():
            if member.isdir():
                continue
            if member.issym() or member.islnk():
                raise FetchError(f"symlink/hardlink in tar member: {member.name!r}")
            if ".." in member.name:
                raise FetchError(f"path traversal in tar member: {member.name!r}")
            target = _safe_member_path(member.name, staging_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            f = tf.extractfile(member)
            if f is not None:
                target.write_bytes(f.read())


def _detect_and_extract(bundle_bytes: bytes, staging_dir: Path, source_url: str) -> None:
    """Detect bundle format from URL extension and extract with traversal guards."""
    url_lower = source_url.lower()
    if url_lower.endswith(".zip"):
        _extract_zip(bundle_bytes, staging_dir)
    elif url_lower.endswith(".tar.gz") or url_lower.endswith(".tgz"):
        _extract_tar(bundle_bytes, staging_dir)
    else:
        raise FetchError(
            f"unsupported bundle format: {source_url!r}; only .zip and .tar.gz supported"
        )


def fetch_plugin_bundle(
    source_url: str,
    expected_digest: str,
    plugin_id: str,
    fetched_plugins_dir: Path,
    *,
    http_client: httpx.Client | None = None,
) -> Path:
    """Fetch one plugin bundle and stage it atomically into fetched_plugins_dir.

    Security ordering (ADR-031 D5; R0-B Y5):
      1. Refuse non-https:// source_url.
      2. Download to temp file.
      3. Verify digest of compressed bundle bytes (BEFORE any extraction).
      4. Extract to temp staging dir (path-traversal guarded).
      5. Validate extracted members.
      6. Atomic rename into fetched_plugins_dir.
      On any failure: clean up temp file / temp dir; fetched_plugins_dir untouched.

    Returns the staged plugin directory path.

    Raises FetchError on any failure (non-https, TLS error, unreachable, digest
    mismatch, oversized bundle, path traversal, format error).
    """
    if not source_url.startswith("https://"):
        raise FetchError(f"fetch refused: source_url must use https://, got {source_url!r}")

    _parse_digest(expected_digest)  # validate format early

    fetched_plugins_dir.mkdir(parents=True, exist_ok=True)
    dest_dir = fetched_plugins_dir / plugin_id

    tmp_bundle: Path | None = None
    tmp_staging: Path | None = None

    try:
        # Step 2: Download to temp file
        _fd, tmp_bundle_str = tempfile.mkstemp(
            prefix=f"plugin_fetch_{plugin_id}_",
            dir=fetched_plugins_dir,
        )
        tmp_bundle = Path(tmp_bundle_str)
        try:
            bundle_bytes = _download(source_url, http_client)
        except Exception as exc:
            raise FetchError(f"download failed from {source_url!r}: {exc}") from exc

        tmp_bundle.write_bytes(bundle_bytes)

        # Step 3: Verify digest BEFORE any extraction (the ordering IS the security property)
        if len(bundle_bytes) > _MAX_BUNDLE_BYTES:
            raise FetchError(
                f"bundle too large: {len(bundle_bytes)} bytes > {_MAX_BUNDLE_BYTES} limit"
            )
        actual_digest = _compute_sha256(bundle_bytes)
        _, expected_hex = _parse_digest(expected_digest)
        if actual_digest != expected_hex:
            raise FetchError(
                f"digest mismatch for {source_url!r}: "
                f"expected sha256:{expected_hex}, got sha256:{actual_digest}"
            )

        # Step 4: Extract to temp staging dir (traversal-guarded, AFTER digest passes)
        tmp_staging = Path(
            tempfile.mkdtemp(prefix=f"plugin_stage_{plugin_id}_", dir=fetched_plugins_dir)
        )
        _detect_and_extract(bundle_bytes, tmp_staging, source_url)

        # Step 5: Validate there is at least a plugin.yaml (basic sanity)
        if not (tmp_staging / "plugin.yaml").exists():
            raise FetchError(f"bundle from {source_url!r} does not contain plugin.yaml at root")

        # Step 6: Atomic rename into fetched_plugins_dir
        # Remove existing staging if present (re-fetch idempotence)
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        tmp_staging.rename(dest_dir)
        tmp_staging = None  # rename succeeded; don't clean it up

        _log.info(
            "plugin %r: fetched and staged from %r (digest sha256:%s)",
            plugin_id,
            source_url,
            expected_hex,
        )
        return dest_dir

    except Exception:
        # Cleanup: fetched_plugins_dir never touched by a failed fetch
        if tmp_staging is not None and tmp_staging.exists():
            shutil.rmtree(tmp_staging, ignore_errors=True)
        if tmp_bundle is not None and tmp_bundle.exists():
            tmp_bundle.unlink(missing_ok=True)
        raise

    finally:
        # Always clean up temp bundle (even on success; staging dir was renamed)
        if tmp_bundle is not None and tmp_bundle.exists():
            tmp_bundle.unlink(missing_ok=True)


def _download(source_url: str, http_client: httpx.Client | None) -> bytes:
    """Download from source_url, returning response bytes.

    Uses caller-supplied httpx.Client or creates a minimal one with verify=True.
    """
    if http_client is not None:
        response = http_client.get(source_url)
        response.raise_for_status()
        return response.content

    # Default: host-built client with verify=True (TLS required, ADR-032 D2 parallel)
    with httpx.Client(verify=True) as client:
        response = client.get(source_url)
        response.raise_for_status()
        return response.content
