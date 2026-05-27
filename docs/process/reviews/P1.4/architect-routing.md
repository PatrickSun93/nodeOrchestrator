---
task_id: P1.4
kind: architect-routing
date: 2026-05-27
reviews_acked:
  - R0-A-on-plan.md
  - R0-B-cross-family.md
decision: ack_all_leans
---

# P1.4 architect routing — "ack all leans"

**Architect decision (this session):** `ack all leans` — every finding
in both `docs/process/reviews/P1.4/R0-A-on-plan.md` and
`docs/process/reviews/P1.4/R0-B-cross-family.md` resolves to the
review-author's own recommended lean. No item-by-item override; no
deferrals beyond what the reviews themselves recommend.

This file is a **signal artifact for the senior revision session**.
The senior session that picks P1.4 next reads this file alongside
both reviews and applies each finding's routed action without further
architect intervention.

## Reviews acked

- `R0-A-on-plan.md` — 0 🔴 / 5 🟡 / 7 🟢 (verdict: `needs_architect`)
  by architect-partner in-family lens.
- `R0-B-cross-family.md` — 2 🔴 / 5 🟡 / 3 🟢 (verdict: `needs_architect`)
  by Claude-subagent proxy-cross-family lens (see R0-B Caveat).

The two reviews are non-overlapping by design (R0-A explicitly avoided
re-raising R0-B's operational findings; R0-B explicitly raised the
operational ones R0-A would miss). Combined revision scope is 12
findings (2 🔴 + 10 🟡); 10 🟢 are confirmation signal not action.

## Per-finding routing — load-bearing 🔴

| Finding | Routed resolution | Source |
|---|---|---|
| R0-B #1 (cooldown unit mismatch — seconds vs ms) | **(a)** Convert in the ADR-010 D2 text and `should_agent_speak` body: `elapsed_s = (current.timestamp - last.timestamp) / 1000`. The conversion site is named in the ADR so impl cannot silently get it wrong. Yaml unit stays human-readable seconds; event-stream unit stays ms. `cooldown_remaining_s: float` matches. | R0-B #1, explicit lean (a). |
| R0-B #2 (StateChangeTrigger metadata gap) | Land `StateTransitionMeta(new_state: str)` in P1.4-4 schema commit (additive to `core/event.py` `TYPED_METADATA` per ADR-001 EventType-metadata precedent). Reference the schema in ADR-010 D1 StateChangeTrigger description. This preserves "all three trigger types ship in P1.4" (brief Decision 4) by closing the typed-metadata gap that made the third type ship-incomplete. Note: this adds a small `core/` change to P1.4 scope — surfaced as plan §5 revision (new push-back #16). | R0-B #2: pick between (land schema) vs (drop state_change); landing schema preserves brief Decision 4 compliance. |

## Per-finding routing — 🟡 cluster

| Finding | Routed resolution | Source |
|---|---|---|
| R0-A Y1 (AgentMatchRecord.reason dead Literal) | **(b)** Drop `reason` field entirely from `AgentMatchRecord` and `AgentSelectionTrace.considered` in P1.4. Trace retains `agent_id + loaded: bool` only — sufficient diagnostic when no filtering variance exists. P1.5+ adds the field back when `agent.applies_to` filtering surfaces real reason variance. Matches ADR-005 D6 / ADR-009 D6 precedent ("carry enough to explain WHY"); in P1.4 there is no WHY to explain. | R0-A Y1, lean (b). |
| R0-A Y2 (LLM-exception policy hidden) | **(b)** ADR-011 grows a **new Decision 7: per-agent LLM exception policy**. Inscribes "log + skip + continue turn" with rationale (multi-perspective Principle 6; don't lose the rest of the turn on one agent failure), Considered Alternatives (abort-on-first; abort-on-N-failures), and Reversibility row. ~150 words added. Plan P1.4-8 acceptance text loses the half-hidden mention; cross-references ADR-011 D7. | R0-A Y2, lean (b). |
| R0-A Y3 (regex-cache strategy ambiguous) | **(a)** ADR-010 D6 picks **separate loader-level registry** explicitly. Reason: frozen-model semantics are load-bearing for the project's invariant discipline; `model_post_init` with private mutable attribute on a `frozen=True, extra="forbid"` model bypasses the discipline the project enforces elsewhere. Loader maintains `_compiled_patterns: dict[(agent_id, trigger_index), re.Pattern]`; `should_agent_speak` accepts the registry via parameter (threaded through `dispatch_turn`). Adds one parameter to two function signatures; one test fixture. | R0-A Y3, lean (a) with separate-registry pick. |
| R0-A Y4 (R0-B-as-state-machine-gate misleading) | **(a)** Plan §1 line 9 edited to one-sentence clarification: "(architect-process-gated: both ADR Accepts + cross-family R0-B clean per P1.3 retro §6; the state machine does not enforce R0-B — architect holds the Accept until both ADR R0-B revisions are absorbed)". No code change; pure documentation accuracy. | R0-A Y4, lean (a). |
| R0-A Y5 (logger specification missing in P1.4-8) | **(a)** Plan P1.4-8 acceptance amended: "log via `logging.getLogger('orchestrator.agents.dispatch').warning(...)` with `agent_id` + the exception in the message; ... skip ... **no `print` / no stdout**." Honors the P1.3-R0-A-1 precedent (W-002-3 plan acceptance) that established `logging.getLogger(__name__).<level>` as the project convention. | R0-A Y5, lean (a). |
| R0-B #3 (Agent.priority over-engineering) | **Drop `Agent.priority` from P1.4.** Use alphabetical-id ordering only for conflict resolution. When the first real conflict appears in P1.5+ (3+ agents per room), schema migration is one field + one default — cheap. Plan §5 push-back #5 inversion: senior's "migration cost" defense was wrong direction; the architect's read is that Skill.priority precedent argues the OTHER way (added because real ordering needs existed; P1.4's 2-agent sample doesn't have those needs). ADR-011 D3 simplifies: "Conflict resolution: alphabetical by `agent.id` ascending. When P1.5+ surfaces multi-agent ordering needs, `Agent.priority` lands additively." | R0-B #3, explicit lean to drop. |
| R0-B #4 (async dispatch_turn maintainability trap) | Make `dispatch_turn` a regular **`def`** for P1.4 (sync). When P1.5+ adds concurrent dispatch, the function signature changes alongside the implementation; the call site (room runtime, not yet written) updates in the same commit. The "async-shape-now for forward-compat" argument is rejected: project has no `asyncio.run(...)` surface anywhere; introducing one to satisfy a hypothetical P1.5+ upgrade is strictly larger blast radius than re-shaping sync→async when concurrency actually lands. ADR-011 D1 revised: "Sequential dispatch + synchronous interface for P1.4. P1.5+ concurrent upgrade re-shapes the signature alongside the body; no callers exist yet to migrate." | R0-B #4, explicit lean to drop async. |
| R0-B #5 (build_agent_context premature factoring) | **Keep `build_agent_context` but honest in ADR-011 D4.** ADR-011 D4 prose revised to remove the oversold "testable in isolation" + "reusable for future preview UI" arguments; replace with honest "kept for symmetry with the dispatch-vs-context concern separation, even though the P1.4 body is trivial. Honest about being a future-callsite hook, not a current-testability win." Combined with R0-B #6 routing (drop snapshot_excerpt), the function is small but defensible. | R0-B #5, lean: "keep + honest" path explicitly named. |
| R0-B #6 (AgentContext.snapshot_excerpt placeholder) | **Drop `snapshot_excerpt: list[str]` from `AgentContext` entirely in P1.4.** Add back in P1.5+ when there's a concrete consumer driving the shape. Placeholder-but-typed fields in shipped frozen models are anti-pattern; pin or drop, and current scope is drop. Plan P1.4-4 schema and P1.4-6 acceptance both updated. | R0-B #6, explicit lean to drop. |
| R0-B #7 (snapshot-per-turn challenged) | **Defend snapshot-per-turn** with the user-facing-latency-cost note added explicitly to ADR-011 D2 Consequences. R0-B's specific request: "If the answer is still snapshot-per-turn, the ADR should name the user-facing latency cost honestly in Consequences." Add ~50 words to ADR-011 Consequences "Harder" section: "Snapshot-per-turn means agent B's reaction to agent A's utterance is delayed by one turn (user sees A's response → user replies → only NOW B reacts to A). For a 2-agent MVP this latency is real and user-visible; the trade is determinism + turn atomicity (Reversibility table marks this Expensive to reverse for a reason)." Decision unchanged; trade made honest. | R0-B #7, lean: defend with honest cost-statement (vs. switch to live-reads). |

## Senior revision actions (derived)

The senior revision session executes the following edits on `claude/P1.4-plan`:

### ADR-010 revisions

1. **D2 cooldown unit conversion** (R0-B #1): insert `elapsed_s = (current.timestamp - last.timestamp) / 1000` in the mechanics list and the body example. Note the conversion site explicitly. `cooldown_remaining_s: float` semantics unchanged (was already seconds-as-float).
2. **D1 StateChangeTrigger metadata reference** (R0-B #2): reference the new `StateTransitionMeta(new_state: str)` (landing in P1.4-4 schema) in the StateChangeTrigger description.
3. **D6 regex-cache strategy** (R0-A Y3): pick separate loader-level registry explicitly; describe the registry shape and the parameter-threading approach.

### ADR-011 revisions

4. **D1 sync dispatch** (R0-B #4): re-shape Decision 1 — sequential AND synchronous (`def`, not `async def`). Update Considered Alternative A to reflect this. Update P1.5+-additive-path language to "re-shape body + signature together when concurrency lands."
5. **D3 alphabetical-id-only conflict resolution** (R0-B #3): drop `Agent.priority` from the decision; conflict resolution is alphabetical by `agent.id` ascending; `Agent.priority` added additively when P1.5+ multi-agent needs surface.
6. **D4 build_agent_context honest framing** (R0-B #5): rewrite the justification prose; drop "testable in isolation" + "reusable for future preview UI"; replace with honest "kept for symmetry; current body is trivial; honest about future-callsite framing."
7. **D2 Consequences user-facing latency note** (R0-B #7): add the user-visible-latency paragraph to "Harder".
8. **New D7 LLM exception policy** (R0-A Y2): ~150-word new decision inscribing log + skip + continue; with Considered Alternatives (abort-on-first; abort-on-N) and Reversibility row.

### Plan revisions

9. **Schema (P1.4-4)** (R0-B #3, R0-B #6, R0-A Y1): drop `Agent.priority`; drop `AgentContext.snapshot_excerpt`; drop `AgentMatchRecord.reason` Literal (field removed entirely from `AgentMatchRecord` and `AgentSelectionTrace.considered`). Add `StateTransitionMeta(new_state: str)` to core/event.py changes block in P1.4-4 scope.
10. **§1 R0-B-as-process-gate clarification** (R0-A Y4): one-sentence edit to plan §1 line 9 per the routed wording.
11. **P1.4-7 should_agent_speak acceptance** (R0-B #1, R0-A Y3): name cooldown unit conversion site; name separate-registry parameter; update test counts.
12. **P1.4-8 dispatch acceptance** (R0-B #4, R0-A Y5): make `dispatch_turn` a `def` (drop `async`); name logger spec for LLM-exception path; cross-reference ADR-011 D7.
13. **§5 push-back additions** — push-back #15 records the W-002-pre-Accept dependency as architect-acknowledged, push-back #16 records the StateTransitionMeta scope add. Push-back #5 (Agent.priority) updated to reflect the architect's reverse routing; push-back #4 stays as deferred-to-P1.5+. The 10 push-back numbers absorb 2 new items; renumbering acceptable if senior judges cleanest.

### Cross-package + scope impact

- New `StateTransitionMeta` in `core/event.py` extends P1.4-4 scope by ~30 LoC + 2 §6 tests. Senior should note in commit body.
- `dispatch_turn` becoming sync removes async test fixtures; simplifies P1.4-8 test surface.
- Three field drops simplify schema tests (~3 fewer §6 tests).
- New ADR-011 D7 expands ADR-011 by ~150 words; well within 2000-3500 budget.

## Status flips that follow

Once senior revision pass lands on `claude/P1.4-plan` (re-verdict expected `clean` from both R0-A and R0-B revisits):

- Plan + ADR-010 + ADR-011 ready for architect Accept.
- **W-002 sequencing dependency**: ADR Accepts on P1.4 still wait for W-002 to land on main (per P1.4 brief). With the W-002 routing (this session's sibling) absorbed by W-002 senior revision, W-002 should land first.
- Distance test: 24h+ pause per `docs/process/distance-test.md` before each Accept.
- Cross-family R0-B: the proxy-lens R0-B in `claude/P1.4-plan` is acked-as-substitute for P1.4 only. **A true cross-family R0-B remains a separate manual action the architect may take** (per R0-B Caveat); not blocking for ack-all-leans routing, but noted for the W-001 retro / RC-2 evidence trail.

## Out of scope for this routing

- Re-arguing any 🟢 finding from either review (all 10 🟢 are confirmation signal; the plan structure they confirm is not being challenged here).
- New ADR drafts beyond ADR-011 D7 (no ADR-012 in P1.4; summon still deferred to P1.5+ per brief + senior push-back #1).
- Re-litigating senior push-backs #1, #2, #6, #7, #8 (all confirmed substantive by R0-A G2/G7).
- Cross-family R0-B re-dispatch (proxy-lens acked as substitute; true cross-family is separate optional action).

## Cross-references

- `docs/process/reviews/P1.4/R0-A-on-plan.md` — in-family lean source.
- `docs/process/reviews/P1.4/R0-B-cross-family.md` — proxy-cross-family lean source.
- `docs/process/senior-plans/P1.4.md` — file the senior revision session edits.
- `docs/decisions/ADR-010-should-agent-speak-contract.md` — ADR revisions per items 1/2/3 above.
- `docs/decisions/ADR-011-multi-agent-dispatch-sequential.md` — ADR revisions per items 4/5/6/7/8 above.
- `docs/process/senior-planner.md` § "Self-organization on session start / resume" — the rule auto-routing senior revision session to this artifact.
- `docs/process/reviews/W-002/architect-routing.md` — sibling routing this session produced; W-002 lands first per P1.4 brief sequencing.
