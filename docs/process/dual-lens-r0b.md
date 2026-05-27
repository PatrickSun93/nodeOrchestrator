# Dual-lens R0-B for shape change (RC-15 codification, post-P1.5)

## Summary

For **shape-change tasks**, the project's R0-B (cross-family review) discipline
admits a **dual-lens pattern**: a proxy-lens R0-B (Claude subagent prompted
to take a deliberately outside-Claude lens) followed by a **true cross-family
R0-B** (a genuinely non-Claude LLM session, typically external — GPT-class
or DeepSeek-class). The two lenses catch **structurally different errors**;
both passes can earn their keep on the highest-stakes architectural cycles.

**Dispatch is architect judgment per task, not blanket-applied to all
shape-change cycles.** This refinement emerged in P1.5: the cycle was
shape-change (third code-driven decision-function module + new layering
edge) but architect routed `skip` on the dual-lens pattern because stakes
were lower than P1.4 (state-machine pattern already battle-tested in
`workflow/`; no new concurrency surface; sequential dispatch settled).

This document codifies the pattern + the dispatch judgment criteria.

---

## Why dual-lens

P1.4 ran the project's first true cross-family R0-B (DeepSeek V4 Pro, on
the multi-agent dispatch design). The result demonstrated empirically that
the two lenses catch **structurally different errors**:

### Proxy-lens R0-B (Claude with contrarian prompt) caught

- 🔴 cooldown unit mismatch (seconds vs milliseconds in spec text)
- 🔴 `StateChangeTrigger` metadata gap (missing `StateTransitionMeta` typed schema)
- 🟡 scope-discipline cluster (Agent.priority, async-shape, build_agent_context, snapshot_excerpt)

These are **spec-level errors** — visible by careful reading of spec text;
the reviewer operates at the level of "is the specification internally
consistent?" Claude with contrarian prompting can find these reliably
because the analysis is text-as-graph: trace symbols + units + schema
dependencies.

### True cross-family R0-B (DeepSeek V4 Pro) caught

- 🔴 `event_store.append` failure path absent (`dispatch_turn` recovery semantic missing for per-turn fatal failure)
- 🔴 all-agents-fail caller contract (TurnResult shape needed; LLM-fail vs no-trigger indistinguishable)
- 🟡 signature honesty (`decide_agents_for_room` taking parameters it ignores)
- 🟡 regex_registry §1 integration test (key shape between loader + speak)
- 🟡 AgentContext naming (misleading scope)
- 🟡 cooldown author-format defense-in-depth (silent bypass on malformed authors)

These are **runtime-integration errors** — visible by tracing failure
modes across module boundaries + asking "what happens when this specific
call fails at 3am?" Claude's cognitive style trusts that "if the types
are right, the runtime is right"; DeepSeek-family models are
structurally more likely to ask the failure-mode question. The contrarian
prompt can move Claude part of the way; it can't move Claude past its own
structural biases.

### Empirical conclusion

The proxy lens **catches spec-level errors the in-family R0-A might miss**.
The true cross-family lens **catches runtime-integration errors neither
in-family R0-A nor proxy R0-B will reliably catch**. Different lenses,
different errors; both passes earn their keep on cycles where the cost
of either error class is high.

**On P1.4**: cost of either 🔴 class shipping ≈ "production bug that
silently misbehaves in 1000× scale (cooldown) OR throws KeyError on
first dispatch (StateTransition) OR fails to recover from a routine
SQLite I/O hiccup (event_store) OR makes all-fail indistinguishable from
no-trigger (caller contract)." Catch cost: ~$2 + ~40 minutes external
LLM session. ROI: unambiguously high.

**On P1.5**: stakes are lower (state-machine pattern is the third code-
driven decision-function instance after autonomy + skills + agents;
contract is reuse-of-pattern not novel-design; no new concurrency
surface). Architect-routed `skip` on dual-lens; relied on in-family R0-A
+ senior plan-vs-impl. **The R1 cycle that surfaced was caught by senior
plan-vs-impl** (not by R0-A; not by any R0-B). Stakes-vs-cost calculus
worked out: skipping dual-lens didn't cost the project on P1.5.

---

## When to dispatch (architect judgment per task)

Dispatch dual-lens R0-B (proxy first; true cross-family second) when **at
least two** of the following criteria hold:

1. **New concurrency surface** (e.g., P1.4's multi-agent dispatch with
   per-turn snapshot semantics; future concurrent-dispatch upgrade).
2. **New cross-package layering edge with runtime consequences** (e.g.,
   P1.4's `agents → autonomy` allowed-but-unused-yet edge; future runtime
   uses of an allowed-but-quiet layering edge).
3. **Contract referenced by ≥5 future tasks** (e.g., P1.4's
   `should_agent_speak` contract referenced by every future agent;
   future "summon" contract; future `tool_result` event contract).
4. **First runtime exercise of a previously-only-allowed pattern** (e.g.,
   P1.5.5's `agents → autonomy` runtime use; would have triggered if any
   genuine surface emerged, but P1.5.5 is integration not architecture).

**Dispatch single-lens R0-A only** (skip both proxy and true cross-family)
when:

- The task is **pattern-reuse, not novel design** (e.g., P1.5's state
  machine is the 3rd code-driven decision function; pattern battle-tested).
- The contract is **inscribed in existing ADRs being reused** (e.g.,
  W-002.5's multi-ADR aggregation extends W-002-1; no new ADR-level
  decisions).
- The stakes-cost calculus suggests **low marginal value** for the dual-
  lens investment (e.g., P1.5.5 integration cycle).

**Default for shape-change tasks: dispatch.** Architect overrides to skip
require explicit reasoning in the brief (P1.5 + P1.5.5 set the precedent
for the override reasoning shape).

---

## How to dispatch

### Step 1 — Proxy-lens R0-B (in-session via Agent tool, or external session)

Launch a reviewer Claude session with the prompt template from
`docs/process/reviews/<task-id>/external-r0b-prompt.md` (per-task
prompt artifact established in P1.4). The prompt explicitly instructs
the reviewer to take a deliberately outside-Claude lens — over-correct
for known Claude biases:

- Over-engineering / premature abstraction.
- Operational/runtime concerns (under-weighted by Claude).
- Missing simpler alternatives.
- Sycophancy / agreeableness.

Output: `docs/process/reviews/<task-id>/R0-B-cross-family.md` (in-family
naming; the **Caveat** section in the body acknowledges the proxy lens
is not a true cross-family review).

### Step 2 — Architect routes proxy findings

If proxy R0-B surfaces findings, architect routes them via
`docs/process/reviews/<task-id>/architect-routing.md` (signal artifact
for senior revision session). Senior absorbs routing; verdict bumps to
`clean` per RC-10 protocol.

### Step 3 — True cross-family R0-B (external; architect-driven)

Architect copies the same prompt + the (revised) artifacts to a
genuinely-non-Claude session (GPT-class / DeepSeek-class / Gemini-class
external LLM). Result is appended to the same `R0-B-cross-family.md` file
under a "True cross-family R0-B review" section (see P1.4's `R0-B-cross-
family.md` post-DeepSeek for the precedent).

The single-file dual-section shape (proxy on top; true cross-family
appended below) preserves audit-trail continuity + makes the verdict
history readable in `verdict_history:` frontmatter.

### Step 4 — Architect routes true-cross-family findings

If true cross-family R0-B surfaces additional findings, architect lands
`docs/process/reviews/<task-id>/architect-routing-<lens>.md` (e.g.,
`architect-routing-deepseek.md`) — sibling artifact to the proxy
routing (NOT superseding). Senior absorbs in another revision pass.

### Step 5 — Verdict bump

Final verdict bump on `R0-B-cross-family.md` per RC-10 protocol.
`verdict_history` grows a fourth entry (post-proxy-routing-absorbed →
post-true-routing-needs-architect → post-true-routing-absorbed →
clean).

---

## Cost (P1.4 empirical)

- Proxy-lens dispatch: in-session via Agent tool. **Cost: ~5-10 minutes**
  of architect time + (subagent token cost, if Agent tool is used)
  OR ~30 minutes via external Claude session.
- True cross-family dispatch: external LLM session (architect copy-pastes
  artifacts + system prompt + reads result). **Cost: ~$2 (LLM API) +
  ~30-40 minutes** of architect time.
- **Total dual-lens cost: ~$2 + ~40-50 minutes** of architect attention.
- **Value (P1.4 measured)**: 4 🔴-class production-bug avoidances on the
  project's most architecturally consequential design decision.

---

## Anti-recommendations

- **Don't blanket-apply dual-lens to all shape-change tasks**. P1.5 is the
  precedent for architect-routed skip. Use the judgment criteria above.
- **Don't substitute proxy for true cross-family on highest-stakes tasks**.
  Proxy lens is bounded by Claude's structural biases; the only way to
  catch what those biases hide is a genuinely-different-family model.
  Proxy-only on P1.4 would have shipped 2 🔴 runtime-integration bugs.
- **Don't dispatch both lenses on integration / pattern-reuse tasks**.
  P1.5 + W-002.5 + P1.5.5 all skip; the marginal value drops sharply
  when the contract is mostly inscribed in existing ADRs.
- **Don't write a separate `R0-B-cross-family-external.md` file**. The
  single-file dual-section shape (proxy + appended-true; per P1.4
  precedent) is the audit-trail-preserving pattern.

---

## Empirical trail

| Task | Shape | Proxy | True cross-family | Result |
|---|---|---|---|---|
| P1.4 | Shape change (multi-agent dispatch) | Yes (in-session subagent) | Yes (DeepSeek V4 Pro external) | 4 🔴 caught + 9 🟡 across both passes |
| P1.5 | Shape change (room state machine) | No (architect-routed skip) | No (architect-routed skip) | R0-A caught Y1; plan-vs-impl caught R1 |
| P1.5.5 (planned) | Integration; not shape change | No (brief skip per RC-15 + P1.5 precedent) | No | TBD at close |

RC-15 graduates from "dual-lens for shape change blanket" to "architect
judgment per task; dual-lens default for shape change unless architect
overrides with explicit reasoning." P1.5 set the precedent for the
override.

---

## Cross-references

- `docs/process/reviews/README.md` — RC-10 verdict-bump protocol (sibling
  process doc; this doc relies on the verdict-bump pattern for the
  multi-routing absorption sequence).
- `docs/process/distance-test.md` — RC-8 graduation (sibling process-doc
  precedent; substrate-canon-as-rule, calendar-pause-as-default).
- `docs/process/reviews/P1.4/R0-B-cross-family.md` — empirical reference
  for the single-file dual-section shape + RC-10 multi-routing-absorption.
- `docs/process/reviews/P1.4/external-r0b-prompt.md` — prompt template
  for true cross-family external LLM dispatch.
- `docs/retrospectives/P1.4.md` §2 — economic analysis of dual-lens R0-B
  on P1.4 (cost ~$2 + 40 min; value 4 🔴 production-bug avoidances).
- `docs/retrospectives/P1.5.md` §4 + §5 — RC-15 refinement after P1.5's
  architect-routed skip; the "architect judgment per task" framing.
