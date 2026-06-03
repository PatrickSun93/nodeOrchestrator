---
task_id: P3.4
round: plan-vs-impl
reviewer: senior
impl_commit: 003284e
verdict: clean
verdict_history:
  - verdict: clean
    at_commit: 003284e
    findings_count: { red: 0, yellow: 0, green: 8 }
    note: >-
      initial plan-vs-impl. Faithful on every axis incl. both plan-stage routing absorptions. The
      gating spine holds and is feed-the-gate: NO change to autonomy/scoring.py, autonomy/emission.py,
      or agents/tool_dispatch.py (verified — the gate decision logic is untouched); the registry merge
      (api/app.py) is `tools = {**tools, **mcp_tools}` (MCP ToolMeta into the same gate registry,
      namespaced mcp__<server>__<tool>, graceful skip_unavailable). adapter.py registers ONLY
      allowlisted∩discovered tools (config reversibility; server hints ignored — HR#2) so unclassified
      → no ToolMeta → UnknownToolError refused (HR#3, discovery≠permission). execution.py keys on the
      TOOL_CALL event (requires it), fails closed (TOOL_FAILED on any error, HR#10), size-limits the
      untrusted result (64KiB, HR#9), no LLM. The R0-B Y1 timeout MUST-FIX is in transport.py: every
      SDK call wrapped in asyncio.wait_for(timeout=connect+op); on timeout the subprocess is killed
      (stdio_client cleanup) — and the subprocess-killed-no-orphan test genuinely verifies it via
      os.kill(pid,0). The arch-Y1 AUTO-only is honored: the e2e demonstrates read_file→AUTO→TOOL_CALL→
      execute→TOOL_RESULT→interpret AND write_file rev2→HARD_CONFIRM→not-executed (no confirm flow
      wired). The interpret (agents/mcp_interpret.py, OUTSIDE mcp/) reuses TOOL_OUTPUT_INTERPRET (no
      new LLMPurpose, HR#5) with untrusted-framing. Scoped subprocess env (HR#10, the c2 lesson) +
      credential indirection + allowlist all tested. Constitution tests (no-upstream-import / no-routing
      / no-LLM-provider / no-new-LLMPurpose / no-namespace-collision). Gates green independently (51 mcp
      tests + ruff + mypy --strict). 8 green; observations noted (execute_mcp_tool_call has no run_turn
      production caller — matches the project's no-tool-executor-for-any-tool state, the loop is proven
      in the e2e; per-operation subprocess connections; the to_mcp_call '__'-split edge).
findings_count:
  red: 0
  yellow: 0
  green: 8
---

# P3.4 plan-vs-impl (senior) — MCP client + tool-adapter + autonomy-gating

| Field | Value |
|---|---|
| Reviewer | senior (plan-vs-deliverable lens) |
| Plan | `docs/process/senior-plans/P3.4.md` (incl. the R0-B Y1 timeout + arch-Y1 AUTO-only absorption) |
| ADR | `ADR-027` (**Accepted**) |
| Impl | `claude/P3.4-impl` @ `003284e` (3 atomics: mcp/ `ee48401`, gating-wiring `b810bf4`, demo-e2e `003284e`) |
| Verdict | **clean** — 0🔴 · 0🟡 · 8🟢 |

## Summary

A faithful, thorough implementation of P3's heaviest constitutional/security slice — the `mcp/` client, the autonomy-gating wiring, the trust boundary, and the demo e2e all match the plan + ADR-027, **both plan-stage routing absorptions** (the R0-B Y1 timeout MUST-FIX + the arch-Y1 AUTO-only) landed, and every spine/trust/routing invariant is **discriminatingly tested**. The constitutional crux holds: P3.4 **feeds the gate, unchanged** — there is **no change** to `autonomy/scoring.py`, `autonomy/emission.py`, or `agents/tool_dispatch.py` (verified), and an MCP tool-call gates identically to a local one via a **registry merge**. Unclassified tools are **refused** (discovery≠permission); the server's hints **never** touch the tier; execution **keys on the `TOOL_CALL` event** and **fails closed**; the result is **untrusted, size-limited, content-gen-interpreted** outside `mcp/`; the subprocess gets a **minimal scoped env** and is **killed on timeout** (no orphan). I re-ran the gates: **51 mcp tests pass, ruff + mypy --strict clean.** No 🔴/🟡 — eight 🟢, with three scope/robustness observations (non-defects).

## Per-axis verification

| Axis | Delivered | Plan/ADR match | Evidence |
|---|---|---|---|
| **Feed-the-gate (HR#1/#6)** | ✓ `b810bf4` | ✓ **unchanged** | NO diff to `autonomy/scoring.py`/`emission.py`/`agents/tool_dispatch.py`; registry merge `api/app.py`: `tools = {**tools, **mcp_tools}` (namespaced, graceful). `test_gate_functions_signature_unchanged`. |
| **Pre-classify allowlist (HR#2/#3, D3)** | ✓ `ee48401` | ✓ | `adapter.build_tool_registry` registers ONLY `server_cfg.tools ∩ discovered` (config reversibility; hints ignored); unclassified → no `ToolMeta` → `UnknownToolError` refused. Tests: `…unclassified_tool_refused`, `…server_safe_hint_does_not_change_tier`, `…build_tool_registry_skips_unclassified`. |
| **Namespacing (D3)** | ✓ | ✓ | `namespace()` → `mcp__<server>__<tool>`; `to_mcp_call` reverse; `test_constitution_c5_no_namespace_collision`. |
| **Execution downstream of gate + AUTO-only (HR#4, arch-Y1)** | ✓ `b810bf4` | ✓ | `execute_mcp_tool_call` **requires a `TOOL_CALL` event** (raises otherwise); the e2e: `read_file` rev10→AUTO→`TOOL_CALL`→execute→`TOOL_RESULT`; `write_file` rev2→**HARD_CONFIRM→no TOOL_CALL→not executed** (`test_demo_write_file_hard_confirm_not_executed`). No confirm flow wired (deferred, per §5). |
| **Fail-closed + untrusted size-limit (HR#9/#10)** | ✓ | ✓ | execution: any error → `TOOL_FAILED`; result size-capped 64KiB + `output_truncated_at`. Tests: `…transport_error_appends_tool_failed`, `…oversized_result_truncated`, `…bad_tool_name_fail_closed`. |
| **R0-B Y1 timeout MUST-FIX (D1)** | ✓ `ee48401` | ✓ **genuinely** | `transport.py`: every SDK call in `asyncio.wait_for(timeout=connect+op)`; on `TimeoutError` → `MCPTimeoutError` + subprocess killed (stdio_client cleanup). `test_transport_hanging_server_subprocess_killed_no_orphan` **verifies the PID is dead via `os.kill(pid,0)`** (fails on orphan). + crash/list_tools/call timeouts fail-closed. |
| **Trust boundary — scoped env + credential + allowlist (HR#7/#8/#10)** | ✓ | ✓ | `_build_scoped_env`: only `_SAFE_ENV_KEYS` + `server.env` + scoped secret — NOT full `os.environ` (the c2 lesson). Tests: `…scoped_env_excludes_orchestrator_secrets`, `…scoped_env_no_full_os_environ`, `…api_key_env_credential_indirection`, `…boundary_undeclared_server_refused`. |
| **Interpret = content-gen, no new purpose (HR#5)** | ✓ `003284e` | ✓ | `agents/mcp_interpret.py` (**outside `mcp/`**): `LLMPurpose.TOOL_OUTPUT_INTERPRET` (no new purpose), **untrusted-external-data framing**, appends OBSERVATION, fails silently on LLM error. Tests: `…uses_tool_output_interpret_purpose`, `…fails_silently_on_llm_error`. |
| **mcp/ no-routing/judgment + config schema (HR#6, §6)** | ✓ `ee48401` | ✓ | constitution: c1 no-upstream-import, c2 no-routing, c3 no-LLM-provider-import, c4 no-new-LLMPurpose, c5 no-collision; `MCPServersConfig` frozen + `extra="forbid"` + loader tests. |

## Findings

None (0🔴 · 0🟡). Eight 🟢 below.

## What holds — verified clean (G1–G8)

- **G1 — feed-the-gate unchanged:** zero change to the gate decision logic (`score`/`decide_tier`/`gate`/`emit_gate_decision`/`process_tool_calls`); MCP tools merge into the same registry; `test_gate_functions_signature_unchanged`.
- **G2 — pre-classify allowlist + discovery≠permission:** only allowlisted∩discovered tools registered (config reversibility; hints ignored); unclassified → `UnknownToolError` refused — all tested discriminatingly.
- **G3 — execution downstream of gate + AUTO-only (both routing items):** `execute_mcp_tool_call` requires a `TOOL_CALL` event; the e2e demonstrates AUTO-executes + HARD-gated-not-executed (the arch-Y1 demonstration); no confirm flow wired (no scope creep).
- **G4 — R0-B Y1 timeout MUST-FIX genuinely closed:** `asyncio.wait_for` on every SDK call + subprocess killed on timeout; the no-orphan test verifies the PID is dead (not just that the timeout fires).
- **G5 — fail-closed + untrusted size-limit:** any transport error → `TOOL_FAILED`; 64KiB cap with `output_truncated_at`; tested.
- **G6 — trust boundary:** minimal scoped subprocess env (the P2.7-S3 c2 lesson, with a no-secrets/no-full-environ test) + `api_key_env` credential indirection + undeclared-server-refused.
- **G7 — interpret content-gen, no new purpose, untrusted-framed, outside `mcp/`:** `agents/mcp_interpret.py` reuses `TOOL_OUTPUT_INTERPRET`, frames the result as untrusted, fails silently — keeping `mcp/` LLM-free.
- **G8 — constitution + gates green independently:** no-upstream-import / no-routing / no-LLM-provider / no-new-LLMPurpose / no-collision + schema; 51 mcp tests + ruff + mypy --strict clean (re-run here).

**Observations (non-findings, 🟢-level):**
- **(a) `execute_mcp_tool_call` has no `run_turn` production caller** — it's a provided + tested capability, exercised **end-to-end in the e2e** (real `process_tool_calls` → real `execute_mcp_tool_call` → real interpret). This **matches the project's state**: there is **no tool-execution loop for *any* tool** (local tools aren't auto-run in `run_turn` either — the plan's own self-discovery "there is no existing tool-executor"). The plan/ADR scoped the execution *capability* keyed on the `TOOL_CALL` event + the e2e (both delivered); a `run_turn`-driven dispatch loop was never scoped (and "feed the gate, don't change it" cautions against adding one to the agent runtime in this slice). **Flagged for calibration:** the MCP loop is proven in-test, not yet turn-driven; wiring `execute_mcp_tool_call` into a general per-turn tool-execution step is the natural next slice (alongside that step for all tools).
- **(b) Per-operation subprocess connections** — `transport.py` spawns a fresh subprocess per `list_tools`/`call_tool` then tears down (vs the plan's `connect → session` reuse implication). A sound simplification (cleaner teardown, no lingering subprocess/session between calls, arguably more fail-closed) — not a defect.
- **(c) `to_mcp_call` `__`-split edge** — the reverse-namespace splits on `__` (maxsplit=1 from the left), so a *server* name containing `__` would mis-parse (`mcp__a__b__t` → `("a","b__t")`). Config-controlled names (the demo names are clean); a validator forbidding `__` inside server/tool names would harden it — low, edge case.

## Net

The implementation matches the plan + Accepted ADR-027 on every axis — the `mcp/` client/transport/adapter (with the bounded-timeout sync-bridge + scoped env), the registry-merge gating wiring (the gate **unchanged**), the pre-classify allowlist (discovery≠permission, fail-closed), the execution (TOOL_CALL-keyed, AUTO-only, fail-closed, size-limited), the content-gen interpret (no new purpose, untrusted-framed, outside `mcp/`), and the demo e2e — with **both plan-stage routing absorptions** (the R0-B Y1 timeout MUST-FIX, genuinely verified via the no-orphan PID check; the arch-Y1 AUTO-only, demonstrated) and every spine/trust invariant discriminatingly tested. Gates green independently (51 mcp tests + ruff + mypy --strict). The three observations are scope/robustness notes (the un-wired `run_turn` execution loop matches the codebase's no-tool-executor state; per-op connections; the `__`-split edge) — none a defect. **Verdict: clean.** Per ADR-008 Route B, state auto-advances; R0-A (+ the dual-lens R0-B, `requires_cross_family_review: true`) fire next. I did not advance or merge.
