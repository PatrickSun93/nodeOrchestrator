---
task_id: P5.1b
stage: impl
review: R0-A (architect-partner, impl-stage) — cycle-3 α close-out re-review
actor: architect-partner
cycle: 3
lens: "Lens A = scheduler safety + headless-initiation correctness; Lens B = spine + auto-fire no-regression; cycle-3 = α close-out only (B1 fail-on-revert + B2 ADR-text sync), test + doc, zero product code"
verdict: clean
date: "2026-06-10"
reviewed_branch: origin/claude/P5.1b-impl
reviewed_at: 30a7d05
supersedes: "cycle-2 R0-A @ cf8680a (same path): all 7 cycle-1 findings resolved + A1 IDOR fail-on-revert confirmed; raised B1 (vacuous Y3 test) + B2 (ADR-042 D4 text), needs_architect"
plan: docs/process/senior-plans/P5.1b.md
adr: ADR-042
routing_absorbed: docs/process/reviews/P5.1b/architect-routing-on-impl-cycle2.md   # all-α, B1 + B2, cycle-3
peer_reviews:
  - docs/process/reviews/P5.1b/plan-vs-impl.md   # senior cycle-3, verdict CLEAN @ 30a7d05 (findings: [])
  - docs/process/reviews/P5.1b/R0-B.md           # r0b cross-family, CLEAN @ cf8680a; no cycle-3 re-run (test/doc-only delta, no product surface — per routing)
read_method: "git diff cf8680a..30a7d05 (cycle-3 delta = ADR-042 D4 step-2 sentence + test_schedule_sweeper.py caplog strengthen; +29/-6, zero product code) on main; no checkout — shared worktree; gates + B1 empirical fail-on-revert in isolated detached worktree @ 30a7d05 (uv sync --all-extras)"
commit_subject_note: "30a7d05 subject reads '→ awaiting_junior_impl cycle 3' (a mislabeled state string); its actual diff is the B1 + B2 close-out — confirmed by name-only (only ADR-042 + the one test file)."
gates:
  ruff: pass (All checks passed!)
  mypy: pass (Success: no issues found in 304 source files — files=src,tests)
  pytest: pass (2424 passed, exit 0; junit-xml authoritative — tests=2424 / failures=0 / errors=0 / skipped=0; 1 pre-existing starlette/httpx-deprecation warning observed, the intermittent DNS-timeout thread warning did not surface this run)
cycle2_closeout:
  B1-vacuous-Y3-test: RESOLVED — caplog assertion added; fail-on-revert EMPIRICALLY CONFIRMED (revert to cycle-1 single-try → AssertionError @ test_schedule_sweeper.py:440 "split-try must emit a WARNING…"; restore → pass)
  B2-adr042-d4-text: RESOLVED — D4 step-2 missing-branch synced to "log + advance next_fire + skip the run (A3 routing)", now parallel to the disabled branch and matching the advance-on-missing code
findings: []
---

# R0-A impl-stage — P5.1b cycle-3 α close-out re-review (recurring pipeline scheduler)

Independent architect-partner **re-review** of the cycle-3 α close-out on
`origin/claude/P5.1b-impl` @ `30a7d05`, against the cycle-2 R0-A (`R0-A.md` @ `cf8680a`,
this path — now superseded), the absorbed routing
(`architect-routing-on-impl-cycle2.md`: **all-α, B1 + B2, test + ADR-text only, one cycle**),
the plan, and **ADR-042 (Accepted)**. Read on `main` via `git diff cf8680a..30a7d05`
(no checkout — shared worktree); canonical gates **and** the targeted **B1 empirical
fail-on-revert** run in an isolated detached worktree @ `30a7d05` (`uv sync --all-extras`).

> Subject note: `30a7d05`'s commit subject is the mislabeled state string
> *"→ awaiting_junior_impl cycle 3"*; its actual content is the B1 + B2 close-out. The
> cycle-3 diff touches **exactly two files** — `ADR-042` (one D4 step-2 sentence) and
> `tests/api/test_schedule_sweeper.py` (the Y3 test) — confirmed by `--name-only`. **Zero
> product code.**

**Bottom line.** Both cycle-2 close-out items are **resolved**, with **no new findings**:
**B1** — the Y3 split-try test now **fails-on-revert** (I confirmed it empirically: reverting
the production split-try back to the cycle-1 single `try/except` turns the test red, restoring
it green); **B2** — the ADR-042 D4 step-2 sentence now matches the ratified advance-on-missing
code. The constitution is untouched by construction (cycle-3 changes **no** product code):
countdown spine **byte-identical** to `origin/main` (re-verified independently), `run_pipeline`
unchanged, `countdown_auto_fire=None` preserved, **no new `LLMPurpose`**. All three gates green.
**Verdict `clean`** — the slice is ready to merge (PR #68); the merge itself is the architect's.

---

## B1 — 🟡→α RESOLVED: Y3 split-try test now fails-on-revert (empirically confirmed)

The cycle-2 finding was that `test_act_create_run_fails_after_successful_run_does_not_raise`
**passed on both** the fixed split-try and the reverted cycle-1 single-try — a guard that does
not guard. The cycle-3 rewrite adds a `caplog`-scoped assertion that, after a
`create_pipeline_run` failure following a **successful** `run_pipeline`, a **WARNING** containing
`"succeeded"` is emitted — the truthful "run … succeeded, but the index write failed" log that
**only** the split-try path can produce. (Logger asserted: `orchestrator.api.app`, matching
`_log` in `app.py:228`.)

I verified the production code is byte-unchanged from cycle-2 (`_schedule_act_on_writer`,
`app.py:600`) — the run is wrapped in one `try` (fail → `error` + `return`), the index write in a
**separate** `try` (fail → `warning "(run %s succeeded)"`), then a fall-through `info`. The
cycle-1 single-`try` collapses all three under one `except` that logs *"run_pipeline failed"* and
returns early — so no `"succeeded"` WARNING is ever emitted.

### Empirical fail-on-revert (isolated worktree @ 30a7d05)

| Step | Action | Result | Reading |
|---|---|---|---|
| **A (as-is)** | run the Y3 test at `30a7d05` | **PASS** (exit 0) | split-try emits the `"succeeded"` WARNING |
| **B (revert)** | merge the split-try back into the cycle-1 single `try/except` (run + create + info under one `try`, one `except` → `error`+`return`); `py_compile` clean | — | faithful cycle-1 form |
| **C (reverted)** | re-run the Y3 test | **FAIL** (exit 1) — `AssertionError` at `test_schedule_sweeper.py:440`: *"split-try must emit a WARNING acknowledging the successful run…"* | the new assertion is the **sole** failure; the *does-not-raise* and *next_fire-advanced* assertions still hold under the revert, so the test now isolates **precisely** the logging-honesty delta |
| **D (restore)** | `git checkout -- app.py` | worktree `porcelain` **empty** | clean restore |
| **E (re-as-is)** | re-run the Y3 test | **PASS** (exit 0) | green again post-restore |

This is the same test-honesty close-out applied at P5.1a cyc3: the guard now genuinely
distinguishes the fix from the bug. **B1 resolved.**

---

## B2 — 🟢→α RESOLVED: ADR-042 D4 step-2 text synced to advance-on-missing

D4 step-2 previously granted the `next_fire` advance only to the **disabled** branch
(*"missing (deleted) → log + skip"*), trailing the A3 code that advances on **missing** too.
Cycle-3 changes the one sentence to:

> *"If the pipeline is **missing** (deleted) → log + **advance `next_fire`** + skip the run
> (breaks the orphan re-discovery loop; A3 routing)."*

The missing branch is now **parallel** to the already-present disabled branch (*"skip the run
but still advance `next_fire`"*), and both match the code's unconditional claim-then-gate
(`app.py:600` step 3 advances `next_fire` before the step-4 missing/disabled gate). I scanned the
rest of ADR-042 (`grep missing|orphan|next_fire`) — no second stale spot; the inscribed contract
and the shipped code now agree. This is the scoped one-line sync the architect routed — **not** a
decision change (the advance-on-missing behavior was ratified at cycle-2 routing). **B2 resolved.**

---

## Constitutional / Lens-B re-confirmation (independent)

Cycle-3 changes **no** product code, so the constitution holds by construction; I re-verified
the spine independently rather than inheriting the cycle-2 result:

| Invariant | Verification (my run) | Status |
|---|---|---|
| countdown spine byte-frozen | AST-extracted `_countdown_sweeper` / `_writer_approve_helper` / `_discover_expired_pendings` from `origin/main` vs `30a7d05` → **byte-identical** (2378b / 3540b / 1883b) | ✅ |
| product code zero-diff | `git diff --name-only cf8680a..30a7d05` → only `ADR-042` + `test_schedule_sweeper.py`; no `src/` file | ✅ |
| `run_pipeline` / `_execute_local_call` / gate unchanged | absent from the cycle-3 diffstat | ✅ |
| `countdown_auto_fire=None` preserved | runner untouched; scheduler remains a second caller passing no kwarg | ✅ |
| no new routing `LLMPurpose` | cycle-3 diff is test + doc; grep clean | ✅ |
| gates | ruff *All checks passed!* · mypy *304 files, no issues* · pytest **2424 passed** / 0 failures / 0 errors / 0 skipped (junit-xml, exit 0) | ✅ |

Senior cycle-3 plan-vs-impl independently returned **`clean`** (findings `[]`, @ `30a7d05`);
R0-B's cycle-2 **`clean`** stands (no cycle-3 re-run — the test/doc-only delta has no product
surface for the cross-family runtime/failure-mode lens, per the routing). My lens adds the
empirical fail-on-revert pass that closes B1.

---

## Verdict: `clean`

Both α close-out items are **resolved** — **B1** fail-on-revert **empirically confirmed**, **B2**
ADR-042 D4 text synced and internally consistent — with **no new findings**. Cycle-3 touches no
product code, so the constitution is intact (spine byte-frozen, `run_pipeline` unchanged,
`countdown_auto_fire=None`, no new `LLMPurpose`) and all three gates are green. With senior
plan-vs-impl `clean` and R0-B `clean` (cycle-2, test/doc-only delta this cycle), the cycle-3
close-out is complete. **PR #68 is ready to merge** → P5.1b closed. I do **not** merge (architect's
call per role boundary).
