---
task_id: P5.1a
review: plan-vs-impl
reviewer: senior
cycle: 2
verdict: clean
supersedes: "cycle-1 plan-vs-impl (needs_architect, Y1 RSS-XXE + Y2 dual run_id)"
plan: docs/process/senior-plans/P5.1a.md
adr: ADR-041
routing: docs/process/reviews/P5.1a/architect-routing-on-impl.md
impl_branch: origin/claude/P5.1a-impl
impl_head: 267da97
reviewed_commits:
  - 267da97  # P5.1a cycle-2 rework: all-α (B1 + F-runid + F-deadloop + F-succeeded + F-ownerparam)
date: "2026-06-09"
summary: >
  Cycle-2 re-review of the all-α rework (architect-routing-on-impl.md). All five
  routed findings are absorbed faithfully and minimally, and both cycle-1 senior
  🟡 (Y1 RSS-XXE doc/impl mismatch + padded-prolog evasion → B1; Y2 dual run_id →
  F-runid) are resolved. B1: the 8 KiB byte pre-scan is replaced with
  defusedxml(forbid_dtd=True) — position-independent, within ADR-041 D4's own
  named floor (no amendment) — the doc now describes the real mechanism, and a
  comment-padded-prolog evasion test reproduces R0-A's exploit and confirms it is
  blocked. F-runid: the store accepts a caller-supplied run_id and the endpoint
  threads result.run_id, so the pipeline_runs row id == the run-anchor event
  run_id. F-deadloop: prev_pass_cursor = prev_cursor restores ADR-041 D2
  multi-pass (verified prev_cursor is the pre-pass-0 snapshot). F-succeeded:
  succeeded = branches_succeeded > 0. F-ownerparam: build_user_author(owner_user_id)
  anchors the run. No plan-external expansion: spine byte-frozen across the full
  range, no new LLMPurpose/EventType/RoomType, only the routed surfaces touched.
  Verdict clean.
---

# P5.1a — senior plan-vs-impl review (cycle 2)

**This file supersedes the cycle-1 plan-vs-impl review** (verdict
`needs_architect`, findings Y1 RSS-XXE + Y2 dual run_id). Both cycle-1 🟡 are
resolved below; the cycle-2 scope is the all-α rework commit `267da97` routed by
`architect-routing-on-impl.md`.

**Method.** Read-only on `main`; impl read via `git show 267da97` / `git diff
origin/main...origin/claude/P5.1a-impl` (shared worktree — no checkout). Each
routed finding was checked against (a) the routing disposition, (b) the cycle-1
finding it answers, and (c) plan T1–T6 + ADR-041 for faithfulness and
non-expansion. The spine-freeze (ADR-041 D9) was re-verified by a per-file
diffstat over the full range.

## Routing → fix map (architect-routing-on-impl.md, all-α)

| # | Sev | Cycle-1 origin | Fix landed | Verified faithful |
|---|---|---|---|---|
| **B1** | 🔴 | pvi-Y1 + R0A + R0B-F3 | `defusedxml(forbid_dtd=True)` + doc fix + padded-prolog test | ✅ |
| F-runid | 🟡 | pvi-Y2 + R0B-F1 | store optional `run_id`; endpoint threads `result.run_id` | ✅ |
| F-deadloop | 🟡 | R0A-Y1 | `prev_pass_cursor = prev_cursor` + multi-pass test | ✅ |
| F-succeeded | 🟡 | R0A-Y2 | `succeeded = branches_succeeded > 0` + all-fail/partial tests | ✅ |
| F-ownerparam | 🟡 | R0B-F2 | `build_user_author(owner_user_id)` anchors run + author test | ✅ |

## Per-finding verification

### B1 (🔴) — RSS billion-laughs / XXE — resolved (closes cycle-1 Y1)

- **Routing asked:** replace the hand-rolled byte-scan with `defusedxml`
  (`forbid_dtd=True`) per ADR-041 D4's own recommendation; add a comment-padded
  prolog test; make the doc describe the actual mechanism.
- **What landed (`sources/rss.py`):** `_check_no_entity_declarations` /
  `_DOCTYPE_SCAN_BYTES` are **deleted**; `_parse_feed` now calls
  `defusedxml.ElementTree.fromstring(xml_text, forbid_dtd=True)` and maps
  `DTDForbidden | EntitiesForbidden → SourceReadError` (fail-closed, no crash).
  The malformed-XML `ET.ParseError` path is preserved.
- **Why this closes the evasion:** `forbid_dtd=True` rejects the DOCTYPE at the
  parser level, so the position of `<!DOCTYPE` in the prolog is irrelevant — the
  8192-byte scan window the cycle-1 exploit padded past no longer exists. The new
  test `test_rss_parse_comment_padded_prolog_doctype_blocked` builds the exact
  R0-A payload (`<!-- {9000×'x'} --><!DOCTYPE foo [<!ENTITY x 'y'>]>…`) and
  asserts `SourceReadError` — the reproduced exploit is now blocked.
- **Floor / ADR:** `defusedxml` is one of T1's two named acceptable mechanisms
  ("use `defusedxml` or `xml.etree` with entity resolution disabled") and is
  ADR-041 D4's own recommendation → **no ADR amendment needed** (correctly none
  taken). Dependency added cleanly: `defusedxml>=0.7` in `pyproject.toml`,
  resolved to `0.7.1` in `uv.lock`, with a `[[tool.mypy.overrides]]
  ignore_missing_imports` entry (defusedxml ships no stubs).
- **Doc (`sources-vs-connectors.md`):** the phantom `_SafeXMLParser` /
  `EntityDeclHandler` claim is removed; the note now reads "uses `defusedxml`
  (`forbid_dtd=True`) … position-independent: DOCTYPE … rejected at the parser
  level regardless of comment or PI padding." Doc now matches code.

### F-runid (🟡) — single run_id across runner↔store — resolved (closes cycle-1 Y2)

- `create_pipeline_run` gains an optional `run_id: str | None = None` (mints
  `prun_{uuid4}` only when `None` — backward-compatible). The `/run` endpoint
  passes `run_id=result.run_id`, and the stale "Use the run_id from the store
  record" comment is removed. Consequence: `pipeline_runs.run_id` == the
  `run_id=…` embedded in the run-anchor OBSERVATION — the dual-id ambiguity from
  cycle-1 Y2 is gone; the index row and the run's events join on a single id.
  Covered by `test_create_pipeline_run_with_caller_supplied_run_id` (store) +
  `test_run_pipeline_run_id_is_stable` / `…_anchor_event_embeds_run_id` (runner).

### F-deadloop (🟡) — restores ADR-041 D2 multi-pass

- The one-line change `prev_pass_cursor = prev_cursor` (was re-snapshot
  `len(get_room_events(room_id))` taken *after* pass-0 execution). **Verified:**
  `prev_cursor` is captured at `runner.py` immediately *before* the pass-0
  `process_tool_calls`, so the first re-dispatch iteration's window
  `[prev_cursor:]` now contains the pass-0 `TOOL_CALL` + result events — the
  loop is live and bounded by `_PIPELINE_MAX_PASSES` / `_PIPELINE_MAX_WALL_CLOCK_S`.
  Before the fix the window was always empty → the loop broke on iteration 1
  (the "dead loop"). This **restores D2 as written** (no ADR/plan change, exactly
  as the routing noted). `test_analyze_branch_multi_pass_redispatch` drives a
  pass-0 tool call and asserts pass-1 executes.

### F-succeeded (🟡) — status reflects reality

- `PipelineRunResult.succeeded = branches_succeeded > 0` (was hard-coded `True`).
  All-branches-fail → `False` → `pipeline_runs.status="failed"`; partial/all
  success → `True`. Both paths tested
  (`…_all_branches_fail_succeeded_false`, `…_partial_success_succeeded_true`).
  This retires the cycle-1 green-note that flagged the hard-coded `True`.

### F-ownerparam (🟡) — owner_user_id is no longer a dead param

- The run-anchor OBSERVATION author changes from `build_author(PIPELINE_AGENT_ID)`
  to `build_user_author(owner_user_id)` (import added; symbol confirmed at
  `core/event.py:460`), so the triggering user is attributed in the event stream
  independent of the `pipeline_runs` index. Faithful to the routing intent
  ("use it inside the runner / anchor the run"). Note: the per-branch analyze
  **utterances** correctly remain `build_author(PIPELINE_AGENT_ID)` — the agent
  speaks, the run is owned by the user; the split is coherent.
  `test_run_pipeline_anchor_event_author_is_owner` covers it.

## Non-expansion / no-regression (re-verified)

- **Spine byte-frozen (ADR-041 D9).** Zero changes across the full range to
  `agents/tool_dispatch.py` (gate), `tools/executor.py` (`_execute_local_call`),
  `core/event.py` (`approval_source` Literal + EventType), `core/room.py`
  (RoomType), `tools/net_trust.py`, `tools/local.py`. Confirmed by per-file
  diffstat (empty).
- **No new authorization / content surface.** No new `LLMPurpose`, `EventType`,
  or `RoomType` member anywhere in the range (grep clean). The pipeline still
  uses `AGENT_RESPONSE`, `OBSERVATION`/`SUMMARY_SNAPSHOT`, and `FREE_CHAT` only.
  The D5 no-headless-actuation mechanism (`countdown_auto_fire=None` at both call
  sites) and the conservative `ThresholdConfig(8,5,0)` are untouched by cycle-2.
- **app.py cycle-2 footprint** is two comment-line deletions + the `run_id=`
  kwarg — no logic drift on the endpoint, owner-private auth path untouched.
- **No ADR-041 amendment** (correct — every fix lands inside an existing
  decision: D4 named defusedxml; D2 is restored not changed; D7/D8 endpoint and
  store shapes unchanged).

## Residual green notes (no action)

- **G1 (carried).** The `/run` endpoint still writes the `pipeline_runs` row
  *after* `run_pipeline` returns with a terminal status, so no `running` row is
  observable and a mid-run crash leaves no index row. Acceptable for the
  synchronous P5.1a path; the create-running-then-update shape the store already
  exposes (now also accepting a caller `run_id`) is the right pattern if P5.1b
  makes runs background/async. Unchanged by cycle-2.

## Verdict

**clean.** All five routed findings (B1🔴 + four 🟡) are absorbed faithfully and
minimally; both cycle-1 senior 🟡 are resolved; the implementation remains
faithful to plan T1–T6 and ADR-041 (spine frozen, no new authorization surface,
D2 multi-pass restored as written, no plan-external expansion). The cycle-2
commit asserts gates green (ruff / mypy strict 297 files / pytest 2352); R0-A and
R0-B will re-run and independently gate-verify in detached worktrees per the
W-005 Route-B flow. No remaining senior concern.
