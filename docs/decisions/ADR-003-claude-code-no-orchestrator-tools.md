# ADR-003: Claude Code provider cannot accept orchestrator tools

**Status:** Accepted — 2026-05-08
**Scope:** Capability declaration of the `claude_code_cli` provider
and the routing constraint it imposes. Companion to ADR-002.

## Context

One of the P1.1 providers is `claude_code_cli`: the orchestrator
shells out to the `claude` binary as a subprocess, which forwards
the request to Anthropic via the user's Claude Code subscription
(typically Max). This routes Anthropic-model LLM calls through quota
the user already owns.

Claude Code, however, is not a thin API wrapper. It is an agentic
CLI with its own baked-in tool ecosystem: `Bash`, `Read`, `Edit`,
`Write`, `Grep`, `Glob`, `WebFetch`, `WebSearch`, MCP integrations,
and so on. When `claude --print` runs, the model has access to those
tools.

Crucially: there is no public path through the CLI surface to inject
*arbitrary* tool definitions defined by a third-party caller (us). The
CLI's tool set is fixed by its own configuration; the caller is a
prompt source, not a tool author.

This matters because the orchestrator agents (especially `operator`)
need to expose their own tools — `read_file`, `search_text`,
`web_search`, plus any P2+ MCP integrations. Those tool definitions
must reach the LLM whose response we then route back through our own
autonomy gateway, event log, and tool execution layer.

## Decisions

### 1. `ClaudeCodeCliProvider.can_use_orchestrator_tools()` returns `False`

The provider hard-codes `False`. Concrete consequences in the
"Concretely" list below.

Concretely:

- The provider's `LLMProvider` Protocol implementation hard-codes
  `False` in this method (not a per-instance config flag).
- The router, before selecting a (model, provider) pair, checks that
  if `LLMRequest.tools` is non-empty then `provider.can_use_orchestrator_tools()`
  must be `True`.
- `config_loader.validate_full_config` catches the static
  misconfiguration: any agent with `required_capabilities: [tools]`
  must have at least one model whose provider answers `True` here. If
  not, startup fails with `ConfigError`.

The implication: agents needing tools (operator, and any future tool-
using agent) run through `openai_compatible` providers — DeepSeek,
Ollama with tool-aware models, MLX with tool-aware models. Agents
producing text only (prober, skeptic, divergence_mapper, logger)
freely use Claude Code or anything else.

## Three architectural strategies considered

The "Claude Code CLI exists; orchestrator agents need tools" tension
admits three architectural approaches at the layer above provider
implementation. Naming and comparing them up front prevents the
"narrow-implementation alternatives" section below from masking the
broader call.

### Strategy 1: boundary by purpose / agent

Hardcode a partition: each `LLMPurpose` (or each agent role) is
declared "may use Claude Code" or "may not." Routing checks the
request's purpose against an allowlist before considering Claude
Code as a candidate.

Why rejected: the constraint is structural to the *provider*
(Claude Code CLI cannot accept orchestrator tools), not to the
*purpose*. A purpose-driven partition would still need updating
every time a new agent role appears or a purpose's tool needs change.
The provider-level check is the boundary that doesn't drift.

### Strategy 2: Claude Code as a compound operation

Treat `claude --print` as a single compound op recorded in the event
stream. The CLI's internal tool calls (Bash, Read, WebFetch, …) run
inside a black box; we record only the wrapping call, not the
internal trajectory.

Why rejected: this violates the "no compound tools" principle from
ADR-001's tool design (handoff.md §5.4 third layer). Compound tools
make agents into dispatchers — the model picks one big lever and the
internal logic is unauditable. We deliberately give agents small,
specific tools so the *recipe* is visible, not just the *outcome*.
Treating Claude Code as a compound would import that anti-pattern
through the back door.

A subtler issue: the orchestrator agent on the *outside* of a Claude
Code call cannot enforce autonomy levels on the *inside* tool uses.
Operator's `propose_edit` runs through the autonomy gateway; if we
let Claude Code run `Edit` internally, the gateway is bypassed.
Strategy 2 would erode the project's safety story to recover one
provider option.

### Strategy 3 (chosen): provider declares capability; routing constrains

Each provider declares `can_use_orchestrator_tools()` as a capability
flag. The router rejects (provider, tools-bearing-request) pairs at
selection time. Agents declare `required_capabilities: [tools]`;
config validation catches the operator-pointed-at-Claude-Code
misconfiguration at startup, not at first call.

This is the chosen strategy because (a) the constraint sits where
the constraint actually exists (provider level), (b) routing logic
is one boolean check, (c) misconfigurations are caught before any
LLM call, (d) future provider changes (e.g., Claude Code adding tool
injection) flip the boolean without touching agents or routing.

The implementation alternatives below (A-D) are choices *within*
strategy 3 — different ways the provider's capability flag could
be exposed.

## Implementation alternatives within strategy 3

### A. Make the flag per-instance configurable

Letting the user toggle `can_use_tools: true` per
`ClaudeCodeCliProvider` instance, on the assumption that future Claude
Code versions might allow tool injection.

Rejected: this is a hard property of the current CLI, not a soft
preference. Letting users override invites
"why-did-this-fail-silently?" debugging when their tools are in the
prompt but not actually exposed to the model. If Claude Code adds tool
injection, the provider class flips its return — one line, one ADR
amendment.

### B. Translate orchestrator tools into Claude Code prompt instructions

Rather than declaring tools to the model, embed tool descriptions in
the system prompt and parse the model's structured text reply for
"please call X tool with args Y."

Rejected: this is the JSON-prompting anti-pattern. We'd be
reinventing tool calls in plaintext, parsing fragile structured
output, losing the structured `tool_use` block, and making error
handling much harder. Tool calls are a first-class API capability for
a reason.

### C. Have operator route through Claude Code anyway, no tools

Rejected by the project requirement: operator's job is to call tools.
A toolless operator is a different agent (and probably should not
exist — it would be a worse-quality utterance generator).

### D. Skip Claude Code provider entirely

Use the Anthropic API directly (which does support tool definitions),
billed against an API key.

Rejected because the user explicitly wants the Max subscription quota
path. P2 may add a `anthropic_api` provider as a third option for
users who prefer (or only have) API billing — that provider will
return `True` for `can_use_orchestrator_tools()` and would be the
right home for tool-using agents that prefer Anthropic models.

## Consequences

**Easier:**

- Routing stays declarative and predictable. No "sometimes tools work
  through Claude Code" edge cases.
- Misconfiguration is loud at startup
  (`validate_full_config` raises a clear `ConfigError`).
- New agents that need tools just declare `required_capabilities: [tools]`
  and the routing system makes the right choice.

**Harder:**

- A user with **only** a Max subscription cannot run `operator` until
  they add a non-Anthropic provider (DeepSeek key, local Ollama). The
  example yaml ships `operator` pointed at DeepSeek with a local-MLX
  fallback — both available in the target user setup.
- Documentation friction: when someone joins and asks "why can't I
  point operator at Opus 4.7?" — this ADR is the answer. Linked from
  `llm-layer.md` and `event-model.md`'s adjacent docs.

**Neutral:**

- Some Anthropic capability (high-quality tool use on Sonnet 4.6) is
  unreachable through this path. P2 `anthropic_api` provider unlocks
  it for users who want it.

## Reversibility

| Aspect | 6-month cost |
|---|---|
| Flipping the boolean | Trivial — one line — *if* Claude Code gains tool injection. The trigger is a Claude Code upgrade, not an internal preference. |
| Adding `anthropic_api` provider as a parallel option | Medium — one new provider class, a few yaml entries. Useful when users with API keys want first-class tool routing through Anthropic models. |
| Removing Claude Code provider entirely | Trivial — yaml entries gone, nobody routes there. Loses the Max-subscription path. |

## References

- `handoff.md` §5.5 (LLM layer, v2)
- `chat-history.md` §17–18 (LLM layer reasoning, v2)
- `docs/architecture/llm-layer.md` §"Why Claude Code cannot accept
  orchestrator tools"
- ADR-002 (companion: three-layer config and where capability flags live)
