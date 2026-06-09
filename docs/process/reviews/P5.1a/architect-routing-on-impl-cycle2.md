---
task_id: P5.1a
stage: architect-routing-on-impl
cycle: 2
actor: architect
date: "2026-06-09"
routing: alpha
disposition:
  F-deadloop-test: alpha
rework_to: junior (cycle 3)
inputs:
  - docs/process/reviews/P5.1a/plan-vs-impl.md   # senior, cycle-2 clean
  - docs/process/reviews/P5.1a/R0-A.md           # arch-partner, cycle-2 needs_architect (1×🟡 F-deadloop-test)
  - docs/process/reviews/P5.1a/R0-B.md           # r0b cross-family, cycle-2 clean
---

# P5.1a cycle-2 routing — **α (fix the vacuous test), one rework cycle 3**

The cycle-2 all-α rework resolved 4 of 5 findings with empirical proof (B1
defusedxml blocks the padded-prolog billion-laughs; F-runid single run_id;
F-succeeded reflects real success/failure; F-ownerparam uses owner in the
run-anchor author). **plan-vs-impl = clean, R0-B = clean.** R0-A returned the lone
remaining 🟡: the **F-deadloop code fix is correct and R0-A empirically proved it
restores ADR-041 D2 multi-pass** (fixed = 3 LLM calls + a pass-1 re-dispatch;
reverted one-line = 2 calls, dead), **but the shipped regression test is vacuous**
— it passes identically on fixed and reverted code.

## Why α (not β)

The cycle-1 all-α mandate for F-deadloop explicitly required *"add a multi-pass
analyze test."* The code half landed; the test half is ineffective. A regression
test that passes whether or not the bug is present is the exact cycle-1 B1 theme
(*tests giving false assurance*) recurring one layer down — the project's
test-honesty bar says we close it now rather than ship a guard that doesn't guard.
The fix is tiny: R0-A already built the corrected probe.

## Disposition

| # | Sev | Routing | Fix |
|---|---|---|---|
| **F-deadloop-test** | 🟡 | **α** | Rewrite `test_analyze_branch_multi_pass_redispatch` (`tests/pipeline/test_runner.py`) to use a **real AUTO tool** (e.g. `tools={"get_current_time": ToolMeta(reversibility=10)}` + `build_local_tool_registry`, mirroring R0-A's probe) so pass-0 emits a genuine `TOOL_CALL`+`TOOL_RESULT`, and assert the re-dispatch actually ran (router call-count == 3, or a pass-1 utterance appearing after the `tool_result`). The test must **fail on the reverted one-line** (`prev_pass_cursor = len(events)`) and **pass on the fix**. |
| N1 (🟢, fold in) | — | α | While here, add the API-level correlation assertion R0-A flagged: in `tests/api/test_pipelines.py`, assert the returned `run_id` equals the in-room run-anchor `run_id` (end-to-end, not just prefix). Cheap, closes the runner↔store↔API loop. |

N2 (mixed attribution: run-anchor `user:<owner>` vs branch/output `agent:pipeline`)
is cosmetic — **no action**.

No product-code change is required or permitted beyond the test (the runner code is
verified correct); spine stays byte-frozen; no ADR-041 amendment. Senior did not
self-accept (RC-3); architect routed.
