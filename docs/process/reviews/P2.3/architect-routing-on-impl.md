---
task_id: P2.3
kind: architect-routing-on-impl
date: 2026-05-31
stage: impl
impl_commit: 7f66ad3
reviews_acked:
  - plan-vs-impl.md   # senior — 0🔴 1🟡 3🟢
  - R0-A.md           # architect-partner — 0🔴 1🟡 5🟢
  - R0-B.md           # cross-family (deepseek) — 0🔴 1🟡 5🟢
decisions:
  Y1: α (reader uses direct subscript access so a raw-INSERT bypass raises KeyError as a constitutional canary; drop the if-hyp_id silent-skip; add a raise-on-malformed test)
---

# P2.3 architect routing — impl stage (Y1 → α)

**Architect decision (this session, chat 2026-05-31, architect = Peidong):** the impl-stage joint verdict carried **one** 🟡 — and it is a **3-lens consensus** (senior plan-vs-impl + architect-partner R0-A + cross-family R0-B), all three independently source-verifying the same finding with zero divergence and zero net-new. Architect routes **Y1 → α**. No `src/` design change — a one-spot impl/test precision that restores the posture the code already documents.

**Headline (the reason this dispatch existed):** P2.3 is the **highest Principle-5 stakes slice in the project** — rule (c) literally validates "truth." **No lens found a boundary leak: all three confirm the Principle-5 boundary is CLEAN at impl** — rule (c) is a deterministic code predicate over a typed `external_validation` verdict, with **zero LLM-judgment in the `memory/` path**, verified by **import trace** (not assertion) by two independent families (R0-A + cross-family R0-B). The relocation of judgment to the connector is a genuine architectural boundary, confirmed at both plan stage and impl stage. **0🔴; 5–6🟢 across all three lenses.** ADR-019's rule-(c) impl is correct on every constitutional invariant; Y1 is one `.get()`→`[...]` edit away from clean.

This file is the **signal artifact for the senior revision session** (impl stage). Senior picks P2.3, reads this + the three impl-stage reviews + the impl at `7f66ad3`, applies the single routed action, and pushes a revision commit on `claude/P2.3-impl`. Then architect judges merge.

## Review picture (1 issue; 3-lens consensus; Principle-5 clean)

| Review | Verdict | On Y1 |
|---|---|---|
| senior plan-vs-impl | needs_architect (0🔴 1🟡 3🟢) | flagged Y1 (the silent-skip drift) |
| R0-A (architect-partner) | needs_architect (0🔴 1🟡 5🟢) | independently converged on Y1; P5 boundary clean (import trace) |
| R0-B (cross-family, deepseek) | needs_architect (0🔴 1🟡 5🟢) | independently confirmed Y1; P5 boundary clean (import trace), genuine boundary not rationalization |

Same single 🟡, same green affirmations — the highest-confidence impl-stage result in the P2 series.

## Per-issue routing

### Y1 → α — reader uses direct subscript access (raise as canary), not silent `.get()`-skip (impl/test precision; no `src/` design change)

**Finding (plan-vs-impl = R0-A = R0-B, three lenses independently source-verified):** `validation.py:40-42` consumes event metadata with `meta.get("verdict")` + `meta.get("validated_hypothesis_id")` + `if hyp_id:` — so a row whose metadata lacks `verdict`/`validated_hypothesis_id` is **silently dropped** (`None == "confirmed"` is `False`; `if None:` is `False`). This **re-opens the exact silent-skip the plan-stage Y1→α routing closed** (absorbed into plan P2.3-3 AC#7 + ADR-019 D2: *no defensive metadata-shape handling; any belt-and-suspenders guard must raise, never silently skip*), and **contradicts the reader's own docstring** (`validation.py:29-33`, which states that resolved posture verbatim). The resolved AC was understood (it is quoted in the docstring) but not implemented — idiomatic `.get()` slipped in three lines below.

**Why α (not β-accept):** append-time `validate_metadata` + `ExternalValidationMeta`'s `extra="forbid"` make a malformed `external_validation` row **unreachable** through `EventStore.append` (proven by `test_schema.py` — missing field / bad verdict / wrong-prefix id / extra field all raise). So the `.get()` branch is **dead code on the sanctioned path** (zero shipped-correctness risk for well-formed events — hence 🟡 not 🔴) — but it (a) quietly re-opens a *closed architect routing*, (b) makes the code contradict its own docstring, and (c) silently **masks the only case it could ever fire on** — a raw `INSERT` bypassing `EventStore.append`, the exact invariant break Y1's resolution said a guard must *surface*, not conceal. No e2e test exercises that path (all events go through `validate_metadata` via the e2e's `_inject_validation`), so the drift is unguarded. An impl quietly re-opening a closed routing should not land silently — that is what the review chain exists to catch.

**Action (senior revision):**
- **Use direct subscript access** in the reader: `meta["verdict"]` and `meta["validated_hypothesis_id"]` (not `.get()`), so a malformed row raises `KeyError` — the **constitutional canary** that surfaces a raw-`INSERT` `EventStore.append`-bypass loudly (fail-loud, ADR-018 D4 posture).
- **Drop the `if hyp_id:` silent-skip guard** — the `hyp_`-pattern constraint on `validated_hypothesis_id` guarantees a non-empty id on the sanctioned path; the guard only ever silences a malformed row.
- **Add one test** asserting the reader **raises** (e.g. `KeyError`) on a **raw-`INSERT`ed** malformed `external_validation` row (bypassing `validate_metadata`) — the canary the current e2e omits (its events all go through `validate_metadata`). This is the guard against future drift.
- **No `src/` design change** — the representation (event option (i)), the deterministic predicate, the pure-derivation reader, and the advisory orthogonality are all correct (5–6🟢, three lenses). This restores exactly the posture the reader's docstring already promises.

## Non-routing affirmations (no α/β/γ — the impl is correct)

All three lenses independently confirmed, for the record (no action):
- **Principle-5 boundary clean at impl** (R0-A G1 / R0-B G1) — `validation.py` imports no LLM (import-trace-verified by two families); the decision is a typed-`Literal` equality check; judgment relocated to the connector. **The load-bearing check, clean at code, from two independent families — at both plan and impl stage.**
- `core` EventType + `ExternalValidationMeta` faithful to ADR-019 D1, append-time-raises proven (`test_schema.py`) · advisory orthogonality by construction + a real AST guard (RC-24, docstring-excluded) + runtime orthogonality e2e-tested (no VK, no `decision` event; promote works on validated + un-validated) · confirmed-only + status-untouched + distinct provenance + **discriminating** determinism test (P2.2 Y1→α applied) · gates green (ruff/mypy 61/pytest), 19th-type ADR-gated, atomic-commit 1:1, handoff §4.5 + `event-model.md`, no §7-P1.2 bundling, RC-23 heeded.

## Net

- **1 routed action:** Y1 → α (direct subscript / raise-as-canary; drop `if hyp_id:`; add a raise-on-malformed test). Impl/test precision, no `src/` design change.
- **0 🔴; 5–6 🟢 across all three lenses; Principle-5 impl boundary confirmed clean by two independent families** — the highest-confidence impl-stage result in the P2 series.
- After the Y1 revision lands + the senior bumps the plan-vs-impl verdict, P2.3 is merge-ready (modulo any orthogonal RC-22-family state-position artifact, handled at merge/advance time).

State: per ADR-008, this routing moves P2.3 to senior-revision territory; senior absorbs Y1 on `claude/P2.3-impl`, bumps the plan-vs-impl verdict, then architect judges merge.
