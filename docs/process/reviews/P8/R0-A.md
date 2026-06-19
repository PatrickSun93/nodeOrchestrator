---
task: P8
cycle: 3
stage: impl
review: R0-A
reviewer: architect-partner
verdict: clean
date: 2026-06-19
impl_reviewed: claude/P8-impl @ 5cab972 (rework C3-1 62cf19a / C3-2 cbe6324)
supersedes: cycle-2 R0-A (needs_architect — Y2-1 + Y2-2 now resolved)
---

# R0-A (impl) — P8 cycle 3 (final: Y2-1 + Y2-2) — verdict: `clean`

## Verdict: `clean`
Both architect-routed α fixes (Y2-1 + Y2-2) are correct; the deferred 🔵 N-1 sorted-class
sweep is correctly left untouched; the gate is **GREEN**. The full cycle-1→3 arc is
resolved. **P8 is ready to merge.**

## Gate — GREEN (re-verified)
`uv sync --all-extras` → ruff format ✓ / ruff check ✓ / **mypy: 0 issues / 312 files** /
**pytest: exit 0**.

## Fixes — both correct
- **Y2-1 (C3-1)** — `ADR-012 :534` (§Amendment 2026-06-18 D1) now reads "(timestamp, rowid)
  insertion order (as `get_room_events` returns — the last `state_transition` in the list)";
  the Accepted ink matches the C2-2 impl. ✓
- **Y2-2 (C3-2)** — `derived/snapshot.py` D2.5: the filter source changed
  `sorted_events` → **raw `events`** (insertion `(timestamp, rowid)` order from
  `get_room_events`), and `max(st_events, key=(timestamp, e.id))` → `st_events[-1]`.
  **This avoids the no-op I flagged at cycle-2** — `st_events[-1]` *from the UUID-sorted
  `sorted_events`* would have equalled the buggy `max`; taking it from raw `events` is what
  makes it correct. `last_state_transition` is now consistent with `derive_room_state`, so a
  same-ms `Snapshot` can no longer carry `room_state` ≠ `last_state_transition`. ✓ (Catch heeded.)

## N-1 deferred — correctly untouched
The 5 `sorted(…, key=(e.timestamp, e.id))` sites are untouched per the architect's N-1-defer
routing; no opportunistic bundling (RC-19 discipline held). `snapshot.py:116`'s sort still
feeds its 9 other derivation predicates unchanged.

## Full arc resolved (cycle 1 → 3)
- **cycle-1**: gate-RED (B1 mypy + B2 isolation) caught; Y1 column-authority drift surfaced.
- **cycle-2**: B1 + B2 fixed (B2 root-cause = UUID tiebreak — sharper than my cycle-1 hypothesis);
  Y1-α (closed-guards derive); Y2-1 / Y2-2 surfaced + routed.
- **cycle-3**: Y2-1 (amendment wording) + Y2-2 (snapshot tiebreak) fixed; N-1 deferred.

## Affirmations
Spine zero-diff (gate / `_execute_local_call` / no new `LLMPurpose`); #5 split out; ADR-025
byte-identical; #3 `eff_auto` / #7 / #8 untouched; ADR-011 + ADR-012 amendments now consistent
with the implementation.

## Bottom line
`clean` — all routed fixes correct, gate green, no drift remains. Ready for PR merge → close.
