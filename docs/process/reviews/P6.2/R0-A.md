---
task_id: P6.2
kind: R0-A
stage: impl
cycle: 2
surface: product
slice_type: bug-fix (dual-lens; requires_cross_family_review=true)
reviewer: architect-partner
verdict: needs_architect          # cycle-2 rework is correct + gates green + Y1/D1-1 resolved; ONE sign-off: the authorized *delegation* factoring makes the (production-dead) select_model_and_provider EAGER — your "lazy early-stop preserved" verification target is literally NOT met. Impact nil; lean accept-as-shipped.
branch_reviewed: origin/claude/P6.2-impl
commit_reviewed: 2a1d28a
cycle2_delta: 5838ce3..2a1d28a    # the α-rework commit only
supersedes: cycle-1 (verdict needs_architect — Y1 + O1) — this file now covers both cycles
reviewed_against:
  - docs/process/reviews/P6.2/architect-routing-on-impl.md (α bundle: D1-1 factor + Y1 reformat)
  - docs/process/senior-plans/P6.2.md (D-mech-A; D1.2 authorized either factoring)
  - docs/process/reviews/P6.2/plan-vs-impl.md (senior cycle-2 — clean)
gates:                            # independently re-run, fresh --all-extras detached worktree @ 2a1d28a
  ruff_check: pass
  ruff_format: pass on all P6.2-touched files (Y1 RESOLVED); 51 pre-existing untouched files dirty (O1 → task #108)
  mypy_strict: pass (310 source files)
  pytest: pass (full suite, exit 0, ran to 100%, zero failure markers)
  spine: unchanged (full slice = 6 files; _execute_local_call / gate / run_pipeline / COUNTDOWN untouched)
  new_llmpurpose: none (purposes.py not in diff; LLMPurpose.AGENT_RESPONSE in tests = existing-value usage)
---

# P6.2 — impl-stage R0-A (cycle 2, α-rework re-review; dual-lens, architect-partner)

Re-review of the cycle-2 α-rework `2a1d28a` on `origin/claude/P6.2-impl`, against the
architect's impl-stage routing (`architect-routing-on-impl.md`): **R0B-D1-1** (factor the
~140-line duplicated filter logic) + **R0A-Y1** (`ruff format` the C1 test file). Cycle-2 delta
(`5838ce3..2a1d28a`) touches exactly two files: `router.py` (the factor) + `test_openai_compatible_provider.py`
(the reformat). Gates independently re-run in a fresh detached `--all-extras` worktree at
`2a1d28a` (shared tree stayed on `main`, no checkout). C1 + D1 **logic** was found correct +
fail-on-revert at cycle-1 and is untouched this cycle (carried forward, §5).

**Bottom line:** the rework does what was routed. Duplication is **gone**, Y1 is **resolved**,
the full gate is **green**, spine is clean, no new `LLMPurpose`. The senior's cycle-2 plan-vs-impl
(clean) is correct on its lens. **One item for you**, and it is exactly the property your dispatch
asked me to verify ⤵.

---

## Decision for you (30 sec)

> **You asked me to confirm `select_model_and_provider`'s lazy health-check early-stop semantics is unchanged. It is NOT — the authorized delegation makes it eager.**
> The junior took the **delegation** option (`return (await select_viable_routes(...))[0]`), not the
> shared-`_evaluate_candidates`-helper option your cycle-2 dispatch described. Both were authorized by
> your routing (D1.2: "either factoring"). Delegation routes `select_model_and_provider` through
> `select_viable_routes`, which health-checks the **whole** chain — so the old lazy early-stop (return
> at first viable, never touch later providers) is replaced by eager whole-chain health-check.
>
> **Impact: nil.** `select_model_and_provider` is **production-dead** (the adapter now calls
> `select_viable_routes` directly; the only `src/` mentions of the old function are docstrings). Its
> **observable return contract is byte-identical** (model/provider/`model_id_requested` + the
> first-match `decision_trace` snapshot + both `NoSuitableModelError` messages — proven §1, agreeing
> with the senior). The eager *mechanism* is the already-accepted **R0B-D1-2**; cycle-2 merely extends
> it to the dead function. All ~30 `test_router.py` + `test_e2e_fallback` callers + constitution
> suites pass unchanged.
>
> **→ Route:** **α accept-as-shipped** (my lean — authorized, benign, contract-identical, production-dead;
> the duplication is genuinely gone) **vs. β re-do as the shared helper with a `stop_at_first` flag**
> (preserves lazy early-stop on the dead function — but adds code for a function nothing calls).
> I surface; I do not route. No `routing.md` until you call.

---

## 1. R0B-D1-1 — duplication factored (via the authorized *delegation*)

`select_model_and_provider`'s ~155-line filter body is **deleted**; it is now a two-line delegation
(`router.py:132-133`):

```python
routes = await select_viable_routes(agent_config, request, models, providers, override)
return routes[0]
```

`select_viable_routes` (unchanged this cycle) is now the **single home** of the registry →
capability → tools → health_check → accept chain. The cycle-1 duplication (R0B-D1-1 / my cycle-1 N2)
is gone — a future filter fix can no longer silently diverge between the two functions. ✓

**Return-contract byte-identity — independently confirmed (concurs with senior plan-vs-impl §R0B-D1-1):**

| Exit path | Old `select_model_and_provider` | New `routes[0]` via `select_viable_routes` | Faithful? |
|---|---|---|---|
| **Success** | `RouteResult(decision_trace=tuple(candidates))` returned **at first match** | `select_viable_routes` snapshots `tuple(candidates)` into `viable[0]` **at first match**; `tuple(...)` freezes the list there, so later appends don't mutate `viable[0].decision_trace`. `routes[0]` *is* that snapshot. | ✅ byte-identical (same model/provider, `model_id_requested`=chain head, same truncated trace) |
| **Exhaustion** | `raise NoSuitableModelError("no suitable model in chain {effective_chain}", trace)` | same message + same trace shape; propagates through `await`, never reaches `routes[0]` | ✅ identical |
| **Override filtered all** | `raise NoSuitableModelError("global override filtered all models from chain {chain}", trace)` | same message + trace; propagates | ✅ identical |

**No `routes[0]` IndexError**: `select_viable_routes` has an `if not viable: raise NoSuitableModelError(...)`
guard — it never returns `[]`, so `routes[0]` is reached only on a non-empty list. ✓
**Router purity intact**: `select_viable_routes` makes **zero** `provider.call()` (health_check only) —
the delegation does not endanger the constitution's zero-LLM-call routing invariant;
`test_constitution_override_path_makes_no_llm_call` + the `select_model_and_provider`-absent
structural suites pass unchanged. ✓

**The one non-preserved property — lazy early-stop → eager (the Decision-block item).**
The table above is the *return* contract. The *side-effect* contract is **not** preserved:
the old function health-checked **lazily** (returned at the first viable provider, never probing
later ones); the delegated form health-checks the **whole** effective chain (because
`select_viable_routes` does, to collect all routes), then returns `[0]`. Two observable deltas, both
test-invisible and production-irrelevant:
1. **Call count** O(1)→O(N) `health_check()` calls. Negligible per R0B-D1-2's accepted rationale
   (cheap in-memory/subprocess-alive boolean).
2. **A *raising* later `health_check()` now masks a viable earlier route.** Old: primary viable →
   returned, later providers never probed → safe even if a fallback's `health_check()` would raise.
   New: a fallback's raising `health_check()` propagates out of `select_viable_routes` → the viable
   primary is never returned. Reachable only if `health_check()` *raises* (not returns `False`) **and**
   something calls `select_model_and_provider` — nothing in `src/` does.

Why this is the item I flag rather than fold silently: **R0B-D1-2 (accepted) explicitly described
`select_model_and_provider` as the *lazy* one** and accepted eagerness only for `select_viable_routes`.
Cycle-2's delegation **newly extends** eagerness to `select_model_and_provider` — so this is a
behavior change introduced *this cycle*, on precisely the property your dispatch named as the
verification target. It is benign (production-dead + contract-identical), but it is yours to accept,
not mine to bless.

---

## 2. R0A-Y1 — `ruff format` the C1 test file — **RESOLVED**

The three `_make_provider(lambda r: httpx.Response(200, json=_tool_call_response(...)))` calls in
`TestToolCallArgumentsNormalization` collapse from 3-line wrapped form to one line each (fit under
the lockfile-pinned ruff 0.15.12 `line-length=100`) — exactly the drift my cycle-1 R0-A predicted.
Format-only; assertions/bodies untouched. `ruff format --check` on the file is now **clean**
(`already formatted`), and the full-repo dirty count dropped **52 → 51**, confirming the slice now
contributes **zero** residual format drift. ✓

---

## 3. Gates (independently re-run, fresh `--all-extras` detached worktree @ `2a1d28a`)

| Leg | Result |
|---|---|
| `ruff check .` | ✅ `All checks passed!` |
| `ruff format --check` (5 P6.2-touched `.py` files) | ✅ `already formatted` (Y1 resolved) |
| `ruff format --check .` (full repo) | 51 dirty — **all P6.2-untouched** (O1, pre-existing; → task #108) |
| `mypy` (`files = src,tests`) | ✅ `Success: no issues found in 310 source files` |
| `pytest` (full suite) | ✅ **exit 0**, progress reached **[100%]**, **zero** `F`/`E`/`x` markers |

Note on the pytest count: this environment's terminal reporter suppresses the final
`===== N passed =====` summary line under output redirection, so an exact count isn't capturable —
but **exit 0 + 100% progress + zero failure markers** is authoritative for green, and R0-B's cycle-1
run recorded **2516 passed**; cycle-2 changes are a behavior-preserving factor + a test reformat,
which add/remove no tests, so the count is unchanged.

---

## 4. Spine / `LLMPurpose`

Full slice diff = **6 files** (`ADR-002`, `llm_adapter.py`, `openai_compatible.py`, `router.py`,
`test_llm_adapter.py`, `test_openai_compatible_provider.py`). Spine (`_execute_local_call`, autonomy
gate, `run_pipeline`, COUNTDOWN) **not in diff**. `purposes.py` **not in diff** → **no new
`LLMPurpose`** (the `LLMPurpose.AGENT_RESPONSE` occurrences in the diff body are test fixtures *using*
the existing enum value, not new definitions). Cycle-2 delta is `router.py` + one test file only. ✓

---

## 5. Carried forward (already-routed cycle-1 dispositions — not re-litigated)

- **C1 + D1 logic — correct + fail-on-revert** (cycle-1 R0-A §1–§2; R0-B; senior plan-vs-impl). No
  logic touched this cycle. C1: empty/blank tool-args → `{}`, malformed `"{bad"` + missing-key still
  `PermanentProviderError`. D1: transient→next, permanent→propagate, all-transient→`NoSuitableModelError`+trace
  (option **b**), `requested(head) != used(fallback)` audit invariant, no double-actuation, ADR-002 D4
  "Implemented" note accurate (`plan_has_adr=false`, no Accept gate).
- **R0B-D1-2** (eager health_check) + **R0B-D1-3** (fallback trace discarded) — **accept-as-noted** (your
  cycle-1 routing). See §1 for the cycle-2 *extension* of D1-2's eagerness — that extension is the new
  thing; the mechanism itself stays accepted.
- **R0A-O1** (51-file pre-existing format drift) — **separate follow-on, task #108**. Re-confirmed: still
  exactly 51, all P6.2-untouched.

### NITs (non-blocking, FYI — no action expected)
- **N1 (persists).** `llm_adapter.py` module/class docstrings (lines 4, 8, 39) still name
  `select_model_and_provider`; the adapter now calls `select_viable_routes`. Doc-drift only; the
  semantic claim ("routing decided by the router, not the adapter") still holds. Cheap to fold into a
  future touch of that file — not worth a cycle on its own.

---

## 6. Verdict

**`needs_architect`** — the cycle-2 α-rework is substantively **merge-ready**: duplication eliminated
via your authorized delegation, return contract byte-identical (structurally + empirically), Y1
resolved, full gate green, spine clean, no new `LLMPurpose`, constitution invariants intact, and the
senior's plan-vs-impl `clean` is correct on its faithfulness lens. The **single** reason this isn't a
flat `clean` is that your dispatch named "lazy early-stop preserved" as a verification target and it
is **literally not preserved** (delegation = eager) — a cycle-2-new, but benign and production-dead,
behavior change. **Route it α (accept-as-shipped — my lean) or β (re-do as the lazy-preserving shared
helper).** I surface; I do not route.
