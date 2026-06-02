---
task_id: P3.3
round: plan-vs-impl
reviewer: senior
impl_commit: 2da9632
verdict: clean
verdict_history:
  - verdict: clean
    at_commit: 2da9632
    findings_count: { red: 0, yellow: 0, green: 8 }
    note: >-
      initial plan-vs-impl (back-filled — the impl-stage senior plan-vs-impl was missed). Faithful
      on every axis incl. both Y1-α contract-drift guards. Scaffold: top-level ui/ (Vite+React+TS+
      Zustand, CSS modules + Tabler, .nvmrc/engines, README) = ADR-026 D1. API client: schema.ts
      codegen'd from openapi.json; client.ts the sole fetch surface; types re-exported from schema
      (codegen-bound, D2). WS client (stream.ts): connect→event/replay_complete(→live)/error/ping-
      noop→onclose-reconnect-with-exponential-backoff; dedup deferred to the store (§4 lifecycle).
      Store: applyEvent is the central dedup(seenIds)+order(insertByTimestamp) chokepoint; setError
      captures the partial-turn stage (D5). ui_strings: exhaustive non-raw mappers with safe
      fallbacks + AGENT_NAME_MAP re-keyed on the product agents prober/skeptic/operator/divergence_
      mapper/logger/facilitator (the Y1 fix) — never returns the raw key (D3/HR#3). Constitutional
      spine all enforced + tested: view+intent only (HR#1); binds-API-only (HR#2 — constitutional.
      test.ts: no fetch/WebSocket outside src/api/, no orchestrator import, no DB dep); 状态机不暴露
      (HR#3 — uiStrings no-raw-leak tests + a RoomView DOM no-raw-token test); partial-turn (HR#4 —
      useIntent stage:turn→sent-no-repost / stage:append→failed-retry; RoomView discriminating test
      asserts the Composer does NOT re-send on stage:turn); no-forge (HR#5 — type-impossible:
      postIntent is user_input-only with no author/id/timestamp). Both Y1-α guards: gate codegen:check
      (HTTP freshness) + WS-type conformance vitest (stream.test.ts:201 vs asyncapi.md shapes). Zero
      Python (only ui/ + the planned contributing.md FE section). NOTE: node/npm is not in this Python
      session → I verified the SOURCE by reading; the FE gate-green is per the orchestrator's
      verification (stated honestly), not independently re-run here.
findings_count:
  red: 0
  yellow: 0
  green: 8
---

# P3.3 plan-vs-impl (senior) — GUI MVP (React/TS over the frozen API contract)

| Field | Value |
|---|---|
| Reviewer | senior (plan-vs-deliverable lens) |
| Plan | `docs/process/senior-plans/P3.3.md` (incl. the Y1-α contract-drift guards) |
| ADR | `ADR-026` (**Accepted**) |
| Impl | `claude/P3.3-impl` @ `2da9632` (the `ui/` package; Y1 AGENT_NAME_MAP re-key + test fix) |
| Verdict | **clean** — 0🔴 · 0🟡 · 8🟢 |
| Gate note | node/npm absent in this (Python) session → source verified by reading; **FE gate-green per the orchestrator's verification** (not independently re-run here). |

## Summary

A faithful, thorough first-frontend implementation — the `ui/` package matches the plan + ADR-026 on every axis, **both Y1-α contract-drift guards** landed, and **all five constitutional invariants** are enforced *and* discriminatingly tested. The GUI is a **view+intent surface, backend-authoritative**: it reads the room (HTTP + WS) and POSTs `user_input` intent; it makes no decision, **binds the API contract only** (structurally guarded — no `fetch`/`WebSocket` outside `src/api/`, no `orchestrator` import, no DB dep), **humanizes the raw wire via `ui_strings`** (exhaustive, never-raw, with the Y1 product-agent re-key), handles **partial-turn** correctly (`stage:"turn"`→reconcile-no-re-post), and **cannot forge** (type-impossible). **Zero Python** — the only non-`ui/` change is the planned `contributing.md` FE-gate section. I verified the source by reading every constitutional-crux file; the FE gate (eslint/prettier/tsc/vitest/codegen:check) being green is per the orchestrator's verification (node is not in my Python session — stated honestly, not claimed as my own run).

## Per-axis verification

| Axis | Delivered | Plan/ADR match | Evidence |
|---|---|---|---|
| **Scaffold + stack** (D1) | ✓ | ✓ | top-level `ui/`; Vite+React+TS+Zustand; **CSS modules** (`*.module.css`) + `@tabler/icons-react` (restrained, no Tailwind — the senior fork); `.nvmrc` + `package.json engines`; `README.md` (node setup). |
| **API client — codegen HTTP** (D2) | ✓ | ✓ | `schema.ts` codegen'd from `openapi.json` (committed, 555 lines); `client.ts` re-exports the contract types + is the **sole `fetch` surface**; `postIntent` returns `IntentResponse` / throws typed `IntentError`. |
| **WS client** (D2/§4) | ✓ | ✓ | `stream.ts`: connect→`event`(onEvent)→`replay_complete`(onReplayComplete + phase live)→live `event`→`error`(onError)→**`ping` no-op**→`onclose`-reconnect (exponential backoff, reset on replay_complete)→abort cleanup. **Dedup deferred to the store** (centralized). |
| **Store** (D5) | ✓ | ✓ | `applyEvent` = the **single dedup(`seenIds`)+order(`insertByTimestamp`) chokepoint** (replay/live/reconnect all funnel here); `setError` records `{stage,reason}` (+ phase `error` on `stage:"turn"`). |
| **Read view + intent** (D5/§6) | ✓ | ✓ | `RoomView`/`MessageList`/`MessageItem` (author+type chip+content via `uiStrings`)/`Composer`/`ConnectionStatus`/`RoomPicker`/`RoomCreate`; `useRoomStream` + `useIntent`. |
| **ui_strings** (D3/HR#3) | ✓ | ✓ **+ Y1 fix** | exhaustive `EVENT_TYPE_LABELS` (19) / `ROOM_TYPE_LABELS` (5) / `ROOM_STATE_LABELS` (all SM states) / `authorLabel`; **`AGENT_NAME_MAP` re-keyed on the product agents** (prober/skeptic/operator/divergence_mapper/logger/facilitator — the Y1 fix); every fn falls back to a **safe generic, never the raw key**. |
| **FE gate + Y1-α drift guards** (D6) | ✓ | ✓ | `gate = lint && format:check && typecheck && test && codegen:check`; **`codegen:check` = `npm run codegen && git diff --exit-code schema.ts`** (Y1-α HTTP freshness); **WS-type conformance vitest** (`stream.test.ts:201` — `StreamMessage` types vs `asyncapi.md` shapes, Y1-α); deps have **no DB/Tailwind**. `contributing.md` FE section added. |

## Findings

None (0🔴 · 0🟡). Eight 🟢 below.

## What holds — verified clean (G1–G8)

- **G1 — view+intent only (HR#1):** the only write is `postIntent({type:"user_input", content})`; no state/route/autonomy logic in `ui/`.
- **G2 — binds-API-only (HR#2), structurally guarded:** `constitutional.test.ts` asserts no `fetch`/`new WebSocket` outside `src/api/`, no `orchestrator`-path import, no DB/sqlite/fs runtime dep in `package.json` — discriminating (regex scan + dep-pattern check).
- **G3 — 状态机不暴露 (HR#3):** the exhaustive never-raw `ui_strings` mapper + the no-raw-leak tests (`uiStrings.test.ts`: every `EventType`/`RoomType`/known state → human ≠ raw key, unknown → safe generic) + a **rendered-DOM no-raw-token test** (`RoomView.test.tsx:225`). The Y1 `AGENT_NAME_MAP` re-key (product agents) is in.
- **G4 — partial-turn (HR#4):** `useIntent` branches on `stage` — `"turn"` → "intent landed, do NOT re-post, WS replay reconciles" (status `sent`); `"append"` → safe retry (status `failed`). The **discriminating** integration test (`RoomView.test.tsx:131`) asserts the Composer is disabled / offers **no re-send** on `stage:"turn"` ("not merely 'renders something'").
- **G5 — no-forge (HR#5):** type-impossible — `postIntent` is `user_input`-only and the codegen'd `IntentRequest` omits `author`/`id`/`timestamp`.
- **G6 — Y1-α drift guards both present:** the HTTP **codegen-freshness** gate step + the **WS-type conformance** vitest — exactly the two durability guards the plan-stage Y1 routed.
- **G7 — WS client faithful + robust:** the full `asyncapi.md` lifecycle incl. the `{"kind":"ping"}` tolerance + reconnect-replay (with store-centralized dedup across the reconnect); the heaviest test coverage (replay/dedup/reconnect/error/ping), as planned.
- **G8 — zero Python / contract-bound:** only `ui/` + the planned `contributing.md` FE section changed; the HTTP types are codegen-bound to `openapi.json`; the WS types are hand-written + conformance-guarded. The API is the sole boundary.

**Minor observations (non-findings):** (a) I could **not** run the FE gate (node/npm absent in this Python session) — the gate-green is the orchestrator's verification; I verified the source by reading. (b) `constitutional.test.ts`'s `fetch`/`WebSocket` detection is a naive regex (could false-positive on a comment/string) — conservative (over-detects, never under-detects), fine for a constitutional guard. (c) `client.ts` uses relative URLs (`BASE=""`) — correct for same-origin / a Vite dev proxy (localhost MVP); a configurable base is a P3.6 nicety.

## Net

The implementation matches the plan + Accepted ADR-026 on every axis — scaffold/stack, the codegen HTTP client + hand-written WS client, the dedup-centralizing store, the read-view + intent loop, the never-raw `ui_strings` (with the Y1 product-agent re-key), and the FE gate — with **both Y1-α contract-drift guards** (codegen-freshness + WS-type conformance) and **all five constitutional invariants** (view+intent / binds-API-only / 状态机不暴露 / partial-turn / no-forge) enforced and discriminatingly tested. Zero Python; the API is the sole boundary. The one caveat is procedural, not a defect: I verified the source by reading (node isn't in my session); the FE gate-green is the orchestrator's verification. **Verdict: clean.** I did not advance or merge.
