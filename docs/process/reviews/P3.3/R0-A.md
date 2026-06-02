---
task_id: P3.3
round: R0-A
stage: impl
reviewer: architect-partner
impl_commit: 05e9a48
lens: single
verdict: needs_architect
findings_count:
  red: 0
  yellow: 1
  green: 12
verdict_history:
  - verdict: needs_architect
    at_commit: 05e9a48
    findings_count: { red: 0, yellow: 1, green: 12 }
    note: >-
      Initial impl-stage R0-A (in-family, single-lens — dual-lens skipped as ruled: frozen-contract
      consumer). New stack (React/TS); reviewed ui/ vs ADR-026 + plan + the frontend-adapted
      checklist in an isolated worktree at 05e9a48, scoped to spine + contract-binding + code
      quality. Gate green per the orchestrator's verification (eslint/format/tsc/vitest 52 passed,
      codegen-freshness exit 0, Python ruff untouched) — node is absent in my env, so I rely on that
      + the code read (noted, vs the Python slices where I re-ran). The constitutional spine holds
      and is largely STRUCTURALLY enforced: (1) view+intent only — the only write is POST /intent
      {user_input}; no client-side state/route/autonomy. (2) binds-API-only — no orchestrator import,
      no sqlite/fs/db runtime dep (deps = tabler/react/zustand), fetch/WebSocket confined to
      src/api/; constitutional.test.ts scans source + asserts all three (discriminating). (3)
      状态机不暴露 — uiStrings never returns a raw key (tsc-enforced Record exhaustiveness over the 19
      EventType + 5 RoomType; safe-generic fallbacks), with an exhaustive no-raw-leak unit test + a
      rendered-DOM no-raw-vocab test. (4) partial-turn — useIntent branches (turn→sent/no-re-post;
      append→failed/retry); Composer disables input+button on stage:turn ("请勿重发"); the integration
      test asserts postIntent called ONCE (discriminating no-re-post). (5) no-forge — postIntent is
      typed {type:"user_input", content}; author/id/timestamp are type-impossible. Contract-binding:
      HTTP types codegen'd (codegen:check regenerates+diffs → schema.ts tracks openapi.json); a
      complete hand-written WS client (connect→replay→replay_complete→live, dedup centralized in
      store.applyEvent, StreamError stage-branch, ping no-op, exponential-backoff reconnect-re-replay).
      Both Y1 α-lite-fold guards landed: codegen:check in the gate + a WS-type conformance test.
      Stack/structure/gate/node match ADR-026; contributing.md FE section added. One 🟡 (Y1,
      medium-low): AGENT_NAME_MAP keys on the dev-workflow roles (architect/senior/junior/reviewers)
      not the product agents (prober/skeptic/operator/divergence_mapper/logger/facilitator) → every
      product agent renders as the generic "助手" — NOT a 不暴露 breach (safe fallback; no-raw-leak
      holds), but a UX defect on the MVP's core "watch the agents" value; cheap fix. Did NOT advance
      state.
---

# P3.3 R0-A (architect-dispatched post-impl review, in-family, single-lens — React/TS)

| Field | Value |
|---|---|
| Round | R0-A impl-stage (in-family; dual-lens R0-B skipped as ruled — frozen-contract consumer) |
| Impl | `claude/P3.3-impl` @ `05e9a48` (P3.3-1 scaffold+gate+codegen → P3.3-2 client/WS/store/uiStrings → P3.3-3 view+intent+integration+landing) |
| Artifacts | `ui/**` (45 files) + `docs/contributing.md` FE section vs ADR-026 + plan + the frontend-adapted checklist |
| Reviewed at | isolated worktree `/tmp/p33-impl` @ `05e9a48` (shared-tree instability — RC-7 isolation) |
| Review scope | architect-ruled (d): **constitutional spine + contract-binding correctness + code quality** |
| Gate | **green per the orchestrator's verification** (eslint/format/`tsc`/vitest **52 passed**, codegen-freshness exit 0, Python ruff untouched). *node is absent in my env → I rely on the orchestrator's gate run + the code read (vs the Python slices where I re-ran the canonical gates myself).* |

## Verdict: needs_architect — 0🔴 · 1🟡 · 12🟢

> **Exemplary new-stack impl.** The constitutional spine holds and is largely **structurally enforced** — `binds-API-only` is a source-scan test (no `fetch`/`WebSocket` outside `src/api/`, no `orchestrator` import, no DB dep), `状态机不暴露` is a tsc-enforced exhaustive `ui_strings` mapper + an exhaustive no-raw-leak unit test + a rendered-DOM check, and `partial-turn` is a discriminating "no-re-post on `stage:turn`" integration test (asserts `postIntent` called **once** + input disabled). The WS client is complete (replay→`replay_complete`→live, store-centralized dedup, `ping` no-op, exponential-backoff reconnect-re-replay), and **both Y1 α-lite-fold guards landed** (codegen-freshness in the gate + a WS-type conformance test). **One 🟡 (Y1, medium-low)** — `AGENT_NAME_MAP` keys on the dev-workflow roles, so product agents render as the generic "助手" (a UX defect on the MVP's core value; safe fallback, not constitutional).

## The checks

| # | Check | Verdict | Evidence |
|---|---|---|---|
| 1 | **[spine]** view+intent only — no decision surface? | **clean (G1)** | The only write is `postIntent(roomId, {type:"user_input", content})`; reads otherwise. No client-side state-machine/routing/autonomy. |
| 2 | **[spine]** binds-API-only — no orchestrator import / sqlite / backdoor; HTTP/WS API the sole boundary? | **clean (G2)** | grep: no `orchestrator` import (only the `<h1>Orchestrator</h1>` title + the test's own checks); no sqlite/fs/db runtime dep (deps = `@tabler/icons-react`/`react`/`react-dom`/`zustand`); `fetch`/`WebSocket` only in `src/api/`. **`constitutional.test.ts` scans source + asserts all three** (discriminating, RC-24-style). |
| 3 | **[spine]** 状态机不暴露 — ui_strings covers the MVP's raw vocab; no raw leak? | **clean (G3); Y1 (agent names)** | `uiStrings.ts`: `Record<EventType/RoomType, string>` (tsc-enforced exhaustive over 19+5) + safe-generic fallbacks → **never returns a raw key**. `uiStrings.test.ts` (≠raw + no-forbidden-token, exhaustive) + the `RoomView` rendered-DOM no-raw-vocab test. **Y1: agent *names* are wrong (not a raw leak) — see finding.** |
| 4 | **[spine]** partial-turn — `stage:append`→retry / `stage:turn`→reconcile-no-re-post (IntentError + StreamError)? | **clean (G4)** | `useIntent`: `turn`→status `sent` (no re-post; WS replay reconciles), `append`→`failed` (retry). `Composer` **disables textarea+button on `stage:turn`** ("请勿重发"); offers retry on `append`. **Discriminating integration test**: `StreamError stage:turn` → `postIntent` called **once** + button/textarea disabled. |
| 5 | **[spine]** no-forge — only `user_input`, no author/id/timestamp? | **clean (G5)** | `postIntent` is typed `{type:"user_input"; content:string}` — author/id/timestamp are **type-impossible** to set; the codegen'd `IntentRequest` omits them. |
| — | **[contract-binding]** HTTP codegen match `openapi.json`? WS client complete (replay→`replay_complete`→live-dedup→`StreamError`→reconnect)? | **clean (G6–G8)** | HTTP types from `schema.ts` (codegen'd); `codegen:check` regenerates + `git diff --exit-code` → tracks `openapi.json` (gate green). WS `stream.ts` lifecycle complete; **dedup centralized in `store.applyEvent`** (replay/live/reconnect funnel); `ping` no-op; exponential-backoff reconnect-re-replay. |
| — | **[tests]** WS hook / no-raw-leak / `StreamError stage:turn`→reconcile-not-re-post discriminating? codegen-freshness + WS-conformance guards? | **clean (G9/G10)** | All discriminating (above). **Y1 α-lite-fold landed**: `codegen:check` in `gate` (codegen-freshness, symmetric to P3.2) + `WS-type conformance (Y1-α drift guard)` test (StreamMessage vs asyncapi sample shapes). 52 vitest passed. |

## Findings

### Y1 🟡 (medium-low) — `AGENT_NAME_MAP` keys on the dev-workflow roles, not the product agents → every product agent renders as the generic "助手"

`ui/src/uiStrings.ts:32` `AGENT_NAME_MAP` keys on `architect`/`senior`/`junior`/`reviewer-r0a`/`reviewer-r0b` — **this repo's dev-workflow roles** — not the **product agents** the GUI actually displays: `prober`/`skeptic`/`operator`/`divergence_mapper`/`logger`/`facilitator` (verified `config/agents/`). So in a real product room, an agent event (`author:"agent:skeptic"`, …) misses the map and `authorLabel(...)` falls to the safe generic **"助手"**. Two consequences:

- **NOT a constitutional breach.** The fallback is a safe generic, so HR#3 / no-raw-leak holds — and `uiStrings.test.ts` correctly passes (it even uses `agent:architect` as its "known agent" example — the **same context-bleed** — so it can't catch this).
- **A UX/correctness defect on the MVP's core value.** P3.3 exists to make "type a message → **watch the agents respond**" demo-able; with every agent shown as "助手", the user can't tell `prober` from `skeptic` from `operator` — the §6.4 "AI 多视角" pattern collapses to one undifferentiated voice. The current map keys are **dead** (they never match a product `author`).

This reads as a **context-bleed**: the implementer's own workflow-role vocabulary (the architect/senior/junior/reviewers *they* operate within) leaked into the product's agent-name map (which should key on the product agents).

**Lean (surface, not decide): α (fix the map keys) or note-for-P3.7.** Either (**α**) re-key `AGENT_NAME_MAP` to the 6 product agents with provisional Chinese names — cheap; restores the MVP's agent-distinguishing value (the exact names are a UX/content choice the architect/senior refine); **or** (**note-for-P3.7**) if agent display names are deferred content, at minimum fix the keys to the product set (so the map isn't dead) and document that product agents show as "助手" in the MVP. Not constitutional, not blocking. Architect: α / note-for-P3.7.

## What holds — verified clean (G1–G12)

- **G1 — view+intent only (HR#1)**: only write is `POST /intent {user_input}`; no client-side decision.
- **G2 — binds-API-only (HR#2), structurally enforced**: no `orchestrator` import, no sqlite/fs/db dep, `fetch`/`WebSocket` confined to `src/api/`; `constitutional.test.ts` scans source + asserts all three (the backdoor is test-forbidden, not convention).
- **G3 — 状态机不暴露 (HR#3)**: `uiStrings` `Record<EventType/RoomType>` (tsc-exhaustive over 19+5) + safe-generic fallbacks (never a raw key); exhaustive no-raw-leak unit test (≠raw + no-forbidden-token) + a rendered-DOM no-raw-vocab test. *(Agent-name correctness is Y1 — a separate UX axis, not a leak.)*
- **G4 — partial-turn (HR#4)**: `useIntent` branches `turn`→sent/no-re-post, `append`→failed/retry; `Composer` disables on `stage:turn` ("请勿重发"); the integration test asserts `postIntent` called **once** + input disabled (discriminating, not "renders something").
- **G5 — no-forge (HR#5)**: `postIntent` typed `{type:"user_input", content}` — author/id/timestamp type-impossible.
- **G6 — HTTP codegen**: `client.ts` types from the codegen'd `schema.ts`; `codegen:check` (regenerate + `git diff --exit-code`) keeps it tracking `openapi.json` (gate green per orchestrator).
- **G7 — WS client complete** (`stream.ts`): connect→loading→replay (`onEvent`)→`replay_complete` (reset backoff + live)→live (`onEvent`)→`StreamError` (`onError`)→`ping` no-op→`onclose` exponential-backoff reconnect (cap 30s)→abort cleanup; **server→client only** (no `ws.send`).
- **G8 — dedup centralized** in `store.applyEvent` (skip `seenIds.has`; insert by timestamp); replay/live/reconnect all funnel; reconnect-re-replay re-dedups (tested).
- **G9 — both Y1 α-lite-fold drift guards landed**: `codegen:check` in `gate` (codegen-freshness, symmetric to the P3.2 OpenAPI-drift test) + the `WS-type conformance (Y1-α drift guard)` test (StreamMessage types vs asyncapi sample shapes).
- **G10 — discriminating tests**: WS hook (replay/live/dedup-delegation/reconnect/error/ping); no-raw-leak (exhaustive unit + DOM); `StreamError stage:turn`→no-re-post (postIntent once + disabled); `stage:append`→retry; binds-API-only source scan; WS-conformance. **52 vitest passed.**
- **G11 — stack/structure/gate/node match ADR-026**: React+Vite+TS+Zustand, CSS-modules+Tabler, top-level `ui/`, `gate` = lint+format+typecheck+test+codegen:check, node `engines>=24`+`.nvmrc`+npm; `contributing.md` FE section (+29).
- **G12 — gate green** (per the orchestrator: eslint/format/`tsc`/vitest 52 passed/codegen-freshness exit 0; Python ruff untouched) — corroborated by the code read + the `codegen:check` gate (contract-binding) + the constitutional/no-raw-leak tests.

## Forward-notes (green — not findings)
- **`WS-type conformance` is a sample-shape pin** (not server-schema-derived — WS isn't in `openapi.json`); this is the inherent WS limitation the routing accepted. It catches an accidental type edit, not a server-side `StreamMessage` change. Acceptable; if WS drift later matters, exporting the `StreamMessage` JSON-schema server-side is the forward hook.
- **`ConnectionStatus` phase text** (loading/live/reconnecting) is a UI-internal connection state (not wire vocabulary) — outside the 不暴露 scope; localization is a P3.6 polish nicety.

## What I did NOT do
- Did not advance `.workflow/P3.3.yaml` (architect/workflow only); committed-state lag is the usual pattern.
- Did not re-run the gate myself (no node in my env) — relied on the orchestrator's verified-green run + the code read; flagged explicitly.
- Did not decide Y1 — surfaced with a lean (α-fix-map-keys / note-for-P3.7); medium-low, non-constitutional (UX correctness).
- Single-lens in-family (dual-lens skipped as ruled); reviewed in an isolated worktree, left the shared tree untouched.
