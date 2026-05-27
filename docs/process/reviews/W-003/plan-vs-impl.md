---
task_id: W-003
round: plan-vs-impl
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 5
---

# Review: W-003 — plan-vs-impl

**Reviewer:** senior planner (Claude Opus 4.7, 1M context)
**Date:** 2026-05-27
**Artifacts reviewed:** 5 impl commits on `claude/W-003-impl` (`5e07f17` → `db89e3a`): W-003-1, W-003-4, W-003-2, W-003-3, W-003-5. 7 files touched, 542 insertions / 26 deletions.
**Plan:** `docs/process/senior-plans/W-003.md` (post-R0-A routing absorption; Y1 → α + Y2 → α; no `adr` key in frontmatter — W-002-2b no-ADR routing third use).
**State context:** `.workflow/W-003.yaml` at `awaiting_senior_plan_vs_impl, cycle: 1`. **Fourth consecutive clean P1.x/W-* cycle end-to-end** (P1.4 + P1.5 + W-002.5 + W-003 all closed at cycle=1 with zero overrides).

---

## 1. Coverage of plan acceptance criteria

Every plan-pinned acceptance bullet checked against the diff. All 5 W-003-* tasks satisfy their criteria; both architect-routing items (Y1 → α + Y2 → α) honored exactly.

| Task | Plan-mandated acceptance | Implemented as | Verdict |
|---|---|---|---|
| W-003-1 | `_git_show` helper added in `io.py` (Y2 pre-pin); `_read_plan_frontmatter` consumes helper; `_has_commit_since` UNTOUCHED per Y1 correct-by-design; ≥4 tests (helper-level + integration) | `io.py:_git_show` exists with exact spec per architect routing (`(rel_path, ref="origin/main") -> str | None`; subprocess + timeout + non-zero-exit handling centralized); `_read_plan_frontmatter` body uses `content = _git_show(rel_path_str)` — no inline subprocess; `_has_commit_since` in `cli.py` UNTOUCHED (verified via `git show 5e07f17 -- src/orchestrator/workflow/cli.py | grep -c "_has_commit_since"` returns 0); `test_io.py` 101 LoC new (helper unit tests + integration) | ✓ Done |
| W-003-2 | New `cmd_verify_merge_readiness` CLI subcommand; checks both `plan-vs-impl.md` + `R0-A.md` exist with `verdict: clean`; warn-don't-block (exit 0 always); ≥5 tests | `cmd_verify_merge_readiness` function present in `cli.py`; subparser registered (CLAUDE.md confirms 6-subcommand surface: status, init, advance, override, verify-workspace, verify-merge-readiness); test_cli.py extends by 291 LoC | ✓ Done |
| W-003-3 | Extend `verify-workspace` with state-file divergence detection; **consumes `_git_show` helper** (no inline subprocess); warn-don't-block; ≥4 tests | `cmd_verify_workspace` body extended; `origin_content = _git_show(f".workflow/{task_id}.yaml")` — exact helper consumption per architect routing Y2; existing `git fetch origin` + `git status --short` checks preserved; new local task (file not on origin/main) skipped silently | ✓ Done |
| W-003-4 | `CLAUDE.md` `## Workflow verify-workspace pre-landing` section ~10 lines (docs-gap root cause hypothesis); manual smoke-test in commit body | `CLAUDE.md` lines 26-31 carry the section with exact wording from plan acceptance criteria ("Before pushing any landing commit (5-surface scan committed), run `uv run workflow verify-workspace`...; CLI exits 0 always; architect lens on warnings is the load-bearing check") | ✓ Done |
| W-003-5 | 5-row tracking table; 5-surface scan with RC-1 pre-edit grep per surface; deterministic state advance; verify-workspace run before push | Commit body has 5-row tracking table + 5-surface scan **in table format with per-file PASS/FAIL** (denser than P1.5-8's narrative — improvement worth noting in G5); state file advanced to `awaiting_senior_plan_vs_impl` with no override entry; verify-workspace run dogfooded successfully (caught real W-002 divergence — see G3 below) | ✓ Done |

## 2. Architect-routing verification (both items)

**Y1 → α (senior pre-investigates `_has_commit_since` at plan revision; pin call up-front):**

Plan absorbed the investigation; impl matches:
- Plan §2 W-003-1 acceptance documents "Verdict: correct-by-design. No fix; no W-003-1b atomic" with rationale (intentional asymmetry: plan content needs publish-event/origin-read; impl activity needs work-event/local-read).
- Impl: `_has_commit_since` in `cli.py` UNTOUCHED in W-003-1 commit (`5e07f17`); verified by grep returning 0. **No regression.**

**Y2 → α (senior pre-pins `_git_show` helper extract upfront in W-003-1):**

Plan absorbed the helper spec; impl matches exactly:
- `_git_show(rel_path: str, ref: str = "origin/main") -> str | None` in `io.py` — exact signature per routing spec.
- Subprocess error handling (timeout + non-zero exit + missing-file return-None) centralized at one boundary.
- W-003-1 (`_read_plan_frontmatter`) + W-003-3 (`verify-workspace` extension) **both** consume the helper. No inline subprocess duplicated in W-003-3.
- Tests mock `_git_show` at helper boundary (cleaner than W-002.5's inline subprocess mocking pattern).

## 3. Senior plan §5 push-back / self-discovery outcomes

All 6 push-backs aligned with brief leans (applied as-is). All 3 self-discoveries pre-resolved per architect routing:

- **#7 `_has_commit_since` investigation** → PRE-RESOLVED (correct-by-design; documented in W-003-1 acceptance).
- **#8 verify-workspace invariant scope** → kept narrow (no cycle monotonicity / override_history checks added per YAGNI — confirmed by reading the W-003-3 diff: only the local-vs-origin divergence check landed).
- **#9 `_git_show` helper extract** → PRE-PINNED (extracted upfront in W-003-1 per Y2 → α).

## 4. Forcing functions applied

- **Constitutional tests**: all 25+ (post-P1.5) remain green. No new constitutional test added (correct per brief Architect-settled decision 5 — no new module / no new layering edge).
- **6-category test-coverage standard**:
  - §1 cross-module: `_read_plan_frontmatter` source ≠ sink test (working-tree path → `_git_show` → origin/main content). ✓
  - §2 N/A correctly.
  - §3 cleanup: `_git_show` helper centralizes subprocess error handling (timeout 10s + non-zero-exit + missing-file). ✓
  - §4 exception payloads: light (verify-merge-readiness graceful frontmatter-parse-failure handling). ✓
  - §5 N/A correctly (no new boundary validators).
  - §6 N/A correctly (no new Pydantic models).
- **5-surface scan**: W-003-5 commit body per-surface PASS/FAIL table. **Format improvement vs P1.5-8's narrative** (see G5 below).
- **Tracking table**: 5-row composite in W-003-5 + per-task tables in each individual commit body.
- **Workflow state machine**: `.workflow/W-003.yaml` advances per ADR-008 D1. **W-002-2b no-ADR routing third use** (after W-002.5 + P1.5.5-original) confirms the path stays stable across 3 cycles.

## 5. Senior observations (🟢 — confirmatory; not blocking)

| # | Severity | Location | What | Recommended action |
|---|---|---|---|---|
| G1 | 🟢 | Overall impl | **All 5 W-003-* tasks complete with zero scope creep.** 7 files touched, all mapping to plan tasks. 693 tests green (delta from W-002.5 / P1.5 baseline); mypy strict clean across 101 source files. Plan accepted bit-for-bit with no junior interpretation drift. | None — confirmatory baseline. |
| G2 | 🟢 (major) | Architect routing Y1 + Y2 absorption | Both routing items honored exactly. **Y1 verification is rare type — "code that should NOT change" is harder to verify than "code that should change"**: senior verified via `git show 5e07f17 -- src/orchestrator/workflow/cli.py | grep -c "_has_commit_since"` returning 0 — `_has_commit_since` UNTOUCHED in W-003-1 commit. The architect-routing pattern of "force decisions to plan revision rather than impl-time" (P1.5 R0-A Y1 + W-003 Y1 + Y2 = 3 instances) is now operationally validated end-to-end. | None — confirmatory milestone. Pattern-recurrence note for W-003 retro: codify in `senior-planner.md` (deferred per architect routing). |
| G3 | 🟢 (notable empirical validation) | W-003-5 commit body | **W-003-3 (the new divergence-detection feature) dogfooded itself on its own landing commit.** Verify-workspace caught real W-002 state-file divergence (W-002 is closed; local override_history entry differs from origin/main). Junior noted in commit body: "Benign — W-003-3 is correctly detecting real divergence. No action needed; architect retains judgment per warn-don't-block discipline." **Empirical validation of the feature working as designed before any external test.** The warn-don't-block discipline + structured output worked exactly as the brief Architect-settled decision 2 envisioned. | Notable milestone — worth referencing in eventual W-003 retro as evidence the feature paid for itself in its own cycle. |
| G4 | 🟢 | `.workflow/W-003.yaml` cycle=1 + override_history=[] | **Fourth consecutive clean P1.x/W-* cycle end-to-end** (P1.4 + P1.5 + W-002.5 + W-003 all closed at cycle=1, zero overrides). The workflow stack (W-001 state machine + W-002 task→ADR + W-002-2 cycle counter + W-002-2b no-ADR routing + W-002.5 multi-ADR aggregation + this W-003 refinement) is now operationally validated through 4 substantive cycles. RC-11 cluster's "no more no-ADR overrides post-W-002-2b" prediction holds. | Notable milestone — worth referencing in W-003 retro alongside G3. |
| G5 | 🟢 | W-003-5 commit body 5-surface scan format | **Format improvement vs prior 5-surface scans.** P1.5-8 used narrative per surface; W-003-5 uses a structured table with per-file location + PASS/FAIL. Denser, scannable in one glance, supports future automation (parse-table-vs-parse-prose). Worth proposing as the new default format in W-003 retro / senior-planner.md addendum candidate. | Watch only — surface to W-003 retro as candidate format-standardization note. |

## Cross-checks

- [x] Implementation matches the plan (no silent scope change) — all 7 touched files map to plan tasks.
- [x] All 5 doc surfaces addressed per Q3 (per-file PASS/FAIL in W-003-5).
- [x] No LLM imports in `src/orchestrator/workflow/` — `test_constitution_no_llm_calls_in_workflow_module` green.
- [x] Architect-routing Y1 (correct-by-design) — `_has_commit_since` UNTOUCHED verified via grep.
- [x] Architect-routing Y2 (`_git_show` helper) — present with exact spec; both consumers (W-003-1 + W-003-3) use it.
- [x] CI gates: `ruff check` / `ruff format --check` / `mypy --strict src tests` clean across 101 source files / `pytest` 693 tests green.
- [x] Cycle stayed at 1; no overrides; fourth consecutive clean cycle.
- [x] verify-workspace dogfooded on own landing commit — caught real divergence; feature validated empirically.

## Verdict summary

W-003 impl is **clean**. All 5 atomic tasks satisfy plan acceptance bit-for-bit; both architect-routing items (Y1 → α + Y2 → α) honored exactly (including the rare "code that should NOT change" verification for Y1); 6 push-backs aligned with brief leans; 3 self-discoveries pre-resolved at routing-absorption time per the architect's discipline of forcing decisions to plan revision rather than impl-time.

Five 🟢 observations — all confirmatory or positive milestones (G2 major: architect-routing-as-precedent operationally validated; G3 notable: verify-workspace dogfooded itself successfully; G4 notable: fourth consecutive clean P1.x/W-* cycle; G5 watch: 5-surface scan format improvement). None blocking.

**The RC-13 forcing function (W-003-2 `verify-merge-readiness`) + RC-16 fix (W-003-1) + verify-workspace divergence detection (W-003-3) + junior-session capability docs-gap closure (W-003-4) close the last 4 deferred workflow-infrastructure items.** Substrate is clean before P1.6 dispatches.

State-machine auto-trigger expectation: with `verdict: clean` frontmatter on this review, the harness routes `awaiting_senior_plan_vs_impl → awaiting_R0_A` per ADR-008 D1.

Recommended next steps:

1. Architect-partner R0-A dispatch on impl branch (default per RC-9; brief Architect-settled decision 6).
2. Cross-family R0-B skipped per brief + RC-15 (already settled — 11th consecutive single-reviewer cycle).
3. Merge → close W-003 → fifth consecutive clean P1.x/W-* cycle if it holds.
4. Substrate pause between W-003 close and P1.6 dispatch per brief cross-reference (one sleep-cycle gap).
5. **W-003 retrospective** at module close. Notable items: dual milestones (G3 dogfood + G4 fourth-cycle); architect-routing pattern operationally validated (G2); 5-surface scan format improvement candidate (G5); pattern-recurrence note for `senior-planner.md` (3 instances of "decision-deferred-to-impl pre-resolved at plan-revision" — codify candidate).
