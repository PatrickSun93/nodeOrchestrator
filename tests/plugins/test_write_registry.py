"""Unit tests for write_plugin_registry (T1, ADR-038 D5 / DP3b).

wpr1  — round-trip fidelity: written registry loads back equal to input.
wpr2  — bool fidelity: enabled=False survives serialization as real bool.
wpr3  — empty registry write: {} → round-trips to {} (not refuse-all).
wpr4  — atomic temp-in-same-dir: a torn write never leaves config/plugins.yaml partial.
wpr5  — round-trip-reject: monkeypatched loader raises ConfigError → existing file unchanged.
wpr6  — first-write: path absent → file is created.
wpr7  — full-field entry: source_url+digest+version+env all round-trip correctly.
wpr8  — no temp file left behind after a validation failure.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from orchestrator.llm.exceptions import ConfigError
from orchestrator.plugins.provenance import (
    PluginRegistry,
    RegistryEntry,
    load_plugin_registry,
    write_plugin_registry,
)


def _entry(
    plugin_id: str,
    *,
    enabled: bool = True,
    version: str | None = None,
    source_url: str | None = None,
    digest: str | None = None,
    env: dict[str, str] | None = None,
) -> RegistryEntry:
    return RegistryEntry(
        plugin_id=plugin_id,
        enabled=enabled,
        version=version,
        source_url=source_url,
        digest=digest,
        plugin_subprocess_env=env or {},
    )


# ---------------------------------------------------------------------------
# wpr1 — round-trip fidelity (operator-placed entries, no fetchd fields)
# ---------------------------------------------------------------------------


def test_wpr1_round_trip_fidelity(tmp_path: Path) -> None:
    registry: PluginRegistry = {
        "alpha": _entry("alpha", enabled=True),
        "beta": _entry("beta", enabled=False),
    }
    p = tmp_path / "plugins.yaml"
    write_plugin_registry(p, registry)
    loaded = load_plugin_registry(p)
    assert loaded == registry


# ---------------------------------------------------------------------------
# wpr2 — enabled=False survives serialization as a real bool (not string)
# ---------------------------------------------------------------------------


def test_wpr2_bool_fidelity(tmp_path: Path) -> None:
    registry: PluginRegistry = {"p": _entry("p", enabled=False)}
    p = tmp_path / "plugins.yaml"
    write_plugin_registry(p, registry)
    raw = yaml.safe_load(p.read_text())
    assert isinstance(raw["plugins"][0]["enabled"], bool)
    assert raw["plugins"][0]["enabled"] is False


# ---------------------------------------------------------------------------
# wpr3 — empty registry: {} permitted, round-trips to {} (not refuse-all)
# ---------------------------------------------------------------------------


def test_wpr3_empty_registry(tmp_path: Path) -> None:
    p = tmp_path / "plugins.yaml"
    write_plugin_registry(p, {})
    loaded = load_plugin_registry(p)
    assert loaded == {}


# ---------------------------------------------------------------------------
# wpr4 — existing file untouched when validation fails
# ---------------------------------------------------------------------------


def test_wpr4_existing_file_unchanged_on_failure(tmp_path: Path) -> None:
    original_text = "plugins:\n  - plugin_id: existing\n    enabled: true\n"
    p = tmp_path / "plugins.yaml"
    p.write_text(original_text)

    # Patch loader to simulate a round-trip failure (monkeypatched validator path).
    with (
        patch(
            "orchestrator.plugins.provenance.load_plugin_registry",
            side_effect=ConfigError("simulated validation failure"),
        ),
        pytest.raises(ConfigError),
    ):
        write_plugin_registry(p, {"new": _entry("new")})

    assert p.read_text() == original_text


# ---------------------------------------------------------------------------
# wpr5 — no temp file left behind after a validation failure
# ---------------------------------------------------------------------------


def test_wpr5_no_temp_left_behind(tmp_path: Path) -> None:
    p = tmp_path / "plugins.yaml"

    with (
        patch(
            "orchestrator.plugins.provenance.load_plugin_registry",
            side_effect=ConfigError("bad"),
        ),
        pytest.raises(ConfigError),
    ):
        write_plugin_registry(p, {"x": _entry("x")})

    leftovers = list(tmp_path.glob(".plugins_tmp_*"))
    assert leftovers == [], f"temp files left behind: {leftovers}"


# ---------------------------------------------------------------------------
# wpr6 — first write: path absent → file is created
# ---------------------------------------------------------------------------


def test_wpr6_first_write_creates_file(tmp_path: Path) -> None:
    p = tmp_path / "config" / "plugins.yaml"
    assert not p.exists()
    registry: PluginRegistry = {"myplugin": _entry("myplugin")}
    write_plugin_registry(p, registry)
    assert p.exists()
    assert load_plugin_registry(p) == registry


# ---------------------------------------------------------------------------
# wpr7 — full-field fetched entry: source_url+digest+version+env preserved
# ---------------------------------------------------------------------------


def test_wpr7_full_field_round_trip(tmp_path: Path) -> None:
    registry: PluginRegistry = {
        "fetched_plugin": _entry(
            "fetched_plugin",
            enabled=True,
            version="2.0.1",
            source_url="https://example.com/plugin.zip",
            digest="sha256:abc123def456",
            env={"API_HOST": "https://api.example.com"},
        )
    }
    p = tmp_path / "plugins.yaml"
    write_plugin_registry(p, registry)
    loaded = load_plugin_registry(p)
    assert loaded == registry
