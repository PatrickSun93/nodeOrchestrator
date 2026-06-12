"""LLM layer data types.

Shapes for requests, responses, model profiles, provider connections,
and the agent-side LLM config block. The provider Protocol
(``protocol.py``) operates on these.

Why every shape is Pydantic with ``frozen=True, extra="forbid"``:
overlapping defense (see docs/architecture/event-model.md) — type
system catches mutations and unknown fields at construction time;
serialization round-trips are stable; tests construct these by name
without hitting drift.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any, Literal, NewType

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orchestrator.llm.purposes import LLMPurpose

# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------

ModelId = NewType("ModelId", str)
"""A model id from llm_models.yaml — the keys of the ``models:`` map.
Specific values live in yaml, never in source."""

ProviderId = NewType("ProviderId", str)
"""A provider id from llm_providers.yaml — the keys of the
``providers:`` map. Specific values live in yaml, never in source."""

RequestId = NewType("RequestId", str)
"""Per-call uuid for trace correlation across event log entries."""


def generate_request_id() -> RequestId:
    """Generate a new request id. Format: ``llmreq_<32-hex>``."""
    return RequestId(f"llmreq_{uuid.uuid4().hex}")


# ---------------------------------------------------------------------------
# Provider type and capability vocabulary
# ---------------------------------------------------------------------------


class ProviderType(StrEnum):
    """Physical provider implementations.

    Adding a new provider type requires a new module under
    ``orchestrator.llm.providers`` plus an entry in the registry map
    in ``config_loader``. See ADR-002 for the P1 set.
    """

    AGY_CLI = "agy_cli"
    """Antigravity CLI (agy) using standard IO interface."""

    OPENAI_COMPATIBLE = "openai_compatible"
    """DeepSeek, Ollama, MLX local, OpenAI itself, anything speaking
    the OpenAI Chat Completions API."""

    CLAUDE_CODE_CLI = "claude_code_cli"
    """The ``claude`` CLI invoked as a subprocess. Used to route
    Anthropic models through a Max subscription's quota. Cannot accept
    orchestrator tools; see ADR-003."""

    MOCK = "mock"
    """Test-only deterministic provider."""


class Capability(StrEnum):
    """Capabilities a model may declare in ``llm_models.yaml``.

    Routing matches an agent's ``required_capabilities`` against the
    model's ``capabilities``. A model missing a required capability
    is skipped in the fallback chain.
    """

    TOOLS = "tools"
    """The model accepts orchestrator tool definitions in
    ``LLMRequest.tools`` and may emit ``ToolCall`` blocks in
    responses."""

    EFFORT = "effort"
    """The model honors ``LLMRequest.effort_level``. Currently true
    only for Claude Code CLI routing — ADR-002 explains why effort
    is a model-profile property, not an agent one."""

    VISION = "vision"
    """Future — accepts image content blocks."""

    JSON_MODE = "json_mode"
    """Future — native JSON output mode."""


class EffortLevel(StrEnum):
    """Reasoning-effort hint for models that support it.

    Honored only by models with ``EFFORT`` in their capabilities;
    silently ignored elsewhere. See ``llm-layer.md`` §"Why
    effort_level lives in the model profile" — agent yaml should NOT
    override this; the model profile's ``default_effort`` is the
    intended ceiling, set per model not per agent.

    The five values mirror Claude Code CLI's ``--effort <level>``
    argument exactly: ``low | medium | high | xhigh | max``. Verified
    by running ``claude --help`` 2026-05-08. Adding or removing a
    level requires confirming against the installed CLI.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


# ---------------------------------------------------------------------------
# Conversation primitives
# ---------------------------------------------------------------------------


class Message(BaseModel):
    """A single message in the conversation."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None
    """When ``role == "tool"``, links this result back to the
    originating ``ToolCall.id``. None otherwise."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ToolDefinition(BaseModel):
    """An orchestrator tool offered to the model.

    The model decides whether to call; the agent runtime (P1.3)
    actually executes.
    """

    name: str = Field(min_length=1)
    description: str
    input_schema: dict[str, Any]  # JSON Schema; not validated here.

    model_config = ConfigDict(frozen=True, extra="forbid")


class ToolCall(BaseModel):
    """The model's request to call a tool. Execution and gating
    (autonomy check, run, record result) are the agent runtime's
    concern, not the LLM layer's."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, Any]

    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Request and response
# ---------------------------------------------------------------------------


class LLMRequest(BaseModel):
    """A single LLM invocation request.

    Every request carries a ``purpose`` so the audit log explains what
    each LLM call was for. PR template Q1 ("why couldn't this LLM
    call be code?") is enforced at PR review against this field's
    call sites.
    """

    request_id: RequestId
    purpose: LLMPurpose

    # ---- Conversation -------------------------------------------------
    messages: list[Message] = Field(min_length=1)
    system: str | None = None

    # ---- Optional features --------------------------------------------
    tools: list[ToolDefinition] = Field(default_factory=list)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)

    effort_level: EffortLevel | None = None
    """Override of the model profile's default effort. Most agents
    leave this None and inherit. See ``EffortLevel`` for caveats."""

    # ---- Identification / observability -------------------------------
    caller_agent_id: str | None = None
    """The agent on whose behalf this call is made, e.g.
    ``"agent:prober"``. None for non-agent callers (snapshot semantic
    fields, hypothesis extraction, etc.). MockProvider's response
    routing keys on ``(purpose, caller_agent_id)``."""

    extra_params: dict[str, Any] = Field(default_factory=dict)
    """Provider-specific extras. Most callers leave this empty."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Usage(BaseModel):
    """Token usage and cost for one LLM call.

    ``cost_usd`` is None when the provider doesn't expose pricing
    (e.g., Claude Code CLI through a Max subscription — quota
    consumption is opaque to the API surface)."""

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    cache_creation_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0.0)

    model_config = ConfigDict(frozen=True, extra="forbid")


class LLMResponse(BaseModel):
    """A successful response from an LLM provider.

    Note ``model_id_requested`` vs ``model_id_used``: when a fallback
    fired, these differ. Both are recorded so the LLM call event in
    the audit log shows what was asked and what answered.
    """

    request_id: RequestId
    content: str
    tool_calls: list[ToolCall] = Field(default_factory=list)

    model_id_requested: ModelId
    model_id_used: ModelId
    provider_id_used: ProviderId

    usage: Usage
    latency_ms: int = Field(ge=0)
    finish_reason: Literal["stop", "max_tokens", "tool_use", "content_filter", "error"]

    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Configuration types (loaded from YAML)
# ---------------------------------------------------------------------------


class ProviderConnection(BaseModel):
    """One physical provider connection from ``llm_providers.yaml``.

    ``params`` is provider-type-specific:
    - ``openai_compatible``: ``base_url``, ``api_key_env``,
      optional ``extra_headers``, ``timeout_s``.
    - ``claude_code_cli``: ``cli_path``, ``timeout_s``.
    - ``mock``: empty.
    """

    id: ProviderId
    type: ProviderType
    params: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelProfile(BaseModel):
    """One model entry from ``llm_models.yaml``.

    Why this is its own layer (not folded into the agent config):
    multiple agents share a model id; swapping a model's underlying
    parameters (effort default, cost data) propagates to every
    consumer without touching agent files. Per ADR-002.
    """

    id: ModelId
    provider: ProviderId
    """References a ``ProviderConnection.id``. Validated at config-
    load time."""

    provider_model_id: str = Field(min_length=1)
    """Provider-specific id. For openai_compatible, the API model
    name the backend expects. For claude_code_cli, the value passed
    to the CLI's ``--model`` argument."""

    capabilities: list[Capability] = Field(default_factory=list)

    default_effort: EffortLevel | None = None
    """Set only when ``EFFORT`` is in capabilities. See ADR-002 for
    why this lives on the model profile, not on agents."""

    context_window: int = Field(gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)

    cost_per_1m_input: float | None = Field(default=None, ge=0.0)
    cost_per_1m_output: float | None = Field(default=None, ge=0.0)

    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="after")
    def _check_effort_capability(self) -> ModelProfile:
        if self.default_effort is not None and Capability.EFFORT not in self.capabilities:
            raise ValueError(
                f"model {self.id!r} declares default_effort but does not "
                "list 'effort' in capabilities"
            )
        return self


class AgentAutonomyThresholds(BaseModel):
    """The ``autonomy_thresholds`` block of an agent's YAML.

    Encodes the agent's risk appetite for the P1.2 autonomy gate.
    Values are PLACEHOLDER (not load-tested); P1.5+ usage-based tuning
    will refine them. See ADR-005 Decision 3.

    The cross-field invariant ``threshold_auto > threshold_confirm`` is
    enforced here at Pydantic validation time (schema-level enforcement
    per ``feedback_schema_enforcement``). Equal values are rejected
    because they collapse COUNTDOWN_CONFIRM to a zero-width band.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    threshold_auto: int = Field(ge=0, le=10)
    threshold_confirm: int = Field(ge=0, le=10)
    user_intent_modifier: int = Field(ge=0, le=10)

    @model_validator(mode="after")
    def _check_auto_gt_confirm(self) -> AgentAutonomyThresholds:
        if self.threshold_auto <= self.threshold_confirm:
            raise ValueError(
                f"threshold_auto ({self.threshold_auto}) must be strictly greater than "
                f"threshold_confirm ({self.threshold_confirm}). "
                f"Equal values collapse COUNTDOWN_CONFIRM to a zero-width band "
                f"(ADR-005 Decision 4). Increase threshold_auto or decrease "
                f"threshold_confirm."
            )
        return self


class AgentLLMConfig(BaseModel):
    """The ``llm_config`` block of an agent's YAML, plus ``autonomy_thresholds``.

    A full agent YAML (P1.3) will have more fields (persona,
    dissent_dimensions, forbidden_behaviors, speaking_triggers,
    output_schema, cooldown_seconds). This dataclass covers the
    LLM-routing portion (P1.1) and the autonomy threshold block (P1.2).
    """

    default_model: ModelId
    """The model the router tries first."""

    fallback_chain: list[ModelId] = Field(default_factory=list)
    """Models to try AFTER ``default_model`` fails (transient or unhealthy
    errors only — permanent errors raise through). Does NOT include
    ``default_model``; the router walks
    ``[default_model, *fallback_chain]`` internally. Per Principle 9
    term audit — duplicating the default in both fields would be
    one concept under two names.

    An empty list means **no fallback**. The agent is single-point-
    of-failure on ``default_model``: a transient outage on the only
    provider strands the agent until the outage clears. This is
    acceptable for development or single-provider setups (e.g., a
    user with only Claude Code, no DeepSeek key). Production agents
    expected to keep working through provider hiccups should have
    at least one fallback."""

    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, gt=0)

    required_capabilities: list[Capability] = Field(default_factory=list)
    """Models lacking any of these are skipped in the effective fallback
    chain. The router raises ``NoSuitableModelError`` if every candidate
    is rejected."""

    autonomy_thresholds: AgentAutonomyThresholds
    """The agent's risk appetite for the autonomy gate. All three
    fields are required; placeholder values live in example yamls.
    See ADR-005 Decision 3."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="after")
    def _check_default_not_in_chain(self) -> AgentLLMConfig:
        if self.default_model in self.fallback_chain:
            raise ValueError(
                f"default_model ({self.default_model!r}) must not appear in "
                f"fallback_chain ({self.fallback_chain!r}). "
                f"fallback_chain lists alternatives tried AFTER default_model "
                f"fails on transient/unhealthy errors; the router walks "
                f"[default_model, *fallback_chain] internally. "
                f"See ADR-002 decision 3."
            )
        return self


# ---------------------------------------------------------------------------
# Global override (Layer-4, ADR-023 D1)
# ---------------------------------------------------------------------------


class GlobalLLMOverride(BaseModel):
    """Deployment-wide cost/quality override (Layer-4, ADR-023 D1).

    Loaded from ``config/llm_override.yaml`` (optional file).  Absent
    file → ``load_global_override`` returns ``None`` → no override
    applied (original three-layer behavior preserved).

    Constitutional guarantee (ADR-023 D3): this model is consumed
    **only** by ``apply_global_override`` — a pure, zero-I/O function.
    No ``LLMPurpose`` values; no provider calls.
    """

    quality_tier: Literal["economy", "balanced", "premium"] | None = None
    """Reorder the candidate chain:

    - ``"economy"`` → cheapest-first (ascending ``cost_per_1m_output``);
      models with unknown cost sort last.
    - ``"premium"`` → most-capable-first (descending capability count);
      ties preserve original order.
    - ``"balanced"`` / ``None`` → identity (no reorder).
    """

    cost_ceiling_per_1m_output: float | None = Field(default=None, ge=0.0)
    """Drop any model whose ``cost_per_1m_output`` **strictly exceeds**
    this value (USD per 1 M output tokens). ``None`` disables the
    ceiling filter."""

    on_unknown_cost: Literal["keep", "drop"] = "keep"
    """What to do with models that have no ``cost_per_1m_output`` data
    when a ceiling is active.

    - ``"keep"`` (default) — treat unknown-cost models as free; keep
      them in the chain.
    - ``"drop"`` — exclude unknown-cost models conservatively.

    Ignored when ``cost_ceiling_per_1m_output`` is ``None``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
