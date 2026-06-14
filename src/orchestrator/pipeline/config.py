"""Pipeline scheduler configuration (ADR-042 D7).

``PipelineSchedulerConfig`` mirrors ``CountdownAutoFireConfig`` exactly:
frozen Pydantic model, loaded once at bootstrap from ``config/pipeline.yaml``
§ ``pipeline_scheduler``.  Absent file / absent section → default (disabled,
fail-closed).  Malformed section → raises ``ValueError`` at startup
(refuse-start, never silently enabled).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class PipelineSchedulerConfig(BaseModel):
    """Server-level config for the recurring pipeline scheduler (ADR-042 D7).

    ``enabled`` gates both boot re-arm and the runtime sweeper — the default
    OFF preserves byte-identical behaviour to P5.1a unless an operator
    deliberately opts in.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = False
    sweep_interval_s: int = Field(default=60, ge=1)


def load_pipeline_scheduler_config(path: Path) -> PipelineSchedulerConfig:
    """Load ``pipeline_scheduler`` section from ``config/pipeline.yaml``.

    Absent file or absent section → returns the default (disabled).
    Malformed section → raises ``ValueError`` (refuse-start; never silently enabled).
    """
    if not path.exists():
        return PipelineSchedulerConfig()
    with path.open() as f:
        raw = yaml.safe_load(f)
    if raw is None:
        return PipelineSchedulerConfig()
    if not isinstance(raw, dict):
        raise ValueError(
            f"{path.name}: expected a YAML mapping at top level, got {type(raw).__name__}"
        )
    section = raw.get("pipeline_scheduler")
    if section is None:
        return PipelineSchedulerConfig()
    try:
        return PipelineSchedulerConfig.model_validate(section)
    except ValidationError as exc:
        raise ValueError(f"{path.name}: pipeline_scheduler: {exc}") from exc
