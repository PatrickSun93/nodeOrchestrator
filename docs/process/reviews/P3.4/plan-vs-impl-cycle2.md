---
task_id: P3.4
cycle: 2
round: plan-vs-impl
reviewer: senior
stage: impl (origin/claude/P3.4-impl @ 6a72c99 — C2-1..C2-4)
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 9
verdict_history:
  - verdict: needs_architect
    at_commit: 6a72c99
    findings_count: { red: 0, yellow: 1, green: 8 }
    note: >-
      Cycle-2 plan-vs-impl @ 6a72c99. 6/7 architect-named hard points faithful; Y1 — the R1
      interpret-timeout ran the whole interpret_mcp_tool_result (incl. OBSERVATION append) on
      a pool thread → OBSERVATION appended off the single-writer thread, drifting on ADR-028
      D1/D5 + a latent timeout-orphan sqlite race. Surfaced, not fixed.
  - verdict: clean
    at_commit: 640a9e3
    findings_count: { red: 0, yellow: 0, green: 9 }
    note: >-
      Y1 absorbed per architect impl-stage routing (architect-routing-on-impl-cycle2.md,
      2026-06-03; α — my lean option (a)). Fix at 1bd3a07: the pool task is now LLM-only
      (get_mcp_tool_interpretation — no event_store access, returns str|None); the OBSERVATION
      event_store.append moved back to the single writer thread, after future.result() returns;
      on timeout → future.cancel() + no append (raw TOOL_RESULT stands, writer unblocked). A
      leaked/timed-out pool thread can only return text, never touches the store — the ADR-028
      D1/D5 single-writer invariant is restored (no ADR change: the impl now matches the
      already-inscribed invariant). Verified: pool submit passes no event_store; append on
      writer; future.cancel on timeout; full gate green + empty gate diff (orchestrator-verified
      @ 640a9e3). 1 finding → 1 new 🟢 (9🟢).
artifacts_reviewed:
  - src/orchestrator/tools/executor.py           # C2-1 execute_pending_tool_calls
  - src/orchestrator/tools/local.py              # C2-2 local impls + sandbox
  - src/orchestrator/api/app.py                  # C2-3 AppContext + _build_context + _write_and_turn stage
  - src/orchestrator/mcp/adapter.py              # C2-3 session-retaining builder
  - tests/tools/test_constitution.py             # C2-4 t1-t4
  - tests/tools/{test_executor,test_local,test_e2e}.py
plan_baseline:
  - docs/process/senior-plans/P3.4-cycle2.md     # C2-1..C2-4 + §3/§4 + §5-resolved
  - docs/decisions/ADR-028-runtime-tool-executor.md  # Accepted (D1..D6)
  - docs/process/reviews/P3.4/architect-routing-on-plan-cycle2.md  # R1 α + 6🟡 α
note: >-
  Cycle-2 plan-vs-impl on the runtime tool-executor @ 6a72c99. Distinct filename from
  cycle-1's plan-vs-impl.md (same path collides despite the cycle counter). 6 of the 7
  architect-named hard points are faithfully implemented; the 7th (R1 interpret-timeout)
  meets its acceptance criterion (the writer is bounded) but the chosen mechanism — running
  the WHOLE interpret_mcp_tool_result, including its OBSERVATION event_store.append, on a
  4-worker ThreadPoolExecutor — appends OFF the single-writer thread, drifting on the
  ADR-028 D1/D5 single-writer invariant the ADR explicitly inscribes ("same writer thread /
  no store concurrency") and opening a latent timeout-path sqlite concurrency hazard
  (an orphaned, timed-out interpret thread can append the late OBSERVATION concurrently
  with the writer on the same check_same_thread=False connection). Surfaced, not fixed
  (Y1 → architect routes; prime impl-stage R0-B target — the D5 liveness/concurrency surface).
---

# P3.4 cycle-2 plan-vs-impl — the runtime tool-executor (@ 6a72c99)

> **Verdict bump 2026-06-03 (RC-10 — frontmatter as live signal): `needs_architect → clean`.**
> The sole 🟡 (Y1 — the R1 interpret-timeout appended the OBSERVATION off the single-writer
> thread) was routed **α** by the architect (`architect-routing-on-impl-cycle2.md`) and fixed at
> **1bd3a07**: the pool task is now the LLM call only (`get_mcp_tool_interpretation`, no
> `event_store` access); the `OBSERVATION` append is back on the single writer thread after
> `future.result()`; on timeout → `future.cancel()` + no append. The single-writer invariant
> (ADR-028 D1/D5) is restored — verified at **640a9e3** (pool submit passes no `event_store`;
> append on the writer; full gate green + empty gate diff). 1🟡 → 1🟢. Finding body preserved below.

> **Senior plan-vs-impl lens.** I check the impl against my `P3.4-cycle2.md` + the **Accepted** ADR-028, focusing on the seven hard points the architect named (the plan-stage routing absorptions). The unique surface this lens covers: where the impl satisfies an acceptance criterion (and passes gates) but drifts on a **plan-implied invariant** the external lenses + the green gate don't structurally see. I found exactly one such drift (Y1) on the R1 interpret-timeout mechanism; the other six points are faithful.

## 1. The seven architect-named hard points

| # | Point | Verdict | Evidence |
|---|---|---|---|
| 1 | **interpret LLM call timeout-wrapped (timeout → raw result, no interpret)** | 🟡 **drift** (see Y1) | `executor.py:223-269` `_interpret_bounded`: submits to `_INTERPRET_EXECUTOR` (`:51`, `max_workers=4`) + `future.result(timeout=INTERPRET_TIMEOUT_S=30.0)`; on `_FutureTimeout`/`Exception` → log + return (raw `TOOL_RESULT` stands, no `OBSERVATION`). **Writer IS bounded (R1 acceptance met)** — but the interpret's `event_store.append(OBSERVATION)` runs on the pool thread, **off the single writer** (Y1). |
| 2 | **read_file bounded read ≤ MAX_RESULT_BYTES(+1), no full-file load** | ✅ faithful | `local.py:58-67`: `fh.read(MAX_RESULT_BYTES + 1)`; `truncated = len(raw) > MAX_RESULT_BYTES`; slice to cap; `output_truncated_at` set. Never loads the whole file. Exactly ADR-028 D3 / routing R0A-Y1. |
| 3 | **double-exec guard = full-room `get_room_events` by `call_id`** | ✅ faithful | `executor.py:97-104`: `all_room_events = event_store.get_room_events(room_id)`; `already_executed` = `{call_id …}` from **all** `TOOL_RESULT`/`TOOL_FAILED` in the room (not the window); `:115` skip if seen; `:167` in-loop add. Matches ADR-028 D2 / routing R0B-Y1. |
| 4 | **MAX_MCP_CALLS_PER_TURN cap, excess fail-closed** | ✅ faithful | `executor.py:43` `MAX_MCP_CALLS_PER_TURN=10` (a documented constant per ADR-028 D5); `:125-139` excess → `TOOL_FAILED(error_class="turn_mcp_cap_exceeded")`, not executed; local tools uncapped. Matches D5 / routing R0B-Y4. |
| 5 | **executor in `tools/` leaf, invoked by `_write_and_turn`** | ✅ faithful | `tools/executor.py` + `tools/local.py` (leaf pkg, imports mcp/agents/core/llm — no upstream importer, see point 6/t1). `app.py:327-336` (diff): `execute_pending_tool_calls(window=get_room_events[pre_cursor:], …)` called **after** `run_turn`, **before** the publish read. Matches ADR-028 D1. `run_turn`/`dispatch_turn` untouched. |
| 6 | **t1-t4 constitution tests exist + effective** | ✅ faithful | `tests/tools/test_constitution.py`: **t1** AST-scans 12 upstream roots for `orchestrator.tools` imports; **t2** AST-scans `tools/` for `decide_tier`/`emit_gate_decision`/`score`/`gate`; **t3** frozen 9-value `LLMPurpose` set; **t4** AST sole-appender (`TOOL_CALL` appended only in `tool_dispatch.py`). All real assertions, not vacuous; behavioral half of t4 in `test_executor.py §7`. |
| 7 | **gate diff empty** | ✅ faithful | `git diff origin/main origin/claude/P3.4-impl -- src/orchestrator/autonomy/ src/orchestrator/agents/tool_dispatch.py` → **empty**. The gate (`score`/`decide_tier`/`emit_gate_decision`/`process_tool_calls`) is untouched; the executor is an additive downstream stage. |

## 2. Finding

| # | Sev | Finding | Basis |
|---|---|---|---|
| **Y1** | 🟡 | **The R1 interpret-timeout is implemented by running the *entire* `interpret_mcp_tool_result` — including its `OBSERVATION` `event_store.append` — on a 4-worker thread pool, so the OBSERVATION is appended OFF the single-writer thread. This satisfies R1's acceptance (the writer is bounded to ≤30 s) but drifts on the ADR-028 D1/D5 single-writer invariant the ADR explicitly inscribes, and opens a latent timeout-path concurrency hazard.** ADR-028 **D1** (stage signature): *"It appends `TOOL_RESULT`/`TOOL_FAILED` (+ MCP `OBSERVATION`) to the same store on the **same writer thread**."* **D5**: *"inline-on-the-writer … **preserves the single-writer invariant — all appends from one thread, no store concurrency**."* The impl (`executor.py:249-257`) submits `interpret_mcp_tool_result` to `_INTERPRET_EXECUTOR` (`max_workers=4`), and that function calls `event_store.append(OBSERVATION)` (`agents/mcp_interpret.py:102`) — i.e. the OBSERVATION append runs on a `tools-interpret` pool thread, **not** the `api-writer` thread. The writer connection is opened `check_same_thread=False` **with the explicit rationale** *"the single-thread executor serializes all writes"* (`api/app.py:126-128`) — a rationale this off-writer append voids. **Success path** (interpret returns < 30 s): the writer is blocked on `future.result(...)` while the pool thread appends, so there is no *simultaneous* access and it works (and the e2e `test_e2e.py:231` asserts the OBSERVATION lands — green). **R1 timeout path** (the LLM hangs > 30 s — exactly what R1 exists to make safe): the writer proceeds after 30 s, the orphaned interpret thread keeps running, and if the LLM later returns it appends the late OBSERVATION from the pool thread **concurrently** with the writer's next-turn appends on the **same** `check_same_thread=False` connection → a sqlite concurrent-use race (`recursive use of cursors` / `database is locked` / interleaved-transaction corruption). The green gate does not cover this — no test exercises the timeout-orphan-then-late-append path. Secondary: a late OBSERVATION lands after `new_events = get_room_events[pre_cursor:]` has already been published → silently dropped from that turn's WS publish. | ADR-028 D1 (`docs/decisions/ADR-028-runtime-tool-executor.md:36`), D5 (`:73`); `executor.py:51,249-257`; `agents/mcp_interpret.py:102`; `api/app.py:126-128` (`check_same_thread=False` + "single-thread executor serializes all writes"); `tests/tools/test_e2e.py:231` (asserts OBSERVATION on success path only) |

**Reconciliation options (architect routes — I do NOT choose):**
- **(a) Bound the LLM call only; append on the writer.** Run `llm_router.call(...)` (the sole unbounded dependency) under the deadline on the pool, return the interpretation string to the writer thread, and append the OBSERVATION there — restoring D1/D5 "same writer thread / no store concurrency" verbatim while keeping the writer bounded. (This is the literal reading of the R1 routing: *"给 mcp_interpret 的 llm_router.call 加 bounded timeout"* — wrap the **call**, not the whole function.)
- **(b) Keep the off-thread interpret but give it its own connection + amend D1/D5.** A separate sqlite connection for the interpret pool removes the shared-connection race; the ADR's "no store concurrency / same writer thread" claim would then need amending (it is no longer accurate), and the late-OBSERVATION-after-publish behavior documented.
- (Lean: (a) — it is the smallest change, preserves the inscribed invariant, and avoids re-opening the concurrency surface R1 was closing. But this is a design call — architect's to route; a prime probe for the mandatory impl-stage dual-lens R0-B, which the brief already points at the D5 liveness/concurrency surface.)

## 3. Confirmations (🟢)

| # | 🟢 | Note |
|---|---|---|
| G1 | Bounded read (point 2) | `read(MAX_RESULT_BYTES+1)` — the no-OOM guard is structural, not store-then-truncate (R0A-Y1 fully absorbed). |
| G2 | Full-room double-exec scope (point 3) | `get_room_events(room_id)` whole-room `call_id` set + in-loop add — cross-turn collisions caught (R0B-Y1 absorbed). |
| G3 | Per-turn MCP cap (point 4) | `MAX_MCP_CALLS_PER_TURN=10`; excess → `turn_mcp_cap_exceeded`; local uncapped (R0B-Y4 absorbed). |
| G4 | `mcp_sessions.get(server)` → `not_available` (S5-2) | `executor.py:193-208` — explicit `TOOL_FAILED(error_class="not_available")`, no bare `KeyError`. |
| G5 | `not_implemented` fail-closed | `executor.py:288-303` — classified-but-unimplemented local tool → `TOOL_FAILED(error_class="not_implemented")`, no silent no-op. |
| G6 | Local sandbox containment | `local.py:97-112` `_check_path` resolves (symlinks followed) + `relative_to(root)` → escape (traversal/absolute/symlink) raises `LocalToolError` → `TOOL_FAILED`. Threat model stated in the module docstring (R0A/R0B-Y2 absorbed). Local results not interpreted (`_execute_local_call` never calls interpret). |
| G7 | Per-call fail-closed isolation + leaf placement (points 5/6/7) | `executor.py:123-164` per-call try/except → one failure → `TOOL_FAILED`, others continue; `tools/` leaf (t1); gate diff empty (t4 sole-appender + the empty diff). |
| G8 | Session-retention + handoff de-claim | `mcp/adapter.py` `build_mcp_tool_registry_and_sessions_from_config` (returns sessions, not discarded); `app.py` AppContext `mcp_sessions`; `handoff.md` de-claims the old "AUTO_EXECUTE 执行" line + records the cycle-2 executor honestly. |

## 4. Process observations (non-blocking)

- **O1 — `_INTERPRET_EXECUTOR` lifecycle.** The interpret pool is a module-global `ThreadPoolExecutor` never shut down (`AppContext.shutdown` closes the writer/reader executors but not this one). Minor resource-cleanup nit; not a correctness issue. (If Y1 is routed to option (a), this pool may disappear entirely.)
- **O2 — cap=10 vs reviewer-suggested 5.** ADR-028 D5 said "a documented constant"; the senior plan left the value to the impl. 10 is within range; not a drift. (Documented in `executor.py:43`.)

## 5. Verdict

**needs_architect** — 0🔴 · 1🟡 · 8🟢. Six of seven hard points faithfully implemented; the gate diff is empty; the constitution tests are real. The one 🟡 (Y1) is the senior-lens catch: the R1 interpret-timeout meets its acceptance criterion (writer bounded) but its mechanism appends the OBSERVATION off the single-writer thread, drifting on the inscribed D1/D5 single-writer invariant and opening a latent timeout-path sqlite concurrency hazard that the green gate does not cover. Surfaced with evidence + two reconciliation options; **not** fixed here (architect routes; prime impl-stage dual-lens R0-B target).

Per ADR-008 Amendment 1 (Route B), the state advances to `awaiting_R0_A` regardless of this verdict; the dual-lens R0-B is mandatory (`requires_cross_family_review: true`) and should re-probe Y1's timeout-path concurrency on the running executor.
