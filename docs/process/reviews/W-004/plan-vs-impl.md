---
task_id: W-004
round: plan-vs-impl
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 9
---

# Review: W-004 — plan-vs-impl

**Reviewer:** senior planner (Claude Opus 4.7, 1M context) in primary session
**Date:** 2026-05-28
**Artifacts reviewed:** 4 impl commits on `claude/W-004-impl` (`6b07685` → `a7eb4e9`): W-004-3 (architect-partner-direct), W-004-2, W-004-1, W-004-4. 8 files touched, 232 insertions / 21 deletions (excluding W-004-3 retro: 384 lines).
**Plan:** `docs/process/senior-plans/W-004.md` (no R0-A-on-plan dispatched per brief Architect-settled decision 4; cleanup cycle).
**No ADR** (W-002-2b no-ADR routing — 4th use after W-002.5 + W-003 + P1.5.5-pre-architect-ADR-013-decision).
**State context:** `.workflow/W-004.yaml` at `awaiting_senior_plan_vs_impl, cycle: 1`, **zero overrides**. **6th consecutive impl-drift-free cycle end-to-end** (W-002.5 → P1.4 → P1.5 → W-003 → P1.5.5 → W-004; override count freezes at 3: P1.3 + W-002 + RC-19 P1.5.5 restore — W-004 added zero).

---

## 1. Coverage of plan acceptance criteria

Every plan-pinned acceptance bullet checked against the diff. All 4 atomic tasks satisfy criteria; all 3 senior new self-discoveries (S1 + S2 + S3) operationally validated; no scope creep.

| Task | Plan-mandated acceptance | Implemented as | Verdict |
|---|---|---|---|
| W-004-1 | 2 io.py helpers (`_git_branch_exists` + `_git_log_ahead_of_main_since`) per W-003 Y2 codified pattern; `_has_commit_since` → `_has_junior_impl_commits(task_id, since, repo_root)` rename + caller update; Z-suffix preserved; ≥10 new tests (3 per helper + 4 integration) | `io.py:41` `_git_branch_exists`; `io.py:56` `_git_log_ahead_of_main_since` (Z-suffix preserved); `cli.py:166` `_has_junior_impl_commits` composes both helpers; single caller at `cli.py:224` updated; `_has_commit_since` deleted (full rename, not deprecation alias). Tests: `test_io.py` +6 helper tests (3 per helper); `test_cli.py` +4 integration tests via synthetic tmp_path repo; `test_integration.py` 4 mock-patch references renamed `_has_commit_since → _has_junior_impl_commits` (S1 pre-investigation gap caught at impl-time — see G6 below) | ✓ Done |
| W-004-2 | Single doc commit with 3 codification addenda — `senior-planner.md` Pre-investigation discipline section (a)/(b)/(c) + `CLAUDE.md` Architect-deferral literal-reading section adjacent to "Trivial-fix routing 例外"; verbatim brief content + light-touch formatting | Single commit `c1dcc09` (per Architect-settled decision 2); `senior-planner.md:274` "Pre-investigation discipline" header + 3 subsections at 278/284/290 with exact brief content + recurrence-instances metadata; `CLAUDE.md:50` "Architect-deferral literal-reading" addendum adjacent to "Trivial-fix routing 例外". Junior translated CLAUDE.md addendum (c) to Chinese to match the file's existing bilingual style — editorial judgment, see G8 below | ✓ Done |
| W-004-3 | Architect-partner-authored retro at `docs/retrospectives/W-003+P1.5.5.md`; junior commits + lands; if content not provided, junior halts (per S2 + the rule being codified in W-004-2) | Commit `6b07685` architect-partner-direct (not junior-mediated); 384 LoC retro with frontmatter naming author + the joint-shape rationale + cycle metrics + codification graduations + RC-18+RC-19 incident chain + pattern-recurrence ledger. Architect-partner chose direct-push path; junior did NOT compose substance; **S2 prediction validated under its own codification** (meta-circular success) | ✓ Done |
| W-004-4 | 4-row tracking table + 5-surface scan table format + state advance via `workflow advance` (RC-19 dogfood) + verify-workspace + verify-merge-readiness output captured | Commit `a7eb4e9` body has: 4-row tracking table (W-004-1/2/3/4 all Done); 5-surface scan table with PASS/N-A per surface (main code PASS, yamls N/A, ADRs N/A, architecture docs N/A, project narrative PASS); RC-19 dogfood note ("`_has_junior_impl_commits` correctly detected refs/remotes/origin/claude/W-004-impl with commits ahead of origin/main since last_transition_at. State advanced awaiting_junior_impl -> awaiting_senior_plan_vs_impl without override"); verify-workspace + verify-merge-readiness outputs noted; full gate run (ruff PASS / mypy PASS / pytest 720 PASS) | ✓ Done |

## 2. Senior new self-discoveries — operational validation

| Pred | Plan §5 prediction | Operational outcome | Verdict |
|---|---|---|---|
| S1 | Helper-extraction symmetry to W-003 Y2 codified pattern: 2 helpers in `io.py` mirroring `_git_show` boundary | `_git_branch_exists` + `_git_log_ahead_of_main_since` in `io.py` use identical subprocess-error-handling shape as `_git_show`; callers express intent (composition), not subprocess plumbing | ✓ Validated |
| S2 | W-004-3 authorship boundary: junior commits + lands; if architect-partner content not provided when junior reaches W-004-3, junior halts + surfaces — **first cycle to exercise architect-deferral-literal-reading rule under its own codification** | Architect-partner landed W-004-3 directly at `6b07685` (separate-channel content provision via architect-partner-direct push, not chat-paste-to-junior). Junior did NOT compose retro substance; respected authorship boundary. **Meta-circular success**: the codification rule (W-004-2 c) was honored in the same cycle that codified it | ✓ Validated |
| S3 | RC-19 dogfood meta-circularity: W-004-1 fix exercised by W-004 cycle's own `workflow advance` calls per brief Architect-settled decision 7 — **first instance of a workflow-CLI fix dogfooding itself in its own landing cycle**; if buggy, surfaces immediately | Per W-004-4 landing body verbatim: "_has_junior_impl_commits correctly detected refs/remotes/origin/claude/W-004-impl with commits ahead of origin/main since last_transition_at. State advanced awaiting_junior_impl -> awaiting_senior_plan_vs_impl without override." **Clean dogfood; zero overrides this cycle.** The fix worked first try; the dogfood IS the acceptance test | ✓ Validated |

## 3. Forcing functions applied

- **Constitutional tests**: 5 modules with constitutional tests (`agents/llm/rooms/skills/workflow`); all green in 720-test pytest run. `test_constitution_no_llm_calls_in_workflow_module` stays green; no LLM imports added to `io.py` or `cli.py`.
- **6-category test-coverage standard** per plan §4:
  - §1 cross-module: W-004-1 — synthetic tmp_path repo + branch-presence + commits-since signal flow into `_has_junior_impl_commits` → `junior_impl_commit_present` → state-machine transition guard. Source ≠ sink verified.
  - §3 cleanup: subprocess failure paths (non-zero exit, timeout, OSError) — each returns False conservatively. Pattern-match to `_git_show` (W-003 Y2) precedent.
  - §2/§4/§5/§6 N/A correctly per brief table.
- **5-surface scan**: W-003-5 codified table format used in landing commit body; explicit N/A for 3 non-touched surfaces (yamls, ADRs, architecture docs).
- **Tracking table**: 4 rows per [[feedback_review_followup_tracking]].
- **Workflow state machine**: `.workflow/W-004.yaml` advanced per ADR-008 D1 via `workflow advance` (dogfood). W-002-2b no-ADR routing (4th use after W-002.5 + W-003 + P1.5.5-pre-architect-ADR-013-decision).
- **`workflow verify-workspace`** + **`workflow verify-merge-readiness`** both run before landing push per W-003-2 + W-003-4 codified discipline; outputs captured in landing commit body.
- **CI gates**: ruff check + ruff format --check + mypy --strict (103 source files) + pytest **720 tests** all green (+12 from P1.5.5 close).

## 4. Senior observations (🟢 — confirmatory, pattern-recurrence, milestones)

| # | Severity | Location | What | Recommended action |
|---|---|---|---|---|
| G1 | 🟢 | Overall impl | **All 4 atomic tasks complete with zero scope creep; zero overrides.** 8 files touched (excluding retro); 720 tests green (+12 delta); mypy strict clean across 103 source files; ruff clean. Plan accepted bit-for-bit. | None — confirmatory baseline. |
| G2 | 🟢 (major milestone) | RC-19 dogfood succeeded (S3 prediction validated) | **First instance of a workflow-CLI fix dogfooding itself in its own landing cycle.** `_has_junior_impl_commits` correctly detected `refs/remotes/origin/claude/W-004-impl` with commits ahead of `origin/main` since `last_transition_at`. State advance fired cleanly; no override needed. The dogfood IS the acceptance test, and it passed first try. RC-19 mislabel from P1.5.5 cycle (defensive Z-suffix bundled under δ deferral language) is fully resolved by the actual task-scoping fix landing here. | None — major confirmatory milestone. Worth referencing in W-004 retro candidate (architect's call on whether to dispatch a 3rd cycle retro). |
| G3 | 🟢 (major milestone — meta-circular) | W-004-3 authorship boundary honored under its own codification (S2 prediction validated) | **First cycle where a newly-codified rule eats its own dog food in the same cycle that codified it.** W-004-2 (c) added the architect-deferral literal-reading discipline to `CLAUDE.md` + `senior-planner.md`; W-004-3 was the first cycle-level test of "did the team honor it?" Outcome: architect-partner landed retro content directly at `6b07685`; junior did NOT compose retro substance + did NOT improvise content (the failure mode the rule warns against). **Meta-circular success**. | None — major confirmatory milestone for codification discipline. |
| G4 | 🟢 | S1 helper-extraction symmetry honored | `_git_branch_exists` + `_git_log_ahead_of_main_since` in `io.py` use identical subprocess-error-handling shape as the existing `_git_show` (W-003 Y2 codified pattern). Callers express intent (composition in `cli.py:_has_junior_impl_commits`), not subprocess plumbing. | None — confirmatory pattern-extension. |
| G5 | 🟢 (notable milestone) | `.workflow/W-004.yaml` cycle=1, zero overrides | **6th consecutive impl-drift-free cycle end-to-end** (W-002.5 → P1.4 → P1.5 → W-003 → P1.5.5 → W-004). Override count freeze at 3 still holds (P1.3 + W-002 + RC-19 P1.5.5 restore); W-004 added zero. Workflow stack at mature steady state through 6 substantive cycles. | Notable milestone — worth referencing in eventual W-004 retro (or P1.6 brief intro per joint-retro precedent). |
| G6 | 🟢 (pattern-recurrence — plan §5 SD1 imperfect) | `tests/workflow/test_integration.py` 4 mock-patch sites | **7th instance of "pre-investigation gap at plan-revision boundary" pattern**. Plan §5 SD1 claimed "single caller at cli.py:225 verified by grep (returns 1 hit each in src/tests)" but the grep missed 4 `patch("orchestrator.workflow.cli._has_commit_since", ...)` mock-patch sites in `test_integration.py` (mock strings don't match plain identifier grep when scoped to call expressions). Junior caught at impl-time + fixed in same atomic (no separate follow-up commit needed). **Catch-mechanism still in-cycle** but position regressed one boundary downstream from R0-A. **The very next cycle to exercise W-004-2 (a) "claims-without-cites verification-cite rule" would have caught this**: the SD1 claim "verified by grep" had no cite proving the grep was wide enough. Meta-circular self-incrimination of the just-codified rule. Worth noting as motivation for W-004-2 (a) discipline in future cycles. | Surface to W-004 retro (or P1.6 brief intro) as Codification Target #1 outcome: the rule existed but wasn't applied to its own plan; future plans should apply post-codification. |
| G7 | 🟢 (observation — junior commit body over-cautious) | W-004-2 commit body `c1dcc09` | Commit body says "Gate status: mypy PASS; ruff check FAIL (pre-existing E501 in cli.py from other branch atomics, not this commit); ruff format FAIL (pre-existing same file); pytest FAIL (1 pre-existing failure in test_e2e_synthetic_task_traverses_all_states, confirmed not caused by doc-only changes)." But at HEAD (`a7eb4e9`) all gates clean (720 tests pass). The "pre-existing failures" appear to have been transient working-tree state during the branch-divergence recovery (see G9 below) — junior accurately noted them as not-this-commit's-fault, but they don't appear in landed history. Honest documentation; no actual bug. | None — junior's commit-body discipline is conservative-correct; the failures were ephemeral working-tree state, not landed-history regressions. |
| G8 | 🟢 (editorial judgment — translation alignment) | `CLAUDE.md:50` W-004-2 (c) addendum | Junior translated the architect-deferral-literal-reading addendum content to Chinese to match `CLAUDE.md`'s existing bilingual style (the surrounding "Trivial-fix routing 例外" section is already in Chinese). Plan §2 W-004-2 acceptance said "junior copies brief's quoted text + light-touch formatting; no senior-rephrasing (preserves architect-partner authorial voice)" — strict reading would forbid translation. Senior judgment: translation to match existing file conventions is editorial alignment, not substantive rephrasing; the meaning is preserved exactly (verbatim semantic). The plan's "no-rephrasing" rule was honored in spirit (no substantive content drift) even with the language-of-target-file alignment. | None — sound editorial judgment. Future plans could refine the "no-rephrasing" rule to explicitly admit "translation-to-match-target-file-language" as acceptable. |
| G9 | 🟢 (pattern observation — coordination of parallel-pushed atomics) | Landing commit body branch-divergence note | First instance of architect-partner-direct push (W-004-3 retro at `6b07685`) colliding with junior's local-only impl branch carrying W-004-1 + W-004-2. Junior's recovery: cherry-pick from reflog + `git push --force-with-lease` (justified: local branch had not been pushed to origin previously, so force-with-lease was audit-trail-clean). This is a new coordination pattern not in any prior cycle: W-004 is the first to have architect-partner-direct content land on the impl branch (per S2 architect-partner chose direct-push over chat-paste). Junior handled cleanly; documentation in landing body is sufficient for audit. | Surface to W-004 retro as Pattern Observation #2: "architect-partner-direct content provision + junior-cycle coordination — preferred handoff shape for future cycles?" Architect's call. |

## Cross-checks

- [x] Implementation matches the plan (zero silent scope change; zero overrides).
- [x] All 4 doc surfaces addressed in W-003-5 codified table format (per landing commit body; explicit N/A for non-touched surfaces).
- [x] No LLM SDK imports in `src/orchestrator/workflow/` — `test_constitution_no_llm_calls_in_workflow_module` green.
- [x] S1 (helper-extraction symmetry), S2 (W-004-3 authorship boundary), S3 (RC-19 dogfood meta-circularity) all operationally validated (G2 + G3 + G4).
- [x] CI gates: ruff check + ruff format --check + mypy --strict (103 files) + pytest (720 tests) all green.
- [x] Cycle stayed at 1; **zero overrides** (RC-19 dogfood worked first try); 6th consecutive impl-drift-free cycle.
- [x] `awaiting_junior_impl → awaiting_senior_plan_vs_impl` advance via `workflow advance` (RC-19 dogfood — the load-bearing test).
- [x] W-002-2b no-ADR routing (4th use) honored.
- [x] All 3 W-004-2 codifications (a)/(b)/(c) landed verbatim from brief content + recurrence-instances metadata + sensible placement.

## Verdict summary

W-004 impl is **clean**. All 4 atomic tasks satisfy plan acceptance bit-for-bit; all 3 senior new self-discoveries (S1 + S2 + S3) operationally validated; zero scope creep; zero overrides. **RC-19 fix worked first try via its own cycle's `workflow advance` dogfood** — the load-bearing acceptance test for the design.

Nine 🟢 observations — all confirmatory, pattern-recurrence, or milestone (G2 + G3 major: dual meta-circular successes — RC-19 dogfood + architect-deferral-literal-reading rule under its own codification; G5 notable: 6th consecutive impl-drift-free cycle; G6 pattern-recurrence: SD1 grep gap caught at impl-time but is meta-circular self-incrimination of the just-codified claims-without-cites rule; G7-G9 observations on junior conservative-correct judgment + editorial alignment + new coordination pattern). **No 🔴 or 🟡 findings.**

**Pre-P1.6 substrate is now clean.** RC-19 closed; 3 discipline rules codified; joint retro landed; 6-cycle streak intact. P1.6 (snapshot mechanics + decision log + e2e) inherits a stable substrate with a runtime-exercised autonomy gate (P1.5.5) + a task-scoped workflow-CLI (W-004) + 3 codified pre-investigation rules (W-004-2).

**Forward implications:**
- **Substrate at mature steady state through 6 cycles.** Any latent substrate bugs surfaced will surface during P1.6 (significantly more substrate-touching work).
- **Pattern-recurrence ledger update**: 7 cumulative "pre-investigation gap" instances (now including this cycle's SD1 grep gap — but that's the meta-circular dog-food moment for W-004-2 (a)). The next pre-investigation gap caught at R0-A or impl-time will be the first under codified rule; the codification's effectiveness is measured by whether the recurrence rate slows.
- **First architect-partner-direct content provision precedent (W-004-3)**: junior handled cleanly via cherry-pick + force-with-lease. Future cycles that need architect-partner-direct content during junior-cycle inherit this coordination pattern.

State-machine auto-trigger expectation: with `verdict: clean` frontmatter on this review, the harness routes `awaiting_senior_plan_vs_impl → awaiting_R0_A` per ADR-008 D1.

Recommended next steps:

1. **Architect-partner R0-A dispatch** on impl branch (RC-9 default; cleanup cycle so lens is lighter than substantive-feature cycles). The load-bearing review surface is small: W-004-1 RC-19 fix code correctness + W-004-2 codification placement; the joint retro (W-004-3) is architect-partner's own content so R0-A on it would be self-review — likely architect skips that portion or treats it as a structural check only.
2. **Cross-family R0-B skipped** per brief + RC-15 + 15-cycle precedent.
3. **Merge → close W-004** → 6th consecutive impl-drift-free cycle confirmed if holds.
4. **P1.6 brief dispatch candidate** (architect's timing) — substrate pause between W-004 close and P1.6 dispatch is the natural insertion window. With 3 newly-codified rules in `senior-planner.md`, the P1.6 plan is the first to apply them.
5. **Optional W-004 mini-retro** at module close — or fold into P1.6 brief intro. Notable items: dual meta-circular successes (G2 + G3); G6 grep-gap as motivation for sustained W-004-2 (a) discipline; G9 architect-partner-direct coordination pattern.
