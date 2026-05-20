# P1.2-C4 R0-A review

| Field | Value |
|---|---|
| Round | R0 (first external review post-impl + followup) |
| Reviewer | A (architect-partner Claude session) |
| Family | Claude (Opus 4.7) — same family as junior (Sonnet 4.6) and senior plan-vs-impl |
| Cross-family R0-B | **not dispatched** (architect decision; **third consecutive skip** on P1.2: C2 freeze + C3 impl + C4 impl — RC-2 evidence trail now has trend-level data, not point-level) |
| Lens | Doc-spec drift / narrative-vs-code + impl-level edge cases + items senior's plan-vs-impl explicitly handed to R0-A (asyncio.to_thread / append-failure dual-exception / ADR-007 References post-Accept / event-model.md table-cell wording / RC-1 grep compliance) |
| Commits in scope | `c20cfcd` + `c40edaa` + `2a46909` (impl) + `115c825` (senior plan-vs-impl) + `85219eb` (Y1+G1+G3 followup) |
| Gates | ruff ✓ / mypy --strict 52 files ✓ / pytest 300 ✓ |

## Findings

| # | 🚦 | File : line | What's wrong | What should be |
|---|----|-------------|--------------|----------------|
| R0-A-1 | 🟡 | `src/orchestrator/autonomy/emission.py:62-79` (refusal path) | **ADR-007 §3 guidance violated.** ADR-007 §3 states *"If `event_store.append()` itself raises (e.g., disk failure mid-append), … the conservative default is 'let both exceptions surface' — losing the audit record is bad but masking the original `UnknownToolError` would be worse."* Current impl: when `event_store.append(...)` raises inside the `except UnknownToolError:` handler, the append's exception **replaces** the visible exception. The original `UnknownToolError` is preserved on `__context__` (per Python implicit chaining), but any caller writing `except UnknownToolError as e:` will NOT catch the append failure — the architectural promise "UnknownToolError surfaces" silently breaks under disk pressure. ADR-007 explicitly named this scenario and stated the preferred direction; junior's impl picked the opposite default without documenting the deviation. | Two reasonable resolutions, architect picks: **(a)** Wrap append in inner try/except, swallow the append exception (or log it), re-raise the original UnknownToolError — guarantees caller's contract holds. **(b)** Amend ADR-007 §3 to say "C4 implements: append-failure exception wins, original UnknownToolError preserved on `__context__` only — caller responsibility to inspect `__context__` if both signals matter." Either resolves the contradiction. (a) preserves the original ADR guidance (cleaner). (b) records the actual junior choice as deliberate. |
| R0-A-2 | 🟢 | `docs/architecture/event-model.md:136` (autonomy_refusal table row) | Cell description *"unknown tool_id, reason"* enumerates 2 of 4 metadata fields. Consistent with autonomy_decision row pattern at line 135 (*"tier, score, full trace"* — also doesn't enumerate the 12 schema fields), so this is acceptable as a *key-dimensions* convention rather than a *full-enumeration* convention. **Watch only**: if the project standardizes on full enumeration later, both rows need expansion. | No change required. If architect prefers full-enumeration: row 136 → *"unknown tool_id, initiating agent, user intent, refusal reason"*; row 135 → *"tier, score, decision trace (10 fields)"* — symmetric expansion. |
| R0-A-3 | 🟢 | `tests/autonomy/test_emission.py:124-149` (`_Recorder` mock) | Test uses inline `_Recorder` class with `# type: ignore[arg-type]` (line 142) because the recorder doesn't implement the full `EventStore` Protocol. Acceptable behavior-verification pattern but creates type-ignore debt. Alternative: `unittest.mock.MagicMock(spec=EventStore)` (no type-ignore needed but loses the inline append-recording structure) or define a small `Protocol` stub matching only `.append(event)`. Cosmetic. | No change required. If hygiene-pass is appealing: define a one-method Protocol `class _EventAppender(Protocol): def append(self, event: Event) -> EventId: ...` and use it as the `_Recorder`'s base. ~5 lines, removes type-ignore. |
| R0-A-4 | 🟢 | `tests/autonomy/test_e2e_emission.py:45-60` (success path) | Senior's G2 ("e2e source-≠-sink only weakly demonstrated") re-evaluation: senior is right that with one tool (`read_file`) the test would still pass if the chain incorrectly substituted any value as long as both ends agreed. **Stronger §1 demonstration**: load N≥2 tools, gate one specifically, assert the OPERATED tool_id appears in the event AND the OTHER tool_ids do NOT. Defer to C5 or module close-out as a §1 standard refinement (not blocking C4 land). | Plan-level decision for module close-out: refine `test-coverage-standard.md` §1 acceptance criterion from "source ≠ sink value" to "source ≠ sink value AND no cross-key substitution possible". Test refinement adds ~5 lines. |
| R0-A-5 | 🟢 | `src/orchestrator/autonomy/emission.py:33-41` (`emit_gate_decision` signature) | Function takes `room_id` and `author` as keyword-only arguments. **Question**: P1.3 agent-runtime (caller) needs to populate both per call. Currently `author` is a plain `str` parameter — caller can pass anything matching the `^(user|system|agent:[a-zA-Z0-9_-]+)$` pattern that `Event.author` validator enforces, but emission has no compile-time guarantee. **Defensible**: validator catches at Event construction (one layer below); emission would just duplicate. **Worth surfacing for P1.3 agent runtime brief**: typing `author` as a `NewType("AgentAuthor", str)` with a constructor that validates would push the contract to caller instead of relying on event-store-level validation. | Not actionable in C4. Surface to P1.3 brief as design question for agent-runtime ↔ emission interface. |

**🔴 None.** All C4 plan tasks satisfied; gates green; all senior-handed-to-R0-A items checked.

## Cross-checks performed (no findings)

- **Senior plan-vs-impl 115c825 findings disposition**:
  - Y1 (missing `test_constitution_core_does_not_import_autonomy`): **fixed by 85219eb** — ast-walk implementation correct (`ast.ImportFrom` + `ast.Import` covered), violation message includes file:line; pattern mirrors `test_constitution_no_llm_calls_in_autonomy_module`. ✓
  - G1 (unused imports + misleading noqa): **fixed by 85219eb** — all 7 imports in emission.py:14-30 verified used in body (`AutonomyScore` return type, `Operation/ThresholdConfig/ToolMeta` parameters, `UnknownToolError` except clause, `gate` call, `Event/EventType/RoomId/generate_event_id/now_ms` event construction, `EventStore` parameter). ✓
  - G3 (operator modifier 0 → 3): **fixed by 85219eb** — `test_e2e_emission.py:29` now `user_intent_modifier=3`, matches ADR-005 §3 placeholder. ✓
  - G2 (weak source-≠-sink): escalated to R0-A-4 above (still 🟢 but architect-partner agrees the demonstration is light; close-out plan-level refinement candidate).
  - G4 (commit body ae69a2b-match verification): cosmetic, post-commit unfixable; no action.
- **RC-1 pre-edit grep sub-rule compliance**: `grep "17 type\|17 meaningful" docs/architecture/event-model.md` returns **0 matches** post-edit. Lines 30, 83, 115 all bumped to 18. ✓ — first procedural-instance of the RC-1 sub-rule executed cleanly.
- **ADR-007 References completeness post-Accept**: lines 260+ reference ADR-001, ADR-005 §6, ADR-006 §3, contributing.md Q3, senior-planner.md "ADR drafting", architect brief, senior plan, event-model.md. Complete. ✓
- **ADR-005 + ADR-006 References gained ADR-007 cross-link**: ADR-005 line 289 + ADR-006 line 244 both add ADR-007 reference. Symmetric. ✓
- **`event-model.md` autonomy_refusal narrative** (lines 50-53): emit-before-raise wording matches ADR-007 §3; metadata field-count "(4 fields)" matches schema; constitutional-test name not cited (could mention `test_constitution_autonomy_refusal_metadata_field_set` symmetric to line 47's autonomy_decision citation — minor, defer).
- **`concurrent / asyncio.to_thread` check**: emission is **synchronous**; EventStore is synchronous (sqlite3 connection). Nothing async in the autonomy module. Senior's "check concurrency under asyncio.to_thread" is moot for C4 — no asyncio path exists yet. P1.4 multi-agent dispatch will revisit. ✓
- **Layering**: constitutional test `test_constitution_core_does_not_import_autonomy` passes (verified by 300 tests green). `autonomy.emission` correctly imports from `core.event` + `core.event_store`. First sanctioned cross-package edge documented in `emission.py:6-10` docstring and in ADR-007 Decision 4. ✓
- **Freeze-vs-impl drift**: `scoring.py` function signatures unchanged from C2 freeze (verified by senior plan-vs-impl; partner re-confirmed). `load_tools_config` signature unchanged from C2 freeze. New `emit_gate_decision` is new (no freeze contract). ✓
- **C4 plan tracking compliance**: all 7 atomic tasks landed; tracking tables present in each task commit body. ✓

## Positives worth surfacing (junior + senior beyond plan minimums)

- **`tests/autonomy/conftest.py`** — junior added shared `event_store` + `room_id` fixtures (not specified in plan). Cleaner than rebuilding per-test. Reusable in any future autonomy test file. **Good unrequested abstraction**.
- **`_Recorder` mock in `test_emit_refusal_event_appended_before_raise`** — junior chose to verify append-then-raise ordering with a recorder that captures the append sequence, rather than using `unittest.mock.MagicMock` or relying on after-the-fact event_store inspection. **Cleaner than what the plan asked for**; the ordering test is self-evident from `assert recorder.appended == ["autonomy_refusal"]` line 147.
- **emission.py docstring lines 6-10** carries the layering rule (`autonomy → core OK; core → autonomy forbidden`) as inline documentation, **even though Y1 (the constitutional test enforcing it) was missing at impl time**. Junior knew the rule conceptually; the test gap was an oversight, not a conceptual miss.
- **R0-A-5 deferral rationale** documented in C4-6 commit body — meta-review at module close finds it without re-reading the plan. Good "future readers" hygiene.
- **R0-A-1's discoverability**: senior's plan-vs-impl pointed R0-A at "EventStore append-failure dual-exception behavior" as something to check. The R0-A-1 finding was directly enabled by that hand-off. Good cross-reviewer chain.

## Cross-family R0-B status

Skipped per architect decision. **Third consecutive skip on P1.2** (C2 freeze, C3 impl, C4 impl). RC-2 evidence trail now has 3 instances. If C5/close-out review or future P1.3 contract bug surfaces a data-flow / signature-semantic issue the same-family chain would have missed, that's the verdict on single-reviewer-R0 sufficiency for non-trivial work. If close-out arrives clean, single-reviewer-R0 is empirically defended for P1.x.

## Recommended next steps

1. **R0-A-1 resolution**: architect picks **(a)** preserve UnknownToolError contract via inner try/except in emission.py OR **(b)** amend ADR-007 §3 to document the deviation. Junior or architect-partner executes per architect-scope. Estimated effort: (a) ~5 LoC + 1 test for append-failure path; (b) ~2 sentences in ADR-007.
2. **R0-A-2 / R0-A-3 / R0-A-4 / R0-A-5**: defer to module close or P1.3 brief depending on architect call.
3. **PR to main**: after R0-A-1 resolved, impl branch merges to main. Likely merge conflict on `handoff.md` §15 (ADR-007 row) similar to C3 — architect-partner can pre-resolve.

## Distance test

C4-1 (ADR-007 Proposed) was 2026-05-20. C4-3 onward (impl) landed 2026-05-20 — same day as accept. **Junior's first commit `c20cfcd` was 2026-05-20**; the distance-test note in the brief said impl should land 2026-05-21+ earliest. This is a **same-day inscription** on the autonomy event-emission contract, which is load-bearing for P1.3 agent runtime.

**Architect-partner observation, not blocking**: the distance-test rhythm was not honored this cycle. Reasons may include (a) C3 itself ran same-day too, so the C4 same-day was less of a step-change than it looks; (b) the impl was mechanical given the senior plan + accepted ADR. Worth a meta-observation at P1.2 close-out: distance-test discipline at the architect/architect-partner level is one thing; junior-impl-same-day-as-plan is another and may be defensible.

## Status

**Verdict: 🟡 — ready for architect review; R0-A-1 has one design-level choice (a/b) blocking clean PR-to-main.** Code is production-quality on every other axis; R0-A-2 through R0-A-5 are accept-or-defer-as-watch. Senior's audit captured Y1+G1+G3 cleanly, Y1+G1+G3 fixed cleanly, R0-A's independent lens added R0-A-1 (exception-handling deviation from ADR-007 §3) plus the 🟢 watch items.

Architect's call on R0-A-1 → land path.
