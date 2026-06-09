# ADR-019: Promotion rule (c) — external ground-truth validation (event-represented, advisory pure-derivation)

**Status:** Accepted — 2026-05-31 (architect sign-off after R0-A-on-plan + R0-B-cross-family clean, Y1→α absorbed at d74da1e; Principle-5 boundary confirmed clean by both lenses; Proposed 2026-05-31, senior-drafted per P2.3 brief)

**Scope:** Locks promotion rule (c) — external ground-truth validation, the third and last rule of the `handoff.md` §4.5 promotion triad. Pins: the representation of "external validation happened" (a new `external_validation` EventType + `ExternalValidationMeta` in `core/`), the deterministic rule-(c) eligibility predicate (a pure-derivation reader in `memory/`), the advisory-only orthogonality to promotion (ADR-016 D10/D11 unchanged), the composition with rules (a)+(b), and the connector-producer deferral. Does NOT govern: external connectors that *produce* validation signals (out of scope — none exist), auto-promotion (forbidden by D10), `refuted`/`inconclusive` handling (forward hook), multi-source aggregation/trust-weighting (forward hook), or any LLM judgment (relocated to the connector, never in `memory/`).

## Context — Principle 5: validate truth WITHOUT an LLM judging truth

Rule (c) completes the promotion triad: (a) cross-room corroboration (ADR-017 `run_matcher`, advisory), (b) user-confirm (ADR-016 `promote_hypothesis`, the sole VK-creating actuator), (c) external ground-truth validation. It is the sharpest test of Principle 5 (`handoff.md` §3.1; ADR-016 Hard Requirements — `memory/` never calls an LLM, rglob-enforced) in the project, because "is this claim externally true?" *sounds* like exactly the judgment Principle 5 forbids `memory/` from making.

**The resolution is relocation, not elimination, of judgment** — and stating this is this ADR's load-bearing reconciliation (the same "not-the-weak-matcher" burden ADR-017 carried):

- The truth-judgment happens **outside `memory/` and outside this slice**, in a future external connector (a CI result, a paper's DOI resolving, a benchmark score, a curated dataset, a price feed — even an LLM-in-a-connector interpreting a tool result). That connector emits a **typed verdict** into the canonical event log.
- `memory/` then makes a **deterministic code decision over the typed verdict** — structurally identical to rule (b)'s eligibility (`status == PENDING`, a column read) and rule (a)'s grouping (canonical tag-set equality, pure code). Rule (c)'s decision is: *"a PENDING hypothesis H has an `external_validation` event with `verdict == confirmed` → H is an external-validation candidate."* An event-field read. No truth-judging in `memory/`.

The judgment lives in the connector; `memory/` reads its output as a typed field. This is Principle-5-clean by construction.

This ADR governs the constitutional invariants:
- **Principle 5** — rule (c) is pure code over a typed verdict; the verdict is produced elsewhere; `memory/` imports no LLM.
- **Principle 1 (event log is truth)** — external validation is a *fact/observation*; it belongs in the canonical append-only log (D1), not only a derived table.
- **D10 (no auto-promote, constitutional)** — rule (c) creates no VK and emits no promotion `decision` event (D3).
- **D11 (promotion atomicity)** — unaffected: rule (c) performs no multi-write (it is a pure reader, D2).
- **Principle 11 (determinism)** — same validation events → same rule-(c) candidate set, scan-order-independent.

## Decisions

### 1. Representation — an `external_validation` EventType + `ExternalValidationMeta` (in `core/`)

The canonical record of "external validation happened" is a new event in the append-only log (push-back #1, option (i)). `core/event.py` gains:

- `EventType.EXTERNAL_VALIDATION = "external_validation"` — the **19th** constitutional event type. Per the `core/event.py` convention ("adding a type requires an ADR"), **this ADR is that ADR**. The `EventType` docstring count and `docs/architecture/event-model.md` update from 18 to 19.
- `ExternalValidationMeta(_BaseMeta)` (frozen + `extra="forbid"`), registered in `TYPED_METADATA`:

```python
class ExternalValidationMeta(_BaseMeta):
    source: str = Field(min_length=1)                  # connector id, e.g. "ci", "doi-resolver"
    verdict: Literal["confirmed", "refuted", "inconclusive"]
    validated_hypothesis_id: Annotated[str, Field(pattern=r"^hyp_[0-9a-f]{32}$")]
    evidence_ref: str | None = None                    # optional pointer (URL, run id, ...)
```

`validated_hypothesis_id` is a pattern-validated `str`, **not** a `HypothesisId` import — the deliberate-duplication rule (`core/` MUST NOT import from `memory/`; ADR-014 D5 / ADR-016 D8 precedent: `DecisionMeta.hypothesis_id` does exactly this). The connector constructs the string; `memory/` reads it.

**Why an event (option (i)) over a `memory/` table (option (ii)) or a hypothesis field (option (iii)):**
- **Principle 1** — external validation is a real-world fact/observation. Facts belong in the canonical log, exactly as a promotion is a `decision` event (ADR-016 D8) and a snapshot is a `summary_snapshot` event (ADR-014). A `memory/` table (ii) would put a fact *outside* the canonical log, in a derived cache — a Principle-1 inversion.
- **Connector-decoupling (the integration-boundary argument)** — the brief's deciding criterion is "how does a connector *write* it without coupling to `memory/` internals?" With option (i) the connector calls `event_store.append(external_validation_event)` — it depends only on the stable `core/event_store` API and never touches `memory/`'s tables or schema. With option (ii) the connector would `INSERT` into a `memory/`-owned table, coupling an external integration to `memory/` internals — backwards. Option (i) gives every future connector a clean, stable, core-only integration surface.
- **Consistency** — reuses the existing event-metadata typing machinery (`TYPED_METADATA` + `validate_metadata`); no new persistence surface.
- Option (iii) (a field on Hypothesis) is rejected outright: nowhere to record `source`/`verdict`/`evidence`, and it conflates external-validation state into the Hypothesis row.

The cost — expanding the constitutional event vocabulary to 19 — is real but justified: `external_validation` is a genuine new event class (a source rendered a verdict), not a `generic_message` catch-all; the ADR gate is satisfied here.

### 2. Rule (c) decision function — a pure-derivation reader (the event is the surface; no flag, no table)

`src/orchestrator/memory/validation.py`:

```python
def list_externally_validated_candidates(conn: sqlite3.Connection) -> list[Hypothesis]:
    """PENDING hypotheses with >=1 confirmed external_validation event. Pure code, no LLM."""
```

It is a **pure derivation over the event log** — it writes nothing (push-back #3, "the typed record itself as the surface"): scan `external_validation` events, Python-parse each metadata (no JSON1 assumption — mirrors ADR-016 D6's lookup posture), collect `validated_hypothesis_id` where `verdict == "confirmed"`, then return the subset of those that are extant + `status == 'pending'` Hypothesis rows (via `store._row_to_hypothesis`), ordered by `id` ASC. Deterministic and scan-order-independent (the candidate set is a pure function of the events + hypothesis rows).

The reader does **no defensive metadata-shape handling** (Y1 → α): every stored `external_validation` event is **guaranteed well-formed by append-time `validate_metadata`** + `ExternalValidationMeta`'s `extra="forbid"` (a malformed event raises `MetadataValidationError` at `EventStore.append` and never lands), so a malformed row is unreachable through the sanctioned path. The reader trusts that contract. A malformed row could only arise from a raw `INSERT` bypassing `EventStore.append` — a deeper invariant break; any belt-and-suspenders guard must **raise** (a constitutional canary), never silently skip (fail-loud, per ADR-018 D4).

**Why derive, not materialize a flag** (the considered Design A — a distinct `externally_validated` column flipped by a `run_external_validation` batch function, symmetric with rule (a)'s `candidate_for_promotion`): the project materializes a derived cache only when a query-pattern or scale justification exists (ADR-015 D5 "derive don't materialize"; ADR-016 D6 "reshape when ≥2 query patterns"). Rule (a) materialized because cross-room grouping is an O(n) batch computation worth caching as a flag + index. Rule (c)'s candidacy is a simple per-hypothesis existence check over events — **no batch computation to cache, no second query pattern, no scale pressure**. So by the project's own materialization discipline, rule (c) derives. This also makes rule (c) the *minimal* contract (push-back #5): it inscribes only the EventType + meta + a reader — **no dormant write/flag machinery** to sit unused until connectors ship. The materialized flag (Design A) is a documented forward hook: add the `externally_validated` column (ADR-018 ALTER template) + a `run_external_validation` writer when a UI needs an index-covered union of rule-(a) and rule-(c) candidates, or when scale demands it.

**Confirmed-only this slice** (push-back #4): the reader filters `verdict == "confirmed"`. `refuted` / `inconclusive` events are still recorded in the canonical log (the verdict enum admits them, so a connector can write them), but rule (c) **ignores non-confirmed verdicts this slice** and **never mutates `status`** — `status == VERIFIED` means "promoted to VK" (set only by `promote_hypothesis`); conflating external-refutation into the status lifecycle would break rule (b)'s contract. Advisory-refutation (mapping `refuted` toward `REJECTED`/`STALE`) is a forward hook.

**Dangling references degrade gracefully**: a confirmed `external_validation` event whose `validated_hypothesis_id` references a non-existent or non-PENDING hypothesis simply yields no candidate (the hypothesis-row join filters it) — no error, no existence-check needed at this slice (there is no producer to validate against; the reader's join is the safety).

### 3. Advisory-only orthogonality — rule (c) writes nothing (D10/D11 unchanged)

Rule (c) is the **maximally advisory** surfacer: being a pure reader, it cannot create a VK, cannot flip a flag, cannot append an event, cannot emit a promotion `decision` event. Orthogonality to the promotion path is **by construction** — there is no write to misuse. `promote_hypothesis` (rule b) remains the **sole** VK-creating actuator; ADR-016 D10 (no auto-promote) and D11 (promotion atomicity) are untouched (D11 is moot — rule (c) performs no multi-write). The e2e (Scenario Z) asserts: after surfacing candidates, no VK row exists and no promotion `decision` event was emitted by rule (c); `promote_hypothesis` works on an externally-validated candidate **and** on an un-validated PENDING row (the signal does not gate promotion). An **AST orthogonality guard** over `validation.py` (per ADR-017 / P2.2 B→α — a real call/import AST check, NOT a whole-file substring scan; RC-24) inscribes this constitutionally.

**Why D10 holds regardless of signal strength** (push-back #2, surfaced honestly): rule (c) is arguably the *strongest* candidacy signal — external truth, not mere cross-room corroboration — which tempts a D10 exception ("if ground truth confirms it, why must the user still click?"). D10 holds anyway, and this is constitutional, not a strength judgment: promotion creates a permanent `VerifiedKnowledge` row + a canonical `decision` event (an irreversible user act in the audit trail); an advisory candidate is reversible-by-ignoring (cost of a false positive = a declined suggestion). The strength of the *signal* does not change the irreversibility of the *act*. A connector confident enough to auto-promote would be smuggling truth-judgment into an automated promotion — the exact Principle-5 + D10 violation this ADR exists to prevent. If a future cycle genuinely wants more than advisory, that is an explicit architect decision amending D10 — not an implementation choice.

### 4. Composition with rules (a) + (b) — distinct provenance, no conflation

The three rules stay orthogonal, with **distinct provenance** (push-back #3):
- **(a)** cross-room corroboration → the `candidate_for_promotion` flag (ADR-017).
- **(c)** external validation → `external_validation` events (this ADR) — surfaced by `list_externally_validated_candidates`.
- **(b)** user-confirm → `status == VERIFIED` + a VK row (ADR-016) — the only actuator.

Rule (c) does **not** reuse `candidate_for_promotion` (which would conflate "cross-room corroborated" and "externally validated" into one boolean, so a reader/UI could not tell *why* a hypothesis is a candidate). Provenance is preserved because the candidacy is carried by the typed `external_validation` event itself (`source` + `verdict` + `evidence_ref`) — strictly richer provenance than a boolean flag. A future "all promotion candidates" surface unions rule-(a) flags and rule-(c) derivations, badged by provenance.

### 5. Connector-producer deferred; rule (c) is dormant-until-fed by design

P2.3 ships the **contract** (the EventType + meta + the reader) — the integration boundary every future ground-truth connector binds to. The connectors that *produce* `external_validation` events (CI hooks, paper-DB lookups, benchmark runners, dataset checkers) are **out of scope**: no connector infrastructure exists (this is why rule (c) was deferred), and building one is its own slice (or P3). This mirrors rule (a) shipping the matcher but deferring the auto-tagging producer (ADR-017). Per Principle 9 (inscribe vocabulary before producers), completing the triad now fixes the promotion-eligibility contract every connector will bind to — the valuable, expensive-to-change-later part — while the minimal pure-derivation shape (D2) keeps the dormant footprint to a contract + a reader, with zero dead write machinery (the push-back #5 worth-it judgment).

### 6. Fresh ADR-019 (not an amendment)

Rule (c) is a standalone decision (the representation, the predicate, the advisory orthogonality). It reuses the next free number (016/017/018 taken). It is not an amendment to the closed/accepted ADR-016/017/018 — amending an accepted ADR risks the RC-23 accept-gate trap near its status region. ADR-019 cites ADR-016 D3/D10/D11 and ADR-017's advisory pattern as unchanged dependencies.

## Considered alternatives

- **(ii) A typed `ExternalValidation` record + table in `memory/`** (push-back #1). Rejected — the connector would couple to `memory/` internals (`INSERT` into a `memory/`-owned table) and the fact would live outside the canonical event log (Principle-1 inversion). Option (i) gives the connector a stable core-only surface and keeps the canonical log authoritative.
- **(iii) A signal field on the Hypothesis row** (push-back #1). Rejected — no room for `source`/`verdict`/`evidence`; conflates external-validation state into the Hypothesis schema.
- **Design A — materialize a distinct `externally_validated` flag** (a column + a `run_external_validation` batch writer, symmetric with rule (a)) (push-back #3). Considered and deferred — derive-don't-materialize discipline (ADR-015 D5): no batch computation to cache, no second query pattern, no scale pressure. Forward hook: materialize via ADR-018's ALTER template when a UI needs an index-covered candidate union or scale demands it.
- **Reuse `candidate_for_promotion`** (push-back #3). Rejected — conflates rule-(a) and rule-(c) provenance into one boolean.
- **Stronger-than-advisory / a D10 exception for rule (c)** (push-back #2). Rejected — constitutional; promotion is a permanent user act, advisory is reversible. Surfaced as an explicit architect call should it ever be wanted (would amend D10).
- **Map `refuted` → `status = REJECTED/STALE`** (push-back #4). Rejected this slice — `status` is `promote_hypothesis`/user territory; rule (c) must not mutate the lifecycle. Forward hook.

## Consequences

**Positive**:
- Completes the §4.5 promotion triad with the hardest Principle-5 reconciliation made explicit (judgment relocated to the connector; `memory/` reads a typed field).
- The cleanest external-integration boundary: connectors write to the canonical log via the stable `EventStore.append` API and never touch `memory/`.
- Maximally advisory + minimal footprint: a pure reader cannot violate D10, and the slice inscribes no dormant write/flag machinery.
- Distinct provenance preserved for free (the typed event carries `source`/`verdict`/`evidence`).

**Negative**:
- Expands the constitutional event vocabulary to 19 types — every event-type consumer/doc now considers one more type (a real, bounded maintenance cost; justified by the ADR gate).
- Dormant-until-fed: rule (c) surfaces nothing until a connector produces `external_validation` events — the third inscribed-but-unfed advisory mechanism (accepted per push-back #5 / Principle 9; mitigated by the minimal pure-derivation shape).
- The reader scans `external_validation` events with a Python metadata-parse (no JSON1) — O(events-of-that-type); fine at expected scale (mirrors ADR-016 D6 lookup); the materialized-flag forward hook is the reshape if scale demands.

**Reversibility**:
- Removing rule (c): easy — delete `validation.py` + the guard + the e2e; the EventType can stay (harmless unused) or be removed via an amendment (events are append-only, so an emitted type is permanent — prefer keeping it).
- Adding the materialized flag later (Design A): an ADR-019 amendment + an ALTER (ADR-018 template) + a `run_external_validation` writer; the reader's signature can stay.
- Adding `refuted`/`inconclusive` handling: an amendment; the verdict enum already admits them, so no schema change — only new consumer logic.

## Forward-amendment hooks

- **`refuted` / `inconclusive` handling**: advisory-refutation (surface toward `REJECTED`/`STALE`, or a "contested" surface) — a new consumer over the already-recorded verdicts; no schema change.
- **Multi-source aggregation / trust-weighting**: when multiple `external_validation` events per hypothesis need a policy ("3 confirm, 1 refutes"), add an aggregation predicate; the events already support multiplicity.
- **Materialized rule-(c) flag** (Design A): an `externally_validated` column + `run_external_validation` writer when a UI needs an index-covered candidate union or scale demands materialization.
- **Connector slice**: the external producers (CI/paper-DB/benchmark/dataset) — their own slice/ADR; they bind to this ADR's event contract.
- **Producer-side existence check**: if a connector needs write-time validation that `validated_hypothesis_id` exists, a `memory/` helper the connector calls (cross-layer); deferred (no producer this slice).

## Cross-references

- `handoff.md` §4.5 (promotion triad — rule (c) the last; "外部 ground truth 验证 — deferred to P2+" now materialized), §3.1 (code-decides, no LLM in `memory/`).
- `docs/decisions/ADR-016-cross-room-memory-persistence.md` (closed/accepted) — D3 (rule (b) eligibility = `status == PENDING`, the code-predicate precedent rule (c) mirrors), D8 (`decision` event on promotion — the event-as-canonical-fact precedent), **D10** (no auto-promote — UNCHANGED, constitutional), **D11** (promotion atomicity — moot here, rule (c) writes nothing). `promote_hypothesis` = sole VK path.
- `docs/decisions/ADR-017-cross-room-hypothesis-matcher.md` (closed/accepted) — rule (a) advisory-only orthogonality + the AST orthogonality guard shape rule (c) reuses; the materialize-vs-derive contrast (rule (a) materialized a flag for batch-grouping/index; rule (c) derives).
- `docs/decisions/ADR-018-cross-room-tag-registry.md` (closed/accepted) — the ALTER-migration template (for the Design-A materialized-flag forward hook) + transaction-neutral posture.
- `docs/decisions/ADR-014-snapshot-contract.md` / `ADR-015-decision-log-shape.md` — derive-don't-materialize precedent (D2) + event-as-canonical-fact (snapshot event).
- `src/orchestrator/core/event.py` — `EventType` (+ `EXTERNAL_VALIDATION`), `TYPED_METADATA` (+ `ExternalValidationMeta`), the deliberate-duplication `str | Field(pattern=...)` id pattern (`DecisionMeta`).
- `src/orchestrator/core/event_store.py` — `append` (the connector's write surface); `events.metadata` is JSON `TEXT`.
- `src/orchestrator/memory/{promotion.py,matcher.py,store.py}` — `promote_hypothesis` (sole actuator), `run_matcher` (advisory precedent), `_row_to_hypothesis` (reused by the reader).
- `tests/memory/test_constitution.py` — no-LLM rglob (covers `validation.py`) + `test_matcher_advisory_orthogonality_ast_guard` (the AST shape rule (c) reuses).
- `docs/retrospectives/P2.2-candidates.md` RC-23/RC-24 (substring-scan fragility — ADR-019 prose + the guard avoid). `docs/process/dual-lens-r0b.md` RC-15/RC-20.
- **P5.1a / ADR-041 name-collision note:** `src/orchestrator/sources/` (ADR-041 D4) is the pipeline *read-input* abstraction (web/rss/file → text for analysis). It is the **opposite direction** from `connectors/` — `connectors/` is ground-truth *output*, `sources/` is data *input*. See `docs/architecture/sources-vs-connectors.md`.
