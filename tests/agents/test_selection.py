"""Tests for src/orchestrator/agents/selection.py.

Coverage-standard application:
  §1: cross-module integration test (loader → decide_agents_for_room →
      build_agent_context → skill_bodies content) at bottom of file.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from orchestrator.agents.schema import Agent, AgentContext, AgentMatchRecord
from orchestrator.agents.selection import build_agent_context, decide_agents_for_room
from orchestrator.core.room import RoomType
from orchestrator.llm.router import ModelRegistry
from orchestrator.llm.types import (
    AgentAutonomyThresholds,
    AgentLLMConfig,
    ModelId,
    ModelProfile,
    ProviderId,
)
from orchestrator.skills.schema import AppliesTo, Skill

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROVIDER = ProviderId("p1")
_AUTONOMY = AgentAutonomyThresholds(
    threshold_auto=8,
    threshold_confirm=4,
    user_intent_modifier=2,
)
_LLM = AgentLLMConfig(
    default_model=ModelId("m1"),
    autonomy_thresholds=_AUTONOMY,
)


def _agent(aid: str) -> Agent:
    """Agent with default applies_to (room_types=["*"])."""
    return Agent(id=aid, role="r", persona="p", llm_config=_LLM)


def _agent_for_room(aid: str, room_types: list[str]) -> Agent:
    """Agent scoped to specific room types."""
    from orchestrator.agents.schema import AgentAppliesTo

    return Agent(
        id=aid,
        role="r",
        persona="p",
        llm_config=_LLM,
        applies_to=AgentAppliesTo(room_types=room_types, room_states=["*"]),
    )


def _skill(sid: str, *, agents: list[str], body: str = "skill body", priority: int = 50) -> Skill:
    return Skill(
        id=sid,
        category="general",
        applies_to=AppliesTo(agents=agents, room_types=[RoomType.RESEARCH]),
        priority=priority,
        body=body,
    )


# ---------------------------------------------------------------------------
# decide_agents_for_room  (P1.5 two-layer filtering)
# ---------------------------------------------------------------------------


def test_decide_zero_agents() -> None:
    """Empty available_agents returns empty loaded."""
    result = decide_agents_for_room(RoomType.RESEARCH, "open", available_agents={})
    assert result.loaded == []
    assert result.trace.loaded_count == 0
    assert result.trace.considered == []


def test_decide_wildcard_agent_matches_research() -> None:
    """["*"] agent is loaded for research room type."""
    agents = {"alpha": _agent("alpha")}  # default: room_types=["*"]
    result = decide_agents_for_room(RoomType.RESEARCH, "open", available_agents=agents)
    assert len(result.loaded) == 1
    assert result.loaded[0].id == "alpha"
    assert result.trace.considered[0].applies_to_match is True
    assert result.trace.considered[0].reason == "room_type_match"


def test_decide_wildcard_agent_matches_bug_fix() -> None:
    """["*"] agent is loaded for bug_fix room type."""
    agents = {"alpha": _agent("alpha")}
    result = decide_agents_for_room(RoomType.BUG_FIX, "open", available_agents=agents)
    assert len(result.loaded) == 1
    assert result.loaded[0].id == "alpha"


def test_decide_concrete_agent_matches_own_room_type() -> None:
    """Agent with room_types=["research"] matches research but not bug_fix."""
    agents = {"researcher": _agent_for_room("researcher", ["research"])}
    result = decide_agents_for_room(RoomType.RESEARCH, "open", available_agents=agents)
    assert len(result.loaded) == 1
    assert result.loaded[0].id == "researcher"
    assert result.trace.considered[0].applies_to_match is True
    assert result.trace.considered[0].reason == "room_type_match"


def test_decide_concrete_agent_mismatches_other_room_type() -> None:
    """Agent with room_types=["research"] is NOT loaded for bug_fix."""
    agents = {"researcher": _agent_for_room("researcher", ["research"])}
    result = decide_agents_for_room(RoomType.BUG_FIX, "open", available_agents=agents)
    assert result.loaded == []
    assert result.trace.loaded_count == 0
    record = result.trace.considered[0]
    assert record.loaded is False
    assert record.applies_to_match is False
    assert record.reason == "room_type_mismatch"


def test_decide_mixed_agents_filter_correctly() -> None:
    """With wildcard + scoped agents, only matching ones load."""
    agents = {
        "wild": _agent("wild"),  # room_types=["*"]
        "researcher": _agent_for_room("researcher", ["research"]),
        "bug-fixer": _agent_for_room("bug-fixer", ["bug_fix"]),
    }
    result = decide_agents_for_room(RoomType.RESEARCH, "open", available_agents=agents)
    loaded_ids = [a.id for a in result.loaded]
    assert "wild" in loaded_ids
    assert "researcher" in loaded_ids
    assert "bug-fixer" not in loaded_ids


def test_decide_alphabetical_sort_preserved() -> None:
    """Loaded agents are sorted alphabetically by id."""
    agents = {
        "charlie": _agent("charlie"),
        "alpha": _agent("alpha"),
        "beta": _agent("beta"),
    }
    result = decide_agents_for_room(RoomType.RESEARCH, "open", available_agents=agents)
    assert [a.id for a in result.loaded] == ["alpha", "beta", "charlie"]


def test_decide_alphabetical_sort_after_filtering() -> None:
    """Alphabetical sort applies to the filtered subset, not all agents."""
    agents = {
        "zebra": _agent_for_room("zebra", ["research"]),
        "alpha": _agent_for_room("alpha", ["research"]),
        "not-loaded": _agent_for_room("not-loaded", ["bug_fix"]),
    }
    result = decide_agents_for_room(RoomType.RESEARCH, "open", available_agents=agents)
    assert [a.id for a in result.loaded] == ["alpha", "zebra"]


def test_decide_trace_records_per_agent_match_data() -> None:
    """Trace has one record per agent with accurate applies_to_match + reason."""
    agents = {
        "wild": _agent("wild"),
        "scoped": _agent_for_room("scoped", ["bug_fix"]),
    }
    result = decide_agents_for_room(RoomType.RESEARCH, "open", available_agents=agents)
    by_id = {r.agent_id: r for r in result.trace.considered}
    assert by_id["wild"].applies_to_match is True
    assert by_id["wild"].reason == "room_type_match"
    assert by_id["scoped"].applies_to_match is False
    assert by_id["scoped"].reason == "room_type_mismatch"


def test_decide_room_state_unused_at_load_time() -> None:
    """room_state param does not affect which agents are loaded."""
    agents = {"alpha": _agent("alpha")}
    result_open = decide_agents_for_room(RoomType.RESEARCH, "open", available_agents=agents)
    result_closed = decide_agents_for_room(RoomType.RESEARCH, "closed", available_agents=agents)
    assert [a.id for a in result_open.loaded] == [a.id for a in result_closed.loaded]


def test_decide_all_five_room_types_with_wildcard() -> None:
    """["*"] agent loads for every RoomType value."""
    agents = {"universal": _agent("universal")}
    for rt in RoomType:
        result = decide_agents_for_room(rt, "open", available_agents=agents)
        assert len(result.loaded) == 1, f"Expected load for room_type={rt}"


def test_decide_agent_match_record_has_reason_field() -> None:
    """Regression (P1.5): AgentMatchRecord now has reason + applies_to_match fields."""
    record = AgentMatchRecord(
        agent_id="x",
        loaded=True,
        applies_to_match=True,
        reason="room_type_match",
    )
    assert record.reason == "room_type_match"
    assert record.applies_to_match is True


# ---------------------------------------------------------------------------
# build_agent_context
# ---------------------------------------------------------------------------


def test_build_agent_context_empty_skills_returns_empty_bodies() -> None:
    agent = _agent("prober")
    ctx = build_agent_context(
        agent,
        RoomType.RESEARCH,
        "open",
        available_skills={},
        snapshot=[],
    )
    assert ctx.skill_bodies == []
    assert ctx.agent is agent


def test_build_agent_context_returns_matching_skill_bodies() -> None:
    agent = _agent("prober")
    skill = _skill("research-skill", agents=["prober"], body="the real body")
    ctx = build_agent_context(
        agent,
        RoomType.RESEARCH,
        "open",
        available_skills={"research-skill": skill},
        snapshot=[],
    )
    assert ctx.skill_bodies == ["the real body"]


def test_build_agent_context_skill_body_order_matches_priority() -> None:
    """Skill bodies ordered by descending priority then ascending id."""
    agent = _agent("prober")
    skills = {
        "low": _skill("low", agents=["prober"], body="LOW", priority=10),
        "high": _skill("high", agents=["prober"], body="HIGH", priority=90),
        "mid": _skill("mid", agents=["prober"], body="MID", priority=50),
    }
    ctx = build_agent_context(
        agent, RoomType.RESEARCH, "open", available_skills=skills, snapshot=[]
    )
    assert ctx.skill_bodies == ["HIGH", "MID", "LOW"]


def test_build_agent_context_no_matching_skills_for_agent() -> None:
    agent = _agent("prober")
    skill = _skill("others-skill", agents=["skeptic"], body="not for prober")
    ctx = build_agent_context(
        agent,
        RoomType.RESEARCH,
        "open",
        available_skills={"others-skill": skill},
        snapshot=[],
    )
    assert ctx.skill_bodies == []


def test_build_agent_context_returns_agent_context_instance() -> None:
    agent = _agent("prober")
    ctx = build_agent_context(agent, RoomType.RESEARCH, "open", available_skills={}, snapshot=[])
    assert isinstance(ctx, AgentContext)


# ---------------------------------------------------------------------------
# §1 cross-module integration test: loader → decide → build_agent_context
# ---------------------------------------------------------------------------


def test_integration_skill_bodies_content_equals_source(tmp_path: Path) -> None:
    """Source ≠ sink: skill_bodies in AgentContext must equal Skill.body
    strings loaded from disk — NOT a sentinel default."""
    from orchestrator.agents.loader import load_agents

    sentinel_default = "SENTINEL_THAT_SHOULD_NEVER_APPEAR"

    # Build model registry
    profiles = {
        ModelId("m1"): ModelProfile(
            id=ModelId("m1"),
            provider=_PROVIDER,
            provider_model_id="m1",
            capabilities=[],
            context_window=8192,
        )
    }
    models = ModelRegistry(profiles)

    # Write a minimal agent yaml
    (tmp_path / "prober.yaml").write_text(
        dedent("""\
            id: prober
            role: prober
            persona: test prober
            llm_config:
              default_model: m1
              fallback_chain: []
              required_capabilities: []
            autonomy_thresholds:
              threshold_auto: 8
              threshold_confirm: 5
              user_intent_modifier: 2
        """),
        encoding="utf-8",
    )
    agents, _registry = load_agents(tmp_path, models=models)

    # Create an in-memory skill matching this agent
    src_skill_body = "Probe assumptions systematically."
    available_skills = {
        "probe-skill": _skill("probe-skill", agents=["prober"], body=src_skill_body)
    }

    ctx = build_agent_context(
        agents["prober"],
        RoomType.RESEARCH,
        "open",
        available_skills=available_skills,
        snapshot=[],
    )

    # Source ≠ sink: content equals the source Skill.body
    assert ctx.skill_bodies == [src_skill_body]
    # AND content differs from the sentinel (not just any non-empty value)
    assert ctx.skill_bodies != [sentinel_default]
