"""Integration tests: load_skills → decide_skills_for_context end-to-end.

Coverage-standard application:
  §1: source ≠ sink — loader reads yaml-derived lists; matcher returns
      Skill objects whose field values come from the loaded files, not
      hardcoded defaults.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from orchestrator.core.room import RoomType
from orchestrator.skills.decision import decide_skills_for_context
from orchestrator.skills.loader import load_skills

_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "skills"


# ---------------------------------------------------------------------------
# Real sample skills from config/skills/
# ---------------------------------------------------------------------------


def test_full_happy_path_research_decomposition_selected() -> None:
    """(prober, research, "open") → research-decomposition selected.

    §1 source ≠ sink: the test passes agent_id="prober" as a literal string;
    the loader derives Skill.applies_to.agents from YAML; the matcher returns
    a Skill whose applies_to.agents list came from the file, not a default.
    Assert the yaml-derived list equals ["prober", "skeptic"] AND differs from
    the sentinel ["sentinel-not-in-yaml"].
    """
    skills = load_skills(_SKILLS_DIR)

    result = decide_skills_for_context("prober", RoomType.RESEARCH, "open", available_skills=skills)

    selected_ids = [s.id for s in result.selected]
    assert "research-decomposition" in selected_ids

    rd_skill = next(s for s in result.selected if s.id == "research-decomposition")
    assert rd_skill.applies_to.agents == ["prober", "skeptic"]
    assert rd_skill.applies_to.agents != ["sentinel-not-in-yaml"]


def test_star_agents_debugging_workflow_selected_for_any_agent() -> None:
    """(operator, bug_fix, "open") → debugging-workflow selected via ["*"] agents."""
    skills = load_skills(_SKILLS_DIR)

    result = decide_skills_for_context(
        "operator", RoomType.BUG_FIX, "open", available_skills=skills
    )

    selected_ids = [s.id for s in result.selected]
    assert "debugging-workflow" in selected_ids

    dw_skill = next(s for s in result.selected if s.id == "debugging-workflow")
    assert dw_skill.applies_to.agents == ["*"]


def test_debugging_workflow_not_selected_when_room_state_is_closed() -> None:
    """(operator, bug_fix, "closed") → debugging-workflow NOT selected (room_state mismatch)."""
    skills = load_skills(_SKILLS_DIR)

    result = decide_skills_for_context(
        "operator", RoomType.BUG_FIX, "closed", available_skills=skills
    )

    selected_ids = [s.id for s in result.selected]
    assert "debugging-workflow" not in selected_ids

    dw_record = next(r for r in result.trace.considered if r.skill_id == "debugging-workflow")
    assert dw_record.rejection_reason == "room_state_mismatch"


def test_priority_and_tiebreak_with_synthetic_third_skill(tmp_path: Path) -> None:
    """Priority + tie-break on a synthetic third skill added at runtime.

    Adds a 3rd skill at priority=70 with id="aaa-synthetic" to conflict with
    debugging-workflow (priority=70). Tie broken alphabetically:
    "aaa-synthetic" < "debugging-workflow", so aaa-synthetic comes first in the
    selection for agents that match both.
    """
    # Copy real skills dir + add a synthetic skill to tmp_path
    import shutil

    shutil.copytree(_SKILLS_DIR, tmp_path / "skills")
    synthetic_content = dedent("""\
        ---
        id: aaa-synthetic
        category: engineering
        applies_to:
          agents: ["*"]
          room_types: [bug_fix]
          room_states: ["open"]
        priority: 70
        ---

        Synthetic skill for tie-break testing.
    """)
    (tmp_path / "skills" / "engineering" / "aaa-synthetic.md").write_text(
        synthetic_content, encoding="utf-8"
    )

    skills = load_skills(tmp_path / "skills")

    result = decide_skills_for_context(
        "operator", RoomType.BUG_FIX, "open", available_skills=skills
    )

    selected_ids = [s.id for s in result.selected]
    assert "aaa-synthetic" in selected_ids
    assert "debugging-workflow" in selected_ids
    # Both priority=70: alphabetical tie-break → aaa-synthetic before debugging-workflow
    aaa_idx = selected_ids.index("aaa-synthetic")
    dw_idx = selected_ids.index("debugging-workflow")
    assert aaa_idx < dw_idx, (
        f"aaa-synthetic (idx={aaa_idx}) should sort before debugging-workflow (idx={dw_idx}) "
        "on priority tie (both 70), alphabetical id order"
    )
