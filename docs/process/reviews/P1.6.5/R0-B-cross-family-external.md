---
task_id: P1.6.5
round: R0-B-cross-family-external
reviewer_family: deepseek
reviewer_model_id: deepseek-v4-pro
reviews_acked:
  - architect-briefs/P1.6.5.md
  - senior-plans/P1.6.5.md
  - decisions/ADR-016-cross-room-memory-persistence.md
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 12
verdict_history:
  - verdict: needs_architect
    at_commit: 6547eb7
    findings_count: { red: 0, yellow: 5, green: 7 }
    note: original — external (DeepSeek V4 Pro) R0-B surfaced 5 Y (Y7 conn-mismatch atomicity hazard; Y8 FK-timing [confirms proxy Y3]; Y9 UNIQUE constraint; Y10 layering-set incomplete [confirms proxy Y4, refines set 4→3]; Y11 untested migration template).
  - verdict: clean
    at_commit: HEAD
    findings_count: { red: 0, yellow: 0, green: 12 }
    note: 2nd senior revision absorbed Y7 α(b) + Y9 α + Y11 α; Y8 folds into proxy Y3, Y10 into proxy Y4 (set refined to 3 product packages). Per architect-routing-r0b-external.md. Y7/Y9/Y11 → 🟢 absorbed; Y8/Y10 → 🟢 confirm.
---

> **RC-10 verdict bump (post-routing-revision)** — frontmatter as live signal. Bump applied after senior absorbed the external R0-B routing (`architect-routing-r0b-external.md`, `3a318fa`) into the 2nd revision commit on this branch. Per RC-10 codification (`docs/process/reviews/README.md` §RC-10); 13th project use; original findings preserved as audit trail below.
>
> Absorption per finding:
> - **Y7 → 🟢 absorbed** (the canonical cross-family catch) — `promote_hypothesis` drops the `conn` param, derives from `event_store.conn`; conn-mismatch atomicity-loss hazard now unrepresentable-by-construction (ADR-016 D3 + D11 + P1.6.5-4 + P1.6.5-5).
> - **Y8 → 🟢 confirm** — independently re-derived proxy Y3 (FK INSERT-time); resolved by the same absorption (ADR-016 D5 + P1.6.5-2).
> - **Y9 → 🟢 absorbed** — `verified_knowledge.promoted_from_hypothesis_id` gains `UNIQUE`; double-promotion prevented at two layers (ADR-016 D2 + D3 + P1.6.5-2/-4 + IntegrityError test).
> - **Y10 → 🟢 confirm + refine** — independently re-derived proxy Y4 (layering-set incomplete) + refined the package set 4→3 (add autonomy/skills/llm; drop `workflow/` as dev-harness). This refinement supersedes proxy Y4's 4-package recommendation.
> - **Y11 → 🟢 absorbed** — on-disk migration test added; converts ADR-016 D5's migration claim from asserted to verified (ADR-016 D5 + P1.6.5-2).
>
> **Dual-lens economics (retro candidate)**: external independently re-derived 4 of 6 proxy findings (Y8↔proxy-Y3, Y10↔proxy-Y4, + 🟢 confirms of proxy-Y2/Y5) AND added 3 net-new (Y7/Y9/Y11) the proxy missed. Both lenses paid for themselves; neither redundant. See `architect-routing-r0b-external.md` + `3873c91` RC-20 candidate.

# P1.6.5 R0-B cross-family external review (plan + ADR-016)

## 🟡 Findings

### 🟡 Y7 — D11 atomicity: no `conn is event_store.conn` assertion (`promote_hypothesis` signature)

**Location**: plan §2 P1.6.5-4 `promote_hypothesis` signature; ADR-016 D11 code block

`promote_hypothesis` accepts both `conn: sqlite3.Connection` and `event_store: EventStore` as parameters. The D11 atomicity guarantee depends on `conn is event_store.conn` — the `with conn:` block wrapping `event_store.append_in_transaction(decision_event)` + VK INSERT + Hypothesis UPDATE requires all three writes to share one transaction on one connection.

Nothing asserts this invariant. If a caller passes `conn != event_store.conn`, `append_in_transaction` writes the `decision` event to `event_store.conn` (auto-committed or in its own transaction) while the VK INSERT + Hypothesis UPDATE go to `conn`. Two independent connections → two independent transactions → **silent atomicity loss**. No error, no warning — the promotion "succeeds" but partial-state outcomes become possible on the failure of either connection's commit.

**Why it matters**: this is the exact class of failure a cross-family lens is designed to catch. Claude-family reviewers (both R0-A and proxy R0-B) probed D11's transaction mechanics (the `with self.conn:` nesting problem, the `append_in_transaction` extraction) but stopped at "same connection → same transaction." The implicit assumption that `conn` and `event_store.conn` are the same object is a Claude-family blind spot — it's the kind of invariant that same-family reviewers accept as "obvious" because they share the mental model of the senior who wrote it. A non-Claude reading asks: "what if they're not?"

**Recommendation**: add `if conn is not event_store.conn: raise ValueError("conn must be event_store.conn for transaction atomicity")` at the top of `promote_hypothesis`. One-line guard; zero runtime cost; catches the caller bug at the earliest possible point. Alternatively, remove the `conn` parameter from `promote_hypothesis` entirely and use `event_store.conn` for all three writes — simpler API surface, fewer invariants for callers to hold.

**Architect-partner lean**: α — fix before junior dispatch. Trivial to add; high-leverage for correctness.

---

### 🟡 Y8 — P1.6.5-2 acceptance criterion factual error: init-order "raises"

**Location**: plan §2 P1.6.5-2 acceptance, bullet 2

The acceptance criterion states:

> `init_memory_schema` requires `events` and `rooms` tables to exist first (FK enforcement); test verifies init order — calling before `EventStore.init_schema` raises

This is factually wrong. SQLite permits forward FK references in DDL: `CREATE TABLE ... FOREIGN KEY (col) REFERENCES nonexistent_table(id)` succeeds without error. The FK is only checked at INSERT/UPDATE time when `PRAGMA foreign_keys = ON` is active. `init_memory_schema` called before `EventStore.init_schema` would NOT raise — all three `CREATE TABLE IF NOT EXISTS` statements would succeed. The FK violation only surfaces later, at first INSERT.

The parenthetical in the plan text ("FK reference resolves at trigger time but SQLite tolerates forward refs by default") acknowledges the SQLite behavior but then contradicts it with "raises." The test as specified would FAIL.

**Why it matters**: the junior implementer reading this acceptance criterion would write a test expecting `pytest.raises(...)` on out-of-order init, get a pass (no exception raised), and falsely conclude init order doesn't matter — which is incorrect because FK enforcement at INSERT time DOES require the referenced tables to exist. The acceptance criterion is self-contradictory and would produce a misleading test.

**Recommendation**: reword the acceptance criterion to:

> test verifies that INSERTs into memory tables fail with FK violation when the referenced `events`/`rooms` tables don't exist (validates FK enforcement at write time). A separate test verifies the documented init order (`EventStore.init_schema` then `init_memory_schema`) produces a correctly-initialized DB where all FKs resolve.

**Architect-partner lean**: α — acceptance criterion error. Fix before junior dispatch to avoid misleading test.

---

### 🟡 Y9 — Missing UNIQUE constraint on `verified_knowledge.promoted_from_hypothesis_id`

**Location**: ADR-016 D2 schema DDL; plan §2 P1.6.5-2 `_MEMORY_SCHEMA`

The `verified_knowledge` table DDL has:

```sql
promoted_from_hypothesis_id TEXT NOT NULL,
FOREIGN KEY (promoted_from_hypothesis_id) REFERENCES hypothesis(id)
```

No `UNIQUE` constraint on `promoted_from_hypothesis_id`. The API-level guard in `promote_hypothesis` (check `status == PENDING`, set to `verified`) prevents double-promotion for the single-writer, single-connection P1.6.5 model. But the schema doesn't enforce it.

**Why it matters**: defense-in-depth. A future cycle that adds concurrent writers, a bulk-import API, or a buggy producer could create two VK rows pointing to the same Hypothesis. The API-level check races under concurrency; the UNIQUE constraint is a schema-level guarantee that survives any code path. Cost: `UNIQUE` on one column. Benefit: impossible to double-promote regardless of future code changes. The table is new in P1.6.5 — zero migration cost to add the constraint now.

**Recommendation**: add `UNIQUE` to the column: `promoted_from_hypothesis_id TEXT NOT NULL UNIQUE`. One-word SQL change. Keep the API-level status check as the primary gate; the UNIQUE constraint is the belt-and-suspenders backup.

**Architect-partner lean**: α (or β if architect considers the API-level check sufficient for P1.6.5's single-writer model and wants to defer the UNIQUE constraint to the concurrent-dispatch forward-amendment hook). Lean α — one word, zero migration cost, impossible to add later without a table rebuild.

---

### 🟡 Y10 — Incomplete layering guard set (`autonomy/`, `skills/` unguarded)

**Location**: plan §2 P1.6.5-1 acceptance, bullet 4; ADR-016 Hard Requirements

The plan adds `*_does_not_import_memory` guards to 4 of 8 sibling packages: `core/`, `agents/`, `rooms/`, `derived/`. Missing: `autonomy/`, `skills/`, `llm/`, `workflow/`.

- `workflow/` is dev harness — N/A (correct to skip).
- `llm/` importing `memory/` would be architecturally incoherent (memory is constitutionally LLM-free) but not a layering violation per se — debatable.
- **`autonomy/`** — the most plausible future violator. Autonomy decisions might query "has this hypothesis been promoted?" or "how many VKs exist in scope X?" as a gating input. `autonomy/` already has a `test_constitution.py` (3 tests). Adding `test_constitution_autonomy_does_not_import_memory` costs ~20 lines.
- **`skills/`** — skills might consume VK types or call `lookup_verified_knowledge` directly, bypassing the agent layer. `skills/` already has a `test_constitution.py` (2 tests). Adding the guard costs ~20 lines.

Both `autonomy/` and `skills/` are product packages with `test_constitution.py` files already in place. Adding the guards is mechanical — same AST-walk pattern as the 4 the plan already adds.

**Why it matters**: dependency-direction guards are cheapest when the package is greenfield. Adding them now prevents accidental dependency creep that would be harder to unwind later (once `autonomy/` code imports `memory/schema.py` for a `VKScope` type hint, removing it requires refactoring the autonomy code). The cost of adding 2 guards now (~40 lines) is far lower than the cost of retrofitting them after an unintended import lands.

**Recommendation**: add `test_constitution_autonomy_does_not_import_memory` to `tests/autonomy/test_constitution.py` and `test_constitution_skills_does_not_import_memory` to `tests/skills/test_constitution.py`. Same AST-walk pattern as the 4 guards in the plan. Optional: add `test_constitution_llm_does_not_import_memory` for completeness (low risk, but consistent).

**Architect-partner lean**: α — add before junior dispatch. Low cost; high prevention value.

---

### 🟡 Y11 — Migration story untested

**Location**: ADR-016 D5 migration claim; plan §2 P1.6.5-2 + P1.6.5-5

ADR-016 D5 claims: "The migration story for existing event_store DBs: on first `init_memory_schema(conn)` call against a pre-P1.6.5 DB, `CREATE TABLE IF NOT EXISTS` for the 3 memory tables succeeds; existing events/rooms/relations tables are untouched."

All P1.6.5 tests use in-memory SQLite (`:memory:`). No test creates an on-disk DB with only event_store tables, closes it, re-opens, and runs `init_memory_schema` to verify the migration path. The first production user with an on-disk event_store DB exercises the migration path **untested**.

**Why it matters**: `CREATE TABLE IF NOT EXISTS` is idempotent by design — the risk is low. But the claim "migration story works" is untested. If a subtle issue exists (e.g., `EventStore.__init__` sets `row_factory = sqlite3.Row` but `init_memory_schema` receives a raw `conn` — no issue, but the point is nothing verifies the full path), it surfaces at the worst possible time (real user data).

**Recommendation**: add a dedicated migration test in `tests/memory/test_store.py`: (1) create on-disk temp DB, (2) `EventStore(conn).init_schema()` only, (3) append a few events + rooms, (4) close connection, (5) re-open, (6) `init_memory_schema(conn)`, (7) verify 3 memory tables exist AND `events`/`rooms`/`relations` tables are untouched, (8) verify `record_hypothesis` + `promote_hypothesis` work against the migrated DB. One test function; ~30 lines.

**Architect-partner lean**: β — add if time permits. Low risk (`CREATE TABLE IF NOT EXISTS` is well-tested by SQLite itself), but the claim should be verified. If deferred, note in the tracking table that migration testing is a P1.6.5-2 follow-up.

---

## 🟢 Observations / confirmations

### 🟢 Confirms proxy Y2: `append_in_transaction` bare-call footgun

The plan documents that calling `append_in_transaction` outside `with conn:` results in auto-commit (P1.6.5-2 acceptance bullet 6c). The proxy R0-B Y2 finding (raise-guard routed, `α (ii)`, pending absorption) is correct — a documented footgun is still a footgun. Confirms the raise-guard routing is the right call.

### 🟢 Confirms proxy Y5: `DecisionMeta` ID fields lack prefix-pattern constraints

The plan's current `DecisionMeta` extension (P1.6.5-3) uses `str | None` for `hypothesis_id`/`vk_id` with no `hyp_`/`vk_` prefix validation. The proxy R0-B Y5 finding (routed `α (a)` at `99f9182`, pending absorption) correctly identifies this gap. The `@model_validator` checks co-presence but not prefix-correctness. Confirms the Y5 routing is correct; prefix-pattern `field_validator` should be added at absorption.

### 🟢 Senior push-back concurrences are reasoned, not deferential

All 8 push-back resolutions (§5 #1-#8) show independent reasoning: the senior cites specific technical grounds (migration tooling absence for #3; ADR-014 D3 precedent for #4; constitutional-type minimalism for #6) rather than blanket agreement. No sycophancy detected. The two self-discoveries (S1 layering, S2 transaction-nesting) surface genuine implementation gaps the brief's wording masked — exactly the senior's role per the planner doc.

### 🟢 D11 `append_in_transaction` design sound for single-connection mode

The `append_in_transaction` extraction (option A) is the minimum-viable refactor. SAVEPOINT (option C) would fight Python sqlite3's autocommit semantics; inline INSERT (option B) breaks the EventStore-is-only-writer invariant; reaching into `EventStore.conn` (option D) is encapsulation break. The forward-amendment hook for concurrent dispatch correctly flags the single-connection assumption for revisit. No simpler alternative was missed.

### 🟢 Cross-room lookup IS genuinely cross-room

`lookup_verified_knowledge(topic_tags, scope, *, conn)` has no `room_id` parameter — it queries across all rooms, filtered by scope only. Room 3 finding Room 1's promoted VK is a genuine cross-room operation. The scenario is not a synthetic "same room, different query context" illusion. The consumer reasoning loop (agent in room 3 uses VK from room 1) is not exercised — but that's a consumer concern, not a persistence-layer concern. The e2e validates the correct contract.

### 🟢 Verification cites in plan §5 are accurate

Spot-checked 3 cites against source: `core/event_store.py:211` (`with self.conn:` confirmed), `core/event.py:69-95` (18-type EventType vocabulary confirmed), `core/event.py:135-145` (DecisionMeta with `extra="forbid"` via `_BaseMeta` confirmed). All three accurate. W-004-2 (a) discipline holds.

### 🟢 `memory/` + `init_memory_schema` layering choice is correct

ADR-016 D5's deviation from the brief's "extend event-store init SQL" wording (which would place memory DDL in `core/event_store.py`) is the right call. `core/` knowing about memory table shapes would violate the same layering invariant that yields ADR-014 D5 deliberate-duplication. The senior's S1 surface was correct and the brief's wording was imprecise, not a design intent.

---

## Cross-probe synthesis

### Probe 1 (transaction-atomicity failure modes): Y7 + confirms Y2

The D11 `append_in_transaction` design is correct for same-connection, single-writer mode. All four failure paths (a-d) traced: the `with conn:` rollback correctly restores all state (event row, relations cache, VK row, Hypothesis.status) on any mid-transaction failure. The commit-phase failure case (disk full) raises `OperationalError` and the `with conn:` context manager issues ROLLBACK — all writes undone. **The gap is the unasserted invariant `conn is event_store.conn`** (Y7).

### Probe 2 (schema-init order vs FK): Y8

The "init order required" claim is partially true (required for INSERT-time FK enforcement) but the acceptance criterion's "raises" claim is factually wrong. SQLite DDL with forward FK refs succeeds; only INSERT/UPDATE with `foreign_keys = ON` enforces.

### Probe 3 (DecisionMeta integrity beyond validators): no net-new finding

With co-presence enforced by `@model_validator` and prefix-pattern constraints pending (Y5 absorption), the remaining gap is cross-scope integrity (`event.room_id` vs `hypothesis.room_id`). The sole P1.6.5 producer (`promote_hypothesis`) constructs both from the same Hypothesis row, so the gap is not exploitable by current code. A future buggy producer could create a mismatch; enumerating that as a forward-amendment hook is reasonable but not required for P1.6.5. **No net-new 🟡; this is a 🟢 deferred concern.**

### Probe 4 (cross-room semantic in Scenario X): 🟢

The lookup IS cross-room (no room filter). The consumer reasoning loop is aspirational but the persistence contract is correctly validated. The "load-bearing" claim is slightly overstated but not misleading.

### Probe 5 (layering risk): Y10

The 4-guard set is incomplete. `autonomy/` and `skills/` are credible import sources.

### Probe 6 (migration story): Y11

Untested. Low risk but the claim should be verified.

### Probe 7 (VK uniqueness): Y9

API-level enforcement works for P1.6.5; UNIQUE constraint is cheap defense-in-depth.

### Probe 8 (no-auto-promote enforcement): 🟢

API-shape enforcement is the right call for P1.6.5. The D10 rationale (constitutional test would be brittle) is defensible. No net-new angle.

### Probe 9 (verification cite completeness): 🟢

The cites checked are accurate. W-004-2 (a) discipline holds.

### Probe 10 (anything else): no additional findings

Performance trajectory of D6 lookup (O(rows-in-scope) Python post-filter) is correctly deferred via the forward-amendment hook. The `contradictions` field's staleness concern (what if a contradicting VK is later retracted?) is a deferred-cycle concern, not a P1.6.5 design gap. The `record_hypothesis` ↔ event atomicity gap is architect-settled (ADR-016 D4 + Y6 forward-amendment hook). No other net-new issues surfaced.

---

## Net assessment

The plan + ADR-016 are well-constructed. The senior correctly resolved all 8 push-backs with reasoned concurrences (not deference), surfaced two implementation-level gaps the brief's wording masked (S1 layering, S2 transaction-nesting), and produced a plan with accurate verification cites. The `append_in_transaction` design (D11) is sound for the single-connection model, and the forward-amendment hooks correctly flag the concurrent-dispatch revisit point.

The 5 🟡 findings are all small-scope and fixable with plan/ADR text amendments — no design rework required:

| Finding | Fix scope | Lines changed |
|---|---|---|
| Y7 — `conn is event_store.conn` assertion | Add 1 guard in `promote_hypothesis` | 2 |
| Y8 — Init-order acceptance criterion error | Reword 1 acceptance bullet | 3 |
| Y9 — Missing UNIQUE constraint | Add `UNIQUE` to 1 DDL column | 1 |
| Y10 — Incomplete layering guard set | Add 2 guard tests | ~40 |
| Y11 — Migration story untested | Add 1 migration test | ~30 |

**Verdict: `needs_architect`** — 0🔴 / 5🟡 / 7🟢. The architect should route all 5 🟡 per standard `architect-routing.md` protocol; the senior absorbs into ADR-016 + plan via `awaiting_senior_revision` before junior dispatch. None are blocking.

Two of the 5 findings (Y7, Y8) are the kind of gap a cross-family lens is uniquely positioned to catch: Y7 is a silent invariant assumption that same-family reviewers accept as obvious; Y8 is a factual assertion about SQLite behavior that same-family reviewers would pattern-match as "test verifies init order" without questioning the specific SQLite DDL behavior. Both are high-leverage catches at plan stage — fixing them now costs minutes; finding them at impl stage would cost a test rewrite and a bug hunt.
