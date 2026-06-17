"""Unit tests for CountdownAutoFireConfig + load_countdown_auto_fire_config (P4.6-1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.autonomy.config import CountdownAutoFireConfig, load_countdown_auto_fire_config

# ---------------------------------------------------------------------------
# CountdownAutoFireConfig model invariants
# ---------------------------------------------------------------------------


class TestCountdownAutoFireConfig:
    def test_defaults_disabled(self) -> None:
        cfg = CountdownAutoFireConfig()
        assert cfg.enabled is False

    def test_defaults_positive_ints(self) -> None:
        cfg = CountdownAutoFireConfig()
        assert cfg.window_s >= 1
        assert cfg.sweep_interval_s >= 1

    def test_defaults_reversibility_floor_in_range(self) -> None:
        cfg = CountdownAutoFireConfig()
        assert 0 <= cfg.reversibility_floor <= 10

    def test_frozen(self) -> None:
        from pydantic import ValidationError

        cfg = CountdownAutoFireConfig()
        with pytest.raises((ValidationError, TypeError)):
            cfg.enabled = True  # type: ignore[misc,unused-ignore]

    def test_extra_forbid(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CountdownAutoFireConfig(unknown_field=True)  # type: ignore[call-arg]

    def test_window_s_ge_1(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CountdownAutoFireConfig(window_s=0)

    def test_sweep_interval_s_ge_1(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CountdownAutoFireConfig(sweep_interval_s=0)

    def test_reversibility_floor_ge_0(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CountdownAutoFireConfig(reversibility_floor=-1)

    def test_reversibility_floor_le_10(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CountdownAutoFireConfig(reversibility_floor=11)

    def test_enabled_true(self) -> None:
        cfg = CountdownAutoFireConfig(
            enabled=True, window_s=60, sweep_interval_s=10, reversibility_floor=3
        )
        assert cfg.enabled is True
        assert cfg.window_s == 60

    def test_window_lt_sweep_raises(self) -> None:
        """P7-6: window_s < sweep_interval_s must raise ValueError (ADR-040 D7)."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CountdownAutoFireConfig(window_s=10, sweep_interval_s=30)

    def test_window_equal_sweep_valid(self) -> None:
        """P7-6: window_s == sweep_interval_s is the boundary valid case."""
        cfg = CountdownAutoFireConfig(window_s=30, sweep_interval_s=30)
        assert cfg.window_s == cfg.sweep_interval_s

    def test_defaults_satisfy_constraint(self) -> None:
        """P7-6: defaults (window_s=300, sweep_interval_s=30) must satisfy constraint."""
        cfg = CountdownAutoFireConfig()
        assert cfg.window_s >= cfg.sweep_interval_s


# ---------------------------------------------------------------------------
# load_countdown_auto_fire_config loader
# ---------------------------------------------------------------------------


class TestLoadCountdownAutoFireConfig:
    def test_absent_file_returns_disabled_default(self, tmp_path: Path) -> None:
        cfg = load_countdown_auto_fire_config(tmp_path / "nonexistent.yaml")
        assert cfg.enabled is False

    def test_absent_section_returns_disabled_default(self, tmp_path: Path) -> None:
        p = tmp_path / "autonomy.yaml"
        p.write_text("other_section:\n  key: val\n")
        cfg = load_countdown_auto_fire_config(p)
        assert cfg.enabled is False

    def test_empty_file_returns_disabled_default(self, tmp_path: Path) -> None:
        p = tmp_path / "autonomy.yaml"
        p.write_text("")
        cfg = load_countdown_auto_fire_config(p)
        assert cfg.enabled is False

    def test_disabled_explicit(self, tmp_path: Path) -> None:
        p = tmp_path / "autonomy.yaml"
        p.write_text("countdown_auto_fire:\n  enabled: false\n  window_s: 120\n")
        cfg = load_countdown_auto_fire_config(p)
        assert cfg.enabled is False
        assert cfg.window_s == 120

    def test_enabled_section_loads(self, tmp_path: Path) -> None:
        p = tmp_path / "autonomy.yaml"
        p.write_text(
            "countdown_auto_fire:\n"
            "  enabled: true\n"
            "  window_s: 60\n"
            "  sweep_interval_s: 10\n"
            "  reversibility_floor: 3\n"
        )
        cfg = load_countdown_auto_fire_config(p)
        assert cfg.enabled is True
        assert cfg.window_s == 60
        assert cfg.sweep_interval_s == 10
        assert cfg.reversibility_floor == 3

    def test_malformed_section_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "autonomy.yaml"
        p.write_text("countdown_auto_fire:\n  window_s: -1\n")
        with pytest.raises(ValueError, match="countdown_auto_fire"):
            load_countdown_auto_fire_config(p)

    def test_unknown_field_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "autonomy.yaml"
        p.write_text("countdown_auto_fire:\n  enabled: false\n  bogus_key: 1\n")
        with pytest.raises(ValueError, match="countdown_auto_fire"):
            load_countdown_auto_fire_config(p)

    def test_non_mapping_file_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "autonomy.yaml"
        p.write_text("- item1\n- item2\n")
        with pytest.raises(ValueError):
            load_countdown_auto_fire_config(p)
