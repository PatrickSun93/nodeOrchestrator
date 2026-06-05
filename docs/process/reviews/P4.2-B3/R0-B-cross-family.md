---
task_id: P4.2-B3
round: R0-B
verdict: needs_architect
findings_count:
  red: 0
  yellow: 3
  green: 3
review_date: 2026-06-05
reviewer: cross-family (DeepSeek V4 Pro via role-rewriting proxy)
---

# R0-B cross-family review — P4.2-B3 (subprocess local tools, impl-stage)

## Lens preamble

This review applies the two lenses from `docs/process/reviews/P4.2-B3/external-r0b-prompt.md`:

- **(A) Subprocess trust boundary** — trace every path: argv injection, env scoping (the c2 lesson), output-as-untrusted framing (P4.1 Y1 surface widened), residual honesty.
- **(B) Liveness under single writer × turn-loop** — kill-no-orphan under timeout, per-turn cap, bounded output, the compounding term.

Over-correction target: Claude-family models trust that "if the types are right, the runtime is right." I specifically probe every async cancellation path, every `error_class` propagation, and every `finally` block placement — the runtime-integration questions Clarkes under-weight.

---

## Lens A — Subprocess trust boundary

### 🟡 A1 — `error_class` homogenized to `"executor_error"` for all subprocess tool failures

**File:line:** `src/orchestrator/tools/executor.py:371-376` (call site) + `:400-407` (`_append_tool_failed` default)

**Claim:** `_execute_local_call` catches any exception from the tool impl and calls `_append_tool_failed(...)` with no `error_class` keyword — the default `"executor_error"` is used. The distinct error types (`subprocess_timeout`, `subprocess_spawn_failed`) are encoded only in the message string (`f"local_tool_error: subprocess_timeout: ..."`), not in the structured `ToolResultMeta.error_class` field.

**Evidence:**
- `_execute_local_call:371-376`: `except Exception as exc: … _append_tool_failed(event_store, room_id, call_id, agent_id, f"local_tool_error: {exc}")` — no `error_class` kwarg.
- `_append_tool_failed:406`: `error_class: str = "executor_error"` — the default.
- `subprocess_tools.py:97-99`: `raise LocalToolError(f"subprocess_timeout: {tool_name} exceeded timeout ({timeout_s}s): {exc}")` — class encoded in message, not metadata.
- `subprocess_tools.py:101-103`: `raise LocalToolError(f"subprocess_spawn_failed: {tool_name} could not start: {exc}")` — same.

**Why it matters:** The agent (or any downstream consumer) must parse the message string to distinguish "tests timed out" from "couldn't start pytest." The structured field exists for this purpose but carries no signal. The plan (B3-2 acceptance) explicitly accepted this: *"if `_execute_local_call`'s generic wrapping cannot carry it without an executor edit, encode the class in the `LocalToolError` message — do NOT edit `_execute_local_call`."* So this is by design, not a bug. But the design tradeoff (byte-frozen executor vs structured error metadata) is worth the architect's explicit acknowledgment.

**Suggested investigation:** Architect should confirm this tradeoff is acceptable for the MVP or flag it for a future executor evolution that plumb `error_class` from `LocalToolError` subclasses without editing `_execute_local_call`.

---

### 🟢 A2 — `_SUBPROCESS_TOOL_NAMES` drift guard correctly placed

**File:line:** `tests/tools/test_constitution.py:553-577` (sync-test) + `agents/selection.py:95-103` (definition)

**Observation:** The drift sync-test `test_b35_subprocess_tool_names_drift_guard` asserts `set(build_subprocess_tool_registry(...).keys()) == set(selection._SUBPROCESS_TOOL_NAMES)`. This fails the build if a future B4/B5 tool is added to the registry without updating the exclusion set. The test crosses the `agents→tools` layer boundary but only in test code (runtime t1 invariant preserved). The same-pass coupling assumption (TOOL_CALL and TOOL_RESULT age out together) is correctly documented in the `_external_output_tool_result_call_ids` watch-point comment. No issue.

---

### 🟢 A3 — Residual inscribed honestly; no softening detected

**File:line:** `ADR-034:52-54` (D2 residual) + `:80` (D4 setpgid residual) + `tests/mcp/test_subprocess_trust.py:278-284` (orphan test scope)

**Observation:** The ADR states the `RB-FS/NET` residual plainly: "The subprocess is NOT syscall-isolated: it runs with the operator process's FS-read + outbound-network privilege." The orphan test explicitly scopes itself to the common case: *"Tests the common case… Does NOT assert the adversarial setpgid(0,0) escape, which is the Accepted kill residual."* No softening, no over-claiming of isolation. The one retirement path (P4.3 wraps `run_scoped_command`) is correctly wired. ✅

---

## Lens B — Liveness under the single writer × turn-loop

### 🟡 B1 — `MAX_SUBPROCESS_CALLS_PER_TURN` name says `_PER_TURN`, counter resets per pass

**File:line:** `src/orchestrator/tools/executor.py:50` (constant) + `:114` (counter init) + `:170` (cap check) + `:184` (error_class string)

**Claim:** The constant is named `MAX_SUBPROCESS_CALLS_PER_TURN` and the `error_class` is `"turn_subprocess_cap_exceeded"`, but the counter `subprocess_calls_this_turn` resets to 0 at line 114 on every invocation of `execute_pending_tool_calls` — which `api/app.py` calls once per pass (pass 0 + each re-dispatch pass). The true per-turn fork bound is `MAX_SUBPROCESS_CALLS_PER_TURN × (1+N) passes`. ADR-034 D5 explains this explicitly, and the comment on line 45 correctly says "Per-pass subprocess fork cap." But a future maintainer reading only the constant name and `error_class` string would miscompute the bound.

**Evidence:**
- Line 45-48: comment says "Per-pass subprocess fork cap" — correct.
- Line 50: `MAX_SUBPROCESS_CALLS_PER_TURN: int = 10` — name says per-turn.
- Line 114: `subprocess_calls_this_turn = 0` — resets each `execute_pending_tool_calls` call.
- Line 184: `error_class="turn_subprocess_cap_exceeded"` — says turn, means pass.
- ADR-034 D5: "The `_PER_TURN` name is retained (the historical name; the multiplier `(1+N)` is the inscribed turn-loop liveness surface)."

**Why it matters:** The bound is still finite (10 × 5 passes × max timeout = bounded), so this is not a safety hole. But the name-reality gap is a maintenance risk — someone tuning the cap for a `_PER_TURN` bound would get the wrong number. The architect explicitly accepted this naming in ADR-034 D5 (R0-A Y2 routed); this finding confirms the decision is visible but flags the maintenance risk.

**Suggested investigation:** Consider adding a one-line comment on line 50: `# Name retained as _PER_TURN for historical reasons; true per-turn bound = this × (1+N) passes (ADR-034 D5).` Already present on lines 45-48 but not linked to the constant name.

---

### 🟡 B2 — `_kill_watchdog` skipped when cancellation resumes after shielded scope in `_run_scoped_command_async`

**File:line:** `src/orchestrator/mcp/subprocess_trust.py:183-189` (finally block) + compare with `:416-435` (`subprocess_mcp_stdio` finally)

**Claim:** In `_run_scoped_command_async`, the LAYER-1 `_kill_watchdog(pid)` call is placed AFTER the `with anyio.CancelScope(shield=True):` block. When the coroutine is cancelled (timeout → `asyncio.wait_for` cancels), the shielded scope defers the cancellation, runs `_terminate_subprocess`, then exits — re-raising the `CancelledError` at the `with` boundary. `_kill_watchdog(pid)` on line 189 is never reached in the cancellation path.

**Evidence:**
- Lines 183-189:
  ```python
  finally:
      if process is not None and pid > 0:
          with anyio.CancelScope(shield=True):
              await _terminate_subprocess(process, pid)
          _kill_watchdog(pid)  # ← OUTSIDE shield; skipped on cancellation
  ```
- `_terminate_subprocess` (lines 285-333) does SIGTERM → SIGKILL escalation (the primary kill) — this IS shielded and completes. The watchdog's value-add is catching the kernel-bug/SIGKILL-surviving edge case, which is exactly the scenario where it's skipped.
- Compare with `subprocess_mcp_stdio:416-435` where `_kill_watchdog` runs in an **outer** `finally` (outside the task group + all shields) — that pattern guarantees watchdog execution.

**Why it matters:** The watchdog was added as LAYER-1 defense-in-depth for the exact case where the primary kill (SIGTERM→SIGKILL escalation) fails. In the timeout path — the most likely path for a hung/misbehaving child — the watchdog is structurally skipped. The primary kill mechanism (`_terminate_subprocess` SIGTERM→SIGKILL on the process group) is robust and shielded, so orphan risk is minimal. But the asymmetry between `_run_scoped_command_async` (watchdog skipped on cancel) and `subprocess_mcp_stdio` (watchdog always runs) is worth noting. The setpgid-escape residual (ADR-034 D4) is a separate concern; this is about the watchdog placement, not the kill mechanism.

**Suggested investigation:** Move `_kill_watchdog(pid)` inside the `with anyio.CancelScope(shield=True):` block (line 188, before the block exits) — a one-line reorder. The watchdog is synchronous (no await), so it doesn't need shield protection itself, but placing it inside the shielded scope ensures it executes even when cancellation is pending. The outer `finally` in `subprocess_mcp_stdio` already uses this pattern correctly.

---

### 🟢 B3 — All liveness terms finite; no unbounded inline dependency

**File:line:** `executor.py:50` (cap), `subprocess_tools.py:32-38` (timeouts), `subprocess_trust.py:66` (output cap), `api/app.py:76,87` (turn-loop passes + wall clock)

**Observation:** The worst-case single-writer block is `MAX_SUBPROCESS_CALLS_PER_TURN (10) × max_timeout (120s for run_tests) × MAX_TURN_LOOP_PASSES (4) = 1200s` per pass, bounded overall by `MAX_REDISPATCH_WALL_CLOCK_S (120s)` for passes 1-N. The output cap (64 KiB) is enforced as data is read (`subprocess_trust.py:169-177` — room check before each `receive()`). Non-zero exit produces `TOOL_RESULT` not `TOOL_FAILED` (`subprocess_tools.py:105-107`). `run_sync`'s `asyncio.wait_for` provides the timeout; `run_scoped_command` maps `MCPTimeoutError` → `SubprocessTimeoutError`. All terms are finite and the chain is clear. ✅

---

## Synthesis

No 🔴 findings. The three 🟡 findings are clustered around edge-case resilience in the failure path:

- **A1** (error_class homogenization): the agent gets less structured signal than the schema supports — a byte-frozen-executor tradeoff the plan accepted.
- **B1** (name-reality gap): the constant name misleads future maintainers — a naming tradeoff ADR-034 D5 accepted.
- **B2** (watchdog skip on cancel): the LAYER-1 backstop is structurally skipped in the timeout path — the only case where it would matter.

All three are acknowledged design decisions or subtle placement issues, not missing capability. The core trust boundary (argv-never-shell, scoped env, output-as-untrusted, excerpt exclusion) and the core liveness guarantees (kill-no-orphan, bounded output, per-pass cap) hold under tracing.
