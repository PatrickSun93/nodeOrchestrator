# LLM Layer

## Why this layer exists

Per `handoff.md` §3.1, the project's load-bearing architecture rule is
that decision paths are code and content generation is LLM. The LLM
layer is the **transport** for content generation: every code path
that needs language understanding, generation, or structured-output
shaping calls into here, and nowhere else.

Routing, gating, scoring, model selection, fallback, health probing —
all of this is decision-path code in this layer's `router.py`,
`config_loader.py`, `health_check.py`. The LLM is consulted only via
`LLMProvider.call()`, never to make architectural choices.

Every call carries an `LLMPurpose` (`purposes.py`), so the audit log
shows what each LLM call was for. PR template Q1 ("why couldn't this
LLM call be done in code?") is enforced against this field's call sites.

## Three-layer configuration

Three YAML files form a chain. See ADR-002 for the rationale.

```
config/llm_providers.yaml      ← physical connections
        │
        ▼ (referenced by `provider`)
config/llm_models.yaml         ← model profiles
        │
        ▼ (referenced by `default_model`, `fallback_chain`)
config/agents/<role>.yaml      ← per-agent llm_config block
```

### Layer 1 — providers

A "provider" is a physical connection: `https://api.deepseek.com/v1`,
the local `claude` CLI, an Ollama endpoint at `localhost:11434`. The
yaml entry has a `type` (one of `openai_compatible`, `claude_code_cli`,
`mock`) plus type-specific `params` (base URL + key env name; CLI path;
…).

Adding a new provider connection is one yaml entry.

### Layer 2 — models

A "model" is a profile attached to a provider: `claude_code_opus_47`
runs through `anthropic_via_claude_code` with model arg
`claude-opus-4-7` and capability `effort` (default xhigh).
`deepseek_v4_flash` runs through `deepseek` with capability `tools`.

Multiple agents can reference the same model id. Swapping a model's
underlying parameters (effort default, cost data, deprecation) propagates
to every consumer without touching agent files.

### Layer 3 — agents

Each agent's yaml has an `llm_config` block:

```yaml
llm_config:
  default_model: claude_code_opus_47
  fallback_chain: [claude_code_opus_47, claude_code_sonnet_46, deepseek_v4_pro]
  temperature: 0.3
  required_capabilities: []
```

`fallback_chain[0] == default_model` is enforced by validator (the
default is conceptually the head of the chain; explicitly listing it
in both fields makes the yaml self-documenting).

`required_capabilities` is the routing constraint: a model in the chain
that doesn't satisfy these is skipped. The canonical case is
operator's `[tools]` — this is what prevents accidentally pointing
operator at a Claude Code model.

## Why `effort_level` lives on the model profile

The Claude Code CLI accepts an effort flag (`minimal`/`low`/
`medium`/`high`/`xhigh`) that controls reasoning depth. Two places to
park its default:

1. **Agent yaml.** Each agent decides "this is how hard I want to think."
2. **Model profile.** Each model entry specifies the default effort for
   that model; agents inherit unless they explicitly override.

The model profile wins (ADR-002, decision 4). Reasoning:

- Effort is a *model-level* property, not a task-level one. `Opus 4.7`
  at `xhigh` is a different cost/latency/quality point than `Opus 4.7`
  at `medium`. Agents care about the *outcome*; the effort that gets
  there is a property of the chosen model.
- If an agent yaml encoded effort, switching from Opus to Sonnet would
  also need an effort adjustment (Sonnet at `xhigh` is excessive).
  Effort-on-model means the swap is one line in the agent yaml.
- Per-agent override is supported via `LLMRequest.effort_level`, but
  agents shouldn't take it. The yaml schema deliberately omits an
  `effort_level` field on `AgentLLMConfig` to discourage this.

## Provider protocol

Every provider implementation satisfies `LLMProvider` (`protocol.py`):

```python
class LLMProvider(Protocol):
    @property
    def provider_id(self) -> ProviderId: ...
    def can_use_orchestrator_tools(self) -> bool: ...
    def health_check(self) -> bool: ...
    def call(self, request: LLMRequest, model: ModelProfile) -> LLMResponse: ...
```

`call()` is the workhorse. It is the provider's job to:

- Translate `LLMRequest` into the wire format.
- Make the request.
- Translate the response back to `LLMResponse`, including
  `model_id_used`, `provider_id_used`, `usage`, `latency_ms`, and
  `finish_reason`.
- Categorize errors as `Transient` / `Permanent` / `Unhealthy`.

The provider is **not** responsible for: routing, fallback, tool
execution (that's the agent runtime), recording the call in the event
log (that's the agent runtime), or cost accounting beyond reporting
`Usage`.

## Why Claude Code cannot accept orchestrator tools

See ADR-003 for the full argument. Summary: the Claude Code CLI ships
with its own tool ecosystem (file ops, shell, web fetch) and exposes
*those* tools to Claude. There is no path through the CLI to inject
arbitrary third-party tool definitions. Therefore:

- `ClaudeCodeCliProvider.can_use_orchestrator_tools()` returns `False`.
- An agent with `required_capabilities: [tools]` cannot route to a
  Claude Code model.
- `validate_full_config` catches the canonical
  "operator-pointed-at-Opus-4.7" misconfiguration at startup, not at
  first call.

The user-facing implication: agents needing tools (operator) run
through OpenAI-compatible providers (DeepSeek, Ollama, MLX). Agents
that produce only text (prober, skeptic, divergence_mapper, logger)
can run through Claude Code.

## `LLMPurpose` and audit

`LLMRequest.purpose` is the audit anchor for every LLM call. P1.1's
purposes:

| Purpose | When | Justification gate |
|---|---|---|
| `AGENT_RESPONSE` | Agent runtime issues a turn | Agent IS the LLM call by design |
| `SNAPSHOT_SEMANTIC` | Generating snapshot's free-text fields | Structural fields are code; text is LLM |
| `HYPOTHESIS_CANDIDATE` | Extracting hypotheses from utterances | Goes to candidate pool (NOT promoted) |
| `KEY_NODE_CANDIDATE` | Marking events as significant | Goes to candidate pool |
| `TOOL_OUTPUT_INTERPRET` | Paraphrasing a long tool result | Context-window optimization |
| `TERM_DEFINITION_PROPOSAL` | Proposing a term definition | Goes to approval queue |

Adding a purpose requires an ADR. The intention is: each entry is a
deliberate "we cannot do this in code" statement, defended in the ADR.
Reviewers can grep `LLMPurpose.X` to find every site that uses the
LLM for that role.

## Mock provider

`MockProvider` (`providers/mock.py`) is the test-only deterministic
implementation. Construction takes a `responses` mapping from
`(LLMPurpose, caller_agent_id | None)` to a list of canned reply
strings; `call()` round-robins through the matched key's list.

Lookup order:

1. Exact match: `(request.purpose, request.caller_agent_id)`.
2. Fallback: `(request.purpose, None)` — purpose-only key.
3. Otherwise: raise `MockResponseExhausted`.

Why the tuple key: with a single `AGENT_RESPONSE` purpose covering
all agent roles, tests for prober vs skeptic vs operator need
different mock replies. The tuple key supports per-agent specifics
plus a purpose-only catch-all.

`MockProvider.calls` captures every request for assertions (prompt
content, tools sent, etc.).

## Why sync (not async)

Claude/DeepSeek/Ollama SDKs all expose async clients, and async LLM
calls are the modern default. We chose sync interfaces for P1
nonetheless:

- **One LLM call per agent turn.** Within an agent's response cycle,
  there is no concurrent LLM work. The dominant pattern is sequential.
- **Test ergonomics.** Sync code is easier to assert against. Async
  fixtures require `pytest-asyncio`, async fixtures, and care around
  event-loop reuse — all friction we'd rather not pay before P3.
- **Async reachability.** When concurrent calls do become needed
  (parallel tool execution; multiple agents speaking simultaneously),
  wrapping a sync provider in `concurrent.futures` is straightforward.
  Going from sync to async at the contract is a one-time refactor;
  going from async-everywhere to sync-where-not-needed is harder.

If a future use case demands streaming (e.g., live "agent typing"
indicators in the UI), we'll add a streaming variant of `call()` then,
not retrofit async into the whole stack now.

## Configuration validation flow

`config_loader.py` runs in three steps at startup:

1. `load_providers()` — instantiate each provider class.
2. `load_models()` — validate each model's provider exists and
   `default_effort` matches capabilities.
3. `load_agent_llm_config()` per agent — validate model references.

Then a single `validate_full_config()` call runs the cross-cutting
checks:

- Every model's provider is present.
- Every agent's `default_model` and `fallback_chain` ids exist.
- Every agent with `required_capabilities: [tools]` has at least one
  routable model whose provider returns
  `can_use_orchestrator_tools() == True`.

Validation is **fail-loud at startup**, not lazy at first call. The
canonical operator-pointed-at-Claude-Code misconfiguration surfaces
when you run the orchestrator, not when you first try to use a tool.

`validate_full_config` collects every violation before raising — a
broken agent yaml shouldn't hide three other broken yamls behind it.

## Routing algorithm

`router.select_model_and_provider(agent_config, request, models, providers)`:

```
candidates = []
for model_id in agent_config.fallback_chain:
    profile = models.get(model_id)
    if profile is None:
        candidates.append(reject "model not in registry")
        continue
    missing = required_capabilities - profile.capabilities
    if missing:
        candidates.append(reject f"missing {missing}")
        continue
    provider = providers.get(profile.provider)
    if provider is None:
        candidates.append(reject "provider not in registry")
        continue
    if request.tools and not provider.can_use_orchestrator_tools():
        candidates.append(reject "tools not supported by provider")
        continue
    if not provider.health_check():
        candidates.append(reject "provider unhealthy")
        continue
    candidates.append(accept "matched")
    return RouteResult(profile, provider, tuple(candidates))

raise NoSuitableModelError(decision_trace=candidates)
```

Every candidate is recorded — accepted or rejected — and the trace
is attached to the LLM call event in the audit log. This is the
LLM-layer analog of the autonomy gateway's `decision_trace`. PR
template Q2 ("does every decision function return a decision_trace?")
applies here.

## Adding things

**A new provider connection.** One entry in `llm_providers.yaml`. No
code changes if the type already has a class.

**A new provider type.** New module under `providers/` satisfying
`LLMProvider`; entry in `PROVIDER_TYPE_REGISTRY` in
`config_loader.py`; ADR documenting why a new type was needed.

**A new model.** One entry in `llm_models.yaml`, referencing an
existing provider id. No code changes.

**A new capability.** Add to `Capability` enum; update routing logic
to check it; add to relevant model profiles. ADR if behavioral
implications are non-trivial.

**A new `LLMPurpose`.** Add to enum; explain in ADR why no code path
sufficed for this work. Update mock and test fixtures.
