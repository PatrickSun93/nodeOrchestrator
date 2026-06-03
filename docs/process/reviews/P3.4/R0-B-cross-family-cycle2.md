---
task_id: P3.4
round: R0-B-cross-family-cycle2
cycle: 2
stage: impl
reviewer_family: deepseek
reviews_acked:
  - decisions/ADR-028-runtime-tool-executor.md
  - senior-plans/P3.4-cycle2.md
  - reviews/P3.4/R0-B-cross-family-on-plan-cycle2.md
  - reviews/P3.4/architect-routing-on-plan-cycle2.md
verdict: needs_architect
findings_count:
  red: 0
  yellow: 1
  green: 10
verdict_history:
  - verdict: needs_architect
    at_commit: 6a72c99
    findings_count: { red: 0, yellow: 1, green: 10 }
    note: >-
      Impl-stage cross-family R0-B (DeepSeek) on P3.4 cycle-2 implementation at 6a72c99
      (C2-1..C2-4: executor framework + MCP wiring + local tools + bootstrap/turn-driver
      wiring + e2e + constitution tests). All seven plan-stage probes verified clean: R1
      interpret timeout FIXED (bounded-deadline + fail-soft), sandbox bounded-read correct
      (MAX_RESULT_BYTES+1 never full-file), path-escape/symlink/absolute all rejected with
      tests, TOCTOU posture explicitly acknowledged per ADR-028 D3, MAX_MCP_CALLS_PER_TURN
      cap enforced + fail-closed on exceed, double-execution guard = full-room-history scan,
      execution strictly downstream-of-TOOL_CALL (behavioral filter + sole-appender test
      confirms only tool_dispatch.py appends TOOL_CALL), not_implemented fail-closed via
      .get() not bare KeyError. One new 🟡: interpret timeout raises TimeoutError but does
      not cancel the future — a late-arriving write from the interpret pool could race with
      the writer thread (SQLITE_BUSY → crash in advisory path; harmless but untidy). Lean
      α one-liner: future.cancel() in the TimeoutError handler. Ten 🟢 cross-family
      confirmations. No 🔴 — the plan-stage blocking concerns are all resolved in the
      implementation.
---

# P3.4 cycle-2 R0-B cross-family impl-stage review — runtime tool-executor

| Field | Value |
|---|---|
| Round | R0-B-cross-family-cycle2 (true cross-family, impl-stage; plan-stage R1/🟡 re-probe) |
| Reviewer family | deepseek |
| Stage | Impl — `claude/P3.4-impl` @ `6a72c99` (C2-1..C2-4) |
| Artifacts | `tools/executor.py` (363 lines), `tools/local.py` (130 lines), `api/app.py` diff (36 lines), `mcp/adapter.py` diff (62 lines), `tests/tools/test_executor.py` (548 lines), `tests/tools/test_local.py` (334 lines), `tests/tools/test_e2e.py` (299 lines), `tests/tools/test_constitution.py` (212 lines), `handoff.md` diff, ADR-028 (Accepted, routing-absorbed) |
| Prior reviews | `R0-B-cross-family-on-plan-cycle2.md` (plan-stage: 1🔴 R1 + 4🟡 Y1-Y4), `architect-routing-on-plan-cycle2.md` (α-absorbed), `R0-A-on-plan-cycle2.md` |
| Date | 2026-06-02 |
| Verdict | **needs_architect** (0🔴 + 1🟡 + 10🟢) — the 🟡 is a one-line fix; no plan-stage concerns survive |

## Lens preamble

This is the **impl re-probe** of the plan-stage cross-family R0-B findings. The plan-stage review flagged 1🔴 (R1 — unbounded LLM interpret call on the single writer) + 4🟡 (Y1 double-exec scope, Y2 sandbox TOCTOU, Y3 t4 over-claim, Y4 Σ-of-bounds). All were routed α, absorbed into ADR-028, and the implementation claims to address each. This review traces the **actual code** at `6a72c99` to verify the claims hold in the implementation — not the ADR text, but the running code.

The seven explicit probes from the dispatch: (1) R1 fix — interpret timeout + fail-soft; (2) bounded read not OOM; (3) path-escape/symlink reject; (4) TOCTOU posture; (5) D5 liveness — cap + bounded deps; (6) double-exec full-room + race-free; (7) execution downstream-of-TOOL_CALL. Plus not_implemented .get() hygiene.

## Verified probes — plan-stage concerns resolved

### 1. R1 Fix — interpret timeout ✅

**Claim:** Interpret LLM call runs under bounded deadline; on timeout, raw TOOL_RESULT stands, no OBSERVATION, writer not blocked indefinitely.

**Code trace:** `tools/executor.py:56-63` defines `INTERPRET_TIMEOUT_S = 30.0` and `_INTERPRET_EXECUTOR = ThreadPoolExecutor(max_workers=4)`. `_interpret_bounded()` (lines 198-230): submits `interpret_mcp_tool_result` to the interpret pool via `future = _INTERPRET_EXECUTOR.submit(...)`, then `future.result(timeout=INTERPRET_TIMEOUT_S)`. On `_FutureTimeout`: logs warning, **no OBSERVATION appended**. On any other `Exception`: same. The writer thread blocks for at most 30s per MCP interpret call → **bounded**. The interpret is **advisory** (content-gen only; the TOOL_RESULT was already appended by the synchronous `execute_mcp_tool_call`).

**Test:** `test_executor.py::test_bounded_interpret_timeout_no_observation` — monkeypatches `INTERPRET_TIMEOUT_S = 0.05`, uses a `HangingRouter` that blocks on a threading.Event, asserts `elapsed < 1.0s` (writer not blocked indefinitely), asserts TOOL_RESULT present, asserts NO OBSERVATION.

**Verdict:** ✅ R1 resolved. The interpret is genuinely bounded + fail-soft.

### 2. Local sandbox bounded read — no OOM ✅

**Claim:** `read_file` reads at most `MAX_RESULT_BYTES (+1)` bytes, never loading the full file into memory.

**Code trace:** `tools/local.py:70-73`:
```python
with resolved.open("rb") as fh:
    raw = fh.read(MAX_RESULT_BYTES + 1)
truncated = len(raw) > MAX_RESULT_BYTES
if truncated:
    raw = raw[:MAX_RESULT_BYTES]
```
Reads at most 64 KiB + 1 byte in **binary mode** — the `+1` detects truncation. The entire file is never materialized. `output_truncated_at` is set iff truncated. `MAX_RESULT_BYTES = 65536` (imported from `mcp/execution.py`).

**Test:** `test_local.py::test_read_file_oversized_bounded_read` — writes a `MAX_RESULT_BYTES + 1000` byte file, verifies result content ≤ `MAX_RESULT_BYTES` bytes, `output_truncated_at == MAX_RESULT_BYTES`.

**Verdict:** ✅ No OOM vector. Bound is correct and tested.

### 3. Path escape / symlink / absolute — all rejected ✅

**Code trace:** `tools/local.py:112-126` — `_check_path(path_str, resolved_root)`:
```python
candidate = (resolved_root / path_str).resolve()
try:
    candidate.relative_to(resolved_root)
except ValueError as exc:
    raise LocalToolError(f"path escapes sandbox root: ...")
```
`Path.resolve()` follows symlinks BEFORE the containment check (`relative_to`). Rejects: `..` traversal, absolute paths, symlinks pointing outside.

**Tests:**
- `test_read_file_path_traversal_rejected` — `../../etc/passwd` → `TOOL_FAILED`
- `test_read_file_absolute_path_outside_rejected` — `/etc/passwd` → `TOOL_FAILED`
- `test_read_file_symlink_escape_rejected` — symlink to outside → `TOOL_FAILED`
- `test_list_files_path_escape_rejected` — `list_files` with `../..` → `TOOL_FAILED`

**Verdict:** ✅ Path containment is correct. Symlink traversal happens BEFORE the check, not after — the ordering is correct.

### 4. TOCTOU posture — explicitly acknowledged ✅

**Code trace:** `tools/local.py:9-10`:
```python
# Threat model: untrusted input = LLM-proposed path; sandbox root = trusted.
# TOCTOU out of MVP scope (ADR-028 D3 — deliberate stated posture).
```
ADR-028 D3 (Accepted, routing-absorbed) explicitly names the TOCTOU window as an MVP-accepted posture. The code documents it inline. This is exactly what plan-stage Y2 asked for: acknowledge the gap, don't over-claim.

**Verdict:** ✅ TOCTOU posture is explicitly stated in both code and ADR — not hidden, not over-claimed.

### 5. D5 single-writer liveness — genuinely bounded ✅

**Claim:** Every inline blocking dependency is timeout-wrapped + a per-turn MCP cap bounds the Σ.

**Code trace:**
- `MAX_MCP_CALLS_PER_TURN = 10` (`executor.py:51`)
- MCP execution: `execute_mcp_tool_call` (cycle-1, bounded via `asyncio.wait_for` + subprocess-kill)
- MCP interpret: `_interpret_bounded` (bounded via `future.result(timeout=30s)`)
- Local tools: clock (pure), FS reads (bounded `MAX_RESULT_BYTES+1` — no network, no subprocess)
- Cap enforcement (`executor.py:120-137`): `mcp_calls_this_turn` counter; excess → `TOOL_FAILED(error_class="turn_mcp_cap_exceeded")`
- Local tools NOT subject to cap (test confirms)

**Test:** `test_per_turn_mcp_cap_exceeded_fails_closed` — `MAX_MCP_CALLS_PER_TURN + 1` MCP calls → first N succeed, excess fails. `test_local_tools_not_subject_to_mcp_cap` — N+5 local calls all succeed.

**Verdict:** ✅ Every inline dependency is timeout-wrapped. The Σ is bounded by `10 × (40s MCP + 30s interpret) = 700s` worst case. The cap is generous but it IS a cap. Per ADR-028 D5: "an absolute bound, every term finite."

### 6. Double-execution guard — full-room history, single-writer race-free ✅

**Code trace:** `tools/executor.py:92-97`:
```python
all_room_events = event_store.get_room_events(room_id)
already_executed: set[str] = {
    str(e.metadata.get("call_id", ""))
    for e in all_room_events
    if e.type in (EventType.TOOL_RESULT, EventType.TOOL_FAILED) and e.metadata.get("call_id")
}
```
Full room history — NOT the post-cursor window. This is what plan-stage Y1 asked for clarification on. Line 152 updates the set after each execution (`already_executed.add(call_id)`), so same-turn duplicate TOOL_CALL events are also guarded.

Race-free because: single-writer thread, the check and execute are sequential, no concurrent writer can insert a result between check and execute. ADR-028 D2 flags the forward-watch: if the deferred separate-execution-lane lands, this becomes a TOCTOU and needs an atomic claim.

**Tests:**
- `test_double_execution_guard_skips_already_executed_in_window` — TOOL_RESULT pre-exists in room → skipped, transport NOT called
- `test_double_execution_guard_full_room_scope_prior_turn` — TOOL_RESULT from a **prior turn** (not in current window) → still skipped

**Verdict:** ✅ Guard is full-room scope, race-free under single-writer, with forward-watch documented.

### 7. Execution downstream of TOOL_CALL — behavioral + sole-appender structural ✅

**Code trace:** `tools/executor.py:88-89`:
```python
tool_calls = [e for e in window_events if e.type == EventType.TOOL_CALL]
if not tool_calls:
    return
```
Behavioral filter on `EventType.TOOL_CALL`. The executor never forges a TOOL_CALL event (it only appends TOOL_RESULT/TOOL_FAILED).

**Structural sole-appender test:** `tests/tools/test_constitution.py::test_t4_tool_call_sole_appender_in_src` — AST-scans ALL `src/` Python files, verifies ONLY `agents/tool_dispatch.py` calls `event_store.append(Event(..., type=EventType.TOOL_CALL))`. Any other file appending TOOL_CALL = violation. This is the "structural" half of t4 — it is an AST check, but it's a genuine one (not vacuous — it walks AST Call nodes and checks keyword arguments). Combined with the behavioral filter, this provides a real defense-in-depth: TOOL_CALLs can ONLY come from `process_tool_calls` (gate-approved); the executor only acts on TOOL_CALL events.

**Gate diff:** `git diff origin/claude/P3.4-impl~4..origin/claude/P3.4-impl -- src/orchestrator/autonomy/ src/orchestrator/agents/tool_dispatch.py src/orchestrator/rooms/` → **empty** (verified). The forcing function holds.

**Test:** `test_no_tool_call_in_window_zero_executions` — USER_INPUT event → executor makes zero calls. `test_empty_window_zero_executions` — empty window → zero calls.

**E2e demo:** `test_e2e_hard_mcp_tool_not_executed` — agent calls HARD_CONFIRM tool (rev 2) → gate appends autonomy_decision but NO TOOL_CALL → executor has nothing to execute → no TOOL_RESULT in room events.

**Verdict:** ✅ Execution is genuinely downstream of the gate. The chain gate→TOOL_CALL→executor has no bypass.

### 8. not_implemented fail-closed — .get() not bare KeyError ✅

**Code trace:** `tools/executor.py:233`:
```python
impl = local_tools.get(tool_name)
if impl is None:
    _log.warning(...)
    _append_tool_failed(..., error_class="not_implemented")
    return
```
Uses `.get()` with explicit None check. Never a bare `local_tools[tool_name]` that would raise `KeyError`. Similarly for MCP sessions: `mcp_sessions.get(server)` at line 176 — miss → `TOOL_FAILED(error_class="not_available")`.

**Test:** `test_classified_but_unimplemented_tool_fails_closed` — `web_search` (in tools.yaml but not in local registry) → `TOOL_FAILED(error_class="not_implemented")`, no TOOL_RESULT, no crash.

**Verdict:** ✅ Fail-closed for all lookup paths. No bare KeyError risk.

---

## New finding — implementation-level

| # | Sev | Finding | Basis |
|---|---|---|---|
| Y1 | 🟡 | **Interpret timeout does not cancel the future — late-arriving OBSERVATION write from the interpret pool can race with the writer thread.** `_interpret_bounded()` (`executor.py:216-230`) catches `_FutureTimeout` and logs, but does NOT call `future.cancel()`. The interpret task continues running on `_INTERPRET_EXECUTOR` in the background. When it eventually completes (after the timeout), `interpret_mcp_tool_result` calls `event_store.append(OBSERVATION)` — potentially while the writer thread is writing the next tool call's `TOOL_RESULT`. SQLite WAL + `check_same_thread=False` allows this, but concurrent `append()` calls from two threads on the same connection can raise `sqlite3.OperationalError: database is locked`. The outcome is harmless (OBSERVATION is advisory; a crash in the interpret just loses the description — same as timeout), but the crash traceback in the interpret pool thread is untidy and the late-arriving OBSERVATION could appear out-of-order in the event stream (after the next turn's events, confusing consumers). Fix: `future.cancel()` in the `except _FutureTimeout` block. One-line addition. | `tools/executor.py:216-230` (`_interpret_bounded` — `future.result(timeout=...)` catches TimeoutError but doesn't cancel); `agents/mcp_interpret.py:39-100` (`interpret_mcp_tool_result` calls `event_store.append(OBSERVATION)` from whichever thread calls it) |

---

## Green confirmations (cross-family)

| # | Finding | Evidence |
|---|---|---|
| G1 | **Constitution t1–t4 all pass + are genuine (non-vacuous).** t1: AST scan forbids upstream imports of `orchestrator.tools` — covers 11 upstream roots, walks AST Import/ImportFrom nodes, not just string grep. t2: AST scan forbids `decide_tier`/`emit_gate_decision`/`score`/`gate` in `tools/` — checks Name and Attribute nodes. t3: runtime check that `LLMPurpose` enum has exactly the frozen set (9 values) — will fail on any new purpose addition. t4: AST scan verifies ONLY `agents/tool_dispatch.py` appends `EventType.TOOL_CALL` events — walks all Call→append→Event→type=TOOL_CALL patterns across `src/`. No vacuous "assert True" or grep-only checks. | `tests/tools/test_constitution.py` (212 lines, full AST walk) |
| G2 | **Session retention works — `build_mcp_tool_registry_and_sessions_from_config` returns both registry and sessions.** The new function (`mcp/adapter.py:149-195`) mirrors the old one but retains `MCPSession` objects built during discovery. Sessions keyed by server name. `skip_unavailable` preserved. The old `build_mcp_tool_registry_from_config` still exists (backward compat). The bootstrap (`api/app.py:149-153`) calls the new function, stores both in `AppContext`. Verified: session holds no long-lived subprocess (transport spawns per-call). | `mcp/adapter.py:149-195`; `api/app.py:149-153` |
| G3 | **Executor placement correct — post-dispatch in `_write_and_turn`, between `run_turn` and `new_events` read.** `api/app.py:327-336`: executor invoked after `run_turn` returns, before the `get_room_events[pre_cursor:]` read that publishes new events. Passes the window of TOOL_CALL events from this turn only. The executor appends TOOL_RESULT/TOOL_FAILED/OBSERVATION to the same store on (mostly) the same writer thread. The post-stage `new_events` read picks them up → published to WS subscribers. | `api/app.py:327-336` |
| G4 | **Local-tool results trusted — not interpreted, no OBSERVATION.** `_execute_local_call` (`executor.py:241-268`) appends `TOOL_RESULT` directly — no interpret call. Test (`test_local_tool_result_not_interpreted`) verifies `llm_router.call` is NOT called for local tools and no OBSERVATION event appears. | `tools/executor.py:241-268`; `test_executor.py:164-185` |
| G5 | **Per-call isolation — first tool failure doesn't block second.** `test_per_call_isolation_first_fails_second_executes`: first local tool raises `RuntimeError` → `TOOL_FAILED`; second tool still runs → `TOOL_RESULT`. Both the executor's main loop (lines 105-152) and the `_execute_local_call` function (lines 248-251) wrap individual calls in try/except. | `tools/executor.py:105-152`; `test_executor.py:300-326` |
| G6 | **HARD_CONFIRM tools genuinely not executed — gate-only, no TOOL_CALL.** `test_e2e_hard_mcp_tool_not_executed`: agent calls `mcp__test__write` (rev 2 → HARD_CONFIRM). Events contain `autonomy_decision` but NO `tool_call`, NO `tool_result`. The gate records its decision; the executor has nothing to execute. The cycle-1 constitutional demonstration carries forward intact. | `tests/tools/test_e2e.py:241-265` |
| G7 | **Handoff de-claimed — cycle-1→cycle-2 distinction clear.** `handoff.md` now reads "P3.4 cycle-1 已落地" (MCP client + gating only) and "P3.4 cycle-2 已落地" (runtime executor — TOOL_CALL events now actually executed at runtime). The cycle-1 "AUTO_EXECUTE 执行" claim is corrected to "TOOL_CALL events 由 gate 写入，但 runtime 未实际执行（execution stage 在 cycle-2）". | `handoff.md` diff (15 lines changed) |
| G8 | **ADR-028 D5 claims verified in code — every claim traced to implementation.** "inline on the single writer" ✅ (executor called in `_write_and_turn` on `ThreadPoolExecutor(max_workers=1)`). "MCP interpret bounded deadline" ✅ (INTERPRET_TIMEOUT_S, future.result timeout). "per-turn cap" ✅ (MAX_MCP_CALLS_PER_TURN, enforced). "local tools fast + bounded" ✅ (clock=no I/O, FS=bounded read, no network/subprocess). "worst-case block ≤ N × (MCP+interpret timeout)" ✅ (cap=10, MCP=40s, interpret=30s). | `tools/executor.py:51,56-63,88-152,198-230`; `tools/local.py:70-73` |
| G9 | **E2e tests exercise the full runtime path — three constitutional demonstrations.** `test_e2e_local_auto_tool`: POST /intent → local AUTO → TOOL_RESULT (no OBSERVATION). `test_e2e_mcp_auto_tool`: POST /intent → MCP AUTO (mocked session) → TOOL_RESULT + OBSERVATION. `test_e2e_hard_mcp_tool_not_executed`: POST /intent → HARD → no TOOL_CALL, no TOOL_RESULT. All three use FastAPI `TestClient` — the actual HTTP request path, not a unit-test shortcut. | `tests/tools/test_e2e.py` (299 lines, 3 e2e + 1 bootstrap default test) |
| G10 | **No executor code path crashes the turn or leaves the room incoherent.** Per-call try/except in the main loop (line 149-152), per-call try/except in `_execute_local_call` (lines 248-251), fail-closed in `execute_mcp_tool_call` (cycle-1, append TOOL_FAILED on any error), fail-closed in `_execute_mcp_call` (session miss → TOOL_FAILED). All event appends are idempotent (SQLite INSERT, not UPDATE). The worst case: executor crashes mid-loop on an internal bug (line 150-152 catches + logs + continues). Partial execution: already-executed tools' results are in the store (appended before the crash); subsequent tools' results are absent → the agent sees what executed on the next turn. This is coherent (the agent can reason about missing results as "not yet executed"). | `tools/executor.py:105-152` |

## Synthesis

The plan-stage 🔴 R1 is **genuinely resolved** in the implementation: the interpret LLM call runs under a bounded 30s deadline on a separate thread pool, and on timeout the raw TOOL_RESULT stands (fail-soft — interpretation is advisory content-gen). All four plan-stage 🟡 (Y1 double-exec scope, Y2 sandbox TOCTOU, Y3 t4 over-claim, Y4 Σ-of-bounds) are addressed: the implementation chose full-room-history for the double-exec guard, explicitly documents the TOCTOU posture, has genuine (non-vacuous) AST-walk constitution tests, and enforces a per-turn MCP call cap. The implementation is thorough, well-tested (28 tests across 4 new test files, plus the carry-forward 51 MCP tests + rooms/agents constitution tests), and faithfully follows the routing-absorbed ADR-028.

One new 🟡 at the implementation level: the interpret timeout handler doesn't cancel the future. A one-line `future.cancel()` addition prevents a harmless-but-untidy late-arriving OBSERVATION write. Not blocking — the worst case is a `sqlite3.OperationalError` traceback in the interpret pool thread (the TOOL_RESULT already landed; the OBSERVATION is advisory). But worth fixing before merge for cleanliness.

No 🔴 findings. The plan-stage blocking concern is resolved. The implementation earns a **needs_architect** → **clean** after the one-line fix.

## Recommended routing

| # | Lean | Rationale |
|---|---|---|
| Y1 | **α one-liner** | Add `future.cancel()` in the `except _FutureTimeout` block at `executor.py:226`. Prevents the late-arriving write from the interpret pool. The fix is trivial; the architect can fold it into the merge or have junior push a C2-5. |
| G1–G10 | **confirm** | Ten cross-family confirmations — all plan-stage concerns verified resolved in the running code. No action needed. |

## Cross-reference — RC-20 correction-mode

The plan-stage R0-B found 1🔴 + 4🟡. All were α-absorbed into ADR-028 and verified in the implementation. This is a **net-new confirmations** round (the impl re-probe validates that the α fixes landed correctly), not a correction of an in-family error. The cross-family lens earned its keep at plan stage (the interpret-timeout 🔴 was a genuine miss the in-family R0-A didn't catch); the impl-stage lens now confirms the fix landed. If the in-family R0-A-cycle2 also returns clean, the dual-lens ROI on cycle-2 is: 1🔴 design-level runtime bug avoided (the no-timeout LLM call on the single writer) + 4🟡 design clarifications + 10🟢 cross-family confirmations at impl. The pattern from cycle-1 R0-B (1🟡 bridge-timeout → α → clean) repeats at one layer up.
