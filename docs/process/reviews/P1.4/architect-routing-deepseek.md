---
task_id: P1.4
kind: architect-routing
date: 2026-05-27
reviews_acked:
  - R0-B-cross-family.md (True cross-family R0-B section — DeepSeek V4 Pro, 2026-05-27)
decision: ack_all_leans
supersedes_partial: architect-routing.md (2b92e34, ack-all-leans on proxy-R0-B + R0-A) — DOES NOT invalidate; absorbs new DeepSeek findings on top of prior absorption
---

# P1.4 architect routing — DeepSeek R0-B "ack all leans"

**Architect decision (this session):** `ack all leans` — every finding
in the True cross-family R0-B section of `docs/process/reviews/P1.4/R0-B-cross-family.md`
(DeepSeek V4 Pro reviewer, committed `d60cd99`) resolves to the
review-author's own recommended lean, with architect-partner
refinement noted per finding.

**Pattern**: same as the prior routing (`architect-routing.md`,
commit `2b92e34`) which acked all proxy-R0-B + R0-A leans into
the senior revision at `33977db`. This routing is the second
absorption pass on the same task — a true cross-family R0-B
surfaced runtime-integration findings that the proxy-lens R0-B
structurally missed.

This file is a **signal artifact for the senior revision session**
that follows. The senior session that picks P1.4 next reads:
- This routing file (DeepSeek findings + leans)
- `R0-B-cross-family.md` (the actual review)
- The prior `architect-routing.md` (proxy + R0-A leans — already absorbed; for context)
- The revised plan + ADRs on main (post-`33977db` state)

and applies each finding's routed action without further architect intervention.

## Cross-validation signal — why this routing matters

The DeepSeek review confirmed 4 of the absorbed proxy-R0-B revisions
(D1 sync, D3 no-priority, D6 separate registry, D7 log+skip+continue)
AND surfaced 6 new findings the proxy lens structurally missed:

- 2 🔴: runtime-integration failure paths (event_store append failure;
  all-agents-fail caller contract). Both visible only by tracing
  call-flow across module boundaries; proxy-Claude's "if types are
  right, runtime is right" cognitive style missed them.
- 4 🟡: signature honesty + integration testing + naming + format
  defense-in-depth. The "correct on paper, fragile at the seams"
  cluster.

**Validates audit item #7**: true cross-family review has structural
value the proxy-lens approach cannot replicate. Worth budgeting for
in future shape-change cycles (P1.5+ Skeptic content tuning likely
doesn't warrant; multi-agent dispatch P1.4-style absolutely did).

## Per-finding routing — 🔴 (load-bearing, block ADR Accepts)

| Finding | Routed resolution | Source / lean origin |
|---|---|---|
| **🔴#1 (event_store.append failure path absent in dispatch_turn)** | **Add ADR-011 D7-b**: event-store append failure **aborts the turn** (raise, do not continue). Asymmetric semantic from LLM-failure (per-agent → continue): event-store failure is per-turn fatal (single source of truth unavailable; further LLM calls would burn budget for unpersistable events). P1.4-8 acceptance gains §3 cleanup variant test: mock `event_store.append` to raise `sqlite3.OperationalError` on agent A's utterance; assert exception propagates (no continue to agent B); assert no further LLM calls. ADR-011 D7-b grows ~80 words; Considered Alternatives: (i) silent skip + log only — rejected (event store IS the truth, silence is dishonest); (ii) per-turn retry with backoff — rejected (P1.4 doesn't have retry infrastructure; defer to P1.5+). | DeepSeek finding #1 lean; architect-partner agrees on asymmetry framing. |
| **🔴#2 (all-agents-fail returns `[]` indistinguishable from no-trigger)** | **Add `TurnResult` Pydantic model** to P1.4-4 schema: `TurnResult(utterances: list[Event], failed_agents: list[str], total_asked: int)`. `dispatch_turn` returns `TurnResult` instead of `list[Event]`. ADR-011 D1 + D7 reference the new return type. Plan P1.4-8 acceptance updates signature and adds one §6 test (frozen + extra-forbid + Field constraints). Tests in P1.4-8 distinguish three cases: zero-asked (no triggers fire); N-asked-N-success (TurnResult with `utterances=N, failed=[], total_asked=N`); N-asked-N-fail (TurnResult with `utterances=[], failed=N-ids, total_asked=N`). Programmatically detectable by caller (room runtime, P1.5+); no log-watching dependency. | DeepSeek finding #2 lean (a); architect-partner agrees over option (b) log-dependency. |

## Per-finding routing — 🟡 (revision-stage absorption)

| Finding | Routed resolution | Source / lean origin |
|---|---|---|
| **🟡#3 (decide_agents_for_room takes 2 unused params)** | **Drop `room_type` and `room_state` from P1.4 signature.** New signature: `decide_agents_for_room(*, available_agents) -> AgentSelection`. Plan P1.4-6 acceptance updates signature + tests. Docstring: "P1.4: returns all available agents (no filtering). P1.5+: filters by `agent.applies_to.room_types`; signature gains `room_type, room_state` parameters additively." Zero callers in P1.4 outside agents module; additive parameter add in P1.5+ is one signature change + N call-site updates (all within agents/). | DeepSeek finding #3 lean; architect-partner agrees — signature-honesty matters more than future-shape-preservation when there are no callers to migrate. |
| **🟡#4 (regex_registry threading §1 test missing)** | **Add §1 integration test** in `tests/agents/test_integration.py` (or `test_dispatch.py`): load a real agent yaml (skeptic.yaml with regex trigger) via `load_agents`; extract the resulting `regex_registry`; construct an event matching the regex; call `should_agent_speak` with that registry; assert `speak=True` with correct `matched_trigger_index`. Verifies the key shape `(agent_id, trigger_index)` matches between loader-producer and speak-consumer at runtime, not just at type-check time. Plan P1.4-8 or P1.4-9 acceptance adds this test (senior judges placement). | DeepSeek finding #4 lean; architect-partner agrees — classic seam failure mode. |
| **🟡#5 (AgentContext naming misleading)** | **Document deferrals in docstring (NOT rename).** `AgentContext` Pydantic model in P1.4-4 schema grows a docstring listing what's deferred to P1.5+: room state, snapshot excerpt, persona templating, autonomy-aware tool context. Rationale for NOT renaming: rename creates a P1.5+ name-evolution path (`AgentSkillContext` → `AgentContext` once context grows) which is a rename refactor; docstring is a content-only change. Same direction as the "honest framing" treatment of ADR-011 D4 — name what the abstraction is + isn't, don't restructure naming around current scope. | DeepSeek finding #5 lean (b) docstring; architect-partner refinement: rejected rename in favor of docstring per evolution-path concern. |
| **🟡#6 (cooldown lookup depends on exact author format)** | **Add `build_author(agent_id: str) -> str` helper in `core/event.py`.** Single point of format truth. Use in: (a) Event constructor in `event_store.append()` path when dispatch creates the utterance event; (b) `should_agent_speak` cooldown lookup. P1.4-7 acceptance updates the cooldown step to call `build_author(agent.id)` instead of f-string. Cost: ~10 LoC in `core/event.py` (helper + 2 §6 tests: simple case + tests of malformed input rejection). The helper exists as a defense-in-depth; the existing `is_valid_author` regex still applies at Event construction time. **Scope add to P1.4 but small** (~one commit's worth of work bundled into P1.4-4 or as a separate P1.4-4b atomic). | DeepSeek finding #6 lean (helper option); architect-partner chose helper over comment-only (helper eliminates the silent-bypass class entirely; comment-only documents but doesn't prevent). |

## Senior revision actions (derived)

The senior revision session (post-this-routing) executes the following edits, ideally on a fresh branch `claude/P1.4-plan-rev2` OR direct on main (architect-partner direct precedent for review-driven revisions):

### ADR-010 revisions

1. No changes from this routing. (Two earlier routing absorptions already revised D2 cooldown unit + D1 trigger references + D6 regex_registry pick. DeepSeek confirmed all three. The author-format helper (🟡#6) lives in `core/event.py`, not ADR-010 — cooldown step in ADR-010 D2 may add a one-line note "uses `build_author(agent.id)` for format-of-truth lookup; see `core/event.py`".)

### ADR-011 revisions

2. **New D7-b: event-store append failure aborts the turn** (🔴#1). ~100-150 words. Considered Alternatives: silent skip (rejected — event store IS truth); per-turn retry (deferred to P1.5+). Reversibility row added.
3. **D1 return type updated to `TurnResult`** (🔴#2). Signature: `def dispatch_turn(...) -> TurnResult`. References P1.4-4 schema for the type. ~50 words added.
4. **D7 cross-reference to TurnResult.failed_agents** (🔴#2). The "log + skip + continue" semantic populates the failed_agents list; LLM-exception is logged AND recorded in the returned TurnResult.

### Plan revisions

5. **P1.4-4 schema** (🔴#2, 🟡#5, 🟡#6 part-1):
   - Add `TurnResult` Pydantic model (frozen + extra-forbid + Field constraints on `total_asked: int >= 0`).
   - Grow `AgentContext` docstring listing P1.5+ deferrals (room state, snapshot excerpt, persona templating, autonomy-aware tool context).
   - Reference: `core/event.py` will gain `build_author(agent_id)` helper as part of P1.4-4 (~10 LoC + 2 §6 tests added to the existing core/event.py changes for `StateTransitionMeta`). Or split as P1.4-4b atomic — senior judges placement.

6. **P1.4-6 selection** (🟡#3): drop `room_type, room_state` from `decide_agents_for_room` signature; update tests; docstring lists P1.5+ filtering additive expansion.

7. **P1.4-7 should_agent_speak** (🟡#6 part-2): cooldown step uses `build_author(agent.id)` instead of inline f-string.

8. **P1.4-8 dispatch_turn** (🔴#1, 🔴#2, 🟡#4):
   - Signature returns `TurnResult` instead of `list[Event]`.
   - Body: on `event_store.append` failure, raise (do NOT continue to next agent). Cross-reference ADR-011 D7-b.
   - On per-agent LLM failure: continue per existing D7 + record agent.id in `failed_agents` list of TurnResult.
   - Add §1 integration test verifying regex_registry threading (load agent → extract registry → construct event → call should_agent_speak → assert speak=True with correct trigger_index).
   - Tests gain three new cases: TurnResult shape with success-only, with mixed success+fail, with all-fail.

9. **P1.4-9 e2e**: update to reflect TurnResult return type; integration test covers TurnResult fields populated correctly.

10. **P1.4-10 doc updates**: 5-surface scan touches `core/event.py` (build_author + StateTransitionMeta).

### Cross-package + scope impact

- `core/event.py` grows ~10 LoC `build_author` helper + 2 §6 tests beyond the already-planned StateTransitionMeta. P1.4-4 scope grows by ~15 LoC + 4 tests total beyond the previous routing.
- `TurnResult` adds 1 Pydantic model + 1 §6 test.
- `dispatch_turn` signature change is propagated through one §1 integration test + multiple §2/§3 test cases.
- Net plan delta: ~50-80 additional LoC + ~6-8 additional tests; one new ADR sub-decision (D7-b). Well within revision scope; no new atomic task needed unless senior judges P1.4-4b separation is cleaner.

## Status flips that follow

Once the senior revision pass lands (third revision on `claude/P1.4-plan` or direct on main):

- **R0-B-cross-family.md verdict bumps** `needs_architect → clean` per RC-10 codified protocol (4th project use; pattern is now stable). 4 🟡 + 2 🔴 absorbed; verdict_history grows a 4th entry.
- **R0-A-on-plan.md** doesn't need re-verdict (its findings were already absorbed in the prior routing; DeepSeek's new findings are R0-B-only).
- **P1.4 ADR Accepts unblocked** for architect action (gated only on substrate distance test + W-002.5 land per multi-ADR semantic).

## Out of scope for this routing

- Re-litigating the 4 🟢 confirmations (D1 sync, D3 no-priority, D6 separate registry, D7 log+skip+continue) — these stay absorbed per prior routing.
- Re-opening the proxy-R0-B absorbed revisions in `33977db` — DeepSeek explicitly does NOT invalidate them (cross-validation confirmed correctness).
- True cross-family R0-B for other tasks (P1.5+, W-003) — case-by-case based on task shape; this pattern is now established as a precedent.

## Cross-references

- `docs/process/reviews/P1.4/R0-B-cross-family.md` — both proxy and true sections; lean source.
- `docs/process/reviews/P1.4/architect-routing.md` — prior routing (proxy + R0-A); this routing is sibling, NOT superseding.
- `docs/process/senior-plans/P1.4.md` — file the senior revision session edits (third revision pass).
- `docs/decisions/ADR-010-should-agent-speak-contract.md` — minor edits (build_author note); no Decisions changed.
- `docs/decisions/ADR-011-multi-agent-dispatch-sequential.md` — D1 return type + new D7-b for event-store-failure.
- `docs/process/reviews/P1.4/external-r0b-prompt.md` — the prompt that produced the true cross-family review; reference for future P1.5+ tasks where external R0-B is warranted.
- `docs/process/senior-planner.md` § "Self-organization on session start / resume" — the rule auto-routing senior revision session to this artifact.

## Validation note for audit trail

This routing closes audit item #7 ("cross-family R0-B gap exposed in P1.4"). The pattern that emerged:

1. Proxy-lens R0-B (Claude subagent with contrarian prompt) — caught specification-level bugs (cooldown unit, missing schema dependency).
2. Architect routing absorbs proxy findings → senior revision applies them.
3. True cross-family R0-B (DeepSeek V4 Pro, external session) — caught runtime-integration gaps the proxy structurally missed (event_store failure asymmetry, caller-contract for all-fail, signature honesty, integration-test seams, naming-vs-scope, format defense-in-depth).
4. Architect routing absorbs true findings → senior revision applies them.
5. ADR Accepts unblocked.

**Two routing passes on the same task is acceptable** when the lens count (proxy + true cross-family) genuinely doubles coverage. For P1.5+ where the proxy alone is sufficient, single-pass is fine. The cost (one extra revision cycle) is justified by the value (catching 2 🔴 runtime gaps that would have shipped to production).

W-001 retro §6 RC-2 framing was "single-reviewer empirically sufficient for P1.2-shape work." P1.4 shape change exercised the dual-lens pattern; both lenses earned their keep. RC-2 stays accepted for non-shape-change; **new RC-15 candidate: dual-lens R0-B for shape-change is the project standard going forward** — proxy first (catches doc-level errors), true cross-family second (catches integration errors).
