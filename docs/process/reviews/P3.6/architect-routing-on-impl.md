---
task_id: P3.6
stage: architect-routing-on-impl
adr_under_review: ADR-030
impl_branch: claude/P3.6-impl
routed_by: architect (Peidong)
routed_via: orchestrator
date: 2026-06-03
reviews_routed:
  - docs/process/reviews/P3.6/R0-A.md  # needs_architect: Y1, Y2 (both should-fix)
reviews_already_clean:
  - docs/process/reviews/P3.6/plan-vs-impl.md  # clean (senior)
  - docs/process/reviews/P3.6/R0-B-cross-family.md  # clean (0🔴/1🟡/7🟢, impl-stage re-review)
disposition: all-α
fix_commit: 1dc0887
---

# Architect routing — P3.6 impl-stage (R0-A)

Architect (Peidong) routed the impl-stage R0-A on 2026-06-03 via the orchestrator. **Both findings → α (junior absorb).** No β/γ. The trust surface is **clean** on every probe (R0-A probes 1–6: no-forge, t4 two-appender guard, downstream-of-gate empty-diff, two-layer idempotency + position-anchored, plant-bypass, 不暴露 — all affirmed); R0-B cross-family impl-stage re-review was **clean** (0🔴/1🟡/7🟢); senior plan-vs-impl was **clean**. The two R0-A findings are **should-fix hardening** (a shared-constant extraction + a missing execute-stage test), not behavior defects — they tighten the very invariants the reviews confirmed hold.

## R0-A Y1 (probe 4 — position-anchored consistency by construction) → **α**

**Finding.** The B2/B3 "byte-for-byte consistent" resolution set was achieved by **duplication** — `_PENDING_RESOLUTION_TYPES` (snapshot.py) and `_CONFIRM_RESOLUTION_TYPES` (app.py) were identical but had no shared constant and no equality test, so a future one-sided edit could silently re-open the cross-turn-collision divergence (this is the same future-drift risk the senior's plan-vs-impl N1 flagged independently).

**Fix (1dc0887).** The frozenset is **hoisted to `orchestrator.core.event.PENDING_RESOLUTION_TYPES`** — one shared public constant in the canonical leaf layer; both `derived/snapshot.py` (D2) and `api/app.py` (D3) **import it** (verified: `snapshot.py:15` + `app.py:42`), and the two private copies are deleted. Consistency is now **structural** (a single source of truth), not comment-enforced. Plus `tests/api/test_confirm.py` **§8 TestPendingResolutionConsistency** pins the behavioral equivalence both directions (unresolved → snapshot-pending ∧ endpoint-confirmable; resolved → snapshot-drops ∧ endpoint-already_resolved). **Absorbed.**

## R0-A Y2 (probe 1 — execute-stage partial-turn coverage) → **α**

**Finding.** The `_ConfirmExecuteError` → `stage:"execute"` branch (ADR-030 D5, a do-not-reverse invariant) had no test — the confirm test classes only exercised the append-stage half.

**Fix (1dc0887).** `tests/api/test_confirm.py` **§9 TestConfirmExecuteStage::test_executor_failure_execute_stage_error_durable_idempotent** injects an executor failure **after** the `TOOL_CALL` append and asserts: `500 stage:"execute"` + the `TOOL_CALL` is **durable** (do-not-reverse) + a re-confirm returns `already_resolved` (idempotency layer 1 catches the orphaned `TOOL_CALL`). **Absorbed.**

## Verification (senior, on `claude/P3.6-impl` @ 1dc0887)

- **Shared helper:** `PENDING_RESOLUTION_TYPES` defined once in `core/event.py`; imported by both `snapshot.py` and `app.py`; no residual private copy. The position-anchored predicate (`later.type in PENDING_RESOLUTION_TYPES and call_id match`, scan after the pending event) is now literally one definition used by both predicates. Layering is clean — `core/` is the canonical leaf both `derived/` and `api/` already import from.
- **Y2 test present:** §9 covers the execute-stage durable+idempotent path; §8 covers the snapshot⟺endpoint consistency.
- **No behavior change / invariants intact:** the fix is pure constant-extraction + test additions. The gate decision logic + executor empty-diff invariant still holds (`autonomy/`, `tools/executor.py`, `emission.py`, `scoring.py` remain untouched). Orchestrator self-verified both gates green (backend mypy 220 / pytest 1576; frontend eslint+prettier+tsc+vitest 107 + codegen:check).

## State / next

- **ADR-030 is `Accepted`** (P3.6).
- `R0-A.md` `verdict` bumps to `clean` (RC-10; `verdict_history` grows a post-routing-absorbed entry). `plan-vs-impl.md` + `R0-B-cross-family.md` are **already clean** — not touched.
- All three review surfaces (senior plan-vs-impl + R0-A + R0-B cross-family) are now **clean**. The architect proceeds to **PR merge / close-out** (orchestrator-driven; state advance + merge are the architect's, not the senior's).
</content>
