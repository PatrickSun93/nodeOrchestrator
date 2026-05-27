"""Agent loader: discovers and validates agent yaml files.

Returns a ``(agents, regex_registry)`` pair.  The registry caches
compiled ``RegexTrigger.pattern`` objects keyed by
``(agent_id, trigger_index)`` so ``should_agent_speak`` never
re-compiles at dispatch time.

Load-time validation (ADR-010 Decision 6):
- YAML parse.
- Filename-stem == ``id`` (ADR-009 D8 extension to agent yamls).
- Duplicate-id detection.
- Pydantic model validation (discriminated-union triggers).
- RegexTrigger pattern compile.
- ``required_capabilities`` satisfied by ≥1 model in the agent's
  fallback chain.

Uses ``load_agent_llm_config`` from ``orchestrator.llm.config_loader``
to compose the ``llm_config`` + ``autonomy_thresholds`` sibling-keys
into one ``AgentLLMConfig`` object (drift D1 resolution β per
pre-impl-spec 2026-05-27).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from orchestrator.agents.exceptions import AgentLoadError, SpeakingTriggerError
from orchestrator.agents.schema import Agent, RegexTrigger
from orchestrator.llm.config_loader import load_agent_llm_config
from orchestrator.llm.exceptions import ConfigError
from orchestrator.llm.router import ModelRegistry


def load_agents(
    directory: Path,
    *,
    models: ModelRegistry,
) -> tuple[dict[str, Agent], dict[tuple[str, int], re.Pattern[str]]]:
    """Discover and validate all ``*.yaml`` agent files in ``directory``.

    Returns a ``(agents, regex_registry)`` pair:
    - ``agents``: ``dict[str, Agent]`` keyed by ``Agent.id``.
    - ``regex_registry``: ``dict[(agent_id, trigger_index), re.Pattern[str]]``
      populated for every ``RegexTrigger`` in every loaded agent.

    Raises:
        AgentLoadError: missing directory, malformed yaml, filename/id
            mismatch, duplicate id, schema validation failure, or
            required_capability unsatisfied.
        SpeakingTriggerError: ``RegexTrigger.pattern`` does not compile.
    """
    if not directory.exists():
        raise AgentLoadError(
            f"agents directory does not exist: {directory}",
        )

    agents: dict[str, Agent] = {}
    regex_registry: dict[tuple[str, int], re.Pattern[str]] = {}

    for yaml_path in sorted(directory.glob("*.yaml")):
        file_stem = yaml_path.stem
        _load_one(yaml_path, file_stem, models, agents, regex_registry)

    return agents, regex_registry


def _load_one(
    yaml_path: Path,
    file_stem: str,
    models: ModelRegistry,
    agents: dict[str, Agent],
    regex_registry: dict[tuple[str, int], re.Pattern[str]],
) -> None:
    """Load and validate one agent yaml file; mutates ``agents`` and
    ``regex_registry`` in-place."""

    # 1. Parse raw yaml
    raw = _parse_yaml(yaml_path, file_stem)

    # 2. Load llm_config (handles autonomy_thresholds sibling-key; ADR-010 D1β)
    try:
        llm_config = load_agent_llm_config(yaml_path, models)
    except ConfigError as exc:
        raise AgentLoadError(str(exc), agent_id=file_stem) from exc

    # 3. Validate filename stem == id
    agent_id = _validate_id(raw, yaml_path, file_stem)

    # 4. Duplicate-id detection
    if agent_id in agents:
        raise AgentLoadError(
            f"duplicate agent id {agent_id!r} — found again in {yaml_path}",
            agent_id=agent_id,
            field="id",
        )

    # 5. Construct Agent (speaking_triggers parsed via Pydantic discriminated union)
    agent_data: dict[str, Any] = {
        k: v for k, v in raw.items() if k not in ("llm_config", "autonomy_thresholds")
    }
    agent_data["llm_config"] = llm_config

    try:
        agent = Agent.model_validate(agent_data)
    except ValidationError as exc:
        raise AgentLoadError(
            f"{yaml_path}: agent validation failed — {exc}",
            agent_id=agent_id,
        ) from exc

    # 6. Compile regex triggers into registry (ADR-010 D6)
    for i, trigger in enumerate(agent.speaking_triggers):
        if isinstance(trigger, RegexTrigger):
            try:
                regex_registry[(agent_id, i)] = re.compile(trigger.pattern)
            except re.error as exc:
                raise SpeakingTriggerError(
                    f"{yaml_path}: speaking_trigger[{i}] pattern "
                    f"{trigger.pattern!r} failed to compile: {exc}",
                    agent_id=agent_id,
                    trigger_index=i,
                ) from exc

    # 7. Validate required_capabilities against models
    _validate_required_capabilities(agent, yaml_path, agent_id, models)

    agents[agent_id] = agent


def _parse_yaml(yaml_path: Path, file_stem: str) -> dict[str, Any]:
    """Read and parse one yaml file; raise AgentLoadError on failure."""
    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise AgentLoadError(
            f"yaml parse error in {yaml_path}: {exc}",
            agent_id=file_stem,
        ) from exc
    if not isinstance(raw, dict):
        raise AgentLoadError(
            f"{yaml_path}: top-level must be a mapping, got {type(raw).__name__}",
            agent_id=file_stem,
        )
    return raw


def _validate_id(raw: dict[str, Any], yaml_path: Path, file_stem: str) -> str:
    """Validate that the ``id`` field matches the filename stem."""
    agent_id = raw.get("id")
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise AgentLoadError(
            f"{yaml_path}: 'id' field is missing or empty",
            agent_id=file_stem,
            field="id",
        )
    if agent_id != file_stem:
        raise AgentLoadError(
            f"{yaml_path}: filename stem {file_stem!r} does not match "
            f"agent id {agent_id!r} (ADR-009 D8 extension to agents)",
            agent_id=agent_id,
            field="id",
        )
    return agent_id


def _validate_required_capabilities(
    agent: Agent,
    yaml_path: Path,
    agent_id: str,
    models: ModelRegistry,
) -> None:
    """Fail fast if any required capability has zero satisfying models."""
    model_chain = [agent.llm_config.default_model, *agent.llm_config.fallback_chain]
    for cap in agent.llm_config.required_capabilities:
        satisfying = [
            mid
            for mid in model_chain
            if (profile := models.get(mid)) is not None and cap in profile.capabilities
        ]
        if not satisfying:
            raise AgentLoadError(
                f"{yaml_path}: required capability {cap!r} not satisfied by any "
                f"model in fallback chain {model_chain}",
                agent_id=agent_id,
            )
