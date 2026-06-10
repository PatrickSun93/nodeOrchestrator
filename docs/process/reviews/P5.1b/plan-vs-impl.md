---
task_id: P5.1b
stage: senior-plan-vs-impl
actor: senior
date: "2026-06-10"
cycle: 3
verdict: clean
reviewed_branch: origin/claude/P5.1b-impl
reviewed_at: 30a7d05
plan: docs/process/senior-plans/P5.1b.md
adr: ADR-042
routing_absorbed:
  - docs/process/reviews/P5.1b/architect-routing-on-plan.md          # Y1 interval-only / Y2 keep / N3 GC
  - docs/process/reviews/P5.1b/architect-routing-on-impl.md          # cycle-1 → cycle-2 all-α
  - docs/process/reviews/P5.1b/architect-routing-on-impl-cycle2.md   # cycle-2 → cycle-3 all-α (B1 + B2)
supersedes: "cycle-2 plan-vs-impl (cf8680a, clean) — content preserved in git history"
findings: []   # B1 + B2 routed α close-out implemented faithfully; nothing new
---

# P5.1b — senior plan-vs-impl (cycle 3, covers cycle 2)

Re-reviewed the cycle-3 α close-out `30a7d05` (single commit on top of cycle-2 `cf8680a`)
against `docs/process/senior-plans/P5.1b.md`, ADR-042 (Accepted), and the architect's
cycle-2 impl-stage routing (`architect-routing-on-impl-cycle2.md`: **all-α, B1 + B2,
test + ADR-text only**). Read on `main` via `git diff cf8680a..origin/claude/P5.1b-impl`
(no checkout — shared worktree). The cycle-3 diff is **exactly** two files:

```
docs/decisions/ADR-042-recurring-pipeline-scheduler.md |  3 +-   (1 line of D4 text)
tests/api/test_schedule_sweeper.py                     | 32 ++++  (Y3 test rewrite)
```

29 ins / 6 del, **nothing else — zero product code, no `src/` hunk at all.**

**Bottom line:** both routed α items land faithfully — **B1** rewrites the vacuous Y3 test
into a genuine **fail-on-revert** guard, **B2** syncs the one line of ADR-042 D4 text to the
ratified advance-on-missing code (A3). No plan-external content, spine still byte-frozen by
construction (no source touched). **Verdict → `clean`.**

This file **supersedes the cycle-2 review** (also `clean`); cycle-2 content remains in git
history at `cf8680a` for the audit trail.

---

## Cycle-2 findings — resolution ledger

| Cycle-2 finding | Routed | Cycle-3 fix | Status |
|---|---|---|---|
| **B1** 🟡 — `test_act_create_run_fails_after_successful_run_does_not_raise` does **not** fail-on-revert (the reverted single-try still passes it) | α | test rewritten to assert the split-try's success-acknowledging WARNING; fails on the revert | ✅ **closed** |
| **B2** 🟢→α — ADR-042 D4 step-2 literal text ("missing → log + skip", no advance) contradicts the ratified advance-on-missing code (A3) | α | one-line D4 text synced to "missing → log + **advance `next_fire`** + skip" | ✅ **closed** |

All seven cycle-1 α items (A1/A2/A3/Y3/A4/A5/A6) remain closed from cycle 2 — untouched and
unaffected by this test/doc-only delta.

---

## Per-fix faithfulness (cycle-3 diff)

### B1 — Y3 test made fail-on-revert — ✅ faithful, **non-vacuous (verified)**

The rewrite adds a `caplog` capture and a new assertion on top of the pre-existing
`next_fire`-advanced assertion:

```python
with (
    caplog.at_level(logging.WARNING, logger="orchestrator.api.app"),
    patch("orchestrator.pipeline.store.create_pipeline_run",
          side_effect=Exception("simulated db failure")),
):
    _schedule_act_on_writer(ctx, sid, _NOW)
...
warning_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
assert any("succeeded" in m for m in warning_msgs), (...)
```

**Fail-on-revert proof (the load-bearing check for this cycle).** I traced both code shapes
against the production body (`app.py:688-726`, byte-frozen this cycle):

- **Split-try (production, A-side):** `create_pipeline_run` sits in its own try; the except
  emits `_log.warning("schedule-sweeper: create_pipeline_run failed for schedule %s (run %s
  succeeded): %s", …)` (`app.py:714-720`) — a WARNING whose message contains **"succeeded"**.
  The new assertion **passes**. ✅
- **Reverted single combined try (cycle-1 B-side):** `run_pipeline` + `create_pipeline_run`
  share one try; a `create_pipeline_run` failure is caught by the *single* except, which logs
  an **ERROR** (`"…run_pipeline failed…"`) and `return`s early. **No WARNING containing
  "succeeded" is ever emitted** → the new assertion **fails**. ✅

So the test now distinguishes the two shapes — exactly the B1 routing intent ("a guard that
passes on both fixed and reverted code does not guard"). The pre-existing `next_fire`
assertion is *kept* (it is correct, just insufficient on its own — the claim advances before
the try block, so it survives the revert; that was precisely B1's vacuity).

**Mock-fires + logger-name verification (non-vacuity guards both checked):**

- **Patch target binds.** The test patches `orchestrator.pipeline.store.create_pipeline_run`;
  `app.py:623-624` does a **function-local** `from orchestrator.pipeline.store import
  (create_pipeline_run, …)` re-resolved on every call, so the patch's `side_effect` genuinely
  fires (same mechanism that made the cycle-2 `next_fire` assertion meaningful). Not the
  P5.1a-cyc2 vacuous-mock class.
- **Logger name matches.** `caplog.at_level(logging.WARNING, logger="orchestrator.api.app")`
  targets the exact logger the production code uses — `_log = logging.getLogger(
  "orchestrator.api.app")` (`app.py:228`). The WARNING at `app.py:714` goes through `_log`, so
  caplog captures it. (If the name were wrong, caplog would capture nothing and the assertion
  would fail closed — i.e. it cannot pass vacuously.)

Same test-honesty close-out as P5.1a cyc3; the discipline is correctly applied here.

### B2 — ADR-042 D4 text synced to A3 code — ✅ faithful

The single changed D4 line now reads:

> the pipeline is **missing** (deleted) → log + **advance `next_fire`** + skip the run
> (breaks the orphan re-discovery loop; A3 routing).

This is a verbatim match to the routing instruction, and an accurate description of the
ratified code: `_schedule_act_on_writer` advances `next_fire` **unconditionally in the claim
step** (`app.py:651-657`, "Advance regardless of pipeline state so orphan/disabled schedules
do not re-appear as due on every subsequent tick"), *then* the `pipeline is None` gate logs a
warning and returns (`app.py:662-668`) — net behaviour: **log + advance + skip**, exactly the
new text. This is a code-vs-inscribed-text consistency repair, **not a decision change**: D4's
neighbouring disabled-pipeline clause already said "skip … but still advance `next_fire`", so
the missing-pipeline clause is now consistent with both the code *and* the sibling clause.
No other ADR line changed; the decision content of D4 is otherwise intact.

---

## Constitutional carry-forward (Lens B) — vacuously clear in cycle 3

The cycle-3 diff contains **no `src/` hunk whatsoever** — only a test file and one ADR line.
Every spine invariant therefore holds by construction:

| Invariant | Result |
|---|---|
| `run_pipeline` / `_schedule_act_on_writer` / `_schedule_sweeper` byte-identical | ✅ no source file in the diffstat |
| `_countdown_sweeper` / `_discover_expired_pendings` / `_writer_approve_helper` byte-untouched | ✅ unchanged |
| `countdown_auto_fire=None` reversible-only preserved | ✅ unchanged |
| gate (`score`/`decide_tier`/`emit_gate_decision`) + `_execute_local_call` untouched | ✅ unchanged |
| No new routing `LLMPurpose` | ✅ no source change; the only LLM in a scheduled run is the unchanged `run_pipeline` content-gen |
| scheduler-OFF ⇒ byte-identical to P5.1a | ✅ unchanged (no runtime delta) |

`RB-PIPELINE-SCHED` remains inscribed honestly; cron stays fully deferred — no stub leaked.

---

## Plan-external expansion / omission scan (cycle 3)

- **Omissions:** none — both routed α items (B1 test rewrite, B2 D4 text) are present.
- **Expansions:** none — the diff is confined to the two files the routing implies. The test
  change is additive (one fixture param + one `with`-clause + one assertion + a docstring
  note); no other test was altered, no product code touched, no opportunistic hardening, no
  defensive bundling under deferral language.

---

## Verdict

**`clean`.** The cycle-3 close-out faithfully resolves both routed α items: B1 turns the Y3
guard into a genuine fail-on-revert test (proven against both the split-try and the reverted
single-try shapes; mock fires + logger name verified, so it cannot pass vacuously), and B2
syncs the one line of ADR-042 D4 text to the ratified advance-on-missing code without changing
any decision. The diff is test + ADR-text only — zero product code, spine byte-frozen by
construction — and introduces nothing outside the routing. All cycle-2 findings are closed and
nothing new surfaced.

Per ADR-008 Amendment 1 (Route B, W-005), state advances to `awaiting_R0_A` regardless of
verdict; this `clean` frontmatter signals no senior-side plan-vs-impl drift remains for the
cycle-3 external review round.
