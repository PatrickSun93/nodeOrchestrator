---
task_id: P8
review_type: plan-vs-impl
reviewer: senior
cycle: 2
verdict: needs_architect
rework_commits:
  - 4a31deb  # C2-1 (B1) mypy import fix
  - ab9ac02  # C2-2 (B2) derive_room_state list-order tiebreak
  - 4aefc89  # C2-3 (Y1-alpha) two closed-guards derive
routing: "R0-A blocking (B1 mypy + B2 isolation) + Y1 column-authority → architect routed α(2 closed-guards)/β(defer _list_rooms)"
plan: docs/process/senior-plans/P8.md
amendments: ["ADR-011 (P8 #6)", "ADR-012 (P8 #1)"]
---

# P8 plan-vs-impl — cycle 2 (rework B1 + B2 + Y1-alpha) — verdict: needs_architect

The three routed fixes are **all correctly implemented**. Verdict is `needs_architect`
**not** for a rework defect but for **two adjacent drifts surfaced by the B2 fix** that
require architect routing: a now-incorrect line in the **Accepted ADR-012 amendment**,
and an **identical-bug-class residual** the B2 fix left in `produce_snapshot`'s sibling
`last_state_transition`.

## Rework deliverables — all correct

### C2-1 (B1, mypy) — fixed
`tests/api/test_context_schema.py:11` now imports `AppContext` from
`orchestrator.api.app` (canonical source) instead of `tests.api.conftest` (which
didn't re-export it). Resolves the deterministic `attr-defined` `mypy --strict` error
exactly as R0-A specified. One-line, in-scope.

### C2-2 (B2, test-isolation) — fixed, with a **sharper root-cause than R0-A's**
`derive_room_state` changes `max(st_events, key=lambda e: (e.timestamp, e.id))` →
`st_events[-1]`. **The junior's diagnosis is correct and better than R0-A's
"shared mutable global" hypothesis:** event ids are `evt_<uuid4hex>` (random, not
time-sortable), so on a same-millisecond timestamp collision the `(timestamp, id)`
tiebreak picked a non-deterministic "latest" → wrong derived state. `get_room_events`
yields `(timestamp ASC, rowid ASC)` insertion order, so `st_events[-1]` is the genuinely
most-recent transition. The co-run failure was timestamp collisions under fast
back-to-back tests (passes in isolation = distinct ms), **not** a leaking global. The
fix is correct; the docstring now pins the insertion-order contract. (Gate-green
re-verification is cycle-2 R0-A's lane; the fix is diff-level sound and addresses the
actual collision root cause.)

### C2-3 (Y1-alpha, closed-guards) — faithful to the architect routing
- `_writer_approve_helper` (`app.py:414`) and `_confirm_on_writer` cancel-path
  (`app.py:1633`): the `room.state == "closed"` raw-column guards become
  `derive_room_state(all_events, seed=room.state) == "closed"`. **Correctly reuses the
  `all_events = get_room_events(rid)` fetch that already sat 3 lines below each guard**
  (moved above the guard) — so **no new full-room read is introduced**, addressing
  R0-A's 🔵 N-2 efficiency note.
- `_list_rooms` (`app.py:1355`) is **untouched** — correct per the architect's β-defer
  routing (display, low-pri).
- New `TestClosedGuardsDeriveState` (2 tests) verifies both guards return
  `room_closed` (422 / `_ConfirmAppendError`) when the room is derived-closed but the
  column is stale. Good direct coverage of the fixed invariant.

This realizes the ADR-012 amendment's "column never authority where stale" at the two
material (correctness) guards, exactly as routed.

## 🟡 Two adjacent drifts the B2 fix surfaced (architect routing)

### Y2-1 — the **Accepted ADR-012 amendment wording is now incorrect**
ADR-012 § "Amendment 2026-06-18 (P8 #1)" D1 (`ADR-012:534`) still reads: *"folds the
room's `state_transition` events … **in `(timestamp, id)` order**, returning the latest
`new_state`."* C2-2 correctly proved `(timestamp, id)` is **non-deterministic and
incorrect** and switched the impl to insertion / `(timestamp, rowid)` order. So the
**Accepted ADR ink now states the very ordering the impl rejects as a bug.** The
amendment wording should be corrected to "in `(timestamp, rowid)` insertion order (as
`get_room_events` returns), i.e. the last `state_transition` in the list." **Architect
routing:** this is a correction to Accepted ADR text (RC-3 — senior does not self-edit
Accepted ink); recommend α (one-line amendment-wording fix).

### Y2-2 — **identical-bug-class residual in `produce_snapshot`'s sibling field**
C2-2 fixed `derive_room_state` (which feeds `Snapshot.room_state`) but the **same
`(timestamp, id)` UUID tiebreak survives 15 lines away in the same module** —
`derived/snapshot.py:188`: `last_st = max(st_events, key=lambda e: (e.timestamp, e.id))`
for `Snapshot.last_state_transition`. After C2-2, on a same-ms collision the same
`Snapshot` can carry `room_state` (list-order, **correct**) that **disagrees** with
`last_state_transition.new_state` (UUID-order, **buggy**) — an intra-snapshot
inconsistency newly created by fixing only one of the two. The tiebreak is pre-existing
(not P8-authored), but it is exactly the bug-class B2 just fixed. **Architect routing:**
α (apply the same `st_events[-1]` fix to `last_state_transition` for consistency — the
fetch is already sorted there) vs β (defer as pre-existing, accept the divergence).
My lean: **α** — it's the identical one-line fix and removes a live room_state ≠
last_state_transition divergence.

## Cross-cutting affirmations

- **Spine zero-diff** across all three rework commits (gate / `_execute_local_call` /
  no new `LLMPurpose`); #5 remains split out; ADR-025 still byte-identical to pre-P8.
- **P8-2 / P8-6** unchanged this cycle and remain clean (cycle-1 finding).
- **Scope discipline held:** `_list_rooms` β-deferred (not touched); #3 `eff_auto`,
  #7/#8 untouched; no new full-room reads added (N-2 respected).

## Verdict

**needs_architect.** The routed rework (B1 + B2 + Y1-alpha) is **correctly and
faithfully implemented** — B2's root-cause is in fact sharper than R0-A's hypothesis,
and Y1-alpha reuses the existing fetch (no N-2 regression). The verdict is
`needs_architect` solely for the **two adjacent drifts the B2 fix exposed**: (Y2-1) the
Accepted ADR-012 amendment now mis-states the ordering as `(timestamp, id)` and should
be corrected; (Y2-2) the identical `(timestamp, id)` tiebreak survives in
`produce_snapshot`'s `last_state_transition`, creating a same-ms `room_state` ≠
`last_state_transition` divergence. Both are one-line α fixes per my lean; the architect
routes. Per the senior boundary I surface with evidence and do not fix here.
