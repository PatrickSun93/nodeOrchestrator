"""Tests for orchestrator/bootstrap.py — LLM layer boot entry (ADR-023 D7-D8).

Coverage:
  §1 (source→sink): load_and_validate_llm_layer returns LLMLayer with all fields.
  §4 (load-bearing message content): render_startup_error message content asserted
      per S2 override and S3 allowlist failure modes.
  §5 (boundary): config errors surface as StartupError, not raw ConfigError.
  §3 (absent override): absent llm_override.yaml → LLMLayer.override is None.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from orchestrator.bootstrap import LLMLayer, load_and_validate_llm_layer, render_startup_error
from orchestrator.llm.exceptions import ConfigError, NoSuitableModelError, StartupError

# ---------------------------------------------------------------------------
# Minimal fixture helpers
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(dedent(content), encoding="utf-8")
    return path


def _write_minimal_config(config_dir: Path) -> None:
    """Write a minimal valid config set (mock provider + one model)."""
    _write(
        config_dir,
        "llm_providers.yaml",
        """
        providers:
          mock_p:
            type: mock
            params: {}
        """,
    )
    _write(
        config_dir,
        "llm_models.yaml",
        """
        models:
          mock_model:
            provider: mock_p
            provider_model_id: mock
            context_window: 1000
            cost_per_1m_input: 1.0
            cost_per_1m_output: 1.0
        """,
    )
    agents_dir = config_dir / "agents"
    agents_dir.mkdir(exist_ok=True)
    _write(
        agents_dir,
        "test_agent.yaml",
        """
        llm_config:
          default_model: mock_model
        autonomy_thresholds:
          threshold_auto: 8
          threshold_confirm: 3
          user_intent_modifier: 5
        """,
    )


# ---------------------------------------------------------------------------
# Happy-path
# ---------------------------------------------------------------------------


class TestLoadAndValidateLLMLayer:
    def test_returns_llm_layer_with_all_fields(self, tmp_path: Path) -> None:
        """load_and_validate_llm_layer returns a populated LLMLayer (§1 source→sink)."""
        _write_minimal_config(tmp_path)
        layer = load_and_validate_llm_layer(tmp_path)
        assert isinstance(layer, LLMLayer)
        assert layer.providers.get("mock_p") is not None  # type: ignore[arg-type]
        assert layer.models.get("mock_model") is not None  # type: ignore[arg-type]
        assert "test_agent" in layer.agent_configs
        assert layer.override is None  # no llm_override.yaml — opt-in

    def test_absent_override_file_yields_none_override(self, tmp_path: Path) -> None:
        """Absent llm_override.yaml → layer.override is None (§3 cleanup)."""
        _write_minimal_config(tmp_path)
        assert not (tmp_path / "llm_override.yaml").exists()
        layer = load_and_validate_llm_layer(tmp_path)
        assert layer.override is None

    def test_override_file_loaded_when_present(self, tmp_path: Path) -> None:
        """Present llm_override.yaml → layer.override is populated."""
        _write_minimal_config(tmp_path)
        _write(
            tmp_path,
            "llm_override.yaml",
            """
            quality_tier: economy
            """,
        )
        layer = load_and_validate_llm_layer(tmp_path)
        assert layer.override is not None
        assert layer.override.quality_tier == "economy"

    def test_no_agents_dir_still_succeeds(self, tmp_path: Path) -> None:
        """No agents/ directory → empty agent_configs, no error."""
        _write(
            tmp_path,
            "llm_providers.yaml",
            """
            providers:
              mock_p:
                type: mock
                params: {}
            """,
        )
        _write(
            tmp_path,
            "llm_models.yaml",
            """
            models:
              mock_model:
                provider: mock_p
                provider_model_id: mock
                context_window: 1000
            """,
        )
        # No agents/ directory
        layer = load_and_validate_llm_layer(tmp_path)
        assert layer.agent_configs == {}


# ---------------------------------------------------------------------------
# Error boundary — ConfigError → StartupError (§5)
# ---------------------------------------------------------------------------


class TestStartupErrorBoundary:
    def test_bad_providers_yaml_raises_startup_error(self, tmp_path: Path) -> None:
        """Malformed providers.yaml → StartupError (not raw ConfigError)."""
        _write(
            tmp_path,
            "llm_providers.yaml",
            """
            providers:
              bad_p:
                type: NONEXISTENT_TYPE
            """,
        )
        _write(tmp_path, "llm_models.yaml", "models: {}")
        with pytest.raises(StartupError):
            load_and_validate_llm_layer(tmp_path)

    def test_bad_models_yaml_raises_startup_error(self, tmp_path: Path) -> None:
        """Malformed models.yaml → StartupError."""
        _write(
            tmp_path,
            "llm_providers.yaml",
            """
            providers:
              mock_p:
                type: mock
                params: {}
            """,
        )
        _write(
            tmp_path,
            "llm_models.yaml",
            """
            models:
              bad_model:
                provider: nonexistent_provider
                provider_model_id: x
                context_window: 100
            """,
        )
        with pytest.raises(StartupError):
            load_and_validate_llm_layer(tmp_path)

    def test_invalid_override_yaml_raises_startup_error(self, tmp_path: Path) -> None:
        """Invalid llm_override.yaml → StartupError (S2 failure mode)."""
        _write_minimal_config(tmp_path)
        _write(
            tmp_path,
            "llm_override.yaml",
            """
            quality_tier: INVALID_TIER
            """,
        )
        with pytest.raises(StartupError) as exc_info:
            load_and_validate_llm_layer(tmp_path)
        # StartupError wraps a ConfigError
        assert isinstance(exc_info.value.cause, ConfigError)

    def test_startup_error_carries_cause(self, tmp_path: Path) -> None:
        """StartupError.cause is the original ConfigError."""
        _write(tmp_path, "llm_providers.yaml", "providers: {bad_p: {type: NOPE}}")
        _write(tmp_path, "llm_models.yaml", "models: {}")
        with pytest.raises(StartupError) as exc_info:
            load_and_validate_llm_layer(tmp_path)
        assert exc_info.value.cause is not None


# ---------------------------------------------------------------------------
# render_startup_error — message content asserted (§4 load-bearing)
# ---------------------------------------------------------------------------


class TestRenderStartupError:
    def test_config_error_with_violations_renders_each_violation(self) -> None:
        """ConfigError violations each appear in the rendered message."""
        exc = ConfigError(
            "config failed",
            violations=["field 'foo' missing", "field 'bar' invalid"],
        )
        msg = render_startup_error(exc)
        assert "foo" in msg
        assert "bar" in msg
        assert "violation" in msg.lower()

    def test_config_error_s2_override_hint(self) -> None:
        """S2 override failure → rendered message contains override hint (§4 load-bearing)."""
        exc = ConfigError(
            "override error",
            violations=["cost_ceiling_per_1m_output must be >= 0"],
        )
        msg = render_startup_error(exc)
        assert "cost_ceiling" in msg
        assert "llm_override.yaml" in msg

    def test_config_error_s3_allowlist_hint(self) -> None:
        """S3 allowlist failure → rendered message mentions trusted_base_urls (§4 load-bearing)."""
        exc = ConfigError(
            "provider error",
            violations=["base_url 'https://evil.example.com' not in trusted_base_urls"],
        )
        msg = render_startup_error(exc)
        assert "trusted_base_urls" in msg

    def test_no_suitable_model_renders_trace(self) -> None:
        """NoSuitableModelError → decision_trace rendered with model ids and reasons."""
        exc = NoSuitableModelError(
            "no suitable model",
            decision_trace=[
                {
                    "model_id": "model_a",
                    "provider_id": "p1",
                    "accepted": False,
                    "reason": "cost_per_1m_output=50.0 exceeds ceiling=10.0",
                },
                {
                    "model_id": "model_b",
                    "provider_id": "p1",
                    "accepted": False,
                    "reason": "provider health_check returned False",
                },
            ],
        )
        msg = render_startup_error(exc)
        assert "model_a" in msg
        assert "model_b" in msg
        assert "ceiling" in msg.lower()
        assert "ceiling" in msg or "cost" in msg

    def test_no_suitable_model_override_filter_hint(self) -> None:
        """NoSuitableModelError with override-filtered trace → hint mentions ceiling (§4)."""
        exc = NoSuitableModelError(
            "all filtered",
            decision_trace=[
                {
                    "model_id": "x",
                    "provider_id": None,
                    "accepted": False,
                    "reason": "global override: cost_per_1m_output=100 exceeds ceiling=5",
                },
            ],
        )
        msg = render_startup_error(exc)
        assert "ceiling" in msg.lower() or "cost" in msg.lower()

    def test_unknown_exception_renders_fallback(self) -> None:
        """Unknown LLMError subclass → fallback message."""
        from orchestrator.llm.exceptions import LLMError

        exc = LLMError("something weird")
        msg = render_startup_error(exc)
        assert "startup error" in msg.lower()


# ---------------------------------------------------------------------------
# StartupError schema (§6)
# ---------------------------------------------------------------------------


class TestStartupErrorSchema:
    def test_startup_error_is_subclass_of_llmerror(self) -> None:
        from orchestrator.llm.exceptions import LLMError

        e = StartupError("test")
        assert isinstance(e, LLMError)

    def test_startup_error_cause_defaults_to_none(self) -> None:
        e = StartupError("msg")
        assert e.cause is None

    def test_startup_error_carries_cause(self) -> None:
        cause = ConfigError("oops")
        e = StartupError("wrapped", cause=cause)
        assert e.cause is cause
        assert str(e) == "wrapped"
