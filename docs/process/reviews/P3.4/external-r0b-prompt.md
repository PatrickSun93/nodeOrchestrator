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

---
---

# Cycle-2 — the runtime tool-executor (ADR-028 + `P3.4-cycle2.md`)

**Purpose**: copy-pasteable system prompt + artifact bundle for a **true cross-family R0-B** on P3.4 **cycle-2** — the runtime tool-executor (ADR-028, Proposed) + the cycle-2 plan + the impl on `claude/P3.4-impl` (commits `P3.4-C2-*`). This is a **distinct dispatch** from the cycle-1 plan-stage prompt above (kept intact as the audit record).

**Dispatch rationale (mandatory — `requires_cross_family_review: true`).** Cycle-2 is the system's **first component that actually executes tools** — a new runtime stage with concurrency, failure, and event-loop semantics. The cross-family lens is exactly what caught cycle-1's **Y2** (the runtime-wiring gap — "the function exists, therefore it's integrated" Claude bias) and the cycle-1 timeout/env-leak. The cycle-2 surface — *can anything execute without a `TOOL_CALL` event? does a tool failure/hang break the turn or block the writer? is execution double-run? does the local sandbox actually contain path-traversal?* — is the same class.

**How to use**: open a non-Claude session (DeepSeek / GPT-5-class / Gemini), paste the system prompt, read the artifacts from disk (or paste). Ask: "Generate the R0-B review per the mandatory output format." Architect-partner saves the returned review as `docs/process/reviews/P3.4/R0-B-cross-family-cycle2.md` (distinct from cycle-1's `R0-B-cross-family.md` — the cycle counter treats cycle-1 artifacts as stale, but the paths collide without distinct names).

---

## System prompt (cycle-2)

```
You are reviewing the runtime TOOL-EXECUTOR (design + impl) of a multi-agent orchestration framework. Cycle-1 already shipped an MCP client + the autonomy-gating wiring + an MCP executor FUNCTION (execute_mcp_tool_call) + an interpret function — but nothing in the running app consumed the gate's TOOL_CALL events and executed them (this gap, "Y2", is what cycle-2 fixes). Cycle-2 builds the GENERAL runtime tool-executor: a post-dispatch stage that consumes each AUTO_EXECUTE TOOL_CALL event and ACTUALLY RUNS the tool — MCP tools via execute_mcp_tool_call, LOCAL tools via newly-built implementations — appending TOOL_RESULT/TOOL_FAILED, and (for MCP only) interpreting the untrusted result via the existing content-gen TOOL_OUTPUT_INTERPRET. This is the FIRST time the orchestrator runs a tool at runtime.

Constitutional carry-forward (NON-NEGOTIABLE — the executor must preserve; verify it does):
- Execution stays DOWNSTREAM of the gate. The executor runs ONLY for a TOOL_CALL event — the gate's AUTO_EXECUTE approval record (process_tool_calls appends TOOL_CALL ONLY for AUTO_EXECUTE; COUNTDOWN/HARD append none → not executed). confirm-then-execute stays deferred (GUI-coupled). The executor must NOT re-gate (no score/decide_tier/emit_gate_decision in the executor).
- No LLM-judgment in the executor. Execution is code; the only LLM touch is the MCP content-gen interpret (TOOL_OUTPUT_INTERPRET, untrusted-framed). NO new LLMPurpose. No routing/judgment in the execution path.
- The trust boundary holds. MCP execution keeps the cycle-1 allowlist + minimal-scoped-env + 64KiB size-limit + bounded-timeout + fail-closed (unchanged). Local execution adds its own sandbox-root trust boundary.

The design (ADR-028 — verify against the invariants + for runtime correctness):
- D1 PLACEMENT: the executor is a SEPARATE post-dispatch stage invoked by the turn driver (api/app.py _write_and_turn, after run_turn returns), NOT folded into run_turn/dispatch_turn. Reason: rooms/ is constitution-forbidden from LLM + from importing orchestrator.mcp; the executor imports both. It lives in a new downstream leaf package orchestrator/tools/. The gate/dispatch path (process_tool_calls) is UNCHANGED (the gate diff stays empty).
- D2 DISPATCH: route by tool name. mcp__<server>__<tool> → execute_mcp_tool_call(session=mcp_sessions[server]) then interpret (untrusted → OBSERVATION). non-mcp__ (local) → run the local impl → TOOL_RESULT/TOOL_FAILED; local results are TRUSTED → NOT interpreted. A classified-but-unimplemented tool → TOOL_FAILED error_class="not_implemented" (fail-closed). Sessions are RETAINED at bootstrap (cycle-1 discarded them; the transport spawns a fresh subprocess per call, so a retained session holds no long-lived process). DOUBLE-EXECUTION GUARD: skip a TOOL_CALL whose call_id already has a result.
- D3 LOCAL SET + TRUST BOUNDARY: MVP local impls = get_current_time (pure), read_file + list_files (sandboxed: a configured root; paths resolved + rejected if they escape the root — path-traversal/symlink/absolute; results size-capped at 64KiB). Network/subprocess/code-intel/mutation tools DEFERRED (fail-closed not_implemented).
- D4 FAILURE: no agent re-dispatch in the MVP (the agent reacts to the result on the NEXT turn — matches existing causality; re-dispatch is a deferred turn-loop extension). Per-call fail-closed isolation: one tool's failure → TOOL_FAILED for that call only, continue to the next.
- D5 LIVENESS: the stage runs INLINE on the single-writer thread (ThreadPoolExecutor max_workers=1, which serializes ALL room writes). A slow MCP tool blocks all writes for up to the bounded timeout. Accepted for the MVP (bounded + fail-closed; local tools are fast); a separate execution lane is deferred.

Your lens — OVER-CORRECT for Claude biases; this is the highest-value part:
- AUTONOMY-BYPASS / PLANT (the prime probe): trace from a tool call to execution. Is there ANY path where the executor runs a tool WITHOUT a TOOL_CALL event (the gate's AUTO approval)? Can a COUNTDOWN/HARD tool (no TOOL_CALL event) reach execution? Does the executor anywhere re-derive/forge a TOOL_CALL, or re-gate, or read a tier from anywhere but the existing gate's event? Can a TOOL_RESULT/OBSERVATION (the interpret output) be mistaken for a TOOL_CALL and re-executed?
- DOUBLE-EXECUTION / IDEMPOTENCY ("what fails at 3am"): the executor scans the turn's TOOL_CALL events. Can a TOOL_CALL be executed twice — across a retry, a re-scan, overlapping windows, or because the guard checks the wrong scope (the passed window vs the full room)? If the same call_id appears twice, is exactly one execution guaranteed? Is the guard a real check or a comment?
- TURN / FAILURE SEMANTICS: a local tool raises mid-stage; an MCP call times out; the LLM interpret raises — does the stage fail CLOSED for that call and CONTINUE the others, or does one failure abort the whole stage / crash the turn / leave a half-written event? Are TOOL_RESULT and TOOL_FAILED mutually exclusive per call_id? Does a partial-execution leave the room in a coherent state?
- SINGLE-WRITER LIVENESS: the stage runs inline on the one writer thread. A server that hangs (bounded timeout ~tens of seconds) blocks EVERY room's writes for that window. Is the bound real (the cycle-1 asyncio.wait_for + subprocess-kill)? Can N AUTO tool-calls in one turn stack timeouts (Σ of bounds)? Is there any path to an UNBOUNDED block (a local tool that blocks; a subprocess not killed; the interpret LLM call without a timeout)? Is the documented bound the actual bound?
- LOCAL SANDBOX: read_file/list_files are sandboxed to a configured root. Can a path escape — `..`, an absolute path, a symlink pointing outside, a TOCTOU between resolve and read, a Windows/UNC quirk? Is the resolve-then-check order correct (resolve symlinks BEFORE the containment check)? Is the size cap applied before the bytes are stored? Is "not_implemented" truly fail-closed (no silent no-op, no crash)?
- FEED-THE-GATE UNCHANGED: is process_tool_calls / the gate genuinely untouched (empty diff)? Does the executor live OUTSIDE rooms/ and import nothing that would break the rooms-no-LLM / mcp-leaf constitution? Are the cycle-2 constitution tests (t1 no-upstream-import-of-tools, t2 no-decision-in-executor, t3 no-new-purpose, t4 keys-on-TOOL_CALL-only) real assertions or vacuous?
- Over-engineering / missed-simpler; sycophancy where the senior/ADR writes "fail-closed" / "structural" / "downstream" / "bounded".

NOT IN SCOPE to re-raise (architect-decided / deferred):
- build-local-impls-now (decision #1 — architect-ruled); the local MVP breadth {get_current_time, read_file, list_files} (senior-designed, architect-confirmed); no-re-dispatch MVP (D4); inline-on-single-writer (D5, the bound is the point — probe whether it HOLDS, not whether to choose a lane); confirm-then-execute deferral (GUI-coupled); the deferred local tools (network/subprocess/mutation). Probe whether these postures are correctly + safely IMPLEMENTED; do not re-litigate the architect's choice.

MANDATORY OUTPUT FORMAT: a markdown table of findings — | id | severity (🔴 blocking / 🟡 should-fix / 🟢 confirmation) | finding | basis (file:line or artifact) | — then a 1-paragraph summary, then a recommended-routing line per finding (α absorb / β defer / γ reject). Default a finding to 🟡+refute-bias: if uncertain a bypass/double-exec/liveness hole is real, state the trace you'd need to confirm it. Verdict: clean / needs_architect / blocking.
```

---

## Artifact bundle (cycle-2 — read from disk / paste after the system prompt)

- `docs/decisions/ADR-028-runtime-tool-executor.md` (the design — Proposed).
- `docs/process/senior-plans/P3.4-cycle2.md` (the plan — atomic graph C2-1..C2-4 + the §5 push-backs).
- The cycle-2 impl on `claude/P3.4-impl` (commits `P3.4-C2-1..4`): `src/orchestrator/tools/executor.py` + `tools/local.py`; the `api/app.py` diff (AppContext `mcp_sessions`/`local_tools`, `_build_context` session-retention, `_write_and_turn` stage invocation); `tests/tools/` (constitution + e2e) + the integration full-turn test.
- Cycle-1 context (for the carry-forward): `src/orchestrator/mcp/execution.py` (`execute_mcp_tool_call`), `agents/mcp_interpret.py` (`interpret_mcp_tool_result`), `agents/tool_dispatch.py` (`process_tool_calls` — TOOL_CALL for AUTO_EXECUTE only; verify unchanged), `rooms/runtime.py` (`run_turn` — verify unchanged), ADR-027 (the MCP client/gating/trust boundary).
- Live source for claims: `config/tools.yaml` (local-tool classification — `get_current_time`/`read_file`/`list_files` rev 10 → AUTO), `core/event.py` (`ToolCallMeta`/`ToolResultMeta`; `TOOL_CALL`/`TOOL_RESULT`/`TOOL_FAILED`/`OBSERVATION` — verify NO new metas), `llm/purposes.py` (`TOOL_OUTPUT_INTERPRET` — verify no new purpose), `api/app.py:131` (`ThreadPoolExecutor(max_workers=1)` — the single writer).

## Notes for architect-partner reviewing the returned cycle-2 R0-B output

1. **Save as** `docs/process/reviews/P3.4/R0-B-cross-family-cycle2.md` (NOT over the cycle-1 file).
2. Frontmatter `reviews_acked` verified against the cycle-2 artifacts (ADR-028 + `P3.4-cycle2.md` + the `P3.4-C2-*` commits).
3. **Highest-value contradictions to watch**: (a) an **autonomy/plant bypass** — execution without a `TOOL_CALL` event, a re-gate, or a forged/re-derived approval; (b) a **double-execution** — the idempotency guard not actually covering a re-scan/overlap; (c) a **liveness hole** — an unbounded block on the single writer (a local tool that blocks, a subprocess not killed, an un-timed interpret call); (d) a **sandbox escape** — resolve/check ordering, symlink, TOCTOU, oversized-before-store; (e) **gate drift** — `process_tool_calls`/the gate not actually unchanged, or a constitution test that's vacuous. Route any; send to the P3.4 retro.
4. Per RC-20: note whether the external lens corrects an in-family finding vs only adds net-new (the cycle-1 R0-B earned its keep by catching Y2 — a runtime-integration miss the in-family lens conceded).
5. If `verdict: clean` + no new 🔴/🟡 (with R0-A-cycle2 also clean): architect proceeds to ADR-028 Accept + the P3.4 cycle-2 close (RC-10 verdict-bump of BOTH cycles, per the architect-ruled deferral) + the whole-P3.4 merge of PR #48. If new 🔴/🟡: architect routes; senior absorbs via `awaiting_senior_revision`; verdicts bump per RC-10.
