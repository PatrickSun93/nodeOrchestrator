"""Tests for llm/exceptions.py — StartupError (ADR-023 D8).

These tests cover the §4 and §6 criteria for the new StartupError class.
"""

from __future__ import annotations

from orchestrator.llm.exceptions import (
    ConfigError,
    LLMError,
    NoSuitableModelError,
    StartupError,
)


class TestStartupError:
    def test_is_subclass_of_llmerror(self) -> None:
        e = StartupError("boom")
        assert isinstance(e, LLMError)

    def test_message_preserved(self) -> None:
        e = StartupError("actionable message here")
        assert str(e) == "actionable message here"

    def test_cause_defaults_to_none(self) -> None:
        e = StartupError("msg")
        assert e.cause is None

    def test_cause_config_error(self) -> None:
        cause = ConfigError("bad yaml")
        e = StartupError("wrapped", cause=cause)
        assert e.cause is cause
        assert isinstance(e.cause, ConfigError)

    def test_cause_no_suitable_model_error(self) -> None:
        cause = NoSuitableModelError("chain exhausted")
        e = StartupError("wrapped", cause=cause)
        assert e.cause is cause
        assert isinstance(e.cause, NoSuitableModelError)

    def test_str_is_rendered_message_not_cause(self) -> None:
        cause = ConfigError("raw config error text")
        e = StartupError("Human-readable: check your yaml.", cause=cause)
        assert "Human-readable" in str(e)
        assert "raw config error text" not in str(e)
