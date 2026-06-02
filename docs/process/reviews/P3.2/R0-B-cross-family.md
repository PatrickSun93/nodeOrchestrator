---
task_id: P3.2
round: R0-B-cross-family
reviewer_family: deepseek
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 9
verdict_history:
  - verdict: needs_architect
    at_commit: a51cfcd
    findings_count: { red: 0, yellow: 3, green: 6 }
    note: >-
      initial R0-B-cross-family (deepseek). Security + backend-authoritative fronts sound (forge
      fail-closed; cursor-diff race-free under serialization; no decision surface). 3 🟡 on the
      concurrency/failure surface — Y1 replay/subscribe ordering inverted (gap), Y2 single-executor
      serializes reads behind a multi-second run_turn (GUI hangs = liveness), Y3 partial-turn error
      ambiguous (append-fail vs turn-fail). All resolvable at plan stage.
  - verdict: clean
    at_commit: PENDING-plan-stage-routing-absorption
    findings_count: { red: 0, yellow: 0, green: 9 }
    note: >-
      Bumped per architect plan-stage routing (all 3 → α) + RC-10 + dual-lens Step 5 — exactly this
      review's leans. Y1 → ADR-025 D6 + plan §4 corrected to subscribe-then-replay+dedup (register
      queue first, then replay, dedup overlap by event id — eliminates the post-SELECT-pre-subscribe
      window the inverted prose would have dropped). Y2 → a separate read-only WAL connection
      (check_same_thread=False) + read executor for GET/WS-replay; writes + run_turn stay on the
      serialized writer executor; the API opens a second EventStore instance (no core change, no wire
      change) so a multi-second run_turn no longer blocks reads (the GUI-liveness fix). Y3 → a pinned
      IntentError{stage: append|turn, appended_event_id, reason} folded into the contract (ADR-025 D5)
      distinguishing safe-retry append-fail from intent-already-landed turn-fail. §2/§3 tests added
      (read-during-turn liveness; gap/dup-free subscribe-replay; stage-distinguished error). All 3 🟡 →
      🟢 (9🟢). (R0-A's arch Y1 DECISION/RETRACTION-authority α-lite was routed in parallel — ADR-025
      D4a; see R0-A verdict_history.) Did NOT accept ADR-025 or advance state.
---

# P3.2 R0-B cross-family review (plan + ADR-025) — API/server boundary

| Field | Value |
|---|---|
| Round | R0-B-cross-family (true cross-family, plan-stage; concurrency/failure-mode/forge lens) |
| Reviewer family | deepseek |
| Stage | Plan + ADR-025 (Proposed), pre-impl |
| Artifacts | `senior-plans/P3.2.md`, `ADR-025-api-server-boundary.md` |
| Baseline | `main` — `event_store.py` (sync sqlite3, caller-owns-conn, `get_room_events` ordered `timestamp ASC, rowid ASC`, TRIGGER-enforced append-only); `event.py:364` (`is_valid_author` permits user\|system\|agent); `rooms/runtime.py:47` (`run_turn` sync, appends side-effect events); `agents/dispatch.py` (`LLMRouterProtocol` — no concrete impl exists) |
| Prior reviews | None yet (R0-A-on-plan pending) |
| Date | 2026-06-02 |
| Verdict | **clean** (bumped from needs_architect) — 0🔴 · 0🟡 · 9🟢 |

> **Routing-absorption note (RC-10 + dual-lens Step 5).** All 3 🟡 routed **α** — exactly these leans. **Y1** → ADR-025 D6 + plan §4 corrected to **subscribe-then-replay + dedup** (register-queue-first → replay → dedup overlap by id; eliminates the dropped-window the inverted prose implied). **Y2** → a **separate read-only WAL connection + read executor** for GET/WS-replay (writes + `run_turn` stay on the serialized writer executor; a second `EventStore` instance, no core change) → a multi-second `run_turn` no longer blocks reads (the GUI-liveness fix). **Y3** → a pinned **`IntentError{stage:"append"|"turn", appended_event_id, reason}`** folded into the contract (ADR-025 D5) distinguishing safe-retry append-fail from intent-already-landed turn-fail. §2/§3 tests added. All 3 🟡 → 🟢. Original findings preserved below.

## Lens preamble

Cross-family concurrency/failure-mode/forge lens per `external-r0b-prompt.md` probes. P3.2 is the **first network surface**: a new concurrency design (async FastAPI + WS lifecycle + concurrent clients over sync single-writer sqlite), a trust/forge boundary, and a contract ≥5 future tasks bind to. This is exactly the surface the cross-family lens catches errors on — the P1.4 precedent (DeepSeek caught `event_store` failure-path + caller-contract bugs the in-family review missed) applies directly. The external prompt names the highest-value targets: cursor-diff races, replay-subscribe gap/dup, single-executor liveness under multi-second turns, partial-turn-on-raise consistency, WS drop recovery, forge bypass paths. Over-correcting for Claude biases: sycophancy toward "airtight"/"atomic"/"no gap" claims without tracing the actual execution ordering, and toward the serialized-executor design without stress-testing the liveness trade-off.

## Findings

| # | Sev | Finding | Evidence |
|---|---|---|---|
| Y1 | 🟡 | **Replay-then-subscribe ordering is underspecified — "replay first, then subscribe" produces a gap.** ADR-025 D6: "WS connect = replay-then-subscribe: send the current events (from a cursor) first, then stream new ones, so no event is missed in the gap between snapshot and subscribe." This reasoning is inverted: if replay happens BEFORE subscribe, events appended during the replay window are **missed** — they were written after the replay SELECT but before the subscribe registered the queue. The correct ordering is **subscribe first, THEN replay** — the queue captures events appended during replay, and any overlap (events appearing in both replay and subscription) is deduplicated. The serialized executor CAN make this gap-free: if both subscribe (register queue) and replay (SELECT) run atomically on the executor, no write can interleave between them. But the plan must pin subscribe-before-replay, not replay-before-subscribe. The current prose actively misleads the implementer toward the wrong ordering. | ADR-025 D6 ("replay-then-subscribe… so no event is missed" — reasoning is inverted); plan §4 ("WS connect = replay-then-subscribe (no gap)") |
| Y2 | 🟡 | **Single-executor serializes ALL reads alongside writes — a multi-second `run_turn` blocks every WS replay, GET endpoint, and health check.** ADR-025 D6: "All core calls (store reads/writes + run_turn + the llm_adapter) run on one dedicated single-thread executor." A `run_turn` that takes 5 seconds of LLM time blocks **all** reads for 5 seconds — a new WS client connecting during a turn gets zero events until the turn completes (hang), a GET /rooms/{id}/snapshot stalls, and the GUI appears frozen. This is a **liveness** problem for an interactive local GUI, not just a throughput concern. SQLite supports concurrent reads in WAL mode — reads do not need to be serialized on the same executor as writes. The plan acknowledges the perf trade-off ("Acceptable for a localhost MVP") but does not acknowledge the *liveness* consequence: the GUI is unresponsive during every turn. The fix: use a **separate read connection** (WAL mode, `check_same_thread=False`, read-only executor) for GET/WS-replay, keeping only writes + `run_turn` on the serialized writer executor. | ADR-025 D6 (all core calls on one executor); plan §4 (serialized single-writer executor holding all reads); SQLite WAL-mode concurrent-read capability |
| Y3 | 🟡 | **Partial-turn error response is ambiguous — `run_turn` raising after `append` succeeded leaves the client not knowing whether to retry.** The write path on the executor: `append(user_event)` → `run_turn(...)`. If `append` succeeds (the user event IS persisted) but `run_turn` raises (LLM failure, state machine error, agent crash), the API returns a `5xx`. The client sees an error but doesn't know: (a) was the intent recorded but the turn failed? → retrying the intent would create a duplicate. (b) did the intent also fail to append? → safe to retry. The plan says "run_turn/append raises → 5xx, no partial-state leak" — but the user event already appended IS partial state (the turn didn't process it). The `IntentResponse` carries both `appended_event` and `turn` — but on failure, neither is returned to the client. The error response should distinguish "append failed" (safe to retry) from "append succeeded, turn failed" (intent recorded, don't re-send). At minimum, the error body should include the `appended_event.id` so the client can query whether the intent landed. | Plan §7-§3 failure modes; ADR-025 D3 (append → run_turn sequence); no distinction between append-failure and turn-failure in the error path |
| G1 | 🟢 | **Cursor-diff is race-free under the serialized executor.** The cursor capture + append + run_turn + read-past-cursor + publish all run atomically on the single executor. Between executor tasks, no interleaving is possible. Two concurrent intents on the same room serialize: task A completes entirely (including publish) before task B starts, so task B's cursor is past all of A's events and B publishes only its own events — no duplicate publication. The `get_room_events` ordering (`timestamp ASC, rowid ASC`) is deterministic — equal-timestamp events are tiebroken by `rowid` (insertion order). Cross-family trace: the serialized executor makes the cursor-diff design race-free by construction. | ADR-025 D6 (serialized executor + cursor-diff on executor); `event_store.py:374` (ORDER BY timestamp ASC, rowid ASC) |
| G2 | 🟢 | **Forge-prevention is fail-closed — `IntentRequest` structurally prevents author/id/timestamp forgery.** The wire model has NO `author`, `id`, or `timestamp` fields (`extra="forbid"` would reject them if a client tried). The server hardcodes `author="user"`, calls `generate_event_id()`, stamps `now_ms()`. The intent-type allowlist `{USER_INPUT, DECISION, RETRACTION}` rejects off-allowlist types (`STATE_TRANSITION`, `AUTONOMY_DECISION`, `UTTERANCE`, etc.) with `422` before any append. `validate_metadata(type, metadata)` catches typed-metadata violations (`DecisionMeta`, `RetractionMeta`). `parent_id` validated by `append`. Cross-family trace: no path from `IntentRequest` to a forged `author:"system"`/`"agent:<id>"` event or a non-user event type — the server is the sole author of all non-user events (which arise only inside `run_turn`/`dispatch_turn`). The `UTTERANCE` exclusion is correct: it prevents client-driven `UTTERANCE`-keyed state transitions, and humans speak via `USER_INPUT`. | ADR-025 D4/D4a; plan §3; `event.py:361` (is_valid_author); `IntentRequest` schema (no author/id/timestamp fields) |
| G3 | 🟢 | **DECISION in the allowlist is safe — the autonomy gate proposes, the user confirms.** A client sending `DECISION` represents the user confirming a decision. `DECISION` carries `DecisionMeta` (validated: `based_on`, `trade_offs`, `promotion`, `hypothesis_id`, `vk_id`, `user_id`). The `author` is server-stamped `"user"` — the metadata `user_id` is the confirming user, not the event author. `promotion=True` in metadata does NOT trigger `promote_hypothesis` — promotion is a separate user-confirm actuator (ADR-016 D3/D10), not called by `run_turn` on a `DECISION` event. The state machine's `_next_<room_type>_state` determines whether `DECISION` is a valid trigger for the current state — if not, `next_room_state` returns `None`. A client cannot force a transition via `DECISION` that the state machine wouldn't accept. Cross-family trace: `DECISION` in the allowlist is the transport for user confirmation — the autonomy gate proposes; the API transports the user's confirm; the backend decides. | ADR-025 D4a; `DecisionMeta` schema (promotion is metadata, not an actuator); `rooms/runtime.py` (run_turn does NOT call promote_hypothesis); `rooms/state_machine.py` (next_room_state gates transitions) |
| G4 | 🟢 | **Backend-authoritative holds — the API has no decision surface.** The intent endpoint does exactly `event_store.append(user_event)` → `run_turn(...)`. Every decision stays backend: `next_room_state` (state), `decide_agents_for_room` + `should_agent_speak` (activation), `select_model_and_provider` (routing), the autonomy gate (operation-gating). The `llm_adapter` delegates the routing decision to `select_model_and_provider` — it executes the backend's choice, makes none of its own. **No new `LLMPurpose`** — the taxonomy stays content-gen-only (verified: all existing purposes are content-gen; no routing/judgment purpose is added). Cross-family trace: no path from the API to a model-selection/state/activation decision — the API is a view + intent transport. | ADR-025 D3 (HR#1); plan §3 (llm_adapter = thin glue); `rooms/runtime.py:86-106` (next_room_state + decide_agents_for_room) |
| G5 | 🟢 | **WS drop mid-turn → turn completes + persists; reconnect recovers exactly.** The turn runs on the executor, independent of the WS connection lifecycle. If the WS drops mid-turn, the turn continues to completion (the executor is not cancelled). On reconnect, the client replays from its last-seen cursor and receives all events (including the completed turn's results). No gap — the events are in the store regardless of connection state. No duplicate — the cursor tracks the client's last-seen position. Cross-family trace: the executor-isolation + append-only store + cursor-based replay provide exactly-once recovery semantics for the live stream. | ADR-025 D6 (executor-isolated turn); plan §7-§3 (WS drop → turn completes); `event_store.py` (append-only, ordered reads) |
| G6 | 🟢 | **Contract pinned first — the wire models + OpenAPI/AsyncAPI are the right inscribe-before-producer artifact.** The first atomic (P3.2-1) commits the wire models (`IntentRequest`/`IntentResponse`/`StreamMessage` + raw `Event`/`Room`/`Snapshot`), the FastAPI-generated OpenAPI JSON, and a hand-authored AsyncAPI note. The wire carries raw state/event-type names (the GUI humanizes via `config/ui_strings/`, P3.3) — correct separation (API = transport, GUI = presentation). The `extra="forbid"` on wire models is itself a forge guard (rejects unknown/identity fields). The optional `[api]` dependency extra keeps core importable without the server. Cross-family assessment: the contract is complete enough for the P3.3 GUI to bind against — the endpoints cover the GUI's read + intent needs, the WS gives live updates, and the error surface (404/422/5xx) is standard HTTP. | ADR-025 D1/D2/D5; plan §2 (endpoints + wire models); plan §6 (P3.2-1 contract-pin atomic) |

## Synthesis

The design is sound on the security and backend-authoritative fronts. The forge-prevention is fail-closed — `IntentRequest` structurally prevents author/id/timestamp forgery, the allowlist rejects non-user event types before any append, and the backend stays the sole author of system/agent/transition events. The backend-authoritative invariant holds — the API appends + calls `run_turn`; every decision stays backend. The cursor-diff design is race-free under the serialized executor.

Three 🟡 from the cross-family lens, all on the concurrency + failure-mode surface — exactly the class of error the P1.4 precedent established the cross-family lens catches:

**Y1** (replay-subscribe ordering): The plan says "replay-then-subscribe" but the correct ordering to prevent a gap is "subscribe-then-replay." The current prose actively misleads.

**Y2** (single-executor liveness): All reads serialized on the same executor as writes means a 5-second `run_turn` blocks every WS replay + GET endpoint. The GUI hangs during turns. SQLite supports concurrent reads in WAL mode — reads should use a separate connection/executor.

**Y3** (partial-turn error ambiguity): When `run_turn` raises after `append` succeeded, the client gets a 5xx but doesn't know whether the intent was recorded. The error response should distinguish "append failed" from "append succeeded, turn failed."

All three are resolvable at plan stage — small design clarifications, no architectural changes.

## What the architect needs to route

1. **Y1 (🟡):** Replay-subscribe ordering — pin **subscribe-before-replay** in ADR-025 D6. The subscriber queue is registered first (on the executor), THEN the replay SELECT runs (on the executor). Since both are serialized, no write interleaves. Deduplicate if an event appears in both replay and queue. One sentence fix.
2. **Y2 (🟡):** Single-executor liveness — use a **separate read connection** (WAL mode, read-only executor) for GET/WS-replay, keeping only writes + `run_turn` on the serialized writer executor. At minimum, document the liveness trade-off explicitly so the GUI team (P3.3) knows reads block during turns. Lean: **α** — separate read executor (low cost, high UX payoff). Alternatively, **β** — document the trade-off and defer the read-executor to a forward hook.
3. **Y3 (🟡):** Partial-turn error response — distinguish "append failed" (safe to retry intent) from "append succeeded, turn failed" (intent recorded, don't re-send). At minimum, include `appended_event.id` in the error body. Lean: **α** — add `appended_event_id` to the error response envelope.
4. **Greens** are cross-family confirmations; no action.
