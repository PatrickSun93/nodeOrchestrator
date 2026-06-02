"""Pinned boot entry for the LLM layer (ADR-023 D7).

``load_and_validate_llm_layer`` is the single call site a future CLI or
web entry uses to bring the LLM layer up in the correct order:

  load_providers → load_models → load_agent_llm_config files
  → load_global_override → validate_full_config → check_all_providers

On any ``ConfigError`` or provider health failures, it raises a
``StartupError`` with a rendered, actionable message.

Why a top-level module (not ``llm/bootstrap.py``):
startup is cross-cutting across llm + future room/agent loading
(ADR-023 D7 senior fork — ``src/orchestrator/bootstrap.py`` over
``llm/bootstrap.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from orchestrator.llm.config_loader import (
    load_agent_llm_config,
    load_global_override,
    load_models,
    load_providers,
    validate_full_config,
)
from orchestrator.llm.exceptions import (
    ConfigError,
    LLMError,
    NoSuitableModelError,
    StartupError,
)
from orchestrator.llm.health_check import ProviderHealth, check_all_providers
from orchestrator.llm.router import ModelRegistry, ProviderRegistry
from orchestrator.llm.types import AgentLLMConfig, GlobalLLMOverride


@dataclass
class LLMLayer:
    """The fully-loaded, validated LLM layer, ready for routing."""

    providers: ProviderRegistry
    models: ModelRegistry
    agent_configs: dict[str, AgentLLMConfig]
    override: GlobalLLMOverride | None
    health: list[ProviderHealth]


def load_and_validate_llm_layer(config_dir: Path) -> LLMLayer:
    """Boot sequence for the LLM layer (ADR-023 D7).

    Loads providers → models → agent configs → global override →
    validates cross-file consistency → checks provider health.

    S4 is sequenced last in the P2.7 atomic graph because this function
    must render friendly errors for S2 (override) and S3 (allowlist)
    failure modes; those land in S2/S3 first.

    Raises:
        StartupError: any config or health failure, with an actionable
            rendered message (ADR-023 D8). The ``cause`` field carries
            the original ``ConfigError`` or ``NoSuitableModelError``.
    """
    try:
        providers = load_providers(config_dir / "llm_providers.yaml")
    except ConfigError as e:
        raise StartupError(render_startup_error(e), cause=e) from e

    try:
        models = load_models(config_dir / "llm_models.yaml", providers)
    except ConfigError as e:
        raise StartupError(render_startup_error(e), cause=e) from e

    agent_configs: dict[str, AgentLLMConfig] = {}
    agents_dir = config_dir / "agents"
    if agents_dir.is_dir():
        for yaml_path in sorted(agents_dir.glob("*.yaml")):
            try:
                cfg = load_agent_llm_config(yaml_path, models)
            except ConfigError as e:
                raise StartupError(render_startup_error(e), cause=e) from e
            agent_configs[yaml_path.stem] = cfg

    override_path = config_dir / "llm_override.yaml"
    try:
        override = load_global_override(override_path)
    except ConfigError as e:
        raise StartupError(render_startup_error(e), cause=e) from e

    try:
        validate_full_config(providers, models, agent_configs)
    except ConfigError as e:
        raise StartupError(render_startup_error(e), cause=e) from e

    health = check_all_providers(providers)
    unhealthy = [h for h in health if not h.healthy]
    if unhealthy:
        # Render a consolidated health-failure message.
        lines = ["Provider health check failed at startup:"]
        for h in unhealthy:
            lines.append(f"  • {h.provider_id}: {h.error or 'unhealthy'}")
        lines.append("Fix: verify the provider is reachable and credentials are set.")
        msg = "\n".join(lines)
        raise StartupError(msg, cause=None)

    return LLMLayer(
        providers=providers,
        models=models,
        agent_configs=agent_configs,
        override=override,
        health=health,
    )


def render_startup_error(exc: LLMError) -> str:
    """Render a structured LLM exception into a multi-line, actionable message.

    Handles:
    - ``ConfigError``: lists ``.violations``; each includes file + field + reason.
    - ``NoSuitableModelError``: renders ``.decision_trace`` per-candidate.

    The rendered message is meant to be shown to an operator setting up
    the system — it says *what* failed, *which file/field*, and *how to fix*.
    """
    if isinstance(exc, ConfigError):
        return _render_config_error(exc)
    if isinstance(exc, NoSuitableModelError):
        return _render_no_suitable_model(exc)
    return f"LLM startup error: {exc}"


def _render_config_error(exc: ConfigError) -> str:
    lines = [f"Configuration error: {exc}"]
    if exc.violations:
        lines.append(f"\n{len(exc.violations)} violation(s):")
        for v in exc.violations:
            lines.append(f"  • {v}")
        lines.append(
            "\nFix: open the yaml file(s) listed above and correct the highlighted field(s)."
        )
        # Hint for known S2/S3 failure modes.
        for v in exc.violations:
            v_lower = v.lower()
            is_override_violation = any(
                kw in v_lower for kw in ("cost_ceiling", "quality_tier", "on_unknown_cost")
            )
            if is_override_violation:
                lines.append(
                    "  Hint (override): review config/llm_override.yaml — "
                    "cost_ceiling_per_1m_output must be >= 0.0; "
                    "quality_tier must be 'economy', 'balanced', or 'premium'."
                )
            if "trusted_base_urls" in v_lower or "base_url" in v_lower:
                lines.append(
                    "  Hint (alt-backend): add the URL to the trusted_base_urls list "
                    "in llm_providers.yaml under the claude_code_cli provider entry."
                )
    return "\n".join(lines)


def _render_no_suitable_model(exc: NoSuitableModelError) -> str:
    lines = [f"No suitable model: {exc}"]
    if exc.decision_trace:
        lines.append(f"\nRouting trace ({len(exc.decision_trace)} candidate(s) considered):")
        for entry in exc.decision_trace:
            model_id = entry.get("model_id", "?")
            reason = entry.get("reason", "?")
            accepted = entry.get("accepted", False)
            prefix = "  [accepted]" if accepted else "  [rejected]"
            lines.append(f"{prefix} {model_id}: {reason}")
        lines.append(
            "\nFix: check that at least one model in the fallback chain is "
            "healthy and passes required_capabilities + any global override filters. "
            "If cost_ceiling_per_1m_output is set, ensure at least one model's cost "
            "is at or below the ceiling (or remove the ceiling)."
        )
    return "\n".join(lines)
