---
task_id: P2.7
kind: architect-routing
stage: impl
date: 2026-06-02
reviews_acked:
  - R0-A.md
  - R0-B.md
  - plan-vs-impl.md
joint_verdict: needs_architect (R0-A 0🔴/1🟡/11🟢 + plan-vs-impl 0🔴/1🟡/6🟢 [convergent Y1] + R0-B clean; Route B — R0-A governs)
decisions:
  Y1: α (complete the plan-stage Y1→α implementation — S2 kept-unknown-cost decision_trace visibility entry + a discriminating test; the junior implemented the drop-mode trace but missed the keep-mode/default one)
fixer: junior (code/test completion; architect said "不改代码 — junior 补")
---

# P2.7 architect routing — impl stage (Y1 → α; complete the kept-unknown-cost trace)

**Architect decision (this session):** joint **needs_architect** (Route B — R0-A governs). The constitutional core + the security boundary are **fully verified** — c1 (S2 routing) and c2/Y2 (S3 env-inheritance) were **both plant-bypass-PROVEN discriminating** in R0-A (planted `.call` → AST guard + spy both fail; planted strip-regression → 3 env tests fail), gates fully green, no new `LLMPurpose`, S1 pure, allowlist fail-closed. The single item is a **visibility completion**, not a defect in the cruxes.

This file is the **signal artifact for the junior's fix-completion pass** (architect designated junior — a code/test completion). Junior reads this + `R0-A.md` + `plan-vs-impl.md` + the impl, completes Y1, re-runs gates, pushes; verdicts bump per RC-10. **This is the final P2 slice — its close closes P2.**

## Per-finding routing

### Y1 → α — complete the S2 kept-unknown-cost `decision_trace` visibility (the plan-stage Y1→α the junior half-implemented)

**Finding (convergent: R0-A Y1 ≡ plan-vs-impl Y1; R0-B missed it at impl).** The plan-stage Y1→α (this slice's own routing) required that the soft-ceiling never be silent — **every** unknown-cost model met under a set `cost_ceiling` gets a `decision_trace` entry, in **both** policies ("kept-despite-unknown-cost, **or** dropped-as-unknown-cost" — now-Accepted **ADR-023 D2** + plan §2-S2 AC#3b). The impl shipped only the **drop**-mode trace; the **default `keep`** mode emits **no** entry — `override.py` appends the kept-unknown-cost model with no reason, its comment defers it "to the router separately," and the router doesn't implement it (stale comment). So a default soft-ceiling silently keeps an unpriced model with no user-visible signal — and the keep-mode **test is non-discriminating** (asserts only that the model is accepted, not that the trace entry exists — an RC-25 vacuous guard that masked the gap).

**Action (junior — code/test completion):**
- **S2 `apply_global_override`** (`llm/override.py`): when `cost_ceiling` is set and a model's `cost_per_1m_output is None` is **kept** (`on_unknown_cost="keep"`, the default), surface it so the router can record visibility — e.g. return a `kept_unknown` set (or a third trace channel) alongside `(effective_chain, drop_reasons)`.
- **Router** (`llm/router.py`): emit a `decision_trace` / `RouteCandidate` entry recording the kept-unknown-cost models — *"N model(s) with unknown cost (cost_per_1m_output=None) skipped the ceiling check (kept under on_unknown_cost='keep', ceiling=X)"* — so a user reading the route never silently believes an unpriced model was cost-bounded.
- **Fix the stale `override.py` comment** (the "router adds trace entries separately" note) — make it match the implemented behavior.
- **Add a discriminating test** (replace/augment the non-discriminating keep-mode test): `cost_ceiling` set + a `None`-cost model kept → assert the `decision_trace` **contains** the kept-unknown-cost entry (not merely that the model is accepted). Mirror the existing discriminating **drop**-mode test (`test_router.py:532`).
- Re-run gates (`uv run mypy` + pytest stay green).

## The rest — clean (no action)

Both cruxes are **proven**, not just present:
- **c1 (S2)** — `apply_global_override` pure (zero LLM, static attrs); AST guard + spy test **both** catch a planted `.call` (R0-A live plant); no new `LLMPurpose`; composes Layer-3; empty-chain fail-loud. **Constitutional boundary held.**
- **c2/Y2 (S3)** — `_build_child_env` strips parent `ANTHROPIC_BASE_URL` (3 tests catch a planted strip-regression; live at both `subprocess.run` sites); allowlist fail-closed (`ConfigError`); `api_key_env` no-inline. **Security boundary held.**
- **S1** pure scaffold transition tables; **S4** `bootstrap.py` + `render_startup_error` (message-content asserted); **ADR-002/012 amendments** accepted RC-23-safe; gates green incl. `mypy` (173). R0-B clean; plan-vs-impl's other 6🟢.

No ADR/design change — Y1 is completing an implementation the ADR-023 D2 + the plan already specified.

## Junior absorb scope (literal-reading)

The change is the Y1 keep-mode trace completion in `src/orchestrator/llm/override.py` + `src/orchestrator/llm/router.py` + the discriminating test in `tests/llm/test_router.py` (+ the stale-comment fix). **No ADR change** (ADR-023 D2 already requires it — this finishes the impl), no other module, no touch to the proven c1/c2/S1/S4 code. Re-run gates. Architect-deferral literal-reading: forward hooks (LLM-evidence-interpret connector, schema-tighten, etc.) stay deferred — Y1 is the trace completion only. Once Y1 lands (gates green) and verdicts bump per RC-10, the architect re-reviews/accepts → **P2.7 closes → P2 closes.**
