---
task_id: P1.4
round: R0-A-on-plan
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 12
verdict_history:
  - verdict: needs_architect
    at_commit: 53ea2dd
    findings_count: { red: 0, yellow: 5, green: 7 }
  - verdict: clean
    at_commit: 33977db
    findings_count: { red: 0, yellow: 0, green: 12 }
    note: All 5 🟡 absorbed into senior revision per architect-routing ack-all-leans (5 🟡 → 5 new 🟢).
---

# P1.4 R0-A on plan (architect-dispatched pre-impl review)

> **Verdict bump 2026-05-27 (W-001-impl RC-10 precedent — frontmatter as live signal):**
> Original verdict `needs_architect` reflected 5 🟡 findings requiring
> architect routing. Architect acked-all-leans
> (`docs/process/reviews/P1.4/architect-routing.md`, commit `2b92e34`).
> Senior revised ADR-010 + ADR-011 + plan (commit `33977db`) absorbing
> all five 🟡 findings:
>
> - **Y1 (AgentMatchRecord dead Literal)** → lean (b): field dropped
>   entirely from `AgentMatchRecord` + `AgentSelectionTrace.considered`
>   in P1.4-4 schema. P1.5+ adds back additively when filtering variance
>   surfaces.
> - **Y2 (LLM-exception policy hidden)** → lean (b): ADR-011 grew
>   new Decision 7 inscribing log+skip+continue with Considered
>   Alternatives + Reversibility row; P1.4-8 cross-references D7;
>   logger spec named explicitly.
> - **Y3 (ADR-010 D6 regex-cache ambiguous)** → lean (a): separate
>   loader-level registry picked explicitly; `regex_registry`
>   parameter threaded through `dispatch_turn` → `should_agent_speak`;
>   frozen-model semantic preserved.
> - **Y4 (plan §1 R0-B-as-gate misleading)** → lean (a): one-sentence
>   clarification — "architect-process-gated (not state-machine-
>   enforced); architect holds the Accept until R0-B revisions
>   absorbed."
> - **Y5 (P1.4-8 logger spec missing)** → lean (a): explicit
>   `logging.getLogger('orchestrator.agents.dispatch').warning(...)`;
>   no `print`; no stdout. Honors P1.3-R0-A-1 + W-002-3 precedent.
>
> Sibling review R0-B-cross-family also bumped in companion commit.
> All five former 🟡 reclassified as 🟢 (post-bump count: 0 🔴 / 0 🟡 /
> 12 🟢, with five new 🟢 documenting clean absorption). Original
> finding bodies preserved below for audit; original verdict preserved
> in git history at commit `53ea2dd`.
>
> Third project use of the frontmatter-as-live-signal pattern after
> W-001-impl R0-A (commit `96c1469`) + W-002 R0-A-on-plan (commit
> `440ab3b`). **P1.3 retro §4 RC-10 graduates to codification** after
> this instance — three clean-absorption cycles is the threshold for
> a post-resolution-frontmatter-update protocol section in
> `docs/process/reviews/README.md`. Defer codification to W-003 or
> earlier per architect call.



| Field | Value |
|---|---|
| Round | R0-A-on-plan (architect-dispatched per RC-9; third instance after W-001-impl + P1.3) |
| Reviewer | architect-partner (Claude Opus 4.7, 1M context) in primary session — see note on dispatch path |
| Date | 2026-05-27 |
| Artifacts reviewed | `docs/process/architect-briefs/P1.4.md`; `docs/process/senior-plans/P1.4.md` (commit `5c2ba29`); `docs/decisions/ADR-010-should-agent-speak-contract.md` (`5c2ba29`); `docs/decisions/ADR-011-multi-agent-dispatch-sequential.md` (`5c2ba29`); `docs/process/reviews/P1.4/R0-B-cross-family.md` (sibling review, `466e98d`) — read to deliberately avoid duplication |
| Companion review | R0-B-cross-family.md committed on this branch (proxy lens per architect-partner caveat); 2🔴 / 5🟡 / 3🟢 |
| Dispatch path note | Architect dispatched two parallel reviews via subagent + parallel W-002 senior work. Subagent for R0-B-cross-family produced the salvageable artifact at `466e98d`; subagent for R0-A-on-plan session-limited before producing an artifact. **This R0-A is the architect-partner fallback** — performed in-session because the subagent dispatch failed and the review work needs doing. Mention captured here for audit trail; not a process precedent (the established pattern remains architect-dispatched-via-fresh-session per RC-9). |

---

## Lens for this review

R0-B caught the load-bearing operational findings — cooldown unit mismatch (🔴), StateChangeTrigger metadata gap (🔴), and a scope-discipline cluster on `Agent.priority` / async-shape / `build_agent_context` / `snapshot_excerpt` / snapshot-per-turn. **I deliberately do not re-raise those.** R0-A's value-add is the in-family lens: brief compliance, push-back disposition, predicted-self-discovery coverage, ADR structural quality, decision-trace pattern shape, layering correctness, and senior policy decisions made silently rather than surfaced.

If the architect routes resolution of R0-B's 🔴 findings into ADR-010 revisions and my findings here into the same revision pass, ADR-010 gets two rounds of revisions absorbed in one cycle.

---

## Findings

### 🟡 Y1 — `AgentMatchRecord.reason` ships a dead Literal value

**Where:** plan P1.4-4 schema (`AgentMatchRecord.reason: Literal["room_type_matched", "room_type_mismatch"]`, plan lines 167-170); plan P1.4-6 acceptance (lines 232-235); plan §5 push-back #4 (lines 366-367).

**What:** plan §5 push-back #4 explicitly states "P1.4 only ships 2 agents — room-type filtering is over-engineering ... `decide_agents_for_room` in P1.4 returns every loaded agent." Per that decision, every `AgentMatchRecord` in P1.4 has `loaded=True, reason="room_type_matched"`. The Literal value `"room_type_mismatch"` is uninstantiable in P1.4. Shipping a closed-Literal with one dead value invites "what is this for?" questions in every code review and locks the project to a name (`room_type_mismatch`) for a P1.5+ predicate whose actual shape isn't yet designed (it might be `applies_to_mismatch` or `priority_excluded` or `room_state_excluded`).

**Options for resolution:**

- (a) Drop `"room_type_mismatch"` from the Literal in P1.4; the field becomes `reason: Literal["room_type_matched"]` (single-value Literal — defensible as a future-extension hook, but smelly). When P1.5+ lands filtering, the Literal extends additively per ADR-007 D2 precedent.
- (b) Drop the `reason` field entirely from `AgentMatchRecord` in P1.4 (and from `AgentSelectionTrace.considered`); add it back in P1.5+ when filtering surfaces real reason variance. The trace still records `loaded: bool`, which is the only useful diagnostic until filtering exists.
- (c) Keep as-shipped + document in ADR-011 D3 or a new D7 that the Literal is forward-compat for the P1.5+ `applies_to` filter and the value name is intentionally generic.

**My lean: (b)** — drop the field. The decision-trace pattern (per ADR-005 D6, ADR-009 D6) is "carry enough to explain WHY the selection happened." In P1.4 the WHY is uniformly "every loaded agent always loads"; there's nothing to explain. Trace doesn't earn its keep until variance exists.

**Severity 🟡 not 🔴**: doesn't ship a runtime bug (the value is unreachable, not wrong); architect-routable.

### 🟡 Y2 — LLM-exception-per-agent policy is a hidden senior decision

**Where:** plan P1.4-8 acceptance (line 271): "On `LLMRouter` exception per agent: log + skip that agent (no event appended); next agent proceeds. (Senior judgment: don't abort the whole turn on one agent failure; aligns with multi-perspective Principle 6. Flag in commit body and §5 push-back #8.)"

**What:** the cross-reference to push-back #8 is misleading. Push-back #8 is about agent count (2 vs 5 yamls). The LLM-exception-handling policy is not surfaced anywhere in §5; it is named only inside P1.4-8 acceptance text. **This is a policy decision masquerading as an impl detail.** Choices: (a) skeptic LLM call fails → swallow + dispatch prober + continue turn; (b) any LLM failure aborts the whole turn (no partial utterances); (c) abort only on cascading failures (e.g., 2+ agents failing in one turn). The brief did not pre-decide this; the senior chose (a) and buried the choice in an acceptance criterion.

**Options for resolution:**

- (a) Plan §5 push-back #15 surfaces the choice explicitly. Architect either acks or routes.
- (b) ADR-011 D7 (or D1 sub-decision) inscribes "per-agent LLM failure → log + skip + continue turn" with rationale + Considered Alternatives (abort-on-first-failure; abort-on-N-failures). This is the right home if the policy carries beyond P1.4.
- (c) Defer the policy entirely — P1.4-8 raises on any LLM exception; P1.5+ designs the per-agent failure semantics. Simpler P1.4; the abort-on-first-failure default is conservative.

**My lean: (b)** — ADR-011 grows a D7 because this is exactly the kind of cross-cutting policy that ADRs exist for. Senior already made the decision; the ADR is the right place to inscribe it with proper consideration of alternatives. Cost: ~150 words added to ADR-011.

**Severity 🟡**: policy choice with reversibility cost (changing later requires re-thinking every dispatch test); architect needs to confirm or route.

### 🟡 Y3 — ADR-010 D6 leaves regex-cache strategy ambiguous; plan inherits ambiguity

**Where:** ADR-010 D6 (lines 220-223): "The compiled pattern is cached on the trigger (mutable cache on a frozen model — handled via a separate registry in the loader, OR via `model_post_init` storing on a private attribute)." Plan P1.4-5 acceptance (lines 219-222): "Regex compile: every `RegexTrigger.pattern` is `re.compile()`'d at load. Compile failure raises `SpeakingTriggerError`..." — picks neither approach.

**What:** the two cached-regex strategies have non-trivial differences. **Separate registry:** loader-level dict `_compiled_patterns: dict[trigger_id, re.Pattern]`; `should_agent_speak` accepts the registry as a parameter or via closure. Pro: cleaner separation; trigger model stays purely declarative. Con: dispatch primitive must thread the registry through; tests need fixtures for it. **`model_post_init` private attribute:** the trigger model itself stores `_compiled_pattern` via Pydantic's mutable private fields. Pro: trigger carries its own compiled form; no registry threading. Con: violates "frozen model" semantic (private attributes are technically allowed but feel adversarial to the model's frozen-ness); harder to test in isolation.

**The decision affects the dispatch signature, the loader signature, the test fixture shape, and the constitutional test scope.** Leaving it open at ADR-time means junior makes the design call mid-impl, which is exactly the senior-drafts-ADR rule (RC-3) trying to prevent.

**Options for resolution:**

- (a) ADR-010 D6 picks one approach explicitly (architect-partner lean: separate registry, because frozen-model semantics are load-bearing for the project's invariant discipline); plan P1.4-5 inscribes it; impl follows.
- (b) ADR-010 D6 stays ambiguous; plan §5 push-back #15 raises it; architect picks at R0-A review time.

**My lean: (a)** with separate-registry pick. Cleaner against the frozen-model invariant. `model_post_init` on a frozen-extra-forbid model is the kind of pattern that bypasses the discipline that ADR-009 + ADR-010 are otherwise enforcing.

**Severity 🟡**: design call needs to land before impl; not a runtime bug, but absorbs design surface that should have been settled in the ADR per RC-3.

### 🟡 Y4 — Plan §1 implies a cross-family-R0-B-clean state-machine gate that doesn't exist

**Where:** plan §1 Workflow state row (line 9): "`.workflow/P1.4.yaml` currently `awaiting_senior_plan`; on push of this plan, advances to `awaiting_architect_accept` (gated on both ADR-010 and ADR-011 Accepts plus cross-family R0-B clean)".

**What:** ADR-008 + the current state-machine impl gates `awaiting_architect_accept → awaiting_junior_impl` on `_read_adr_status` returning `"accepted"`. Cross-family R0-B is a **process** gate (architect-policy commitment per P1.3 retro §6) — it is not enforced by code. The state machine will happily advance to `awaiting_junior_impl` the moment both ADRs flip to Accepted on origin/main, regardless of whether R0-B has been dispatched, returned, or absorbed. Plan §1's parenthetical implies a gating that the code does not enforce, and the architect (or future architect-partner reading the plan in a stale context) could be misled into thinking the harness will block until R0-B is clean.

**Options for resolution:**

- (a) Plan §1 line 9 is edited: "(architect-process-gated: both ADR Accepts + cross-family R0-B clean per P1.3 retro §6; the state machine does not enforce R0-B — architect holds the Accept until both ADR R0-B revisions are absorbed)". One-sentence clarification.
- (b) The state machine grows a `requires_cross_family_review: bool` field that, when true, blocks `awaiting_architect_accept → awaiting_junior_impl` until a `docs/process/reviews/{task-id}/R0-B-*.md` exists with `verdict: clean`. This is W-002+ territory; **NOT** a P1.4 plan revision.
- (c) Accept that R0-B is a soft gate and the plan should say so explicitly without code-level enforcement.

**My lean: (a)** — the cheapest fix; one-sentence clarification in plan §1; no architectural change. (b) is a real future feature but doesn't belong in the P1.4 plan revision pass.

**Severity 🟡**: documentation accuracy issue; could mislead a future reader. Not a ship-bug.

### 🟡 Y5 — "log + skip" lacks a logger specification; risks stdout pollution under impl

**Where:** plan P1.4-8 acceptance (line 271, sibling to Y2): "On `LLMRouter` exception per agent: log + skip that agent..."

**What:** P1.3-R0-A-1 surfaced the precedent: `load_skills` non-skill `.md` handling now requires `logging.getLogger(__name__).debug(...)`, NOT `print(...)`, per W-002-3 plan acceptance (W-002 plan section W-002-3). P1.4-8 says "log + skip" with no logger specification. Without an explicit binding, junior could plausibly `print(f"agent {agent.id} failed: {e}")` (stdout pollution; breaks test capture; violates the implicit project precedent).

**Options for resolution:**

- (a) Plan P1.4-8 acceptance amended: "log via `logging.getLogger('orchestrator.agents.dispatch').warning(...)` with `agent_id` + the exception in the message; ... skip ... no stdout."
- (b) Plan §4 forcing functions adds a project-wide note "all `log` actions use `logging.getLogger(__name__).<level>`; no `print` in `src/orchestrator/`."

**My lean: (a)** — surgical fix to P1.4-8. (b) is a real project convention worth codifying eventually but not in this plan revision.

**Severity 🟡**: precedent-honoring nit; low risk but the right fix is one line.

---

### 🟢 G1 — Brief decision compliance is complete

All 6 Architect-settled decisions in brief §"Architect-settled design decisions" are honored:

- **D1 (all three decisions are code)** — plan P1.4-6/7/8 declare each function as pure; constitutional test `test_constitution_no_llm_calls_in_agents_module` covers.
- **D2 (cooldown event-stream-driven)** — ADR-010 D2 explicit; Considered Alternative B (wall-clock) explicitly rejected; both R0-B 🔴#1 (cooldown unit) and my findings don't dispute the rule, only the unit conversion.
- **D3 (concurrency boundaries (a)(b)(c))** — ADR-011 D1 defends (a) sequential; D3 defends (b) priority+id; D2 defends (c) per-turn snapshot. All three Boundaries pinned.
- **D4 (Skeptic schema correctness)** — plan P1.4-9 has full skeptic yaml with dissent_dimensions + forbidden_behaviors + 3 trigger types + opus-tier llm_config. Placeholder TODO content acknowledged per brief.
- **D5 (workflow integration)** — plan §3 explicitly defers P1.4-3 Accepts until W-002 lands; §1 dependency row says the same.
- **D6 (cross-package layering)** — three new constitutional tests in P1.4-4 (`no_llm_calls_in_agents_module`, `core_does_not_import_agents`, `skills_does_not_import_agents`); ADR-011 D5 declares the same.

### 🟢 G2 — Push-back disposition is complete

All 8 brief push-backs addressed in plan §5 (numbered #1-#8); brief's cross-family R0-B mandate added as #9. No silent ignores. Each has a defended position. Cross-family R0-B push-back #9 correctly defers reviewer-model selection to architect.

### 🟢 G3 — Predicted self-discoveries surfaced

All 5 brief-predicted self-discoveries appear in plan §5 #10-#14 (no new EventType; cooldown × snapshot interaction; `required_capabilities` validation; `state_transition` metadata gap surfaced for junior; Skeptic role thin acknowledged). Self-discovery #13 (`state_transition` metadata) is the seed of R0-B 🔴#2 — same gap surfaced from two lenses, consistent.

### 🟢 G4 — Filename-stem-equals-id rule extended cleanly

Plan P1.4-5 acceptance line 219 inscribes the ADR-009 D8 precedent (`.md` filename stem equals frontmatter id) extended to `.yaml` agents: `config/agents/skeptic.yaml` MUST declare `id: skeptic`; mismatch raises `AgentLoadError(field="id")`. Clean precedent reuse; consistent across two loader modules.

### 🟢 G5 — ADR cross-references are symmetric and complete

ADR-010 References include ADR-011 ("sibling ADR consuming `SpeechDecision`"); ADR-011 References include ADR-010 ("this ADR consumes `SpeechDecision` and enforces the per-turn snapshot invariant from ADR-010 D5"). Both reference ADR-001 (EventType closed-enum precedent), ADR-005 D6 + ADR-007 D2 (Literal-extensibility precedent), ADR-008 (state machine), ADR-009 (`Skill.priority` + decision-trace precedent). Reference completeness is on par with ADR-009 (the gold standard from P1.3).

### 🟢 G6 — Decision-trace pattern correctly extended

`SpeechDecision` embeds trace inline (per ADR-010 D3) — matches ADR-005 D6 + ADR-009 D6 precedent. `AgentSelectionTrace` exists in plan P1.4-4 schema. The trace shape for P1.4 is bounded (no per-trigger fields; matched-index + cooldown-remaining only) — addresses ADR-010 Considered Alternative D (per-trigger trace explosion). Decision-trace discipline preserved from P1.3 into P1.4.

(Caveat: Y1 above flags that the AgentSelectionTrace's `reason` Literal has dead values. That's a refinement to G6, not a contradiction of it.)

### 🟢 G7 — Scope discipline holds — summon correctly deferred to P1.5+

Plan §5 push-back #1 defends the summon deferral against the brief's "include if plan stays ≤6 tasks" lean — plan is 10 tasks even with summon out; including summon would push to 12-13 + add ADR-012 + new EventType. The defense is honest about why the architect-partner lean held. **This is exactly the kind of senior push-back the architect-partner role exists to invite + honor.**

(Side note: R0-B finding #9 also praises this cut from the cross-family lens. Two-lens agreement on a scope decision is a strong signal the cut is correct.)

---

## Push-back disposition table (architect-decision view)

For each of the 8 brief push-backs, was the plan's disposition substantive (defended with reasoning) vs nominal (acknowledged but not defended)?

| # | Brief push-back | Plan disposition (§5) | Substantive? | My read |
|---|---|---|---|---|
| 1 | Summon in P1.4 scope | #1: defer | yes (10-tasks argument) | ✓ correct cut; G7 agrees |
| 2 | Concurrency model | #2: sequential + additive path | yes (ADR-011 D1 + 4 sub-reasons) | ✓ architect lean was no-strong-preference; senior picks; defensible |
| 3 | Skill→agent integration location | #3: separate `build_agent_context` | partial (ADR-011 D4) | ⚠ R0-B 🟡#5 challenges; combine with R0-B feedback in revision |
| 4 | `Agent.priority` field exists | #5: include | partial (parallel to Skill.priority) | ⚠ R0-B 🟡#3 challenges harder; combine |
| 5 | All 3 trigger types | #6: include all 3 | yes (each has a current consumer) | ✓ defensible; R0-B Y agrees impl-level concern is StateChange metadata not the count |
| 6 | Loader as separate commit | #7: separate (P1.4-5 atomic) | yes (P1.3 pattern) | ✓ standard precedent |
| 7 | `should_agent_speak` testing | dedicated `test_should_agent_speak.py` (plan P1.4-7) | yes (full table-driven coverage) | ✓ matches brief push-back #7 directly |
| 8 | 2 vs 5 agent yamls | #8: 2 (skeptic + prober) | yes (dispatch logic exercises with 2) | ✓ correct cut |

**Verdict on push-back coverage:** 6 substantive, 2 partial (#3, #4 challenged harder by R0-B). The architect's revision pass should bundle R0-B Y3 (Agent.priority) + Y5 (build_agent_context) with this lens to produce a single coherent ADR-011 revision.

---

## Cross-checks

- [x] Frontmatter contract on this file followed.
- [x] Plan §3 execution order coherent (P1.4-1..10 sequential dependencies resolve cleanly).
- [x] No new LLMPurpose values added (plan uses existing `AGENT_RESPONSE` + `caller_agent_id` discriminator per handoff §5.5).
- [x] Three new constitutional tests align with W-001-impl Y1 + P1.3 layering precedent.
- [x] ADR-009 D8 filename-stem-equals-id rule extended to .yaml agents.
- [x] Decision-trace pattern preserved (SpeechDecision embeds trace inline).
- [x] W-002 sequencing constraint honored (plan §3, §1 dependency).
- [ ] **Brief Architect-settled decision 1 (decision functions are code)** — passes structurally; depends on impl honoring constitutional test (P1.4-4 lands the test).
- [ ] **AgentSelectionTrace reason values** — Y1 above; one dead Literal.
- [ ] **LLM-exception policy explicit** — Y2 above; hidden in P1.4-8 acceptance text.
- [ ] **Regex-cache strategy picked** — Y3 above; ADR-010 D6 ambiguous.
- [ ] **State-machine vs process gate for R0-B** — Y4 above; plan §1 misleading.
- [ ] **Logger specification for P1.4-8** — Y5 above; risks stdout pollution.

---

## Net assessment

**Recommendation: needs_architect.** Five 🟡 findings, none individually blocking, all routable:

- Y1 (dead Literal in trace) and Y3 (regex-cache strategy) are 1-line plan/ADR edits.
- Y2 (LLM-exception policy) wants ADR-011 D7 addition (~150 words) OR plan §5 push-back surfacing for architect ack.
- Y4 (R0-B as process gate) is a 1-sentence clarification in plan §1.
- Y5 (logger specification) is a 1-line addition to P1.4-8 acceptance.

**The 7 🟢 findings are not filler.** Brief compliance is complete; push-back disposition is substantively defended (6 of 8 fully, 2 partial that combine with R0-B feedback); predicted self-discoveries surfaced; ADR structure is on par with ADR-009 gold standard; cross-references are symmetric; decision-trace pattern preserved; scope discipline holds at multiple levels.

**Combined with R0-B (2🔴 / 5🟡 / 3🟢):** the architect's revision-pass scope is:

- ADR-010 revisions: cooldown unit fix (R0-B 🔴#1) + StateChangeTrigger metadata resolution (R0-B 🔴#2) + regex-cache strategy pick (my Y3). 3 substantive edits.
- ADR-011 revisions: optional D7 for LLM-exception policy (my Y2) + R0-B Y-cluster scope-discipline calls (Y3 priority, Y4 async-shape, Y5 build_agent_context, Y6 snapshot_excerpt, Y7 snapshot-per-turn defense). Architect picks which Y-cluster items to absorb vs accept-with-recorded-rationale.
- Plan revisions: §1 clarification (my Y4) + AgentMatchRecord.reason fix (my Y1) + P1.4-8 logger spec (my Y5) + §5 push-back addition for LLM-exception (my Y2).

**No 🔴 findings from the architect-partner lens.** The plan is structurally sound; the R0-B 🔴 cluster is on impl-detail bugs (unit math, missing schema), not on plan-architecture defects. This is consistent with the plan-stage-vs-impl-stage finding-shape pattern observed since P1.3 retro §5.1: substantive findings concentrate at the plan-revision phase rather than at post-impl review.

**The cross-family R0-B (proxy lens) and this in-family R0-A together exercised the dual-review discipline the brief mandated for shape-change work. The plan + ADRs are revisable to clean status with the combined finding set; no return-to-senior-for-redraft is warranted.**
