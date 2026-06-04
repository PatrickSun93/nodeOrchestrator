# External R0-B prompt for P4.1 — agent turn-loop + read-only code-intel tools (impl-stage dual-lens)

**Purpose**: copy-pasteable system prompt + artifact bundle for a **true cross-family R0-B** (DeepSeek-class / GPT-class) on the **P4.1 implementation** (the agent turn-loop B1 + the read-only code-intel tools B2) + ADR-033 (Proposed) + the ADR-028/011 amendments. Dispatched at **impl stage** on `claude/P4.1-impl` (commits `P4.1-1..8`).

**Dispatch rationale (`requires_cross_family_review: true` — architect-ratified the senior §5 flip, plan-stage).** P4.1 was briefed single-lens, but the R0-A-on-plan absorption **widened the slice** into exactly the two surfaces the cross-family lens out-probes Claude on:
1. **Liveness arithmetic** — the turn-loop multiplies the single-writer block by `(1+N)` over a dominant `agents × provider-timeout_s` term (**up to 600s** `claude_code_cli`), a **cross-room head-of-line** stall, now mediated by a `MAX_TURN_LOOP_WALL_CLOCK_S = 120s` wall-clock-deadline timing mechanism. This is the runtime-integration / liveness class the **P1.4 DeepSeek** R0-B caught (the `event_store.append` + liveness findings the in-family pass conceded) and that Claude structurally under-weights.
2. **The `snapshot_excerpt` prompt-assembly surface** — Y3 resolved the long-deferred P1.4 `AgentContext.snapshot_excerpt` and now feeds accumulated investigation into the `dispatch_turn` LLM prompt. A constitutional + bounding surface (new purpose? new event type? a live read? unbounded context? untrusted-result injection?).

**How to use**: open a non-Claude session (DeepSeek via the local proxy on `:8788`, or a GPT-class web session), paste the system prompt, read the artifacts from disk (or paste). Ask: "Generate the R0-B review per the mandatory output format." Architect-partner saves the returned review as `docs/process/reviews/P4.1/R0-B-cross-family.md`. Per RC-15, external findings carry the same weight as in-session R0-A.

---

## System prompt

```
You are reviewing the IMPLEMENTATION (+ design: ADR-033 Proposed + the ADR-028/011 amendments) of an AGENT TURN-LOOP for a multi-agent orchestration framework called "shipOrchestrator" — an AI research/decision assistant built by a solo developer through a structured, role-separated workflow. Until now a tool result NEVER fed back to the agent within a turn (ADR-028 D4 no-re-dispatch MVP): the agent reacted only on the NEXT turn. P4.1 (B1) closes that loop — a DRIVER-LEVEL bounded loop that re-dispatches the agent within the SAME turn so it can chain read_file → search_text → find_references → … — and (B2) adds the in-process read-only code-intel tools (search_text/search_code/find_references/find_definition) + log_event so the loop has something to chain. The loop wraps the EXISTING executor + dispatch_turn; it must NOT change the autonomy gate.

Constitutional carry-forward (NON-NEGOTIABLE — ADR-033 inscribes; the impl must enforce; verify it does):
- The loop is CODE-DRIVEN. The loop condition ("did this pass append a new TOOL_CALL, and are we under the bound N / under the wall-clock deadline?") is pure driver code. NO LLM judges "should I loop again." The LLM only generates content WITHIN each dispatched pass.
- Every pass routes the UNCHANGED gate. Each pass's tool calls go through the unchanged process_tool_calls → gate → TOOL_CALL (AUTO_EXECUTE only). The executor's "execute-on-TOOL_CALL-only" (t4) holds PER PASS. A COUNTDOWN/HARD call in a pass appends TOOL_CALL_PENDING (no TOOL_CALL) → NOT executed in-loop → out-of-band confirm flow; the loop does NOT wait for human confirm.
- No new LLMPurpose (still AGENT_RESPONSE), no new EventType. snapshot_excerpt is context fed to the existing prompt, not a new purpose.
- Single-writer preserved + BOUNDED. The loop stays inline on the single-writer thread (ThreadPoolExecutor max_workers=1, which serializes ALL rooms' writes). The block is (1+N)× the per-pass block, further capped by an absolute wall-clock deadline.
- B2 = read-only, IN-PROCESS (os.walk + re; NO subprocess/grep/rg/git-grep/language-server), SANDBOXED (reuse the ADR-028 D3 sandbox-root + _check_path), bounded output + bounded traversal, TRUSTED → NOT interpreted (no OBSERVATION).

The design (ADR-033 — verify against the invariants + for runtime correctness):
- D1 SHAPE: bounded-loop. After the initial turn (pass 0 = run_turn + execute_pending_tool_calls), the driver re-dispatches ≤ N times. N = MAX_TURN_LOOP_PASSES = 4 (documented constant). Total dispatch_turn invocations ≤ 1+N = 5.
- D2 WHAT RE-DISPATCHES: passes 1..N call dispatch_turn DIRECTLY (not run_turn), so the state machine (next_room_state) runs ONCE per turn (pass 0) — avoids a duplicate state_transition. Filtered agents come from a behavior-preserving extraction select_dispatch_agents (factored out of run_turn). current_event for pass k = the LATEST result-class event (TOOL_RESULT/TOOL_FAILED/OBSERVATION) of pass k-1 — the TRIGGER the agent reacts to. snapshot_excerpt = the bounded accumulated CONTEXT (see D6).
- D3 TERMINATION (any of): (1) zero new TOOL_CALL appended by the pass; (2) no new result-class event to react to; (3) N passes; (4) the WALL-CLOCK DEADLINE MAX_TURN_LOOP_WALL_CLOCK_S = 120.0s — stamped loop_start = time.monotonic() before pass 0, checked AT EACH PASS BOUNDARY (exit if monotonic()-loop_start >= deadline). Checked between passes, NOT mid-pass (no async cancellation of an in-flight LLM call), so absolute wall-clock <= deadline + one final pass overrun.
- D4 LIVENESS BOUND (enumerated with ADR-028 D5 rigor): worst-case single-writer block per turn <= (1+N) × [ (speaking agents) × (provider timeout_s) + the ADR-028 D5 per-pass execution bound ]. Dominant term: agents × provider timeout_s, where provider timeout_s is up to 600.0s (claude_code_cli, asyncio.wait_for) / 60.0s (openai_compatible, httpx). This is a CROSS-ROOM head-of-line block (the single writer serializes all rooms). The wall-clock deadline (D3.4) bounds the ABSOLUTE wall-clock independent of that product. Per-pass cap reconciliation: the executor's MAX_MCP_CALLS_PER_TURN / MAX_POSTURE_B_CALLS_PER_TURN are per-invocation counters → reset PER PASS → total <= (1+N)× the cap. Cooldown: chaining requires cooldown_seconds=0 (a >0-cooldown agent re-speaks at most once in the sub-second loop); termination is INDEPENDENT of cooldown.
- D5 B2 TOOLS + log_event + the INVESTIGATOR AGENT: in-process search_text/search_code/find_references/find_definition + log_event (a write that lands as a TOOL_RESULT — no event_store handle given to the tool fn, no new EventType). Reuse the ADR-028 D3 sandbox + a NEW MAX_SEARCH_FILES traversal cap. A minimal cooldown_seconds=0 investigator agent (config/agents/investigator.yaml; user_input + tool_result triggers) is bundled so the chain runs LIVE on landing (the existing operator at cooldown_seconds:10 cannot chain).
- D6 CONSTITUTION + the ADR-011 AMENDMENT: snapshot-per-turn extended to snapshot-per-pass; AND snapshot_excerpt is added to AgentContext, populated in build_agent_context (bounded by MAX_SNAPSHOT_EXCERPT_CHARS), and fed into the dispatch_turn LLM prompt — resolving the P1.4 deferral. Additive: no new LLMPurpose/EventType, no live read.

Your lens — OVER-CORRECT for Claude biases; this is the highest-value part. The architect named TWO focus surfaces:

(A) LIVENESS / TERMINATION (the prime probe — the class the P1.4 DeepSeek pass caught and the in-family pass under-weights):
- Is the enumerated bound the ACTUAL bound? Trace a worst case: N=4 re-dispatches × (speaking agents) × (a claude_code_cli pass at timeout_s=600s) — is the (1+N) multiplier real, and does it block EVERY room (cross-room head-of-line) for that whole duration, not just this room? Is "inline on the single writer" actually inline (no offload)?
- Does the WALL-CLOCK DEADLINE actually fire? Is it a real check (time.monotonic() at each pass boundary, before starting a re-dispatch) or a comment? Can an IN-FLIGHT pass overrun the deadline UNBOUNDEDLY (no mid-pass cancel) — is the "deadline + one final pass" honesty actually what the code guarantees, or can a single pass itself be unbounded (a local tool that blocks; an un-timed call)? Is loop_start stamped before pass 0 (so the deadline covers the whole turn) or only before the loop?
- Can the loop FAIL TO TERMINATE? If the LLM re-emits the same tool call with a NEW call_id each pass (the executor's double-exec guard skips by call_id — does a fresh call_id defeat it, re-executing the same read N times?) — is that bounded by N, or can it spin? If a pass appends a TOOL_CALL but the executor skips it (dup) so NO new result lands — does condition (2) "no new result-class event" actually fire, or does the driver pass a STALE current_event and loop on it? Does any path re-enter the loop without incrementing the pass counter?
- Per-pass cap interaction: the executor's per-turn MCP/Posture-B caps reset per pass. Can a 5-pass loop therefore run 5×10 = 50 MCP calls — is that the intended bound, and is it still absolutely bounded? Does the loop interact with the executor's full-room double-exec scan (O(room events) per pass) to make the per-pass cost grow with the loop (re-scanning a growing log each pass)?
- Cross-room starvation: while room A runs a 5-pass loop, rooms B/C/D cannot write. Is this acceptable as implemented, and does the wall-clock deadline actually cap the starvation window?

(B) snapshot_excerpt PROMPT-ASSEMBLY (the second named surface — constitutional + bounding):
- NEW PURPOSE / EVENT TYPE: does feeding snapshot_excerpt introduce a new LLMPurpose (must stay AGENT_RESPONSE) or a new EventType? Grep the LLMRequest construction — is the purpose unchanged?
- LIVE READ: does build_agent_context read the event store directly (event_store.get_room_events / any I/O) to build the excerpt, or does it use ONLY the passed per-pass snapshot? A live read would break the per-pass snapshot invariant (ADR-011 D2/D5: should_agent_speak + context must read the SAME snapshot). Verify the excerpt is sourced from the snapshot param, not a fresh read.
- BOUNDED: is the excerpt actually capped at MAX_SNAPSHOT_EXCERPT_CHARS (a documented constant)? Can a long accumulated investigation (many large read_file results across passes) blow the context window / cost — is the cap applied to the RENDERED bytes before they hit the prompt? Is the most-recent slice chosen (so the agent sees the latest, not an arbitrary truncation)?
- UNTRUSTED-RESULT INJECTION: the excerpt renders recent events INCLUDING tool results. Local results are trusted; but MCP results / OBSERVATIONs are untrusted-provenance. Feeding them into the agent's prompt — can a prompt-injection in a tool result steer the agent to emit a tool call it otherwise wouldn't? Note the gate STILL routes every emitted call (so injection cannot bypass the gate) — but probe whether the excerpt's framing (or lack of it) lets injected text masquerade as instructions. Is this materially different from the agent seeing the same event on the next turn anyway?
- RECONCILIATION: current_event (the trigger) vs snapshot_excerpt (the context) — is the agent's reaction coherent (it speaks because of the trigger; it reasons over the excerpt)? Does the excerpt DUPLICATE current_event.content (the latest result appears both as trigger and in the excerpt) in a confusing way?

Also verify (carry-forward, lower-novelty but load-bearing):
- GATE-PER-PASS UNCHANGED: is process_tool_calls / the gate genuinely untouched? Does any pass re-gate or read a tier from anywhere but the gate's TOOL_CALL event? Is a COUNTDOWN/HARD pass correctly terminating the loop (TOOL_CALL_PENDING, no TOOL_CALL) without executing or human-blocking?
- B2 IN-PROCESS + SANDBOX: do search_*/find_* use os.walk+re only (NO subprocess/Popen/os.system/grep/git)? Does _check_path contain the scope param (../ , absolute, symlink escape → TOOL_FAILED)? Is the traversal capped (MAX_SEARCH_FILES) and each file read bounded (no full multi-GB read)? Is output byte-capped?
- log_event: does it land as a TOOL_RESULT via the local path WITHOUT an event_store handle and WITHOUT a new EventType? Over the N-pass loop, is the bloat the only cost (no liveness hit, since it's a pure local tool)?
- INVESTIGATOR AGENT: can config/agents/investigator.yaml (cooldown_seconds=0, tool_result trigger) speak-loop OUTSIDE the bounded loop (on normal turns), or is tool_result only the current_event during in-turn re-dispatch (a fresh user turn anchors on user_input)?
- Over-engineering / missed-simpler; sycophancy where the ADR/senior writes "bounded" / "absolute" / "unchanged" / "trusted-not-interpreted".

NOT IN SCOPE to re-raise (architect-decided / ratified — probe whether IMPLEMENTED safely, do NOT relitigate the choice):
- The bounded-loop SHAPE + N=4 (architect §(a) ruling); the 120s wall-clock-deadline VALUE; log_event INCLUDED (rev-8 triviality accepted, no per-pass write-cap this cycle); snapshot_excerpt BUNDLED (Y3); the minimal investigator agent BUNDLED (Y2); single-lens→dual-lens flip itself. The gate decision logic (score/decide_tier/process_tool_calls — unchanged); the deferred heavier tools (subprocess B3 / network B4 / mutation B5); a separate execution lane (ADR-028 D5 — deferred; probe whether the inline bound HOLDS, not whether to choose a lane).

MANDATORY OUTPUT FORMAT:

---
task_id: P4.1
round: R0-B-cross-family
reviewer_family: <deepseek | gpt-5 | gemini | other>
reviewer_model_id: <specific model>
reviews_acked:
  - decisions/ADR-033-agent-turn-loop.md
  - process/senior-plans/P4.1.md
  - the claude/P4.1-impl commits P4.1-1..8
verdict: <clean | needs_architect | blocking>
findings_count:
  red: N
  yellow: N
  green: N
---

# P4.1 R0-B cross-family review (turn-loop + code-intel tools)

[Body — markdown; per-finding 🔴 blocking / 🟡 should-fix / 🟢 confirmation; each: id, location (file:line or artifact), what, why-it-matters, recommended routing (α absorb / β defer / γ reject). Then a 1-paragraph net assessment + verdict.]

Verdict semantics: clean = 0🔴/0🟡 → architect proceeds to ADR-033 Accept + merge. needs_architect = ≥1🟡 OR an issue needing routing. blocking = ≥1🔴 (design/impl-breaking) → revise before merge.

Style: terse, technical, direct. Severity icons, no flowery language, no apologies for skepticism. Aim for 5-12 findings — quality over quantity. The LIVENESS (is the (1+N)×agents×600s cross-room bound real + does the wall-clock deadline actually fire + can the loop fail to terminate) and the snapshot_excerpt (new-purpose / live-read / unbounded / injection) probes are the highest value — they are exactly what an in-family pass misses (the P1.4 DeepSeek liveness precedent). An honest `clean` from cross-family is high-trust signal. Treat the paths / prior decisions / RC numbers in this prompt as authoritative.
```

---

## Artifact bundle — read from disk (in-repo dispatch)

Read in full:
1. `docs/decisions/ADR-033-agent-turn-loop.md` — the design (Proposed; D1 shape/N · D2 trigger+context · D3 termination incl. wall-clock deadline · D4 enumerated liveness · D5 B2 tools + investigator · D6 constitution + ADR-011 amendment).
2. `docs/process/senior-plans/P4.1.md` — the plan (8 atomics P4.1-1..8 + the §5 dual-lens rationale).
3. `docs/decisions/ADR-028-runtime-tool-executor.md` (D3/D4/D5 — the amended sections + the bound D4 extends) + `docs/decisions/ADR-011-multi-agent-dispatch-sequential.md` (the snapshot-per-pass + snapshot_excerpt amendment note).
4. The impl on `claude/P4.1-impl` (commits `P4.1-1..8`): `api/app.py::_write_and_turn` (the loop + the 120s deadline), `rooms/runtime.py` (`select_dispatch_agents` extraction), `agents/dispatch.py` + `agents/selection.py` + `agents/schema.py` (the `snapshot_excerpt` field/population/feed), `tools/local.py` (the B2 impls + `log_event`), `config/agents/investigator.yaml`, `tests/{integration,tools,agents}/`.

Plus live source on `main`/the impl branch when probing claims:
- `src/orchestrator/agents/dispatch.py:112,116` (the LLM prompt = current_event.content + system; the un-inline-timeout llm_router.call) + `agents/selection.py:99` (the `_ = snapshot` the amendment resolves) + `agents/speaking.py:71` (the cooldown gate).
- `src/orchestrator/providers/claude_code_cli.py:84` (`timeout_s=600.0`) + `providers/openai_compatible.py:67` (`timeout_s=60.0`) — the D4 dominant-term magnitude.
- `src/orchestrator/api/app.py:171` (`ThreadPoolExecutor(max_workers=1)` — the single writer) + `:389-400` (the existing window/publish the loop wraps).
- `src/orchestrator/tools/executor.py:98,111` (execute-on-TOOL_CALL-only filter; the per-invocation MCP cap counter that resets per pass) + `agents/tool_dispatch.py` (`process_tool_calls` — TOOL_CALL for AUTO_EXECUTE only; verify unchanged).
- `src/orchestrator/core/event.py:84,97` (`TOOL_CALL`/`TOOL_CALL_PENDING` already exist; verify NO new EventType) + `llm/purposes.py` (`AGENT_RESPONSE`; verify no new purpose).
- The P1.4 cross-family precedent (`docs/process/reviews/P1.4/…`) — the liveness / `event_store.append` class the DeepSeek lens caught.

(For an external web-session dispatch — GPT/Gemini — paste the doc files + these source files after the system prompt.)

---

## Notes for architect-partner reviewing the returned external R0-B output

1. **Save as** `docs/process/reviews/P4.1/R0-B-cross-family.md` (no `-external` suffix needed — single dispatch).
2. Frontmatter preserved verbatim; `reviews_acked` verified against the artifacts + the `P4.1-1..8` commits.
3. **Highest-value contradictions to watch**: (a) a **liveness hole** — the wall-clock deadline not actually firing (a comment, or an in-flight pass that overruns unboundedly), or the loop failing to terminate (fresh call_id defeating the double-exec guard → re-execution spin; a stale current_event loop); (b) **cross-room starvation** worse than the bound claims; (c) a **new purpose / event-type / live read** snuck in via snapshot_excerpt; (d) an **unbounded excerpt** (cap not applied to rendered bytes) or an **untrusted-result injection** path; (e) **gate drift** — a pass re-gating or executing a non-`TOOL_CALL`. Route any; send to the P4.1 retro.
4. Per RC-20: note whether the external lens **corrects** an in-family finding (the liveness magnitude — R0-A-on-plan's Y1 was in-family; does cross-family deepen or refute it?) vs only adds net-new.
5. If `verdict: clean` + no new 🔴/🟡 (with the impl-stage R0-A also clean): architect proceeds to ADR-033 Accept + the ADR-028/011 amendments + the P4.1 merge. If new 🔴/🟡: architect routes via `architect-routing.md`; senior absorbs via `awaiting_senior_revision`; verdicts bump per RC-10.
6. The dual-lens is dispatched precisely because the in-family pass structurally under-probes **liveness arithmetic** + **cross-room concurrency** (the P1.4 DeepSeek precedent) — the two surfaces the R0-A-on-plan absorption widened the slice into.
