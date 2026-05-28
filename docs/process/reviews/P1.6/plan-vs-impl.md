---
task_id: P1.6
round: plan-vs-impl
verdict: needs_architect
findings_count:
  red: 0
  yellow: 2
  green: 5
---

# Review: P1.6 — plan-vs-impl

**Reviewer:** senior planner (Claude Opus 4.7, primary session)
**Date:** 2026-05-28
**Artifacts reviewed:** 5 impl commits on `claude/P1.6-impl` (`cca42e3` → `6c7cf7d`): P1.6-1 (derived/ package) → P1.6-2 (SummarySnapshotMeta) → P1.6-3 (Logger wiring) → P1.6-4 (e2e) → P1.6-5 (landing). 1079 + 547 + 1231 + 318 + 1228 LoC delta (largely test-heavy; `event.py` and `dispatch.py` LoC counts inflated by CRLF flip noise — verified by reading current files, not raw diff).
**Plan:** `docs/process/senior-plans/P1.6.md` (multi-ADR W-002.5 aggregation; ADR-014 + ADR-015 both Accepted via `89bfdba` predecessor).
**State context:** `.workflow/P1.6.yaml` at `awaiting_senior_plan_vs_impl, cycle: 1, override_history: []`. **7th consecutive impl-drift-free cycle** (W-002.5 → P1.4 → P1.5 → W-003 → P1.5.5 → W-004 → P1.6) — landing dogfooded RC-19 fix in **first substantive-cycle context** (SD-DOGFOOD validated; zero overrides this cycle).

---

## 1. Coverage of plan acceptance criteria

Every plan-pinned acceptance bullet checked against the diff. All 5 atomic tasks satisfy criteria; 3 senior new self-discoveries (S1 + S2 + S3) operationally validated; no scope creep beyond the senior pins.

| Task | Plan-mandated acceptance | Implemented as | Verdict |
|---|---|---|---|
| P1.6-1 | `derived/` combined package (§5 #4 senior pin deviating from brief split-package lean); `snapshot.py` + `decision_log.py` + `test_constitution.py`; ≥20 §6 schema tests + ≥10 snapshot cross-module + ≥8 decision-log; D2.1-D2.5 predicates implementation-cited to ADR-014 sections; purity per ADR-014 D1 (clock-injection `snapshot_at: TimestampMs` kw); no LLM imports | `src/orchestrator/derived/{__init__,snapshot,decision_log}.py` (229 + 82 LoC); 5 Ref classes (HypothesisRef + DecisionRef + ToolCallRef + StateTransitionRef + Snapshot) + 2 DecisionLog classes; D2.1-D2.5 derivation implemented per typed-metadata cite chains at `snapshot.py:108-204`; `produce_snapshot(events, room, *, snapshot_at: TimestampMs)` signature matches Y2-absorbed pin; constitutional test verifies no `anthropic`/`openai`/`LLMRouter` imports; **34 snapshot tests + 16 decision-log tests + 1 constitutional = 51 new tests** (vs plan ≥20+10+8+1 = ≥39). | ✓ Done |
| P1.6-2 | `SummarySnapshotMeta` in `core/event.py` with field shape mirroring `Snapshot` (ADR-014 D5 deliberate duplication; `core` MUST NOT import from `derived/`); registered in `TYPED_METADATA`; ≥4 §6 tests + 1 round-trip test | `core/event.py` `SummarySnapshotMeta(_BaseMeta)` at expected shape — `room_id`/`room_type`/`room_state`/`snapshot_at`/`event_count`/`decision_count`/`open_hypotheses`/`closed_decisions`/`tool_calls_pending_confirm`/`last_state_transition`/`participants`; `TYPED_METADATA[EventType.SUMMARY_SNAPSHOT] = SummarySnapshotMeta` registered; **6 new tests in TestSummarySnapshotMeta** including `test_snapshot_roundtrip` exercising the ADR-014 D5 invariant via real `produce_snapshot()` round-trip; **no `derived/` import in `core/event.py`** (deliberate-duplication preserved — confirmed by grep). | ✓ Done |
| P1.6-3 | `logger.yaml` adds `speaking_triggers: [{type: state_change, target_state: snapshot_pending}]` (cooldown 120s stays); `agents/snapshot_dispatch.py` new sibling per ADR-013 D1 precedent (S1 pin); `produce_and_emit_snapshot()` clock-injection per ADR-014 D1+D6 (one `now_ms()` call threaded through to both `produce_snapshot` AND event `timestamp`); single new call site in `dispatch.py` gated by `agent.id == "logger" AND state_transition AND new_state == "snapshot_pending"`; ≥4 + 1 integration tests | `config/agents/logger.yaml` block present at expected shape; `agents/snapshot_dispatch.py:52-71` exactly matches plan pseudo-code structure (snapshot_at captured once → threaded through to `produce_snapshot` AND used as event `timestamp` per D1+D6); `SnapshotDispatchResult` BaseModel returned; `dispatch.py:155-173` adds single call site gated correctly; **5 tests in `test_snapshot_dispatch.py` + 1 integration `test_dispatch_logger_produces_summary_snapshot_on_snapshot_pending` at `test_dispatch.py:683`**; constitutional invariant preserved (`snapshot_dispatch.py` imports only `agents.schema` + `core.event` + `core.event_store` + `core.room` + `derived.*` — no LLM imports). See Y1 below re: call-site wrapper. | ✓ Done (Y1 concern) |
| P1.6-4 | `tests/integration/test_p1_6_e2e.py` (new — explicit P1.6-scope naming per plan); full Research room state chain `setup → exploration → divergence → convergence → snapshot_pending → closed`; 8-step assertion sequence; source ≠ sink invariant on `decision1.id` flowing event-stream → `produce_decision_log` → `DecisionEntry.event_id`; closing transition `prior_state="snapshot_pending", new_state="closed"`; <2s | New `tests/integration/test_p1_6_e2e.py` (318 LoC, 1 e2e test); 5-step state advance via `next_room_state` direct + manual transition-event appends (senior pin honored); `dispatch_turn` with `MagicMock(spec=LLMRouterProtocol)` returns `summary_snapshot` event; closing-transition assertion verifies `rule_matched == "summary_snapshot_triggers_closed"`; source ≠ sink invariant asserted via `decision1.id in decision_entry_ids`. See G2 + G3 + G4 below for minor deviations. | ✓ Done (3 green) |
| P1.6-5 | 5-row tracking table; 5-surface scan table (W-003-5 format) covering 5 surfaces incl `handoff.md` §4.5 + §5.8 light-touch; constitutional tests green (7+ modules incl new `derived/`); test delta ≥35; `workflow verify-workspace` + `workflow verify-merge-readiness --task-id P1.6` invoked; state advance via `workflow advance` (RC-19 dogfood in substantive-cycle context — SD-DOGFOOD) | Commit `6c7cf7d` body has all elements: 5-row tracking table (P1.6-1 through P1.6-5 all Done with sha refs); 5-surface scan table with PASS/N-A per surface; `handoff.md` 2436-line update (mostly CRLF noise per inspection; substantive §4.5 + §5.8 light-touch addition cite ADR-014 + ADR-015); test delta **+64** (>= plan ≥35); 25+ constitutional tests green incl new `test_constitution_no_llm_calls_in_derived_module`; verify-workspace + verify-merge-readiness outputs documented (both warnings expected); state advance via `workflow advance` succeeded **zero overrides** — SD-DOGFOOD validated in substantive-cycle context. | ✓ Done |

---

## 2. Senior new self-discoveries — operational validation

| Pred | Plan §5 prediction | Operational outcome | Verdict |
|---|---|---|---|
| S1 | `agents/snapshot_dispatch.py` sibling-module per ADR-013 D1 precedent (mirrors P1.5.5's `tool_dispatch.py`); single new call site in `dispatch.py` | `snapshot_dispatch.py:37-71` implements the sibling per the predicted shape; `dispatch.py:157-167` adds exactly one new call site (excluding the surrounding try/except wrapper — see Y1); ADR-013 D1 second exercise validated. | ✓ Validated |
| S2 | Hardcoded `agent.id == "logger"` is acceptable for P1.6 single-producer scope; future multi-producer needs ADR-014 amendment per Principle 9 | `dispatch.py:157` literal `agent.id == "logger"` per plan; amendment hook surfaced (no in-cycle stab at multi-producer abstraction). | ✓ Validated |
| S3 | Constitutional test count: 1 new test (combined-package pin), not 2 (brief lean was split) | `tests/derived/test_constitution.py` single file with `test_constitution_no_llm_calls_in_derived_module`; brief Constraint #2 ("2 new constitutional tests expected") corrected to 1 per S3 prediction. | ✓ Validated |

Additionally, two **brief-predicted self-discoveries** operationally validated:

- **SD-METADATA**: `SummarySnapshotMeta` + `TYPED_METADATA` registration is P1.6-2; project pattern (ADR-013 D5 `ToolCallMeta` precedent) honored.
- **SD-DOGFOOD**: First substantive-cycle dogfood of W-004-1 RC-19 fix succeeded — `workflow advance` correctly detected junior-impl commits ahead of origin/main since `last_transition_at`; state advanced `awaiting_junior_impl → awaiting_senior_plan_vs_impl` without override.

---

## 3. Findings

### 🟡 Y1 — Snapshot dispatch wrapped in broad `except Exception` (silent swallow + warn-log)

**Location:** `src/orchestrator/agents/dispatch.py:155-173`.

**Plan §2 P1.6-3 acceptance pseudo-code:**

```python
if agent.id == "logger" and current_event.type == EventType.STATE_TRANSITION:
    meta = StateTransitionMeta.model_validate(current_event.metadata)
    if meta.new_state == "snapshot_pending":
        produce_and_emit_snapshot(
            agent=agent, room=room, current_event=current_event,
            event_store=event_store, snapshot_events=snapshot,
        )
```

**Implemented:**

```python
if agent.id == "logger" and current_event.type == EventType.STATE_TRANSITION:
    try:
        st_meta = StateTransitionMeta.model_validate(current_event.metadata)
        if st_meta.new_state == "snapshot_pending":
            produce_and_emit_snapshot(...)
    except Exception as exc:
        _log.warning("agent %s snapshot dispatch failed; skipping (continuing): %s", agent.id, exc)
```

**Concern:** the broad `try/except Exception` wrapper was not in the plan. If snapshot dispatch silently fails, no `summary_snapshot` event is appended → `rooms/state_machine.py:26` `snapshot_pending → closed` never fires → **room is stuck in `snapshot_pending` forever**. The warn-log preserves a forensic trail but the room state machine has no way to recover.

This is a substantive policy question that the plan did not resolve:
- **Option A (impl chose):** `log + skip` symmetric with ADR-011 D7 LLM-failure pattern.
- **Option B (plan literal):** propagate unwrapped per ADR-011 D7-b (treats snapshot dispatch like `event_store.append` — a load-bearing persistence operation whose failure should abort the turn so the caller can retry / surface).

ADR-011 D7-b covers `event_store.append` specifically; snapshot dispatch internally calls `event_store.append` so plan literal would mean the embedded `append` raises propagate-unwrapped. The impl's outer wrapper would catch ADR-011 D7-b's intentional propagation, **contradicting ADR-011 D7-b's contract for event-store persistence failures**.

Additionally, `except Exception` is overly broad — it masks programming errors (e.g., AttributeError if `StateTransitionMeta` field renamed), not just ValidationError on malformed metadata.

**Recommended architect routing:** α (architect rules on intended error semantic for snapshot-dispatch failures). If A: keep current code but narrow to `except (ValidationError, RuntimeError)` or similar; if B: drop the wrapper and let it propagate per ADR-011 D7-b. Either way, the decision deserves a one-line note in ADR-014 D? error-semantic addendum.

### 🟡 Y2 — `produce_snapshot` + `produce_decision_log` silently swallow Pydantic ValidationError on metadata parsing

**Locations:**
- `snapshot.py:119-135` (DECISION/REJECTION/RETRACTION metadata parsing for `closed_hypothesis_ids`).
- `snapshot.py:148-153` (RETRACTION metadata for `retracted_event_ids`).
- `snapshot.py:166-188` (AUTONOMY_DECISION + TOOL_CALL metadata for `tool_calls_pending`).
- `snapshot.py:194-204` (STATE_TRANSITION metadata for `last_state_transition`).
- `decision_log.py:52-64` (REJECTION/RETRACTION metadata for `parent_event_id`).

All 8 sites use the pattern `try: meta = X.model_validate(e.metadata); ... except Exception: pass`.

**Plan §4 forcing functions §4 says** (line 335): "exception payloads: NO new error classes ... failures surface as Pydantic ValidationError on malformed metadata; matches the brief lean."

**Plan §4 §3 cleanup says** (line 334): "empty event stream / malformed metadata / Logger LLM failure handled per existing ADR-011 D7-b pattern."

These two acceptance clauses **conflict**:
- §4 §3 (cleanup) implies graceful handling per ADR-011 D7-b → matches impl.
- §4 §4 (exception payloads) implies ValidationError surfaces → impl contradicts.

ADR-011 D7-b is specifically the `event_store.append` propagation rule, not a generic "all errors are swallowed" license. The most defensible reading of the plan is: malformed metadata in `produce_snapshot`/`produce_decision_log` **should propagate ValidationError**, because:

1. These are pure-function derivations over event-store contents; if a stored event has malformed metadata, that is itself a constitutional violation (typed-metadata invariant) that should surface, not silently warp the derivation result.
2. The current swallow has correctness implications: if a `DECISION` event has malformed `based_on`, the hypotheses that decision was meant to close stay in `open_hypotheses` — the Snapshot lies about room state.
3. The `except Exception` (vs `except ValidationError`) masks programming errors, not just data errors — e.g., if a field rename ever happens without metadata-schema migration, the snapshot quietly degrades instead of failing loudly.
4. No tests cover the swallow path; the swallow is uncovered behavior that the test suite cannot catch regressions in.

**Recommended architect routing:** α (architect rules on whether snapshot/decision-log derivations should be strict or lax on malformed metadata). If strict (recommended): remove the `try/except` wrappers — let ValidationError propagate; add 1-2 §3-cleanup tests asserting that malformed metadata raises ValidationError up through `produce_snapshot`. If lax (impl current): narrow to `except ValidationError`, add log statements (not silent `pass`), and add §3-cleanup tests pinning the swallow behavior so future refactors can't regress it accidentally.

---

### 🟢 G1 — `snapshot_dispatch.py:57` discards `produce_decision_log` result

```python
# Decision log is derived and available to callers via event_store, not persisted.
# Produce here to exercise the derivation; result not stored (ADR-015 D5).
_ = produce_decision_log(snapshot_events, room)
```

Plan §2 P1.6-3 acceptance literal: "call `produce_snapshot(snapshot, room)` + `produce_decision_log(snapshot, room)` + append `summary_snapshot` event." The impl honors plan literal by calling both functions, but ADR-015 D5 says DecisionLog is not persisted — so the call computes a structure and discards it on every snapshot. This is wasted compute on every Logger trigger. Either: (a) remove the call (it is not load-bearing for the snapshot or the summary_snapshot event), or (b) accept the comment + `_ =` pattern as deliberate exercise-only. Plan literal is honored; impl just hews closely. Low-stakes; surface for architect awareness.

### 🟢 G2 — e2e test uses `>= 1` rather than exact decision count

`tests/integration/test_p1_6_e2e.py:302` asserts `len(decision_entries) >= 1`. Plan §2 P1.6-4 acceptance step-8 says: "`DecisionLog.entries length == count of `decision` events emitted`." The test emits exactly one DECISION event (`decision1`), so exact would be `== 1`. Loose assertion passes but does not enforce plan-stated invariant; future regression that emits 2 decisions but produces 1 entry would not fire.

### 🟢 G3 — e2e test exercises `produce_snapshot` rather than `Snapshot.model_validate(meta)` round-trip

`test_p1_6_e2e.py:295` calls `produce_snapshot(snapshot_events, room, snapshot_at=...)` directly. Plan §2 P1.6-4 acceptance step-8c says: "`Snapshot.model_validate(event.metadata)` after the round-trip yields fields matching expected." The dict→Snapshot direction of the round-trip is covered in `test_event.py::TestSummarySnapshotMeta::test_snapshot_roundtrip` (P1.6-2). Cross-task coverage is OK but the e2e doesn't literally execute the round-trip clause the plan named.

### 🟢 G4 — e2e test runtime: commit reports <3s; plan target <2s

P1.6-5 commit body: "1 e2e test passing in <3s (SQLite in-memory)." Plan §2 P1.6-4 acceptance: "Test runs in <2 seconds." Likely environmental jitter (load_agents reads 5 yamls + SQLite init); not load-bearing.

### 🟢 G5 — `SnapshotDispatchResult` return is discarded at call site

`dispatch.py:161-167` does not capture `produce_and_emit_snapshot()` return. The plan did not explicitly require capturing; `SnapshotDispatchResult` is used by `test_snapshot_dispatch.py` assertions. Consistent with plan; surface only because the call discards a structured result that could later be useful (logging, metrics, multi-snapshot rooms).

---

## 4. Forcing functions applied

- **Constitutional tests**: 8 modules now (`agents/autonomy/core/llm/rooms/skills/workflow/derived`) — new `test_constitution_no_llm_calls_in_derived_module` per S3 pin; all green.
- **6-category test-coverage standard** per plan §4:
  - §1 cross-module: P1.6-4 e2e test exercises event-stream → `dispatch_turn` → `summary_snapshot` event → `next_room_state` close transition.
  - §2 concurrency / clock: ADR-014 D6 caller-frozen-time semantic implemented via `snapshot_at` threaded through `produce_snapshot` + event `timestamp` (verified at `snapshot_dispatch.py:52-69`).
  - §3 cleanup: malformed-metadata path implemented as swallow (Y2 disagrees with plan §4 §4 strict-failure clause).
  - §4 exception payloads: no new error classes (plan honored); but see Y2 for clause-vs-impl tension.
  - §5 boundary validators multi-position: `event_count`/`decision_count` ge=0 tested at 0 / 1 / negative (per `TestSummarySnapshotMeta::test_wrong_type_event_count`).
  - §6 schema invariants: 20+ §6 tests across 8 new schema classes (Snapshot + 4 Refs + DecisionEntry + DecisionLog + SummarySnapshotMeta).
- **5-surface scan**: W-003-5 codified table format used; explicit PASS/N-A per surface.
- **Tracking table**: 5 rows per [[feedback_review_followup_tracking]] pattern.
- **Workflow state machine**: multi-ADR W-002.5 aggregation (2nd project use after W-002.5 itself); both ADR-014 + ADR-015 Accepted before `awaiting_junior_impl`; state advanced via `workflow advance` (RC-19 dogfood).
- **3 W-004-2 codified pre-investigation rules**: (a) claims-without-cites — plan §5 had verification cites; (b) promotion-impact grep — SD-PROMO ran; (c) architect-deferral literal-reading — brief Out-of-scope items honored (no in-cycle stabs).
- **Per-atomic commit subjects** (RC-17): 5 commits each named `P1.6-N: <subject>` — discipline preserved.

---

## 5. Verdict and recommended next action

**Verdict:** `needs_architect`.

**Reason:** 2 yellow findings (Y1 + Y2) both concern **error-handling discipline** for the snapshot-derivation + snapshot-dispatch surfaces. They are not blocking impl correctness (the happy path works end-to-end per P1.6-4 e2e); they are policy questions the plan left ambiguous, and the impl resolved them in the lenient direction without explicit plan license. Resolution shape:

1. **Architect rules Y1**: snapshot-dispatch failure → log+skip (current) OR propagate per ADR-011 D7-b? Adds 1-line ADR-014 addendum.
2. **Architect rules Y2**: malformed-metadata-in-derivation → swallow (current) OR raise? Likely raise; consider 1-line ADR-014/ADR-015 addendum.
3. **5 green findings**: surface for awareness; architect may route as δ (defer) en bloc or fold into Y resolution at junior R0-A revision.

If Y1/Y2 land as "current impl is correct," the cycle proceeds to R0-A-on-impl dispatch. If they land as "tighten error handling," junior gets a small follow-up commit (1 commit, ~5-15 LoC across `dispatch.py` + `snapshot.py` + `decision_log.py` + 2-3 new tests pinning the chosen semantic) before R0-A.

**Expected next state-file transition:** `awaiting_senior_plan_vs_impl → awaiting_architect_review_of_plan_vs_impl` per ADR-008 (architect routes Y findings → either inline fix in current branch or dispatch R0-A-on-impl with findings folded into review prompt).

**Audit observation:** 7th consecutive impl-drift-free cycle on the *coverage* axis (every plan-pinned acceptance bullet was implemented; senior pins S1/S2/S3 validated; SD-DOGFOOD substantive-cycle exercise succeeded). The Y findings here are not coverage drift — they are **first-substantive-cycle exposure of an error-handling policy gap** the plan didn't think to pin because brief did not surface it. Worth noting in P1.6 retrospective as a future plan-stage forcing function: "for new module surfaces with derivation/dispatch failure modes, plan §4 must pin error semantic explicitly (raise vs swallow vs log+skip)."
