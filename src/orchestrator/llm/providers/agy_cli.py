"""Agy CLI provider — invokes the ``agy`` binary as subprocess.

Similar to the Claude Code CLI provider, this invokes a local CLI tool
and parses the JSON output into an LLMResponse.
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
    Capability,
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
                f"; request had {len(request.tools)} tool(s)"
            )

        args: list[str] = [
            self.cli_path,
            "--json",
            "--model",
            model.provider_model_id,
        ]

        if request.temperature is not None:
            args.extend(["--temperature", str(request.temperature)])
        elif model.default_temperature is not None:
            args.extend(["--temperature", str(model.default_temperature)])

        system_text = "\n\n".join(request.system)
        user_text = "\n\n".join(msg.content for msg in request.messages if msg.role == "user")
        assistant_text = "\n\n".join(msg.content for msg in request.messages if msg.role == "assistant")

        # Basic flattened stdin formulation
        stdin_content = ""
        if system_text:
            stdin_content += f"System: {system_text}\n\n"
        stdin_content += user_text

        t0 = time.monotonic()
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._build_child_env(),
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(input=stdin_content.encode("utf-8")),
                timeout=self.timeout_s,
            )
        except FileNotFoundError as exc:
            raise ProviderUnhealthyError(
                f"agy binary not found at {self.cli_path!r}"
            ) from exc
        except asyncio.TimeoutError as exc:
            raise TransientProviderError(
                f"agy_cli timed out after {self.timeout_s}s"
            ) from exc

        stdout_str = stdout_bytes.decode("utf-8", errors="replace")
        stderr_str = stderr_bytes.decode("utf-8", errors="replace")
        latency_ms = int((time.monotonic() - t0) * 1000)

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
            request_id=request.id,
            model_id_requested=model_id_requested,
            model_id_used=model.provider_model_id,
            provider_id=self.provider_id,
            latency_ms=latency_ms,
        )
