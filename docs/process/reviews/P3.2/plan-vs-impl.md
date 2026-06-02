---
task_id: P3.2
round: plan-vs-impl
reviewer: senior
impl_commit: fa5aa18
verdict: clean
verdict_history:
  - verdict: clean
    at_commit: fa5aa18
    findings_count: { red: 0, yellow: 0, green: 7 }
    note: >-
      initial plan-vs-impl. Faithful on every axis incl. all four plan-stage routing absorptions.
      Contract pinned (wire.py + openapi.json + asyncapi.md): IntentRequest has no author/id/timestamp
      + extra="forbid"; allowlist {USER_INPUT,DECISION,RETRACTION} (UTTERANCE excluded); IntentError
      {stage,appended_event_id,reason}; discriminated StreamMessage; raw Event/Room/Snapshot. Forge-
      prevention is load-bearing + discriminating (author hardcoded "user", server-stamped id/ts,
      allowlist+metadata 422 before any I/O; off-allowlist STATE_TRANSITION/UTTERANCE/AUTONOMY/TOOL
      rejected; author/id/ts/agent_id wire fields rejected). All four absorptions present: Y1 WS
      subscribe-then-replay+dedup (correct order: subscribe->replay->replay_complete->drain-with-id-
      dedup); Y2 separate read-only WAL connection + reader executor (reads off reader, writes+run_turn
      off the serialized writer executor) with read-not-blocked-while-writer-busy liveness tests; Y3
      partial-turn IntentError (append-fail 422 stage:append / turn-fail 500 stage:turn + appended_event_id);
      arch-Y1 DECISION{promotion:true} appends but does not promote. Backend-authoritative holds (intent
      = append + run_turn; llm_adapter delegates routing to select_model_and_provider, decision-free);
      wrap-don't-reimplement (ONLY api/ touched in src — core/rooms/autonomy/llm unchanged); no new
      LLMPurpose. Gates green independently (92 api tests + ruff + mypy --strict on api/). 7 green;
      minor non-defects noted (dead _NoopLLMRouter placeholder; the promotion-authority test asserts
      via a proxy, acceptable since the API context has no VK store; StreamErrorMessage defined-but-
      unemitted per HTTP-only intent).
findings_count:
  red: 0
  yellow: 0
  green: 7
---

# P3.2 plan-vs-impl (senior) — API/server boundary (HTTP/WS over the event store + room runtime)

| Field | Value |
|---|---|
| Reviewer | senior (plan-vs-deliverable lens) |
| Plan | `docs/process/senior-plans/P3.2.md` (incl. the all-α routing absorption: r0b Y1/Y2/Y3 + arch Y1) |
| ADR | `ADR-025` (**Accepted**) |
| Impl | `claude/P3.2-impl` @ `fa5aa18` (5 atomics: contract `3fadf94`, read+bootstrap `b8d5267`, WS+pubsub `ee35d00`, intent+forge `c469811`, failure+landing `fa5aa18`) |
| Verdict | **clean** — 0🔴 · 0🟡 · 7🟢 |

## Summary

A faithful, thorough implementation of the new-infra slice — the contract is pinned, the HTTP read + WS live stream + intent write paths are all present, and **all four plan-stage routing absorptions** (r0b Y1/Y2/Y3 + arch Y1) landed exactly as inscribed. The constitutional/security spine holds: the API has **no decision surface** (intent = `append(user_event)` + `run_turn`; the `llm_adapter` delegates routing to `select_model_and_provider`), the **forge-prevention** is load-bearing and discriminating (server-stamped `author="user"`/id/ts; allowlist + metadata `422` *before* any I/O; the `IntentRequest` `extra="forbid"` rejects identity fields), the wire is **raw**, and the trust boundary is localhost-MVP. **Wrap-don't-reimplement is honored** — the **only** `src/` change is the new `api/` package (core/rooms/autonomy/llm untouched), and **no new `LLMPurpose`**. I re-ran the gates independently: **92 api tests pass, ruff + mypy --strict clean on `api/`.** No 🔴/🟡 — seven 🟢, with three small non-defects noted.

## Per-axis verification

| Axis | Delivered | Plan/ADR match | Evidence |
|---|---|---|---|
| **Contract pin** (D5) | ✓ `3fadf94` | ✓ | `api/wire.py`: `IntentRequest{type,content,metadata?,parent_id?}` **no author/id/ts** + `frozen`/`extra="forbid"`; `INTENT_TYPE_ALLOWLIST={USER_INPUT,DECISION,RETRACTION}`; `IntentResponse`; `IntentError{stage,appended_event_id,reason}`; discriminated `StreamMessage` (event/error/replay_complete); raw `Event`/`Room`/`Snapshot` re-exported. `api/openapi.json` (752 lines) + `api/asyncapi.md` committed — inscribe-before-producer. `§6` wire round-trip + identity-field-rejection tests. |
| **HTTP read** (D2) | ✓ `b8d5267` | ✓ | `POST /rooms`, `GET /rooms/{id}` (404), `/events`, `/snapshot` (`produce_snapshot`), `/events/{id}/thread` (404 on `EventNotFoundError`) — all over the **reader** executor/conn. |
| **WS live stream + Y1** | ✓ `ee35d00` | ✓ **subscribe-then-replay+dedup** | `_room_stream`: **(1) subscribe** (`bus.subscribe` registers the queue first) → **(2) replay** off the reader conn (track `sent_ids`) → **(3) `replay_complete`** sentinel → **(4) drain queue, skip ids already replayed** (dedup). The corrected Y1 order — register-first eliminates the dropped window. `RoomEventBus`: bounded queues (512), drop-on-full, threadsafe publish. Tests: replay order/ids, two-subscriber, no-dup-ids, slow-subscriber-drop. |
| **Intent write + forge (D4)** | ✓ `c469811` | ✓ **discriminating** | `_post_intent`: payload-size guard → **allowlist check `422`** → **`validate_metadata` `422`** (both before any I/O) → `Event(author="user"` **hardcoded**, `id`/`ts` server-stamped`)` → `append`+`run_turn` on the **writer** executor → cursor-diff publish. Tests: off-allowlist (STATE_TRANSITION/UTTERANCE/AUTONOMY_DECISION/TOOL_CALL) → `422`; author/id/timestamp/agent_id wire fields → rejected; missing-field/oversized → `422` + store-empty. |
| **Partial-turn Y3** | ✓ `c469811` | ✓ | `_AppendFailedError` → `422` `IntentError{stage:"append", appended_event_id:null}` (safe retry); `_TurnFailedError(reason, event_id)` → `500` `IntentError{stage:"turn", appended_event_id:<id>}` (intent persisted). Tests: invalid-parent → 422 append-stage + store-empty; `run_turn`-raise → 500 turn-stage + **intent persisted** + no partial writes surfaced. |
| **Separate WAL read conn Y2** | ✓ `b8d5267`/`ee35d00` | ✓ | `_build_context`: **two `EventStore` instances** — `writer_store` (WAL enabled, `writer_executor` `max_workers=1` serialized) + `reader_store` (separate conn, `reader_executor` `max_workers=4`). GETs/WS-replay on reader; writes+`run_turn` on writer. **No `core/event_store.py` change.** Tests: `get_events`/`snapshot` **not blocked while writer busy**; reader cross-thread no `check_same_thread` crash. |
| **bootstrap + spine** | ✓ all | ✓ | `create_app(config_dir, db_path)` + lifespan (two conns + two executors + bus + `load_and_validate_llm_layer`/agents/skills/tools + `RealLLMRouter`); `api/__main__.py` binds `127.0.0.1` (D7). `llm_adapter` **decision-free** (delegates to `select_model_and_provider`). **No new `LLMPurpose`**; `api/` no routing/judgment. |

## Findings

None (0🔴 · 0🟡). Seven 🟢 below.

## What holds — verified clean (G1–G7)

- **G1 — contract pinned + faithful**: wire models + OpenAPI + AsyncAPI; `IntentRequest` structurally forge-proof (no identity fields + `extra="forbid"`); `IntentError`/`StreamMessage` per Y3/Y1; raw wire.
- **G2 — forge-prevention load-bearing + discriminating** (D4/D4a): `author="user"` hardcoded, server-stamped id/ts, allowlist+metadata `422` before any I/O; the full off-allowlist + wire-identity-field rejection matrix tested. Client cannot forge `system`/`agent`/`STATE_TRANSITION`/`AUTONOMY_*`.
- **G3 — Y1 subscribe-then-replay+dedup** correct (register→replay→sentinel→drain-with-id-dedup); the corrected ordering; bounded-queue/drop-slow.
- **G4 — Y2 dual-connection liveness**: separate WAL reader conn + reader executor; writes+`run_turn` on the serialized writer; **no core change**; read-not-blocked-while-writer-busy tested (the GUI-liveness fix).
- **G5 — Y3 partial-turn envelope**: append-fail (safe-retry, no event id) vs turn-fail (intent persisted, carries `appended_event_id`) distinguished + tested (incl. store-consistency).
- **G6 — backend-authoritative / wrap-don't-reimplement / no new `LLMPurpose`**: intent = `append`+`run_turn`; `llm_adapter` delegates routing to `select_model_and_provider` (decision-free glue); **only `api/` touched in `src/`**; `purposes.py` untouched.
- **G7 — arch-Y1 authority**: `DECISION{promotion:true}` appends but does **not** promote — the boundary holds structurally (`run_turn` never calls `promote_hypothesis` per ADR-016 D10, **and** the API `AppContext` carries no memory/VK store, so promotion is impossible by construction); gates green independently (92 tests + ruff + mypy).

**Minor observations (non-findings, 🟢-level):**
- **(a)** the arch-Y1 promotion-authority test (`test_decision_promotion_true_appends_but_no_vk_created`) asserts "no promotion" via a **proxy** (no `autonomy_decision` event) rather than directly asserting VK-store absence / hypothesis-status-unchanged (the plan §4 wording). **Acceptable** — the API `AppContext` has **no memory/VK store**, so promotion is structurally impossible regardless of the assertion (a guarantee *stronger* than any test); a one-line comment noting the no-VK-store structural guarantee (or asserting it) would be cleaner. Non-blocking — the requirement (appends-but-doesn't-promote) is met and the boundary is real.
- **(b)** `_NoopLLMRouter` (app.py:102) is **dead code** — an unused P3.2-1 stub placeholder; `_build_context` always installs `RealLLMRouter`. Trivial cleanup.
- **(c)** `StreamErrorMessage` is defined in `wire.py` but the WS handler never emits it — correct given intents are **HTTP-only** (D2), so there is no streamed-intent turn-fail to report on the WS; it remains in the contract for completeness. (Also minor: the `llm_adapter` opens a fresh event loop per call — correct + isolated on the writer thread; the WS handler's `except Exception: pass` is intentional connection-isolation but could log.)

## Net

The implementation matches the plan + Accepted ADR-025 on every axis — the pinned contract, the HTTP read + WS live stream + intent write surfaces, and **all four plan-stage routing absorptions** (Y1 subscribe-then-replay+dedup, Y2 separate WAL read connection, Y3 partial-turn `IntentError` envelope, arch-Y1 promotion-authority) — with discriminating tests for each. The constitutional spine holds (no decision surface, fail-closed forge-prevention, raw wire, localhost trust), wrap-don't-reimplement is honored (only `api/` in `src/`), and no new `LLMPurpose`. The three minor observations are non-defects (a dead placeholder, a proxy assertion on an already-structurally-closed boundary, an unemitted contract-completeness message). **Verdict: clean.** Per ADR-008 Route B, state auto-advances; R0-A (+ the dual-lens R0-B, `requires_cross_family_review: true`) fire next. I did not accept anything or advance state.
