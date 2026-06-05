---
task_id: P4.2-B3
stage: impl
reviewer: senior
verdict: clean
date: 2026-06-05
plan: docs/process/senior-plans/P4.2-B3.md
adr: docs/decisions/ADR-034-subprocess-local-tools.md (Accepted)
commits_reviewed:
  - ef12aa7 P4.2-B3-1
  - bde8c7a P4.2-B3-2
  - 9015173 P4.2-B3-3
  - e00b47f P4.2-B3-4
  - b07d316 P4.2-B3-5
  - 5437a73 P4.2-B3-6
  - 607b32d P4.2-B3-7
---

# P4.2-B3 — senior plan-vs-impl (impl-stage)

The junior pushed all seven atomics (B3-1…B3-7) on `origin/claude/P4.2-B3-impl`.
This is the senior lens: **plan vs deliverable** (not deliverable vs spec — that's
R0-A/R0-B). Each atomic verified against its acceptance criteria in
`senior-plans/P4.2-B3.md` + ADR-034 (Accepted). Verdict: **clean**.

## Structural

- **atomic → commit 1:1 (RC-17):** exactly seven commits, each named after its
  atomic, no bundling. ✓
- **Scope:** `git diff --stat origin/main..HEAD` = 16 files; every file maps to a
  plan atomic (no drift). The pre-existing `reviews/P4.2-B3/R0-B-cross-family.md`
  is a shared-tree reviewer artifact, outside the junior impl.
- **Gates green:** `ruff check src tests` clean; `mypy --strict src tests` →
  "no issues found in 238 source files"; full `pytest` exit 0 (no failures);
  constitution suite **t1–t9** + B3-5 drift guard all pass.

## Per-atomic verification

### B3-1 — `run_scoped_command` (`mcp/subprocess_trust.py`)
- Signature matches plan: `run_scoped_command(argv, *, cwd, env, timeout_s=30.0,
  max_bytes=MAX_RESULT_BYTES) -> SubprocessResult` (`subprocess_trust.py:200-207`);
  `SubprocessResult` carries `exit_code/output/truncated` (`:114-121`). ✓
- **argv-never-shell:** spawns via `anyio.open_process(argv, cwd=, env=,
  stderr=STDOUT, start_new_session=True)` — argv is a **list**; no `shell=True`,
  no shell-string (`:154-160`). ✓
- **Bounded read:** stops accumulating at `max_bytes` *as it reads* (`:166-178`),
  does not buffer an unbounded child log. ✓
- **Shielded-finally kill (R0-A N3):** the kill runs in `with
  anyio.CancelScope(shield=True): await _terminate_subprocess(...)` then
  `_kill_watchdog(pid)` in `finally` (`:183-189`); `_terminate_subprocess`
  additionally wraps its own shield (`:291`) — survives `run_sync`'s
  `asyncio.wait_for` cancellation. ✓
- **Reuse, distinct error class:** reuses `_terminate_subprocess` +
  `_kill_watchdog`; timeout → distinct `SubprocessTimeoutError` (`:227-228`);
  spawn-failure unwrapped to `OSError` (`:229-235`). ✓
- **scoped_env factored core, NOT `MCPServerConfig(env={})`:** `scoped_env(extra_env,
  api_key_env)` core (`:74-96`) preserves the exact three-step behaviour;
  `build_scoped_env(server_cfg)` is now a thin wrapper (`:99-106`). The B3-2/A1
  trap (Pydantic `transport="stdio"` requires `command`) is avoided — no
  `MCPServerConfig` is constructed. ✓

### B3-2 — five tool closures (`tools/subprocess_tools.py`)
- **Param allowlist:** `_check_disallowed` rejects any key outside the per-tool
  `frozenset` → `LocalToolError` (`:72-81`); no flag passthrough on any tool. ✓
- **Resolved-abs path into argv:** every path goes through reused `_check_path`,
  the **resolved absolute** path enters argv (never the raw LLM string); git
  commands place `--` before the path (`git_blame:155`, `git_log:181`,
  `git_diff:197`). ✓
- **Pinned argv** matches the plan table for all five (`run_tests` =
  `[sys.executable, "-m", "pytest", "-q", <abs?>]` `:122-125`; `run_lint` =
  `["ruff","check",<abs|root>]` `:138-139`; git trio as pinned). ✓
- **Per-tool timeouts pinned (R0-B B1):** `_SUBPROCESS_TIMEOUTS` = run_tests **120**
  / run_lint **30** / git_* **10** s (`:32-38`), passed as `timeout_s`. ✓
- **Result semantics:** any exit code → `LocalToolOutput` (content embeds
  `exit_code=…`) → `TOOL_RESULT`; non-zero exit is **not** `TOOL_FAILED`
  (`_dispatch:105-107`). ✓
- **Distinct error classes (R0-B B4):** timeout → `subprocess_timeout`; spawn-fail
  → `subprocess_spawn_failed`, both **encoded in the `LocalToolError` message**
  (`:96-103`) — the plan's sanctioned fallback that keeps `_execute_local_call`
  byte-frozen. ✓
- **scoped_env() with no extra_env / no api_key_env** (`_dispatch:91`). ✓
- **Marker:** `_SubprocessToolFn` callable class carries
  `_is_posture_b_subprocess: ClassVar[bool] = True` (`:50-58`), mirroring the
  `_PostureBFn` precedent. ✓
- **git_log clamp:** `max_count` clamped `[1,100]`, default 50, non-int rejected
  (`:169-179`). ✓

### B3-3 — wire into the registry (`api/app.py`)
- Composed at the api/ root **after** the plugin merge (`app.py:236-238`):
  `local_tools = {**local_tools, **build_subprocess_tool_registry(sandbox_root)}`.
  6 lines, import-local. `local.py` does **not** import the subprocess module
  (t6 stays pristine — verified by passing t6). ✓
- **Empty-executor-diff held:** the executor decision path is untouched (B3-3
  diff is app.py only; see B3-4 for the only executor edit = a rename). ✓

### B3-4 — cap rename (isolated)
- `MAX_POSTURE_B_CALLS_PER_TURN` → `MAX_SUBPROCESS_CALLS_PER_TURN`,
  `posture_b_calls_this_turn` → `subprocess_calls_this_turn`,
  `error_class` `turn_posture_b_cap_exceeded` → `turn_subprocess_cap_exceeded`
  (`executor.py:48,112,166,170,179,183`). ✓
- Marker `_is_posture_b_subprocess` **name retained** (plan + ADR-034 D5). ✓
- **Grep-confirmed test-only (R0-B B3):** the commit records the pre-rename
  repo-wide grep (no `config/`/UI consumer); the post-rename grep shows
  `turn_subprocess_cap_exceeded` lives only in `executor.py` + the two plugin
  test files (`test_posture_b.py`, `test_p3_7_remote_plugins.py`). ✓
- One atomic, one commit (rename only; comment text updated to note the per-pass
  generalisation, matching ADR-034 D5). ✓

### B3-5 — extend the `snapshot_excerpt` exclusion
- `_mcp_tool_result_call_ids` → `_external_output_tool_result_call_ids`, widened to
  `tool_name.startswith("mcp__")` **OR** `tool_name in _SUBPROCESS_TOOL_NAMES`
  (`selection.py:106-129`). ✓
- `_SUBPROCESS_TOOL_NAMES` defined **in `selection.py`** (the consumer), NOT
  imported from `tools/` at runtime (t1 holds) (`:95-103`). ✓
- **Drift sync-test (Y1):** `test_b35_subprocess_tool_names_drift_guard` asserts
  `set(build_subprocess_tool_registry(<tmp>).keys()) == _SUBPROCESS_TOOL_NAMES`
  (`test_constitution.py:553-577`) — only the *test* crosses the layer. ✓
- **Two-channel behavioural test** confirms injected bytes are absent from the
  excerpt but reach the acting agent as `current_event`
  (`test_b35_subprocess_result_excluded_from_excerpt`). ✓
- R0-B A2 same-pass-coupling watch-point inscribed as a comment (`:116-119`). ✓

### B3-6 — ADR amendments
- **ADR-028 D3:** subprocess tools struck from the deferred list +
  `[Amended P4.2-B3 → ADR-034, Accepted 2026-06-05]` inline note; mutation surface
  remains deferred; top status block updated. Reads **Accepted**, matching the
  Accepted ADR-034 (the plan's status-coupling instruction). ✓
- **ADR-031 D2:** one-line `[Extended P4.2-B3 → ADR-034, Accepted 2026-06-05]`
  cross-ref naming `run_scoped_command` as the non-MCP plain-exec entrypoint —
  the plan's must-land item. ✓

### B3-7 — constitution t9
- `test_t9_no_shell_in_subprocess_surface`: AST-forbids `shell=True`, `os.system`,
  and shell-string argv across `subprocess_tools.py` + `subprocess_trust.py`
  (run_scoped_command context) (`test_constitution.py:475-545`). ✓
- **t6 still passes** (local.py in-process-pristine) — confirmed in the suite run;
  t9 covers the new module, t6 unbroadened (plan out-of-scope honoured). ✓

## Plan-implied invariants (the senior-only surface)

- **Empty-executor-diff:** `_execute_local_call` is byte-unchanged — the only
  `executor.py` edit is the B3-4 rename of the *cap* path (in
  `execute_pending_tool_calls`, upstream of the decision logic; t3b passes). The
  distinct error classes were encoded in the `LocalToolError` *message* precisely
  to avoid a `ToolResultMeta` write inside the frozen executor. Invariant held. ✓
- **Single-call flagship loop survives the excerpt exclusion:** the
  `current_event` channel (`api/app.py`) is distinct from `snapshot_excerpt`; the
  two-channel test demonstrates the raw bytes still reach the acting agent on the
  dominant single-call shape. The batched-non-last edge is the ADR-034 D3-iv
  **inscribed** known-limitation (not a discovered drift). ✓
- **One subprocess protocol (ADR-031 D2):** B3 adds exactly one new entrypoint to
  `subprocess_trust.py`, reusing scoped-env + kill machinery; no second mechanism.
  ✓

## Findings

**🟢 G1 (cosmetic, non-blocking) — stale test-name reference in a comment.**
`agents/selection.py:93` cites the drift guard as
`t9_drift_sync_subprocess_names`, but the landed test is
`test_b35_subprocess_tool_names_drift_guard` (`tests/tools/test_constitution.py:553`).
A reader grepping the cited name finds nothing. Pure comment text; no runtime or
test effect; the drift guard itself is correct and passing. Noting for the
architect's routing — not a blocker.

## Verdict

**clean.** All seven atomics deliver their acceptance criteria; no scope drift;
atomic→commit 1:1; every ratified/absorbed item (argv-never-shell + allowlist;
`scoped_env()` factored core, no `MCPServerConfig(env={})`; per-tool timeouts
120/30/10; distinct error classes; empty-executor-diff; cap rename grep-confirmed
test-only; excerpt exclusion + drift sync-test; ADR-028 D3 + ADR-031 D2
amendments matching Accepted; t9 + t6) landed as planned. Gates green
(ruff + mypy --strict canonical + full pytest exit 0 + constitution t1–t9). One
🟢 cosmetic comment nit (G1) surfaced for architect routing. I surface; the
architect routes.
