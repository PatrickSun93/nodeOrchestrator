---
task_id: P1.6.5
round: R0-B-proxy-lens
reviewer_lens: in-session-proxy (Claude with contrarian prompt; not true cross-family)
reviews_acked:
  - architect-briefs/P1.6.5.md
  - senior-plans/P1.6.5.md
  - decisions/ADR-016-cross-room-memory-persistence.md
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 10
verdict_history:
  - verdict: needs_architect
    at_commit: 3b15115
    findings_count: { red: 0, yellow: 6, green: 4 }
    note: original — proxy-lens R0-B surfaced 6 Y (Y1 grep miscount; Y2 append_in_transaction footgun; Y3 FK-timing; Y4 layering-set incomplete; Y5 prefix-bypass; Y6 keep-vs-defer contradictions).
  - verdict: clean
    at_commit: HEAD
    findings_count: { red: 0, yellow: 0, green: 10 }
    note: 2nd senior revision absorbed all 6 routings (architect-routing-r0b.md = α α α α α γ; Y4 package set refined 4→3 per external Y10). Y1-Y5 → 🟢 absorbed; Y6 → 🟢 keep-with-recorded-rationale (γ). Cross-reference architect-routing-r0b.md + architect-routing-r0b-external.md.
---

> **RC-10 verdict bump (post-routing-revision)** — frontmatter as live signal. Bump applied after senior absorbed the proxy R0-B routing (`architect-routing-r0b.md`, `99f9182`) into the 2nd revision commit on this branch. Per RC-10 codification (`docs/process/reviews/README.md` §RC-10); 12th project use; original findings preserved as audit trail below.
>
> Absorption per finding:
> - **Y1 → 🟢 absorbed** — §4/§5 grep corrected 5→6 callers (named `rooms/runtime.py:103`); false "Layering clean" claim struck; P1.6.5-2 behavior-preserve set + `tests/rooms/`.
> - **Y2 → 🟢 absorbed** — `append_in_transaction` gains explicit-`RuntimeError` entry guard (ADR-016 D11 + P1.6.5-2 + test).
> - **Y3 → 🟢 absorbed** — ADR-016 D5 + P1.6.5-2 FK enforcement corrected CREATE-time → INSERT-time (external Y8 independently confirmed).
> - **Y4 → 🟢 absorbed** — dep-guard set 4 → 7 product packages (add autonomy/skills/llm; `workflow/` skipped per external Y10 refinement, which supersedes this finding's original 4-package recommendation).
> - **Y5 → 🟢 absorbed** — `DecisionMeta` ID fields gain `Field(pattern=…)`; ADR-016 D8 + P1.6.5-3 + 3 prefix-bypass tests.
> - **Y6 → 🟢 keep (γ)** — `contradictions` field kept; ADR-016 D9 records the considered-and-declined defer-option. Semantic-already-pinned (R0-A G5) outweighs deferral.

## Caveat

This is the **proxy lens** — in-session Claude with a contrarian prompt, not an external session. The true cross-family R0-B pass (GPT-5 / DeepSeek / Gemini per `docs/process/reviews/P1.6.5/external-r0b-prompt.md`) is dispatched separately by the architect; the structural biases that bound this review (in-family training pull toward the senior's Pydantic + ADR-014-precedent framing, sympathy with the deliberate-duplication chain reasoning, over-weighting of textual rigor relative to runtime failure modes) are not corrected here, only partially counter-pulled.

R0-A-on-plan already absorbed Y1-Y6 (D8 layering, source_event_ids integrity, DecisionMeta co-presence, lookup empty-tags, promotion event room_id, record_hypothesis ↔ event atomicity) on this same branch via the senior revision at `748da5b`. The findings below probe **different** dimensions — primarily runtime / operational failure modes, layering-set completeness, schema invariant gaps not caught by the @model_validator, and verification-cite gaps in the post-revision plan + ADR. Pass count is honest, not manufactured.

## Findings

### 🟡 Y1 — Plan §5 verification cites count "5 EventStore.append callers" but actual count is 6; missed `rooms/runtime.py:103`

**Where:** `docs/process/senior-plans/P1.6.5.md` §5 "Verification cites for S1 + S2" (line 507) and §4 W-004-2 (b) promotion-impact grep results (lines 521-523):

```
- 5 EventStore.append callers grep'd: `agents/dispatch.py:135`,
  `agents/tool_dispatch.py:101`, `autonomy/emission.py:68 + :86`,
  `agents/snapshot_dispatch.py:62` — verified by grep.
```

The plan also states "all in `agents/` and `autonomy/`" (line 522).

**What's actually there** (grep `grep -rn "event_store\.append(" src/orchestrator --include='*.py'` excluding comments + relations.append):

1. `src/orchestrator/agents/snapshot_dispatch.py:62`
2. `src/orchestrator/agents/dispatch.py:135`
3. `src/orchestrator/agents/tool_dispatch.py:101`
4. `src/orchestrator/autonomy/emission.py:68`
5. `src/orchestrator/autonomy/emission.py:86`
6. **`src/orchestrator/rooms/runtime.py:103`** (state_transition event append on room state change)

**Why it matters:**

The W-004-2 (b) "promotion-impact systematic grep" forcing function exists *because* missed callers in past cycles caused regressions. The miss is exactly the bias the rule was codified to prevent (P1.5 RC-19 lineage). The senior plan claim "no callers of `event_store.append` from outside `agents/` + `autonomy/`" is **false**; `rooms/runtime.py:103` calls it during room state transitions. This also affects the plan's layering narrative (claim line 523: "Layering clean") — `rooms/` is a layer above `agents/`.

The behavior-preservation guarantee for the `append → append_in_transaction` split (P1.6.5-2 acceptance line 209) lists test files in agents/ + autonomy/ + core/ but **omits `tests/rooms/test_runtime.py`** (or wherever runtime.append's coverage lives). If the split changes timing of the `with self.conn:` exit relative to the appended event being visible to a subsequent room state read, runtime tests may surface a regression that the plan's acceptance criteria doesn't gate against.

**Recommendation:** Senior amends §5 cite block + §4 grep results to 6 sites, names `rooms/runtime.py:103`, and P1.6.5-2 acceptance line 209 adds `tests/rooms/` to the "behavior unchanged" test set. Architect-routing: not load-bearing for the ADR (D11 mechanism unchanged); load-bearing for "junior trusts the grep results without re-grepping" failure mode.

**Lean: α** (absorb — single cite-block amendment + test set expansion).

### 🟡 Y2 — Plan P1.6.5-2 acceptance (c) on `append_in_transaction` outside `with conn:` is technically incorrect under Python sqlite3 default isolation

**Where:** `docs/process/senior-plans/P1.6.5.md` P1.6.5-2 acceptance line 210:

> (c) calling `append_in_transaction` outside a `with conn:` results in auto-commit per default sqlite3 isolation (documented behavior; not the recommended pattern).

**What's actually true** (verified by `python3 -c "import sqlite3; conn=sqlite3.connect(':memory:'); conn.execute('CREATE TABLE t (x INTEGER)'); conn.execute('INSERT INTO t VALUES (5)'); print(conn.in_transaction)"` → `True`):

Python sqlite3's **legacy default** `isolation_level=""` is `Connection.isolation_level=""`, which means the driver auto-begins a transaction on DML, but does NOT auto-commit. The transaction stays open until an explicit `commit()` call OR a `with conn:` `__exit__` fires. Calling `append_in_transaction` raw (no enclosing `with conn:` and no explicit commit by caller) leaves an open transaction; the INSERT is durable only after the next implicit commit point — which may never come if the connection is closed without commit, **losing the appended event silently**.

**Why it matters:**

This is a footgun in a public method that just got promoted to API surface. The documented behavior is exactly opposite the project's "append-only is the load-bearing invariant" framing — under default isolation, raw `append_in_transaction` produces a silent-loss path that doesn't exist with the existing `append()` (which has `with self.conn:` enforcing commit).

The plan calls this "documented behavior; not the recommended pattern" — but for an EventStore method, the gap between "not recommended" and "guaranteed-not-to-silently-lose-events" is the API contract distance.

**Why this matters for D11 specifically:**

D11 (ADR-016 line 395-419) pins `append_in_transaction` as a public method to support cross-module atomicity. But the public-method-with-footgun shape pushes the failure mode out of `memory/promotion.py` (the intended single consumer in P1.6.5) into "any future consumer who reads the method name and uses it without an enclosing `with conn:`." Cf. Principle 9: every public API is a future commitment; this one ships with a sharp edge.

**Three options for architect:**

- **(a) Document it harder**: docstring of `append_in_transaction` warns explicitly + names "must be called inside a `with conn:` block; otherwise events may not be durably committed." Cheapest. Junior writes a docstring test.
- **(b) Runtime guard**: `append_in_transaction` calls `assert self.conn.in_transaction, "append_in_transaction requires enclosing with conn:"`. One-line guard; closes the silent-loss path. Mildly violates "let the caller manage the transaction" mental model.
- **(c) Make `append_in_transaction` private** (`_append_in_transaction`): the public `append(event)` stays the only public path; `memory/promotion.py` calls `event_store._append_in_transaction(event)` with a name-mangling acknowledgment. Most defensive; "underscore = private" project convention.

The senior plan acceptance criterion (c) implicitly admits the gap exists ("not recommended") without closing it; the cross-family lens reads this as a design-stage decision that should be pinned, not deferred to "consumer hygiene."

**Lean: α toward (b)** (runtime guard) — closes the silent-loss path at the cost of one line; D11 atomicity guarantee then survives the "future consumer who doesn't read the docstring" failure mode. (b) is the smallest defensive change that makes the guarantee mechanical, not procedural.

### 🟡 Y3 — ADR-016 D5 + plan P1.6.5-2 acceptance overstate FK enforcement as requiring init order; CREATE order is actually soft

**Where:** ADR-016 D5 line 249:

> Both schema-init functions are idempotent (`CREATE TABLE IF NOT EXISTS`). Calling order is `event_store.init_schema` first (memory tables FK-reference `events` and `rooms` per D2). **The FK enforcement requires the referenced tables to exist; init order matters.**

Plan P1.6.5-2 acceptance line 205:

> `init_memory_schema` requires `events` and `rooms` tables to exist first (FK enforcement); test verifies init order — calling before `EventStore.init_schema` raises (FK reference resolves at trigger time but SQLite tolerates forward refs by default; the test asserts the documented init order works).

**What's actually true** (verified by `python3` test creating `hypothesis` with FK to nonexistent `rooms`):

```
CREATE succeeded with forward FK to nonexistent rooms
INSERT failed: no such table: main.rooms
```

SQLite tolerates forward FK references at `CREATE TABLE` — the FK is recorded but not enforced until an INSERT triggers it. So calling `init_memory_schema(conn)` BEFORE `EventStore.init_schema(conn)` **does not raise** — the test in the plan ("calling before `EventStore.init_schema` raises") will fail because the operation succeeds silently. The first INSERT after the wrong init order raises `no such table: main.rooms` from the *FK trigger*, not from CREATE.

The parenthetical in the plan ("FK reference resolves at trigger time but SQLite tolerates forward refs by default") correctly identifies this — but the rest of the sentence ("the test asserts the documented init order works") then asserts the wrong test. ADR D5's "init order matters" is **soft**: it matters for *correctness at insert time*, not for *schema-init success*.

**Why it matters:**

- The test the plan specifies will fail when junior writes it (silently or with `pytest.raises` not catching anything).
- The doc claim "init order matters [for CREATE]" is technically wrong; junior may write `init_memory_schema` to defensively raise if `rooms` is missing, which is over-engineering against soft semantics.
- The cleaner shape: state explicitly "init order is recommended for clarity; `CREATE` is order-insensitive in SQLite; subsequent INSERT fails if order was wrong." Test verifies the INSERT-time failure, not the CREATE-time failure.

**Recommendation:** ADR-016 D5 sentence "The FK enforcement requires the referenced tables to exist; init order matters" → "The FK enforcement triggers at INSERT time; init order is recommended convention but `CREATE` succeeds regardless. Calling `init_memory_schema` against a connection lacking the events/rooms tables yields a deferred failure mode (first INSERT into a memory table with FK refs raises `no such table`)." Plan P1.6.5-2 acceptance: test verifies "INSERT after wrong init order raises," not "CREATE raises."

**Lean: α** (absorb — small textual correction in ADR + plan; prevents junior writing a broken test).

### 🟡 Y4 — Layering guard set is incomplete; `llm/`, `skills/`, `workflow/` ↛ `memory/` not guarded

**Where:** Plan P1.6.5-1 (lines 36-39) ships 4 dependency-direction guards:

- `tests/core/test_constitution.py` — `test_constitution_core_does_not_import_memory`
- `tests/agents/test_constitution.py` — `test_constitution_agents_does_not_import_memory`
- `tests/rooms/test_constitution.py` — `test_constitution_rooms_does_not_import_memory`
- `tests/derived/test_constitution.py` — `test_constitution_derived_does_not_import_memory`

The 9-package set (verified: `find src/orchestrator -maxdepth 1 -type d`) is: `agents`, `autonomy`, `core`, `derived`, `llm`, `rooms`, `skills`, `workflow` + new `memory`. The plan guards 4 of 8 sibling packages. Missing: `autonomy/`, `llm/`, `skills/`, `workflow/`.

**Why it matters:**

- `autonomy/`: handoff §3.1 establishes the autonomy module decides whether agents emit; memory contents (verified knowledge cross-room) could plausibly inform future autonomy scoring (e.g., "autonomy decision relies on whether the room's claim is contradicted by a VK"). The guard's absence makes it implicit-allowed for a future cycle to introduce that dependency — possibly contradicting the "code-driven decisions" invariant if autonomy scoring becomes a function of memory query results.
- `llm/`: an LLM-augmented promotion or matcher (architect explicitly defers per brief Out-of-scope) would surface here as `llm/parsers/` reading memory rows — the kind of layering breach the constitutional test was designed to catch.
- `skills/`: skill loading is per-agent; if a skill loader imports memory schema for "what fields can a skill reference," that's a layering breach.
- `workflow/`: orchestrator workflow CLI imports memory if it ever surfaces a `workflow memory dump` command; the guard would force an ADR amendment before that lands.

The senior plan does correctly enforce the **reverse** direction (memory may import core; core MUST NOT) but only for 4 of 8 reverse-direction guards. The asymmetry is a tell that the senior thought "core/agents/rooms/derived are the layers I touched, those are the ones to guard," missing the 4 layers untouched-this-cycle that constitute the layering set.

Note: this is **R0-A's miss too** — the R0-A-on-plan absorbed Y1-Y6 but didn't surface layering-set completeness. Cross-family lens specifically pulls toward "did anyone enumerate the full sibling set?"

**Recommendation:** Plan P1.6.5-1 adds 3-4 guards covering `autonomy/`, `llm/`, `skills/`, `workflow/` ↛ `memory/`. Each is a 5-line mirror of the existing pattern (`forbidden_patterns = ["from orchestrator.memory", "import orchestrator.memory"]`). Same atomic; no new files; +4 small tests.

**Lean: α** (absorb — small completeness fix; tightens the layering invariant before any sibling package has a reason to break it).

### 🟡 Y5 — Schema-level co-presence validator (post-Y3 absorption) catches typed shapes but does NOT enforce ID-prefix invariants; runtime "valid string but wrong-prefix" path bypasses

**Where:** ADR-016 D8 `@model_validator` (lines 324-334):

```python
@model_validator(mode="after")
def _promotion_co_presence(self) -> "DecisionMeta":
    if self.promotion and (self.hypothesis_id is None or self.vk_id is None):
        raise ValueError("promotion=True requires both hypothesis_id and vk_id")
    if not self.promotion and (self.hypothesis_id is not None or self.vk_id is not None):
        raise ValueError("hypothesis_id/vk_id forbidden when promotion=False")
    return self
```

The validator enforces presence/absence co-presence but NOT prefix correctness. Since `hypothesis_id: str | None` (per Y1 deliberate-duplication absorption) and `vk_id: str | None`, the schema accepts:

- `DecisionMeta(based_on=[e], promotion=True, hypothesis_id="vk_xxx", vk_id="hyp_yyy")` — IDs swapped; **validates**.
- `DecisionMeta(based_on=[e], promotion=True, hypothesis_id="evt_zzz", vk_id="evt_zzz")` — both populated with event ids; **validates**.
- `DecisionMeta(based_on=[e], promotion=True, hypothesis_id="", vk_id="")` — empty strings; **validates** (no `min_length=1` on the optional fields, unlike `promoted_by_user_id` which has `Field(min_length=1)`).

**Why it matters:**

The cross-family lens probes: "what malformed producer values pass the validator?" — and finds that the schema enforces co-presence semantic (Y3 fix) but not the typed-prefix invariant. A junior bug in `memory/promotion.py` step 3 ("Generate vk_id; construct DecisionMeta") that swaps argument positions or passes a stale value would persist a malformed promotion event into the canonical event stream (Principle 1: event log = truth) — and the canonical stream would carry a permanent broken-ref.

The senior plan response to Y3 was to push co-presence into the schema layer ("catches malformed producers at validate_metadata step 0 inside EventStore.append, the earliest possible point in the writing path" — plan line 261). The cross-family lens reads this as a half-step: presence is enforced; semantic correctness of the values isn't. The earliest-possible-point framing implies "catches all malformed producers"; in fact it catches "absent or unexpectedly-present" but not "present-but-wrong."

**Mitigating context:** the `HypothesisId` / `VKId` NewType aliases live in `memory/schema.py`; `memory/promotion.py` constructs them via `generate_hypothesis_id()` / `generate_vk_id()` which DO enforce prefix at runtime. So the wrong-prefix bug requires a non-canonical caller (test fixture, future producer outside `memory/`); the standard call path is safe. This is a partial defense; the layered enforcement still leaks the canonical event stream as the place where the invariant is NOT checked.

**Three options:**

- **(a) Add prefix `Field(pattern=...)` constraints** on `hypothesis_id` + `vk_id`: `hypothesis_id: Annotated[str, Field(pattern=r"^hyp_[0-9a-f]{32}$")] | None`. Closes the prefix-bypass path at the schema layer. Mild duplication of `memory/schema.py` regex.
- **(b) Accept the partial defense**: ADR D8 amendment acknowledges "co-presence enforced; semantic correctness is producer-layer (`memory/promotion.py`) responsibility." Cheapest; matches the actual code shape.
- **(c) Defer to a future cycle** when a wrong-prefix bug surfaces: don't pin now.

**Lean: β or γ** — this is a hardening probe, not a load-bearing gap. (a) is the cleanest defensive shape; (b) is the most honest. (c) is the "ship it as-is" path. Architect call.

### 🟡 Y6 — VK schema field choices (D2): three fields ship with no producer-this-cycle; D9 `contradictions` is the most exposed

**Where:** ADR-016 D2 + D9. VK schema (line 90-101):

```python
class VerifiedKnowledge(BaseModel):
    ...
    topic_tags: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)
    last_validated: TimestampMs
    contradictions: list[VKId] = Field(default_factory=list)
    ...
```

The plan's `promote_hypothesis` signature (line 282-291) takes `topic_tags: list[str] | None = None` and `evidence: dict[str, Any] | None = None`; no producer for `contradictions`. ADR D9 (line 376) confirms: "no producer writes contradictions in P1.6.5."

**Why it matters:**

Principle 9 is a two-edged sword: "vocabulary inscribed before producer ships" prevents future migration; "schema field without consumer/producer" inflates the surface area to defend (every field is a forward commitment). The cross-family lens probes each:

- **`topic_tags`**: load-bearing — lookup filters by it. Producer (`promote_hypothesis` arg) exists. **Keep.**
- **`evidence`**: producer (`promote_hypothesis` arg) exists; no consumer in P1.6.5 (lookup doesn't filter by evidence). Forward-compat for "show evidence in UI" (P2). **Cost: small** (one TEXT column). **Reasonable to keep.**
- **`contradictions`**: no producer in P1.6.5; D9 explicitly says "field is present, defaults to [], queryable; a future cycle (cross-room contradiction-detector — code or LLM-assisted, undetermined) writes to it." **The most-deferred field in the slice.**
- **`last_validated`**: load-bearing — ordering uses it. But the producer (`promote_hypothesis`) doesn't explicitly set it; presumably `now_ms()` at construction. Plan P1.6.5-4 module-surface doesn't pin which clock-injection style is used (cf. ADR-014 D6 caller-frozen-time semantic). Potential purity gap.

**Specifically for D9 `contradictions`:**

The ADR (lines 366-376) considers three semantics (Hypothesis IDs / source event IDs / VK IDs), lands on VK IDs, then says no producer in P1.6.5. The cross-family lens probes: this is a schema commitment whose semantic justification ("VKs are the verified-and-cross-room-addressable layer; contradictions among them are load-bearing for cross-room reasoning") rests on a single sentence; the actual cross-room contradiction-detector is "code or LLM-assisted, undetermined." If the future detector turns out to need *finer-grained* contradiction info (e.g., "VK X contradicts VK Y on dimension Z" — list of pairs of (vk_id, dimension)), the `list[VKId]` shape is wrong and migrates poorly.

**Three options:**

- **(a) Defer the `contradictions` field**: D2 schema drops `contradictions`; D9 becomes "deferred to first contradiction-producer cycle when its semantic is concrete." Schema migration cost when it lands: one ALTER TABLE ADD COLUMN. Acceptable.
- **(b) Keep `list[VKId]`** (current plan). Defensive against future schema migration; commits to a semantic before the producer's needs are known. P1.6.5 ships an empty field.
- **(c) Make it more flexible**: `contradictions: list[dict[str, Any]] = []` or a dedicated `Contradiction` BaseModel. Over-engineering for zero producer.

Senior's lean (b) is reasonable; cross-family lens asks: is the migration cost (one ALTER TABLE) actually higher than the lock-in cost? In a project with no migration tooling, ADD COLUMN with a default is the cheapest possible migration (SQLite supports it natively, lossless). The Principle-9 forward-commitment argument tilts (b); the YAGNI/lock-in argument tilts (a).

**Lean: γ or β** — architect judgment call. The cross-family lens flags this as the most-deferred schema field in the slice; senior's defense is reasonable but not airtight.

### 🟢 G1 — D11 atomicity mechanism (append_in_transaction split) is correct on the merits; verified runtime semantic

The D11 design choice (option A: extract `append_in_transaction`; existing `append` wraps) is correct. Verified by `python3` test that nested `with conn: ... with conn: ...` in Python sqlite3 default isolation **commits the inner block independently** (the inner `with conn:` `__exit__` issues `COMMIT`), confirming the senior's framing that naive nesting from `memory/promotion.py` would break outer atomicity. The split is the right shape.

Considered alternatives (B inline-events-INSERT, C SAVEPOINT, D reach-into-conn) are correctly rejected; senior's analysis is sound.

### 🟢 G2 — DecisionMeta deliberate-duplication (`str | None` per ADR-014 D5 precedent) is correct after Y1 absorption

After R0-A-on-plan Y1 absorption, ADR-016 D8 + plan P1.6.5-3 both use `str | None` with the deliberate-duplication rationale cited. The constitutional `test_constitution_core_does_not_import_memory` guard plus the same-layer precedent from `SummarySnapshotMeta` make this the right shape. Internally consistent post-revision.

### 🟢 G3 — e2e Scenario X (P1.6.5-5) genuinely exercises cross-room semantic, not just persistence + lookup

The test's load-bearing assertion is **source ≠ sink across rooms**: hyp1 in room1 → promotion event whose `room_id = room1.id` (per Y5 pin) → VK1 → `lookup_verified_knowledge(...)` from room3 context returns `[vk1]`. The "from room3 context" is the cross-room semantic; the lookup query carries `scope=PERSONAL`, NOT `room_id=room3.id` (the API has no room_id parameter), so the test's "from room3" is really "from any consumer in any room" — which IS the cross-room contract being validated.

Probe answer: yes, Scenario X validates cross-room semantic. The cross-room-ness is in the **API shape** (lookup has no `room_id` filter) more than in the test framing. Worth a small textual note in P1.6.5-5 acceptance, but the test is genuinely load-bearing.

### 🟢 G4 — D10 "no auto-promote" API-shape enforcement is the right call; deferred test-enforcement is honest

D10 enforces "no auto-promote" purely through API shape (`promote_hypothesis` is the only path; no `create_verified_knowledge(...)` constructor; no public ROW INSERT). The senior considered a constitutional grep-test asserting no event-stream consumer calls `promote_hypothesis`, rejected as impractical (test fixture false positives; brittle across cycles). Cross-family lens: agrees. Future regression risk is low because the API shape is minimal; if a `bulk_import_vk(...)` is added in a future cycle, it would surface in code review + the lack of `user_confirm` would be visible. Honest deferral.

---

## Net assessment

**Two things to revise before architect Accept:**

1. **Y1** (callsite count + layering claim): single textual amendment to plan §5 + §4; tightens the W-004-2 (b) discipline that was the codification's whole point.
2. **Y3** (FK enforcement timing): single textual amendment to ADR D5 + plan P1.6.5-2 acceptance; prevents junior writing a broken test against soft semantics.

**Two for architect routing:**

3. **Y2** (`append_in_transaction` outside `with conn:` footgun): architect call between (a) docstring-warn, (b) runtime guard, (c) make private. The semantic gap is real; the question is which closing mechanism. Lean (b).
4. **Y4** (layering guard set completeness): small addition (3-4 mirror tests); architect call on whether to ship the full set now vs accept the 4-of-8 subset.

**Two architect judgment calls:**

5. **Y5** (schema validates co-presence but not prefix correctness): partial vs full defense at the schema layer; current shape is partial. Architect call on hardening level.
6. **Y6** (VK `contradictions` field with no producer): ship-now per Principle 9 vs defer per YAGNI; ADD COLUMN migration cost is actually low. Architect judgment call on Principle 9 weighting.

**4 areas accept-with-recorded-rationale (G1-G4):** D11 mechanism, DecisionMeta duplication, e2e cross-room semantic, D10 API-shape enforcement.

The plan + ADR-016 are substantially correct; the load-bearing design choices (D5 placement, D8 event-type reuse, D11 atomicity, D6 OR-semantics) have honest reasoning. The findings cluster in (Y1, Y3) cite/claim correctness — typical post-revision gap-finding — and (Y2, Y4, Y5, Y6) cross-family probes that pull from operational / completeness / hardening dimensions in-family review under-weighted. No 🔴 findings: nothing is design-breaking; the ADR can Accept after textual amendments.

## Verdict

`needs_architect` — 6🟡 / 4🟢 / 0🔴. Two Y items (Y1 + Y3) absorb cleanly as α; four (Y2, Y4, Y5, Y6) need architect call on closing mechanism. No blocking concerns; ADR-016 path to Accept is short.

**Caveat repeat**: this is the proxy lens. True cross-family (external session) findings may differ in shape; this output is bounded by Claude's structural biases even with the contrarian prompt. Architect dispatches the external session separately per `external-r0b-prompt.md`.
