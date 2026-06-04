# ADR-033: Agent Turn-Loop — In-Turn Tool-Result Re-Dispatch + Loop Bound

**Status:** Proposed — 2026-06-04 (senior-drafted for P4.1, the P4 capability opener; architect Accepts). Bundles two proposed amendments accepted together with this ADR: **ADR-028 D3** (read-only code-intel tools + `log_event` added to the local MVP set) and **ADR-028 D4** (the re-dispatch deferral marked resolved → this ADR), plus a light **ADR-011** snapshot-per-turn extension note. RC-23-safe: no `Status: Accepted` here or in the amendments until the architect accepts.

**Scope:** Governs the **agent turn-loop** — the driver-level mechanism that feeds a turn's tool results back to the agent **within the same turn**, so an agent can chain *investigate → read-result → act → re-investigate* (the flagship bug-fix / code-review scenario, `handoff.md` §toolset 第一/二层). Inscribes: the loop **shape** (bounded-loop ≤N, the architect's §(a) ruling) and the documented bound `N` (D1); **what re-dispatches** and the per-pass `current_event` (D2); the **termination test** + the confirm-gated-call interaction (D3); the **total single-writer liveness bound** extending ADR-028 D5, the per-pass cap reconciliation, and the cooldown interaction (D4); the **B2 read-only code-intel tools** (`search_text`/`search_code`/`find_references`/`find_definition`) + `log_event`, in-process + sandboxed + bounded-traversal + trusted-not-interpreted (D5); the **constitutional invariants under the loop** + the ADR-011 extension (D6). Does **NOT** govern: the autonomy gate decision logic (`score`/`decide_tier`/`emit_gate_decision`/`process_tool_calls` — **unchanged**; the loop re-runs the gate per pass, never changes it); a separate execution lane off the single writer (ADR-028 D5 — stays deferred); the heavier tool surfaces (subprocess B3 / network B4 / mutation B5 — each its own P4.2 slice); richer in-turn agent context (`snapshot_excerpt` on `AgentContext` — deferred since P1.4, ADR-011 D4 / `agents/selection.py`; see D2 and Consequences).

## Context

ADR-028 (the runtime tool-executor) shipped tool **execution** but left the agent loop **open at one end**: `execute_pending_tool_calls` appends `TOOL_RESULT`/`TOOL_FAILED`/`OBSERVATION` and **returns** — the agent reacts only on the *next* real turn's snapshot (ADR-028 D4's no-re-dispatch MVP). So an agent **cannot** do "read file → see contents → search for the symbol I found → see hits → open the reference" inside one turn. ADR-028 D4 deferred re-dispatch precisely to *"a follow-up that explicitly inscribes the loop bound — an ADR-011 touch-point."* This is that follow-up.

The substrate P4.1 reuses (verified `origin/main`, d878f26):
- `api/app.py::_write_and_turn` — the turn driver: `append(user_event)` → `run_turn(...)` → `execute_pending_tool_calls(window)` → publish. The loop lives **here** (the driver), wrapping `run_turn`/`dispatch_turn` + the executor; neither the executor nor `dispatch_turn` is rewritten.
- `rooms/runtime.py::run_turn` — snapshot → `next_room_state` (may append a `state_transition`) → load-time + dispatch-time agent filter → `dispatch_turn`.
- `agents/dispatch.py::dispatch_turn` — re-takes its own snapshot at entry (`event_store.get_room_events(room.id)`), evaluates `should_agent_speak` per agent, calls the LLM with `messages=[user: current_event.content]`, appends `UTTERANCE`, and routes any tool calls through the **unchanged** `process_tool_calls` (gate) → `TOOL_CALL` (AUTO) or `TOOL_CALL_PENDING` (COUNTDOWN/HARD).
- `agents/speaking.py::should_agent_speak` — cooldown is event-stream-driven: `elapsed_s = (current_event.timestamp − last_utterance.timestamp)/1000`; if `< cooldown_seconds` and `cooldown_seconds > 0`, the agent is suppressed (ADR-010 D2).
- `tools/local.py` — 3 read-only local tools (`get_current_time`/`read_file`/`list_files`) + the ADR-028 D3 sandbox-root trust boundary (`_check_path` resolve-then-containment, bounded read/output). `config/tools.yaml` already classifies `search_text`/`search_code`/`find_references`/`find_definition` at **rev 10 → AUTO** + `log_event` at **rev 8 → AUTO**, all currently `not_implemented` (fail-closed). ADR-033 builds the in-process impls.

**A substrate fact that shapes D2 (verified, load-bearing):** `dispatch_turn` feeds the LLM **only** `current_event.content` (`agents/dispatch.py:112`); `build_agent_context` explicitly **ignores** the snapshot (`agents/selection.py:99` — `_ = snapshot`; `snapshot_excerpt` was deferred at P1.4). So the only way an agent's LLM prompt *sees* a tool result is for that result event to be passed as `current_event`. This is why D2 passes the latest result event on each re-dispatch pass, and why richer accumulated-investigation context is named as a deferred follow-up, not silently assumed.

## ⭐⭐ Constitutional carry-forward (NON-NEGOTIABLE — inscribed, not decided; per P4-roadmap §10)

The senior inscribes; the impl enforces; R0-A probes each.

1. **The loop is CODE-driven (routing = code).** The loop condition — *"did this pass append a new `TOOL_CALL` event, and are we under the bound N?"* — is **pure driver code**. **No LLM judges "should I loop again."** The LLM only generates content **within** each dispatched turn (which may contain tool calls). The re-dispatch trigger, the bound, and the termination test are all code.
2. **No new `LLMPurpose`.** A re-dispatched pass reuses the existing `AGENT_RESPONSE` turn primitive (`dispatch_turn`); the MCP interpret (if any pass calls an MCP tool) reuses the existing content-gen `TOOL_OUTPUT_INTERPRET`. "Agent reacts to a tool result" is **not** a new purpose — it is `dispatch_turn` re-run against a snapshot that now **includes** the appended result events. No new event type, no new purpose.
3. **Every pass routes the gate — the loop NEVER bypasses or re-decides autonomy.** Each pass's tool calls go through the **unchanged** `process_tool_calls`→gate→`AUTO_EXECUTE`-only-appends-`TOOL_CALL` path; the executor's `t4` (execute-on-`TOOL_CALL`-only) holds **per pass**. A `COUNTDOWN`/`HARD` call in a pass appends a `TOOL_CALL_PENDING` (no `TOOL_CALL`) → is **not** executed in-loop → uses the existing confirm-then-execute flow (ADR-030) out-of-band; **the loop does NOT wait for human confirm** (D3).
4. **Single-writer invariant preserved (ADR-028 D1/D5).** Re-dispatch stays **inline on the single writer** (the D5 MVP posture); a separate execution lane stays deferred. The loop multiplies the per-pass block by `(1+N)` — that bounded multiplier is the **named, inscribed** liveness surface (D4), not an accident.
5. **The loop TERMINATES and the single-writer block is absolutely BOUNDED.** Termination via the bound `N` **and** early-exit when a pass appends zero new `TOOL_CALL`s (D3); liveness via `(1+N) ×` the per-pass bound (D4).
6. **B2 = read-only, in-process, sandboxed, trusted-not-interpreted (D5).** In-process only (`os.walk`+`re`; **no** `grep`/`rg`/`git grep`/language-server — shelling out would smuggle in the deferred B3 subprocess surface); reuse the ADR-028 D3 trust boundary (sandbox root, `_check_path`, bounded output) + a **new bounded traversal** cap; local results are trusted → **not** interpreted (no `OBSERVATION`).

## Decisions

### D1. Loop shape — bounded-loop ≤N; `N = MAX_TURN_LOOP_PASSES = 4` (a documented constant)

Per the architect's §(a) ruling: the turn-loop is a **bounded-loop**, not a single-re-dispatch. After `run_turn` + the executor finish the initial turn (**pass 0**), the driver **re-dispatches repeatedly** until a pass appends no new `TOOL_CALL`s **or** `N` re-dispatch passes elapse. `N = 4` (`MAX_TURN_LOOP_PASSES`, a module-level constant in the driver). Total `dispatch_turn` invocations per turn ≤ **1 + N = 5**.

**Why bounded-loop, not single-re-dispatch:** the flagship investigation (`read_file` → `search_text` → `find_references` → `find_definition`/`log_event`) is a ≥3-hop chain; single-re-dispatch gives the agent exactly **one** reaction and cannot chain. **Why N = 4:** it covers the 第一/二层 flagship chain with one hop of headroom, while keeping the single-writer multiplier small and the liveness cost conservative (D4). `N` is the **inscribe-before-producer** constant every P4.2+ tool slice rides on; it is tuned by amending this ADR, never by ad-hoc code.

### D2. What re-dispatches — `dispatch_turn` per pass; the state machine runs once; `current_event` = the latest result of the prior pass

- **Pass 0** is the existing `run_turn` (snapshot → `next_room_state` → filter → `dispatch_turn`) followed by `execute_pending_tool_calls`. **Passes 1…N** call **`dispatch_turn` directly** (not `run_turn`): the state-machine evaluation (`next_room_state`, which may append a `state_transition`) runs **exactly once per turn** (pass 0). Re-running `run_turn` per pass would re-evaluate `next_room_state` against the unchanged (frozen) `room.state` and risk a **duplicate `state_transition`** — and is conceptually wrong: a state transition takes effect on the **next** turn (ADR-011 D2), not mid-loop. The in-turn loop is *within one room state*.
- **Filtered agents.** `dispatch_turn` needs the load-time + dispatch-time-filtered agent set that `run_turn` computes inline. P4.1 **extracts** that filter into a pure helper `select_dispatch_agents(room, available_agents)` in `rooms/runtime.py` (behavior-preserving); `run_turn` calls it (unchanged behavior) and the driver calls it once before the loop. This avoids duplicating the filter in the driver — single source of truth.
- **`current_event` per pass.** On re-dispatch pass `k`, the driver passes the **most-recent result-class event** (`TOOL_RESULT` / `TOOL_FAILED` / `OBSERVATION`) appended during pass `k−1`'s execution as `current_event`. Rationale (load-bearing, see Context): `dispatch_turn` feeds the LLM only `current_event.content`, so the result event must **be** the `current_event` for the agent to react to it. `dispatch_turn` re-takes its own snapshot at entry, so the full updated event log is visible to `should_agent_speak`/cooldown. If a pass appended multiple results, the **last in store order** is chosen (deterministic). If a pass appended **no** result-class event, the loop terminates (D3).

**Named limitation (honest, not silent):** the agent's LLM prompt sees only the **latest** result per pass (plus persona/skills), **not** the full accumulated investigation — because `build_agent_context` ignores the snapshot (`selection.py:99`, deferred at P1.4). The agent chains step-by-step (each pass reacts to the immediately-preceding result), which is sufficient for the flagship chain at MVP fidelity. Richer in-turn context (`snapshot_excerpt`) is a **separate deferred enrichment**, out of P4.1 scope.

### D3. Termination test + confirm-gated-call interaction

The loop terminates when **any** of:
1. **Zero new `TOOL_CALL` events** were appended by the just-completed pass (the agent stopped calling tools — investigation done). This is the primary early-exit.
2. **No new result-class event** exists to pass as the next `current_event` (defensive: e.g., every new `TOOL_CALL` was a double-execution-guard skip → nothing fresh to react to).
3. **`N` re-dispatch passes** have run (the hard bound).

`TOOL_CALL` here means the gate's `AUTO_EXECUTE` record. A pass producing **only** a `COUNTDOWN`/`HARD` call appends a `TOOL_CALL_PENDING` (no `TOOL_CALL`) → condition 1 fires → the loop **terminates**; the pending call is resolved later via the confirm endpoint (ADR-030) on a **future real turn** (out-of-band). The loop **never blocks on human confirm** and stays synchronous + terminating (carry-forward #3). The confirm path (`_post_confirm`) itself is **unchanged** and stays a single execute (a post-confirm re-dispatch loop is a possible future symmetry — out of scope, named).

### D4. The total single-writer liveness bound (extends ADR-028 D5) + per-pass cap + cooldown interaction

- **The bound (the claim, kept true).** Worst-case single-writer block per turn ≤ **`(1 + N) ×` (one `dispatch_turn` block + the ADR-028 D5 per-pass execution bound)**. The per-pass execution bound is ADR-028 D5 verbatim (`MAX_MCP_CALLS_PER_TURN × (MCP-call timeout + interpret timeout)` + negligible local-tool time). The `dispatch_turn` block (sequential agent LLM calls) is the **existing** per-turn cost inherited from ADR-011 — the loop does **not** make it unbounded; it multiplies it by the **constant** `(1+N)`. The **new** liveness cost of this ADR is exactly that bounded `(1+N)` multiplier.
- **Per-pass cap reconciliation.** `MAX_MCP_CALLS_PER_TURN` / `MAX_POSTURE_B_CALLS_PER_TURN` are **per-`execute_pending_tool_calls`-invocation** counters (locals reset at function entry). A pass = one invocation → the caps reset **per pass** (the chosen semantics). Total MCP/Posture-B calls across the loop ≤ `(1+N) ×` the per-pass cap — still **absolutely bounded** by the constants. The executor is **unchanged**; "per turn" is honestly "per pass" under the loop, and the loop bound caps the number of passes.
- **Cooldown interaction (load-bearing for whether the loop *progresses*).** `should_agent_speak` suppresses an agent whose last utterance is within `cooldown_seconds` (ADR-010 D2). Loop passes are sub-second, so **any** `cooldown_seconds > 0` agent re-speaks **at most once** per loop (cooldown is its per-agent backstop). An agent that should chain multi-step must be configured **`cooldown_seconds = 0`**. **Termination is independent of cooldown** — it relies on the bound `N` + zero-new-`TOOL_CALL` (D3), never on cooldown. Cooldown + the zero-new-`TOOL_CALL` early-exit + `N` together prevent a non-tool-calling agent from a speak-loop (the ADR-011 backstops).

### D5. B2 — read-only code-intel tools + `log_event` (impl + wire; reuse the ADR-028 D3 boundary + a new traversal bound)

P4.1 builds the **in-process** impls for the already-classified names and registers them in `build_local_tool_registry`:

| Tool | tools.yaml | Semantics | Implementation (in-process; **no subprocess**) |
|---|---|---|---|
| `search_text(query, scope=None)` | rev 10 AUTO | literal/substring text search | `os.walk` over the sandbox (or `scope` subdir) + substring match; `file:line` hits |
| `search_code(pattern, scope=None)` | rev 10 AUTO | regex search | `os.walk` + `re.search(pattern, line)`; `file:line` hits |
| `find_references(symbol, scope=None)` | rev 10 AUTO | identifier usages (heuristic) | `os.walk` + word-boundary regex on the identifier; **not** a language server |
| `find_definition(symbol, scope=None)` | rev 10 AUTO | definition site (heuristic) | `os.walk` + regex for `def <symbol>` / `class <symbol>` / `<symbol> =`; **not** a language server |
| `log_event(content, type)` | rev 8 AUTO | agent records a finding | returns a `LocalToolOutput` recording the note → lands as a **`TOOL_RESULT`** via the executor's local path |

**Trust boundary (reused + extended).** All four search/find tools reuse the ADR-028 D3 boundary: the **same operator-configured sandbox root**, `_check_path` resolve-then-containment on the optional `scope` (reject traversal/symlink/absolute escape → `TOOL_FAILED`), and **bounded output** (`MAX_RESULT_BYTES`). **New: bounded traversal** — the FS-walk liveness analog of `read_file`'s bounded read: a files-scanned cap `MAX_SEARCH_FILES` (a documented constant) bounds the walk, and each file is read bounded (never load a multi-GB file fully). This keeps every B2 call **fast + absolutely bounded**, so it adds no unbounded inline block to the single writer (D4). Local results are **trusted → not interpreted** (no `OBSERVATION`; ADR-028 D2) — they stand in the next pass's snapshot.

**`log_event` (the one write — included; rev-8 triviality accepted).** `log_event` is a *write*, but it writes **only to our own event log** by returning a `LocalToolOutput` that the executor appends as a normal `TOOL_RESULT` — **no `event_store` handle is given to the tool fn** (the `dict → LocalToolOutput` contract is preserved) and **no new event type** is added. The durable "log" is the `TOOL_RESULT` event, visible in the next pass's snapshot (flagship: investigate → log finding). **Loop-write interaction:** local tools have no per-turn cap (ADR-028 D5 exempts them as fast/bounded), so over `(1+N)` passes an agent could emit several `log_event`s. This is **accepted as rev-8 trivia**, because: (i) `log_event` lands via the pure local path — sub-ms, **no single-writer block** → zero liveness impact (the D4 bound is untouched); (ii) the only cost is event-log row growth, itself bounded by `(1+N) ×` per-pass agent generation and harming only the emitting agent's own room snapshot (no cross-room effect); (iii) rev-8 = trivially prunable. **Forward-watch:** if bloat is ever observed, the Posture-B cap pattern (`_is_posture_b_subprocess` attribute → `MAX_*_PER_TURN`) is the ready extension point for a `MAX_LOCAL_WRITES_PER_PASS` — deferred until observed, named here so this is a posture, not an oversight.

### D6. Constitutional invariants under the loop + the ADR-011 extension

- **No new `LLMPurpose`** (`tests/tools/test_constitution.py` t3 stays green). **No autonomy decision in the loop** — the driver loop calls `dispatch_turn` + `execute_pending_tool_calls`; it never calls `score`/`decide_tier`/`emit_gate_decision`. **Execute-on-`TOOL_CALL`-only holds per pass** (executor t4 unchanged; the loop re-invokes the same executor). **B2 trusted-not-interpreted** (local code-intel/`log_event` results append no `OBSERVATION`).
- **ADR-011 snapshot-per-turn extension.** In-turn re-dispatch re-runs `dispatch_turn` against the **growing** event log within the **same** turn — each pass re-takes the per-turn snapshot at `dispatch_turn` entry, so pass `k` sees pass `k−1`'s appended results. This **extends** ADR-011 D2 (snapshot-per-turn) to **snapshot-per-pass within a turn**; the cross-turn causality is unchanged (state transitions still take effect next turn — `next_room_state` runs once, pass 0). The speak-loop backstops (cooldown + zero-new-`TOOL_CALL` + `N`) keep the per-turn pass count bounded (see ADR-011 amendment note).

## Considered alternatives

- **Single-re-dispatch (one extra pass).** Rejected (D1, architect §(a)): terminates trivially but gives the agent only one reaction — cannot chain the ≥3-hop flagship investigation.
- **Re-run the full `run_turn` each pass.** Rejected (D2): re-evaluates `next_room_state` per pass against the frozen `room.state` → risks a duplicate `state_transition` and contradicts ADR-011's "transition takes effect next turn." `dispatch_turn`-per-pass keeps the state machine once-per-turn.
- **Narrowed re-dispatch (only the tool-calling agent re-evaluates).** Rejected (D2 / senior-design surface): a new narrowed dispatch primitive; full `dispatch_turn` is ADR-011-consistent and multi-perspective, with the same termination backstops.
- **Give `log_event` an `event_store` write handle / a new `NOTE` event type.** Rejected (D5): breaks the `dict → LocalToolOutput` local-tool contract and widens the surface; the `TOOL_RESULT`-as-log shape is durable with zero new vocabulary.
- **Per-loop accumulate caps (one budget across all passes).** Rejected (D4): the executor's per-invocation counters give per-pass reset for free; `(1+N) ×` the per-pass cap is already absolutely bounded — accumulate would require changing the (reused-unchanged) executor.

## Consequences

**Easier:** the flagship multi-step bug-fix / code-review scenario **actually runs** — an agent chains `read_file → search_text → find_references → …` within one turn. The loop bound `N` is the single inscribed constant every P4.2+ tool slice rides on. The B2 sandbox + bounded-traversal pattern is established for future read tools.

**Harder:** a `(1+N)` single-writer multiplier on the per-turn block (named, bounded — D4); a new FS-walk traversal bound to get right; the agent's in-turn context fidelity is limited to the latest result per pass (D2 named limitation) until `snapshot_excerpt` lands; multi-step investigation only progresses for `cooldown_seconds = 0` agents (D4).

**Neutral:** the executor and `dispatch_turn` are reused unchanged; the only new code is the driver loop + the `select_dispatch_agents` extraction + the 5 tool impls. confirm-gated calls stay out-of-band (D3). The gate decision logic is untouched.

## Reversibility

| Decision | 6-month reversal cost |
|---|---|
| D1 bounded-loop + `N` | **Low** — `N` is one constant; reverting to no-loop removes the driver while-loop (the executor/dispatch are untouched). |
| D2 `dispatch_turn`-per-pass + `select_dispatch_agents` + `current_event`=latest-result | **Low** — the extraction is behavior-preserving; the `current_event` choice is a driver-local rule. |
| D3 termination test | **Low** — driver-local conditions. |
| D4 liveness bound / per-pass cap / cooldown | **Medium** — moving caps to per-loop-accumulate, or moving execution off the writer, is a concurrency change (ADR-028 D5 territory). |
| D5 B2 tools + sandbox + traversal bound | **Medium** — the tool set is additive; relaxing the sandbox/traversal bound is a trust-surface decision (architect-gated). |
| D5 `log_event`-as-`TOOL_RESULT` (no new event type) | **Low** — additive; a future `NOTE` type or a local-write cap is additive on top. |
| D6 constitution invariants + ADR-011 extension | **Do-not-reverse** — the code-driven-loop / no-new-purpose / gate-per-pass spine is the carry-forward. |

## References

- `docs/process/architect-briefs/P4.1.md` (the 4 decision points + the constitutional carry-forward §⭐⭐; architect-ratified bounded-loop / small N / new-ADR-033 + amend-028/011 / single-lens R0-A / `log_event` in).
- `docs/process/senior-plans/P4.1.md` (this ADR's plan — atomic graph + test plan).
- `docs/process/P4-roadmap.md` §3 (B1/B2 ledger), §7 (the lowest-new-trust opener), §10 (routing=code / inscribe-before-producer).
- ADR-028 D1/D2/D3/D4/D5/D6 (the executor — downstream-of-gate, mcp/local dispatch, the **sandbox-root boundary** B2 reuses, the **re-dispatch deferral** this ADR resolves, the **single-writer liveness bound** D4 extends, the constitution tests). **Amended by this ADR: D3** (code-intel tools + `log_event` → local MVP set), **D4** (re-dispatch deferral → resolved).
- ADR-011 D2 (snapshot-per-turn — extended to snapshot-per-pass-within-a-turn by D6; see the ADR-011 amendment note). ADR-010 D2 (cooldown — the speak-loop backstop, D4). ADR-030 (confirm-then-execute — the out-of-band path for `COUNTDOWN`/`HARD` calls in a pass, D3). ADR-005/006 (the gate every pass re-routes).
- `src/orchestrator/api/app.py::_write_and_turn` (the loop site), `rooms/runtime.py::run_turn` (`select_dispatch_agents` extraction), `agents/dispatch.py::dispatch_turn` (reused), `agents/selection.py:99` + `agents/dispatch.py:112` (the snapshot-not-in-LLM-prompt fact behind D2), `tools/executor.py::execute_pending_tool_calls` (reused; per-pass caps), `tools/local.py` (B2 impls + `_check_path` + bounded patterns), `config/tools.yaml` (the rev-10 code-intel + rev-8 `log_event` classifications), `handoff.md` §toolset 第一/二层.
