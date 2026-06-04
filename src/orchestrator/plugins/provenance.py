"""Plugin provenance tracking and activation allowlist (ADR-031 D3/D4).

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

Activation allowlist (ADR-031 D4):
  A fetched plugin loads ONLY if the operator has an explicit activation entry that
  pins source_url + digest.  The entry is operator-authored (not plugin-authored):
  the fetched plugin cannot self-request env keys or api_key_env.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Literal

import yaml

from orchestrator.llm.exceptions import ConfigError

PluginProvenance = Literal["operator_placed", "fetched"]


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
