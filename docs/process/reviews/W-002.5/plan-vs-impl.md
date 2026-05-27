---
task_id: W-002.5
round: plan-vs-impl
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 5
---

# Review: W-002.5 — plan-vs-impl

**Reviewer:** senior planner (Claude Opus 4.7, 1M context)
**Date:** 2026-05-27
**Artifacts reviewed:** 2 impl commits on `claude/W-002.5-impl`: `c3f1fa3` (W-002.5-1), `5dceef5` (W-002.5-2). 6 files touched, 296 insertions / 24 deletions. Also reviewed the predecessor state-advance commit `7c7391f` (the first end-to-end proof of W-002-2b's no-ADR routing on a merged plan).
**Plan:** `docs/process/senior-plans/W-002.5.md` (no `adr` key in frontmatter — path β; merged via PR #11).
**State context:** `.workflow/W-002.5.yaml` shows `state: awaiting_senior_plan_vs_impl, cycle: 1`. Cycle stayed at 1 (W-002-2's record_override fix in effect; no override invoked anywhere in this task's lifecycle). This is the **first task whose state-file cycle counter behaves correctly end-to-end** since the RC-11 fixes landed.

---

## 1. Coverage of plan acceptance criteria

Every plan-pinned acceptance bullet was checked against the diff. Both W-002.5-* tasks satisfy their criteria.

| Task | Plan-mandated acceptance | Implemented as | Verdict |
|---|---|---|---|
| W-002.5-1 | `_read_adr_status` signature unchanged; `isinstance(adr_val, list)` discriminator; `_normalize_adr_refs` helper extracted if >10 LoC; empty-list raises with `path` populated; per-element type check; per-element glob; aggregation (any none→none; any proposed→proposed; all accepted→accepted); Superseded → "proposed" (W-002-1 preserved); list length cap = none; multi-glob raise message includes offending ADR-id; README updated with `str \| list[str]` form + aggregation paragraph + empty-list rejection + cross-links; ≥8 new tests + 1 integration test + W-002 single-ADR regression preserved | `cli.py`: signature unchanged at `_read_adr_status(task_id, repo_root) -> Literal[...]`; `_normalize_adr_refs(adr_val, plan_path) -> list[str]` helper extracted (~25 lines including docstring + per-element validation); discriminator at line 114 `if isinstance(adr_val, list)`; aggregation order matches plan (`"none" in statuses → "none"`; `"proposed" in statuses → "proposed"`; else `"accepted"` at lines 128-132); multi-glob raise message `f"Multiple ADR files match {ref!r}: {[str(m) for m in matches]}"` names the offending ADR-id (refinement from plan §5 #3 applied); empty-string element also rejects whitespace-only strings via `.strip()` (defensive improvement over plan baseline); `senior-plans/README.md` row updated to `str \| list[str]`, "not yet supported" paragraph replaced with aggregation + empty-list rejection + cross-links to W-002.5 plan + ADR-008 Decision 1; `test_cli.py` 8 new aggregation tests covering matrix (len=1/2/3 + 0-raise + non-string + duplicate-aggregates-twice); `test_integration.py` 1 new §1 e2e test (`test_e2e_multi_adr_plan_advances_when_all_accepted` with both-Proposed→stays + both-Accepted→advances, source≠sink); 2 obsolete list-raise tests removed (multi_adr_list_raises + multi_adr_single_element_list_raises) | ✓ Done |
| W-002.5-2 | 2-row tracking table; 5-surface scan with RC-1 pre-edit grep per surface (specifically grep `senior-plans/README.md` for stale "list raises" / "not yet supported"); deterministic state advance `awaiting_junior_impl → awaiting_senior_plan_vs_impl` (no override entry); gates clean | `5dceef5` commit body carries 2-row tracking table; 5-surface scan enumerates each surface with concrete RC-1 grep result per surface; `senior-plans/README.md` grep returns zero stale matches (verified); state file advanced to `awaiting_senior_plan_vs_impl` with fresh `last_transition_at`; no `override_history` entry; 478 tests pass / ruff / mypy strict clean across 75 source files | ✓ Done |

## 2. Architect-settled decisions — verification

All 4 brief decisions honored:

- **Decision 1 (all-or-nothing aggregation, not granular)** — `statuses` list aggregated in code: `if "none" in statuses: return "none"` then `if "proposed" in statuses: return "proposed"` then `return "accepted"`. No new return value; no new state. Matches the architect-settled order exactly.
- **Decision 2 (`adr` field shape — `str | list[str]` union)** — discriminator `isinstance(adr_val, list)` (line 114) and `isinstance(adr_val, str)` (line 133) cover both cases; `None` falls through to the W-002 fallback path. Non-list-non-string raises `WorkflowError` with `path` populated.
- **Decision 3 (P1.4 plan frontmatter manual edit post-W-002.5)** — out of W-002.5 impl scope per plan; architect-partner does the P1.4 edit after this lands (no impl artifact for it in this branch — correct scoping).
- **Decision 4 (no ADR drafted)** — ADR-008 untouched; no new ADRs in this branch. `git diff main..HEAD -- docs/decisions/` returns no changes. ✓

## 3. Senior plan §5 push-backs — outcomes

All 4 push-backs aligned with brief leans + honored:

- #1 (no list length cap): no length cap in impl; only empty-list rejected.
- #2 (Superseded → "proposed"): preserved via `_parse_adr_status`'s existing logic (lowered.contains check for "accepted" / "proposed" — "Superseded" matches neither, falls through to "none" → aggregates correctly per Decision 1).
- #3 (per-ADR missing → "none"; multi-glob raise includes offending ADR-id): impl includes the ADR-id in both list-path and string-path multi-glob raises (`f"Multiple ADR files match {ref!r}: {[str(m) for m in matches]}"`). Refinement applied.
- #4 (senior observation — W-002-2b end-to-end proof on this plan's publish): **EMPIRICALLY VALIDATED via `7c7391f`**. State advanced `awaiting_senior_plan → awaiting_junior_impl` directly, zero overrides, cycle stayed at 1. See observation #1 below.

## 4. Forcing functions applied

- **Constitutional tests**: all 20+ tests (post-P1.3 + W-002 set) remain green. No new constitutional test introduced (correctly — no new module, no new layering, no new LLM surface).
- **6-category test-coverage standard**:
  - §1 cross-module: `test_e2e_multi_adr_plan_advances_when_all_accepted` (source `SYNTH-002.5` ≠ sink ADR filenames). ✓
  - §2 concurrency: N/A correctly stated.
  - §3 cleanup: minor — `Path.glob()` same pattern as W-002-1; no new subprocess. ✓
  - §4 exception payloads: `WorkflowError` with `path` populated for empty-list, non-string element, empty-string element, multi-glob. All tested. ✓
  - §5 boundary multi-position: list lengths 0 (raise), 1 (degenerate single-ADR), 2 (true multi-ADR), 3 (multi-position) all covered. ✓
  - §6 schema invariants: N/A correctly stated (no new Pydantic model). ✓
- **5-surface scan**: W-002.5-2 commit body per-surface with RC-1 pre-edit grep result. ✓ (See observation #4 below on RC-1 judgment.)
- **Tracking table**: 2-row composite in W-002.5-2.

## 5. Senior observations (🟢 — not blocking; for awareness)

| # | Severity | Location | What | Recommended action |
|---|---|---|---|---|
| 1 | 🟢 (major positive) | `7c7391f` — the state-advance commit between plan-merge and impl-1 | **W-002-2b end-to-end proof landed cleanly.** This is the first commit where the no-ADR routing fired on a merged plan: `plan_has_adr=False → next_state returned AWAITING_JUNIOR_IMPL directly`. Zero architect overrides. Cycle stayed at 1 (W-002-2's record_override fix in effect; no rework, no override path triggered). **The plan §5 push-back #4 prediction was validated empirically.** The RC-11 cluster of state-machine bugs is now structurally closed AND operationally validated end-to-end. | Notable milestone — worth referencing in the eventual W-002 / W-002.5 retrospective. The "fix the bug in the cycle it was caught" discipline (W-002-2b set the precedent; W-002.5 absorbed multi-ADR) has paid for itself: P1.4 ADR Accepts can now proceed without override, which is exactly the goal that justified W-002.5's existence. |
| 2 | 🟢 | `cli.py:66-91` `_normalize_adr_refs` helper | Plan acceptance said "keep inline if <10 LoC; extract to `_normalize_adr_refs` if exceeds." Junior extracted (helper is 25 lines including docstring + 3-case validation). The threshold judgment was correct: empty-list raise + per-element type check + empty-string check + accumulator + return is well past 10 LoC inline. The helper signature is also defensible: `(list[object], Path) -> list[str]` types the unsafe input and produces the safe output. | None — plan-faithful judgment call. |
| 3 | 🟢 | `cli.py:113` `decisions_dir` hoisted before discriminator | Junior moved `decisions_dir = repo_root / "docs" / "decisions"` to before the `isinstance` branches, used in both list and str paths. Plan didn't specify; this is a DRY refactor reducing duplication. | None — minor improvement. |
| 4 | 🟢 | `5dceef5` W-002.5-2 commit body RC-1 grep interpretation | Junior correctly distinguished historical artifact text from live convention text. The W-002 plan still contains "multi-ADR not yet supported (W-003 scope)" — that's the W-002 plan's HISTORICAL audit record of what W-002 implemented at land time. W-002.5 supersedes that decision but does NOT retroactively edit the W-002 plan (matches "ADRs as audit snapshots" semantic from Y1→β). Current README + impl code is clean of stale phrases; historical plans retain their own context. | None — correct discipline. |
| 5 | 🟢 | `_normalize_adr_refs` empty-string check uses `.strip()` (line 85) | Plan acceptance said "empty-string element raises (same shape as existing single-ADR validation)". Junior strengthened the check: `if not elem.strip()` rejects whitespace-only strings too. Strictly defensive; aligns with the project's schema-level-enforcement preference. The normalized `elem.strip()` is also what gets appended to `refs`, so downstream globs receive trimmed values. | None — defensive improvement. |

## Cross-checks

- [x] Implementation matches the plan (no silent scope change) — all 6 touched files map to plan tasks.
- [x] All 5 doc surfaces touched per Q3 — explicit per-surface report in W-002.5-2 commit body with RC-1 pre-edit grep per surface.
- [x] No LLM imports in `src/orchestrator/workflow/` — constitutional test green.
- [x] ADR-008 body untouched (Y1→β preserved) — `git diff main..HEAD -- docs/decisions/` shows no changes.
- [x] CI gates pass: `ruff check` clean / `ruff format --check` clean / `mypy --strict src tests` clean / `pytest` 478 tests green (+6 net over W-002 close baseline of 472).
- [x] W-002-2b end-to-end proof: `7c7391f` state advance fired cleanly via no-ADR routing (cycle=1; no override).
- [x] W-002-1 single-ADR behavior preserved bitwise — `cli.py:139-146` str-path matches W-002-1 verbatim modulo the hoisted `decisions_dir`.
- [x] W-002.5 itself is correctly path-β (no `adr` key in `senior-plans/W-002.5.md` frontmatter; first task to validate W-002-2b on main).

## Verdict summary

W-002.5 impl is **clean**. Every plan acceptance bullet maps to a verifiable element of the diff; all 4 brief Architect-settled decisions honored exactly; all 4 senior plan §5 push-backs aligned with brief leans and applied (including the refinement on multi-glob raise message); no new constitutional tests needed (correctly); the 5-surface scan + RC-1 grep judgment correctly distinguishes historical context from live convention.

The five 🟢 observations are positive notes (major: W-002-2b end-to-end validated; minor: helper extraction judgment, hoisted decisions_dir, RC-1 historical-vs-live discipline, defensive empty-string check). None blocking.

**The cycle that justified W-002.5's existence is now closed:** P1.4 has 2 ADRs; W-002-1 only handled single-ADR; W-002.5 extended to `str | list[str]` with all-or-nothing aggregation; the multi-ADR future predicted in W-002 plan §5 push-back #4 + W-002 R0-A "Forward implications" is now implemented and tested. **P1.4 ADR Accepts can now auto-trigger without override** once architect-partner adds the `adr: [ADR-010, ADR-011]` frontmatter to the P1.4 plan (architect-settled decision 3, a separate one-line edit).

State machine auto-trigger expectation: with this review's frontmatter `verdict: clean`, the next `workflow advance` should fire `awaiting_senior_plan_vs_impl → awaiting_R0_A` per ADR-008 Decision 1. This should work cleanly (W-002 closure observation pattern matches; no timezone-fallback needed for the post-clean-verdict transition).

Recommended next steps:

1. Architect-partner R0-A dispatch decision (RC-9 default skip per W-002 precedent; W-002.5 is mechanical workflow refinement).
2. Merge W-002.5 to main.
3. Architect-partner adds `adr: [ADR-010, ADR-011]` frontmatter to `docs/process/senior-plans/P1.4.md` (one-line edit; architect-settled decision 3 in W-002.5 brief).
4. Architect Accepts ADR-010 + ADR-011 — P1.4 state advances auto-cleanly with zero overrides (the goal that justified W-002.5).
