---
task_id: P6.2
round: plan-vs-impl
cycle: 2
reviewer: senior
verdict: clean                    # cycle-2 α-rework faithful: D1-1 factor is behavior-preserving (delegation preserves all 3 exit paths byte-identically), Y1 ruff-format resolved, full gate green. C1+D1 logic unchanged from cycle-1's faithful baseline.
findings_count:
  blocking: 0
  yellow: 0
  green: 1
reviewed_commit: 2a1d28a
reviewed_branch: origin/claude/P6.2-impl
cycle2_delta: 5838ce3..2a1d28a    # the α-rework commit only
plan: docs/process/senior-plans/P6.2.md
routing: docs/process/reviews/P6.2/architect-routing-on-impl.md
surface: product
lens: plan-vs-deliverable faithfulness (senior's non-overlapping audit surface)
supersedes: cycle-1 (verdict needs_architect, Y1) — this file covers both cycles
---

# P6.2 — senior plan-vs-impl review (cycle 2, α-rework re-review)

## Lens + scope

Senior **plan-vs-impl** lens: does the impl faithfully realize the plan I wrote
(`docs/process/senior-plans/P6.2.md`)? This cycle-2 re-review covers the **α-rework
delta only** (`5838ce3..2a1d28a`, the single commit `2a1d28a`), against the architect's
routing (`architect-routing-on-impl.md`): **R0B-D1-1** (factor the duplicated filter
logic) + **R0A-Y1** (`ruff format` the C1 test file). The cycle-1 C1+D1 logic baseline
(`bf7c9c9`, `5838ce3`) was already found **faithful** and fail-on-revert-verified — that
assessment stands unchanged and is recorded in §"Cycle-1 baseline" below; this cycle only
adjudicates whether the rework is **behavior-preserving** and whether it broke anything.

**Cycle-2 delta touches exactly two files** — `src/orchestrator/llm/router.py` (the factor)
and `tests/llm/test_openai_compatible_provider.py` (the reformat). **Zero plan-外 expansion**;
`purposes.py` untouched (no new `LLMPurpose` — grepped the delta); no spine change; no ADR
change; no stray `.workflow/` self-advance commit on the impl branch.

---

## R0B-D1-1 — factor the duplicated per-candidate filter logic (`2a1d28a`)

The junior chose the **delegate** factoring the plan explicitly sanctioned (D1.2: "or have
`select_model_and_provider` delegate to `select_viable_routes(...)[0]`"). The ~155-line
duplicated body of `select_model_and_provider` is deleted; the function is now a two-line
delegation:

```python
routes = await select_viable_routes(agent_config, request, models, providers, override)
return routes[0]
```

`select_viable_routes` (the cycle-1 code, **unchanged** this cycle) is now the single home of
the registry → capability → tools → health_check → accept filter chain.

**Behavior-preservation proof** — the delegation preserves `select_model_and_provider`'s
observable contract on **all three exit paths**, byte-identically:

| Exit path | Old `select_model_and_provider` | New (delegate to `select_viable_routes[0]`) | Faithful? |
|---|---|---|---|
| **Success** | returns `RouteResult(decision_trace=tuple(candidates))` **at the first match** — returns immediately, so the trace stops at the matched candidate | `select_viable_routes` snapshots `tuple(candidates)` into `viable[0]` **at the first match** (before walking the rest of the chain); `tuple(...)` freezes the running list at that instant, so later appends don't mutate `viable[0].decision_trace`. `routes[0]` is exactly that first-match snapshot. | ✅ byte-identical (same model, provider, `model_id_requested`=chain head, same truncated trace) |
| **Exhaustion** (all rejected) | `raise NoSuitableModelError(f"no suitable model in chain {effective_chain}", decision_trace=…)` | `select_viable_routes` raises the **same** message + same trace shape; propagates through `await` — never reaches `routes[0]` | ✅ identical |
| **Override filtered all** | `raise NoSuitableModelError(f"global override filtered all models from chain {chain}", …)` | `select_viable_routes` raises the **same** message + trace; propagates | ✅ identical |

**No `routes[0]` IndexError risk**: `select_viable_routes` has an `if not viable: raise
NoSuitableModelError(...)` guard, so it **never returns an empty list** — it either returns
≥1 route or raises. The delegation can only reach `routes[0]` when `viable` is non-empty. ✅

**D-mech-A semantics intact** (my §5 design call):
- **Router still pure** — `select_viable_routes` makes **zero** `provider.call()` (health_check
  only); the factor moved no `.call()` into the router. `router.py:15` invariant holds; the
  constitution suites (`test_constitution_override_path_makes_no_llm_call` + the
  `select_model_and_provider`-absent structural tests across `tests/{llm,mcp,plugins,tools}`)
  pass unchanged.
- **Adapter loop untouched** this cycle (`llm_adapter.py` not in the delta) — the call-time
  fallback iteration, exhaustion → `NoSuitableModelError`, and `requested(head) != used(fallback)`
  audit invariant are exactly as ratified in cycle-1.
- **`async def` preserved** — `select_model_and_provider` is still `async`, signature unchanged;
  its 30+ `test_router.py` callers + constitution refs untouched.

**Back-compat empirically confirmed**: `tests/llm/test_router.py` + `test_e2e_fallback.py`
(the ~30 callers exercising the exact first-viable `RouteResult` + `decision_trace` + exhaustion
contract) pass **unchanged** on the reworked code. The contract-preservation argument above is
thus both structural (the trace-snapshot reasoning) and empirical (the caller suite).

This resolves the cycle-1 🟢-1 latent-divergence note: the filter logic now lives in **one**
place, so a future filter change can no longer silently diverge between the two functions.

---

## R0A-Y1 — `ruff format` the C1 test file (`2a1d28a`)

The three `_make_provider(lambda r: httpx.Response(200, json=_tool_call_response(...)))` calls
in `TestToolCallArgumentsNormalization` are collapsed from three-line wrapped form onto one
line each (they fit under the lockfile-pinned ruff 0.15.12 `line-length=100`). **Format-only,
zero behavior change** — assertions and test bodies untouched. This resolves cycle-1 **Y1**.

Verified in a fresh `--all-extras` worktree on `2a1d28a`: `ruff format --check` is now **clean**
on both touched files (`2 files already formatted`).

---

## Gate (fresh `--all-extras` worktree on `2a1d28a`)

| Leg | Result |
|---|---|
| `ruff format --check` (touched files) | ✅ clean (Y1 resolved) |
| `ruff check src tests` | ✅ `All checks passed!` |
| `mypy src tests` | ✅ `Success: no issues found in 310 source files` |
| `pytest` (full suite) | ✅ exit 0 |
| targeted: router / e2e_fallback / llm_adapter / openai_compatible / constitution ×4 | ✅ 105 passed |

The plan §4 forcing function ("full gate green: ruff + mypy + pytest") is now **met** — the
single leg that failed at cycle-1 (`ruff format`) is green.

---

## Findings

No blocking, no yellow. One 🟢 informational (carried from cycle-1, now partially retired):

- **🟢-2 (informational, unchanged).** With the adapter on `select_viable_routes`,
  `select_model_and_provider` has **no `src/` caller** — but it is **not dead code**: it is the
  single-route public contract exercised by ~30 `test_router.py` callers + constitution refs,
  deliberately preserved (plan §5 back-compat). After the factor it is now a thin delegating
  wrapper over `select_viable_routes`, which is the strongest possible expression of that
  back-compat intent. Noted only so a future reader doesn't mistake the wrapper for redundancy.

(Cycle-1 🟢-1 DRY/latent-divergence is **retired** — the duplication it flagged is gone.)

---

## Cycle-1 baseline (unchanged, recorded for the audit trail)

C1 + D1 **logic** was found faithful at cycle-1 and remains so (no logic touched this cycle):
- **C1** — empty/blank tool-args string → `{}`; malformed `"{bad"` + missing-key still
  `PermanentProviderError` (scope boundary held); fail-on-revert independently re-run.
- **D1** — D-mech-A (router exposes ordered viable routes; adapter iterates); transient→next,
  permanent→propagate, all-transient→`NoSuitableModelError`+trace (option **(b)**);
  `requested(head) != used(fallback)` audit invariant by construction; ADR-002 D4 "Implemented"
  note matching the agy-cli precedent weight (`plan_has_adr=false`, no Accept gate);
  fail-on-revert independently re-run. No same-provider retry, no `.call()` in the router.

The accepted-as-noted items (R0B-D1-2 eager health_check; R0B-D1-3 trace-discarded-on-fallback)
and the separate follow-on (R0A-O1 51-file format drift → task #108) are the architect's routing
dispositions and are **not** re-litigated here.

---

## Verdict: `clean`

The cycle-2 α-rework **faithfully** executes the architect's routing. The D1-1 factor is
**behavior-preserving** — the delegation preserves `select_model_and_provider`'s observable
contract byte-identically on all three exit paths (proven both structurally via the
`tuple(candidates)` first-match snapshot and empirically via the unchanged caller suite), with
no IndexError risk, no `LLMPurpose`, and the D-mech-A router-purity + adapter semantics intact.
The Y1 ruff-format is resolved; **full gate is green**. No plan-外 expansion. The single cycle-1
gap (Y1) that moved the verdict off `clean` is closed, and the cycle-1 DRY note is retired by the
factor. **P6.2 is ready to merge.**
