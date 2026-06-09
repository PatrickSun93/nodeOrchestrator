---
task_id: P5.1a
stage: R0-A (impl)
reviewer: architect-partner
verdict: clean
cycle: 3
supersedes: "cycle-2 R0-A (needs_architect; 1×🟡 F-deadloop-test vacuous)"
findings_count: 0
findings: []
resolved_from_cycle2:
  - "F-deadloop-test (🟡 vacuous → RESOLVED): test_analyze_branch_multi_pass_redispatch rewritten to drive a real AUTO tool (get_current_time, reversibility=10 ≥ threshold_auto=8) so pass-0 emits a genuine TOOL_CALL+TOOL_RESULT; asserts router.call.call_count==3. EMPIRICAL fail-on-revert: reverting runner.py:170 `prev_pass_cursor=prev_cursor` → `len(...get_room_events(room_id))` makes the test FAIL (got 2 calls, expected 3); restore → PASS. The guard now guards."
  - "N1 (🟢 folded in): test_run_pipeline_run_id_matches_anchor_event asserts the FULL returned run_id ∈ the room run-anchor event content (end-to-end, not just prefix) — closes the runner↔store↔API loop. Passes."
lenses: ["A: pipeline test-efficacy (fail-on-revert proof)", "B: spine no-regression"]
reviewed_branch: "origin/claude/P5.1a-impl @ 958d316 (cycle-3 test-only rework, +62 / -13, 2 files, tests/ only)"
reviewed:
  - "tests/pipeline/test_runner.py (rewritten F-deadloop multi-pass redispatch test)"
  - "tests/api/test_pipelines.py (N1: API run_id ↔ anchor-event correlation)"
against:
  - "docs/process/reviews/P5.1a/architect-routing-on-impl-cycle2.md (the α fix-test + N1 mandate)"
  - "docs/process/reviews/P5.1a/R0-A.md (my cycle-2 finding — superseded by this file)"
gates_independently_run: "isolated detached worktree @ 958d316, uv sync --all-extras (defusedxml 0.7.1)"
gates_result: "ruff: All checks passed ✅ | mypy: Success, no issues in 297 source files ✅ | pytest: 2353 passed / 0 failed / 0 error / 0 skipped (JUnit-XML authoritative; 2352→2353 = the +1 N1 test) ✅ — the lone thread-warning is the pre-existing by-design net_trust DNS-timeout test; net_trust is byte-frozen"
empirical_log: "Fail-on-revert proven in the disposable worktree. FIXED → both target tests PASS. REVERTED (prev_pass_cursor = len(get_room_events(room_id))) → deadloop test FAILS: `AssertionError: Expected 3 router calls (analyze + re-dispatch + reduce), got 2; re-dispatch loop may be dead` (assert 2 == 3). RESTORED → PASS. The cycle-2 vacuity (empty tools={} registry → autonomy_refusal → no TOOL_CALL event → loop breaks at guard 1 before the cursor is read) is gone: the real get_current_time AUTO tool emits TOOL_CALL+TOOL_RESULT, so pass-1 genuinely re-dispatches under the fix and dies under the bug."
date: "2026-06-09"
---

# R0-A (impl) — P5.1a cycle-3 re-review (α fix-test + N1)

> **This file supersedes the cycle-2 R0-A** (verdict `needs_architect`; lone 🟡
> F-deadloop-test vacuous). The cycle-3 scope is the **test-only** rework commit
> `958d316` routed by `architect-routing-on-impl-cycle2.md` (α: harden the
> regression test so it actually fails on the reverted one-line; fold in N1).
>
> **Verdict `clean` — 0 findings.** My single cycle-2 🟡 is resolved with an
> empirical **fail-on-revert** proof; N1 is added and effective. Zero product
> code changed this cycle; the constitutional spine is byte-frozen; gates green
> (2353 passed). With this, **all three lenses are now clean** (senior
> plan-vs-impl `clean` cy-2 · R0-B cross-family `clean` cy-2 · R0-A `clean` cy-3).

## Method

Reviewed `origin/claude/P5.1a-impl @ 958d316` **without checking out** the shared
worktree (stayed on `main`; read via `git diff 267da97..958d316`). Per the
dispatch I did **not** trust the rewritten test at face value — I reproduced the
**fail-on-revert** experiment in an **isolated detached worktree**
(`git worktree add --detach … 958d316`, `uv sync --all-extras`): ran the test on
the fix, reverted `runner.py:170` to the cycle-1-bug form, re-ran, restored.

## The two routed items

### F-deadloop-test (was 🟡) — **RESOLVED**, fail-on-revert proven

The cycle-2 test was vacuous because pass-0 emitted a `read_file` call against an
**empty `tools={}` registry** → `autonomy_refusal` → **no `TOOL_CALL` event** →
the re-dispatch loop broke at its first guard (`runner.py:178 if not
new_tool_calls: break`) before the cursor was ever read, so it passed on the
fixed **and** the reverted code.

The rewrite replaces the deps with a **real AUTO tool** —
`tools={"get_current_time": ToolMeta(reversibility=10)}` +
`build_local_tool_registry(tmp_path)` (mirroring my cycle-2 probe). `reversibility=10
≥ threshold_auto=8` → `AUTO_EXECUTE` tier → `process_tool_calls` emits a genuine
`TOOL_CALL`, `execute_pending_tool_calls` appends the `TOOL_RESULT`; the
assertion is now `router.call.call_count == 3` (analyze + re-dispatch + reduce).

Empirical proof in the disposable worktree:

```
FIXED (prev_pass_cursor = prev_cursor)                 → PASS (3 router calls)
REVERTED (prev_pass_cursor = len(get_room_events()))   → FAIL  AssertionError: got 2, expected 3
RESTORED                                               → PASS
```

A test that fails on the reverted one-line and passes on the fix is a real guard.
The cycle-1 theme (tests giving false assurance) is closed at this layer.

### N1 (was 🟢) — added and effective

`test_run_pipeline_run_id_matches_anchor_event` drives a full create→run through
the real API stack and asserts the **HTTP-returned `run_id`** appears in the
**room run-anchor event content** (`events[0]`). It checks the full
`prun_<uuid4hex>` id (globally unique), not the `prun_` prefix — so it is an
end-to-end correlation, not the cycle-2 prefix-only check. It exercises two code
paths that *did* diverge in cycle-1 Y2 (runner-minted vs store-minted run_id), so
it genuinely guards the runner↔store↔API loop. Passes on the fix.

## Lens B — spine no-regression: **CLEAN** ✅

Cycle-3 changes **zero `src/` lines** (`267da97..958d316` = `tests/` only), so the
spine state R0-A + R0-B cleared at cycle-2 carries forward unchanged. Re-verified
over the **full** range `origin/main...958d316`:

- `tool_dispatch.py` (gate), `executor.py` (`_execute_local_call`), `net_trust.py`,
  `local.py`, `event.py`, `room.py`, `purposes.py`, `scoring.py` → **0 diff-lines each**.
- **No new `LLMPurpose`** (`purposes.py` unchanged); pipeline LLM calls remain
  `AGENT_RESPONSE` only.
- `_write_and_turn` **byte-untouched** — its only mention in the app.py range is a
  comment in the new pipeline endpoint ("Runs synchronously on writer_executor
  (mirrors _write_and_turn)"), not a modification.
- No ADR-041 amendment (none required — test-only).

## Cross-review map

| Lens | cycle-2 | cycle-3 |
|---|---|---|
| senior plan-vs-impl | `clean` (267da97) | n/a — product code byte-identical to cy-2 |
| R0-B cross-family | `clean` 0🔴0🟡7🟢 (267da97) | n/a — product code byte-identical to cy-2 |
| R0-A (me) | `needs_architect` 1🟡 | **`clean` 0 findings** (this file) |

Cycle-3 touches only tests; the product surface R0-B and senior cleared in cycle-2
is unchanged, so `requires_cross_family_review` remains satisfied over a frozen
product surface. (If you want a fresh R0-B on the test-only delta, that's your
dispatch call — my lean: not needed, zero product/runtime delta.)

## What the architect does next

1. **Nothing to route** — this review carries no 🔴/🟡. The lone open item from
   cycle-2 is empirically resolved.
2. **ADR-041 Accept (Proposed → Accepted) + merge** stay yours (RC-3; my role does
   not Accept ADRs or merge PRs). All three review lenses are now clean and gates
   are green (2353 passed) — surfacing readiness only, not deciding it.

Awaiting your call.
