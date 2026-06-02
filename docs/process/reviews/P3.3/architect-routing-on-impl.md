---
task_id: P3.3
kind: architect-routing
stage: impl
date: 2026-06-02
reviews_acked:
  - R0-A.md   # architect-partner in-family, single-lens (dual-lens R0-B skipped — frozen-contract consumer)
joint_verdict: needs_architect (single-lens R0-A; 0🔴 / 1🟡 / 12🟢) → Y1 α, rest clean
decisions:
  Y1: α — re-key AGENT_NAME_MAP to the 6 product agents (prober/skeptic/operator/divergence_mapper/logger/facilitator) + fix uiStrings.test.ts's same context-bleed (use a product agent as the known-agent example, not architect)
---

# P3.3 architect routing — impl stage (Y1 → α; rest clean)

**Architect decision (this session):** the GUI impl is **clean** on the constitutional spine + contract-binding (12🟢 — view+intent / binds-API-only structurally-enforced / 状态机不暴露 / partial-turn / no-forge / the codegen-HTTP + complete-WS-client binding with both Y1-plan drift guards). **One UX defect — Y1 → α** (the junior fixes it; no design/contract change).

This is the **signal artifact for the junior fix.** Junior absorbs Y1 into `ui/src/uiStrings.ts` + `ui/src/uiStrings.test.ts`, the FE gate stays green, then the verdict bumps per RC-10 → accept + merge.

## Per-finding routing

### Y1 → α — re-key `AGENT_NAME_MAP` to the product agents (+ fix the test's same context-bleed)

**Finding (R0-A Y1, 🟡 medium-low):** `ui/src/uiStrings.ts:32` `AGENT_NAME_MAP` keys on the **dev-workflow roles** (`architect`/`senior`/`junior`/`reviewer-r0a`/`reviewer-r0b`), not the **product agents** the GUI displays — so every product agent event (`author:"agent:skeptic"`, …) misses the map and falls to the generic "助手", collapsing the MVP's "watch the agents" value (the §6.4 "AI 多视角" pattern). Not a 不暴露 breach (safe fallback), so the no-raw-leak test passes — and `uiStrings.test.ts` itself uses `agent:architect` as its "known agent" example, the same context-bleed, so it can't catch this.

**Action (junior — code fix; no design/contract change):**
1. **Re-key `AGENT_NAME_MAP`** to the **6 product agents** (verified full set from `config/agents/`): `prober`, `skeptic`, `operator`, `divergence_mapper`, `logger`, `facilitator` — **not** the dev-workflow roles. Give each a provisional Chinese display name (the exact names are a UX/content choice, refinable later; the requirement is the **keys** match the product agent ids so the map isn't dead + agents are distinguishable). Unknown agents keep the safe "助手" fallback.
2. **Fix `uiStrings.test.ts`'s same context-bleed** — the "known agent" example must be a **product agent** (e.g. `agent:skeptic`), **not** `agent:architect`, so the test asserts a product agent maps to its real name (≠ "助手") and **would catch** a regression of this class. Keep the existing unknown-agent → safe-generic case.

The FE gate (`lint+format+typecheck+test+codegen:check`) stays green. No change to the spine, the contract-binding, the WS client, the store, or the gate — this is a data-map correction + a test-example correction.

## The rest — clean (no action)

R0-A's other 12🟢 stand: the constitutional spine holds **and is structurally enforced** (binds-API-only = no-DB-dep + `fetch`/`WebSocket` confined to `src/api/` + `constitutional.test.ts` source-scan; 状态机不暴露 = tsc-exhaustive never-raw `ui_strings` + the no-raw-leak unit + rendered-DOM tests; partial-turn = `Composer` disables on `stage:turn` + the integration test asserts `postIntent` called once; no-forge = type-impossible); contract-binding is right (HTTP codegen tracking `openapi.json` via `codegen:check`; a complete hand-written WS client — replay→`replay_complete`→live-dedup-in-`applyEvent`→`StreamError`→ping-no-op→exponential-backoff reconnect); both Y1-plan-stage drift guards landed (codegen-freshness + WS-type conformance); stack/structure/gate/node match ADR-026; `contributing.md` FE section added. (Note: the gate-green is per the orchestrator's verified run — eslint/format/tsc/vitest 52 passed/codegen-freshness exit 0 — since node was absent in the reviewer env.)

## Junior absorb scope (literal-reading)

The single edit is the **`AGENT_NAME_MAP` re-key (to the 6 product agents) + the `uiStrings.test.ts` known-agent example fix (to a product agent)**. No spine/contract/WS/store/gate change. Keep the FE gate green. Bump the R0-A verdict per RC-10. Then the architect accepts + merges P3.3 (Wave-1 closed; the frontend track opens — P3.6 ∥ the backend track P3.4/P3.5).
