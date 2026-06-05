---
review: R0-A
task_id: P4.2-B3
stage: impl
lens: in-family (architect-partner); cross-family impl-stage R0-B runs in parallel (r0b session)
reviewer: architect-partner
baseline: origin/claude/P4.2-B3-impl @ 607b32d (7 atomics B3-1..7 over the merged plan 50d7c05)
artifacts:
  - src/orchestrator/mcp/subprocess_trust.py (scoped_env + run_scoped_command)
  - src/orchestrator/tools/subprocess_tools.py (5 closures + registry)
  - src/orchestrator/tools/executor.py (cap rename)
  - src/orchestrator/agents/selection.py (excerpt exclusion) + dispatch.py/schema.py (framing)
  - src/orchestrator/api/app.py (wiring)
  - docs/decisions/ADR-028 D3 + ADR-031 D2 amendments
  - tests/{tools/test_subprocess_tools,tools/test_constitution,mcp/test_subprocess_trust,plugins/test_posture_b,plugins/test_p3_7_remote_plugins}.py
verdict: needs_architect
findings: 2 minor (Y1 missing timeout acceptance-test; Y2 distinct-error-class realized message-level-not-metadata + inscription gap) + 3 trivial nits
blocking: none
gates: ruff PASS · mypy --strict PASS (238 files) · pytest PASS (1793) · t1–t9 + drift + excerpt PASS (12)
---

# R0-A (impl-stage) — P4.2-B3 (subprocess local tools)

## 0. Method + independence

Mandatory impl-stage R0-A (ADR-008 Amendment 1 — runs regardless of plan-vs-impl; `requires_cross_family_review: true`). Verify-cite of every load-bearing claim in the 7 atomics against ADR-034 (Accepted) + the constitution, with the gates actually run. Written **independently** of the parallel cross-family R0-B (r0b session); the architect synthesizes both. I do **not** re-litigate the Accepted ADR — I verify the impl enforces it and that the plan-stage routed findings (Y1/Y2 on-plan; A1/B1/B2/B4/B5 from R0-B-on-plan) are faithfully absorbed.

**Bottom line:** the implementation is **faithful, accurate, and gates-green**. `_execute_local_call` is byte-identical; argv-never-shell is real + t9-enforced; scoped-env is factored cleanly (A1); per-tool timeouts (B1), shielded kill-no-orphan (N3), the setpgid residual (B2), the excerpt-exclusion + drift-guard, and the ADR-028/031 amendments are all present and correct. **Nothing blocks.** Two **minor** findings need an architect routing call (Y1 a missing acceptance-test; Y2 the "distinct error classes" granularity + a one-line inscription gap), plus 3 trivial nits. → **needs_architect.**

## 1. Probe spine — all eight verified

**(1) argv-never-shell — REAL + test-enforced. ✓** No `shell=True` / shell-string / `os.system` anywhere; `_run_scoped_command_async` spawns via `anyio.open_process(argv, …, start_new_session=True)` with a list argv (`subprocess_trust.py:107-116`). Param allowlist blocks flag passthrough — `_check_disallowed` rejects any key outside the per-tool allowlist (`subprocess_tools.py:88-98`); allowlists are `{"path"}` (run_tests/run_lint/git_blame/git_diff) and `{"path","max_count"}` (git_log), so `-p`/`--pdb`/`-c`/`ref`/`cached` cannot enter (tested `test_param_allowlist_rejects_disallowed`). The path entering argv is the **resolved absolute** path from `_check_path` (`subprocess_tools.py:147,159,…`) — never the raw LLM string (tested path-escape + dash-path-not-flag). git places `--` before the path (`["git","blame","--",abs]` etc., `:170,194,209`). **t9** AST-forbids shell=True/os.system/shell-string in both subprocess files (`test_constitution.py:475-545`, PASS) and **t6** (local.py in-process) still passes — both in the 12-passed constitution run.

**(2) scoped env — factored core, no secrets, PATH present. ✓** A1 resolved correctly: the new `scoped_env(extra_env, api_key_env)` core (`subprocess_trust.py:71-93`) holds the 3-step behaviour (safe-keys → overlay → conditional api_key); `build_scoped_env` is now a thin delegating wrapper (`:96-104`) — **not** the `MCPServerConfig(env={})` trap the plan flagged. B3 tools call `scoped_env()` with no extra_env / no api_key_env → zero secrets (`subprocess_tools.py:113`). Tested: `test_b3_env_scoped_no_secrets` (PATH present; no key outside `_SAFE_ENV_KEYS`; seeded secret absent), `test_build_scoped_env_delegates_to_scoped_env` (wrapper == core), and the **existing** MCP `build_scoped_env` tests remain green (mcp suite PASS).

**(3) result semantics — correct split. ✓** Non-zero exit → `LocalToolOutput(content=f"exit_code={N}\n…")` at any exit code → `TOOL_RESULT` (`subprocess_tools.py:117-126`; tested `test_run_tests_nonzero_exit_is_tool_result`, `test_run_scoped_command_nonzero_exit_no_raise`). Timeout / spawn-failure raise → `TOOL_FAILED` (`_dispatch` re-wraps to `LocalToolError`, `:114-122`). Bounded output `MAX_RESULT_BYTES` (64 KiB, reused; tested `test_run_scoped_command_truncation`). *Distinct-error-class nuance → Y2.* *(Observation: when output exceeds the cap the child is killed rather than drained, so a truncated run's `exit_code` reflects the kill signal, not the program — but it is flagged via `output_truncated_at`, so the agent knows; inherent to bounded-output-by-kill, not a defect.)*

**(4) liveness — bound holds. ✓** Per-tool timeouts pinned (B1): `_SUBPROCESS_TIMEOUTS = {run_tests:120, run_lint:30, git_*:10}` (`subprocess_tools.py:42-48`). Kill-no-orphan in a **shielded `finally`** (N3): `_run_scoped_command_async`'s finally wraps `_terminate_subprocess` in `anyio.CancelScope(shield=True)` + `_kill_watchdog` (`subprocess_trust.py:147-153`), so the `run_sync`/`wait_for` cancellation on timeout still kills (tested `test_run_scoped_command_timeout_kills_no_orphan`, PID-liveness assertion). Per-pass cap renamed `MAX_SUBPROCESS_CALLS_PER_TURN`, enforced in `execute_pending_tool_calls` (counter resets per invocation = per pass, `executor.py:114,183-188`) → true per-turn bound `cap×(1+N)` (D5-inscribed; tested pb4). The **setpgid residual** (B2) is inscribed in ADR-034 D4, and the timeout test docstring explicitly scopes itself to the common case, **not** the adversarial `setpgid(0,0)` escape (`test_subprocess_trust.py:264-272`) — faithful.

**(5) empty-executor-diff — holds, byte-exact. ✓** `_execute_local_call` is **byte-identical** between 50d7c05 and HEAD (AST-extracted, 1530==1530 chars). The 26-line `executor.py` diff is **entirely** the `MAX_POSTURE_B_CALLS_PER_TURN → MAX_SUBPROCESS_CALLS_PER_TURN` rename inside `execute_pending_tool_calls` (constant + local var + error_class string + comments) — none touches the local-dispatch function. B3 rides the Posture-B path via the `_is_posture_b_subprocess` ClassVar on `_SubprocessToolFn` (`subprocess_tools.py:54-72`), mirroring `_PostureBFn`. **t3b** (walks only `_execute_local_call`) PASS; `test_all_tools_have_posture_b_marker` PASS.

**(6) snapshot_excerpt exclusion extended. ✓** `_mcp_tool_result_call_ids → _external_output_tool_result_call_ids`, now matching `mcp__`-prefix **OR** `tool_name ∈ _SUBPROCESS_TOOL_NAMES` (`selection.py:99-127`). The drift sync-test asserts `build_subprocess_tool_registry(...).keys() == _SUBPROCESS_TOOL_NAMES` (`test_constitution.py:553-577`, PASS) — A2/§5.2 guard live. Two-channel split verified behaviorally: the canary in a `run_tests` TOOL_RESULT is **absent** from the excerpt while a trusted in-process local TOOL_RESULT **is** rendered (`test_b35_subprocess_result_excluded_from_excerpt`, PASS). The **Y1 known-limitation** (batched-non-last subprocess result invisible to the next pass) is inscribed in ADR-034 D3-iv; the **A2 watch-point** (TOOL_CALL aging out) is inscribed as a comment (`selection.py:115-119`). dispatch.py/schema.py are doc-only framing updates.

**(7) ADR amendments inscribed, match Accepted. ✓** ADR-028 D3 `[Amended P4.2-B3 → ADR-034, Accepted 2026-06-05]` — the five no-longer-deferred, mutation remains deferred (Status header + inline D3). ADR-031 D2 `[Extended P4.2-B3 → ADR-034, Accepted 2026-06-05]` — `run_scoped_command` as the non-MCP plain-exec entrypoint reusing `scoped_env`/`_terminate_subprocess`/`_kill_watchdog`. Both provenance strings match ADR-034's Accepted date.

**(8) gates green. ✓** `ruff check src tests` → all passed. `mypy src tests` (strict, canonical `files=["src","tests"]`) → no issues, 238 files. `pytest` full suite → **1793 passed**, 0 failed. t1–t9 + both b35 tests → 12 passed.

## 2. Findings needing an architect call (both minor; neither blocks)

### Y1 🟡 needs_architect — a named B3-2 acceptance test (timeout → TOOL_FAILED) is missing

`tests/tools/test_subprocess_tools.py:8` lists *"timeout → subprocess_timeout in TOOL_FAILED message"* as a B3-2 acceptance test, but **no such test exists in the file**. The `_dispatch` branch `except SubprocessTimeoutError → raise LocalToolError("subprocess_timeout: …")` (`subprocess_tools.py:114-117`) is **uncovered**. Timeout is exercised only at the lower `run_scoped_command` level (`test_run_scoped_command_timeout_kills_no_orphan` asserts `SubprocessTimeoutError` + no-orphan), and the **symmetric** spawn-failure re-wrap **is** covered (`test_spawn_failure_raises_local_tool_error`). So the gap is the thin tool-level re-wrap only — low severity, but it is a **stated acceptance criterion with no test**, against the project's tests-mandatory bar.

- **Architect routes:** (a) require a ~5-line test this cycle (monkeypatch `run_scoped_command` to raise `SubprocessTimeoutError`, assert `_dispatch` raises `LocalToolError` matching `subprocess_timeout`); or (b) accept the lower-level coverage as sufficient and **drop the stale docstring line**. Lean **(a)** — it closes the one uncovered failure branch and matches the spawn-failure twin; trivial for the junior.

### Y2 🟡 needs_architect — "distinct error classes" is realized message-level, not error_class-metadata; the forcing constraint isn't inscribed

The dispatch probes *"timeout/spawn-failure → TOOL_FAILED with DISTINCT error classes."* The impl encodes the class as a **message prefix** (`subprocess_timeout:` / `subprocess_spawn_failed:`) inside the `LocalToolError` (`subprocess_tools.py:115,120`). But `_execute_local_call:375` catches it as `f"local_tool_error: {exc}"` with **no** `error_class` arg → both surface with the shared **default `error_class="executor_error"`** metadata (`executor.py:404`). So the two are distinct in the TOOL_FAILED **content**, identical in the **metadata** field.

This is **forced by empty-executor-diff**: `_execute_local_call` is byte-frozen (carry-forward #5 / ADR-031 HR#2) and ignores any structured class, so distinct error_class *metadata* is **impossible without editing the executor** — the same tension that made §5.2 reject the `external_output` flag. The agent (an LLM) **can** still distinguish via the message, and the primary B4 distinction ("tests failed" = TOOL_RESULT vs "couldn't start" = TOOL_FAILED) is cleanly at the event-type level. So this is **defensible and arguably the only option under the constraint** — I flag it because (a) the probe explicitly asked for "distinct classes," and (b) ADR-034 D5 does **not** inscribe that the distinction is message-level-only-by-HR#2 — a small "inscribe-don't-discover" gap (cf. the P4.1 Y1 / on-plan Y1 inscriptions).

- **Architect routes:** (a) accept message-level distinction + add a one-line ADR-034 D5 note ("the timeout/spawn-failure classes are encoded in the TOOL_FAILED *message*; `error_class` metadata stays the shared default because `_execute_local_call` is byte-frozen — HR#2"); or (b) — only if metadata-level distinction is genuinely wanted — that reopens the empty-executor-diff invariant (**not** recommended). Lean **(a) accept + inscribe** — this is your residual/inscription call, not mine.

## 3. Trivial nits (non-routing; junior may fold in if Y1/Y2 reopen the files)

- **N1:** ADR-034 D3-iv:70 cites `agents/selection.py::_mcp_tool_result_call_ids` — the symbol **B3-5 itself renamed** to `_external_output_tool_result_call_ids`. Defensible as point-in-time prose ("what existed before B3 widened it"), but a post-impl reader chasing the cite won't find it.
- **N2:** t9's shell-string-as-first-positional-arg check runs only over `subprocess_tools.py`, not `subprocess_trust.py` (the shell=True / os.system checks **do** cover both). No live gap — `subprocess_trust.open_process` passes a Name (`argv`), nothing to catch — but the defense-in-depth check is asymmetric.
- **N3:** `run_lint` omits the `--` separator before its path (`["ruff","check",abs]`) where the git trio uses `--`. Safe (the abs path can't be flag-shaped), but inconsistent with the git tools' belt-and-suspenders.

## 4. Verdict + recommended next action

**needs_architect** — impl is faithful, accurate, and **gates-green (1793 pytest / mypy-strict-clean / ruff-clean / t1–t9)**; **not blocking**. To route:

- **Y1** (missing timeout acceptance-test) — require the ~5-line test this cycle, or accept lower-level coverage + drop the stale docstring line?
- **Y2** (distinct classes message-level + D5 inscription gap) — accept + add the one-line D5 note, or (not recommended) reopen empty-executor-diff?
- **N1–N3** — fold in only if Y1/Y2 reopen the files; otherwise leave.

The parallel cross-family impl-stage R0-B (r0b) re-probes the same trust + liveness spine; synthesize both before routing. Once routed (and Y1/Y2 absorbed if α), the remaining step is your cycle-close dispatch for P4.2-B3 → then B4 (network).
