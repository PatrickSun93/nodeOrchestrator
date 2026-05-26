---
task_id: P1.3
round: plan-vs-impl
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 3
---

# Review: P1.3 — plan-vs-impl

**Reviewer:** senior planner (Claude Opus 4.7, 1M context)
**Date:** 2026-05-26
**Artifacts reviewed:** commits `3351ee2` through `eddd7ae` on `claude/P1.3-impl` (5 atomic impl commits, 15 files, 1375 insertions). ADR-009 Accepted on main (`99aae9e`).
**Cycle context:** `.workflow/P1.3.yaml` shows `cycle: 2` — the increment came from architect-partner's override `cfbf087` (`awaiting_architect_accept → awaiting_junior_impl` after `_read_adr_status` failed to detect ADR-009 Accept, surfaced as RC-11). **This is the first plan-vs-impl pass on P1.3**, not a rework review.

---

## 1. Coverage of plan acceptance criteria

Every plan-pinned acceptance bullet was checked against the diff. All 7 plan tasks satisfy their criteria (P1.3-1 and P1.3-2 already landed via PR #6 on main; P1.3-3 through P1.3-7 are the impl branch).

| Task | Plan-mandated acceptance | Implemented as | Verdict |
|---|---|---|---|
| P1.3-1 | ADR-009 Proposed at locked path; 8 enumerated Decisions; A–E Considered alternatives; References complete | Landed on main as part of PR #6 / ADR commit `99aae9e`; verified Status: Accepted — 2026-05-26 + 8 Decisions present | ✓ Done (out-of-branch) |
| P1.3-2 | ADR-009 status `Proposed → Accepted` + state-file transition to `awaiting_junior_impl` | ADR-009 Accepted on main; state transition done via override `cfbf087` because `_read_adr_status` didn't detect Accept (RC-11). Override path is ADR-008 Decision 10's legitimate force-advance mechanism. | ✓ Done (via override; flagged as 🟢 observation #2 below) |
| P1.3-3 | `src/orchestrator/skills/` package; 5 Pydantic models with full §6 coverage; 2 constitutional tests (`no_llm_calls_in_skills_module` + `core_does_not_import_skills`); R0-A-on-plan-1(a) `SkillMatchRecord` has no `matched: bool`; R0-A-on-plan-4 `Skill.body = Field(min_length=1)`; §5 multi-position star-mixing rejection | `schema.py` declares exactly 5 models matching the plan's frozen API; `SkillMatchRecord` has only `skill_id + rejection_reason` (R0-A-on-plan-1(a) honored); `Skill.body: str = Field(min_length=1)` (R0-A-on-plan-4 honored); `test_constitution.py` carries both required constitutional tests; `test_schema.py` 37 tests including star-mixing rejection at positions 0 and 1 (`test_agents_star_with_concrete_id_raises` + variant); `exceptions.py` `SkillError` carries `path` and `field` payload | ✓ Done |
| P1.3-4 | `load_skills(directory) -> dict[str, Skill]`; filename-stem-equals-id rule (ADR-009 Decision 8) enforced at load time with `field="id"` on mismatch; SkillError carries `path` + `field`; non-dict frontmatter raises (R0-A-on-plan-5 — pattern from `llm/config_loader._read_yaml`); ≥9 tests | `loader.py:70` returns `dict[str, Skill]`; `_parse_frontmatter:61-65` raises `SkillError` on `isinstance(raw, dict) == False` with "must be a mapping" message (R0-A-on-plan-5 honored); filename-stem check at lines 100-107 raises `SkillError` with `field="id"` (ADR-009 Decision 8 honored); duplicate-id detection at lines 109-117; `test_loader.py` has 12 tests | ✓ Done |
| P1.3-5 | `decide_skills_for_context` pure function; ordered `selected` by `(-priority, id asc)`; predicate precedence (1 agent → 2 room_type → 3 room_state); `triggering_event_type` accepted but unused with docstring; `SkillSelection` carries `SkillDecisionTrace`; ≥10 tests including §1 cross-module integration | `decision.py:21` signature matches plan exactly; predicate evaluation at lines 49-72 honors precedence; `matched_skills.sort(key=lambda s: (-s.priority, s.id))` at line 76; `_ = triggering_event_type` at line 44 with explicit unused-in-P1.3 docstring; returns `SkillSelection` embedding `SkillDecisionTrace`; `test_decision.py` 16 tests | ✓ Done |
| P1.3-6 | 2 sample skills (research-decomposition + debugging-workflow) covering both `agents` shapes (`["*"]` + concrete), both `room_states` shapes (None + explicit), both categories (general + engineering), distinct priorities; ≥4 integration tests including §1 source ≠ sink with sentinel assertion | `config/skills/general/research-decomposition.md` (agents=[prober, skeptic], room_types=[research, idea_validation], no room_states, priority 50) + `config/skills/engineering/debugging-workflow.md` (agents=["*"], room_types=[bug_fix, code_review], room_states=["open"], priority 70) exactly match the plan's schema-branch coverage; `test_integration.py` 4 tests including `test_full_happy_path` with `assert rd_skill.applies_to.agents != ["sentinel-not-in-yaml"]` (§1 source ≠ sink asserted) | ✓ Done |
| P1.3-7 | Tracking table 7 rows; 5-surface scan per Q3; RC-1 pre-edit grep per surface; deterministic state advance to `awaiting_senior_plan_vs_impl` with no override entry; handoff.md §5.3 + arch docs updates; gates green | Commit body has 7-row tracking table; 5-surface scan enumerated each surface with concrete grep result; state file transitions deterministically from `awaiting_junior_impl → awaiting_senior_plan_vs_impl` with fresh `last_transition_at` and no new `override_history` entry; `handoff.md` §5.3 gains "P1.3 已落地" paragraph with module path, loader/matcher API, sample skills location, downstream-scope note; commit body notes 454 tests / ruff / mypy strict all clean | ✓ Done |

## 2. Architect-locked R0-A-on-plan items — verification

| Item | Verification |
|---|---|
| R0-A-on-plan-1(a) — drop `matched: bool` from `SkillMatchRecord` | `schema.py:53-65` confirms the field is absent; only `skill_id + rejection_reason` present. `decision.py:53/60/69/73` constructs records using only those two fields. No commented-out `matched: bool`; no test referencing `.matched`. Clean. |
| R0-A-on-plan-2 — ADR-009 Decision 8 (filename-stem) | ADR-009 line 222–238 carries Decision 8 with the load-time-validator rationale. `loader.py:100-107` enforces the rule with `SkillError(path=md_path, field="id")`. Test `test_loader.py` covers the mismatch case. |
| R0-A-on-plan-3 — closed-category Harder sentence with Literal-extension precedent | ADR-009 Consequences "Harder" section carries the new bullet citing ADR-007 Decision 2 reversibility-Low precedent. |
| R0-A-on-plan-4 — `Skill.body = Field(min_length=1)` | `schema.py:50` matches. Empty-body test would raise (Pydantic). |
| R0-A-on-plan-5 — non-dict frontmatter check | `loader.py:61-65` `isinstance(raw, dict)` check raises `SkillError(path=path)` with "must be a mapping" message. Pattern parallel to `llm/config_loader._read_yaml`. |

## 3. Senior's 6 push-backs (from plan §5) — outcomes

All accepted by architect-partner per `R0-A-on-plan.md`; impl honored each:

- #1 ADR-009 yes → ADR-009 exists Accepted on main.
- #2 `applies_to.room_states = None` for "all" → `schema.py:15` + validator at lines 30-40.
- #3 2 sample skills → exactly 2 files in `config/skills/`.
- #4 alphabetical tie-break by `id` → `decision.py:76` sort key.
- #5 `triggering_event_type` kept-but-unused → present on signature; explicit `_ = triggering_event_type` line; docstring states "no effect in P1.3".
- #6 `dict[str, Skill]` not `SkillRegistry` wrapper → `load_skills` returns `dict`; `decide_skills_for_context` accepts `dict`; no wrapper class anywhere.

## 4. Forcing functions applied

- **Constitutional tests**: 2 new (`no_llm_calls_in_skills_module`, `core_does_not_import_skills`) added in P1.3-3; both green. All 16 prior constitutional tests remain green per the 454-test count vs W-001-impl close's 379.
- **6-category test-coverage standard**: §1 (cross-module integration) covered in `test_integration.py::test_full_happy_path` with sentinel; §3 (cleanup) covered by `Path.read_text()` (context-managed) + the no-leak guarantee implicit in the loader's `for md_path in sorted(...)` iteration; §4 (exception payloads) covered — `SkillError` carries `path` + `field` and tests assert both; §5 (boundary multi-position) covered by star-mixing rejection tests at multiple positions; §6 (schema invariants) covered exhaustively in `test_schema.py` (37 tests). §2 (concurrency) explicitly N/A per `loader.py` and `decision.py` module docstrings.
- **5-surface scan**: P1.3-7 commit body enumerates each of the 5 surfaces with concrete file paths + RC-1 pre-edit grep result per surface. Surface 5 (handoff §5.3) updated; chat-history pseudocode intentionally not updated (rationale recorded in commit body).
- **Tracking table**: every impl commit body leads with a single-row table; P1.3-7 carries the 7-row composite.
- **Workflow state machine**: state-file transitions tracked. cycle=2 carried forward from override (see observation #2 below).

## 5. Senior observations (🟢 — not blocking; surfaced for R0-A awareness)

| # | Severity | File:line | What | Recommended action |
|---|---|---|---|---|
| 1 | 🟢 | `src/orchestrator/skills/loader.py:109-117` | Duplicate-id detection re-scans `directory.rglob("*.md")` to locate the "existing" file when a duplicate is hit — O(N²) on a duplicate. Tracking the `(id → first_path)` pair in a parallel dict during the main iteration would make this O(N). Not a correctness issue (the iteration is `sorted`, so "existing" deterministically resolves to the alphabetically-first match); pure perf and cleanliness. | Watch only. Worth a one-line refactor (`paths_by_id: dict[str, Path] = {}`) if a future commit touches this file; not worth a dedicated fix. |
| 2 | 🟢 | `.workflow/P1.3.yaml` `cycle: 2` | Cycle counter incremented to 2 due to architect-partner's `cfbf087` override into `awaiting_junior_impl`. Per `record_override`, **any** override `to_state == AWAITING_JUNIOR_IMPL` increments cycle — not just rework cycles. Architect's initial override here (to bypass ADR-Accept detection failure, RC-11) tripped this. Cycle is now misleading: it suggests "this is rework round 2" when it's actually "this is round 1, but reached via override." | Surfaced as RC-11-area observation in P1.3-7 commit body. W-001-impl close-out or first P1.4 retro evaluates whether `record_override` should distinguish "force-advance to junior_impl from architect_decision (rework)" from "force-advance from any other state (administrative)". Not blocking this review. |
| 3 | 🟢 | `src/orchestrator/workflow/cli.py` `_has_commit_since` (referenced in P1.3-7 commit body) | Workflow harness `_has_commit_since` strips timezone from a UTC `datetime` before passing to `git --after`, causing git to interpret the timestamp as local time. P1.3-7 used direct `write_state` (per W-001-impl-9 precedent) to avoid the bug; semantic transition is correct. | RC-11-area surfaced in P1.3-7 commit body. The harness needs a small fix; orthogonal to P1.3 close. Open as a separate task or batch with RC-11. |

## R0-A-on-plan-2 (filename-stem) cross-check

The plan said the load-time validator (not a Pydantic `@field_validator`) enforces the filename-stem-equals-id rule. Implementation matches: `loader.py:100-107` does the check after Pydantic construction, raising `SkillError` with `path` + `field="id"`. The `Skill` model itself has no validator for this — correct, because the Pydantic layer has no access to the file path. Recorded in ADR-009 Decision 8 narrative; respected here.

## Cross-checks

- [x] Implementation matches the plan (no silent scope change) — all 15 touched files map to plan tasks; no extras.
- [x] All 5 doc surfaces touched per Q3 — explicit per-surface report in P1.3-7 commit body with RC-1 pre-edit grep per surface.
- [x] No LLM imports in `src/orchestrator/skills/` (ADR-009 Decision 7 + Principle 3.1) — `test_constitution_no_llm_calls_in_skills_module` green.
- [x] `core` does not import `skills` — `test_constitution_core_does_not_import_skills` green.
- [x] CI gates pass: `ruff check` clean / `ruff format --check` clean / `mypy --strict src tests` clean across 75 source files / `pytest` 454 tests green.

## Verdict summary

P1.3 impl is **clean**. Every plan acceptance bullet maps to a verifiable element of the diff; all five architect-locked R0-A-on-plan items (1(a)/2/3/4/5) honored exactly; all six senior push-backs from plan §5 implemented as specified; constitutional tests for the new module load-bearing; 5-surface scan executed with RC-1 sub-rule applied per surface in the landing commit body. The three 🟢 observations are cosmetic / future-cleanup / harness-bug-area — none blocking. The architect-partner's override path (cfbf087) is a documented use of ADR-008 Decision 10's force-advance mechanism, not a process anomaly.

State machine auto-advance expectation: with this review's frontmatter `verdict: clean`, the next `workflow advance` invocation should fire `awaiting_senior_plan_vs_impl → awaiting_R0_A` per ADR-008 Decision 1 auto-trigger row. (Note: if the `_has_commit_since` timezone bug in observation #3 prevents auto-advance, direct `write_state` is the W-001-impl-9 precedent fallback.)

Recommended next step: architect-partner dispatches R0-A on this branch.
