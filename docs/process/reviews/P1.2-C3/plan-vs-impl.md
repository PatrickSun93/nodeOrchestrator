# P1.2-C3 plan-vs-impl review

| Field | Value |
|---|---|
| Task ID | P1.2-C3 |
| Junior commit | `57b0b33` on `claude/p1.2-c3-impl` |
| Senior plan | [`docs/process/senior-plans/P1.2-C3.md`](../../senior-plans/P1.2-C3.md) |
| Architect brief | [`docs/process/architect-briefs/P1.2-C3.md`](../../architect-briefs/P1.2-C3.md) |
| Reviewer | senior planner (this role) |
| Date | 2026-05-20 |
| Verdict | **Ready for external R0 dispatch** with 1 🟡 + 3 🟢 noted below; no blockers. |

## 1. Gates

| Gate | Result |
|---|---|
| `uv run ruff format --check src tests` | ✅ 47 files formatted |
| `uv run ruff check src tests` | ✅ All checks passed |
| `uv run mypy src tests` | ✅ 48 source files clean |
| `uv run pytest` | ✅ 274 collected (245 baseline + 29 new) |

Counts match commit-message claim verbatim.

## 2. Per-task verification

All 10 tasks satisfy acceptance criteria. File:line citations below.

| Task | Acceptance check | Result |
|---|---|---|
| C3-1 ADR-006 land | Status `Proposed → Accepted — 2026-05-20`; no body change | ✅ `docs/decisions/ADR-006-unknown-tool-id-semantics.md:3` Accepted (in prior commit `299b3be`) |
| C3-2 `UnknownToolError` + Literal sync | Class with `tool_id` attr + composed message; constitutional test extended with `get_type_hints` parity assertion | ✅ `src/orchestrator/autonomy/scoring.py:130-141` exception; `tests/core/test_constitution.py:74-84` extension uses `typing.get_type_hints(...)['rule']` comparison |
| C3-3 `score()` body | UnknownToolError on registry-miss; returns `reversibility`; docstring Raises section + ADR-006 ref; old "returns 0" sentence removed | ✅ `scoring.py:147-162`; old sentence removed (verified by grep) |
| C3-4 `decide_tier()` body | ADR-005 §5 formula verbatim; `max(0, …)` clamp; all 10 DecisionTrace fields; three-way comparison with correct rule labels | ✅ `scoring.py:165-207` |
| C3-5 `gate()` body | Pure composition; UnknownToolError propagates unwrapped (no try/except) | ✅ `scoring.py:210-223` (5-line body, grep of `try:` / `except` in body returns nothing) |
| C3-6 behavior tests | ≥ 14 tests in groups (a/b/c); named `test_git_push_with_user_intent_lands_on_countdown_not_hard` verbatim; references `git_push` at `config/tools.yaml.example:49-50` | ✅ `tests/autonomy/test_scoring.py:55-227`; 22 behavior-test instances (5 parametrized + 17 named); named pinning test at line 177-201 with exact name + correct file:line refs |
| C3-7 hard_confirm constitutional | Exact name; 22 (score, modifier) tuples; docstring cites ADR-005 §5(c) AND §5 Alternative B | ✅ `tests/autonomy/test_constitution.py:61-112`; 22 = 2 tuples × 11 scores; docstring at lines 62-87 covers both references; bonus: also asserts `threshold_confirm_effective == 0` (plan-implied, junior went a step further) |
| C3-8 §6 schema invariants | `TestSchemaInvariants` class; 6 tests (3 per class); docstring states scope + push-back #2 reference | ✅ `tests/autonomy/test_scoring.py:237-319`; 6 tests; class docstring (lines 238-247) names the scope and references senior plan §5 push-back #2 |
| C3-9 ADR-005 §5(c) revision | Architect verbatim sentence appended | ✅ `docs/decisions/ADR-005-autonomy-scoring-tiered-reversibility.md:144-148`; prose-wrapped but content verbatim |
| C3-10 commit + 5-surface scan | All gates clean; verbatim "ToolMeta + ThresholdConfig §6 explicit coverage queued for C4"; freeze-vs-impl line; tracking table + Q1-Q4 itemized; 5 surfaces spelled out | ✅ commit `57b0b33` message has all required elements |

## 3. Findings

### 🔴 Red

None.

### 🟡 Yellow

**Y1. `test_gate_happy_path_returns_autonomy_score` docstring self-contradiction**
- **Where**: `tests/autonomy/test_scoring.py:209-212`
- **What's wrong**: docstring first line says "→ HARD_CONFIRM" while the parenthetical immediately after correctly says "→ COUNTDOWN_CONFIRM", and the assertion at line 218 correctly asserts `COUNTDOWN_CONFIRM`. The first-line phrase is a stale documentation artifact.
- **What should be**: drop or correct the first phrase, e.g., "operator + propose_edit (reversibility=5) + no user intent → COUNTDOWN_CONFIRM (score=5 < eff_auto=6, score=5 ≥ eff_confirm=3)."
- **Why this matters**: a future contributor scanning the test file may copy the wrong intuition from the docstring. Two readings of the same docstring producing different tiers is exactly the kind of drift Principle 9 (terminology audit) flags. The assertion is correct, so behavior is fine — the doc is the problem.

### 🟢 Green

**G1. handoff.md §4.3 Operation-block verification not surfaced in commit message**
- **Where**: commit `57b0b33` 5-surface scan, surface 5 (narrative)
- **Observation**: plan §4 forcing function and C3-10 acceptance criteria both asked junior to *"verify Operation block + tier rules still match impl; minor edit only if drift discovered."* Junior correctly did not edit `handoff.md` §4.3 (verified: `handoff.md:161-166` Operation block matches `scoring.py:19-33` exactly). However, the verification result is invisible in the commit message — it just says "handoff.md §15 ADR index: ADR-006 row added", which only documents the §15 edit. A reader cannot tell from the commit whether §4.3 was checked or simply skipped.
- **What should be**: 5-surface scan surface 5 should explicitly say "handoff.md §4.3 — verified against scoring.py:19-33, no drift, no edit needed; handoff.md §15 — ADR-006 row added." Half-line addition; future R0 reviewers know the surface was scanned.

**G2. R0-A retrospective sub-rule "grep pre-edit values gone" not surfaced in commit message**
- **Where**: commit `57b0b33`, 5-surface scan or freeze-vs-impl drift line
- **Observation**: plan §4 forcing function called out *"R0-A retrospective sub-rule applied: grep pre-edit values gone where edits land (ADR-005 §5(c), `test-coverage-standard.md` §6 P1.1-example, handoff.md §15 ADR index)."* I verified manually that the edits don't leave stale text behind (ADR-005's prior §5(c) text is preserved with the new sentence appended; test-coverage-standard.md §6 P1.1-example field cleanly replaced with the P1.2-R1 instance; handoff.md §15 row added below existing entries). But the commit message doesn't itemize the grep result for each. Reader has to do their own grep to confirm the R0-A sub-rule was applied.
- **What should be**: add one line in the commit body, e.g., "Pre-edit values grep-verified gone (R0-A sub-rule): ADR-005 §5(c) prior prose preserved + new sentence appended; test-coverage-standard.md §6 P1.1-example field replaced cleanly; handoff.md §15 row added at end-of-list."

**G3. Process observation — branch topology oddity (not junior's fault)**
- **Where**: `git log --all --graph`
- **Observation**: PR #2 (carrying the senior plan + ADR-006 Accept) was merged INTO `claude/p1.2-c3-impl` (merge commit `c4458d3`), not into `main`. Main HEAD is still `cbd2e64` — main does NOT yet contain the senior plan, accepted ADR-006, or the architect's brief amend `8b727c0`. This means: (a) anyone reading main today does not see the C3 plan or ADR-006; (b) when the impl branch is eventually cherry-picked or merged to main, the merge commit `c4458d3` will look strange in main's history (a merge against a state main doesn't have); (c) external R0 reviewers fetching `claude/p1.2-c3-impl` get a consistent worldview, but anyone working off main is missing pieces.
- **What should be**: not in this commit's scope to fix. Architect's call on whether to land PR #2's plan + ADR commits to main now (recommended for locked-paths convention coherence) or after R0 completes. Flagging for visibility.

## 4. Plan-implied invariants junior caught (positives)

These weren't acceptance criteria but reflect care:

- **C3-7 extra assertion**: also asserts `result.trace.threshold_confirm_effective == 0` for every clamped case, not just `tier != HARD_CONFIRM`. This catches a regression where the tier is correct but the trace lies — exactly the kind of decoupled-failure the constitutional test should guard.
- **ADR-005 References section gained an ADR-006 cross-reference entry** (`docs/decisions/ADR-005-autonomy-scoring-tiered-reversibility.md:274-277`). Not in plan but appropriate per 5-surface scan; future readers of ADR-005 find ADR-006 from there.
- **`test_decide_tier_tool_id_does_not_affect_tier_selection`** (test_scoring.py:158-164): pins the docstring contract "tool_id is for trace only" as an executable assertion. Plan said this in `decide_tier`'s Out-of-scope but didn't require a test — junior added one anyway. Good defense.
- **C3-2 sync test failure-mode message** (test_constitution.py:79-84): the assertion message specifically tells the future contributor which file to edit. Reduces R0 round-trip on a future regression.

## 5. What external R0 reviewers should still check

senior plan-vs-impl is non-overlapping with external R0; the things below are NOT covered above and external R0 should scrutinize:

- **Pydantic / typing edge cases** I did not exhaust: are there `Field(ge=0, le=10)` boundary cases for `Operation.estimated_cost_usd` (which carries `default=0.0`, no upper bound) that could leak into the gate path?
- **Async/concurrency**: `gate()` is sync and pure today. If C4's caller wraps it in async with shared `tools` dict, does any mutation race appear? (Plan said §2 concurrency N/A; reviewer can confirm.)
- **Layering audit**: did C3 accidentally introduce any `from orchestrator.llm import …` in `autonomy/`? (`test_constitution_no_llm_calls_in_autonomy_module` should catch; reviewer should confirm it's still passing and the import-graph diff is empty.)
- **Recording / playback** (LLM test recordings dir) — irrelevant for C3 but worth confirming no recording invalidation.

## 6. Verdict

**Ready for external R0 dispatch.** Y1 is a one-line fix; junior can land it in a follow-up commit before or in parallel with R0-A/B work, or fold it into the first R0 round-up. G1-G3 are observations for the meta-review record, not gates.

After R0-A (and optionally R0-B), I'll write the close-out `meta.md` at `docs/process/reviews/P1.2-C3/meta.md` per the locked-paths convention.
