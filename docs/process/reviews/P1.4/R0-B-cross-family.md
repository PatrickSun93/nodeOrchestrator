---
task_id: P1.4
round: R0-B-cross-family
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 10
verdict_history:
  - verdict: needs_architect
    at_commit: 466e98d
    findings_count: { red: 2, yellow: 5, green: 3 }
  - verdict: clean
    at_commit: 33977db
    findings_count: { red: 0, yellow: 0, green: 10 }
    note: All 2 🔴 + 5 🟡 absorbed into senior revision per architect-routing ack-all-leans (7 findings → 7 new 🟢).
---

# P1.4 R0-B cross-family review (proxy lens — see Caveat below)

> **Verdict bump 2026-05-27 (W-001-impl RC-10 precedent — frontmatter as live signal):**
> Original verdict `needs_architect` reflected 2 🔴 (load-bearing ship-
> bugs) + 5 🟡 (scope-discipline cluster). Architect acked-all-leans
> (`docs/process/reviews/P1.4/architect-routing.md`, commit `2b92e34`).
> Senior revised ADR-010 + ADR-011 + plan (commit `33977db`) absorbing
> all seven findings:
>
> - **🔴#1 (cooldown unit ms vs s)** → lean (a): ADR-010 D2 inscribes
>   `elapsed_s = (current.timestamp - last.timestamp) / 1000.0`
>   conversion site explicitly. Yaml stays seconds; event-stream stays
>   ms; `cooldown_remaining_s: float` semantics matched. P1.4-7
>   acceptance gets the regression test for the bug
>   (`cooldown_seconds=60` with 30_000ms-ago utterance blocks; with
>   90_000ms-ago doesn't).
> - **🔴#2 (StateChangeTrigger metadata gap)** → land schema in P1.4:
>   `StateTransitionMeta(new_state: str)` added to `core/event.py`
>   `TYPED_METADATA` (P1.4-4 scope grew ~30 LoC + 2 §6 tests). ADR-010
>   D1 references the typed schema. StateChangeTrigger evaluation
>   reads `current_event.metadata.new_state` (typed field access).
>   Preserves all-three-trigger-types-ship per brief Decision 4.
> - **🟡#3 (Agent.priority over-engineering)** → drop. ADR-011 D3
>   revised: conflict resolution is alphabetical-id ascending only.
>   `Agent.priority` lands additively in P1.5+ when real conflict
>   surfaces.
> - **🟡#4 (async dispatch_turn maintainability trap)** → drop async.
>   ADR-011 D1 revised: `def dispatch_turn(...)` sync. P1.5+
>   concurrent upgrade re-shapes both signature and body in one
>   commit (zero callers in P1.4 to migrate).
> - **🟡#5 (build_agent_context premature factoring)** → keep +
>   honest. ADR-011 D4 rewritten: drops oversold "testable in
>   isolation" + "reusable for future preview UI"; honest about
>   future-callsite hook framing. Combined with 🟡#6 drop of
>   `snapshot_excerpt`, the function is small but defensible.
> - **🟡#6 (AgentContext.snapshot_excerpt placeholder)** → drop. Field
>   removed from `AgentContext` in P1.4 schema. P1.5+ adds back when
>   a concrete consumer drives the shape.
> - **🟡#7 (snapshot-per-turn challenged)** → defend with honest
>   latency cost. ADR-011 D2 Consequences "Harder" section gained the
>   user-facing-latency paragraph (cross-agent reaction delayed by
>   one turn; trade-off named).
>
> Sibling review R0-A-on-plan also bumped in companion commit. All 7
> non-green findings reclassified as 🟢 (post-bump count: 0 🔴 / 0 🟡 /
> 10 🟢; 3 original 🟢 + 7 new 🟢 from absorption). Original finding
> bodies preserved below for audit; original verdict preserved in git
> history at commit `466e98d`.
>
> Third project use of the frontmatter-as-live-signal pattern. P1.3
> retro §4 RC-10 graduates after this instance (see sibling R0-A-on-
> plan verdict bump for details). **First R0-B-cross-family use of
> the pattern** (W-001-impl + W-002 + P1.4 R0-A-on-plan covered
> in-family lens; this is the first cross-family-lens bump).
>
> Caveat from original review unchanged: this review was produced by
> a Claude subagent with deliberately outside-Claude lens, not a true
> non-Claude model. The 🔴 findings (cooldown unit; StateChangeTrigger
> metadata gap) were correctly load-bearing despite the proxy-lens
> limitation; the verdict bump confirms the architect routing
> resolved both. A true cross-family R0-B remains a separate optional
> action the architect may take.



**Reviewer:** Claude subagent prompted with deliberately outside-Claude lens
(see Caveat). Not a true cross-family review.
**Date:** 2026-05-26
**Artifacts reviewed:**
- `docs/process/architect-briefs/P1.4.md`
- `docs/process/senior-plans/P1.4.md`
- `docs/decisions/ADR-010-should-agent-speak-contract.md`
- `docs/decisions/ADR-011-multi-agent-dispatch-sequential.md`
- `src/orchestrator/core/event.py`, `core/event_store.py`
- `src/orchestrator/llm/types.py`, `llm/router.py`, `llm/purposes.py`
- `src/orchestrator/skills/decision.py`, `skills/schema.py`
- `docs/process/reviews/README.md` (frontmatter contract)

---

## Caveat

The harness's R0-B convention is to dispatch a model from a different LLM
family (GPT / Gemini / DeepSeek) so it surfaces blind-spots same-family
review cannot see. **This review was produced by a Claude subagent** with a
prompt explicitly instructing me to over-correct for known Claude biases
(over-engineering, premature abstraction, missing simpler alternatives,
under-weighting runtime / operational concerns, agreeableness, over-
specification). It is the best approximation available inside the current
managed remote container; a true cross-family review remains a separate
manual action the architect may take. **Treat the findings as adversarial
self-review by Claude with a contrarian prompt, not as independent non-
Claude signal.** In particular: my coverage of operational/runtime failure
modes is the area I most likely under-call, because that bias is the
hardest for a same-family review to neutralize through instruction alone.

---

## Findings

| # | Severity | File:line | What's wrong | What should be |
|---|----------|-----------|--------------|----------------|
| 1 | 🔴 | ADR-010 §Decisions/2 (lines 110-126); plan P1.4-7 acceptance (line 249) | **Unit mismatch: cooldown in seconds vs event timestamps in milliseconds.** `core/event.py:30-35` defines `TimestampMs = NewType("TimestampMs", int)` populated by `now_ms()` (`int(time.time() * 1000)`). ADR-010 D2 writes `elapsed = current_event.timestamp - last_utterance.timestamp` and compares to `agent.cooldown_seconds`. With current code, a `cooldown_seconds=60` agent would actually be blocked for 60ms. The plan and ADR are silent about the unit conversion. `cooldown_remaining_s: float` in SpeechDecision also implies seconds-as-float, but the source is integer ms. | Either (a) explicitly convert in the ADR text and `should_agent_speak` body (`elapsed_s = (current.timestamp - last.timestamp) / 1000`), with the conversion site named; or (b) rename `Agent.cooldown_seconds` → `cooldown_ms` to match the event-stream unit. I'd prefer (a) because seconds is the human-readable yaml unit, but the conversion site must be inscribed in the ADR so the impl can't silently get it wrong. The current plan would compile clean (both ints) and ship a 1000× bug. |
| 2 | 🔴 | ADR-010 §Decisions/1 (lines 97-100); plan P1.4-7 (line 252) | **`StateChangeTrigger` depends on metadata that does not exist in the project's event vocabulary.** `StateChangeTrigger.target_state` is matched against `current_event.metadata["new_state"]`. `core/event.py` defines `STATE_TRANSITION` enum value but `TYPED_METADATA` (lines 259-267) has no entry for it — no `StateTransitionMeta` class exists. The plan notes this as "self-discovery 13: surface during P1.4-7 implementation; potential one-line metadata schema addition (no new EventType)". This is hand-waved away as a junior-time discovery, but it is **load-bearing for the closed enum the ADR is committing the project to**. If `new_state` isn't a typed field, then either (a) the ADR is committing to an untyped-dict contract for the central trigger evaluation path, or (b) a `StateTransitionMeta` ADR-001-style schema change needs to land in P1.4, not P1.5. | Resolve before architect Accept on ADR-010: either land `StateTransitionMeta(new_state: str)` in P1.4-4 schema commit (and reference it in ADR-010), or drop `state_change` from P1.4's trigger types (defer with summon to P1.5+). The current plan straddles: the ADR says all three trigger types ship, the plan defers schema validation of the metadata field they depend on. That straddle is the bug — pick one. |
| 3 | 🟡 | ADR-011 §Decisions/3 (lines 144-163); schema in plan (line 142) | **`Agent.priority` is unearned over-engineering for P1.4 scope.** Per ADR-011 D3's own admission ("essential once 3+ agents are loaded per room (P1.5+)") and Consequences ("MVP-overengineering for 2 agents"). The plan ships skeptic + prober (2 agents), and Skeptic explicitly never collides with Prober in the sample (different triggers). The justification is "migration cost of adding later is higher" — but that argument generalizes to "always add every field you might ever need", which is the bias I was asked to challenge. The actual migration cost is: one int default in yaml + one Pydantic field. That's not high. The cost of including it now is: every test thinks about priority, every reviewer has to defend why the default is 50 and the range is 0-100 (why not 0-9? Why not a simple `before/after/normal` enum?), and the field is a precedent that locks future agents into thinking about priority before they've encountered a real conflict. | Drop `Agent.priority` from P1.4. Use alphabetical-id ordering only (ADR-011 D3's tiebreaker). When the first real conflict appears in P1.5+, the schema migration is one field + one default. The skill priority precedent (ADR-009 D6) actually argues the other way: `Skill.priority` was added because real ordering needs exist in the current skill set. P1.4's 2-agent sample doesn't have those needs. |
| 4 | 🟡 | ADR-011 §Decisions/1 (lines 70-108); plan P1.4-8 (line 261) | **`async def dispatch_turn` with body that never awaits concurrently is a maintainability trap, not just a stylistic question.** The ADR Consequences (line 350-353) names this honestly ("'why is this async if it doesn't await anything concurrent' is a real question newcomers ask"), but proceeds anyway. Operational concern under-weighted: `async` color (PEP 492) propagates upward — every caller of `dispatch_turn` now must be async, every test fixture, every CLI entry. The project does not currently have an `asyncio.run(...)` surface anywhere (verify: nothing in `src/orchestrator/workflow/` or `src/orchestrator/core/` is async). Introducing one to satisfy a hypothetical P1.5+ upgrade is a strictly larger blast radius than re-shaping the function from sync→async in P1.5+ when concurrent dispatch actually lands. Sync-to-async refactor IS painful in general, but the dispatch primitive has exactly one caller (the room runtime, not yet written), so the blast radius is small. | Make `dispatch_turn` a regular `def` for P1.4. When P1.5+ adds concurrent dispatch, the function signature changes — and the call site (which doesn't exist yet) is updated in the same commit. The async-shape-now argument is "interface forward-compat for free"; the cost is dragging an async runtime into the project before it's needed. Sequential dispatch in sync code is genuinely simpler. If the architect prefers async-shape-now, the ADR should name the concrete caller surface that justifies it (room runtime API design — which is P1.5+ scope and therefore unknown). |
| 5 | 🟡 | ADR-011 §Decisions/4 (lines 165-208); plan P1.4-6 (lines 224-239) | **`build_agent_context` separation may be premature factoring — the testability argument is partially tautological.** ADR-011 D4's justification: "Testable in isolation — 'given this agent and this room state, what skills enter context?' is a pure-function unit test, no dispatch mocking required." But the answer to that question is already trivially answered by calling `decide_skills_for_context(agent.id, room_type, room_state, available_skills=…)` directly — which is itself a pure function tested in P1.3. `build_agent_context` adds: skill_bodies extraction (one list comprehension) + snapshot_excerpt (deferred to []) + an `AgentContext` Pydantic model. The "single-concern" argument is real, but the function is currently doing one trivial thing (`[s.body for s in selected]`). The "reusable for a future preview UI (P2-ish)" is the kind of speculative-future-callsite justification I was asked to discount. | Either inline `decide_skills_for_context` + skill body extraction into `dispatch_turn`, OR keep `build_agent_context` but be honest in the ADR that it exists for symmetry and future-callsite rather than current testability. The current ADR oversells. If you keep it, drop `snapshot_excerpt: list[str]` (it's `[]` in P1.4 anyway — placeholder fields in shipped schemas are a smell — see finding #6). |
| 6 | 🟡 | plan P1.4-4 schema (line 184); P1.4-6 acceptance (line 235) | **`AgentContext.snapshot_excerpt: list[str]` ships as `[]` placeholder.** Placeholder-but-typed fields in shipped frozen Pydantic models are a worse pattern than not having the field. They invite "what is this supposed to be?" questions in every code review, they force tests to assert against `[]` (which doesn't test anything meaningful), and once the field has a real consumer in P1.5+, the producer changes shape in ways that may not match what the empty-list shipping committed to. | Drop `snapshot_excerpt` from P1.4's `AgentContext` entirely. Add it in P1.5+ when there's a concrete consumer driving the shape. The plan acknowledges the "impl detail (P1.4-6 pins)" caveat at line 185; that's not enough — pin or drop. |
| 7 | 🟡 | brief Architect-settled decision 3 Boundary (c); ADR-011 §Decisions/2 (lines 111-141) | **The brief itself may be wrong about per-turn snapshot semantics being the right default.** This finding challenges the brief, not the plan (per dispatch-prompt §F). The "agent A speaks → agent B sees it next turn" rule is presented as the obviously correct atomicity model. But under sequential dispatch in a 2-agent room where prober speaks first and triggers a hypothesis, skeptic's reaction to that hypothesis is delayed by one full turn — i.e., one event-stream cycle which may be user-visible (user sends message → prober responds → user sees prober's response → user sends another message → only NOW skeptic reacts to prober's hypothesis). For an MVP with 2 agents, "B sees A's utterance immediately within the same turn" might be the more intuitive user experience, and it doesn't break determinism under sequential dispatch (the order is still priority-then-id; the only change is that B's `should_agent_speak` is computed against a snapshot that includes A's just-appended utterance). The brief presents this as load-bearing for ADR-011's atomicity story, but under sequential dispatch the alternative is also deterministic. | Architect should explicitly revisit Boundary (c) before Accept. The "turn-as-atomic-unit" framing is defensible but is not the only defensible choice. The cost of getting this wrong is high (Reversibility table calls it "Expensive — switching to live reads breaks turn atomicity, breaks every multi-agent test, breaks cooldown determinism"). Pick deliberately, not by inheritance from the brief. If the answer is still snapshot-per-turn, the ADR should name the user-facing latency cost honestly in Consequences. |
| 8 | 🟢 | ADR-011 §Decisions/1 (lines 86-95); §Considered Alternative A | **Sequential vs concurrent argument is sound; this is a 🟢 because the plan chose the right thing for the right reasons.** The "smaller test surface + no project precedent for concurrency + Run > polish" framing matches the project's stated values. Recording as 🟢 to acknowledge the decision and counter-balance findings #3/#4/#5 which all push the other direction. |
| 9 | 🟢 | plan §5 push-back #4 (line 366) | **Deferring `agent.applies_to.room_types` to P1.5+ is the right cut.** Symmetry with Skill.applies_to is tempting but not earned — `decide_agents_for_room` returning every agent in P1.4 is the simpler shape, and the function exists as the future hook. This is the kind of cut Claude-on-Claude would over-rationalize keeping; the plan got it right. |
| 10 | 🟢 | ADR-010 §Considered Alternative D (lines 262-269); ADR-011 §Considered Alternative D (lines 290-300) | **Both ADRs correctly reject pre-extending the event vocabulary on speculation** (turn-boundary events, full-trace per-trigger fields). These rejections preserve closed-enum discipline and don't ship trace bloat. |

---

## Cross-checks

- [x] Both ADR drafts present, status `Proposed`, dates correct.
- [x] Frontmatter contract on this file followed.
- [x] Plan §3 execution order coherent (P1.4-1..10 sequential dependencies resolve).
- [ ] **Cooldown unit consistency** — fails (finding #1).
- [ ] **StateChangeTrigger schema dependency** — unresolved at ADR-010 Accept time (finding #2).
- [x] No new LLMPurpose values added (uses existing `AGENT_RESPONSE`).
- [x] Three new constitutional tests align with W-001-impl precedent.

---

## Net assessment

**Recommendation: revise before Accept on ADR-010; revise or accept-with-
recorded-revisions on ADR-011.**

The two 🔴 findings (cooldown unit mismatch, StateChangeTrigger metadata
gap) are concrete bugs in the design, not stylistic preferences. Both
become production bugs in P1.4-7's impl if shipped as drafted — the
cooldown one is silent (60-second cooldowns work as 60ms cooldowns; tests
that don't sleep won't catch it), the state-change one is loud (KeyError
on metadata lookup at first dispatch). The cooldown bug in particular is
the kind of finding that justifies the R0-B existence: same-family review
tends to read "elapsed = current.timestamp - last.timestamp" as obviously
correct because the variable names match; outside-Claude lens forces the
question "what unit is timestamp actually in?", and the answer in this
codebase is milliseconds.

The five 🟡 findings cluster around over-engineering for unrealized future
needs (`Agent.priority`, async-shaped sync function, `build_agent_context`
separation, `snapshot_excerpt` placeholder field, snapshot-per-turn as
inherited-not-defended default). None of them are individually blocking,
but together they describe a plan that is at the upper end of what P1.4
scope warrants. The brief explicitly invited push-back on scope; the plan
absorbs the architect-partner-named push-backs but doesn't volunteer
additional cuts. A 30%-simpler plan that ships only `dispatch_turn(sync) +
2 trigger types + no priority + inlined skill bodies + no AgentContext`
would still deliver the architectural decision the brief is buying.

ADR-010 minimal revisions before Accept: address #1 (cooldown unit) and
#2 (StateChangeTrigger metadata). Address #6 (drop snapshot_excerpt) if
ADR-011 doesn't move on #5 (build_agent_context).

ADR-011 minimal revisions before Accept: name or resolve #4 (async
shaping), name or resolve #5 (build_agent_context justification), and
explicitly defend or revisit #7 (snapshot-per-turn as challenged by this
review). #3 (Agent.priority drop) is recommended but defensible to keep
with stronger justification than "migration cost".

Substantive findings count is on the higher end (4-10 expected; 10
delivered with 2🔴 / 5🟡 / 3🟢). The contrarian prompt is partially
responsible; an architect reading this should weight findings #1 and #2
as load-bearing and treat the 🟡 cluster as a single "scope discipline"
signal rather than five independent escalations.

A true cross-family R0-B remains worth dispatching for this shape-change
task. The findings here cover unit-consistency and over-engineering
biases that I can prompt around; biases I am structurally unable to
neutralize (e.g., systematic over-confidence in Pydantic-validation
approaches, blind spots around what production multi-agent systems
actually break on) need a genuinely different model family to surface.
