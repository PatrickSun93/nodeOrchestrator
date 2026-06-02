"""Tests for ClaudeCodeCliProvider — mocks asyncio.create_subprocess_exec
and subprocess.run to avoid invoking a real CLI."""

from __future__ import annotations

import asyncio
import json
import subprocess
from typing import Any

import pytest

from orchestrator.llm.exceptions import (
    PermanentProviderError,
    ProviderUnhealthyError,
    ToolsNotSupportedError,
    TransientProviderError,
)
from orchestrator.llm.providers.claude_code_cli import ClaudeCodeCliProvider
from orchestrator.llm.purposes import LLMPurpose
from orchestrator.llm.types import (
    Capability,
    EffortLevel,
    LLMRequest,
    LLMResponse,
    Message,
    ModelId,
    ModelProfile,
    ProviderId,
    ToolDefinition,
    generate_request_id,
)


def _model(default_effort: EffortLevel | None = EffortLevel.HIGH) -> ModelProfile:
    return ModelProfile(
        id=ModelId("claude_code_sonnet_46"),
        provider=ProviderId("cli"),
        provider_model_id="claude-sonnet-4-6",
        capabilities=[Capability.EFFORT],
        default_effort=default_effort,
        context_window=1_000_000,
    )


def _request(
    *,
    tools: list[ToolDefinition] | None = None,
    effort: EffortLevel | None = None,
    system: str | None = None,
) -> LLMRequest:
    return LLMRequest(
        request_id=generate_request_id(),
        purpose=LLMPurpose.AGENT_RESPONSE,
        messages=[Message(role="user", content="ping")],
        system=system,
        tools=tools or [],
        effort_level=effort,
    )


def _provider() -> ClaudeCodeCliProvider:
    return ClaudeCodeCliProvider(
        provider_id=ProviderId("cli"),
        cli_path="claude",
        timeout_s=30.0,
    )


async def _call(
    provider: ClaudeCodeCliProvider,
    request: LLMRequest,
    model: ModelProfile,
) -> LLMResponse:
    """Test wrapper: defaults model_id_requested to model.id."""
    return await ClaudeCodeCliProvider.call(provider, request, model, model_id_requested=model.id)


def _ok_envelope(content: str = "pong") -> bytes:
    return json.dumps(
        {
            "content": [{"type": "text", "text": content}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 5, "output_tokens": 3},
        }
    ).encode("utf-8")


class FakeProc:
    """Stand-in for asyncio.subprocess.Process."""

    def __init__(
        self,
        returncode: int = 0,
        stdout: bytes = b"",
        stderr: bytes = b"",
        hang: bool = False,
    ) -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._hang = hang
        self._killed = False
        self._kill_error: Exception | None = None

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        if self._hang:
            await asyncio.sleep(60)  # never finishes within test timeouts
        return self._stdout, self._stderr

    def kill(self) -> None:
        if self._kill_error is not None:
            raise self._kill_error
        self._killed = True

    async def wait(self) -> int:
        return self.returncode


def _patch_exec(
    monkeypatch: pytest.MonkeyPatch,
    proc_factory: Any,
) -> dict[str, Any]:
    """Patch asyncio.create_subprocess_exec to return proc_factory(args)."""
    captured: dict[str, Any] = {"calls": []}

    async def fake_exec(*args: Any, **kwargs: Any) -> Any:
        captured["calls"].append({"args": list(args), "kwargs": kwargs})
        return proc_factory(args)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return captured


# ---------------------------------------------------------------------------
# Defensive: tools rejected at call site
# ---------------------------------------------------------------------------


class TestToolsRejection:
    async def test_tools_in_request_raises_tools_not_supported(self) -> None:
        provider = _provider()
        tool = ToolDefinition(name="x", description="y", input_schema={"type": "object"})
        with pytest.raises(ToolsNotSupportedError, match="ADR-003"):
            await _call(provider, _request(tools=[tool]), _model())


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    async def test_basic_call_invokes_cli(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _patch_exec(monkeypatch, lambda args: FakeProc(0, _ok_envelope("hello")))
        provider = _provider()
        resp = await _call(provider, _request(), _model())

        assert resp.content == "hello"
        assert resp.finish_reason == "stop"
        # CLI invoked with the right shape
        cli_args = captured["calls"][0]["args"]
        assert cli_args[0] == "claude"
        assert "--print" in cli_args
        assert "--output-format" in cli_args
        assert "json" in cli_args
        assert "--model" in cli_args
        assert "claude-sonnet-4-6" in cli_args  # provider_model_id

    async def test_effort_passed_from_model_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _patch_exec(monkeypatch, lambda args: FakeProc(0, _ok_envelope()))
        provider = _provider()
        await _call(provider, _request(), _model(EffortLevel.XHIGH))

        cli_args = captured["calls"][0]["args"]
        assert "--effort" in cli_args
        i = cli_args.index("--effort")
        assert cli_args[i + 1] == "xhigh"

    async def test_request_effort_overrides_model_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _patch_exec(monkeypatch, lambda args: FakeProc(0, _ok_envelope()))
        provider = _provider()
        # model default is XHIGH; request says LOW
        await _call(provider, _request(effort=EffortLevel.LOW), _model(EffortLevel.XHIGH))
        cli_args = captured["calls"][0]["args"]
        i = cli_args.index("--effort")
        assert cli_args[i + 1] == "low"

    async def test_no_effort_when_neither_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _patch_exec(monkeypatch, lambda args: FakeProc(0, _ok_envelope()))
        provider = _provider()
        await _call(provider, _request(), _model(default_effort=None))
        cli_args = captured["calls"][0]["args"]
        assert "--effort" not in cli_args

    async def test_effort_silently_dropped_for_models_without_capability(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Per ``EffortLevel`` docstring, effort is "Honored only by
        models with EFFORT in their capabilities; silently ignored
        elsewhere." The validator on ``ModelProfile`` prevents
        ``default_effort`` from being set without the capability, but a
        caller can still pass ``LLMRequest.effort_level`` for any model.
        That request must not become a ``--effort`` CLI arg on a
        non-capable model; the CLI would reject as unknown arg and the
        call would fail loudly, contradicting the docstring's
        "silently ignored" promise.
        """
        captured = _patch_exec(monkeypatch, lambda args: FakeProc(0, _ok_envelope()))
        # Model with NO effort capability (e.g., Haiku 4.5 in real config).
        no_effort_model = ModelProfile(
            id=ModelId("model_without_effort"),
            provider=ProviderId("cli"),
            provider_model_id="claude-haiku-4-5",
            capabilities=[],  # critical: no Capability.EFFORT
            context_window=200_000,
        )
        provider = _provider()
        # Caller provides effort_level despite the model not supporting it.
        await _call(provider, _request(effort=EffortLevel.HIGH), no_effort_model)

        cli_args = captured["calls"][0]["args"]
        # The contract: effort silently dropped, no --effort flag.
        assert "--effort" not in cli_args


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


class TestErrorClassification:
    async def test_filenotfound_raises_unhealthy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_exec(*args: Any, **kwargs: Any) -> Any:
            raise FileNotFoundError("claude not found")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        provider = _provider()
        with pytest.raises(ProviderUnhealthyError, match="not found"):
            await _call(provider, _request(), _model())

    async def test_nonzero_exit_with_rate_limit_is_transient(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_exec(
            monkeypatch,
            lambda args: FakeProc(1, b"", b"Error: rate limit exceeded, try again"),
        )
        provider = _provider()
        with pytest.raises(TransientProviderError, match="exited 1"):
            await _call(provider, _request(), _model())

    async def test_nonzero_exit_with_503_is_transient(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_exec(
            monkeypatch,
            lambda args: FakeProc(2, b"", b"upstream returned 503"),
        )
        provider = _provider()
        with pytest.raises(TransientProviderError):
            await _call(provider, _request(), _model())

    async def test_nonzero_exit_without_transient_marker_is_permanent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_exec(
            monkeypatch,
            lambda args: FakeProc(1, b"", b"Authentication failed: bad token"),
        )
        provider = _provider()
        with pytest.raises(PermanentProviderError, match="exited 1"):
            await _call(provider, _request(), _model())

    async def test_timeout_raises_transient(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Provider with very short timeout
        provider = ClaudeCodeCliProvider(
            provider_id=ProviderId("cli"),
            cli_path="claude",
            timeout_s=0.05,
        )
        _patch_exec(monkeypatch, lambda args: FakeProc(0, hang=True))
        with pytest.raises(TransientProviderError, match="timed out"):
            await _call(provider, _request(), _model())

    async def test_kill_failure_does_not_mask_original_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When proc.kill() raises OSError (Windows quirk), the original
        timeout error still surfaces as TransientProviderError."""
        provider = ClaudeCodeCliProvider(
            provider_id=ProviderId("cli"),
            cli_path="claude",
            timeout_s=0.05,
        )
        proc = FakeProc(0, hang=True)
        proc._kill_error = OSError("access denied")
        _patch_exec(monkeypatch, lambda args: proc)
        with pytest.raises(TransientProviderError, match="timed out"):
            await _call(provider, _request(), _model())

    async def test_outer_cancellation_kills_subprocess(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An outer task.cancel() kills the subprocess and propagates
        CancelledError unwrapped (not wrapped as TransientProviderError)."""
        provider = ClaudeCodeCliProvider(
            provider_id=ProviderId("cli"),
            cli_path="claude",
            timeout_s=30.0,  # long enough that cancellation fires first
        )
        proc = FakeProc(0, hang=True)
        _patch_exec(monkeypatch, lambda args: proc)

        task = asyncio.create_task(_call(provider, _request(), _model()))
        # Let the task start so the subprocess is spawned
        await asyncio.sleep(0.01)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert proc._killed is True


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    def test_unknown_binary_returns_false(self) -> None:
        provider = ClaudeCodeCliProvider(
            provider_id=ProviderId("cli"),
            cli_path="definitely_does_not_exist_xyz_123",
        )
        assert provider.health_check() is False

    def test_returncode_zero_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Pretend the binary exists on PATH
        import shutil

        monkeypatch.setattr(shutil, "which", lambda name: "/fake/path/claude")

        # Mock subprocess.run to return a successful CompletedProcess
        def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(
                args=args[0], returncode=0, stdout=b"claude 1.0.0", stderr=b""
            )

        monkeypatch.setattr(subprocess, "run", fake_run)
        provider = ClaudeCodeCliProvider(provider_id=ProviderId("cli"), cli_path="claude")
        assert provider.health_check() is True

    def test_returncode_nonzero_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import shutil

        monkeypatch.setattr(shutil, "which", lambda name: "/fake/path/claude")

        def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(
                args=args[0], returncode=1, stdout=b"", stderr=b"failed"
            )

        monkeypatch.setattr(subprocess, "run", fake_run)
        provider = ClaudeCodeCliProvider(provider_id=ProviderId("cli"), cli_path="claude")
        assert provider.health_check() is False

    def test_subprocess_timeout_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import shutil

        monkeypatch.setattr(shutil, "which", lambda name: "/fake/path/claude")

        def fake_run(*args: Any, **kwargs: Any) -> Any:
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=3)

        monkeypatch.setattr(subprocess, "run", fake_run)
        provider = ClaudeCodeCliProvider(provider_id=ProviderId("cli"), cli_path="claude")
        assert provider.health_check() is False


# ---------------------------------------------------------------------------
# S3: Alt-backend trust boundary (ADR-023 D4-D5)
# ---------------------------------------------------------------------------


class TestS3Allowlist:
    def test_base_url_in_allowlist_is_accepted(self) -> None:
        """Trusted base_url passes construction (no ConfigError)."""
        provider = ClaudeCodeCliProvider(
            provider_id=ProviderId("test"),
            base_url="https://trusted.example.com",
            trusted_base_urls=["https://trusted.example.com"],
        )
        assert provider.base_url == "https://trusted.example.com"

    def test_base_url_not_in_allowlist_raises_config_error(self) -> None:
        """Untrusted base_url raises ConfigError at construction (fail-closed)."""
        from orchestrator.llm.exceptions import ConfigError

        with pytest.raises(ConfigError, match="not in trusted_base_urls"):
            ClaudeCodeCliProvider(
                provider_id=ProviderId("test"),
                base_url="https://untrusted.evil.com",
                trusted_base_urls=["https://trusted.example.com"],
            )

    def test_base_url_empty_allowlist_raises_config_error(self) -> None:
        """Empty allowlist + set base_url raises ConfigError (fail-closed)."""
        from orchestrator.llm.exceptions import ConfigError

        with pytest.raises(ConfigError):
            ClaudeCodeCliProvider(
                provider_id=ProviderId("test"),
                base_url="https://somewhere.com",
                trusted_base_urls=[],
            )

    def test_no_base_url_no_validation(self) -> None:
        """Unset base_url (None) skips allowlist validation entirely."""
        provider = ClaudeCodeCliProvider(
            provider_id=ProviderId("test"),
            # No base_url, no trusted_base_urls needed
        )
        assert provider.base_url is None

    def test_config_error_message_includes_url_and_allowlist(self) -> None:
        """ConfigError message names both the rejected URL and the allowlist."""
        from orchestrator.llm.exceptions import ConfigError

        with pytest.raises(ConfigError) as exc_info:
            ClaudeCodeCliProvider(
                provider_id=ProviderId("test"),
                base_url="https://bad.example.com",
                trusted_base_urls=["https://good.example.com"],
            )
        msg = str(exc_info.value)
        assert "https://bad.example.com" in msg
        assert "trusted_base_urls" in msg

    def test_config_error_has_violations(self) -> None:
        """ConfigError.violations is populated (ADR-023 D5)."""
        from orchestrator.llm.exceptions import ConfigError

        with pytest.raises(ConfigError) as exc_info:
            ClaudeCodeCliProvider(
                provider_id=ProviderId("test"),
                base_url="https://bad.example.com",
                trusted_base_urls=["https://good.example.com"],
            )
        assert len(exc_info.value.violations) == 1
        assert "not in trusted_base_urls" in exc_info.value.violations[0]


class TestS3ChildEnv:
    def test_child_env_clears_anthropic_base_url_when_base_url_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Y2-alpha: parent env ANTHROPIC_BASE_URL=<untrusted> + config base_url=None
        => _build_child_env does NOT contain ANTHROPIC_BASE_URL."""
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://evil-parent.example.com")
        provider = ClaudeCodeCliProvider(provider_id=ProviderId("test"))
        child_env = provider._build_child_env()
        assert "ANTHROPIC_BASE_URL" not in child_env

    def test_child_env_sets_base_url_when_configured(self) -> None:
        """base_url set + allowlisted => child env has ANTHROPIC_BASE_URL=base_url."""
        provider = ClaudeCodeCliProvider(
            provider_id=ProviderId("test"),
            base_url="https://trusted.example.com",
            trusted_base_urls=["https://trusted.example.com"],
        )
        child_env = provider._build_child_env()
        assert child_env.get("ANTHROPIC_BASE_URL") == "https://trusted.example.com"

    def test_child_env_does_not_inherit_parent_base_url_when_allowlisted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even with a parent env value, only the allowlisted config base_url flows to child."""
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://evil-parent.example.com")
        provider = ClaudeCodeCliProvider(
            provider_id=ProviderId("test"),
            base_url="https://trusted.example.com",
            trusted_base_urls=["https://trusted.example.com"],
        )
        child_env = provider._build_child_env()
        assert child_env.get("ANTHROPIC_BASE_URL") == "https://trusted.example.com"
        assert child_env.get("ANTHROPIC_BASE_URL") != "https://evil-parent.example.com"

    def test_child_env_no_base_url_no_anthropic_base_url_key(self) -> None:
        """Unset base_url: child env has no ANTHROPIC_BASE_URL key."""
        provider = ClaudeCodeCliProvider(provider_id=ProviderId("test"))
        child_env = provider._build_child_env()
        assert "ANTHROPIC_BASE_URL" not in child_env

    def test_child_env_preserves_other_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_build_child_env preserves unrelated env vars from parent."""
        monkeypatch.setenv("MY_CUSTOM_VAR", "custom_value")
        provider = ClaudeCodeCliProvider(provider_id=ProviderId("test"))
        child_env = provider._build_child_env()
        assert child_env.get("MY_CUSTOM_VAR") == "custom_value"

    async def test_call_passes_child_env_to_subprocess(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """call() passes the explicit child env (with ANTHROPIC_BASE_URL stripped)
        to asyncio.create_subprocess_exec."""
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://evil-parent.example.com")
        captured = _patch_exec(monkeypatch, lambda args: FakeProc(0, _ok_envelope()))
        provider = ClaudeCodeCliProvider(
            provider_id=ProviderId("test"),
            cli_path="claude",
        )
        await _call(provider, _request(), _model())

        kwargs = captured["calls"][0]["kwargs"]
        assert "env" in kwargs
        assert "ANTHROPIC_BASE_URL" not in kwargs["env"]

    async def test_call_injects_base_url_into_child_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """call() with an allowlisted base_url injects it as ANTHROPIC_BASE_URL
        in the child env passed to asyncio.create_subprocess_exec."""
        captured = _patch_exec(monkeypatch, lambda args: FakeProc(0, _ok_envelope()))
        provider = ClaudeCodeCliProvider(
            provider_id=ProviderId("test"),
            cli_path="claude",
            base_url="https://trusted.example.com",
            trusted_base_urls=["https://trusted.example.com"],
        )
        await _call(provider, _request(), _model())

        kwargs = captured["calls"][0]["kwargs"]
        assert kwargs["env"].get("ANTHROPIC_BASE_URL") == "https://trusted.example.com"

    def test_health_check_passes_child_env_to_subprocess_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """health_check() passes the explicit child env to subprocess.run."""
        import shutil

        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://evil-parent.example.com")
        monkeypatch.setattr(shutil, "which", lambda name: "/fake/path/claude")

        captured_kwargs: dict[str, Any] = {}

        def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
            captured_kwargs.update(kwargs)
            return subprocess.CompletedProcess(
                args=args[0], returncode=0, stdout=b"claude 1.0.0", stderr=b""
            )

        monkeypatch.setattr(subprocess, "run", fake_run)
        provider = ClaudeCodeCliProvider(provider_id=ProviderId("cli"), cli_path="claude")
        provider.health_check()

        assert "env" in captured_kwargs
        assert "ANTHROPIC_BASE_URL" not in captured_kwargs["env"]
