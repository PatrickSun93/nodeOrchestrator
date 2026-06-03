# ADR-028: Runtime Tool-Executor

**Status:** Proposed — 2026-06-03 (senior-drafted; P3.4 cycle-2. Awaiting architect acceptance + dual-lens R0-B. RC-23-safe — no acceptance substring until the architect accepts.)

**Scope:** P3.4 cycle-2 — the **general runtime tool-executor**: the post-dispatch stage that consumes `TOOL_CALL` events (the autonomy gate's `AUTO_EXECUTE` approval records) and *actually executes* them — MCP tools via the cycle-1 `execute_mcp_tool_call`, **local tools via newly-built implementations** — appending `TOOL_RESULT`/`TOOL_FAILED`, and (for MCP only) interpreting the untrusted result via the existing content-gen `TOOL_OUTPUT_INTERPRET`. Governs: the execution-stage placement in the turn lifecycle (D1), the MCP-and-local dispatch (D2), the local-tool MVP set + local trust boundary (D3), the failure / no-re-dispatch semantics (D4), the sync/inline-on-single-writer liveness posture + its bound (D5), and the executor's constitutional invariants (D6). Does NOT govern: the autonomy gate's decision logic (`score`/`decide_tier`/`emit_gate_decision`/`process_tool_calls` — **unchanged**, as in ADR-027 D2); the MCP client/transport/adapter (ADR-027); confirm-then-execute for `COUNTDOWN`/`HARD` (still deferred — GUI-coupled, ADR-027 D6); agent re-dispatch / a tool-result→agent turn-loop (deferred, D4); the deferred local tools (network/subprocess/mutation — D3).

## Context

P3.4 cycle-1 shipped the MCP client, the autonomy-gating wiring, and the MCP executor *function* (`execute_mcp_tool_call`) + the interpret wiring (`interpret_mcp_tool_result`). The impl-stage cross-family R0-B caught **Y2**: those functions are defined, correct, and tested (mocked transport), but **nothing in the running app consumes `TOOL_CALL` events and executes them** — `process_tool_calls` appends a `TOOL_CALL` event for each `AUTO_EXECUTE` tool, but no runtime stage reads those events and calls the executor. So an MCP tool is *gated* but never *executed* in the living application. The architect routed Y2 → **α wire-now**, scoped to a **general runtime tool-executor**, and ruled (decision #1, 2026-06-03) **build-local-impls-now**: cycle-2 builds the general framework, wires the MCP executor, **and** implements actual local-tool execution (not deferred).

This is the system's **first component that actually runs a tool**. ADR-013 (operator tool dispatch) explicitly *"does not govern tool execution itself (P1.6+)"*; ADR-003 names the orchestrator as the intended tool-execution layer for `openai_compatible` providers but it was **unbuilt**. So the runtime executor is *beyond* the current ADR envelope — it earns its own ADR + a mandatory dual-lens R0-B (the runtime/concurrency/failure surface — the same class that caught Y2).

Verified against `origin/claude/P3.4-impl` (cycle-1) + `origin/main`:
- `process_tool_calls` (`agents/tool_dispatch.py:57,100`) appends a `TOOL_CALL` event **only** for `AUTO_EXECUTE`; `COUNTDOWN`/`HARD` append none. The gate diff is empty (ADR-027 D2 held).
- `execute_mcp_tool_call` (`mcp/execution.py:40`) requires a `TOOL_CALL` event, calls `tools/call` (bounded-timeout, size-limited, fail-closed → `TOOL_RESULT`/`TOOL_FAILED`), no LLM, no decision.
- `interpret_mcp_tool_result` (`agents/mcp_interpret.py:39`) calls the LLM via `TOOL_OUTPUT_INTERPRET` (untrusted-framed) → `OBSERVATION`. Lives in `agents/`, not `mcp/`.
- The bootstrap (`api/app.py` `_build_context`) builds the MCP `ToolMeta` registry via `build_mcp_tool_registry_from_config` and **discards the `MCPSession`s** (`adapter.py:121` — `session` is a local; R0-B Y2 noted this).
- The turn runs inside `_write_and_turn` on a **single-writer** `ThreadPoolExecutor(max_workers=1)` (`api/app.py:131`; "serializes all writes").
- **No local-tool implementations or local executor exist** (`config/tools.yaml` classifies tool *names* — `read_file`/`list_files`/`get_current_time` rev 10, etc. — but none is implemented). Constitution test `tests/mcp/test_constitution.py` c1 forbids upstream layers (`core/autonomy/agents/llm/rooms/skills/…`) from importing `orchestrator.mcp`; `tests/rooms/test_constitution.py::test_constitution_no_llm_calls_in_rooms_module` forbids LLM in `rooms/`.

## Constitutional carry-forward (NON-NEGOTIABLE — inscribed from cycle-1; the executor preserves)

1. **Execution stays DOWNSTREAM of the gate.** The executor runs **only** for a `TOOL_CALL` event — the gate's `AUTO_EXECUTE` approval record. It never executes a gated-but-unapproved call. `COUNTDOWN`/`HARD` append no `TOOL_CALL` event → are correctly **not executed**; **confirm-then-execute stays deferred** (GUI-coupled, ADR-027 D6).
2. **No LLM-judgment in the executor.** Execution is code. The only LLM touch is the content-gen interpret (`TOOL_OUTPUT_INTERPRET`, untrusted-framed, MCP-only). **No new `LLMPurpose`.** No routing/judgment in the execution path; the executor never calls `score`/`decide_tier`/`emit_gate_decision` (no re-gating).
3. **The trust boundary holds.** MCP execution keeps the cycle-1 allowlist + scoped-env + size-limit + bounded-timeout + fail-closed (unchanged). Local execution adds its own trust boundary (D3).

## Decisions

### D1. Execution-stage placement — a post-dispatch stage invoked by the turn driver (NOT inside `run_turn`)

The execution stage is a **separate pass that runs after `run_turn` returns**, invoked by the **turn driver** (today: `api/app.py::_write_and_turn`, between the `run_turn` call and the `get_room_events[pre_cursor:]` cursor-diff that publishes new events). It is **not** folded into `run_turn`/`dispatch_turn`.

- **Why a separate stage, not inside `run_turn`:** the executor imports `orchestrator.mcp` (for `execute_mcp_tool_call`) and the LLM (for the MCP interpret). `rooms/` is forbidden from both — `test_constitution_no_llm_calls_in_rooms_module` (no LLM in `rooms/`) and the mcp-c1 leaf rule (no upstream import of `orchestrator.mcp`). Keeping execution out of `run_turn` preserves both invariants and keeps `dispatch_turn`/`process_tool_calls` pure gate-and-dispatch (the empty gate diff from ADR-027 D2 stays empty).
- **Why downstream of the gate:** the stage consumes the `TOOL_CALL` events `process_tool_calls` appended this turn — the gate's approval record. Execution-downstream-of-gate is **structural** (the executor has no path to a server/impl without a `TOOL_CALL` event), exactly as ADR-027 D6 made it for MCP.
- **The new package:** `src/orchestrator/tools/` — `tools/executor.py` (the stage) + `tools/local.py` (local impls + the local trust boundary). `tools/` is a **downstream leaf consumer** (imports `mcp`/`autonomy`/`core`/`llm`/`agents.mcp_interpret`); no upstream layer imports it. The turn driver (`api/`, the composition root) is the only caller.
- **The stage signature** consumes the `TOOL_CALL` events appended this turn (the driver passes the `[pre_cursor:]` window, or the executor reads the room events since a cursor) + the injected `mcp_sessions` registry + the `local_tools` registry + `event_store` + `llm_router`. It appends `TOOL_RESULT`/`TOOL_FAILED` (+ MCP `OBSERVATION`) to the **same** store on the **same** writer thread, so the driver's post-stage `get_room_events[pre_cursor:]` read picks them up and publishes them.

### D2. MCP-and-local dispatch — route on the `mcp__` prefix

For each `AUTO_EXECUTE` `TOOL_CALL` event in the turn's window, the executor routes by tool name:
- **`mcp__<server>__<tool>`** → `execute_mcp_tool_call(tool_call_event, session=mcp_sessions[server], …)`; on `TOOL_RESULT`, then `interpret_mcp_tool_result(...)` (untrusted-framed content-gen → `OBSERVATION`). The `<server>` is parsed via the existing `to_mcp_call`; the session comes from the **injected `mcp_sessions` registry** (D-fix below). MCP results are untrusted → interpreted.
- **non-`mcp__` (local)** → look up `local_tools[tool_name]` and run the implementation → `TOOL_RESULT` (success) / `TOOL_FAILED` (raised / not-implemented). **Local results are trusted** (our own code) → **not** interpreted (no `OBSERVATION`); the `TOOL_RESULT` stands on its own in the next turn's snapshot.
- **Classified-but-not-implemented local tool** (a tool in `tools.yaml`/the gate registry whose `AUTO_EXECUTE` `TOOL_CALL` reaches the executor but which has no `local_tools` entry — the deferred set, D3) → `TOOL_FAILED` with `error_class="not_implemented"` (fail-closed; honest; no silent no-op).

**Session-discard fix (R0-B Y2 sub-finding):** the bootstrap currently discards the `MCPSession`s built during discovery. Cycle-2 **retains** them in an `mcp_sessions: dict[str, MCPSession]` (built in the same `connect()` pass that builds the `ToolMeta` registry) and injects them into the executor. The cycle-1 transport spawns+kills a fresh subprocess **per operation** (per `call_tool`), so a retained `MCPSession` holds only config + discovered tools — no long-lived subprocess (verified: `transport.py` per-call `asyncio.new_event_loop()` + `stdio_client` context-manager spawn/kill).

**Double-execution guard (idempotency).** Before executing a `TOOL_CALL`, the executor checks the room's current events for an existing `TOOL_RESULT`/`TOOL_FAILED` with the same `call_id`; if present, it **skips** (already executed). This protects against re-scan/retry edge cases and is the defense against the double-execution failure mode the cross-family lens probes.

### D3. Local-tool MVP set + the local trust boundary (senior-designed; surfaced for architect breadth-confirm)

Per decision #1 (build-local-impls-now), cycle-2 ships **real local-tool implementations**. The senior-designed MVP set is the **safe, `AUTO_EXECUTE`-tier (rev 10), low-trust-surface** subset that exercises the executor end-to-end without opening a network or subprocess surface:

| Local tool | tools.yaml rev | Tier | Trust surface | Execution |
|---|---|---|---|---|
| `get_current_time` | 10 | AUTO | none (pure clock read) | returns current time; no I/O |
| `read_file` | 10 | AUTO | local FS (sandboxed) | reads a file **within a configured sandbox root**; size-capped |
| `list_files` | 10 | AUTO | local FS (sandboxed) | lists a directory within the same sandbox root |

**The local trust boundary** (for `read_file`/`list_files`): a **configured sandbox root** (a single workspace dir); every path is resolved (`Path.resolve()`, symlinks followed) and **rejected if it escapes the root** (path-traversal / `..` / absolute-path / symlink-escape → `TOOL_FAILED`); results are **size-capped** (reuse the `MAX_RESULT_BYTES = 64 KiB` truncation pattern from `mcp/execution.py`). No write/move/delete in the MVP local set (those are mutation tier → `HARD_CONFIRM` → gated-not-executed anyway under the no-confirm-flow MVP).

**Deferred local tools (out of scope this cycle — fail-closed `not_implemented` until their slices land):** network tools (`web_search`/`web_fetch` — a network trust surface), subprocess tools (`run_tests`/`run_lint`/`git_blame`/`git_log`/`git_diff` — a subprocess surface, the c2 env-leak class), code-intel (`search_text`/`search_code`/`find_references`/`find_definition`), and mutation tools (`propose_edit`/`apply_edit`/`send_email`/`git_push` — `HARD`/`COUNTDOWN` tier; **provably dead until confirm-then-execute lands**, so implementing them now is dead code). Each distinct surface (network / subprocess / mutation) warrants its own slice + classification review. This is a **scope boundary the senior designs**; the architect may broaden or narrow it (see the plan §5 — the breadth is the surfaced call).

### D4. Failure / re-dispatch semantics — no-re-dispatch MVP; per-call fail-closed isolation

- **No agent re-dispatch in the MVP.** The executor appends `TOOL_RESULT`/`TOOL_FAILED` (+ MCP `OBSERVATION`) and returns. The agent does **not** react to the result in the same turn. The results are in the room and appear in the **next** turn's snapshot — which matches the existing causality model (a `state_transition` likewise takes effect on the next turn; `run_turn` docstring). A tool-result→agent-reaction loop is a **turn-loop extension** (ADR-011 territory) that introduces termination/loop-bounding concerns + multiplies LLM calls + compounds the single-writer liveness cost (D5). It is **deferred** to a follow-up that explicitly inscribes the loop bound (noted as an ADR-011 touch-point). Alternatives considered: single-re-dispatch (one extra dispatch pass after results) and bounded-loop (re-dispatch ≤N until no new tool calls) — both deferred for the reasons above; the MVP's no-re-dispatch is the conservative, terminating choice consistent with the AUTO-only / no-confirm-flow posture.
- **Per-call fail-closed isolation.** The executor iterates the turn's `TOOL_CALL` events; each call executes independently. A failure (raise / timeout / not-implemented) → `TOOL_FAILED` for **that** call only; the executor continues to the next call. No single tool failure aborts the others or the turn (mirrors `dispatch_turn`'s per-agent isolation, ADR-011 D7). An executor-internal bug (not a tool failure) propagates — but each tool call is wrapped fail-closed.
- **`TOOL_FAILED` and turn continuation:** the turn (`run_turn`) has already returned before the execution stage runs; there is no turn to abort. `TOOL_FAILED` is simply recorded for the next turn.

### D5. Sync / inline-on-the-single-writer — bounded; the liveness interaction flagged

The execution stage runs **inline on the same single-writer thread** as the turn (`ThreadPoolExecutor(max_workers=1)`, which "serializes all writes"). An MCP tool call spawns a subprocess and blocks that thread for up to the **bounded** MCP timeout (cycle-1: `asyncio.wait_for` + subprocess kill-no-orphan; connect+call ≈ tens of seconds, configurable per `mcp_servers.yaml`). Local tools (clock; size-capped FS reads, no network/subprocess) are fast (sub-ms to ms).

- **Posture (MVP): inline-on-the-writer.** Simplest; preserves the single-writer invariant (all appends from one thread, no store concurrency); the cycle-1 bounded-timeout + fail-closed guarantees the block is **finite** (no indefinite hang — HR#10).
- **The liveness cost (flagged — the R0-B probe surface):** because the writer is single-threaded and serializes **all** rooms' writes, a slow MCP tool blocks not just its own room's turn but **every** queued write for up to the per-call timeout. Worst-case writer block for a turn ≈ Σ(bounded timeouts of that turn's `AUTO_EXECUTE` MCP calls), executed sequentially. This is the P3.2 single-writer serialization point, now extended to cover tool execution.
- **Deferred:** a separate execution lane (offload tool execution off the writer, free it for other rooms) is a real concurrency redesign (result-append ordering vs the single-writer invariant) — deferred to a perf/scale slice. The MVP accepts the bounded block; the bound + the interaction are documented here so the dual-lens evaluates a known posture, not an accident.

### D6. The executor's constitutional invariants (enforced by tests/tools/test_constitution.py)

- **t1 — `tools/` is a downstream leaf:** no upstream layer (`core/autonomy/agents/llm/rooms/skills/connectors/memory/producers/reentry/derived/workflow`) imports `orchestrator.tools` (mirrors the mcp-c1 rule; only `api/` + bootstrap wire it).
- **t2 — no autonomy decision in the executor:** `tools/` does not reference `decide_tier`/`emit_gate_decision`/`score`/`gate` (the executor consumes the gate's `TOOL_CALL` record; it never re-gates — carry-forward #2 / HR#6-analog).
- **t3 — no new `LLMPurpose`:** the frozen purpose set is unchanged; the MCP interpret reuses `TOOL_OUTPUT_INTERPRET` (carry-forward #2 / HR#5).
- **t4 — execution keys on `TOOL_CALL` only:** the executor's entry point requires `TOOL_CALL` events (no path from a `UTTERANCE`/`USER_INPUT`/raw tool-call to a server or a local impl) — the structural downstream-of-gate guarantee (carry-forward #1 / HR#4), asserted by a no-`TOOL_CALL`→no-execution test.

## Considered alternatives

- **Fold execution into `run_turn` / `dispatch_turn`** — Rejected (D1): `rooms/` is LLM-free + mcp-free by constitution; folding would either break those invariants or split the executor across layers. A post-dispatch driver-invoked stage keeps the gate/dispatch path pure (empty gate diff stays empty) and the executor in a downstream leaf.
- **Execute inside `process_tool_calls`** — Rejected (already rejected in ADR-027 D6): that puts external I/O + execution into the gate path; keying on the `TOOL_CALL` event keeps execution downstream and the gate decision-only.
- **Per-call MCP connection at the executor (re-discover each time)** — Rejected (D2): the bootstrap already discovers; retaining the `MCPSession`s avoids re-discovery and fixes the R0-B session-discard sub-finding. (The transport still spawns a fresh subprocess per `call_tool` — the retained session holds no long-lived process.)
- **Single-re-dispatch / bounded-loop (agent reacts to the result in-turn)** — Deferred (D4): a turn-loop extension with termination + liveness implications; the MVP's no-re-dispatch terminates and matches existing causality.
- **Separate execution lane (off the single writer)** — Deferred (D5): a concurrency redesign (ordering vs the single-writer invariant); the MVP accepts the bounded inline block.
- **Implement the full `tools.yaml` set now** — Rejected (D3): network/subprocess/mutation each open a distinct trust surface; mutation tools are dead under the no-confirm-flow MVP. The safe AUTO subset proves the framework; the rest are framework-ready (fail-closed `not_implemented`) until their slices.

## Consequences

**Easier:** the system finally **runs tools at runtime** — both MCP and local — through the one existing gate (no second decision surface). The session-discard gap is fixed. The local-tool + local-trust-boundary pattern (sandbox root) is established for future local tools. The handoff's runtime claim becomes true.

**Harder:** a new runtime stage + a single-writer liveness cost (a slow MCP tool blocks all writes for a bounded window) to evaluate; a local-FS trust boundary (path-traversal/symlink/size) to get right; the not-implemented fail-closed seam means some classified AUTO tools fail at runtime until their slices land (honest, but visible).

**Neutral:** no-re-dispatch means the agent reacts to a tool result on the *next* turn, not in-turn (matches existing causality; re-dispatch is additive later). confirm-then-execute remains GUI-deferred (unchanged). The gate decision logic is untouched (ADR-027 D2 preserved).

## Reversibility

| Decision | 6-month reversal cost |
|---|---|
| D1 post-dispatch driver-invoked stage / `tools/` package | **Low** — a contained stage + a leaf package; moving the invocation site is local. |
| D2 mcp/local dispatch + session-retention | **Low** — prefix routing + a session dict; additive. |
| D3 local MVP set + sandbox root | **Medium** — broadening the set / relaxing the sandbox is a trust-surface decision (architect-gated); the sandbox-root contract is the reusable piece. |
| D4 no-re-dispatch | **Low** — re-dispatch is additive (a later turn-loop slice); not reversing a decision so much as not-yet-making one. |
| D5 inline-on-single-writer | **Medium** — moving to a separate execution lane is a concurrency redesign (ordering vs single-writer). |
| D6 executor constitution tests | **Do-not-reverse** — the downstream-of-gate / no-decision / no-new-purpose invariants are the carry-forward spine. |

## References

- `docs/process/architect-briefs/P3.4.md` §"⭐ Cycle-2 brief — the runtime tool-executor" (the 5 decision points + the constitutional carry-forward; decision #1 ruled build-local-impls-now).
- `docs/process/senior-plans/P3.4-cycle2.md` (this ADR's plan; atomic graph + test plan).
- `docs/process/reviews/P3.4/R0-B-cross-family.md` (impl-stage Y2 — the runtime-wiring gap) + `architect-routing-on-impl.md` (Y2 → α wire-now).
- ADR-027 (MCP client/transport/adapter/gating/trust boundary + D6 execution-on-`TOOL_CALL` + MVP-AUTO-only); ADR-013 (operator tool dispatch — *"does not govern tool execution itself (P1.6+)"*); ADR-003 (orchestrator as the tool-execution layer for `openai_compatible`, previously unbuilt); ADR-011 (turn loop — the re-dispatch deferral touch-point); ADR-005 (autonomy scoring/tiers/reversibility); ADR-006 (unknown-tool → fail-closed).
- `src/orchestrator/mcp/execution.py` (`execute_mcp_tool_call`), `agents/mcp_interpret.py` (`interpret_mcp_tool_result`), `agents/tool_dispatch.py` (`process_tool_calls` — `TOOL_CALL` for `AUTO_EXECUTE` only), `rooms/runtime.py` (`run_turn`), `api/app.py` (the turn driver + single-writer executor + the bootstrap registry merge), `config/tools.yaml` (local-tool classification).
