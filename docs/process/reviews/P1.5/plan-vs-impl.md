---
task_id: P1.5
round: plan-vs-impl
verdict: clean
findings_count:
  red: 0
  yellow: 1
  green: 4
verdict_history:
  - verdict: blocking
    date: 2026-05-27
    summary: 1 🔴 R1 (test_state_transition_event_before_utterance fails in full-suite due to get_room_events unstable secondary ordering on ms-tied events) + 1 🟡 Y1 (commit 5d21370 bundles P1.5-4 under P1.5-6 subject)
  - verdict: clean
    date: 2026-05-27
    summary: R1 fixed by 307a8fa per senior lean (a) — get_room_events ORDER BY changed from (timestamp, id) to (timestamp, rowid); root-cause diagnosis (random-UUID id is not insertion-order) matches review §R1 hypothesis exactly. 677 tests green; mypy strict + ruff clean. Y1 carried forward to retro as candidate forcing function (not blocking).
---

# Review: P1.5 — plan-vs-impl

**Reviewer:** senior planner (Claude Opus 4.7, 1M context)
**Date:** 2026-05-27
**Artifacts reviewed:** 5 impl commits on `claude/P1.5-impl` (`211b003` → `e4b272b`): P1.5-3, P1.5-5, P1.5-6 (bundles P1.5-4 — see 🟡 #1 below), P1.5-7, P1.5-8. ~2700 LoC insertions across `src/orchestrator/{agents,core,rooms}/` + `config/` + 5 test files + docs.
**Plan:** `docs/process/senior-plans/P1.5.md` (post-R0-A-on-plan routing absorption; `adr: ADR-012` in frontmatter).
**State context:** `.workflow/P1.5.yaml` at `awaiting_senior_plan_vs_impl, cycle: 1`. Cycle stayed at 1 — second P1.x task to do so end-to-end through impl.

---

## Post-fix update (2026-05-27)

Junior pushed `307a8fa R1: fix get_room_events unstable ordering — ORDER BY rowid replaces id` per senior lean (a). Verdict bumped `blocking → clean` per RC-10 codified protocol; verdict_history preserved in frontmatter.

**R1 resolution verification:**

- Diagnosis matches review §R1 hypothesis: junior identified `id` is a random `evt_<uuid4.hex>` UUID, so `ORDER BY ... id ASC` was effectively random within ms ties. The `RoomRuntime` reliably appends state_transition + utterance within the same millisecond, making the ambiguity concrete.
- Fix is **senior lean (a)**: `core/event_store.py` `get_room_events` ORDER BY changed from `(timestamp ASC, id ASC)` to `(timestamp ASC, rowid ASC)`. SQLite `rowid` is the implicit auto-increment B-tree key — insertion-order-stable.
- Applied consistently: same fix in `_all_events` debug query.
- Bonus refactor: covering index renamed `idx_events_room_ts_id` → `idx_events_room_ts` (one column dropped; rowid is the implicit B-tree key so SQLite uses it for the tiebreaker at no extra storage cost).
- **Signature unchanged**: `get_room_events` return type + arguments identical. No downstream caller changes. The fix benefits every consumer of `get_room_events` (current P1.4 dispatch reads; future P1.6 snapshot mechanics; future P2 UI).
- Junior commit body carries Q1-Q4 + tracking table per project convention.
- Full suite: 677 tests green. ruff + mypy strict clean across 100 source files.

**Y1 disposition:** carried forward to P1.5 retrospective as candidate forcing function "commit subject must enumerate all bundled task IDs whose content is in the commit body." Not blocking; architect rules at retro.

The post-fix impl is **ready for R0-A dispatch**. State-machine auto-trigger expectation: with frontmatter `verdict: clean`, the harness routes `awaiting_senior_plan_vs_impl → awaiting_R0_A` per ADR-008 D1.

---

## 🔴 BLOCKING (1 finding) — RESOLVED in 307a8fa

### R1 — `test_state_transition_event_before_utterance` fails in full-suite

**Where:** `tests/rooms/test_runtime.py:225`.

**What:** the test passes when run in isolation (`pytest tests/rooms/test_runtime.py::test_state_transition_event_before_utterance`) but **fails in the full suite** (`pytest tests/`). The assertion `assert state_idx < utterance_indices[-1]` fails with `assert 2 < 1`, meaning the STATE_TRANSITION event lands at index 2 in `events`, AFTER the agent's utterance at index 1.

**Root cause hypothesis:** timestamp-tie ordering in `EventStore.get_room_events`. `RoomRuntime.run_turn` correctly appends the state_transition event at step 3 BEFORE calling `dispatch_turn` (which appends the agent's utterance later) — confirmed by reading `src/orchestrator/rooms/runtime.py:80-103`. The order in the event store is correct by insertion. But both events get timestamps via `now_ms()` (epoch milliseconds); when both `event_store.append` calls happen within the same millisecond, `get_room_events`'s `ORDER BY timestamp` returns an unstable secondary ordering (likely SQLite default — ROWID or insertion order, neither guaranteed).

P1.5 makes this concrete because RoomRuntime reliably appends state_transition + utterance within ms of each other. P1.4 didn't surface this because `dispatch_turn` only appends utterances (no inter-event ordering invariant tested at ms precision).

**Why senior is blocking, not 🟡:**
- CI / `pytest` is red. Architect's `awaiting_R0_A → awaiting_PR_merge` auto-trigger gates on `gates.tests_pass` per ADR-008 D8 — this is a hard gate, not an architect-decision point.
- The ADR-012 D5 invariant is "transition persisted BEFORE dispatch so the event log reflects the transition in the order it happened." The invariant is upheld in code (run_turn appends in correct order) but violated in observable behavior (get_room_events returns wrong order). This is a contract bug.
- Junior's P1.5-8 commit body presumably claimed "all gates green"; either junior ran a partial suite OR the failure is fresh (time-sensitive). Either way: ship-blocking.

**Options for resolution:**

- **(a) Fix `get_room_events` ordering** — add `ORDER BY timestamp, id` (or `ROWID`) so timestamp ties resolve by insertion order. Most general fix; benefits all consumers of get_room_events. Likely a `src/orchestrator/core/event_store.py` change. Test stays as-is.
- **(b) Force monotonic timestamps in `event_store.append`** — if the last appended event's timestamp ≥ the new event's `now_ms()`, increment by 1ms. Brittle (mutates timestamps) but fixes the symptom.
- **(c) Test-side fix** — change the test to verify INSERTION ORDER via a different mechanism (e.g., list events in the order they were appended via an instrumented store) rather than `get_room_events` ordering. Doesn't fix the underlying ordering ambiguity; only papers over the test.

**Senior lean: (a)** — the ordering ambiguity is a real bug that affects any future code reading `get_room_events` with millisecond-precision-tied events. Fixing at the store level is one line + one test; benefits future P1.6 snapshot mechanics + P2 UI rendering. (c) papers over.

**Junior action required before R0-A dispatch:** fix per (a) or (b); re-run full suite; re-push.

---

## 🟡 (1 finding)

### Y1 — Commit subject discrepancy: P1.5-4 invisible in git log

**Where:** commit `5d21370` subject line.

**What:** Commit subject reads "P1.5-6: rooms/templates.py + load_room helper + 5 RoomType templates + tests". The commit body **also** contains:
- `src/orchestrator/rooms/exceptions.py` (44 lines — P1.5-4 scope)
- `src/orchestrator/rooms/state_machine.py` (312 lines — **the entire P1.5-4 state machine**)
- `tests/rooms/test_state_machine.py` (464 lines — 21 P1.5-4 tests)

`git log --oneline main..HEAD` shows only 5 commit subjects (P1.5-3, -5, -6, -7, -8). **P1.5-4 is invisible** in the audit-trail search. Future readers looking for "where did `next_room_state` land?" via `git log --grep "P1.5-4"` find nothing — they must inspect `5d21370`'s actual diff to discover the bundling.

The bundling itself isn't wrong (P1.5-4 + P1.5-6 are both in `rooms/`; one cohesive commit is defensible). But the **commit subject didn't reflect the bundled scope**, which violates the tracking-table-precise discipline (every task subject names its content).

**Options for resolution:**

- **(a) Junior amends the commit subject** to "P1.5-4 + P1.5-6: rooms/state_machine.py + rooms/templates.py + tests" via a force-push (rewriting history on the impl branch before merge). Cleanest audit; one-time history rewrite cost.
- **(b) Architect-partner notes the bundling in R0-A** + tracks for retrospective; commit subjects unchanged on merge. Audit trail has the latent gap.
- **(c) Senior amends only the commit message in this review note** (this finding documents the bundling for future audit-trail searches); junior does not rewrite history.

**Senior lean: (b)** — the bundling is cosmetic-level audit-trail concern, not a behavioral bug. Force-pushing history rewrites for cosmetics adds workflow friction; documenting the discrepancy here suffices for future audit. (a) is overkill; (c) is what this review does anyway.

**Severity 🟡:** documentation/audit-trail issue; not blocking, but architect should rule on whether to enforce subject-content alignment as a forcing function going forward.

---

## 🟢 (3 findings)

### G1 — Architect-routing Y1 absorbed faithfully

`AgentAppliesTo` has `default_factory` per the architect routing (`docs/process/reviews/P1.5/architect-routing.md`):

```python
applies_to: AgentAppliesTo = Field(
    default_factory=lambda: AgentAppliesTo(
        room_types=["*"],
        room_states=["*"],
    )
)
```

skeptic.yaml + prober.yaml NOT updated (default applies); P1.4 e2e tests continue without fixture changes. Brief lean restored exactly as routing prescribed.

### G2 — All 7 ADR-012 decisions implemented + 4 constitutional tests + StateTransitionMeta extension

- D1 (per-RoomType code-driven state machines): `rooms/state_machine.py` (312 LoC) ✓
- D2 (per-RoomType Literals): Research full 6-state + 4 scaffold 2-state ✓
- D3 (`applies_to` with `["*"]` sentinel + default_factory): G1 above ✓
- D4 (two-layer filtering): `decide_agents_for_room` updated; `run_turn` step 5 does dispatch-time `room_states` filter ✓
- D5 (separate `RoomRuntime`): `rooms/runtime.py` `run_turn` function (not inline in dispatch_turn) ✓
- D6 (StateTransitionMeta extension): `core/event.py` gains `prior_state: str = Field(min_length=1)` ✓
- D7 (4 constitutional tests): all 4 present with locked names in `tests/rooms/test_constitution.py` ✓

### G3 — Parallelism rule honored implicitly + state-machine pattern preserved end-to-end

Plan §3 directed P1.5-4 ‖ P1.5-5 ‖ P1.5-6 as parallel agents. Junior bundled P1.5-4 + P1.5-6 (one commit; ~1000 LoC) and split P1.5-5 (another commit; ~250 LoC) — effectively 2 logical units instead of 3. Acceptable interpretation given P1.5-4 and P1.5-6 both touch `rooms/` (more cohesion than the plan suggested) — the parallelism rule said "no shared mutable state"; bundling related work into one commit doesn't violate that. The rule's intent (parallel agents save wall-time) was honored even if the atomicity differs from plan.

Test counts (post-W-001 + W-002 + P1.4 + this impl):
- `tests/agents/test_schema.py`: 68 + class-method tests
- `tests/rooms/test_state_machine.py`: 21 tests (in classes)
- `tests/rooms/test_templates.py`: 14 tests
- `tests/rooms/test_runtime.py`: 9 tests (1 failing — R1 above)
- `tests/rooms/test_constitution.py`: 4 tests

Cycle stayed at 1 throughout (W-002-2 fix in effect; second consecutive P1.x task with end-to-end clean cycle counter).

---

## Architect-settled decisions — verification (per brief)

All 7 brief Architect-settled decisions honored:
- D1 (code-driven event-triggered): `rooms/state_machine.py` is pure code. ✓
- D2 (state machine integrates with dispatch_turn post-loop): `RoomRuntime.run_turn` orchestrates per ADR-012 D5. ✓
- D3 (`applies_to` shape `["*"]` sentinel): present in `AgentAppliesTo`. ✓
- D4 (5 RoomTypes — Research full + 4 scaffold): `templates.py` declares all 5. ✓
- D5 (ADR-012 yes): drafted + Accepted (`c496d52`). ✓
- D6 (workflow integration via single-ADR path β): plan frontmatter has `adr: ADR-012`; state advanced correctly through awaiting_architect_accept → awaiting_junior_impl. ✓
- D7 (cross-package layering): 4 constitutional tests landed; layering preserved. ✓

## Senior plan §5 push-backs — outcomes

All 8 push-backs aligned with brief leans + applied; all 4 self-discoveries surfaced and addressed:
- Push-backs 1-7 + architect-routing Y1 (default_factory): applied. ✓
- #8 cross-family R0-B: architect routed to skip; honored. ✓
- Self-discovery #1 (prior_state extension): landed in P1.5-3. ✓
- Self-discovery #2 (recency window N=50): pinned in `next_room_state` docstring. ✓
- Self-discovery #3 (cycles allowed): Research transition `exploration → divergence → exploration` permitted (no cycle-count enforcement). ✓
- Self-discovery #4 (empty-room is silent): `run_turn` step 5 yields empty `filtered` → `dispatch_turn(empty, ...)` returns `TurnResult(total_asked=0, ...)`. ✓

## Forcing functions applied

- **Constitutional tests**: 4 new in `tests/rooms/test_constitution.py`; all green individually. 25+ prior remain green individually.
- **6-category test-coverage**:
  - §1 cross-module: `test_integration_research_room_state_advance_and_agent_speaks` in test_runtime.py ✓
  - §2 N/A (correctly stated)
  - §3 N/A (correctly stated)
  - §4 exception payloads: `RoomStateError` tested ✓
  - §5 boundary validators: multi-position `["*"]` sentinel rejection in AgentAppliesTo ✓
  - §6 schema invariants: 68+ tests across new schemas ✓
- **5-surface scan**: P1.5-8 commit body — to be re-verified after R1 fix lands.
- **Tracking table**: present in each commit; P1.5-8 carries composite (verify Y1 bundling note in retro).
- **Workflow state machine**: cycle=1, no overrides; second consecutive clean P1.x cycle through impl.

## Verdict summary

P1.5 impl is **blocking** due to R1 (`test_state_transition_event_before_utterance` fails in full-suite). The bug is a real event-store ordering issue that affects ADR-012 D5's "transition before dispatch" invariant in observable behavior — not a flaky test that can be ignored. Junior must fix before R0-A dispatch.

Y1 (commit subject doesn't reflect bundled P1.5-4 content) is cosmetic audit-trail concern; architect rules whether to enforce subject-content alignment going forward.

The 3 🟢 confirmations show the architecturally-load-bearing work is correct: all 7 ADR-012 decisions implemented; architect routing Y1 (default_factory) absorbed faithfully; cycle counter stayed clean.

**Recommended path:**

1. **Junior fix R1 immediately** — senior lean is option (a) (`get_room_events` ORDER BY timestamp, id/ROWID for stable secondary ordering); junior may pick another option but must justify in commit body. Re-run full suite; confirm green; push fix commit to `claude/P1.5-impl`.
2. **Re-run senior plan-vs-impl** verdict-bump to `clean` after fix lands (RC-10 codified protocol).
3. **Architect-partner R0-A dispatch** on revised impl branch.
4. **Cross-family R0-B skipped per architect routing** (already settled in routing).
5. **Merge → close P1.5**.
6. **Y1 captured for P1.5 retro** as candidate forcing function: "commit subject must enumerate all task numbers whose content is in the commit body" — architect decides whether to graduate.

State-machine auto-trigger expectation: with current `verdict: blocking`, the harness routes to `awaiting_architect_decision` per ADR-008 D7. Architect picks routing path: most likely "junior fixes R1 → re-verdict clean → continue."
