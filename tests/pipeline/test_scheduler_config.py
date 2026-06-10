"""Tests for PipelineSchedulerConfig + loader (ADR-042 D7 / P5.1b-3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from orchestrator.pipeline.config import PipelineSchedulerConfig, load_pipeline_scheduler_config


def test_default_is_disabled() -> None:
    cfg = PipelineSchedulerConfig()
    assert cfg.enabled is False
    assert cfg.sweep_interval_s == 60


def test_absent_file_returns_default(tmp_path: Path) -> None:
    cfg = load_pipeline_scheduler_config(tmp_path / "nonexistent.yaml")
    assert cfg.enabled is False


def test_absent_section_returns_default(tmp_path: Path) -> None:
    p = tmp_path / "pipeline.yaml"
    p.write_text("other_key: 1\n")
    cfg = load_pipeline_scheduler_config(p)
    assert cfg.enabled is False


def test_enabled_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "pipeline.yaml"
    p.write_text("pipeline_scheduler:\n  enabled: true\n  sweep_interval_s: 30\n")
    cfg = load_pipeline_scheduler_config(p)
    assert cfg.enabled is True
    assert cfg.sweep_interval_s == 30


def test_empty_file_returns_default(tmp_path: Path) -> None:
    p = tmp_path / "pipeline.yaml"
    p.write_text("")
    cfg = load_pipeline_scheduler_config(p)
    assert cfg.enabled is False


def test_malformed_section_raises_valueerror(tmp_path: Path) -> None:
    p = tmp_path / "pipeline.yaml"
    p.write_text("pipeline_scheduler:\n  enabled: not_a_bool\n  sweep_interval_s: -5\n")
    with pytest.raises(ValueError, match="pipeline_scheduler"):
        load_pipeline_scheduler_config(p)


def test_top_level_not_mapping_raises_valueerror(tmp_path: Path) -> None:
    p = tmp_path / "pipeline.yaml"
    p.write_text("- item1\n- item2\n")
    with pytest.raises(ValueError, match="expected a YAML mapping"):
        load_pipeline_scheduler_config(p)


def test_sweep_interval_s_minimum_one(tmp_path: Path) -> None:
    p = tmp_path / "pipeline.yaml"
    p.write_text("pipeline_scheduler:\n  enabled: false\n  sweep_interval_s: 0\n")
    with pytest.raises(ValueError, match="pipeline_scheduler"):
        load_pipeline_scheduler_config(p)


def test_frozen_immutable() -> None:
    cfg = PipelineSchedulerConfig(enabled=True, sweep_interval_s=10)
    with pytest.raises(ValidationError, match="frozen"):
        cfg.enabled = False  # assignment is legal to mypy but raises at runtime (frozen pydantic)
