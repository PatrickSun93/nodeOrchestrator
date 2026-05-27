---
task_id: W-002
round: plan-vs-impl
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 4
---

# Review: W-002 — plan-vs-impl

**Reviewer:** senior planner (Claude Opus 4.7, 1M context)
**Date:** 2026-05-27
**Artifacts reviewed:** 5 impl commits on `claude/W-002-impl` (now merged to main via PR #10): `8b9e1d8` (W-002-1), `156c670` (W-002-2), `fb965ce` (W-002-2b), `7cea117` (W-002-3), `f7b14d2` (W-002-4). 17 files touched, 2540 insertions / 75 deletions.
**Plan:** `docs/process/senior-plans/W-002.md` (revised version absorbing architect-routing `5ae24d4`).
**Cycle context:** `.workflow/W-002.yaml` shows `cycle: 2` — the increment came from the architect-partner override `236dac1` (`awaiting_architect_accept → awaiting_junior_impl`) BEFORE the W-002-2 cycle-counter fix landed. **This is the first plan-vs-impl pass on W-002.** The cycle-2 value is the durable audit evidence of the bug W-002-2 fixed (same documentation-as-evidence treatment as `P1.3.yaml`'s `cycle: 2`).

---

## 1. Coverage of plan acceptance criteria

Every plan-pinned acceptance bullet was checked against the diff. All 5 W-002-* tasks satisfy their criteria.

| Task | Plan-mandated acceptance | Implemented as | Verdict |
|---|---|---|---|
| W-002-1 | `_read_adr_status` rewritten to parse plan frontmatter + glob-resolve ADR; `senior-plans/README.md` carries the convention with one-direction cross-link to ADR-008 (Y1→β honored — ADR-008 body untouched); multi-ADR list raises; multi-glob raises; backward-compat fallback for legacy no-frontmatter plans; ≥6 unit tests + 1 integration test (source ≠ sink: task_id `SYNTH-002` ≠ ADR filename `ADR-099-synth.md`) | `cli.py:_read_adr_status` rewritten; `_read_plan_frontmatter` extracted to `workflow/io.py` per the >20-line criterion (12 tests across paths in `test_cli.py`; `test_e2e_path_beta_task_with_adr_advances` in `test_integration.py`); multi-ADR-list-raise + multi-glob-match-raise both implemented; legacy fallback present; `senior-plans/README.md` gains the post-W-002 frontmatter contract section with cross-link to ADR-008 (one-direction); **ADR-008 body untouched per Y1→β** | ✓ Done |
| W-002-2 | `record_override` gates cycle increment on BOTH `from_state == AWAITING_ARCHITECT_DECISION` AND `to_state == AWAITING_JUNIOR_IMPL`; cycle≥4 warning fires only on real rework; P1.3-case regression test + defense-in-depth from=BRIEF test + warning-on-rework-vs-non-rework test | `transitions.py:record_override` condition `if from_state == ARCH_DECISION and to_state == JUNIOR_IMPL: new_cycle = state.cycle + 1` — exact match to plan; warning emission moved inside same branch (warning only on real rework); `test_record_override_to_junior_impl_from_accept_does_not_increment_cycle`, `..._from_brief_...`, `..._cycle_warning_fires_only_on_rework_reaching_threshold` all present | ✓ Done |
| W-002-2b | `next_state` discriminates `AWAITING_SENIOR_PLAN → ?` on plan frontmatter (no `adr` key → skip accept gate; `adr` key present → route through accept; legacy no-frontmatter → route through accept); shared parser via `workflow/io.py` (layering preserved); 3 new tests | `ArtifactSnapshot` gains `plan_has_adr: bool | None` field (None=legacy, False=no-`adr`-key, True=`adr`-key-present); `build_artifact_snapshot` reads the plan via `_read_plan_frontmatter` from `workflow/io.py` and sets the tri-state; `next_state` discriminator at the `AWAITING_SENIOR_PLAN → ?` branch checks `artifacts.plan_has_adr is False`; 3 tests cover all three cases (no-adr-key, adr-key-present, legacy-no-frontmatter) | ✓ Done — with senior-noted architectural improvement (observation #2 below) |
| W-002-3 | Graceful skip of non-skill `.md` files via typed sentinel `_NotASkillFile`; module-level `logger = logging.getLogger(__name__)`; `logger.debug` on skip; unclosed fence continues to raise; schema validation failure continues to raise; ≥3 new tests | `loader.py` declares `class _NotASkillFile`, module-level `_NOT_A_SKILL` singleton, `logger = logging.getLogger(__name__)`; `_parse_frontmatter` signature returns `tuple[dict[str, Any] \| _NotASkillFile, str]`; `load_skills` checks `isinstance(..., _NotASkillFile)` and emits `logger.debug("skipping non-skill file: %s", md_path)`; tests for missing-frontmatter-skipped, scalar-yaml-skipped, debug-log-emitted, schema-validation-failure-still-raises (the regression test); unclosed-fence still raises per existing test | ✓ Done — sentinel design matches plan verbatim |
| W-002-4 | 5-row tracking table; 5-surface scan with RC-1 pre-edit grep per surface (§3 ADRs entry "none touched in W-002" per Y1→β); deterministic state advance to `awaiting_senior_plan_vs_impl` (no override entry); gates clean | f7b14d2 commit body carries 5-row composite tracking table; 5-surface scan report enumerates each surface (§1 src — 4 files; §2 yaml — none; §3 ADRs — "none touched in W-002" per Y1→β; §4 architecture-docs — none; §5 narrative — senior-plans/README.md updated); `.workflow/W-002.yaml` advanced via direct write (overriding the timezone-bug fallback per W-001-impl-9 / P1.3-7 precedent); RC-1 pre-edit grep applied per surface | ✓ Done |

## 2. Architect-routing items — verification

Both Y1 and Y2 routings (β leans, both applied per architect ack):

- **Y1 → β (ADR-008 stays untouched)**: confirmed. `git diff 5ae24d4..f7b14d2 -- docs/decisions/ADR-008-workflow-state-machine.md` returns no changes. The plan-frontmatter convention lives in `docs/process/senior-plans/README.md` with one-direction cross-link to ADR-008 Decision 1. "ADRs as audit snapshots" semantic preserved; sets the project's first precedent for post-Accept ADR amendment discipline.
- **Y2 → β (W-002-2b in scope)**: confirmed. New atomic commit `fb965ce` (`W-002-2b: next_state no-ADR routing fix`) — exactly the routing-driven scope addition. The fix closes the RC-11 pattern in the same cycle the bug was caught. With this fix landed on main, future no-ADR tasks (W-003+) take the new path and need no architect override.

## 3. Senior's plan §5 push-backs — outcomes

All 6 push-backs from the plan §5 absorbed correctly:

- #1 path β (no ADR for W-002) — held: no ADR-012 drafted; W-002 lands as code-only cycle.
- #2 `verify-workspace` divergence detection deferred to W-003 — held: no scope creep.
- #3 no-ADR routing fix originally "defer + override" then revised to "INCLUDED via W-002-2b" per architect-routing Y2 — held with reflection paragraph in plan.
- #4 multi-ADR-per-task deferred to W-003 — held: `adr` accepts single string only; list raises informatively.
- #5 CI-enforce frontmatter convention deferred to W-003 — held.
- #6 meta-discovery on path-β no-ADR override — informational; absorbed into W-002-2b scope.

## 4. Forcing functions applied

- **Constitutional tests**: all 18 pre-W-002 tests remain green. W-002 introduces no new module; no new layering edge; no new constitutional test expected (correct). `test_constitution_no_llm_calls_in_workflow_module` + `..._skills_module` exercised throughout.
- **6-category test-coverage standard**:
  - §1 cross-module: W-002-1 `test_e2e_path_beta_task_with_adr_advances` with source≠sink (task_id "SYNTH-002" ≠ ADR file "ADR-099-synth.md"). ✓
  - §2 concurrency: N/A correctly stated; no new concurrency surface.
  - §3 cleanup: W-002-1's `_read_plan_frontmatter` uses `Path.read_text()` (context-managed under the hood); no new subprocess.
  - §4 exception payloads: W-002-1 multi-ADR + multi-glob raises populate `path`. W-002-3 SkillError payload unchanged.
  - §5 boundary validators: W-002-1 multi-ADR list rejection tested with 1-element AND 2-element list positions.
  - §6 schema invariants: no new Pydantic model (path-β avoided schema extension); existing schema tests untouched.
- **5-surface scan**: W-002-4 commit body per-surface report with RC-1 pre-edit grep result per surface. ✓
- **Tracking table**: every commit body has one; W-002-4 has 5-row composite.

## 5. Senior observations (🟢 — not blocking; surfaced for R0-A awareness)

| # | Severity | Location | What | Recommended action |
|---|---|---|---|---|
| 1 | 🟢 | `.workflow/W-002.yaml` `cycle: 2` | Final state-file carries `cycle: 2` from the architect override that incremented it before W-002-2 fix landed (same shape as `P1.3.yaml`'s `cycle: 2` documented in P1.3 retro §11 as "evidence of the bug"). The plan explicitly puts retroactive cycle-correction out of scope for the same reason. No action; preserving as audit evidence is correct. | Watch only. W-003+ no-ADR tasks will not have this issue per W-002-2b. |
| 2 | 🟢 | `transitions.py` `ArtifactSnapshot.plan_has_adr: bool \| None` field (W-002-2b architectural choice beyond literal plan) | Plan said "`next_state` consults plan frontmatter at the `awaiting_senior_plan → ?` transition." Literal reading: `next_state` reads the plan directly. Implementation: `ArtifactSnapshot` gains a `plan_has_adr` tri-state field; `build_artifact_snapshot` reads the plan; `next_state` stays a pure function consuming the snapshot. **This is architecturally cleaner** — preserves the ADR-008 D2 "transitions are pure functions of `(current_state, artifacts, gates)`" invariant. Junior chose the better shape than the literal plan reading would have produced. | Acknowledge as a positive deviation. The `next_state`-stays-pure invariant is now stronger than it would have been under literal plan reading. |
| 3 | 🟢 | `_NotASkillFile` sentinel pattern in loader (W-002-3) | Plan §5 acceptance preferred typed sentinel over `None`; impl matches verbatim (`class _NotASkillFile: pass` + module-level singleton). Distinction matters: `None`-as-sentinel collides with "valid empty dict" semantically, even if Pydantic rejects empty dict downstream. The typed sentinel makes the loader's intent unambiguous at the type-checker level. | None — match-to-plan is the finding. |
| 4 | 🟢 | W-002-1 parser placement chose `workflow/io.py` extraction over inline-in-`cli.py` | Plan said "small inline parser at `cli.py` boundary is fine; if it grows past ~20 lines, extract to `workflow/io.py` as `_read_plan_frontmatter(path) -> dict[str, Any] \| None`." Junior extracted to `workflow/io.py` immediately. Subsequent W-002-2b consumes the parser without circular-import risk (`transitions.py → workflow/io.py` is within-module; `transitions.py → cli.py` would have been awkward). The early extraction made W-002-2b's layering trivially clean. | None — execution-order foresight by junior. |

## Cross-checks

- [x] Implementation matches the plan (no silent scope change) — all 17 touched files map to plan tasks.
- [x] All 5 doc surfaces touched per Q3 — explicit per-surface report in W-002-4 commit body with RC-1 pre-edit grep per surface.
- [x] No LLM imports in `src/orchestrator/workflow/` or `src/orchestrator/skills/` — both constitutional tests green.
- [x] ADR-008 body untouched (Y1→β) — verified via `git diff`.
- [x] CI gates pass: `ruff check` clean / `ruff format --check` clean / `mypy --strict src tests` clean across 75 source files / `pytest` 472 tests green (+18 over P1.3-close baseline of 454).
- [x] W-002-2b layering: `transitions.py` imports parser from `workflow/io.py`, NOT from `cli.py`; no constitutional-test violation.

## Verdict summary

W-002 impl is **clean**. Every plan acceptance bullet maps to a verifiable element; both architect-routing items (Y1→β + Y2→β) honored exactly; all 6 senior push-backs from plan §5 implemented as specified; no new constitutional tests needed (correctly); the cycle-counter and no-ADR routing fixes both close their respective RC-11 sub-findings in the same cycle the bugs were caught. The four 🟢 observations are positive notes (audit-evidence preservation, architectural improvement, plan-faithful sentinel, foresightful parser placement) — none blocking, all confirmatory.

The state-machine RC-11 cluster is now structurally closed:
- W-002-1 fixes task→ADR mapping (sub-finding a).
- W-002-2 fixes the cycle-counter from-state gating (sub-finding b).
- W-002-2b fixes no-ADR task routing (the senior-discovered third bug surfaced during plan-writing).

State machine auto-trigger expectation: with this review's frontmatter `verdict: clean`, the next `workflow advance` invocation should fire `awaiting_senior_plan_vs_impl → awaiting_R0_A` per ADR-008 Decision 1. (Note: with W-002-1 + W-002-2 + W-002-2b all on main, the harness's transition + override semantics are now correct; this should be the first plan-vs-impl review where state advance Just Works without any manual override or timezone fallback.)

Recommended next step: architect-partner dispatches R0-A on this branch (or on main, since W-002 is already merged via PR #10).
