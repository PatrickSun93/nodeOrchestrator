---
task_id: P5.1b
stage: impl
review: R0-A (architect-partner, impl-stage) — cycle-2 re-review
actor: architect-partner
cycle: 2
lens: "Lens A = scheduler safety + headless-initiation correctness; Lens B = spine + auto-fire no-regression; cycle-2 = all-α rework resolution + empirical fail-on-revert"
verdict: needs_architect
date: "2026-06-09"
reviewed_branch: origin/claude/P5.1b-impl
reviewed_at: cf8680a
supersedes: "cycle-1 R0-A @ a7e485c (same path): A1 must-fix + A2/A3 🟡 + A4/A5/A6 🟢, needs_architect"
plan: docs/process/senior-plans/P5.1b.md
adr: ADR-042
routing_absorbed: docs/process/reviews/P5.1b/architect-routing-on-impl.md   # all-α, cycle-2
peer_reviews:
  - docs/process/reviews/P5.1b/plan-vs-impl.md   # senior cycle-2, verdict CLEAN @ cf8680a
read_method: "git diff a7e485c..cf8680a (cycle-2 delta) + origin/main...cf8680a (full); no checkout — shared worktree, stayed on main; gates + empirical fail-on-revert in isolated detached worktree @ cf8680a (uv sync --all-extras)"
gates:
  ruff: pass (All checks passed!)
  mypy: pass (Success: no issues found in 304 source files — files=src,tests)
  pytest: pass (2424 passed, exit 0; +6 vs cycle-1 2418; 2 pre-existing unrelated warnings — starlette/httpx deprecation + tests/tools/test_net_trust.py DNS-timeout thread warning)
cycle1_resolution:
  A1-IDOR: RESOLVED — guard in both verbs; fail-on-revert EMPIRICALLY CONFIRMED (neutralized guard → DELETE 204 / PATCH 200 land on the cross-pipeline schedule)
  A2-docstring: RESOLVED — docstring rewritten to match the reordered code
  A3-orphan-loop: RESOLVED — claim moved before the state-gate; fail-on-revert EMPIRICALLY CONFIRMED (early-return → next_fire stays == old)
  A4-ast-coverage: RESOLVED — new test_schedule_act_on_writer_does_not_call_countdown_spine
  A5-get-404: RESOLVED — GET on missing pipeline now 404 + test
  A6-index: RETAINED — store.py:55 partial index untouched in cycle-2
  Y3-split-try: PRODUCTION RESOLVED; TEST does not fail-on-revert (see B1)
findings:
  - id: B1
    severity: yellow
    atomic: P5.1b cycle-2 (Y3 test)
    title: "Y3 split-try is correct in production, but test_act_create_run_fails_after_successful_run_does_not_raise does NOT fail-on-revert — the cycle-1 single-try still passes it (empirically confirmed). Test-only, production-correct, low-stakes (the delta is logging fidelity)."
  - id: B2
    severity: green
    atomic: ADR-042 D4 (doc text)
    title: "ADR-042 D4 step-2 literal text still reads 'missing (deleted) → log + skip' (no advance), now trailing the ratified advance-on-missing code. Architect already ruled no-amendment at routing — flagging the code-vs-inscribed-text gap for an optional one-line D4 sync."
---

# R0-A impl-stage — P5.1b cycle-2 re-review (recurring pipeline scheduler)

Independent architect-partner **re-review** of the all-α cycle-2 rework on
`origin/claude/P5.1b-impl` @ `cf8680a` (cycle-2 delta = `app.py` + 2 test files, +177/−23),
against the cycle-1 findings (`R0-A.md` @ `a7e485c`, this path), the absorbed routing
(`architect-routing-on-impl.md`: **all-α, one rework cycle**), the plan, and **ADR-042 (Accepted)**.
Read on `main` via `git diff` (no checkout — shared worktree); canonical gates **and** targeted
**empirical fail-on-revert** run in an isolated detached worktree @ `cf8680a` (`uv sync --all-extras`).

> State note: the dispatch named `awaiting_senior_plan_vs_impl`; during this review the senior's
> **cycle-2 plan-vs-impl landed `clean` @ cf8680a** and the state advanced to **`awaiting_R0_A`** — so
> this R0-A is in-order, not out-of-band.

**Bottom line.** The cycle-2 rework **resolves all seven cycle-1 findings**, and the must-fix
authorization gap (**A1 cross-pipeline IDOR**) is closed with a guard whose test I **empirically
confirmed fail-on-revert** (neutralize the guard → the cross-pipeline DELETE returns 204 and PATCH
returns 200, i.e. the mutation lands on the other owner's schedule). The constitution still holds —
countdown spine **byte-identical** to `origin/main` (AST-verified), `run_pipeline` byte-unchanged,
`countdown_auto_fire=None` preserved, **no new `LLMPurpose`**, **no ADR amendment in the diff**, all
three gates green (2424 passed). Two **non-blocking** items route the verdict to `needs_architect`:
**B1** — the Y3 split-try test does not fail-on-revert (the production fix is correct; only its test
is weak); **B2** — a 🟢 code-vs-ADR-text gap the architect already pre-ruled. Neither is a correctness
or safety regression.

---

## Cycle-1 findings — resolution (all seven)

| # | cycle-1 (sev) | cycle-2 fix | Verified |
|---|---|---|---|
| **A1 / PVI-1** | 🟡 **must-fix** IDOR | `if sched.pipeline_id != pipeline_id: raise HTTPException(404)` in **both** `_delete_schedule` (app.py:2107) and `_patch_schedule` (app.py:2156), after the `get_schedule` fetch; 404 reuses the "schedule not found" detail (no existence oracle) | ✅ **empirical fail-on-revert** (below) |
| **A2 / Y1** | 🟡 docstring | `_schedule_act_on_writer` docstring (steps 2–5) rewritten: "fetch pipeline → **always claim** → skip run if missing/disabled (next_fire already advanced)" — now matches the reordered body | ✅ read |
| **A3 / Y2 / PVI-3** | 🟡 orphan loop | claim (`update_schedule_next_fire`) moved **before** the missing/disabled gate, so **missing also advances next_fire** → orphan re-discovered once per interval, not every tick | ✅ **empirical fail-on-revert** (below) + `test_act_missing_pipeline_advances_next_fire_no_run` |
| **A4** | 🟢→α AST coverage | new `test_schedule_act_on_writer_does_not_call_countdown_spine` — AST-walks the **act** fn, asserts zero calls to the 3 spine symbols (fails-on-introduce) | ✅ read |
| **A5 / PVI-4** | 🟢→α GET 404 | `_list_schedules` raises 404 on missing pipeline (was `[]`) + `test_list_schedules_missing_pipeline_404` | ✅ read (fail-on-revert by construction: `[]`→200≠404) |
| **A6 / PVI-2** | 🟢→α index | partial index `idx_pipeline_schedules_due` untouched in cycle-2 (store.py:55) — confirmed retained | ✅ grep |
| **Y3** | 🟡 audit gap | try split: `run_pipeline` (fail → log + `return`) then `create_pipeline_run` in a **separate** try (fail → warning, does **not** discard the run; the success info-log still fires) | ⚠️ **production correct**, but the **test is not fail-on-revert** → **B1** |

### Empirical fail-on-revert (isolated worktree @ cf8680a)

I reverted each must-rework fix in turn and re-ran its test:

| Fix reverted | How | Test result | Reading |
|---|---|---|---|
| **A1** guard → `if False` | both verbs neutralized | `test_delete…idor_404` → **assert 204 == 404 FAIL**; `test_patch…idor_404` → **assert 200 == 404 FAIL** | guard genuinely closes the IDOR; the cross-pipeline DELETE/PATCH **succeeds** without it (the run lands on `S_other`) |
| **A3** missing early-return before claim (cycle-1 behavior) | re-inserted `if pipeline is None: return` pre-claim | `test_act_missing…advances` → **assert next_fire > old FAIL** (`1699999999999 > 1699999999999`) | advance-on-missing genuinely breaks the every-tick loop |
| **Y3** merged back to cycle-1 single-try | one `try` over run+create+info, one `except` | `test_act_create_run_fails…` → **STILL PASSES (exit 0)** | the test does **not** distinguish the fix from the bug → **B1** |

A1 and A3 are airtight: their tests fail without the fix. The worktree was restored to `cf8680a`
(clean) after each revert.

---

## New findings

### B1 — 🟡 Y3 split-try test does not fail-on-revert (production-correct, test-only)

The Y3 production fix is **correct** — `run_pipeline` and `create_pipeline_run` are now in separate
`try`s, so a `create_pipeline_run` failure after a successful run logs a truthful warning
("run %s succeeded") and the success info-log still fires, instead of the cycle-1 single-`try` that
mislabeled it "run_pipeline failed". I verified the structure by reading app.py:688–727.

But `test_act_create_run_fails_after_successful_run_does_not_raise` only asserts (a) the call does not
propagate and (b) `next_fire` is advanced — **both of which already held under the cycle-1 single-try**
(the shared `except` also swallowed the exception, and the claim already ran before the run in both).
I confirmed this empirically: **reverting to the single-try still passes the test.** So a future
re-merge of the two `try`s would silently regress the logging honesty without turning the suite red —
a test that *looks* like it guards the split but doesn't (false fail-on-revert confidence).

**Stakes are low** — the behavioral delta between cycle-1 and cycle-2 here is purely **logging
fidelity** (in both, the run's room events persist and the `pipeline_runs` index row is absent because
`create_pipeline_run` failed). The routing framed this test as "if cheaply mockable" (best-effort).
**Surfaced, not self-routed:** the natural α is a one-line strengthen (assert via `caplog` that the
"run … succeeded" / "create_pipeline_run failed" message fires and the misleading "run_pipeline
failed" does **not**); the architect may equally accept-as-noted given the production fix is correct
and the stakes are logging-only.

### B2 — 🟢 ADR-042 D4 step-2 text now trails the ratified code (architect already pre-ruled)

ADR-042 D4 step-2 (line 199) still reads: *"If the pipeline is **missing** (deleted) → log + skip. If
`pipelines.enabled=0` → skip the run **but still advance next_fire**"* — i.e. the inscribed text grants
the advance only to the **disabled** case. The A3 fix now advances on **missing** too. The architect's
cycle-2 routing **already ruled "no ADR-042 amendment … A3's advance-on-missing matches D4's re-arm
intent"**, so the behavior is ratified; I am only flagging that the **literal** D4 step-2 sentence is
now the one spot where the inscribed contract trails the shipped code (the same doc-vs-code shape as
the A2 in-code docstring that *was* synced this cycle, one level up at the ADR). **No behavioral
implication; your call** whether a one-line D4 text-sync is worth it or the routing's intent-match
stands. Not blocking.

---

## Constitutional / Lens-B re-confirmation (independent)

| Invariant | Verification (my run) | Status |
|---|---|---|
| countdown spine byte-frozen | AST-extracted `_countdown_sweeper` / `_writer_approve_helper` / `_discover_expired_pendings` from `origin/main` vs `cf8680a` → **byte-identical** (2378b / 3540b / 1883b) | ✅ |
| gate + `_execute_local_call` + `run_pipeline` zero diff | `autonomy/`, `tools/executor.py`, `pipeline/runner.py` absent from the full diffstat; cycle-2 delta touches only `app.py` + 2 tests | ✅ |
| `countdown_auto_fire=None` preserved | runner untouched; scheduler is a second caller, passes no kwarg | ✅ |
| no new routing `LLMPurpose` | grep clean on the cycle-2 diff (`^\+.*LLMPurpose` → none) | ✅ |
| no ADR amendment in the diff | cycle-2 touches **zero** `docs/` files (name-only confirms `app.py` + 2 tests) | ✅ |
| A1 fix faithful to ADR-042 D9 | guard binds the mutation to `sched.pipeline_id` ("owner of the **parent** pipeline only", D9) — the fix *realizes* the inscribed intent | ✅ |
| gates | ruff *All checks passed!* · mypy *304 files, no issues* · pytest **2424 passed** (exit 0) | ✅ |

Senior cycle-2 plan-vs-impl independently returned **`clean`**; my lens adds the empirical
fail-on-revert pass (which surfaced B1, outside the plan/ADR-faithfulness lens).

---

## Verdict: `needs_architect`

All seven cycle-1 findings are **resolved**; the must-fix **A1 IDOR is closed and fail-on-revert
confirmed empirically**; the constitution holds (spine byte-frozen, `run_pipeline` unchanged,
`countdown_auto_fire=None`, no new `LLMPurpose`, no ADR amendment) and all three gates are green
(2424 passed). The slice is **safe to merge on correctness/safety grounds.**

Two non-blocking items are the architect's to route: **B1** (🟡 — the Y3 test does not fail-on-revert;
production-correct, low-stakes logging-fidelity; α one-line `caplog` strengthen vs accept-as-noted) and
**B2** (🟢 — optional one-line ADR-042 D4 text-sync; you already pre-ruled no-amendment). I do **not**
self-route either. Per ADR-008 Amendment 1, R0-A is mandatory regardless of the plan-vs-impl verdict;
with senior plan-vs-impl `clean` and this R0-A flagging two non-blocking items, the joint verdict is
the architect's synthesis call.
