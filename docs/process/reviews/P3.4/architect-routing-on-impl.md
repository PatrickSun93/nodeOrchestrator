---
task_id: P3.4
kind: architect-routing
stage: impl
date: 2026-06-02
reviews_acked:
  - R0-A.md                # architect-partner in-family + plant-bypass (clean 0R/0Y/14G on spine/trust; CONCEDED Y2 post-R0-B)
  - R0-B-cross-family.md   # deepseek cross-family, impl-stage section (needs_architect 0R/1Y/6G — caught Y2)
  - plan-vs-impl.md        # senior (clean 0R/0Y/8G — missed Y2)
joint_verdict: needs_architect (impl-stage; R0-B caught Y2, R0-A conceded it, senior clean) → Y2 α wire-now
decisions:
  Y2: α wire-now — build the general runtime tool-executor into the event loop (MCP + local; TOOL_CALL → execute → TOOL_RESULT/TOOL_FAILED); confirm-then-execute stays deferred per plan §5. Implementation PATH assessed separately (architect-partner recommends an ADR + senior design note first — see the report; this artifact records the α call + scope).
---

# P3.4 architect routing — impl stage (Y2 → α wire-now; spine/trust 3-lens clean)

**Architect decision (this session):** the impl-stage is **3-lens**. The constitutional spine + trust boundary are **clean, confirmed by all three** (R0-A G1–G14 + R0-B impl-stage G1–G6 + senior plan-vs-impl): MCP feeds the **unchanged** gate (AST-enforced no-decision-in-`mcp/`); discovery≠permission; server hints don't change the tier; execution-downstream-of-gate structural; env-leak prevented (the c2 lesson, secret-injection-tested); both routed plan-stage α's landed + tested. **One 🟡 — Y2 — routed α wire-now.**

## The finding + the basis (why needs_architect)

**Y2 🟡 (scope/completeness, NOT constitutional):** `execute_mcp_tool_call` + `interpret_mcp_tool_result` are defined, correct, and tested (mocked transport + direct calls) — but **never called from the runtime**. `app.py` merges the MCP `ToolMeta` registry at bootstrap but adds **no consumer** for `TOOL_CALL` events. So an MCP tool gets **gated** (AUTO → `TOOL_CALL` event) but **never executed** in the living app.

**Lens basis (joint needs_architect):**
- **R0-B cross-family (impl-stage): caught Y2** — traced the runtime call path (its specialty), found no call site (`needs_architect` 0🔴/1🟡/6🟢).
- **R0-A architect-partner: CONCEDED Y2** — clean (0🔴/0🟡/14🟢) on the spine/trust/plant-bypass axes it checked, but **verified R0-B's Y2 independently** (grep: zero call sites in `src/`) and conceded the miss (the "function exists → assumed integrated" bias; the cross-family lens's runtime-integration specialty — RC-20).
- **senior plan-vs-impl: clean** (0🔴/0🟡/8🟢) — verified plan-faithfulness, also missed the runtime-wiring gap.
- Net: post-concession, R0-A + R0-B **converge on needs_architect** (Y2); the senior was clean. The dual-lens earned its keep on P3's heaviest slice.

## The decision — Y2 → α wire-now

**Scope (architect-ruled):** build the **general runtime tool-executor** into the event loop — **MCP + local tools** — consuming `TOOL_CALL` events → execute → append `TOOL_RESULT`/`TOOL_FAILED`. **confirm-then-execute stays deferred** (plan §5; `COUNTDOWN`/`HARD` remain gated-not-executed until a confirm flow lands with the GUI work). Also de-claim the handoff's "AUTO_EXECUTE 执行" until the runtime executor exists.

## Implementation path — assessed separately (architect orchestrates)

The architect asked for a path recommendation (direct-junior / senior-design / ADR-revision) before orchestrating. **Key determination (this artifact records the pointer; the reasoning is in the architect-partner report):** this is the **first runtime tool-executor**, and **ADR-013 explicitly "does not govern tool execution itself (P1.6+)"** — so the executor is *beyond* the current ADR envelope, not within it. It introduces a new event-loop stage, failure semantics (`TOOL_FAILED` → turn continuation), a tool-result → agent-re-dispatch loop (event-model / ADR-011 territory), sync/async + the P3.2 single-writer-executor liveness interaction, and a **local-tool-scope** question (no local-tool implementations or executor exist today — ADR-003 makes the orchestrator the intended "tool execution layer" for openai_compatible providers, but it's unbuilt). **Architect-partner recommendation: a new ADR (e.g. ADR-028 runtime tool-executor) + a senior design note FIRST, then junior — likely with a dual-lens R0-B** (the runtime/concurrency/failure surface — the same class the impl-stage R0-B just caught). NOT directly-junior; a senior-design-note-alone (no ADR) would leave the first runtime-executor's architecture un-inscribed. See the report for the full reasoning + orchestration options.

## The rest — 3-lens clean (no action)

Spine + trust boundary verified by all three lenses (above + R0-A G1–G14 / R0-B G1–G6). Both plan-stage α's (r0b-Y1 timeout: `asyncio.wait_for` + subprocess-kill-no-orphan + hanging-mock test; arch-Y1 AUTO-only) landed + tested. ADR-027 governs the MCP client/gating/trust; the runtime-executor ADR (above) governs the new execution stage. No spine/trust rework — Y2 is purely the runtime glue + its (newly-needed) architectural inscription.

## Senior/next-slice scope (literal-reading)

Y2 → α wire-now is a **new architectural increment**, not an in-cycle patch: it needs an **ADR (runtime tool-executor) + a senior design note** (the execution-stage placement, MCP-executor-wired + local-tool-impls-deferred, failure/re-dispatch semantics, sync/async + P3.2-liveness; confirm-then-execute stays §5-deferred), then junior, then reviews (likely dual-lens). The architect orchestrates whether P3.4 closes first (MCP client + gating + the executor *function* shipped; the runtime-wiring is the follow-up slice) or stays open for it. Bump the impl-stage verdicts per RC-10 once the path is set.
