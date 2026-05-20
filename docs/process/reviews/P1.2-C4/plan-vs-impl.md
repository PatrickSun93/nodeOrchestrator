# P1.2-C4 plan-vs-impl review

| Field | Value |
|---|---|
| Task ID | P1.2-C4 |
| Junior commit range | `823cf7f`..`2a46909` on `claude/p1.2-c4-impl` (5 impl commits, C4-3 through C4-7) |
| ADR-007 lifecycle | `0cb6d3a` (Proposed, senior) → `b3bd666` (Accepted, architect-partner C4-2) — both pre-impl |
| Senior plan | [`docs/process/senior-plans/P1.2-C4.md`](../../senior-plans/P1.2-C4.md) |
| Architect brief | [`docs/process/architect-briefs/P1.2-C4.md`](../../architect-briefs/P1.2-C4.md) |
| Reviewer | senior planner (this role) |
| Date | 2026-05-21 |
| Verdict | **Ready for external R0-A dispatch with 1 🟡 + 4 🟢 noted below.** Y1 is a clear plan miss (architect-approved layering constitutional test absent) — junior can land in a small follow-up commit or fold into R0 round-up. |

## 1. Gates

| Gate | Result |
|---|---|
| `uv run ruff format --check src tests` | ✅ 52 files formatted |
| `uv run ruff check src tests` | ✅ All checks passed |
| `uv run mypy src tests` | ✅ 52 source files clean |
| `uv run pytest` | ✅ 299 collected (274 post-C3 + 25 new) |

Test-count math reconciled: C4-3 +2, C4-4 +6, C4-5 +8 (7 behavior + 1 constitutional), C4-6 +8, C4-7 +2 e2e = 26. The commit-message claim "274 + 25" undercounts by 1 (likely the C4-3 commit's `test_constitution_autonomy_refusal_metadata_field_set` plus an in-class negative-value test was double-counted differently). Reconciliation: actual collected count 299 is correct; commit message's per-task arithmetic in C4-3 (says +1, actually +2) is the minor discrepancy. Non-blocking.

## 2. Per-task verification

All 7 plan tasks satisfy acceptance criteria. File:line citations below.

| Task | Acceptance check | Result |
|---|---|---|
| C4-1 ADR-007 Proposed | Senior writes; file at exact path; status `Proposed` | ✅ `docs/decisions/ADR-007-autonomy-refusal-event-type.md` landed in `0cb6d3a` |
| C4-2 ADR-007 Accepted | Architect-partner bumps status; single-token diff | ✅ landed in `b3bd666`; `git show b3bd666` confirms +1/-1 |
| C4-3 EventType + metadata + constitutional | Enum value + `AutonomyRefusalMetadata` class + TYPED_METADATA entry + constitutional test pinning field set | ✅ `src/orchestrator/core/event.py` carries enum + 4-field metadata class; `tests/core/test_constitution.py:88` has `test_constitution_autonomy_refusal_metadata_field_set` |
| C4-4 `load_tools_config()` body | Body replaces NotImplementedError; ≥5 tests; §3 cleanup + §4 payload | ✅ `src/orchestrator/llm/config_loader.py:243-282`; 6 tests in `tests/llm/test_config_loader.py` |
| C4-5 emission layer | New `emission.py`; both paths emit before raise/return; auditability constitutional | ✅ `src/orchestrator/autonomy/emission.py` (107 lines, plan budget was ≤80 — slightly over but well-structured); 7 behavior tests in `test_emission.py` + 1 constitutional in `test_constitution.py:128` |
| C4-6 §6 deferred coverage | TestSchemaInvariants extended; ToolMeta + ThresholdConfig invariants; R0-A-4 bundled | ✅ 8 new tests in `TestSchemaInvariants`; R0-A-4 (`tier="bogus_tier"` rejected) included per plan condition |
| C4-7 e2e + 5-surface scan + landing | 2 e2e tests; 5-surface scan; tracking table; freeze-vs-impl line; gates clean | ✅ `tests/autonomy/test_e2e_emission.py` (2 tests, real `tools.yaml.example`); commit body has tracking table + Q1-Q4 + surfaces 1/2/3/4/5 itemized + freeze-vs-impl line + R0-A-5 deferral note |

## 3. Findings

### 🔴 Red

None.

### 🟡 Yellow

**Y1. Layering constitutional test (`test_constitution_core_does_not_import_autonomy`) is missing**
- **Where**: should exist in `tests/core/test_constitution.py` alongside `test_constitution_autonomy_decision_event_carries_trace` and `test_constitution_autonomy_refusal_metadata_field_set`
- **Plan reference**: §4 forcing functions last bullet ("Proposed new forcing function — architect decides") AND §5 push-back #2 ("Senior leans land in C4-5 — the test is cheap and the rule is being established this very commit")
- **Architect ack reference**: "**2** + forcing function land in C4-5 confirmed" (from your ack message)
- **What's missing**: an ast-walk test (~20 lines) over `src/orchestrator/core/**.py` asserting no `from orchestrator.autonomy` import lines
- **What's wrong**: C4-5 is the first `autonomy → core` import edge — the reverse direction (`core → autonomy`) being forbidden is now enforced only by convention. The C2 deliberate-duplication design in `src/orchestrator/core/event.py:209-211` is the lone reminder; no CI signal will catch a future regression.
- **What should be**: add the test in a small follow-up commit to `claude/p1.2-c4-impl` before R0-A dispatch (mirrors C3 Y1 fix pattern `60acc04`). The architect's ack explicitly approved landing in C4-5; impl missed it. Plan-vs-impl drift surface that external reviewers may catch independently.

### 🟢 Green

**G1. Unused imports in emission.py with misleading comment**
- **Where**: `src/orchestrator/autonomy/emission.py:24-25`
- **What**: imports `AutonomyDecisionMetadata` and `AutonomyRefusalMetadata` with `# noqa: F401 — imported to trigger validate_metadata` comment
- **Issue**: emission.py never references these classes (metadata is constructed as raw dict at lines 73-78 and 91-104). The comment promises a side-effect ("trigger validate_metadata") but Python imports do not trigger schema validation; `EventStore.append()` validates via `TYPED_METADATA[event.type]` which is populated at import time by `event.py` itself when those classes are *defined*, not when emission.py *imports* them.
- **Fix**: remove the two lines (and the `noqa` annotations). Net diff: -2 lines.

**G2. E2E source-≠-sink demonstration is weak**
- **Where**: `tests/autonomy/test_e2e_emission.py:59-60` (`assert decision_events[0].metadata["operation_tool_id"] == "read_file"`)
- **Plan reference**: C4-7 "source ≠ sink: e.g., `operation.tool_id != \"tools_yaml_default_tool_id\"` and event metadata's `operation_tool_id` equals operation's tool_id (not a yaml default), proving the value flowed end-to-end rather than being substituted upstream"
- **Issue**: the test proves data flowed (input "read_file" → metadata "read_file"), but a hypothetical bug like "emission hardcodes operation_tool_id='read_file'" would still pass since the operation IS "read_file". The plan intent was to rule out value-substitution-from-yaml-key by demonstrating multiple distinct tool_ids survive the chain.
- **Fix (optional)**: parametrize the success-path e2e test across 2-3 tool_ids from `tools.yaml.example` (e.g., `read_file` reversibility=10 → AUTO_EXECUTE; `git_push` reversibility=1 with non-explicit intent → HARD_CONFIRM; `propose_edit` reversibility=5 → COUNTDOWN_CONFIRM). Each parametrization proves the operation's tool_id is what flows, not any yaml-key substitution. ~10 lines of parametrize.

**G3. E2E test uses non-canonical operator fixture**
- **Where**: `tests/autonomy/test_e2e_emission.py:29` uses `ThresholdConfig(threshold_auto=6, threshold_confirm=3, user_intent_modifier=0)`
- **Issue**: ADR-005 §3 canonical operator has `modifier=3`. The deviation is functionally harmless (test uses `user_explicit_intent=False` so modifier doesn't apply), but creates a fixture that diverges from the canonical reference. Future readers grepping for ADR-005 §3 placeholder threshold values won't find this one.
- **Fix (optional)**: align to `modifier=3` per ADR-005 §3, OR add a one-line docstring on the fixture explaining the deviation. Either resolves the silent divergence.

**G4. ADR-005 §5(c) `ae69a2b`-match verification not surfaced in commit message**
- **Where**: C4-7 commit `2a46909` body, surface 3 of the 5-surface scan
- **Plan reference**: §1 ("plan §1 verification confirms: docs/decisions/ADR-005-…md:149 reads 'asymmetric absence of a floor on effective_threshold_auto'") AND §5 push-back #9 ("C4-7's 5-surface scan should verify the §5(c) text matches what ae69a2b landed")
- **Issue**: commit body says "ADR-005 References += ADR-007" (the new cross-link) but doesn't itemize "ADR-005 §5(c) verified vs `ae69a2b` — no drift". Plan-implied invariant left as silent verification. External R0-A may have to do the grep themselves to confirm.
- **Fix (optional)**: one line added to the commit message body — non-amend, can be noted in plan-vs-impl record as the verification was done correctly (junior didn't touch §5(c)) but invisibly.

**G5. C4-1 / C4-2 tracking-table rows say "landed pre-session" without commit hashes**
- **Where**: `2a46909` commit body tracking table rows for C4-1 and C4-2
- **Issue**: minor stylistic — reader has to git-log to find `0cb6d3a` (C4-1) and `b3bd666` (C4-2). Other rows are scoped to this commit so no hash needed; pre-existing rows would benefit from explicit references.
- **Fix (optional)**: tracking-table convention for next batch — include pre-existing commit hashes in "Notes" column when a task was completed in an earlier commit.

## 4. Plan-implied invariants junior caught (positives)

These exceed the plan's stated acceptance criteria and reflect care:

- **`tests/autonomy/conftest.py` (40 lines, new)**: room_id + event_store fixtures abstracted out so emission and e2e tests share setup. Plan didn't require a conftest; junior introduced one for cleaner test bodies. Future emission-adjacent tests inherit the pattern.
- **`test_emit_refusal_event_appended_before_raise` (test_emission.py:117-149)**: uses an inline `_Recorder` class with structural typing to verify ordering. The plan asked for "ordering" coverage; junior delivered with an isolated, mock-free test that doesn't rely on EventStore's internal queue. Clean implementation.
- **`emission.py:6-10` docstring** explicitly calls out the layering rule and points at `core/event.py:209-211`. Even with the missing constitutional test (Y1), this docstring carries the intent forward — a future contributor reading emission.py will encounter the layering rule before they have a chance to break it.
- **R0-A-5 deferral surfaced cleanly in commit body** with rationale ("changes a frozen-schema field — architect ack needed for frozen-schema evolution policy"). Plan §5 push-back #8 said this; junior repeated the reasoning in commit so meta-review records it without re-reading the plan.
- **C4-3 inline negative-case test** (`refusal_reason="bogus"` rejected) — plan acceptance criterion mentioned "one negative-case test"; junior delivered one. Not surprising but worth confirming since the architect ack didn't itemize C4-3 sub-checks.

## 5. What external R0-A should still check (non-overlapping with senior)

Senior plan-vs-impl audits plan vs. deliverable; external R0-A audits deliverable vs. spec + edge-cases. The below are NOT covered above:

- **Concurrency**: `emit_gate_decision` is sync; if a future caller wraps it in `asyncio.to_thread`, does the inline `EventStore.append` block behave correctly? (Plan said §2 N/A for C4; reviewer can confirm or escalate.)
- **EventStore append failures**: ADR-007 §3 says "if `event_store.append()` itself raises (e.g., disk failure mid-append), behavior is implementation-defined in C4-5". The current impl re-raises the append exception which masks the original UnknownToolError. Worth a §4 exception-payload test for the dual-exception case (or explicit assertion that this is acceptable behavior).
- **Pre-edit grep sub-rule (RC-1) compliance** on event-model.md "17 → 18 types": junior claims it was applied. R0-A should grep `17 type` against pre-/post-edit to confirm zero residual matches.
- **ADR-007 References completeness**: ADR-007 references ADR-001 / 005 / 006. ADR-007 itself was added — but does ADR-007 reference back to the C4 senior plan (the artifact that drove it)? My ADR-007 draft included that reference; verify it survived the Accept bump.
- **Doc-spec drift on event-model.md table row**: the new row for `autonomy_refusal` should match `AutonomyRefusalMetadata`'s field signature ("yes — strict metadata"). Verify the table cell wording matches the schema.

## 6. Verdict

**Ready for external R0-A dispatch** with Y1 routed as a small follow-up commit on `claude/p1.2-c4-impl`. The 4 🟢 items are optional cleanups; architect can route them now (one combined commit) or defer to module close-out per their judgement.

After R0-A (and R0-B if dispatched), I'll write the close-out `meta.md` at `docs/process/reviews/P1.2-C4/meta.md`. P1.2 module close-out then evaluates RC-1 (graduating per architect ack) and RC-6 (frozen-schema evolution policy) for codification.
