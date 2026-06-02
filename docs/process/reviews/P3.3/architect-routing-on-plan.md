---
task_id: P3.3
kind: architect-routing
stage: plan
date: 2026-06-02
reviews_acked:
  - R0-A-on-plan.md   # architect-partner in-family, single-lens (dual-lens R0-B skipped — frozen-contract consumer)
joint_verdict: needs_architect (single-lens R0-A; 0🔴 / 1🟡 / 12🟢) → Y1 α-lite-fold, rest clean
decisions:
  Y1: α-lite-fold — add two contract-drift guards to the FE gate (codegen-freshness diff + WS-type conformance check), folded into plan §6/§7 + ADR-026
---

# P3.3 architect routing — plan stage (Y1 → α-lite-fold; rest clean)

**Architect decision (this session):** the plan is **clean** on the constitutional spine + contract-binding (12🟢 — view+intent / binds-API-only structurally-enforced / 状态机不暴露 via the never-raw `ui_strings` mapper / partial-turn / no-forge / the codegen-HTTP + complete-WS-client binding). **One low precision point — Y1 → α-lite-fold** (the senior folds two contract-drift guards into the plan + ADR-026 during revision — no stack/design change, no new infra).

This is the **signal artifact for the senior revision session.** Senior absorbs Y1 into plan §6/§7 + ADR-026, then **bumps the R0-A-on-plan verdict per RC-10** (→ clean). Then the architect accepts ADR-026 → P3.3 impl.

## Per-finding routing

### Y1 → α-lite-fold — add two contract-drift guards to the FE gate

**Finding (R0-A Y1, low):** the binding is correct against the frozen contract, but the drift guards are under-specified — the FE gate (eslint+prettier+tsc+vitest) has no codegen-freshness check (a stale `schema.ts` vs a changed `openapi.json` wouldn't be caught), and the hand-written WS types have no drift-guard vs `wire.py`'s `StreamMessage`. Low for the frozen MVP; matters as the contract evolves (P3.4+).

**Action (senior absorb — plan §6/§7 + ADR-026; no stack/design change):**
1. **Codegen-freshness gate step** — add `npm run codegen && git diff --exit-code ui/src/api/schema.ts` to the FE gate; **fail if `schema.ts` is stale** vs `openapi.json`. This is the **symmetric counterpart of the P3.2 OpenAPI-drift test** (which guards the API side) — it guards the GUI side, so a contract change that isn't re-codegen'd is caught.
2. **WS-type conformance check** — assert the hand-written `StreamMessage` types against the `asyncapi.md` / a sample shape, so a future `StreamMessage` envelope change can't drift the GUI's hand-written WS types silently.

Fold both into the plan's **§6/§7** (the FE gate + the test plan — add the freshness step to `npm run gate`/CI and the conformance assertion to the WS-client tests) and into **ADR-026** (D6 gate + the D2 WS-types note). No ADR-026 design reversal; no new infra; the stack/structure/role decisions stand.

## The rest — clean (no action)

R0-A's other 12🟢 stand: the constitutional spine is faithfully inscribed **and structurally enforced** (binds-API-only = no-DB-dep + eslint-confined `fetch`/`WebSocket` + a test; 状态机不暴露 = exhaustive never-raw `ui_strings` + a no-raw-leak DOM test; partial-turn = store branches on `stage` + the no-re-post-on-`stage:turn` integration test; no-forge = type-impossible); the contract-binding is right (codegen HTTP from the drift-tested `openapi.json`; a complete hand-written WS client matching `asyncapi.md` incl. the `ping`-keepalive tolerance + reconnect-re-replay; dedup centralized in `applyEvent`); the stack/structure/gate/role match the rulings; ADR-026 is RC-23-safe; the read+intent MVP scope (deferring §6.4 patterns / `DECISION`/`RETRACTION` / theming / auth → P3.6) is clear.

## Senior absorb scope (literal-reading)

The single edit is the **two contract-drift guards in plan §6/§7 + ADR-026** (the codegen-freshness gate step + the WS-type conformance check). No stack/design change; no new infra; the role/review arrangement (Sonnet junior + single-lens architect-partner R0-A, R0-B skipped) stands. Bump the R0-A-on-plan verdict per RC-10. Then the architect accepts ADR-026 → P3.3 impl (single-lens R0-A on the implementation — spine + contract-binding + code quality).
