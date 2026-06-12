"""Tests for AgyCliProvider — mocks asyncio.create_subprocess_exec
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
from orchestrator.llm.providers.agy_cli import AgyCliProvider
from orchestrator.llm.purposes import LLMPurpose
from orchestrator.llm.types import (
    LLMRequest,
    LLMResponse,
    Message,
    ModelId,
    ModelProfile,
    ProviderId,
    ToolDefinition,
    generate_request_id,
)


def _model() -> ModelProfile:
    return ModelProfile(
        id=ModelId("agy_gemini_flash"),
        provider=ProviderId("agy"),
        provider_model_id="gemini-2.0-flash",
        capabilities=[],
        context_window=1_000_000,
    )


def _request(
    *,
    tools: list[ToolDefinition] | None = None,
    temperature: float | None = None,
    system: str | None = None,
    messages: list[Message] | None = None,
) -> LLMRequest:
    return LLMRequest(
        request_id=generate_request_id(),
        purpose=LLMPurpose.AGENT_RESPONSE,
        messages=messages or [Message(role="user", content="ping")],
        system=system,
        tools=tools or [],
        temperature=temperature,
    )


def _provider() -> AgyCliProvider:
    return AgyCliProvider(
        provider_id=ProviderId("agy"),
        cli_path="agy",
        timeout_s=30.0,
    )


async def _call(
    provider: AgyCliProvider,
    request: LLMRequest,
    model: ModelProfile,
) -> LLMResponse:
    return await AgyCliProvider.call(provider, request, model, model_id_requested=model.id)


def _ok_envelope(content: str = "pong") -> bytes:
    return json.dumps(
        {
            "content": content,
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
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
        self.last_input: bytes | None = None

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        self.last_input = input
        if self._hang:
            await asyncio.sleep(60)
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
    captured: dict[str, Any] = {"calls": [], "procs": []}

    async def fake_exec(*args: Any, **kwargs: Any) -> Any:
        proc = proc_factory(args)
        captured["calls"].append({"args": list(args), "kwargs": kwargs})
        captured["procs"].append(proc)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return captured


# ---------------------------------------------------------------------------
# Tools rejected
# ---------------------------------------------------------------------------


class TestToolsRejection:
    async def test_tools_in_request_raises_tools_not_supported(self) -> None:
        provider = _provider()
        tool = ToolDefinition(name="x", description="y", input_schema={"type": "object"})
        with pytest.raises(ToolsNotSupportedError):
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
        cli_args = captured["calls"][0]["args"]
        assert cli_args[0] == "agy"
        assert "--json" in cli_args
        assert "--model" in cli_args
        assert "gemini-2.0-flash" in cli_args

    async def test_temperature_from_request_passed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _patch_exec(monkeypatch, lambda args: FakeProc(0, _ok_envelope()))
        provider = _provider()
        await _call(provider, _request(temperature=0.7), _model())
        cli_args = captured["calls"][0]["args"]
        assert "--temperature" in cli_args
        i = cli_args.index("--temperature")
        assert cli_args[i + 1] == "0.7"

    async def test_no_temperature_when_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _patch_exec(monkeypatch, lambda args: FakeProc(0, _ok_envelope()))
        provider = _provider()
        await _call(provider, _request(temperature=None), _model())
        cli_args = captured["calls"][0]["args"]
        assert "--temperature" not in cli_args

    async def test_system_none_handled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """system=None (default) must not crash — no System block in stdin."""
        captured = _patch_exec(monkeypatch, lambda args: FakeProc(0, _ok_envelope()))
        provider = _provider()
        await _call(provider, _request(system=None), _model())
        proc: FakeProc = captured["procs"][0]
        assert proc.last_input is not None
        assert b"[System]" not in proc.last_input

    async def test_system_str_sent_as_block(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """system=str should appear as [System]\\n<text> in stdin, not character-split."""
        captured = _patch_exec(monkeypatch, lambda args: FakeProc(0, _ok_envelope()))
        provider = _provider()
        await _call(provider, _request(system="Be concise."), _model())
        proc: FakeProc = captured["procs"][0]
        assert proc.last_input is not None
        stdin_text = proc.last_input.decode()
        assert "[System]\nBe concise." in stdin_text
        # Verify it was NOT split character-by-character
        assert "B\n\ne\n\n " not in stdin_text

    async def test_all_messages_in_stdin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """All roles (user + assistant) must appear in stdin."""
        captured = _patch_exec(monkeypatch, lambda args: FakeProc(0, _ok_envelope()))
        provider = _provider()
        msgs = [
            Message(role="user", content="hello"),
            Message(role="assistant", content="hi there"),
            Message(role="user", content="follow up"),
        ]
        await _call(provider, _request(messages=msgs), _model())
        proc: FakeProc = captured["procs"][0]
        assert proc.last_input is not None
        stdin_text = proc.last_input.decode()
        assert "[User]\nhello" in stdin_text
        assert "[Assistant]\nhi there" in stdin_text
        assert "[User]\nfollow up" in stdin_text

    async def test_model_id_used_is_model_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """model_id_used in response must be model.id, not provider_model_id."""
        _patch_exec(monkeypatch, lambda args: FakeProc(0, _ok_envelope()))
        provider = _provider()
        resp = await _call(provider, _request(), _model())
        assert resp.model_id_used == ModelId("agy_gemini_flash")


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


class TestErrorClassification:
    async def test_filenotfound_raises_unhealthy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_exec(*args: Any, **kwargs: Any) -> Any:
            raise FileNotFoundError("agy not found")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        provider = _provider()
        with pytest.raises(ProviderUnhealthyError, match="not found"):
            await _call(provider, _request(), _model())

    async def test_oserror_raises_unhealthy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_exec(*args: Any, **kwargs: Any) -> Any:
            raise OSError("permission denied")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        provider = _provider()
        with pytest.raises(ProviderUnhealthyError, match="launch failed"):
            await _call(provider, _request(), _model())

    async def test_nonzero_exit_with_rate_limit_is_transient(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_exec(
            monkeypatch,
            lambda args: FakeProc(1, b"", b"Error: rate limit exceeded, try again"),
        )
        provider = _provider()
        with pytest.raises(TransientProviderError, match="transient failure"):
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
        with pytest.raises(PermanentProviderError, match="code 1"):
            await _call(provider, _request(), _model())

    async def test_timeout_raises_transient(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = AgyCliProvider(
            provider_id=ProviderId("agy"),
            cli_path="agy",
            timeout_s=0.05,
        )
        _patch_exec(monkeypatch, lambda args: FakeProc(0, hang=True))
        with pytest.raises(TransientProviderError, match="timed out"):
            await _call(provider, _request(), _model())

    async def test_timeout_kills_subprocess(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = AgyCliProvider(
            provider_id=ProviderId("agy"),
            cli_path="agy",
            timeout_s=0.05,
        )
        proc = FakeProc(0, hang=True)
        _patch_exec(monkeypatch, lambda args: proc)
        with pytest.raises(TransientProviderError):
            await _call(provider, _request(), _model())
        assert proc._killed is True

    async def test_kill_failure_does_not_mask_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = AgyCliProvider(
            provider_id=ProviderId("agy"),
            cli_path="agy",
            timeout_s=0.05,
        )
        proc = FakeProc(0, hang=True)
        proc._kill_error = OSError("access denied")
        _patch_exec(monkeypatch, lambda args: proc)
        with pytest.raises(TransientProviderError, match="timed out"):
            await _call(provider, _request(), _model())

    async def test_cancellation_kills_subprocess_and_propagates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = AgyCliProvider(
            provider_id=ProviderId("agy"),
            cli_path="agy",
            timeout_s=30.0,
        )
        proc = FakeProc(0, hang=True)
        _patch_exec(monkeypatch, lambda args: proc)

        task = asyncio.create_task(_call(provider, _request(), _model()))
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
        provider = AgyCliProvider(
            provider_id=ProviderId("agy"),
            cli_path="definitely_does_not_exist_xyz_123",
        )
        assert provider.health_check() is False

    def test_returncode_zero_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import shutil

        monkeypatch.setattr(shutil, "which", lambda name: "/fake/path/agy")

        def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(
                args=args[0], returncode=0, stdout=b"agy 0.1.0", stderr=b""
            )

        monkeypatch.setattr(subprocess, "run", fake_run)
        provider = AgyCliProvider(provider_id=ProviderId("agy"), cli_path="agy")
        assert provider.health_check() is True

    def test_returncode_nonzero_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import shutil

        monkeypatch.setattr(shutil, "which", lambda name: "/fake/path/agy")

        def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
            return subprocess.CompletedProcess(
                args=args[0], returncode=1, stdout=b"", stderr=b"failed"
            )

        monkeypatch.setattr(subprocess, "run", fake_run)
        provider = AgyCliProvider(provider_id=ProviderId("agy"), cli_path="agy")
        assert provider.health_check() is False

    def test_subprocess_timeout_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import shutil

        monkeypatch.setattr(shutil, "which", lambda name: "/fake/path/agy")

        def fake_run(*args: Any, **kwargs: Any) -> Any:
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=3)

        monkeypatch.setattr(subprocess, "run", fake_run)
        provider = AgyCliProvider(provider_id=ProviderId("agy"), cli_path="agy")
        assert provider.health_check() is False


# ---------------------------------------------------------------------------
# Alt-backend trust boundary (base_url allowlist)
# ---------------------------------------------------------------------------


class TestAllowlist:
    def test_base_url_in_allowlist_is_accepted(self) -> None:
        provider = AgyCliProvider(
            provider_id=ProviderId("test"),
            base_url="https://trusted.example.com",
            trusted_base_urls=["https://trusted.example.com"],
        )
        assert provider.base_url == "https://trusted.example.com"

    def test_base_url_not_in_allowlist_raises_config_error(self) -> None:
        from orchestrator.llm.exceptions import ConfigError

        with pytest.raises(ConfigError, match="not in trusted_base_urls"):
            AgyCliProvider(
                provider_id=ProviderId("test"),
                base_url="https://untrusted.evil.com",
                trusted_base_urls=["https://trusted.example.com"],
            )

    def test_base_url_empty_allowlist_raises_config_error(self) -> None:
        from orchestrator.llm.exceptions import ConfigError

        with pytest.raises(ConfigError):
            AgyCliProvider(
                provider_id=ProviderId("test"),
                base_url="https://somewhere.com",
                trusted_base_urls=[],
            )

    def test_no_base_url_no_validation(self) -> None:
        provider = AgyCliProvider(provider_id=ProviderId("test"))
        assert provider.base_url is None


# ---------------------------------------------------------------------------
# Child env / AGY_BASE_URL stripping
# ---------------------------------------------------------------------------


class TestChildEnv:
    def test_child_env_strips_agy_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGY_BASE_URL", "https://evil-parent.example.com")
        provider = AgyCliProvider(provider_id=ProviderId("test"))
        child_env = provider._build_child_env()
        assert "AGY_BASE_URL" not in child_env

    def test_child_env_injects_allowlisted_base_url(self) -> None:
        provider = AgyCliProvider(
            provider_id=ProviderId("test"),
            base_url="https://trusted.example.com",
            trusted_base_urls=["https://trusted.example.com"],
        )
        child_env = provider._build_child_env()
        assert child_env.get("AGY_BASE_URL") == "https://trusted.example.com"

    def test_child_env_preserves_other_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_CUSTOM_VAR", "custom_value")
        provider = AgyCliProvider(provider_id=ProviderId("test"))
        child_env = provider._build_child_env()
        assert child_env.get("MY_CUSTOM_VAR") == "custom_value"

    async def test_call_strips_agy_base_url_from_subprocess(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AGY_BASE_URL", "https://evil-parent.example.com")
        captured = _patch_exec(monkeypatch, lambda args: FakeProc(0, _ok_envelope()))
        provider = AgyCliProvider(provider_id=ProviderId("test"), cli_path="agy")
        await _call(provider, _request(), _model())
        kwargs = captured["calls"][0]["kwargs"]
        assert "AGY_BASE_URL" not in kwargs["env"]
