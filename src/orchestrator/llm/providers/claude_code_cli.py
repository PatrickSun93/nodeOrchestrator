"""Claude Code CLI provider — invokes the ``claude`` binary as subprocess.

Use case: a user with a Max subscription routes Anthropic-model LLM
calls through Claude Code's quota. The provider serializes the
request to the CLI's input format, runs ``claude --print
--output-format json``, parses the JSON envelope (in
``parsers/claude_code_output.py``), and returns an ``LLMResponse``.

ADR-003 explains why this provider returns False for
``can_use_orchestrator_tools()``: Claude Code's CLI ships with its
own tool ecosystem (file ops, web fetch, …) baked in and does not
accept arbitrary third-party tool definitions. Agents that require
tools (``required_capabilities: [tools]``) cannot route here, and
``config_loader.validate_full_config`` catches misconfiguration at
startup.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from dataclasses import dataclass

from orchestrator.llm.exceptions import (
    PermanentProviderError,
    ProviderUnhealthyError,
    ToolsNotSupportedError,
    TransientProviderError,
)
from orchestrator.llm.parsers.claude_code_output import parse_claude_code_output
from orchestrator.llm.types import (
    Capability,
    LLMRequest,
    LLMResponse,
    ModelId,
    ModelProfile,
    ProviderId,
)

# Substrings in CLI stderr that suggest a transient (retryable) failure.
# Lowercase comparison; exhaustive enough to cover the common surfaces
# without false-positive-classifying genuine bugs as transient.
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
class ClaudeCodeCliProvider:
    """Provider wrapping ``claude --print --output-format json``."""

    provider_id: ProviderId
    cli_path: str = "claude"
    """Absolute path or PATH-resolved binary name. Default ``claude``
    works if the CLI is on PATH after ``npm install -g @anthropic/claude-code``."""

    timeout_s: float = 600.0
    """Generous default — Claude Code at ``xhigh`` effort can run
    several minutes on hard prompts. Health checks use a separate
    short timeout."""

    def can_use_orchestrator_tools(self) -> bool:
        # Structural property of the CLI; not a per-instance choice.
        # See ADR-003. Do not override.
        return False

    def health_check(self) -> bool:
        """``claude --version`` subprocess, expect exit code 0 within
        ~3 seconds. Returns False on missing binary, non-zero exit,
        or timeout — does NOT raise.
        """
        if shutil.which(self.cli_path) is None and not (
            self.cli_path.startswith("/") or self.cli_path.startswith(".")
        ):
            # PATH-resolved name not found and not an absolute path: skip
            # the subprocess attempt entirely.
            return False
        try:
            result = subprocess.run(
                [self.cli_path, "--version"],
                capture_output=True,
                timeout=3,
                check=False,
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
        """Invoke the CLI with the request serialized as stdin.

        Uses ``asyncio.create_subprocess_exec`` so the orchestrator
        process stays responsive while the CLI runs (potentially
        several minutes at xhigh effort). This is the load-bearing
        reason the provider Protocol is async.

        Build process:

        - ``messages`` and ``system`` are flattened into stdin (the
          CLI's ``--print`` mode reads stdin).
        - ``model.provider_model_id`` is passed as the CLI's
          ``--model`` argument.
        - ``request.effort_level`` (or ``model.default_effort``) maps
          to the CLI's effort flag.
        - ``request.tools`` is rejected defensively: per ADR-003,
          ``can_use_orchestrator_tools()`` returns False, so the router
          should never select this provider for a tool-bearing request.
          If somehow we get here with tools, raise ``ToolsNotSupportedError``.
        - Output is parsed via ``parse_claude_code_output``.

        Error categorization:

        - Missing binary → ``ProviderUnhealthyError``.
        - Timeout → ``TransientProviderError``.
        - Non-zero exit with a transient stderr marker → ``TransientProviderError``.
        - Non-zero exit otherwise → ``PermanentProviderError``.
        """
        if request.tools:
            raise ToolsNotSupportedError(
                f"claude_code_cli provider rejects tool-bearing requests "
                f"(see ADR-003); request had {len(request.tools)} tool(s)"
            )

        args: list[str] = [
            self.cli_path,
            "--print",
            "--output-format",
            "json",
            "--model",
            model.provider_model_id,
        ]
        effort = request.effort_level or model.default_effort
        # Per ``EffortLevel`` docstring: "Honored only by models with
        # EFFORT in their capabilities; silently ignored elsewhere."
        # ModelProfile's _check_effort_capability validator prevents
        # default_effort being set without the capability, but a caller
        # can still pass LLMRequest.effort_level for any model. Drop
        # silently rather than passing --effort to a model that doesn't
        # accept it (the CLI would reject as unknown argument and the
        # call would fail loudly — contradicting the docstring).
        # `--effort <level>` flag verified against installed claude CLI
        # via `claude --help` (2026-05-08); accepted values mirror
        # EffortLevel exactly: low | medium | high | xhigh | max.
        if effort is not None and Capability.EFFORT in model.capabilities:
            args.extend(["--effort", effort.value])

        prompt_parts: list[str] = []
        if request.system:
            prompt_parts.append(f"[System]\n{request.system}")
        for msg in request.messages:
            prompt_parts.append(f"[{msg.role.title()}]\n{msg.content}")
        stdin_data = "\n\n".join(prompt_parts).encode("utf-8")

        start = time.perf_counter()

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as e:
            raise ProviderUnhealthyError(f"claude CLI not found: {self.cli_path!r}") from e
        except OSError as e:
            raise ProviderUnhealthyError(f"claude CLI launch failed: {e}") from e

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin_data),
                timeout=self.timeout_s,
            )
        except TimeoutError as e:
            try:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
            raise TransientProviderError(f"claude CLI timed out after {self.timeout_s}s") from e

        latency_ms = int((time.perf_counter() - start) * 1000)

        if proc.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace")
            stderr_lower = stderr_text.lower()
            transient = any(marker in stderr_lower for marker in _TRANSIENT_STDERR_MARKERS)
            err_msg = f"claude CLI exited {proc.returncode}: {stderr_text[:500]}"
            if transient:
                raise TransientProviderError(err_msg)
            raise PermanentProviderError(err_msg)

        return parse_claude_code_output(
            stdout.decode("utf-8", errors="replace"),
            request_id=request.request_id,
            model_id_requested=model_id_requested,
            model_id_used=model.id,
            provider_id=self.provider_id,
            latency_ms=latency_ms,
        )
