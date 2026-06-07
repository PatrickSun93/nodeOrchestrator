---
task_id: P4.6
review: plan-vs-impl
stage: impl
reviewer: senior planner
verify_base: "claude/P4.6-impl @ 1f34a3b (commits P4.6-1..7; plan-land base b224c40); senior-plans/P4.6.md + ADR-040 + live impl code re-read this review"
verdict: clean
findings_count: 3
gates:
  ruff: pass
  mypy: "pass (files=src,tests; 278 source files, no issues)"
  pytest: "pass (2259 passed, 0 failed; full suite, -p no:warnings; targeted auto_fire+constitution 22 passed)"
date: "2026-06-07"
---

# Senior plan-vs-impl — P4.6: COUNTDOWN auto-fire-on-timer

**Lens:** the non-overlapping audit surface only the senior holds — *did the impl drift on a plan-implied invariant while still satisfying the acceptance criteria?* (external reviewers see deliverable-vs-spec; senior sees plan-vs-deliverable.) Checked against `senior-plans/P4.6.md` §2 (the six-field atomics) + the four contract-absorbed findings (F1 helper-span / F2 fresh-window re-arm / A2 enabled-gates-both-paths / F3 exact-field-set pins).

**Verdict: clean.** All six impl atomics (P4.6-1..5, P4.6-6+7) faithfully realize the plan; no acceptance criterion unmet, no plan-implied invariant drifted. Three 🟢 observations (non-blocking, no routing) below. **Route nothing.**

**Process note (FYI, not a finding):** R0-A (impl) + R0-B (impl) already landed `clean` in this same shared worktree (parallel dispatch). Senior plan-vs-impl normally precedes reviewer dispatch; here the architect ran the three concurrently. Recorded for awareness only — no action.

---

## Per-atomic verification

### P4.6-1 — auto-fire config (opt-in OFF) + AppContext + thread to dispatch ✅
- **What/Where:** `CountdownAutoFireConfig` (`autonomy/config.py`) frozen, `extra="forbid"`, `window_s/sweep_interval_s ≥ 1`, `0 ≤ reversibility_floor ≤ 10`; loader fail-closed; `config/autonomy.yaml § countdown_auto_fire`; threaded `AppContext → run_turn → dispatch_turn → process_tool_calls` and read by the sweeper from `ctx.countdown_auto_fire`.
- **Acceptance:** (1) absent file ⇒ `CountdownAutoFireConfig()` (disabled) ✓; (2) malformed section ⇒ `raise ValueError` (refuse-start, never silently enabled) ✓; non-mapping top level also raises ✓; (3) single bootstrap source reaches both `process_tool_calls` (via thread) and the sweeper (via `ctx`) ✓; (4) cross-field bounds at Pydantic time ✓; (5) gates green ✓. `AppContext.countdown_auto_fire` defaults to a disabled instance ⇒ existing tests' implicit-OFF byte-compat preserved.

### P4.6-2 — durable `expires_at` + stamp at gate time ✅
- **What/Where:** additive nullable `expires_at: TimestampMs | None = None` on `ToolCallPendingMeta` (`core/event.py:367`); stamp in `process_tool_calls`' COUNTDOWN/HARD `else`.
- **Acceptance:** (1) HARD ⇒ `None` (stamp only in `tier == COUNTDOWN_CONFIRM` branch) ✓; (2) disabled / `cfg is None` ⇒ `None` ✓; (3) `reversibility < floor` ⇒ `None` ✓; (4) COUNTDOWN+enabled+`≥floor` ⇒ `pending_ts + window_s*1000` — **note the impl captures `pending_ts = now_ms()` once and uses the *same* value for the event `timestamp` and the deadline base**, so `expires_at == pending.timestamp + window_s*1000` holds **exactly** (not an approximate second sample) ✓; (5) gate byte-frozen — `git diff b224c40..HEAD` on `scoring.py`+`emission.py` is empty; stamp runs strictly after the tier decision ✓; (6) field pinned by P4.6-6(i) ✓; (7) no new `LLMPurpose` (diff grep empty) ✓. `reversibility` read from the existing `tools` dict — no new data source ✓.

### P4.6-3 — `approval_source` provenance + human path sets `"human"` ✅
- **What/Where:** additive nullable `approval_source: Literal["human","auto_timer"] | None = None` on `ToolCallMeta` (`core/event.py`); HTTP approve sets `"human"`.
- **Acceptance:** (1) human approve ⇒ `approval_source="human"`, `approver_user_id` from principal (unchanged) ✓; (2) legacy/AUTO_EXECUTE events ⇒ `None` (additive nullable) ✓; (3) `approver_user_id` + still-pending scan byte-unchanged (scan keys on type+call_id) ✓; (4) schema + confirm tests green ✓.

### P4.6-5 — room-enumeration read API ✅
- **What/Where:** `EventStore.list_room_ids() -> list[RoomId]` (`event_store.py`), `SELECT id FROM rooms ORDER BY created_at ASC`.
- **Acceptance:** (1) populated ⇒ all ids ✓; (2) empty ⇒ `[]` ✓; (3) read-only (no writes; runs on reader conn — verified by `test_list_room_ids_read_only`) ✓; (4) unit-tested ✓; (5) lands before P4.6-4 in commit order ✓.

### P4.6-4 — shared writer-approve helper + durable sweeper ✅ (the core; checked hardest)
- **Helper extraction span = steps 2–5 (F1 absorbed):** `_writer_approve_helper` contains **all five** — room-state gate (`room.state == "closed"` → `_ApproveSkipped("room_closed")`), position-anchored still-pending check, agent-authored reconstruct (`build_author(pending_meta.initiating_agent)`, payload from the persisted record, never the caller), `execute_pending_tool_calls`, and the `call_soon_threadsafe` bus-publish — **all on the writer** (HTTP via `_confirm_on_writer` on `writer_executor`; sweeper via `run_in_executor(ctx.writer_executor, …)`). It is **not** a reconstruct-only tail: the two guards live *inside* the helper, so the sweeper *inherits* the TOCTOU still-pending re-check + closed-room rejection (F1's exact requirement). Signature adds `ctx` as first param vs the plan's `(rid, …, loop)` — a **necessary, faithful** deviation (module-level fn cannot close over `ctx` as the original handler did).
- **HTTP behavior-identical:** the outcome→exception mapping reproduces the original exactly — `not_found`/`room_closed`/`already_resolved` → `_ConfirmAppendError(reason)`; append-fail (`RoomNotFoundError`/`InvalidParentError`/`MetadataValidationError`) → `_ApproveSkipped(str(exc))` → `_ConfirmAppendError`; execute-fail → `_ApproveFailed(reason, event_id)` → `_ConfirmExecuteError`. The **cancel branch is duplicated inline** (steps 1–3 + step 4), not shared — matches the plan's "minus the cancel branch"; cancel path sequence + `approver_user_id`/`pending_meta` usage preserved. Existing confirm suite passes (full suite green).
- **Sweeper:** discovery on `reader_executor` (`_discover_expired_pendings` via `ctx.get_reader_store()`), actuation submitted to `writer_executor` — discovery never appends, never holds the writer (ADR-025 D6 reader-liveness) ✓.
- **Acceptance:** (1) HTTP behavior-identical ✓; (2) sweeper fires enabled+expired+still-pending COUNTDOWN → agent-authored `TOOL_CALL` w/ `approval_source="auto_timer"`, `approver_user_id=None`, executor runs, bus-publishes ✓; (3) HARD never fires — structural (`expires_at is None`) **plus** explicit `meta.tier != "countdown_confirm": continue` in discovery (defense-in-depth) ✓ (`test_discover_skips_hard_pending`); (4) early human approve/cancel ⇒ later timer `already_resolved` no-op ✓; (5) simultaneity ⇒ single writer, one winner ✓; (6) **boot re-arm (F2):** `effective_deadline = expires_at if evt.timestamp >= server_start_ms else server_start_ms + window_s*1000` — branches on *arming process*, not on deadline survival; a prior-process pending gets a fresh full window and does **not** fire on the first post-boot sweep (`test_prior_process_pending_gets_fresh_window`); a current-process pending fires at original `expires_at` (`test_current_process_pending_uses_original_deadline`) ✓ — **exactly the F2-ratified fresh-full-window posture**; (7) cancelled cleanly on shutdown (`_sweeper_task.cancel()` + `suppress(CancelledError)` before `ctx.shutdown()`; coroutine re-raises `CancelledError`) ✓ (`test_sweeper_cancels_cleanly`); (8) **disabled ⇒ no fire (A2):** sweeper **not started** when `enabled` false (`if ctx.countdown_auto_fire.enabled:` in lifespan) — the runtime fire gate, so a stale durable `expires_at` from a prior enabled run cannot fire after disable+restart ✓; (9) closed-room fire rejected via the inherited gate ✓ (`test_writer_approve_helper_closed_room_skip`).

### P4.6-6 — constitutional + functional tests ✅
- **Exact-field-set pins (F3):** `test_constitution_tool_call_pending_meta_field_set_pin` (`{tool_name, call_id, params, tier, initiating_agent, expires_at}`) + `test_constitution_tool_call_meta_field_set_pin` (`{tool_name, call_id, params, approver_user_id, approval_source}`) — mirrors the `DecisionTrace`/`AutonomyDecisionMetadata` pattern; **this is the lock R0-A-on-plan F3 found did not previously exist** ✓.
- `tests/api/test_auto_fire.py` pins (a) HARD-never, (b) opt-in-OFF ⇒ `expires_at=None`, (c) reversibility floor (below + at-floor), (d) idempotency (double-sweep → `already_resolved`; human-cancel-then-timer no-op), (e) boot re-arm both branches, (g) provenance honest, (h) t4 appender-guard (`test_auto_fire_reconstructs_from_record`), clean-shutdown ✓.

### P4.6-7 — inscribe the amendments ✅
- All three are **annotations** in the `[Annotated ADR-040, Accepted 2026-06-07 (P4.6): …]` form, **not rewrites**: ADR-030 D4 (deferred → realized), ADR-030 D7(c) (conditionally inverted when ON / unconditional for HARD + OFF — inline annotation preserving original text), ADR-005 (COUNTDOWN consequence gains a timer; `decide_tier` byte-frozen), ADR-025 D6 (bounded background-task sweeper beside the single writer). Cross-refs to ADR-040 present ✓. ADR-008 untouched ✓.

---

## Findings (3 🟢 — non-blocking, no routing)

- **🟢 G1 (test-coverage, A2 runtime fire gate).** The runtime fire gate — sweeper *not started* when disabled, so a **stale non-`None` `expires_at`** surviving from a prior enabled run never fires after disable+restart — is the load-bearing half of acceptance (8) / R0-B A2. The impl satisfies it structurally (`if ctx.countdown_auto_fire.enabled:` in lifespan). But the closest test (`test_disabled_config_no_expires_at_not_discovered`) exercises only the **stamp-gate** path (a `None` `expires_at` is not discovered) — there is no test asserting that a *stamped* deadline + a disabled sweeper produces no fire across a restart. Coverage gap, not a defect; the property holds by construction. Optional future hardening: a test that stamps a real `expires_at`, then asserts `lifespan` with `enabled=False` starts no sweeper task.

- **🟢 G2 (style).** `import functools` sits inside the `_countdown_sweeper` coroutine body rather than at module top. Harmless (ruff/mypy clean); flagged only as a tidy-up-if-touched note.

- **🟢 G3 (gate count, FYI).** Full suite reports **2259 passed** in this environment vs the **2261** in the P4.6-6 commit message — a 2-test delta, consistent with environment-conditional skips (e.g. cross-family/proxy-gated), **0 failed / 0 errored**. Not an impl issue; noted so the next reader doesn't chase the number.

---

## Gates (run by senior this review)
- `ruff check src tests` → **All checks passed**
- `uv run mypy` (canonical `files=src,tests`) → **Success: no issues found in 278 source files**
- `uv run pytest` (full) → **2259 passed, 0 failed**; targeted `tests/api/test_auto_fire.py tests/core/test_constitution.py` → **22 passed**
- Gate byte-freeze: `git diff b224c40..HEAD -- autonomy/scoring.py autonomy/emission.py` **empty**; `tools/executor.py` **untouched**; no new `LLMPurpose` in the diff.

**Expected auto-advance (ADR-008 Amendment 1, Route B):** plan-vs-impl `clean` ⇒ state → `awaiting_R0_A` (never short-circuits to `awaiting_architect_decision`). R0-A + R0-B impl reviews already present and `clean`.
