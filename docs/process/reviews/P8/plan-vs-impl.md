---
task_id: P8
review_type: plan-vs-impl
reviewer: senior
cycle: 3
verdict: clean
rework_commits:
  - 62cf19a  # C3-1 (Y2-1) ADR-012 amendment wording (timestamp,id)→(timestamp,rowid)
  - cbe6324  # C3-2 (Y2-2) last_state_transition tiebreak → events[-1] rowid order
routing: "cycle-2 needs_architect (Y2-1 + Y2-2 → α; N-1 sorted-class sweep → deferred)"
plan: docs/process/senior-plans/P8.md
amendments: ["ADR-011 (P8 #6)", "ADR-012 (P8 #1)"]
---

# P8 plan-vs-impl — cycle 3 (final: Y2-1 + Y2-2 fixes) — verdict: clean

Both architect-routed α fixes are correctly and precisely implemented; the deferred
🔵 N-1 sorted-class sweep is correctly left untouched. No drift remains. **P8 is clean.**

## Rework deliverables — both correct

### C3-1 (Y2-1) — ADR-012 amendment wording corrected ✓
`ADR-012:534` (§ Amendment 2026-06-18 D1) changes *"folds … in `(timestamp, id)`
order"* → *"in `(timestamp, rowid)` insertion order (as `get_room_events` returns — the
last `state_transition` in the list)."* The Accepted ADR ink now matches the corrected
impl (`st_events[-1]`, C2-2) instead of the UUID-tiebreak ordering C2-2 proved buggy.
One-line amendment-text fix; no code touched.

### C3-2 (Y2-2) — `last_state_transition` tiebreak fixed + made consistent with `derive_room_state` ✓
`derived/snapshot.py` D2.5 block: the filter source changes `sorted_events`
(`sorted(events, key=(timestamp, id))`) → `events` (raw `(timestamp, rowid)` insertion
order from `get_room_events`), and the selection changes
`max(st_events, key=lambda e: (e.timestamp, e.id))` → `st_events[-1]`. This is exactly
right: `last_state_transition` now selects the genuinely most-recently-appended
transition by the same rowid insertion order `derive_room_state` uses, so a same-ms
`Snapshot` can no longer carry `room_state` ≠ `last_state_transition.new_state`. The
intra-snapshot divergence C2-2 had created is eliminated. The set of `STATE_TRANSITION`
events is identical under either source — only the tiebreak order changed — so no other
snapshot field is affected.

## Deferred / scope discipline — verified

- **🔵 N-1 (sorted-class sweep) correctly left deferred.** Per the architect routing
  (cycle-2: N-1 deferred), the 5 `sorted(…, key=(e.timestamp, e.id))` sites are
  **untouched**: `app.py:421/506/650/1643` (app.py has **zero** cycle-3 diff) and
  `snapshot.py:116` (verified unchanged — still `(timestamp, e.id)`, feeding the 9 other
  derivation predicates). The junior respected the deferral literally (no opportunistic
  bundling — the RC-19 discipline held).
- `sorted_events` remains used by 9 downstream predicates (D2.1–D2.x) → the C3-2 source
  switch introduced no unused-variable / behavior change elsewhere.
- **Scope is exactly the two routed fixes**: cycle-3 diff = ADR-012 (1 line) +
  `snapshot.py` (D2.5 block, 3 lines). Nothing else.

## Cross-cutting affirmations

- **Spine zero-diff** (gate / `_execute_local_call` / no new `LLMPurpose`); #5 split;
  ADR-025 byte-identical; #3 `eff_auto`, #7, #8 untouched.
- **P8-2 / P8-6 / P8-1** logic unchanged this cycle and remain clean (cycle-1/2 findings
  resolved). Both ADR amendments (ADR-011 #6, ADR-012 #1) now consistent with the impl.
- Gate-green re-verification is cycle-3 R0-A's lane; cycle-3 changes are a 1-line doc
  edit + a 3-line tiebreak alignment, both diff-level sound (R0-A confirmed GREEN at
  cycle-2; these strictly reduce a divergence).

## Verdict

**clean.** Y2-1 (amendment wording) and Y2-2 (`last_state_transition` tiebreak) are both
correctly fixed; the two ADR amendments now match the implementation; the deferred N-1
sorted-class sweep is consciously left untouched per architect routing. The full
cycle-1 → cycle-3 arc is resolved (B1/B2 gate-RED → green; Y1 column-authority → derived
at the material guards; Y2-1/Y2-2 ordering → consistent). No drift remains — P8 is ready
to proceed to merge.
