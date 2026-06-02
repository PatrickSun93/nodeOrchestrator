---
task_id: P3.3
round: R0-A-on-plan
stage: plan
reviewer: architect-partner
plan_commit: c9c6567
lens: single
adr: ADR-026
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 13
verdict_history:
  - verdict: clean
    at_commit: PENDING-plan-stage-routing-absorption
    findings_count: { red: 0, yellow: 0, green: 13 }
    note: >-
      Bumped per architect plan-stage routing (Y1 → α-lite-fold) + RC-10. Both contract-drift guards
      folded into ADR-026 + plan (precision/durability; design unchanged). (a) HTTP codegen-freshness:
      the FE gate gains a codegen:check step (`npm run codegen && git diff --exit-code ui/src/api/
      schema.ts`) that fails on a stale schema.ts vs openapi.json — the symmetric counterpart of the
      P3.2 OpenAPI-drift test (ADR-026 D6 + plan §3/§7 P3.3-1 + gate table). (b) WS-type conformance:
      a vitest asserts the hand-written StreamMessage TS types against the asyncapi.md sample shapes
      (event/replay_complete/error{stage,appended_event_id,reason}/ping) — guards WS-envelope drift
      that codegen can't track (ADR-026 D2 + plan §4/§7 P3.3-2 + gate table). Y1 🟡 → 🟢 (13🟢). Did
      NOT accept ADR-026 or advance state.
  - verdict: needs_architect
    at_commit: c9c6567
    findings_count: { red: 0, yellow: 1, green: 12 }
    note: >-
      Initial R0-A-on-plan (in-family, single-lens — dual-lens R0-B skipped as architect-ruled: a
      read-mostly consumer of a frozen contract). New stack (React/TS); reviewed senior-plans/P3.3.md
      + ADR-026 (Proposed) in an isolated worktree at c9c6567, scoped to the architect's (d) ruling:
      spine + contract-binding correctness + code quality. Exemplary new-stack plan — the
      constitutional spine is faithfully inscribed (ADR-026 HR#1-5) and, where possible, STRUCTURALLY
      enforced: (1) view+intent only, no decision surface; (2) binds-API-only — no orchestrator
      import / no DB/fs/sqlite dep in package.json / fetch+WebSocket confined to src/api/ via eslint
      no-restricted-globals + a constitutional test (the "reach sqlite directly" backdoor is rejected
      constitutionally); (3) 状态机不暴露 — a GUI-owned exhaustive ui_strings mapper that never
      returns the raw key (unknown → safe-generic) + a no-raw-vocab-leak DOM test; (4) partial-turn
      correctness — store/intent branch on stage (turn → reconcile-via-replay, no re-post; append →
      retry) + a discriminating integration test asserting the Composer does NOT re-send on
      stage:turn; (5) no-forge type-impossible (codegen'd IntentRequest omits author/id/timestamp).
      Contract-binding: HTTP types codegen'd from the drift-tested openapi.json; a complete
      hand-written WS client matching asyncapi.md (connect → replay → replay_complete → live-dedup-
      by-event.id → StreamError stage-branching → ping-keepalive-tolerate → reconnect-re-replay),
      dedup centralized in the store's applyEvent. Stack/structure/gate/role all match the rulings
      (React+Vite+TS+Zustand, CSS-modules+Tabler, top-level ui/, eslint+tsc+vitest+prettier gate,
      Sonnet junior + R0-A spine+contract review). Sharp self-discoveries (the ping-keepalive a
      non-StreamMessage frame to tolerate; binds-API-only structurally checkable). ADR-026 RC-23-safe;
      scope (read+intent MVP; §6.4 patterns/DECISION/RETRACTION/theming/auth → P3.6) clear. One LOW
      🟡 (Y1): contract-drift guards under-specified — the FE gate has no codegen-freshness check
      (a stale schema.ts vs a changed openapi.json wouldn't be caught — the P3.2 OpenAPI-drift test's
      symmetric counterpart), and the hand-written WS types have no drift-guard vs wire.py's
      StreamMessage. Low for the frozen MVP; matters as the contract evolves (P3.4+). Did NOT accept
      ADR-026 or advance state.
---

# P3.3 R0-A on plan (architect-dispatched pre-impl review, in-family, single-lens)

| Field | Value |
|---|---|
| Round | R0-A-on-plan (RC-9; **single-lens** — `requires_cross_family_review: false`, architect-ruled skip: read-mostly frozen-contract consumer) |
| Artifacts | `senior-plans/P3.3.md` + `ADR-026` (Proposed) vs the frozen ADR-025 contract + brief P3.3 |
| Reviewed at | isolated worktree `/tmp/p33-plan` @ plan `c9c6567` (shared-tree instability — RC-7 isolation) |
| Review scope | architect-ruled (d): **constitutional spine + contract-binding correctness + code quality** (new stack) |
| ADR status | ADR-026 left **Proposed** — informs accept; I did not accept (architect-only). |

## Verdict: clean (bumped from needs_architect) — 0🔴 · 0🟡 · 13🟢

> **Routing-absorption note (RC-10).** Y1 → **α-lite-fold**. Both contract-drift guards folded into ADR-026 + plan (durability; design unchanged): **(a)** the FE gate gains a **codegen-freshness** step (`codegen:check` = re-run `openapi-typescript` + `git diff --exit-code schema.ts`) — the symmetric counterpart of the P3.2 OpenAPI-drift test (ADR-026 D6 + plan §3/§7); **(b)** a **WS-type conformance** vitest asserts the hand-written `StreamMessage` types against the `asyncapi.md` sample shapes — guards WS-envelope drift codegen can't track (ADR-026 D2 + plan §4/§7). Y1 🟡 → 🟢 (13🟢). Original finding preserved below.

> **Exemplary plan for a new stack.** The constitutional spine I inscribed in the brief is faithfully carried into ADR-026 (HR#1–5) and, crucially, **structurally enforced** where it can be — the **binds-API-only** invariant becomes an eslint rule + a no-DB-dep check + a test (not just convention), and **状态机不暴露** becomes an exhaustive never-returns-raw `ui_strings` mapper + a no-raw-vocab-leak DOM test. The contract-binding is right: HTTP types **codegen'd** from the drift-tested `openapi.json`; a **complete** hand-written WS client matching `asyncapi.md` (incl. the sharp `{"kind":"ping"}`-tolerance catch), with dedup centralized in the store. **One LOW 🟡 (Y1)** — the contract-drift guards are under-specified (no codegen-freshness gate; hand-written WS types). Low for the frozen MVP; matters as the contract evolves.

## The five named checks

| # | Check | Verdict | Evidence |
|---|---|---|---|
| 1 | **[spine]** view+intent only? binds-API-only? 状态机不暴露 (no raw leak)? partial-turn correct? no-forge? | **clean (G1–G5)** | ADR-026 HR#1–5 + D4 (each invariant + its enforcement). **binds-API-only is structural** (no DB/fs dep; `fetch`/`WebSocket` confined to `src/api/` via eslint + a test; backdoor rejected constitutionally). partial-turn: store branches on `stage` (turn→reconcile-no-re-post; append→retry). no-forge **type-impossible** (codegen'd `IntentRequest` omits `author`/`id`/`timestamp`). |
| 2 | **[contract-binding]** HTTP types codegen from `openapi.json`? WS client complete (replay→`replay_complete`→live-dedup→`StreamError`→reconnect)? types match ADR-025? | **clean (G6/G7); Y1 (drift guards)** | D2/§3: `openapi-typescript` → `schema.ts`; `client.ts` the sole HTTP surface. D2/§4: hand-written WS client matching `asyncapi.md` exactly — replay/`replay_complete`/live-**dedup-by-`event.id`**/`StreamError`-stage-branch/**ping-tolerate**/reconnect-re-replay; dedup centralized in `applyEvent`. **Y1: no drift-guard binding `schema.ts`/WS-types to the contract — see finding.** |
| 3 | stack (React+Vite+TS+Zustand) + top-level `ui/` + GUI-owned `ui_strings` + FE gate (eslint+tsc+vitest+prettier)? | **clean (G8/G9)** | D1/D3/D6: matches the rulings; CSS-modules+Tabler (restrained §6.1); top-level `ui/`; GUI-owned `ui_strings`; `npm run gate` = eslint+prettier+tsc+vitest (+ codegen script); node `.nvmrc`+`engines`+npm; `contributing.md` FE section mirroring the P3.2 `[api]` pattern. |
| 4 | FE test discriminating (WS replay→live→dedup→reconnect→error; `ui_strings` no-raw-vocab; `StreamError stage:turn`→reconcile-not-re-post)? | **clean (G11)** | §7: the **WS client** test is the heaviest (replay/dedup/reconnect/error/ping); the **`ui_strings`** no-raw-leak test (every enum → human ≠ raw; unknown → safe); the **integration** test asserts `StreamError stage:"turn"` → reconcile (the Composer does **NOT** re-send) — discriminating, not "renders something"; the binds-API-only assertion. |
| 5 | ADR-026 RC-23-safe? scope (read+intent MVP) clear? | **clean (G12)** | ADR-026 `Status: Proposed` (`:3`); grep clean — no `status: accepted`. §Scope explicit: governs spine+stack+`ui/`+gate+role; read+intent MVP; **defers** §6.4 patterns / `DECISION`/`RETRACTION` UX / theming / auth → P3.6. |

## Findings

### Y1 🟡 (low) — contract-drift guards are under-specified (the binding's durability as the contract evolves)

The binding is correct **today** (against the frozen contract). But two drift paths aren't guarded:
- **(a) HTTP codegen freshness.** `schema.ts` is generated by `npm run codegen` from `openapi.json` and **committed**. The FE gate (D6) is `eslint + prettier + tsc + vitest` — **no codegen-freshness step**. So if a future contract change regenerates `openapi.json` but someone forgets `npm run codegen`, `schema.ts` goes **stale** and `tsc` still passes (against the stale types) → silent drift. The ADR calls codegen "drift-proof," but that holds only if the gate **re-runs codegen + diffs** (exactly the symmetric counterpart of the P3.2 **OpenAPI-drift test** the senior already built on the API side).
- **(b) WS types are hand-written** (`asyncapi.md`/`wire.py`'s `StreamMessage` aren't in `openapi.json`) with **no** drift-guard. A future change to the `StreamMessage` envelope would drift the GUI's hand-written types silently.

Neither bites the frozen-contract MVP — but the frontend track's whole premise is that it tracks an **evolving** contract (P3.4+ may add endpoints/event types/fields), and the codegen story is the durability mechanism. Non-constitutional; a robustness/process gap.

**Lean (surface, not decide): α-lite or note-for-impl.** Either (**α-lite**) the senior adds a **codegen-freshness gate step** (`npm run codegen && git diff --exit-code ui/src/api/schema.ts` — fail if stale) and a small **WS-type conformance check** (assert the hand-written `StreamMessage` types against a sample/`asyncapi` shape), folded into the plan's §6/§7; **or** (**note-for-impl**) verify at the impl-stage R0-A. Low; the design is sound, this is durability/completeness. Architect: α-lite-fold / note-for-impl.

## What holds — verified clean (G1–G12)

- **G1 — HR#1 view+intent / no decision surface** (D4): the only write is `POST /intent {type:"user_input", content}`; no client-side state/route/autonomy.
- **G2 — HR#2 binds-API-only, STRUCTURALLY enforced** (D4): `package.json` has no DB/fs/sqlite dep; `fetch`/`WebSocket` confined to `src/api/` via an eslint `no-restricted-globals`/`no-restricted-imports` rule + a constitutional test; no `orchestrator`-path import. "Reach the sqlite directly" is rejected **constitutionally** in the alternatives — the no-backdoor invariant is enforceable, not convention.
- **G3 — HR#3 状态机不暴露** (D3): a GUI-owned `ui_strings` mapper, **exhaustive over the contract enums**, that **never returns the raw key** (unknown → a safe generic), with internal-only vocab (skill / state machine / autonomy / dissent) 不暴露 — plus the no-raw-vocab-leak DOM test.
- **G4 — HR#4 partial-turn correctness** (D4/§5): the store + intent flow branch on `stage` (`turn`→mark landed + reconcile via WS replay, **no re-post**; `append`→retry); the discriminating integration test asserts no re-send on `stage:"turn"`.
- **G5 — HR#5 no-forge, type-impossible**: the codegen'd `IntentRequest` omits `author`/`id`/`timestamp`; the Composer sets only `type:"user_input"`+`content`.
- **G6 — HTTP codegen** (D2): `openapi-typescript` → `schema.ts` from the drift-tested `openapi.json`; `client.ts` the sole HTTP surface (typed `fetch`).
- **G7 — WS client complete + matches `asyncapi.md`** (D2/§4): connect → replay → `replay_complete` (flip loading→live) → live (**dedup by `event.id`**) → `StreamErrorMessage` (`stage` branch) → tolerate `{"kind":"ping"}` → reconnect + re-replay (re-dedup); dedup **centralized** in the store's `applyEvent` (replay/live/reconnect all funnel through it). The highest-risk surface, correctly identified for the heaviest test.
- **G8 — stack + structure** (D1/D5): React+Vite+TS+Zustand, CSS-modules+Tabler, top-level `ui/`; the dedup-centralizing Zustand store; the `App→RoomPicker/RoomCreate→RoomView→{MessageList→MessageItem, Composer, ConnectionStatus}` + `useRoomStream`/`useIntent` tree.
- **G9 — FE gate + contributing + node** (D6): `npm run gate` = eslint+prettier+tsc+vitest (+ `codegen`); `contributing.md` FE section (scoped, mirroring the P3.2 `[api]` pattern); FE PR checklist replacing Q1–Q5 for `ui/`; node `.nvmrc`+`engines`+npm + `ui/README`.
- **G10 — role/review** (D7): Sonnet junior (plan **explicit about FE patterns** since there's no FE to pattern-match); architect-partner R0-A (spine + contract-binding + quality); R0-B skip per the frozen-consumer ruling.
- **G11 — discriminating FE test plan** (§7): the WS client (replay/dedup/reconnect/error/ping), the `ui_strings` no-raw-leak, the `StreamError stage:"turn"`→reconcile-not-re-post integration, the binds-API-only assertion — all discriminating, several **structurally enforcing the spine**.
- **G12 — ADR-026 RC-23-safe + scope clear + sharp self-discoveries**: Proposed (no `status: accepted`); scope defers §6.4 patterns/`DECISION`/`RETRACTION`/theming/auth → P3.6; the self-discoveries (the `ping` keepalive is a non-`StreamMessage` frame to tolerate; binds-API-only is structurally checkable; WS types are hand-written) are accurate and load-bearing.

## What I did NOT do

- Did not accept ADR-026 (architect-only) or advance `.workflow/P3.3.yaml` (committed-state lag is the usual pattern; architect advances).
- Did not decide Y1 — surfaced with a lean (α-lite-fold / note-for-impl); low, non-constitutional (durability/process).
- Single-lens in-family (dual-lens R0-B skipped as ruled); reviewed in an isolated worktree, left the shared tree untouched.
