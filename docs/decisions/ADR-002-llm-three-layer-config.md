# ADR-002: Three-layer LLM Configuration

**Status:** Accepted — 2026-05-08
**Scope:** P1.1 LLM layer config and routing. Establishes the
provider / model / agent split, where effort_level lives, and the
fallback-chain semantic.

## Context

The Orchestrator project must transport LLM calls to multiple
backends:

- Anthropic models (Opus 4.7, Sonnet 4.6, Haiku 4.5) via the user's
  Claude Code CLI quota (Max subscription).
- DeepSeek API (v4 Pro and v4 Flash) for tool-using agents.
- Local Ollama / MLX endpoints as offline fallback.
- Test mocks.

Different agents have different LLM needs:

- **Skeptic** wants the strongest reasoner available (Opus 4.7 at
  xhigh) for dissent quality. Falls back to Sonnet, then DeepSeek pro.
- **Prober / divergence_mapper** want Sonnet 4.6. Falls back to
  DeepSeek flash.
- **Logger** wants stability and cheap tokens (Haiku 4.5 / DeepSeek
  flash).
- **Operator** needs tool support (DeepSeek flash → MLX local).
  Cannot use Claude Code (see ADR-003).

A single user may have all four runtimes (Max sub + DeepSeek + Ollama
+ MLX). Switching one out (cancel the Max sub; replace MLX with a
hosted Mistral) shouldn't require touching every agent yaml.

Per Principle 11 ("environment shapes agent, agent does not shape
itself"), routing decisions belong to a code+config layer, not to the
agents themselves.

## Decisions

### 1. Three layers: providers, models, agents

`config/llm_providers.yaml` defines physical connections (one per
URL/CLI/socket). `config/llm_models.yaml` defines model profiles,
each referencing a provider. `config/agents/<role>.yaml` defines
per-agent llm_config (default_model + fallback_chain), each
referencing models.

The chain is provider ← model ← agent. Each layer is independent.

### 2. Effort level lives on the model profile, not the agent

`ModelProfile.default_effort` is the source of truth for how hard
each model thinks. Agents inherit it. `LLMRequest.effort_level` exists
for ad-hoc overrides but is not a field on `AgentLLMConfig` — agent
yaml deliberately cannot encode it.

Reasoning: effort is a model-level property (Opus-at-xhigh and
Opus-at-medium are different cost/latency/quality points). If agents
encoded effort, swapping models (Opus → Sonnet) would also need
effort tuning (Sonnet at xhigh is overkill); effort-on-model means
the swap is one line in the agent yaml.

### 3. `fallback_chain` does NOT include `default_model`

Both fields are required, but they are non-overlapping:
`fallback_chain` only lists models tried *after* `default_model`
if the primary fails. Router walks `[default_model, *fallback_chain]`
internally.

Why not "first element must equal default": that is the same
concept named twice, violating Principle 9 (term audit).
`default_model` and `fallback_chain[0]` always being equal means
one concept with two names — subtle term accumulation that grows
future complexity. The yaml stays self-documenting as long as
both fields are present: "primary is X, backups are Y, Z."

Pydantic validator: `fallback_chain` must NOT contain
`default_model` (catches accidental duplication).

### 4. Fallback only on transient / unhealthy errors

The router walks the chain on:

- model not in registry (config drift),
- missing required capability,
- provider unhealthy (health_check returned False),
- (at call time) `TransientProviderError` from the call itself.

The router does **not** walk the chain on:

- `PermanentProviderError` (auth, malformed request) — raises through.
- `ToolsNotSupportedError` — raises through (config-validation bug).
- Any other unexpected exception — raises through.

Reasoning: fallbacks are for resilience, not for masking caller bugs.
A 401 should fail loudly so the user knows their key is bad; cycling
through other models would just spend more tokens producing the same
401.

### 5. Validation is fail-loud at startup

`validate_full_config` runs once at startup, collects every
violation, raises one `ConfigError` listing all of them.

Cross-checks include the canonical
"operator-with-tools-pointed-at-Claude-Code" misconfiguration —
caught at startup, not at first tool call.

The "fail-loud at startup, accumulate violations" pattern is general
project discipline (see ADR-001 §"Append-only enforcement"); every
config validator should follow it.

## Considered alternatives

### A. Flat per-agent config

Each agent yaml carries `model_id`, `provider_url`, `api_key_env`
inline. No shared model layer.

Rejected: rotating a provider URL or model id requires editing every
agent. Same model attributes (Sonnet 4.6 context window, cost) get
duplicated and drift.

### B. Two-layer (provider + agent)

Drop the model layer; agents reference providers directly with
inline model overrides.

Rejected: a model is more than (provider, model_id). Capabilities,
effort default, context window, cost — these are model-level and
shouldn't live inside each agent yaml.

### C. Code-only configuration

Define providers / models / agent configs in Python modules.

Rejected: changes require deploys. The user wanted to swap a model
without rebuilding. YAML is the right granularity for "operational
knobs that change without code review."

### D. Effort on agent, not on model

Considered as the natural place ("agent X wants to think hard").

Rejected for the reasons in decision 2: model-swap ergonomics, and
the conceptual fit (effort is a model dial, not a task dial).

## Consequences

**Easier:**

- Adding a new model: one entry in `llm_models.yaml`.
- Adding a new provider: one entry in `llm_providers.yaml`.
- Rotating a model across all agents: one line in `llm_models.yaml`.
- Per-agent overrides: a few lines per agent yaml.
- Audit: every LLM call logs the requested + used model + provider.

**Harder:**

- "I just want to set my key in one file" — the user needs to touch
  the providers yaml, then make sure their model/agent yamls
  reference it. A wizard could collapse this in P3 UI; ad-hoc users
  edit yaml.
- Adding an agent-level concept that should *also* be a model dial
  (e.g., "JSON mode") requires deciding which layer owns it. Default
  rule: model property → model profile; task property → agent.

**Neutral:**

- Three files instead of one. Adds a few hundred lines to the
  starting config but each is small and human-readable.

## Reversibility

| Decision | 6-month cost |
|---|---|
| Three-layer YAML | Collapsing back to two layers: medium (re-flatten ~100 lines, update validators). Worth keeping unless a yaml-tax becomes a real complaint. |
| Effort on model | Moving to agent: low refactor (~20 lines), but defeats the model-swap ergonomic. Don't unless the rule itself is wrong. |
| `fallback_chain` excludes `default_model` | Trivial (re-add validator allowing duplicates, document the change). |
| Fallback only on transient errors | Trivial (change router error handling). |
| Fail-loud startup validation | Trivial (relax to lazy). |

## References

- `handoff.md` §3.1 (decision-path codification)
- `handoff.md` §5.5 (LLM layer specification, v2)
- `chat-history.md` §17–18 (LLM layer reasoning, v2)
- `docs/architecture/llm-layer.md` (full design)
- ADR-003 (companion: why Claude Code can't have orchestrator tools)

## Amendments

### 2026-06-02 (P2.7 / ADR-023) — Implemented (ADR-023 accepted; P2.7 impl)

**Amendment to Decision 1 — add a 4th layer: the global override.**

P2.7-S2 (ADR-023 D1–D3) introduces a deployment-wide cost/quality override that sits **above** the agent layer. The layer model extends from three to four:

**Original (Decision 1):** the chain is provider ← model ← agent. Each layer is independent.

**Amended:** the chain is provider ← model ← agent ← **global override**. The 4th layer (`config/llm_override.yaml`, parsed into `GlobalLLMOverride`) is **optional** (absent file = no override = the original three-layer behavior, unchanged) and **deployment-global** (one per deployment, distinct from the per-agent layer-3 `AgentLLMConfig`).

The 4th layer is a **deterministic code transform**, not a new judgment surface (ADR-023 D2): a pure function `apply_global_override(chain, override, models) -> chain` filters/reorders the candidate `[default_model, *fallback_chain]` over **static `ModelProfile` attributes** (cost, capability count) *before* the router (`select_model_and_provider`) walks it. It **composes with — never bypasses** — Decision 4's fallback semantics: the transformed chain is still subject to the per-candidate required-capability / provider-exists / tools-support / health filters. If the override empties the chain, the router raises `NoSuitableModelError` (Decision 5 fail-loud), never a silent unfiltered fallback.

This amendment is **additive**: every existing config (no `llm_override.yaml`) loads and routes exactly as before; the new `override` parameter on `select_model_and_provider` defaults to `None`. Effort-on-model (Decision 2), `fallback_chain` excludes `default_model` (Decision 3), and fail-loud startup validation (Decision 5) are **unchanged**. Constitutional guarantee (ADR-023 D3): the override path makes **no** `LLMProvider.call` (structural test) and adds **no** routing/judgment `LLMPurpose` — routing stays code (Principle 5; `llm-layer.md:11-14`).

### 2026-06-11 (agy-cli-provider) — Implemented

**Amendment to Decision 5 — register `agy_cli` as a new provider type.**

`ProviderType.AGY_CLI` is added to the enumerated provider set, following the same "new type = new module + `PROVIDER_TYPE_REGISTRY` entry" contract as `CLAUDE_CODE_CLI` and `OPENAI_COMPATIBLE`. The new `AgyCliProvider` wraps the Antigravity (`agy`) CLI subprocess to route Google/Gemini model calls.

Structural stance: `can_use_orchestrator_tools()` returns `False` and `call()` rejects tool-bearing requests with `ToolsNotSupportedError`, mirroring the ADR-003 constraint for `claude_code_cli`. No new `LLMPurpose` is introduced. The provider is a pure additive content-gen surface; constitutional spine and routing logic are unchanged.
