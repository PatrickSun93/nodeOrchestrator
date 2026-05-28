---
task_id: P1.6
round: R0-B-cross-family
reviewer_family: claude-proxy
reviewer_model_id: claude-opus-4-7
reviewer_note: >
  Proxy-lens review — NOT a true cross-family review. Executed in-session
  by reviewer-r0b role with deliberately contrarian prompt (over-correcting
  for Claude biases: operational/failure-mode concerns, spec-implementation
  divergence, silent error paths). A true cross-family R0-B (DeepSeek/GPT/Gemini
  external session) should follow per RC-15 + external-r0b-prompt.md.
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 19
verdict_history:
  - verdict: needs_architect
    at_commit: c5ba841
    findings_count: { red: 1, yellow: 8, green: 10 }
    note: Cycle-1 proxy-lens review surfaced R1 (ToolCallRef anomaly handling contradicts ADR-014 D2.3) + 8 yellows spanning operational failure modes (Y4 stuck-room, Y2/Y6 silent ValidationError swallow), spec-impl divergence (R1 only), wasted work (Y1 produce_decision_log discard), semantic imprecision (Y5/Y7/Y8). 10 G's confirm structural soundness (clock-injection, D2.1-D2.5 predicates, schema discipline, e2e coverage, constitutional test, SummarySnapshotMeta duplication, ADR-013 D1 sibling pattern, ADR-015 D2 filter, chronological ordering, content_excerpt verbatim).
  - verdict: clean
    at_commit: 900d6f7
    findings_count: { red: 0, yellow: 0, green: 19 }
    note: Cycle-2 absorption per architect-routing-on-impl.md. R1+Y1-Y8 all 🟢-absorbed via M-R1+M-Y3+M-Y2+M-Y4+M-Y1+M-Y5+M-Y6+M-Y7 routing decisions. Original 10 greens preserved. Proxy-lens caveat preserved; true cross-family R0-B deferred per Y1 γ-override (architect skip).
---

# P1.6 R0-B cross-family review (proxy lens)

> **RC-10 frontmatter-as-live-signal bump (cycle-2 absorption, 2026-05-28)**
>
> Cycle-1 verdict `needs_architect (1🔴/8🟡/10🟢)` at `c5ba841` → cycle-2 verdict `clean (0🔴/0🟡/19🟢)` per architect-routing-on-impl.md absorption. All R1 + Y findings absorbed via routing decisions; original cycle-1 finding bodies preserved below as audit trail; **bump is additive history, not a rewrite**. Absorption trace per finding:
>
> - **R1 (ToolCallRef anomaly handling contradicts ADR-014 D2.3) → 🟢-absorbed via M-R1 α.** Literal expanded to `["countdown_confirm", "hard_confirm", "unknown"]` at `snapshot.py:44`; anomaly TC path now includes conservatively with `autonomy_tier="unknown"` at `snapshot.py:180-189`; ADR-014 D2.3 inscribes conservative-include rationale at `af8ccc4`; test `test_produce_snapshot_tc_without_preceding_ad_gets_unknown_tier` pins the semantic. **1st impl-stage empirical validation of dual-lens-r0b.md "trusts-the-types" Claude-family bias prediction** — proxy lens (deliberately contrarian Claude) earned its 1 🔴 against same-family R0-A senior + architect-partner who missed it.
> - **Y1 (`produce_decision_log` result discarded in `snapshot_dispatch.py`) → 🟢-absorbed via M-Y3 β.** Comment at `snapshot_dispatch.py:55-58` rewritten to name both (a) ADR-015 D5 derivation-not-persistence intent + (b) intent to exercise derivation path so ValidationError surfaces at trigger, not at first downstream consumer. No code change; comment is now load-bearing documentation.
> - **Y2 (pervasive `except Exception: pass` silences metadata errors) + Y6 (`last_state_transition` silently becomes `None` on metadata failure) → 🟢-absorbed via M-Y2 α-strict.** All swallow blocks removed (8 sites: 6 in `derived/snapshot.py`, 2 in `derived/decision_log.py`; senior+junior grep-confirmed zero remain in `derived/`). ValidationError now propagates; consumers responsible for catching at boundary. ADR-014 D7.1 inscribes the strict-propagation contract.
> - **Y3 (no test coverage for malformed-metadata paths) → 🟢-absorbed via M-Y4 α.** 4 cleanup tests pinning the strict semantic across both modules (`test_produce_snapshot_malformed_decision_metadata_raises`, `..._retraction_..._raises`, `..._state_transition_..._raises`, `test_produce_decision_log_malformed_rejection_metadata_raises`).
> - **Y4 (stuck-room risk: snapshot dispatch failure leaves room in `snapshot_pending` permanently) → 🟢-absorbed via M-Y1 α-A.** `dispatch.py:174` narrowed to `except ValidationError`; `TurnResult.snapshot_failed: bool` field added at `schema.py:239`; failure surfaced from dispatch block at line 186; non-ValidationError (e.g. `event_store.append` RuntimeError) now propagates per ADR-011 D7-b. Caller (room runtime) can retry/escalate. ADR-014 D7.2 inscribes the narrow-and-surface contract.
> - **Y5 (`event_count` semantic is "events at fetch time" not "events at snapshot_at time") → 🟢-absorbed via M-Y5 δ-with-fold-in.** 1-line comment at `snapshot.py:222-223` documents `len(events)` reflects fetch-time count per ADR-011 D1 sequential dispatch; revisit at async-reshape via ADR-014 D6 amendment hook.
> - **Y7 (`participants` excludes silent-voter agents) → 🟢-absorbed via M-Y6 β.** 6-line docstring at `snapshot.py:69-74` above `_AGENT_PARTICIPATION_TYPES` cites ADR-014 D2.4 + names double-count-avoidance rationale + flags future silent-voter revisit hook.
> - **Y8 (snapshot uses pre-turn frozen events; same-turn utterances absent) → 🟢-absorbed via M-Y7 δ-with-fold-in.** 1-line comment at `dispatch.py:77` documents pre-turn snapshot per ADR-011 D2; same-turn utterances not reflected.
> - **G1-G10 (cycle-1 greens) → 🟢-preserved** per architect-routing-on-impl §"Out of scope": "Re-litigating any 🟢 finding from R0-A senior, R0-B proxy, or R0-A architect-partner (all 26 confirm impl + ADR structural soundness)." No action; original findings preserved below as audit trail.
>
> **Proxy-lens caveat update**: this review remains a Claude-family proxy lens, **NOT** a true cross-family review. Cycle-2 dispatched γ-override (Y1 from architect-partner R0-A) **skipping true cross-family R0-B** per architect-routing-on-impl §Y1; rationale + risk-capture there. Future cycles may still dispatch external R0-B per `dual-lens-r0b.md:147` codified append-in-place convention (would append as new "True cross-family R0-B section" in this file).
>
> **Expected next state transition:** cycle close (multi-ADR W-002.5 aggregation 2nd project use); companion bumps: `plan-vs-impl.md` (senior; already bumped at `46de79e`) + `R0-A.md` (architect-partner; bumping in this pass).

---

## ORIGINAL CYCLE-1 REVIEW (preserved as audit trail per RC-10 §3)

**Reviewed**: `claude/P1.6-impl` at `6c7cf7d` — all 5 atomics (P1.6-1 through P1.6-5).

**Lens**: Deliberately contrarian. Over-weighting operational failure modes, silent error paths, spec-implementation divergence, and wasted work. Under-weighting type-safety, abstraction quality, and architectural elegance — those are the in-family R0-A's strengths.

**Caveat**: This is a proxy-lens review by a Claude model, not a true cross-family review by a non-Claude LLM. Claude structural biases limit what this lens can catch (see dual-lens-r0b.md §"Empirical conclusion"). A true cross-family R0-B (DeepSeek V4 Pro or GPT-4-class) should follow per the `external-r0b-prompt.md` artifact.

---

## 🔴 Findings

### R1 — `ToolCallRef` anomaly handling contradicts ADR-014 D2.3

**Location**: `src/orchestrator/derived/snapshot.py` lines ~150-155 (TC-without-AD branch) vs ADR-014 D2.3 edge case specification (lines 137-138 in ADR).

**What**: ADR-014 D2.3 specifies: "if a TC exists without a preceding AD, that's a data anomaly (snapshot still includes TC in pending-confirm conservatively, since 'no decision = treat as awaiting confirmation')." The implementation does the opposite:

```python
# No preceding AD (anomaly): skip; can't determine tier for ToolCallRef.
```

The TC is silently excluded from `tool_calls_pending_confirm` rather than conservatively included.

**Root cause**: `ToolCallRef.autonomy_tier` is `Literal["countdown_confirm", "hard_confirm"]` — there's no value for "unknown/unmatched." The schema constrains the implementation to violate the ADR. If the ADR's conservative stance is correct, the schema needs a nullable tier or an `"unknown"` literal variant.

**Why it matters**: This isn't just a spec nit — it's a defined edge case with a specified behavior. If a future bug (e.g., event emission ordering change in async-reshape P1.5+) produces a TC without a preceding AD, the snapshot silently drops it from the pending list. A consumer asking "what's awaiting confirmation?" gets an incomplete answer with no error signal. The ADR's conservative choice ("include; treat as pending") is the safer default for an anomaly case.

**Architect-partner lean**: α — align implementation with ADR. Options:
- **α1 (preferred)**: Add `"unknown"` to `ToolCallRef.autonomy_tier` Literal; include anomaly TCs with `autonomy_tier="unknown"`. Consumers can decide how to handle unknown-tier pending calls.
- **α2**: Make `autonomy_tier` optional (`str | None`) and set `None` for anomaly TCs.
- **β**: Amend ADR-014 D2.3 to match implementation (skip anomaly TCs). Weaker — loses the conservative-default property.
- **γ**: Skip. Unlikely to fire in practice under sequential dispatch; but the spec-implementation divergence is a documented inconsistency that future readers will trip over.

---

## 🟡 Findings

### Y1 — `produce_decision_log` called and result discarded in `snapshot_dispatch.py`

**Location**: `src/orchestrator/agents/snapshot_dispatch.py` line 49.

```python
_ = produce_decision_log(snapshot_events, room)
```

**What**: The decision log is derived and immediately discarded. The comment says "Produce here to exercise the derivation; result not stored (ADR-015 D5)." But "exercising the derivation" is what tests do — it's not a valid runtime reason. At runtime, this is wasted CPU (a full event-stream scan + sort) producing a result nobody reads.

**Why it matters**: This looks like leftover scaffolding. Either:
- The decision log should be persisted alongside the snapshot (appended as event metadata or a separate event) — contradicts ADR-015 D5.
- The call should be removed — the derivation is exercised by tests; runtime doesn't need it.
- There's an unstated reason (future consumer that reads from this call site?) that should be documented.

Every future reader of this code will ask "why is this here?" and either cargo-cult it or delete it. Neither is good.

**Architect-partner lean**: β — remove the call. If the intent is to ensure `produce_decision_log` is importable/functional at runtime, that's a test concern (integration test), not a production code concern. If there IS a future consumer that needs it called here, document it with a `# TODO(P1.6.5): consumed by cross-room memory promotion` style comment.

### Y2 — Pervasive `except Exception: pass` silences all metadata errors

**Location**: `src/orchestrator/derived/snapshot.py` — every `model_validate` call in `produce_snapshot` (5 locations: DecisionMeta, RejectionMeta, RetractionMeta (×2), AutonomyDecisionMetadata, ToolCallMeta, StateTransitionMeta).

**What**: Every typed-metadata parse is wrapped in:

```python
try:
    meta = XxxMeta.model_validate(e.metadata)
    # ... use meta
except Exception:
    pass
```

This catches and discards ALL exception types including `KeyboardInterrupt`, `MemoryError`, `SystemExit` — though those are unlikely inside a Pydantic validation. The real concern is more mundane:

- A `DecisionMeta` with a missing `based_on` field → hypothesis stays "open" forever (should have been closed).
- A `RetractionMeta` with a malformed `retracts` → retracted decision stays in `closed_decisions` (false positive — consumer thinks a retracted decision is still standing).
- A `StateTransitionMeta` with a bad `new_state` → `last_state_transition` is `None` (consumer thinks no transition ever happened).

**Why it matters**: The project's event-store layer validates metadata at append time via `validate_metadata()`, so in theory malformed metadata can't exist in the store. But:
1. Events written before `SummarySnapshotMeta` was added to `TYPED_METADATA` (P1.6-2) would have unvalidated metadata.
2. Future cycles could add event producers that bypass `validate_metadata`.
3. SQLite direct writes (debugging, migration, manual fix) bypass validation.
4. The `except Exception: pass` pattern means these cases produce silently wrong snapshots rather than surfacing errors.

A more defensive approach: log a warning at minimum, or use `except ValidationError` (narrower) so unexpected exceptions still propagate.

**Architect-partner lean**: α — narrow the exception to `except ValidationError` and add `_log.warning(...)` for each silenced validation failure. The `except Exception: pass` pattern should be reserved for cases where "no data" is the correct semantic regardless of failure mode — here, "no data" is a specific semantic (hypothesis not closed, decision not retracted) that may be incorrect.

### Y3 — No test coverage for malformed-metadata paths

**Location**: `tests/derived/test_snapshot.py` — all 51 tests use well-formed metadata.

**What**: The `except Exception: pass` branches in `produce_snapshot` have zero test coverage. Every test constructs events with valid metadata matching the typed schema. There are no tests for:
- HYPOTHESIS followed by DECISION with missing `based_on` field → hypothesis stays open?
- DECISION followed by RETRACTION with missing `retracts` field → decision stays closed?
- TOOL_CALL with malformed `ToolCallMeta` → skipped or included?
- STATE_TRANSITION with malformed `StateTransitionMeta` → `last_state_transition` is None?

**Why it matters**: The behavior of these error paths is untested and therefore undefined. If Y2 is addressed (narrowing exceptions + adding warnings), these paths need tests. If Y2 is skipped, these paths still represent real behavior that future refactors could accidentally change.

**Architect-partner lean**: α — add ≥4 tests covering malformed-metadata paths after Y2 resolution. These are §3 cleanup tests per the test-coverage standard.

### Y4 — Stuck-room risk: snapshot dispatch failure leaves room in `snapshot_pending` permanently

**Location**: `src/orchestrator/agents/dispatch.py` lines ~165-179 (snapshot dispatch call site).

**What**: The snapshot dispatch is wrapped in a catch-all:

```python
try:
    st_meta = StateTransitionMeta.model_validate(current_event.metadata)
    if st_meta.new_state == "snapshot_pending":
        produce_and_emit_snapshot(...)
except Exception as exc:
    _log.warning("agent %s snapshot dispatch failed; skipping (continuing): %s", agent.id, exc)
```

If `produce_and_emit_snapshot` raises (e.g., `event_store.append` fails with a SQLite error), the `summary_snapshot` event is never appended. The next turn won't re-trigger Logger because there's no new `state_transition` to `snapshot_pending`. The room is stuck in `snapshot_pending` with no path to `closed`.

**Why it matters**: This is a silent liveness failure. The room state machine's `snapshot_pending → closed` transition has exactly ONE producer (Logger agent triggered by `state_transition` to `snapshot_pending`). If that producer fails, the transition never fires, and there's no retry mechanism. The current ADR-011 D7-b pattern ("event_store.append exception: propagate unwrapped") is overridden here by the catch-all in the snapshot dispatch block — the error is logged and swallowed.

This is the kind of runtime-integration failure mode that Claude-style review structurally under-weights (per dual-lens-r0b.md §"Empirical conclusion" — "Claude's cognitive style trusts that 'if the types are right, the runtime is right'").

**Architect-partner lean**: α — at minimum, surface the failure in `TurnResult` (add `snapshot_failed: bool` or include in `failed_agents`). The caller (room runtime) can then decide whether to retry or escalate. A more involved fix (retry next turn, or add a `snapshot_failed` room state) is P1.7+ scope.

### Y5 — `event_count` semantic is "events at fetch time" not "events at snapshot_at time"

**Location**: `src/orchestrator/derived/snapshot.py` line ~195 (`event_count=len(events)`).

**What**: `Snapshot.event_count` is set to `len(events)` (the length of the pre-fetched event list). The `snapshot_at` timestamp is captured AFTER the fetch (`now_ms()` after `get_room_events`). Under sequential dispatch (ADR-011 D1), this gap is typically 0ms, but the semantic is imprecise: the snapshot claims "at snapshot_at T, there were N events" when actually "at fetch time T₁ ≤ T, there were N events."

**Why it matters**: Under P1.5+ async-reshape (concurrent dispatch, ADR-011 D1 reserved), the gap between fetch and snapshot_at could be non-trivial. Events appended by concurrent agents between T₁ and T would be counted in neither `event_count` nor the snapshot's derived fields. The ADR-014 D6 caller-frozen-time semantic covers this ("any events appended between T₁ and step 5 are NOT in this snapshot's view"), but `event_count` should reflect what was actually counted, not claim alignment with `snapshot_at`.

**Architect-partner lean**: β — document the semantic in a code comment at the `event_count=len(events)` line. This is a P1.6 non-issue (sequential dispatch), but the async-reshape future-amendment hook in ADR-014 D6 should name `event_count` semantic precision as a revisit item.

### Y6 — `last_state_transition` silently becomes `None` on metadata failure

**Location**: `src/orchestrator/derived/snapshot.py` lines ~170-178.

```python
if st_events:
    last_st = max(st_events, key=lambda e: (e.timestamp, e.id))
    try:
        st_meta = StateTransitionMeta.model_validate(last_st.metadata)
        last_state_transition = StateTransitionRef(...)
    except Exception:
        pass  # last_state_transition stays None
```

**What**: If the single most-recent `STATE_TRANSITION` event has malformed metadata, `last_state_transition` is `None`. A consumer interprets `None` as "this room has never transitioned" — which is semantically wrong (transitions happened; the most recent one is just unparseable). This is a specific instance of Y2 but warrants separate flagging because the semantic distortion is sharper: `None` has a specific meaning ("no transitions"), and silent fallback to `None` on parse failure conflates "no data" with "bad data."

**Architect-partner lean**: α — same resolution as Y2 (narrow exception + log warning). If validation fails, `last_state_transition` should still be `None` (can't construct the ref), but the warning distinguishes "no transitions exist" from "most recent transition had malformed metadata."

### Y7 — `participants` excludes agents who only decide (never utter)

**Location**: `src/orchestrator/derived/snapshot.py` `_AGENT_PARTICIPATION_TYPES` + D2.4 implementation.

**What**: The `participants` set is built from `{UTTERANCE, SUMMARY_SNAPSHOT, TOOL_CALL, AUTONOMY_DECISION, AUTONOMY_REFUSAL}` event types. Agent-authored `DECISION`/`HYPOTHESIS`/`REJECTION`/`RETRACTION` events don't count. The ADR-014 D2.4 rationale says this avoids double-counting when an agent "both speaks and decides on the same content."

But consider: an agent that emits only a `DECISION` event (no `UTTERANCE`) — perhaps a future "silent voter" agent. That agent would not appear in `participants` despite having contributed a decision to the room. A consumer asking "who participated in this room?" gets an incomplete answer.

**Why it matters**: This is a narrow edge case today (agents that decide also tend to utter), but the "participants" name implies completeness. Either the name should be narrower (`speaking_participants` or `active_participants`) or the event-type set should include agent-authored decision-class events.

**Architect-partner lean**: β — document the exclusion rationale in a code comment above `_AGENT_PARTICIPATION_TYPES` referencing ADR-014 D2.4. The current implementation matches the ADR; this is a naming/clarity concern, not a bug.

### Y8 — Snapshot uses pre-turn frozen snapshot; doesn't include same-turn agent utterances

**Location**: `src/orchestrator/agents/dispatch.py` — the `snapshot` variable captured at line ~70 (`snapshot = event_store.get_room_events(room.id)`) is passed to `produce_and_emit_snapshot` later in the loop.

**What**: When Logger triggers on `state_transition(snapshot_pending)`, the `snapshot_events` passed to `produce_snapshot` is the pre-turn snapshot — captured before any agent (including Logger itself) spoke in this turn. If other agents spoke before Logger in the same turn (alphabetical ordering), their utterances are NOT in the snapshot. Logger's own utterance (which happens just before the snapshot dispatch in the same loop iteration) is also NOT in the snapshot.

**Why it matters**: This is intentional per ADR-011 D2 (snapshot frozen at turn entry), so it's a design choice, not a bug. But future readers may not realize that the `summary_snapshot` event's metadata reflects pre-turn state, not "state at the moment the snapshot was produced." A consumer retrieving a `summary_snapshot` event and seeing `event_count=47` might not realize that 3 more events (same-turn agent utterances) happened before the snapshot was persisted. The gap is visible (snapshot_at timestamp > last event timestamp in the snapshot), but subtle.

**Architect-partner lean**: δ — no code change. This is a documentation concern. The ADR-014 D6 caller-frozen-time semantic covers it, but a code comment at the dispatch call site noting "uses pre-turn snapshot per ADR-011 D2; same-turn utterances are NOT reflected" would help future readers.

---

## 🟢 Findings (confirmations of structural soundness)

### G1 — Clock-injection pattern correctly isolates wall-clock impurity

`produce_snapshot` receives `snapshot_at` as a keyword-only parameter. The caller (`produce_and_emit_snapshot`) calls `now_ms()` once and threads the value through. Purity contract restored per ADR-014 D1 Y2 absorption. The same `snapshot_at` value is used for both the Snapshot's clock field AND the appended Event's timestamp — consistent caller-frozen-time semantic.

### G2 — ADR-014 D2.1-D2.5 derivation predicates accurately implemented

Each predicate matches its ADR specification:
- D2.1: typed-metadata cite chains (DecisionMeta.based_on, RejectionMeta.rejects, RetractionMeta.retracts) — correctly uses metadata-level links, not `parent_id`.
- D2.2: DECISION not retracted; DECISION_PIVOT excluded.
- D2.3: (author, tool_name) correlation with most-recent preceding AUTONOMY_DECISION; tier filter correct.
- D2.4: agent-authored participation types sorted ascending lex.
- D2.5: max(timestamp, id) lex tie-break; None if absent.

### G3 — Schema invariants thoroughly tested

5 classes × ≥4 §6 tests each = ≥20 schema tests, plus §5 boundary validators (event_count ≥ 0, decision_count ≥ 0). `extra="forbid"` and `frozen=True` enforced on all classes. `ToolCallRef.autonomy_tier` correctly rejects `"auto_execute"`.

### G4 — E2e test exercises the full state chain correctly

`test_p1_6_e2e_full_room_state_chain_through_snapshot_pending_to_closed` walks all 6 states (setup → exploration → divergence → convergence → snapshot_pending → closed), verifies `summary_snapshot` event presence, `SummarySnapshotMeta` validation, `Snapshot` re-derivation, `DecisionLog` derivation, chronological ordering, source≠sink invariant on event_id flow, and the closing `snapshot_pending → closed` transition with `rule_matched="summary_snapshot_triggers_closed"`.

### G5 — Constitutional test correctly scoped to single `derived/` package

`test_constitution_no_llm_calls_in_derived_module` covers the combined package (per senior §5 #4 deviation). Matches the `autonomy/` constitutional test pattern. Forbidden patterns: `anthropic`, `openai`, `LLMRouter`, `llm_router`.

### G6 — SummarySnapshotMeta deliberate duplication correctly mirrors Snapshot

Field shape matches between `core/event.py:SummarySnapshotMeta` and `derived/snapshot.py:Snapshot`. Round-trip invariant tested (`Snapshot.model_dump() → SummarySnapshotMeta.model_validate()`). `core/event` has no import from `derived/` — layering preserved per ADR-014 D5.

### G7 — ADR-013 D1 sibling-module pattern correctly followed

`agents/snapshot_dispatch.py` mirrors `agents/tool_dispatch.py` from P1.5.5: separate module, single call site in `dispatch.py`, module owns the dispatch logic + event emission ordering.

### G8 — Decision log filter semantic matches ADR-015 D2

4-event-type binary filter (DECISION, DECISION_PIVOT, REJECTION, RETRACTION). Non-decision events excluded. `parent_event_id` correctly populated from `RejectionMeta.rejects` / `RetractionMeta.retracts`; `None` for decision/decision_pivot.

### G9 — Chronological ordering + lex tie-break correctly implemented

`entries.sort(key=lambda entry: (entry.timestamp, entry.event_id))` ascending. Per-set determinism via UUID v4 lex sort. ADR-015 D4 rationale correctly documented in code comments.

### G10 — `content_excerpt[:200]` verbatim discipline correct

No paraphrase, no LLM summarization. Matches ADR-015 D3 + Logger's `forbidden_behaviors` ("paraphrasing_decisions").

---

## Verdict summary

**1 🔴, 8 🟡, 10 🟢 → `needs_architect`**

The 🔴 is real: implementation contradicts ADR-014 D2.3 on a defined edge case. The fix is small (schema Literal change + 3 lines in `produce_snapshot`), but it should be architect-routed because it touches the ADR-implementation contract boundary.

The 🟡 cluster has a pattern: operational failure modes (Y2, Y3, Y4, Y6) that Claude-style review structurally under-weights. Y4 (stuck-room) is the most operationally significant — a single `event_store.append` failure in the snapshot path permanently wedges a room with no recovery path.

The 🟢 confirmations are strong: the core derivation predicates, schema discipline, constitutional test, clock-injection, and e2e test are all correctly implemented per ADR specifications.

**Comparison to in-family R0-A**: The in-family R0-A-on-plan caught 3 🟡 (ADR D-section precision items — Y1+Y2+Y3). This cross-family review catches 1 🔴 + 8 🟡, with a different error distribution: spec-implementation divergence (R1) + operational silence (Y2/Y3/Y4/Y6) + wasted work (Y1) + semantic imprecision (Y5/Y7/Y8). The error-class difference matches the P1.4 dual-lens empirical pattern: proxy lens catches spec-level errors; true cross-family would additionally probe runtime-integration errors. The stuck-room finding (Y4) is the kind of runtime failure-mode error the dual-lens-r0b.md predicts Claude-family reviewers structurally under-weight.

**Recommendation**: Architect routes R1 + Y1-Y4 + Y6 (6 findings); Y5+Y7+Y8 are documentation/clarity items that can be addressed inline without a full routing cycle. Then dispatch the true cross-family R0-B (DeepSeek V4 Pro external) per `external-r0b-prompt.md` — the external lens may surface additional runtime-integration errors this proxy lens missed.
