"""Tests for src/orchestrator/skills/schema.py — §6 invariants for all models.

Coverage-standard application:
  §4: SkillError payload assertions live in test_loader.py (loader context).
  §5: multi-position boundary tests for AppliesTo.agents star-mixing.
  §6: every Pydantic model — frozen + extra-forbid + Field constraints + Literals.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from orchestrator.core.room import RoomType
from orchestrator.skills.exceptions import SkillError
from orchestrator.skills.schema import (
    AppliesTo,
    Skill,
    SkillDecisionTrace,
    SkillMatchRecord,
    SkillSelection,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_APPLIES_TO = AppliesTo(
    agents=["prober"],
    room_types=[RoomType.RESEARCH],
)

_VALID_SKILL = Skill(
    id="test-skill",
    category="general",
    applies_to=_VALID_APPLIES_TO,
    priority=50,
    body="placeholder body",
)

_VALID_MATCH_RECORD = SkillMatchRecord(
    skill_id="test-skill",
    rejection_reason="matched",
)

_VALID_TRACE = SkillDecisionTrace(
    considered=[_VALID_MATCH_RECORD],
    selected_count=1,
    rejected_count=0,
)


# ---------------------------------------------------------------------------
# AppliesTo — §6 + §5 boundary
# ---------------------------------------------------------------------------


class TestAppliesTo:
    def test_frozen_raises_on_mutation(self) -> None:
        obj = AppliesTo(agents=["prober"], room_types=[RoomType.RESEARCH])
        with pytest.raises(ValidationError):
            obj.agents = ["other"]  # Pydantic frozen raises ValidationError at runtime

    def test_extra_forbid_raises(self) -> None:
        with pytest.raises(ValidationError):
            AppliesTo(
                agents=["prober"],
                room_types=[RoomType.RESEARCH],
                unknown_field="x",  # type: ignore[call-arg]
            )

    def test_agents_empty_raises(self) -> None:
        with pytest.raises(ValidationError):
            AppliesTo(agents=[], room_types=[RoomType.RESEARCH])

    def test_room_types_empty_raises(self) -> None:
        with pytest.raises(ValidationError):
            AppliesTo(agents=["prober"], room_types=[])

    def test_room_states_empty_list_raises(self) -> None:
        with pytest.raises(ValidationError, match="non-empty list"):
            AppliesTo(agents=["prober"], room_types=[RoomType.RESEARCH], room_states=[])

    def test_room_states_none_accepted(self) -> None:
        obj = AppliesTo(agents=["prober"], room_types=[RoomType.RESEARCH], room_states=None)
        assert obj.room_states is None

    def test_room_states_non_empty_accepted(self) -> None:
        obj = AppliesTo(agents=["prober"], room_types=[RoomType.RESEARCH], room_states=["open"])
        assert obj.room_states == ["open"]

    # §5 multi-position boundary: star-mixing forbidden at any position
    def test_agents_star_with_concrete_id_raises(self) -> None:
        """["*", "prober"] — star first."""
        with pytest.raises(ValidationError, match="cannot be mixed"):
            AppliesTo(agents=["*", "prober"], room_types=[RoomType.RESEARCH])

    def test_agents_concrete_id_with_star_raises(self) -> None:
        """["prober", "*"] — star last."""
        with pytest.raises(ValidationError, match="cannot be mixed"):
            AppliesTo(agents=["prober", "*"], room_types=[RoomType.RESEARCH])

    def test_agents_star_alone_accepted(self) -> None:
        obj = AppliesTo(agents=["*"], room_types=[RoomType.RESEARCH])
        assert obj.agents == ["*"]

    def test_agents_multiple_concrete_accepted(self) -> None:
        obj = AppliesTo(agents=["prober", "skeptic"], room_types=[RoomType.RESEARCH])
        assert obj.agents == ["prober", "skeptic"]


# ---------------------------------------------------------------------------
# Skill — §6
# ---------------------------------------------------------------------------


class TestSkill:
    def test_frozen_raises_on_mutation(self) -> None:
        with pytest.raises(ValidationError):
            _VALID_SKILL.id = "other"  # Pydantic frozen raises ValidationError at runtime

    def test_extra_forbid_raises(self) -> None:
        with pytest.raises(ValidationError):
            Skill(
                id="x",
                category="general",
                applies_to=_VALID_APPLIES_TO,
                priority=50,
                body="body",
                unknown_field="y",  # type: ignore[call-arg]
            )

    def test_priority_below_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            Skill(
                id="x",
                category="general",
                applies_to=_VALID_APPLIES_TO,
                priority=-1,
                body="body",
            )

    def test_priority_above_100_raises(self) -> None:
        with pytest.raises(ValidationError):
            Skill(
                id="x",
                category="general",
                applies_to=_VALID_APPLIES_TO,
                priority=101,
                body="body",
            )

    def test_priority_zero_accepted(self) -> None:
        s = Skill(id="x", category="general", applies_to=_VALID_APPLIES_TO, priority=0, body="body")
        assert s.priority == 0

    def test_priority_100_accepted(self) -> None:
        s = Skill(
            id="x",
            category="general",
            applies_to=_VALID_APPLIES_TO,
            priority=100,
            body="body",
        )
        assert s.priority == 100

    def test_category_invalid_literal_raises(self) -> None:
        with pytest.raises(ValidationError):
            Skill(
                id="x",
                category="invalid-category",  # type: ignore[arg-type]
                applies_to=_VALID_APPLIES_TO,
                priority=50,
                body="body",
            )

    def test_id_empty_raises(self) -> None:
        with pytest.raises(ValidationError):
            Skill(
                id="",
                category="general",
                applies_to=_VALID_APPLIES_TO,
                priority=50,
                body="body",
            )

    def test_body_empty_raises(self) -> None:
        # R0-A-on-plan-4: empty body rejected at schema time.
        with pytest.raises(ValidationError):
            Skill(
                id="x",
                category="general",
                applies_to=_VALID_APPLIES_TO,
                priority=50,
                body="",
            )

    def test_all_categories_accepted(self) -> None:
        for cat in ("general", "engineering", "business"):
            s = Skill(
                id="x",
                category=cat,
                applies_to=_VALID_APPLIES_TO,
                priority=50,
                body="body",
            )
            assert s.category == cat


# ---------------------------------------------------------------------------
# SkillMatchRecord — §6
# ---------------------------------------------------------------------------


class TestSkillMatchRecord:
    def test_frozen_raises_on_mutation(self) -> None:
        with pytest.raises(ValidationError):
            _VALID_MATCH_RECORD.skill_id = "other"  # frozen: raises at runtime

    def test_extra_forbid_raises(self) -> None:
        with pytest.raises(ValidationError):
            SkillMatchRecord(
                skill_id="x",
                rejection_reason="matched",
                extra="y",  # type: ignore[call-arg]
            )

    def test_invalid_rejection_reason_raises(self) -> None:
        with pytest.raises(ValidationError):
            SkillMatchRecord(
                skill_id="x",
                rejection_reason="not_a_valid_reason",  # type: ignore[arg-type]
            )

    def test_all_valid_rejection_reasons_accepted(self) -> None:
        for reason in ("agent_mismatch", "room_type_mismatch", "room_state_mismatch", "matched"):
            rec = SkillMatchRecord(
                skill_id="x",
                rejection_reason=reason,
            )
            assert rec.rejection_reason == reason

    def test_match_derived_from_rejection_reason(self) -> None:
        """No matched: bool field — derive match-ness from rejection_reason == "matched"."""
        matched = SkillMatchRecord(skill_id="x", rejection_reason="matched")
        not_matched = SkillMatchRecord(skill_id="x", rejection_reason="agent_mismatch")
        assert matched.rejection_reason == "matched"
        assert not_matched.rejection_reason != "matched"
        assert not hasattr(matched, "matched"), "matched: bool field must not exist on the model"


# ---------------------------------------------------------------------------
# SkillDecisionTrace — §6
# ---------------------------------------------------------------------------


class TestSkillDecisionTrace:
    def test_frozen_raises_on_mutation(self) -> None:
        with pytest.raises(ValidationError):
            _VALID_TRACE.selected_count = 0  # Pydantic frozen raises ValidationError at runtime

    def test_extra_forbid_raises(self) -> None:
        with pytest.raises(ValidationError):
            SkillDecisionTrace(
                considered=[],
                selected_count=0,
                rejected_count=0,
                extra="y",  # type: ignore[call-arg]
            )

    def test_selected_count_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            SkillDecisionTrace(considered=[], selected_count=-1, rejected_count=0)

    def test_rejected_count_negative_raises(self) -> None:
        with pytest.raises(ValidationError):
            SkillDecisionTrace(considered=[], selected_count=0, rejected_count=-1)

    def test_zero_counts_accepted(self) -> None:
        t = SkillDecisionTrace(considered=[], selected_count=0, rejected_count=0)
        assert t.selected_count == 0
        assert t.rejected_count == 0


# ---------------------------------------------------------------------------
# SkillSelection — §6
# ---------------------------------------------------------------------------


class TestSkillSelection:
    def test_frozen_raises_on_mutation(self) -> None:
        sel = SkillSelection(selected=[_VALID_SKILL], trace=_VALID_TRACE)
        with pytest.raises(ValidationError):
            sel.selected = []  # Pydantic frozen raises ValidationError at runtime

    def test_extra_forbid_raises(self) -> None:
        with pytest.raises(ValidationError):
            SkillSelection(
                selected=[],
                trace=_VALID_TRACE,
                extra="y",  # type: ignore[call-arg]
            )

    def test_empty_selected_accepted(self) -> None:
        empty_trace = SkillDecisionTrace(considered=[], selected_count=0, rejected_count=0)
        sel = SkillSelection(selected=[], trace=empty_trace)
        assert sel.selected == []


# ---------------------------------------------------------------------------
# SkillError — §4 payload
# ---------------------------------------------------------------------------


class TestSkillError:
    def test_path_and_field_populated(self) -> None:
        p = Path("/config/skills/general/test.md")
        err = SkillError("test error", path=p, field="id")
        assert err.path == p
        assert err.field == "id"
        assert "test error" in str(err)

    def test_path_and_field_optional(self) -> None:
        err = SkillError("minimal error")
        assert err.path is None
        assert err.field is None

    def test_is_exception(self) -> None:
        with pytest.raises(SkillError, match="test"):
            raise SkillError("test", path=Path("/x.md"), field="id")
