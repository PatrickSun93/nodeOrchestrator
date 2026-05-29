---
task_id: P1.6.5
round: R0-B
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 8
---

# P1.6.5 R0-B cross-family impl review (commit 5cd6f34)

## Lens preamble

Cross-family review at impl stage. Focus per `dual-lens-r0b.md`: runtime-integration lens — trace failure modes across module boundaries, verify D11 atomicity in actual code, check that the plan-stage external Y7 (conn-mismatch atomicity hazard) is truly absorbed, probe partial-state recovery paths. Claude-family reviewers (R0-A, plan-vs-impl) will cover spec-level correctness and plan-to-impl fidelity; this lens asks: *when does this break at runtime, and does the code know it?*

## External findings absorption — all verified

| Plan-stage finding | Absorption | Evidence |
|---|---|---|
| Y7 — conn-mismatch atomicity | 🟢 absorbed | `promotion.py:62`: `conn = event_store.conn` — no separate `conn` param; same-connection invariant unrepresentable-by-construction |
| Y8 — FK timing (merged → proxy Y3) | 🟢 absorbed | `store.py:86-88`: docstring correctly states "FK enforcement is INSERT-time" and "CREATE succeeds even if events/rooms tables don't exist" |
| Y9 — UNIQUE constraint | 🟢 absorbed | `store.py:57`: `promoted_from_hypothesis_id TEXT NOT NULL UNIQUE`; tested at `test_promotion.py:281-297` (`test_double_promote_unique_constraint`) |
| Y10 — layering guards | 🟢 absorbed (expanded) | 7 guards: agents, autonomy, core, derived, llm, rooms, skills — all 7 product packages covered; `workflow/` correctly excluded (dev harness) |
| Y11 — untested migration | 🟢 absorbed | `test_store.py:124-171`: `test_on_disk_migration` — creates on-disk DB, closes, reopens, runs `init_memory_schema`, verifies data preserved + new tables exist + `record_hypothesis` works |

Proxy findings (Y1-Y6) also absorbed: `DecisionMeta` uses `str | None` deliberate-duplication (Y1), `append_in_transaction` has `in_transaction` runtime guard (Y2), FK enforcement documented as INSERT-time (Y3), 7 layering guards (Y4), `Field(pattern=...)` prefix enforcement on `hypothesis_id`/`vk_id` (Y5), `record_hypothesis` producer-time existence check with batch path (Y6).

## 🟢 Observations

### 🟢 D11 atomicity: `append_in_transaction` guard + promotion ordering correct

`event_store.py:266-272`: the `in_transaction` guard prevents bare-call silent-data-loss. `promotion.py:99-128`: executes UPDATE first to start the transaction, THEN calls `append_in_transaction`, THEN INSERTs VK. The ordering deviation from plan (c→a→b instead of a→b→c) is well-documented in the commit message and the module docstring. Both `TestAppendInTransaction` (5 tests) and `TestPromoteHypothesisAtomicity` (3 tests) cover the guard, the rollback paths, and the double-promote UNIQUE backstop. The design is correct for the single-connection P1.6.5 model.

### 🟢 UNIQUE constraint on `promoted_from_hypothesis_id` — defense-in-depth verified

`store.py:57`: `UNIQUE` constraint is in the DDL. `test_promotion.py:281-297` (`test_double_promote_unique_constraint`) verifies the constraint catches double-promotion even when the API-level status check is bypassed (status reset to PENDING after first promotion). Two independent layers of enforcement: the Pydantic `status == PENDING` check AND the schema UNIQUE constraint. If a future cycle introduces a bug that skips the status check, the UNIQUE constraint catches it.

### 🟢 Migration test exercises on-disk path

`test_store.py:124-171`: `test_on_disk_migration` creates a temp-file DB, initializes only event_store tables, appends 3 events + 1 room, closes the connection, re-opens, runs `init_memory_schema(conn)`, and asserts both the new memory tables exist AND the existing data is preserved. This converts ADR-016 D5's migration claim from asserted to verified. The test also verifies `record_hypothesis` works against the migrated DB.

### 🟢 7/7 layering guards across all product packages

All 7 product packages (`agents`, `autonomy`, `core`, `derived`, `llm`, `rooms`, `skills`) have `*_does_not_import_memory` guards. The plan-stage concern (only 4 of 8 guarded) is fully addressed. `workflow/` (dev harness) correctly excluded.

### 🟢 `DecisionMeta` prefix-pattern enforcement at the schema layer

`event.py:153-154`: `Field(pattern=r"^hyp_[0-9a-f]{32}$")` and `Field(pattern=r"^vk_[0-9a-f]{32}$")` enforce ID prefix correctness at Pydantic validation time (earliest possible point in the write path). Three prefix-bypass tests cover: wrong prefix, event-id-style prefix, and empty string. The `@model_validator` co-presence check + prefix patterns close the integrity gap the proxy R0-B identified.

### 🟢 `record_hypothesis` batch-path existence check

`store.py:134-148`: implements two-path existence check — single `SELECT 1` per id for <3 `source_event_ids`, batched `SELECT id FROM events WHERE id IN (...)` for ≥3. `test_store.py:307-318` (`test_source_event_ids_batch_check_3plus`) exercises the batch path. The separate `source_event_id_existence_check_missing_raises` test verifies the early-return + no-row-inserted contract.

### 🟢 `promote_hypothesis` derives `conn` from `event_store` — Y7 fully absorbed

`promotion.py:44-45`: no `conn` parameter. `promotion.py:62`: `conn = event_store.conn`. The conn-mismatch atomicity hazard identified by the plan-stage external review is now structurally impossible — a caller cannot pass a different connection. This is the cleanest absorption: make the bug unrepresentable rather than guard against it.

### 🟢 `author="system"` on promotion event — design choice, not specified in plan

`promotion.py:82`: `author="system"`. The plan + ADR-016 D3 don't specify the promotion event's `author` field. The user identity is carried in `promoted_by_user_id` on the VK row. `author="system"` means the event log records the promotion subsystem as the actor; the VK row records who requested it. This is defensible (the system executed the promotion; the user confirmed it), but the architect may want to confirm the intent — `author="user"` would also be a reasonable choice given the user-confirm semantic.

## Net assessment

The implementation is clean. All 5 plan-stage external findings (Y7-Y11) and all 6 proxy findings (Y1-Y6) are absorbed. The `append_in_transaction` guard, UNIQUE constraint, migration test, layering guards, and prefix patterns are all present and tested. The D11 atomicity ordering (UPDATE-first) is correct and well-documented. 893 tests pass.

**Verdict: `clean`** — 0🔴 / 0🟡 / 8🟢. No net-new findings at the impl stage that require architect routing. The plan-stage cross-family external review paid for itself (5 🟡 caught at plan stage; all absorbed correctly at impl stage). No impl-stage cross-family concerns remain.

The 🟢 observation on `author="system"` is a design-choice confirmation point for the senior's plan-vs-impl review, not a finding requiring action.
