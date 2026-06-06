"""Plugin loader — discover, validate, collision-check, load, and merge (ADR-029 D2).

Security-load-bearing step order (R0-B R1; collision-check before any import):
  1. Discover  — iterate plugins/ subdirs; each with plugin.yaml is a candidate.
  2. Validate  — parse+validate manifest (frozen/extra="forbid"/schema_version);
                 check dependencies. A failure → refuse that plugin, log, continue.
  3. Collision — check ALL declared names (roles/skills/tools/tool_impls/mcp_servers)
                 against host registries and cross-plugin. Fail-closed on any clash.
  4. Non-code  — reuse existing loaders on plugin subpaths (no reimplementation).
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

from orchestrator.agents.loader import load_agents
from orchestrator.agents.schema import Agent
from orchestrator.autonomy.scoring import ToolMeta
from orchestrator.llm.config_loader import load_tools_config
from orchestrator.llm.exceptions import ConfigError
from orchestrator.llm.router import ModelRegistry
from orchestrator.plugins.provenance import (
    ActivationEntry,
    ActivationRegistry,
    PluginProvenance,
    PluginRegistry,
    RegistryEntry,
    _RegistryRefuseAll,
    check_fetched_activation,
    load_activation_registry,
)
from orchestrator.plugins.schema import PluginManifest
from orchestrator.skills.loader import load_skills
from orchestrator.skills.schema import Skill
from orchestrator.tools.executor import LocalToolFn

if TYPE_CHECKING:
    from orchestrator.mcp.client import MCPSession
    from orchestrator.sandbox.posture import PostureResolver

_log = logging.getLogger("orchestrator.plugins.loader")

__all__ = ["PluginLoadResult", "load_plugins"]


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
    provenance: PluginProvenance = "operator_placed"


# ---------------------------------------------------------------------------
# Steps 1-2: Discover + validate + dependency-check (P3.5-2)
# ---------------------------------------------------------------------------


def _discover_and_validate(
    plugins_dir: Path,
    models: ModelRegistry,
    host_room_types: frozenset[str],
    host_contract_version: int,
    provenance: PluginProvenance = "operator_placed",
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

        candidates.append(_ValidatedCandidate(plugin_id, subdir, manifest, provenance))
        _log.debug(
            "plugin %r: manifest valid, candidate for loading (provenance=%s)",
            plugin_id,
            provenance,
        )

    return candidates


# ---------------------------------------------------------------------------
# Step 3: Collision-check ALL declared names BEFORE any import (P3.5-3)
# ---------------------------------------------------------------------------


def _collision_check(
    candidate: _ValidatedCandidate,
    host_agents: dict[str, Agent],
    host_skills: dict[str, Skill],
    host_tools: dict[str, ToolMeta],
    host_local_tool_names: frozenset[str],
    host_mcp_server_names: frozenset[str],
) -> bool:
    """Check host-collision (bare name, fail-closed) and within-plugin duplicates.

    Cross-plugin collision is resolved by deterministic always-prefix namespacing
    (<plugin_id>__<name>, ADR-038 D4) — no refusal for cross-plugin duplicates.

    Host-collision and within-plugin dup checks evaluate the BARE declared name
    (absorbed R0-A Y4 / R0-B b1; ADR-038 D4 order-of-operations):
      - A plugin tool_impl shadowing a host local_tool (shadow-bypass) → refused
        on the bare name even though namespacing would de-conflict it.
      - Within-plugin duplicate names → refused.

    Returns True (pass) or False (refused). Runs BEFORE any importlib call.
    """
    pid = candidate.plugin_id
    c = candidate.manifest.contributions

    # Role ids: host-collision + within-plugin dup (bare name)
    _plugin_roles: set[str] = set()
    for role_id in c.roles:
        if role_id in host_agents:
            _log.warning("plugin %r: role %r collides with host agent — refusing", pid, role_id)
            return False
        if role_id in _plugin_roles:
            _log.warning("plugin %r: role %r duplicate within plugin — refusing", pid, role_id)
            return False
        _plugin_roles.add(role_id)

    # Skill ids: host-collision + within-plugin dup (bare name)
    _plugin_skills: set[str] = set()
    for skill_id in c.skills:
        if skill_id in host_skills:
            _log.warning(
                "plugin %r: skill %r collides with host skill — refusing", pid, skill_id
            )
            return False
        if skill_id in _plugin_skills:
            _log.warning(
                "plugin %r: skill %r duplicate within plugin — refusing", pid, skill_id
            )
            return False
        _plugin_skills.add(skill_id)

    # Tool classification names: host-collision + within-plugin dup (bare name)
    # Cross-plugin tool name collisions are resolved by namespacing, not refusal.
    _plugin_tools: set[str] = set()
    for tool_name in c.tools:
        if tool_name in host_tools:
            _log.warning(
                "plugin %r: tool %r collides with host tools — refusing", pid, tool_name
            )
            return False
        if tool_name in _plugin_tools:
            _log.warning(
                "plugin %r: tool %r duplicate within plugin — refusing", pid, tool_name
            )
            return False
        _plugin_tools.add(tool_name)

    # tool_impls names (→ local_tools): host shadow-bypass check (bare name, fail-closed).
    # ADR-038 D4 / ADR-029 D2: host-collision evaluated on BARE name; a plugin declaring
    # tool_impl "read_file" is REFUSED even though prefixing would de-conflict it.
    # NOTE: tool_impls is a dict → no within-plugin dup possible.
    # NOTE: tool_impls intentionally NOT checked against host_tools (ToolMeta-only
    # classifications from config/tools.yaml may pre-classify plugin impls, ADR-029 D5/D7).
    for impl_name in c.tool_impls:
        if impl_name in host_local_tool_names:
            _log.warning(
                "plugin %r: tool_impl %r shadows host local_tools (shadow-bypass) — refusing",
                pid,
                impl_name,
            )
            return False

    # MCP server names: host-collision + within-plugin dup (bare name)
    _plugin_servers: set[str] = set()
    for server_name in c.mcp_servers:
        if server_name in host_mcp_server_names:
            _log.warning(
                "plugin %r: mcp_server %r collides with host servers — refusing",
                pid,
                server_name,
            )
            return False
        if server_name in _plugin_servers:
            _log.warning(
                "plugin %r: mcp_server %r duplicate within plugin — refusing",
                pid,
                server_name,
            )
            return False
        _plugin_servers.add(server_name)

    return True


# ---------------------------------------------------------------------------
# Step 6: Reversibility cap (P3.5-3)
# ---------------------------------------------------------------------------


def _apply_reversibility_cap(
    plugin_tools: dict[str, ToolMeta],
    host_tools: dict[str, ToolMeta],
) -> dict[str, ToolMeta]:
    """Cap plugin-asserted reversibility to host-authoritative-or-default-0 (ADR-029 D5).

    Host classification present  → min(plugin_value, host_value).
    No host classification       → default 0 → HARD_CONFIRM (never AUTO_EXECUTE).

    The plugin's claimed reversibility is never used as the authoritative value;
    it can only lower the host cap (ADR-027 HR#2 analog).
    """
    result: dict[str, ToolMeta] = {}
    for tool_name, plugin_meta in plugin_tools.items():
        host_meta = host_tools.get(tool_name)
        if host_meta is None:
            result[tool_name] = ToolMeta(reversibility=0)
        else:
            result[tool_name] = ToolMeta(
                reversibility=min(plugin_meta.reversibility, host_meta.reversibility)
            )
    return result


# ---------------------------------------------------------------------------
# Steps 3-6: Per-plugin load (P3.5-3 + P3.5-4)
# ---------------------------------------------------------------------------


def _load_plugin(
    candidate: _ValidatedCandidate,
    *,
    models: ModelRegistry,
    host_agents: dict[str, Agent],
    host_skills: dict[str, Skill],
    host_tools: dict[str, ToolMeta],
    host_local_tool_names: frozenset[str],
    host_mcp_server_names: frozenset[str],
    activation_entry: ActivationEntry | None = None,
    registry_entry: RegistryEntry | None = None,
    posture_resolver: PostureResolver | None = None,
    sandbox_root: Path | None = None,
) -> PluginLoadResult | None:
    """Load one plugin: provenance-check → collision-check → non-code load → code load → rev-cap.

    Returns a per-plugin PluginLoadResult on success, None on any failure.
    None discards the whole intermediate — host registries are never mutated
    by a partially-loaded plugin (atomic merge, HR#5 / R0-B Y4).

    For fetched plugins: activation_entry must be present (fail-closed if absent).
    The plugin_subprocess_env from the activation entry is operator-authored and
    passed to load_plugin_code — the fetched manifest cannot override it (ADR-031 D4).

    registry_entry: the unified RegistryEntry for this plugin (ADR-038 D1/D2).
    Used for shape-coherence and version-coherence checks.
    """
    pid = candidate.plugin_id
    plugin_dir = candidate.plugin_dir
    manifest = candidate.manifest
    provenance = candidate.provenance

    # Shape-coherence guard (ADR-038 D1): entry's admission-proof shape must match
    # the plugin's host-derived root. A fetched-shape entry (source_url+digest present)
    # for an operator-placed plugin is an authoring error — refuse loudly.
    if (
        registry_entry is not None
        and registry_entry.source_url is not None
        and provenance == "operator_placed"
    ):
        _log.warning(
            "plugin %r: registry entry has fetched-shape (source_url+digest) but "
            "plugin is operator-placed — shape/root mismatch, refusing",
            pid,
        )
        return None

    # Version-coherence check (ADR-038 D2, A3): operator-intent / update-consistency.
    # registry.version (if set) must equal manifest.version for fetched plugins.
    # This catches the operator pinning the wrong version label for a digest.
    # version absent → no check (fail-safe; digest is the integrity anchor).
    if (
        provenance == "fetched"
        and registry_entry is not None
        and registry_entry.version is not None
        and registry_entry.version != manifest.version
    ):
        _log.warning(
            "plugin %r (fetched): version mismatch: registry has %r, manifest has %r "
            "— refusing (ADR-038 D2)",
            pid,
            registry_entry.version,
            manifest.version,
        )
        return None

    # Fetched provenance guard: activation required, fail-closed if absent (ADR-031 D4).
    # Activation can come from (a) unified registry_entry with fetched-shape (source_url present)
    # or (b) legacy activation_entry. (a) is the ADR-038 D1 unified path; (b) is legacy.
    if provenance == "fetched":
        _has_registry_activation = (
            registry_entry is not None and registry_entry.source_url is not None
        )
        if not _has_registry_activation and activation_entry is None:
            _log.warning(
                "plugin %r (fetched): no activation entry — refusing (ADR-031 D4)",
                pid,
            )
            return None
        _log.debug("plugin %r (fetched): activation proof present, continuing load", pid)

    # Step 3: Host-collision + within-plugin-dup check BEFORE any import (ADR-029 D2 step 3).
    # Cross-plugin collision is resolved by namespacing (ADR-038 D4).
    if not _collision_check(
        candidate,
        host_agents,
        host_skills,
        host_tools,
        host_local_tool_names,
        host_mcp_server_names,
    ):
        return None

    # Step 4: Load non-code surfaces by reusing existing loaders (ADR-029 D2 step 4).
    # Pure data parse — no arbitrary code runs here.
    try:
        plugin_agents, plugin_regex = (
            load_agents(plugin_dir / "agents", models=models)
            if (plugin_dir / "agents").exists()
            else ({}, {})
        )
    except Exception as exc:
        _log.warning("plugin %r: failed to load agents: %s — refusing", pid, exc)
        return None

    try:
        plugin_skills = (
            load_skills(plugin_dir / "skills") if (plugin_dir / "skills").exists() else {}
        )
    except Exception as exc:
        _log.warning("plugin %r: failed to load skills: %s — refusing", pid, exc)
        return None

    declared_tools = set(manifest.contributions.tools)
    try:
        raw_own_tools: dict[str, ToolMeta] = (
            load_tools_config(plugin_dir / "tools.yaml")
            if (plugin_dir / "tools.yaml").exists()
            else {}
        )
        # Only load ToolMeta entries that the manifest declares (manifest is authority;
        # undeclared entries in tools.yaml are silently ignored — not collision-checked).
        plugin_own_tools: dict[str, ToolMeta] = {
            k: v for k, v in raw_own_tools.items() if k in declared_tools
        }
    except ConfigError as exc:
        _log.warning("plugin %r: failed to load tools.yaml: %s — refusing", pid, exc)
        return None

    plugin_mcp_tools: dict[str, ToolMeta] = {}
    plugin_mcp_sessions: dict[str, MCPSession] = {}
    if (plugin_dir / "mcp_servers.yaml").exists():
        try:
            from orchestrator.mcp.adapter import (  # local: avoids startup cycle
                build_mcp_tool_registry_and_sessions_from_config,
            )

            plugin_mcp_tools, plugin_mcp_sessions = (
                build_mcp_tool_registry_and_sessions_from_config(plugin_dir / "mcp_servers.yaml")
            )
        except Exception as exc:
            _log.warning("plugin %r: failed to load mcp_servers.yaml: %s — refusing", pid, exc)
            return None

    # Merge plugin tool-classifications (own + MCP namespaced)
    plugin_all_tools: dict[str, ToolMeta] = {**plugin_own_tools, **plugin_mcp_tools}

    # Step 5: Load code — ONLY after validation + collision-check cleared (P3.5-4 wires this).
    # Dual posture: operator-placed → in-process importlib (Posture A, ADR-029 D4);
    # fetched → subprocess-launching _PostureBFn (Posture B, ADR-031 D1/D2).
    # subprocess_env: operator-authored (from activation entry for fetched; unused for
    # operator-placed Posture A); the fetched plugin manifest cannot override (ADR-031 D4).
    plugin_local_tools: dict[str, LocalToolFn] = {}
    if manifest.contributions.tool_impls:
        from orchestrator.plugins.code import PluginCodeLoadError, load_plugin_code

        # subprocess_env: prefer unified registry_entry, fall back to legacy activation_entry.
        subprocess_env: dict[str, str] = {}
        if activation_entry is not None:
            subprocess_env = activation_entry.plugin_subprocess_env
        elif registry_entry is not None:
            subprocess_env = registry_entry.plugin_subprocess_env
        try:
            plugin_local_tools = load_plugin_code(
                plugin_dir,
                pid,
                manifest.contributions.tool_impls,
                plugin_subprocess_env=subprocess_env,
                provenance=provenance,
                posture_resolver=posture_resolver,
                sandbox_root=sandbox_root,
            )
        except PluginCodeLoadError as exc:
            _log.warning("plugin %r: code load failed: %s — refusing", pid, exc)
            return None

    # Step 6: Reversibility cap (host-authoritative-or-default-0, ADR-029 D5)
    capped_tools = _apply_reversibility_cap(plugin_all_tools, host_tools)

    _log.info(
        "plugin %r (%s): loaded — roles=%d skills=%d tools=%d impls=%d servers=%d",
        pid,
        provenance,
        len(plugin_agents),
        len(plugin_skills),
        len(capped_tools),
        len(plugin_local_tools),
        len(plugin_mcp_sessions),
    )

    return PluginLoadResult(
        agents=plugin_agents,
        regex_registry=plugin_regex,
        skills=plugin_skills,
        tools=capped_tools,
        local_tools=plugin_local_tools,
        mcp_sessions=plugin_mcp_sessions,
    )


# ---------------------------------------------------------------------------
# Public API
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
    fetched_plugins_dir: Path | None = None,
    activation_registry_path: Path | None = None,
    plugin_registry: PluginRegistry | _RegistryRefuseAll | None = None,
    posture_resolver: PostureResolver | None = None,
    sandbox_root: Path | None = None,
) -> PluginLoadResult:
    """Discover, validate, and merge plugin contributions (ADR-029 D2, ADR-031 D3/D4; ADR-038 D2).

    Absent plugins/ dir → no-op (clean boot). Per-plugin load isolation:
    a failure at ANY stage refuses that plugin without crashing bootstrap
    or refusing valid siblings. Host registries are never mutated by a
    partially-loaded plugin (atomic-merge guarantee, HR#5 / R0-B Y4).

    fetched_plugins_dir: if provided, a SEPARATE directory for fetched plugin bundles.
      Must be disjoint from plugins_dir (provenance-laundering prevention, ADR-031 D3).
      Fetched plugins require activation entries (fail-closed if absent, ADR-031 D4).
      Both roots are processed; collision-check is global (cross-root).

    activation_registry_path: path to the operator's activation allowlist YAML.
      Absent / None → no fetched plugins activated (fail-closed default).

    plugin_registry: the unified RegistryEntry registry (ADR-038 D1/D2).
      None → absent registry → today's shipped defaults (operator-placed by
      presence; fetched none). Used for enabled-gate + version-coherence.
    """
    fetched_empty = fetched_plugins_dir is None or not fetched_plugins_dir.exists()
    if not plugins_dir.exists() and fetched_empty:
        return PluginLoadResult()

    # Disjoint-root guard: fetched_plugins_dir must not overlap with plugins_dir
    # (provenance-laundering prevention, ADR-031 D3 un-launderable property).
    if fetched_plugins_dir is not None and fetched_plugins_dir.exists():
        try:
            plugins_dir.resolve().relative_to(fetched_plugins_dir.resolve())
            # If we got here, plugins_dir is INSIDE fetched_plugins_dir → overlap
            raise ValueError(
                f"plugins_dir {plugins_dir!r} is inside fetched_plugins_dir "
                f"{fetched_plugins_dir!r} — roots must be disjoint (ADR-031 D3)"
            )
        except ValueError as exc:
            if "roots must be disjoint" in str(exc):
                raise
        try:
            fetched_plugins_dir.resolve().relative_to(plugins_dir.resolve())
            raise ValueError(
                f"fetched_plugins_dir {fetched_plugins_dir!r} is inside plugins_dir "
                f"{plugins_dir!r} — roots must be disjoint (ADR-031 D3)"
            )
        except ValueError as exc:
            if "roots must be disjoint" in str(exc):
                raise

    # Load activation registry (operator-authored; absent = no fetched plugins, ADR-031 D4).
    activation_registry: ActivationRegistry = load_activation_registry(activation_registry_path)

    # Steps 1-2: Discover + validate — operator-placed root
    candidates: list[_ValidatedCandidate] = []
    if plugins_dir.exists():
        candidates.extend(
            _discover_and_validate(
                plugins_dir,
                models,
                host_room_types,
                host_contract_version,
                provenance="operator_placed",
            )
        )

    # Steps 1-2: Discover + validate — fetched root (separate provenance, ADR-031 D3)
    if fetched_plugins_dir is not None and fetched_plugins_dir.exists():
        candidates.extend(
            _discover_and_validate(
                fetched_plugins_dir,
                models,
                host_room_types,
                host_contract_version,
                provenance="fetched",
            )
        )

    # Sentinel guard: malformed plugins.yaml → refuse-all (ADR-038 D2).
    # REGISTRY_REFUSE_ALL is distinct from None (absent → defaults) and {} (empty → defaults).
    # On malformed config the operator's intent is unknown — the safe position is refuse-all,
    # never admit-by-presence.  This mirrors _resolve_sandbox_posture → fail_closed().
    if isinstance(plugin_registry, _RegistryRefuseAll):
        _log.warning(
            "plugins.yaml is malformed — refusing all %d candidate(s) (ADR-038 D2 refuse-all)",
            len(candidates),
        )
        return PluginLoadResult()

    # Steps 3-7: Per-plugin host-collision-check + load + namespaced merge (global, cross-root).
    # Cross-plugin collision is resolved by deterministic always-prefix namespacing
    # (<plugin_id>__<name>, ADR-038 D4). No seen_* sets needed for cross-plugin dedup.
    merged = PluginLoadResult()

    for candidate in candidates:
        # enabled-gate: short-circuit disabled plugins BEFORE _load_plugin (ADR-038 D2,
        # absorbed R0-A Y1). _load_plugin builds MCP sessions (live stdio subprocesses);
        # a disabled plugin must never enter _load_plugin — no subprocess spawned.
        # Operator-placed with no registry entry → still loads (presence=opt-in, ADR-029 D5).
        r_entry: RegistryEntry | None = (
            plugin_registry.get(candidate.plugin_id) if plugin_registry is not None else None
        )
        if r_entry is not None and not r_entry.enabled:
            _log.info(
                "plugin %r: disabled in registry (enabled: false) — skipping",
                candidate.plugin_id,
            )
            continue

        activation = (
            check_fetched_activation(candidate.plugin_id, activation_registry)
            if candidate.provenance == "fetched"
            else None
        )
        result = _load_plugin(
            candidate,
            models=models,
            host_agents=host_agents,
            host_skills=host_skills,
            host_tools=host_tools,
            host_local_tool_names=host_local_tool_names,
            host_mcp_server_names=host_mcp_server_names,
            activation_entry=activation,
            registry_entry=r_entry,
            posture_resolver=posture_resolver,
            sandbox_root=sandbox_root,
        )
        if result is None:
            continue

        # Atomic namespaced merge: prefix all contribution names with <plugin_id>__
        # (ADR-038 D4 deterministic coexistence). regex_registry uses agent.id as key
        # (not the agents dict key), so it merges bare — consistent with speaking.py lookup.
        pid = candidate.plugin_id
        merged.agents.update({f"{pid}__{k}": v for k, v in result.agents.items()})
        merged.regex_registry.update(result.regex_registry)
        merged.skills.update({f"{pid}__{k}": v for k, v in result.skills.items()})
        merged.tools.update({f"{pid}__{k}": v for k, v in result.tools.items()})
        merged.local_tools.update({f"{pid}__{k}": v for k, v in result.local_tools.items()})
        merged.mcp_sessions.update({f"{pid}__{k}": v for k, v in result.mcp_sessions.items()})

    return merged
