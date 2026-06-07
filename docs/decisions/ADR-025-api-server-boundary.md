# ADR-025: API/Server Boundary — HTTP/WS over the Event Store + Room Runtime

**Status:** Accepted — 2026-06-02 (architect-accepted; P3.2 plan-stage dual-lens reviews clean after all-α routing: r0b Y1 subscribe-then-replay+dedup, Y2 separate WAL read connection, Y3 partial-turn error envelope, arch Y1 allowlist-authority α-lite; constitutional spine — backend-authoritative, write-surface forge-prevention, state-machine-not-exposed, trust boundary — preserved)

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
- `author` is **server-stamped from the authenticated principal** (never read from the request — a client literally cannot set it). **[Annotated P4.5 → ADR-039, Accepted 2026-06-06: generalised from hardcoded `"user"` to `build_user_author(principal.user_id)` = `"user:<id>"`; bare `"user"` stays valid as the system-default/backward-compat form; `is_valid_author` regex generalised to include `user:<id>`.]**
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

**Authority is gated downstream, not by `validate_metadata` (arch Y1 → α-lite — keep the allowlist; verify-don't-assume).** `DECISION`/`RETRACTION` are *legitimately user-authored* (so allowlisting them is correct, **not** a forge gap), but their typed metadata carries **authority** semantics beyond shape: a `DECISION{promotion:true}` references the durable-memory promotion path (Principle 11; `hypothesis_id`/`vk_id`/`user_id`), and a `RETRACTION{retracts:X}` targets another event. `validate_metadata` checks shape/co-presence only — it does **not** confirm the referenced entity exists, is in a promotable state, or that the target is the user's own event. The API does **not** add authority checks (no decision surface — HR#1) and does **not** narrow the allowlist; instead the impl **verifies** that the **existing backend** paths gate authority: `promote_hypothesis` is the **sole** promotion actuator (ADR-016 D10 — `run_turn` does **not** call it on a bare `DECISION` event), and a `RETRACTION` is inert beyond the recorded event unless a downstream consumer acts on it. The impl-stage R0-A confirms (and the dual-lens R0-B's forge/authority lens probes) that a client-posted `DECISION{promotion:true}` cannot reach the durable-memory path through `/intent` + `run_turn` alone — i.e. shape-validation at the API plus the backend's own actuator gating is the whole gate, and the API adds none of its own.

### D5. Wire = raw schemas (HR#3) — the contract is the frozen models + OpenAPI/AsyncAPI

The wire `Event`/`Room`/`Snapshot` are the **existing frozen, `extra="forbid"` models** emitted **raw** (raw `state` string, raw `event_type` names). The GUI maps to human terms via `config/ui_strings/` (P3.3 builds it). The **pinned contract** (the inscribe-before-producer artifact, committed in the first atomic) =
- the Pydantic wire models (`Event`, `Room`, `Snapshot`, `IntentRequest`, `IntentResponse`, the WS `StreamMessage` envelope),
- the **OpenAPI** JSON (FastAPI-generated, committed under `docs/` or `api/`),
- a hand-authored **AsyncAPI** note for the WS `/rooms/{id}/stream` channel (message shapes + the connect-replay-then-stream semantic).

`IntentResponse = {appended_event: Event, turn: TurnResult}` (the appended user event + the `run_turn` result — `utterances`, `failed_agents`, `total_asked`, `snapshot_failed`). `StreamMessage` is a discriminated envelope `{kind: "event", event: Event}` (+ `{kind:"error", …}` / `{kind:"replay_complete"}`).

**Partial-turn error envelope (R0-B Y3 → α — folded into the pinned contract).** The intent path is `append(user_event)` → `run_turn`; the two failure modes are **not** interchangeable and the contract must distinguish them so a client knows whether re-sending duplicates the intent. The error body is a pinned `IntentError`:
- **`stage: "append"`** — the `append` itself failed (room missing, bad parent, metadata violation): **nothing was persisted → safe to retry** the intent. `appended_event_id: null`. HTTP `422`/`404`.
- **`stage: "turn"`** — `append` **succeeded** (the user event **is** persisted) but `run_turn` raised (LLM/state-machine/agent failure): **do NOT re-send** — the intent already landed; the client should reconcile via replay, not re-post. The body carries **`appended_event_id`** (so the client can locate the persisted intent) + `reason`. HTTP `5xx`. The store stays consistent (append-only; the user event is durable, the turn's side-effects either committed or absent — no partial write surfaced as success).

So `IntentError = {stage: "append" | "turn", appended_event_id: EventId | None, reason: str}`. The same `stage`/`appended_event_id` distinction is mirrored in the WS `{kind:"error", …}` message when a turn fails after a streamed intent.

### D6. Sync-core bridge + push (senior forks; revised per R0-B Y1+Y2 → α)

**Two connections, two executors (R0-B Y2 → α — liveness).** The store is sync `sqlite3`. The API opens **two** connections to the same DB file (it constructs **two `EventStore` instances** — one per connection; **no `core/event_store.py` change**, no wire-contract change):
- a **serialized writer connection + single-thread writer executor** — **all writes + `run_turn` + the `llm_adapter`** run here, serialized on one thread (correct for append-only single-writer sqlite; sidesteps `check_same_thread` + write contention; a turn's multi-append is atomic w.r.t. other writers). The writer connection enables **WAL mode** (`PRAGMA journal_mode=WAL`) at startup so readers see committed writes concurrently.
- a **separate read-only WAL connection (`check_same_thread=False`) + read executor** — **all `GET` reads + the WS replay** run here. Because they no longer share the writer executor, **a multi-second `run_turn` (which holds the writer thread across an LLM call) no longer blocks reads** — the GUI stays responsive during a turn (the liveness fix; the prior single-executor design hung every read behind an in-flight turn). Async handlers `await loop.run_in_executor(<writer|read>, …)` accordingly.

**Per-room pub/sub hub (`RoomEventBus`) + cursor-diff capture.** A registry of per-subscriber bounded `asyncio.Queue`s keyed by room. The write path, on the **writer** executor: capture the room's pre-turn event cursor → `append(user_event)` + `run_turn` → read the **newly-appended** events (`get_room_events` past the cursor) → publish them to the hub → fan out to each room subscriber's queue (on the loop). The cursor-diff is **race-free** because all writes/publishes are serialized on the one writer executor (between executor tasks no write interleaves; equal-`timestamp` events are tiebroken by `rowid` per `get_room_events`'s `ORDER BY timestamp ASC, rowid ASC`). **No `EventStore` change** (cursor-diff *observation*, not an `append` hook).

**WS connect = subscribe-then-replay + dedup (R0-B Y1 → α — gap-free; the prior "replay-then-subscribe" prose was inverted and is corrected).** On connect, in this order: **(1) register** the subscriber's queue in the hub (in-memory, on the loop) — from this instant every published event is enqueued; **(2) replay** the current events (read executor / read connection); **(3) dedup** — track the replayed event ids and, when draining the queue, **skip any id already sent in replay**. This is gap-free + dup-safe: register-first captures *every* event appended from step 1 onward (nothing can fall into a window after the replay SELECT but before subscribe — that window no longer exists); replay covers the prefix; an event appended between (1) and (2)'s SELECT appears in **both** and is removed by the id-dedup. (Registering *before* reading is the load-bearing ordering — replay-first would drop any event appended during the replay window.)

**Backpressure/failure-isolation:** bounded queues; a slow/disconnected subscriber is dropped (full queue / send raises → unsubscribe) and **never blocks the writer**.

**[Annotated ADR-040, Accepted 2026-06-07 (P4.6): a new **bounded background-task surface** (the COUNTDOWN sweeper) sits beside the single writer within this two-connection model. The sweeper *discovers* expired COUNTDOWN pendings on the reader path (via `reader_executor`) and *actuates* each via `writer_executor` — preserving the single-writer-consistency and reader-liveness guarantees: discovery never appends, never holds the writer; actuation is serialized on the same `max_workers=1` writer executor as all other writes. This is an additive lifespan task; the underlying two-connection model is unchanged. See ADR-040 D1/D3 for design details.]**

**[Annotated P4.5 → ADR-039, Accepted 2026-06-06 (RW7 honest-inscription): the *reader* side of this two-connection model evolved from a single shared read connection to a **per-thread WAL reader pool**. The "Considered alternatives" entry below that marks *"a thread pool of connections"* as **Rejected-for-MVP** held for a single-operator MVP, but P4.5's multi-user concurrent reads **activated the reader pool as an in-scope correctness requirement**: the single shared read-only `sqlite3` connection, driven by the multi-worker `reader_executor` (`max_workers=4`), raced under genuinely concurrent reads (e.g. two WS subscribers replaying at once). The fix (RW7, commit `d2b5566`): the `reader_executor` runs a per-worker `initializer` that opens a **per-thread** read connection (`check_same_thread=False`); each worker owns its own WAL connection (WAL permits multiple independent connections to read concurrently), so there is no shared-reader-connection contention. Routes and the HTTP auth middleware (`_resolve_principal` in `middleware.py`) resolve the calling worker's connection via `AppContext.get_reader_conn()` / `get_reader_store()` — RW7 fixed the route lambdas; RW8 extended this to the `_resolve_principal` path (which previously captured `ctx.reader_store.conn` on the async loop thread, the same pattern as the pre-RW7 WS handler). The original `reader_store` is retained only as a single-thread/test fallback. The **writer side is unchanged** — one serialized writer connection + single-thread `writer_executor` (`max_workers=1`); the single-writer append-atomicity and the pub/sub cursor-diff race-freedom guarantees above hold verbatim (the two-connection model's writer side was not touched). Net: pooling-as-perf-forward-hook was the right call for the writer; for the reader it became a correctness need once reads went concurrent.]**

### D7. Trust boundary — localhost-trust MVP (architect-ruled c)

- **Bind** `127.0.0.1` only (the GUI is a local app). **Auth: none** (localhost-trust). Input validation + fail-closed (D4) + a **payload size limit** on intent bodies. CORS restricted to the local GUI origin.
- **Remote hardening is a forward hook** (auth tokens, TLS, rate-limiting, network bind) — explicitly out of MVP scope, recorded so the boundary can be hardened without re-architecting (the forge-prevention + no-decision-surface invariants already hold regardless of bind scope).

**[Annotated P4.5 → ADR-039, Accepted 2026-06-06: localhost-trust posture superseded by authenticated posture. A per-request authenticated `Principal` (cookie-session or bearer token) is now required for every non-public route. Remote bind (`--host` beyond loopback) is fail-closed at startup when no users are provisioned (ADR-039 D8 M1: loopback = 127.0.0.0/8 + ::1 + "localhost"). TLS terminated at the deployment/reverse-proxy layer (`TLS-at-deployment` residual). CORS: NOT a GUI dependency under same-origin deployment (ADR-039 D3 A-2) — a future cross-origin affordance only, never `*`-with-credentials. The "CORS restricted to the local GUI origin" promise was never built and is now superseded by the same-origin assumption (no CORS middleware needed for the GUI). Rate-limiting deferred as named residual (ADR-039 D10). Still deferred: `RB-AUTHZ` (any authenticated account is full operator); in-app TLS; a role model (DP3b).]**

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
