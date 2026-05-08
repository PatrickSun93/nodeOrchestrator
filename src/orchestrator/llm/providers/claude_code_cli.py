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

from dataclasses import dataclass

from orchestrator.llm.types import (
    LLMRequest,
    LLMResponse,
    ModelProfile,
    ProviderId,
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
        or timeout — does NOT raise."""
        raise NotImplementedError

    async def call(self, request: LLMRequest, model: ModelProfile) -> LLMResponse:
        """Invoke the CLI with the request serialized as input.

        Uses ``asyncio.create_subprocess_exec`` so the orchestrator
        process stays responsive while the CLI runs (potentially several
        minutes at xhigh effort). This is the load-bearing reason the
        provider Protocol is async.

        Build process:

        - ``messages`` and ``system`` are flattened into stdin (the
          CLI's ``--print`` mode reads stdin).
        - ``model.provider_model_id`` is passed as the CLI ``--model``
          argument (e.g., ``claude-opus-4-7``).
        - ``request.effort_level`` (or ``model.default_effort``) maps
          to the CLI's effort flag.
        - ``request.tools`` is ignored at this level — but
          ``can_use_orchestrator_tools`` returns False, so the router
          should never have selected this provider for a tool-bearing
          request. If tools is non-empty here, raise
          ``ToolsNotSupportedError`` (defensive).
        - Output is parsed via
          ``orchestrator.llm.parsers.claude_code_output.parse_claude_code_output``.

        Error categorization:

        - Missing binary → ``ProviderUnhealthyError``.
        - Non-zero exit with a transient body (rate limit, network) →
          ``TransientProviderError``.
        - Non-zero exit with a permanent body (auth, malformed) →
          ``PermanentProviderError``.
        - Timeout → ``TransientProviderError``.
        """
        raise NotImplementedError
