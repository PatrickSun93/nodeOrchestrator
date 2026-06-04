---
task_id: P4.1
round: R0-A-on-plan
stage: plan
reviewer: architect-partner
plan_commit: a181f56
round2_plan_commit: c549c25
lens: single (plan stage; dual-lens R0-B ratified for IMPL stage only)
adr: ADR-033 (+ amend ADR-028 D3/D4 + SUBSTANTIVE ADR-011 amendment)
verdict: needs_architect
findings_count:
  round1: { red: 0, yellow: 3, green: 10 }
  round2: { red: 0, yellow: 1, green: 6, forward_note: 1 }
verdict_history:
  - verdict: needs_architect
    at: '2026-06-04'
    round: 1
    note: >
      Single-lens R0-A-on-plan (requires_cross_family_review=false; carry the
      plan-stage weight alone). All load-bearing code claims verified vs
      origin/main d878f26 — no blocking defect (loop terminates, gate holds
      per pass, bound is technically absolute). 3 items the architect routes:
      Y1 (liveness magnitude — D4 under-quantifies the dominant term);
      Y2 (the loop ships dormant-in-production — §5#2 confirm);
      Y3 (in-turn context fidelity = latest-result-only — §5#1/#3 confirm).
  - verdict: needs_architect
    at: '2026-06-04'
    round: 2
    note: >
      RE-RUN re-verifying the absorption (db496ef + c549c25). The 3 routed
      yellows are FAITHFULLY ABSORBED + verified sound, the spine is untouched
      (additive-only revisions), ADR-033 stays Proposed (RC-23) + is
      constitutionally clean. Nothing blocks the ADR-033 Accept. One light
      scope-confirm + one routing-confirm remain: R2-Y1 (the bundled
      investigator's room-scope + always-on user_input posture — confirm the β
      shape); R2-N1 (snapshot_excerpt untrusted-MCP-content framing — already
      routed to the impl external-R0B; confirm it stays tasked). Verdict stays
      needs_architect only for those two confirms — absorption itself: clears.
scope: plan + ADR-033 + ADR-028/011 amendments (claude/P4.1-plan); round 2 re-verifies the Y1/Y2/Y3 absorption
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

---

# Round 2 — absorption re-verification (revision `db496ef` + `c549c25`)

**Dispatch:** RE-RUN, plan stage, single-lens (the dual-lens flip the senior §5
raised + the architect ratified applies at **impl** stage only —
`external-r0b-prompt.md` is written for it). The architect routed all 3 round-1
yellows **in-cycle** (Y1 → α + wall-clock deadline; Y2 → β bundle the
investigator; Y3 → bundle `snapshot_excerpt`), materially widening the plan
(5 → 8 atomics). I re-verify the **absorption** against `origin/main` d878f26;
I do **not** re-derive the round-1-cleared spine (re-confirmed untouched below).

## Absorption verdict per routed yellow — all three VERIFIED SOUND

| Routed | Absorbed as | My re-verification (verify-cite) | Result |
|---|---|---|---|
| **Y1** α + wall-clock | ADR-033 **D4 enumerated** + **D3 condition 4** | D4 now states the dominant term explicitly: `(speaking agents) × provider timeout_s` bounded by `claude_code_cli timeout_s=600.0` (`providers/claude_code_cli.py:84`) / `openai 60.0` (`providers/openai_compatible.py:67`), no inline wrapper (`agents/dispatch.py:116`), **cross-room** on the single writer `ThreadPoolExecutor(max_workers=1)` (`api/app.py:171` — **cite verified**), `× (1+N)`. The enumeration is faithful to my Y1. The wall-clock deadline `MAX_TURN_LOOP_WALL_CLOCK_S=120.0` (D3 cond. 4): `loop_start=time.monotonic()` **before pass 0** (covers the whole turn), checked **at each pass boundary** — and the honesty is explicit: "checked between passes, not mid-pass (no async cancellation, ADR-011 D1) → absolute wall-clock ≤ deadline + **one** final-pass overrun," incomplete work "continues on the next real turn." Sound: the deadline caps the *absolute* occupancy (≈`deadline + 1 pass`) where `N` alone capped only the *factor* (`5 × agents × 600s`). | ✅ **honest + sound** |
| **Y2** β investigator | ADR-033 **D5** + atomic **P4.1-7** + `config/agents/investigator.yaml` | Genuinely minimal + **no smuggled capability**: `cooldown_seconds: 0` (the chaining prereq); the `tool_result` chain-trigger is **schema-valid** (`EventTypeTrigger.event_type: EventType` `agents/schema.py:36` ⊇ `TOOL_RESULT` `core/event.py:85`); read-only persona (`read_file`/`search_*`/`find_*`/`log_event`), **no mutation** — and the **gate backstops** anything beyond read-only regardless of persona (a rev-1 `git_push` → `TOOL_CALL_PENDING`, not auto-exec); auto-loaded via `load_agents(config_dir/"agents")` (`api/app.py:176` — **cite verified**); the existing tool-caller `operator` is `cooldown_seconds: 10` (`config/agents/operator.yaml:28` — **verified**, genuinely cannot chain). Roster-count blast radius is handled (P4.1-7 names the promotion-impact grep). | ✅ **minimal + scoped** (see R2-Y1) |
| **Y3** bundle `snapshot_excerpt` | ADR-033 **D2/D6** + **substantive ADR-011 amendment** + atomic **P4.1-6** | Constitutionally clean on every axis the dispatch named: a **new optional field** `snapshot_excerpt: str\|None=None` on `AgentContext` (`agents/schema.py:191` additive — and `:205` already documents the P1.4 deferral this resolves); populated in `build_agent_context` from the **already-passed** snapshot param (`agents/selection.py:99` — **no live read**); **bounded** `MAX_SNAPSHOT_EXCERPT_CHARS`; fed into the system block (additive to `agents/dispatch.py:105-106`); **no new `LLMPurpose`** (still `AGENT_RESPONSE`, `dispatch.py:109`); **no new `EventType`**; additive to ADR-011 (the amendment correctly couples snapshot-per-pass + the field). | ✅ **constitutionally clean** (see R2-N1) |

## Spine re-confirmation (round-1-cleared — untouched, additive-only)

The revision diff touches **only** `ADR-033` / `ADR-011` / the plan /
`external-r0b-prompt.md` — **no `src/` change** (it is plan stage). The round-1
spine holds: termination conditions 1–3 unchanged (cond. 4 *added*); gate-per-pass
(carry-forward #3) reaffirmed; `current_event`-as-trigger (D2) preserved + now
*split* from `snapshot_excerpt`-as-context (a clarification, not a reversal);
executor + `dispatch_turn` gate/dispatch path still reused unchanged. The
widening is purely **additive**. Not re-derived; confirmed additive.

## Round-2 findings (none blocking; the absorption itself clears)

### 🟡 R2-Y1 — confirm the bundled investigator's room-scope + always-on posture (β shape)
The architect ruled β ("bundle a minimal investigator"); the senior chose
`applies_to.room_types: [bug_fix, code_review, research]` + room_states `["*"]` +
an **always-on `user_input` trigger** (P4.1-7 / D5). Consequence worth a conscious
nod: this is the roster's **first always-on `cooldown_seconds=0` agent** and the
**first `tool_result`-triggered agent** — so **every** user message in any
bug_fix/code_review/research room now starts an investigation loop (up to `N=4`
passes + tools). That is the intended *live-on-landing* demonstration of β, but
the room breadth + always-on cost are a senior-design choice within β, not
derivable from "minimal" alone. **Lean: acceptable as the capability demo —
architect confirm the room-scope + always-on shape** (or narrow, e.g.
bug_fix/code_review only). Minor advisory, same surface: the plan does not pin the
investigator's `autonomy_thresholds` (the existing `operator` sets
`threshold_auto: 6`, `operator.yaml:38`) — recommend an **explicit conservative**
value for true minimality (the gate backstops either way). **Architect routes.**

### ▫️ R2-N1 (forward-note, not a new decision) — `snapshot_excerpt` untrusted-content framing
The excerpt renders the recent event slice (`author: content`) into the LLM
prompt — which can include **raw MCP `TOOL_RESULT`** content (untrusted), one pass
before/with its interpreted `OBSERVATION`. This is (i) **partially pre-existing**
(the loop's `current_event` could already be a raw result) and (ii) **already
explicitly routed to the impl-stage external R0-B** (`external-r0b-prompt.md`
tasks "untrusted-result injection" on the `snapshot_excerpt` surface). So plan
stage is **clean**; I only **confirm it stays tasked** + recommend the excerpt
prefer the interpreted/trusted view or carry untrusted-framing. No plan-stage
action; the impl dual-lens owns the deep probe.

## Coherence + RC-23
- **8 atomics + order coherent.** `1→2→3→4→5→6→7→8`; deps sound (4 needs 1+2/3;
  5 layers the deadline on 4; 6 precedes 7 so the live investigator reasons over
  accumulated context; 7's live test needs 2/3/4/5/6; 8 constitution last).
  One-commit-each (RC-17). The new atomics (5 wall-clock / 6 `snapshot_excerpt` /
  7 investigator) map 1:1 to Y1/Y3/Y2. ✅
- **RC-23.** `ADR-033` remains `**Status:** Proposed` (the revision notes +
  "architect Accepts" are prose, not a `Status: Accepted` literal); the ADR-028 /
  ADR-011 amendments are marked "Proposed … pending architect Accept." ✅

## Round-2 verdict — `needs_architect` (light); the absorption clears
The three routed yellows are **faithfully absorbed and verified sound**; the spine
is untouched; ADR-033 is constitutionally clean + RC-23-safe; the 8-atomic graph
is coherent. **Nothing blocks the ADR-033 Accept.** The verdict stays
`needs_architect` **only** for the two confirms — **R2-Y1** (investigator
room-scope + always-on β shape; + explicit thresholds) and **R2-N1** (confirm the
`snapshot_excerpt` untrusted-framing stays on the impl-R0B list) — both
*confirm-while-accepting*, neither a blocker. **I surface; I do not route.**

**Round-2 authorship note.** Architect-partner re-verification, single-lens (plan
stage), verified vs `origin/main` d878f26 — every absorption claim re-cited
(`app.py:171`/`:176`, `claude_code_cli.py:84`, `openai_compatible.py:67`,
`schema.py:36`/`:191`/`:205`, `operator.yaml:28`/`:38`, `core/event.py:85`). I
did not re-derive the round-1 spine (confirmed additive-only). The Y1 enumeration
+ wall-clock honesty are exactly the absorption I asked for at round 1; Y2/Y3 are
minimal + clean. Residual is two confirms, neither blocking Accept.
