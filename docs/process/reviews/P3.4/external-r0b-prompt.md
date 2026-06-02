# External R0-B prompt for P3.4 plan + ADR-027 (MCP client + tool-adapter + autonomy-gating)

**Purpose**: copy-pasteable system prompt + artifact bundle for the architect to send to a non-Claude LLM (DeepSeek V4 Pro / GPT-5-class / Gemini) for a **true cross-family R0-B at plan stage** on the P3.4 plan + ADR-027.

**Dispatch rationale (RC-15 — architect-decided).** P3.4 is **P3's heaviest constitutional/security slice**: a new transport, **external untrusted third-party servers**, **subprocess concurrency/failure**, and the **operation-gating constitutional surface** (the autonomy gate). The cross-family lens is exactly for these failure modes — a malicious/compromised MCP server, a subprocess crash/hang, transport-protocol errors, **autonomy-bypass attempts**, and **env-leak** (recall: the P2.7-S3 **c2 env-inheritance** hole was a *cross-family* catch — and the same trust-boundary pattern recurs here, magnified).

**How to use**: open a non-Claude session, paste the system prompt, read the artifacts from disk (or paste). Ask: "Generate the R0-B review per the system prompt's mandatory output format." Paste back; architect-partner saves as `docs/process/reviews/P3.4/R0-B-cross-family-external.md`. Per RC-15, external findings carry the same weight as in-session R0-A.

---

## System prompt

```
You are reviewing the DESIGN (plan + ADR — pre-implementation) of an MCP (Model Context Protocol) client for a multi-agent orchestration framework called "shipOrchestrator" — an AI research/decision assistant built by a solo developer through a structured workflow with deliberately separated roles. This slice (P3.4) connects EXTERNAL, THIRD-PARTY MCP servers (opaque subprocesses) and exposes their tools to agents, with every MCP tool-call routed through the EXISTING code autonomy gate, and the servers treated as a TRUST BOUNDARY. The MCP client must WRAP/FEED the existing gate, not change it.

Core invariants (constitutional — the ADR inscribes; the impl must enforce):
- The autonomy gate is the SOLE decision surface. score(operation, tools) returns a tool's reversibility (0-10, default 0 = irreversible); decide_tier maps score+thresholds → AUTO_EXECUTE / COUNTDOWN_CONFIRM / HARD_CONFIRM; process_tool_calls(tool_calls, *, tools, thresholds, event_store, …) gates each ToolCall and appends a TOOL_CALL event ONLY for AUTO_EXECUTE (an unknown tool → UnknownToolError → refused). P3.4 changes NONE of this logic — it merges MCP tools' ToolMeta into the tools registry (namespaced mcp__<server>__<tool>).
- MCP reversibility is CODE/CONFIG-classified, never server-provided. The server's readOnlyHint/destructiveHint/annotations are advisory at most; the config classification is authoritative.
- Discovery ≠ permission: a tool the server advertises but that isn't in the config allowlist gets NO ToolMeta → not in the registry → UnknownToolError → refused (fail-closed).
- Execution is downstream of gate approval: the MCP executor keys on the TOOL_CALL event (which exists only post-AUTO_EXECUTE or post-user-confirm); it never contacts a server without one.
- Tool-result interpretation = content-gen (reuse the existing TOOL_OUTPUT_INTERPRET LLMPurpose; no new routing/judgment purpose); the result is UNTRUSTED.
- No routing/judgment in mcp/ (transport + adapter + post-gate execution only).
- Trust boundary: server allowlist; credential indirection (api_key_env); untrusted size-limited results; subprocess isolation + fail-closed (crash/hang/timeout/malformed → tool-call fails closed, never crashes the orchestrator); MINIMAL SCOPED subprocess env (the P2.7-S3 c2 env-inheritance lesson — do not leak the orchestrator's env/secrets).

The senior's design (verify against the invariants + for runtime correctness):
- Transport = stdio (local subprocess via npx/uvx); the official `mcp` Python SDK (async) bridged to the sync orchestrator via a managed event loop. A new mcp/ package (transport/client/adapter/config/execution) as a leaf; an optional [mcp] dependency extra.
- Pre-classify allowlist: config/mcp_servers.yaml declares per server {command, args, api_key_env, env (minimal scoped), tools: {<tool>: {reversibility}}}. At connect, tools/list discovery → a ToolMeta is built ONLY for tools in the config allowlist (reversibility = config value); unclassified discovered tools get no ToolMeta → refused.
- Execution keys on the TOOL_CALL event → call_tool (bounded timeout, size-limited) → TOOL_RESULT / TOOL_FAILED (fail-closed). Interpret (content-gen, outside mcp/) frames the result as untrusted external data.
- Demo connector = the filesystem MCP server (read tools rev-10 → AUTO; write tools rev-1/2 → HARD_CONFIRM) to demonstrate tier discrimination.

Your lens — OVER-CORRECT for Claude biases; this is the highest-value part:
- AUTONOMY-BYPASS (the prime constitutional probe): Can a malicious/compromised server, or a crafted tool-call, reach EXECUTION without passing the gate? Trace: (a) is there ANY path where the MCP executor contacts a server for a tool-call that has no TOOL_CALL event (i.e. that the gate didn't AUTO-approve / the user didn't confirm)? (b) Can a server influence its tool's tier — does any server-provided field (a hint, an annotation, a tool name colliding with a high-reversibility local tool, a re-advertised tool changing classification between discovery and call) change the reversibility the gate uses? (c) The namespacing mcp__<server>__<tool> — can a server pick a name that collides with a local tool or another server's tool to inherit a more permissive classification? (d) Does discovery (tools/list) ever auto-register or auto-permit? Is "unclassified → refused" airtight, or is there a default-register path?
- SUBPROCESS FAILURE / LIVENESS ("what fails at 3am"): a server that hangs forever on connect or on a tools/call — does a bounded timeout actually fire, or can it hang the orchestrator (esp. across the async-SDK ↔ sync-orchestrator bridge — does the sync wrapper have a real timeout, or can run_until_complete block indefinitely)? A server that crashes mid-call — is the tool-call failed CLOSED (TOOL_FAILED) without crashing the orchestrator? A server that floods an oversized/streaming result — is the size limit enforced before OOM? A malformed-protocol response — handled, not an unhandled exception? Concurrent tool-calls + the single managed loop — deadlock/starvation?
- TRUST / ENV-LEAK (the recurring c2 catch): does the stdio subprocess get a MINIMAL scoped env, or does it inherit the orchestrator's full environment (leaking ANTHROPIC_API_KEY / DEEPSEEK keys / etc. to a third-party process)? Is the api_key_env secret scoped to ONLY the server that needs it, or visible to all? Can a server read secrets via the env it's launched with?
- UNTRUSTED RESULT: the result is content-gen-interpreted — can a prompt-injection in the tool result cause the interpreting LLM to take an action, or does the untrusted-framing + "describe don't act" + "no result drives a routing/autonomy decision" actually hold? Is the size limit applied to the raw bytes before they hit any LLM context?
- FEED-THE-GATE: is the gate's decision logic genuinely unchanged (score/decide_tier/emit_gate_decision/process_tool_calls)? Any place P3.4 re-implements or forks the tier decision?
- Over-engineering / missed-simpler; sycophancy where the senior writes "fail-closed"/"structural"/"unchanged".

NOT IN SCOPE to re-raise (architect-decided / constitutional):
- stdio transport + a filesystem demo connector (a); dual-lens (b); the pre-classify allowlist (c); the trust posture (d); MCP-client-now + config-anticipates-plugin (e) — architect ruled.
- The gate's decision logic (score/decide_tier/reversibility-tiers); discovery≠permission; content-gen-only interpret; no new LLMPurpose — constitutional; probe whether the DESIGN honors them, do not relitigate.
- Remote transports, many connectors, the plugin packaging (P3.5), the GUI surfacing — deferred.

Output format (mandatory):

---
task_id: P3.4
round: R0-B-cross-family-external
reviewer_family: <deepseek | gpt-5 | gemini | other>
reviewer_model_id: <specific model>
reviews_acked:
  - architect-briefs/P3.4.md
  - senior-plans/P3.4.md
  - decisions/ADR-027-mcp-client-tool-adapter-autonomy-gating.md
verdict: <clean | needs_architect | blocking>
findings_count:
  red: N
  yellow: N
  green: N
---

# P3.4 R0-B cross-family external review (plan + ADR-027)

[Body — markdown, project review tradition: per-finding 🔴/🟡/🟢 grouped by severity; each finding: location, what, why-it-matters, architect-partner lean (α absorb / β defer / γ reject), recommendation. Net assessment + verdict summary.]

Verdict semantics:
- clean = 0🔴 / 0🟡 / any 🟢 → architect proceeds to ADR-027 Accept.
- needs_architect = >=1🟡 OR an issue needing routing → architect Decision blocks until routed.
- blocking = >=1🔴 (design-breaking) → plan + ADR revised before junior dispatch.

Style: terse, technical, direct. Severity icons, no flowery language, no apologies for skepticism. Aim for 5-12 findings — quality over quantity. The AUTONOMY-BYPASS (can a server reach execution without the gate / influence its tier / namespace-collide) and the SUBPROCESS-LIVENESS (does the timeout actually fire across the async↔sync bridge) and the ENV-LEAK (minimal scoped env vs full inheritance) probes are the highest value — they are exactly what an in-family pass misses. An honest `clean` from cross-family is high-trust signal. Treat the external-prompt context (paths, prior decisions, RC numbers) as authoritative.
```

---

## Artifact bundle — read from disk (in-repo dispatch)

Read in full:
1. `docs/process/architect-briefs/P3.4.md` — the brief (the ⭐⭐ spine + ⭐ trust boundary + the 5 decisions).
2. `docs/process/senior-plans/P3.4.md` — the plan (§2 gating spine, §3 allowlist, §4 client, §5 execution+interpret, §6 trust boundary, §7 atomic graph, §8 test plan, §11 self-discoveries).
3. `docs/decisions/ADR-027-mcp-client-tool-adapter-autonomy-gating.md` — the proposed ADR (HR#1–10 + D1–D7 + alternatives).

Plus the live source on `main` when probing claims:
- `src/orchestrator/autonomy/scoring.py` (`score`/`decide_tier`/`gate`/`ToolMeta`/`UnknownToolError` — the gate MCP feeds, unchanged) + `agents/tool_dispatch.py` (`process_tool_calls` — the dispatch path; note it appends `TOOL_CALL` only for `AUTO_EXECUTE`, does NOT execute) + `autonomy/emission.py` (`emit_gate_decision`).
- `config/tools.yaml` + `llm/config_loader.py::load_tools_config` (the reversibility registry MCP joins).
- `src/orchestrator/core/event.py` (`ToolCallMeta`/`ToolResultMeta`; `TOOL_CALL`/`TOOL_RESULT`/`TOOL_FAILED`) + `llm/purposes.py` (`TOOL_OUTPUT_INTERPRET` — existing content-gen; no new purpose).
- The P2.7-S3 review (`docs/process/reviews/P2.7/…`) — the trust-boundary + **c2 env-inheritance** pattern that recurs here.

(For an external web-session dispatch — GPT-5 / Gemini — paste the 3 doc files + these source files after the system prompt.)

---

## Notes for architect-partner reviewing the returned external R0-B output

1. **Save as** `docs/process/reviews/P3.4/R0-B-cross-family-external.md`.
2. **Frontmatter** preserved verbatim; `reviews_acked` verified against the artifacts.
3. If `verdict: clean` + no new 🔴/🟡: architect proceeds to ADR-027 Accept + junior dispatch.
4. If new 🔴/🟡: architect routes via `architect-routing.md`; senior absorbs via `awaiting_senior_revision`. Verdict bumps per RC-10.
5. **Highest-value contradictions to watch**: (a) an **autonomy-bypass** — a path to execution without a `TOOL_CALL` event, or a server influencing its tier (hint/annotation/namespace-collision/re-advertise-between-discovery-and-call); (b) a **subprocess-liveness hole** — the timeout not actually firing across the async-SDK↔sync-orchestrator bridge (a hang); (c) an **env-leak** — the subprocess inheriting the orchestrator's full env/secrets instead of a minimal scoped env (the recurring c2 catch); (d) an **untrusted-result** path where a prompt-injection in the result drives an action. Route any; send to the P3.4 retro.
6. Per RC-20: note whether the external lens corrects an in-family finding vs only adds net-new.
7. This is the autonomy/trust boundary — the dual-lens is dispatched precisely because the in-family pass structurally under-probes external-adversary + subprocess-failure modes (the P2.7-S3 c2 precedent).
