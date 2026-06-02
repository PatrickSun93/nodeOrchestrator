# ADR-022: Feeding the dormant promotion rules — tagging producer (rule a) + external connectors (rule c) + refuted handling

**Status:** Accepted — 2026-06-01 (architect-accepted after plan-stage dual-lens reviews clean: R0-A-on-plan + R0-B-cross-family both `clean`; c2 → α structural AST guard (ExternalValidationMeta only in connectors/_emit.py), c1 → α-lite tagging selection guard, Y2 overwrite; boundary confirmed code-enforced)

**Scope:** Ships the **first producers/connectors** that feed the dormant promotion rules on real data: **(B1)** a rule-a **tagging producer** (LLM content-gen → `Hypothesis.topic_tags` → `run_matcher`), **(B2)** rule-c **external connector(s)** (externally-grounded verdicts → `external_validation` events → `list_externally_validated_candidates`), and **(B3)** **refuted/inconclusive handling** (an advisory `memory/` reader, no status mutation). Pins: the producer/connector contracts, the content-gen-vs-judgment boundary (c1), the connector-verdict external-grounding guarantee (c2), the new content-gen `LLMPurpose` (`HYPOTHESIS_TAG_PROPOSAL`), and the refuted handling. **One slice with parallel atomics** (prelude → B1∥B2∥B3 → e2e; architect-decided). Does NOT govern: the rule readers (`run_matcher`/`list_externally_validated_candidates` — unchanged), multi-source aggregation/trust-weighting, a user-confirm reject actuator (forward hooks), or P2.7.

## Context — Principle 5 + Principle 11, a fifth time: producers generate/interpret; code + external ground truth decide

P2.1–2.3 built promotion rules a (cross-room matcher) and c (external validation); both shipped **dormant** — `run_matcher` excludes untagged hypotheses (`matcher.py:72`, empty canonical set), and `list_externally_validated_candidates` returns nothing until a connector produces `external_validation` events. P2.6 ships the producers that feed them — the **first producers in the project** — making this the sharpest test yet of *where content-gen ends and judgment begins*. The recurring rule applies a **fifth time** and this ADR settles it as a hard boundary:

- **Code + external ground truth decide; the LLM only generates content or interprets external evidence.** Nothing inferred becomes durable without code-derivation-from-canonical-facts or user-confirm (generalized D10). Producers/connectors live **outside `memory/`** (the no-LLM rglob is preserved; the rule readers stay pure code).
- **(c1, B1)** Generating descriptive `topic_tags` is **content-gen** (keyword extraction — like `HYPOTHESIS_CANDIDATE`/`TERM_DEFINITION_PROPOSAL`: LLM proposes, code/human disposes). It would cross into **judgment** if the LLM decided *which* hypotheses match/promote, *ranked* them, or chose tags *to make a hypothesis promotable*. The boundary (D3): LLM emits **descriptive** tags → deterministic `resolve_tags` normalizes/registers (ADR-018) → `run_matcher`'s deterministic grouping → **advisory** `candidate_for_promotion` (ADR-016 D3/D10 — not a promotion precondition) → **rule-b user-confirmed** promotion. The LLM never makes the durable-knowledge decision.
- **(c2, B2)** ADR-019 explicitly permits an LLM-in-a-connector interpreting a tool result, so the boundary is **not** "no LLM in connectors" — it is **interprets-external-evidence (grounded) vs judges-the-bare-hypothesis (drift, Principle 11)**. The anchor is `evidence_ref` (D4): every connector verdict traces to real external evidence; an LLM, if used, interprets that **evidence**, not the bare hypothesis.

This ADR governs: Principle 5 (no LLM in `memory/`; producers/connectors outside it), Principle 11 (no LLM selection/ranking/gating; no auto-durable-from-inference — candidacy advisory, promotion user-confirmed), the no-status-mutation constraint for rule-c (B3, ADR-019 push-back #4), and the EventStore-append-only invariant for `external_validation` events (the `validation.py` fail-loud canary).

## Decisions

### 1. Placement — new `producers/` + `connectors/` packages; B3 a `memory/` sibling reader

The producers/connectors compose `memory/`/`core/`/`llm/` and (B2) external I/O, so they **cannot live in `memory/`** (the no-LLM rglob). New top-level packages:
- **`src/orchestrator/producers/`** — B1's `tagging.py` (the LLM tagging producer).
- **`src/orchestrator/connectors/`** — B2's emit helper + the demo connector.
- **B3** is a sibling reader in **`memory/validation.py`** (pure code, no LLM — it belongs with the rule-c reader it parallels).

**Dependency direction**: `producers/` + `connectors/` import `memory/`/`core/`/`llm/`; **`core/`, `memory/`, `derived/`, `llm/` MUST NOT import `producers/` or `connectors/`** — a constitutional AST/import guard (mirroring the `reentry/` no-upstream-import guard, ADR-021). The producers are leaf consumers.

### 2. One slice, parallel atomics (architect-decided)

P2.6 ships as **one slice** under one ADR-022, with a sequential **prelude** (this ADR + the new `LLMPurpose` + package scaffolding) → **B1 ∥ B2 ∥ B3** (disjoint file footprints, parallelizable across worktrees/subagents) → **e2e + landing** (reconcile). The only shared file (`llm/purposes.py`) is fully resolved in the prelude (D6), so the parallel blocks never co-edit it. The plan §3 pins the dependency graph + file boundaries.

### 3. (c1) B1 tagging producer — descriptive content-gen; the LLM never selects/ranks/gates

`producers/tagging.py`: `propose_hypothesis_tags(hypothesis, source_events, *, llm_router) -> list[str]` — a content-gen LLM call (new `LLMPurpose.HYPOTHESIS_TAG_PROPOSAL`, D6) that reads a hypothesis + its source events and emits **descriptive candidate `topic_tags`** (raw strings). It does **not** match, rank, select, or decide promotability — it describes. The pipeline then proceeds entirely in deterministic code + human:

```
propose_hypothesis_tags (LLM, descriptive)  →  resolve_tags (code, normalize/register, ADR-018)
  →  run_matcher (code, group by canonical tag-set, flag candidate_for_promotion across ≥2 rooms)
  →  advisory candidate (ADR-016 D3/D10 — NOT a promotion precondition)  →  promote_hypothesis (rule-b, user-confirmed)
```

The LLM is one step (tag proposal); every downstream decision (which group, which candidate, which promotes) is code or the user. So the LLM never makes the durable-knowledge decision (generalized D10).

**Applying the tags — two write paths** (push-back: at-creation vs retro; pinned **both**):
- **At creation** — the producer proposes tags before `record_hypothesis(content, …, topic_tags=resolved)` (the existing write path, ADR-018; resolves via `resolve_tags`).
- **Retro-tag-update** — for the **dormant existing untagged** hypotheses (the ones already in the store that `run_matcher` ignores), a new minimal `memory/store.py::update_hypothesis_tags(hyp_id, *, topic_tags, conn)` routes the proposed tags through `resolve_tags` and updates the row's `topic_tags` (mirroring the registry's resolve-then-store posture). This is the path that actually *feeds the dormant mechanism* (tags hypotheses already recorded untagged). It is a deterministic `memory/` write (no LLM in `memory/`; the producer supplies the raw tags from outside). **Semantics = overwrite** (Y2, senior fork): re-tagging an already-tagged hypothesis **replaces** the row's `topic_tags` with the new resolved canonical set (latest-wins) — not merge/append; the simplest "update the row's tags", and moot for the dormant-untagged case the e2e exercises.

**c1 structural guard (belt-and-suspenders; α-lite)**: c1's boundary is already fail-safe by chain (per-hypothesis tagging cannot force a grouping; `run_matcher` needs ≥2 independent rooms; candidacy is advisory; `promote_hypothesis` requires a `user_id`). A **lightweight constitutional AST guard** (real AST, RC-24; mirrors the `reentry/` LLM-free-selection + the `EntityType.PREFERENCE` idiom) adds symmetric defense-in-depth: the tagging producer (`producers/`) **references no selection/promotion/gate symbols** — none of `run_matcher`, `promote_hypothesis`, `list_promotion_candidates`, or a `candidate_for_promotion` write — proving structurally that the producer **proposes descriptive tags only** and never matches/ranks/gates. Discriminating (a planted `run_matcher(...)`/`promote_hypothesis(...)` reference in `producers/` trips it).

### 4. (c2) B2 external connector — verdict is `evidence_ref`-anchored; EventStore-append-only

`connectors/` produces `external_validation` events whose verdict is **derived from external evidence**, anchored by `evidence_ref`. The structural enforcement is a connector-side emit helper (`connectors/_emit.py`):

```python
def emit_external_validation(event_store, *, room_id, source, verdict, validated_hypothesis_id,
                             evidence_ref: str) -> EventId:
    """Append an external_validation event. evidence_ref is REQUIRED + non-empty."""
    if not evidence_ref:
        raise ValueError("evidence_ref is required + non-empty — a verdict must trace to external evidence")
    # constructs ExternalValidationMeta + Event, then event_store.append(...)
```

- **`evidence_ref` required + non-empty + external-source-pointing** — the connector contract (the emit helper raises on empty), mirroring promotion's required `user_id` (ADR-016 D8) / `record_preference`'s required `user_id` (ADR-020). Every connector verdict thus traces to real external evidence (a CI result, a DOI, a benchmark, a dataset entry, a price feed — or an LLM reading *that* evidence). *(The `ExternalValidationMeta.evidence_ref` field stays `str | None` for backward-compat with ADR-019's existing test-injection path; the **connector contract** — the emit helper — requires it. A future schema-level tightening of the meta is a forward hook, deferred to avoid touching the closed ADR-019/core for this slice.)*
- **Verdict derives from evidence** — never from judging the bare hypothesis. If a connector uses an LLM, it interprets the **evidence** referenced by `evidence_ref` (content-gen — `EXTERNAL_EVIDENCE_INTERPRET`, a forward-hook purpose added when such a connector ships), never the bare hypothesis (that would be Principle-11 drift).
- **EventStore.append only — never raw-INSERT.** The emit helper appends via `event_store.append` (→ `validate_metadata` + `ExternalValidationMeta` `extra="forbid"`). Connectors never raw-`INSERT` into the events table — the `validation.py` reader is a fail-loud canary (it `meta["verdict"]`-subscripts, raising on a malformed bypass; ADR-019 / P2.3 Y1→α).
- **c2 structural guard — the emit helper is the sole `ExternalValidationMeta` construction site** (c2 → α). Because `ExternalValidationMeta.evidence_ref` stays `str | None` (the schema is unchanged — D-Consequences forward hook; no closed-ADR-019 edit), the `evidence_ref`-required check lives in `emit_external_validation` and would be bypassable by a future connector constructing `ExternalValidationMeta(…, evidence_ref=None)` directly + appending (it passes `validate_metadata`, the verdict-only canary, and the import guard → an **ungrounded durable verdict**). A **constitutional AST guard** (real AST, RC-24; mirrors the `EntityType.PREFERENCE` construction guard) asserts that `ExternalValidationMeta(...)` is **constructed only in `connectors/_emit.py`** (+ test files) — making the emit helper's `evidence_ref` required+non-empty check **unbypassable** (every connector verdict must go through it). Discriminating (a planted `ExternalValidationMeta(...)` in any other `src/` file — e.g. `connectors/dataset_check.py` constructing it directly instead of calling the helper — trips it). Schema-level `evidence_ref` tightening remains a forward hook (Consequences).

**Demo connector — deterministic (the cleanest demo)** (push-back: which connector): `connectors/<source>.py` is a **deterministic ground-truth/dataset-check** connector — given a hypothesis + a curated external dataset, it deterministically derives a verdict (`confirmed`/`refuted`/`inconclusive`) and sets `evidence_ref` to the dataset entry it matched. **No LLM** — the cleanest demonstration that the verdict is externally grounded (no judgment surface at all). The c2 LLM-interprets-evidence path is the documented forward hook.

### 5. (B3) refuted/inconclusive handling — an advisory reader; rule-c never mutates status

The hard constraint (ADR-019 push-back #4, **unchanged**): rule-c **never mutates `status`** (status is `promote_hypothesis`/user territory; conflating external-refutation into the lifecycle would break rule-b). So B3 is **advisory**: a sibling reader `memory/validation.py::list_refuted_candidates(conn) -> list[Hypothesis]` — PENDING hypotheses with ≥1 `external_validation` event where `verdict == 'refuted'` (mirroring `list_externally_validated_candidates`'s structure for `confirmed`). Pure code, no LLM, **no status mutation** — it surfaces refuted candidates for the user to review (badged by provenance), exactly as the confirmed reader surfaces promotion candidates. (Inconclusive verdicts are recorded in the canonical log and queryable via the same scan; a dedicated inconclusive surface has no actionable advisory — neither promote nor reject — so it is a forward hook.)

The **user-confirm reject path** (a hypothesis whose status moves to `REJECTED` after a user confirms an external refutation) is **deferred** (push-back: advisory vs reject-path). It would be a new promotion-lifecycle *actuator* — the inverse of `promote_hypothesis`, user-confirmed — and is the **only** way a refuted verdict could touch status without violating the no-auto-mutation constraint. That actuator is a standalone surface (its own slice, symmetric to `promote_hypothesis`); B3 ships the advisory reader, which is the minimal constraint-respecting feeding of the refuted signal.

**B3 lives in ADR-022, not an ADR-019 amendment** (push-back: amend vs new ADR): ADR-019's confirmed-path contract (confirmed-only, no-status-mutation) is **unchanged**; B3 *adds* a sibling reader per ADR-019 push-back #4's forward hook. No closed-ADR edit (RC-23-safe).

### 6. New content-gen `LLMPurpose` — `HYPOTHESIS_TAG_PROPOSAL` (added in the prelude)

`LLMPurpose.HYPOTHESIS_TAG_PROPOSAL = "hypothesis_tag_proposal"` is added to `llm/purposes.py` (adding a purpose requires an ADR — this is that ADR). It is **content-gen** (descriptive tag extraction), the only new LLM surface this slice, confined to `producers/tagging.py`. It is added in the **prelude** (D2) so the parallel B1/B2/B3 blocks never co-edit `purposes.py`. The demo connector (D4) is deterministic, so B2 adds **no** purpose this slice; the LLM-evidence-interpret path's `EXTERNAL_EVIDENCE_INTERPRET` is a forward hook (added when an LLM connector ships). (No `LLMPurpose`-exhaustiveness/usage test exists — verified — so adding the value is safe.)

### 7. Fresh ADR-022 (not an amendment)

ADR-022 reuses the next free number (016–021 taken). It is not an amendment to ADR-017/019 (both closed/accepted) — it ships the producers those ADRs forward-hooked, citing them as unchanged dependencies (rule-a/rule-c readers unmodified; ADR-019 push-back #4 fulfilled additively).

## Considered alternatives

- **Split into P2.6a/b/c** (push-back a). Architect-decided: one slice, parallel atomics.
- **B1 at-creation only** (no retro path) (push-back). Rejected — the *dormant* hypotheses are already recorded untagged; without `update_hypothesis_tags` they stay invisible to `run_matcher`. Both paths ship.
- **B2 LLM connector demo** (push-back). Rejected for the demo — a deterministic ground-truth connector is the cleanest proof of external grounding (zero judgment surface); the LLM-interprets-evidence path is a documented forward hook.
- **Schema-level `evidence_ref` required** in `ExternalValidationMeta` (push-back c2). Rejected for this slice — would amend the closed ADR-019 + touch `core/event.py` (shared with the existing test-injection path); the connector-contract (emit helper) enforces it without that churn. Forward hook.
- **B3 user-confirm reject path** (push-back). Deferred — a status-mutating actuator is a standalone surface (inverse of `promote_hypothesis`); B3 ships the advisory reader, within ADR-019's no-status-mutation constraint.
- **Amend ADR-019 for B3** (push-back). Rejected — B3 adds a sibling reader; ADR-019's contract is unchanged; ADR-022 pins it (no closed-ADR edit).
- **B1 LLM selects/ranks tags or gates promotability** (c1). Rejected outright — Principle 11; the LLM emits descriptive tags only, matching/candidacy/promotion are code/human.

## Consequences

**Positive**:
- The dormant rules a + c fire on real producer data — the promotion triad is finally end-to-end (producer → rule reader → user-confirm), closing the deferrals from P2.1–2.3.
- The constitutional boundary is drawn precisely + structurally enforced: descriptive-tags content-gen (the LLM never decides promotion), evidence-anchored verdicts (emit helper requires `evidence_ref` + appends only), no-status-mutation refuted handling.
- The slice parallelizes cleanly (disjoint footprints) for faster delivery.

**Negative**:
- Two new top-level packages (`producers/`, `connectors/`) + a new `memory/` write path + a new reader — real surface, mitigated by the disjoint split + the deterministic demo connector.
- The c2 `evidence_ref` requirement is connector-contract-enforced, not schema-enforced (a future raw constructor could omit it) — the emit helper + the EventStore-append-only canary are the guards; schema tightening is a forward hook.

**Reversibility**:
- Dropping a block: each is independent (delete the package/reader); the rules revert to dormant.
- Tightening `evidence_ref` to schema-required later: an ADR-019 amendment + a `core/event.py` change.

## Forward-amendment hooks

- **LLM-interprets-evidence connector** — adds `LLMPurpose.EXTERNAL_EVIDENCE_INTERPRET` (content-gen) + a connector that reads the evidence referenced by `evidence_ref`.
- **User-confirm reject actuator** — a status-mutating (`→ REJECTED`) user-confirmed surface, symmetric to `promote_hypothesis`, consuming B3's refuted reader.
- **Schema-required `evidence_ref`** — tighten `ExternalValidationMeta` (ADR-019 amendment).
- **Multi-source aggregation / trust-weighting** — when multiple verdicts per hypothesis need a policy.
- **More connectors** — CI, DOI, benchmark, price-feed — each via the emit helper.
- **Inconclusive surface** — a dedicated reader if a consumer needs the "checked-but-unresolved" set.

## Cross-references

- `handoff.md` §4.5 (promotion triad — the producers feed rules a/c), §3.1 (code-decides, no LLM in `memory/`), §7 (P2.6 in the P2.1→P2.7 序; the §7 P2.5 row may read a stale status — flagged, not corrected here).
- `chat-history.md` (the promotion triad + "dormant-until-fed"; Principle 11 no-LLM-judgment-without-ground-truth).
- `docs/decisions/ADR-017-cross-room-hypothesis-matcher.md` (rule-a `run_matcher` + the auto-tagging-producer deferral B1 fulfills); `ADR-019-external-ground-truth-validation.md` (rule-c contract; push-back #4 refuted forward hook B3 fulfills; line 13 LLM-in-connector permitted — the c2 basis; the EventStore-append-only canary); `ADR-016` (D3/D10 advisory candidacy / no-auto-promote / required `user_id` precedent); `ADR-018` (`resolve_tags` normalization B1 routes through).
- `src/orchestrator/memory/{matcher.py:72,validation.py,tags.py,store.py}` (rule-a/rule-c readers + the tag write path; `record_hypothesis(topic_tags=…)`; `resolve_tags`); `src/orchestrator/core/event.py` (`ExternalValidationMeta`, `EventStore.append`); `src/orchestrator/llm/purposes.py` (content-gen taxonomy + `HYPOTHESIS_TAG_PROPOSAL`).
- `tests/memory/test_constitution.py` / `tests/reentry/test_constitution.py` (the no-LLM rglob + the AST import-guard idiom the `producers/`/`connectors/` guard mirrors).
- `docs/process/dual-lens-r0b.md` RC-15 (dual-lens dispatched), RC-20; `docs/process/distance-test.md` RC-8; `docs/retrospectives/P2.2-candidates.md` RC-23/RC-24/RC-25.
