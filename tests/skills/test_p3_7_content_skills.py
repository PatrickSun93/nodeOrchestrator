"""Discriminating tests for P3.7-content new skills (P3.7-content-5..7).

Per plan §2 Common acceptance bar:
  - filename stem == id (ADR-009 D8 — loader enforces)
  - non-empty body
  - validates against frozen Skill schema
  - skill matches for a declared room/agent/state
  - skill rejected (rejection_reason != "matched") for a non-declared room type
"""

from __future__ import annotations

from pathlib import Path

from orchestrator.core.room import RoomType
from orchestrator.skills.decision import decide_skills_for_context
from orchestrator.skills.loader import load_skills
from orchestrator.skills.schema import Skill

_SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "skills"


def _load() -> dict[str, Skill]:
    return load_skills(_SKILLS_DIR)


# ---------------------------------------------------------------------------
# P3.7-content-5: business/idea-validation-rubric
# ---------------------------------------------------------------------------


class TestBusinessSkill:
    """Discriminating tests for idea-validation-rubric (P3.7-content-5)."""

    def test_idea_validation_rubric_loads(self) -> None:
        """idea-validation-rubric loads from config/skills/business/."""
        skills = _load()
        assert "idea-validation-rubric" in skills

    def test_idea_validation_rubric_is_valid_skill(self) -> None:
        """idea-validation-rubric validates against frozen Skill schema."""
        skills = _load()
        skill = skills["idea-validation-rubric"]
        assert isinstance(skill, Skill)
        assert skill.id == "idea-validation-rubric"
        assert skill.category == "business"

    def test_idea_validation_rubric_non_empty_body(self) -> None:
        """idea-validation-rubric has non-empty body."""
        skills = _load()
        assert len(skills["idea-validation-rubric"].body) > 0

    def test_idea_validation_rubric_matches_for_idea_validation_room(self) -> None:
        """idea-validation-rubric selected for (*, idea_validation, *)."""
        skills = _load()
        result = decide_skills_for_context(
            "prober", RoomType.IDEA_VALIDATION, "pitching", available_skills=skills
        )
        selected_ids = {s.id for s in result.selected}
        assert "idea-validation-rubric" in selected_ids

    def test_idea_validation_rubric_rejected_for_code_review(self) -> None:
        """idea-validation-rubric NOT selected for code_review (room_type_mismatch)."""
        skills = _load()
        result = decide_skills_for_context(
            "skeptic", RoomType.CODE_REVIEW, "reviewing", available_skills=skills
        )
        selected_ids = {s.id for s in result.selected}
        assert "idea-validation-rubric" not in selected_ids
        record = next(
            (r for r in result.trace.considered if r.skill_id == "idea-validation-rubric"),
            None,
        )
        assert record is not None
        assert record.rejection_reason == "room_type_mismatch"

    def test_idea_validation_rubric_rejected_for_research(self) -> None:
        """idea-validation-rubric NOT selected for research (room_type_mismatch)."""
        skills = _load()
        result = decide_skills_for_context(
            "prober", RoomType.RESEARCH, "open", available_skills=skills
        )
        selected_ids = {s.id for s in result.selected}
        assert "idea-validation-rubric" not in selected_ids


# ---------------------------------------------------------------------------
# P3.7-content-6: engineering/code-review-checklist
# ---------------------------------------------------------------------------


class TestEngineeringSkill:
    """Discriminating tests for code-review-checklist (P3.7-content-6)."""

    def test_code_review_checklist_loads(self) -> None:
        """code-review-checklist loads from config/skills/engineering/."""
        skills = _load()
        assert "code-review-checklist" in skills

    def test_code_review_checklist_is_valid_skill(self) -> None:
        """code-review-checklist validates against frozen Skill schema."""
        skills = _load()
        skill = skills["code-review-checklist"]
        assert isinstance(skill, Skill)
        assert skill.id == "code-review-checklist"
        assert skill.category == "engineering"

    def test_code_review_checklist_non_empty_body(self) -> None:
        """code-review-checklist has non-empty body."""
        skills = _load()
        assert len(skills["code-review-checklist"].body) > 0

    def test_code_review_checklist_matches_for_code_review_room(self) -> None:
        """code-review-checklist selected for (*, code_review, *)."""
        skills = _load()
        result = decide_skills_for_context(
            "skeptic", RoomType.CODE_REVIEW, "reviewing", available_skills=skills
        )
        selected_ids = {s.id for s in result.selected}
        assert "code-review-checklist" in selected_ids

    def test_code_review_checklist_rejected_for_research(self) -> None:
        """code-review-checklist NOT selected for research (room_type_mismatch)."""
        skills = _load()
        result = decide_skills_for_context(
            "prober", RoomType.RESEARCH, "open", available_skills=skills
        )
        selected_ids = {s.id for s in result.selected}
        assert "code-review-checklist" not in selected_ids
        record = next(
            (r for r in result.trace.considered if r.skill_id == "code-review-checklist"),
            None,
        )
        assert record is not None
        assert record.rejection_reason == "room_type_mismatch"

    def test_code_review_checklist_rejected_for_bug_fix(self) -> None:
        """code-review-checklist NOT selected for bug_fix (room_type_mismatch)."""
        skills = _load()
        result = decide_skills_for_context(
            "operator", RoomType.BUG_FIX, "diagnosed", available_skills=skills
        )
        selected_ids = {s.id for s in result.selected}
        assert "code-review-checklist" not in selected_ids


# ---------------------------------------------------------------------------
# P3.7-content-7: general/facilitation-norms
# ---------------------------------------------------------------------------


class TestGeneralSkill:
    """Discriminating tests for facilitation-norms (P3.7-content-7)."""

    def test_facilitation_norms_loads(self) -> None:
        """facilitation-norms loads from config/skills/general/."""
        skills = _load()
        assert "facilitation-norms" in skills

    def test_facilitation_norms_is_valid_skill(self) -> None:
        """facilitation-norms validates against frozen Skill schema."""
        skills = _load()
        skill = skills["facilitation-norms"]
        assert isinstance(skill, Skill)
        assert skill.id == "facilitation-norms"
        assert skill.category == "general"

    def test_facilitation_norms_non_empty_body(self) -> None:
        """facilitation-norms has non-empty body."""
        skills = _load()
        assert len(skills["facilitation-norms"].body) > 0

    def test_facilitation_norms_matches_for_free_chat_room(self) -> None:
        """facilitation-norms selected for (*, free_chat, *)."""
        skills = _load()
        result = decide_skills_for_context(
            "facilitator", RoomType.FREE_CHAT, "active", available_skills=skills
        )
        selected_ids = {s.id for s in result.selected}
        assert "facilitation-norms" in selected_ids

    def test_facilitation_norms_rejected_for_bug_fix(self) -> None:
        """facilitation-norms NOT selected for bug_fix (room_type_mismatch)."""
        skills = _load()
        result = decide_skills_for_context(
            "operator", RoomType.BUG_FIX, "diagnosed", available_skills=skills
        )
        selected_ids = {s.id for s in result.selected}
        assert "facilitation-norms" not in selected_ids
        record = next(
            (r for r in result.trace.considered if r.skill_id == "facilitation-norms"),
            None,
        )
        assert record is not None
        assert record.rejection_reason == "room_type_mismatch"

    def test_facilitation_norms_rejected_for_research(self) -> None:
        """facilitation-norms NOT selected for research (room_type_mismatch)."""
        skills = _load()
        result = decide_skills_for_context(
            "prober", RoomType.RESEARCH, "open", available_skills=skills
        )
        selected_ids = {s.id for s in result.selected}
        assert "facilitation-norms" not in selected_ids
