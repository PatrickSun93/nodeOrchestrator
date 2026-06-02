---
task_id: P3.2
round: R0-A-on-plan
stage: plan
reviewer: architect-partner
plan_commit: a51cfcd
lens: single
adr: ADR-025
verdict: needs_architect
findings_count:
  red: 0
  yellow: 1
  green: 14
verdict_history:
  - verdict: needs_architect
    at_commit: a51cfcd
    findings_count: { red: 0, yellow: 1, green: 14 }
    note: >-
      Initial R0-A-on-plan (in-family, single-lens — the dual-lens R0-B is dispatched for the
      impl stage, requires_cross_family_review: true). Reviewed senior-plans/P3.2.md + ADR-025
      (Proposed) in an isolated worktree at a51cfcd. Exemplary new-infra plan — every named
      check verifies clean. The constitutional/security spine is faithfully inscribed (ADR-025
      HR#1-4, non-negotiable): (1) no decision surface — the intent endpoint does exactly
      append(user_event) + run_turn; state/activation/routing/autonomy stay backend; the one
      LLM-touching seam (api/llm_adapter delegating to select_model_and_provider) is decision-free
      glue; no new LLMPurpose (9 unchanged). (2) forge-prevention is load-bearing and solid: the
      IntentRequest carries no author/id/timestamp; the server hardcodes author:"user" + stamps
      id/ts + 422-fail-closed off-allowlist before any append → a client cannot forge
      system/agent/STATE_TRANSITION/AUTONOMY_*. (3) raw wire + GUI-owns-ui_strings (状态机不暴露
      shifts to P3.3); localhost-trust MVP (127.0.0.1, auth-none, payload-limit, CORS) with the
      invariants holding regardless of bind. (4) the contract (wire models + OpenAPI + AsyncAPI)
      is complete, pinned in the first atomic (inscribe-before-producer), frozen/extra=forbid
      round-trip + OpenAPI-drift tested. (5) sync-bridge = a serialized single-writer executor
      (correct for append-only single-writer sqlite) + RoomEventBus cursor-diff pub/sub with NO
      EventStore change (wrap-don't-reimplement honored; the serialization is what makes
      cursor-diff attribution correct). (6) heavy discriminating test plan (§1-§4/§6) incl. the
      run_turn/append-raises -> 5xx-store-consistent failure mode (the P1.4 dual-lens lesson).
      ADR-025 RC-23-safe (Proposed; no status:accepted substring). One LOW 🟡 (Y1): the allowlist
      admits DECISION + RETRACTION whose typed metadata carries authority semantics beyond
      shape-validation (DECISION promotion=True is the durable-memory-promotion path = Principle
      11; RETRACTION targets another event) — validate_metadata checks shape, not authority;
      confirm downstream gating or constrain the MVP. Not a forge gap (these are legitimately
      user-authored); non-blocking; Principle-11-adjacent. Concurrency/failure-mode watch-items
      handed to the dispatched dual-lens R0-B. Did NOT accept ADR-025 or advance state.
---

# P3.2 R0-A on plan (architect-dispatched pre-impl review, in-family, single-lens)

| Field | Value |
|---|---|
| Round | R0-A-on-plan (RC-9; single-lens — the **dual-lens R0-B is dispatched for the impl stage**, `requires_cross_family_review: true`) |
| Artifacts | `senior-plans/P3.2.md` + `ADR-025` (Proposed) vs `origin/main` substrate + brief P3.2 |
| Reviewed at | isolated worktree `/tmp/p32-r0a` @ plan `a51cfcd` (shared tree was mid-branch-switch by a concurrent session — RC-7 isolation) |
| ADR status | ADR-025 left **Proposed** — informs accept; I did not accept (architect-only). |

## Verdict: needs_architect — 0🔴 · 1🟡 · 14🟢

> **Exemplary plan for a new-infra slice.** The constitutional/security spine I inscribed in the brief is faithfully carried into ADR-025 (HR#1–4, non-negotiable) and the plan, and the senior's self-discoveries are sharp — especially **"`Event.author` permits `user|system|agent` so the schema alone is *not* the forge guard; the API must hardcode `author:"user"` + omit author from the wire"** (the load-bearing security insight) and the **`UTTERANCE` exclusion** (barring the agent speech-act so a client can't drive `UTTERANCE`-keyed transitions). Every named check verifies clean. **One LOW 🟡 (Y1)** — two allowlisted intent types (`DECISION`/`RETRACTION`) carry typed-metadata *authority* semantics beyond shape-validation (Principle-11-adjacent); a verify-don't-assume gap, not a forge gap. Concurrency/failure-mode pressure-points are handed to the **dispatched dual-lens R0-B** (the lens built to catch exactly those).

## The six named checks

| # | Check | Verdict | Evidence |
|---|---|---|---|
| 1 | **[spine]** API no decision surface (backend-authoritative)? no new routing/judgment `LLMPurpose`? `api/` no routing/gating? | **clean (G1–G3)** | ADR HR#1 + D3: intent = `append(user_event)` + `run_turn`; `next_room_state`/`should_agent_speak`/`select_model_and_provider`/autonomy-gate all backend. The one seam — `api/llm_adapter` — **delegates** the routing decision to `select_model_and_provider` + executes it (decision-free glue, §10). **No new `LLMPurpose`** (9, grep-asserted); `api/` no routing/judgment. |
| 2 | write-surface forge-prevention: client only `author:user` + allowlist, fail-closed, can't forge `system`/`agent`/`STATE_TRANSITION`/`AUTONOMY_*` | **clean (G4/G5); Y1 (authority depth)** | D4: `IntentRequest` has **no author/id/timestamp**; server hardcodes `author:"user"` + stamps id/ts; type-allowlist → **`422` before any append**; metadata + parent_id validated. `UTTERANCE` excluded (D4a). **Y1: `DECISION`/`RETRACTION` typed-metadata authority — see finding.** |
| 3 | state machine 不暴露 (wire raw + GUI mapping)? trust boundary (localhost MVP)? | **clean (G6/G7)** | D5: raw `state`/event-type wire; GUI owns `config/ui_strings/` (P3.3). D7: bind `127.0.0.1`, auth-none, payload-limit, CORS; invariants hold regardless of bind; remote hardening = forward hook. |
| 4 | contract (ADR-025 + Pydantic + OpenAPI) complete, inscribe-before-producer, frozen `extra=forbid` round-trip? | **clean (G8)** | D5 + plan P3.2-1 (first atomic): wire models + FastAPI **OpenAPI** + hand-authored **AsyncAPI** committed first; `§6` round-trip (frozen/`extra=forbid`) + an **OpenAPI-drift** test. `IntentRequest` `extra="forbid"` is itself a forge guard. |
| 5 | FastAPI HTTP/WS/pub-sub + sync-bridge reasonable? wrap-don't-reimplement (core/rooms/autonomy/llm unchanged)? | **clean (G9–G11)** | D6: serialized **single-writer executor** (one conn/one thread; correct for append-only single-writer sqlite; sidesteps `check_same_thread`; frees loop for WS) + `RoomEventBus` **cursor-diff** pub/sub + replay-then-subscribe + drop-slow-subscriber. **No `EventStore` change** (cursor-diff observation, not an `append` hook). Plan is docs-only — `core/rooms/autonomy/llm` untouched. |
| 6 | Q1–Q5 + test-coverage (§1–§4/§6)? | **clean (G12/G13)** | Heavy discriminating plan: §1 full intent loop (right events + forged-author/off-allowlist/bad-metadata **rejected**); §2 concurrency; §3 failure-modes (`run_turn`/`append` raises → `5xx`, store consistent — the P1.4 dual-lens lesson); §4 boundary; §6 round-trip + drift. No new `LLMPurpose` grep-asserted. |

## Findings

### Y1 🟡 (low) — the intent allowlist admits `DECISION` + `RETRACTION`, whose typed metadata carries *authority* semantics beyond shape-validation (verify-don't-assume; Principle-11-adjacent)

The forge-prevention itself is **solid** (G4): a client cannot set `author` or forge a `system`/`agent`/`STATE_TRANSITION`/`AUTONOMY_*` event. Y1 is a **different axis** — two of the three allowlisted types (`{USER_INPUT, DECISION, RETRACTION}`, D4a) carry typed metadata whose *authority* `validate_metadata` does **not** check (it validates shape/co-presence, not authority):

- **`DECISION{promotion:true}`** is the **durable-memory-promotion** speech-act (ADR-016 D11; "user-confirm promotion" requires `hypothesis_id` + `vk_id` + `user_id`). `validate_metadata` confirms the three co-present; it does **not** confirm the referenced hypothesis/vk **exist**, are in a **promotable state**, or that this is the legitimate confirmer. A client reading the event stream could construct a promotion `DECISION` → reach the durable-memory path (**Principle 11** territory).
- **`RETRACTION{retracts:X}`** targets another event. Per the plan, `retracts` "must reference an existing event" — but it's not stated whether the target must be the user's **own** event (vs. retracting an **agent**/`system` event). Can a user retract an agent's utterance?

Both are *legitimately user-authored* (so **not a forge gap**). The open question is whether the MVP intends a client-posted `DECISION`/`RETRACTION` to reach these durable/cross-event paths, and if so, whether the **downstream** paths gate authority (`promotion.py` validating hypothesis/vk existence+state; retraction validating target ownership/room) — or whether shape-validation at the API is the whole gate.

**Lean (surface, not decide): α-lite or note-for-impl.** Either (**α-lite**) the senior adds a one-line spec — "promotion `DECISION` + `RETRACTION` via `/intent` are gated downstream by [the existing checks]; **or** the MVP allowlist constrains `DECISION` to `promotion=False` + `RETRACTION` to `author:"user"` targets" — and the impl tests it; **or** (**note-for-impl**) verify at the impl-stage R0-A + flag explicitly for the dual-lens R0-B (the forge/authority lens). Low; non-blocking; the forge boundary holds. Touches **Principle 11**, so worth the architect's eye. Architect: α-lite-fold / note-for-impl.

## What holds — verified clean (G1–G14)

- **G1** — HR#1 backend-authoritative (D3): the intent endpoint is exactly `append(user_event)` + `run_turn`; every decision (`next_room_state`, `decide_agents_for_room`/`should_agent_speak`, `select_model_and_provider`, autonomy gate) stays backend.
- **G2** — the `llm_adapter` (the missing concrete `LLMRouterProtocol`, §10 gap) is **decision-free glue**: it delegates the routing *decision* to the unchanged `select_model_and_provider` and executes it; makes none of its own. Explicitly flagged (D3) "so reviewers can confirm the boundary holds" — the right transparency for the one LLM-touching seam.
- **G3** — **no new `LLMPurpose`** (9, unchanged; grep-asserted in the plan); `api/` carries no routing/judgment.
- **G4** — HR#2 forge-prevention core (D4): `IntentRequest` has no `author`/`id`/`timestamp`; server hardcodes `author:"user"` + stamps id/ts; off-allowlist `type` → **`422` fail-closed before any append**; `metadata` + `parent_id` validated. Backend stays sole author of `system`/`agent`/transition events.
- **G5** — `UTTERANCE` excluded (D4a): correctly bars the **agent** speech-act, preventing a client from driving `UTTERANCE`-keyed transitions — a sharp boundary catch.
- **G6** — HR#3 raw wire (D5): raw `state`/event-type names; the 状态机不暴露 obligation lands on the GUI (`config/ui_strings/`, P3.3). Pre-humanized wire correctly rejected (would leak presentation into a ≥5-task contract).
- **G7** — HR#4 trust boundary / localhost MVP (D7): `127.0.0.1`, auth-none, validation + fail-closed + payload-limit + CORS; the forge + no-decision-surface invariants hold **regardless of bind**; remote hardening (auth/TLS/rate-limit) = forward hook.
- **G8** — contract complete + pinned-first (D5 + P3.2-1): wire models + OpenAPI + AsyncAPI committed in the **first atomic** (inscribe-before-producer); frozen/`extra=forbid` round-trip + OpenAPI-drift test; `IntentResponse`/`StreamMessage` envelopes specified.
- **G9** — sync-bridge = serialized single-writer executor (D6): one conn/one thread for all core calls; correct for append-only single-writer sqlite; sidesteps `check_same_thread` + write contention; frees the loop for WS fan-out; a turn's multi-append is atomic w.r.t. other writers.
- **G10** — push = `RoomEventBus` cursor-diff pub/sub + replay-then-subscribe + bounded-queue/drop-slow-subscriber, with **no `EventStore` change** (cursor-diff *observation*, not an `append` hook) — wrap-don't-reimplement honored. Design coherence: the serialized executor is precisely what makes cursor-diff attribution correct (no concurrent writer can interleave into the window).
- **G11** — wrap-don't-reimplement: only net-new `api/` (+ the optional `[api]` dep + the decision-free `llm_adapter`); `core/rooms/autonomy/llm` decision logic untouched (verified — the plan diff is docs-only).
- **G12** — atomic graph: contract-first, **single-junior serial** (new infra, tightly coupled — no within-slice parallelism, consistent with the brief); the right test-§ attached per atomic.
- **G13** — test plan heavy + discriminating (Q1/Q3/Q4/Q5; §1–§4/§6): the full intent loop with explicit rejections; §2 concurrency (N subscribers, interleaved intents, drop-slow); §3 failure-modes incl. `run_turn`/`append` raises → `5xx` store-consistent (the P1.4 dual-lens lesson applied); §6 round-trip + OpenAPI-drift.
- **G14** — ADR-025 **RC-23-safe** (Proposed; no literal `status: accepted` substring; the "accept" mentions are the Proposed-status line + a semantic "accepted intent").

## Watch-items for the dual-lens R0-B + forward notes (green — flagged, not findings)

The cross-family R0-B is dispatched (`requires_cross_family_review: true`; §9; external prompt drafted). These are sound/acknowledged in the plan — I hand them to the concurrency/failure-mode lens (per `dual-lens-r0b.md`, exactly what it catches) rather than route them:

- **W-a (concurrency latency):** the single-writer executor serializes **reads** behind any in-flight turn — and a turn includes the LLM network call (via `llm_adapter`), so a slow turn blocks other clients' `GET`s. D6 acknowledges this ("acceptable for localhost MVP; WAL/read-replica forward hook"). R0-B should pressure-test read-latency under a concurrent turn; a **separate read connection** is the natural forward hook if it bites.
- **W-b (push correctness):** confirm no event escapes or duplicates across the **replay→subscribe** handoff under concurrent turns (the serialized executor should guarantee it — verify the cursor handoff is gap/dup-free).
- **W-c (contract):** confirm `TurnResult` (embedded in `IntentResponse`) serializes cleanly to the wire — it's part of the pinned contract.
- **W-d (forward note for P3.3):** the **状态机不暴露** UI obligation now lands on the GUI (`config/ui_strings/`) — carry it into the P3.3 brief so the raw-wire contract isn't surfaced to users verbatim.

## What I did NOT do

- Did not accept ADR-025 (architect-only) or advance `.workflow/P3.2.yaml` (committed state lags reality — see report; architect advances).
- Did not decide Y1 — surfaced with a lean (α-lite-fold / note-for-impl); low, Principle-11-adjacent, non-blocking.
- Single-lens in-family (the dual-lens R0-B is dispatched for impl); reviewed in an isolated worktree, left the shared tree untouched.
