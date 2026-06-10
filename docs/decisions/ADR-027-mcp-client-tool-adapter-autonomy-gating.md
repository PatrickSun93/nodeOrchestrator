# ADR-027: MCP Client + Tool-Adapter + Autonomy-Gating

**Status:** Accepted — 2026-06-02 (architect-accepted; P3.4 plan-stage dual-lens reviews clean after all-α routing: r0b Y1 sync-over-async timeout (asyncio.wait_for + subprocess kill/wait + hanging-mock test), arch Y1 α-lite-fold (MVP AUTO_EXECUTE-only, confirm-then-execute deferred to GUI-interaction work); constitutional spine — MCP tool-calls through the code autonomy gate, discovery≠permission/fail-closed, feed-the-gate-unchanged, content-gen-only result interpret — and the trust boundary (allowlist + api_key_env + scoped subprocess env, the P2.7-S3 c2 lesson) preserved)

**Scope:** P3.4 — a new `mcp/` package: an MCP **client + stdio transport** + a **generic tool-adapter** that connects external MCP servers and exposes their tools to agents, with **every MCP tool-call routed through the existing code autonomy gate** and external servers treated as a **trust boundary**. Governs: the client/transport (D1), the **constitutional gating spine** (D2 — feed the existing gate, don't change it), the **pre-classify-allowlist mechanism** (D3 — how an MCP tool gets its code-classified reversibility + namespacing), the **trust boundary** (D4), the **tool-adapter + config contract** P3.5 (plugin packaging) / P3.7 (more connectors) bind (D5), the **execution + interpret path** (D6), and the **demo connector** (D7). Does NOT govern: the autonomy gate's decision logic (`score`/`decide_tier`/`emit_gate_decision`/`process_tool_calls` — **unchanged**); plugin packaging (P3.5); remote transports / many connectors (P3.7); the GUI's MCP surfacing.

## Context

The **code autonomy gate** is the chokepoint and is **tool-source-agnostic** (verified):
- `autonomy/scoring.py`: `Operation{tool_id, initiating_agent, user_explicit_intent, params, …}`; `ToolMeta{reversibility: int 0–10, default=0}` (frozen, `extra="forbid"`; **default 0 = irreversible**); `score(op, tools)→int` (raises `UnknownToolError(tool_id)` if `tool_id ∉ tools`); `decide_tier(score, thresholds, intent, *, tool_id)→AutonomyScore` → `AUTO_EXECUTE` (score≥eff_auto) / `COUNTDOWN_CONFIRM` / `HARD_CONFIRM`; `gate()` = score+decide (pure, no I/O).
- `agents/tool_dispatch.py::process_tool_calls(tool_calls, *, agent_id, room_id, current_event, event_store, tools: dict[str, ToolMeta], thresholds)→ToolDispatchResult`: for each `ToolCall{id,name,arguments}` builds an `Operation(tool_id=name, …)` → `emit_gate_decision` → on `UnknownToolError` a `ToolDispatchDecision(refusal_reason="unknown_tool")`; **only `AUTO_EXECUTE` appends a `TOOL_CALL` event** (`ToolCallMeta{tool_name, call_id, params}`); `COUNTDOWN`/`HARD` append no `TOOL_CALL` (await confirm).
- `autonomy/emission.py::emit_gate_decision(...)` appends `autonomy_decision` (success) / `autonomy_refusal` (UnknownToolError) **before** returning/raising.
- `config/tools.yaml` → `load_tools_config(path)→dict[str, ToolMeta]` (per-tool `reversibility`). The `tools` registry flows `run_turn → dispatch_turn → process_tool_calls`.
- **There is no tool-executor** — `process_tool_calls` *records* the gate decision (the `TOOL_CALL` event is the AUTO-approval signal); actually running a tool is a downstream consumer that P3.4 must add for MCP. `TOOL_RESULT`/`TOOL_FAILED` + `ToolResultMeta{call_id, success, output_truncated_at, error_class}` exist; `LLMPurpose.TOOL_OUTPUT_INTERPRET` exists (content-gen) with **no consumer yet**.

So an MCP tool-call is **just a `ToolCall`** — if its `ToolMeta` is in the `tools` registry it gates identically; if not, `UnknownToolError`→refused (ADR-006, fail-closed). P3.4 **plugs MCP into this path; it builds no second decision surface.** There is **no `mcp/` package**; the official `mcp` Python SDK is not a dependency yet.

## Hard requirements — the constitutional spine + trust boundary (NON-NEGOTIABLE; inscribed)

**Spine (Principle 5; roadmap §9):**
1. **MCP tool-calls route through the existing CODE gate** (`process_tool_calls`→`emit_gate_decision`) — the tier comes from `score`+`decide_tier` (code); **no MCP-server-decided autonomy**; the client never auto-executes a call the gate didn't approve.
2. **Reversibility is CODE/config-classified, not server-provided** — each MCP tool's `ToolMeta.reversibility` comes from config (D3); the protocol's `readOnlyHint`/`destructiveHint`/annotations are **advisory at most**, never authoritative; unclassified → not in the registry (D3).
3. **Unregistered MCP tool → fail-closed** (`UnknownToolError`→refused). **Discovery ≠ permission.**
4. **Execution is downstream of gate approval** — the client contacts the server **only** for a tool-call with a `TOOL_CALL` event (the gate's approval record). In the MVP that means **`AUTO_EXECUTE` only**; `COUNTDOWN`/`HARD` are gated-but-not-executed (no confirm-then-execute flow yet — D6, deferred to GUI-interaction work). When that flow lands, a user-confirm appends the `TOOL_CALL` and the same executor runs it unchanged.
5. **Result interpretation = content-gen** (reuse `TOOL_OUTPUT_INTERPRET`; **no new routing/judgment `LLMPurpose`**) — the LLM **describes** the (untrusted) result; never routes/gates/executes on it.
6. **No routing/judgment in `mcp/`** — transport + adapter (+ post-gate execution) only.

**Trust boundary (the P2.7-S3 pattern, magnified):**
7. **Server allowlist** — only explicitly-declared, opt-in servers are connectable; a non-allowlisted server is refused.
8. **Credential indirection** — secrets via `api_key_env` (no plaintext in config), per-server scoped.
9. **Untrusted results** — size-limit the result; treat it as **untrusted external data** in the interpret prompt; no tool-result drives a routing/autonomy decision.
10. **Subprocess isolation + fail-closed** — a server crash/hang/timeout/malformed-protocol **fails the tool-call closed** (never crashes/hangs the orchestrator); the stdio subprocess gets a **minimal scoped env** (the P2.7-S3 **c2 env-inheritance** lesson — do not leak the orchestrator's secrets/full env).

## Decisions

### D1. Client + transport — the official `mcp` Python SDK, stdio (subprocess via npx/uvx); optional `[mcp]` extra

`mcp/` uses the **official `mcp` Python SDK** (`modelcontextprotocol/python-sdk` — `ClientSession` + `stdio_client`) for the MVP, added as an **optional `[mcp]` dependency extra** (like `[api]`; core stays importable without it). **Transport = stdio** only (a local subprocess server the user launched via `npx`/`uvx` — the most-trusted tier, consistent with the `claude_code_cli` subprocess pattern); SSE/streamable-http (remote = a larger trust surface) deferred. **Sync bridge + bounded-timeout (R0-B Y1 → α, MUST-FIX — HR#10 hang→fail-closed).** The SDK is async but the orchestrator (`run_turn`, `event_store`, the gate) is **sync** — `mcp/` runs the async client on a **managed event loop** and exposes a **sync** surface. Unlike P3.2's `llm_adapter` (whose timeout came for free from the HTTP client's internal timeout), a **stdio subprocess read has no built-in timeout** — a malicious/broken server that never responds to `connect`/`tools/list`/`tools/call` would block the sync thread **indefinitely**. So the bridge **must** enforce the timeout itself: **every** SDK call is wrapped in **`asyncio.wait_for(<coro>, timeout=<bounded>)`** (i.e. `loop.run_until_complete(asyncio.wait_for(...))`), and **on `TimeoutError` the server subprocess is killed** (`proc.kill()` then `proc.wait()`) — never abandoned as an orphan — and the tool-call **fails closed** (`TOOL_FAILED`). **Bounded timeout values** (config-overridable defaults): `connect`/`tools/list` ≈ **10 s**, `tools/call` ≈ **30 s**. A **deliberately-hanging mock server** test asserts: a hang → the tool-call fails closed **and** the subprocess is killed (no orphan). Reasoned alternative (hand-rolled JSON-RPC) rejected — don't reinvent the protocol.

### D2. The gating spine — feed the existing gate unchanged (HR#1–6)

P3.4 changes **nothing** in `score`/`decide_tier`/`gate`/`emit_gate_decision`/`process_tool_calls`. It **merges MCP tools' `ToolMeta` into the `tools` registry** (namespaced, D3) that already flows into `process_tool_calls`. An MCP tool-call is a `ToolCall{name="mcp__<server>__<tool>", arguments}` — it gates **identically** to a local tool: registered+classified → tier from reversibility; **unregistered → `UnknownToolError`→refused** (HR#3). `mcp/` makes **no autonomy/routing/model decision** (HR#6) — a constitution test forbids `mcp/` referencing `decide_tier`/`emit_gate_decision`/`gate`/`select_model_and_provider` and forbids any `llm/` provider call.

### D3. The pre-classify-allowlist mechanism (architect-ruled — the constitutional crux)

**Only classified+allowlisted MCP tools are callable.** `config/mcp_servers.yaml` declares, per server, the **allowlist of tools with their code-classified reversibility**:

```yaml
servers:
  filesystem:                       # the server allowlist key (HR#7)
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/scoped/dir"]
    api_key_env: null               # credential indirection (HR#8); null = no secret
    env: {}                         # MINIMAL scoped subprocess env additions (HR#10) — not the orchestrator's env
    tools:                          # the pre-classify allowlist (HR#2/#3) — ONLY these are callable
      read_file:     { reversibility: 10 }
      list_directory:{ reversibility: 10 }
      write_file:    { reversibility: 2 }
      move_file:     { reversibility: 1 }
```

At connect, the adapter runs `tools/list` (discovery) and builds a `ToolMeta` **only** for tools present in the config allowlist, keyed `mcp__<server>__<tool>`, with the **config reversibility** (never the server's hints). A discovered-but-**unclassified** tool gets **no `ToolMeta`** → it is **not in the registry** → calling it raises `UnknownToolError`→refused (HR#3, **discovery ≠ permission**, fail-closed). The server's `readOnlyHint`/`destructiveHint`/annotations are **ignored for the tier** (optionally logged advisory-only — they never change the classification; a test asserts a server "safe" hint does not change the tier). **Namespacing:** `mcp__<server>__<tool>` (double-underscore), collision-free vs local tools (none carry the `mcp__` prefix) — a test asserts no collision.

### D4. The trust boundary (architect-ruled posture; HR#7–10)

- **Server allowlist** — only servers declared in `config/mcp_servers.yaml` are connectable; an undeclared server name is refused (fail-closed).
- **Credential indirection** — `api_key_env: <ENV_VAR>` per server; the secret is read from the env var at connect (never inline in config), passed **only** into that server's scoped subprocess env.
- **Untrusted results** — `tools/call` results are **size-limited** (a max-bytes cap; over-cap → truncated with `ToolResultMeta.output_truncated_at`, or rejected); the result is recorded as `TOOL_RESULT` and **content-gen-interpreted** (D6) with an **untrusted-external-data** framing (no auto-action); **no tool-result drives a routing/autonomy decision** (HR#9).
- **Subprocess isolation + fail-closed + scoped env** — a server crash/hang/**timeout**/malformed-protocol **fails the tool-call closed** (a `TOOL_FAILED` event; never crashes/hangs the orchestrator — bounded timeouts on connect + every `tools/call`); the stdio subprocess env is **constructed minimal-scoped** (`{**minimal_base, **server.env, [api_key_env→secret]}`) — **not** the orchestrator's full environment (the c2 env-inheritance lesson; the orchestrator's secrets never leak into a third-party subprocess).

### D5. The tool-adapter + config contract (inscribe-before-producer — P3.5/P3.7 bind it)

- **Adapter:** `mcp_tool → (namespaced_name="mcp__<server>__<tool>", ToolMeta(reversibility=<config>))`; a call `mcp__<server>__<tool>(arguments)` → the SDK `tools/call(<tool>, arguments)` on `<server>`'s session.
- **Config shape** (`config/mcp_servers.yaml`, frozen + `extra="forbid"` Pydantic models, validated by a loader mirroring `load_tools_config`): the D3 shape. It **anticipates plugin-delivery** (P3.5): a plugin can carry an `mcp_servers` block of the **same shape**, and the loader merges plugin-provided server configs into the registry without re-architecting the client (P3.5 wraps; it doesn't reshape).
- The MCP `ToolMeta`s merge into the **same `tools: dict[str, ToolMeta]`** the gate already consumes (built at bootstrap: `load_tools_config(tools.yaml)` ∪ the MCP-discovered namespaced `ToolMeta`s).

### D6. Execution + interpret path (HR#4/#5 — downstream of the gate, content-gen interpret)

- **Execution keys on the `TOOL_CALL` event** — the gate's approval record. An MCP executor (`mcp/execution.py` — transport-driven, **no LLM, no decision**) runs **only** for a `TOOL_CALL` event whose tool is `mcp__*`, calls `tools/call` (bounded timeout, size-limited, fail-closed → `TOOL_RESULT`/`TOOL_FAILED`). It **never** contacts a server without a `TOOL_CALL` event (HR#4 structural).
- **MVP executes `AUTO_EXECUTE` only (arch Y1 → α-lite; scope, not constitutional).** `process_tool_calls` appends a `TOOL_CALL` event **only** for `AUTO_EXECUTE`; `COUNTDOWN_CONFIRM`/`HARD_CONFIRM` append **none** (await confirm) — and **there is no confirm-then-execute flow today** (no flow consumes a user-confirm to append the `TOOL_CALL`; the snapshot's `tool_calls_pending_confirm` only *tracks* pending calls for surfacing). So in the MVP a `COUNTDOWN`/`HARD` MCP tool is **correctly gated but not executed**. This is **constitutionally correct** — the demo's `write_file` (rev 2 → `HARD_CONFIRM` → **not** executed) *is* the constitutional demonstration. **`confirm-then-execute` is GUI-coupled and deferred** to a later GUI-interaction slice (the GUI surfaces the pending call → the user confirms → a `TOOL_CALL` event is appended → the same executor runs it, unchanged). P3.4 **does not** wire a confirm flow (no scope creep); the e2e (D7) demonstrates **AUTO-executes** + **HARD-gated-not-executed**, not confirm-then-execute.
- **Interpret = content-gen, outside `mcp/`** — the (untrusted) `TOOL_RESULT` is interpreted via the **existing** `LLMPurpose.TOOL_OUTPUT_INTERPRET` (a thin wiring in the agent/dispatch layer, **not** `mcp/`), with the prompt framing the result as **untrusted external data** (describe, don't act). **No new `LLMPurpose`** (HR#5).

### D7. Demo connector — the filesystem MCP server (architect-ruled low-risk; senior fork)

The MVP demo connector is the **official filesystem MCP server** (`@modelcontextprotocol/server-filesystem` via `npx`, scoped to a read-only/sandboxed dir). It exposes **both** high-reversibility reads (`read_file`/`list_directory` → reversibility 10 → `AUTO_EXECUTE`) **and** low-reversibility writes (`write_file`/`move_file` → reversibility 1–2 → `HARD_CONFIRM`) — so the e2e **demonstrates the gate's tier discrimination** (read auto-executes; write requires hard-confirm) end-to-end. (Git — `git_log`/`git_diff`, reversibility 10 — is a recorded alternative; filesystem is picked because it exercises both tiers.)

## Considered alternatives

- **Auto-register discovered tools at reversibility 0 (callable-but-always-HARD_CONFIRM)** instead of the allowlist — Rejected (D3, architect-ruled): the **pre-classify allowlist** is the stronger fail-closed posture (an unclassified tool can't be called at all, not merely hard-confirmed); discovery ≠ permission. (The two compose — the allowlist *is* the permission; the conservative default-0 still applies to any allowlisted-but-reversibility-omitted tool.)
- **Trust the server's `readOnlyHint`/`destructiveHint` for the tier** — Rejected, **constitutionally** (HR#2): a malicious/buggy server would lie; the authoritative reversibility is the code classification.
- **Execute inside `process_tool_calls`** — Rejected (D6/HR#6): that would put external I/O + a second decision into the gate path; keying execution on the `TOOL_CALL` event keeps execution downstream + `mcp/` decision-free.
- **Inherit the orchestrator env into the subprocess** — Rejected, **constitutionally** (HR#10): the P2.7-S3 c2 env-leak; the subprocess gets a minimal scoped env.
- **Hand-rolled MCP protocol client** — Rejected (D1): use the official SDK; don't reinvent JSON-RPC.
- **Remote (SSE/http) transport in the MVP** — Rejected (D1): stdio (local, user-launched) is the most-trusted tier; remote is a larger trust surface for later.

## Consequences

**Easier:** real external tools reach agents through the **one** existing gate (no second decision surface); the trust boundary reuses the S3 pattern; P3.5 packages the config without reshaping the client.

**Harder:** a new external-I/O + subprocess concurrency surface (timeouts/crash/hang) to test fail-closed; an async SDK ↔ sync orchestrator bridge; a new `[mcp]` dependency + the node/`npx` server runtime for the demo.

**Neutral:** the pre-classify allowlist means every new MCP tool needs a config classification (the intended friction — discovery ≠ permission). stdio-only is an MVP scope; remote is additive. The interpret wiring is thin (reuses an existing purpose).

## Reversibility

| Decision | 6-month reversal cost |
|---|---|
| D1 official SDK / stdio / `[mcp]` extra | **Low** — a self-contained package + optional dep; adding remote transport is additive. |
| D2 feed-the-gate-unchanged | **Do-not-reverse** — the whole point; the gate stays the sole decision surface. |
| D3 pre-classify allowlist + namespacing | **Medium** — relaxing to auto-register reverses the architect's fail-closed ruling; namespacing is a key-format change. |
| D4 trust boundary | **Do-not-reverse** — the security crux (allowlist / credential indirection / untrusted-result / scoped-env / fail-closed). |
| D5 adapter + config contract | **Medium** — once P3.5/P3.7 bind it, changes are contract migrations (inscribe-before-producer front-loads the cost). |
| D6 execution-on-TOOL_CALL + content-gen interpret | **Low** — the executor + the thin interpret wiring are contained. |
| D7 filesystem demo | **Trivial** — config + a test. |

## References

- `docs/process/architect-briefs/P3.4.md` (the ⭐⭐ spine + ⭐ trust boundary + the 5 decisions).
- `docs/process/senior-plans/P3.4.md` (this ADR's plan; atomic graph, test plan, senior forks).
- `docs/process/reviews/P3.4/external-r0b-prompt.md` (dual-lens R0-B — the malicious-server / subprocess-failure / autonomy-bypass / env-leak cross-family lens).
- `src/orchestrator/autonomy/scoring.py` (`score`/`decide_tier`/`gate`/`ToolMeta`/`UnknownToolError`) + `agents/tool_dispatch.py` (`process_tool_calls` — the path MCP feeds) + `autonomy/emission.py` (`emit_gate_decision`) + `config/tools.yaml` + `llm/config_loader.py::load_tools_config` (the registry MCP joins).
- `src/orchestrator/core/event.py` (`ToolCallMeta`/`ToolResultMeta`; `TOOL_CALL`/`TOOL_RESULT`/`TOOL_FAILED`) + `llm/purposes.py` (`TOOL_OUTPUT_INTERPRET` — the existing content-gen interpret purpose; **no new purpose**).
- ADR-005 (autonomy scoring/tiers/reversibility), ADR-006 (unknown-tool→fail-closed = discovery≠permission), ADR-013 (operator tool dispatch — the path MCP extends), ADR-023 (the bootstrap), the P2.7-S3 review (the trust-boundary + c2 env-inheritance pattern). `handoff.md` §3.3 ("MCP 作为插件不是核心" — the P3.5 relation); roadmap §3(C)/§9.
- **P5.1c note (ADR-043):** The gate logic governing MCP tool autonomy decisions is
  byte-frozen across P5.1c. The pipeline-email actuator is a post-gate layer that
  actuates an already-gated `TOOL_CALL_PENDING` (HARD tier); it does not affect MCP
  tool gating or the autonomy-decision path.
