---
task_id: P2.4
kind: architect-routing
stage: impl
date: 2026-06-01
reviews_acked:
  - R0-A.md
  - R0-B.md
  - plan-vs-impl.md
joint_verdict: needs_architect (Route B — R0-A governs; R0-B + plan-vs-impl both clean)
decisions:
  Y1: α-lite (ADR-020 D2 wording ONLY — "un-representable" → "un-representable through the memory/ API", to match D5's documented raw-INSERT caveat; NO code, NO new guard; the raw-SQL gap stays a knowingly-accepted D5 limitation)
  Y2: β (DEFER — non-atomic read-modify-write upsert + created_at-overwrite captured as future-concurrency retro candidate RC-26; NOT fixed this cycle; manifests only under a future multi-connection surface)
---

# P2.4 architect routing — impl stage (Y1 → α-lite, Y2 → β)

**Architect decision (this session):** the impl-stage joint verdict is **needs_architect** (Route B — the mandatory R0-A governs even though R0-B and plan-vs-impl are both `clean`). The two R0-A 🟡 are both **single-in-family-lens at the 🟡 level**, both independently *traced and cleared* by r0b's cross-family lens as 🟢 forward-notes (G7), and both resolve **without code change this cycle**.

This file is the **signal artifact for the senior absorb session.** Senior picks P2.4, reads this + `R0-A.md` + `R0-B.md` + `plan-vs-impl.md` + ADR-020, applies the single routed edit (Y1 α-lite), and bumps the R0-A verdict per RC-10. **No code change; Y2 is deferred, not fixed.**

## Per-finding routing

### Y1 → α-lite — reconcile ADR-020 D2 wording only (no code, no new guard)

**Finding (R0-A Y1):** the Principle-11 AST guard catches `EntityType.PREFERENCE` *construction* (R0-A proved it fails on a planted attribute bypass) but not a raw-SQL `INSERT … 'preference'` (proved it passes). **This is a re-surfacing, not a new defect** — ADR-020 **D5 already acknowledges** the raw-INSERT gap explicitly and reasons-away the sturdier store-layer alternative; r0b **G7c** independently cleared it as correct guard scoping. The routed Y1→α (the AST typed-path guard) was satisfied at impl.

**Action (senior absorb — the *only* edit this cycle):**
- **ADR-020 D2**: change the flat "an LLM-inferred preference with no user is **un-representable**" to "**un-representable through the `memory/` API**" (or equivalent), so D2 matches D5's documented caveat that a raw-string `INSERT INTO entity … 'preference'` is a knowingly-accepted, out-of-guard-scope limitation. One-line wording reconcile.
- **No code.** **No new guard.** The raw-SQL gap **stays** a D5-accepted limitation (a raw INSERT bypasses every Pydantic model regardless; the guard's job is the typed path, which it covers).

### Y2 → β — defer the non-atomic upsert as a future-concurrency retro candidate

**Finding (R0-A Y2):** `record_preference`'s existence-`SELECT` sits outside the `with conn:` block with no DB `UNIQUE` backstop → concurrent same-`(user_id, key, scope)` calls could duplicate a row the upsert keeps singular; `created_at` is also overwritten on update.

**Manifestation:** **future-concurrency only.** Under the current single-connection sequential model (ADR-011 D1) it cannot occur. r0b **G7a** independently traced the exact same non-atomic read-modify-write and cleared it "correct under single-connection; a multi-connection future would need `SELECT … FOR UPDATE` or a `UNIQUE` constraint" — so both lenses agree on the fact and the non-manifestation, differing only in tag (R0-A 🟡 vs R0-B 🟢). (Note: ADR-020 D2 sanctioned "read-modify-write within the existing transaction posture"; the impl's SELECT-outside-the-block is functionally equivalent single-threaded.)

**Action:**
- **NOT fixed this cycle.** Captured as **RC-26** in `docs/retrospectives/P2.4-candidates.md` — revisit when a concurrency surface (multi-connection access) arrives, mirroring R0-B G7a's clearance.
- No ADR change, no code change for Y2.

## Senior absorb scope (literal-reading)

The **only** working-tree edit is the ADR-020 D2 one-line wording reconcile (Y1 α-lite). Y2 is **deferred** (RC-26 already logged — do not touch `record_preference`). Do **not** edit `R0-A.md`'s findings (bump its verdict per RC-10 if your protocol requires, but the findings stand as the session-time record). Architect-deferral literal-reading applies: Y2's defer is a substantive deferral, not a green light to "harden the upsert while we're here."
