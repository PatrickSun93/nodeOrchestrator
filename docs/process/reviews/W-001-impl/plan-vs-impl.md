---
task_id: W-001-impl
round: plan-vs-impl
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 3
---

# Review: W-001-impl — plan-vs-impl

**Reviewer:** senior planner (Claude Opus 4.7, 1M context)
**Date:** 2026-05-26
**Artifacts reviewed:** commits `04eaf97` through `8ffabff` on `claude/w-001-impl` (9 atomic impl-* commits, 23 files, 2391 insertions, 4 deletions).

---

## 1. Coverage of plan acceptance criteria

Every plan-pinned acceptance bullet was checked against the diff. All 9 impl-* tasks satisfy their plan acceptance criteria.

| impl-* | Plan-mandated acceptance | Implemented as | Verdict |
|---|---|---|---|
| impl-1 | `schema.py` with exact 6-class shape; `.workflow/README.md`; 6 §6 invariant tests | `schema.py` matches byte-for-byte (9-state enum, OverrideEntry, TaskState with `requires_cross_family_review` schema hook from §5.1); README documents 9 states + override-pointer; `test_schema.py` has 11 tests covering all 6 mandated invariants + cycle-boundary positive case | ✓ Done |
| impl-2 | `transitions.py` with `parse_verdict / next_state / record_override / evaluate_merge_clean`; `WorkflowError` with `task_id`+`path` payload; constitutional test; §3 cleanup, §4 payload, §5 boundary coverage | All four functions present with docstrings explicitly citing §5.2 / §5.3 / §5.4 / R0-A-8 / R0-A-4; `WorkflowError` carries both `task_id` and `path` (`exceptions.py:26-31`); `test_constitution_no_llm_calls_in_workflow_module` mirrors the autonomy-module analogue; 40 tests in `test_transitions.py` cover all 5 gated rows × {match, no-match} + all 5 auto-trigger branches + 8 `parse_verdict` cases + 4 `evaluate_merge_clean` paths including timeout + OSError | ✓ Done |
| impl-3 | `reviews/README.md` frontmatter contract section + Pre-ADR-008 section calling out `P1.2-C3/`, `P1.2-C4/`; `_template-review.md` | README §"Frontmatter contract (post-ADR-008)" + §"Pre-ADR-008 review files" both present and name both task dirs explicitly (lines 58–67); template carries valid frontmatter + findings table skeleton + cross-checks | ✓ Done |
| impl-4 | argparse CLI, 5 subcommands (`status / init / advance / override / verify-workspace`), `pyproject.toml` scripts entry, RC-7 link in module docstring, **no `--strict` flag** per R0-A-on-plan-3 | All 5 subcommands present; `pyproject.toml` `[project.scripts] workflow = "orchestrator.workflow.cli:main"`; module docstring lines 3–4 cite RC-7 by name; no `--strict` anywhere in `cli.py` (grep clean); 21 CLI tests including 4 `verify-workspace` paths (clean / dirty / timeout / OSError) | ✓ Done |
| impl-5 | `.claude/settings.json` hook shells to CLI; hook is **non-blocking even on hard-error** per R0-A-on-plan-4; `session-start-hook.md` doc | `settings.json` SessionStart entry uses `uv run workflow status; uv run workflow verify-workspace; exit 0` — the `; exit 0` enforces non-blocking literally; `session-start-hook.md:24` states "non-blocking by design" + cites R0-A-on-plan-4 at line 31 | ✓ Done |
| impl-6 | `cmd_advance` body wires snapshot→`next_state`→atomic write; side-channel filter at the artifact-snapshot builder (per §5.2 + senior push-back #1); 4 mandated integration tests + source≠sink (§1) | `build_artifact_snapshot` at `cli.py:118` reads only `plan-vs-impl.md` and `R0-A.md` (hardcoded paths, not regex) and calls `_safe_load_verdict` on each — side-channel filter at the boundary as planned; `test_integration.py` has 6 tests covering e2e traversal + blocking + merge-conflict + rework + side-channel-no-op + atomic-write | ✓ Done |
| impl-7 | `.workflow/W-001-impl.yaml` with `state: awaiting_junior_impl` (R0-A-on-plan-1 (b)); commit body cites the rationale | impl-7 commit (`a4853ea`) state value `awaiting_junior_impl` ✓; commit body explicitly states "current truth, not future truth" rationale and cites R0-A-on-plan-1 (b) + Decisions 5 + 9 | ✓ Done |
| impl-8 | 4 doc-surface edits: `handoff.md` §17, `senior-planner.md` output-paths row, `contributing.md` RC-1 sub-bullet (graduation), `workflow-overview.md` §5 status flip + RC-1 row update | All 4 surfaces touched correctly; RC-1 wording matches plan's prescription verbatim including the "reverse drift" rationale (`contributing.md:84-88`); `workflow-overview.md` RC-1 row flipped from "Ready to graduate" to "Graduated" | ✓ Done |
| impl-9 | Deterministic state advance to `awaiting_senior_plan_vs_impl`; full 9-row tracking table; 5-surface scan report; verify-workspace run | impl-9 commit (`8ffabff`) advances state value with fresh `last_transition_at` and **no `override_history` entry** (natural transition); commit body contains 9-row table + 5-surface report enumerating each surface + RC-1 pre-edit grep applied to the state-file edit + verify-workspace clean note + 78 tests + ruff + mypy all green | ✓ Done |

## 2. Three architect-locked items — verification

- **R0-A-on-plan-1 (b) — impl-7 + impl-9 deterministic state flow**: confirmed. impl-7 sets `awaiting_junior_impl` with `last_transition_at: 2026-05-26T00:00:00+00:00`; impl-9 deterministically advances to `awaiting_senior_plan_vs_impl` with new timestamp `2026-05-26T12:00:00+00:00`. No `override_history` entry on impl-9. The "state file IS the truth" invariant (Decisions 5 + 9) is honored at the harness's first real use.
- **R0-A-on-plan-3 — `--strict` removed**: `grep -n "strict" src/orchestrator/workflow/cli.py` returns no matches; the `verify-workspace` subparser has no `--strict` argument; the hook command does not pass any strict flag.
- **R0-A-on-plan-4 — hook hard-error non-blocking**: `settings.json` uses `; exit 0` to force exit code 0 regardless of CLI exit; `session-start-hook.md` lines 24-31 explicitly document non-blocking semantics and cite R0-A-on-plan-4.

## 3. Scope and forcing functions

- **No scope creep.** All 23 touched files map to a plan-pinned task. Nothing landed outside the plan.
- **Constitutional tests**: new `test_constitution_no_llm_calls_in_workflow_module` lands in impl-2; all prior constitutional tests remain green.
- **5-surface scan**: PR-level scan in impl-9 commit body covers all 5 surfaces with concrete file paths.
- **RC-1 pre-edit grep**: applied to impl-9's own edits (state-file diff verified `awaiting_junior_impl` value gone post-edit). This is the first commit to use the sub-rule that the same commit graduates.
- **Tracking table**: present in every impl-* commit body; full 9-row composite in impl-9.

## 4. Senior observations (🟢 — not blocking; surfaced for R0-A awareness)

| # | Severity | File:line | What | Recommended action |
|---|---|---|---|---|
| 1 | 🟢 | `src/orchestrator/workflow/cli.py:126` | `build_artifact_snapshot` docstring references a `_REVIEW_FILENAMES` constant that doesn't exist; the implementation hardcodes `plan-vs-impl.md` and `R0-A.md` paths directly. Docstring drift only — behavior is correct. | One-line docstring fix in a future cleanup commit (or R1-A bundle if any). Not blocking. |
| 2 | 🟢 | `src/orchestrator/workflow/transitions.py:193-198` | Cycle-warning uses `print(..., file=sys.stderr)` rather than `warnings.warn()`. The plan said "emit a stderr warning" — `print` to stderr is a literal match. `warnings.warn` would interoperate with `-W` filters and be more conventional. Senior judgement at impl-2 time chose print-stderr; defensible per the plan's literal phrasing. | Watch only. Re-evaluate at first real cycle≥4 occurrence. |
| 3 | 🟢 | `src/orchestrator/workflow/transitions.py:25-46` | `ArtifactSnapshot` and `GateSnapshot` Pydantic models live in `transitions.py`. The plan permitted either `transitions.py` or `schema.py` ("frozen Pydantic dataclasses also declared in this file or in `schema.py`"). They are arguably more schema-shaped than transition-shaped; a future cleanup could move them. | Watch only. Cosmetic; no impact on behavior or layering. |

## 5. R0-A-on-plan-2 disposition (architect-deferred watch item)

The architect resolved R0-A-on-plan-2 (review-filename filter — explicit list vs regex) to "senior chooses at impl-6 implementation time; W-001-impl close evaluates canonicalization." Junior's impl-6 chose **explicit hardcoded paths** (`plan-vs-impl.md` and `R0-A.md` only — not R0-B, not R1-*), which is the narrowest valid scope: it matches the only two `ArtifactSnapshot` fields the transition table actually reads. Empirically validated by `test_side_channel_file_does_not_reach_parse_verdict` in `tests/workflow/test_integration.py`. **No action required this round.** W-001-impl close-out evaluates whether to canonicalize a regex pattern when R0-B / R1-* verdict fields eventually enter the snapshot schema.

## Cross-checks

- [x] Implementation matches the plan (no silent scope change) — all 23 files mapped to plan tasks; no extras.
- [x] All 5 doc surfaces updated for schema changes (code / example yaml / ADRs / arch docs / narrative) — full report in impl-9 commit body.
- [x] No LLM imports in `src/orchestrator/workflow/` (ADR-008 Decision 2) — `test_constitution_no_llm_calls_in_workflow_module` green.
- [x] CI gates pass: `ruff check` clean / `ruff format --check` clean / `mypy --strict src tests` clean / `pytest` 78 tests green.

## Verdict summary

W-001-impl is **clean**. Every plan acceptance bullet maps to a verifiable commit element; all three architect-locked R0-A-on-plan items applied correctly; constitutional test for the new module is in place and load-bearing; 5-surface scan executed and reported in impl-9 commit body; the harness eats its own dog food at impl-7/impl-9 (first real state file lands at the correct value, advances deterministically). Three 🟢 observations are cosmetic / future-cleanup — none blocking.

State machine should auto-advance to `awaiting_R0_A` on push of this review (per ADR-008 Decision 1 auto-trigger row: plan-vs-impl `verdict: clean` → `awaiting_R0_A`). The state file already reflects `awaiting_senior_plan_vs_impl` (impl-9 advance); after `workflow advance` runs against this committed review, the state file should transition to `awaiting_R0_A`.

Recommended next step: architect-partner dispatches R0-A on the impl branch.
