---
task_id: P6.8
stage: architect-routing-on-impl
cycle: 1
actor: architect (orchestrator, under the P6 bug-fix-backlog delegation)
date: "2026-06-15"
routing: accept-as-shipped
disposition:
  R0A-Y1-fe-catch: accept-light-track
inputs:
  - docs/process/reviews/P6.8/plan-vs-impl.md   # clean
  - docs/process/reviews/P6.8/R0-A.md           # needs_architect (1 🟡 Y1, FE minor)
  - docs/process/reviews/P6.8/R0-B.md           # clean (BE auth-enumeration)
---

# P6.8 routing — accept-as-shipped (merge)

**BE atom clean** (R0-B + R0-A): `GET /rooms` is auth-protected (outside the middleware allowlist), `list_rooms()` is a single read-only reader-pool query (no N+1, no writer block), returns only room metadata, and the **ADR-039 D10 RB-AUTHZ residual line IS present and correct** (the enumeration is a read-surface instance of the already-accepted any-auth-reads-any-room posture — boundary not widened). plan-vs-impl clean. Spine byte-frozen, no new ADR, no scope creep; gates green (BE + FE; `codegen:check` byte-matches).

**FE atom — one 🟡 (Y1), accepted for the light-list track.** `RoomList`'s on-mount fetch lacks a `.catch()`, so a failed `GET /rooms` silently shows an empty sidebar rather than a distinct error state (diverges from sibling components' error-handling). **Non-destructive UX nit, not a bug** (passive on-mount list; no crash; no stated error-UI requirement). R0-A offered β = accept for the light track; taking it — not worth a cycle-2 + full FE re-review round for a 1-line consistency tweak on the established light frontend track. If a distinct error/empty state is wanted later, it's a trivial 1-line `.catch` add.

**Disposition: merge P6.8.** No spine/ADR/contract touch; the only finding is a sanctioned light-track FE residual.

(Routed by the orchestrator under the delegated bug-fix-backlog authority: BE clean, residual correctly inscribed, FE nit accepted per R0-A's β option for the light track.)
