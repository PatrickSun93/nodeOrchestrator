---
task_id: P2.4
kind: architect-routing
date: 2026-06-01
reviews_acked:
  - R0-A-on-plan.md
  - R0-B-cross-family.md
decisions:
  Y1: α (absorb a lightweight structural/AST guard for the Principle-11 no-inferred-prefs invariant THIS cycle — not deferred to P2.6)
  Y2: α (preferences upsert-by-(user_id, key[, scope]); general entities stay plain-insert; re-add the brief's dropped duplicate-create test to lock the upsert semantic)
  ProjectArchive_persist: ratified (formal accept at ADR-020)
---

# P2.4 architect routing — Y1 → α, Y2 → α; ProjectArchive persist ratified

**Architect decision (this session):** both plan-stage 🟡 findings — flagged by *both* lenses (R0-A-on-plan + R0-B-cross-family, two-lens overlap, high-confidence) — resolve to **α (absorb)**. The ProjectArchive persist-vs-derive headline is **ratified** (both lenses confirmed persist with no dissent; formal accept happens at the ADR-020 status bump).

This file is the **signal artifact for the senior revision session.** Senior picks P2.4, reads this + `R0-A-on-plan.md` + `R0-B-cross-family.md` + the current plan + ADR-020, applies the routed actions, and pushes a revision commit on `claude/P2.4-plan`. Then the architect accepts ADR-020 (status bump) — the accept-gate gates `awaiting_architect_accept → awaiting_junior_impl`.

**Principle-11 boundary status (the lead constitutional check):** *no leak found.* Both lenses confirmed the no-inferred-prefs boundary is **code-enforced for this slice** — `record_preference` requires `user_id`, `record_entity` rejects `type=PREFERENCE`, and the baseline has zero pre-existing entity write paths. Y1 is not a present leak; it hardens the invariant against a *future* third write path.

## Per-finding routing

### Y1 → α — lightweight structural guard for the no-inferred-prefs invariant (this cycle)

**Problem (R0-A Y1 + R0-B Y1, confirmed):** ADR-020 D2 claims an inferred preference is "un-representable," but that guarantee rests on two *behavioral* unit tests on two functions. A future raw `INSERT INTO entity type='preference'` (e.g. the P2.6 producer) or a new `memory/` module constructing `Entity(type=PREFERENCE)` would bypass both, tests staying green. The project's established pattern for constitutional "must-not-X" invariants is a structural AST guard (`test_constitution.py:63-131`, matcher + validation); ADR-020 D5 declined one on "no actuation invariant" grounds, which answers a different question.

**Action (absorb THIS cycle — explicitly not deferred to P2.6):**
- Add a **lightweight structural guard** in `tests/memory/test_constitution.py` that the Principle-11 invariant cannot be bypassed by a future write path. **Senior designs the exact shape** — r0b's candidate is an AST check that `EntityType.PREFERENCE` is referenced only within `entity.py`'s preference functions; an equivalent structural enforcement (e.g. a store-layer assertion that any `type='preference'` row carries `evidence.declared_by`) is acceptable if senior judges it sturdier. Match the existing AST-guard idiom (real AST nodes, not whole-file substring — RC-24).
- **ADR-020 D5**: revise from "no new guard" to record the routed structural guard + its rationale (Principle 11 is absolute; first preference surface; consistency with the matcher/validation precedent). This is an ADR substance change folded into the senior's revision before accept.
- **Plan §2 / §4**: reflect the guard in the relevant atomic's acceptance + the forcing-functions list.

### Y2 → α — preferences upsert-by-(user_id, key[, scope]); entities stay plain-insert

**Problem (R0-A Y2 + R0-B Y2, confirmed; R0-B's data-model framing adopted):** `record_preference` as plain-insert creates a new row per call, so two `(user_id, "response_style")` calls yield two rows with no deterministic current-value resolution. Preferences semantically ARE a key-value settings map; an append-only log pushes latest-wins dedup onto every consumer. (General *entities* as an append-only fact log is correct.)

**Action (absorb THIS cycle):**
- **`record_preference`**: upsert by **`(user_id, key[, scope])`** — exactly one row per preference key per user (per scope), so the current value is deterministic by construction. Implementation shape (unique constraint + `INSERT … ON CONFLICT … DO UPDATE`, or read-modify-write in the existing transaction posture) is senior's call.
- **`record_entity`**: **stays plain-insert** (append-only; entities accumulate). The split is deliberate — entities log, preferences map.
- **Re-add the brief's dropped duplicate-create test** (brief §test-coverage 2/3) to **lock the upsert semantic**: a second `record_preference(same user_id, same key, new value)` updates in place → `list_preferences` surfaces exactly one row with the latest value + the declaring user's provenance. (A parallel entity duplicate-create test asserting *two* rows pins the append-only contract for entities.)
- **ADR-020 D2**: state the preference upsert-by-`(user_id, key[, scope])` data model explicitly (vs the current silence on uniqueness); keep prefs-as-entity-rows (D2 unchanged on that).

### ProjectArchive persist → ratified

**No change required.** Both lenses confirmed ADR-020 D3 (persist, not derive) — captured-at-close frozen snapshot that must outlive event compaction/edits; genuine disanalogy with ADR-015's live within-room derive-view. The architect ratifies; persist is formally accepted at the ADR-020 status bump. Senior keeps D3 as-is.

## Non-routing fold-ins (R0-A minor notes — senior's discretion, no α/β/γ)

Optional to absorb during the same revision (hygiene, not routed): M1 (`memory/`-no-import-`derived/` is asserted but unguarded — leave or make explicit), M2 (`entity_id` not reserved on ProjectArchive — acceptable; relations are a forward hook), M3 (`user_id` min_length is a function-body check, not a model field — ensure the impl validates explicitly; Y1's guard reinforces this), M4 (`memory/__init__.py` re-exports + `test_schema.py` enum/default updates — caught by the P2.4-6 5-surface scan). No other findings; ADR-020 is accept-worthy once the Y1 + Y2 revision lands.
