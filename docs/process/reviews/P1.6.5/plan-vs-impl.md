---
task_id: P1.6.5
round: plan-vs-impl
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 11
verdict_history:
  - verdict: needs_architect
    at_commit: f4156b8
    findings_count: { red: 0, yellow: 2, green: 9 }
    note: original — Y1 (ADR-016 D11 + plan P1.6.5-2 non-functional as written vs proxy-Y2 entry guard) + Y2 (promotion event omits confirming user_id).
  - verdict: clean
    at_commit: c5c971c
    findings_count: { red: 0, yellow: 0, green: 11 }
    note: impl-stage 3rd revision (Path A, same-branch) absorbed both — Y1 α(a) doc-to-impl reconciliation (ADR-016 D11 + plan P1.6.5-2 → _append_body + DML-first); Y2 α(a) DecisionMeta gains user_id (required under promotion=True) + promotion.py event metadata + tests. Per architect-routing-on-impl.md. Both Y → 🟢. Gates green (896 passed).
---

> **RC-10 verdict bump (impl-stage routing absorption, 2026-05-29)** — frontmatter as live signal. Per `architect-routing-on-impl.md` (Y1 α(a) · Y2 α(a) · Y3 dismissed), Path A same-branch absorption on `claude/P1.6.5-impl`; cycle stays 1. Original finding bodies preserved below as audit trail.
> - **Y1 → 🟢 absorbed** — ADR-016 D11 example rewritten to the `_append_body` factoring (`append` calls it directly, not `append_in_transaction`) + DML-first caller contract + entry-guard-ambiguity forward-amendment hook; plan P1.6.5-2 EventStore-split block matched. Impl was already correct; this reconciles the Accepted-ADR + plan text to it.
> - **Y2 → 🟢 absorbed** — `DecisionMeta` gains `user_id` (required under `promotion=True`, 3-way co-presence); `promote_hypothesis` adds `"user_id"` to the canonical `decision` event metadata; ADR-016 D3+D8 inscribe; tests in `test_event.py` + `test_promotion.py` + e2e. `author` stays `system`.
> - Cleanliness note (store.py:222 dead import) remains a non-routed observation; not addressed this cycle.

# Review: P1.6.5 — plan-vs-impl

**Reviewer:** senior planner (Claude Opus 4.7, primary session)
**Date:** 2026-05-29
**Artifacts reviewed:** 6 impl commits on `claude/P1.6.5-impl` (`4ba8654` → `5cd6f34`): P1.6.5-1 (memory package skeleton) → P1.6.5-3 (DecisionMeta) → P1.6.5-2 (store + EventStore split) → P1.6.5-4 (promotion + lookup) → P1.6.5-5 (e2e) → P1.6.5-6 (landing). +2642 / −114 LoC (test-heavy). Read every new `src/orchestrator/memory/*.py`, the `core/event.py` + `core/event_store.py` diffs, the e2e + key memory tests, and the landing commit's IMPLEMENTATION NOTES.
**Plan:** `docs/process/senior-plans/P1.6.5.md` (single-ADR path; ADR-016 Accepted `2026-05-29` after plan-stage dual-lens R0-B all-clean).
**Verification run (audit):** `ruff check` PASS · `ruff format --check` PASS (128 files) · `mypy --strict` PASS (58 files) · `pytest` **893 passed** (was ~833 pre-cycle; +60 matches the plan P1.6.5-6 ≥60 delta estimate).
**State context:** `.workflow/P1.6.5.yaml` at `awaiting_senior_plan_vs_impl, cycle: 1, override_history: []`. 8th consecutive impl-drift-free cycle window; zero overrides this cycle.

The unique value of this pass: the impl satisfies every plan acceptance criterion and every routed R0-A/R0-B/external finding, AND it exposes that **two pieces of plan/ADR text are non-functional as written** because of an interaction the plan-stage reviews could not see at runtime. The junior caught both, resolved them correctly, and surfaced them in the landing notes — but the ADR + plan text still ship the broken shapes. That's the 🟡 routing surface below.

---

## 1. Coverage of plan acceptance criteria

| Atomic | Plan acceptance | Impl | Status |
|---|---|---|---|
| P1.6.5-1 | `memory/` schema + exceptions + `no_llm` constitutional + 7 product-package dep-guards | `schema.py` (3 models frozen+forbid, 3 enums, 3 id-gens) + `exceptions.py` (4 classes incl. `EventNotFoundError` per R0-A-Y2) + `test_constitution.py` + guards in `tests/{core,agents,rooms,derived,autonomy,skills,llm}` (7; **no `workflow/` guard** per external Y10) | ✅ |
| P1.6.5-2 | `init_memory_schema` + `record_hypothesis` (+ source-event existence check) + EventStore split + INSERT-time FK + on-disk migration + UNIQUE + entry-guard | `store.py` matches D2/D5; SCHEMA has `UNIQUE` (Y9); existence check (≥3 batched / else per-id) raises `EventNotFoundError`; `test_insert_time_fk_enforcement` + `test_on_disk_migration` present; EventStore split via `_append_body` + entry-guarded `append_in_transaction` | ✅ (see Y1 on the split shape) |
| P1.6.5-3 | `DecisionMeta` +3 fields, `str\|None`, `@model_validator` co-presence, `Field(pattern=…)` | exact match to ADR-016 D8 (`Annotated[str, Field(pattern=…)]` + co-presence validator); 52 `test_event` functions incl. co-presence + prefix-bypass | ✅ |
| P1.6.5-4 | `promote_hypothesis` (drops `conn`, derives `event_store.conn` per Y7) + `lookup_verified_knowledge` (empty→`ValueError` per Y4) + both atomicity tests + double-promote | `promotion.py` no `conn` param; `lookup.py` empty raises; `test_promotion.py` has `test_atomicity_vk_insert_fails_rolls_back_event` + `test_atomicity_append_fails_rolls_back` + `test_double_promote_unique_constraint` (13 tests) | ✅ (see Y2 on event actor) |
| P1.6.5-5 | e2e Scenario X (3-room) + room_id pin + atomicity sub-test + source≠sink | `test_p1_6_5_e2e.py` 2 tests; room_id=room1 asserted (7e); cross-room lookup from room3; UNIQUE-collision atomicity sub-test asserts decision-event rollback + status PENDING | ✅ |
| P1.6.5-6 | handoff §4.5/§5.8/§10 + 6-row tracking + 5-surface scan + state advance | landing commit `5cd6f34`: tracking table (6 rows, SHAs), 5-surface scan, handoff all 3 sections updated with ADR-016 cites + deferrals, gate summary, state advance | ✅ |

All six atomics map 1:1 to commits with the correct per-atomic subjects (RC-17). All routed findings from the three plan-stage reviews are present in the impl: R0-A Y1-Y6, proxy Y1-Y6, external Y7-Y11. No deferred item (Entity full impl, ProjectArchive, matcher, external ground-truth, UI, `hypothesis` auto-mirror) was opportunistically bundled — W-004-2 (c) literal-reading held.

---

## 2. Findings

### 🟡 Y1 — The entry guard (proxy Y2) makes ADR-016 D11's example code AND plan P1.6.5-2's `append`-wrapper shape non-functional as written; impl resolved correctly but the canonical text still ships the broken shapes

**Where:** `ADR-016` D11 example block; plan `P1.6.5-2` "EventStore split" block; resolved in `src/orchestrator/core/event_store.py:235-247` (`append_in_transaction` guard) + `src/orchestrator/memory/promotion.py:97-128` (reordered sequence). Surfaced by the junior in landing commit `5cd6f34` IMPLEMENTATION NOTES 1+2.

**What:**

The proxy-Y2 entry guard (absorbed into ADR-016 D11 in the 2nd revision) is implemented as:

```python
def append_in_transaction(self, event: Event) -> EventId:
    if not self.conn.in_transaction:
        raise RuntimeError(...)
```

Python sqlite3 (default isolation) only sets `conn.in_transaction = True` **after the first DML statement** — not on entry to a `with conn:` block. Two consequences the plan-stage reviews could not see:

1. **ADR-016 D11 example code would raise.** The D11 block (2nd-revision text) shows `append_in_transaction(decision_event)` as the **first** statement inside `with conn:`. At that point no DML has run → `in_transaction` is `False` → the guard fires `RuntimeError`. The ADR's own example violates the ADR's own guard.

2. **Plan P1.6.5-2's `append` wrapper would raise.** The plan specifies `append(event)` becomes `with self.conn: return self.append_in_transaction(event)`. Same problem: `append_in_transaction` is the first statement in the block → guard fires. The plan's literal refactor shape is non-functional.

**How the impl correctly resolved it (and why it's right):**

- **EventStore split** factors a private `_append_body(event, normalized_metadata)` (no transaction) that *both* `append` (self-managed `with self.conn:`) and `append_in_transaction` (caller-managed, guarded) call. The guard lives only in `append_in_transaction`. `validate_metadata` runs in both paths. 6 existing `append` callers unaffected (verified: `tests/core/test_event_store.py::test_append_wrapper_behavior_preserved` + full suite green). This is **better** than the plan's "thin wrapper" phrasing.
- **promotion.py reorders** the D11 sequence from a→b→c (append → VK insert → status UPDATE) to **c→a→b** (UPDATE status first to start the transaction so `in_transaction` becomes `True`, then `append_in_transaction`, then VK INSERT). Atomicity is unchanged — all three writes are in one `with conn:` block; commit-on-exit / rollback-on-exception. Verified by `test_atomicity_*` (3 tests) + e2e atomicity sub-test (decision event rolled back, status stays PENDING).

**Why it's a finding (not just an impl note):** the impl is correct, but **ADR-016 (Accepted) D11 and plan P1.6.5-2 still contain code that raises if followed verbatim.** ADR-016 governs every future module that wants transaction-atomic event-stream + own-table writes (D11 explicitly frames `append_in_transaction` as a reusable cross-module primitive). The next author who copies the D11 example hits `RuntimeError`. There is also a latent contract subtlety the guard's text does not state: the guard cannot distinguish "first statement inside `with conn:`" (legitimate) from "bare call outside any transaction" (the footgun) — both have `in_transaction == False` — so it (a) false-positives on natural append-first usage, forcing the DML-first dance, and (b) still passes a bare call that follows an earlier uncommitted DML on the same connection. The guard partially closes the footgun proxy-Y2 targeted, at the cost of a non-obvious caller contract.

**Architect call needed** (this is an amendment to an **Accepted** ADR, so it's architect-only):
- **(a)** Amend ADR-016 D11 example + plan P1.6.5-2 to match the impl: show the `_append_body` factoring, and document the "issue a DML before calling `append_in_transaction`" contract (mirror promotion.py's UPDATE-first ordering). Mechanical doc-to-impl reconciliation. **Senior lean: α (a)** — the impl is the correct shape; the text should follow it, and the caller-contract subtlety deserves one explicit sentence + a forward-amendment hook.
- **(b)** Reconsider the guard mechanism (e.g., a sentinel the caller sets, or accept docstring-only). Heavier; the impl already works, so this is optional.
- **(c)** Accept the inconsistency as "example is illustrative, impl is canonical." Cheapest, but leaves an Accepted ADR with example code that raises — weak per the project's no-orphan-spec bias.

This is the canonical plan-vs-impl catch: an interaction visible only when the guard (added at plan stage) meets the transaction sequence (specified at plan stage) **at runtime**. Neither R0-A, proxy R0-B, nor external R0-B surfaced it — they reviewed the two pieces separately. Credit to the junior for catching it during impl and surfacing rather than silently working around.

### 🟡 Y2 — Promotion's `decision` event records the act but not the promoting user; `user_id` lives only in the VK row, not the canonical event stream

**Where:** `src/orchestrator/memory/promotion.py:78-92` (decision event construction).

**What:** the promotion `decision` event is built with `author="system"` and metadata `{based_on, trade_offs, promotion, hypothesis_id, vk_id}` — **no `user_id`**. The promoting user (`"peidong"` in the e2e) is persisted only in `verified_knowledge.promoted_by_user_id`.

**Why it's a finding:** ADR-016 D8 + brief architect-settled #7 frame promotion as **a user decision** ("(b) user-confirm" is the whole mechanism shipping this cycle; `handoff.md` §4.5 "用户显式确认"). Principle 1 (ADR-001) makes the event stream the canonical record of what happened. A pure event-stream audit ("who promoted hypothesis X?") cannot answer from the `decision` event alone — the actor is `system`, and the user attribution is only in the VK table. Mitigating facts: the VK row is authoritative durable storage (not a rebuildable derived cache), so the attribution is not at risk of loss; and `is_valid_author` would not accept an arbitrary `user_id` string as `author` directly. But the asymmetry — a *user decision* whose canonical event omits the user — is a real gap the plan did not pin (neither the plan nor ADR-016 specified where `user_id` lands in the event).

**Architect call needed:**
- **(a)** Add `user_id` to the `decision` event metadata (one key; `promote_hypothesis` already has it). Makes the canonical event self-describing. **Senior lean: mild α (a)** — cheap, and it closes the Principle-1 completeness gap for the cycle's headline mechanism.
- **(b)** Accept VK-row-only attribution — the act is in the event log, the actor is in durable VK storage; rule the event need not carry the user. Defensible; record the rationale in ADR-016 D3.

Not blocking (promotion works, attribution is durably stored); routes to architect because it's a Principle-1 / contract-completeness judgment the plan left unpinned.

### 🟢 G1 — `memory/schema.py` matches ADR-016 D2 field-for-field
3 models frozen + `extra="forbid"`; `Hypothesis` (incl. `candidate_for_promotion`), `VerifiedKnowledge` (incl. `contradictions: list[VKId]`, `UNIQUE`-backed `promoted_from_hypothesis_id`), `Entity` stub; 3 id-generators with `hyp_`/`vk_`/`ent_` prefixes. 27 schema tests.

### 🟢 G2 — `lookup.py` matches D6 exactly
Empty `topic_tags` raises `ValueError` (Y4); scope-exact + tag OR-semantics (Python set-intersection); `ORDER BY last_validated DESC, id ASC` deterministic; no LLM/ranking. 6 tests.

### 🟢 G3 — `DecisionMeta` extension matches D8 exactly
`str | None` (deliberate-duplication, no `memory/` import — constitutional guard green), `Field(pattern=…)` prefix constraints (proxy Y5), `@model_validator` co-presence (R0-A Y3). Promotion events round-trip through `validate_metadata` inside both append paths.

### 🟢 G4 — EventStore split is cleaner than the plan's phrasing and behavior-preserving
`_append_body` shared helper; `validate_metadata` preserved in both `append` and `append_in_transaction`; all 6 callers (incl. `rooms/runtime.py:103`, the one the original plan grep missed and proxy-Y1 corrected) unaffected — full suite + `test_append_wrapper_behavior_preserved` green. (The plan-text shape that *would* have broken is Y1.)

### 🟢 G5 — Dependency-direction guard set is exactly the 7 product packages (external Y10)
`core/agents/rooms/derived/autonomy/skills/llm` each guard `does_not_import_memory`; **no `workflow/` guard** (dev-harness, correctly skipped per external Y10's refinement of proxy Y4). `memory/` itself has the `no_llm_calls` constitutional test.

### 🟢 G6 — Both required atomicity tests + the double-promote backstop are present and pass
`test_atomicity_vk_insert_fails_rolls_back_event`, `test_atomicity_append_fails_rolls_back` (plan required both), `test_double_promote_unique_constraint` (Y9). e2e atomicity sub-test independently re-validates rollback under the reordered sequence — strong evidence the c→a→b reorder (Y1) preserves atomicity.

### 🟢 G7 — On-disk migration (Y11) + INSERT-time FK (proxy Y3 / external Y8) are tested, not just asserted
`test_on_disk_migration` (init event_store on disk, append, close/reopen, `init_memory_schema`, assert tables + preserved row counts + working CRUD); `test_insert_time_fk_enforcement` (CREATE succeeds out-of-order; INSERT raises). Converts the two ADR-D5 claims from asserted to verified.

### 🟢 G8 — `record_hypothesis` producer-time existence check (R0-A Y2) honors ADR-016 D2:155
Batched `SELECT … IN (…)` for ≥3 ids / per-id `SELECT` otherwise; raises `EventNotFoundError` before any INSERT; happy + sad path tested. The D2:155 integrity-guarantee claim is now true in code.

### 🟢 G9 — Gates green + 5-surface scan honest about the formatting scope-bleed
ruff/format/mypy/pytest all pass (893). The landing commit's verify-workspace note explicitly discloses that `workflow/{cli,transitions}.py` + `test_constitution_line_endings.py` + `test_integration.py` received **format-only** reflows (verified semantically null: boolean-expr wrapping / set one-per-line / call one-line) bundled to pass the `ruff format --check` gate — pre-existing unformatted-file debt normalized, benign scope-bleed, honestly surfaced rather than hidden.

---

## 3. Cleanliness note (not a finding)

`src/orchestrator/memory/store.py:222` — `_row_to_vk` opens with `from orchestrator.memory.schema import EntityType, VKScope  # noqa: F401 (used via dict)`. Neither symbol is used in the function (`scope` is passed as a raw string and Pydantic coerces it); the `# noqa: F401 (used via dict)` comment is inaccurate and suppresses a real unused-import warning. Harmless (no runtime effect), but a dead import + misleading suppression worth removing in any follow-up touch. Flagged for awareness, not routing.

---

## 4. Verdict

**`needs_architect`** — 0🔴 / 2🟡 / 9🟢.

The implementation is high quality: every plan acceptance criterion met, all 17 routed plan-stage findings (R0-A Y1-6 + proxy Y1-6 + external Y7-11) present and tested, gates green, 893 passing, zero deferred-scope bleed, and the EventStore split + atomicity model are arguably better-factored than the plan specified. The junior surfaced both runtime interactions proactively in the landing notes rather than silently working around them.

The two 🟡 route to the architect because both are contract/text judgments the senior must not decide alone:
- **Y1**: ADR-016 D11 example + plan P1.6.5-2 wrapper shape are non-functional as written (the proxy-Y2 guard fires before the first DML); impl is correct via `_append_body` + DML-first reorder. Lean **α(a)**: amend the Accepted ADR-016 D11 + plan to match impl + document the DML-first caller contract. ADR amendment is architect-only.
- **Y2**: the promotion `decision` event omits the promoting `user_id` (author=`system`; user only in the VK row). Lean **mild α(a)**: add `user_id` to event metadata for Principle-1 completeness; or **(b)** accept VK-row-only and inscribe the rationale.

Per ADR-008 Amendment 1 (W-005 Route B): R0-A fires regardless of this verdict; state advances to `awaiting_R0_A`. The 🟡 findings surface for architect routing after R0-A lands (→ `awaiting_architect_decision` → `awaiting_senior_revision` if routed α, where the ADR/plan amendments + this file's verdict bump would land in a 2nd cycle per RC-10).

## Cross-references
- `docs/process/senior-plans/P1.6.5.md` — plan acceptance criteria (P1.6.5-1 … -6).
- `docs/decisions/ADR-016-cross-room-memory-persistence.md` — D3 (Y2 event actor) + D11 (Y1 entry-guard/sequence); both candidates for the architect-routed amendment.
- `docs/process/reviews/P1.6.5/architect-routing-r0b.md` (proxy Y2 entry guard origin) + `architect-routing-r0b-external.md` (external Y7 drop-conn; Y9 UNIQUE; Y10 guard-set; Y11 migration).
- Impl: `src/orchestrator/memory/{schema,store,promotion,lookup,exceptions}.py`; `src/orchestrator/core/event.py` (DecisionMeta); `src/orchestrator/core/event_store.py` (`_append_body` + `append_in_transaction`); `tests/memory/*`, `tests/integration/test_p1_6_5_e2e.py`, `tests/core/test_event{,_store}.py`.
- `src/orchestrator/core/event_store.py:235-247` (entry guard) + `src/orchestrator/memory/promotion.py:97-128` (c→a→b sequence) — Y1 resolution sites.
