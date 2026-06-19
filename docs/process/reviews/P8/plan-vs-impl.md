---
task_id: P8
review_type: plan-vs-impl
reviewer: senior
cycle: 1
verdict: needs_architect
impl_commits:
  - adcddce  # P8-2 memory+reentry schema init
  - 853ea23  # P8-6 bounded per-pass snapshot read (ADR-011 Amdt)
  - 352f1f3  # P8-1 derive room state + create-seed (ADR-012 Amdt)
plan: docs/process/senior-plans/P8.md
brief: docs/process/architect-briefs/P8.md
amendments: ["ADR-011 (P8 #6)", "ADR-012 (P8 #1)"]
---

# P8 plan-vs-impl — verdict: needs_architect

Verdict formed **independently** from a diff-level read of the three atomics
against `senior-plans/P8.md` + the two ADR amendments, before any R0-A. Two atomics
are clean; **P8-1 implements its named acceptance surface faithfully but drifts on a
plan-implied invariant** (the ADR-012 amendment's "column = derived cache, never
authority") at three unenumerated column-readers — one routing call for the architect.

## Per-atomic audit

### P8-2 — `_build_context` + fixture memory/reentry schema (adcddce) — clean

- `init_memory_schema(writer_conn)` then `init_reentry_schema(writer_conn)`, placed
  after `_init_pipeline_schema` (so after `init_schema` → auth → pipeline), on the
  **writer** conn, via the existing local-import idiom. FK order memory→reentry
  preserved. Mirrored into `tests/api/conftest.py`'s `ctx` fixture.
- New `tests/api/test_context_schema.py`: asserts `hypothesis` / `verified_knowledge`
  / `reentry_marker` present on the built context, and double-init idempotency.
- **Acceptance met.** No dead-subsystem internals touched (#7/#8 untouched). Spine
  zero-diff.

### P8-6 — bounded per-pass snapshot read [ADR-011 Amdt] (853ea23) — clean

- `EventStore` gains `count_room_events` (`COUNT(*)`) + `get_room_events_since`
  (`… ORDER BY timestamp ASC, rowid ASC LIMIT -1 OFFSET ?`); existing
  `get_room_events` byte-identical. Same ordering contract → exact parity with
  `len(...)` / `[cursor:]`.
- Migrations are exactly the per-pass re-dispatch hot callers: pure-count `len(...)` →
  `count_room_events` (`app.py:1474,1486,1545`; `runner.py:146,187`); pure-tail
  `[cursor:]` → `get_room_events_since` (`app.py:1505,1529,1561,1572`;
  `runner.py:157,178,225`). Line numbers shifted +~5 from the plan's by the P8-2
  insertion — same logical sites.
- **Full-read callers untouched** (verified by the changed-file set =
  event_store/app/runner only): the once-per-turn `next_room_state` snapshots
  (`rooms/runtime.py:104`, `agents/dispatch.py:80`), the executor dedup/result scans
  (`tools/executor.py:114,308`), and the approval/discovery scans
  (`app.py:417,482,502,646`) — deep-history correctness preserved per the amendment.
- `MAX_SNAPSHOT_EXCERPT_CHARS` untouched; spine zero-diff; parity tests added.
- **Acceptance met.** (Nit, non-blocking: the commit-message prose says
  "api/app.py (5 sites)" while the table + code show 7 = 3 count + 4 since — message
  prose only, code is correct.)

### P8-1 — derive room state + create-seed [ADR-012 Amdt] (352f1f3) — named sites met; 🟡 invariant drift

**Faithful at the plan's named sites:**
- `derive_room_state(events, seed)` (`rooms/state_machine.py`) — pure, folds
  `StateTransitionMeta.new_state` by `(timestamp, id)` asc, returns latest or `seed`;
  matches the amendment + `snapshot.py:185–196`'s existing last-transition logic.
- `_create_room` seeds `ROOM_TEMPLATES[type].default_initial_state` (`"setup"`), not
  the model default `"open"` (`app.py:1343`). ✓
- `_write_and_turn` derives at turn entry and `model_copy`s the room with the derived
  state, which flows into `select_dispatch_agents` (so `rooms/runtime.py:59,63` sees
  derived state without touching runtime.py). ✓
- `produce_snapshot` emits `derive_room_state(events, seed=room.state)`
  (`snapshot.py:211`). ✓
- Test (`tests/api/test_room_state_derive.py`) drives the **real cross-turn HTTP path**
  via `TestClient` (POST /rooms seeds setup for all 5 types; snapshot derives
  `exploration` after a transition; cross-turn derive picks up the transitioned
  state) — **not** the in-memory `Room(state=…)` rebuild that masked the bug. ✓

**🟡 Drift on the plan-implied invariant — column read as authority at 3 unenumerated sites.**
The ADR-012 amendment inscribes *"the `rooms.state` column … is **never read as
authority** where it could be stale."* The impl makes the column **write-once** — it
is seeded at create and **never updated** (the in-memory `model_copy` is not
persisted; the test asserts this is deliberate: *"the rooms.state column still reads
'setup' (never updated — deliberate)"*). Derivation is applied at the dispatch +
snapshot sites the plan named, but **three other readers still read the raw, now-
permanently-stale column as authority**:
  1. `_writer_approve_helper` `app.py:414` — `room = get_room(rid); if room.state ==
     "closed": return _ApproveSkipped("room_closed")`. A room that is **derived-closed**
     (a `state_transition`→`closed` event) has column ≠ `"closed"`, so the guard does
     **not** fire → a tool approval proceeds on a logically-closed room.
  2. confirm cancel path `app.py:1633` — same `get_room` + `room.state == "closed"`
     guard, same stale read.
  3. `_list_rooms` `app.py:1355` → `list_rooms()` returns the column state → the GUI
     room list shows the **seed** state forever, never the derived current state.

This staleness is **pre-existing** (the column was never updated before P8 either,
so P8-1 does not *regress* these sites), but P8-1 (a) **cements** the column as
write-once and (b) **inscribes** the "column = derived cache, never authority"
contract — so these three readers now *contradict the freshly-laid ink*. The plan's
acceptance criterion #3 scoped the invariant to "(dispatch + snapshot sites)", which
the impl meets; the **broader amendment invariant** is what these sites violate.

**This is an architect routing call (I do not decide it):**
- **α (expand):** derive at the two `"closed"` guards (correctness) and/or
  `_list_rooms` (display) in this cycle or an immediate follow-on — the guards are
  the material ones.
- **β/defer:** accept the pre-existing staleness as a known gap and narrow the
  ADR-012 amendment's wording to "dispatch + snapshot sites" (matching the plan's
  scoping), tracking the guards as a separate slice.

### 🟢 P8-1 seed-source (non-blocking observation)

Both call sites pass `seed=room.state` (the column), not the template
`default_initial_state` the plan and the reducer's own docstring describe as the
post-fix convention. **Benign for new rooms** — the column is now correctly seeded
`"setup"` and never mutated, so `seed=room.state` ≡ the template default whenever
there are zero transition events (the only case the seed is consulted). It differs
only for **legacy column-wrong rooms** (column `"open"`, no transitions), which the
brief scopes out ("none exist in prod"). Seeding from the template default would
self-heal such rooms; the current form would not. No action required unless legacy
rooms surface.

## Cross-cutting

- **Spine zero-diff** across all three (gate / `_execute_local_call` / no new
  `LLMPurpose`) — #5, the only spine-adjacent change, was split out (architect
  2026-06-18), and nothing here touches the spine.
- **Out-of-scope items fenced:** #7/#8 (runtime-dead) untouched; #3 `eff_auto`
  no-floor untouched (RC-19 class); ADR-025 restored byte-identical (the withdrawn #5
  amendment).
- **Amendments consumed correctly:** ADR-011 Amdt (bounded read) ↔ P8-6; ADR-012 Amdt
  (derive-from-events) ↔ P8-1, with the invariant-scope gap noted above.

## Verdict

**needs_architect.** P8-2 + P8-6 are clean. P8-1 meets its named acceptance surface
(create-seed + derive at dispatch/snapshot, cross-turn HTTP test) but the ADR-012
amendment's "column never authority where stale" invariant is violated at three
unenumerated column-readers — two `"closed"` gate guards (correctness) and the rooms
list (display) — now made permanent by the deliberate write-once column. **The
architect routes α (extend derivation to the guards / list) vs β (narrow the
amendment wording + defer).** Per the senior plan-vs-impl boundary I surface the drift
with evidence and do not fix it here. The 🟢 seed-source note is advisory only.
