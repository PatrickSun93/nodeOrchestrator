---
task_id: P1.6
kind: architect-routing-on-impl
date: 2026-05-28
reviews_acked:
  - plan-vs-impl.md  # senior R0-A, 0🔴/2🟡/5🟢
  - R0-B-cross-family.md  # proxy R0-B (Claude reviewer-r0b, deliberately contrarian), 1🔴/8🟡/10🟢
  - R0-A.md  # architect-partner R0-A, 0🔴/2🟡/11🟢
decisions:
  M-R1: α  # add "unknown" to ToolCallRef.autonomy_tier Literal + include anomaly TCs
  M-Y1: α-A  # narrow except + surface failure in TurnResult
  M-Y2: α-strict  # drop swallows; let ValidationError propagate
  M-Y3: β  # sharpen _ = produce_decision_log comment
  M-Y4: α  # ≥4 §3-cleanup tests pinning M-Y2 strict semantic
  M-Y5: δ  # defer to async-reshape ADR-014 D6 amendment hook
  M-Y6: β  # docstring on _AGENT_PARTICIPATION_TYPES re ADR-014 D2.4
  M-Y7: δ  # defer (intentional per ADR-011 D2)
  Y1: γ-override  # skip external R0-B this cycle (architect override of architect-partner lean)
  Y2: α  # add ADR-014 D2.6 for decision_count + opportunistic D2.1/D2.2 clarification
---

# P1.6 architect routing — impl stage (α / α-A / α-strict / β / α / δ / β / δ / γ-override / α)

**Architect decisions (this session):** 7 α-class routings (M-R1, M-Y1, M-Y2, M-Y4, Y2 + sub-choices) + 2 β + 2 δ + 1 γ-override. Routing slate extends the project's α-discipline streak: **8 cumulative impl-stage α + 7 plan-stage α = 15 cumulative α since the discipline gradient began climbing**. Pattern recurrence shape: most-substantive items resolve α; lower-severity items β/δ per opportunity-cost discipline.

**Routing scope context**:
- M-R1 + M-Y1 + M-Y2 + M-Y4 + Y2 = the substantive impl + ADR amendment scope.
- M-Y3 + M-Y6 = documentation/comment hardening (low LoC; fold into the same cycle-2 commit).
- M-Y5 + M-Y7 = δ-deferred per intentional design + async-reshape future-amendment hook.
- Y1 = architect override of architect-partner lean (skip external R0-B); rationale in §"Y1 architect override" below.

This file is the **signal artifact for the senior revision + junior cycle-2 sessions**. Senior picks P1.6 next, amends ADR-014 + plan §4 per §"Senior revision actions" below; junior cycle-2 dispatches after senior commits revisions.

## Per-finding routing

### 🔴 M-R1 → α — `ToolCallRef.autonomy_tier` Literal expansion + ADR-014 D2.3 anomaly-handling code fix

**Source**: proxy R0-B R1 + architect-partner R0-A G1 (independent verification).

**Action**: add `"unknown"` to `ToolCallRef.autonomy_tier` Literal (α1 per architect-partner R0-A lean). Update `snapshot.py:158-188` to assign `autonomy_tier="unknown"` for TC events without a preceding correlated AD, per ADR-014 D2.3's conservative-include semantic (line 137: "snapshot still includes TC in pending-confirm conservatively, since 'no decision = treat as awaiting confirmation'").

**Code shape**:
```python
class ToolCallRef(BaseModel):
    autonomy_tier: Literal["countdown_confirm", "hard_confirm", "unknown"]
```
And at snapshot.py:186, replace the `# No preceding AD (anomaly): skip` branch with:
```python
else:
    tool_calls_pending.append(
        ToolCallRef(
            event_id=e.id,
            tool_name=tc_meta.tool_name,
            autonomy_tier="unknown",
        )
    )
```

**Test additions**: ≥1 test in `tests/derived/test_snapshot.py` exercising "TC without preceding AD → included with tier='unknown'."

**ADR-014 amendment**: D2.3 line 137 footnote-addendum naming the third Literal value + the conservative-include semantic. ~3 LoC.

**Why α (not β)**: β would amend ADR-014 D2.3 to match impl (skip anomaly TCs), losing the conservative-default property the ADR was designed around. α preserves ADR semantic + small impl change.

**Why not γ**: documented edge case with specified behavior; P1.5+ async-reshape weakens ordering guarantee + would surface this anomaly in practice.

### 🟡 M-Y1 → α-A — Narrow `except Exception` in dispatch.py snapshot block + surface failure via TurnResult

**Source**: R0-A senior Y1 + R0-B proxy Y4 (stuck-room risk).

**Action** (α-A per architect-partner R0-A lean):
1. Narrow `dispatch.py:155-173` `except Exception` to `except ValidationError` only (catches the explicit `StateTransitionMeta.model_validate` failure path).
2. Surface snapshot dispatch failure in `TurnResult` — add `snapshot_failed: bool` field (defaults False) OR include failed agent id in `failed_agents` list per existing dispatch convention. Caller (room runtime) can decide retry/escalate.
3. ADR-014 error-semantic addendum (1-2 sentences): "Snapshot dispatch failure path: ValidationError on metadata is logged + surfaced via TurnResult; non-ValidationError exceptions (e.g., event_store.append failure) propagate unwrapped per ADR-011 D7-b."

**Why α-A (not α-B / drop wrapper entirely)**: α-B's pure propagation breaks the turn on any failure type including transient ValidationError on degraded state; α-A keeps recoverability for typed-metadata corruption while restoring ADR-011 D7-b semantics for event_store persistence.

**Test additions**: ≥2 tests in `tests/agents/test_dispatch.py` covering (a) snapshot dispatch ValidationError → TurnResult.snapshot_failed True (b) event_store.append RuntimeError → propagates (does not get swallowed by the snapshot block).

**Why not γ**: room state machine has exactly ONE producer for `snapshot_pending → closed`; silent failure = silent liveness violation. Not acceptable per ADR-012 room state-machine semantics.

### 🟡 M-Y2 → α-strict — Drop all 8 silent swallows in `produce_snapshot` / `produce_decision_log`; let `ValidationError` propagate

**Source**: R0-A senior Y2 + R0-B proxy Y2 + R0-B proxy Y6 (last_state_transition None-on-failure).

**Action** (α-strict per architect-partner R0-A lean):
1. Remove all **9** `try/except Exception: pass` blocks (senior R0-A Y2 said "8 sites" — miscount; actually 9). **7 in `derived/snapshot.py`**: D2.1 DECISION at 119-123, D2.1 REJECTION at 125-129, D2.1 RETRACTION at 131-135, D2.2 RETRACTION at 149-153, D2.3 AUTONOMY_DECISION at 167-171, D2.3 TOOL_CALL at 173-187, D2.5 STATE_TRANSITION at 196-204. **+ 2 in `derived/decision_log.py`**: REJECTION at 53-58, RETRACTION at 59-64.
2. Let `pydantic.ValidationError` propagate from each `model_validate` call. Justification: event_store-level `validate_metadata` runs at append time (per `core/event.py:_BaseMeta` discipline); a `ValidationError` in `produce_snapshot` therefore means either a non-validated write path (debug SQLite, migration script) OR a programming error (schema rename without metadata migration). Both must surface.

**ADR-014 error-semantic addendum** (paired with M-Y1's): "Derived module (`derived/snapshot.py`, `derived/decision_log.py`) propagates Pydantic ValidationError on malformed typed metadata; consumers responsible for catching at boundary if degraded snapshot is preferable to raise."

**ADR-015 cross-reference**: D3 verbatim-content-excerpt discipline implies REJECTION/RETRACTION metadata correctness is load-bearing; propagation is consistent.

**Test additions (coupled to M-Y4 below)**: at minimum 4 tests pinning the new semantic.

**Why α-strict (not α-lax narrow+log)**: α-lax pins the swallow behavior in tests but leaves the lie-about-room-state risk standing (e.g., hypothesis stays "open" when DECISION metadata is malformed). α-strict surfaces the lie; consumers can catch if they need degraded mode (none in P1.6 scope).

**Why not γ (status quo)**: R0-A senior's concrete example holds — "if a DECISION has malformed `based_on`, hypotheses stay in `open_hypotheses` — the Snapshot lies about room state." Lying snapshots are not acceptable when an unambiguous-error path is available.

### 🟢→🟡 M-Y3 → β — Sharpen `_ = produce_decision_log(...)` comment in `snapshot_dispatch.py:57`

**Source**: R0-A senior G1 (low-stakes) ↔ R0-B proxy Y1 (escalated; looks like leftover scaffolding).

**Action** (β per architect-partner R0-A lean):
Rewrite the comment to explicitly state both (a) ADR-015 D5 derivation-not-persistence intent AND (b) that the call exercises the derivation path at runtime to catch regressions where it'd raise. Example:
```python
# Decision log is derived (ADR-015 D5: not persisted; consumers always recompute).
# Call at snapshot dispatch exercises the derivation path so any ValidationError
# (per M-Y2 strict-propagation semantic) surfaces at the same trigger as
# produce_snapshot, not at first downstream consumer.
_ = produce_decision_log(snapshot_events, room)
```

**Why β (not α)**: not load-bearing for correctness; no ADR amendment; small comment-only change. M-Y3 is the only severity-disagreement finding between senior and proxy; β resolves both leans (senior says "fine as-is, low-stakes" + proxy says "cargo-cult-looking, document or remove" — β documents).

**Why not γ**: the proxy's "future readers will ask why" concern is real even if low-stakes; precise comment is cheap insurance.

### 🟡 M-Y4 → α — ≥4 §3-cleanup tests pinning M-Y2's strict-propagation semantic

**Source**: R0-B proxy Y3 (no test coverage for malformed-metadata paths).

**Action** (α, coupled to M-Y2 routing):
Add ≥4 tests in `tests/derived/test_snapshot.py` + `tests/derived/test_decision_log.py` covering both modules' swallow removal (9 sites total per M-Y2):
1. DECISION with malformed `based_on` field (e.g., None instead of list) → `produce_snapshot` raises `ValidationError`.
2. RETRACTION with malformed `retracts` field → raises.
3. STATE_TRANSITION with malformed `new_state` field → raises.
4. (decision_log) REJECTION OR RETRACTION with malformed metadata → `produce_decision_log` raises.

**Test pattern**: construct an Event with `.metadata = {"based_on": "not_a_list"}` (or similar invalid shape), call `produce_snapshot(events, room, snapshot_at=...)`, assert `pytest.raises(ValidationError)`.

**Why α (not β as test-coverage)**: M-Y4 is the test-coverage dual of M-Y2; the semantic only holds if pinned by tests. Without these, future refactors could accidentally regress to swallow-and-lie. α earns its weight by making the M-Y2 semantic load-bearing.

### 🟡 M-Y5 → δ — Defer `event_count` semantic precision to async-reshape

**Source**: R0-B proxy Y5.

**Action** (δ): no code change in P1.6 cycle-2. ADR-014 D6 already has an async-reshape future-amendment hook; capture `event_count` semantic precision as a named revisit item there.

**Optional sub-action** (fold into Y2's ADR-014 amendment commit): 1-line comment at `snapshot.py:222` (`event_count=len(events)`) noting "len(events) reflects fetch-time count per ADR-011 D1 sequential dispatch; revisit at async-reshape per ADR-014 D6 amendment hook." Cost: 1 LoC.

**Why δ (not β fold-in)**: pure P1.6 non-issue per proxy's own lean (sequential dispatch makes the gap 0ms). Async-reshape will be the natural venue. Fold-in via 1-line comment is acceptable opportunistic improvement but not required.

### 🟡 M-Y6 → β — Add docstring on `_AGENT_PARTICIPATION_TYPES` referencing ADR-014 D2.4

**Source**: R0-B proxy Y7 (participants excludes silent-voter agents).

**Action** (β per architect-partner R0-A lean):
2-3 lines above `_AGENT_PARTICIPATION_TYPES` at `snapshot.py:69`:
```python
# Per ADR-014 D2.4: agent participation tracked via event types that
# carry per-event author identity unambiguously (UTTERANCE + ops gate +
# Logger snapshot). Decision-class events (DECISION/HYPOTHESIS/REJECTION/
# RETRACTION) excluded to avoid double-count — agents that decide also
# typically utter; counting via UTTERANCE alone preserves single-event-per-
# agent participation semantic. Future "silent voter" agents may motivate
# revisit (P1.7+ scope).
_AGENT_PARTICIPATION_TYPES: frozenset[EventType] = frozenset(...)
```

**Why β (not α)**: per architect-partner R0-A G3 D2.4 spot-check + proxy own lean: impl matches ADR-014 D2.4. Pure naming/clarity finding; no code or ADR change.

**Why not γ**: "participants" naming is genuinely confusing for future readers; one-time inline annotation beats repeated future questions.

### 🟡 M-Y7 → δ — Defer pre-turn-snapshot semantic documentation

**Source**: R0-B proxy Y8 (snapshot uses pre-turn frozen events; same-turn utterances absent).

**Action** (δ): no code change. Intentional per ADR-011 D2 + ADR-014 D6 caller-frozen-time semantic. ADR coverage exists.

**Optional sub-action** (fold into Y2's ADR-014 amendment commit if desired): 1-line comment at `dispatch.py:158` call site noting "uses pre-turn snapshot per ADR-011 D2; same-turn utterances are NOT reflected in this snapshot." Cost: 1 LoC.

**Why δ**: proxy's own lean; documentation concern; ADR-014 D6 already covers.

### 🟡 Y1 (architect-partner) → γ-override — Skip external R0-B (DeepSeek/GPT/Gemini) this cycle

**Source**: architect-partner R0-A Y1 (dispatch ordering concern).

**Architect override rationale**: architect-partner lean was "dispatch external first; route on union." Architect (this session) decides to **skip external R0-B for P1.6 cycle-2** and proceed with routing on the existing R0-A senior + R0-B proxy + R0-A architect-partner triple. Rationale:
- Substrate maturity (7-cycle impl-drift-free streak; α-discipline gradient holds; ADR-014 + ADR-015 substantively sound per all three same-family reviews' G-finding density).
- Cost-benefit at this cycle: external R0-B dispatch + return + merge + re-route cycle adds ≥1 day of latency; the routing slate is already concrete and the M-R1 + M-Y1 + M-Y2 + Y2 amendments are independently well-motivated.
- Project momentum: P1.6 unblocks P1.6.5+ cross-room memory work; cycle-2 fix lands → close → next cycle starts.

**Captured implications**:
- This is the **1st instance of architect overriding architect-partner cross-family-dispatch lean at impl stage**. Worth retro capture as a precedent — under what cost-benefit calculus is external R0-B skip defensible?
- Risk acknowledged: if cycle-2 ships and a runtime-integration bug the proxy lens under-weighted surfaces in P1.6.5 substantive use, **the cost of the skip is observable then**. Project pattern-recurrence note will capture (cycle-2 close as "external R0-B skipped; no late-surfacing finding yet" or "external R0-B skipped; finding X surfaced at P1.6.5 — pattern signal").

**Existing R0-B-cross-family.md filename**: stays. Per `dual-lens-r0b.md:147` convention, external R0-B (if dispatched in a future cycle, e.g., P1.6.5) would append as a new section in the same file with file-level verdict bumping per RC-10.

### 🟡 Y2 (architect-partner) → α — Add ADR-014 D2.6 for `decision_count` predicate + opportunistic D2.1/D2.2 clarification

**Source**: architect-partner R0-A Y2 (ADR-014 D2 inscription-completeness gap).

**Action** (α per architect-partner R0-A lean):

**1. Add ADR-014 D2.6** inscribing the `decision_count` derivation predicate. Suggested text (senior verifies + pins):
```markdown
### 2.6 `decision_count` predicate

`decision_count = |{e ∈ events : e.type ∈ {DECISION, DECISION_PIVOT, REJECTION, RETRACTION}}|`.

I.e., the count of all decision-class events in the room — not filtered by closure (per D2.2 retraction filter), not limited to literal DECISION events. Decision-class includes pivots (re-orientation = decision-making act) + rejections + retractions (each is itself a decision).

**Why this set** (not literal DECISION only): consumers asking "how decision-active is this room?" want the full decision-class signal, including reversals and re-orientations. Closure-aware count (`len(closed_decisions)`) is available separately via the `closed_decisions` field; `decision_count` complements as "decision-class events total."

**Verification path**: `core/event.py` TYPED_METADATA registers DecisionMeta + RejectionMeta + RetractionMeta + (DECISION_PIVOT has no typed metadata per `core/event.py:272-282`); all 4 event types are present at schema layer; count semantic is over event types not metadata correctness (ValidationError propagation per M-Y2 strict semantic does not affect count).
```

**2. Opportunistic D2.1 + D2.2 clarification** (architect-partner R0-A G3 sub-observation):
ADR-014 D2.1 + D2.2 say "no subsequent event satisfies close-condition"; impl iterates all events (no order constraint). For valid event streams these are equivalent; for anomaly cite-before-cited streams they diverge. Add 1-sentence clarification to each:
- D2.1: "Note: impl scans all events for cite (not strictly 'subsequent') — equivalent for valid streams; for anomaly cite-before-cited streams, impl's 'any-event-cites' semantic is preferred over 'subsequent-only' for conservative closure."
- D2.2: same.

**3. Cross-reference in `snapshot.py:215`**: 1-line comment above `decision_count = sum(...)` line citing "ADR-014 D2.6."

**ADR-014 Total amendment LoC**: ~15-25 (D2.6 subsection + 2 clarification sentences).

**Why α (not β / γ)**: per architect-partner R0-A Y2 reasoning — same anti-pattern shape as plan-stage Y1; β leaves inscription incomplete (asymmetry with D2.1-D2.5 already-amended state); γ accepts unpinned impl choice (breaks Principle 9 vocabulary discipline).

---

## Senior revision actions (derived)

P1.6 cycle-2 starts with **senior revision** of ADR-014 + plan §4 before junior cycle-2 impl. Amendments commit on `claude/P1.6-impl` (P1.6 plan branch was already merged + closed at cycle-1 plan-stage; impl branch is the only live one). State stays `awaiting_architect_decision` while senior amends; only the subsequent `workflow advance` transitions to `awaiting_junior_impl` (cycle 2). Senior picks P1.6 next, reads this routing + ADR-014 + plan, applies:

1. **ADR-014 amendments** (Y2 + M-Y1 + M-Y2 + M-R1 + opportunistic D2.1/D2.2): single commit on `claude/P1.6-impl`. ~30-40 LoC total. Components:
   - D2.6 subsection for `decision_count`.
   - D2.1 + D2.2 "any vs subsequent" clarification sentences.
   - D2.3 footnote-addendum: `"unknown"` Literal value for anomaly TCs.
   - New D7 (or D? — senior decides numbering) **error-semantic** subsection: derived module propagates ValidationError; snapshot dispatch caller (`dispatch.py`) narrows + surfaces via TurnResult; ADR-011 D7-b semantics preserved for event_store persistence.

2. **Plan §4 amendment** (G8 forcing-function: error-semantic pinning rule for new module surfaces): add to plan-template forcing-functions list — "for new module surfaces with derivation/dispatch failure modes, plan §4 must pin error semantic explicitly (raise vs swallow vs log+skip)." This is a 1-instance W-005 codification candidate per architect-partner R0-A G8; for P1.6 plan, retroactive pin via a §4 addendum referencing the M-Y1 + M-Y2 routing decisions.

3. **Senior plan-vs-impl verdict-bump preparation**: senior plans for the post-impl R0-A bump per RC-10 (`needs_architect → clean` after cycle-2 junior impl + R0-A senior re-review).

## Junior cycle-2 actions (derived)

After senior revision lands (signal: ADR-014 + plan revisions committed on `claude/P1.6-impl`), junior picks P1.6 next, reads:
- This routing.
- ADR-014 post-amendment.
- Plan §4 post-amendment.
- Existing impl (cca42e3 → 6c7cf7d).

Junior cycle-2 commit (single commit; ~130-160 LoC per breakdown below) covers:

| Change | LoC | Source files |
|---|---|---|
| M-R1: `ToolCallRef.autonomy_tier` `"unknown"` + anomaly-include in `produce_snapshot` | ~10 | `derived/snapshot.py` (lines 39-43 schema + 158-188 logic) |
| M-Y1: narrow except + TurnResult.snapshot_failed surfacing | ~15 | `agents/dispatch.py:155-173` + `core/event.py` TurnResult dataclass + `agents/snapshot_dispatch.py` (return shape adjustment) |
| M-Y2: drop 8 swallow blocks in derived/ | ~15-25 | `derived/snapshot.py` + `derived/decision_log.py` |
| M-Y3: sharpen produce_decision_log comment | ~3 | `agents/snapshot_dispatch.py:57` |
| M-Y4: ≥4 §3-cleanup malformed-metadata tests | ~50-60 | new in `tests/derived/test_snapshot.py` + `tests/derived/test_decision_log.py` |
| M-Y5 opt: `event_count` async-reshape comment (1 LoC) | ~1 | `derived/snapshot.py:222` |
| M-Y6: `_AGENT_PARTICIPATION_TYPES` docstring | ~3 | `derived/snapshot.py:69` |
| M-Y7 opt: pre-turn-snapshot dispatch-site comment (1 LoC) | ~1 | `agents/dispatch.py:158` |
| Y2: 1-line cross-ref above `decision_count = sum(...)` | ~1 | `derived/snapshot.py:215` |
| M-R1 test: TC-without-AD anomaly inclusion | ~10 | `tests/derived/test_snapshot.py` |
| M-Y1 tests: snapshot_failed surfacing + propagation | ~25 | `tests/agents/test_dispatch.py` |

Junior R0-A on cycle-2 senior review verifies: ADR-014 amendments structurally sound + impl matches amendment + tests cover routing-pinned semantics.

## Status flips that follow

Once senior revision pass lands on `claude/P1.6-impl`:
- **State**: `awaiting_architect_decision → awaiting_junior_impl` (cycle 2) — via `uv run workflow advance --task-id P1.6`. **Note**: RC-19 fix (`_has_junior_impl_commits`) does NOT fire on this transition (RC-19 checks junior-impl-commits-ahead-of-main; relevant at the `awaiting_junior_impl → awaiting_senior_plan_vs_impl` advance, not the dispatch). The **end-of-junior-cycle-2-impl push** will be the **3rd substantive RC-19 use** (after W-004 dogfood + P1.6 cycle-1).
- Junior cycle-2 commit lands → `workflow advance` runs → state `awaiting_junior_impl → awaiting_senior_plan_vs_impl` (cycle 2; **3rd RC-19 use fires here**).
- Senior cycle-2 plan-vs-impl review → state `awaiting_senior_plan_vs_impl → awaiting_architect_decision` (cycle-2 routing).
- Architect routes cycle-2 review → if clean, state `awaiting_architect_decision → closed` (multi-ADR W-002.5 aggregation 2nd project use closes).
- **RC-10 verdict bumps** in same close pass:
  - `plan-vs-impl.md` (senior): `needs_architect → clean` (Y1 + Y2 absorbed via M-Y1 + M-Y2 routing).
  - `R0-B-cross-family.md` (proxy): `needs_architect → clean` (R1 + Y1-Y7 absorbed; verdict_history entry added).
  - `R0-A.md` (architect-partner): `needs_architect → clean` (Y2 absorbed via ADR-014 D2.6 amendment; Y1 captured as architect-override rather than absorbed).

## Pattern-recurrence note for future plans

**P1.6 cycle α count**: 3 plan-stage α (Y1+Y2+Y3 → D2.1-D2.5 inscription) + 5 impl-stage α (M-R1 + M-Y1 + M-Y2 + M-Y4 + Y2) = **8 cumulative α in the P1.6 cycle**. **Project cumulative α since discipline gradient began climbing** (W-003 onward): 7 plan-stage (W-003 αα + P1.5.5 αα + P1.6 ααα) + 5 impl-stage (P1.6 this routing) = **12 cumulative project α** (13 including P1.5 R0-A Y1 as the gradient's origin). Discipline gradient holds; impl-stage routing now contributes meaningfully alongside plan-stage routings. Sub-pattern: **ADR D-section vocabulary types declared without derivation algorithms** holds across both stages (plan-stage Y1 → D2.1-D2.5; impl-stage Y2 → D2.6). 2 instances of this sub-pattern in 1 cycle.

**W-005 codification queue updates** (per architect-partner R0-A G8 + G9 + G11):

1. **ADR D-section precision rule** — now **2 instances in 1 cycle** (D2.1-D2.5 + D2.6). Per W-003 architect-routing.md 3-instance threshold, one more instance accumulates → codification trigger. Watch for cycle-2 senior revision and P1.6.5 ADR work for the 3rd instance.
2. **Plan-stage error-semantic pinning rule for new module surfaces** (M-Y1 + M-Y2 origin) — 1st instance. Joins as 1-instance item.
3. **Same-family-consensus blind spot at architect-partner synthesis layer** (architect-partner R0-A G11 self-incrimination) — 1st instance.
4. **Dual-lens-r0b.md impl-stage dispatch criteria** (architect-partner R0-A G9 trusts-the-types validation; this routing's Y1 γ-override establishes the cost-benefit precedent) — codification candidate; capture "when same-family R0-A misses spec-impl divergence that proxy R0-B catches, architect-partner LEAN is dispatch external; architect CAN override based on cycle-velocity vs runtime-integration risk tradeoff."
5. **Architect override of architect-partner cross-family-dispatch lean** — 1st instance (this cycle Y1 γ-override). Joins as 1-instance item.

All wait for 2nd-instance accumulation per 3-instance codification threshold. W-005 brief dispatches when ≥1 accumulates 2nd OR architect-partner judges enough pattern surface area exists.

## Out of scope for this routing

- Re-litigating any 🟢 finding from R0-A senior, R0-B proxy, or R0-A architect-partner (all 26 confirm impl + ADR structural soundness — 5+10+11 = 26 cumulative greens this cycle).
- Re-opening plan-stage α/α/α routings (D2.1-D2.5 already inscribed; clock-injection signature stable; D4 lex-tiebreak rationale stable).
- External R0-B dispatch — explicitly skipped per Y1 γ-override; pattern-recurrence risk captured.
- Cross-room memory architectural decisions (P1.6.5+ scope per brief Out-of-scope #1 + W-004-2(c) literal-reading discipline).
- LLMPurpose.SNAPSHOT_SEMANTIC introduction (brief Out-of-scope #3).
- Async-reshape ADR-011 D1 amendment (P1.5+ scope; M-Y5 + M-Y7 deferred there).

## Cross-references

- `docs/process/reviews/P1.6/plan-vs-impl.md` — senior R0-A; M-Y1 + M-Y2 source.
- `docs/process/reviews/P1.6/R0-B-cross-family.md` — proxy R0-B; M-R1 source.
- `docs/process/reviews/P1.6/R0-A.md` — architect-partner R0-A; Y1 + Y2 source.
- `docs/process/reviews/P1.6/architect-routing.md` — plan-stage routing precedent (α/α/α).
- `docs/process/reviews/P1.6/external-r0b-prompt.md` — dispatch artifact (deferred per Y1 γ-override; remains ready for future use).
- `docs/decisions/ADR-014-snapshot-contract.md` — M-R1 + M-Y1 + M-Y2 + Y2 amendment subject (D2.3 footnote, error-semantic addendum, D2.6 new subsection, D2.1/D2.2 clarification).
- `docs/decisions/ADR-015-decision-log-shape.md` — M-Y2 affects `produce_decision_log` swallow-block removal (2 of the 9 sites; REJECTION + RETRACTION metadata parsing).
- `docs/process/dual-lens-r0b.md` — Y1 γ-override rationale source; future-amendment candidate.
- `docs/process/senior-planner.md` § Pre-investigation discipline — G8 codification queue entry.
- `docs/process/reviews/README.md` § Post-resolution verdict-bump protocol — RC-10 mechanics for the post-impl close.
- `docs/retrospectives/W-003+P1.5.5.md` § 13 — 1-instance codification queue precedent for §"Pattern-recurrence note" entries.
- `docs/process/reviews/W-004/R0-A.md` — architect-partner R0-A format precedent.
