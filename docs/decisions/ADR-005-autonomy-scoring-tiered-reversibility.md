# ADR-005: Autonomy Scoring — Tiered Reversibility

**Status:** Accepted — 2026-05-19
**Scope:** Governs the P1.2 autonomy gate: how an `Operation` is mapped
to one of three execution tiers, where the configuration lives, and
how the decision is recorded in the event stream. Out of scope: P1.3
Hard Guards (a sibling layer that refuses operations regardless of
score), P1.4+ model-confidence concerns handled inside agent prompts,
and P1.5+ usage-based threshold tuning.

## Context

Every tool call in the orchestrator must pass through a gate that
decides whether the call executes automatically, executes after a
countdown the user can interrupt, or blocks until the user explicitly
confirms. Per handoff §3.1 ("decision paths in code, LLMs generate
content") and Principle 11 ("no ground truth → drift"), this gate
must be pure code. Per the constitutional test
`test_constitution_no_llm_calls_in_autonomy_module`, the autonomy
module is forbidden from importing any LLM SDK; the test is
currently vacuous and becomes load-bearing the moment
`src/orchestrator/autonomy/` is created.

The original handoff §4.3 specified six scoring dimensions
(`reversibility`, `blast_radius`, `data_sensitivity`, `cost_impact`,
`decision_finality`, `user_intent`) and a four-tier output enum
`AutonomyLevel` (`FORBIDDEN`, `APPROVAL_REQUIRED`,
`NOTIFY_AND_EXECUTE`, `AUTO_EXECUTE`). Two weeks of design iteration
(2026-05-05 → 2026-05-19, the 6-day distance test) surfaced two
problems with that shape. First, four of the six dimensions cannot
be reliably quantified per tool type — `blast_radius` and
`cost_impact` in particular vary per call parameters, which the
P1.2-mandated per-type design cannot express. Weighting an
unquantifiable dimension into a sum hides the uncertainty as a
"score", which is exactly the drift Principle 11 warns against. The
architect's working rule made this explicit: "if cannot reliably
quantify, prefer binary trigger over continuous score." Second, the
four-tier enum collapses `FORBIDDEN` and the other three tiers into
the same data path, even though `FORBIDDEN` is categorically
different (refusal regardless of agent or user intent) and belongs
in a sibling layer that runs *before* the scorer.

P1.2's gate must therefore: produce a tier from one objective
dimension (reversibility), keep agent risk-appetite tunable without
mutating the dimension, integrate cleanly with the event store, and
defer all per-parameter and refusal-class concerns to the P1.3
Hard Guards layer. The decisions below converge on a shape that
satisfies these requirements.

## Decisions

### 1. One dimension: reversibility

The P1.2 score is a single continuous value in `[0, 10]` derived
from the tool's `reversibility` field. The other five dimensions
relocate: `cost_impact`, `blast_radius`, `destructive`, and
`external_visibility` move to P1.3 Hard Guards (a sibling layer
expressed as binary triggers, not a continuous score);
`model_confidence` moves to the P1.4+ agent layer where prober and
skeptic already address output-quality questions.

The collapse follows from Principle 11. Of the original six
dimensions, only `reversibility` admits a per-type, parameter-
independent number that a tool author can pick honestly without
guessing per call. The other five either require per-call context
(blast_radius), require subjective project knowledge (cost_impact),
or address output rather than action (model_confidence). Forcing
them into the scorer would manufacture precision that doesn't exist.

### 2. Reversibility lives in `tools.yaml`

Reversibility is a physical property of the tool, not of the agent
calling it. It lives in `config/tools.yaml` as a per-tool, per-type
integer; agents cannot override it. The default for tools missing
the field is conservative-low ("if reversibility cannot be measured,
treat as irreversible"), and this default is enforced at the
**Pydantic Field level** (schema enforcement), not in the scorer's
fallback logic. Schema-level enforcement matches the project's
preference recorded in `feedback_schema_enforcement.md`: install the
invariant at the deepest layer, not by convention.

### 3. Thresholds live in `agent.yaml`

Each agent declares its risk appetite via three fields:
`threshold_auto`, `threshold_confirm`, and `user_intent_modifier`.
Thresholds are subjective and per-agent — they encode "how cautious
is this role", which is exactly the kind of decision that should
not be globally fixed. The placeholder values below are marked
`# PLACEHOLDER (not tuned, P1.5+ usage-based tuning)` in the
example yamls and are explicitly not load-tested:

| Agent | `threshold_auto` | `threshold_confirm` | `user_intent_modifier` |
|---|---|---|---|
| prober | 8 | 5 | 2 |
| skeptic | 8 | 5 | 2 |
| divergence_mapper | 8 | 5 | 2 |
| operator | 6 | 3 | 3 |
| logger | 4 | 2 | 1 |

Operator's lower thresholds reflect that operator is the tool-using
agent — its day job is calling tools, so the bar for `AUTO_EXECUTE`
is set lower and the user-intent modifier is larger.

### 4. Three-tier output enum `AutonomyTier`

The output enum is renamed and reshaped — this is **a semantic
shift, not a pure rename**. The new enum has exactly three values:

- `AUTO_EXECUTE` when `score >= threshold_auto`
- `COUNTDOWN_CONFIRM` when `threshold_confirm <= score < threshold_auto`
- `HARD_CONFIRM` when `score < threshold_confirm`

**[Annotated ADR-040, Accepted 2026-06-07 (P4.6): the COUNTDOWN tier's *consequence* now includes an optional server-side timer (the durable `expires_at` field + in-process sweeper). The tier-decision logic (`decide_tier`) is byte-frozen — COUNTDOWN is still the output of the reversibility scoring, not a timer decision. The timer is a *scheduler over an already-gated COUNTDOWN call*; it actuates, never decides. See ADR-040 for the full design. HARD_CONFIRM never acquires a timer (ADR-040 D2/4a).]**

The old `FORBIDDEN` value is gone — refusal is the Hard Guards
layer's job, not the scorer's. `APPROVAL_REQUIRED` and
`NOTIFY_AND_EXECUTE` collapse into the new tier shape. Future
contributors looking at the old enum should be reoriented by this
ADR rather than reaching for "add `FORBIDDEN` back" as the obvious
move.

### 5. `user_intent` is a threshold modifier, not a dimension and not a router

When the user has issued an explicit instruction that this tool
call satisfies, both thresholds are reduced by the agent's
`user_intent_modifier`:

```
effective_threshold_auto    = threshold_auto    - modifier
effective_threshold_confirm = max(0, threshold_confirm - modifier)
```

Sub-decisions, all binding:

- **(a) Scope.** "User explicit" means text-intent only in P1.2.
  Button-click and GUI affordance contexts (which carry weaker
  intent signal) defer to P1.5.
- **(b) Symmetry.** The modifier subtracts from both thresholds.
  Asymmetric application would create a band where user intent
  promotes a call to `AUTO_EXECUTE` while leaving the
  `HARD_CONFIRM` boundary untouched — a fence guarding nothing.
- **(c) Floor.** `effective_threshold_confirm` is clamped to `0`
  via `max(0, ...)`. A negative value would make `HARD_CONFIRM`
  unreachable for any score, which contradicts Hard Guards'
  existence rationale (some actions must reach the strictest tier
  even with user cooperation). Concrete example: a `git_push`
  (reversibility=1) called by `operator` (modifier=3) with
  `user_explicit_intent=True` lands on COUNTDOWN_CONFIRM, not
  HARD_CONFIRM — Hard Guards (P1.3) is the destructive-action
  refusal layer, not the scorer's HARD_CONFIRM tier. The
  asymmetric absence of a floor on `effective_threshold_auto`
  is intentional: by symmetry, when `user_intent_modifier >=
  threshold_auto`, `eff_auto` can go non-positive and
  `AUTO_EXECUTE` absorbs the full score range. This is the
  AUTO-side counterpart of the `HARD_CONFIRM`-unreachable case
  above — Hard Guards remains the destructive defense regardless
  of which side of the band collapses. Adding a Pydantic
  validator constraining `user_intent_modifier < threshold_auto`
  is deferred to P1.5 tuning unless dogfooding surfaces a real
  misconfiguration (surfaced as P1.2-C3 R0-A-1, architect-resolved
  as narrative-only here).

Modifier-not-dimension is the central call: the *score* is an
objective property of the tool and must not change with who asked.
Only the agent's *threshold* changes, because risk appetite
legitimately depends on whether the user is steering. This split
keeps P1.3 Hard Guards able to refuse user-cooperative requests
("user said delete the database") — Hard Guards reads the score,
not the effective threshold.

### 6. New `EventType` value `autonomy_decision`

`autonomy_decision` is added to `src/orchestrator/core/event.py`'s
`EventType` enum. One event is emitted per autonomy gate
evaluation, **synchronously before tool execution proceeds**.
Metadata carries: a reference to the `Operation`, the computed
continuous score, the chosen `AutonomyTier`, and the full
`DecisionTrace` (rules matched, both raw and effective thresholds,
the `user_intent` flag, modifier applied). The metadata shape is
locked by a new constitutional test
`test_constitution_autonomy_decision_event_carries_trace`, added
in C2 freeze. The synchronous-before-execution ordering is what
makes the event the audit record of the decision rather than a
post-hoc log.

## Considered alternatives

### A. Keep six dimensions, weighted sum

Score every operation across all six original dimensions, combine
via a configurable weight vector. Rejected: four of six dimensions
cannot be honestly quantified per type, so the weighted sum
manufactures false precision. The weights themselves would have
no ground truth — exactly the drift form Principle 11 names.

### B. `user_intent` as a binary router

When the user is explicit, skip scoring entirely and execute. When
not explicit, run the full scorer. Rejected: this collapses the
Hard Guards layer's authority to refuse user-cooperative
destructive calls. The whole point of P1.3 Hard Guards is that
some operations are out of bounds regardless of who asks; a
binary router that defers to user intent removes the layer.

### C. Continuous output (raw 0–10 risk score), no enum

Return the score; let downstream code (or UI) decide what to do
with it. Rejected: the UI has to make a categorical decision
anyway — countdown, hard prompt, or auto — so the discretization
happens somewhere. Pushing it into the scorer keeps the contract
honest (the scorer commits to a tier and records why) and pairs
with `feedback_calibrated_honesty.md`: the function with the
information should make the call, not punt it.

### D. Per-parameter reversibility

Distinguish `git_push` from `git_push --force`. Rejected here but
**deferred, not refused**: P1.3 Hard Guards is the layer for
per-parameter risk. Adding per-parameter scoring in P1.2 would
require an `Operation`-shape change that P1.3 will need to
redesign anyway; the larger drift is worse than the wait.

## Consequences

**Easier:**

- Adding a new tool: one yaml row in `tools.yaml` with
  `reversibility: N`. No code, no scorer change.
- Tuning agent risk appetite: edit three yaml fields per agent.
  No code, no scorer change.
- `decision_trace` on every gate event means "why did this call
  fall to `HARD_CONFIRM`?" is answerable from the event stream
  alone, without re-running the scorer.
- The autonomy module is provably LLM-free
  (`test_constitution_no_llm_calls_in_autonomy_module` is now
  load-bearing).

**Harder:**

- Contributors must learn the two-layer mental model (scorer →
  Hard Guards) once P1.3 lands. Some failures will be the scorer's
  job, others will be Hard Guards' — which is which is not
  obvious from a code search.
- Placeholder thresholds are explicitly not tuned. P1.5 dogfooding
  may surface that, e.g., `operator: auto=6` is too liberal for
  `propose_edit` calls. The placeholders are a known unknown.
- `Operation` (handoff §4.3) now carries P1.3-reserved fields
  (`estimated_cost_usd`, etc.) that look unused in P1.2 — handoff
  §4.3 keeps them with an explicit "consumed by P1.3 Hard Guards"
  comment (per C3's 5-surface scan).

**Neutral:**

- No production caller of the old four-tier `AutonomyLevel` exists
  yet, so the rename to `AutonomyTier` is a clean replacement, not
  a migration. Future readers of git history will see the
  semantic shift recorded here.
- The single-dimension score is numerically identical to the
  `reversibility` value (so far). Future P1.2 follow-ups could
  add normalization or a wrapper without changing the contract.

## Reversibility

| Decision | 6-month reversal cost |
|---|---|
| 1. One dimension (reversibility-only) | Medium — adding a dimension back requires re-deriving the weight question, updating tools.yaml schema, and re-justifying past tuning. Recoverable but not cheap. |
| 2. Reversibility in `tools.yaml` | Medium — moving the field to agent-level would invert the project-vs-agent split and require migration of every tool entry. |
| 3. Thresholds in `agent.yaml` (placeholders) | Trivial — the placeholders are *expected* to be retuned via P1.5 dogfooding; retuning is one yaml edit per agent. |
| 4. Three-tier `AutonomyTier` enum | Expensive — once UI and event-stream consumers depend on the tier names, adding a fourth tier (e.g., reintroducing `FORBIDDEN`) propagates through every consumer and breaks event-stream replay of prior decisions. |
| 5. `user_intent` as modifier | Low — switching to a binary router is a contained scorer change, but invalidates prior `decision_trace` records and forces re-statement of the Hard Guards contract. |
| 6. `autonomy_decision` EventType | Expensive — once event-stream records exist, removing or renaming the type breaks replay forever; per `docs/architecture/event-model.md`, EventType additions are constitutional. |

## References

- `handoff.md` §3.1 (decision paths in code), §4.3 (`Operation`,
  old `AutonomyLevel` — to be updated in C3), §7 P1.2 (detailed
  design narrative, 2026-05-19 land).
- `docs/architecture/event-model.md` — EventType extension
  precedent; this ADR registers `autonomy_decision`.
- `docs/architecture/test-coverage-standard.md` — six-category
  coverage standard applied to C3 and C4 implementations.
- `docs/contributing.md` Q1 (no LLM calls), Q2 (`decision_trace`
  obligation), Q3 (5-surface scan triggered by C2/C3/C4).
- ADR-001 (event store foundation) — establishes the EventType
  enum and the "adding a type requires an ADR" rule that this ADR
  satisfies.
- ADR-006 (unknown tool_id semantics) — refines Decision 2 by
  distinguishing registry-miss (raises `UnknownToolError`) from
  missing-field (Pydantic default 0). Landed in C3 alongside
  the §5(c) narrative revision above.
- ADR-007 (autonomy_refusal event type) — adds the `AUTONOMY_REFUSAL`
  event type and `AutonomyRefusalMetadata`; extends Decision 6 audit
  obligation to the registry-miss path. Landed in C4.
- Implementation entry point: C2 freeze commit (P1.2 interface
  freeze), to follow this ADR upon acceptance.
- **P5.1c note (ADR-043):** The gate logic (`score` / `decide_tier` /
  `emit_gate_decision`) is byte-frozen across P5.1c. The pipeline-email
  actuator is a **post-gate actuation-authorization layer** — it actuates
  a `TOOL_CALL_PENDING` the gate already produced (HARD tier, `expires_at=None`),
  without re-tiering or altering the gate decision. `send_email`'s HARD tier
  (reversibility=3 < all pipeline `threshold_confirm` values) is unchanged.
