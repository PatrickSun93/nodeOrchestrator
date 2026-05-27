---
task_id: P1.5
kind: architect-routing
date: 2026-05-27
reviews_acked:
  - R0-A-on-plan.md
decisions:
  Y1: β (default, not required — brief lean restored)
  cross_family_r0b: skip (no dispatch this round)
---

# P1.5 architect routing

**Architect decisions (this session):**

- **Y1 → β** (NOT reviewer's lean γ): `Agent.applies_to` is **additive with default `{room_types: ["*"], room_states: ["*"]}`** per the original brief. Senior's "required, no default" choice is reversed; existing skeptic.yaml + prober.yaml + P1.4 test fixtures stay untouched. Brief lean honored; senior over-disciplined.
- **Cross-family R0-B → skip** (option iii from R0-A "Net assessment"): no dispatch this round, neither proxy nor true external. R0-A alone is sufficient pre-merge review. RC-15 narrowly applied — P1.5 is shape change but lower-stakes than P1.4 (no concurrency; sequential dispatch settled; state-machine pattern battle-tested in workflow/).

This file is the **signal artifact for the senior revision session**. The senior session that picks P1.5 next reads:
- This routing file (Y1 + R0-B decisions)
- `R0-A-on-plan.md` (the review)
- Brief + plan + ADR-012 (current state on `claude/P1.5-plan`)

and applies the routed actions without further architect intervention.

## Per-finding routing

| Finding | Routed resolution | Source |
|---|---|---|
| **R0-A Y1** (required vs default for `Agent.applies_to`) | **(β)** `Agent.applies_to: AgentAppliesTo = Field(default_factory=lambda: AgentAppliesTo(room_types=["*"], room_states=["*"]))`. Existing skeptic.yaml + prober.yaml + P1.4 test fixtures NOT updated. New agent yamls (P1.5.5 operator + divergence_mapper + logger) should declare `applies_to` explicitly to opt-out of the default but the default-`["*"]` is safe-fallback for "agent doesn't care which room/state." | Architect choice over reviewer's lean γ. Brief's original lean restored. |
| **Cross-family R0-B** (per RC-15 codified) | **Skip both** (no proxy, no true external). R0-A alone covers; P1.5 shape change is lower-stakes than P1.4; the state-machine pattern is battle-tested in workflow/ (ADR-008 + W-002-1/-2b/-2.5); decisions trace to brief + R0-A coverage. Captured for P1.5 retro as "RC-15 not blanket applied; architect judgment per task." | Architect choice. |

## Senior revision actions (derived)

### ADR-012 revisions

1. **D3 prose update** — replace "Existing skeptic.yaml + prober.yaml gain default `applies_to: {room_types: ["*"], room_states: ["*"]}` — backwards compat; both continue to load" with: "**`AgentAppliesTo` has a class-level `default_factory` producing `{room_types: ["*"], room_states: ["*"]}`**. Existing skeptic.yaml + prober.yaml omit the field; the default applies. New agent yamls declaring specific filters override the default. Backwards compat: every agent yaml that predated this ADR continues to load unchanged." Architect-restored brief lean.
2. **D3 Pydantic snippet update** — `Agent.applies_to` field gains `default_factory`:
   ```python
   class Agent(BaseModel):
       ...
       applies_to: AgentAppliesTo = Field(
           default_factory=lambda: AgentAppliesTo(
               room_types=["*"],
               room_states=["*"],
           )
       )
   ```
3. **D3 Reversibility row** — update from "Medium — switching to required is a Pydantic shape change + agent yaml migration" to "Medium — switching to required (no default) is a Pydantic shape change + agent yaml migration across all extant agent yamls (5 in MVP set)."

### Plan revisions

4. **P1.5-3 acceptance** — remove the "required (no default) — every agent yaml must declare it explicitly" language. Replace with: "`Agent.applies_to: AgentAppliesTo` field has a `default_factory` producing `AgentAppliesTo(room_types=['*'], room_states=['*'])`. Existing skeptic.yaml + prober.yaml DO NOT need updates. P1.4 e2e tests continue to work unchanged (Agent objects without explicit `applies_to` get the default)."
5. **P1.5-3 acceptance** — remove the deferred-to-junior "OR backwards-compat default_factory" alternative; the default-factory is now the architectural choice, not an alternative.
6. **Plan §5 push-back #3** — add a one-sentence reflection: "Brief lean (default with `['*']`) restored after architect routing on R0-A Y1; senior's 'required no default' over-disciplined; the migration cost concession from the brief is preserved."

### Cross-family R0-B disposition

7. **Plan §5 push-back #8 / closer block** — strike the "lean dispatch" recommendation; replace with: "Cross-family R0-B skipped this round per architect routing (RC-15 not blanket applied; architect judgment per task; P1.5 state-machine pattern is battle-tested via workflow/ + RC-15 codified for shape-change but P1.5 stakes are lower than P1.4)."

### No changes needed

- All 7 brief architect-settled decisions stay honored.
- All other push-back dispositions (1, 2, 4, 5, 6, 7) stay as-is.
- All 4 predicted self-discoveries stay surfaced.
- ADR-012 D1, D2, D4, D5, D6, D7 unchanged.
- All other ADR-012 sections (Scope, Context, Considered Alternatives, Consequences, References) unchanged.
- Plan §3 execution order (including the P1.5-4 ‖ -5 ‖ -6 parallelism) unchanged.
- Plan tasks P1.5-1, P1.5-2, P1.5-4 through P1.5-8 acceptance unchanged.

## Status flips that follow

Once the senior revision pass lands on `claude/P1.5-plan`:

- **R0-A-on-plan verdict bumps `needs_architect → clean`** per RC-10 codified protocol (5th project use; pattern stable).
- **PR opens** for `claude/P1.5-plan` → merge → `awaiting_architect_accept` on plan-publish (single-ADR path β via `adr: ADR-012`).
- **Architect Accepts ADR-012** after substrate distance test pause per `docs/process/distance-test.md`.
- **`workflow advance --task-id P1.5`** fires `awaiting_architect_accept → awaiting_junior_impl` cleanly (single-ADR W-002-1 path β; status "accepted" → state advances).
- **Junior dispatches** to `claude/P1.5-impl` per the revised plan; the parallel set P1.5-4 ‖ -5 ‖ -6 is first formal use of the parallelism rule.

## Out of scope for this routing

- Re-litigating any 🟢 finding from R0-A (all 7 confirm clean structural quality; not challenged).
- Re-opening the brief's seven architect-settled decisions.
- Cross-family R0-B for P1.5 — skip is explicit; if architect later wants it, dispatch is a separate action (not retroactive).
- RC-15 amendment / graduation — not codified by this routing; P1.5 retro may capture "RC-15 not blanket-applied; architect judgment per task" as a refinement.

## Cross-references

- `docs/process/reviews/P1.5/R0-A-on-plan.md` — lean source.
- `docs/process/senior-plans/P1.5.md` — file the senior revision session edits.
- `docs/decisions/ADR-012-room-state-machine.md` — Decision 3 prose + code snippet edits.
- `docs/process/architect-briefs/P1.5.md` — brief lean restored (the `Agent.applies_to` is additive constraint).
- `docs/process/senior-planner.md` § "Self-organization on session start / resume" — the rule auto-routing senior revision session to this artifact.
