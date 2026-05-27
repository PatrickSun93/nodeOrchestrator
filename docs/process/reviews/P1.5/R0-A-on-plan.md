---
task_id: P1.5
round: R0-A-on-plan
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 8
verdict_history:
  - verdict: needs_architect
    at_commit: e74afd1
    findings_count: { red: 0, yellow: 1, green: 7 }
  - verdict: clean
    at_commit: fe3dd82
    findings_count: { red: 0, yellow: 0, green: 8 }
    note: Y1 absorbed per architect routing (Y1 → β; default_factory restored; brief lean honored). 5th project use of frontmatter-as-live-signal pattern.
---

# P1.5 R0-A on plan (architect-dispatched pre-impl review)

> **Verdict bump 2026-05-27 (RC-10 protocol — 5th project use):**
> Senior absorbed architect routing at `fe3dd82` (Y1 → β; cross-family
> R0-B skip per `architect-routing.md` at `c3ab2ec`). Spot-check verified:
>
> - **ADR-012 D3 prose** updated to "`AgentAppliesTo` has a class-level
>   `default_factory` producing `{room_types: ["*"], room_states: ["*"]}`"
>   per Y1 → β routing.
> - **ADR-012 D3 Pydantic snippet** updated:
>   `applies_to: AgentAppliesTo = Field(default_factory=lambda: ...)`.
> - **ADR-012 Reversibility D3 row** updated to reflect default_factory.
> - **Plan P1.5-3 acceptance** drops "required (no default)" language;
>   default_factory is the architectural choice (not alternative).
>   "skeptic.yaml + prober.yaml are NOT updated" explicit.
> - **Plan P1.5-3 backwards-compat** "P1.4 e2e tests continue to work
>   unchanged" — no fixture updates needed.
>
> Y1 reclassified as 🟢 G8 (the absorption itself is the proof; brief
> lean restored; senior over-discipline reversed). Verdict bumps
> `needs_architect → clean` (0🔴 / 0🟡 / 8🟢; 7 prior 🟢 + 1 new 🟢 from
> Y1 absorption).
>
> Cross-family R0-B skip honored — no proxy, no true external dispatch.
> Plan §5 push-back #8 / closer updated per routing artifact.
>
> **Fifth project use of the frontmatter-as-live-signal pattern** (RC-10):
> 1. W-001-impl R0-A (`96c1469`) — post-fix bump
> 2. W-002 R0-A-on-plan (`440ab3b`) — post-revision bump
> 3. P1.4 R0-A + R0-B proxy (`047daa4`) — dual-review bump
> 4. P1.4 R0-B DeepSeek (`e8a1ee8`) — dual-routing-on-same-file bump
> 5. **This bump (commit pending)** — single-routing absorption bump
>
> Pattern is stable across 5 uses; codification target remains
> `docs/process/reviews/README.md` "Post-resolution verdict-bump
> protocol" section. Defer to W-003 brief authorship.

| Field | Value |
|---|---|
| Round | R0-A-on-plan (architect-dispatched per RC-9; 5th instance after W-001-impl + P1.3 + P1.4 + W-002) |
| Reviewer | architect-partner (Claude Opus 4.7, 1M context) in primary session |
| Date | 2026-05-27 |
| Artifacts reviewed | `docs/process/architect-briefs/P1.5.md`; `docs/process/senior-plans/P1.5.md` (commit `9004f26`); `docs/decisions/ADR-012-room-state-machine.md` (`9004f26`). Cross-referenced: ADR-009 D3 (`["*"]` sentinel precedent), ADR-010/011 (P1.4 contracts being extended), ADR-008 (`next_state` conceptual ancestor), W-002.5 plan + brief (multi-ADR aggregation; senior-plans frontmatter convention). |

---

## Lens

P1.5 introduces the third code-driven decision-function module (after `autonomy/gate` + `skills/decide_skills_for_context + agents/should_agent_speak`). Plan is comprehensive — 8 atomic tasks, ADR-012 drafted with 7 decisions + 6 considered alternatives + reversibility table, all 7 brief architect-settled decisions honored, all 4 predicted self-discoveries surfaced.

R0-A-distinct lens (vs senior plan-vs-impl which lands later): brief-compliance audit, push-back disposition substance, ADR-012 structural quality, decision-trace preservation, parallelism rule first-use verification, audit-#6 scope-cut discipline.

---

## Findings

### 🟡 Y1 — `Agent.applies_to` shape: required-no-default vs additive-with-default (brief lean diverged silently)

**Where:** plan P1.5-3 acceptance lines 84-86, 95-103 + ADR-012 D3 (lines 110-140 of the ADR).

**What:** Brief §"Constraints" lean read:

> **`Agent.applies_to` is additive**: existing skeptic.yaml + prober.yaml get default `{room_types: ["*"], room_states: ["*"]}`; they continue to load without yaml changes.

Plan P1.5-3 acceptance instead specifies:

> `Agent.applies_to: AgentAppliesTo` is a **required** field (no default) — every agent yaml must declare it explicitly. skeptic.yaml + prober.yaml updated.

Then defers further at the e2e-test-fixture layer:

> "If P1.4 e2e tests construct Agent objects without applies_to, they need updates — junior surfaces and either updates the fixtures (with `["*"]` defaults) OR adds a backwards-compat `default_factory` for `applies_to` (senior judgement at impl-time; lean: explicit updates because 'required no default' is the architectural choice)."

**Two divergences from the brief lean:**
1. Senior chose `required` (stricter discipline) over brief's `default` (migration-friendly).
2. The required-vs-default decision is then **deferred to junior** for the e2e-test-fixture case, with a "lean explicit" + "alternative default_factory" — putting an architecturally-relevant question on junior's plate at impl-time.

**Both shapes are defensible:**

- **(a) Required, no default** (senior's lean): forces every agent author to think about `applies_to` explicitly; matches the project's frozen+extra-forbid+min_length-discipline pattern; no hidden defaults. Cost: 2 yaml updates + N test-fixture updates (small surface in P1.5; grows with each future yaml).
- **(b) Default `{room_types: ["*"], room_states: ["*"]}`** (brief's lean): existing yamls + test fixtures continue to work; "agent doesn't care which room" is the safe default. Cost: hides the choice; future agent authors may rely on default without realizing they should be explicit (the operator agent in P1.5.5 absolutely needs explicit `applies_to` — would the default silently work-but-wrong if junior forgets?).

**My architectural-partner read leans (a)** — the project's overall discipline (closed enums, no Any, no hidden defaults, frozen+extra-forbid) trends toward "required + explicit." The brief's "additive" lean was a migration-cost concession that's small enough to absorb. Senior identified the same direction. **But:** the deferred-to-junior framing at impl-time is wrong; the architectural choice should be settled in the plan, not the impl.

**Options for resolution:**

- **(α)** Architect routes (a) — required no default; plan P1.5-3 acceptance loses the "OR backwards-compat default_factory" alternative; junior just updates fixtures + yamls.
- **(β)** Architect routes (b) — additive with default per brief; plan P1.5-3 reverses; skeptic + prober yamls don't change; test fixtures unchanged.
- **(γ)** Architect routes (a) but adds an ADR-012 D3 clarification noting the "no defaults" choice; senior's deferral text in P1.5-3 acceptance is removed.

**My lean: (γ)** — match senior's (a) direction, formalize it in ADR-012 D3 prose, remove the deferral. The architectural choice (required vs default) belongs in the ADR; the impl follows it without further senior judgment.

**Severity 🟡** — not a runtime bug; both shapes work; but the silent divergence from brief + deferral-to-junior is the kind of architectural ambiguity R0-A-on-plan exists to surface.

### 🟢 G1 — All 7 brief architect-settled decisions honored

| Brief decision | Honored in |
|---|---|
| 1. Room state machine code-driven, event-triggered | ADR-012 D1 ✓ |
| 2. State machine integrates via separate `RoomRuntime` post-loop | ADR-012 D5 (lean accepted) ✓ |
| 3. `agent.applies_to` shape with `["*"]` sentinel | ADR-012 D3 ✓ (with Y1 caveat on required vs default above) |
| 4. 5 RoomTypes: Research full + 4 scaffolded | ADR-012 D2 + plan P1.5-6 ✓ |
| 5. ADR-012 new (senior call; lean YES) | drafted; 459 lines ✓ |
| 6. Workflow integration via `adr: ADR-012` frontmatter (W-002-1 path β) | plan §1 + frontmatter declares it ✓ |
| 7. Cross-package layering: 4 new constitutional tests | ADR-012 D7 + plan P1.5-3 ✓ |

### 🟢 G2 — All 7 brief push-backs disposed substantively + 4 predicted self-discoveries surfaced

Plan §5 enumerates 8 items (7 push-backs + meta-block for self-discoveries):

- Push-back #1 ADR-012 yes — defended (3 reasons: third pattern + perpetual reference + ADR-005/008/010/011 precedent)
- Push-back #2 Research room states — accepted lean defensibly (6 states; cycles allowed)
- Push-back #3 `AgentAppliesTo` sentinel shape — accepted; codify-ready note added
- Push-back #4 integration site — separate `RoomRuntime` chosen with rationale
- Push-back #5 5 RoomTypes scoping — Research+4-scaffolds; matches P1.3 pattern; audit #6 cited
- Push-back #6 `room_states` validation loose — defended (cross-RoomType validation = layering inversion)
- Push-back #7 two-layer filtering — defended (load-time/dispatch-time pattern parallel to skills+triggers)
- Self-discovery cluster: prior_state extension + N=50 recency window + cycles-allowed + empty-room-silent all surfaced and addressed

**Substantive defense per push-back; no silent ignores.** Push-back #1 + #5 explicitly cite project precedents and audit-item history. Senior reflection-on-design at multiple points (e.g., push-back #3 codify-ready note).

### 🟢 G3 — ADR-012 structural quality on par with ADR-009/010/011 gold standard

| Section | Present? |
|---|---|
| Status header with revision tracking | ✓ Proposed — 2026-05-27 |
| Scope (in + out) | ✓ explicit out-of-scope: snapshot mechanics, decision log, operator + autonomy, content polish |
| Context with hard requirements | ✓ 5 numbered hard requirements |
| Decisions | ✓ 7 enumerated decisions with rationale + code snippets |
| Considered alternatives | ✓ 6 alternatives (A: LLM-driven; B: shared state set; C: inline; D: cross-RoomType validation; E: one-layer; F: no state_transition events) |
| Consequences (Easier/Harder/Neutral) | ✓ all three sections populated |
| Reversibility table | ✓ all 7 decisions with 6-month reversal cost |
| References | ✓ handoff sections + 5 prior ADRs + brief + plan + impl entry points |

Cross-reference completeness: ADR-012 references ADR-001 (event store + closed enums), ADR-008 (workflow state machine — `next_state` conceptual ancestor), ADR-009 (`["*"]` sentinel + skill applies_to), ADR-010 + ADR-011 (P1.4 contracts). **Same shape as ADR-009 (gold standard from P1.3)**; no structural gaps.

### 🟢 G4 — Decision-trace pattern preserved + extended

`RoomStateTransition` Pydantic model (plan P1.5-4 acceptance):
- `prior_state: str`, `new_state: str` (the arc)
- `triggering_event_type: EventType` (which event class fired)
- `rule_matched: str` (rule identifier, e.g., `"hypothesis_density_triggers_divergence"`)

`AgentSelection.trace.considered` extended in P1.5-5 with `applies_to_match: bool` + reintroduced `reason` field (P1.4-4 R0-A Y1 dropped reason because there was no variance to record — P1.5 has variance again).

Pattern matches ADR-005 D6 / ADR-009 D6 / ADR-010 D3 precedent — trace lives inline with decision. Diagnostic surface for "why didn't this room transition?" + "why didn't this agent load?" both populated.

### 🟢 G5 — Parallelism rule first formal use (P1.5-4 ‖ -5 ‖ -6)

Senior applies the new `senior-planner.md` "Plan task parallelism" rule (added in `2868d83`; this is the first plan to formally use it):

```
P1.5-3 (sequential — gates the parallel set)
       ↓
[P1.5-4 ‖ P1.5-5 ‖ P1.5-6]  (3 parallel agents)
       ↓
P1.5-7 (sequential — consumes 4+5+6)
       ↓
P1.5-8 (landing)
```

File-disjointness verified:
- P1.5-4: `src/orchestrator/rooms/state_machine.py` + `tests/rooms/test_state_machine.py`
- P1.5-5: `src/orchestrator/agents/selection.py` + `tests/agents/test_selection.py`
- P1.5-6: `src/orchestrator/rooms/templates.py` + `tests/rooms/test_templates.py`

`src/orchestrator/rooms/__init__.py` stays empty per P1.5-3 acceptance (no re-exports to conflict on); `tests/rooms/__init__.py` also empty. Parallelism is safe.

**First-instance dogfood of the parallelism rule.** Worth a project-retro note: if it works cleanly, the pattern is reusable for future plans with similarly-disjoint-task structure.

### 🟢 G6 — Audit #6 scope-cut discipline maintained

Plan §1 explicitly addresses audit-item #6 (P1.4-P1.5 boundary drift): "Scope is deliberately cut to 'Research room as architectural exemplar.' Operator agent + autonomy-aware tool dispatch defer to P1.5.5 (biggest deferred P1.4 item). divergence_mapper + logger yamls defer to P1.5.5 unless trivial-to-include. The 4 non-Research RoomTypes get scaffold-only state machines (`{setup, closed}`); the content polish lands as P2 work."

Deferred items cleanly traced to follow-up brief candidates:
- P1.5.5: operator + autonomy-aware tools; divergence_mapper + logger yamls
- P1.6: snapshot mechanics, decision log, e2e persistence (per handoff §7)
- W-003: RC-16, verify-workspace divergence, junior-session CLI capability, multi-ADR granularity, RC-10 codification
- Later content tasks: skeptic content tuning, other 4 RoomType content

**No scope creep.** Plan stays in its lane.

### 🟢 G7 — W-002.5 single-ADR path β dogfooded by plan frontmatter

Plan declares `adr: ADR-012` in frontmatter — first single-ADR task post-W-002.5's union extension. Tests the single-ADR path still works after the `str | list[str]` discriminator landed. Plan §1 calls this out explicitly: "First single-ADR task post-W-002.5 — proves the single-ADR path still works after the union extension."

Quiet dogfood evidence accumulating: W-002.5 plan dogfooded W-002-2b no-ADR routing; P1.5 plan dogfoods W-002-1 single-ADR-string discrimination post-W-002.5. The harness gets stress-tested by every real task.

---

## Cross-checks

- [x] Frontmatter contract followed; `adr: ADR-012` declared.
- [x] All 7 brief architect-settled decisions honored (G1).
- [x] All 7 brief push-backs disposed substantively (G2).
- [x] All 4 predicted self-discoveries surfaced (within plan §5 + ADR-012 D6 + plan P1.5-4 acceptance).
- [x] ADR-012 structural quality matches ADR-009/010/011 gold standard (G3).
- [x] Decision-trace pattern preserved (`RoomStateTransition` + `AgentSelection.trace`) (G4).
- [x] Parallelism rule first formal use verified disjoint (G5).
- [x] Audit #6 scope-cut discipline maintained (G6).
- [x] W-002.5 single-ADR path β dogfooded (G7).
- [x] Constitutional test naming convention consistent (`no_llm_calls_in_rooms_module` + 3 layering tests; matches W-001-impl + P1.3 + P1.4 5-module pattern).
- [x] Cross-references symmetric in ADR-012.
- [x] No new `LLMPurpose` values; `LLMPurpose.AGENT_RESPONSE` reused via `dispatch_turn` per P1.4.
- [ ] **`Agent.applies_to` required vs default** — Y1 above; brief lean diverged silently; architect should explicitly route.

---

## Push-back disposition table (architect-decision view)

| # | Brief push-back | Plan disposition (§5) | Substantive? | My read |
|---|---|---|---|---|
| 1 | ADR-012 yes/no | #1: yes | yes (3 defenses) | ✓ correct; matches architect-partner lean |
| 2 | Research room state set | #2: accept 6-state lean | yes (defensible against handoff §5.2 narrative) | ✓ |
| 3 | `AgentAppliesTo` `["*"]` sentinel shape | #3: accept; codify-ready note | yes (third use of pattern) | ✓ but see Y1 above on required-vs-default sub-question |
| 4 | State-machine integration site | #4: separate `RoomRuntime` | yes (decoupling rationale) | ✓ |
| 5 | 5 RoomTypes scoping | #5: Research + 4 scaffold | yes (audit #6 + P1.3 precedent) | ✓ |
| 6 | `room_states` validation strictness | #6: loose | yes (cross-RoomType validation = layering inversion) | ✓ |
| 7 | Two-layer filtering | #7: load-time/dispatch-time split | yes (precedent parallel to skills+triggers) | ✓ |
| 8 | Cross-family R0-B for P1.5 | mentioned in plan §5 closer: lean dispatch | partial (architect-pickable) | architect explicitly decides — see "Cross-family R0-B" section below |

**Verdict on push-back coverage:** 7/7 substantive + 1 architect-routable (cross-family R0-B).

---

## Net assessment

**Verdict: needs_architect.** One 🟡 (Y1 — required vs default for `Agent.applies_to`) + seven 🟢 confirmations.

The plan is structurally sound: ADR-012 quality on par with prior gold-standard ADRs; brief leans largely honored with substantive defense; decision-trace pattern preserved; parallelism rule first formal use is safely disjoint; audit-#6 scope-cut discipline holds. The one 🟡 is a routing decision the architect should make explicitly rather than letting the senior defer to junior at impl time.

**Architect routing needed on Y1**: required vs default for `Agent.applies_to`. Three options (α / β / γ); my lean (γ): match senior's (a) direction, formalize in ADR-012 D3, remove the impl-time deferral. ~5 line ADR edit + 1 line plan-acceptance simplification.

**Cross-family R0-B for P1.5** (per plan §5 closer): architect should decide explicitly. RC-15 (dual-lens R0-B for shape-change) codified for shape-change tasks. P1.5 is third pattern instance (state machine; not concurrency; lower stakes than P1.4). Two options:
- (i) **Dispatch proxy + true cross-family** like P1.4 — costs ~$2 + 30-40 min external + one extra revision-pass cycle; surfaces blind-spots the proxy alone can't see. Right call if P1.5.5 will reference this contract heavily (likely — operator + autonomy-aware tools all consume the room state machine).
- (ii) **Proxy only** (skip true external) — relies on RC-15 graduation being narrowly scoped to "highest-stakes shape change"; P1.5 is shape change but smaller-stakes than P1.4.
- (iii) **Skip both R0-B passes** — R0-A alone covers; RC-15 narrowly applied. Architect-decision-gated per RC-9.

**My lean: (i)** — given that P1.5.5 + future RoomTypes will reference this contract, the dual-lens investment is worth it once. Same logic as P1.4. If RC-15 graduates to "proxy only is sufficient" after P1.5.5, that's a follow-up codification.

**Plan + ADR-012 are revisable to clean in one revision pass** absorbing Y1 routing + optional cross-family R0-B findings. No return-to-senior-for-redraft warranted.

## Captured for P1.5 retro

- **First parallelism-rule use** — track whether parallel set runs cleanly (no merge conflicts, no shared-state surprises).
- **W-002.5 single-ADR path β dogfood** — single-ADR plan post-multi-ADR-union landing.
- **First task to address audit #6 explicitly** — scope-cut discipline emerges as a project pattern.
- **Required vs default `applies_to`** (Y1 resolution path becomes precedent) — captured for the "agent yaml convention" cluster of decisions.
- **ADR-012's "rule_matched: str" not a closed Literal** — kept free-string for P1.5 (small surface; one RoomType fully impl'd); may want to type-narrow per RoomType when transition count grows (P2 content-polish).
