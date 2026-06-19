---
task: P8
cycle: 2
stage: impl
review: R0-A
reviewer: architect-partner
verdict: needs_architect
date: 2026-06-19
impl_reviewed: claude/P8-impl @ 2f9cfe7 (rework C2-1 4a31deb / C2-2 ab9ac02 / C2-3 4aefc89)
supersedes: cycle-1 R0-A (verdict blocking — B1 + B2 now resolved)
---

# R0-A (impl) — P8 cycle 2 (rework B1 + B2 + Y1-α)

## Verdict: `needs_architect`

**The gate is now GREEN** — my cycle-1 blocking findings (B1 mypy + B2 pytest) are
both resolved, and the three routed fixes (C2-1/C2-2/C2-3) are correct. Verdict is
`needs_architect` (converging with the senior cycle-2 plan-vs-impl) **solely for the
two adjacent drifts the B2 fix surfaced** — plus an independent 🔵 bug-class sweep.
No rework defect remains.

## Gate — GREEN (the cycle-1 blocking resolution, re-verified by me)
`uv sync --all-extras` → ruff format ✓ / ruff check ✓ / **mypy: Success, 0 issues /
312 files** (B1 resolved) / **pytest: exit 0, all pass** (B2 resolved). The two
cycle-1 🔴 are closed.

## Rework deliverables — all correct
- **C2-1 (B1, mypy) ✓** — `test_context_schema.py:11` now imports `AppContext` from
  `orchestrator.api.app` (canonical source); the `attr-defined` error is gone.
- **C2-2 (B2) ✓ — and my cycle-1 root-cause was wrong; the junior's is right.** I
  characterized B2 as a "shared mutable global leak." It is **not**. `derive_room_state`
  used `max(st_events, key=(timestamp, e.id))`, and `e.id` is `evt_<uuid4hex>` (random,
  not time-sortable) → on a same-millisecond collision the tiebreak picked a
  non-deterministic "latest" → wrong derived state (full-suite fast same-ms exposed it;
  isolation hid it — *looked* like flakiness, was a determinism bug). C2-2's
  `st_events[-1]` (using `get_room_events`' `(timestamp, rowid)` insertion order) is
  correct and the docstring now pins the contract. **I under-diagnosed at cycle-1.**
- **C2-3 (Y1-α guards) ✓** — both closed-guards (`app.py:414`, `:1633`) now
  `derive_room_state(all_events, …) == "closed"`, **reusing the adjacent
  `get_room_events` fetch (no new full read — N-2 respected)**; `_list_rooms:1355`
  untouched (β-deferred); 2 new `TestClosedGuardsDeriveState` tests cover the invariant.

## 🟡 Two adjacent drifts (needs_architect — converges with senior plan-vs-impl)
- **Y2-1 — the Accepted ADR-012 amendment wording is now wrong.** §Amendment-2026-06-18
  D1 (`ADR-012:534`) still says "folds … in `(timestamp, id)` order" — the exact ordering
  C2-2 proved buggy. **I accepted this wording at cycle-1 R0-A-on-plan — I missed the
  UUID-tiebreak too** (as did the senior who drafted it; the junior caught it). Fix:
  "(timestamp, rowid) insertion order (as `get_room_events` returns) — the last
  `state_transition` in the list." Architect routes (Accepted-ink correction, RC-3).
  **Lean: α (one-line).**
- **Y2-2 — the same bug-class survives in `produce_snapshot`'s sibling field.**
  `snapshot.py:191` `max(st_events, key=(e.timestamp, e.id))` for `last_state_transition`
  — the **identical** UUID tiebreak. After C2-2, a same-ms `Snapshot` can carry
  `room_state` (list-order, **correct**) ≠ `last_state_transition` (UUID-order, **buggy**)
  — an intra-snapshot divergence C2-2 created by fixing only one of the two. Pre-existing,
  but now live. **Lean: α (same one-line `st_events[-1]` fix — events already sorted
  there)** / β (defer as pre-existing). Architect routes.

## 🔵 N-1 (bug-class sweep — independent of the senior's two)
The `(timestamp, e.id)` UUID-tiebreak class also appears in **5 `sorted(…, key=(e.timestamp,
e.id))` sites** — `app.py:421/506/650/1643`, `snapshot.py:116` — which re-sort by UUID for
same-ms ties, diverging from `get_room_events`' canonical `(timestamp, rowid)` order. These
are **pre-existing + latent**: a mis-tied `sorted()` is observable only if a consumer relies
on same-ms *insertion* order (unlike the `max()` cases, which pick the wrong "latest"). So
the bug-class is **not fully contained** by C2-2 + Y2-2. Not blocking, not P8-introduced —
flagging so a sweep (`(timestamp, id)` → `(timestamp, rowid)` / `get_room_events` order
everywhere) vs defer is a **conscious** architect choice, not an unseen gap.

## Affirmations
- Spine zero-diff (gate / `_execute_local_call` / no new `LLMPurpose`); #5 split;
  ADR-025 byte-identical; #3 `eff_auto` / #7 / #8 untouched; P8-2 / P8-6 unchanged + clean.

## Bottom line
`needs_architect`: gate GREEN (B1 + B2 resolved), rework correct. Route **Y2-1**
(amendment wording, α) + **Y2-2** (snapshot tiebreak, α/β); decide the **🔵 sorted-class**
sweep-vs-defer. All are one-liners or a scoped hygiene call — no blocking defect remains.
