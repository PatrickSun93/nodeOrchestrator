"""Tests for src/orchestrator/skills/loader.py.

Coverage-standard application:
  §3: file-handle cleanup on mid-iteration raise (tested implicitly via tmp_path
      — pathlib.Path.read_text() is context-managed, so handles are released even
      on exception; the test verifies no SkillError swallows a second file's error).
  §4: SkillError carries path and field on validation failures.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from orchestrator.skills.exceptions import SkillError
from orchestrator.skills.loader import load_skills

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_FRONTMATTER = dedent("""\
    ---
    id: {id}
    category: general
    applies_to:
      agents: [prober]
      room_types: [research]
    priority: 50
    ---

    Placeholder body text for testing.
""")

_STAR_AGENTS_FRONTMATTER = dedent("""\
    ---
    id: {id}
    category: engineering
    applies_to:
      agents: ["*"]
      room_types: [bug_fix]
      room_states: ["open"]
    priority: 70
    ---

    Placeholder body text for testing.
""")


def _write_skill(directory: Path, stem: str, content: str) -> Path:
    p = directory / f"{stem}.md"
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_load_two_valid_files(tmp_path: Path) -> None:
    _write_skill(tmp_path, "skill-a", _VALID_FRONTMATTER.format(id="skill-a"))
    _write_skill(tmp_path, "skill-b", _VALID_FRONTMATTER.format(id="skill-b"))

    result = load_skills(tmp_path)

    assert set(result) == {"skill-a", "skill-b"}
    assert result["skill-a"].id == "skill-a"
    assert result["skill-b"].id == "skill-b"


def test_load_star_agents_skill(tmp_path: Path) -> None:
    _write_skill(tmp_path, "debug-tool", _STAR_AGENTS_FRONTMATTER.format(id="debug-tool"))

    result = load_skills(tmp_path)

    assert "debug-tool" in result
    assert result["debug-tool"].applies_to.agents == ["*"]
    assert result["debug-tool"].applies_to.room_states == ["open"]


def test_load_skill_with_explicit_room_states(tmp_path: Path) -> None:
    content = dedent("""\
        ---
        id: room-state-skill
        category: general
        applies_to:
          agents: [prober]
          room_types: [research]
          room_states: ["open", "reviewing"]
        priority: 40
        ---

        Body.
    """)
    _write_skill(tmp_path, "room-state-skill", content)

    result = load_skills(tmp_path)
    assert result["room-state-skill"].applies_to.room_states == ["open", "reviewing"]


def test_load_empty_directory(tmp_path: Path) -> None:
    result = load_skills(tmp_path)
    assert result == {}


# ---------------------------------------------------------------------------
# Error cases — §4 payload assertions
# ---------------------------------------------------------------------------


def test_missing_directory_raises(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent"
    with pytest.raises(SkillError) as exc_info:
        load_skills(missing)
    assert exc_info.value.path == missing


def test_missing_frontmatter_raises_with_path(tmp_path: Path) -> None:
    p = _write_skill(tmp_path, "no-frontmatter", "# Just a markdown file\n\nNo YAML here.")
    with pytest.raises(SkillError) as exc_info:
        load_skills(tmp_path)
    assert exc_info.value.path == p
    assert "missing" in str(exc_info.value).lower() or "fence" in str(exc_info.value).lower()


def test_unclosed_frontmatter_raises(tmp_path: Path) -> None:
    content = "---\nid: test\ncategory: general\n# no closing fence"
    p = _write_skill(tmp_path, "unclosed", content)
    with pytest.raises(SkillError) as exc_info:
        load_skills(tmp_path)
    assert exc_info.value.path == p
    assert "unclosed" in str(exc_info.value).lower()


def test_scalar_yaml_frontmatter_raises_with_path(tmp_path: Path) -> None:
    """R0-A-on-plan-5: frontmatter that parses to a non-dict scalar raises SkillError."""
    content = "---\nfoo\n---\n\nBody."
    p = _write_skill(tmp_path, "scalar-fm", content)
    with pytest.raises(SkillError) as exc_info:
        load_skills(tmp_path)
    assert exc_info.value.path == p
    assert "must be a mapping" in str(exc_info.value)


def test_filename_id_mismatch_raises(tmp_path: Path) -> None:
    # file is named "wrong-name.md" but declares id: correct-id
    _write_skill(tmp_path, "wrong-name", _VALID_FRONTMATTER.format(id="correct-id"))
    with pytest.raises(SkillError) as exc_info:
        load_skills(tmp_path)
    assert exc_info.value.field == "id"
    assert "wrong-name" in str(exc_info.value)
    assert "correct-id" in str(exc_info.value)


def test_duplicate_id_raises(tmp_path: Path) -> None:
    # Two files with the same id — possible if different categories
    subdir = tmp_path / "general"
    subdir.mkdir()
    subdir2 = tmp_path / "engineering"
    subdir2.mkdir()
    _write_skill(subdir, "my-skill", _VALID_FRONTMATTER.format(id="my-skill"))
    _write_skill(subdir2, "my-skill", _VALID_FRONTMATTER.format(id="my-skill"))
    with pytest.raises(SkillError) as exc_info:
        load_skills(tmp_path)
    assert exc_info.value.field == "id"
    assert "duplicate" in str(exc_info.value).lower()


def test_schema_validation_failure_raises_with_path(tmp_path: Path) -> None:
    content = dedent("""\
        ---
        id: bad-priority
        category: general
        applies_to:
          agents: [prober]
          room_types: [research]
        priority: 999
        ---

        Body.
    """)
    p = _write_skill(tmp_path, "bad-priority", content)
    with pytest.raises(SkillError) as exc_info:
        load_skills(tmp_path)
    assert exc_info.value.path == p
    assert exc_info.value.field is not None


# ---------------------------------------------------------------------------
# §3 file-handle cleanup (mid-iteration raise)
# ---------------------------------------------------------------------------


def test_mid_iteration_raise_does_not_prevent_second_file_from_being_attempted(
    tmp_path: Path,
) -> None:
    """One valid file + one malformed file: loader raises on the malformed file.
    If file handles leaked, the tmp_path cleanup at end of test would fail.
    pathlib.Path.read_text() is context-managed — handles are freed on return
    or exception. This test verifies the loader raises (not swallows) the error
    from the second file.
    """
    subdir = tmp_path
    # Sort order: "aaa-valid.md" < "zzz-malformed.md" — valid loads first
    _write_skill(subdir, "aaa-valid", _VALID_FRONTMATTER.format(id="aaa-valid"))
    p_bad = _write_skill(subdir, "zzz-malformed", "no frontmatter")

    with pytest.raises(SkillError) as exc_info:
        load_skills(tmp_path)
    assert exc_info.value.path == p_bad
