# P1.2-C3 R0-A review

| Field | Value |
|---|---|
| Round | R0 (first external review post-impl) |
| Reviewer | A (architect-partner Claude session) |
| Family | Claude (Opus 4.7) — same family as junior (Sonnet 4.6) and senior plan-vs-impl |
| Cross-family R0-B | **not dispatched** (architect decision; second instance after P1.2-C2 freeze — see RC-2 evidence trail) |
| Lens | Doc-spec drift / vocabulary / narrative-vs-code consistency + impl-level edge cases (R0 specialty per P1.1 retro §4 + previous dispatch precedent on da65165) |
| Commits in scope | `57b0b33` (impl) + `aee8302` (senior plan-vs-impl) + `60acc04` (Y1 fix) |
| Gates | ruff ✓ / mypy --strict ✓ / pytest 274 ✓ |

## Findings

| # | 🚦 | File : line | What's wrong | What should be |
|---|----|-------------|--------------|----------------|
| R0-A-1 | 🟡 | `src/orchestrator/autonomy/scoring.py:177` (`decide_tier` `eff_auto` computation) + `docs/decisions/ADR-005-…md` §5(c) | **Asymmetric floor**: `effective_threshold_confirm` has `max(0, …)` clamp (ADR-005 §5(c)); `effective_threshold_auto` has **no floor and no validator**. When `user_intent_modifier ≥ threshold_auto`, `eff_auto ≤ 0` and *every* score in `[0, 10]` lands on `AUTO_EXECUTE` — the symmetric counterpart of the HARD_CONFIRM dead branch the ADR explicitly accepts. The Pydantic cross-field validator only enforces `threshold_auto > threshold_confirm`; `Field` constraints allow `threshold_auto=4, user_intent_modifier=10` (eff_auto = -6, AUTO-always). With current placeholders this can't trigger (modifier always < auto), but **no schema layer prevents it.** Same shape as the bug ADR-005 §5(c) discusses for the confirm side — but the auto side isn't even named. | Architect's call between three options: **(a)** Add one sentence to ADR-005 §5(c) explicitly noting `effective_threshold_auto` has no floor *by design* (Hard Guards is the destructive defense; AUTO over-reach by design parallels HARD-unreachable by design); **(b)** Add a Pydantic cross-field validator on `AgentAutonomyThresholds` + `ThresholdConfig` enforcing `user_intent_modifier ≤ threshold_auto - 1` so eff_auto can't go non-positive; **(c)** Both (a) + (b). Architect-partner lean: **(a)** for narrative completeness + **defer (b)** unless P1.5 dogfooding surfaces a real misconfiguration. The ADR-level coverage gap is the more immediate concern. |
| R0-A-2 | 🟢 | `tests/autonomy/test_constitution.py:89-92` (`combinations` list) | `test_constitution_hard_confirm_unreachable_when_effective_confirm_clamped` uses two tuples — `(auto=8, confirm=2, modifier=5)` and `(auto=7, confirm=3, modifier=3)`. Both have `eff_auto > 0`. The combined "eff_auto AND eff_confirm both clamped" case (e.g., `auto=4, confirm=3, modifier=7` → eff_auto=-3, eff_confirm=0) is not exercised. If R0-A-1 is resolved as (a) (doc-only), the constitutional test name is accurate. If (b) (validator), this test would need a corresponding "validator rejects modifier ≥ auto" boundary case. | Conditional on R0-A-1 resolution. If (a): no change. If (b): add `test_constitution_modifier_cannot_force_eff_auto_non_positive` (or merge into the existing test). |
| R0-A-3 | 🟢 | `handoff.md` §15 (impl branch) vs `handoff.md` §15 (main `b59b35d`) | **Merge conflict at PR time**. Impl branch's `57b0b33` added ADR-006 to §15 (per Q3 5-surface scan). Main's `b59b35d` also added ADR-006 to §15 in a different commit. When impl branch PRs to main, git will see two parallel additions to the same section — likely a textual conflict (wording / surrounding context differs). Not a code bug; PR-time concern. | Pre-resolve: before PR-to-main, junior (or architect) does a rebase/merge dry-run, manually consolidates §15 to a single coherent entry. Document the consolidation in the merge commit. Alternatively, defer to PR review and resolve inline — but flagging now so it doesn't surprise. |
| R0-A-4 | 🟢 | `tests/autonomy/test_scoring.py` `TestSchemaInvariants` | `DecisionTrace.tier: AutonomyTier` (StrEnum, not Literal). The §6 standard says "One test per Literal field, with a non-allowed value" — strict reading: StrEnum ≠ Literal. Semantically equivalent (closed set of valid values), Pydantic enforces both. Test class doesn't exercise "invalid tier value" at construction. Defensible under literal-strict reading of §6; missing under semantic reading. Watch only. | If architect wants symmetric coverage with the `rule` Literal test, add one test `test_decision_trace_invalid_tier_raises` constructing with `tier="bogus_tier"` and asserting `ValidationError`. Cheap; ties off the symmetry question. Otherwise document in test class docstring why tier is excluded. |
| R0-A-5 | 🟢 | `src/orchestrator/autonomy/scoring.py:102` (`DecisionTrace.reversibility_score: int`) | Unconstrained `int` field. The only call site (`decide_tier`) gets the value from `score()` which is bounded `[0, 10]` by `ToolMeta.reversibility = Field(ge=0, le=10)`. Defensive bound at `DecisionTrace` level would catch any future caller bypassing `score()` and constructing a trace with `reversibility_score=999`. Per "Run > polish", optional. | If adopted: change to `reversibility_score: int = Field(ge=0, le=10)`. If not: docstring note "value mirrors `ToolMeta.reversibility` bounds; callers must respect upstream invariant". Architect's call. |

**🔴 None.** Impl satisfies all C3 plan acceptance criteria, ADR-005 / ADR-006 / brief decisions; gates green; freeze signatures preserved.

## Cross-checks performed (no findings)

- **Constitutional tests**: `test_constitution_no_llm_calls_in_autonomy_module` still passes (no LLM imports in `autonomy/`). `test_constitution_autonomy_decision_event_carries_trace` extended with rule-Literal parity assertion per brief decision 4 / R0-A item #4 — extension is one-line, well-placed, fails loudly with named-file fix instruction. ✓
- **Layering**: `orchestrator.autonomy` does not import from `orchestrator.llm`. `orchestrator.core` does not import from `orchestrator.autonomy`. `orchestrator.llm.config_loader` imports `ToolMeta` from `orchestrator.autonomy.scoring` (pre-existing, senior watch item from C2 review). ✓
- **Freeze-vs-impl drift**: `scoring.py` function signatures (`score`, `decide_tier`, `gate`) byte-identical to C2 freeze `da65165` per senior plan-vs-impl audit; partner re-verified by reading signature lines. ✓
- **ADR-005 §5(c) revision wording**: verbatim per brief decision 2 (no paraphrase). ✓
- **ADR-005 References**: ADR-006 cross-link added (planned C3-10 item) — symmetric to ADR-006's reference to ADR-005. ✓
- **`test_git_push_with_user_intent_lands_on_countdown_not_hard`**: name preserved per architect override on senior push-back #6. Test docstring cites `config/tools.yaml.example:49` for `git_push`. Confirmed correct: line 49 is indeed `git_push: reversibility: 1` (senior's earlier "git_push not in tools.yaml.example" claim was factually wrong; architect-partner verified during R0-A). ✓
- **`test-coverage-standard.md` §6 P1.1-example field**: updated to point at `tests/autonomy/test_scoring.py::TestSchemaInvariants` as P1.2-R1 canonical example; the "ToolMeta + ThresholdConfig queued for C4" caveat preserved per architect ack. ✓
- **Brief amendment wording (`8b727c0` "one constitutional + one boundary, not two constitutional")**: respected — C3-7 is constitutional, C3-6's `test_git_push_…` is boundary, file placements match. ✓
- **Junior's commit body Q3 5-surface scan**: each surface itemized; pre-edit grep sub-rule (P1.2-RC-1 propose) implicitly applied — §15 ADR-006 row is additive (no pre-edit values to remove), so the sub-rule does not fire here. ✓
- **Y1 fix (`60acc04`)**: single-line docstring sync, exactly as routed. Architect-partner verified diff = +1/-1 in `test_scoring.py`, gates unchanged at 274. ✓

## Positives worth surfacing (junior + senior caught beyond plan minimums)

- **`test_decide_tier_tool_id_does_not_affect_tier_selection`** — pins the docstring's "trace-only" claim about `tool_id` as an executable invariant. Not requested in brief or plan; junior added prophylactically. Useful for future refactors.
- **`test_decide_tier_modifier_clamps_effective_confirm_to_zero`** asserts BOTH `tier` and `trace.threshold_confirm_effective == 0`. The second assertion catches the case where the if/elif gives the right tier but the trace doesn't record the clamp — silent observability bug.
- **`UnknownToolError` message format**: includes `repr(tool_id)` so empty-string and whitespace-only tool_ids are visible at log inspection time. Cheap, surprisingly useful.
- **ADR-005 References section** gained an ADR-006 cross-link (symmetric to ADR-006 referencing ADR-005). Architect-partner had flagged the reverse direction (ADR-006 → senior plan circular) as a minor stylistic during ADR-006 review; this symmetric direction is fine because ADR-005 was previously accepted and ADR-006 is now accepted — both are decision artifacts, not in-flight planning.

## Recommended next steps

1. **R0-A-1 resolution**: architect picks (a) / (b) / (c). If (a), one-line ADR-005 §5(c) edit by architect-partner (architect-scope) or junior (impl-scope; same kind of fix as Y1).
2. **R0-A-3 merge conflict**: pre-resolve before PR-to-main; architect-partner can offer a manual consolidation of §15.
3. **R0-A-2 / R0-A-4 / R0-A-5**: 🟢 watch items. Bundle into C4 or close-out if any decided to fix; otherwise document.
4. **R0-B (cross-family)**: skipped this round per architect decision. Second consecutive skip on P1.2 (C2 + C3); RC-2 evidence trail updated.

## Distance test

Impl + Y1 fix + this R0-A all 2026-05-20. Same-day land for *external review* is acceptable (it's review, not architectural inscribing). Architect's land-vs-defer decision for the impl PR itself should respect the C2-freeze-was-also-today pattern — likely tomorrow earliest for PR-to-main, especially if R0-A-1 routes to (a)/(b)/(c) and needs another short cycle.

## Status

**Verdict: 🟡 — ready for architect review, one design-level finding (R0-A-1) blocks clean land until architect picks a resolution.** Code is production-quality on every other axis; R0-A-1 is a real edge-case the ADR doesn't cover symmetrically. The four 🟢 items are accept-or-defer-as-watch.

Architect's call on R0-A-1 → land path.
