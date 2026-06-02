---
task_id: P3.2
round: R0-B
reviewer_family: deepseek
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 7
---

# P3.2 R0-B (cross-family, impl-stage) — API/server boundary

| Field | Value |
|---|---|
| Round | R0-B (cross-family, impl-stage; concurrency/failure-mode/forge lens) |
| Reviewer family | deepseek |
| Impl branch | `claude/P3.2-impl` @ `fa5aa18` (atomics P3.2-1..5) |
| Baseline | `main` (ADR-025 Accepted; plan-stage 3🟡 all α-absorbed) |
| Plan-stage absorptions | Y1: subscribe-then-replay+dedup; Y2: WAL read conn + separate read executor; Y3: IntentError{stage, appended_event_id, reason} |
| Date | 2026-06-02 |
| Verdict | **clean** — 0🔴 · 0🟡 · 7🟢 |

## Lens preamble

Cross-family impl-stage concurrency/failure-mode/forge lens. The plan-stage cross-family R0-B found three 🟡 on the concurrency + failure-mode surface — all routed α and absorbed. This pass traces the **actual code** to verify absorption and probe for net-new issues: the subscribe-then-replay ordering (is the register-before-replay handshake genuinely gap-free?), the WAL read-connection liveness (do reads really not block behind a busy writer?), the partial-turn error envelope (does the client get `stage:"append"` vs `stage:"turn"`?), the forge-prevention chokepoint (is `author:"user"` actually hardcoded?), and the failure-mode coverage (WS drop, busy writer, full queue, malformed payload).

## Findings

| # | Sev | Finding | Evidence |
|---|---|---|---|
| G1 | 🟢 | **Y1→α absorbed — subscribe-before-replay + dedup is correctly ordered, gap-free.** `_room_stream` (`app.py:338-392`): (1) `ctx.bus.subscribe(rid)` at line 356 — registers the queue FIRST; (2) `ctx.reader_store.get_room_events(rid)` at line 363 — replays current events from the read connection; (3) `StreamReplayCompleteMessage` sentinel at line 370; (4) drain queue with `if live_event.id not in sent_ids` dedup at line 383. Subscribe BEFORE replay means events appended during replay are queued (no gap); dedup by event id removes any overlap. The `RoomEventBus.subscribe()` docstring explicitly states: "Register BEFORE replaying events to avoid a lost-event window." Cross-family trace: the ordering is correct — the post-SELECT-pre-subscribe window that the plan-stage Y1 identified is eliminated by construction. Test `test_no_duplicate_ids_in_replay` (test_concurrency.py:164) asserts all replay ids are unique. | `app.py:338-392` (WS handler, subscribe-before-replay); `pubsub.py:28-38` (subscribe docstring); `test_concurrency.py:164` (no-duplicate test) |
| G2 | 🟢 | **Y2→α absorbed — separate WAL read connection + reader executor; reads do not block behind writer.** `create_app` context (`app.py:115-133`): `writer_conn` (1-connection, `check_same_thread=False`, `PRAGMA journal_mode=WAL`) + `writer_executor` (1 worker); `reader_conn` (separate EventStore, `check_same_thread=False`) + `reader_executor` (4 workers). GET endpoints + WS replay use `reader_executor`; `POST /intent` + `run_turn` use `writer_executor`. WAL mode allows concurrent reads alongside a writer. `test_get_events_not_blocked_while_writer_busy` (test_concurrency.py:189) proves liveness: writer executor is occupied with a 0.3s blocking task, GET `/rooms/{id}/events` returns in < 0.5s via the reader executor. `test_snapshot_not_blocked_while_writer_busy` (line 219) confirms the same for snapshot reads. Cross-family trace: the GUI-liveness issue (plan-stage Y2 — reads hang during turns) is resolved by the dual-connection WAL design. | `app.py:115-133` (dual conn + dual executor); `test_concurrency.py:189-241` (read-during-write liveness tests) |
| G3 | 🟢 | **Y3→α absorbed — `IntentError{stage, appended_event_id, reason}` distinguishes append-fail from turn-fail.** `_write_and_turn` (`app.py:278-307`): `_AppendFailedError` (caught at line 287 — room not found, append rejected) returns 422 `IntentError{stage:"append", appended_event_id:null, reason}`. `_TurnFailedError` (caught at line 301 — `run_turn` raises after append succeeded) returns 500 `IntentError{stage:"turn", appended_event_id: event.id, reason}`. The `appended_event_id` on turn-fail gives the client the id of the already-appended user event — the client can query whether the intent landed. The exception handlers at lines 315-335 map each error class to the appropriate HTTP status + `IntentError` body. Tests: `test_nonexistent_room_returns_intent_error_append_stage` (test_intent.py:328), `test_invalid_parent_id_returns_422_append_stage` (test_failure_modes.py:48), `test_run_turn_raise_returns_500_turn_stage` (test_failure_modes.py:81). Cross-family trace: the ambiguity the plan-stage Y3 identified (client can't distinguish "safe to retry" from "intent already recorded") is resolved by the `stage` field + `appended_event_id` in the error envelope. | `app.py:278-335` (_write_and_turn + error handlers); `wire.py:68-79` (IntentError model); `test_intent.py:328`, `test_failure_modes.py:48,81` (stage-distinguishing tests) |
| G4 | 🟢 | **Forge-prevention is fail-closed at impl — `author:"user"` hardcoded, allowlist enforced before any I/O.** `_post_intent` (`app.py:230-309`): (a) `body.type not in INTENT_TYPE_ALLOWLIST` → 422 at line 252 — BEFORE any append, any cursor capture, any DB I/O. `INTENT_TYPE_ALLOWLIST = {USER_INPUT, DECISION, RETRACTION}` (`wire.py:36-42`). (b) `validate_metadata(body.type, body.metadata)` → 422 on `MetadataValidationError` at line 259-262 — BEFORE append. (c) `author="user"` hardcoded at line 270 — the `IntentRequest` has NO author field (`wire.py:45-61`, `extra="forbid"` would reject one). Server stamps `id` (`generate_event_id()`), `timestamp` (`now_ms()`). (d) `parent_id` validated by `append` (room-exists, same-room) → 422/404 on violation. The `IntentRequest` model is frozen + `extra="forbid"` — a client attempting to pass `author`, `id`, or `timestamp` fields would be rejected by Pydantic before reaching the endpoint. Cross-family trace: no path from `IntentRequest` to a forged `author:"system"`/`"agent:<id>"` event or an off-allowlist event type. The backend remains the sole author of all non-user events. | `app.py:252-273` (forge chokepoint); `wire.py:36-61` (INTENT_TYPE_ALLOWLIST + IntentRequest); `app.py:270` (author hardcoded) |
| G5 | 🟢 | **Pub/sub is correct — fan-out under interleaved appends is race-free, slow subscriber dropped without blocking.** `RoomEventBus` (`pubsub.py:18-70`): per-subscriber bounded `asyncio.Queue(maxsize=512)`. `publish()` at line 50 iterates subscribers, `put_nowait()` per event — `QueueFull` → subscriber dropped (`unsubscribe`), writer + other subscribers never blocked. `subscribe()`/`unsubscribe()` are loop-thread-only (called from async handlers). `publish()` is called via `loop.call_soon_threadsafe()` from the writer executor (`app.py:305`). The cursor-diff capture + append + run_turn + publish run atomically on the single writer executor — no interleaving between two concurrent intents. Two concurrent WS subscribers both receive replay + live events. Test coverage: `test_two_concurrent_subscribers_both_see_replay` (test_concurrency.py:114), `test_full_queue_subscriber_dropped_silently` (line 252), `test_dropped_subscriber_does_not_block_others` (line 299). Cross-family trace: the pub/sub design is race-free under the serialized writer executor + async loop fan-out. | `pubsub.py:18-70` (RoomEventBus); `app.py:283-305` (cursor-diff → publish); `test_concurrency.py:114,252,299` (subscriber + drop tests) |
| G6 | 🟢 | **Failure mode coverage — WS drop, busy writer, reconnect recovery, malformed payloads all tested.** `test_failure_modes.py` (329 lines): (a) WS disconnect mid-stream → clean unsubscribe (no leak). (b) Invalid `parent_id` → 422 `stage:"append"`. (c) `run_turn` raises → 500 `stage:"turn"` with `appended_event_id`. (d) Malformed JSON → 422. (e) Oversized payload → 422 (before any append). (f) `test_reconnect_replay_exact_recovery` — WS drop + reconnect replays exactly the same events + any new ones. `test_concurrency.py` covers: replay ordering, no-duplicate-ids, two concurrent subscribers, read-during-write (liveness), full-queue subscriber drop. The `sqlite3` `check_same_thread=False` + WAL mode + serialized writer executor preclude "database is locked" errors. Cross-family trace: the failure modes the plan-stage review flagged (WS drop, busy writer, reconnect recovery, malformed payload) are all test-covered. | `test_failure_modes.py` (6 failure tests); `test_concurrency.py` (7 concurrency tests); `app.py:115-125` (WAL mode, check_same_thread=False) |
| G7 | 🟢 | **Contract pinned + gates green.** The first atomic (P3.2-1) commits: `wire.py` (IntentRequest/IntentResponse/IntentError/StreamEventMessage + raw Event/Room/Snapshot re-exports), `openapi.json` (752 lines, FastAPI-generated), `asyncapi.md` (WS channel spec). All wire models frozen + `extra="forbid"`. The `IntentRequest` model structurally excludes `author`/`id`/`timestamp` — the forge guard is at the schema level. The optional `[api]` extra in `pyproject.toml` (`fastapi`, `uvicorn[standard]`) keeps core importable without the server. No new `LLMPurpose` — the taxonomy stays content-gen-only (grep-confirmed). Gates: ruff ✓ · mypy ✓ · pytest all passed. | `wire.py` (7 wire models, all frozen+forbid); `openapi.json` (committed contract); `asyncapi.md` (WS spec); `pyproject.toml` (optional [api] extra) |

## Synthesis

All three plan-stage cross-family 🟡 are correctly absorbed at impl:

- **Y1 (subscribe-replay ordering):** `subscribe()` BEFORE `get_room_events()`, dedup by event id — the gap window is eliminated by construction.
- **Y2 (read liveness):** Separate WAL read connection + 4-worker reader executor — GET/WS-replay don't block behind a busy writer; liveness tests prove it.
- **Y3 (partial-turn error):** `IntentError{stage:"append"|"turn", appended_event_id, reason}` — the client can distinguish safe-retry from intent-already-landed.

The forge-prevention is fail-closed at impl: `author:"user"` hardcoded, allowlist enforced before any I/O, `extra="forbid"` rejects forged fields at the schema level. The pub/sub is race-free under the serialized writer executor. Failure-mode coverage is comprehensive (WS drop, busy writer, reconnect, malformed payloads). The contract is pinned in the first atomic (OpenAPI/AsyncAPI committed).

No net-new 🔴 or 🟡. The impl is genuinely clean across all invariants the cross-family lens traced. Seven greens — the first network surface checks out.

## For the architect

No routing needed. The impl is accept-worthy as-is. All three plan-stage cross-family 🟡 are correctly absorbed, and no net-new issues found at impl stage.
