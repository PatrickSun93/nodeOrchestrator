"""Plugin loader — discover, validate, collision-check, load, and merge (ADR-029 D2).

Security-load-bearing step order (R0-B R1; collision-check before any import):
  1. Discover  — iterate plugins/ subdirs; each with plugin.yaml is a candidate.
  2. Validate  — parse+validate manifest (frozen/extra="forbid"/schema_version);
                 check dependencies. A failure → refuse that plugin, log, continue.
  3. Collision — check ALL declared names (roles/skills/tools/tool_impls/mcp_servers)
                 against host registries and cross-plugin. Fail-closed on any clash.
  4. Non-code  — reuse existing loaders on plugin subpaths (P3.5-3).
  5. Code      — importlib load tool_impls ONLY after steps 2-3 cleared (P3.5-4).
  6. Rev-cap   — cap plugin-asserted reversibility (host-authoritative-or-default-0).
  7. Merge     — atomically per-plugin; any-stage failure discards the whole intermediate.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import ValidationError

from orchestrator.agents.schema import Agent
from orchestrator.autonomy.scoring import ToolMeta
from orchestrator.llm.router import ModelRegistry
from orchestrator.plugins.schema import PLUGIN_HOST_CONTRACT_VERSION, PluginManifest
from orchestrator.skills.schema import Skill
from orchestrator.tools.executor import LocalToolFn

if TYPE_CHECKING:
    from orchestrator.mcp.client import MCPSession

_log = logging.getLogger("orchestrator.plugins.loader")

# Re-export so callers only need to import from plugins.loader.
__all__ = ["PluginLoadResult", "load_plugins"]

# Suppress "imported but unused" for the re-export.
_ = PLUGIN_HOST_CONTRACT_VERSION


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class PluginLoadResult:
    """Merged contributions from all successfully-loaded plugins.

    Used both as the per-plugin intermediate (built up during loading) and
    as the return type of load_plugins() (the aggregation of all valid plugins).
    Never partially-filled: a plugin either contributes its full intermediate
    or nothing (atomic merge, HR#5 / R0-B Y4).
    """

    agents: dict[str, Agent] = dataclasses.field(default_factory=dict)
    regex_registry: dict[tuple[str, int], re.Pattern[str]] = dataclasses.field(default_factory=dict)
    skills: dict[str, Skill] = dataclasses.field(default_factory=dict)
    tools: dict[str, ToolMeta] = dataclasses.field(default_factory=dict)
    local_tools: dict[str, LocalToolFn] = dataclasses.field(default_factory=dict)
    mcp_sessions: dict[str, MCPSession] = dataclasses.field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal: validated candidate (output of steps 1-2)
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _ValidatedCandidate:
    plugin_id: str
    plugin_dir: Path
    manifest: PluginManifest


# ---------------------------------------------------------------------------
# Steps 1-2: Discover + validate + dependency-check (P3.5-2)
# ---------------------------------------------------------------------------


def _discover_and_validate(
    plugins_dir: Path,
    models: ModelRegistry,
    host_room_types: frozenset[str],
    host_contract_version: int,
) -> list[_ValidatedCandidate]:
    """Iterate plugin subdirs; parse, validate, and dependency-check each manifest.

    Returns only the candidates that passed all checks. Per-plugin isolation:
    a bad manifest never crashes the bootstrap or refuses a valid sibling.
    """
    candidates: list[_ValidatedCandidate] = []

    for subdir in sorted(plugins_dir.iterdir()):  # sorted → deterministic load order
        if not subdir.is_dir():
            continue
        manifest_path = subdir / "plugin.yaml"
        if not manifest_path.exists():
            _log.debug("plugins: skipping %s — no plugin.yaml", subdir.name)
            continue

        plugin_id = subdir.name

        # Parse YAML
        try:
            raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            _log.warning("plugin %r: cannot parse plugin.yaml: %s — refusing", plugin_id, exc)
            continue

        if not isinstance(raw, dict):
            _log.warning("plugin %r: plugin.yaml is not a mapping — refusing", plugin_id)
            continue

        # Validate manifest (schema_version gated + extra="forbid")
        try:
            manifest = PluginManifest(**raw)
        except ValidationError as exc:
            _log.warning("plugin %r: manifest validation failed: %s — refusing", plugin_id, exc)
            continue

        # id must match directory name
        if manifest.id != plugin_id:
            _log.warning(
                "plugin %r: manifest id %r does not match directory name — refusing",
                plugin_id,
                manifest.id,
            )
            continue

        # Dependency: min_host_contract
        if manifest.dependencies.min_host_contract > host_contract_version:
            _log.warning(
                "plugin %r: requires host contract %d but host is %d — refusing",
                plugin_id,
                manifest.dependencies.min_host_contract,
                host_contract_version,
            )
            continue

        # Dependency: model_ids
        missing_models = [
            mid
            for mid in manifest.dependencies.model_ids
            if models.get(mid) is None  # type: ignore[arg-type]
        ]
        if missing_models:
            _log.warning(
                "plugin %r: unmet model_id dependencies %s — refusing",
                plugin_id,
                missing_models,
            )
            continue

        # Dependency: room_types
        missing_rooms = [rt for rt in manifest.dependencies.room_types if rt not in host_room_types]
        if missing_rooms:
            _log.warning(
                "plugin %r: unmet room_type dependencies %s — refusing",
                plugin_id,
                missing_rooms,
            )
            continue

        candidates.append(_ValidatedCandidate(plugin_id, subdir, manifest))
        _log.debug("plugin %r: manifest valid, candidate for loading", plugin_id)

    return candidates


# ---------------------------------------------------------------------------
# Public API (P3.5-2 stub — extended in P3.5-3 and P3.5-4)
# ---------------------------------------------------------------------------


def load_plugins(
    plugins_dir: Path,
    *,
    models: ModelRegistry,
    host_room_types: frozenset[str],
    host_contract_version: int,
    host_agents: dict[str, Agent],
    host_skills: dict[str, Skill],
    host_tools: dict[str, ToolMeta],
    host_local_tool_names: frozenset[str],
    host_mcp_server_names: frozenset[str],
) -> PluginLoadResult:
    """Discover, validate, and merge plugin contributions (ADR-029 D2).

    Absent plugins/ dir → no-op (clean boot). Per-plugin load isolation:
    a failure at ANY stage refuses that plugin without crashing bootstrap
    or refusing valid siblings. Host registries are never mutated by a
    partially-loaded plugin (atomic-merge guarantee, HR#5 / R0-B Y4).
    """
    if not plugins_dir.exists():
        return PluginLoadResult()

    # Steps 1-2: Discover + validate + dependency-check
    _discover_and_validate(plugins_dir, models, host_room_types, host_contract_version)

    # Steps 3-7 implemented in P3.5-3 (collision-check + non-code loaders + rev-cap)
    # and P3.5-4 (code loading).
    # Unused params accepted now; used in P3.5-3 extension:
    _ = host_agents, host_skills, host_tools, host_local_tool_names, host_mcp_server_names
    return PluginLoadResult()
