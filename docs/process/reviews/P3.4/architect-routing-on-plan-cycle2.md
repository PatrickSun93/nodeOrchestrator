---
task_id: P3.4
kind: architect-routing
stage: plan
cycle: 2
date: 2026-06-03
actor: architect (Peidong) — routed via the orchestrator session
reviews_acked:
  - R0-B-cross-family-on-plan-cycle2.md   # deepseek cross-family, plan-stage (blocking 1🔴/4🟡/5🟢 — caught R1 interpret-liveness)
  - R0-A-on-plan-cycle2.md                # architect-partner in-family (needs_architect 0🔴/2🟡/7🟢 — spine structural-clean; 2🟡 on the net-new local FS surface)
joint_verdict: needs_architect (plan-stage; R0-B blocking on R1, R0-A needs_architect on 2🟡) → R1 α MUST-FIX + all 🟡 α-absorb + 4 §5 calls confirmed
decisions:
  R1: α MUST-FIX — bounded timeout on the MCP interpret LLM call (asyncio.wait_for / run_in_executor+deadline); on timeout → keep the raw TOOL_RESULT, skip interpret (content-gen is advisory). ADR-028 D5 liveness bound becomes Σ(MCP-call timeouts + bounded-interpret timeouts), per-turn-capped.
  R0B-Y1: α — double-execution guard scope = FULL room history scan by call_id (not the post-cursor window); LLM-generated call_ids can collide cross-turn. Inscribe in ADR-028 D2 with rationale.
  R0B-Y4: α — document a per-turn MCP AUTO tool-call cap; bound the Σ-liveness in ADR-028 D5.
  R0A-Y1: α-fold into C2-2 — read_file reads AT MOST MAX_RESULT_BYTES(+1) bytes (bounded read, not read-all-then-truncate); + acceptance criterion + §3 large-file no-OOM test.
  R0B-Y2_R0A-Y2: α-lite — ADR-028 D3 states the local-FS threat model (untrusted = the LLM-proposed path param; the sandbox root is a trusted workspace; resolve→open TOCTOU is out-of-MVP-scope; no O_NOFOLLOW/fd-re-validate in the MVP).
  R0B-Y3: α-lite — ADR-028 D6 t4 reworded: input-boundary STRUCTURAL (sole TOOL_CALL appender → the executor's input window can only hold gate-approved events) + executor-internal BEHAVIORAL filter (keys on EventType.TOOL_CALL), backed by the C2-4 behavioral test. NOT a type-level invariant.
  S5-1: confirm — local-tool MVP breadth = {get_current_time, read_file, list_files} + sandbox (the architect's pre-set line; R0-A noted convergence).
  S5-2: confirm — keep deferred-but-classified tools classified + fail-closed (not_implemented); + the executor's MCP session lookup uses mcp_sessions.get(server) → explicit not_available, never a bare KeyError.
  S5-3: confirm-defer — no-re-dispatch MVP (agent reacts on the next turn); in-turn re-dispatch is deferred ADR-011 work.
  S5-4: accept — inline-on-the-single-writer liveness posture; now made genuinely bounded by R1 (interpret-timeout) + R0B-Y4 (per-turn cap).
adr_status: ADR-028 stays Proposed (RC-23-safe) — architect Accepts after verifying this absorption.
---

# P3.4 cycle-2 architect routing — plan stage (R1 α MUST-FIX + all 🟡 α-absorb)

**Architect decision (2026-06-03, routed via the orchestrator session).** The cycle-2 plan-stage is **dual-lens**: R0-B-cross-family-on-plan (DeepSeek, **blocking** 1🔴/4🟡/5🟢) + R0-A-on-plan (architect-partner, **needs_architect** 0🔴/2🟡/7🟢). The **constitutional carry-forward spine is structural-clean, confirmed by both** (R0-A G1–G7 traced it structural against the impl-branch source + live constitution tests; R0-B G1/G4 confirmed autonomy-bypass fail-closed + the empty gate diff). The blocking 🔴 + all six 🟡 route **α** (absorb); the four §5 calls are **confirmed**. This artifact records the routing; the senior absorbs (it does not re-route).

## The 🔴 — R1 → α MUST-FIX (the liveness contradiction)

**R0-B R1 (🔴 blocking):** the MCP interpret LLM call (`agents/mcp_interpret.py:39`, `llm_router.call(request)`) has **no timeout** and the cycle-2 executor calls it **inline on the single writer** (D5). An LLM hang → all room writes blocked **indefinitely** → contradicts ADR-028 D5's "bounded" claim (the real bound was Σ(MCP timeouts + *unbounded* LLM calls)). A flaky LLM takes down the orchestrator.

**Routing — α MUST-FIX:** wrap the interpret in a **bounded timeout** (reuse the cycle-1 pattern — `asyncio.wait_for`, or `run_in_executor` with a deadline). On timeout → **keep the raw `TOOL_RESULT`, skip the interpret** (the interpretation is advisory content-gen — its absence is acceptable; the `TOOL_RESULT` stands alone, no `OBSERVATION`). Absorb into: **ADR-028 D5** (the liveness bound is now Σ(MCP-call timeouts + bounded-interpret timeouts), and per-turn-capped — R0B-Y4), **C2-1 acceptance criteria** (interpret runs under a bounded deadline; timeout → raw result stands, writer not blocked beyond the bound), and **plan §3 / §4 test-coverage** (a failure-mode test: interpret hangs → bounded → raw `TOOL_RESULT` persisted, the writer is not blocked indefinitely). This is the **same error class** as the cycle-1 R0-B Y1 (an unbounded blocking dependency on the single writer), one layer up — the cross-family lens earned its keep again.

## The 🟡 — all α-absorb (per reviewer lean)

- **R0-B Y1 (double-exec guard scope) → α.** Pin the guard to a **full room-history scan by `call_id`** (`event_store.get_room_events(room_id)`), not the post-cursor window. Rationale (inscribe in **ADR-028 D2**): the **LLM** (not the system) generates `call_id`s, so a duplicate can appear cross-turn / cross-window; a window-only check would miss a prior-turn collision. The scan cost is acceptable under the inline single-writer; the guard is race-free there (R0-A G5). Forward-watch (R0-A §3): if the deferred separate-execution-lane (D5) ever lands, the check-then-execute guard must become an atomic claim — that slice owns it.
- **R0-B Y4 (Σ-liveness cap) → α.** Document a **per-turn MCP AUTO tool-call cap** in **ADR-028 D5**; MCP `TOOL_CALL`s beyond the cap fail-closed (`TOOL_FAILED`, not executed). This makes the per-turn writer block **absolutely** bounded (cap × (MCP-call timeout + interpret timeout)), not merely Σ-bounded-per-call.
- **R0-A Y1 (read-cap-on-READ) → α-fold into C2-2.** `read_file` must read **at most `MAX_RESULT_BYTES (+1)` bytes** — a **bounded read**, not read-the-whole-file-then-truncate. Else a multi-GB in-sandbox file + an LLM-proposed `read_file(path=…)` OOMs the single `max_workers=1` writer → the whole process dies (every room). No adversary needed. Sharpen the C2-2 acceptance criterion ("oversized file → reads at most the cap, never loads the whole file") + add a §3 failure-mode test (oversized file → bounded read, not OOM). Cross-family DoS class — bake in now.
- **R0-A Y2 / R0-B Y2 (local-FS threat model) → α-lite.** Add one sentence to **ADR-028 D3**: the **untrusted input is the LLM-proposed `path` parameter**; the **sandbox root is a trusted workspace dir**; the **resolve→open TOCTOU** window (a concurrent on-disk process swapping a symlink between the containment check and the open) is **out of the MVP threat model** — no `O_NOFOLLOW` / post-open fd re-validation in the MVP (the inline single-writer makes the window near-nil). So the mandatory dual-lens evaluates a **known posture**, mirroring how D5 flags the liveness posture. (R0-A offered δ-watch as the alternative; architect chose α-lite — inscribe it.)
- **R0-B Y3 (t4 "structural" overstated) → α-lite.** Reword **ADR-028 D6 t4**: the downstream-of-gate guarantee is **input-boundary structural** (`EventType.TOOL_CALL` has exactly **one** appender — `process_tool_calls`, AUTO_EXECUTE-only — so the executor's input window can only contain gate-approved records; AST/grep-verifiable on the *producer* side) **plus** an **executor-internal behavioral filter** (the executor filters its input to `EventType.TOOL_CALL` — a runtime `if`, not a type-level invariant), **backed by the C2-4 behavioral test** (no `TOOL_CALL` in window → no execution). The combination — not the type system — is the guarantee. Name it accurately; don't claim a type-level invariant.

## The §5 calls — confirmed (architect)

1. **Breadth (§5 #1):** **confirm** `{get_current_time, read_file, list_files}` + sandbox — the architect's pre-set line; R0-A noted the senior independently converged on it. No change.
2. **`not_implemented` seam (§5 #2):** **confirm** keep deferred-but-classified tools classified + fail-closed (no `tools.yaml` churn; honest failure ≻ silent no-op). **Plus** (R0-A G7 nit, now binding): the executor's MCP session lookup uses `mcp_sessions.get(server)` → explicit `TOOL_FAILED(error_class="not_available")`, **never** a bare `KeyError`.
3. **No-re-dispatch (§5 #3 / D4):** **confirm the deferral** — agent reacts to a result on the next turn; in-turn re-dispatch is additive ADR-011 work (loop-bounding + liveness cost) for a later slice.
4. **Inline liveness (§5 #4 / D5):** **accept the posture for the MVP** — and note it is now made genuinely **bounded** by R1 (interpret-timeout) + R0B-Y4 (per-turn cap). This is the surface the mandatory impl-stage dual-lens R0-B will re-probe.

## Out of scope for this routing (no re-litigation)

- The 5🟢 (R0-B) + 7🟢 (R0-A) confirmations — autonomy-bypass fail-closed, session-retention safe, `not_implemented` honest, empty gate diff, leaf placement, plant-bypass, local-breadth conservative — stay confirmed.
- The architect-ruled cycle-2 frame: build-local-impls-now (decision #1), stay-open cycle-2 / PR #48 accumulates, RC-10 verdict-bump of the **cycle-1** impl-stage reviews deferred to cycle-2 close.
- The two R0-A forward-watches (double-exec-guard-↔-future-lane; windowed-consumption stranding a `TOOL_CALL` from a turn that raised after append) — fail-closed, MVP-acceptable; carried as watch items, not cycle-2 inscriptions (one-line note added to the plan).

## Next

Senior absorbs R1 + the six 🟡 into ADR-028 (D2/D3/D5/D6) + `P3.4-cycle2.md` (C2-1/C2-2 acceptance + §3/§4 tests + §5 resolved-note), bumps both review verdicts per RC-10 (R0-B blocking→clean; R0-A needs_architect→clean). ADR-028 stays **Proposed**. Architect verifies the absorption, then Accepts ADR-028 → junior implements C2-1..C2-4 on `claude/P3.4-impl` → **mandatory impl-stage dual-lens R0-B** re-probes the interpret-timeout + read-bound + sandbox TOCTOU posture + the D5 liveness block.

## Cross-references

- `docs/process/reviews/P3.4/R0-B-cross-family-on-plan-cycle2.md` (R1 + 4🟡 + 5🟢; lean source).
- `docs/process/reviews/P3.4/R0-A-on-plan-cycle2.md` (2🟡 + 7🟢; spine structural-clean; the §5 leans).
- `docs/decisions/ADR-028-runtime-tool-executor.md` (D2/D3/D5/D6 — the absorption target; stays Proposed).
- `docs/process/senior-plans/P3.4-cycle2.md` (C2-1/C2-2 acceptance + §3/§4 + §5 resolved-note).
- `docs/process/reviews/P3.4/architect-routing-on-impl.md` (the cycle-1 impl-stage routing — Y2 → α wire-now; decision #1 build-local-impls-now).
