---
task_id: P1.4
round: R0-B-cross-family
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 14
verdict_history:
  - verdict: needs_architect
    at_commit: 466e98d
    findings_count: { red: 2, yellow: 5, green: 3 }
    note: Proxy-lens review (Claude subagent with contrarian prompt)
  - verdict: clean
    at_commit: 33977db
    findings_count: { red: 0, yellow: 0, green: 10 }
    note: All 2 🔴 + 5 🟡 absorbed into senior revision per architect-routing ack-all-leans (7 findings → 7 new 🟢).
  - verdict: needs_architect
    at_commit: f7b14d2
    findings_count: { red: 2, yellow: 4, green: 4 }
    note: True cross-family review (DeepSeek V4 Pro, 2026-05-27). New runtime-integration findings not covered by proxy-lens review. See "True cross-family R0-B review" section below.
  - verdict: clean
    at_commit: 608eef5
    findings_count: { red: 0, yellow: 0, green: 14 }
    note: All 2 🔴 + 4 🟡 from DeepSeek section absorbed into senior revision per architect-routing-deepseek ack-all-leans (6 findings → 6 new 🟢; 4 prior 🟢 confirmations stand; 4 original-proxy 🟢 still in count). Fourth project use of frontmatter-as-live-signal pattern (RC-10 codification trigger reached).
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

---

# True cross-family R0-B review (DeepSeek V4 Pro — 2026-05-27)

**Reviewer:** DeepSeek V4 Pro session (genuinely different model family from
Claude). This review is independent of the proxy-lens review above — it
reads the same artifacts fresh and may re-surface or confirm prior findings
from a different cognitive angle.

**Date:** 2026-05-27
**Artifacts reviewed (post-revision state):**
- `docs/process/senior-plans/P1.4.md` (revised, post R0-A + proxy-R0-B absorption)
- `docs/decisions/ADR-010-should-agent-speak-contract.md` (revised)
- `docs/decisions/ADR-011-multi-agent-dispatch-sequential.md` (revised)
- `src/orchestrator/core/event.py` (current main, TYPED_METADATA + EventStore.append)
- `src/orchestrator/core/event_store.py` (append exception surface)

**Prior reviews already absorbed (not re-litigated):**
- Proxy R0-B 🔴#1 (cooldown ms-vs-s) → ADR-010 D2 `/1000.0` conversion site ✅
- Proxy R0-B 🔴#2 (StateTransitionMeta missing) → P1.4-4 scope add ✅
- Proxy R0-B 🟡#3 (Agent.priority drop) → ADR-011 D3 revised ✅
- Proxy R0-B 🟡#4 (sync not async) → ADR-011 D1 revised ✅
- Proxy R0-B 🟡#5 (build_agent_context honest framing) → ADR-011 D4 revised ✅
- Proxy R0-B 🟡#6 (snapshot_excerpt drop) → removed from AgentContext ✅
- Proxy R0-B 🟡#7 (snapshot-per-turn latency named) → ADR-011 Consequences ✅
- R0-A Y1 (AgentMatchRecord.reason drop) ✅
- R0-A Y2 (ADR-011 D7 LLM exception policy) ✅
- R0-A Y3 (regex_registry separate from frozen model) ✅

---

## Cross-family lens calibration

DeepSeek-family models differ from Claude-family on several cognitive axes
relevant to this review:

- **Higher sensitivity to runtime failure modes.** Claude tends to trust
  that "if the types are right, the runtime is right." DeepSeek is more
  likely to ask "what happens when this specific call fails at 3am."
- **Lower tolerance for signature-dishonesty.** Claude accepts "add the
  parameter now, implement it later" as forward-compat. DeepSeek views
  unused parameters in a shipped function as a false signal.
- **Higher weight on integration-surface correctness.** Claude reviews
  individual modules well; DeepSeek is more likely to catch gaps at the
  seams between modules (loader → dispatch → speak, dispatch → event_store).
- **Similar closed-enum discipline appreciation.** Both families agree on
  Principle 4; no systematic bias difference here.

Where this review disagrees with the proxy R0-B above, it's because the
proxy was a Claude model simulating a contrarian — structurally limited in
which biases it can escape. This review has different structural biases
and may therefore surface different findings.

---

## Findings

| # | Severity | File:section | What's wrong | What should be |
|---|----------|-------------|--------------|----------------|
| 1 | 🔴 | ADR-011 §D7 (LLM exception); plan P1.4-8 (line 283-300) | **No failure path for `event_store.append()` inside `dispatch_turn`.** ADR-011 D7 covers LLM call failures exhaustively (log+skip+continue, with 3 considered alternatives). But after a successful LLM call, `dispatch_turn` calls `event_store.append(event)` to persist the utterance (plan line 294). `EventStore.append()` can raise: `RoomNotFoundError`, `InvalidParentError`, `MetadataValidationError`, and `sqlite3.OperationalError` (disk I/O, database locked). The LLM cost is already sunk (the model generated the response), but the utterance can't be persisted. Unlike the LLM-failure case where continuing to the next agent preserves multi-perspective, an event-store failure means the system's single source of truth is unavailable — continuing to dispatch MORE agents burns more LLM budget for events that also can't be persisted. | Add to ADR-011 D7 scope (or as D7-b): event-store append failure **aborts the turn** (raise, don't continue). The rationale is different from the LLM-failure case: LLM failure is per-agent (other agents' work is independent); event-store failure is per-turn (no agent's work can be persisted). The test in P1.4-8 should add a §3 cleanup variant: mock `event_store.append` to raise `sqlite3.OperationalError` on agent A's utterance; assert the exception propagates (does not continue to agent B); assert no further LLM calls are made. |
| 2 | 🔴 | ADR-011 §D2+D7; plan P1.4-8 acceptance | **All-agents-fail produces zero utterances with no contract for the caller.** ADR-011 D7 says "skip that agent's utterance append; continue to next agent." If ALL agents' LLM calls fail (rate-limit cascade, fallback-chain exhaustion, API outage), `dispatch_turn` returns `[]`. This is tested (P1.4-8 "no-agent-speaks" test covers the trigger-mismatch case, but the all-agents-LFAIL case is NOT the same — in the trigger-mismatch case, zero agents were ASKED to speak; in the all-fail case, N agents were asked, N failed, and the returned `[]` is indistinguishable from "nobody wanted to speak." The caller (room runtime, P1.5+) cannot tell the difference between "nothing to say" and "everything broke." | Add to `dispatch_turn` return shape or to an out-of-band signal: either (a) return a richer type than `list[Event]` (e.g., a `TurnResult` with `utterances: list[Event]` + `failed_agents: list[str]` + `total_asked: int`), or (b) document in ADR-011 D7 that the caller MUST check logs for the WARNING-level messages emitted by the exception handler. Option (b) is cheaper for P1.4 but creates a silent dependency on log observation. I recommend (a) with a minimal `TurnResult` Pydantic model — adds one type, one §6 test, and makes the all-fail case programmatically detectable. The plan P1.4-8 already acknowledges the return type; extending it to a small struct is a low-cost pre-emptive fix. |
| 3 | 🟡 | plan P1.4-6 §5 push-back #4; P1.4-6 acceptance | **`decide_agents_for_room(room_type, room_state, *, available_agents)` takes two parameters it ignores.** P1.4 returns every agent regardless of room_type or room_state. The plan acknowledges this as "P1.4 simple shape" but keeps the full signature. A function that takes parameters it ignores trains readers to not trust function signatures — "does this param matter? did someone forget to implement it? was it for a future PR that never landed?" When P1.5+ adds real room-type filtering, the function body changes — adding the parameters THEN (additive signature change) costs nothing in P1.4 (zero callers outside the agents module). | Remove `room_type` and `room_state` from the P1.4 signature. Add them in P1.5+ alongside the filtering logic. The function's docstring should say "P1.4: returns all available agents. P1.5+: filters by agent.applies_to.room_types." The plan's §5 push-back #4 can stay as-is (the deferral reasoning is correct); the signature just shouldn't pretend the filtering exists yet. |
| 4 | 🟡 | plan P1.4-5 loader + P1.4-8 dispatch + P1.4-7 speak | **regex_registry threading across three modules has no §1 integration test.** The compiled regex patterns flow: P1.4-5 loader creates `dict[(agent_id, trigger_index), Pattern]` → P1.4-8 `dispatch_turn` receives it as kwarg → P1.4-7 `should_agent_speak` reads `regex_registry[(agent.id, trigger_index)]`. The plan has §1 cross-module tests for skill bodies (source≠sink) and utterance authorship, but nothing verifying that a Pattern compiled at load-time is the same object used at match-time. A regression where someone refactors the loader to return uncompiled patterns (or where the registry key shape changes) would silently break `should_agent_speak`'s regex evaluation at runtime (KeyError on registry miss, caught by the plan's "registry-miss raises SpeakingTriggerError" test — but that test uses a manually constructed registry, not the one from the loader). | Add one §1 integration test in `tests/agents/test_integration.py` (or P1.4-8's test_dispatch.py): load a real agent yaml with a regex trigger via `load_agents`, extract the regex_registry, construct a matching event, call `should_agent_speak` with that registry, assert `speak=True` with the correct `matched_trigger_index`. This verifies the key shape `(agent_id, trigger_index)` matches between loader producer and speak consumer. |
| 5 | 🟡 | plan P1.4-4 schema; ADR-011 §D4 | **`AgentContext` naming is misleading for P1.4 scope.** The model contains `agent: Agent` + `skill_bodies: list[str]`. The name "Context" implies the full prompt-ready context, but it's missing room state, event snapshot excerpt, agent persona templating, and autonomy-aware tool context — all named in ADR-011 D4 as future additions. When P1.5+ adds those, either `AgentContext` grows (fine) or a sibling type appears ("which one is the REAL context?"). Consider renaming to `AgentSkillContext` for P1.4 to be honest about scope. If the name stays, add a docstring field explicitly listing what's deferred to P1.5+. |
| 6 | 🟡 | ADR-010 §D2 (line 147-148); `core/event.py` author validation | **Cooldown lookup depends on exact author string format with no defense-in-depth.** ADR-010 D2 step 1 searches for `author == f"agent:{agent.id}"` in the snapshot. The author format `agent:<id>` is validated by regex at the application layer (`is_valid_author` in `core/event.py:275-278`), not at SQLite CHECK constraint level (ADR-001 D11 explicitly chose application-layer-only). If a future bug (or direct SQL insert bypassing the API, or a hand-rolled Event constructor in a test fixture) produces `author="agent: skeptic"` (space), `author="Agent:skeptic"` (capital A), or `author="agent:skeptic "` (trailing space), the string comparison silently fails — the agent is never found in cooldown, and speaks more often than intended. This is not a P1.4 bug (it's a pre-existing ADR-001 design choice), but P1.4 is the **first code path where this lookup has real behavioral consequences** (agent speaks with incorrect cooldown gating). | No schema change needed. Add a comment in `should_agent_speak`'s cooldown section: "Depends on exact `f'agent:{agent.id}'` format matching `Event.author`. See `core/event.py:is_valid_author` for the canonical format. A malformed author string (e.g., extra whitespace, wrong case) causes silent cooldown bypass." The P1.4-7 table-driven tests should include one case with a correctly-formatted author string to lock the format expectation. Optionally: add a `build_author(agent_id: str) -> str` helper in `core/event.py` and use it in both the Event constructor and `should_agent_speak` — single point of format truth. |
| 7 | 🟢 | ADR-011 §D1 (sync `def`) | **Sequential + synchronous dispatch is the correct choice for P1.4.** Confirmed. The R0-B 🟡#4 revision (async→sync) was correct. The additive-upgrade path is documented with zero migration cost. |
| 8 | 🟢 | ADR-011 §D3 (no `Agent.priority`) | **Dropping `Agent.priority` from P1.4 is correct.** Confirmed. The 2-agent sample with disjoint triggers has no real conflict surface. The P1.5+ additive migration cost is small (one field + one default + tune 2 yamls). |
| 9 | 🟢 | ADR-010 §D6 (separate regex_registry) | **Separate registry over `model_post_init` private attr is the right trade.** Confirmed. Frozen-model invariant preservation is load-bearing for the project's discipline; threading one extra kwarg through two function signatures is cheap insurance. |
| 10 | 🟢 | ADR-011 §D7 (log+skip+continue) | **Per-agent LLM exception policy is the correct default.** Confirmed. Abort-on-first-failure would violate multi-perspective Principle 6. The 3 considered alternatives are correctly rejected for P1.4. Finding #2 above (all-agents-fail) is about the *caller's* ability to detect the failure, not about the intra-turn policy itself. |

---

## Cross-checks (post-revision state)

- [x] ADR-010 D2 `/1000.0` conversion site explicitly inscribed ✅
- [x] `StateTransitionMeta` scoped into P1.4-4 ✅
- [x] ADR-011 D1 `def` not `async def` ✅
- [x] ADR-011 D3 alphabetical-id only, no `Agent.priority` ✅
- [x] ADR-011 D4 honest framing (no oversold justification) ✅
- [x] `AgentContext.snapshot_excerpt` dropped ✅
- [x] `AgentMatchRecord.reason` dropped ✅
- [ ] **event_store failure path** — absent (finding #1)
- [ ] **all-agents-fail caller contract** — absent (finding #2)
- [ ] **regex_registry §1 threading test** — absent (finding #4)
- [x] Three new constitutional tests correctly specified
- [x] No new `LLMPurpose` values; `AGENT_RESPONSE` + `caller_agent_id` reused
- [x] No new `EventType` values (turn boundaries correctly deferred)
- [x] P1.4-4 `StateTransitionMeta` addition is one-direction `core → agents` (correct)

---

## Cross-model comparison with proxy R0-B

The proxy R0-B (Claude with contrarian prompt) caught **unit-consistency** and
**missing-schema-dependency** bugs — both are specification-level errors that
are visible from the document text alone. These are real and were correctly
absorbed.

This true cross-family review catches **runtime-integration** gaps —
event-store failure, all-agents-fail detectability, registry threading,
signature honesty. These are harder for any Claude-family review to surface
because Claude's cognitive style trusts that "if the contracts are right,
the integration is right." DeepSeek is structurally more likely to ask
"what happens when this specific call fails at runtime."

The two 🔴 findings here do NOT invalidate the absorbed revisions. They
address failure paths the revised ADRs and plan still don't cover. Both
are fixable with small scope additions (one new exception-handling branch
in dispatch_turn for #1; one TurnResult struct for #2).

---

## Net assessment (true cross-family)

**Verdict: `needs_architect`** — 2 🔴 / 4 🟡 / 4 🟢

The two 🔴 findings are runtime-failure gaps that become production bugs the
first time SQLite has an I/O error or an API outage cascades across all agents.
Both are fixable with targeted scope additions to P1.4-8 (dispatch_turn) +
ADR-011 D7 extension. Neither requires re-opening the absorbed proxy-R0-B
revisions.

The four 🟡 findings share a theme: **the plan trusts its abstractions more
than it verifies their integration.** The signature-dishonesty (#3), missing
registry threading test (#4), misleading naming (#5), and silent format
dependency (#6) are all "correct on paper, fragile at the seams." They won't
break the build but they will break the first junior who refactors the loader
without re-reading all three module specs.

**Recommendation:** address 🔴#1 and 🔴#2 before architect Accept on
ADR-010 + ADR-011. The 🟡 cluster can be resolved via plan revision
(acceptance criteria additions) without ADR changes. Architect routing
expected within the same acceptance window as the already-absorbed proxy
R0-B revisions.

---

## Verdict bump 2026-05-27 (RC-10 protocol — 4th project use)

**Bumped `needs_architect → clean` after second-routing absorption at commit `608eef5`.** All 6 DeepSeek findings (2 🔴 + 4 🟡) absorbed faithfully per `docs/process/reviews/P1.4/architect-routing-deepseek.md` (commit `5b6c96f`). Architect-partner verified the senior revision (Bash grep of ADR-010 + ADR-011 + plan against each routed action):

| DeepSeek finding | Routing | Absorption evidence |
|---|---|---|
| 🔴#1 event_store failure | D7-b: abort the turn | ADR-011 §7-b new section (line 363); P1.4-8 acceptance "On `event_store.append` exception" branch (line 351) |
| 🔴#2 all-agents-fail caller contract | TurnResult Pydantic model | P1.4-4 schema `class TurnResult` (line 208); ADR-011 D1 signature returns `TurnResult` (line 83-91); D7 references `TurnResult.failed_agents` (line 347-352) |
| 🟡#3 unused signature params | drop room_type/room_state from P1.4 | P1.4-6 signature now `decide_agents_for_room(*, available_agents)` (line 303, 309); docstring lists P1.5+ additive expansion |
| 🟡#4 regex_registry §1 threading test | add integration test | P1.4-8 §1 cross-module integration test for regex_registry threading (line 356); P1.4-9 e2e references it |
| 🟡#5 AgentContext naming | docstring deferrals (not rename) | AgentContext docstring "P1.5+ adds (additively, per future ADRs)" (line 188) |
| 🟡#6 cooldown author format | build_author helper in core/event.py | P1.4-4 schema adds `def build_author(agent_id: str) -> str` (line 246); P1.4-7 cooldown step uses `build_author(agent.id)` (line 326); ADR-010 D2 mechanics step 1 references the helper (line 147-153) |

All 6 findings reclassified as 🟢 in post-bump count (6 new 🟢 + 4 prior DeepSeek-confirmation 🟢 + 4 original proxy-section 🟢 = 14 total 🟢; original 🔴/🟡 finding bodies preserved above for audit).

**Fourth project use of the frontmatter-as-live-signal pattern** (RC-10):
1. W-001-impl R0-A (commit `96c1469`) — first use, post-fix verdict bump
2. W-002 R0-A-on-plan (commit `440ab3b`) — post-revision bump
3. P1.4 R0-A + R0-B proxy (commit `047daa4`) — first dual-review-bump
4. **This bump (commit pending)** — first dual-routing-on-same-file bump (proxy absorbed at `33977db`; true cross-family absorbed at `608eef5`; both routings preserved in `verdict_history`)

RC-10 has now hit graduation threshold (P1.3 retro §4: "if a third clean-absorption cycle exercises the pattern, RC-10 graduates for codification"). Codification target: `docs/process/reviews/README.md` "Post-resolution verdict-bump protocol" section. Defer to W-003 brief or architect-partner-direct addendum.

**Captured for RC-15 (new candidate)**: dual-lens R0-B for shape-change is project standard going forward — proxy-lens first (catches doc-level errors), true cross-family second (catches integration errors). Two routing passes on the same task is acceptable when the lens count genuinely doubles coverage. Worth ~$2 + 30-40 min architect time per shape-change task; not warranted for mechanical refinement (W-002, W-002.5).

## State-machine sequencing post-bump

With this verdict bump:
- `R0-B-cross-family.md` verdict: clean ✓
- `R0-A-on-plan.md` verdict: clean ✓ (unchanged; DeepSeek findings were R0-B-only)
- P1.4 ADR Accepts unblocked from review-side; gated only on:
  - (a) Substrate distance test per `docs/process/distance-test.md`
  - (b) Multi-ADR ergonomics via W-002.5 land (optional — architect can also accept 1-2 overrides during ADR Accepts if W-002.5 not yet impl'd)

Verified by Bash spot-check of revised files; full proof in the commit diff at `608eef5`.
