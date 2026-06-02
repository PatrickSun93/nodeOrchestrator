---
task_id: P3.4
kind: architect-routing
stage: plan
date: 2026-06-02
reviews_acked:
  - R0-A-on-plan.md       # architect-partner in-family, single-lens (needs_architect 0R/1Y/13G)
  - R0-B-cross-family.md  # deepseek cross-family, dual-lens (needs_architect 0R/1Y/7G)
joint_verdict: needs_architect (dual-lens plan-stage; 0🔴 / 2🟡 / spine+trust-boundary 2-way clean) → both α
decisions:
  r0b_Y1: α (must-fix) — pin the sync-over-async timeout mechanism (asyncio.wait_for wrap + kill+wait subprocess + hanging-mock test) in ADR-027 D1; realizes HR#10 hang→fail-closed
  arch_Y1: α-lite-fold — clarify MVP executes AUTO_EXECUTE only (COUNTDOWN/HARD gated-not-executed); confirm-then-execute is GUI-coupled, deferred; in plan §5 + ADR-027 D6/HR#4
---

# P3.4 architect routing — plan stage (both 🟡 → α; spine + trust boundary 2-way clean)

**Architect decision (this session):** the dual-lens plan-stage review is **clean on the entire constitutional spine + trust boundary, 2-way confirmed** (R0-A G1–G13 + R0-B G1–G7): MCP feeds the **unchanged** code gate (registry merge; gate decision logic untouched + a constitution test); discovery≠permission (pre-classify allowlist; unclassified→`UnknownToolError`→refused); the server can't influence the tier (reversibility code-classified; hints advisory); execution-downstream-of-gate is structural; and the c2 env-inheritance lesson is explicitly applied (R0-B confirms it's the exact S3 catch, same structural fix). **Two 🟡 — non-overlapping, different axes — both routed α.** No ADR-027 design reversal; D-decisions stand, refined.

This is the **signal artifact for the senior revision session.** Senior absorbs both below into the plan + ADR-027, then **bumps BOTH plan-stage verdicts per RC-10** (R0-A-on-plan + R0-B-cross-family → clean). Then the architect accepts ADR-027 → P3.4 impl.

## Per-finding routing

### r0b Y1 → α (must-fix) — pin the sync-over-async bridge timeout mechanism (realizes HR#10 hang→fail-closed)

**Finding (R0-B Y1, 🟡):** the sync-over-async bridge timeout mechanism is underspecified. The cited P3.2 `llm_adapter` precedent's timeout is the HTTP client's **internal** timeout (not bridge-enforced) — a stdio subprocess has no such fallback. A malicious/broken MCP server that hangs (`tools/list` never responds, `tools/call` indefinite read) would **block the orchestrator's sync thread indefinitely** if the bridge uses `run_until_complete` without an explicit timeout. This is a reliability/DoS hole on the trust boundary (a malicious server weaponizes the hang). The cross-family lens's runtime-failure specialty (P1.4 / P2.7-S3 precedent).

**Action (senior absorb — ADR-027 D1; no design change):**
1. The bridge **wraps all MCP SDK calls in `asyncio.wait_for()`** with a configurable timeout (connect + every `tools/list`/`tools/call`) — the explicit bridge-level timeout (not relying on an internal client timeout that stdio lacks).
2. **On timeout, the subprocess is `.kill()`ed + `.wait()`ed** (no orphaned process) and the tool-call fails closed (`TOOL_FAILED`).
3. **Test with a deliberately-hanging mock server** (asserts the timeout fires + the orchestrator does not block + the subprocess is reaped).

This **realizes HR#10's "hang → fail-closed"** (the boundary is inscribed; this pins the mechanism that enforces it). Folds into ADR-027 D1 (the sync-bridge) + the §8-§3 failure-mode tests. No design reversal.

### arch Y1 → α-lite-fold — clarify MVP is AUTO_EXECUTE-only; defer confirm-then-execute (GUI-coupled)

**Finding (R0-A Y1, 🟡 medium-low):** plan §5 + ADR-027 D6/HR#4 reference a "post-user-confirm" execution path that **does not exist** (no flow consumes a user-confirm to append a `TOOL_CALL`; the snapshot's `tool_calls_pending_confirm` only tracks). So the MVP executes `AUTO_EXECUTE` only; `COUNTDOWN`/`HARD` MCP tools are gated-and-not-executed. Constitutionally fine — but the wording implies a working path that isn't there.

**Action (senior absorb — plan §5 + ADR-027 D6/HR#4; clarification, no design change):** state that **MVP execution = `AUTO_EXECUTE` only**; `COUNTDOWN`/`HARD` MCP tools are **correctly gated-and-not-executed** (that *is* the constitutional demonstration); the **user-confirm → `TOOL_CALL` → execute** flow **does not exist yet and is GUI-coupled** (the snapshot's `tool_calls_pending_confirm` + handoff §899's `COUNTDOWN_CONFIRM` UI contract) → **deferred to the subsequent GUI work**. The **e2e demonstrates AUTO-executes + HARD-gated-not-executed** (not confirm-then-execute). Correct the "post-user-confirm" wording in D6/HR#4 to reflect the deferral. *(This traces partly to the brief's wording — a shared clarification, not a senior miss.)*

## The two are independent (no overlap)

r0b Y1 is the **transport-bridge timeout** (a runtime/reliability-security mechanism); arch Y1 is the **gate→execution scope** (which tiers execute in the MVP). Different layers; each is fixed independently. (R0-A's earlier *W-c* watch-item touched the timeout area — r0b Y1 sharpened that watch-item, not arch Y1.)

## The rest — clean, 2-way confirmed (no action)

The constitutional spine + trust boundary stand, verified by **both** lenses: MCP through the code gate / feed-the-gate-unchanged (R0-A G1/G2 + R0-B G6); discovery≠permission / pre-classify allowlist (R0-A G4 + R0-B G3); server-can't-influence-the-tier (R0-A G3 + R0-B G2); execution-downstream-of-gate structural (R0-A G6 + R0-B G1); the trust boundary — allowlist / `api_key_env` credential indirection / untrusted-result size-limit+framing / **env-leak-prevented (the c2 lesson)** (R0-A G8–G11 + R0-B G4/G5/G7); no new `LLMPurpose`; ADR-027 RC-23-safe; the adapter/config contract anticipates P3.5 plugin-delivery. R0-B G5 also clears R0-A's untrusted-result watch-items (the describe-don't-act seam is the acceptable P2.5-G2 known seam).

## Senior absorb scope (literal-reading)

The edits are: **ADR-027 D1** (the bridge timeout mechanism: `asyncio.wait_for` + kill+wait + the hanging-mock test) and **plan §5 + ADR-027 D6/HR#4** (the AUTO-only clarification + the confirm-then-execute deferral). No design reversal; the spine + trust boundary D-decisions stand. **Bump BOTH** R0-A-on-plan + R0-B-cross-family per RC-10. Then the architect accepts ADR-027 → P3.4 impl (where the dual-lens R0-B re-runs on the implementation — `requires_cross_family_review: true`; the hanging-server/orphan-subprocess/env-leak surface is the re-probe target).
