---
task_id: P2.3
round: R0-A
verdict: clean
verdict_history:
  - needs_architect  # original (0🔴 1🟡 5🟢); Y1 → α absorbed, bumped per RC-10
findings_count:
  red: 0
  yellow: 1
  green: 5
---

# P2.3 R0-A (post-impl, architect-partner lens) — promotion rule (c), external ground-truth validation

| Field | Value |
|---|---|
| Round | R0-A (post-impl; architect-dispatched) |
| Reviewer | architect-partner (Claude family; **Principle-5 constitutional** / correctness lens) |
| Commit | `7f66ad3` on `claude/P2.3-impl` (atomics P2.3-2/-3/-4 at `fef0f06`, `71c8cef`, `7f66ad3`) |
| Baseline | `main` (ADR-019 Accepted; ADR-016/017/018; `core/event.py` verified) |
| Date | 2026-05-31 |
| Gates | ruff ✓ · mypy ✓ (61 files) · pytest **all passed** · no-LLM constitution (covers `validation.py`) ✓ |
| Verdict | **needs_architect** — 0🔴 · 1🟡 · 5🟢 |
| Note | Senior `plan-vs-impl.md` already present (`c086f6d`, 0🔴 1🟡 3🟢) — my R0-A is independent and **converges** on the same 🟡. R0-B (cross-family) runs after me on the shared tree; branch left clean. State NOT advanced. |

## Summary — the Principle-5 verdict (the dispatch's highest-stakes check)

**CLEAN. Rule (c) is a deterministic code predicate over the typed `external_validation` input, with zero LLM-judgment anywhere in the `memory/` path — verified by import trace, not asserted.** `validation.py` imports only `json`, `sqlite3`, `memory.schema.Hypothesis`, `memory.store._row_to_hypothesis` — **no LLM import** (the only "LLM" strings in the file are docstring prose saying it has none). The decision is `meta["verdict"] == "confirmed"` — a string-equality over a typed `Literal`, structurally identical to rule (b)'s `status == PENDING` (a column read) and rule (a)'s tag-set equality. The judgment is relocated to the connector (which writes via `EventStore.append`, a core-only API) exactly as ADR-019 D1 specifies; `memory/` only ever *reads* the typed result. The constitutional boundary the dual-lens dispatch existed to protect holds at impl, not just plan.

The impl is otherwise faithful and high-quality: `core/event.py` adds the 19th EventType + `ExternalValidationMeta` exactly per ADR-019 D1 (verdict `Literal`, `hyp_`-pattern `str`, frozen+`extra="forbid"`, `TYPED_METADATA`-registered, "18→19" docstring + `event-model.md`); the reader writes nothing (advisory-by-construction); the AST orthogonality guard is a real `ast.walk` call/import check (RC-24 honored); gates fully green.

**One 🟡, and it is the irony of the cycle:** the reader **re-introduces the exact silent malformed-metadata skip the plan-stage Y1→α routing removed** — via `meta.get(...)` + `if hyp_id:` — while its *own docstring* states the resolved posture ("any belt-and-suspenders guard must raise, never silently skip"). Functionally harmless on the sanctioned path (append-time validation makes malformed rows unreachable), but it re-opens the precise question Y1 closed and contradicts the docstring. Cheap fix; no design change. The design itself is correct on every invariant.

## Findings

| # | Sev | Finding | Lean |
|---|---|---|---|
| Y1 | 🟡 | Reader's `meta.get("verdict")` + `meta.get("validated_hypothesis_id")` + `if hyp_id:` **silently skips** malformed metadata — re-opening the Y1→α-closed silent-skip, contradicting `validation.py`'s own docstring; no canary test | α — direct subscript (`meta["…"]`) so a bypass raises; drop `if hyp_id:`; add a raise-on-raw-INSERT test |
| G1 | 🟢 | **Principle-5 boundary clean** — import trace confirms zero LLM in `validation.py`; verdict read as typed field (the load-bearing check) | affirm |
| G2 | 🟢 | `core` EventType + `ExternalValidationMeta` faithful to ADR-019 D1; thoroughly tested (append-time raises proven) | affirm |
| G3 | 🟢 | Advisory orthogonality by construction (pure reader, no writes); AST guard real + docstring-excluded; e2e proves runtime orthogonality | affirm |
| G4 | 🟢 | Confirmed-only + don't-touch-`status` + distinct provenance + discriminating determinism test (P2.2 Y1→α applied) | affirm |
| G5 | 🟢 | Gates green; vocabulary discipline (19th type ADR-gated); atomic-commit 1:1; handoff §4.5; no §7 bundling | affirm |

---

### 🟡 Y1 — the reader silently skips malformed metadata, re-opening the Y1→α-closed question (and contradicting its own docstring)

`validation.py:38-43`:

```python
for row in rows:
    meta = json.loads(row[0])
    if meta.get("verdict") == "confirmed":          # .get() → None on a missing key → silently skipped
        hyp_id = meta.get("validated_hypothesis_id")
        if hyp_id:                                   # silently skips an absent/empty id
            confirmed_ids.add(hyp_id)
```

The plan-stage **Y1 → α** routing (absorbed into plan P2.3-3 AC#7 + ADR-019 D2) settled this exact point: the reader does **no** defensive metadata-shape handling, and any belt-and-suspenders guard must **raise** (a constitutional canary), **never silently skip**. The impl's `.get()` + `if hyp_id:` is precisely that silent skip — a row whose metadata lacks `verdict` or `validated_hypothesis_id` is silently dropped (`None` → not added) instead of surfacing the upstream break.

The damning detail (independently confirmed): **`validation.py`'s own docstring (lines 29-33) states the resolved intent verbatim** — *"any belt-and-suspenders guard must raise, never silently skip (ADR-018 D4 fail-loud posture)"* — while the code three lines below does the opposite. The resolved AC was understood (it's quoted in the docstring) but not implemented; idiomatic `.get()` slipped in. I verified the e2e never exercises the gap: every `external_validation` event in `test_p2_3_e2e.py` is round-tripped through `validate_metadata` (line 409), so no test injects a raw-`INSERT` malformed row — the silent-skip drift is **unguarded**.

**Why 🟡, not 🔴 (and not lower):** append-time `validate_metadata` + `extra="forbid"` make a malformed `external_validation` row unreachable through `EventStore.append` (proven by `test_schema.py`), so the `.get()` branch is dead code on the sanctioned path and there is **zero shipped-correctness risk** for well-formed events. But it is (a) an impl-deviates-from-the-routed-resolution item — the precise silent-skip the architect's Y1→α call removed, now back; (b) a code-contradicts-its-own-docstring inconsistency a future reader will trip on; and (c) the one place the impl masks rather than surfaces the only break it could ever encounter (a raw-INSERT bypass — the deeper invariant violation Y1 said a guard must surface). An impl quietly re-opening a closed architect routing shouldn't land silently — that's what R0-A is for.

**Lean α (test/impl precision, no design change):** use **direct subscript** — `meta["verdict"]` and `meta["validated_hypothesis_id"]` — so a malformed row raises `KeyError` (the canary), and drop the `if hyp_id:` guard (the `hyp_`-pattern constraint guarantees a non-empty id on the sanctioned path). Optionally add one test asserting the reader **raises** on a raw-`INSERT`ed malformed `external_validation` row (the canary the e2e omits). This restores exactly the posture the reader's docstring already promises. **β (accept `.get()` as harmless)** is the considered alternative — but it leaves a silent-skip that re-opens the closed Y1 question and contradicts the docstring, so I lean against it, converging with the senior.

### 🟢 G1 — Principle-5 boundary clean (the load-bearing check, verified by trace)

The dispatch's central question — *is rule (c) a deterministic code predicate, or did LLM-judgment sneak into `memory/`?* — answered by import trace, not assertion: `validation.py`'s only imports are `json`, `sqlite3`, `memory.schema.Hypothesis`, `memory.store._row_to_hypothesis` (grep-confirmed; the only "LLM" tokens are docstring prose). The reader's decision is `meta["verdict"] == "confirmed"` over a typed `Literal["confirmed","refuted","inconclusive"]` — a code equality check, the same class as rule (b)'s `status == PENDING`. The verdict is *produced* by the connector outside `memory/` (possibly by an LLM-in-a-connector — content-gen at the edge, which is allowed) and *consumed* here as an opaque typed field. No LLM-judgment in the boundary. The no-LLM rglob constitutional guard covers `validation.py` and is green. Clean.

### 🟢 G2 — `core` EventType + `ExternalValidationMeta` faithful + thoroughly tested

Matches ADR-019 D1 exactly (diff-verified): `EXTERNAL_VALIDATION` as the 19th type; `ExternalValidationMeta(_BaseMeta)` with `source: str (min_length=1)`, `verdict: Literal[...]`, `validated_hypothesis_id: Annotated[str, Field(pattern=r"^hyp_[0-9a-f]{32}$")]` (deliberate-duplication — `str`, not `HypothesisId`, so `core/` imports no `memory/`, mirroring `DecisionMeta.hypothesis_id`), `evidence_ref: str | None`; registered in `TYPED_METADATA`; "18 → 19" docstring + `event-model.md` updated. `test_schema.py` proves the append-time guarantee load-bearing for Y1: missing field / bad verdict / wrong-prefix id / extra field all raise `MetadataValidationError` — so malformed rows genuinely cannot reach the DB. The 19th-type addition is correctly ADR-gated (ADR-019 is that ADR), and no `len(EventType)` test exists to break.

### 🟢 G3 — advisory orthogonality by construction + genuinely tested

The reader writes nothing → it *cannot* create a VK, flip a flag, or append — D10 orthogonality is structural. `test_validation_advisory_orthogonality_ast_guard` is a real `ast.walk` over `Import`/`Name`/`Attribute`/`Constant` nodes (verified: it checks call/import nodes + only string-literal SQL, so the docstring's mention of `append`/`promote` in prose does **not** trip it — RC-24 honored, the P2.2 B→α shape reused correctly). The e2e proves runtime orthogonality: after the reader, `verified_knowledge` count == 0 and `decision`-event count == 0, and `promote_hypothesis` works on the externally-validated hyp-A **and** the un-validated hyp-C (the signal does not gate promotion — ADR-016 D3/D10 hold). D11 is moot (no multi-write).

### 🟢 G4 — confirmed-only + status-untouched + distinct provenance + discriminating determinism

Confirmed-only: `refuted`/`inconclusive` ignored (two e2e cases), `status` never mutated (e2e AC#5 asserts a refuted hyp-B stays PENDING) — correct, `status == VERIFIED` stays `promote_hypothesis`'s contract. Distinct provenance: rule (c) gets its own reader (`list_externally_validated_candidates`), does not reuse rule (a)'s `candidate_for_promotion`; provenance carried by the typed event. The determinism test is **discriminating** — asserts the exact surfaced set by stable content label, not a count proxy — the P2.2 Y1→α lesson applied so this slice doesn't ship a "test that can't fail." Set-dedup for multiple confirmations; dangling/non-PENDING refs filtered by `IN (...) AND status='pending'`.

### 🟢 G5 — gates, vocabulary discipline, commit discipline

ruff ✓ · mypy ✓ (61 files) · full pytest green · no-LLM constitution covers `validation.py`. The constitutional event vocabulary grows to 19 via the ADR gate (justified — a genuine new event class, not a catch-all). 3 atomics → 3 commits 1:1 (RC-17). handoff §4.5 materializes the triad (rule (c) done); `event-model.md` count updated; no §7-P1.2-stale bundling.

## What the architect needs to route

1. **Y1 (🟡):** the reader's `.get()` + `if hyp_id:` silently skips malformed metadata, re-opening the plan-stage Y1→α-closed silent-skip and contradicting `validation.py`'s own docstring. Lean **α** — direct subscript access (`meta["verdict"]`/`meta["validated_hypothesis_id"]`) so a raw-`INSERT` bypass raises (canary), drop `if hyp_id:`, optionally add a raise-on-malformed test. No `src/` design change. (Independent convergence with the senior's plan-vs-impl Y1.)
2. **Greens** are affirmations. The Principle-5 boundary — the reason this dispatch existed — is **clean at impl**, verified by import trace.

R0-A does not change state. R0-B (cross-family) is the separate dispatch; I'll synthesize R0-A + R0-B + senior plan-vs-impl for routing once R0-B lands. The rule-(c) impl is correct on every constitutional invariant; Y1 is a one-spot fix to honor a resolution the code already documents. Branch left checked out clean for the R0-B pass.

---

## Verdict bump (RC-10) — needs_architect → clean

This review's lone 🟡 (Y1 — the reader's `.get()` silent-skip) was routed **α** (`architect-routing-on-impl.md`, 2026-05-31; 3-lens consensus with senior plan-vs-impl + R0-B-cross-family). Absorbed in the senior revision: the reader now uses **direct subscript access** (`meta["verdict"]`, `meta["validated_hypothesis_id"]`) so a raw-`INSERT` bypass raises `KeyError` (constitutional canary); the `if hyp_id:` silent-skip is dropped; a raise-on-malformed test was added. No `src/` design change — the Principle-5 boundary, the representation, and the pure-derivation reader are confirmed clean (this review's import-trace included). Gates green (ruff · mypy --strict · pytest). Verdict → **clean**.
