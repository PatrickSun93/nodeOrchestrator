---
task_id: P2.5
round: plan-vs-impl
reviewer: senior
impl_commit: 1728c0d
verdict: clean
verdict_history:
  - verdict: clean
    at_commit: 1728c0d
    findings_count: { red: 0, yellow: 0, green: 3 }
    note: initial plan-vs-impl; faithful on every atomic + all four absorbed routing items (Y1 ARCHIVE_SUMMARY_RENDER + by-named-function guard, Y2 four-layer import guard, Y3 typed new_since_leave + first-visit=[], Y4 hygiene); 3🟢 (D3-vs-D7 produce_snapshot vestige, routing-absorption affirmation, impl-detail nits) — none blocking.
findings_count:
  red: 0
  yellow: 0
  green: 3
---

# P2.5 plan-vs-impl (senior) — room re-entry / 离开-回来追平 ("AI 记得我")

| Field | Value |
|---|---|
| Reviewer | senior (plan-vs-deliverable lens) |
| Plan | `docs/process/senior-plans/P2.5.md` (incl. the Y1–Y4 plan-stage absorption) |
| ADR | `docs/decisions/ADR-021-room-reentry-catchup.md` (Accepted) |
| Impl | `claude/P2.5-impl` @ `1728c0d` (P2.5-6 landing; atomics P2.5-2..6 at `907021f`,`8ea50a5`,`c2a4e05`,`04b5735`,`1728c0d`) |
| Verdict | **clean** — 0🔴 · 0🟡 · 3🟢 |

## Summary

Faithful implementation of the milestone — the first consumer of the read-side memory surface — across all six atomics and all four absorbed plan-stage routing items. The constitutional crux holds structurally: `assemble_reentry` (digest.py) and `derive_query_tags` are pure code with no `llm/` import; the only two LLM calls are content-gen renders (`REENTRY_DIGEST_RENDER` in `render.py`, `ARCHIVE_SUMMARY_RENDER` in `leave.py`), both `caller_agent_id=None`; and the two AST guards — keyed by named selection function (Y1-fix) + covering all four upstream layers (Y2) — are real-AST and **discriminating** (with self-tests, including one proving `leave.py`'s legitimate render is not false-tripped). `new_since_leave` is the typed `NewSinceLeaveItem` with first-visit→`[]` (Y3), and the e2e is source≠sink with exact-facts-by-label assertions and every cleanup case. No 🔴/🟡 — three 🟢, the most substantive being an ADR-internal D3-vs-D7 vestige (`produce_snapshot`), which the impl correctly resolved by following the D7 contract.

## Per-atomic verification

| Atomic | Delivered | Plan/ADR match | Evidence |
|---|---|---|---|
| P2.5-2 scaffolding | ✓ `907021f` | ✓ | `reentry/schema.py` — `NewSinceLeaveItem` + `ReentryDigest` + `ReentryResult`, all frozen + `extra="forbid"`, `new_since_leave: list[NewSinceLeaveItem]` (typed, Y3); `reentry/store.py` — `reentry_marker(room_id,user_id,last_seen_ts, PK)` + `init_reentry_schema` (same file, ADR-016 D5); both `LLMPurpose` values present; `memory/lookup.py::list_room_topic_tags` (deterministic union, sorted, no LLM, in `memory/`). |
| P2.5-3 leave-gen | ✓ `8ea50a5` | ✓ | `leave.py::record_leave_marker` (INSERT OR REPLACE, latest-wins); `generate_and_record_archive` **genuinely generates** `one_line_summary`/`spinoff_questions` via `ARCHIVE_SUMMARY_RENDER` (content-gen, in `reentry/`, outside `memory/`) → `record_project_archive`; `decision_log`/`duration_ms` code-derived; graceful JSON fallback. `derive_query_tags` correctly **not** here (Y1-fix). |
| P2.5-4 assemble | ✓ `c2a4e05` | ✓ | `digest.py::assemble_reentry` pure code (no `llm` import): tags→VK (skips lookup if no tags, never passes `[]`), entities (PREFERENCE-excluded), preferences, archive, marker diff → typed `new_since_leave`, **first-visit (`last_seen_ts is None`)→`[]`** (Y3), sorted `occurred_at` ASC; `derive_query_tags` here (Y1-fix). |
| P2.5-5 render + guards | ✓ `04b5735` | ✓ | `render.py::render_reentry_prose` (`REENTRY_DIGEST_RENDER`, system="phrase ONLY… add NO facts") + `reenter` (assemble→render→`ReentryResult`); `tests/reentry/test_constitution.py` — guard (i) 4 upstream layers (Y2), guard (ii) by named function (Y1-fix), both with discriminating self-tests. |
| P2.5-6 e2e + landing | ✓ `1728c0d` | ✓ | full leave→reenter e2e (source≠sink, exact facts by label, sorted diff, content-gen purpose asserted) + first-visit/no-archive/empty-memory/no-tags cleanup; handoff updated; 5-surface. |

ADR-021 accept-gate honest (Accepted). The no-LLM rglob stays scoped to `memory/`; `reentry/` legitimately imports `llm/`. Junior reports 1129 passed (+51 new), gates green.

## Findings

### 🟢 G1 — ADR D3 lists `produce_snapshot` as an assembly input, but D7's `ReentryDigest` has no snapshot field and the impl doesn't use it (impl correctly follows D7)

ADR-021 D3 (the assembly contract) names `produce_snapshot(events, room, snapshot_at=now)` "for current state" among the assembly inputs. But the `ReentryDigest` (D7) has **no** snapshot / current-state field, and `assemble_reentry` (digest.py:41-111) **does not call `produce_snapshot`** — it computes `new_since_leave` directly from the `events` param (`timestamp > last_seen_ts`). This is **not an impl gap**: the impl is faithful to the D7 *contract* (which has no snapshot field), and the milestone (recall VK + entities + prefs + archive + what's-new diff) is fully met without it. The `produce_snapshot` mention in D3 is **vestigial** — an ADR-internal D3-vs-D7 inconsistency the impl resolved correctly by following the contract. Non-blocking; optional cleanup: drop the `produce_snapshot` line from ADR-021 D3 (the digest never carried a snapshot), or, if "current room state" is later wanted in the catch-up, that is a `ReentryDigest`-field amendment + its own slice. No action needed for P2.5.

### 🟢 G2 — the four plan-stage routing items are all faithfully + discriminatingly implemented

- **Y1** — `ARCHIVE_SUMMARY_RENDER` is a real, distinct content-gen surface (`leave.py`, generates the archive semantics); `REENTRY_DIGEST_RENDER` is the re-entry render (`render.py`); `derive_query_tags` is in `digest.py` (the pinned canonical location); the LLM-free-selection guard is **by named function** — and its self-test `test_constitution_legitimate_render_calls_not_tripped` proves `leave.py`'s legitimate render is *not* false-tripped (function-scoped, not file-scoped). ✓
- **Y2** — `test_constitution_no_upstream_imports_reentry` covers `core/`+`memory/`+`derived/`+`llm/` (all four), real-AST, with a discriminating self-test. ✓
- **Y3** — `new_since_leave` is the typed `NewSinceLeaveItem` (fact_type Literal VK/event, ref_id, label, occurred_at); first-visit (`last_seen_ts is None`)→`[]` (digest.py:76 guard + the e2e `test_scenario_first_visit_no_marker_no_crash` asserting `== []`). ✓
- **Y4** — handled at the doc/PR layer (Q2 N/A + Q4 walk are plan/PR-commit hygiene, not code). ✓

### 🟢 G3 — sound impl details beyond the spec

`assemble_reentry` excludes `type=PREFERENCE` from `entities` (preferences are surfaced in their own field — avoids double-listing); `_parse_archive_summary` degrades gracefully on malformed LLM JSON (strips code fences, falls back); both render system prompts explicitly forbid adding facts (the prompt-enforced phrasing-only seam r0b-G2 flagged + the architect accepted for the MVP — correctly *not* hardened here, it is a recorded forward hook). The e2e's `test_scenario_no_tags_no_vk_lookup_no_value_error` is discriminating ("fails if `[]` is passed").

## Net

The implementation matches the plan + Accepted ADR-021 on every atomic and every absorbed routing item, with discriminating tests for the load-bearing constitutional invariants (the two AST guards) and the milestone behavior (exact facts by label, first-visit=[], no-tags-no-crash). The one substantive observation (G1) is an ADR-internal vestige the impl resolved by following the contract, not a defect. **Verdict: clean.** Per ADR-008 Amendment 1 (Route B), state auto-advances to `awaiting_R0_A` regardless; R0-A (+ R0-B, dual-lens dispatched) fire next — with a clean plan-vs-impl, the joint verdict turns on the external lenses.
