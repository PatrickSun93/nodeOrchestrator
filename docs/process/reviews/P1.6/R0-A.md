---
task_id: P1.6
round: R0-A
verdict: needs_architect
findings_count:
  red: 0
  yellow: 2
  green: 11
---

# P1.6 R0-A review (architect-partner lens)

| Field | Value |
|---|---|
| Round | R0-A (post-impl, architect-partner) per RC-9 default + P1.6 substantive new-architectural-pattern cycle precedent |
| Reviewer | architect-partner (Claude Opus 4.7, 1M context) in primary session |
| Date | 2026-05-28 |
| Artifacts reviewed | 5 impl commits on `claude/P1.6-impl` (`cca42e3` → `6c7cf7d`): P1.6-1 (`derived/` package) → P1.6-2 (SummarySnapshotMeta) → P1.6-3 (Logger wiring + snapshot_dispatch sibling) → P1.6-4 (e2e) → P1.6-5 (landing). Independent reads of: `src/orchestrator/derived/snapshot.py` (full), `src/orchestrator/derived/decision_log.py` (full), `src/orchestrator/agents/snapshot_dispatch.py`, `src/orchestrator/agents/dispatch.py:155-173` snapshot-dispatch block, `src/orchestrator/core/event.py` SummarySnapshotMeta + TYPED_METADATA registration, `tests/integration/test_p1_6_e2e.py`. Plus existing reviews: `plan-vs-impl.md` (senior planner, 0🔴/2🟡/5🟢) + `R0-B-cross-family.md` (Claude reviewer-r0b proxy lens, 1🔴/8🟡/10🟢). |
| Brief lean | R0-A dispatch per project default + RC-9 + 7-cycle precedent. Plan-stage R0-A-on-plan dispatched + routed α/α/α; impl-stage R0-A is the standard follow. |
| Distinct from plan-vs-impl | Senior `plan-vs-impl.md` covered: 5-task acceptance verification + S1/S2/S3 senior self-discoveries operational validation + Y1/Y2 error-handling findings + 5 greens + 7-cycle audit observation. Proxy `R0-B-cross-family.md` covered: 1 spec-impl divergence (R1) + 8 operational/runtime concerns (Y1-Y8) + 10 structural confirmations. **This R0-A focuses on**: independent code-level spot-checks of ADR-014 D2.1-D2.5 predicates (beyond senior's acceptance check and proxy's spec scrutiny — produces 1 new Y); project-perspective milestones (7-cycle streak, SD-DOGFOOD 2nd instance, W-002.5 multi-ADR 2nd use, ADR-012/014/015 first-runtimes); cross-cycle pattern-recurrence (M-Y1+M-Y2 as P1.5.5 RC-19 anti-pattern; senior R1 miss as dual-lens-r0b.md trusts-the-types empirical validation); brief-vs-impl trajectory coherence (W-004-2(c) first non-meta-circular application); role-separation self-incrimination (my own merge over-claim earlier this session); process-discipline observation (external R0-B dispatch ordering for impl stage). |

---

## Findings

### 🟢 G1 — Independent verification: R1 ADR-014 D2.3 ↔ `snapshot.py:186` divergence confirmed

Proxy R0-B (R1) flagged that `ToolCallRef.autonomy_tier: Literal["countdown_confirm", "hard_confirm"]` schema constraint mechanically blocks ADR-014 D2.3's specified conservative-include behavior for the TC-without-preceding-AD anomaly case.

**Independent read**:
- ADR-014 D2.3 line 137 verbatim: "if a TC exists without a preceding AD, that's a data anomaly (snapshot still includes TC in pending-confirm conservatively, since 'no decision = treat as awaiting confirmation')."
- `snapshot.py:186` verbatim: "# No preceding AD (anomaly): skip; can't determine tier for ToolCallRef."

Direct contradiction confirmed. Root cause is the schema's tier Literal — the impl has no defensible third-option value to assign for the anomaly case. **Proxy R0-B R1 stands as a real impl-stage 🔴 awaiting architect routing** (architect-partner merged-finding ID: **M-R1**; my impl-stage merge document tracks this as routing-pending).

Worth noting for retro: senior plan-vs-impl review did not catch this. Senior's verification path (per plan-stage Y1 absorption: "senior verifies predicate substance against runtime schema") covered D2.3 predicate at the algorithm level (most-recent preceding AD correlation walk) but did not stress-test the *edge case clause* the ADR explicitly adds. The proxy lens, primed to look for spec-impl divergence specifically, caught it. This is the **first impl-stage empirical instance of the dual-lens-r0b.md "trusts-the-types" Claude-family bias prediction**; see G9 for pattern-recurrence framing.

### 🟢 G2 — Independent verification: ADR-014 D5 layering invariant preserved

ADR-014 D5 ("deliberate duplication of Snapshot fields in SummarySnapshotMeta in core/event.py; core MUST NOT import from derived/") is the invariant most at risk in P1.6-2 — if a future refactor accidentally imports `derived/snapshot.py` from `core/event.py` to deduplicate, the layering breaks.

**Independent grep**:
```
grep -n "from orchestrator.derived\|import.*derived" src/orchestrator/core/event.py
→ (no matches)
```

`core/event.py` carries `SummarySnapshotMeta` as a literal `_BaseMeta` subclass with field shape mirroring `Snapshot` — no derived/ import, no dynamic schema generation from `Snapshot`. The round-trip invariant test (`test_event.py::TestSummarySnapshotMeta::test_snapshot_roundtrip`) covers the runtime equality of field set; the constitutional test (`test_constitution_no_llm_calls_in_derived_module`) covers no-LLM-in-derived but does NOT cover no-reverse-import.

**Sub-observation for future-amendment hook (not a finding)**: the deliberate-duplication pattern's correctness depends on the no-reverse-import invariant, which is currently enforced only by convention + this single round-trip test. A constitutional test variant `test_constitution_no_derived_import_in_core_event` would be a load-bearing complement. Not Y-worthy for P1.6 (current convention holds; no observed drift), but worth capture for P1.6 retro / future ADR-014 hardening.

### 🟢 G3 — Independent spot-check of D2.1, D2.2, D2.4, D2.5 predicates against impl

Walked each ADR-014 D2.x predicate against `derived/snapshot.py` independently of senior + proxy reviews:

- **D2.1 `open_hypotheses`** (snapshot.py:108-140): impl iterates all sorted events, building `closed_hypothesis_ids` from DECISION.based_on / REJECTION.rejects / RETRACTION.retracts metadata cite chains. Matches ADR's metadata-cite semantic (not parent_id walk). **Subtle**: ADR specifies "no SUBSEQUENT event satisfies" the close condition; impl tests "no event in the full sorted stream cites H." For valid event streams (citation always happens after the cited event), these are equivalent. For anomaly streams (a DECISION authored before the HYPOTHESIS it cites — possible if metadata references are stored without causal-order validation), the impl would mark H as closed while ADR semantic would mark it open. Low-impact edge case (cite-before-cited is a data anomaly itself); flagged for ADR-014 audit-trail clarity, not as a Y finding.
- **D2.2 `closed_decisions`** (snapshot.py:142-156): impl uses subsequent-retraction filter; DECISION_PIVOT correctly excluded from `decision_event_ids`. Same subtle "any" vs "subsequent" semantic as D2.1; same edge-case impact (low).
- **D2.3 `tool_calls_pending_confirm`**: R1 anomaly handling divergence (see G1). Non-anomaly correlation walk via `latest_ad_tier: dict[(author, tool_name)] → tier` correctly implements ADR's "most-recent preceding AD" semantic (dict overwrite-on-newest, lookup-at-TC-time produces most-recent preceding).
- **D2.4 `participants`** (snapshot.py:69-77 + 206-212): event-type set `{UTTERANCE, SUMMARY_SNAPSHOT, TOOL_CALL, AUTONOMY_DECISION, AUTONOMY_REFUSAL}` matches ADR D2.4 line 141. Author filter via `e.author.startswith("agent:")` correctly excludes user + system authors. Prefix-strip + ascending lex sort correct. ✓ clean.
- **D2.5 `last_state_transition`** (snapshot.py:190-204): `max(st_events, key=lambda e: (e.timestamp, e.id))` correctly implements ADR D2.5 max-tuple. The `try/except Exception: pass` swallow on `StateTransitionMeta.model_validate` is the known M-Y2 / proxy-Y6 silent-degradation concern (already on routing table). Predicate itself clean.

**Spot-check verdict**: D2.1/D2.2/D2.4/D2.5 all match ADR. D2.3 confirms G1. Subtle "any vs subsequent" semantic for D2.1+D2.2 is a low-impact ADR-vs-impl precision gap (anomaly-only manifestation); worth a 1-sentence ADR-014 amendment for D2.1+D2.2 ("scan all events for cite; for anomaly cite-before-cited streams, conservative-close semantics may diverge from subsequent-only readings — not load-bearing for ADR-011 D1 sequential dispatch") but not a Y finding for P1.6.

**However, the spot-check surfaced one genuine Y finding the senior + proxy + plan-stage all missed — see Y2 below.**

### 🟢 G4 — Major milestone: 7th consecutive impl-drift-free cycle

Independent count via `.workflow/{task-id}.yaml` state + `override_history`:

- W-002.5: closed cycle 1, zero overrides
- P1.4: closed cycle 1, zero overrides
- P1.5: closed cycle 1, zero overrides (first R1 cycle)
- W-003: closed cycle 1, zero overrides
- P1.5.5: closed cycle 1, **1 override** (RC-19 — defensive Z-suffix workflow-CLI restore; root cause traced to W-004-1)
- W-004: closed cycle 1, zero overrides (RC-19 fix lands; dogfood successful)
- P1.6: in-flight (current state `awaiting_architect_decision`); if architect routing completes + cycle-2 follow-up (if any) closes cleanly, **7th cycle in the streak**

Cumulative override count freeze at 3 (P1.3 `cfbf087` + W-002 `236dac1` + P1.5.5 `c4e247d`) holds; P1.6 added zero this cycle. **Substrate at mature steady state through 7 substantive cycles** (or 6 closed + 1 in-flight).

Important framing distinction (echoes senior plan-vs-impl §5 audit observation): the 7-cycle streak is on the **coverage axis** — every plan-pinned acceptance bullet was implemented; senior pins S1/S2/S3 validated; brief-predicted self-discoveries (SD-METADATA, SD-DOGFOOD) operationally validated. The M-R1 + M-Y1 + M-Y2 findings are NOT coverage drift — they are first-substantive-cycle exposure of an **error-handling policy gap** the plan didn't think to pin because the brief didn't surface it. See G8 for the pattern-recurrence framing.

### 🟢 G5 — Major milestone: SD-DOGFOOD 2nd instance (W-004-1 RC-19 fix's first non-meta-circular substantive use)

W-004-1 implemented the RC-19 fix (`_has_junior_impl_commits` task-scoped branch detection). W-004 was the **1st instance** of the fix being exercised — but meta-circular: W-004 dogfooded its own fix at landing. The cycle was simultaneously the fix author and the fix consumer.

P1.6 is the **2nd instance + 1st non-meta-circular substantive use**: the fix was authored in a prior cycle (W-004); P1.6 inherits it as substrate and exercises it on the unrelated payload (snapshot mechanics + decision log + e2e). Per senior plan-vs-impl §2 SD-DOGFOOD validation entry: "`workflow advance` correctly detected junior-impl commits ahead of origin/main since `last_transition_at`; state advanced `awaiting_junior_impl → awaiting_senior_plan_vs_impl` without override."

**Empirical validation of "δ ≠ skip-forever; δ = bounded-venue" framing** (P1.5.5 R0-A `architect-routing-R0-A.md` precedent): the RC-19 defer-to-W-004 routing held — W-004 was the venue; the fix landed; P1.6 is the **2nd cycle to consume the fix transparently**. Discipline gradient held cross-cycle.

### 🟢 G6 — Notable milestone: W-002.5 multi-ADR aggregation 2nd project use

W-002.5 codified the multi-ADR aggregation path β (`adr: [list]` in plan frontmatter; both ADRs must reach Accepted before `awaiting_junior_impl`). W-002.5 was the **1st use** (its own self-dogfood with ADR-014 + ADR-015 — wait, W-002.5 itself was about ADR-010 + ADR-011 codification + dogfood; ADR-014 + ADR-015 are P1.6).

Correcting: W-002.5's own dogfood was ADR-010 + ADR-011 pair → **1st use** of W-002-2b path β multi-ADR aggregation. P1.6 (ADR-014 + ADR-015 pair) is the **2nd project use** — first cross-cycle application after the codification + self-dogfood.

Independent verification: ADR-014 and ADR-015 both at `Accepted` status post `89bfdba` predecessor commit; senior plan + brief both reference multi-ADR aggregation; `workflow advance --task-id P1.6` fired `awaiting_architect_accept → awaiting_junior_impl` cleanly. The state-machine path held under the second pair-type (Snapshot/DecisionLog vs the original codification's senior-planning/multi-agent-dispatch).

### 🟢 G7 — Notable milestone: ADR-012 `snapshot_pending → closed` first-fire + ADR-014/015 first-runtime + Logger-as-producer first instance

Three first-instances aggregated in P1.6:

1. **ADR-012 `snapshot_pending → closed` room state transition first-fire**: ADR-012 (P1.5) declared the room state machine including this transition rule (`rule_matched="summary_snapshot_triggers_closed"`); P1.5 + P1.5.5 + W-003 + W-004 all transitioned rooms through earlier states but never reached `snapshot_pending`. P1.6-4 e2e test is the **first runtime exercise** of the closing transition. Verified at `tests/integration/test_p1_6_e2e.py` closing-transition assertion.

2. **ADR-014 (snapshot contract) + ADR-015 (decision log shape) first-runtime**: Both Accepted at plan-stage routing absorption (`89bfdba`); P1.6 impl is the first runtime — every D-section in both ADRs is exercised for the first time. SD-METADATA brief-predicted self-discovery operationally validated (TYPED_METADATA pattern + `_BaseMeta` subclass pattern preserved).

3. **Logger-as-producer first instance**: Logger agent existed before P1.6 with `speaking_triggers` only on UTTERANCE-style triggers; P1.6-3 adds `StateChangeTrigger(target_state="snapshot_pending")` + the new `agents/snapshot_dispatch.py` sibling module per ADR-013 D1 precedent (mirror of P1.5.5 `tool_dispatch.py`). **First non-utterance Logger role + first ADR-013 D1 sibling-module pattern second exercise** (P1.5.5 tool_dispatch was 1st).

Independent verification of (3): `git log -p origin/claude/P1.6-impl -- config/agents/logger.yaml` shows the `speaking_triggers` block addition is net-new; `git log --diff-filter=A -- src/orchestrator/agents/snapshot_dispatch.py` confirms file is new in P1.6-3.

### 🟢 G8 — Pattern-recurrence: M-Y1 + M-Y2 are same anti-pattern shape as P1.5.5 RC-19 (W-005 codification queue candidate)

Both senior plan-vs-impl Y1+Y2 and proxy R0-B Y2+Y4 + Y6 converge on the same **error-handling policy gap** root cause: the plan §4 forcing functions §3 cleanup said "per ADR-011 D7-b pattern" but ADR-011 D7-b is specifically the `event_store.append` propagation rule, not a generic license for derivation/dispatch failure modes. The plan didn't disambiguate; junior chose the lenient direction (broad try/except wrappers + silent swallow) without explicit plan license.

**Pattern-recurrence claim**: same anti-pattern shape as P1.5.5 RC-19 (defensive Z-suffix timezone hardening implemented under δ deferral language; junior improvised under unclear policy without explicit license). Different specific failures; same meta-shape: **junior implementing defensive measures under plan-stage policy ambiguity that aren't explicitly licensed**.

The fixes also share meta-shape: a plan-stage forcing function that pre-empts the gap. P1.5.5 RC-19's resolution was W-004-2(c) literal-reading discipline (junior must not improvise under deferral language). P1.6's analogous pre-emption would be **a plan §4 forcing function explicitly requiring error-semantic pinning for new-module derivation/dispatch surfaces** (raise vs swallow vs log+skip + which exception types).

**W-005 codification queue capture**: this is the **1st codified instance of "plan-stage error-semantic pinning rule"** as a senior-planner.md / brief-template forcing function. Per W-003 architect-routing.md precedent (3-instance codification threshold), this single instance does not yet warrant codification; capture for W-005 + accumulate until 2nd + 3rd instances emerge. Also reference: P1.5.5 R0-A R0-A-on-plan.md and joint retro W-003+P1.5.5.md §13 already names "diagnose-before-fix codification" as a 1-instance item awaiting accumulation; the error-semantic-pinning rule joins as a sibling 1-instance item.

### 🟢 G9 — Pattern-recurrence: R0-A senior R1 miss = 1st impl-stage empirical validation of dual-lens-r0b.md "trusts-the-types" Claude-family bias

`docs/process/dual-lens-r0b.md` § "Empirical conclusion" names "Claude's cognitive style trusts that 'if the types are right, the runtime is right'" as a structural bias of same-family review. P1.4 was the 1st empirical validation at plan stage (DeepSeek V4 Pro caught plan-level issues senior + architect-partner missed).

P1.6 is the **1st empirical validation at impl stage**: the proxy R0-B (deliberately contrarian Claude, primed to over-correct for the trusts-the-types bias) caught R1 — a spec-impl divergence on a documented ADR edge case that senior plan-vs-impl missed despite walking D2.3 algorithmically. Senior's verification stopped at "predicate correlation walk implemented correctly"; the edge-case clause was structurally invisible because the schema's Literal type already constrained out the third option.

**Process-validation framing**: even with deliberately contrarian Claude-family priming, only 1 🔴 surfaced. This bounds the proxy-lens coverage; true cross-family R0-B (DeepSeek V4 Pro / GPT-class / Gemini per `external-r0b-prompt.md` post-update) is likely to surface the runtime-integration class of issue the proxy explicitly says it under-weights. **Worth retro capture** as the empirical evidence base for "when same-family impl-stage R0-A misses a spec-impl divergence that proxy R0-B catches, ALWAYS dispatch true cross-family before architect routes."

This framing motivates Y1 below.

### 🟢 G10 — Brief-vs-impl coherence: W-004-2(c) literal-reading discipline first applied in non-meta-circular cycle

W-004-2(c) codified the architect-deferral-literal-reading discipline at `c1dcc09`. W-004 itself was the meta-circular cycle (rule codified + first cycle-level test); W-004-3 dogfood held cleanly per W-004 R0-A G3.

P1.6 is the **first cycle where W-004-2(c) is applied to a brief written before the rule's codification** (P1.6 brief published earlier than the W-004-2(c) codification commit). Brief Out-of-scope items honored as literal-read deferrals:

- **Cross-room memory promotion** (brief Out-of-scope #1): no in-cycle stab; deferred to P1.6.5/P1.7 per literal-read; no improvised "while we're here" cross-room hooks in the impl.
- **LLMPurpose.SNAPSHOT_SEMANTIC deferral** (brief Out-of-scope #3): no LLMPurpose enum addition; no LLM-router wiring for snapshots in P1.6 scope.
- **Combined `derived/` package** (senior §5 #4 deviation from brief split-package lean): senior explicitly took this as a `senior decides verification path` move, with brief-architect-partner approval at routing time. This is NOT a literal-read violation — it's a substantive senior-judgment move with audit trail.

**1st instance of W-004-2(c) holding cleanly on a brief authored before its codification.** Discipline gradient at architect-deferral level held cross-cycle.

### 🟢 G11 — Role-separation discipline validation: architect-partner self-incrimination caught by architect

Earlier in this session, architect-partner (me) produced a merge synthesis combining R0-A senior + R0-B proxy findings, framed as "two independent reviews converge → high confidence" for M-Y1 + M-Y2. Architect (user) caught the over-claim immediately: "R0-A是你自己 lol" — both reviewers are Claude-family; the convergence is NOT independent evidence but rather a shared-bias confirmation that signals the **opposite** of independence.

This is exactly the Claude-family-consensus blind spot `dual-lens-r0b.md` warns about, surfacing **at the architect-partner synthesis layer rather than at the individual review layer**. The architect's catch validates two project-discipline assumptions:

1. **Role-separation works as designed**: architect-partner and architect (user) are deliberately separate roles for cross-perspective independence. The architect-partner's instinct to merge same-family reviews as "independent" is exactly the bias the role-separation guards against; the architect's intervention closes the gap.
2. **Same-family blind spots are recursive**: the bias the proxy lens was deliberately primed against (over-corrected for at R0-B) re-emerges at the synthesis layer if the architect-partner forgets the proxy's same-family status. The "two reviews converged" framing felt natural because it would have been true for two-independent-family reviews; the framing's incorrectness depends on remembering the family lineage.

**Captured as 2nd instance of architect-partner-direct-action correction pattern in 2 consecutive cycles**: W-004 had architect-partner-direct retro authorship (W-004-3); P1.6 has architect-partner-direct merge over-claim. W-004 instance was a positive process signal (architect-partner-direct channel as intended); P1.6 instance is a corrective process signal (architect-partner-direct synthesis caught + recalibrated by architect). Both are about the architect-partner-direct interface; pattern-recurrence in opposite directions.

**Worth retro capture** as a sub-pattern of "Claude-family-consensus blind spots also surface at synthesis layers, not only at individual review layers." Possible W-005 codification candidate (1st instance; await accumulation).

---

### 🟡 Y1 — External R0-B (true cross-family) not yet dispatched at impl stage; routing-before-dispatch risks cycle-3 follow-up

**Process observation**, not impl-line finding.

**State**: per `docs/process/reviews/P1.6/external-r0b-prompt.md` (updated this session for impl-stage targeting), the dispatch prompt is ready but no external session has run yet. The existing `R0-B-cross-family.md` file is the proxy-lens placeholder (frontmatter `reviewer_family: claude-proxy`); the architect has not yet sent the artifact bundle to a non-Claude model.

**Concern**: if architect routes M-R1 + M-Y1 + M-Y2 now (per the merge synthesis tabled earlier this session), junior gets cycle-2 follow-up scoped to those three. If external R0-B subsequently surfaces NEW 🔴 or 🟡 findings (highly possible per G9 — proxy explicitly under-weights runtime-integration class issues), junior gets cycle-3. Cycle-2 + cycle-3 is more expensive than cycle-2-on-union.

**Lean (α)**: dispatch true cross-family R0-B (DeepSeek V4 Pro / GPT / Gemini per updated `external-r0b-prompt.md`) BEFORE architect routes. Merge external findings with the existing R0-A-senior + R0-B-proxy synthesis; architect routes union; junior gets one cycle-2 commit covering the full set.

**Filename convention note**: external R0-B result will be **appended as a new 'True cross-family R0-B' section in the existing `R0-B-cross-family.md`** per P1.4 precedent + `dual-lens-r0b.md:147` codified convention ("Result is appended to the same `R0-B-cross-family.md` file"). File-level verdict bumps in-place per RC-10. No file rename needed — frontmatter `reviewer_family: claude-proxy` on the current section already disambiguates from the external section that will follow. (An earlier draft of this Y1 mistakenly proposed a split-file rename "per P1.4 convention"; correction: P1.4 convention is single-file append, not split files.)

**Why not γ**: routing-before-external is defensible if (a) the architect believes proxy lens is near-comprehensive and (b) cycle-3 overhead is acceptable. Both are weakly true; project history (P1.4 plan-stage external R0-B caught 3 net-new findings beyond in-session reviews) argues for routing-after-external as the higher-EV default.

**Why not β**: there isn't a meaningfully different shape — the action is "dispatch first" or "route first," binary.

---

### 🟡 Y2 — ADR-014 D2 has no derivation predicate for `decision_count`; impl chose `{DECISION, DECISION_PIVOT, REJECTION, RETRACTION}` without ADR sanction

**This finding surfaced from the G3 spot-check; neither senior plan-vs-impl, proxy R0-B, nor plan-stage R0-A-on-plan caught it.**

**ADR-014 §2 introduction** describes `decision_count` (line 99): "total decisions made in the room — separate from open_hypotheses to signal closure." No D2.6 subsection inscribes the derivation predicate (which event types count as "decisions"?). The plan-stage Y1 absorption added D2.1-D2.5 for `open_hypotheses`, `closed_decisions`, `tool_calls_pending_confirm`, `participants`, `last_state_transition` — but `decision_count` (the only other non-trivially-derived Snapshot field, alongside `event_count` which is literally `len(events)`) was not given its own predicate subsection.

**Impl** (`snapshot.py:79-87 + 215`):
```python
_DECISION_CLASS_TYPES: frozenset[EventType] = frozenset(
    {EventType.DECISION, EventType.DECISION_PIVOT,
     EventType.REJECTION, EventType.RETRACTION}
)
# ...
decision_count = sum(1 for e in sorted_events if e.type in _DECISION_CLASS_TYPES)
```

Junior chose to count all 4 decision-class event types. Other defensible choices the ADR text could support:
- **Literal-read**: only `DECISION` events (the "total decisions" phrase taken narrowly).
- **Closure-aware**: `len(closed_decisions)` (decisions still standing post-retraction).
- **Decision-as-direction**: `DECISION + DECISION_PIVOT` (decisions and re-orientations).
- **Impl choice**: `DECISION + DECISION_PIVOT + REJECTION + RETRACTION` (all decision-class events).

Each interpretation produces a different number for the same event stream. A consumer asking "how many decisions in this room?" gets impl-choice's answer (sum-of-decision-class), but a reader of ADR-014 §2 intro would be unable to predict that answer from the ADR text alone.

**Pattern-recurrence claim**: this is the **same anti-pattern shape as the plan-stage Y1 finding** that drove the D2.1-D2.5 amendment ("vocabulary types declared without derivation algorithms is incomplete inscription per Principle 9"). At plan-stage routing, architect-partner caught D2.1-D2.5 missing predicates; at impl-stage, `decision_count`'s missing predicate slipped past **plan-stage R0-A-on-plan, senior plan-vs-impl, AND proxy R0-B** — all three reviews implicitly accepted the impl choice without flagging that ADR text didn't predict it. **2nd instance of "ADR D-section vocabulary types declared without derivation algorithms" anti-pattern surfacing post-fix.**

**Lean (α)**: amend ADR-014 D2 with a new **D2.6 `decision_count` predicate** inscribing the event-type set. Almost certainly ratifies impl's choice (all 4 decision-class types) — that's the most useful count for consumers asking "how active is this room decision-wise?" and the impl chose it for defensible reason. Cost: ~10-15 LoC of ADR amendment text + 1-line comment cross-reference in `snapshot.py:215`. No runtime change.

**Why α (not β)**: β would be "accept impl choice in-place, document via code comment only" — but this is the **same trade-off the plan-stage Y1 found inadequate for D2.1-D2.5**. ADR inscription is the load-bearing audit-trail; code comments are downstream. Symmetry with plan-stage routing pattern argues for α.

**Why α (not γ)**: γ would mean accepting that some Snapshot fields have ADR-inscribed predicates and some don't. This breaks the inscription-completeness invariant that the plan-stage Y1 amendment was designed to establish.

**Sub-observation about D2.1 + D2.2 "any vs subsequent" semantic** (from G3 spot-check): the ADR specifies "no subsequent event satisfies close condition"; impl checks "no event in the full sorted stream cites the hypothesis/decision." Equivalent for valid streams; divergent for anomaly cite-before-cited streams. **Not folded into Y2 routing scope** because (a) anomaly-only manifestation; (b) impl's "any" reading is arguably more defensible than ADR's "subsequent" reading for the anomaly case (impl says "close H because something cites it, regardless of order"; ADR says "leave H open until subsequent cite"). Worth a 1-sentence ADR-014 D2.1 + D2.2 clarification at the same routing pass if Y2 routes α — opportunistic precision improvement. Not Y-worthy alone.

---

## Verdict and recommended next action

**Verdict**: `needs_architect`.

**Reason**: 2 architect-partner yellow findings (Y1 + Y2) compound with the existing senior + proxy findings (merge-table M-R1 + M-Y1 + M-Y2 + 5 lower-severity items) on the architect's routing docket. Y1 is a **process-discipline ordering question** (dispatch true cross-family before route, vs. route now); Y2 is a **substantive ADR-014 amendment** that should land in the same cycle as M-R1's amendment (both touch ADR-014 D2 inscription completeness).

**Recommended order**:
1. **First**: architect dispatches true cross-family R0-B per updated `external-r0b-prompt.md` (Y1 action). External result appends as new section in existing `R0-B-cross-family.md` per `dual-lens-r0b.md:147` convention; file-level verdict bumps in-place per RC-10.
2. **Second**: external R0-B returns. Architect-partner re-merges with NEW / CONFIRM / CONTRADICT markers per the external prompt's mandatory output format. Y2 (decision_count predicate) joins the routing table.
3. **Third**: architect routes the union (M-R1 + M-Y1 + M-Y2 + Y2 + any new external findings). Junior cycle-2 follow-up commit scoped to the full set.
4. **Fourth**: cycle-2 closes; verdict bumps (RC-10) on this R0-A + R0-A senior + R0-B proxy + R0-B external (each acknowledges the routing's resolution); state advances `awaiting_architect_decision → awaiting_senior_plan_vs_impl` for the cycle-2 senior review, then `→ closed`.

**Audit observation echoing senior plan-vs-impl §5**: the 7-cycle impl-drift-free streak is on the **coverage axis** (every plan-pinned acceptance bullet implemented; senior pins validated; SD-DOGFOOD operationally validated; all Y findings are post-coverage error-handling/inscription-completeness issues, not impl miss-the-plan drift). The streak's value is the substrate maturity P1.6 inherits — it does NOT mean the impl is finding-free, only that the impl-implements-the-plan invariant holds.

**Cross-references**:
- `docs/process/reviews/P1.6/plan-vs-impl.md` — senior R0-A; M-Y1 + M-Y2 source.
- `docs/process/reviews/P1.6/R0-B-cross-family.md` — proxy R0-B; M-R1 source.
- `docs/process/reviews/P1.6/external-r0b-prompt.md` — Y1 action artifact (impl-stage updated this session).
- `docs/process/reviews/P1.6/architect-routing.md` — plan-stage routing (α/α/α precedent); impl-stage routing TBD (architect creates `architect-routing-on-impl.md` or similar).
- `docs/decisions/ADR-014-snapshot-contract.md` — Y2 amendment subject (add D2.6 for `decision_count`) + opportunistic D2.1+D2.2 "any vs subsequent" clarification.
- `docs/process/dual-lens-r0b.md` — G9 + Y1 framing source; possible future-amendment hook for "impl-stage dispatch criteria when same-family R0-A misses spec-impl divergence."
- `docs/process/senior-planner.md` § Pre-investigation discipline (W-004-2 codified) — G8 "plan-stage error-semantic pinning rule" candidate for future codification.
- `docs/retrospectives/W-003+P1.5.5.md` § 13 — 1-instance codification queue precedent; G8 + G11 join as sibling 1-instance items.
- `docs/process/reviews/W-004/R0-A.md` — architect-partner R0-A format precedent.
