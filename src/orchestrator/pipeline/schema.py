"""Pipeline domain types — definition, run record, result, schedule record (ADR-041 D8 / ADR-042 D2)."""  # noqa: E501

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from orchestrator.sources.schema import Source


class OutputConfig(BaseModel):
    """Output routing options for a pipeline run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    room_prefix: str = Field(default="pipeline", min_length=1)


class PipelineDefinition(BaseModel):
    """Mutable operational config for one pipeline (ADR-041 D8).

    sources:          ordered list of sources to fetch each run.
    analysis_prompts: ordered list of per-branch prompts for fan-out stage.
    output_config:    routing options for the reduce-stage output.

    No schedule fields (cron/interval/next_fire) — those are P5.1b (ADR-041 D10).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    sources: list[Source] = Field(min_length=1)
    analysis_prompts: list[str] = Field(min_length=1)
    output_config: OutputConfig = Field(default_factory=OutputConfig)


@dataclass(frozen=True)
class PipelineRecord:
    """A row from the pipelines side table."""

    pipeline_id: str
    owner_user_id: str
    definition: PipelineDefinition
    enabled: bool
    created_at: int


@dataclass(frozen=True)
class PipelineRunRecord:
    """A row from the pipeline_runs index."""

    run_id: str
    pipeline_id: str
    room_id: str
    owner_user_id: str
    started_at: int
    status: str


@dataclass
class BranchResult:
    """Result of one analyze-branch LLM call."""

    prompt_index: int
    content: str | None  # None if the branch failed
    error: str | None = None


@dataclass
class PipelineRunResult:
    """Full result returned by run_pipeline()."""

    run_id: str
    room_id: str
    succeeded: bool
    branch_results: list[BranchResult] = field(default_factory=list)
    summary: str = ""
    sources_read: int = 0
    branches_succeeded: int = 0
    branches_failed: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "room_id": self.room_id,
            "succeeded": self.succeeded,
            "sources_read": self.sources_read,
            "branches_succeeded": self.branches_succeeded,
            "branches_failed": self.branches_failed,
            "summary": self.summary,
            "error": self.error,
        }


# Schedule kind — interval implemented; cron column kept for forward-compat (ADR-042 D3).
ScheduleKind = Literal["interval", "cron"]


@dataclass(frozen=True)
class PipelineScheduleRecord:
    """A row from the pipeline_schedules side table (ADR-042 D2 / ADR-043 D5)."""

    schedule_id: str
    pipeline_id: str
    owner_user_id: str
    kind: str
    expr: str
    next_fire: int  # epoch-ms; mutable runtime state, updated on every fire
    enabled: bool
    created_at: int
    # Email opt-in 3-state: OFF (email_enabled=False) → DRY-RUN → LIVE (ADR-043 D5)
    email_enabled: bool = False
    email_mode: str = "dry_run"  # "dry_run" | "live"
    email_recipient: str | None = None
