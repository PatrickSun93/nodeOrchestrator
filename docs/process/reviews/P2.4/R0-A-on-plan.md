---
task_id: P2.4
round: R0-A-on-plan
verdict: needs_architect
findings_count:
  red: 0
  yellow: 2
  green: 10
---

# P2.4 R0-A on plan (architect-dispatched pre-impl review)

| Field | Value |
|---|---|
| Round | R0-A-on-plan (architect-dispatched per RC-9) |
| Artifacts reviewed | `senior-plans/P2.4.md` + `ADR-020-memory-data-model-completion.md` (Proposed) against the merged substrate (`origin/main`) + brief `architect-briefs/P2.4.md` |
| ADR status | ADR-020 left **Proposed** — this review informs the accept decision; I did **not** accept (architect-only). |
| Tree | Clean — only this file added (r0b R0-B runs after me on the shared tree). |

## Verdict: needs_architect

The plan + ADR-020 are **sound and faithful** — every substrate claim I spot-checked is accurate (Entity stub `schema.py:119-131`, `entity` table `store.py:68-73`, the ALTER template `store.py:87-96`, `VKScope` 3-value `schema.py:58-61`, the derivations `decision_log.py:45` / `snapshot.py:98`, the no-LLM rglob `test_constitution.py:44`, the migration test template `test_store.py:129/224`). The constitutional reasoning holds: Principle 5 is satisfied, the ProjectArchive **persist** decision is well-justified, the ALTER migration mirrors ADR-018 D5 correctly, and the `scope`/`evidence` reserve-fields ship day-one.

**Two findings need an architect call before/at ADR-020 accept** — neither blocking, both routable:
- **Y1** — Principle-11 enforcement is by *direct unit test* on the two current write paths; there is no *structural* guard against a future third write path (the brief invited "add a guard if needed"; the senior declined; the matcher/validation precedent cuts the other way).
- **Y2** — the brief framed entity create as **"upsert (insert-or-update)"** (twice: §test-coverage 2 + 3); the plan ships **plain-insert** (fresh `ent_` id per call, no key-uniqueness). For preferences this leaves a *non-deterministic current-value resolution* and drops the brief's named "duplicate entity upsert" test.

Both are surfaced with a lean below — the architect routes; I do not.

## The dispatch's named checks

| Check | Verdict | Evidence |
|---|---|---|
| **Principle 11** — prefs explicit/confirm only; no LLM-inferred-durable; create path requires `user_id`/confirm; nothing infers | **holds for current code; Y1** | `record_preference` requires `user_id` (min_length≥1); `record_entity` rejects `type=PREFERENCE` → closes the bypass (ADR-020 D1/D2). I verified there is **no existing `INSERT INTO entity`** (entity is schema-only stub) — so post-P2.4 there are *exactly two* write paths to a PREFERENCE row, both tested (P2.4-3 AC#1, P2.4-4 AC#2). The "un-representable" claim is therefore true for this slice. The forward-looking gap is Y1. |
| **Principle 5** — extraction stays out of `memory/`; deterministic create/read only | **clean (G1)** | no-LLM rglob (`test_constitution.py:44`) auto-covers `entity.py`+`archive.py` — no new test needed (correct). Semantic content (`one_line_summary`, `spinoff_questions`, attributes) produced outside `memory/` and passed in as plain data; `memory/` calls no LLM. |
| **ProjectArchive persist-vs-derive** (§5 headline) | **persist justified (G3)** — confirm is architect's | The load-bearing reason is sound: the archive is captured **once at room close** and must outlive the event lifecycle; `chat-history`'s 遗忘机制 (超期降级) compacts events, so a derive-on-read view would degrade/break — and you *cannot retroactively derive* from compacted events, so capture-at-close (= persist) is the only forward-compatible choice. This is a genuine disanalogy with ADR-015's *live within-room* derive-discipline (`decision_log.py` recomputes from present events). No hidden flaw; the explicit persist confirmation remains the senior-flagged architect call. |
| **ADR-018 ALTER template followed** | **clean (G2)** | `_ensure_entity_columns` mirrors `_ensure_hypothesis_topic_tags` (`store.py:87-96`): `PRAGMA table_info(entity)` → guarded `ALTER ... ADD COLUMN ... NOT NULL DEFAULT <const>`; SQLite backfills. On-disk round-trip (P2.4-2 AC#2) mirrors `test_column_add_migration_round_trip` (`test_store.py:129`). `project_archive` is a plain `CREATE TABLE IF NOT EXISTS` (new table, no ALTER) — correct. |
| **Reserve `scope`/`evidence` fields** | **clean (G5); minor M2** | both Entity + ProjectArchive gain `scope` + `evidence` day-one (chat-history reserve discipline). `entity_id` (also named in the discipline) not reserved on ProjectArchive — see M2 (acceptable; consistent with deferring relations). |

## Findings (architect to route)

### Y1 🟡 — Principle-11: direct unit tests vs a structural regression guard

**What.** ADR-020 D2 claims an LLM-inferred preference is "un-representable." That guarantee is enforced by **two behavioral unit tests** on two functions (`record_entity` rejects `PREFERENCE`; `record_preference` requires `user_id` — P2.4-3 AC#1, P2.4-4 AC#2). It is **not guarded against a future *third* write path** — a later module that constructs an `Entity(type=PREFERENCE)` or does a raw `INSERT INTO entity` with `type='preference'` and no declaring user would bypass the discipline, and the two unit tests would stay green.

**Why it's an architect call (not mine).** The brief's constraint set explicitly said *"add an AST guard if any new advisory/creation surface needs an orthogonality invariant"* (brief §"Constitutional guards"). The senior reasoned **no guard** (ADR-020 D5) — correct that there's no *advisory-actuation* invariant like matcher/validation. But D5 answers a different question than Y1: the existing AST guards (`test_constitution.py:63` validation, `:132` matcher) exist precisely to protect *"no bypass in any future code path"* invariants — which is exactly the shape of the Principle-11 "un-representable" claim. So the project's established bar for a constitutional invariant is a structural guard, and Principle 11 is described as "absolute" + this is the project's **first preference surface** (inscribe-before-producer; the P2.6 producer is the high-risk bypass moment).

**My lean:** I lean *toward a lightweight structural guard* — the "un-representable" claim is stated structurally but enforced only behaviorally, and the matcher/validation precedent argues for consistency. **But** the senior's YAGNI counter is legitimate (a future bypass is new code that gets its own R0-A/R0-B; the guard would protect a non-existent path today), and the senior explicitly punted this to you ("Surfaced for the architect to override"). The guard's *shape* (if wanted) is a senior design choice, not part of this routing — candidates range from an AST check that `EntityType.PREFERENCE` is referenced only in `entity.py`'s pref functions, to a store-layer assertion that any `type='preference'` row carries `evidence.declared_by`.

**Architect: α (require a structural guard, senior designs it) / β (defer — direct unit tests suffice, revisit at the P2.6 producer) / γ (drop)?**

### Y2 🟡 — entity/preference create: plain-insert vs the brief's "upsert (insert-or-update)"

**What.** The brief framed entity create as **upsert** in two places — §test-coverage 2 ("Entity **upsert (insert-or-update)** under SQLite default isolation") and §3 cleanup ("duplicate entity **upsert**"). The plan ships **plain-insert**: `record_entity`/`record_preference` call `generate_entity_id` every time (P2.4-3 "Where"), so there is no key-uniqueness and no update path. The plan neither justifies the divergence nor carries the brief's "duplicate entity upsert" cleanup test (P2.4-3 AC#5 covers empty-DB / missing / malformed, not duplicate-create).

**Why it matters — not cosmetic.** For **preferences** specifically, plain-insert means `record_preference("response_style","concise",user_id="peidong")` called twice yields **two PREFERENCE rows**, and `list_preferences` returns both. "The user's *current* `response_style`" then has **no deterministic resolution**: ids are random `ent_<uuid>`, so if two rows tie on `created_at` (e.g. same injected `now` in a test), latest-by-`(created_at,id)` is non-deterministic-by-value — brushing the brief's Principle-11 determinism requirement. Upsert-by-`(user_id,key)` gives exactly one row per key (the current value) and sidesteps this. Because the ADR calls these containers "the expensive-to-change contract" P2.5 binds to, append-vs-upsert is a **P2.4 data-model decision**, not a P2.5 consumer concern (shipping append-only then wanting upsert in P2.5 = a dedup migration).

**My lean:** this is a real brief-vs-plan divergence the plan should resolve explicitly. Either (a) **justify plain-insert** as deliberate append-only (entities are an event-like log; dedup/latest-wins is the consumer's job) **and** add the brief's duplicate-create cleanup test to *lock* the semantic; or (b) **implement upsert** for preferences (insert-or-update by `user_id,key`) as the brief framed. I lean (a) for general entities (append-only is fine) but think **preferences want (b)** (a settings map, one current value per key) — but this is the senior's design call once you confirm the intent.

**Architect: confirm the intended semantic** (append-only entities + key-unique preference upsert? / append-only for both? / upsert for both?) — then it's a plan refinement, not a re-design.

## Minor notes (non-gating; impl/landing hygiene — for the senior/junior, no architect call)

- **M1 — `memory/` does-not-import-`derived/` is asserted but unguarded** (P2.4-5 AC#3). No current `memory/→derived/` import exists, and the *real* invariant (readers are deterministic + no-LLM) is already guarded; the no-import rule is belt-and-suspenders. Acceptable unguarded; flag only if you want it explicit.
- **M2 — ProjectArchive reserves `scope`+`evidence` but not `entity_id`** (chat-history names `entity_id` in the reserve discipline). Consistent with deferring entity↔entity relations (ADR-020 D1 forward hook), and the proven ALTER template makes a late add cheap — and the existing Hypothesis/VK rows don't reserve `entity_id` either. Acceptable; flag only if you want the archive↔project-entity link day-one.
- **M3 — `record_preference`'s `user_id` is a function-body check, not a model field.** The `user_id` lands in the free `evidence` dict, so `min_length≥1` must be enforced *in the function body* (not a pydantic constraint). P2.4-4 AC#2's test forces it — ensure the impl validates explicitly rather than assuming a model constraint catches it. (This is the load-bearing Principle-11 line, so worth the precision.)
- **M4 — existing Entity schema tests + `memory/__init__.py` exports need updating.** `test_schema.py:74-79` asserts exactly the 4 `EntityType` values (needs `+PREFERENCE`); `_make_entity` (`:243`) still constructs fine (scope/evidence have defaults) but should gain default-value assertions. New public surface (`EntityScope`, `ProjectArchive`, `record_entity/preference/project_archive` + readers) should re-export from `memory/__init__.py`. Both fall under P2.4-2 AC#3 / the P2.4-6 5-surface scan — not separately listed; confirm they're caught at landing.

## What holds — verified clean (G1–G10)

- **G1** Principle 5 — no-LLM rglob auto-covers the new files; content-gen produced outside `memory/`, passed in (`test_constitution.py:44`).
- **G2** ALTER migration mirrors ADR-018 D5 + the on-disk round-trip test template (`store.py:87`, `test_store.py:129/224`).
- **G3** ProjectArchive **persist** is well-reasoned (capture-at-close + compaction ⇒ can't derive-on-read post-close; genuine disanalogy with ADR-015's live derive-view). The `current_focus`-in-`summary_snapshot` content-gen-persisted precedent is real (`event.py:88/302/352`).
- **G4** `EntityScope` separate from `VKScope` justified — `VKScope` is 3-value, no `project` (`schema.py:58-61`); entities need `project`.
- **G5** `scope`+`evidence` reserve-fields ship day-one on both models (chat-history discipline).
- **G6** Principle-11 create-path correct for the current code — two write paths, both tested; zero pre-existing entity writers verified.
- **G7** Execution order + atomic decomposition sound — `entity.py` (3→4) sequential, `archive.py` (5) parallel-after-2; RC-17 one-atomic-one-subject with prefs getting their own commit.
- **G8** e2e shape faithful — cross-room create→read for all three, source≠sink, discriminating determinism asserts (P2.2/P2.3 precedent), models frozen + `extra="forbid"`, ProjectArchive `room_id` PK fail-loud on duplicate.
- **G9** No new AST *advisory-orthogonality* guard is correctly declined (ADR-020 D5) — the existing AST guards protect must-not-actuate advisory readers; P2.4's APIs are deterministic write sinks with no actuation to forbid. (Distinct from Y1, which is about a *bypass* guard, not an advisory-actuation guard.)
- **G10** `core/` untouched; the `core`-no-import-`memory` guard is unaffected (the new enums live in `memory/schema.py`, unlike P2.3's core `EventType`).

## What I did NOT do

- Did **not** accept ADR-020 (architect-only; the dispatch confirmed).
- Did **not** re-route or re-interpret any finding — Y1/Y2 are surfaced with a lean for the architect to call.
- Did **not** touch the tree beyond this review file (r0b R0-B runs next on the shared tree).
