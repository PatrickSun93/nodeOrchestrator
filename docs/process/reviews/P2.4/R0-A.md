---
task_id: P2.4
round: R0-A
verdict: needs_architect
findings_count:
  red: 0
  yellow: 2
  green: 11
verdict_history:
  - verdict: needs_architect
    at_commit: 68fcedf
    findings_count: { red: 0, yellow: 2, green: 11 }
    note: initial R0-A (impl-stage, architect-partner in-family lens); gates fully green (ruff+format+mypy --strict 141 files + pytest 1063 passed); 2🟡 are both "invariant weaker than the ADR claims but does not manifest under the current single-connection model" — architect routes fix-now vs defer.
---

# P2.4 R0-A (impl-stage, architect-partner in-family lens)

| Field | Value |
|---|---|
| Commit reviewed | `68fcedf` (`origin/claude/P2.4-impl` tip) |
| ADR | ADR-020 **Accepted** (Y1→α + Y2→α absorbed; persist ratified) |
| Lens | In-family (Claude). Principle-5, Principle-11 (Y1 guard incl. **active planted-bypass test**), decision_trace, 5-surface drift, upsert correctness, migration idempotency. contributing.md Q1–Q5. |
| Reviewed in | Isolated git worktree at `68fcedf` — see "Workspace note" (the shared checkout was mid-operation on `main`; I did not touch it). |
| Gates | **All green** (run in worktree): `ruff check` ✅ · `ruff format --check` ✅ (141 files) · `mypy --strict` ✅ (141 source files) · `pytest` ✅ **1063 passed** (matches the impl commit's claim, 0 fail / 0 skip). |

## Verdict: needs_architect

The implementation is **faithful, correct under the current usage model, and fully gated**. Both routed findings landed as specified: the Y1 Principle-11 AST guard exists and I **proved it fails on a planted bypass**; the Y2 preference upsert + the brief's duplicate-create lock-test are present and discriminating. Principle 5 holds (no-LLM rglob covers the new files; `memory/` does not import `derived/`). Migration is idempotent. The e2e is cross-room and discriminating.

**Two 🟡 need an architect call** — both are the same shape: *an invariant the ADR states absolutely is enforced only under the current single-connection / idiomatic-construction model, with a residual hole that does not manifest today.* Neither blocks; the architect routes fix-now vs defer.

## Findings

### Y1 🟡 — the Principle-11 AST guard closes the construction path but not the raw-SQL path (proven both ways)

The Y1→α guard (`tests/memory/test_constitution.py:210` `test_principle_11_preference_ast_guard`) flags `EntityType.PREFERENCE` used as an `ast.Attribute` outside the allowed `(entity.py, {record_preference, record_entity, list_preferences})` set. I verified it **live**, not by inspection:

- **Plant A — attribute form.** Inserted `_planted_bypass = EntityType.PREFERENCE` into `store.py:_row_to_entity` (a non-allowed location) → guard **FAILED** precisely: `line 302: EntityType.PREFERENCE in store.py:_row_to_entity (not in allowed set)` (exit 1). Revert → **PASS** (exit 0). So the guard **is discriminating** for the construction bypass — the architect's explicit question is answered **yes**.
- **Plant B — raw-SQL form.** Inserted a string literal `"INSERT INTO entity (... type ...) VALUES ('p', 'preference', ...)"` into `store.py` (no `EntityType.PREFERENCE` attribute node) → guard **PASSED** (exit 0). So a future producer that writes a preference row via **raw SQL** (the most realistic out-of-`memory/` bypass) is **not** caught.

The two sibling guards (`test_matcher_advisory_orthogonality_ast_guard`, `test_validation_advisory_orthogonality_ast_guard`) **do** check string-literal SQL (`ast.Constant` containing `INSERT INTO verified_knowledge`). The Y1 guard omits the analogous check, so by the project's own precedent it is the *lighter* of the two available shapes — which the routing explicitly contemplated ("a store-layer assertion that any `type='preference'` row carries `evidence.declared_by` is acceptable if senior judges it sturdier"). The junior implemented the named lighter candidate correctly; the residual hole is a property of that choice, not a deviation.

**Lean (surface, not decide):** extend the guard to also flag an `INSERT INTO entity` string-literal carrying `'preference'` outside the allowed functions (mirrors the sibling guards), **or** adopt the sturdier store-layer `declared_by` assertion that catches any write path. **Architect: α (harden the guard this cycle) / β (accept construction-only coverage + document the limitation in ADR-020 D5) / γ (defer to the P2.6 producer)?** The ADR-020 D2 "un-representable" wording currently overstates what the guard enforces — whichever way you route, that sentence should be reconciled with the actual coverage.

### Y2 🟡 — the preference upsert is correct sequentially, but the read-modify-write is non-atomic (and `created_at` is overwritten on update)

`record_preference` (`entity.py:107`) is the routed upsert-by-`(user_id, key, scope)`. The **sequential** semantic is correct and discriminating-tested (`test_entity.py:227` asserts 1 row + latest value; `test_different_scopes_are_distinct_upsert_keys:268` confirms scope is part of the key; the append-only contrast for `record_entity` is locked at `:98`). Two sub-issues:

- **(a) Non-atomic read-modify-write.** The existence `SELECT` (`entity.py:132–141`) sits **outside** the `with conn:` block; only the subsequent `UPDATE`/`INSERT` is transactional. There is **no DB-level uniqueness** backstop (the pref key lives inside the `attributes` JSON blob, so no column constraint). Under the brief's §2 concurrency case ("Entity upsert … under SQLite default isolation"), two concurrent `record_preference` calls for the same `(user_id, key, scope)` can both `SELECT`-miss and both `INSERT` → **two rows**, breaking the "exactly one row per key" invariant ADR-020 D2 asserts. It does **not** manifest under the current sequential single-connection dispatch (ADR-011), and the test (sequential) cannot catch it.
  **Lean:** wrap the `SELECT`+write in one transaction (`BEGIN IMMEDIATE` for true cross-connection safety) **or** document a single-writer assumption on the preference path. **Architect: α (atomicity fix this cycle) / β (document single-writer + defer to when multi-connection access lands)?**
- **(b) `created_at` becomes "last-declared-at" on upsert.** The `UPDATE` sets `created_at = ts` (`entity.py:146`), so a re-declaration overwrites the original creation time; the field name still says `created_at`. Defensible for a latest-wins row, but it's a silent semantic and the update path's `created_at` behavior is untested. **Lean:** either preserve the original `created_at` on update (and add a `last_declared_at`-style field later if needed) or rename intent in the docstring; low severity. Folded here as the architect will route (a) and (b) together.

## What holds — verified clean (G1–G11)

- **G1 — Gates fully green** (run in worktree at `68fcedf`): ruff + ruff-format + `mypy --strict` (141 files) + **pytest 1063 passed**, 0 fail / 0 skip.
- **G2 — Principle 5 (Q1) clean.** No-LLM rglob (`test_constitution.py:51`) covers `entity.py`+`archive.py` (confirmed by the full green run); `grep` confirms `memory/` does **not** import `derived/`; semantic fields (`one_line_summary`, `spinoff_questions`) and `decision_log` are passed in, never generated in `memory/`.
- **G3 — Principle 11 enforcement.** `record_entity` rejects `type=PREFERENCE` (`entity.py:43`); `record_preference` requires non-empty `user_id` (`:123`). Both have discriminating e2e tests (`test_p2_4_e2e.py:127,137` — explicitly "fails if … silently accepts"). For the *current two write paths*, an inferred pref with no declaring user is un-representable (the Y1 hole is forward-looking only).
- **G4 — Y1 guard discriminating** on the construction form (live plant A above).
- **G5 — Migration idempotent.** `_ensure_entity_columns` (`store.py:107`) PRAGMA-guards **each** column independently; `test_store.py:273` is an on-disk round-trip (OLD schema → migrate → both columns present, old row backfilled `personal`/`{}`, count preserved, **idempotent second init**) — discriminating.
- **G6 — Upsert sequential correctness** (discriminating, see Y2).
- **G7 — 5-surface (Q3) consistent, no drift.** Code (`schema.py`/`store.py`/`entity.py`/`archive.py`), ADR-020, `handoff.md §4.5` (Entity materialized + `EntityType … preference` + `EntityScope` + upsert semantic), and `test_schema.py` (`PREFERENCE` value `:82`, all 4 `EntityScope` values `:85`, new Entity fields `:290–306`, ProjectArchive `:310`) all agree; `memory/__init__.py` re-exports the full new surface (my R0-A-on-plan M4 closed); no `docs/architecture/` references to update; `chat-history.md` untouched.
- **G8 — decision_trace (Q2) N/A.** P2.4 adds deterministic CRUD + two fail-loud validation guards, not routing/gating/scoring/selection functions; the guards carry their "why" in the `ValueError` messages. No decision function lacks a trace.
- **G9 — ProjectArchive (ADR-020 D3) faithful.** Persist; caller composes `produce_decision_log` and passes it in (`test_p2_4_e2e.py:152` round-trips it; `memory/` never re-derives); duplicate `room_id` → `IntegrityError` fail-loud (`test_archive.py:92`, discriminating); minimal readers + empty-DB cleanup (`:139`, `test_p2_4_e2e.py:204`).
- **G10 — Determinism.** Readers order by `id ASC` / `room_id ASC`; `test_p2_4_e2e.py:216` reverses insertion order across two connections and asserts stable order — discriminating (avoids the P2.2 by-construction anti-pattern, RC-25).
- **G11 — Schema invariants (Q4 §6).** All three models `frozen + extra="forbid"`; defaults + round-trips tested (`test_schema.py`); `_row_to_entity`/`_row_to_project_archive` map `scope`/`evidence` correctly (`store.py:301,312`).

Minor (non-finding): `get_entity_by_id`/`get_project_archive` take `conn` positionally whereas the rest of `memory/` uses keyword-only `*, conn` — cosmetic, leave or align at the senior's discretion.

## Workspace note (process, not impl)

The shared checkout was on `main` (`527f364`) with a **dirty index** (staged deletions of `entity.py`/`archive.py`/the e2e test + untracked re-creations) — a concurrent session/script mid-operation, not my changes, and `68fcedf` was not in that HEAD's history. To avoid clobbering another role's in-progress work (RC-7), I did **not** stash/reset/checkout the shared tree; I reviewed + wrote this file + committed in an isolated `git worktree` pinned at `68fcedf`, then removed it. Flagging so you can reconcile the `main` working tree separately — it is unrelated to the impl correctness, which is sound.

## What I did NOT do

- Did not decide Y1/Y2 — both surfaced with a lean for you to route (α/β/γ).
- Did not modify the impl (the two planted bypasses were reverted; tree clean before commit).
- Did not touch the shared `main` working tree, the senior's pending plan-vs-impl, or ADR-020's status.
