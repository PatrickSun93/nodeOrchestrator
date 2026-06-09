# ADR-040: COUNTDOWN auto-fire-on-timer — a durable backend scheduler + the first human-out-of-loop execution posture

**Status:** Accepted (architect, 2026-06-07) — senior-drafted for P4.6, the Wave-3 completeness slice riding ADR-030 confirm machinery; architect Accepted after plan-stage lean dual-lens cleared 0🔴 (R0-A-on-plan 0🔴2🟡1🔵 + R0-B-on-plan cross-family 0🔴1🟡), the F2 restart re-arm posture ruled (any restart-interrupted window re-arms a fresh full window) and F1/A2/F3 absorbed (α) (RC-3: the senior did **not** self-accept). `requires_cross_family_review: true` (set in `.workflow/P4.6.yaml`); P4-roadmap §8 — **lean dual-lens** (A=auto-fire safety/over-authorization/race, B=spine no-regression). Amendments to ADR-030 / ADR-005 / ADR-025 are inscribed at impl (plan task P4.6-7), matching the eventual Accepted status (the ADR-039 / ADR-037 precedent).

**Ratification context.** All five decision-surface points (DP1–DP5) of `docs/process/architect-briefs/P4.6.md` were **architect-ratified along the lean lines** in the ratification commit `96a9a4d`: **DP1 = (b)** durable `expires_at` persisted on the pending record + a single lifespan-started in-process asyncio sweeper (DP1″ expired-during-downtime → re-arm a fresh window); **DP2 = (a)** reuse `_post_confirm`'s approve closure as a shared writer helper + **(2b/i)** `approver_user_id` stays `None` with an explicit positive `approval_source` marker (the honesty crux); **DP3 = inherited** (writer-serialized + position-anchored still-pending; no new resolution event type); **DP4 = (4a)** COUNTDOWN-only/HARD-never + **(4b)** reversibility floor + **(4c)** opt-in default OFF + **(4d)** inscribe `RB-AUTOFIRE` honestly; **DP5 =** this new ADR + amend ADR-030 D4/D7(c) + annotate ADR-005 / ADR-025 D6. The architect Accepts — **the senior does not self-accept (RC-3).**

**Scope:** The **first durable timed-execution surface in the product** + the **first deliberate human-out-of-loop execution posture**. Before P4.6 the `COUNTDOWN_CONFIRM` "countdown" is a *name and a UI hint with no server timer* — `COUNTDOWN_CONFIRM` and `HARD_CONFIRM` take the **identical** wait-for-human path (`agents/tool_dispatch.py:126-145`), so if the user does nothing a COUNTDOWN call stays pending **indefinitely, exactly like HARD** (ADR-030 D4: "the countdown is a UI hint, not a server timer"). This ADR adds, **for the COUNTDOWN tier only**: a **durable `expires_at`** stamped at gate time (D1); a **single in-process asyncio sweeper** that actuates expired-and-still-pending COUNTDOWN calls on the writer (D1); the **eligibility gate** that bounds *which* COUNTDOWN calls may headless-fire (D2); the **reuse of the confirm-actuate closure** as a shared writer helper (D3); the **no-human-approver provenance** record (D4); the **inherited cancel/preempt idempotency** (D5); the **restart-survival + boot re-arm** semantics (D6); the **opt-in, default-OFF** config posture (D7); the honest **`RB-AUTOFIRE` residual** (D8); and the **room-enumeration read API** the sweeper requires (D9). Does **NOT** govern: the autonomy gate's **decision logic** (`score`/`decide_tier`/`emit_gate_decision` — byte-frozen; the timer **actuates, never decides**; ADR-027 D2 / ADR-005 D4); the executor's execution/dispatch logic (`execute_pending_tool_calls` — unchanged, tier-agnostic, ADR-028); the **HARD tier** (never acquires a timer — D2/4a); auth/identity (ADR-039 — auto-fire is a step *beyond* `RB-AUTHZ`, D8); external/distributed scheduling (rejected — D1 alternatives); agent re-dispatch on the tool result (still deferred, ADR-028 D4).

## Context

Verified against `origin/main` @ `408e568` (the brief's verify-cite base) and re-confirmed @ `96a9a4d`.

**The "countdown" is, today, a name with no timer.** `AutonomyTier{AUTO_EXECUTE, COUNTDOWN_CONFIRM, HARD_CONFIRM}` (`autonomy/scoring.py:11-16`); `decide_tier` maps `eff_confirm ≤ score < eff_auto → COUNTDOWN` purely on reversibility + thresholds (`scoring.py:165-207`) — **no timer concept**. `process_tool_calls`'s countdown/hard branch is **one `else`** (`agents/tool_dispatch.py:126-154`): both tiers append a `TOOL_CALL_PENDING` carrying `ToolCallPendingMeta{tool_name, call_id, params, tier, initiating_agent}` (`core/event.py:351-365`) and then **wait forever** for a human `POST /confirm`.

**The confirm-actuate path C1 reuses.** `_post_confirm` (`api/app.py:734-867`) runs entirely on the **single writer** (`writer_executor`, `max_workers=1`, `app.py:316`): resolve room → room-state gate (closed → reject) → **position-anchored still-pending check** (idempotency layer 1, `app.py:791-799`, keyed on `PENDING_RESOLUTION_TYPES` + `call_id`, `core/event.py:401-408`) → on approve, **reconstruct an agent-authored `TOOL_CALL` from the persisted record** (`app.py:830-843`, `tool_name`/`params`/`author` from `ToolCallPendingMeta`, never the request) → `execute_pending_tool_calls` (executor `call_id` guard = idempotency layer 2, `app.py:849-858`) → publish to the bus. `check→append→execute` is atomic on the single writer; no TOCTOU.

**Provenance (the P4.5 interaction).** `ToolCallMeta.approver_user_id: str | None` (`core/event.py:218`) and `ToolCallCancelledMeta.approver_user_id` (`:380`) are **server-derived from the verified principal** (`app.py:758-761`, never the body — ADR-039 D6), nullable for legacy. The executed `TOOL_CALL` stays `agent:<initiating_agent>`-authored — `approver_user_id` is *provenance, not authorship*. The approve site is ADR-039 "D5 checkpoint seam #1: authenticated ⇒ allowed."

**No timer / scheduler / boot-recovery exists.** A full grep (`scheduler|call_later|create_task|timer`) finds only auth-session TTL, MCP deadlines, sandbox timeouts — **no background-task loop**. The server has an asyncio loop (lifespan, `app.py:1054-1062`), the single `writer_executor`, the per-thread reader pool, and the `RoomEventBus` — but **zero background-task infrastructure**, and **no executor boot-recovery scan** ("find `TOOL_CALL_PENDING` without a resolution"): ADR-030's own Consequences (L104-106) name this "a general executor crash-recovery gap, out of P3.6 scope."

**Two store invariants this ADR is built around (senior-verified at plan time).**
1. **The event store is append-only — `BEFORE UPDATE`/`BEFORE DELETE` triggers `RAISE(ABORT)`** (`core/event_store.py:78-90`). A `TOOL_CALL_PENDING`'s metadata **cannot be mutated in place**. The brief's DP1″ "re-arm a fresh window" and DP3's "clear the durable expiry on resolution" therefore **cannot** be a metadata rewrite; D6 realizes re-arm as a **read-time derivation** and D5 drops the expiry-clear as moot (the still-pending predicate is the sole correctness guarantee).
2. **No room-enumeration API exists** — `EventStore` has `get_room`/`get_room_events` by id only (`event_store.py:358-382`); nothing lists rooms. The sweeper cannot scan without one (D9).

**The boundary this slice turns on.** ADR-030 D4 deferred auto-fire and named the exact surfaces this ADR resolves ("which thread fires it vs the single writer; what survives a server restart mid-window; how the timer interacts with a concurrent cancel"). P4-roadmap §10 fixes the framing that keeps "routing/gating = code" intact: auto-fire is **a scheduler over an already-gated COUNTDOWN tier** — the gate decided the tier; the timer **only actuates** the operator's standing "approve-unless-cancelled." Hold that line and the slice is a *recording/actuation* addition, not a new decision surface (the ADR-030 D1 discipline for the pending record).

## Decisions

### D1. Durable `expires_at` + a single in-process sweeper (DP1 = (b))

The auto-fire timer is **durable and event-sourced**, not a live in-memory timer:

- **`expires_at` is stamped at gate time** as an additive nullable field on `ToolCallPendingMeta` (`core/event.py:351-365`), `expires_at: TimestampMs | None = None`. When set (D2 gates *when*), `expires_at = pending_event.timestamp + window_s * 1000` — an **absolute epoch-ms deadline**, immutable for the life of the event (store invariant #1).
- **A single lifespan-started asyncio sweeper** (`create_app`'s `lifespan`, `app.py:1054-1062`) wakes every `sweep_interval_s`, **discovers** COUNTDOWN `TOOL_CALL_PENDING` events whose effective deadline (D6) has passed and that are **still-pending** (the position-anchored predicate, `PENDING_RESOLUTION_TYPES`), and **dispatches each fire to the `writer_executor`** via the shared helper (D3). Discovery reads via the reader path; actuation + the still-pending re-check are atomic on the single writer (the ADR-025 D6 reader-liveness discipline — a multi-second `run_turn` holding the writer does not block discovery, and discovery never appends).
- **Runtime `enabled` gate (the stale-deadline guard).** The sweeper is **started only when auto-fire is enabled** (D7) — when disabled it is **never started**. This is load-bearing for the disable-then-restart case: deadlines stamped during a *previous enabled run* are durable events that survive into a *disabled* run, so a sweeper that started-and-fired unconditionally would actuate stale deadlines after the operator turned auto-fire off. Not-starting-when-disabled closes that path (an equivalent impl may instead re-check `enabled` before every fire); either way **`enabled` is a runtime fire precondition, not only a stamp-time gate**, so "disabled ⇒ byte-identical to today" (D7) holds across a config change + restart.
- **Survives restart natively**: the deadline lives in a durable event, so a sweep after boot picks it up (D6) — this is the bounded boot-recovery scan ADR-030 left open, **for COUNTDOWN only**.

Fire latency is rounded up to one `sweep_interval_s` tick — negligible for a seconds-to-minutes window, the conscious cost of durability over a precise in-memory timer.

**Rejected:** (a) an in-process `call_later`/task per pending — simplest and precise, **but the timer lives only in event-loop memory** (a restart mid-window loses it silently, re-opening the exact durability hole ADR-030 D4 named) and needs cross-thread arming (`process_tool_calls` runs on the writer thread, not the loop). (c) an external scheduler (cron/APScheduler/job queue/separate process) — new dependency + deployment surface, breaks the single-process localhost posture, over-builds the "small" slice; reconsider only if a distributed deployment is foreseen.

### D2. The eligibility gate — *which* COUNTDOWN calls may headless-fire (DP4a/4b/4c)

`expires_at` is stamped in `process_tool_calls` **iff all three hold**, else it stays `None` (and the call waits for a human, exactly as today):

1. **`tier == COUNTDOWN_CONFIRM`** — HARD **never** acquires a deadline (4a). The sweeper additionally hard-guards `tier == countdown_confirm` (defense-in-depth); a HARD pending is structurally unreachable by the timer. **Constitutional-test-pinned.**
2. **auto-fire is enabled** (D7) — disabled ⇒ no deadline ever stamped ⇒ byte-identical to today.
3. **`tools[tool_id].reversibility ≥ reversibility_floor`** (4b) — the subtle trap is that **COUNTDOWN ≠ reversible** (ADR-005 §5(c): `git_push` reversibility=1 lands on COUNTDOWN under `user_explicit_intent`). Below the floor the COUNTDOWN call **degrades to explicit-confirm** (stays pending for a human) so an **irreversible op never headless-fires**. The floor is **code/config, not LLM** — it stays on the right side of "routing = code." `reversibility` is read from the same `tools: dict[str, ToolMeta]` the gate already consumes (`tool_dispatch.py:65`); no new data source.

The **gate decision logic is byte-frozen** — `score`/`decide_tier`/`emit_gate_decision` are untouched; the eligibility gate runs *after* the tier is decided and only governs whether a *deadline* is recorded. The timer **actuates, never decides**; **no new `LLMPurpose`**.

### D3. Auto-fire actuation — reuse the confirm-actuate closure (DP2 = (a))

`_post_confirm`'s approve path is **extracted into a shared writer helper** called by **both** the HTTP confirm handler and the sweeper, **both on `writer_executor`**:

- **The extraction span is steps 2–5 of the approve path (`app.py` `~:769-865` minus the cancel branch)** — the **room-state gate** (closed-room rejection, `:769-771`) + the **position-anchored still-pending check** (`:791-799`) + the agent-authored **reconstruct** (`:830-843`) + **execute** (`:849-858`) + **bus-publish** (`:863-864`), **all on the single writer**. The two guards (room-state + still-pending) **must be inside the helper**, not left in the HTTP handler — the sweeper discovers on the *reader* path (necessarily stale: a human may cancel/approve in the gap between discovery and the writer append), so the **writer-side still-pending re-check is the sole TOCTOU guard**, and the closed-room rejection is only *inherited* (DP3 "no new mechanism") if it lives in the shared helper. Extracting a reconstruct-only helper (the post-`:826` tail) would force the sweeper to **re-implement** both guards — duplicated mechanism, a Lens-B regression.
- **Signature** `(rid, pending_event_id, approval_source, approver_user_id, loop)` — `rid` + the target `pending_event_id` (HTTP: `body.pending_event_id`; sweeper: the discovered pending) + the two provenance params (D4) + `loop` (for the `call_soon_threadsafe` bus-publish, today closed over from the async handler, `:756,864`).
- **Caller-agnostic outcome contract.** The helper's `already_resolved` / `room_closed` / `not_found` outcomes are **errors for the HTTP caller** (→ `422` via the existing exception handlers) but **benign skips for the sweeper** (→ log + skip; **never** an unhandled exception in the asyncio task). The helper returns a discriminated outcome both callers consume; it does not raise HTTP-coupled exceptions past its own boundary for the sweeper path.
- **Executor unchanged + tier-agnostic** (ADR-028 carry-forward); **idempotency layers 1+2 inherited** (→ D5 falls out free).
- **`TOOL_CALL` appenders stay at two** — HTTP-confirm + timer-confirm — each **downstream-of-gate**, keeping the ADR-028 D6 **t4 appender-guard** intact: the auto-fire append reconstructs `{tool_name, call_id, params}` from a **persisted, gate-produced** COUNTDOWN record, **never inventing a call**.
- Reuse gives **bus-publish for free** (the GUI sees the live `TOOL_CALL`/`TOOL_RESULT` stream).

**Rejected:** a second, independent actuation path — re-opens the t4-appender invariant and duplicates the idempotency reasoning.

### D4. Provenance — the no-human-approver fact, recorded honestly (DP2b — the honesty crux)

The `TOOL_CALL` stays `agent:<initiating_agent>`-authored (the gate approved *that agent's* op). For the approver slot:

- **`approver_user_id` stays `None`** for an auto-fire (no human approved) — but `None` alone collides with the pre-P4.5 legacy `None`, so silence would **under-record the single most security-relevant fact of this slice**.
- **An explicit positive marker** is added: `approval_source: Literal["human", "auto_timer"] | None = None` on `ToolCallMeta` (additive nullable). The HTTP confirm path sets `"human"`; the sweeper sets `"auto_timer"`; pre-existing events read `None`. The audit then reads **"executed BY TIMER, no human approver"** — never an ambiguous null.

**Rejected:** a sentinel principal (`approver_user_id = "system:countdown-timer"`) — `approver_user_id` is a bare `<user_id>` field (ADR-039 D1 namespace); a non-user sentinel pollutes it and could confuse a future role/authz consumer. The marker lives in a **distinct** field.

**The deeper inscription (see D8):** the real "who authorized this" is **not an actor at fire time** — it is the operator's **standing, config-time decision** to enable auto-fire with window *N* (+ the cancel window that elapsed unused). The human-in-the-loop moment moves *earlier*, from per-action approval to the configuration act.

### D5. Cancel / preempt race — inherited, no new mechanism (DP3)

The single writer already serializes the race and the position-anchored still-pending predicate already resolves it:

- **Early human approve / cancel during the window** appends a `TOOL_CALL` / `TOOL_CALL_CANCELLED`; when the timer later fires, its **still-pending check fails (`already_resolved`) → no-op.**
- **The simultaneity instant** (human approves exactly as the timer fires) → both land on `writer_executor` (`max_workers=1`); **exactly one wins**, the other no-ops.
- **The timer appends an ordinary `TOOL_CALL`** (same as human-approve) — it is *already* a resolution; **no new resolution event type** is added (that would ripple into `PENDING_RESOLUTION_TYPES` + the snapshot derivation, which ADR-030 D7 / ADR-039 D6 require unchanged).
- **No expiry-clear-on-resolution.** The brief's "clear the durable expiry as housekeeping" presumed a mutable field; under the append-only store (invariant #1) `expires_at` is immutable and there is nothing to clear — the **still-pending check is the sole correctness guarantee** (a resolved pending is simply skipped by every future sweep). This is *simpler* than the brief's lean, not a weakening.

### D6. Restart durability + boot re-arm (DP1″ = (ii) re-arm a *fresh full window*) — the conservative posture

Because `expires_at` is immutable (invariant #1), "re-arm a fresh window" is a **read-time derivation**, not a rewrite. The sweeper captures `server_start_ms = now_ms()` once at lifespan start and branches on **whether the pending was armed by *this* process** — keyed on the pending event's own timestamp, not on whether its deadline survived boot (architect ratification of DP1″-ii, R0-A-on-plan F2):

```
effective_deadline = expires_at                       if pending_event.timestamp >= server_start_ms   # armed by THIS process
                     server_start_ms + window_s*1000   otherwise                                       # armed by a PRIOR process → fresh full window
fire when:  now_ms() >= effective_deadline  AND  still-pending  AND  tier == countdown_confirm
```

- A pending **armed by a prior process** (`pending_event.timestamp < server_start_ms`) — i.e. **any** window a restart interrupted, regardless of whether its original deadline had already elapsed — is re-armed to a **fresh full window from boot** (`server_start_ms + window_s*1000`). The operator gets a complete new cancel window after every restart. This is the literal DP1″-ii "re-arm a fresh window" and the most conservative human-out-of-loop reading: **no restart-interrupted window ever fires on a shrunken (or already-elapsed) cancel window.**
- A pending **armed by the current process** (`pending_event.timestamp >= server_start_ms`) fires at its original `expires_at` on the next sweep — normal operation; its full window was live during this process's uptime.

**Why branch on the arming event, not on the deadline.** An earlier draft floored only windows whose `expires_at` had *fully elapsed during downtime* (`expires_at < server_start_ms`); that satisfied the safety floor ("no fire without a live cancel window having existed in some process") but **not** the liveness generosity of "a *fresh* window" — a partial-downtime restart landing just before expiry would have left only the surviving tail (near-zero at the boundary). Branching on `pending_event.timestamp` grants a fresh full window to **every** restart-interrupted pending, which is what DP1″-ii ratified.

This is the bounded boot-recovery scan ADR-030 left open, **scoped to COUNTDOWN**. **Residual (inscribed):** a server that repeatedly crashes/restarts will re-arm on **every** boot, so a sustained restart loop keeps deferring the fire indefinitely — over-conservative (more so than the deadline-branch would have been), but it never fires headless without a fresh live window, which is the ratified safety-over-liveness posture.

### D7. Opt-in, default OFF (DP4c)

A config surface (lean: `config/autonomy.yaml`, section `countdown_auto_fire`) carries `enabled: bool = False`, `window_s`, `sweep_interval_s`, `reversibility_floor`. **Absent file ⇒ disabled** (fail-closed for the feature = OFF = today's behavior). With it **off, COUNTDOWN behaves exactly as today** (explicit-confirm) — **zero regression**; the ADR-030/P4.5 human-in-every-loop trust surface is **preserved unless an operator deliberately enables it**. The opt-in default **is** the honesty mechanism (roadmap §10 "opt-in, fail-closed"): the system never *silently* goes human-out-of-loop. Loaded once in `_build_context`; the resolved config is the sweeper's source for `window_s`/`sweep_interval_s` and `process_tool_calls`' source for the stamp gate (D2).

**`enabled` gates both the stamp path *and* the fire path.** It is not only a stamp-time condition (D2): because a durable `expires_at` from a previous enabled run survives into a later disabled run, the **sweeper itself is gated on `enabled` at runtime** (D1 — not started when disabled, or re-checks before each fire). Without this, a disable-then-restart could fire stale deadlines, breaking the "disabled ⇒ byte-identical" guarantee (R0-B-on-plan A2). The two gates together make OFF mean OFF — no new deadline is stamped *and* no surviving deadline fires.

### D8. `RB-AUTOFIRE` — the honest residual (DP4d)

> **`RB-AUTOFIRE`** — When COUNTDOWN auto-fire is enabled, a gated operation **executes with no human in the loop at fire time**. The human-in-the-loop moment moves to the **config-time** decision to enable auto-fire (+ the unused cancel window); within the window a human may still preempt (approve early / cancel), after it the operator's standing "approve-unless-cancelled" posture actuates the call. This is **qualitatively beyond `RB-AUTHZ`**: `RB-AUTHZ` left *any authenticated account* a full actuator; auto-fire lets **no account at all** actuate within the window. Bounded by: **COUNTDOWN-only, HARD never** (D2/4a); the **reversibility floor** — irreversible ops never headless-fire (D2/4b); and **opt-in, default OFF** (D7). The conservative boot re-arm (D6) ensures no call fires without a live cancel window having existed.

This reads as honestly as `RB-FS/NET` and `RB-AUTHZ` did — the deliberate weakening is **Accepted as the real surface, not softened** (roadmap §177).

### D9. The room-enumeration read API (the gap the sweeper exposes)

`EventStore` exposes no room listing (invariant #2). The sweeper needs to enumerate candidate rooms. A **read-only** method is added (lean: `EventStore.list_room_ids() -> list[RoomId]`, or a narrower "rooms with an unresolved COUNTDOWN pending" query if the room count grows). Read-only, no append, no spine coupling — it touches only the SQLite `rooms` table the store already owns. Pure additive read API.

### Amendments carried by this slice (inscribed at impl — plan task P4.6-7)

- **ADR-030 D4** — the deferral **lands**: auto-fire-on-timer was "a clean follow-up slice"; amend deferred → **realized** (this ADR owns the durable-timer design).
- **ADR-030 D7(c)** — the probed invariant *"COUNTDOWN has no server-side auto-fire (no headless execution)"* is **conditionally inverted** for the COUNTDOWN tier when opt-in is on. **This is the honest-inscription amendment** — D7(c) is annotated, not deleted: it remains true when auto-fire is OFF (the default) and bounded (COUNTDOWN-only, reversibility-floored) when ON.
- **ADR-005** (annotation) — the COUNTDOWN tier's *consequence* gains a timer; the **tier-decision logic is unchanged** (`decide_tier` byte-frozen).
- **ADR-025 D6** (note) — a new **bounded background-task surface** (the sweeper) sits beside the single writer: it discovers on the reader path and actuates via the writer executor, preserving the single-writer-consistency + reader-liveness model.

### P5.1b annotation (ADR-042 / `_schedule_sweeper`)

> **`_schedule_sweeper`** (ADR-042 D1 / P5.1b) reuses this ADR's **pattern** — the
> asyncio-task lifecycle, discover-on-reader / act-on-writer, `except CancelledError:
> raise`, lifespan start-when-enabled + clean teardown — but **shares NONE of the
> spine-critical actuation code**: `_countdown_sweeper`, `_discover_expired_pendings`, and
> `_writer_approve_helper` are the `RB-AUTOFIRE` security crux (still-pending predicate +
> writer-atomic actuation of a *gated* op). The schedule sweeper's logic is independent:
> it discovers *due schedules* (not expired pendings) and its act is `run_pipeline` +
> `create_pipeline_run` + re-arm — **never** `_writer_approve_helper`. Duplicating the
> ~10-line skeleton is correct: **spine-untouched > DRY** for trivial control flow.
>
> **`RB-PIPELINE-SCHED`** (ADR-042 D8) is the **milder neighbor** of `RB-AUTOFIRE`:
> `…-SCHED` initiates a *reversible* run with no human at *start* time; `RB-AUTOFIRE`
> actuates a *gated* pending (possibly irreversible). The distinction: `RB-AUTOFIRE`
> applies a *pre-gated, pre-approved pending*; `RB-PIPELINE-SCHED` starts a new
> *reversible* run. `countdown_auto_fire=None` in every scheduled run ensures the two
> residuals are categorically separate (ADR-041 D5 / ADR-042 D6).

## Considered alternatives

- **DP1 (a) in-process per-pending timer / (c) external scheduler** — see D1 (loses restart-survival / over-builds).
- **DP4b (b1) fire-all-COUNTDOWN (no floor)** — most faithful to "the timer doesn't re-decide," but lets an *irreversible* op execute with no human ever in the loop — the sharpest edge of the residual. **Rejected** for the reversibility floor (D2). *(Per-tool opt-in `auto_fire_eligible` (b3) is a compatible future extension that composes with the floor; deferred — the floor bounds the blast radius now.)*
- **DP2b (ii) sentinel principal** — pollutes the `approver_user_id` namespace; see D4.
- **DP3 a new resolution event type / proactive expiry-clear** — ripples the idempotency scan + snapshot; moot under append-only; see D5.
- **DP1″ (i) fire-immediately-on-boot / (iii) leave-for-explicit-human** — (i) risks firing a window the operator never saw live; (iii) voids the auto-posture on every restart. **Re-arm (ii)** is the conservative middle (D6).

## Consequences

**Positive:** COUNTDOWN gains the auto-fire convenience its name always implied, **durably + restart-safe**, with the human-out-of-loop blast radius **bounded three ways** (COUNTDOWN-only, reversibility-floored, opt-in-OFF) and the no-approver fact **recorded honestly**. The slice **closes the boot-recovery gap** ADR-030 left open (for COUNTDOWN). Reuse of the confirm closure means **no new actuation surface, no new idempotency reasoning, no executor change**.

**Negative / residual:** `RB-AUTOFIRE` (D8) — a real human-out-of-loop posture, Accepted not softened. The conservative re-arm (D6) re-arms a fresh window on **every** restart, so a sustained restart loop can defer a fire indefinitely (the explicit cost of the fresh-full-window posture F2 ratified). Fire latency is granular to `sweep_interval_s`. A new background-task surface (the sweeper) is added to the process lifecycle — it must shut down cleanly (cancelled in lifespan teardown) and must never block the writer (discovery is read-path).

**Neutral:** with auto-fire OFF (the default) the behavior is **byte-identical to today** — the additive `expires_at`/`approval_source` fields are never set and never inspected on any existing path. The agent does not react to the auto-fired tool's result in-turn (ADR-028 D4 no-re-dispatch carried forward).

## Reversibility

| Decision | Reversibility |
|---|---|
| D1 durable expiry + sweeper | **Medium** — the `expires_at` field shape + the sweeper lifecycle bind future consumers; the sweeper itself is removable (off ⇒ inert). |
| D2 eligibility gate (COUNTDOWN-only + floor + enabled) | **Do-not-reverse (4a)** / **Medium (floor value)** — HARD-never is a spine invariant; the floor *value* is config-tunable. |
| D3 reuse the confirm closure | **Low** — a refactor seam; the shared helper is the natural shape. |
| D4 provenance marker | **Medium** — `approval_source` is an additive audit field; future consumers may key on it. |
| D5 inherited idempotency | **Do-not-reverse** — the still-pending + executor guards are the security crux (ADR-030 D7). |
| D6 boot re-arm derivation | **Low** — a read-time rule; tunable without schema change. |
| D7 opt-in default OFF | **Do-not-reverse (default)** — fail-closed default is the honesty mechanism. |
| D8 `RB-AUTOFIRE` residual | **Do-not-reverse** — honest inscription of the real surface. |
| D9 room-enumeration read API | **Low** — additive read method. |

## References

- **ADR-030** (the confirm machinery this rides — D1 pending record, D3 the actuate path C1 reuses, D4 the auto-fire deferral that lands, D7(c) the no-headless invariant conditionally inverted, Consequences L104-106 the boot-recovery gap) + `src/orchestrator/api/app.py:734-867,316,1054-1062`.
- **ADR-005** (D4 three-tier semantics — COUNTDOWN gains a timer, decision logic unchanged; §5(c) the `git_push` rev=1 → COUNTDOWN example — why COUNTDOWN ≠ reversible, D2/4b) + `src/orchestrator/autonomy/scoring.py:11-16,165-207`.
- **ADR-028** (the runtime executor — D2 dispatch + the `call_id` double-exec guard, D6 t4 sole-appender) + `src/orchestrator/tools/executor.py`.
- **ADR-039** (D6 approver provenance — the field D4's no-approver case extends; D5 `RB-AUTHZ`, the residual `RB-AUTOFIRE` steps beyond) + `src/orchestrator/core/event.py:203-218,351-380`.
- **ADR-025** (D6 single-writer / two-connection model the sweeper sits beside) + the append-only store triggers `src/orchestrator/core/event_store.py:78-90`; the room read APIs `:358-382`.
- **Process:** `docs/process/architect-briefs/P4.6.md` (the decision-surface, 5 DPs) + ratification commit `96a9a4d` + `docs/process/reviews/P4.6/external-r0b-prompt.md` (the lean dual-lens) + `docs/process/dual-lens-r0b.md`.
