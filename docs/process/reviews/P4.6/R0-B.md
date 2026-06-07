---
task_id: P4.6
round: R0-B-cross-family-external
reviewer_family: deepseek
reviewer_model_id: deepseek-v4-pro
reviews_acked:
  - architect-briefs/P4.6.md
  - senior-plans/P4.6.md
  - decisions/ADR-040-countdown-auto-fire-on-timer.md
verdict: clean
findings_count: { red: 0, yellow: 0, green: 3 }
---

# R0-B-cross-family — P4.6 COUNTDOWN auto-fire-on-timer (impl stage)

All 15 changed files (1248 insertions, 82 deletions) read and traced; every Lens A and Lens B item traced against real code at `claude/P4.6-impl` (6 commits P4.6-1..7), diff base `origin/main`. Testing: 40/40 new tests + 148/148 existing confirm/event/event_store tests green. Scoring and emission verified byte-frozen (`git diff origin/main..HEAD -- autonomy/scoring.py autonomy/emission.py` → empty).

---

## Lens A — Auto-fire safety / over-authorization / race

### A1. HARD never auto-fires (ADR-040 D2/4a)

**Two-layer defense, both correct.**

Stamp gate (`src/orchestrator/agents/tool_dispatch.py:135-145`): `expires_at` is stamped **iff** `result.tier == AutonomyTier.COUNTDOWN_CONFIRM and countdown_auto_fire is not None and countdown_auto_fire.enabled`. HARD is structurally excluded — `expires_at` stays `None` for any `hard_confirm` tier. Confirmed by `TestHardNeverFires::test_hard_expires_at_always_none` (HARD with enabled auto-fire → `expires_at is None`).

Sweeper gate (`src/orchestrator/api/app.py:348`): `if meta.tier != "countdown_confirm": continue` — defense-in-depth. Even if a HARD pending somehow carried `expires_at != None` (should be impossible due to stamp gate + append-only store), the sweeper skips it. Confirmed by `TestHardNeverFires::test_discover_skips_hard_pending` (HARD with `expires_at` set → not in candidates).

The constitutional test `test_constitution_tool_call_pending_meta_field_set_pin` (`tests/core/test_constitution.py:262-278`) pins the exact six-field set including `expires_at`, making it a test failure if anyone adds a `hard_expires_at` or similar in the future.

**Verdict: ✓ HARD auto-fire is structurally impossible. 0🔴.**

### A2. Fires only when enabled + only within/after the window (D2/4c, D1/D7)

**Dual gate (stamp + runtime), both correct.**

Disabled → no stamp (`tool_dispatch.py:138`): `countdown_auto_fire is not None and countdown_auto_fire.enabled` — both `None` (old call sites) and `enabled=False` → no `expires_at` stamped. Confirmed by `TestOptInOff::test_countdown_disabled_expires_at_none`.

Disabled → sweeper not started (`src/orchestrator/api/app.py:1275`): `if ctx.countdown_auto_fire.enabled:` — the sweeper task is only created when enabled. This closes the stale-deadline-after-disable+restart path (R0-B-on-plan A2): deadlines stamped during a previous enabled run survive as durable events, but the sweeper never starts in the disabled run → no fire.

Early-fire guard (`api/app.py:358`): `if current_ms < effective_deadline: continue` — strictly not-early.

**The dual-gate design is load-bearing**: the stamp gate prevents new deadlines when disabled; the runtime gate (not-started-when-disabled) prevents stale deadlines from firing across a config change + restart. Both correctly implemented.

**Verdict: ✓ Auto-fire never triggers when disabled or within the window. 0🔴.**

### A3. Reversibility floor (D2/4b)

`tool_dispatch.py:139-145`:
```python
tool_meta = tools.get(tc.name)
rev_floor = countdown_auto_fire.reversibility_floor
if tool_meta is not None and tool_meta.reversibility >= rev_floor:
    expires_at = TimestampMs(pending_ts + countdown_auto_fire.window_s * 1000)
```

- `reversibility` is read from the same `tools: dict[str, ToolMeta]` the gate consumes — not an LLM judgment.
- `tool_meta is None` (unknown tool) → `expires_at = None` (fail-safe, see 🟢 G1 below).
- `tool_meta.reversibility < floor` → `expires_at = None` (degraded to explicit-confirm).
- Config-level validation: `reversibility_floor` is bounded `0 ≤ floor ≤ 10` via Pydantic (`ge=0, le=10`), loaded once at bootstrap.

Confirmed by `TestReversibilityFloor::test_below_floor_expires_at_none` (reversibility=4, floor=5 → `None`) and `test_at_floor_expires_at_set` (reversibility=5, floor=5 → stamped).

**Verdict: ✓ No irreversible op can headless-fire. 0🔴.**

### A4. Idempotency under timer-vs-human race (D5)

**Writer-serialized, position-anchored, double-gated — all correct.**

Position-anchored still-pending check (`api/app.py:266-273`):
```python
already_resolved = any(
    later.type in PENDING_RESOLUTION_TYPES
    and str(later.metadata.get("call_id", "")) == pending_meta.call_id
    for later in sorted_events[pending_idx + 1 :]
)
```
Keys on `type + call_id` — **never** on `expires_at` or `approval_source`. This is the exact same predicate as the pre-extraction HTTP handler.

Single-writer serialization: both HTTP handler and sweeper submit to `writer_executor` (`max_workers=1`) — exactly one wins at the simultaneity instant.

Double-sweep protection: the first fire appends a `TOOL_CALL` (which IS in `PENDING_RESOLUTION_TYPES`). The second sweep's discovery pre-filter finds it resolved (reader-side) AND `_writer_approve_helper`'s authoritative check catches it (writer-side).

Confirmed by `TestIdempotency::test_double_sweep_no_duplicate` (first fire → `_ApproveOk`, second → `_ApproveSkipped("already_resolved")`, exactly 1 `TOOL_CALL`) and `test_human_cancel_then_timer_noop` (human cancel during window → timer `already_resolved`).

**Verdict: ✓ ≤ one TOOL_CALL per pending, all race paths covered. 0🔴.**

### A5. Restart / crash semantics — fresh-full-window re-arm (D6/DP1″-ii/F2)

`api/app.py:354-357`:
```python
if evt.timestamp >= server_start_ms:
    effective_deadline = meta.expires_at        # armed by THIS process
else:
    effective_deadline = TimestampMs(server_start_ms + cfg.window_s * 1000)  # armed by PRIOR → fresh full window
```

Branch is on `evt.timestamp` (the arming event's timestamp), not on `meta.expires_at`. This is the architect-ratified F2 posture — **any** restart-interrupted window (regardless of whether its original deadline had elapsed) gets a fresh full `window_s` from boot. `server_start_ms` captured once at lifespan start (`app.py:1276`), not per-sweep.

Confirmed by `TestBootRearm::test_prior_process_pending_gets_fresh_window` (pending from prior process → not in candidates immediately after boot) and `test_current_process_pending_uses_original_deadline` (current-process pending past expiry → in candidates).

The over-conservative tail (sustained restart loop keeps re-arming → defers indefinitely) is honestly inscribed in ADR-040 D6 Consequences as a residual, not a silent bug.

**Verdict: ✓ No call fires without a live cancel window having existed. 0🔴.**

### A6. Provenance — no-human-approver fact recorded honestly (D4)

Auto-fire path: `_writer_approve_helper(ctx, rid, pending_event_id, "auto_timer", None, loop)` → `ToolCallMeta(approval_source="auto_timer", approver_user_id=None)`.

Human path: `_writer_approve_helper(ctx, rid, body.pending_event_id, "human", _approver_user_id, loop)` → `ToolCallMeta(approval_source="human", approver_user_id=<verified principal>)`.

Pre-P4.5 legacy: `approval_source=None` (additive nullable field, default). Three distinct states — no collision.

The `approval_source` field is on `ToolCallMeta` (`core/event.py:224`), distinct from `approver_user_id`. ADR-040 D4's rejected sentinel-principal approach is correctly avoided.

Confirmed by `TestProvenance::test_human_approve_sets_approval_source_human` (HTTP → `"human"`) and `test_writer_approve_helper_sets_auto_timer` (sweeper → `"auto_timer"`, `approver_user_id=None`).

**Verdict: ✓ No silent-null provenance. `RB-AUTOFIRE` is honestly inscribed. 0🔴.**

### A7. Fire into closed/transitioned room (inherited D3 / ADR-030 D3 step 2)

`_writer_approve_helper` lines 249-252:
```python
room = ctx.writer_store.get_room(rid)
if room is None:
    return _ApproveSkipped("not_found")
if room.state == "closed":
    return _ApproveSkipped("room_closed")
```

The room-state gate is **inside the shared helper**, so both HTTP and sweeper paths inherit it. The sweeper discovers on the reader path (stale: room may close between discovery and actuation), but the writer-side gate catches it authoritatively. Confirmed by `TestClosedRoom::test_writer_approve_helper_closed_room_skip` (closed room → `_ApproveSkipped("room_closed")`).

**Verdict: ✓ Auto-fire never fires into a closed room. 0🔴.**

### A8. Clean shutdown

Lifespan teardown (`app.py:1285-1289`):
```python
if _sweeper_task is not None:
    _sweeper_task.cancel()
    with suppress(asyncio.CancelledError):
        await _sweeper_task
ctx.shutdown()
```

- Sweeper cancelled before `ctx.shutdown()` — no fire-after-shutdown.
- `await _sweeper_task` with `CancelledError` suppression — clean exit, no "Task was destroyed but it is pending" warning.
- Any fire already submitted to `writer_executor` before cancellation completes normally (executor hasn't been shut down yet). `ctx.shutdown()` then waits for the writer executor to drain.
- The sweeper's loop handles `CancelledError` correctly (`except asyncio.CancelledError: raise`).

Confirmed by `TestSweeperShutdown::test_sweeper_cancels_cleanly` (create task → cancel → `CancelledError` raised cleanly).

**Verdict: ✓ Clean shutdown, no fire-after-shutdown, no pending-task warning. 0🔴.**

### Lens A summary: 0🔴 0🟡

---

## Lens B — Spine no-regression

### B1. Gate decision logic byte-frozen (ADR-040 D2 / roadmap §10)

`git diff origin/main..HEAD -- src/orchestrator/autonomy/scoring.py src/orchestrator/autonomy/emission.py` → **empty**. Confirmed byte-frozen.

The eligibility stamp in `process_tool_calls` runs *after* `result = emit_gate_decision(...)` returns (`tool_dispatch.py:112-126`). The tier is decided first; the stamp only records whether a deadline should exist. No timer input feeds the gate.

**No new `LLMPurpose`** on any auto-fire surface file. Grep of `LLMPurpose` across `tool_dispatch.py`, `config.py`, `app.py`, `event.py`, `event_store.py` → only pre-existing usage in `dispatch.py:109/123` (`LLMPurpose.AGENT_RESPONSE` — predates P4.6).

**Verdict: ✓ Gate untouched; timer actuates, never decides. 0🔴.**

### B2. Confirm idempotency + human path preserved after helper extraction

The extraction moved steps 2–5 of the approve path into `_writer_approve_helper`:
1. Room-state gate (`get_room` + `state == "closed"` check) — identical logic
2. Find pending event by `pending_event_id` — identical logic
3. Position-anchored still-pending check (`PENDING_RESOLUTION_TYPES` + `call_id` match on later events) — identical logic
4. Reconstruct `TOOL_CALL` from `ToolCallPendingMeta` (tool_name/params/author from persisted record) — identical logic
5. `execute_pending_tool_calls` + `call_soon_threadsafe` bus-publish — identical logic

The cancel path was **not** extracted (stayed inline in `_confirm_on_writer`) — correct, the sweeper never cancels.

HTTP error mapping: `_ApproveSkipped` → `_ConfirmAppendError` → 422. `_ApproveFailed` → `_ConfirmExecuteError` → 500. Both match the old error taxonomy exactly.

**Existing test suite**: 148/148 confirm + event + event_store tests pass green with zero modifications. This is the "behavior-identical" proof.

**Verdict: ✓ HTTP confirm path is byte-equivalent post-extraction. 0🔴.**

### B3. Executor unchanged + tier-agnostic (ADR-028)

The sweeper calls `execute_pending_tool_calls` with a single `TOOL_CALL` event — the same call shape as the HTTP path. The executor sees `EventType.TOOL_CALL` — no auto-fire-specific input. The `call_id` double-exec guard (idempotency layer 2) is intact. No executor code changed.

**Verdict: ✓ Executor unchanged, tier-agnostic. 0🔴.**

### B4. t4 appender-guard (ADR-028 D6 / ADR-030 D1)

The auto-fire `TOOL_CALL` is reconstructed from `ToolCallPendingMeta` fields: `tool_name`, `call_id`, `params`, `initiating_agent` — all gate-produced, persisted, immutable (append-only store). Never invents a call, never reads a request.

`TOOL_CALL` appenders remain at exactly **two**: HTTP confirm handler + countdown sweeper. Both downstream-of-gate (a `TOOL_CALL_PENDING` with a COUNTDOWN tier must exist first).

Confirmed by `TestApproverGuard::test_auto_fire_reconstructs_from_record` (auto-fired TOOL_CALL carries `tool_name`, `call_id`, `author` from the pending record).

**Verdict: ✓ t4 appender-guard holds. 0🔴.**

### B5. `PENDING_RESOLUTION_TYPES` + snapshot unchanged (ADR-030 D2/D7, ADR-039 D6)

`PENDING_RESOLUTION_TYPES` (`core/event.py:412-419`) is the same frozenset `{TOOL_CALL, TOOL_RESULT, TOOL_FAILED, TOOL_CALL_CANCELLED}`. The auto-fire appends an ordinary `TOOL_CALL` — already a resolution. **No new resolution event type added.**

The still-pending predicate keys on `type in PENDING_RESOLUTION_TYPES and call_id match` — the new fields (`expires_at`, `approval_source`) are never inspected. The discovery pre-filter in `_discover_expired_pendings` (reader-side) also uses the same predicate at `api/app.py:361-366`.

The exact-field-set pin tests (`test_constitution_tool_call_pending_meta_field_set_pin`, `test_constitution_tool_call_meta_field_set_pin`) explicitly enumerate the canonical field sets (6 fields for Pending, 5 for ToolCallMeta), making additive fields explicit and verifiable — any future drift fails the test.

**Verdict: ✓ Snapshot/scan unchanged. 0🔴.**

### B6. Backward-compat: opt-in-OFF ⇒ byte-identical (ADR-040 D7)

With no config file or `enabled: false`:
- `expires_at` **never stamped** — `process_tool_calls` checks `countdown_auto_fire is not None and countdown_auto_fire.enabled` before stamping. Confirmed by `TestOptInOff::test_countdown_disabled_expires_at_none`.
- `approval_source` is set to `"human"` on every HTTP approve — **additive** audit field, never inspected by any existing read path, no behavior change.
- Sweeper **never started** — lifespan guards on `enabled`.
- `approver_user_id` unchanged — HTTP handler still passes the verified principal.
- Pre-existing events read `approval_source=None` — backward-compat default.

**Existing test suite**: all 148 confirm + event + event_store tests pass green — this IS the "byte-identical when off" proof.

**Verdict: ✓ Off-path behavior is byte-identical to today. 0🔴.**

### B7. Background-task + read surface respects ADR-025 D6

**Discovery on reader path**: `_discover_expired_pendings` runs on `reader_executor` (`api/app.py:383-385`). Uses `ctx.get_reader_store()` (per-thread reader connection). Never appends, never writes. A multi-second `run_turn` holding the writer does not block discovery.

**Actuation on writer path**: each fire submitted to `writer_executor` via `run_in_executor` (`api/app.py:388-400`). Fires are serialized on the single writer (`max_workers=1`).

**Room enumeration** (`event_store.py:394-402`): `list_room_ids()` is a pure `SELECT id FROM rooms` — read-only, no `check_same_thread` violation, safe on reader connection.

**Half-fire crash window**: inherited from ADR-030 D7, not worsened. The crash between `append(TOOL_CALL)` and `execute_pending_tool_calls` leaves an orphaned TOOL_CALL (no TOOL_RESULT) — same as the HTTP path. P4.6 doesn't change this.

**Verdict: ✓ Discovery never blocks writer; ADR-025 D6 single-writer consistency preserved. 0🔴.**

### Lens B summary: 0🔴 0🟡

---

## 🟢 Green findings (nits, no fix required)

### G1. Unknown-tool COUNTDOWN → silent no-auto-fire

`tool_dispatch.py:139`: `tool_meta = tools.get(tc.name)`. If the tool is NOT in the tools map, `tool_meta is None` → `expires_at = None`. Meanwhile, the scoring path (`_read_reversibility_or_default`) returns `_DEFAULT_REVERSIBILITY = 5` for unknown tools — so an unknown tool CAN be scored COUNTDOWN by the gate but will **silently never auto-fire** (the stamp path gets `None`, not the default).

This is **fail-safe** (unknown tool doesn't headless-fire — correct) but **unobservable**: the event shows `tier="countdown_confirm"` with `expires_at=None` and no log message explaining why. An operator who enabled auto-fire for what they believe is a reversible tool may never realize it silently degrades to explicit-confirm.

**Severity: 🟢 nit.** Requires a tool-not-in-tools-map edge case (shouldn't happen in normal operation), and the behavior is safe. The ADR-040 D2/DP4b design already acknowledges the "COUNTDOWN that doesn't auto-fire" sub-state as inherent to the reversibility floor. A future improvement could log a WARNING when `result.tier == COUNTDOWN_CONFIRM` and auto-fire is enabled but the expiry stamp is skipped (for any reason — unknown tool, below floor, disabled), so the operator sees the degradation.

### G2. Sweeper discovery: no per-room exception isolation

`_discover_expired_pendings` (`api/app.py:332-370`) iterates all rooms via `for rid in reader.list_room_ids()` and calls `reader.get_room_events(rid)` for each. If `get_room_events` raises for one room (e.g., room deleted between `list_room_ids()` and `get_room_events`), the **entire discovery tick** fails. The sweeper's outer `except Exception` catches it and logs an error, continuing on the next tick — so the failure is transient (the deleted room won't appear in the next `list_room_ids()`). But this could drop valid candidates from other rooms in the same tick.

**Severity: 🟢 nit.** Requires a room deletion concurrent with sweeper discovery — a rare edge case. The discovery is approximate (stale reader) by design; dropping one tick is within the design envelope. A per-room try/except would be more robust.

### G3. Full-room event scan on every sweep tick

`_discover_expired_pendings` loads ALL events for EVERY room on every sweep tick, sorting them in-memory. For N rooms and M events per room, this is O(N × M log M) per tick. The sweeper runs on the reader path (doesn't block the writer), and `sweep_interval_s` defaults to 30s, so correctness is not impacted. However, at scale, the reader work per tick could exceed the sweep interval, causing effective fire latency to grow beyond `sweep_interval_s`.

**Severity: 🟢 nit.** ADR-040 D9 explicitly acknowledges this as a known trade-off and notes the narrower "rooms with an unresolved COUNTDOWN pending" query as a compatible future refinement. Not a correctness issue at current scale.

---

## Verdict: clean

**0🔴 — no HARD auto-fire, no fire-when-disabled, no fire-into-closed-room, no irreversible-headless-fire, no fire-without-live-window, no silent-null provenance, no gate regression, no pierced appender guard, no confirm-idempotency break, no writer-blocking sweeper.**

**0🟡 — no should-fix issues identified.**

**3🟢 — nits only (silent degradation observability, per-room exception isolation, full-room scan trade-off), all within architect-acknowledged design boundaries.**

The architect proceeds to Accept ADR-040 + junior dispatch. The impl faithfully realizes all five ratified DPs with the correct conservative posture (fresh-full-window re-arm, dual gate on enabled, honest provenance marker) and zero spine regression.
