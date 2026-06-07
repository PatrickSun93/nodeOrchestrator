"""Plugin provenance tracking, activation allowlist, and unified registry.

ADR-031 D3/D4 + ADR-038 D1.


Provenance-by-origin: a plugin's trust level is determined by WHICH discovery root
it was found in — not by anything the plugin itself claims.

  operator_placed: found in the operator-curated plugins_dir (ADR-029 D4 premise
                   preserved — curation = the only basis for Posture-A trust).
                   Code loading: in-process importlib via _load_posture_a_fns
                   (code.py).

  fetched:         found in the segregated fetched_plugins_dir (ADR-031 D3).
                   Curation premise is VOID → Posture A constitutionally invalid.
                   Posture B is REQUIRED and TEST-ENFORCED for all fetched plugins.
                   Code loading: subprocess harness via _load_posture_b_fns /
                   _PostureBFn (code.py) — fetched code NEVER runs in-process.
                   api_key_env is structurally unreachable for fetched subprocess
                   (MCPServerConfig built without api_key_env; ADR-031 D4).

Disjoint roots: fetched_plugins_dir and plugins_dir must not overlap — a fetched
bundle can never be re-discovered as operator-placed (provenance-laundering prevented,
ADR-031 D3 un-launderable property).  Enforced at bootstrap by loader.py's
disjoint-root guard (ValueError on overlap).

Activation allowlist (ADR-031 D4, generalised to unified registry by ADR-038 D1):
  A fetched plugin loads ONLY if the operator has an explicit registry entry that
  pins source_url + digest.  The entry is operator-authored (not plugin-authored):
  the fetched plugin cannot self-request env keys or api_key_env.

Unified registry (ADR-038 D1):
  config/plugins.yaml — a list of RegistryEntry covering both roots.
  Operator-placed entries are optional (presence=opt-in preserved, ADR-029 D5).
  Fetched entries require source_url+digest (fail-closed, ADR-031 D4 unchanged).
  Provenance is NEVER a registry field — it stays host-derived by root.
"""

from __future__ import annotations

import dataclasses
import os
import tempfile
from pathlib import Path
from typing import Literal

import yaml

from orchestrator.llm.exceptions import ConfigError

PluginProvenance = Literal["operator_placed", "fetched"]


# ---------------------------------------------------------------------------
# ActivationEntry — legacy fetched-only proto-registry (ADR-031 D4).
# Kept for backward-compat; unified path uses RegistryEntry + load_plugin_registry.
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ActivationEntry:
    """Operator-pinned activation record for one fetched plugin (ADR-031 D4).

    source_url:           the exact https:// URL the bundle was fetched from.
    digest:               sha256:<hex> digest of the compressed bundle bytes
                          (verified before extraction; ADR-031 D5).
    plugin_subprocess_env: non-secret env keys the operator approves for the child
                          subprocess.  Operator-authored; the fetched plugin manifest
                          CANNOT override this or request additional keys.
    """

    source_url: str
    digest: str
    plugin_subprocess_env: dict[str, str] = dataclasses.field(default_factory=dict)


# Registry mapping plugin_id → ActivationEntry (operator-authored).
ActivationRegistry = dict[str, ActivationEntry]


def load_activation_registry(path: Path | None) -> ActivationRegistry:
    """Load the operator's fetched-plugin activation allowlist from a YAML file.

    Returns an empty registry if path is None or the file is absent (no fetched
    plugins activated → fail-closed by default).

    Schema (example):
      activations:
        - plugin_id: "my_plugin"
          source_url: "https://example.com/my_plugin.zip"
          digest: "sha256:abc123..."
          plugin_subprocess_env:
            SOME_PUBLIC_KEY: "value"

    Raises ConfigError on malformed YAML or schema violation.
    """
    if path is None or not path.exists():
        return {}

    raw_text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(raw_text)
    if raw is None:
        return {}

    if not isinstance(raw, dict):
        raise ConfigError(f"{path.name}: expected a mapping at root, got {type(raw).__name__}")

    entries_raw = raw.get("activations")
    if entries_raw is None:
        return {}

    if not isinstance(entries_raw, list):
        raise ConfigError(f"{path.name}: 'activations' must be a list")

    registry: ActivationRegistry = {}
    for i, entry in enumerate(entries_raw):
        if not isinstance(entry, dict):
            raise ConfigError(f"{path.name}: activations[{i}] must be a mapping")

        plugin_id = entry.get("plugin_id")
        if not isinstance(plugin_id, str) or not plugin_id:
            raise ConfigError(f"{path.name}: activations[{i}]: 'plugin_id' must be a non-empty str")

        source_url = entry.get("source_url")
        if not isinstance(source_url, str) or not source_url:
            raise ConfigError(
                f"{path.name}: activations[{i}]: 'source_url' must be a non-empty str"
            )

        digest = entry.get("digest")
        if not isinstance(digest, str) or not digest:
            raise ConfigError(f"{path.name}: activations[{i}]: 'digest' must be a non-empty str")

        env = entry.get("plugin_subprocess_env", {})
        if not isinstance(env, dict):
            raise ConfigError(
                f"{path.name}: activations[{i}]: 'plugin_subprocess_env' must be a mapping"
            )
        env_str: dict[str, str] = {}
        for k, v in env.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ConfigError(
                    f"{path.name}: activations[{i}]: "
                    f"plugin_subprocess_env keys and values must be strings"
                )
            env_str[k] = v

        registry[plugin_id] = ActivationEntry(
            source_url=source_url,
            digest=digest,
            plugin_subprocess_env=env_str,
        )

    return registry


def check_fetched_activation(
    plugin_id: str,
    registry: ActivationRegistry,
) -> ActivationEntry | None:
    """Return the activation entry for a fetched plugin, or None if not activated.

    A fetched plugin with no activation entry must be REFUSED (fail-closed, ADR-031 D4).
    The caller is responsible for the refusal; this function only does the lookup.
    """
    return registry.get(plugin_id)


# ---------------------------------------------------------------------------
# RegistryEntry — unified registry schema (ADR-038 D1).
# Covers both roots: operator-placed entries optional; fetched entries require
# source_url+digest.  Provenance is NEVER a field here — stays host-derived.
# ---------------------------------------------------------------------------

# Allowed keys in a registry entry — anything else is rejected (extra="forbid" equivalent).
# ADR-038 D1: provenance/posture are NOT allowed fields (un-spoofable invariant).
_KNOWN_REGISTRY_ENTRY_KEYS: frozenset[str] = frozenset(
    {"plugin_id", "enabled", "version", "source_url", "digest", "plugin_subprocess_env"}
)


@dataclasses.dataclass(frozen=True)
class RegistryEntry:
    """Unified registry entry for one declared plugin (ADR-038 D1).

    Covers both operator-placed and fetched roots.

    plugin_id:            identity = the plugin subdir name.
    enabled:              bool, default True.  False = declared-but-disabled.
                          MUST be a real bool — YAML `enabled: "false"` (string)
                          is truthy and would silently enable a disabled plugin.
                          isinstance(enabled, bool) is enforced at parse time.
    version:              operator-pinned version label (str or None).
                          For fetched plugins coherence-checked against
                          manifest.version at boot (ADR-038 D2).
    source_url:           fetched-only.  None for operator-placed entries.
    digest:               fetched-only.  None for operator-placed entries.
                          source_url and digest must come as a pair.
    plugin_subprocess_env: fetched-only.  Operator-authored non-secret env.
    """

    plugin_id: str
    enabled: bool = True
    version: str | None = None
    source_url: str | None = None
    digest: str | None = None
    plugin_subprocess_env: dict[str, str] = dataclasses.field(default_factory=dict)


# Registry mapping plugin_id → RegistryEntry (operator-authored, both roots).
PluginRegistry = dict[str, RegistryEntry]


class _RegistryRefuseAll:
    """Sentinel: plugins.yaml exists but failed to parse → refuse ALL candidates.

    Distinct from None (absent registry → today's defaults, op-placed loads by
    presence) and {} (empty registry, same absent-defaults behaviour).
    load_plugins receiving this value must refuse every candidate without
    processing, regardless of provenance (ADR-038 D2 refuse-all, graceful).
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "REGISTRY_REFUSE_ALL"


REGISTRY_REFUSE_ALL: _RegistryRefuseAll = _RegistryRefuseAll()


def load_plugin_registry(path: Path | None) -> PluginRegistry:
    """Load the unified plugin registry from config/plugins.yaml.

    Returns an empty registry if path is None or the file is absent.
    Raises ConfigError on malformed YAML or schema violation (fail-closed).

    Schema (example):
      plugins:
        - plugin_id: "my_plugin"
          enabled: true
          version: "1.0.0"
          source_url: "https://example.com/my_plugin.zip"
          digest: "sha256:abc123..."
          plugin_subprocess_env:
            KEY: "value"
        - plugin_id: "local_plugin"
          enabled: false

    Validation rules (ADR-038 D1 absorbed findings):
      - Unknown entry keys raise ConfigError (extra="forbid" equivalent).
      - `enabled` MUST be a real bool — isinstance(enabled, bool) enforced.
        YAML `enabled: "false"` parses to a non-empty string (truthy), which
        would silently fail-open; this is caught and rejected.
      - `version` must be str or None.
      - `source_url` and `digest` must come as a pair (or both absent).
      - Duplicate plugin_id raises ConfigError (list format prevents silent overwrite).
      - `provenance` / `posture` fields are NOT accepted (un-spoofable invariant).
    """
    if path is None or not path.exists():
        return {}

    raw_text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(raw_text)
    if raw is None:
        return {}

    if not isinstance(raw, dict):
        raise ConfigError(f"{path.name}: expected a mapping at root, got {type(raw).__name__}")

    entries_raw = raw.get("plugins")
    if entries_raw is None:
        return {}

    if not isinstance(entries_raw, list):
        raise ConfigError(f"{path.name}: 'plugins' must be a list")

    registry: PluginRegistry = {}
    for i, entry in enumerate(entries_raw):
        if not isinstance(entry, dict):
            raise ConfigError(f"{path.name}: plugins[{i}] must be a mapping")

        # Reject unknown keys (extra="forbid" equivalent; catches provenance/posture attempts).
        unknown_keys = set(entry.keys()) - _KNOWN_REGISTRY_ENTRY_KEYS
        if unknown_keys:
            raise ConfigError(
                f"{path.name}: plugins[{i}]: unknown keys {sorted(unknown_keys)!r}"
            )

        # plugin_id: non-empty str
        plugin_id = entry.get("plugin_id")
        if not isinstance(plugin_id, str) or not plugin_id:
            raise ConfigError(f"{path.name}: plugins[{i}]: 'plugin_id' must be a non-empty str")

        # Duplicate plugin_id — list format lets us catch this; mapping format cannot.
        if plugin_id in registry:
            raise ConfigError(
                f"{path.name}: plugins[{i}]: duplicate plugin_id {plugin_id!r}"
            )

        # enabled: MUST be isinstance bool.  YAML `enabled: "false"` (quoted string) is
        # truthy — it would silently enable a plugin the operator intended to disable.
        enabled_raw = entry.get("enabled", True)
        if not isinstance(enabled_raw, bool):
            raise ConfigError(
                f"{path.name}: plugins[{i}] ({plugin_id!r}): "
                f"'enabled' must be a bool (true/false), got {type(enabled_raw).__name__!r} "
                f"— quoted string values like \"false\" are not bools in YAML"
            )

        # version: str or None
        version = entry.get("version", None)
        if version is not None and not isinstance(version, str):
            raise ConfigError(
                f"{path.name}: plugins[{i}] ({plugin_id!r}): "
                f"'version' must be a str or null, got {type(version).__name__!r}"
            )

        # source_url: non-empty str or absent
        source_url: str | None = entry.get("source_url", None)
        if source_url is not None and (not isinstance(source_url, str) or not source_url):
            raise ConfigError(
                f"{path.name}: plugins[{i}] ({plugin_id!r}): "
                "'source_url' must be a non-empty str"
            )

        # digest: non-empty str or absent
        digest: str | None = entry.get("digest", None)
        if digest is not None and (not isinstance(digest, str) or not digest):
            raise ConfigError(
                f"{path.name}: plugins[{i}] ({plugin_id!r}): "
                "'digest' must be a non-empty str"
            )

        # source_url + digest must come as a pair (both or neither).
        if (source_url is None) != (digest is None):
            raise ConfigError(
                f"{path.name}: plugins[{i}] ({plugin_id!r}): "
                "'source_url' and 'digest' must both be present or both absent "
                "(a fetched entry requires both; an operator-placed entry requires neither)"
            )

        # plugin_subprocess_env: strings-only dict
        env = entry.get("plugin_subprocess_env", {})
        if not isinstance(env, dict):
            raise ConfigError(
                f"{path.name}: plugins[{i}] ({plugin_id!r}): "
                "'plugin_subprocess_env' must be a mapping"
            )
        env_str: dict[str, str] = {}
        for k, v in env.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ConfigError(
                    f"{path.name}: plugins[{i}] ({plugin_id!r}): "
                    "plugin_subprocess_env keys and values must be strings"
                )
            env_str[k] = v

        registry[plugin_id] = RegistryEntry(
            plugin_id=plugin_id,
            enabled=enabled_raw,
            version=version,
            source_url=source_url,
            digest=digest,
            plugin_subprocess_env=env_str,
        )

    return registry


def write_plugin_registry(path: Path, registry: PluginRegistry) -> None:
    """Write the unified plugin registry to path atomically.

    Serializes registry to the plugins:-list YAML shape, round-trip-validates
    the serialized form through load_plugin_registry before persisting, then
    atomically replaces path via temp-in-same-dir + os.replace.

    Raises (ConfigError, yaml.YAMLError) if the round-trip fails; the
    pre-existing file at path is left byte-unchanged (no torn write).

    ADR-038 D5 / DP3b: the round-trip guard mirrors the boot refuse-all
    catch set (app.py:506) — any write that would fail the boot parser is
    rejected before it can produce a REGISTRY_REFUSE_ALL sentinel at boot.
    """
    entries: list[dict[str, object]] = []
    for entry in registry.values():
        d: dict[str, object] = {"plugin_id": entry.plugin_id, "enabled": entry.enabled}
        if entry.version is not None:
            d["version"] = entry.version
        if entry.source_url is not None:
            d["source_url"] = entry.source_url
        if entry.digest is not None:
            d["digest"] = entry.digest
        if entry.plugin_subprocess_env:
            d["plugin_subprocess_env"] = dict(entry.plugin_subprocess_env)
        entries.append(d)

    serialized = yaml.safe_dump({"plugins": entries}, allow_unicode=True, sort_keys=False)

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(dir=path.parent, prefix=".plugins_tmp_", suffix=".yaml")
    tmp_path = Path(tmp_str)
    try:
        os.write(fd, serialized.encode("utf-8"))
        os.close(fd)
        fd = -1

        # Round-trip validate: mirrors boot parse catch set (app.py:506).
        # Raises (ConfigError, yaml.YAMLError) if the serialized form would
        # trigger REGISTRY_REFUSE_ALL at boot — reject before persisting.
        load_plugin_registry(tmp_path)

        os.replace(str(tmp_path), str(path))
    except BaseException:
        try:
            if fd >= 0:
                os.close(fd)
        except OSError:
            pass
        tmp_path.unlink(missing_ok=True)
        raise
