---
task_id: P4.1
round: R0-A-on-plan
stage: plan
reviewer: architect-partner
plan_commit: a181f56
lens: single
adr: ADR-033 (+ amend ADR-028 D3/D4 + light ADR-011 touch)
verdict: needs_architect
findings_count:
  red: 0
  yellow: 3
  green: 10
verdict_history:
  - verdict: needs_architect
    at: '2026-06-04'
    note: >
      Single-lens R0-A-on-plan (requires_cross_family_review=false; carry the
      plan-stage weight alone). All load-bearing code claims verified vs
      origin/main d878f26 — no blocking defect (loop terminates, gate holds
      per pass, bound is technically absolute). 3 items the architect routes:
      Y1 (liveness magnitude — D4 under-quantifies the dominant term);
      Y2 (the loop ships dormant-in-production — §5#2 confirm);
      Y3 (in-turn context fidelity = latest-result-only — §5#1/#3 confirm).
scope: plan + ADR-033 + ADR-028/011 amendments (claude/P4.1-plan)
---

# R0-A-on-plan — P4.1 (agent turn-loop + read-only code-intel tools)

**Lens:** single (architect-confirmed skip of dual-lens, brief §(c)). I carry the
plan-stage weight alone, so I traced every load-bearing code claim in the plan +
ADR to `origin/main` (d878f26) rather than reading the design at face value
(verify-cite discipline; the RC-20 caution — my own R0-A has a fabricated-probe
false-positive precedent at P2.1/P2.2, so each claim below carries a `file:line`).

**Verdict: `needs_architect`.** The design is sound and I found **no blocking
defect** — the loop terminates, every pass routes the unchanged gate, and the
liveness bound is *technically* absolute. But three items need an architect
route/confirm before the plan locks: **Y1** is a precision/posture finding on the
load-bearing liveness claim (the dispatch's Focus-1); **Y2 + Y3** are the
Focus-5 assessment of the senior's own §5 surfacings (both correctly-scoped — I
lean confirm, but the boundary is the architect's to ratify).

---

## What I verified sound (the load-bearing spine — green)

The plan/ADR rest on a set of substrate facts; I checked each against the code:

- **G1 — Focus-3 no-gate-bypass holds per pass.** `process_tool_calls` appends
  `EventType.TOOL_CALL` **only** for `AUTO_EXECUTE` (`agents/tool_dispatch.py:101,106`)
  and `EventType.TOOL_CALL_PENDING` for `COUNTDOWN_CONFIRM`/`HARD_CONFIRM`
  (`tool_dispatch.py:126,133`); the executor filters its window to `TOOL_CALL`
  only (`tools/executor.py:98`). `process_tool_calls` is **unchanged** by P4.1 and
  is the sole gate path, so a re-dispatch pass cannot execute a tool the gate
  didn't approve, and a confirm-gated call in a pass appends `TOOL_CALL_PENDING`
  (not `TOOL_CALL`) → executor skips it → loop terminates (ADR-033 D3). **Verified.**
- **G2 — Focus-2 termination is real and cooldown-independent.** Bound `N=4`
  (`MAX_TURN_LOOP_PASSES`, D1) + zero-new-`TOOL_CALL` + no-new-result (D3). The
  cooldown gate (`agents/speaking.py:71` — suppress iff `last_utterance and
  cooldown_seconds > 0 and elapsed_s < cooldown_seconds`) only governs whether an
  agent *re-speaks*, never the loop bound. Even if conditions 1–2 never fire, `N`
  caps it. **Verified.**
- **G3 — Focus-1: the agent LLM call IS bounded (refutes an unbounded-correctness
  concern).** I probed whether `dispatch_turn`'s `llm_router.call`
  (`agents/dispatch.py:116`, no inline timeout wrapper) could hang the single
  writer. It cannot indefinitely: providers bound the call —
  `openai_compatible` `timeout_s=60.0` (`providers/openai_compatible.py:67,207`,
  `httpx.TimeoutException → TransientProviderError`), `claude_code_cli`
  `timeout_s=600.0` (`providers/claude_code_cli.py:84,239,257`,
  `asyncio.wait_for`). So ADR-033 D4's "every term finite" is **technically true**
  — I did **not** raise this as a correctness defect. (The *magnitude* of that
  finite term is Y1.)
- **G4 — per-pass cap reconciliation is honest.** The executor's
  `MAX_MCP_CALLS_PER_TURN` / `MAX_POSTURE_B_CALLS_PER_TURN` are function-local
  counters reset at entry (`tools/executor.py:111` `mcp_calls_this_turn = 0`), so
  "per turn" is honestly "per pass" under the loop; total ≤ `(1+N)×` the per-pass
  cap, bounded by constants (ADR-033 D4). The executor is reused unchanged. **Verified.**
- **G5 — the D2 mechanism is correct + honestly limited.** The LLM prompt is
  built from **only** `current_event.content` (`agents/dispatch.py:112`) +
  persona + skill bodies; `build_agent_context` provably ignores the snapshot
  (`agents/selection.py:99` `_ = snapshot`). `dispatch_turn` re-takes its own
  snapshot at entry (`agents/dispatch.py:78`), so pass *k* sees pass *k−1*'s
  appended results. `run_turn` evaluates `next_room_state` **before** dispatch
  and appends a `state_transition` (`rooms/runtime.py:86,90-103`) — so the D2
  decision to re-dispatch via **`dispatch_turn` directly** (not `run_turn`) per
  pass is correct: it keeps the state machine once-per-turn and avoids a duplicate
  `state_transition`. **Verified — the design rationale is sound, not asserted.**
- **G6 — the driver loop is feasible exactly as P4.1-4 describes.**
  `_write_and_turn` is `pre_cursor` → `run_turn` → `window =
  get_room_events[pre_cursor:]` → `execute_pending_tool_calls(window_events=window)`
  → single publish (`api/app.py:366,374,389,390,399-400`). The bounded loop wraps
  cleanly (re-dispatch + execute per pass, publish the accumulated
  `[pre_cursor:]` once). The separate `_post_confirm` path does a single execute
  with no loop (`api/app.py:514`) and is correctly named out-of-scope (P4.1-4). **Verified.**
- **G7 — the P4.1-1 extraction is genuinely behavior-preserving.** The load-time
  + dispatch-time filter the helper factors out is `decide_agents_for_room` +
  the `applies_to.room_states ∈ {["*"], room.state}` comprehension
  (`rooms/runtime.py:106-115`); extracting it to `select_dispatch_agents` and
  having both `run_turn` and the driver call it is a pure refactor. **Verified.**
- **G8 — the constitution carry-forward is structurally guaranteed, not just
  tested.** The only new code is the driver loop (calls `dispatch_turn` +
  `execute_pending_tool_calls`) + the tool impls; gate-per-pass is structural
  (the sole gate path `process_tool_calls` is unchanged), and there is no new
  `LLMPurpose`/`EventType` (`core/event.py:84,97` already has `TOOL_CALL` +
  `TOOL_CALL_PENDING`; ADR-030). P4.1-5 asserts in-process B2 (no
  `subprocess`/`Popen`) + trusted-not-interpreted. **Sound.**
- **G9 — RC-23-safe.** ADR-033 is `Status: Proposed`; the ADR-028/011 amendments
  are explicitly marked "Proposed via ADR-033 … pending architect Accept." No
  premature `Status: Accepted` on the new contract. **Verified.**
- **G10 — B2 trust boundary reuse is correct.** The 4 code-intel tools are
  already `rev 10 → AUTO` + `log_event` `rev 8 → AUTO` in `config/tools.yaml`
  (impl, not re-classification); they reuse the ADR-028 D3 `_check_path` sandbox
  + bounded output, plus a new `MAX_SEARCH_FILES` traversal cap (the FS-walk
  liveness analog of the bounded read). Carry-forward #6 (in-process only) is
  inscribed + test-guarded. **Sound.**

---

## Findings the architect routes (none blocking)

### 🟡 Y1 — D4's "absolute bound" is true but **under-quantifies the dominant, cross-room-blocking term** (Focus-1)

**Evidence.** ADR-033 D4 states the bound as `≤ (1+N) × (one dispatch_turn block
+ the ADR-028 D5 per-pass execution bound)` and labels it "(the claim, kept
true)". It names the `dispatch_turn` block as "sequential agent LLM calls …
inherited from ADR-011" — **honest as far as it goes** — but leaves it as an
un-quantified symbol, whereas ADR-028 D5 (the bound D4 *extends*) meticulously
enumerated every term (`MAX_MCP_CALLS_PER_TURN × (MCP timeout + interpret
timeout)`). The actual magnitude of that symbol: `(speaking agents) ×
(provider timeout_s)`, where `provider timeout_s` is **up to 600s**
(`providers/claude_code_cli.py:84`; `openai_compatible` is 60s,
`providers/openai_compatible.py:67`). So the headline bound is really
`(1+N) × agents × up-to-600s` — and, per ADR-028 D5's own framing, the single
writer "blocks **every** room's writes, not just its own room's turn." P4.1 thus
multiplies the **cross-room head-of-line block** by `(1+N)=5×` over a
per-pass occupancy that can already be minutes long.

**Why it matters / why `needs_architect`.** This is **not** a correctness defect
(the bound *is* finite — G3) and **not** the senior missing the term (D4 names
it). It is a precision gap that hides a **posture** question the architect should
rule, exactly as ADR-028 D5 made the inline-vs-separate-lane posture explicit:
*is `N=4` × (agents × up-to-600s) inline-on-the-single-writer an acceptable
cross-room liveness posture for P4.1?* The "new liveness cost is exactly the
bounded `(1+N)` multiplier" framing is true but reads as small; the felt cost is
multiplier × a minutes-scale, all-rooms-blocking multiplicand.

**My lean (architect routes — I do not):** α — amend D4 to **enumerate the
dominant term with D5's rigor** (agents × provider `timeout_s`, naming the 600s
worst case + the cross-room occupancy), and on that basis confirm `N=4`
inline-on-writer is the ratified posture **or** add an overall turn-loop
wall-clock deadline (the cheapest way to make the *absolute* wall-clock — not
just the *factor* — bounded). This is the D5/R1 precedent (name the boundary
explicitly); it does not change the design, only its honesty + the architect's
informed sign-off.

### 🟡 Y2 — the turn-loop ships **built + tested but dormant in production** (Focus-5 / §5#2)

**Evidence.** Multi-step chaining requires `cooldown_seconds = 0`
(`agents/speaking.py:71` — verified), and the §1 chain is proven by a **test
agent** only; the plan scopes out any production-roster change (P4.1-3/§5#2). I
could not find a production `cooldown_seconds=0` investigator/operator agent, so
on landing, **no production agent exercises the loop** — the capability is live
in tests and dormant in the shipped roster until such an agent is configured.

**Why `needs_architect`.** This is the inscribe-mechanism-before-producer pattern
(defensible — the same shape as ADR-028 shipping the executor before tools, and
B2's tools landing before an agent wields them), and the senior **correctly
flagged it for confirm** ("confirm that is the intended boundary"). It is a scope
boundary, not a defect — but it is the architect's to ratify, because "the
flagship scenario runs" is the slice's stated value and it does **not** run for
any shipped agent until the follow-up.

**My lean (architect routes):** α — accept dormant-in-production; a follow-up
(separate content/roster surface) adds the `cooldown=0` investigator agent. (β
would bundle a minimal investigator agent into P4.1 to make it live on landing —
viable if the architect wants the capability demonstrably live, not just tested.)

### 🟡 Y3 — in-turn context fidelity is **latest-result-only**, named but architect-confirm (Focus-5 / §5#1+#3)

**Evidence.** Because the LLM prompt is `current_event.content` only
(`agents/dispatch.py:112`; `agents/selection.py:99` `_ = snapshot`), the
re-dispatched agent sees **only the latest result event** each pass — not its
accumulated investigation — and when a pass produced several results, only the
**last in store order** is passed (ADR-033 D2 + §5#3). `snapshot_excerpt` (the
richer-context field) has been deferred since P1.4 (`selection.py:90-93`).

**Why `needs_architect`.** Honest + named (not a defect), but it is a real
fidelity ceiling on the flagship "investigate → synthesise findings" scenario the
slice exists for: the agent chains step-by-step but cannot reason over its own
prior-pass results in one prompt. The senior recommends shipping at this fidelity
with `snapshot_excerpt` as a separate enrichment; I **agree it is correctly
scoped** (it is a distinct context-builder surface), but the architect should
consciously confirm P4.1 ships at step-by-step fidelity.

**My lean (architect routes):** confirm-as-scoped — `snapshot_excerpt` is a
separate follow-up, not bundled. (Lowest-stakes of the three; leans clean-confirm.)

---

## Probe-foci coverage (the 5 the dispatch named)

| Focus | Result |
|---|---|
| 1. Liveness bound — `(1+N)×`, N=4; per-pass cap honest | cap reconciliation **sound** (G4); `(1+N)×` multiplier real; agent-LLM term **bounded** (G3) but **under-quantified** → **Y1** |
| 2. Termination — zero-new-`TOOL_CALL` / no-new-result / N; cooldown-independent | **verified sound** (G2) |
| 3. No-gate-bypass — unchanged `process_tool_calls`; t4 per pass; COUNTDOWN/HARD → `TOOL_CALL_PENDING` → terminate, not executed, no human-block | **verified sound** (G1) |
| 4. Constitution carry-forward inscribed (ADR-033 D6) + enforced (P4.1-5) | **sound** (G8) — gate-per-pass structural; no new purpose/event-type |
| 5. The 3 senior §5 surfacings — boundaries right? | (a) latest-result fidelity → **Y3**; (b) no cooldown=0 roster → **Y2**; (c) `current_event`=last-result-class → folded into **Y3**; all **correctly-scoped, architect-confirm** |

## Authorship note

Architect-partner R0-A-on-plan, single-lens, verified vs `origin/main` d878f26.
Every load-bearing claim carries a `file:line` (verify-cite). I refuted one
candidate finding (agent-LLM-unbounded) by tracing the provider timeouts rather
than asserting it (G3) — the bound is finite; **Y1 is its under-quantified
magnitude + the posture call it hides, not a correctness break.** No blocking
defect. **I surface; I do not route** — the architect routes Y1/Y2/Y3
(per the dispatch + my role boundary).
