"""Agy CLI provider — invokes the ``agy`` binary as subprocess.

Similar to the Claude Code CLI provider, this invokes a local CLI tool
and parses the JSON output into an LLMResponse.

Alt-backend support: the optional ``base_url`` field redirects
AGY_BASE_URL in the child subprocess — allowing the CLI to talk to a
trusted proxy or staging endpoint.  Security contract:

- ``base_url`` MUST be in ``trusted_base_urls`` (fail-closed allowlist,
  checked at construction time in ``__post_init__``).  An untrusted URL
  raises ``ConfigError`` immediately.
- The child subprocess env is built explicitly via ``_build_child_env()``,
  which always strips any AGY_BASE_URL inherited from the parent process
  before optionally injecting the allowlisted ``base_url`` value.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field

from orchestrator.llm.exceptions import (
    PermanentProviderError,
    ProviderUnhealthyError,
    ToolsNotSupportedError,
    TransientProviderError,
)
from orchestrator.llm.parsers.agy_cli_output import parse_agy_cli_output
from orchestrator.llm.types import (
    LLMRequest,
    LLMResponse,
    ModelId,
    ModelProfile,
    ProviderId,
)

_TRANSIENT_STDERR_MARKERS: tuple[str, ...] = (
    "rate limit",
    "rate_limit",
    "rate-limited",
    "503",
    "502",
    "504",
    "service unavailable",
    "timeout",
    "connection reset",
    "temporarily unavailable",
)


@dataclass
class AgyCliProvider:
    """Provider wrapping ``agy --json``."""

    provider_id: ProviderId
    cli_path: str = "agy"
    timeout_s: float = 600.0
    base_url: str | None = None
    trusted_base_urls: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.base_url is not None and self.base_url not in self.trusted_base_urls:
            from orchestrator.llm.exceptions import ConfigError

            raise ConfigError(
                f"agy_cli provider: base_url {self.base_url!r} is not in "
                f"trusted_base_urls {self.trusted_base_urls!r}.",
                violations=[f"base_url {self.base_url!r} not in trusted_base_urls"],
            )

    def _build_child_env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k != "AGY_BASE_URL"}
        if self.base_url is not None:
            env["AGY_BASE_URL"] = self.base_url
        return env

    def can_use_orchestrator_tools(self) -> bool:
        # Structural property of the CLI; not a per-instance choice.
        # Do not override.
        return False

    def health_check(self) -> bool:
        if shutil.which(self.cli_path) is None and not (
            self.cli_path.startswith("/") or self.cli_path.startswith(".")
        ):
            return False
        try:
            result = subprocess.run(
                [self.cli_path, "--version"],
                capture_output=True,
                timeout=3,
                check=False,
                env=self._build_child_env(),
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    async def call(
        self,
        request: LLMRequest,
        model: ModelProfile,
        *,
        model_id_requested: ModelId,
    ) -> LLMResponse:
        if request.tools:
            raise ToolsNotSupportedError(
                f"agy_cli provider rejects tool-bearing requests "
                f"(request had {len(request.tools)} tool(s))"
            )

        args: list[str] = [
            self.cli_path,
            "--json",
            "--model",
            model.provider_model_id,
        ]

        if request.temperature is not None:
            args.extend(["--temperature", str(request.temperature)])

        system_text = request.system or ""
        prompt_parts: list[str] = []
        if system_text:
            prompt_parts.append(f"[System]\n{system_text}")
        for msg in request.messages:
            prompt_parts.append(f"[{msg.role.title()}]\n{msg.content}")
        stdin_data = "\n\n".join(prompt_parts).encode("utf-8")

        t0 = time.monotonic()

        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._build_child_env(),
            )
        except FileNotFoundError as exc:
            raise ProviderUnhealthyError(
                f"agy binary not found at {self.cli_path!r}"
            ) from exc
        except OSError as exc:
            raise ProviderUnhealthyError(f"agy CLI launch failed: {exc}") from exc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(input=stdin_data),
                timeout=self.timeout_s,
            )
        except (TimeoutError, asyncio.CancelledError) as exc:
            try:
                process.kill()
                await process.wait()
            except (ProcessLookupError, OSError):
                pass
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise TransientProviderError(
                f"agy_cli timed out after {self.timeout_s}s"
            ) from exc

        latency_ms = int((time.monotonic() - t0) * 1000)
        stdout_str = stdout_bytes.decode("utf-8", errors="replace")
        stderr_str = stderr_bytes.decode("utf-8", errors="replace")

        if process.returncode != 0:
            err_lower = stderr_str.lower()
            if any(marker in err_lower for marker in _TRANSIENT_STDERR_MARKERS):
                raise TransientProviderError(
                    f"agy_cli transient failure (code={process.returncode}): {stderr_str}"
                )
            raise PermanentProviderError(
                f"agy_cli failed with code {process.returncode}:\n{stderr_str}"
            )

        return parse_agy_cli_output(
            raw_stdout=stdout_str,
            request_id=request.request_id,
            model_id_requested=model_id_requested,
            model_id_used=model.id,
            provider_id=self.provider_id,
            latency_ms=latency_ms,
        )
