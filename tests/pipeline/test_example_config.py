"""T6: validate example_pipeline.json against PipelineDefinition (ADR-041 D4)."""

from __future__ import annotations

import json
from pathlib import Path

from orchestrator.pipeline.schema import PipelineDefinition


def test_example_pipeline_validates() -> None:
    """Example pipeline fixture loads and validates against PipelineDefinition."""
    fixture = Path(__file__).parent / "fixtures" / "example_pipeline.json"
    assert fixture.exists(), f"fixture not found: {fixture}"
    data = json.loads(fixture.read_text())
    defn = PipelineDefinition.model_validate(data)
    assert len(defn.sources) == 3
    kinds = {s.kind for s in defn.sources}
    assert kinds == {"web", "rss", "file"}
    assert len(defn.analysis_prompts) == 3


def test_example_pipeline_has_no_schedule_fields() -> None:
    """Example config must not contain any P5.1b schedule fields (ADR-041 D10)."""
    fixture = Path(__file__).parent / "fixtures" / "example_pipeline.json"
    raw = fixture.read_text()
    for field in ("cron", "interval", "next_fire", "schedule"):
        assert field not in raw, f"schedule field {field!r} found in example — must be P5.1b only"
