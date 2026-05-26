# W-001-impl R0-A on plan (pre-impl)

| Field | Value |
|---|---|
| Round | R0-A on plan (architect-dispatched gated transition; first instance of this review type per RC-9) |
| Reviewer | A (architect-partner Claude session) |
| Family | Claude (Opus 4.7) — same as senior (Sonnet 4.6) |
| Cross-family R0-B | not dispatched (default skip; RC-2 evidence trail) |
| Lens | Plan-design review (atomic task coverage / acceptance-criteria completeness / push-back substance / cross-cutting consistency with ADR-008) |
| Commits in scope | `d8e9ab6` (senior W-001-impl full plan) on main |
| Gates | N/A — plan-only artifact; no code yet |

## Findings on the plan

| # | 🚦 | Where | What | What should be |
|---|----|-------|------|----------------|
| R0-A-on-plan-1 | 🟡 | impl-7 acceptance + impl-9 acceptance + §5 push-back #3 | **Impl-7 initial state introduces an audit-trail lie during the impl-7→impl-9 window.** Senior chose `awaiting_senior_plan_vs_impl` for the bootstrap state file at impl-7 land. Rationale: "future-truthful at impl-9 land" — by the time junior finishes pushing impl-9, the task IS waiting on senior plan-vs-impl. But at impl-7 commit, junior is **still implementing** (impl-8 doc updates + impl-9 landing commit not yet pushed). The state file claims a state that is FALSE for the duration of two more commits. A session walking in during that window reads "awaiting_senior_plan_vs_impl" and would (correctly per state file, incorrectly per reality) try to start writing plan-vs-impl. The Decision-5 invariant *"state file IS the truth, not chat history or session memory"* (ADR-008 Decisions 5/9) is undermined: here the state file is **future-truthful** rather than **current-truthful**, which is a different category. | Truthful alternative: impl-7 sets `state: awaiting_junior_impl` (junior is in the middle of pushing impl-8, impl-9). impl-9 advances to `awaiting_senior_plan_vs_impl` as part of the landing commit's state-file edit. Cost: one additional state-file write across the PR (currently zero state-file edits between impl-7 and impl-9; alternative has one). Benefit: state file never lies; git log of the state file shows two transitions matching real task progress; sets a precedent for "state file = current truth" that future bootstraps inherit. Architect's call between (a) accept senior's choice (operationally OK, audit-trail lies for ~2 commits, fewer writes) and (b) the truthful alternative. Architect-partner lean: **(b)** — the lie window is small but the precedent matters, especially for the FIRST .workflow/ file ever written. |
| R0-A-on-plan-2 | 🟢 | impl-6 acceptance — review filename filter | Hard-coded list `(plan-vs-impl.md, R0-A.md, R0-B.md, R1-A.md, R1-B.md, ...)`. The trailing `...` suggests extensibility but the filter is closed at impl time. Future review types (R2-*, R3-*, R0-A-on-plan.md itself per RC-9) require code change. impl-6 should at least document the extension pattern (e.g., "filter is `re.compile(r'^(plan-vs-impl|R\d+-[AB])(-on-plan)?\.md$')'`" or similar). | Senior's choice OK for now; flag for W-001 close: revisit whether to canonicalize a regex / pattern-based filter that's additive without code change. The R0-A-on-plan.md path (this file) is the immediate first extension case; impl-6 should include it in the filter or explicitly exclude it (since it's a pre-impl artifact, not consumed by state machine). |
| R0-A-on-plan-3 | 🟢 | impl-4 acceptance — `verify-workspace --strict` | `--strict` mode is defined (exit 1 on divergence) but never described as to **when it's used**. CI? Manual operator gate before a critical command? Architect override? The non-strict mode (warning + exit 0) is clearly the SessionStart hook's mode. The strict mode is dangling. | impl-4 docstring (or `_template-review.md` / `session-start-hook.md`) should give one sentence: "Use `--strict` when you want divergence to be a hard error — e.g., before opening a PR or during a CI gate." If no clear use case exists today, drop `--strict` and add later if/when needed (Run > polish). |
| R0-A-on-plan-4 | 🟢 | impl-5 acceptance — hook behavior on CLI hard-error | "Exit code does NOT block session startup" is stated for the warning case. But if `workflow status` itself errors (malformed state file, missing `.workflow/` directory, permission denied), is that also non-blocking? Implicit: yes (session-start is informational). But not explicit. | impl-5 acceptance should add one line: "Hook errors (CLI exits non-zero) are also non-blocking; the hook output is informational. Session continues regardless." Tightens the contract; no behavior change. |
| R0-A-on-plan-5 | 🟢 | impl-9 acceptance — state-file edit when no transition fires | Senior recommends `state: awaiting_senior_plan_vs_impl` remains (no transition between impl-7 and impl-9). But the acceptance criteria say "advance `state` from `awaiting_senior_plan_vs_impl` (impl-7's initial value) to whatever the operational reality is at the moment of impl-9 commit." If reality IS `awaiting_senior_plan_vs_impl` (senior's reading), there's nothing to advance — impl-9 should not touch the state file. The acceptance prose ambiguously suggests touching it (`advance state from X to Y`). | impl-9 acceptance should be explicit: "If no transition fires (state-file content unchanged), impl-9 does NOT touch `.workflow/W-001-impl.yaml` — the commit body explicitly records 'no state transition: junior task complete; awaiting senior plan-vs-impl, same as impl-7's bootstrap value.' If R0-A-on-plan-1 resolves to the truthful alternative (impl-7 = `awaiting_junior_impl`), impl-9 DOES touch the state file to advance." This makes the conditional explicit. |

**🔴 None.** Plan is implementer-ready modulo R0-A-on-plan-1 (architect-decision pending) and the four 🟢 watch items.

## Senior's §5 push-backs — architect-partner judgements

| Senior push-back | Architect-partner read |
|---|---|
| **§5 #1**: Side-channel filtering at impl-6 (artifact-snapshot), not impl-2 (`parse_verdict`). Senior reasons: pure parser shouldn't silent no-op. | ✅ **Accept.** Boundary-of-responsibility is correct: parsers raise on garbage; the layer that decides what to feed the parser filters. Pure-function discipline preserved. |
| **§5 #2**: `cycle >= 4` as stderr warning, not `WorkflowError` raise (R0-A-4 routing). Senior reasons: architect-judgement-driven per Decision 11; harness surfaces, doesn't block. | ✅ **Accept.** Consistent with the broader "harness is mechanism, architect is judgement" framing (ADR-008 Decision 10 override pattern). Block-via-harness would relocate architect's responsibility. |
| **§5 #3**: impl-7 initial state = `awaiting_senior_plan_vs_impl`. Senior reasons: future-truthful at end-of-impl. | ⚠️ **Challenged** — see R0-A-on-plan-1 above. Operationally OK; architect-partner leans toward the truthful alternative (`awaiting_junior_impl` at impl-7, advance at impl-9). |
| **§5 #4**: No retroactive `.workflow/W-001.yaml` for the parent task. Senior reasons: Decision 12 symmetry. | ✅ **Accept.** Decision 12 closed P1.x by definition does not get retroactive state files; W-001 (closed via `819d8f5`) sits in the same category. Manufacturing retroactive audit data is exactly what Decision 12 rejects. |

3 of 4 senior push-backs accepted; 1 challenged for architect resolution.

## Cross-checks performed (no findings)

- **9 atomic tasks vs ADR-008 13 decisions coverage matrix**: every Decision is exercised by at least one impl-* task. Decisions 1+7+8+11 → impl-2; 4+5+6 → impl-1; 9 → impl-5; 10 → impl-2+impl-4 (`workflow override`); 12 → impl-7+impl-8; 13 → impl-1 schema hook (`requires_cross_family_review: bool`). ✓
- **Cross-package import direction**: impl-2 introduces no import from `orchestrator.autonomy` or `orchestrator.llm`. impl-4 CLI invokes only within `orchestrator.workflow`. `test_constitution_core_does_not_import_autonomy` (from W-001-impl Y1 precedent) is unaffected; the new `test_constitution_no_llm_calls_in_workflow_module` parallels it. ✓
- **Constitutional test additions**: 1 new test (`test_constitution_no_llm_calls_in_workflow_module`). Plus the 15 existing remain green. ✓
- **6-category coverage standard mapping**: §1 (impl-6 e2e), §2 (N/A documented), §3 (impl-2 subprocess + impl-6 write-and-rename), §4 (impl-2 WorkflowError, impl-4 CLI), §5 (impl-2 verdict boundary, impl-1 actor Literal), §6 (impl-1 + impl-2 schema). Complete. ✓
- **RC-1 (pre-edit grep sub-rule) graduation in impl-8**: precise wording matches P1.2 retro RC-1 proposal. impl-8 is also the first commit to APPLY the sub-rule to its own edits — both codifies and exercises in one commit. ✓
- **RC-7 (stale-workspace-as-truth) mitigation in impl-4 `verify-workspace`**: directly implements the divergence check proposed in W-001-candidates RC-7. CLI docstring must cite RC-7 link. ✓
- **R0-A watch items routing**: R0-A-4 → impl-2 `record_override` stderr warning ✓; R0-A-5 → impl-3 README updates ✓; R0-A-8 → impl-2 `next_state` docstring ✓. All three carried forward correctly. ✓
- **Stub self-discoveries routing**: §5.1 → impl-1 `TaskState.requires_cross_family_review: bool` field ✓; §5.2 → impl-6 filter (senior push-back #1) ✓; §5.3 → impl-2 docstring ✓; §5.4 → impl-2 `evaluate_merge_clean` reads `origin/main` only ✓. All four carried forward. ✓
- **Length budget**: 368 lines = ~3000 words excluding code blocks. Senior-planner.md calibration range 1800-2600 for typical plans; this is over but justified (9 tasks vs typical 6-7, includes full `schema.py` code block). Acceptable. ✓
- **Distance test status (impl-1 floor)**: 2026-05-22 floor honored; today 2026-05-26 = +4 days past floor. ✓

## Architect-decision dependency

Before junior dispatch, architect picks resolution for R0-A-on-plan-1:

- **(a)** Accept senior's choice — impl-7 sets `awaiting_senior_plan_vs_impl`, no state-file touch in impl-9. Audit-trail lies for ~2 commits but operationally fine; fewer writes.
- **(b)** Truthful alternative — impl-7 sets `awaiting_junior_impl`, impl-9 advances to `awaiting_senior_plan_vs_impl`. State file always reflects reality; one extra write; better precedent for the first `.workflow/` file ever written.

Architect-partner lean: **(b)** — the precedent matters for the bootstrap; the cost is small.

🟢 items (R0-A-on-plan-2 through -5) are doc-clarity additions senior can fold in during a single revision pass, or defer to W-001-impl-close as watch items. None block.

## Verdict

**🟡 — plan is implementer-ready pending R0-A-on-plan-1 architect resolution.** Senior's quality is high; the 4 senior-self-flagged push-backs are well-reasoned (3 accept, 1 challenge above). Cross-checks all pass. Length is justified by scope.

Once R0-A-on-plan-1 is resolved:
- (a) → senior pushes no plan revisions; junior dispatches immediately
- (b) → senior revises impl-7 + impl-9 acceptance (small edit); architect-partner light re-review (small-edits-only pass); then junior dispatches

🟢 items can fold into senior's revision pass (if (b) chosen) or defer to W-001-impl-close as watch items.
