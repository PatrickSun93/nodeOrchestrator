---
task_id: P4.6
round: R0-B-on-plan-cross-family-external
reviewer_family: deepseek
reviewer_model_id: deepseek-v4-pro
reviews_acked:
  - architect-briefs/P4.6.md
  - senior-plans/P4.6.md
  - decisions/ADR-040-countdown-auto-fire-on-timer.md
verdict: needs_architect
findings_count: { red: 0, yellow: 1, green: 0 }
---

# R0-B-on-plan (cross-family external) — P4.6 COUNTDOWN auto-fire-on-timer

**Artifact bundle read:** brief (`docs/process/architect-briefs/P4.6.md`), senior plan (`docs/process/senior-plans/P4.6.md`), ADR-040 (`docs/decisions/ADR-040-countdown-auto-fire-on-timer.md`), plus the full live substrate (all files listed in the prompt §"Artifact bundle") and the five referenced ADRs (030, 005, 028, 039, 025). Traces cited as `file:line` or `artifact §`.

## Lens A — AUTO-FIRE SAFETY / OVER-AUTHORIZATION / RACE

### A1. HARD never auto-fires — ✅ CLEAN

- **Stamp site guard:** `ToolCallPendingMeta.tier` is `Literal["countdown_confirm", "hard_confirm"]` (`core/event.py:364`). The design stamps `expires_at` iff `tier == COUNTDOWN_CONFIRM` (ADR-040 D2). A HARD pending is structurally `expires_at is None` at the type level.
- **Sweeper defense-in-depth:** ADR-040 D2 specifies the sweeper additionally hard-guards `tier == countdown_confirm`. Two independent gates.
- **No malformed-record path:** `ToolCallPendingMeta` is server-produced in `process_tool_calls` (`agents/tool_dispatch.py:126-145`), which runs on the writer — no external input can craft a pending record with a forged tier. The event store is append-only (`event_store.py:78-90`, `BEFORE UPDATE/DELETE ... RAISE(ABORT)`) — no in-place mutation of a HARD pending's metadata to inject `expires_at`.
- **Constitutional test pinned:** brief §4a + plan P4.6-6(a) require a test that *fails* if the guard is removed. This is the correct constitutional-test posture.

Verdict: design holds. No path found for a HARD call to acquire a deadline or reach the fire.

### A2. Fires only when enabled + only within/after the window — 🟡 ONE GAP

- **Stamp-time gate:** `expires_at` is stamped iff `enabled` is true (ADR-040 D2 condition 2). Disabled ⇒ no new deadlines stamped. ✓
- **Window timing:** `expires_at = pending_event.timestamp + window_s * 1000` (ADR-040 D1) — an absolute deadline. The sweeper fires when `now_ms() >= effective_deadline` (D6) — not early. ✓
- **🟡 Sweeper runtime `enabled` gate not explicit in the ADR.** Trace the scenario: (1) auto-fire is enabled, deadlines are stamped. (2) Operator sets `enabled: false` + restarts. (3) The sweeper starts (or not). If the sweeper **always starts and does not re-check `enabled` at sweep time**, it will discover and fire the stale deadlines from step 1 — violating D7's "disabled ⇒ byte-identical to today, zero regression" claim. The ADR D1 describes the sweeper's discovery as "discovers COUNTDOWN `TOOL_CALL_PENDING` events whose effective deadline has passed and that are still-pending" — **`enabled` is not listed as a filter condition in D1**, and D7 only discusses the stamp path, not the sweeper's runtime gating. The plan P4.6-4 acceptance (8) covers this ("disabled ⇒ the sweeper either is not started or finds nothing") and P4.6-6(b) will pin it with a constitutional test, so the *impl* will be correct — but the **ADR as the durable contract** should explicitly state that the sweeper either does not start when `enabled` is false, or checks `enabled` before each fire. Without this, a future reader of the ADR could implement a sweeper that fires stale deadlines after disable+restart.
  - **Severity:** 🟡 should-fix. The plan's acceptance criteria + constitutional test already cover the invariant; the ADR text should match.
  - **Confidence:** medium — the impl is guarded by acceptance criteria; the gap is in the ADR's completeness as a standalone contract.

### A3. Reversibility floor bounds the irreversible tail — ✅ CLEAN

- `ToolMeta.reversibility` defaults to 0 (`scoring.py:42-51`), read from the same `tools: dict[str, ToolMeta]` the gate already consumes (`tool_dispatch.py:65`).
- ADR-040 D2 condition 3: `tools[tool_id].reversibility ≥ reversibility_floor`. Below-floor COUNTDOWN calls get `expires_at = None` → degrade to explicit-confirm.
- ADR-005 §5(c) example: `git_push` reversibility=1 lands on COUNTDOWN with `user_explicit_intent`. With `reversibility_floor=2`, it would NOT auto-fire — the floor correctly bounds the irreversible tail.
- Floor is code/config (`config/autonomy.yaml`, bounded `0 ≤ floor ≤ 10`), not LLM. ✓

Verdict: design holds.

### A4. Idempotency under timer-vs-human race — ✅ CLEAN (inherited)

- **Single-writer serialization:** `writer_executor = ThreadPoolExecutor(max_workers=1)` (`api/app.py:316`). Both the HTTP confirm handler and the sweeper's fire path submit to this executor. Exactly one wins at the simultaneity instant.
- **Position-anchored still-pending predicate:** `PENDING_RESOLUTION_TYPES` (`core/event.py:401-408`) keys on `{TOOL_CALL, TOOL_RESULT, TOOL_FAILED, TOOL_CALL_CANCELLED}`. The helper's still-pending check scans events AFTER the pending event's position for matching `call_id` — same predicate used by `_post_confirm` today (`api/app.py:791-799`) and by snapshot derivation (`derived/snapshot.py:166-183`). The timer appends an ordinary `TOOL_CALL` — already a resolution type. No new resolution event type. ✓
- **Double-sweep:** first fire appends `TOOL_CALL`; second sweep's still-pending check finds it → no-op. The sweeper discovers on the reader path (may see stale state), but the writer-side still-pending re-check inside the shared helper is the correctness guard. ✓
- **No reliance on `expires_at`/`approval_source` in the predicate:** both the `_post_confirm` still-pending scan (`api/app.py:794-796`) and the snapshot scan (`derived/snapshot.py:171-174`) key on `type in PENDING_RESOLUTION_TYPES` + `call_id` — never on the new fields. ✓

Verdict: the inherited mechanism covers all race scenarios. Design holds.

### A5. Restart / crash — never fire without a live cancel window — ✅ CLEAN

- **Boot re-arm:** `server_start_ms = now_ms()` captured once at lifespan start (ADR-040 D6). `effective_deadline = expires_at if expires_at ≥ server_start_ms else server_start_ms + window_s*1000`.
- **Conservative posture proven:** a window whose `expires_at` fell entirely during downtime gets a **fresh full window from boot** — the operator gets a live cancel window. No fire without a live cancel window having existed in some running process. ✓
- **`server_start_ms` captured once, not per-sweep:** D6 states "captures `server_start_ms = now_ms()` once at lifespan start." The sweeper reads it — an integer, never mutated after capture, thread-safe. ✓
- **Repeated-crash deferral inscribed as residual:** ADR-040 D6 Consequences + D8 explicitly call out that repeated within-window crashes can defer the fire indefinitely. Honest. ✓
- **Append-only store forces read-time derivation:** the `BEFORE UPDATE/DELETE ... RAISE(ABORT)` triggers (`event_store.py:78-90`) make event mutation impossible. The re-arm as a **read-time `effective_deadline` computation** is the correct mechanism — no metadata rewrite needed. ✓

Verdict: design holds. The re-arm derivation is correct and conservative.

### A6. No-human-approver fact recorded honestly — ✅ CLEAN

- `approval_source: Literal["human", "auto_timer"] | None = None` (ADR-040 D4). Human path → `"human"`; auto-fire → `"auto_timer"`; legacy events → `None`.
- `approver_user_id` stays `None` for auto-fire — but now disambiguated by `approval_source="auto_timer"`. No silent-null collision with pre-P4.5 legacy `None`. ✓
- `RB-AUTOFIRE` (ADR-040 D8) honestly states: *"no account at all actuates within the window; the human-in-the-loop moment moved to config-time."* Not softened. ✓
- **Rejected sentinel principal** (`approver_user_id = "system:countdown-timer"`) — correct rejection; keeps the `approver_user_id` namespace clean for actual user IDs (ADR-039 D1). ✓

Verdict: design holds. The provenance is honest and unambiguous.

### A7. Fire into closed room + boundary escalation — ✅ CLEAN

- **Room-state gate inherited:** the shared helper (ADR-040 D3) reuses `_post_confirm`'s logic, which checks `room.state == "closed"` (`api/app.py:770-771`) and raises `_ConfirmAppendError("room_closed")`. A COUNTDOWN whose room closed between discovery and fire is rejected. ✓
- **Boundary escalation:** the eligibility gate (D2) is the single point where auto-fire eligibility is decided — COUNTDOWN-only, enabled, reversibility-floored. The sweeper cannot escalate beyond these bounds because it only actuates what the eligibility gate stamped. No new decision surface. ✓

Verdict: design holds.

### A8. Clean shutdown — ✅ CLEAN

- **Sweeper lifecycle:** plan P4.6-4 places the sweeper in `lifespan` after `_build_context`, cancelled in teardown before `ctx.shutdown()`. The current lifespan (`api/app.py:1054-1062`) does `yield` then `ctx.shutdown()` — the sweeper task cancellation fits between `yield` and `ctx.shutdown()`.
- **In-flight fires:** `ctx.shutdown()` calls `writer_executor.shutdown(wait=True)` (`api/app.py:141`) — any fire already submitted to the writer completes before the executor tears down. No fire-after-shutdown. ✓
- **Plan forcing functions §4:** "Clean-shutdown check: the sweeper task must be cancelled in lifespan teardown — no 'Task was destroyed but it is pending' warning, no fire-after-shutdown." Explicitly tested. ✓

Verdict: design holds.

---

## Lens B — SPINE NO-REGRESSION

### B1. Gate decision logic byte-frozen — ✅ CLEAN

- **`score`/`decide_tier`/`emit_gate_decision` untouched:** `score()` (`scoring.py:147-162`) is a pure reversibility lookup. `decide_tier()` (`scoring.py:165-207`) maps score→tier with no timer/window input. `emit_gate_decision()` (`emission.py:35-110`) wraps `gate()` and emits audit events. The eligibility stamp runs *after* the tier is decided, in `process_tool_calls` (`tool_dispatch.py:126-145`) — it only governs whether `expires_at` is recorded, never alters the tier. ✓
- **No new `LLMPurpose` on the auto-fire surface:** grep confirms `LLMPurpose` usage is confined to `agents/dispatch.py` (AGENT_RESPONSE), `agents/mcp_interpret.py` (TOOL_OUTPUT_INTERPRET), `producers/tagging.py` (HYPOTHESIS_TAG_PROPOSAL), `reentry/` (REENTRY_DIGEST_RENDER, ARCHIVE_SUMMARY_RENDER), and `llm/purposes.py` (definition). Zero `LLMPurpose` in `tool_dispatch.py`, `scoring.py`, `emission.py`, `event.py`, or any auto-fire path. ✓
- **Plan forcing functions §4:** "Gate byte-freeze diff: before commit, `git diff autonomy/scoring.py` + `autonomy/emission.py` — the timer actuates, never decides." ✓

Verdict: design holds. The gate is untouched.

### B2. Confirm idempotency + human path preserved after helper extraction — ✅ CLEAN

- **Extraction surface:** ADR-040 D3 extracts `_post_confirm`'s approve branch (still-pending check → reconstruct `TOOL_CALL` from persisted record → `execute_pending_tool_calls` → publish) into a shared helper. The HTTP handler calls it with `("human", principal_user_id)`. ✓
- **Position-anchored still-pending check preserved:** the predicate at `api/app.py:791-799` (type in `PENDING_RESOLUTION_TYPES` + `call_id`, position-anchored AFTER the pending event) is extracted unchanged into the helper. ✓
- **Agent-authored reconstruct preserved:** `tool_name`/`params`/`author` from `ToolCallPendingMeta` (backend-authoritative), never from request — same as today (`api/app.py:830-843`). ✓
- **Partial-turn `stage` envelope preserved:** the HTTP handler still wraps the helper call and raises `_ConfirmAppendError`/`_ConfirmExecuteError` with the same `stage` semantics. ✓
- **`approver_user_id` from principal unchanged for human path:** `api/app.py:758-761` — server-derived, never from body. ✓
- **Plan P4.6-4 acceptance (1):** "the existing confirm test suite passes byte-for-byte at the response level." ✓

Verdict: design holds. The extraction is a pure refactor.

### B3. Executor unchanged + tier-agnostic — ✅ CLEAN

- **Call shape identical:** both the HTTP handler and the sweeper call `execute_pending_tool_calls` with a `TOOL_CALL` event reconstructed from the persisted `ToolCallPendingMeta`. The executor sees no difference between a human-fired and auto-fired `TOOL_CALL`. ✓
- **`call_id` double-exec guard intact:** the executor's existing idempotency layer 2 (ADR-028 D2) operates on `TOOL_CALL` events — unchanged. ✓
- **No auto-fire-specific input to executor:** the `approval_source` field is on the `TOOL_CALL` metadata — the executor doesn't read it (it dispatches based on `tool_name`/`params`/`call_id`). ✓

Verdict: design holds.

### B4. t4 appender-guard holds — ✅ CLEAN

- **Appenders stay at two:** HTTP-confirm + timer-confirm — both downstream-of-gate (ADR-040 D3). ✓
- **Auto-fire reconstructs from persisted record only:** `{tool_name, call_id, params, author}` come from the `ToolCallPendingMeta` produced by `process_tool_calls` at gate time — never from a request, never invented. ✓
- **No new actuation surface re-opens the invariant:** the shared helper is the single actuation path; both callers go through it. ✓
- **ADR-028 D6 amendment:** plan P4.6-7 will annotate ADR-028 D6 to note the second appender. ✓

Verdict: design holds.

### B5. `PENDING_RESOLUTION_TYPES` + snapshot derivation unchanged — ✅ CLEAN

- **No new resolution event type:** the timer appends an ordinary `TOOL_CALL` — already in `PENDING_RESOLUTION_TYPES` (`core/event.py:401-408`). No new `EventType`. ✓
- **Snapshot still-pending scan unchanged:** `derived/snapshot.py:166-183` keys on `EventType.TOOL_CALL_PENDING` → position-anchored scan → `PENDING_RESOLUTION_TYPES` + `call_id`. The additive `expires_at`/`approval_source` fields are never inspected by this scan. ✓
- **Additive fields don't leak:** `expires_at` is on `ToolCallPendingMeta`, `approval_source` is on `ToolCallMeta`. Neither field is read by the still-pending predicate (which checks only `type` + `call_id`). ✓

Verdict: design holds.

### B6. Backward-compat: opt-in-OFF ⇒ byte-identical — ✅ CLEAN

- **Absent config file ⇒ disabled = fail-closed:** ADR-040 D7 specifies absent `config/autonomy.yaml` ⇒ `enabled=False`. Plan P4.6-1 acceptance (1) confirms. ✓
- **`expires_at` never set or inspected when disabled:** ADR-040 D2 condition 2 stops stamping; D7 says old paths never inspect the field. ✓
- **`approval_source` always set to `"human"` on human path:** this is a deliberate design choice (plan P4.6-3). The field is additive nullable — existing consumers don't read it; the still-pending scan doesn't read it. Backward-compat: pre-existing events deserialize with `approval_source=None`. New human-approved events carry `"human"`. The API response shape gains one nullable field — additive, not breaking. ✓
- **`ToolCallPendingMeta` constitutional test extended, not bypassed:** plan P4.6-2 acceptance (6) explicitly requires extending the test to cover `expires_at` presence/absence per tier. ✓
- **Existing confirm suite passes unchanged:** plan P4.6-6(b) + forcing functions §4 require the opt-in-off byte-identical check. ✓

Verdict: design holds. Additive fields are backward-compat.

### B7. Background-task + read surface respects ADR-025 D6 — ✅ CLEAN

- **Discovery on reader path, actuation on writer:** ADR-040 D1 explicitly separates discovery (reads via reader path, no appends) from actuation (submitted to `writer_executor`, atomic on single writer). Matches ADR-025 D6 reader-liveness discipline. ✓
- **Multi-second `run_turn` doesn't block discovery:** the sweeper's discovery reads on the reader path — independent of the writer. ✓
- **Discovery never appends:** the sweeper only reads during discovery; all writes (the shared helper) go through the writer executor. ✓
- **New `list_room_ids()` is read-only:** ADR-040 D9 specifies a read-only SQLite query against the `rooms` table. ✓
- **No existing room-enumeration API:** grep confirms zero `list_room_ids`/`list_rooms`/room-enumeration methods in the codebase (senior-verified, plan §5 finding 2). The sweeper genuinely needs this. ✓

Verdict: design holds.

---

## Verdict

**`needs_architect`** — 0🔴 / 1🟡 / 0🟢.

The single 🟡 finding (A2) is a documentation gap in ADR-040: the sweeper's runtime `enabled` gate is not explicitly stated in D1 or D7, creating ambiguity about whether stale deadlines from a previous enabled run could fire after disable+restart. The plan's acceptance criteria (P4.6-4(8) + P4.6-6(b)) already cover the invariant — no code change is needed, only an ADR clarification.

All other Lens A invariants (HARD-never, reversibility floor, idempotency, re-arm, provenance honesty, closed-room gate, clean shutdown) and Lens B invariants (gate byte-frozen, confirm idempotency, executor tier-agnostic, t4 appender-guard, PENDING_RESOLUTION_TYPES unchanged, backward-compat, ADR-025 D6 reader-liveness) trace cleanly through the design against the live substrate.

**Routing:** architect routes (α/β/γ/δ). No re-routing performed by this review.
