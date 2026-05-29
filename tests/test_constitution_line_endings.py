"""Constitutional test: all tracked text files use LF line endings only.

If this test fails: do NOT change the test. Find the file with CRLF and
strip carriage returns:

    sed -i 's/\\r$//' <file>

The .gitattributes rule `* text=auto eol=lf` is the source of truth;
this test is the runtime check that catches violations the moment they
are introduced (Windows-side tool LF→CRLF conversion, manual edits with
wrong line endings, .gitattributes regressions).

Source incident: P1.6 cycle workflow surfaced 174 files in CRLF/LF
limbo due to Windows-side tools converting LF → CRLF in a shared
WSL/Windows working tree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# File extensions that are binary by convention; skip the CR check.
_BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".tar",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
}

# Files that intentionally keep CRLF (Windows-only scripts).
_CRLF_EXTENSIONS = {".bat", ".cmd", ".ps1"}


def _tracked_files() -> list[Path]:
    """Return absolute paths of all git-tracked files in the repo."""
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return [_REPO_ROOT / line for line in result.stdout.splitlines() if line]


def test_constitution_all_text_files_use_lf() -> None:
    """All tracked text files must use LF line endings (no CRLF).

    Detection: any occurrence of the byte pair `\\r\\n` in raw file
    bytes. Files whose extension is in `_BINARY_EXTENSIONS` are skipped
    (binary, no line-ending normalization needed). Files whose extension
    is in `_CRLF_EXTENSIONS` are skipped (Windows scripts intentionally
    CRLF per .gitattributes).
    """
    violators: list[str] = []
    for path in _tracked_files():
        if not path.exists():
            continue
        suffix = path.suffix.lower()
        if suffix in _BINARY_EXTENSIONS or suffix in _CRLF_EXTENSIONS:
            continue
        try:
            raw = path.read_bytes()
        except (OSError, PermissionError):
            continue
        if b"\r\n" in raw:
            violators.append(str(path.relative_to(_REPO_ROOT)))

    if violators:
        preview = "\n".join(f"  - {p}" for p in sorted(violators)[:20])
        more = f"\n  ... and {len(violators) - 20} more" if len(violators) > 20 else ""
        raise AssertionError(
            f"{len(violators)} tracked text files contain CRLF line endings "
            f"(must be LF only per .gitattributes):\n{preview}{more}\n\n"
            "Fix with: sed -i 's/\\r$//' <file>"
        )
