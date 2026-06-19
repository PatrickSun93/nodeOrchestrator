---
task: P8
cycle: 1
stage: impl
review: R0-A
reviewer: architect-partner
verdict: blocking
date: 2026-06-19
impl_reviewed: claude/P8-impl @ d149197 (atomics adcddce P8-2 / 853ea23 P8-6 / 352f1f3 P8-1)
plan: docs/process/senior-plans/P8.md
---

# R0-A (impl) — P8 (#2 / #6 / #1)

## Verdict: `blocking`

The gate is **RED** — a deterministic `mypy` error + a reproducible test-isolation
failure (two room-state tests). These must be fixed before merge. **Separately**, I
independently confirm the senior plan-vs-impl's P8-1 column-authority drift (🟡
needs_architect routing). P8-2 + P8-6 logic is otherwise sound, and P8-1's derivation
logic itself is correct (its test passes in isolation).

## Method

Reviewed the diff per atomic **and ran the full gate myself** (`uv sync --all-extras`
→ ruff → `mypy --strict` → `pytest`). The junior commit (Q-block) **and** the senior
plan-vs-impl both report gates green / "cross-turn HTTP test ✓"; **they are not** — the
gate is red. (This is the independent-R0-A value: I ran it, the prior reviews did not
reproduce it.)

## 🔴 Blocking — the gate is RED

### B1 — `mypy` error (deterministic) — P8-2 test import
`tests/api/test_context_schema.py:11` does `from tests.api.conftest import AppContext`,
but `conftest` does not explicitly re-export it →
`error: Module "tests.api.conftest" does not explicitly export attribute "AppContext"
[attr-defined]` (1 error, `mypy --strict`; `ruff` is clean). **Fix:** import
`AppContext` from its canonical source (as `tests/api/test_auto_fire.py:30` and others
do), or add an explicit re-export to `conftest`. Cheap + deterministic.

### B2 — `pytest` test-isolation failure (reproducible) — 2 room-state tests
Full suite fails:
`tests/api/test_room_state_derive.py::…::test_cross_turn_http_path_decision_triggers_state_transition`
and `tests/integration/test_p1_6_e2e.py::…snapshot_pending_to_closed`. Both **pass in
isolation**; the cross-turn test **reproduces the failure when its file is co-run** with
`test_p1_6_e2e.py` →
`AssertionError: Expected diagnosed→fix_proposed transition event … none found.
derive_room_state was not used on the HTTP path`. So it is a **test-isolation / ordering
bug** — a shared mutable global (most likely the LLM stub / agent config / room registry)
leaking from an earlier test, so the agent does not produce the expected
`diagnosed→fix_proposed` transition (and the test then reads "derive not used").
**The derivation logic is NOT the bug** — the test passes alone, so P8-1's
`derive_room_state` + HTTP wiring work; this is test-hygiene. **Fix (junior):** isolate
the shared state (fresh stub / fixture per test; verify with the file-level co-run
above). Gate stays red until green.

## 🟡 Y1 (needs_architect — converges with the senior plan-vs-impl) — P8-1 column-authority drift

Independently verified. The just-Accepted **ADR-012 amendment** inscribes "the
`rooms.state` column is **never read as authority** where it could be stale." P8-1 makes
the column **write-once** (derived state is `model_copy`'d in-memory at
`app.py:1484-1487`, never persisted) and derives only at the 2 named sites (dispatch +
snapshot). **Three unenumerated readers still read the raw, now-permanently-stale column
as authority:**
- `_writer_approve_helper` `app.py:414` `if room.state == "closed"` — **correctness**:
  a derived-closed room's guard never fires → a tool approval proceeds on a
  logically-closed room.
- confirm-cancel `app.py:1633` — same stale closed-guard.
- `_list_rooms` `app.py:1355` — **display**: the GUI room list shows the seed state forever.

This is my R0-A-on-plan **🔵 N-1** ("pick ONE derive mechanism consistently") realized as
a defect — the impl half-applied derive-on-read.

**Architect routing (I don't decide):**
- **α (extend derivation):** the 2 `"closed"` guards (correctness, material) ± `_list_rooms`
  (display). **Low cost** — the full event list is already fetched 3 lines below each guard
  (`app.py:417`, `:1636`), so deriving there is local.
- **β (narrow + defer):** scope the ADR-012 amendment wording to "dispatch + snapshot
  sites" (matching plan acceptance #3) + track the guards as a separate slice.

**My lean: α for the 2 closed-guards** (correctness — the freshly-laid "never authority"
ink shouldn't be contradicted by safety guards); β-ish for the list (display, low-pri).
Your call.

## 🔵 N-2 (efficiency, non-blocking)
P8-1 adds a per-turn full `get_room_events(rid)` at `app.py:1484` solely to derive (fold
for the latest `state_transition`) — a new full-room read per turn, in mild tension with
P8-6's read-bounding. Could be a bounded "latest `state_transition`" query. Relevant if α
extends derivation (do it via a bounded helper, not repeated full reads).

## Affirmations
- **P8-2** schema-init logic correct (FK order memory→reentry, after `init_schema`,
  idempotent, fixture mirrored) — modulo B1's test import.
- **P8-6** bounded-read logic correct (additive `count_room_events` /
  `get_room_events_since`, parity, full-read deep-history callers preserved).
- **Spine zero-diff** (gate / `_execute_local_call` / no new `LLMPurpose`); **#3 `eff_auto`
  untouched** (RC-19 class); **#7/#8 untouched**; **ADR-025 restored** byte-identical.
- P8-1 derivation logic + cross-turn HTTP wiring correct (passes in isolation).

## Bottom line
`blocking`: fix B1 (mypy import) + B2 (test isolation) to green the gate; route Y1
(column-authority drift) α/β. B1/B2 are junior fixes; Y1 is your routing call — both land
in the rework cycle.
