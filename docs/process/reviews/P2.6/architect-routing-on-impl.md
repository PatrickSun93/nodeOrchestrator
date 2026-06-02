---
task_id: P2.6
kind: architect-routing
stage: impl
date: 2026-06-01
reviews_acked:
  - R0-A.md
  - R0-B.md
  - plan-vs-impl.md
joint_verdict: needs_architect (R0-A 0🔴/1🟡/10🟢 + R0-B clean + plan-vs-impl clean; Route B — R0-A governs; the single 🟡 is Y1)
decisions:
  Y1: α (align the first producer's LLM-call pattern to the established sync + typed LLMRouterProtocol convention — agents/dispatch + reentry/render; no async color, no Any; sets the producer-LLM-call template)
fixer: junior (code/test fix; architect said "不要改代码 — junior 修")
---

# P2.6 architect routing — impl stage (Y1 → α; pattern-setting)

**Architect decision (this session):** joint verdict **needs_architect** (Route B — the mandatory R0-A governs; the single 🟡 is Y1). The constitutional core is fully held + structurally enforced — **both c1/c2 AST guards were plant-bypass-verified discriminating in R0-A** (live real-source plants: c1 caught `run_matcher` in `tagging.py:80`, c2 caught `ExternalValidationMeta(...)` in `dataset_check.py:52`; both pass post-revert), and r0b R0-B independently active-cleared c1/c2/the emit path/B3/the e2e. Gates fully green (incl. `mypy --strict` — the P2.5 R1 lesson learned). The one item resolves **without** touching the boundary.

This file is the **signal artifact for the junior's fix pass** (architect designated junior — a code/test fix). Junior reads this + `R0-A.md` + the impl, applies the fix, re-runs gates to green, pushes; verdicts bump per RC-10.

## Per-finding routing

### Y1 → α — align the first producer's LLM-call pattern to the sync + typed `LLMRouterProtocol` convention

**Finding (R0-A Y1):** `propose_hypothesis_tags` (`producers/tagging.py:47`) deviates from the project's established LLM-call convention on three axes — it's **`async`** (`await llm_provider.call(...)`, :105) vs the project's sync posture (ADR-011 D1, "no async color yet"); it calls the **provider directly** (with a sentinel model profile) vs the **router**; and it types the LLM handle **`Any`** (:51) vs a typed Protocol. `agents/dispatch.py` (:45/:116) and `reentry/render.py` (:26/:71) both use a **sync, typed `LLMRouterProtocol`** with `llm_router.call(request)`. Not a constitutional breach (the call is still content-gen `HYPOTHESIS_TAG_PROPOSAL`) or a gate failure — but **P2.6 is the first producer, so this sets the producer-LLM-call template** every future producer (P2.7+, the deferred LLM-evidence-interpret connector, etc.) will follow. The architect ruled it aligned **now** (cheap to align one; expensive to re-align N later) — no async color, no `Any`.

**Action (junior — code/test fix):**
- Change `propose_hypothesis_tags` to take a typed **`llm_router: LLMRouterProtocol`** (sync; mirror `reentry/render.py`'s local `Protocol`) instead of `llm_provider: Any`.
- Make it **`def`** (sync): `response = llm_router.call(request)` instead of `async def` + `await llm_provider.call(request, model, model_id_requested=...)`.
- Drop the sentinel `_TAG_MODEL_PROFILE` + the `model=` param (the router resolves the model, as agents/reentry do).
- Keep the `LLMRequest(purpose=LLMPurpose.HYPOTHESIS_TAG_PROPOSAL, …)` construction (the content-gen purpose is correct — unchanged).
- Update `tests/producers/test_tagging.py` to pass a **sync mock router** (the agents/reentry test idiom) instead of a `MockProvider`.
- Re-run gates to green (`uv run mypy` must stay clean — no `Any`).

**This is the producer-LLM-call template** — record the sync-typed-router pattern as the convention so P2.7+ producers follow it (not a coin-flip).

## The rest — clean (no action)

- **c1/c2 constitutional boundaries: held + structurally enforced + doubly verified.** R0-A plant-bypass-tested both guards (live, real-source — discriminating, not vacuous); r0b R0-B active-cleared c1 (content-gen tagging, no selection symbols, cross-room backstop), c2 (`evidence_ref`-anchored emit helper, sole construction site, `EventStore.append`), B3 (no status mutation + fail-loud canary), and the discriminating e2e. **plan-vs-impl: clean. R0-B: clean.**
- **No ADR-022/code change beyond Y1's producer fix.** The guards, the emit helper, B3, the e2e, the retro-tag-update (overwrite) all stand. `evidence_ref` stays `str|None` (no closed-ADR-019 edit). Forward hooks (LLM-evidence-interpret connector + `EXTERNAL_EVIDENCE_INTERPRET`, schema-tighten, reject actuator, multi-source) remain deferred — do NOT bundle.

## Junior absorb scope (literal-reading)

The **only** change is the Y1 producer-pattern alignment in `src/orchestrator/producers/tagging.py` + `tests/producers/test_tagging.py` (sync + typed `LLMRouterProtocol`, drop `Any`/sentinel-model). No ADR change, no other module. Re-run gates (esp. `uv run mypy`). Architect-deferral literal-reading: the forward hooks above stay deferred — Y1 is a pattern alignment, not a license to refactor the producer layer.
