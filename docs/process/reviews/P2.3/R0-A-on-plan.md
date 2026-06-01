---
task_id: P2.3
round: R0-A-on-plan
verdict: needs_architect
findings_count:
  red: 0
  yellow: 1
  green: 6
---

# P2.3 R0-A on plan (architect-dispatched pre-impl review) — promotion rule (c), external ground-truth validation

| Field | Value |
|---|---|
| Round | R0-A-on-plan (architect-dispatched per RC-9) |
| Reviewer | architect-partner (doc / architecture / **Principle-5 constitutional** lens) |
| Stage | Plan + ADR-019 (Proposed), pre-impl. State `awaiting_architect_accept`. |
| Artifacts | `docs/process/senior-plans/P2.3.md`, `docs/decisions/ADR-019-external-ground-truth-validation.md` |
| Baseline | merged P2.1/P2.2 (ADR-017/018); ADR-016; `core/event.py` (verified) |
| Date | 2026-05-31 |
| Verdict | **needs_architect** — 0🔴 · 1🟡 · 6🟢 |
| Note | R0-B (cross-family) runs after me on the shared tree; branch left checked out clean. ADR-019 NOT accepted (architect-only). |

## Summary

Excellent plan + ADR. The highest-stakes check the brief flagged — **is rule (c) genuinely a deterministic code predicate, or did LLM-judgment sneak in / does the representation quietly require an LLM inside `memory/`?** — comes out **clean, and is the strongest part of the work**. The Principle-5 reconciliation is correct and load-bearingly explicit (D1 below). The representation choice (event, option (i)) over a `memory/` table (ii) or a hypothesis field (iii) is well-argued on Principle-1 + connector-decoupling grounds, and the senior went *further* than the brief leaned by making rule (c) a **pure-derivation reader** (no flag, no table, no write) — which makes advisory orthogonality true *by construction* (no write to misuse) and the dormant footprint minimal (contract + reader only). Every constitutional cite verified against `origin/main` source (G6). RC-23 heeded (ADR-019 parses `proposed`).

One **🟡**, and it is minor: a reader acceptance criterion (P2.3-3 AC#7) defends against malformed event metadata that, because `validate_metadata` runs at append-time with `extra="forbid"`, **cannot reach the database** — guarding an unreachable state, with a "skip vs raise" ambiguity that should be resolved toward "the invariant is upstream." Not a design defect; a test/spec precision item. The design is accept-worthy once it's routed.

## Findings

| # | Sev | Finding | Lean |
|---|---|---|---|
| Y1 | 🟡 | Reader's "skip malformed metadata" branch (P2.3-3 AC#7) guards an append-time-unreachable state (`validate_metadata` + `extra="forbid"` blocks malformed `external_validation` at write); skip-vs-raise ambiguity | α — drop the defensive skip, assert the upstream invariant instead (or raise-on-violation as a constitutional canary) |
| G1 | 🟢 | **Principle-5 reconciliation is correct** — judgment relocated to the connector; `memory/` reads a typed verdict field, no LLM possible inside the boundary | affirm (the load-bearing check) |
| G2 | 🟢 | Representation (i) event + pure-derivation reader: Principle-1 + connector-decoupling + derive-don't-materialize all correct | affirm |
| G3 | 🟢 | Advisory orthogonality by construction (pure reader); D10/D11 untouched; D10-holds-regardless-of-strength argument sound | affirm |
| G4 | 🟢 | Confirmed-only scope (#4) + don't-touch-`status` correct; distinct provenance (#3) preserved | affirm |
| G5 | 🟢 | AST orthogonality guard (RC-24, not substring) + discriminating determinism test (P2.2 Y1→α precedent) correctly carried | affirm |
| G6 | 🟢 | Every constitutional cite verified against `core/` source (18→19, deliberate-dup, TYPED_METADATA, no len-test) | affirm |

---

### 🟡 Y1 — the reader's "skip malformed metadata" branch guards an append-time-unreachable state

Plan P2.3-3 AC#7 lists, among cleanup cases: *"malformed metadata JSON (skip or raise — pin: skip a row whose metadata lacks the keys, since a connector contract violation should not break the reader; document)."* Two problems, both small:

1. **The state is unreachable by construction.** I verified `EventStore.append` calls `validate_metadata(event.type, event.metadata)` on **every** append (event_store.py:300; `append_in_transaction` at :273), and `ExternalValidationMeta(_BaseMeta)` is `frozen + extra="forbid"` (verified event.py:120). So an `external_validation` event with missing/extra/ill-typed metadata **raises `MetadataValidationError` at write time and never lands in the `events` table**. The reader therefore cannot encounter a row "whose metadata lacks the keys" — the only way such a row exists is if someone bypassed `EventStore.append` and raw-`INSERT`ed (which no code path does, and which would be a far deeper invariant break than this reader should paper over).

2. **"Skip" silently hides the one case that matters.** If a malformed `external_validation` row *did* somehow exist, it signals an upstream invariant violation (a connector or test bypassing `validate_metadata`). Silently skipping it is exactly the "fail-soft hides the bug" anti-pattern the project rejects elsewhere (cf. ADR-018's empty-tag `ValueError` — fail-loud on a producer bug). The senior's own instinct ("a connector contract violation should not break the reader") is reasonable for *runtime resilience* but wrong for *this* invariant, because the contract violation is already impossible through the sanctioned path — so the only time the branch fires is when something is genuinely broken.

**Why 🟡, not lower:** it's a single acceptance-criterion line, the impl is otherwise correct, and it has zero effect on the happy path. But an AC that specs a defensive branch for an impossible state (a) adds dead code, (b) bakes in a "skip" that would hide a real upstream break, and (c) reads as not-quite-understanding that append-time validation is the guard. Worth one routing beat to land it cleanly.

**Lean α:** drop the defensive skip from the reader. The reader should trust the append-time contract — it `json.loads` the metadata of events already validated at write. If the architect wants belt-and-suspenders, the correct shape is **raise (not skip)** on a metadata-parse failure, as a constitutional canary that surfaces an upstream bypass loudly (mirroring the project's fail-loud posture) — but my lean is to simply not spec the branch and note in the plan that `external_validation` metadata is guaranteed well-formed by `validate_metadata` at append. Either way, resolve the "skip or raise" the plan left open toward **not-skip**.

(Adjacent, non-blocking: P2.3-3 AC#2's reader does `SELECT metadata FROM events WHERE type='external_validation'` then `json.loads` each — that's correct and matches ADR-016 D6's no-JSON1 posture. The Y1 point is only about the *malformed* branch, not the parse itself.)

### 🟢 G1 — the Principle-5 reconciliation is correct (the load-bearing check)

This is the check the brief said matters most, and it holds. The ADR's framing — *judgment is **relocated**, not eliminated* — is the right resolution and is made explicit (ADR-019 Context + D1): the truth-call happens in a future connector **outside `memory/`**, which emits a typed `verdict`; `memory/` reads `verdict == "confirmed"` as an event-field, structurally identical to rule (b)'s `status == PENDING` (a column read) and rule (a)'s tag-set equality (pure code). **No LLM can enter `memory/` by this design** — the rglob constitutional guard covers `validation.py`, and the reader imports only `sqlite3` + `store`/`schema`. The "does the representation quietly require an LLM to populate `verdict` inside the boundary?" trap is avoided: `verdict` is populated by the connector (outside the boundary, possibly *by* an LLM-in-a-connector — which is fine, it's content-gen at the edge), and `memory/` only ever *reads* the typed result. This is Principle-5-clean by construction, and the ADR carries the "not-the-weak-matcher"-class reconciliation burden well.

### 🟢 G2 — representation (i) + pure-derivation: well-argued

The three deciding reasons for option (i) event over (ii) table / (iii) field are correct: **Principle 1** (external validation is a fact → the canonical append-only log, like a promotion `decision` event / a snapshot event — a `memory/` table would invert Principle 1 by putting a fact in a derived cache); **connector-decoupling** (a connector writes via `EventStore.append` — a stable core-only API — and never touches `memory/` internals; option (ii) would couple an external integration to `memory/` tables, backwards); **derive-don't-materialize** (ADR-015 D5 / ADR-016 D6 — rule (c)'s candidacy is a per-hypothesis existence check, not a batch computation worth caching like rule (a)'s grouping, so no flag/column/ALTER). The contrast with rule (a) (which *did* materialize a flag) is principled, not arbitrary. The materialized-flag Design A is correctly held as a forward hook (ADR-018 ALTER template) for when a UI needs an index-covered candidate union.

### 🟢 G3 — advisory orthogonality by construction; D10/D11 sound

Making rule (c) a pure reader is the cleanest possible answer to push-back #2: it **cannot** create a VK, flip a flag, or append an event, so orthogonality to D10 is structural, not a discipline to maintain. `promote_hypothesis` stays the sole VK actuator; D11 is genuinely moot (no multi-write). The D10-holds-regardless-of-signal-strength argument is correct and constitutional, not a strength judgment: promotion is a permanent user act (a VK row + a canonical `decision` event); advisory is reversible-by-ignoring; the signal's strength doesn't change the act's irreversibility; an auto-promoting connector would smuggle truth-judgment into automation — the exact Principle-5 + D10 violation rule (c) is most at risk of. Correctly surfaced as "if you ever want more, it's an explicit D10 amendment, not an impl choice."

### 🟢 G4 — confirmed-only + don't-touch-status + distinct provenance

Confirmed-only (#4) is the right bounded scope: `refuted`/`inconclusive` are still *recordable* (the enum admits them, so connectors aren't blocked) but rule (c) ignores them and **never mutates `status`** — correct, because `status == VERIFIED` is `promote_hypothesis`'s contract and conflating external-refutation into the lifecycle would break rule (b). Distinct provenance (#3) is preserved for free: the typed event carries `source`/`verdict`/`evidence_ref` (richer than a boolean), and rule (c) gets its own reader (`list_externally_validated_candidates`) distinct from `list_promotion_candidates` — so a future "all candidates" surface can badge by provenance. Both correct.

### 🟢 G5 — AST guard + discriminating determinism test carried forward

The plan reuses P2.2's `test_matcher_advisory_orthogonality_ast_guard` shape (a real `ast.walk` call/import check, **not** a whole-file substring scan — RC-24 honored), and the e2e determinism assertion uses the **discriminating** shape (assert the exact surfaced candidate set by stable content labels, not a count) — the exact P2.2 Y1→α lesson, correctly applied so this slice doesn't ship a "test that can't fail." Both prior-cycle lessons absorbed without being told.

### 🟢 G6 — every constitutional cite verified against source

I checked the load-bearing cites against `core/event.py` directly (not the plan's word):
- **"18 → 19"**: the `EventType` docstring literally says "The 18 constitutional event types" (event.py:69) and I counted exactly 18 members — so the increment is correct, not an off-by-one. ✓
- **"adding a type requires an ADR"**: present in the docstring verbatim — ADR-019 satisfies the gate. ✓
- **deliberate-duplication precedent**: `DecisionMeta.hypothesis_id: Annotated[str, Field(pattern=r"^hyp_[0-9a-f]{32}$")] | None` (event.py:156) is exactly the `str`-not-`HypothesisId` pattern ADR-019 mirrors for `validated_hypothesis_id` — so `core/` stays free of `memory/` imports and the constitutional guard holds. ✓
- **`TYPED_METADATA` + `validate_metadata`**: registry at event.py:322, validation runs on every `append` (event_store.py:300) — confirms both the registration site and (the Y1 point) that append-time validation is the real guard. ✓
- **no `len(EventType)` test**: consistent with the plan's claim that `test_schema.py` checks per-type mappings, so the addition won't break a count assertion. ✓

The plan's "verified against origin/main" claims are accurate — a notable contrast worth recording given recent cycles where a verification claim was not actually run; this one checks out.

## What the architect needs to route

1. **Y1 (🟡):** the reader's malformed-metadata branch (P2.3-3 AC#7) guards an append-time-unreachable state. Lean **α** — drop the defensive skip (trust append-time `validate_metadata`), or if belt-and-suspenders is wanted, **raise** (constitutional canary) rather than silently skip. Resolve the plan's open "skip or raise" toward not-skip.
2. **Greens** are affirmations; no action. The Principle-5 check — the reason this review existed — is clean.

ADR-019 is accept-worthy once Y1 is routed (it's a one-line acceptance-criterion precision, not a design change). R0-A-on-plan does not change state (RC-9 manual dispatch). Branch left checked out clean for the R0-B pass.
