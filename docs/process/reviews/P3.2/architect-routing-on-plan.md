---
task_id: P3.2
kind: architect-routing
stage: plan
date: 2026-06-02
reviews_acked:
  - R0-A-on-plan.md       # architect-partner in-family (needs_architect 0R/1Y/14G)
  - R0-B-cross-family.md  # deepseek cross-family (needs_architect 0R/3Y/6G)
joint_verdict: needs_architect (dual-lens plan-stage; 0🔴 / 4🟡 / spine clean) → all 4 routed α
decisions:
  r0b_Y1: α — pin subscribe-then-replay + dedup in ADR-025 D6 (executor-atomic, not replay-first)
  r0b_Y2: α — separate WAL read connection + read-only executor (writes + run_turn stay on the writer; api opens a 2nd conn, no core/contract change)
  r0b_Y3: α — partial-turn error envelope folded into the pinned contract (distinguish append-fail vs turn-fail, carry appended_event.id)
  arch_Y1: α-lite — validate DECISION/RETRACTION authority-metadata handling, do NOT tighten the allowlist, UTTERANCE stays excluded
---

# P3.2 architect routing — plan stage (all 4 → α; spine clean)

**Architect decision (this session):** the dual-lens plan-stage review is **clean on the constitutional/security spine** (backend-authoritative / forge-prevention / no-decision-surface — 2-way confirmed: R0-A G1/G2/G4 + R0-B G2/G4; no new `LLMPurpose`). All four 🟡 are on the concurrency / failure-mode / contract-completeness surface and are **plan-stage-resolvable** — **all routed α** (three full-fold + one α-lite). No ADR-025 design reversal; the decisions D1–D7 stand, refined.

This is the **signal artifact for the senior revision session.** Senior absorbs the four below into the plan + ADR-025, then **bumps both plan-stage verdicts per RC-10** (R0-A-on-plan + R0-B-cross-family → clean). Then the architect accepts ADR-025 → impl.

## Per-finding routing

### r0b Y1 → α — fix the replay/subscribe ordering (correctness)

**Finding (R0-B Y1, 🟡):** ADR-025 D6 / plan §4 say "replay-then-subscribe," which **drops events appended in the replay window** (after the replay SELECT, before the queue registers).

**Action (senior absorb — ADR-025 D6 + plan §4):** pin **subscribe-then-replay + dedup** — register the subscriber queue **first**, then run the replay SELECT, both **atomically on the executor** (so no write interleaves), and deduplicate any event appearing in both. Correct the misleading prose. The impl test (§2) asserts no-gap **and** no-dup across the handoff under a concurrent write.

### r0b Y2 → α — separate WAL read connection (liveness)

**Finding (R0-B Y2, 🟡):** the single executor serializes **all** reads behind writes — a multi-second `run_turn` (incl. the LLM call) blocks every GET / WS-replay → the GUI freezes during every turn (a liveness problem, not just throughput).

**Action (senior absorb — ADR-025 D6 + plan §4/§5):** use a **separate WAL read connection on a read-only executor** for GET/WS-replay; keep **writes + `run_turn` on the single writer executor**. The `api/` layer opens a **second `EventStore`/connection** (WAL `journal_mode`, `check_same_thread=False` read-only) — **no `core/` change, no contract change** (the read endpoints' shapes are unchanged). The §2/§3 tests assert reads stay responsive during an in-flight turn.

### r0b Y3 → α — partial-turn error envelope (fold into the pinned contract)

**Finding (R0-B Y3, 🟡):** `append` succeeds then `run_turn` raises → the client gets a bare `5xx` and cannot tell whether the intent landed → retry duplicates the user event.

**Action (senior absorb — ADR-025 D5 + plan §2/§7-§3):** the error envelope **distinguishes** `append-failed` (safe to retry) from `append-succeeded / turn-failed` (intent recorded — do **not** re-send) and **carries `appended_event.id`** in the latter. This lands in the **pinned contract** (inscribe-before-producer — fix now, before P3.3 binds; it's part of the OpenAPI error schema). The §3 failure-mode test asserts the two cases are distinguishable.

### arch Y1 → α-lite — validate the authority handling, don't tighten the allowlist

**Finding (R0-A Y1, 🟡 low):** the allowlist `{USER_INPUT, DECISION, RETRACTION}` admits two types whose typed metadata carries authority semantics beyond shape (DECISION `promotion=True` → Principle-11 durable memory; RETRACTION targets another event).

**Action (senior absorb — α-lite, plan §3/§8 + ADR-025 D4a):** **keep the allowlist** (DECISION/RETRACTION are the GUI's confirm/retract actuators — do not tighten to `USER_INPUT`-only; **`UTTERANCE` stays excluded** as the agent speech-act). Add a one-line authority confirmation: ① cite R0-B G3 — `promotion=True` does **not** trigger `promote_hypothesis` (promotion is a separate user-confirm actuator, not driven by a `DECISION`-append; `next_room_state` gates transitions); ② confirm `RETRACTION`'s target handling (`validate_metadata` + the retraction path) is appropriate for a user-authored retraction. Low; a record-closing clarification, not a design change.

## Senior absorb scope (literal-reading)

The edits are: **ADR-025 D6** (subscribe-then-replay + the read/writer executor split), **D5** (the error envelope), **D4a** (the authority-confirmation note), and the matching **plan §2/§4/§5/§7** + the §2/§3 tests. **No `core/rooms/autonomy/llm` change** (the read-conn + error-envelope are `api/`-layer; wrap-don't-reimplement holds). **No allowlist tightening; `UTTERANCE` stays excluded.** Bump R0-A-on-plan + R0-B-cross-family per RC-10. Then the architect accepts ADR-025 → P3.2 impl (where the dispatched dual-lens R0-B re-runs on the implementation, `requires_cross_family_review: true`).
