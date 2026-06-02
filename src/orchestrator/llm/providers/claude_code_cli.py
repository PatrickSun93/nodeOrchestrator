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

Alt-backend support (ADR-023 D4-D5):

The optional ``base_url`` field redirects ANTHROPIC_BASE_URL in the
child subprocess — allowing the CLI to talk to a trusted proxy or
staging endpoint.  Security contract (Y2-alpha MUST-FIX):

- ``base_url`` MUST be in ``trusted_base_urls`` (fail-closed allowlist,
  checked at construction time in ``__post_init__``).  An untrusted URL
  raises ``ConfigError`` immediately — the provider never reaches the
  subprocess call stage.
- The child subprocess env is built explicitly via ``_build_child_env()``,
  which always strips any ANTHROPIC_BASE_URL inherited from the parent
  process before optionally injecting the allowlisted ``base_url`` value.
  This prevents a hostile parent-env value from bypassing the D5 allowlist.
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

    base_url: str | None = None
    """Alt-backend endpoint. When set, must be in ``trusted_base_urls`` (D5 allowlist).
    Plumbed to the subprocess env as ANTHROPIC_BASE_URL (the claude CLI honors it).
    Unset (None) = default Anthropic endpoint."""

    trusted_base_urls: list[str] = field(default_factory=list)
    """Allowlist of trusted base URLs. A non-None ``base_url`` must be a member;
    otherwise ConfigError at startup (ADR-023 D5 fail-closed)."""

    def __post_init__(self) -> None:
        """Validate allowlist at construction (ADR-023 D5 fail-closed)."""
        if self.base_url is not None and self.base_url not in self.trusted_base_urls:
            from orchestrator.llm.exceptions import ConfigError

            raise ConfigError(
                f"claude_code_cli provider: base_url {self.base_url!r} is not in "
                f"trusted_base_urls {self.trusted_base_urls!r}. "
                f"Add the URL to trusted_base_urls to authorize this redirect "
                f"(ADR-023 D5 fail-closed allowlist).",
                violations=[f"base_url {self.base_url!r} not in trusted_base_urls"],
            )

    def _build_child_env(self) -> dict[str, str]:
        """Build the child subprocess env, explicitly controlling ANTHROPIC_BASE_URL.

        Never inherits ANTHROPIC_BASE_URL from the parent process (Y2-alpha
        MUST-FIX: a parent-env value would bypass the D5 allowlist). When
        ``base_url`` is set (and has already passed allowlist validation in
        ``__post_init__``), it is injected into the child env.
        """
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_BASE_URL"}
        if self.base_url is not None:
            env["ANTHROPIC_BASE_URL"] = self.base_url
        return env

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
                env=self._build_child_env(),
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
        # Note: if outer cancellation happens AGAIN while we're awaiting
        # proc.wait() in cleanup, the second CancelledError will propagate
        # out, bypassing the `if isinstance(e, asyncio.CancelledError)`
        # branch below. Net behavior: still CancelledError out, just via
        # a different path. Acceptable since the contract is "cancellation
        # propagates", not "cancellation propagates through this exact line".
        except (TimeoutError, asyncio.CancelledError) as e:
            try:
                proc.kill()
                await proc.wait()
            except (ProcessLookupError, OSError):
                pass
            if isinstance(e, asyncio.CancelledError):
                raise
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
