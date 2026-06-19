---
task: P8
cycle: 1
stage: plan
review: R0-A-on-plan
reviewer: architect-partner
verdict: clean
date: 2026-06-19
plan_reviewed: docs/process/senior-plans/P8.md @ 7724488 (revised — #5 split)
brief: docs/process/architect-briefs/P8.md
amendments_reviewed: ["ADR-012 §2026-06-18 (P8 #1)", "ADR-011 §2026-06-18 (P8 #6)"]
---

# R0-A-on-plan — P8 (revised: #2 / #6 / #1; #5 split out)

## Verdict: `clean`

The revised plan faithfully realizes the reconciled brief, the 2 ADR amendments
are sound + Proposed + committed, #5 is cleanly split (ADR-025 restored), and every
guardrail holds. Implementation-ready. **Recommend Accept** of the 2 amendments.

## Method

Verified the revised plan (`@7724488`) against the reconciled brief + `HEAD`
(spot-checked the cited sites) + the two amendment drafts.

## Findings — all confirmed

### Scope realization ✓
P8 = **P8-2 → P8-6 → P8-1** (serial, risk-ascending; all three edit `api/app.py` in
overlapping regions → single-junior serial, correct). **#5** (executor DoS / ADR-025
D6) is split to its own cycle, its ADR-025 amendment **withdrawn and ADR-025 restored**
(grep: zero P8 leftover in ADR-025 ✓). #7/#8 deferred (runtime-dead); #3/#4/#9/#10 are
absent from the plan (rejected).

### ADR amendments ✓ (Proposed, committed on `claude/P8-plan`)
- **ADR-012 §2026-06-18 (P8 #1)** — room state **derived** from the `state_transition`
  stream; `rooms.state` is a **derived cache, never authority** (upholds
  Rejected-Alternative-F / Principle 11); creation seeds the template
  `default_initial_state`. No new `EventType`/`LLMPurpose`/migration. Sound — matches
  the verified root cause (incl. the `_create_room` "open"-seed bug the intake missed).
- **ADR-011 §2026-06-18 (P8 #6)** — bound the **per-pass** re-dispatch reads; the
  **once-per-turn `next_room_state` snapshot stays full** (the deep-history guardrail);
  `MAX_SNAPSHOT_EXCERPT_CHARS=8000` cap untouched; additive `EventStore` surface
  (`count_room_events` + `get_room_events_since`), existing `get_room_events` unchanged.
  Sound.

### Citations spot-checked ✓
- **#1**: `_create_room` builds `_CoreRoom(id=…, type=body.type)` with **no `state=`**
  → defaults `"open"` (confirmed) — the root-cause seed bug.
- **#2**: `app.py:1085/1092/1097` init events/auth/pipeline schemas, **not**
  memory/reentry (confirmed).
- **#6**: `event_store.py:358` `get_room_events` "Return all events in a room" —
  unbounded (confirmed).

### Guardrails ✓
- **#3 `eff_auto` NOT touched** (§5b fences it — ADR-005 §4(c) / the P7 RC-19 class).
- **Spine-orthogonal**: #2 (schema init), #6 (read methods), #1 (room-state derivation)
  — none touch the gate / `_execute_local_call` / `LLMPurpose`; the only spine-adjacent
  defect (#5) is correctly split out.
- **#5 split clean** — ADR-025 restored to its pre-P8 text.

### Amendment-routing note (§5a) ✓ accurate
The plan correctly flags: `adr: [ADR-011, ADR-012]` routes P8 through
`awaiting_architect_accept` (`transitions.py:150`, `plan_has_adr=True`), but because
both are amendments to **already-Accepted** ADRs, `_read_adr_status` reads `"accepted"`
from the base `**Status:**` headers (`cli.py:136-162`, header-only/accepted-wins) — so
the accept gate **auto-passes on the next `advance`** rather than blocking on a
Proposed→Accepted flip (as a new ADR would). The architect's conscious review of the
amendment **text** is therefore not state-machine-enforced — the Accept act is that
conscious bless.

## 🔵 N-1 (minor — junior-impl detail, not a plan defect)
The #1 amendment leaves the column-maintenance mechanism slightly open
("`rooms.state` updated as a cache **or** derived on read"). The junior should pick
**one** consistently — derive-on-read is simplest and structurally cannot go stale.

## Bottom line
`clean` — 2 amendments sound, plan implementation-ready (serial P8-2 → P8-6 → P8-1),
spine-orthogonal. No `🔴`/`🟡`. Proceed to Accept + junior dispatch.
