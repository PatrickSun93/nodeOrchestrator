---
task_id: P1.6.5
kind: architect-routing (R0-B proxy-lens, plan stage)
date: 2026-05-28
reviews_acked:
  - R0-B-cross-family.md
decisions:
  Y1: α (senior amends §5 cite block 5→6 + §4 grep results; names rooms/runtime.py:103; P1.6.5-2 adds tests/rooms/ to behavior-preserve set)
  Y2: α (b) (append_in_transaction gains a self.conn.in_transaction guard that raises — explicit raise, NOT bare assert)
  Y3: α (ADR-016 D5 FK-timing sentence corrected to INSERT-time enforcement; P1.6.5-2 test asserts INSERT-time failure not CREATE-time)
  Y4: α (P1.6.5-1 adds 4 dependency-direction guards: autonomy/ + llm/ + skills/ + workflow/ ↛ memory/)
  Y5: α (a) (DecisionMeta hypothesis_id + vk_id gain Field(pattern=…) prefix constraints)
  Y6: γ (keep contradictions field per Principle 9 + D9 semantic-stability; R0-B's defer-option considered + declined)
---

# P1.6.5 architect routing — R0-B proxy-lens findings ("α α α α α γ")

**Architect decisions (this session):** 5 α + 1 γ across R0-B's 6 🟡 findings. Y2 + Y5 sub-options + Y6 keep-vs-defer chosen by architect via architect-partner AskUserQuestion. Distinct routing artifact from `architect-routing.md` (which routed the R0-A-on-plan Y1-Y6, already absorbed at senior revision `748da5b`) — that record stays immutable; this file routes the **different-dimension** findings the proxy-lens R0-B surfaced.

This is the **signal artifact for the second senior revision session**. Senior reads this file + `R0-B-cross-family.md` + current plan + ADR-016, applies the routed actions, pushes a second revision commit on `claude/P1.6.5-plan`, bumps `R0-B-cross-family.md` verdict `needs_architect → clean` per RC-10.

## Independent verification (architect-partner)

Before routing, the architect-partner independently verified R0-B's three empirical claims (Y1, Y3, Y4) — all confirmed true:

- **Y1**: `grep` of `event_store.append(` across `src/orchestrator` → **6 real callers**: `agents/snapshot_dispatch.py:62`, `agents/dispatch.py:135`, `agents/tool_dispatch.py:101`, `autonomy/emission.py:68`, `autonomy/emission.py:86`, **`rooms/runtime.py:103`** (state_transition append on room state change). Senior plan §5 + §4 listed 5, missed `rooms/runtime.py:103`. (`core/event.py:375` `store.append(event)` is a docstring example inside `InvalidParentError`, correctly excluded.) `rooms/` is a layer above `agents/` — senior's "all in agents/ + autonomy/" + "Layering clean" claims (plan §522-523) are both false.
- **Y3**: `python3` test — `CREATE TABLE` with forward FK to nonexistent `rooms` **succeeds** (no raise); first `INSERT` raises `OperationalError: no such table: main.rooms`. So the senior's planned test ("calling before EventStore.init_schema raises") would fail — enforcement is INSERT-time, not CREATE-time. ADR D5 "init order matters [for CREATE]" is technically wrong (it matters for INSERT correctness).
- **Y4**: `find src/orchestrator -maxdepth 1 -type d` → 8 sibling packages (`agents`, `autonomy`, `core`, `derived`, `llm`, `rooms`, `skills`, `workflow`) + new `memory`. Plan guards 4 (`core`, `agents`, `rooms`, `derived`); missing reverse-guards for `autonomy`, `llm`, `skills`, `workflow`.

## Per-finding routing

### Y1 → α — append-caller count + layering claim correction + test-set expansion

**Action:**
- §5 "Verification cites for S1 + S2" + §4 W-004-2 (b) grep results: 5 → **6** callers; add `rooms/runtime.py:103`.
- Strike / correct the false claims: "all in agents/ + autonomy/" → "agents/ + autonomy/ + rooms/"; "Layering clean" → note `rooms/` (above `agents/`) is a caller; the split's behavior-preservation must hold for it too.
- P1.6.5-2 acceptance line 209 ("behavior unchanged" test set): add `tests/rooms/` (wherever `rooms/runtime.py:103` append coverage lives).

**Note for senior (non-blocking nuance):** the `append → append_in_transaction` split is genuinely **safe** for `rooms/runtime.py:103` — it calls the public `append()`, which keeps its `with self.conn:` wrapper unchanged. So Y1 has no actual regression risk; its real bite is (1) the false grep claim and (2) the W-004-2 (b) discipline — the promotion-impact-grep forcing function exists precisely to catch missed callers (P1.5 RC-19 lineage), and it missed one here. Absorb for the discipline signal + claim correctness, not because the split is unsafe.

**Why α:** verified-true factual correction; mechanical. β/γ would leave a false grep claim in a plan that the junior trusts without re-grepping.

### Y2 → α (b) — `append_in_transaction` raise-guard (explicit raise, not assert)

**Action:** `EventStore.append_in_transaction(event)` opens with a transaction-state guard:

```python
def append_in_transaction(self, event: Event) -> EventId:
    if not self.conn.in_transaction:
        raise RuntimeError(
            "append_in_transaction requires an enclosing `with conn:` "
            "block; calling it bare leaves an uncommitted transaction "
            "that can silently lose the appended event"
        )
    # ... validation + INSERT + relations (no outer `with self.conn:`)
```

**Explicit `raise`, NOT bare `assert`** — `assert` statements strip under `python -O`, and this guards a *silent data-loss* path (verified: Python sqlite3 default isolation auto-begins on DML but does not auto-commit; a bare `append_in_transaction` leaves an open transaction that loses the event if the connection closes without commit). The guard makes D11's atomicity guarantee **mechanical**, surviving any future consumer who uses the method without reading the docstring.

**Plan + ADR updates:**
- P1.6.5-2 acceptance line 210: replace "(c) calling outside a `with conn:` results in auto-commit per default sqlite3 isolation (documented behavior; not recommended)" with "(c) calling `append_in_transaction` outside a `with conn:` raises `RuntimeError` (guard at method entry); the silent-loss path is closed mechanically." Add a test: bare call raises; call inside `with conn:` succeeds.
- ADR-016 D11: note the entry guard as part of the `append_in_transaction` contract.

**Why α(b) over (a)/(c):** (a) docstring-only leaves a procedural (not mechanical) guarantee on a silent-data-loss footgun — too weak given Principle 1. (c) make-private would work (memory/promotion.py is the only P1.6.5 consumer) but contradicts D11's stated intent of a reusable cross-module atomicity primitive; the guard preserves the public-primitive intent while closing the edge. Architect picked (b).

### Y3 → α — FK enforcement timing correction (INSERT-time, not CREATE-time)

**Action:**
- ADR-016 D5 line 249: "The FK enforcement requires the referenced tables to exist; init order matters." → "The FK enforcement triggers at **INSERT time**, not CREATE time; SQLite records forward FK references at `CREATE TABLE` regardless of whether the referenced table exists. Init order (`EventStore.init_schema` first) is recommended convention; calling `init_memory_schema` against a connection lacking events/rooms yields a **deferred** failure (the first INSERT into a memory table with FK refs raises `no such table`)."
- P1.6.5-2 acceptance line 205: test asserts **INSERT-time** failure on wrong init order (not CREATE-time raise). The existing "calling before EventStore.init_schema raises" wording is removed — that test cannot pass.

**Why α:** verified-true; prevents the junior writing a `pytest.raises` test that catches nothing (CREATE succeeds) and over-engineering a defensive CREATE-time table-existence check against soft semantics.

### Y4 → α — complete the dependency-direction guard set (8 of 8)

**Action:** P1.6.5-1 adds 4 reverse-direction guards mirroring the existing pattern (`forbidden_patterns = ["from orchestrator.memory", "import orchestrator.memory"]`):
- `tests/autonomy/test_constitution.py` — `test_constitution_autonomy_does_not_import_memory`
- `tests/llm/test_constitution.py` — `test_constitution_llm_does_not_import_memory`
- `tests/skills/test_constitution.py` — `test_constitution_skills_does_not_import_memory`
- `tests/workflow/test_constitution.py` — `test_constitution_workflow_does_not_import_memory`

(Plus the 4 already planned: core / agents / rooms / derived → 8 of 8 sibling packages.)

**Architect-partner acknowledgment:** **this is an R0-A-on-plan miss too.** My R0-A G7 praised the parallel set as "file-disjoint" but did not enumerate the full 8-sibling guard set; R0-B's cross-lens caught the completeness gap. Recording honestly — the dual-lens value is exactly this kind of catch (in-family review under-weighted "did anyone enumerate the full sibling set?").

**Why α:** completeness fix; 4× 5-line mirrors; same atomic, no new files; tightens the layering invariant before any sibling package has a reason to break it. `autonomy/` is the most load-bearing guard (handoff §3.1 — autonomy scoring must not become a function of memory-query results, which would breach "code-driven decisions").

### Y5 → α (a) — prefix-pattern constraints on `DecisionMeta` ID fields

**Action:** `DecisionMeta.hypothesis_id` + `vk_id` gain `Field(pattern=…)` prefix constraints:

```python
hypothesis_id: Annotated[str, Field(pattern=r"^hyp_[0-9a-f]{32}$")] | None = None
vk_id: Annotated[str, Field(pattern=r"^vk_[0-9a-f]{32}$")] | None = None
```

This closes the prefix-bypass path the co-presence `@model_validator` (Y3-of-R0-A) does NOT catch: swapped IDs (`vk_…` as hypothesis_id), event-ids, and empty strings currently validate. Because promotion events land in the canonical event stream (Principle 1 — event log is permanent truth), a malformed promotion event is a permanent broken-ref; closing it at the schema layer (the earliest write-path point) is worth the mild duplication of `memory/schema.py`'s id format.

**Plan + ADR updates:**
- ADR-016 D8: add the pattern constraints to the code block + a sentence ("prefix-correctness is schema-enforced; complements the co-presence validator").
- P1.6.5-3 acceptance: +tests — wrong-prefix (`hypothesis_id="vk_…"`), empty-string, and event-id values raise ValidationError.

**Why α(a) over (b)/(c):** Principle 1 makes the canonical-stream gap matter more than the "standard path is safe" mitigation; (a) closes it cheaply at the truth layer. (b) accepts a permanent-truth gap; (c) defers a cheap fix. Architect picked (a).

### Y6 → γ — keep `contradictions` field (R0-B's defer-option considered + declined)

**Decision:** **keep** `VerifiedKnowledge.contradictions: list[VKId]` as planned. γ (decline R0-B's defer suggestion; no plan/ADR change to the field itself).

**Rationale (recorded):**
- D9 already pinned the VK-to-VK semantic (architect-partner R0-A G5 affirmed it). Deferring the field **reopens** that pinned decision; re-litigating D9 in a future cycle costs more discussion than the `ADD COLUMN` it saves.
- An empty, queryable, frozen field is near-free; Principle 9 (inscribe vocabulary before producer) is the project's standing bias and applies cleanly here.
- R0-B's strongest counter (ADD COLUMN is cheap SQLite-native migration) is acknowledged — but it argues migration is *cheap*, not that the field is *harmful*; the semantic-stability of a pinned ADR decision outweighs a deferred-and-cheap-to-add column.

**ADR-016 D9 amendment (record the considered-and-declined):** add a sentence: "R0-B (proxy lens) surfaced defer-the-field as an option (ADD COLUMN later is cheap); architect routing γ — keep, because D9's VK-to-VK semantic is already pinned and deferring reopens it. The field ships empty + queryable in P1.6.5; the first contradiction-producer cycle writes it."

**Asymmetry note (for senior awareness):** R0-B correctly distinguished `evidence` (has a producer — `promote_hypothesis` arg) from `contradictions` (no producer this cycle). The γ decision keeps `contradictions` despite the zero-producer asymmetry; the semantic-already-pinned argument is what carries it, not symmetry with `evidence`.

## Combined second-revision shape

Senior absorbs all 6 R0-B routings on `claude/P1.6.5-plan` in a second revision commit:

**ADR-016 amendments:**
- D5: FK-timing sentence → INSERT-time (Y3).
- D8: add `Field(pattern=…)` to hypothesis_id/vk_id + prefix-enforcement sentence (Y5).
- D9: record considered-and-declined defer-option (Y6 γ).
- D11: note `append_in_transaction` entry guard as part of the contract (Y2).

**Plan amendments:**
- §5 cite block + §4 grep: 5 → 6 callers; name `rooms/runtime.py:103`; correct "Layering clean" (Y1).
- P1.6.5-1: +4 dependency-direction guards (autonomy/llm/skills/workflow ↛ memory) (Y4).
- P1.6.5-2: behavior-preserve test set +`tests/rooms/` (Y1); `append_in_transaction` raise-guard + test (Y2); FK init-order test → INSERT-time failure (Y3).
- P1.6.5-3: +prefix-pattern tests (Y5).
- P1.6.5-6: test-delta expectation bumps (~+8: Y2 guard test, Y3 reshaped, Y4 ×4 guards, Y5 prefix tests).

**Verdict bump (RC-10):** senior bumps `R0-B-cross-family.md` frontmatter `needs_architect → clean` at the second revision commit (Y1+Y3+Y4 → 🟢 absorbed; Y2+Y5 → 🟢 absorbed with chosen sub-option; Y6 → 🟢 keep-with-recorded-rationale). 12th project use of RC-10 verdict-bump; 6th under codified protocol.

## External (true cross-family) R0-B — still pending

Per the proxy-lens caveat (`R0-B-cross-family.md` line 18 + 264): this routing covers the **proxy lens** only. The true cross-family external session (per `external-r0b-prompt.md`) is dispatched separately by the architect, OR γ-overridden (skipped) as in P1.6 cycle-2. **Not decided in this routing** — surface separately. If dispatched, its findings append to `R0-B-cross-family.md` as a new section with file-level verdict bumping per `dual-lens-r0b.md`.

## Pattern-recurrence notes

- **Second AskUserQuestion sub-option routing in one cycle** (R0-A routing had Y2+Y4 sub-options; this R0-B routing has Y2+Y5+Y6). The "α/γ with sub-option" pattern is now 2 instances in P1.6.5 alone — strengthens the codification candidate flagged in `architect-routing.md` (consider a `senior-planner.md` / role-doc note on "routing sub-option capture" if it recurs in the next 1-2 cycles).
- **Dual-lens caught what single-lens missed**: Y1 (grep miss), Y3 (FK timing), Y4 (layering-set completeness — also R0-A's own miss) are all findings the R0-A-on-plan lens did not surface. First clean demonstration in P1.6.5 that the proxy R0-B adds non-overlapping value at plan stage (R0-A found contract/consistency issues; R0-B found operational/completeness/cite-correctness issues). Reinforces RC-15 dual-lens dispatch discipline.
- **First γ routing at plan stage in the α-streak window**: prior 4 cycles (W-003/P1.5.5/P1.6/P1.6.5-R0A) were all-α. Y6 γ is the first non-α plan-stage routing — a keep/decline, not a defer or override-of-substance. Discipline gradient note: γ-keep is the lightest non-α (no work; record rationale), so the "α-discipline gradient" is not broken, just nuanced.

## Cross-references

- `docs/process/reviews/P1.6.5/R0-B-cross-family.md` — findings detail (proxy lens; 6🟡/4🟢).
- `docs/process/reviews/P1.6.5/architect-routing.md` — R0-A-on-plan routing (Y1-Y6, all α, absorbed at `748da5b`); immutable record.
- `docs/process/reviews/P1.6.5/R0-A-on-plan.md` — G5 affirmed D9 VK-to-VK pin (Y6 rationale); G7 is the layering-set miss (Y4 acknowledgment).
- `docs/decisions/ADR-016-cross-room-memory-persistence.md` — D5 (Y3) + D8 (Y2 guard note + Y5 pattern) + D9 (Y6) + D11 (Y2) amended.
- `docs/process/senior-plans/P1.6.5.md` — §4/§5 grep (Y1) + P1.6.5-1 guards (Y4) + P1.6.5-2 (Y1+Y2+Y3) + P1.6.5-3 (Y5).
- `docs/process/dual-lens-r0b.md` RC-15 — dual-lens dispatch; external session append convention.
- `docs/process/reviews/README.md` § RC-10 — verdict-bump protocol (R0-B-cross-family.md bumps at second revision).
- Verified runtime cites: 6 `event_store.append` callers incl `rooms/runtime.py:103` (Y1); FK INSERT-time enforcement via `python3` test (Y3); 8 sibling packages via `find` (Y4).
