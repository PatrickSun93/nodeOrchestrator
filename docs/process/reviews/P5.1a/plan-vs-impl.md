---
task_id: P5.1a
review: plan-vs-impl
reviewer: senior
cycle: 3
verdict: clean
supersedes: "cycle-2 plan-vs-impl (clean, all-α rework @267da97)"
plan: docs/process/senior-plans/P5.1a.md
adr: ADR-041
routing: docs/process/reviews/P5.1a/architect-routing-on-impl-cycle2.md
impl_branch: origin/claude/P5.1a-impl
impl_head: 958d316
reviewed_commits:
  - 958d316  # P5.1a cycle-3 rework: fix vacuous F-deadloop test + N1 run_id correlation
date: "2026-06-09"
summary: >
  Cycle-3 re-review of the test-only rework routed by
  architect-routing-on-impl-cycle2.md (α: fix the vacuous F-deadloop regression
  test + fold in the N1 API-level run_id correlation assertion). The cycle-3 diff
  (267da97→958d316) touches tests/ ONLY — zero product-code change, exactly as
  the routing required and permitted. Both routed items land faithfully and
  minimally. F-deadloop-test: test_analyze_branch_multi_pass_redispatch is
  rewritten to inject a real AUTO tool (get_current_time, reversibility=10 ≥
  threshold_auto=8) via explicit PipelineDeps + build_local_tool_registry,
  mirroring R0-A's probe, so pass-0 emits a genuine TOOL_CALL+TOOL_RESULT and the
  test asserts the re-dispatch ran (router.call.call_count == 3 — one of the two
  sanctioned assertions). The cycle-2 vacuity defect is closed: empirically the
  test now FAILS on the reverted one-line (prev_pass_cursor = len(...)) with
  "got 2, expected 3" and PASSES on the fix — proven by reverting product line
  170 in a throwaway worktree. N1: a new self-contained API test
  (test_run_pipeline_run_id_matches_anchor_event) asserts the API-returned run_id
  appears in the room run-anchor event content — substring containment on the
  full id, satisfying "end-to-end, not just prefix". N2 left untouched (cosmetic,
  routed no-action). No plan-external expansion; spine byte-frozen; no ADR-041
  amendment. Verdict clean.
---

# P5.1a — senior plan-vs-impl review (cycle 3)

**This file supersedes the cycle-2 plan-vs-impl review** (verdict `clean`, all-α
rework `@267da97`). The cycle-2 product code was verified clean there and is
unchanged this cycle; the cycle-3 scope is the **test-only** rework commit
`958d316` routed by `architect-routing-on-impl-cycle2.md` (α: fix the one
remaining R0-A 🟡 — the vacuous F-deadloop regression test — plus fold in the N1
API run_id correlation assertion).

**Method.** Read-only on `main` (shared worktree — no checkout). The reviewed diff
was read via `git diff 267da97 958d316`. To discharge the routing's load-bearing
empirical requirement (the regression test *must fail on the reverted one-line and
pass on the fix*), the impl tip `958d316` was checked out into a **throwaway
detached worktree** (`/tmp/p51a-verify`, removed after) so the product code under
test was present without disturbing the shared `main` checkout. There the two
reworked tests were run on the fix (PASS), the F-deadloop product fix (runner.py
line 170) was reverted to its buggy form and the runner test re-run (FAIL),
the fix restored, and the full affected modules + lint/type gates run.

## Scope guard — tests-only, zero product change

`git diff --name-only 267da97 958d316`:

| File | Δ |
|---|---|
| `tests/pipeline/test_runner.py` | +37 −13 (rewrite F-deadloop test) |
| `tests/api/test_pipelines.py` | +25 (new N1 test) |

No file outside `tests/` is touched. This matches the routing's explicit bound:
*"No product-code change is required or permitted beyond the test (the runner code
is verified correct); spine stays byte-frozen; no ADR-041 amendment."* ✅

## Routing → fix map (architect-routing-on-impl-cycle2.md, all-α)

| # | Sev | Fix routed | Fix landed | Verified faithful |
|---|---|---|---|---|
| **F-deadloop-test** | 🟡 | Rewrite to a real AUTO tool so pass-0 emits genuine TOOL_CALL+TOOL_RESULT; assert re-dispatch ran (call-count==3 OR pass-1 utterance after tool_result); test must fail on revert, pass on fix | Explicit `PipelineDeps(tools={"get_current_time": ToolMeta(reversibility=10)}, local_tools=build_local_tool_registry(tmp_path), …)`; asserts `router.call.call_count == 3` | ✅ (empirically fails-on-revert) |
| N1 | 🟢→α | API test: returned `run_id` == in-room run-anchor `run_id`, end-to-end not just prefix | New `test_run_pipeline_run_id_matches_anchor_event`: `assert run_id in anchor.content` (full id, not a truncation) | ✅ |
| N2 | 🟢 | no action (cosmetic mixed attribution) | untouched | ✅ |

## Per-item verification

### F-deadloop-test (🟡) — vacuous regression test → genuine guard

The cycle-2 test returned a fabricated `read_file` ToolCall but injected no real
tool registry, so pass-0 wrote no `TOOL_CALL`/`TOOL_RESULT` events — the
re-dispatch loop's `prev_pass_window` was empty on both fixed and reverted code,
making the test pass identically either way (the recurrence of the cycle-1 B1
"tests give false assurance" theme that the project's test-honesty bar requires us
to close).

The rework adopts R0-A's probe exactly:

- Replaces the `_make_deps` helper with an explicit `PipelineDeps` that wires a
  **real AUTO tool** — `tools={"get_current_time": ToolMeta(reversibility=10)}`
  (10 ≥ `threshold_auto`=8 → AUTO_EXECUTE tier) plus
  `local_tools=build_local_tool_registry(tmp_path)`. So pass-0's tool call is
  genuinely processed: `process_tool_calls` emits a `TOOL_CALL` event and
  `execute_pending_tool_calls` appends a `TOOL_RESULT`, giving the re-dispatch
  loop real events to detect.
- Pass-0 returns a `get_current_time` ToolCall; calls 2 (re-dispatch) and 3
  (reduce) return plain results. The assertion is `router.call.call_count == 3`
  — the first of the two sanctioned forms.

**Empirical proof (the load-bearing check):**

- On the fix (`prev_pass_cursor = prev_cursor`, line 170): **PASS** — 3 router
  calls (analyze + re-dispatch + reduce).
- Reverting line 170 to the buggy `prev_pass_cursor = len(deps.writer_store.get_room_events(room_id))`:
  **FAIL** — `AssertionError: Expected 3 router calls …, got 2; re-dispatch loop
  may be dead` (`assert 2 == 3`).

The test now discriminates fixed vs dead-loop code. The cycle-2 vacuity defect is
closed. ✅

### N1 (🟢, folded in) — API↔anchor run_id correlation

`test_run_pipeline_run_id_matches_anchor_event` creates a pipeline as USER_A,
POSTs `/run`, reads the API response `run_id`/`room_id`, fetches the room events
from `writer_store`, and asserts `run_id in events[0].content` (the run anchor is
always event 0). Substring containment on the **complete** run_id — not a prefix
or truncated compare — closes the runner↔store↔API loop end-to-end, as routed.
Complements the existing runner-level `test_run_pipeline_anchor_event_embeds_run_id`
by tying the *API-returned* id to the embedded one. ✅

### N2 — correctly left untouched

Routed no-action (cosmetic run-anchor `user:<owner>` vs branch/output
`agent:pipeline` attribution). No change appears. ✅

## Non-expansion / spine-freeze

The diff adds only test imports (`RoomId`, `ToolMeta`, `build_local_tool_registry`)
and test bodies. No product module, no `LLMPurpose`/`EventType`/`RoomType`, no
ADR-041 surface is touched. The cycle-2 spine-freeze stands unchanged. No ADR
amendment. ✅

## Gate evidence (throwaway worktree @958d316)

- `pytest tests/pipeline/test_runner.py tests/api/test_pipelines.py` → **34 passed**.
- Fail-on-revert: runner test FAILS (`got 2`) with the F-deadloop one-line reverted.
- `ruff check` (both test files) → **All checks passed**.
- `mypy` (both test files) → **Success: no issues found in 2 source files**.

## Verdict

**clean.** The test-only rework absorbs the cycle-2 routing faithfully and
minimally: the F-deadloop regression test is now a genuine guard (empirically
fails on the reverted bug), N1 closes the run_id correlation end-to-end, N2 is
correctly untouched, and there is zero product-code change. Senior did not
self-accept (RC-3); the architect routes.
