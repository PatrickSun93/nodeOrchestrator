# ADR-026: GUI Frontend Boundary — React/TS view+intent over the frozen API contract

**Status:** Accepted — 2026-06-02 (architect-accepted; P3.3 R0-A-on-plan clean after Y1 → α-lite-fold (codegen-freshness gate + WS-type conformance drift-guards); constitutional spine — view+intent only, binds-API-only, state-machine-not-exposed via ui_strings, partial-turn correctness, no-forge — inscribed; dual-lens skipped (frozen-contract consumer))

**Scope:** P3.3 — the first frontend: a read-mostly React/TS GUI (top-level `ui/`) that **reads** a room (HTTP snapshot + WS live stream) and **sends user intent** (`POST /intent`), binding the **frozen ADR-025 API contract** (`api/openapi.json` + `api/asyncapi.md`). Governs the frontend's **constitutional posture** (view+intent only / backend-authoritative / binds-API-only / 状态机不暴露 via `ui_strings` / partial-turn correctness / no-forge), the **stack** (React+Vite+TS+Zustand, CSS modules, Tabler Icons), the **`ui/` location + gate + node setup**, and the **role/review** arrangement. Adds **zero Python** — the API is the sole boundary. Does NOT govern: any backend/API change (surface, don't backdoor); the rich §6.4 GUI patterns / `DECISION`/`RETRACTION` UX / theming (P3.6); auth (localhost-trust MVP, ADR-025 D7); the backend track (P3.4/P3.5).

## Context

P3.2 shipped the FastAPI server + the **frozen contract**: HTTP (`POST /rooms`, `GET /rooms/{id}`·`/events`·`/snapshot`, `GET /events/{id}/thread`, `POST /rooms/{id}/intent`) + WS (`/rooms/{id}/stream`) + the wire models (`Event{id,parent_id,room_id,type,author,timestamp,content,metadata}`, `Room`, `Snapshot`, `IntentRequest{type,content,metadata?,parent_id?}` — **no author/id/timestamp**, `IntentResponse{appended_event,turn}`, `IntentError{stage,appended_event_id,reason}`, the `StreamMessage` envelope) + committed `openapi.json` (HTTP types, drift-tested) + `asyncapi.md` (WS semantics: subscribe→replay→`replay_complete`→live-dedup-by-`event.id`→`StreamErrorMessage`→ping keepalive). `config/ui_strings/` does **not** exist; there is **no** frontend dir. The 19 `EventType` + 5 `RoomType` values are raw wire vocabulary the GUI must humanize.

P3.3 is a **new stack** (React/TS/node — nothing shared with the Python product) and the **frontend-track opener** (the cleanest parallel track in P3 — it binds only the frozen contract). It makes the product demo-able: type a message → watch agents respond live.

## Hard requirements — the constitutional spine (NON-NEGOTIABLE; inscribed, not chosen)

1. **View + intent only; no decision surface.** The GUI **reads** the stream and **sends** user intent; it makes **no** state/routing/autonomy decision. (The API already prevents forging; the GUI must not even attempt to decide.)
2. **Binds the API contract ONLY.** The GUI must **never** reach into the Python product — **no `orchestrator` import, no direct event-store/sqlite/filesystem access, no non-API network call.** The HTTP/WS API is the **sole** boundary. This is what keeps backend-authoritative true.
3. **状态机不暴露 — the GUI's unique constitutional duty.** The wire is **raw** (raw `state`/event-type names). The GUI maps internal vocabulary to human terms via `ui_strings` and **never surfaces raw internal vocabulary** (`state_transition`, `autonomy_decision`, raw state names, "skill", "state machine", "dissent dimension", …) to the user.
4. **Partial-turn correctness.** On `IntentError`/`StreamErrorMessage`: `stage:"turn"` → the intent **landed** → reconcile via replay, **do NOT re-post**; `stage:"append"` → nothing persisted → safe to retry.
5. **No forge attempt.** Send only allowlisted intent (`USER_INPUT` for the MVP); the contract omits `author`/`id`/`timestamp` — the GUI must not try to set them (type-impossible via the codegen'd `IntentRequest`).

## Decisions

### D1. Stack — React + Vite + TypeScript + Zustand; CSS modules + Tabler Icons; top-level `ui/`

React + TypeScript + **Vite** (fast scaffold/HMR); **Zustand** for state (handoff §11 "Zustand 不要 Redux" — simplest). **Restrained UI** (§6.1 — no gradients/shadows/neon): **CSS modules** (Vite-native, scoped, zero extra build-config; rejected Tailwind for the MVP — utility sprawl + a config dep is overkill for a small read-view + compose box; senior fork) + **Tabler Icons** (outline) for the few glyphs. The frontend lives at **top-level `ui/`** (repo-root sibling of `src/`/`tests/`/`docs/`; its own `package.json`/`node_modules`/gate) — **not** nested in the Python package (`src/orchestrator/ui/` would awkwardly embed a node app in a Python package; senior+architect resolved to top-level). **node** pinned via `.nvmrc` + `package.json` `engines` (LTS); package manager **npm**.

### D2. API integration — codegen HTTP types + hand-written WS client

- **HTTP** — **codegen** the types from the committed, drift-tested `openapi.json` via **`openapi-typescript`** (a build/dev script regenerates `ui/src/api/schema.ts`), wrapped in a thin typed `fetch` client (`ui/src/api/client.ts`). A contract change regenerates → the GUI types track the contract automatically (no hand-drift). **The client module is the SOLE network surface** (HR#2).
- **WS** — **hand-written** typed client (`ui/src/api/stream.ts`; AsyncAPI is a markdown note, not codegen-able), honoring `asyncapi.md` exactly: **connect → replay (`StreamEventMessage` frames, ordered) → `replay_complete` (flip UI loading→live) → live (`StreamEventMessage`, dedup by `event.id`) → `StreamErrorMessage` (`stage:"turn"`→reconcile-via-replay, no re-post; `stage:"append"`→safe retry) → tolerate `{"kind":"ping"}` keepalive (no-op) → on disconnect, reconnect + re-replay (dedup against already-seen ids)**. The WS message types are hand-written to match `wire.py`'s `StreamMessage` (codegen covers HTTP only). **WS-type conformance check (Y1-α):** because the `StreamMessage` envelope is **not** in `openapi.json` (so codegen can't track it), a **vitest conformance test** asserts the hand-written WS types against the `asyncapi.md` sample shapes (`{kind:"event",event}` / `{kind:"replay_complete"}` / `{kind:"error",stage,appended_event_id,reason}` + the `{kind:"ping"}` keepalive) — guarding against silent WS-envelope drift as the contract evolves (the WS analogue of the HTTP codegen-freshness step).

### D3. `ui_strings` — GUI-owned TS module; the 不暴露 mapper (HR#3)

`ui_strings` lives **in the GUI** (`ui/src/uiStrings.ts`, a typed module) for the MVP — the GUI is the only consumer, and a node app can't cleanly read a Python `config/` dir at runtime (rejected API-served / build-copy for the MVP; revisitable if the `config/ui_strings/` canon later needs sharing). It maps raw wire vocabulary → human terms (Chinese), covering everything the MVP renders: `eventTypeLabel(EventType)`, `authorLabel(author)` (`"user"`→你, `"system"`→系统, `"agent:<id>"`→the agent's human name via an id→name sub-map, unknown→助手), `roomTypeLabel(RoomType)`, `roomStateLabel(state)` (raw state-machine states → human progress). **The no-raw-leak guarantee:** the mapper is **exhaustive** over the contract enums and **never returns the raw key**; an unknown value falls back to a **safe generic** term (never the raw string). Internal-only vocabulary (skill / state machine / autonomy level / dissent dimension) is **不暴露** — the MVP surfaces conversation + room state + room type, none of which exposes those.

### D4. The constitutional spine — how each invariant is enforced (HR#1–5)

- **No decision surface (HR#1)** — the GUI's only write is `POST /intent {type:"user_input", content}`; it computes no state/route/autonomy. Reviewer checks: no client-side state-machine/routing logic. **[Annotated P4.5 → ADR-039, Accepted 2026-06-06: the GUI now also sends `POST /login {user_id, password}` and `POST /logout` — the credential-carrying path. It still carries a credential (the session cookie) but still decides nothing; the API remains the sole boundary. GUI login is a frontend-track follow-on (P4.7); this slice pins the integration contract (the cookie semantics + the 401 handling the GUI must implement).]**
- **Binds-API-only (HR#2)** — **structurally:** `package.json` has **no** DB/fs/sqlite runtime deps (only React/Zustand/Tabler + the API client over native `fetch`/`WebSocket`); the **API client + WS client modules are the sole network surface**; an **eslint rule** (`no-restricted-globals`/`no-restricted-imports`) forbids `fetch`/`WebSocket`/`orchestrator`-path imports outside those modules. A constitutional test asserts no direct `fetch`/`WebSocket` usage outside `ui/src/api/`. **[Annotated P4.5 → ADR-039, Accepted 2026-06-06: the GUI now carries a session cookie (set by `POST /login`, HttpOnly+Secure+SameSite=Strict) — still view+intent only; the API is the sole boundary. The cookie is a credential, not a decision surface. The P4.5 backend ships the cookie mechanism; the React login form is the frontend-track follow-on (ADR-039 D10).]**
- **状态机不暴露 (HR#3)** — D3's exhaustive non-raw mapper + a discriminating **no-raw-vocab-leak test** (every `EventType`/`RoomType`/known state maps to a human term ≠ the raw key; rendered output contains no raw internal token).
- **Partial-turn (HR#4)** — the store + intent flow branch on `stage`: `"turn"`→mark intent landed + reconcile via the WS replay (no re-post); `"append"`→allow retry. A discriminating integration test (`StreamError stage:"turn"` → reconcile, **not** re-post).
- **No forge (HR#5)** — type-impossible: the codegen'd `IntentRequest` omits `author`/`id`/`timestamp`; the compose box only sets `type:"user_input"` + `content`.

### D5. Store shape + component structure (senior forks)

- **Store (Zustand, `ui/src/store.ts`):** `{ roomId, roomType, events: Event[] (ordered, deduped), seenIds: Set<string>, phase: 'idle'|'loading'|'live'|'reconnecting'|'error', pendingIntent: {content, status:'sending'|'sent'|'failed'}|null, lastError: {stage,reason}|null }` + actions (`setRoom`, `applyEvent` (dedup by id, ordered insert), `replayComplete`, `setPhase`, `setError`, `setPendingIntent`). The dedup-by-id is centralized in `applyEvent` (the WS hook feeds it; replay + live + reconnect all dedup through it).
- **Components:** `App` → `RoomPicker`/`RoomCreate` (minimal `POST /rooms` + pick) → `RoomView` (drives `useRoomStream(roomId)`) → `MessageList`→`MessageItem` (events→messages, `ui_strings`-mapped author/type/content) + `Composer` (compose→`POST /intent`) + `ConnectionStatus` (loading/live/reconnecting from `phase`). Hooks: `useRoomStream` (the WS client lifecycle) + `useIntent` (POST + partial-turn handling).

### D6. Frontend gate + contributing.md + node setup

A **separate** frontend gate in `ui/` (the Python ruff/mypy/pytest does **not** apply to TS): **eslint** + **prettier --check** + **`tsc --noEmit`** + **vitest** + a **codegen-freshness step** (`npm run codegen && git diff --exit-code ui/src/api/schema.ts` — re-runs `openapi-typescript` and **fails if the committed `schema.ts` is stale** vs `openapi.json`) — all under `npm run gate` in `ui/`. The codegen-freshness step is the **symmetric counterpart of the P3.2 OpenAPI-drift test** (Y1-α): without it, a contract change that regenerates `openapi.json` but isn't re-codegen'd leaves `schema.ts` stale and `tsc` still passes against the stale types → silent drift; the gate re-running codegen + diffing makes the "drift-proof" claim real. `contributing.md` gains a **frontend section** (clearly scoped, mirroring the P3.2 `[api]`-extra-note pattern): the `ui/` gate command + node setup; the Python gates stay unchanged (they don't touch `ui/`). A **frontend-adapted PR checklist** (view-only? binds-API-only? ui_strings-no-raw-vocab? partial-turn handled?) replaces the Python Q1–Q5 for `ui/` PRs. `ui/README.md` documents node setup (`.nvmrc` → `npm install` → `npm run dev`/`gate`).

### D7. Role / review (architect-ruled)

Sonnet **junior** builds the frontend (React/TS within range; **the plan is explicit** about the FE patterns since there is no FE to pattern-match). **architect-partner R0-A** reviews the spine (view-only / binds-API-only / ui_strings-no-raw-vocab / partial-turn) + contract-binding correctness (types match `openapi.json`; WS replay/`replay_complete`/dedup/reconnect/`StreamError`) + code quality. **dual-lens R0-B SKIP** (`requires_cross_family_review: false`) — a read-mostly consumer of a frozen contract is lower runtime risk than the API server; the one real integration surface (WS-client robustness) is R0-A's focus.

## Considered alternatives

- **Tailwind over CSS modules** — Rejected for the MVP (D1): a restrained small view doesn't need utility CSS + a config dep; CSS modules are Vite-native + scoped. (Revisitable in P3.6 if the design system grows.)
- **`ui_strings` API-served / build-copied from `config/ui_strings/`** — Rejected for the MVP (D3): the GUI is the only consumer; a node app reading a Python `config/` dir at runtime is awkward. GUI-owned now; promote to a shared canon only if a 2nd consumer appears.
- **Nest `ui/` under `src/orchestrator/ui/`** (handoff §10 sketch) — Rejected (D1): embedding a node/TS app in the Python package mixes toolchains/gates; top-level `ui/` keeps them cleanly separate.
- **Hand-written HTTP types** — Rejected (D2): they drift from the contract; codegen from the drift-tested `openapi.json` keeps them honest.
- **Redux** — Rejected (handoff §11): Zustand is simpler for this scope.
- **Reach the event-store/sqlite directly for speed** — Rejected, **constitutionally** (HR#2): that *is* the backdoor the spine forbids; the API is the sole boundary.

## Consequences

**Easier:** the product becomes demo-able (type → watch agents); the frontend track (P3.3→P3.6) proceeds independently of the backend track (binds only the frozen contract; codegen catches additive contract changes); a clean new-stack template (gate, structure, the WS-client pattern) for P3.6 to extend.

**Harder:** a whole new toolchain (node/npm/eslint/vitest) + review domain; no FE to pattern-match (the plan must spell out the patterns); the WS-client robustness (reconnect-replay/dedup/error) is the real integration risk to test hard.

**Neutral:** GUI-owned `ui_strings` means the GUI owns all humanization (a future 2nd consumer would promote it to a shared canon). CSS-modules-over-Tailwind is a restrained-MVP call, tunable later.

## Reversibility

| Decision | 6-month reversal cost |
|---|---|
| D1 React+Vite+TS+Zustand / CSS modules / top-level `ui/` | **Low–Med** — a self-contained new dir; swapping CSS approach or state lib is contained; relocating `ui/` is a path move. |
| D2 codegen HTTP + hand-written WS | **Low** — regenerate / rewrite a client module; the contract is frozen. |
| D3 GUI-owned `ui_strings` | **Low** — promoting to API-served/shared is an additive move behind the same mapper interface. |
| D4 the spine (view+intent/binds-API-only/不暴露/partial-turn/no-forge) | **Do-not-reverse** — constitutional. |
| D5 store/component shape | **Low** — refactor within `ui/`. |
| D6 FE gate / D7 role | **Low** — gate scripts + a contributing.md section; role is per-cycle. |

## References

- `docs/process/architect-briefs/P3.3.md` (the spine + the 7 decisions).
- `docs/process/senior-plans/P3.3.md` (this ADR's plan; the FE patterns, the atomic graph, the FE gate, the test plan).
- `docs/decisions/ADR-025-api-server-boundary.md` (the **frozen contract** P3.3 binds — HR#1–4, D2/D4/D5/D6) + `src/orchestrator/api/openapi.json` (HTTP types to codegen) + `api/asyncapi.md` (WS semantics) + `api/wire.py` (the wire models).
- `handoff.md` §6.1–6.4 (restrained design language; 状态机不暴露; the §6.4 patterns deferred to P3.6), §10 (`ui/`/`config/ui_strings/` sketch), §11 (React+TS / Zustand-not-Redux / Tabler Icons), §747/§898 (backend-authoritative / 不暴露).
- `docs/process/P3-roadmap.md` §4/§5 (GUI MVP after the contract; frontend∥backend track parallelism); `docs/process/dual-lens-r0b.md` (the R0-B-skip judgment for a frozen-contract consumer).
