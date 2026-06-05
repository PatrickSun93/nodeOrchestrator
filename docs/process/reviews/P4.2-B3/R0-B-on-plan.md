---
task_id: P4.2-B3
round: R0-B-on-plan
verdict: needs_architect
findings_count:
  red: 0
  yellow: 4
  green: 3
---

# R0-B on-plan review — P4.2-B3 (subprocess local tools)

**Lens preamble.** This is a plan-stage cross-family review. Code does not yet exist; the review probes the DESIGN (senior plan + ADR-034 + ADR-028 D3 amendment) for structural failure modes Claude-family reviewers under-weight: trust-boundary leaks through indirection, liveness terms that compound silently, and honest-residual claims that soften between ADR and plan. The two lenses are (a) subprocess trust boundary and (b) liveness under the single writer × the turn-loop's N passes, per `external-r0b-prompt.md`.

Each finding cites file:line evidence from the plan, ADR, or existing code the plan builds on. No routing — the architect routes.

---

## Lens (a) — Subprocess trust boundary

### A1. 🟡 `build_scoped_env` reuse has an `MCPServerConfig` validation trap

- **File:line:** plan B3-2:61 (`"Construct a minimal MCPServerConfig(env={})"`); `mcp/config.py:65-79` (model validator); `mcp/subprocess_trust.py:63-79` (fn body)
- **Claim:** The plan offers two approaches for scoped-env reuse: (1) construct `MCPServerConfig(env={})` and pass to `build_scoped_env`, or (2) factor out a `scoped_env()` core. The plan calls this "junior's call."
- **Finding:** Approach (1) fails Pydantic validation. `MCPServerConfig` defaults to `transport="stdio"`, and the `_validate_transport_fields` validator (config.py:67-69) raises `ValueError("stdio transport requires 'command'")` when `command is None`. The junior cannot construct a valid `MCPServerConfig` without either a dummy `command` (semantically misleading — B3 never uses it) or `transport="streamable_http"` with a fake `url` (equally misleading). Approach (2) — factoring out a `scoped_env()` core — is the only clean path. The plan's framing of this as an open "junior's call" obscures a concrete implementation trap.
- **Suggested investigation:** Pin approach (2) in the plan. The factored `scoped_env()` must preserve the existing three-step behaviour (safe-keys-from-os-environ → overlay-cfg-env → conditional-api-key-env), and both `build_scoped_env` (MCP path) and the B3 closure must call it. Verify the existing MCP env tests still pass with the refactor. Add a B3-specific test: subprocess env contains `PATH` (so `git`/`ruff`/`pytest` resolve), and does NOT contain any key from `os.environ` that isn't in `_SAFE_ENV_KEYS`.

### A2. 🟢 Subprocess TOOL_RESULT exclusion from `snapshot_excerpt` — drift sync-test correctly guards tool-name list

- **File:line:** plan B3-5:90-96; `agents/selection.py:92-104` (`_mcp_tool_result_call_ids`); ADR-034 D3-iv:70-71
- **Finding:** The plan correctly keys excerpt exclusion on `TOOL_CALL.tool_name` (matching the existing `mcp__` prefix pattern), drift-guarded by a constitution sync-test (`set(build_subprocess_tool_registry(...).keys()) == selection._SUBPROCESS_TOOL_NAMES`). This is the right design — it needs no executor change (preserves empty-executor-diff), and the sync-test neutralises the tool-name-list's only weakness (B4/B5 additions without filter update → build fails). The two-channel verification (excerpt-excluded but still in `current_event`) is correctly traced at `api/app.py:454` + `agents/dispatch.py:112-123`. No finding against the design.
- **Minor observation:** The exclusion logic matches on `TOOL_CALL` events in the snapshot to build the call_id exclusion set. If the snapshot window is small enough that a TOOL_CALL ages out while its TOOL_RESULT remains (theoretical — in practice both are produced in the same executor pass and enter the snapshot together), the exclusion would miss. The B3-5 behavioural test (two-channel split) covers the happy path; this edge is not worth a dedicated test but is worth a comment in `_external_output_tool_result_call_ids`.

### A3. 🟢 Argv-injection surface — well-defended at design level

- **File:line:** plan B3-2:48-65 (per-tool argv templates); ADR-034 D3-i:61-62; `mcp/subprocess_trust.py:210-215` (`anyio.open_process([...])`, `start_new_session=True`)
- **Finding:** Every path to a shell is closed at design level. The argv is always a list; `shell=True` is constitution-forbidden (t9); paths are resolved to absolute form via `_check_path` before entering argv (no flag-shaped params); git commands place `--` before the path (defence-in-depth). The `sys.executable` for `run_tests` is the orchestrator's own Python — trusted. `ruff check` is a fixed command. No param allowlist permits flag passthrough. The existing `anyio.open_process` call in `subprocess_trust.py:210` already uses a list argv — the B3 `run_scoped_command` entrypoint inherits this shape. The design is air-tight on this surface.
- **Minor observation:** The plan uses `sys.executable` for `run_tests`'s argv0. In a venv/container context this is correct (the same Python that runs the orchestrator). If the sandbox root contains a different Python project (non-pytest, different Python version), the spawn will fail-closed (`TOOL_FAILED`). The plan §5.1 surfaces this as a conscious MVP scope choice — confirmed.

---

## Lens (b) — Liveness under the single writer × the turn-loop's N passes

### B1. 🟡 Subprocess timeout values are unspecified — the absolute single-writer bound has an unbound term

- **File:line:** plan B3-1:39-40 (`run_scoped_command` signature with `timeout_s: float`); B3-2:48-65 (per-tool param tables — no timeout column); ADR-034 D2:48 (`"Bounded timeout + kill-no-orphan"`)
- **Claim:** The worst-case single-writer block is `≤ MAX_SUBPROCESS_CALLS_PER_TURN × subprocess_timeout × (1+N) passes` (plan §1:19, ADR-034 D5/D2). Every term is claimed finite.
- **Finding:** The `subprocess_timeout` term is a variable, not a constant — `run_scoped_command` takes `timeout_s` as a caller-provided parameter. Neither the plan nor the ADR pins a value for any of the five tools. `run_tests` (pytest) can reasonably need 60–120s; git commands need 5–10s; `run_lint` (ruff) needs 10–30s. Without specified values, the claim "every term finite" is true at the type level (the parameter IS a float) but the INSTANTIATED bound is unknown until implementation. If `run_tests` timeout defaults to 300s, the worst-case block is `10 × 300 × 5 = 15,000s` (~4 hours) — still finite, but operationally indistinguishable from a hang for other rooms.
- **Suggested investigation:** Pin per-tool timeout defaults in the plan (or in a `_SUBPROCESS_TIMEOUTS` dict in `subprocess_tools.py`). At minimum, state the default value for `run_scoped_command`'s `timeout_s` parameter and the per-tool overrides. The values should balance usefulness (pytest needs time to run) against the single-writer stall: `run_tests` ≤ 120s, `run_lint` ≤ 30s, git tools ≤ 10s.

### B2. 🟡 Process-group kill does not cover `setpgid` escape — the "no orphan" claim needs the honest-residual treatment

- **File:line:** plan B3-1:40-41 (`"a spawned child that forks a grandchild is group-killed (no-orphan under the watchdog)"`); `mcp/subprocess_trust.py:118-126` (`_pgid_kill` via `os.killpg`); `mcp/subprocess_trust.py:87-110` (`_kill_watchdog` — checks top-level PID only)
- **Claim:** The kill machinery (`start_new_session=True` → `pgid==pid` → `os.killpg(pgid, SIGTERM/SIGKILL)` + LAYER-1 `_kill_watchdog(pid)`) produces "no orphan."
- **Finding:** A child that forks a grandchild which calls `setpgid(0, 0)` (creating a new process group) escapes both `os.killpg` (targets the parent's pgid) and `_kill_watchdog` (checks only the top-level PID). The plan's B3-1 acceptance test ("a spawned child that forks a grandchild is group-killed") passes only if the test grandchild does NOT escape the process group — which is the common case (pytest workers, git subcommands all stay in the parent's pgid). But the claim "no orphan" is stated without this caveat. The ADR's honest-residual discipline (D2: "Accept the real surface, not a softened one") should extend to this: the kill machinery covers the common case; a determined escape via `setpgid` is an Accepted residual of the process-group approach.
- **Suggested investigation:** Add a sentence to ADR-034 D4 or the plan B3-1 acceptance noting the `setpgid` caveat. The B3-1 orphan test should document that it covers the common case (grandchild in same pgid), not the adversarial escape. This is consistent with the honest-residual pattern — the residual is smaller than the FS/network one but real.

### B3. 🟢 The per-turn cap rename has a blast-radius edge: `error_class` string is a quasi-public API

- **File:line:** plan B3-4:78-86; `tools/executor.py:48,179-180`; `tests/plugins/test_posture_b.py:8,9,38,292,302,324,327,343`
- **Finding:** The rename `MAX_POSTURE_B_CALLS_PER_TURN` → `MAX_SUBPROCESS_CALLS_PER_TURN` correctly changes the constant, local var, and `error_class` string (`"turn_posture_b_cap_exceeded"` → `"turn_subprocess_cap_exceeded"`). The plan correctly identifies the two plugin test files that assert on this string. However, the `error_class` string appears in `TOOL_FAILED` event metadata and could be consumed by dashboards, log alerting, or the future web UI. No grep for external consumers of the string is mentioned in the plan. The blast radius is likely test-only (the string was introduced in P3.7 and is unlikely to have external consumers yet), but the plan doesn't verify.
- **Suggested investigation:** Grep for `"turn_posture_b_cap_exceeded"` across the full repo (including config/, docs/, scripts/) before the rename. If the only hits are in `executor.py` + the two test files, the rename is safe. If there are dashboard/config references, surface them.

### B4. 🟡 Non-zero exit → TOOL_RESULT semantics are correctly specified, but `run_scoped_command`'s exception surface needs precision

- **File:line:** plan B3-2:62-63 (`"normal completion at any exit code → LocalToolOutput"`); plan B3-1:38 (`"a timeout raises (MCPTimeoutError via run_sync, or a local SubprocessTimeout) — caller turns it into TOOL_FAILED"`); `tools/executor.py:367-372` (`_execute_local_call` — `impl(params)` exception → `TOOL_FAILED`)
- **Claim:** A failing test suite (non-zero exit) produces `TOOL_RESULT`, not `TOOL_FAILED`. Only timeout/spawn-failure/path-validation/disallowed-param → `TOOL_FAILED`.
- **Finding:** The semantics are correctly specified, but the B3-2 closure must carefully implement the split: `run_scoped_command` returns a `SubprocessResult(exit_code=N, output=..., truncated=...)` on normal completion (including non-zero exit); the closure formats this into `LocalToolOutput` (which `_execute_local_call` wraps as `TOOL_RESULT`). If `run_scoped_command` RAISES on timeout (the plan says it does), the exception propagates through the closure → `_execute_local_call:369` catches it → `TOOL_FAILED`. This is correct. The risk is in `run_scoped_command`'s implementation: a spawn failure (e.g., `ruff` not on PATH) must raise, not return a non-zero exit. The plan's acceptance tests cover this (spawn-failure → `TOOL_FAILED`), but the B3-2 closure's exception-handling boundary is not explicitly tested — the closure currently has no try/except in the plan's pseudocode. If `run_scoped_command` raises an unexpected exception type, it still becomes `TOOL_FAILED` (safe), but the `error_class` will be the generic `"local_tool_error"` rather than a specific `"subprocess_spawn_failed"`.
- **Suggested investigation:** Add an acceptance criterion to B3-2: the closure must catch expected `run_scoped_command` error types (timeout, spawn-failure) and re-raise as `LocalToolError` with distinct error classes, so the agent can distinguish "tests failed" (TOOL_RESULT with non-zero exit) from "couldn't start pytest" (TOOL_FAILED).

### B5. 🟢 64 KiB output cap — generous for git, tight for test failures

- **File:line:** plan B3-1:33 (`max_bytes` parameter); `mcp/execution.py:37` (`MAX_RESULT_BYTES = 65_536`)
- **Finding:** The plan reuses `MAX_RESULT_BYTES` (64 KiB) for subprocess output truncation. This is generous for `git_blame`/`git_log`/`git_diff` output and adequate for `run_lint` (ruff output is typically compact). But `run_tests` (pytest) failure output — a full test run with multiple failures, each with a stack trace — can easily exceed 64 KiB. Truncation at 64 KiB may drop the most actionable part of the output (the last failure). The agent will see `output_truncated_at=65536` and can request a narrower test run, so this is a graceful degradation, not a blindness. The plan's bounded-output posture is correct; the cap value is a tunable, not a design flaw.
- **Minor observation:** The 64 KiB value was chosen for MCP tool results (JSON-RPC responses) and `read_file` (code files). Test output has a different size distribution. Consider a larger cap for `run_tests` specifically (256 KiB?), or add a note that the value is tunable per ADR-034 Reversibility.

---

## Cross-lens synthesis

No findings rise to 🔴 (blocking). The design's trust boundary is thorough — argv-never-shell is air-tight, env-scoping correctly identifies the `api_key_env=None` path, and the output-untrusted two-channel split (excerpt-excluded / `current_event`-included) is correctly traced through the existing code. The honest residual is inscribed without softening.

The 🟡 findings cluster around **unspecified numeric parameters** (B1 — timeout values) and **claims that need the honest-residual treatment applied to their edge cases** (A1 — the scoped-env validation trap is a concrete implementation issue, not a design disagreement; B2 — the process-group escape caveat; B4 — exception-surface precision). None of these block the design from proceeding to implementation; each becomes a sharper risk if left unspecified when the junior starts coding.

**Pattern:** Three of the four 🟡 findings (A1, B1, B4) are instances of the plan deferring a concrete value/constraint to the junior with "junior's call" framing, where the constraint-interaction is more specific than the framing suggests. The senior's §5 surfaces the hardcoded-runner call; the same explicitness would help on the scoped-env path and the timeout values.

---

## Checksums

- **Lens (a) argv-injection:** PASS — no path to shell; list-argv, t9-enforced, path-resolve before argv, git `--` defence-in-depth.
- **Lens (a) env-scoping:** NEEDS ATTENTION (A1) — `build_scoped_env` reuse has a concrete validation trap; the plan's "junior's call" framing obscures it.
- **Lens (a) output-as-untrusted:** PASS — two-channel split correctly traced; drift sync-test guards tool-name list; raw-bytes-preserved.
- **Lens (a) residual honesty:** PASS — ADR-034 D2 inscribes `RB-FS/NET` honestly (FS-read + outbound-network, names `~/.ssh/id_rsa` and `socket()` explicitly, one retirement path via P4.3).
- **Lens (b) kill-no-orphan:** NEEDS ATTENTION (B2) — process-group kill works for common case; `setpgid` escape is an unstated residual.
- **Lens (b) per-turn cap:** PASS — rename is correct; counting in `execute_pending_tool_calls` preserves empty-executor-diff; blast radius identified.
- **Lens (b) bounded output:** PASS — truncate-as-you-read approach prevents OOM; 64 KiB cap is tunable.
- **Lens (b) compounding term:** NEEDS ATTENTION (B1) — the timeout value (a multiplier in the absolute bound) is unspecified.
