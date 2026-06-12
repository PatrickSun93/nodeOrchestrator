---
task_id: P6.2
round: R0-B
verdict: clean
findings_count:
  red: 0
  yellow: 1
  green: 7
reviewed_commits:
  cycle_1: 5838ce3
  cycle_2: 2a1d28a (origin/claude/P6.2-impl)
reviewed_diff: 5838ce3..2a1d28a
surface: product
lens: runtime-integration + failure-mode (cross-family)
---

# P6.2 R0-B — cross-family review, cycle-2 α-rework (factoring verification)

## Lens preamble

This is the **cycle-2** cross-family re-review. The cycle-1 R0-B surfaced D1-1 (duplication) +
D1-2 (eager health_check trade-off) + D1-3 (trace discarded on fallback). The architect
routed D1-1 as **α factor** and D1-2/D1-3 as **accept-as-noted**. The junior's cycle-2
commit (`2a1d28a`) factors the ~140-line duplication by making `select_model_and_provider`
delegate to `select_viable_routes(...)[0]`, and ruff-formats the C1 test file.

The cross-family lens here focuses on **factoring correctness**: does the delegation
preserve both callers' semantics, especially the lazy-vs-eager health_check boundary
that was a cycle-1 🟡 concern? I also re-verify D1's transient fallback invariants
(the adapter loop and `model_id_requested` audit — both untouched in cycle-2).

Gates run in an isolated `--all-extras` worktree at `2a1d28a`: ruff check clean,
mypy clean (310 sources), full pytest suite exit 0, all P6.2-key suites (30 test_router +
1 test_e2e_fallback + 3 test_llm_adapter + 20 test_openai_compatible_provider) pass.
P6.2-touched files are ruff-format-clean (the 51-file pre-existing O1 drift is not P6.2).

## Factoring analysis: delegation to `select_viable_routes(...)[0]`

The junior chose the delegation approach (one of the two options the architect routing
explicitly authorized: "have `select_model_and_provider` delegate to
`select_viable_routes(...)[0]`"). The ~140-line per-candidate filter block is removed
from `select_model_and_provider`; it now delegates to `select_viable_routes` and returns
`routes[0]`. `select_viable_routes` itself is **byte-identical** to cycle-1 (the diff
has a single hunk covering only `select_model_and_provider`).

## Findings

### Y1 — `select_model_and_provider` health_check behavioral drift (lazy → eager)

| ID | Sev | File/Line | Claim | Suggested investigation |
|---|---|---|---|---|
| R0B-D1-Y1 | 🟡 | `router.py:132-133` (`select_model_and_provider` → `select_viable_routes(...)[0]`) | **Delegation changes `select_model_and_provider` from lazy health_check (early-stop on first viable) to eager health_check (full chain scan).** In cycle-1, `select_model_and_provider` iterated the chain and returned on the first candidate that passed all filters including `health_check()` — it never called `health_check()` on fallback providers when the primary was viable. In cycle-2, it delegates to `select_viable_routes` which health_checks **every** provider in the chain, collecting all viable routes before returning `routes[0]`. The **observable output** is preserved identically (same first-viable `RouteResult`, same `decision_trace` contents, same `NoSuitableModelError` on exhaustion, same `model_id_requested`). The **internal cost profile** changes: N health_check calls instead of 1 in the common case. | Architect: confirm the trade-off is acceptable. The architect routing authorized delegation as one of two options; `health_check()` is a cheap in-memory/subprocess-alive boolean per the D-mech-A rationale, and chains are short (2-3 models). If preserving `select_model_and_provider`'s lazy semantics is desired, the alternative approach (a shared `_evaluate_candidates` generator consumed lazily by `select_model_and_provider` and eagerly by `select_viable_routes`) would restore early-stop. |

### Factoring invariants — verified (🟢)

| ID | Sev | What was checked | Result |
|---|---|---|---|
| R0B-D1-G1 | 🟢 | `select_viable_routes` byte-identical to cycle-1 | The diff has a single hunk (`@@ -116,175 +116,21 @@`). `select_viable_routes` is untouched — its per-candidate filter chain (registry → capability → provider → tools → health_check), eager full-scan semantics, and `RouteResult` construction are all unchanged. All cycle-1 D1 invariants that held in `select_viable_routes` continue to hold. |
| R0B-D1-G2 | 🟢 | `select_model_and_provider` observable contract preserved | `routes[0]` carries the same first-viable `RouteResult` with identical `decision_trace` contents (all rejected candidates up to and including the first match, snapshotted at the point the first viable was appended). `model_id_requested` = chain head (`agent_config.default_model`). The exception shape is preserved (`NoSuitableModelError` with identical messages and `decision_trace` shape). The ~30 `test_router.py` callers + `test_e2e_fallback.py` all pass green. |
| R0B-D1-G3 | 🟢 | D1 adapter loop untouched | `llm_adapter.py` is not in the cycle-2 diff. The adapter's transient→next, permanent→propagate, success→return, all-transient→`NoSuitableModelError` semantics are byte-identical to cycle-1 (were correct then, still correct). |
| R0B-D1-G4 | 🟢 | `model_id_requested` ≠ `model_id_used` audit invariant | The adapter loop is unchanged; `RouteResult.model_id_requested` is still the chain head (unchanged in `select_viable_routes`). The cycle-1 verification that `test_transient_primary_falls_to_fallback` asserts `requested != used` still holds (test passes, adapter unchanged). |
| R0B-D1-G5 | 🟢 | Router purity | `select_viable_routes` still makes zero `provider.call()` (unchanged). The `.call()` loop lives in the adapter (unchanged). `router.py:15` invariant holds. |
| R0B-D1-G6 | 🟢 | C1 ruff-format (Y1 from cycle-1) | `tests/llm/test_openai_compatible_provider.py`: 3 test methods reformatted — multi-line `_make_provider(lambda r: ...)` calls collapsed to single-line under `line-length=100`. Ruff-format-clean at `2a1d28a`. No logic change. |
| R0B-D1-G7 | 🟢 | Spine + LLMPurpose | Diff = `router.py` + `test_openai_compatible_provider.py` only. Gate, `_execute_local_call`, `run_pipeline`, COUNTDOWN, `purposes.py` — none in the diff. No new `LLMPurpose`. |

## Gates verification (cycle-2, commit 2a1d28a)

| Gate | Result |
|---|---|
| ruff check | Clean |
| ruff format (P6.2 files) | Clean (both `router.py` + `test_openai_compatible_provider.py` are format-clean; the 51-file O1 drift is pre-existing, not P6.2) |
| mypy (`files = src,tests`) | Clean (310 sources) |
| pytest (full) | Exit 0, all pass |
| P6.2-key suites | 30 test_router + 1 test_e2e_fallback + 3 test_llm_adapter + 20 test_openai_compatible_provider = 54 passed |
| Constitution tests | Pass (all suites) |
| Spine diff | 0-diff |
| `LLMPurpose` grep | No new values |

## Synthesis

The cycle-2 factoring is **correct and behavior-preserving at the observable-contract level**.
All cycle-1 D1 invariants hold; the adapter loop and `select_viable_routes` are untouched.
The single 🟡 advisory (Y1) flags a low-impact internal behavioral drift: `select_model_and_provider`
now does eager health_check via its delegation to `select_viable_routes`, whereas it was lazy
in cycle-1. The architect's routing explicitly authorized the delegation approach; `health_check()`
is a cheap boolean; the observable output is identical. Whether to accept the drift or request
the alternative factoring (shared `_evaluate_candidates` generator) is the architect's call.

No 🔴 findings. The factoring resolved the D1-1 duplication the cycle-1 R0-B flagged.
The cycle-1 D1-2 (eager health_check, now inherited by `select_model_and_provider` too)
and D1-3 (trace discarded) remain at their accept-as-noted disposition.

The cross-family lens does not surface any new runtime-integration failure modes from
the factoring itself — the delegation is structurally straightforward and the observable
contract is provably preserved.
