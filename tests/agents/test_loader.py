"""Tests for src/orchestrator/agents/loader.py.

Covers: happy paths, error paths, and §3/§4 categories per
test-coverage-standard.md.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from orchestrator.agents.exceptions import AgentLoadError, SpeakingTriggerError
from orchestrator.agents.loader import load_agents
from orchestrator.llm.router import ModelRegistry
from orchestrator.llm.types import (
    Capability,
    ModelId,
    ModelProfile,
    ProviderId,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROVIDER = ProviderId("p1")


def _make_registry(*model_ids: str, capabilities: list[Capability] | None = None) -> ModelRegistry:
    caps = capabilities or []
    profiles = {
        ModelId(mid): ModelProfile(
            id=ModelId(mid),
            provider=_PROVIDER,
            provider_model_id=mid,
            capabilities=caps,
            context_window=8192,
        )
        for mid in model_ids
    }
    return ModelRegistry(profiles)


_MODELS = _make_registry("m1", "m2")

_MINIMAL_YAML = dedent("""\
    id: {stem}
    role: r
    persona: p
    llm_config:
      default_model: m1
      fallback_chain: []
      required_capabilities: []
    autonomy_thresholds:
      threshold_auto: 8
      threshold_confirm: 5
      user_intent_modifier: 2
""")

_REGEX_TRIGGER_YAML = dedent("""\
    id: {stem}
    role: r
    persona: p
    speaking_triggers:
      - type: regex
        pattern: "hello"
    llm_config:
      default_model: m1
      fallback_chain: []
      required_capabilities: []
    autonomy_thresholds:
      threshold_auto: 8
      threshold_confirm: 5
      user_intent_modifier: 2
""")

_ALL_TRIGGERS_YAML = dedent("""\
    id: {stem}
    role: r
    persona: p
    speaking_triggers:
      - type: regex
        pattern: "hello"
      - type: event_type
        event_type: hypothesis
      - type: state_change
        target_state: research
    llm_config:
      default_model: m1
      fallback_chain: []
      required_capabilities: []
    autonomy_thresholds:
      threshold_auto: 8
      threshold_confirm: 5
      user_intent_modifier: 2
""")


def _write(directory: Path, stem: str, template: str = _MINIMAL_YAML) -> Path:
    path = directory / f"{stem}.yaml"
    path.write_text(template.format(stem=stem), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_load_single_agent(tmp_path: Path) -> None:
    _write(tmp_path, "alpha")
    agents, _registry = load_agents(tmp_path, models=_MODELS)
    assert set(agents.keys()) == {"alpha"}
    assert agents["alpha"].id == "alpha"


def test_load_two_agents(tmp_path: Path) -> None:
    _write(tmp_path, "alpha")
    _write(tmp_path, "beta")
    agents, _registry = load_agents(tmp_path, models=_MODELS)
    assert set(agents.keys()) == {"alpha", "beta"}


def test_load_empty_directory(tmp_path: Path) -> None:
    agents, registry = load_agents(tmp_path, models=_MODELS)
    assert agents == {}
    assert registry == {}


def test_load_agent_with_empty_speaking_triggers(tmp_path: Path) -> None:
    _write(tmp_path, "notrig")
    agents, registry = load_agents(tmp_path, models=_MODELS)
    assert agents["notrig"].speaking_triggers == []
    assert registry == {}


def test_load_agent_with_all_trigger_types(tmp_path: Path) -> None:
    _write(tmp_path, "multi", _ALL_TRIGGERS_YAML)
    agents, registry = load_agents(tmp_path, models=_MODELS)
    assert len(agents["multi"].speaking_triggers) == 3
    assert ("multi", 0) in registry


def test_load_regex_trigger_compiles_at_load(tmp_path: Path) -> None:
    _write(tmp_path, "re", _REGEX_TRIGGER_YAML)
    _agents, registry = load_agents(tmp_path, models=_MODELS)
    assert ("re", 0) in registry
    # Pattern is a compiled re.Pattern (verify by searching)
    assert registry[("re", 0)].search("say hello world") is not None


def test_load_registry_key_uses_agent_id_and_index(tmp_path: Path) -> None:
    _write(tmp_path, "rekey", _REGEX_TRIGGER_YAML)
    _, registry = load_agents(tmp_path, models=_MODELS)
    assert ("rekey", 0) in registry


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_missing_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(AgentLoadError, match="does not exist"):
        load_agents(tmp_path / "nonexistent", models=_MODELS)


def test_malformed_yaml_raises_with_path(tmp_path: Path) -> None:
    (tmp_path / "bad.yaml").write_text("{ invalid: yaml: content: :", encoding="utf-8")
    with pytest.raises(AgentLoadError):
        load_agents(tmp_path, models=_MODELS)


def test_filename_id_mismatch_raises(tmp_path: Path) -> None:
    yaml_content = _MINIMAL_YAML.format(stem="other_id")
    (tmp_path / "myfile.yaml").write_text(yaml_content, encoding="utf-8")
    with pytest.raises(AgentLoadError) as exc_info:
        load_agents(tmp_path, models=_MODELS)
    assert exc_info.value.field == "id"


def test_duplicate_id_raises(tmp_path: Path) -> None:
    """Duplicate detection fires when two `_load_one` calls populate the same id.

    The filesystem never produces two files with the same stem (guaranteeing
    uniqueness through the id==stem rule).  This test exercises the guard
    directly via the internal `_load_one` helper to prove it is reachable
    and raises correctly.
    """
    import re as _re

    from orchestrator.agents.loader import _load_one
    from orchestrator.agents.schema import Agent

    yaml_path = _write(tmp_path, "dup")
    agents: dict[str, Agent] = {}
    registry: dict[tuple[str, int], _re.Pattern[str]] = {}

    # First load succeeds
    _load_one(yaml_path, "dup", _MODELS, agents, registry)
    assert "dup" in agents

    # Second call for the same id must raise
    with pytest.raises(AgentLoadError) as exc_info:
        _load_one(yaml_path, "dup", _MODELS, agents, registry)
    assert exc_info.value.field == "id"


def test_invalid_trigger_type_raises(tmp_path: Path) -> None:
    bad_yaml = dedent("""\
        id: badtrig
        role: r
        persona: p
        speaking_triggers:
          - type: unknown_trigger_type
            extra_field: value
        llm_config:
          default_model: m1
          fallback_chain: []
          required_capabilities: []
        autonomy_thresholds:
          threshold_auto: 8
          threshold_confirm: 5
          user_intent_modifier: 2
    """)
    (tmp_path / "badtrig.yaml").write_text(bad_yaml, encoding="utf-8")
    with pytest.raises(AgentLoadError):
        load_agents(tmp_path, models=_MODELS)


def test_bad_regex_pattern_raises_at_load_not_dispatch(tmp_path: Path) -> None:
    """Regex compile error must surface at load time, not at first dispatch."""
    bad_regex_yaml = dedent("""\
        id: badregex
        role: r
        persona: p
        speaking_triggers:
          - type: regex
            pattern: "[invalid"
        llm_config:
          default_model: m1
          fallback_chain: []
          required_capabilities: []
        autonomy_thresholds:
          threshold_auto: 8
          threshold_confirm: 5
          user_intent_modifier: 2
    """)
    (tmp_path / "badregex.yaml").write_text(bad_regex_yaml, encoding="utf-8")
    with pytest.raises(SpeakingTriggerError) as exc_info:
        load_agents(tmp_path, models=_MODELS)
    assert exc_info.value.agent_id == "badregex"
    assert exc_info.value.trigger_index == 0


def test_missing_required_capability_raises(tmp_path: Path) -> None:
    """Agent requiring a capability that no model in its chain supports."""
    cap_yaml = dedent("""\
        id: capagent
        role: r
        persona: p
        llm_config:
          default_model: m1
          fallback_chain: []
          required_capabilities:
            - tools
        autonomy_thresholds:
          threshold_auto: 8
          threshold_confirm: 5
          user_intent_modifier: 2
    """)
    (tmp_path / "capagent.yaml").write_text(cap_yaml, encoding="utf-8")
    # _MODELS has models with no capabilities; "tools" is not satisfied
    with pytest.raises(AgentLoadError) as exc_info:
        load_agents(tmp_path, models=_MODELS)
    assert exc_info.value.agent_id == "capagent"


def test_required_capability_satisfied_succeeds(tmp_path: Path) -> None:
    """Agent with required_capabilities=[tools] succeeds when model has tools."""
    models_with_tools = _make_registry("m1", capabilities=[Capability.TOOLS])
    cap_yaml = dedent("""\
        id: toolagent
        role: r
        persona: p
        llm_config:
          default_model: m1
          fallback_chain: []
          required_capabilities:
            - tools
        autonomy_thresholds:
          threshold_auto: 8
          threshold_confirm: 5
          user_intent_modifier: 2
    """)
    (tmp_path / "toolagent.yaml").write_text(cap_yaml, encoding="utf-8")
    agents, _ = load_agents(tmp_path, models=models_with_tools)
    assert "toolagent" in agents


def test_model_not_in_registry_raises(tmp_path: Path) -> None:
    """Agent referencing a model not in ModelRegistry raises at load."""
    no_models = ModelRegistry({})
    _write(tmp_path, "x")
    with pytest.raises(AgentLoadError):
        load_agents(tmp_path, models=no_models)


# ---------------------------------------------------------------------------
# Integration: all 5 canonical agents load
# ---------------------------------------------------------------------------

_CANONICAL_DIR = Path(__file__).parent.parent.parent / "config" / "agents"


_FULL_REGISTRY_CAPS: dict[str, list[Capability]] = {
    "deepseek_v4_flash": [Capability.TOOLS],
    "qwen_mlx_30b": [Capability.TOOLS],
    "claude_code_opus_47": [Capability.EFFORT],
    "claude_code_sonnet_46": [Capability.EFFORT],
    "claude_code_haiku_45": [],
    "deepseek_v4_pro": [],
}


def _make_full_registry() -> ModelRegistry:
    """Registry covering all model IDs used by the 5 canonical agents."""
    profiles = {
        ModelId(mid): ModelProfile(
            id=ModelId(mid),
            provider=_PROVIDER,
            provider_model_id=mid,
            capabilities=_FULL_REGISTRY_CAPS.get(mid, []),
            context_window=8192,
        )
        for mid in _FULL_REGISTRY_CAPS
    }
    return ModelRegistry(profiles)


def test_all_canonical_agents_load() -> None:
    """All canonical agents load without error (includes synthesizer, P3.7-content-1)."""
    registry = _make_full_registry()
    agents, _reg = load_agents(_CANONICAL_DIR, models=registry)
    expected = {
        "divergence_mapper",
        "facilitator",
        "logger",
        "operator",
        "planner",
        "prober",
        "skeptic",
        "synthesizer",
        "verifier",
    }
    assert set(agents) == expected
