---
task_id: P3.6
stage: R0-A-on-plan
reviewer: architect-partner
verdict: clean
verdict_history:
  - needs_architect
  - [2026-06-03, clean, "Architect routed Y1+Y2 → α (Y1 ratified as the ADR-028 D6 t4 two-appender broadening). Senior absorbed: ADR-030 D1 retracts 'preserved verbatim' + inscribes the broadening; t4 test amended in B3; B1 acceptance scoped to B1; Y2 predicates position-anchored + consistent; N1-N3 absorbed. See architect-routing-on-plan.md."]
adr_under_review: ADR-030
plan_under_review: docs/process/senior-plans/P3.6.md
date: 2026-06-03
scope: >-
  R0-A-on-plan lens over ADR-030 + the P3.6 senior plan. Seven probes the architect set:
  (1) no-forge/backend-authoritative, (2) downstream-of-gate, (3) TOOL_CALL_PENDING decision-neutrality,
  (4) idempotency, (5) the TOOL_CALL sole-appender invariant, (6) partial-turn, (7) 不暴露.
findings:
  - id: Y1
    severity: needs_architect
    probe: 5
    title: >-
      ADR-028 D6 t4 sole-appender invariant is broken by B3 (a second TOOL_CALL appender) while ADR-030 D1
      claims it is "preserved verbatim"; B1 acceptance + the external R0-B prompt carry the contradicting framing.
  - id: Y2
    severity: needs_architect
    probe: 4
    title: >-
      The endpoint still-pending check (D3 step 2) and the snapshot predicate (D2) key on call_id — documented
      collision-prone cross-turn (executor.py:98) — and are specified inconsistently (D3 "existing" vs D2 "later").
---

# R0-A-on-plan — P3.6 (confirm-then-execute + GUI completeness), ADR-030

**Verdict: `needs_architect`.** The plan + ADR are strong work — the senior caught a real error in my brief (the "already on the wire" premise; §below) and designed a minimal, decision-neutral fix around it. Two findings need the architect: **Y1** is a constitutional-invariant amendment that the ADR claims to *preserve* but the slice actually *breaks* (the `TOOL_CALL` sole-appender) — it must be honestly restated + re-tested, and it under-specifies the slice's own security crux; **Y2** is a traced collision/consistency gap in the two idempotency predicates. Neither is blocking — the design is sound and both fixes are bounded — but both turn on calls that are the architect's, not mine or the senior's (a constitutional restatement; an idempotency posture).

## Verification basis (checked against `origin/main` @ b0e7fae, not eyeballed)

| Claim | Verified |
|---|---|
| `EventType.TOOL_CALL` has **one** appender today | ✅ `agents/tool_dispatch.py:105` only (grep across `src/`; `event.py:347` is the meta-registry, `snapshot.py:79/168` + `executor.py:93` are **reads**). |
| countdown/hard branch "persists nothing" today | ✅ `tool_dispatch.py:125-134` — the `else` appends only an in-memory `ToolDispatchDecision`; **no `event_store.append`**. So B1's `TOOL_CALL_PENDING` is purely additive in a dead branch. |
| `tool_calls_pending_confirm` is **structurally empty** in the running app | ✅ `snapshot.py:157-190` correlates a `TOOL_CALL` to its AD; every `TOOL_CALL` is AUTO → AD tier `auto_execute` → hits the `:190` "not pending" branch. The field can never populate. **The senior's §5 push-back #1 is correct.** |
| `AUTONOMY_DECISION` lacks `call_id`+`params` | ✅ `emission.py:86-109` carries `operation_tool_id`/`tier`/trace, no `call_id`, no `params` — so the AD genuinely cannot reconstruct the call (D1's rejected-alternative reasoning holds). |
| executor keys on `TOOL_CALL` only + full-room `call_id` guard | ✅ `executor.py:93` filters to `TOOL_CALL`; `:100-115` builds `already_executed` from `TOOL_RESULT`/`TOOL_FAILED` (full-room, D2). |

## Y1 — the `TOOL_CALL` sole-appender invariant (probe #5, the architect's flagged judgment) — **needs_architect**

**The finding.** ADR-028 D6 t4(i) is: "`EventType.TOOL_CALL` has exactly **one** appender in `src/` … AST/grep-verifiable (sole-appender)" — the *structural* half of the downstream-of-gate guarantee. **B3's confirm endpoint appends a `TOOL_CALL` on approve** (ADR-030 D3 step 4). So after P3.6, `TOOL_CALL` has **two** appenders: `tool_dispatch.py:105` (AUTO) **and** `api/app.py` (confirm-approve). **The sole-appender invariant is broken by this slice.**

ADR-030 D1 states the opposite: "`EventType.TOOL_CALL` keeps exactly one appender (the AUTO branch) … so ADR-028 D6 t4's sole-appender property is **preserved verbatim** for `TOOL_CALL`." That sentence is true for **B1 in isolation** (B1 only adds `TOOL_CALL_PENDING`, a distinct type) but **false for the slice** — it conflates "B1 adds no `TOOL_CALL` appender" with "the slice preserves sole-appender." B3 does add one. The inconsistency then propagates:
- **B1 acceptance** asserts "`EventType.TOOL_CALL` still has exactly one appender (the AUTO branch) — ADR-028 D6 t4 preserved." After B3 that test **must fail or be deleted** — the plan ships a test that cannot survive its own slice.
- **The external R0-B prompt** point 6 tells the dual-lens to "Confirm `EventType.TOOL_CALL` still has exactly **one** appender (the AUTO branch)." The cross-family reviewer, tracing the confirm endpoint, will find **two** — the prompt mis-primes them against the very property the slice changes.

**Why it matters (not cosmetic).** The *semantic* guarantee — every `TOOL_CALL` is gate-approved — **is** preserved: the AUTO appender fires only for `AUTO_EXECUTE`, and the confirm appender fires only after the gate decided countdown/hard **and** a human approved over a persisted `TOOL_CALL_PENDING`. But t4 deliberately split the guarantee into "(i) grep-verifiable structural + (ii) behavioral filter + test" *because* the structural half is what makes it cheap to audit. The confirm appender's "I only append from a persisted gate-produced record, reconstructing payload/author from it, never from client input, only after the still-pending check" is **not grep-verifiable** — it is exactly the runtime trust-surface the dual-lens exists to probe. Leaving t4 stated as "sole-appender preserved" means the slice's **own security crux has no named structural invariant or test** — it's asserted in prose (D3/HR#1) and tested ad-hoc in B3 acceptance, but not elevated to the t4-level guarantee it replaces.

**Lean (α-absorb; architect ratifies the constitutional restatement).** Restate ADR-028 D6 t4 inside ADR-030 as the honest post-P3.6 invariant: **`TOOL_CALL` now has two appenders, both gate-approved** — (i′) the AUTO branch (grep-verifiable, unchanged) and (i″) the confirm-approve path, which needs its **own named constitutional guard + test**: it appends a `TOOL_CALL` *only* by reconstructing `{tool_name, call_id, params}` + `author=agent:<initiating_agent>` from a persisted `TOOL_CALL_PENDING`, *only* after the still-pending check, *never* from request fields. Then fix B1's acceptance (move the appender-count assertion to B3: "exactly two, both gate-approved") and external-prompt point 6. This is the same honest-inscription discipline the ADR already applies to the `process_tool_calls` change (D1) and the ADR-025 D4 authorship broadening (D3) — it just **missed the t4 structural invariant**, which is the one most directly broken. The architect's call because it ratifies a constitutional-invariant amendment (CLAUDE.md: ADR amendment + Architect Accept required).

## Y2 — idempotency/pending predicates key on collision-prone `call_id`, inconsistently (probe #4) — **needs_architect**

The two idempotency layers and the snapshot predicate all resolve by `call_id`, which the codebase **already documents as collision-prone cross-turn** (`executor.py:98`: "LLM-generated call_ids can collide cross-turn") — and they're specified **inconsistently**:
- **D2 (snapshot, B2):** a `TOOL_CALL_PENDING` is pending iff "no **later** event for the same `call_id` resolves it" — ordering-aware ("later").
- **D3 step 2 (endpoint still-pending check, B3):** "scan room history for **an existing** `TOOL_CALL`/`TOOL_RESULT`/`TOOL_FAILED`/`TOOL_CALL_CANCELLED` with the same `call_id`. If present → `already_resolved`." — **position-blind** ("an existing").

Note this is a **new** dependency on `call_id`: the *current* snapshot keys pending on `(author, tool_name)` (`snapshot.py:159,167,170`), not `call_id` — so B2 introduces the `call_id`-resolution model, and the cross-turn-collision exposure comes with it.

**Traced failure.** Turn 1: a countdown call `call_id="abc"` is confirmed + executed → `TOOL_RESULT(call_id="abc")`. Turn 5: the LLM re-emits `call_id="abc"` for a new countdown call → a fresh `TOOL_CALL_PENDING(call_id="abc")`. The snapshot (D2, "later") correctly shows it **pending** (the turn-1 result is *earlier*). The endpoint (D3, "existing") scans, finds the turn-1 `TOOL_RESULT(abc)`, and **rejects the confirm as `already_resolved`** → the GUI shows a confirmable call the endpoint refuses to confirm. A latent **liveness defect + a GUI/endpoint inconsistency** on the exact trust surface this slice establishes. (The fail direction is *closed* — it refuses rather than double-executes — consistent with the executor's deliberate posture, so it's not a forge/double-execute; but a silent "can't confirm this" is a real defect the dual-lens point 7 also gestures at.)

**Lean (α-absorb).** Make both predicates **ordering/lineage-aware and consistent**: scope the resolution scan to events **after** the specific `TOOL_CALL_PENDING` (by `pending_event_id` position), or thread `pending_event_id` into the reconstructed `TOOL_CALL`/result lineage so resolution is keyed on the unique pending id rather than the bare `call_id`. State the collision posture explicitly, mirroring the executor's documented full-room-but-collision-aware reasoning (D2 / `executor.py:97-98`). Architect routes (it's a posture choice that touches the ADR-014 re-point + the endpoint contract).

## Affirmed — the senior's brief-error catch is correct; my brief needs a correction note

The senior's §5 push-back #1 (and ADR-030 §Context) is **right, and it is a correction of my brief.** I wrote — in the P3.6 brief and in my chat summary to the orchestrator — that pending calls are "already on the frozen wire (`Snapshot.tool_calls_pending_confirm`), no contract change," framing even (b) as pure-frontend. **That premise is false against the live code** (verified: the field is structurally empty; §Verification). Even D-B=(b) would have needed the D2 snapshot fix; (c) needs D1+D2+D3. The senior surfaced rather than improvising, and the resolution (a recording-only `TOOL_CALL_PENDING`, gate logic untouched) is the minimal correct fix. **Recommend a brief correction note** so the architect's (and the record's) mental model is right — this is an honest brief defect I own, not a ding on the plan.

## Affirmed strengths (probes 1, 2, 3, 6, 7 — what's right)

- **No-forge / backend-authoritative (1):** `ConfirmRequest{pending_event_id, decision}` `extra="forbid"`; `tool_name`/`params`/`author` reconstructed from the persisted record; author forced to `agent:<initiating_agent>`. Forge-guard at the schema layer + reconstruction-from-record — correctly specified (D3/HR#1).
- **Downstream-of-gate (2):** executor unchanged (`executor.py:93` only-on-`TOOL_CALL`), no re-gate, gate functions untouched. Holds — **modulo Y1's restatement of *why* it still holds with two appenders.**
- **Decision-neutrality (3):** verified the countdown/hard branch is genuinely empty today, so `TOOL_CALL_PENDING` is additive; `score`/`decide_tier`/`emit_gate_decision` untouched; the narrow `process_tool_calls` amendment is honestly inscribed (D1). Good.
- **Partial-turn (6):** D5 mirrors ADR-025 D5 with a dedicated `ConfirmError` type (`stage:{append, execute}`) — clean separation from `IntentError`'s `{append, turn}`.
- **不暴露 (7):** `autonomy_tier` drives affordance only (never rendered), `mcp__` stripped, unknown tool → "一个工具", no-raw-leak tests (D6 / F2-F3). Appropriately discriminating.
- The senior's push-backs #2 (COUNTDOWN explicit-confirm, auto-fire deferred — a correct trust-surface call), #3 (the agent-authored `TOOL_CALL` broadening, honestly flagged), #4 (length) are all sound surfacings.

## Nits (🟢 — senior may absorb without architect routing)

- **N1:** D3 step 4 records a `DECISION` event citing `user_id`, but auth is out of scope (localhost-trust, ADR-025 D7) — there is no `user_id` source. Either drop it for the MVP or mark it an explicit placeholder; don't inscribe a field with no provenance.
- **N2:** B3 introduces `TOOL_CALL_CANCELLED`. Give it the **same** discipline B1 gives `TOOL_CALL_PENDING` — EventType-exhaustiveness + metadata-registry + `validate_metadata` round-trip + the constitutional test (B3's "where" mentions it; the acceptance doesn't assert the exhaustiveness coverage).
- **N3:** The single-writer atomicity of check→append→execute is load-bearing for both idempotency layers. Add an explicit plan-level test target asserting the confirm handler runs on the **writer** executor (the dual-lens re-probes the runtime, but a named test pins the intent).

## For the dispatch flow
- **Y1 fix must also patch `external-r0b-prompt.md` point 6** before the dual-lens runs — otherwise the cross-family reviewer is primed against a property the slice intentionally changes.
- Routing leans are **α-absorb for both Y1 and Y2** (restate + re-test; tighten the predicates) — but I do **not** route; the architect calls α/β/γ. State stays `awaiting_senior_plan` (R0-A-on-plan is a manual RC-9 dispatch, no state change).
