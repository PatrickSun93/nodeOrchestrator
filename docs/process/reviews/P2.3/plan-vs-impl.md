---
task_id: P2.3
round: plan-vs-impl
reviewer: senior
impl_commit: 7f66ad3
verdict: clean
verdict_history:
  - needs_architect  # original (0🔴 1🟡 3🟢); Y1 → α absorbed (reader subscript access + canary test), bumped per RC-10
findings_count:
  red: 0
  yellow: 1
  green: 3
---

# P2.3 plan-vs-impl (senior) — promotion rule (c) external ground-truth validation

| Field | Value |
|---|---|
| Reviewer | senior (plan-vs-deliverable lens) |
| Plan | `docs/process/senior-plans/P2.3.md` (incl. the Y1→α plan-stage revision) |
| ADR | `docs/decisions/ADR-019-external-ground-truth-validation.md` (Accepted) |
| Impl | `claude/P2.3-impl` @ `7f66ad3` (atomics P2.3-2..4 at `fef0f06`, `71c8cef`, `7f66ad3`) |
| Verdict | **needs_architect** — 0🔴 · 1🟡 · 3🟢 |

## Summary

Faithful, high-quality implementation across the representation, the constitutional boundary, and the test surface. `core/event.py` adds `EXTERNAL_VALIDATION` + `ExternalValidationMeta` exactly per ADR-019 D1 (verdict enum, `hyp_`-pattern `str`, `extra="forbid"`, registered in `TYPED_METADATA`, "18→19" docstring + `event-model.md`), and `test_schema.py` proves the append-time guarantee thoroughly (missing field / bad verdict / bad pattern / extra field all raise). The reader is a pure derivation that writes nothing, the AST orthogonality guard is a real call/import check (not a substring scan), and the e2e (Scenario Z) covers confirmed/refuted/inconclusive, dedup, dangling-ref, promoted-not-surfaced, orthogonality (no VK + no `decision` event), status-untouched, and a **discriminating** determinism test (by content label, per P2.2 Y1→α precedent). Principle 5 is honored — `memory/` imports no LLM; the verdict is read as a typed field.

One **🟡**, and it is exactly the invariant this review was asked to scrutinize: **the reader re-introduces a silent malformed-metadata skip via `meta.get(...)` + `if hyp_id:`** — contradicting the Y1→α resolution (and the reader's own docstring) that there be no silent skip and that any guard *raise* as a constitutional canary. The impl is functionally correct for well-formed events (all that can occur via the sanctioned path), so this is plan-implied-invariant drift, not a shipped-correctness bug — but it is the precise thing the plan-stage Y1 routing settled. Cheap to fix.

## Per-atomic verification

| Atomic | Delivered | Plan match | Notes |
|---|---|---|---|
| P2.3-2 core EventType + Meta | ✓ `fef0f06` | ✓ | `EXTERNAL_VALIDATION` (19th); `ExternalValidationMeta` {source, verdict Literal, `hyp_`-pattern `str`, evidence_ref?} frozen+extra-forbid (event.py); `TYPED_METADATA` registered; "18→19" docstring + `event-model.md`. `test_schema.py`: verdict-enum exhaustiveness, pattern, wrong-prefix, extra-forbid, frozen, `validate_metadata` append-time raises, TYPED_METADATA mapping. `core/` imports no `memory/` (str, not HypothesisId). |
| P2.3-3 memory reader | ✓ `71c8cef` | ✓ **(1🟡)** | `list_externally_validated_candidates` pure derivation, no writes; confirmed-only; set-dedup; `IN (...) AND status='pending'` filters dangling/non-PENDING; `id ASC`; Python-parse (no JSON1). **🟡 Y1: `.get()`+`if hyp_id:` silent skip — see below.** |
| P2.3-4 e2e + AST guard + handoff | ✓ `7f66ad3` | ✓ | Scenario Z (full pipeline + 7 edge tests); AST orthogonality guard (real, code-not-comments); discriminating determinism; handoff §4.5; no §7 bundling. |

ADR-019 accept-gate honest (Accepted; RC-23 clear). Constitution: `validation.py` no LLM imports — rglob covers it.

## Findings

### 🟡 Y1 — the reader silently skips malformed metadata via `.get()` + `if hyp_id:`, contradicting the Y1→α resolution (and its own docstring)

`validation.py:38-43`:

```python
for row in rows:
    meta = json.loads(row[0])
    if meta.get("verdict") == "confirmed":          # .get() → None on missing key → silently skipped
        hyp_id = meta.get("validated_hypothesis_id")
        if hyp_id:                                   # silently skips a row with absent/empty id
            confirmed_ids.add(hyp_id)
```

The plan-stage **Y1 → α** routing (absorbed into plan P2.3-3 AC#7 + ADR-019 D2) settled this exact point: *"The reader trusts that contract and does **no** metadata-shape handling (no skip branch) … any belt-and-suspenders parse guard … must **raise** (a constitutional canary), **never silently skip** (fail-loud, mirroring ADR-018 D4)."* The impl's `meta.get("verdict")` and `meta.get("validated_hypothesis_id")` + `if hyp_id:` are precisely the silent-skip-on-shape-variance the resolution removed: a row whose metadata lacks `verdict`/`validated_hypothesis_id` is silently dropped (returns `None` → not added), rather than surfacing the upstream break.

**Why it matters (plan-implied invariant, reinforced by this very impl's tests):** `test_schema.py` proves `validate_metadata(EXTERNAL_VALIDATION, {…missing field…})` raises `MetadataValidationError` at append — so a malformed `external_validation` event is **unreachable** through `EventStore.append`. The `.get()` defensiveness therefore (a) is dead code on the sanctioned path, and (b) silently masks the *only* case it could ever fire on — a raw `INSERT` bypassing `EventStore.append`, the exact invariant break Y1 said a guard must surface, not conceal. Tellingly, **`validation.py`'s own docstring (lines 29-33) states the resolved intent verbatim** ("any belt-and-suspenders guard must raise, never silently skip") while the code does the opposite — a docstring-vs-code contradiction that confirms the resolved AC was understood but not implemented (idiomatic `.get()` slipped in). No test exercises a malformed/raw-INSERT row, so the drift is unguarded.

**Lean — α** (test/impl precision, no design change): use **direct subscript access** — `meta["verdict"]` and `meta["validated_hypothesis_id"]` — so a malformed row raises `KeyError` (the constitutional canary), and drop the `if hyp_id:` guard (the pattern constraint guarantees a non-empty `hyp_`-id on the sanctioned path). Optionally add one test asserting the reader **raises** on a raw-`INSERT`ed malformed `external_validation` row (the canary the e2e currently omits — all its events go through `validate_metadata`). This restores exactly the Y1→α posture the reader's own docstring already promises. (β — accept `.get()` as harmless given append-time validation — is the considered alternative; it leaves a silent-skip that re-opens the precise question Y1 closed and contradicts the docstring, so I lean against it.)

### 🟢 G1 — core EventType + `ExternalValidationMeta` faithful and thoroughly tested

Matches ADR-019 D1 exactly: the verdict `Literal["confirmed","refuted","inconclusive"]`, `validated_hypothesis_id` as a `hyp_`-pattern `str` (deliberate-duplication — `core/` imports no `memory/`, mirroring `DecisionMeta`), `evidence_ref: str | None`, frozen + `extra="forbid"`, registered in `TYPED_METADATA`. The "18 → 19" docstring + `event-model.md` are updated; the per-type `TYPED_METADATA[EXTERNAL_VALIDATION] is ExternalValidationMeta` assertion matches the existing test pattern; no `len(EventType)` test exists to break (as predicted). `test_schema.py` covers verdict-enum exhaustiveness, the pattern (incl. a `vk_`-wrong-prefix case), `extra="forbid"`, frozen, and the append-time `validate_metadata` raises. ✓

### 🟢 G2 — advisory orthogonality enforced by construction + genuinely tested

The reader writes nothing, so orthogonality is by construction. The new `test_validation_advisory_orthogonality_ast_guard` is a real AST call/import check (mirrors the matcher guard; RC-24) — it inspects `Name`/`Attribute`/`Import` nodes and only string-literal SQL Constants, so it correctly does **not** trip on `validation.py`'s docstring (which mentions `append`/`promote` in prose). The e2e asserts the runtime orthogonality: after the reader, `verified_knowledge` count == 0 and `decision`-event count == 0, and `promote_hypothesis` succeeds on the externally-validated hyp-A **and** the un-validated hyp-C (the signal does not gate promotion — ADR-016 D3/D10 hold). Principle 5: `validation.py` imports no LLM (rglob covers it). ✓

### 🟢 G3 — scope discipline + the reader's functional behavior correct

Confirmed-only (refuted/inconclusive ignored — two e2e tests); set-dedup for multiple confirmations; dangling-ref and non-PENDING/VERIFIED rows filtered by `IN (...) AND status='pending'` (promoted-not-surfaced test); determinism asserted **discriminatingly** by content label (not a count proxy — P2.2 Y1→α precedent applied); status never mutated (e2e AC#5). No new table/flag (pure derivation per ADR-019 D2). handoff §4.5 light-touch (triad complete), **no §7-P1.2-stale bundling**; `event-model.md` updated. One-atomic-one-commit (RC-17). ✓

## What the architect needs to route

1. **Y1 (🟡):** the reader's `.get()` + `if hyp_id:` silently skips malformed metadata — re-opening the exact silent-skip the plan-stage Y1→α routing closed, and contradicting the reader's own docstring. Lean **α** — direct subscript access (`meta["verdict"]`, `meta["validated_hypothesis_id"]`) so a raw-`INSERT` bypass raises (canary), drop `if hyp_id:`, optionally add a raise-on-malformed test. No design change.
2. **Greens** are affirmations.

Per ADR-008 Amendment 1 (Route B), state auto-advances to `awaiting_R0_A` regardless of this verdict; R0-A (+ R0-B, dual-lens dispatched) fire, then joint-verdict evaluation. This 🟡 makes the joint verdict non-clean → `awaiting_architect_decision` for routing.

---

## Verdict bump (RC-10) — needs_architect → clean

Architect routed Y1 → α (`architect-routing-on-impl.md`, 2026-05-31; **3-lens consensus** — senior plan-vs-impl + R0-A + R0-B-cross-family, zero divergence; Principle-5 boundary confirmed clean by import-trace from two families). Absorbed in the senior revision: the reader (`validation.py`) now uses **direct subscript access** — `meta["verdict"]` and `meta["validated_hypothesis_id"]` — so a malformed metadata shape (only reachable via a raw `INSERT` bypassing `EventStore.append`) raises `KeyError` as the constitutional canary; the `if hyp_id:` silent-skip guard is dropped. This restores the posture the reader's own docstring already promised (raise, never silently skip — ADR-019 D2 / ADR-018 D4). Added `test_scenario_z_reader_raises_on_raw_malformed_event` (raw-`INSERT`ed `external_validation` row missing `verdict` → reader raises) — the canary the e2e previously omitted; it is discriminating (the old `.get()` would have silently skipped and failed `pytest.raises`). **No `src/` design change.** Gates green: ruff ✓ · mypy --strict ✓ (23 files) · pytest ✓ (memory + integration). Verdict → **clean**.
