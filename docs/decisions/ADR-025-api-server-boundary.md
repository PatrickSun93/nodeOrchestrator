# ADR-025: API/Server Boundary — HTTP/WS over the Event Store + Room Runtime

**Status:** Proposed — 2026-06-02 (senior-drafted per P3.2 brief; awaiting architect accept)

**Scope:** P3.2 — the first `api/` package: a thin FastAPI HTTP/WS server over the existing event store + room runtime + bootstrap. Governs **the wire contract** (the frozen `Event`/`Room`/`Snapshot` schemas + the intent/response/WS envelopes + the OpenAPI/AsyncAPI artifacts) that ≥5 future tasks bind to (P3.3 GUI, P3.6, future clients), **the backend-authoritative invariant** (no decision surface in the API), **write-surface forge-prevention**, and **the MVP trust posture**. Wraps `core/`/`rooms/`/`autonomy/`/`llm/` **unchanged**. Does NOT govern: the GUI (P3.3 — binds this contract); MCP/plugins (Wave 2); remote/multi-user hardening beyond the ruled MVP; any change to backend decision logic.

## Context

`origin/main` has the full backend but **no network surface** (no `api/`, no `main.py`, no server). The substrate the API wraps (verified):
- **Read** — `EventStore` (sync `sqlite3`, **caller-owns-connection**): `get_room`, `get_room_events` (ordered `timestamp ASC, rowid ASC`), `get_event`, `get_thread` (recursive CTE; raises `EventNotFoundError`), `get_relations_*`; plus `derived/snapshot.py::produce_snapshot(events, room, *, snapshot_at) -> Snapshot` (pure, frozen).
- **Write/drive** — `EventStore.append(Event) -> EventId` (validates metadata + room-exists + parent; append-only enforced by schema TRIGGERs + `frozen=True` + no update/delete API), then `run_turn(room, current_event, *, available_agents, available_skills, event_store, llm_router, regex_registry, tools) -> TurnResult` — **sync**; reads a snapshot, evaluates `next_room_state` (appends a `state_transition` event; **never mutates `room.state`**), filters agents, `dispatch_turn`s (which runs the **autonomy gate** + **LLM router**). It appends the agents' utterances + the transition as side effects.
- **The forge surface** — `Event.author` is validated by `is_valid_author` (`event.py:361`): `^(user|system|agent:[a-zA-Z0-9_-]+)$`. The schema *permits* all three; **the API must not** — a client must only ever produce `author:"user"`.
- **Boot** — `bootstrap.py::load_and_validate_llm_layer(config_dir) -> LLMLayer{providers, models, agent_configs, override, health}`. **Gap:** there is **no concrete `LLMRouterProtocol`** in the codebase — `run_turn` takes one, but only `select_model_and_provider` (async, the routing *decision*) + `provider.call` (async) exist; every current caller injects a mock. P3.2 is the **first** to need a real one (see D3).
- **Deps** — `pydantic`, `httpx`, `PyYAML`; Python 3.12; `pytest-asyncio` present. **FastAPI/uvicorn must be added.** `config/ui_strings/` does **not** exist (the GUI builds it — D5).

## Hard requirements — the constitutional / security spine (NON-NEGOTIABLE; inscribed, not chosen)

1. **No decision surface in the API.** The server never decides state, agent activation, model/routing, or autonomy. It appends a user event and calls `run_turn`; the **state machine / `should_agent_speak` / LLM router / autonomy gate (all backend code) decide.** No new `LLMPurpose`; no routing/judgment logic in `api/` (Principle 5; CLAUDE.md).
2. **Write-surface forge-prevention.** A client may append **only** `author:"user"` events of a fixed intent-type allowlist. It is **impossible** to forge `author:"system"`/`"agent:<id>"` or a `STATE_TRANSITION`/`AUTONOMY_DECISION`/`AUTONOMY_REFUSAL` (backend is their sole author). Fail-closed.
3. **State machine 不暴露.** The wire carries **raw** `state`/event-type names (the product's internal contract); human-term mapping is the GUI's (`config/ui_strings/`, P3.3).
4. **Trust boundary.** First network surface: bind scope, input validation, fail-closed, payload limits. MVP posture is ruled (D7); the boundary's *existence* is non-negotiable.

## Decisions

### D1. Stack — FastAPI + uvicorn (architect-ruled a)

FastAPI (native Pydantic ↔ our `frozen=True` schemas; first-class WS; auto-generated OpenAPI = the pinnable contract) on uvicorn. Added as an **optional dependency group** `[project.optional-dependencies] api = ["fastapi", "uvicorn[standard]"]` so the core library stays importable without the server. The FastAPI `TestClient` (over the existing `httpx` dep) + `pytest-asyncio` cover HTTP + WS tests.

### D2. HTTP/WS split — HTTP for create/read/snapshot **and intent**; WS read-only for the live stream (senior fork: intent over HTTP POST)

- **HTTP** — `POST /rooms` (create), `GET /rooms/{id}`, `GET /rooms/{id}/events`, `GET /rooms/{id}/snapshot`, `GET /events/{id}/thread`, and **`POST /rooms/{id}/intent`** (the write path).
- **WS** — `GET /rooms/{id}/stream` (server→client **only**): on connect, replay the current event list (from a cursor), then push each newly-appended event live.
- **Intent is HTTP POST, not bidirectional WS** (senior fork): a discrete request/response with HTTP status codes is the cleaner home for the **fail-closed forge boundary** (a rejected intent → `403`/`422` with a reason; an accepted one → the appended event + the turn result), keeps the WS a pure read-only push channel (simpler lifecycle + trust surface), and isolates the single write/forge-prevention chokepoint to one auditable endpoint. The WS never accepts client→server *writes*.

### D3. Backend-authoritative — the API has no decision surface (HR#1)

The intent endpoint does exactly two backend calls: `event_store.append(user_event)` then `run_turn(...)`. **Every decision stays backend:** `next_room_state` (state), `decide_agents_for_room` + `should_agent_speak` (activation), `select_model_and_provider` (routing), the autonomy gate (operation-gating). The API adds **no `LLMPurpose`** and **no routing/judgment**.

The one LLM-touching glue P3.2 must add — the missing concrete **`llm_router`** — is a **thin adapter** (`api/llm_adapter.py`) satisfying `LLMRouterProtocol.call(request)` by delegating the routing **decision** to the unchanged `select_model_and_provider` and then invoking the selected `provider.call`. It **makes no routing decision of its own** (it executes the backend's); it only bridges sync↔async (run on the serialized executor, D6). This is wrapping, not a decision surface — explicitly called out so reviewers can confirm the boundary holds.

### D4. Write-surface forge-prevention (HR#2) — the security crux

The wire **`IntentRequest`** carries **only** `{type, content, metadata?, parent_id?}` — **no `author`, no `id`, no `timestamp`, no agent fields**. The server constructs the `Event` itself:
- `author` is **hardcoded to `"user"`** (never read from the request — a client literally cannot set it).
- `id = generate_event_id()`, `timestamp = now_ms()` — server-stamped.
- `type` must be in the **intent-type allowlist** (D4a); anything else → **`422`** (fail-closed), *before* any append.
- `metadata` is validated via `validate_metadata(type, metadata)` (fail-closed `422` on a typed-metadata violation).
- `parent_id`, if present, is validated by `append` (same-room/exists) → `422`/`404` on violation.

A client therefore **cannot** forge `author:"system"`/`"agent:<id>"` (the field is server-set), nor a `STATE_TRANSITION`/`AUTONOMY_DECISION`/`AUTONOMY_REFUSAL`/`TOOL_*` (off-allowlist → `422`). The backend remains the **sole author** of system/agent/transition events (they only ever arise from `run_turn`/`dispatch_turn`). This is the "operation-gating = code" analogue: the *gate* is server code, not client-trusted input.

#### D4a. Intent-type allowlist (senior fork) — `{USER_INPUT, DECISION, RETRACTION}`; `UTTERANCE` excluded

- **`USER_INPUT`** — the primary human message that drives a turn (untyped metadata; the common path).
- **`DECISION`** — the human making/confirming a decision (e.g. confirming an autonomy-gated action, or a decision in `idea_validation`); the user-confirm actuator the GUI needs. Carries `DecisionMeta` (validated).
- **`RETRACTION`** — the human correcting the record (retract a prior statement). Carries `RetractionMeta` (validated; `retracts` must reference an existing event).
- **`UTTERANCE` excluded.** `UTTERANCE` is the **agent** speech act (agents emit it via `dispatch_turn`); letting a client forge an `UTTERANCE` would (a) blur the human/agent boundary and (b) let a client directly drive `UTTERANCE`-keyed state transitions (`research`/`idea_validation`/`free_chat` `setup→…`), bypassing the intent that those transitions reflect *agent* activity. Humans speak via `USER_INPUT`. (Broadening the allowlist later is an additive config/ADR change.)

### D5. Wire = raw schemas (HR#3) — the contract is the frozen models + OpenAPI/AsyncAPI

The wire `Event`/`Room`/`Snapshot` are the **existing frozen, `extra="forbid"` models** emitted **raw** (raw `state` string, raw `event_type` names). The GUI maps to human terms via `config/ui_strings/` (P3.3 builds it). The **pinned contract** (the inscribe-before-producer artifact, committed in the first atomic) =
- the Pydantic wire models (`Event`, `Room`, `Snapshot`, `IntentRequest`, `IntentResponse`, the WS `StreamMessage` envelope),
- the **OpenAPI** JSON (FastAPI-generated, committed under `docs/` or `api/`),
- a hand-authored **AsyncAPI** note for the WS `/rooms/{id}/stream` channel (message shapes + the connect-replay-then-stream semantic).

`IntentResponse = {appended_event: Event, turn: TurnResult}` (the appended user event + the `run_turn` result — `utterances`, `failed_agents`, `total_asked`, `snapshot_failed`). `StreamMessage` is a discriminated envelope `{kind: "event", event: Event}` (+ `{kind:"error", …}` / `{kind:"replay_complete"}`).

### D6. Sync-core bridge + push (senior forks)

- **Serialized single-writer executor.** The store is sync `sqlite3` (caller-owns-conn, single-writer, `check_same_thread`). All core calls (store reads/writes + `run_turn` + the `llm_adapter`) run on **one dedicated single-thread executor** holding the **one** connection; async handlers `await loop.run_in_executor(core_executor, …)`. This serializes all DB/turn work on one thread (sidesteps `check_same_thread` + write contention; append-only + single-writer makes serialization correct), keeps the event loop free for WS fan-out, and makes a turn's multi-append atomic w.r.t. other writers. Acceptable perf for a localhost MVP; WAL/read-replica is a forward hook.
- **Per-room pub/sub hub (`RoomEventBus`) + cursor-diff capture.** A registry of per-subscriber `asyncio.Queue`s keyed by room. The write path, on the executor: capture the room's pre-turn event cursor → `append(user_event)` + `run_turn` → read the **newly-appended** events (`get_room_events` after the cursor) → publish them to the hub → fan out to each room subscriber's queue (on the loop). **No `EventStore` change** (wrap-don't-reimplement; the hub observes via cursor-diff, not by hooking `append`). WS connect = **replay-then-subscribe**: send the current events (from a cursor) first, then stream new ones, so no event is missed in the gap between snapshot and subscribe. **Backpressure/failure-isolation:** bounded queues; a slow/disconnected subscriber is dropped (full queue / send raises → unsubscribe) and **never blocks the writer**.

### D7. Trust boundary — localhost-trust MVP (architect-ruled c)

- **Bind** `127.0.0.1` only (the GUI is a local app). **Auth: none** (localhost-trust). Input validation + fail-closed (D4) + a **payload size limit** on intent bodies. CORS restricted to the local GUI origin.
- **Remote hardening is a forward hook** (auth tokens, TLS, rate-limiting, network bind) — explicitly out of MVP scope, recorded so the boundary can be hardened without re-architecting (the forge-prevention + no-decision-surface invariants already hold regardless of bind scope).

## Considered alternatives

- **Intent over bidirectional WS** — Rejected (D2): a client→server write channel over WS complicates the fail-closed forge boundary + error semantics + lifecycle; HTTP POST gives status-coded rejection and one auditable write chokepoint. WS stays read-only push.
- **Pre-humanized wire (API maps to human terms)** — Rejected (D5): the wire is the product's internal contract; humanization is GUI-locale concern (`ui_strings`). Pre-humanizing would bind the API to UI copy + leak presentation into the contract ≥5 tasks share.
- **Per-request sqlite connections / a thread pool of connections** — Rejected for MVP (D6): a serialized single-writer is simpler + correct for append-only single-writer sqlite; pooling is a perf forward hook (WAL).
- **Hook `EventStore.append` for push** — Rejected (D6): would modify core (violates wrap-don't-reimplement); cursor-diff observation keeps core untouched.
- **Cursor-polling for the live stream** — Rejected (architect-ruled a = pub/sub): polling wastes cycles + adds latency; in-process pub/sub is the right in-process design.
- **Let the client set `author`/`id`/`timestamp`** — Rejected, constitutionally (D4): that *is* the forge vector. The server stamps all three.

## Consequences

**Easier:** the P3.3 frontend binds a frozen contract immediately (inscribe-before-producer; unblocks the frontend track); the backend stays wrapped + unchanged; the forge boundary is one auditable endpoint; the live stream is push (no polling).

**Harder:** a new concurrency surface (serialized executor + async WS lifecycle) to test (heavy §2/§3); a `fastapi`/`uvicorn` dependency; P3.2 must add the missing concrete `llm_router` adapter (the one LLM-touching glue — kept decision-free).

**Neutral:** serialized single-writer trades throughput for simplicity/correctness (localhost MVP; WAL later). The allowlist `{USER_INPUT, DECISION, RETRACTION}` is additively broadenable. Raw wire means the GUI owns all humanization.

## Reversibility

| Decision | 6-month reversal cost |
|---|---|
| D1 FastAPI / optional `api` extra | **Low** — a self-contained package + optional dep. |
| D2 HTTP-intent / WS-read-only | **Low–Med** — moving intent onto WS is a handler change, but re-opens the forge-boundary design. |
| D3 backend-authoritative / no decision surface | **Do-not-reverse** — constitutional. The `llm_adapter` delegating to `select_model_and_provider` is the seam to keep decision-free. |
| D4 forge-prevention (server-stamped author/id/ts + allowlist) | **Do-not-reverse** — the security crux. |
| D5 raw wire + pinned contract | **Med** — once P3.3 binds it, changes are contract migrations (the cost inscribe-before-producer front-loads). |
| D6 serialized executor + pub/sub | **Med** — the core concurrency design; swapping to pooled/WAL is a contained rework behind the same contract. |
| D7 localhost-trust MVP | **Low** — hardening is additive (bind/auth/TLS) without touching the invariants. |

## References

- `docs/process/architect-briefs/P3.2.md` (the 4 decisions + the ⭐ non-negotiable spine).
- `docs/process/senior-plans/P3.2.md` (this ADR's plan; atomic graph, the §test plan, the senior forks).
- `docs/process/reviews/P3.2/external-r0b-prompt.md` (dual-lens R0-B — concurrency/failure/forge cross-family lens).
- `src/orchestrator/core/event_store.py` + `core/event.py` (`is_valid_author:361`, `EventType`, `validate_metadata`) — the read/write API + the forge surface.
- `src/orchestrator/rooms/runtime.py` (`run_turn` — the sync drive entry) + `agents/dispatch.py` (`LLMRouterProtocol`, the autonomy-gate/router path) + `derived/snapshot.py` (`produce_snapshot`).
- `src/orchestrator/bootstrap.py` (`load_and_validate_llm_layer` — the boot the server composes) + `llm/router.py` (`select_model_and_provider` — the routing decision the `llm_adapter` delegates to).
- `handoff.md` §6.2/§899 (state-machine 不暴露; UI contract backend-authoritative); `docs/process/P3-roadmap.md` §4/§5/§9; CLAUDE.md (routing=code); ADR-001 (append-only), ADR-011/ADR-012 (dispatch/state machine), ADR-023 (bootstrap).
