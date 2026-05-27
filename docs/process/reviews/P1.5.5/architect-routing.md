---
task_id: P1.5.5
kind: architect-routing
date: 2026-05-27
reviews_acked:
  - R0-A-on-plan.md
decisions:
  Y1: α (senior pre-pins test fixture capability extension in P1.5.5-1 acceptance)
  Y2: α (senior names + defends 3 reversibility deltas in plan §5 #7)
---

# P1.5.5 architect routing — "ack both leans"

**Architect decisions (this session):** both Y findings resolve to reviewer's lean α. The "pre-investigation gap at plan-revision boundary" pattern from W-003 (Y1+Y2 → α α) repeats at P1.5.5 (Y1+Y2 → α α) — same shape, same routing. Pattern-recurrence threshold for codification is now visibly crossed; capture for retro.

This file is the **signal artifact for the senior revision session**. Senior picks P1.5.5 next, reads this file + `R0-A-on-plan.md` + the current plan, applies the routed actions, pushes a revision commit on `claude/P1.5.5-plan`.

## Per-finding routing

### Y1 → α — Senior pre-pins test fixture capability extension in P1.5.5-1 acceptance

**Action:** plan §2 P1.5.5-1 acceptance updates to specify the `tests/agents/test_integration.py` fixture extension. Current `_make_model` (line 50-58) declares `capabilities=[]` unconditionally; after operator.yaml lands in `config/agents/`, existing integration tests trip `_validate_required_capabilities` because `deepseek_v4_flash` + `qwen_mlx_30b` in the test `_MODELS` registry have no `tools` capability.

**Concrete spec sketch** (senior may refine; the shape is the load-bearing part):

```python
# tests/agents/test_integration.py
from orchestrator.llm.types import ModelCapability

_CAPS_BY_MODEL: dict[str, list[ModelCapability]] = {
    "deepseek_v4_flash": [ModelCapability.TOOLS],
    "qwen_mlx_30b": [ModelCapability.TOOLS],
    "claude_code_opus_47": [ModelCapability.EFFORT],
    "claude_code_sonnet_46": [ModelCapability.EFFORT],
    "claude_code_haiku_45": [],
    "deepseek_v4_pro": [],
}

def _make_model(mid: str) -> ModelProfile:
    return ModelProfile(
        id=ModelId(mid),
        provider=_PROVIDER,
        provider_model_id=mid,
        capabilities=_CAPS_BY_MODEL.get(mid, []),
        context_window=8192,
    )
```

And extend `_models_for_config()` (line 90-97) to include `claude_code_haiku_45` + `qwen_mlx_30b` so the registry covers all 5 promoted agents' chains.

**Senior decides verification path** — verify against actual capability enum (`ModelCapability.TOOLS` import path may be `from orchestrator.llm.types import ModelCapability` or similar; senior reads `llm/types.py` to confirm).

**Plan §5 self-discovery #3 expands** from "`test_loader.py` 2→5 assertion bump" to also cover the `test_integration.py` fixture extension. Removes the impl-time fixture-design burden from junior P1.5.5-1.

**Why α (not skip):** matches W-003 routing pattern discipline gradient (P1.5 Y1 → W-003 Y1+Y2 → P1.5.5 Y1+Y2 — same shape, same routing). The fix is mechanical but the discovery sequence (junior pushes operator.yaml → CI fails → junior reads `_validate_required_capabilities` → junior designs fixture extension → junior pushes again) costs more than the ~10-line plan acceptance update.

### Y2 → α — Senior names + defends 3 reversibility deltas in plan §5 #7

**Action:** plan §5 #7 ("tools.yaml content — pre-investigated; senior pin: PROMOTE `.example` VERBATIM") gets an explicit delta table + a defense clause.

**Spec sketch:**

> **#7 tools.yaml content — pre-investigated; senior pin: PROMOTE `.example` VERBATIM with documented 3-delta-from-brief acknowledgment.**
>
> Existing `tools.yaml.example` contains all entries brief's architect-partner table suggested plus extras (`run_lint`, `git_blame`, `git_log`, `find_references`, `find_definition`, `send_email`, `git_push`).
>
> **Reversibility values mostly match brief leans (9/12)**; 3 deltas exist:
>
> | Tool | Brief lean | `.example` (canonical) | Routing |
> |---|---|---|---|
> | `web_fetch` | 9 | 10 | `.example` wins — earlier ADR-005 D2 architect-approval supersedes |
> | `log_event` | 10 | 8 | `.example` wins — same |
> | `run_tests` | 8 | 9 | `.example` wins — same |
>
> **Defense:** brief's table represents most-recent architect leans (architect-partner authored); `.example` values represent earlier architect approval at ADR-005 D2. Reversibility values are P1.5+ usage-based tuning territory (per `.example` header comment line 1-3); pre-merge value re-litigation buys little over post-merge usage-based re-tune. Promotion verbatim keeps the audit trail clean (no value-touching this PR).
>
> Result: P1.5.5-2 = rename + delete `.example`; no value-touching. Removes any "senior derives reversibility values" risk. Architect explicitly routed α at R0-A (route: senior names + defends the deltas rather than promoting silently).

**Why α (not skip):** the discipline is naming-over-eliding. A future reader tracing "where did `web_fetch=10` come from?" finds the plan §5 #7 table + rationale; without it, they find silence + have to bisect git history to architect's brief lean vs ADR-005 D2 vintage.

## Senior revision actions (derived)

1. **Plan §2 P1.5.5-1 acceptance update**: insert fixture-extension bullet after the existing `test_loader.py` bullet:
   > - `tests/agents/test_integration.py` fixture extends `_make_model` to a caps-aware variant per `_CAPS_BY_MODEL` mapping (deepseek_v4_flash + qwen_mlx_30b declare `tools` capability; claude_code_opus_47 + claude_code_sonnet_46 declare `effort`; claude_code_haiku_45 + deepseek_v4_pro declare `[]`). `_models_for_config()` extends to include `claude_code_haiku_45` + `qwen_mlx_30b`. This unblocks the existing integration tests' `load_agents(_CONFIG_DIR, models=_MODELS)` paths once operator.yaml + divergence_mapper.yaml + logger.yaml land in `config/agents/`.

2. **Plan §5 self-discovery #3 expansion**: rewrite to also cover `test_integration.py`:
   > **S3 (NEW) Existing `tests/agents/test_loader.py` + `tests/agents/test_integration.py` fixture impact** — `test_loader.py` line 114 etc. assume 2 agents (skeptic + prober); promotion to 5 trips count assertion. `test_integration.py` already loads real `config/agents/` dir but its `_make_model` declares `capabilities=[]` unconditionally; promotion trips `_validate_required_capabilities` against operator's `required_capabilities: [tools]`. P1.5.5-1 acceptance pre-pins both fixture extensions (per R0-A Y1 → α architect routing).

3. **Plan §5 #7 rewrite**: per Y2 spec sketch above. Replace single-paragraph claim "values match" with explicit delta table + defense clause.

4. **No ADR-013 edits**: ADR-013 is unchanged. Both Y findings are plan-only.

5. **Plan §3 (execution order) unchanged**: parallelism set [P1.5.5-1 ‖ P1.5.5-2 ‖ P1.5.5-3] still file-disjoint at code level. The `test_integration.py` fixture is touched only by P1.5.5-1 (per the routing); P1.5.5-2 + P1.5.5-3 don't touch it.

6. **Verdict bump on `R0-A-on-plan.md` per RC-10 protocol**: senior edits frontmatter in place after revision lands. `needs_architect → clean`. `findings_count: {red: 0, yellow: 0, green: 10}` (both Y reclassify as 🟢 to document absorption). `verdict_history:` array gets a new entry. Add blockquoted preamble naming the bump + cite this routing artifact.

## Status flips that follow

Once the senior revision pass lands on `claude/P1.5.5-plan`:

- **R0-A-on-plan verdict bumps `needs_architect → clean`** per RC-10 codified protocol (`reviews/README.md` post-`6365cce`; 8th project use).
- **PR opens** for `claude/P1.5.5-plan`; merge brings senior plan + ADR-013 + R0-A + this routing onto main.
- **Architect Accepts ADR-013** post-merge: edits status from `Proposed` → `Accepted` on a follow-up commit (standard ADR-Accept pattern from ADR-008 D5 + W-002-1 single-ADR path β).
- **`workflow advance --task-id P1.5.5`** fires `awaiting_architect_accept → awaiting_junior_impl` (W-002-1 single-ADR path β; 4th use after W-002 + P1.4 + P1.5).
- **Junior dispatches** to `claude/P1.5.5-impl`; **parallelism set [P1.5.5-1 ‖ P1.5.5-2 ‖ P1.5.5-3] runs as 3 parallel agents** per `senior-planner.md` RC-17-codified rule. **First post-RC-17-codification 3-parallel use** (W-003 was 2-parallel; raises the bar).

## Pattern-recurrence note for future plans

P1.5 R0-A Y1 (required-vs-default for `Agent.applies_to`) + W-003 R0-A Y1 + Y2 + P1.5.5 R0-A Y1 + Y2 = **five instances of "pre-investigation gap at plan-revision boundary" pattern**. Same shape every time:
- Senior plan §5 pre-resolves most push-backs + self-discoveries (good discipline; W-003 routing pattern adopted).
- 1-2 items slip through where senior under-investigated OR mis-claimed (e.g., "values match" when 3 deltas exist; "validate_consistency exercises" without naming which test fixture's capability mapping).
- Reviewer (architect-partner R0-A lens) catches at plan stage instead of impl stage.
- Architect routes α α α α α (every instance).

**Five instances** is well past the three-instance codification threshold this routing artifact named in W-003 (`architect-routing.md` line 70-71). **Codification candidate sharpens**: `senior-planner.md` addendum stating:

> When plan §5 self-discoveries / push-back results claim "values match" / "X passes" / "fixture exists" against an external surface (test fixture, existing config, existing ADR), include a verification cite — either a grep result OR an explicit "verified against `<file>:<line>`" annotation. The discipline closes the gap where claims-without-cites become Y findings at R0-A.

Architect may capture in P1.5.5 retro OR commission a small **W-004** brief (pure process refinement; orthogonal to feature work) bundling this codification target + other accumulated process items.

## Out of scope for this routing

- Re-litigating any 🟢 finding from R0-A-on-plan (all 8 confirm plan + ADR-013 structural soundness).
- Re-opening brief's 7 Architect-settled decisions.
- Cross-family R0-B for P1.5.5 — already skipped per brief + RC-15 + P1.5 precedent.
- Codifying the "claims-without-cites" pattern in `senior-planner.md` (W-004 brief candidate OR architect-partner-direct addendum; orthogonal to P1.5.5 impl).
- ADR-013 edits (both Y findings are plan-only).

## Cross-references

- `docs/process/reviews/P1.5.5/R0-A-on-plan.md` — lean source for both Y routings.
- `docs/process/senior-plans/P1.5.5.md` — the file senior revises in absorption pass.
- `docs/decisions/ADR-013-operator-tool-dispatch.md` — unchanged; not touched by either routing.
- `docs/process/reviews/W-003/architect-routing.md` — direct precedent for the Y1+Y2 → α α shape; this routing mirrors it 1:1.
- `docs/process/reviews/README.md` § Post-resolution verdict-bump protocol — RC-10 mechanics for the `needs_architect → clean` bump after senior absorbs routing.
- `docs/process/senior-planner.md` § "Self-organization on session start / resume" — the rule auto-routing senior revision session to this artifact.
- `tests/agents/test_integration.py:45-97` — the surface Y1 references; `_CONFIG_DIR`, `_make_model`, `_models_for_config`.
- `config/tools.yaml.example` — Y2 reference; the source-of-truth for the 3 deltas vs brief table.
