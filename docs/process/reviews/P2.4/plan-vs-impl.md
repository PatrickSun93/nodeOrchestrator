---
task_id: P2.4
round: plan-vs-impl
reviewer: senior
impl_commit: 68fcedf
verdict: clean
verdict_history:
  - clean  # initial plan-vs-impl verdict — faithful on every checklist item; no findings requiring architect routing
findings_count:
  red: 0
  yellow: 0
  green: 3
---

# P2.4 plan-vs-impl (senior) — memory data-model completion (Entity + ProjectArchive + 用户偏好)

| Field | Value |
|---|---|
| Reviewer | senior (plan-vs-deliverable lens) |
| Plan | `docs/process/senior-plans/P2.4.md` (incl. the Y1 + Y2 → α plan-stage revision) |
| ADR | `docs/decisions/ADR-020-memory-data-model-completion.md` (Accepted) |
| Impl | `claude/P2.4-impl` @ `68fcedf` (atomics P2.4-2..6 at `b26cb64`, `2517487`, `9a497b8`, `d477631`, `68fcedf`) |
| Verdict | **clean** — 0🔴 · 0🟡 · 3🟢 |

## Summary

Faithful implementation across all three subsystems and both plan-stage routing items. Entity is fleshed off the stub with the reserved `scope`/`evidence` fields + `EntityScope` + `EntityType.PREFERENCE`; `record_entity` is plain-insert and rejects `PREFERENCE`; `record_preference` upserts by `(user_id, key, scope)` and requires `user_id`; ProjectArchive persists (room_id PK, fail-loud duplicate, semantic fields passed in, no `derived/` re-derivation); the Y1 Principle-11 structural guard is a real-AST `NodeVisitor` confining `EntityType.PREFERENCE` to `entity.py`'s preference functions; the Y2 dual duplicate-create tests are discriminating; the PRAGMA-guarded `entity` ALTER ships with an on-disk migration round-trip; and the 5-surface (schema/store/APIs/`__init__` re-exports/handoff §4.5/test_schema) is complete with no §7-P1.2-stale bundling. The constitutional invariants (Principle 5 no-LLM-in-`memory/`, Principle 11 no-inferred-prefs) are enforced both behaviorally and structurally. No 🔴/🟡 — three 🟢 observations (one minor semantic, one efficiency note, one review-methodology note), none blocking.

## Checklist verification (per the dispatch + plan §5 / ADR-020)

| Item | Status | Evidence |
|---|---|---|
| Entity reserved fields `scope`+`evidence` + `EntityScope` + `EntityType.PREFERENCE` | ✓ | schema.py — `EntityScope(personal\|team\|project\|global)`, `EntityType += PREFERENCE`, `Entity{… scope: EntityScope=PERSONAL, evidence: dict={}}` frozen + `extra="forbid"` (ADR-020 D1) |
| `record_entity` plain-insert + **rejects `type=PREFERENCE`** | ✓ | entity.py:43-46 (`ValueError`); append-only INSERT (fresh id each call); `test_rejects_preference_type` + `test_append_only_duplicate_creates_two_rows` (asserts **2** rows, "fails if upsert") |
| `record_preference` **upsert by (user_id,key,scope)** + **requires user_id** | ✓ | entity.py:107-180 — empty `user_id`→`ValueError`; read-modify-write keyed on `(scope, attrs.key, evidence.declared_by)`; `test_upsert_same_key_yields_one_row` (1 row, value→"verbose"), `test_empty_user_id_raises`, different-users/keys/scopes → distinct rows (ADR-020 D2) |
| ProjectArchive **persist** (D3) | ✓ | archive.py — `project_archive` table (room_id PK, FK→rooms); duplicate room_id → `IntegrityError` (fail-loud); semantic fields (`one_line_summary`/`spinoff_questions`) + `decision_log` passed in; **imports only core/schema/store — no `derived/`** (never re-derives) |
| Y1 structural **AST guard** confines `EntityType.PREFERENCE` to entity.py pref fns (real AST, RC-24) | ✓ | test_constitution.py `test_principle_11_preference_ast_guard` — `ast.NodeVisitor` with a function stack; allowed-set `{(entity.py, record_preference/record_entity/list_preferences)}`; matches `ast.Attribute(attr="PREFERENCE", value=Name("EntityType"))` only (enum def is `Assign`, `EntityType(row[...])` is `Call` — neither flagged); discriminating (a ref elsewhere fails) |
| Dual duplicate-create tests **discriminating** (Q5) | ✓ | pref → exactly **1** row, latest value ("fails if plain-insert"); entity → **2** rows ("fails if upsert") |
| PRAGMA-guarded **ALTER** migration | ✓ | store.py `_ensure_entity_columns` (PRAGMA `table_info(entity)` → ALTER add `scope`+`evidence`, mirror `_ensure_hypothesis_topic_tags`); `test_entity_column_add_migration_round_trip` (on-disk, pre-P2.4 table → reopen → both columns present + old row reads defaults) |
| 5-surface complete | ✓ | schema + store + entity.py + archive.py + `__init__.py` re-exports (M4) + handoff §4.5 + `test_schema.py` enum/model tests; **no §7-P1.2-stale bundling** (only §7 mention is the pre-existing P2.7 roadmap row) |
| Principle 5 (no LLM in `memory/`) | ✓ | entity.py + archive.py import no LLM (no-LLM rglob covers them); archive's semantic fields are content-gen produced outside `memory/`, passed in |
| Determinism (Principle 11) | ✓ | readers `id ASC` / `room_id ASC`; upsert latest-wins is deterministic by the `(user_id,key,scope)` key |

## Findings

### 🟢 G1 — `record_preference` upsert overwrites `created_at` with the latest declaration time

On upsert (entity.py:146-147), the in-place `UPDATE` sets `created_at = ts` (the new declaration's timestamp). So for a re-declared preference, `created_at` reflects the **latest** declaration, not the original — the field named `created_at` effectively behaves as `last_declared_at`. ADR-020 D2 / the plan are silent on the timestamp's upsert behavior, so this is an **unspecified detail the impl chose reasonably** (latest-wins naturally includes the timestamp), not a divergence. Non-blocking; optional future clarity: document this on the model field, or split `created_at` (first) vs an `updated_at` (latest) if a consumer ever needs the original declaration time. No action required for P2.4.

### 🟢 G2 — preference upsert scan is O(prefs-in-scope), user_id filtered in Python

`record_preference` reads `WHERE type='preference' AND scope=?` (all users in the scope), then Python-filters by `attrs.key` + `evidence.declared_by` to find the existing row (entity.py:132-141). This is O(prefs-in-scope) per upsert and not SQL-scoped to `user_id` — fine at the expected small preference volume, and consistent with the project's Python-post-filter posture (ADR-016 D6 lookup; the plan allowed read-modify-write). Single-connection sequential (ADR-011 D1) → no read-modify-write race. A future scale reshape (a `(user_id,key,scope)` index/projection) is the forward path if preference volume ever grows. Non-blocking.

### 🟢 G3 — review-methodology note (environment, not a P2.4 finding)

During the review the working tree transiently flipped between `main` and `claude/P2.4-impl` (an apparent crashed-git state on the WSL2 `/mnt/d` mount — a "may have crashed earlier" warning + an `archive.py`-missing/`git status: main` inconsistency mid-review). Per the stale-workspace guard I halted, re-ran `git checkout claude/P2.4-impl`, and **verified `HEAD == 68fcedf` + a clean, consistent working tree (entity.py + archive.py present)** before completing every verification above. This review reflects the verified-consistent `68fcedf` tree. Recording it for transparency / a possible tooling RC; it is **not** a P2.4 implementation finding.

## Net

The implementation matches the plan + Accepted ADR-020 on every checklist item, with discriminating tests for the two routing-absorbed invariants (Y1 structural AST guard; Y2 upsert-vs-append-only) and the constitutional Principle-5/11 enforcement. Junior reports 1063 tests green. **Verdict: clean.** Per ADR-008 Amendment 1 (Route B), state auto-advances to `awaiting_R0_A` regardless; R0-A (+ R0-B, dual-lens dispatched) fire next, then joint-verdict evaluation. With a clean plan-vs-impl, the joint verdict turns on the external lenses.
