"""Auto-fire configuration for the COUNTDOWN tier (ADR-040 D7).

``CountdownAutoFireConfig`` is a frozen Pydantic model loaded once at
bootstrap from ``config/autonomy.yaml`` § ``countdown_auto_fire``.
Absent file or absent section → default (disabled, fail-closed).
Malformed section → raises ``ValueError`` at startup (refuse-start).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class CountdownAutoFireConfig(BaseModel):
    """Server-level auto-fire config for the COUNTDOWN tier (ADR-040 D7).

    ``enabled`` gates both the stamp path (D2) and the runtime fire path
    (D1 sweeper) — the default OFF preserves byte-identical behaviour to
    today unless an operator deliberately opts in.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = False
    window_s: int = Field(default=300, ge=1)
    sweep_interval_s: int = Field(default=30, ge=1)
    reversibility_floor: int = Field(default=5, ge=0, le=10)


def load_countdown_auto_fire_config(path: Path) -> CountdownAutoFireConfig:
    """Load ``countdown_auto_fire`` section from ``config/autonomy.yaml``.

    Absent file or absent section → returns the default (disabled).
    Malformed section → raises ``ValueError`` (refuse-start; never silently enabled).
    """
    if not path.exists():
        return CountdownAutoFireConfig()
    with path.open() as f:
        raw = yaml.safe_load(f)
    if raw is None:
        return CountdownAutoFireConfig()
    if not isinstance(raw, dict):
        raise ValueError(
            f"{path.name}: expected a YAML mapping at top level, got {type(raw).__name__}"
        )
    section = raw.get("countdown_auto_fire")
    if section is None:
        return CountdownAutoFireConfig()
    try:
        return CountdownAutoFireConfig.model_validate(section)
    except ValidationError as exc:
        raise ValueError(
            f"{path.name}: countdown_auto_fire: {exc}"
        ) from exc
