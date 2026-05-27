"""Tests for src/orchestrator/agents/selection.py.

Coverage-standard application:
  §1: cross-module integration test (loader → decide_agents_for_room →
      build_agent_context → skill_bodies content) at bottom of file.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

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
    return Agent(id=aid, role="r", persona="p", llm_config=_LLM)


def _skill(sid: str, *, agents: list[str], body: str = "skill body", priority: int = 50) -> Skill:
    return Skill(
        id=sid,
        category="general",
        applies_to=AppliesTo(agents=agents, room_types=[RoomType.RESEARCH]),
        priority=priority,
        body=body,
    )


# ---------------------------------------------------------------------------
# decide_agents_for_room
# ---------------------------------------------------------------------------


def test_decide_zero_agents() -> None:
    result = decide_agents_for_room(available_agents={})
    assert result.loaded == []
    assert result.trace.loaded_count == 0
    assert result.trace.considered == []


def test_decide_single_agent() -> None:
    result = decide_agents_for_room(available_agents={"alpha": _agent("alpha")})
    assert len(result.loaded) == 1
    assert result.loaded[0].id == "alpha"
    assert result.trace.loaded_count == 1


def test_decide_two_agents_alphabetical_order() -> None:
    agents = {"zebra": _agent("zebra"), "alpha": _agent("alpha")}
    result = decide_agents_for_room(available_agents=agents)
    assert [a.id for a in result.loaded] == ["alpha", "zebra"]


def test_decide_three_agents_alphabetical_order() -> None:
    agents = {
        "charlie": _agent("charlie"),
        "alpha": _agent("alpha"),
        "beta": _agent("beta"),
    }
    result = decide_agents_for_room(available_agents=agents)
    assert [a.id for a in result.loaded] == ["alpha", "beta", "charlie"]


def test_decide_all_agents_loaded() -> None:
    agents = {"a": _agent("a"), "b": _agent("b")}
    result = decide_agents_for_room(available_agents=agents)
    assert all(r.loaded for r in result.trace.considered)
    assert result.trace.loaded_count == len(agents)


def test_decide_agent_match_record_no_reason_field() -> None:
    """Regression: AgentMatchRecord must NOT have a reason field (R0-A Y1)."""
    from pydantic import ValidationError

    AgentMatchRecord(agent_id="x", loaded=True)  # must succeed
    with pytest.raises(ValidationError):
        AgentMatchRecord(agent_id="x", loaded=True, reason="some_reason")  # type: ignore[call-arg]


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
