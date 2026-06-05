---
review: R0-A-on-plan
task_id: P4.2-B3
stage: plan
lens: in-family (architect-partner); cross-family R0-B-on-plan runs in parallel (r0b session)
reviewer: architect-partner
baseline: origin/main 4df2c82 (product code unchanged at HEAD 2167ed1; plan/ADR are docs-only commits on top)
artifacts:
  - docs/process/senior-plans/P4.2-B3.md (B3-1..7 + §5)
  - docs/decisions/ADR-034-subprocess-local-tools.md (Proposed) + the ADR-028 D3 amendment
verdict: needs_architect
findings: 2 substantive (Y1 channel-blinding edge, Y2 cap per-pass/per-turn inscription) + 5 §5 design-calls to route; 3 junior watch-point nits
blocking: none
---

# R0-A-on-plan — P4.2-B3 (subprocess local tools)

## 0. Method + independence

Verify-cite of every load-bearing claim in the plan + ADR-034 against the source at this tree (product `src/` is byte-identical between `4df2c82` and HEAD — the two later commits are docs-only). Written **independently** of `R0-B-on-plan.md` (already landed in the shared tree) to preserve dual-lens independence; the architect synthesizes both. I do **not** re-litigate the 5 architect-ratified brief decisions — I verify the plan/ADR implement them faithfully, then probe the six trust/liveness surfaces the dispatch named.

**Bottom line:** the plan is **faithful to all 5 ratified decisions, accurately cited, and implementable**; constitution invariants hold; the honest residual is inscribed faithfully. **Not blocking.** Two real cross-decision *interactions* need an architect call (Y1, Y2), plus the senior's 5 §5 design-calls need routing. → **needs_architect.**

## 1. Faithfulness to the 5 ratified decisions — all faithful

| Ratified | Plan / ADR | Verified |
|---|---|---|
| (1a) ship all 5; run_tests AUTO | ADR D1; plan B3-2/B3-3 | `tools.yaml:34` run_tests rev **9**, `:36/:38/:40/:42` others rev **10** → AUTO at `threshold_auto ≤ 9` ✓ |
| (2A) lighter-inline posture + honest RB-FS/NET residual; P4.3 retires via same iface | ADR D2 + Reversibility; plan §1 | Matches ADR-031 D1a model (see probe iv) ✓ |
| (3) raw TOOL_RESULT + untrusted-framing + extend P4.1 excerpt filter | ADR D3-iv; plan B3-5 | Implemented; one interaction caveat → **Y1** |
| (4) Posture-B LocalToolFn path; empty-executor-diff; cap→`MAX_SUBPROCESS_CALLS_PER_TURN` | ADR D5; plan B3-3/B3-4 | Empty-diff holds (probe iii); naming caveat → **Y2** |
| (5) ADR-034 + amend ADR-028 D3 | ADR-034; plan B3-6 | ADR-028 D3 amendment target real + actionable (`ADR-028:65`) ✓ |

The decisions are faithfully implemented. Y1/Y2 are *interactions surfaced by* the faithful implementation, not departures from it.

## 2. Probe results (the six the dispatch named)

**(i) argv-never-shell — REAL + test-enforced. ✓** B3-1 spawns via `anyio.open_process([...], start_new_session=True)` (list argv, the exact `subprocess_mcp_stdio` pattern, `subprocess_trust.py:210-215`); **no** `shell=True`/shell-string. B3-2 param allowlist rejects any non-allowlisted key → `LocalToolError`→`TOOL_FAILED`; the path entering argv is the **resolved absolute** path from `_check_path` (`local.py:120-135` — `(root/p).resolve()` is always `/`-prefixed and under root, so it can never be flag-shaped; an absolute LLM string is *discarded-then-rejected* by `relative_to`), and git argv place `--` before the path. B3-7 adds AST `t9` forbidding `shell=True`/`os.system`/shell-string in the new module + `run_scoped_command`. Clean.

**(ii) scoped env — no secrets, PATH present. ✓** `build_scoped_env` (`subprocess_trust.py:63-79`) inherits only `_SAFE_ENV_KEYS` (`:42-52`, includes `PATH`), overlays `server_cfg.env`, and overlays `api_key_env` **only if set** (`:75-78`). B3 passes **no** `api_key_env` (ADR D2; plan B3-2) → zero secrets; `git`/`ruff`/`pytest` resolve via PATH. Clean. (Nit N1 below on the literal reuse snippet.)

**(iii) empty-executor-diff — holds. ✓** `_execute_local_call` (`executor.py:338-388`) does **not** branch on posture or tool-name; it runs `impl(params)`→`TOOL_RESULT` for any `LocalToolFn`, so B3 tools ride it **byte-unchanged**. The cap lives in `execute_pending_tool_calls` (`:158-202`) — what B3-4 renames — **not** in `_execute_local_call`. The excerpt filter (B3-5) lives in `agents/selection.py`, not the executor, so it writes nothing there. `t3b` (`test_constitution.py:183-224`) walks **only** the `_execute_local_call` FunctionDef → the B3-4 rename of `execute_pending_tool_calls` cannot trip it; t3b's own docstring blesses "the cap is a mechanism addition in `execute_pending_tool_calls`, NOT a decision-logic change." Clean.

**(iv) honest residual — inscribed faithfully as ADR-031 D1a. ✓** ADR-034 D2 ("**Accept the real surface, not a softened one**"; same `RB-FS/NET` class; `open() ~/.ssh/id_rsa`/`socket()` out; **strictly narrower** — first-party fixed-argv over a trusted workspace vs ADR-031's fetched/untrusted callables; **P4.3/A1 wraps the existing `run_scoped_command`**, retiring this + the ADR-031 residual on **one** path; env-scoping does not reverse) is a verbatim-in-spirit match to ADR-031 D1a (`ADR-031:39-41`, `:122`). Faithful. *(Minor: ADR-031 names "the operator who activates a fetched plugin assumes the residual"; B3 has no per-call activation — the assuming authority is the operator's `sandbox_root` + autonomy-threshold config, with first-party-fixed-argv as the narrowing substitute. Defensible; flagging only for completeness — no action needed.)*

**(v) liveness — bound holds, but the "per-turn" framing is imprecise → Y2.** Bounded output (`MAX_RESULT_BYTES=65_536`, `execution.py:37`), kill-no-orphan (`_terminate_subprocess` + `_kill_watchdog`, `subprocess_trust.py:129/87`), and the per-call cap are all **reused** — the fork count is finite. **But** see Y2: the cap is enforced **per pass**, so the true per-turn bound is `cap × (1+N)`, not `cap`.

**(vi) excerpt filter doesn't blind the acting agent — true for the single-call flagship loop, NOT for multi-result passes → Y1.** Confirmed two-channel split: `snapshot_excerpt`→system block (`dispatch.py:112-116`), `current_event.content`→user message (`dispatch.py:123`); the prior pass's last result-class event becomes `current_event` (`app.py:449-454,460-463`). So a `run_tests` result the agent issued **alone** survives as `current_event`. See Y1 for the multi-result exception.

## 3. Findings needing an architect call

### Y1 🟡 needs_architect — subprocess results can be invisible to the next pass when batched (probe vi)

A subprocess `TOOL_RESULT` is (a) **excluded from `snapshot_excerpt`** (B3-5) **and** (b) has **no `OBSERVATION` proxy** (D3-iv raw-not-interpret). So it reaches the next pass through **exactly one** channel: `current_event` — and `current_event = result_events[-1]`, the **last** result-class event of the prior pass (`app.py:449-454`). When a pass emits **multiple** result-class events and the subprocess result is **not last** (e.g. the agent batches `run_tests` before a `read_file`, or before an `mcp__` call whose `OBSERVATION` lands after), the subprocess bytes appear in **neither** channel → the acting agent cannot see its own test output on the next pass.

This is **asymmetric with MCP**, contra the plan's "parity with the existing `mcp__` treatment, minus the `OBSERVATION`" (plan §1; ADR D3-iv). MCP's raw result is also excerpt-excluded, **but its `OBSERVATION` is rendered in the excerpt** (`OBSERVATION ∈ _EXCERPT_EVENT_TYPES`, not excluded — `selection.py:81-89,122-130`), so MCP's signal survives in the "reason over **all** prior-pass results" channel. Subprocess's "minus the `OBSERVATION`" removes exactly that carrier. `schema.py:200-202` states the excerpt's job is precisely to "reason over ALL prior-pass results, not only the latest" — which is what's undercut for non-last subprocess results.

- **Not blocking:** the dominant flagship loop ("re-investigate on a failed test") issues `run_tests` as the focused/last call → works.
- **Cross-links §5.2** (tool-name-match keying is what implements the exclusion).
- **Architect routes:** (a) accept the MVP edge (single-call dominant) + **document it as a known limitation in ADR-034 D3-iv** so it's inscribed not discovered; or (b) require a mitigation (e.g. the loop preferring a subprocess result as `current_event`, or a thin excerpt-presence for subprocess results). Lean: **(a) accept + inscribe** — but this is your residual-acceptance call, not mine.

### Y2 🟡 needs_architect — the cap is enforced per-*pass*; "per-turn" name + ADR D5 prose overstate it (probe v)

`subprocess_calls_this_turn` (renamed from `posture_b_calls_this_turn`) resets at `executor.py:112`, at the **start of each `execute_pending_tool_calls` call** — and `app.py` calls that **once per pass** (`:416` pass-0, `:473` inside `for _pass in range(MAX_TURN_LOOP_PASSES)`). So the cap bounds forks **per pass**; the true **per-turn** fork bound is `MAX_SUBPROCESS_CALLS_PER_TURN × (1 + N_passes)`.

ADR-034 is **internally inconsistent** on this: **D3** is honest ("now **multiplied by the turn-loop's (1+N) passes**"), but **D5** says the cap "**bounds all subprocess forks per turn**", and the ratified name `MAX_SUBPROCESS_CALLS_PER_TURN` reinforces the D5 (incorrect) reading. Liveness is **not** broken (`cap×(1+N)` is finite); this is an **inscription-accuracy** finding, surfaced because B3 makes subprocess tools **AUTO + first-party** (the amplification is now a live default property, not a latent plugin-only one) and **B3-4 is the moment the semantics are re-inscribed**. The existing `test_posture_b.py` pb4 already asserts the cap **per `execute_pending_tool_calls` call** (per-pass) — so the impl/test semantics are fine; only the ADR prose + the name mislead.

- **Cross-links §5.4** (the rename atomic).
- **Architect routes:** (a) keep the ratified `_PER_TURN` name [decision-4] but **fix ADR D5's sentence to match D3** (state the real `cap×(1+N)` per-turn bound); or (b) rename to `_PER_PASS` to make the enforcement boundary literal. Lean: **(a)** — the name was your call; just reconcile D5↔D3. Not a safety hole.

## 4. Assessment of the senior's §5 design-calls — all need routing; my leans

The senior surfaced 5 cleanly (claims-with-cites). My read on each + whether it needs your call:

1. **argv0 hardcode** (`python -m pytest` / `ruff check`) — **route.** A capability-scope call (Python-MVP vs config-driven runner). Reversible-additive (ADR Reversibility, low). Lean **accept hardcode** (matches the project's own Python loop, `app.py:206` sandbox = `config_dir.parent`); config-driven is cleanly additive later.
2. **tool-name-match, not a `ToolResultMeta.external_output` flag** — **confirm.** This is **forced by a ratified constraint**, not a free choice: the flag would have to be written by `_execute_local_call` (the sole local `TOOL_RESULT` appender, `executor.py:374-388`), breaking the architect-ratified empty-executor-diff (carry-forward #5 / ADR-031 HR#2). The drift-guard sync-test (B3-5) neutralizes the tool-name-list's one weakness. Lean **keep tool-name-match** (the flag *reverses* a ratified decision). **Consider together with Y1** (this keying is the exclusion mechanism).
3. **ADR-031 D2 one-line cross-ref** (vs a fuller amendment) — **route.** Adding `run_scoped_command` to `subprocess_trust.py` extends the "one subprocess protocol" (ADR-031 D2) with a second entrypoint. ADR-031 already anticipates reuse (`:122`, Consequences). Lean **one-liner** (`[Extended P4.2-B3 → ADR-034]`) — additive entrypoint; ADR-034 carries the substance.
4. **cap full rename** (constant+var+error_class) touching 2 plugin test files — **route.** Blast radius verified accurate (`executor.py:48,112,166,170,179,180,183`; `code.py:24,65` comments; `test_posture_b.py:8,9,38,292,302,324,327,343`; `test_p3_7_remote_plugins.py:50,330,341,363`). The **one externally-observable change** is the `error_class` string `turn_posture_b_cap_exceeded`→`turn_subprocess_cap_exceeded` (in `TOOL_FAILED` metadata). Lean **full rename, isolated atomic** (coherent for B4/B5). **Decide alongside Y2** (the name's per-pass/per-turn semantics).
5. **git no-ref-passthrough** (working-tree + path only) — **confirm.** Verified: argv carry no ref param (`["git","blame","--",<abs>]` etc.); refs deferred as an option-injection/scope surface. Lean **accept** (security-conservative MVP). Low-stakes awareness item.

None block. #1/#3/#4 are clean scope/stewardship calls; #2/#5 are "confirm the forced/safe default" (the alternatives reverse a ratified constraint [#2] or widen a security surface [#5]).

## 5. Verified-solid + junior watch-point nits (non-routing)

**Solid (so you know what's load-bearing-checked):** all cited file:line accurate; `t3b`/`t6` hold (`t6` inspects only `local.py` → the new `subprocess_tools.py` is correctly out of its scope, which is *why* B3-7 adds `t9`); ADR-028 D3 amendment target real (`ADR-028:65` lists the 5 tools verbatim, mirrors the `[Amended P4.1 → ADR-033]` pattern at `:63`); `MAX_RESULT_BYTES=64 KiB` reused; t1 respected (B3-5 defines `_SUBPROCESS_TOOL_NAMES` *in* `selection.py`, not imported from `tools/`; only the *test* crosses the layer, and tests are outside t1's `_SRC` scan).

- **N1 (junior):** the B3-2 reuse snippet `MCPServerConfig(env={})` will **fail validation** — `transport="stdio"` (default) requires `command` (`config.py:65-69`). Use the plan's offered alternative (factor a `scoped_env()` core) **or** pass a dummy `command=` (as `code.py:93-97` does). The plan already hedges this ("junior's call") — flagging so it's not a wasted cycle.
- **N2 (junior):** B3-4's enumerated blast radius omits the **comment** at `executor.py:159` ("Posture-B subprocess cap: applied before dispatch"), which describes the cap and should track the rename. The "all references updated" acceptance + grep will catch it; just not in the pinned list.
- **N3 (junior):** `run_sync`'s `asyncio.wait_for` **cancels the coroutine** on timeout (`_async_bridge.py:51-53`) → `run_scoped_command` must kill the child in a **shielded `finally`** (the `subprocess_mcp_stdio` pattern, `subprocess_trust.py:254-279` + the `CancelScope(shield=True)` in `_terminate_subprocess:135`), else a cancelled coro could orphan. The B3-1 acceptance ("timeout → child killed, no orphan; assert PID reaped") covers it — calling it out as the sharp impl edge.

## 6. Verdict + recommended next action

**needs_architect** — plan is faithful, accurate, and implementable; **not blocking**. To route:

- **Y1** (multi-result subprocess blind spot) — accept+inscribe MVP edge / mitigate?
- **Y2** (cap per-pass vs `_PER_TURN` name + D5 prose) — reconcile D5↔D3 / rename `_PER_PASS`? (decide with §5.4)
- **§5.1–§5.5** — α/accept the senior's leans, or redirect.

Once routed, the remaining step is your **Accept of ADR-034** (Proposed → Accepted; state is `awaiting_architect_accept`), then junior dispatch for B3-1…B3-7. The impl-stage `external-r0b-prompt.md` is ready for the mandatory dual-lens.
