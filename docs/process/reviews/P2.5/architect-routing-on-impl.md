---
task_id: P2.5
kind: architect-routing
stage: impl
date: 2026-06-01
reviews_acked:
  - R0-A.md
  - R0-B.md
  - plan-vs-impl.md
joint_verdict: needs_architect (R0-A 1🔴/2🟡/10🟢 + R0-B 0🔴/1🟡/6🟢 + plan-vs-impl clean; Route B — R0-A governs + carries the 🔴)
decisions:
  R1: α (MUST-FIX — mypy --strict gate RED; junior code-fix, not a routing decision)
  R0A-Y1: α (rename the duplicate test_frozen_raises_on_mutation so the shadowed ReentryDigest frozen test runs)
  R0A-Y2a: α (new_since_leave sort — add secondary ref_id tie-break key; determinism hardening)
  R0A-Y2b: α (architect-ruled: new_since_leave's event part = decision-class events ONLY, not all post-marker events)
  R0B-Y1: α (architect-ruled: _parse_archive_summary parse-failure → degradation marker + test, NOT raise)
fixer: junior (all code/test fixes; architect said "不要改代码 — junior 修")
---

# P2.5 architect routing — impl stage (1🔴 + 3🟡 → all α)

**Architect decision (this session):** joint verdict **needs_architect** (Route B — the mandatory R0-A governs and carries the 🔴). All five items → **α (absorb this cycle)**. The constitutional core is confirmed clean by all lenses + R0-A's live planted-bypass guard tests — none of these touch the code/LLM boundary. **R1 is a hard gate failure (must-fix), not a judgment call.** Two items (Y2b, R0B-Y1) are architect **design rulings** recorded below.

This file is the **signal artifact for the junior's fix pass** (architect designated junior, not senior — all five are code/test fixes). Junior reads this + `R0-A.md` + `R0-B.md` + the current impl, applies the fixes, re-runs gates to green, and pushes. Then verdicts bump per RC-10.

## Per-finding routing (all α)

### R1 → α (MUST-FIX) — `mypy --strict` gate is RED; correct `tests/reentry/test_schema.py`

Not a routing decision — a mandatory gate the landing misreported as green (canonical `uv run mypy`, config `files=["src","tests"]`, exits 1). Junior:
- **Delete the 4 unused `# type: ignore`** comments (lines 49, 81, 98, 161) — pydantic frozen-attr mutation is a *runtime* `ValidationError`, not a mypy error, so the `[misc]` ignores are unused; the line-81 `[call-arg]` is unused too.
- **Line 82 `fact_type="hypothesis"`** — per the **plan design (ADR-021 D8: `new_since_leave` fact-types = `verified_knowledge` + `event`, NOT `hypothesis`)**, change the test to use `verified_knowledge`/`event` (hypothesis is out-of-design — `Literal["verified_knowledge","event"]` is correct as-is; do **not** widen it).
- **`uv run mypy` must be green before merge.** (Process note: `src/` was already type-clean; the 5 errors were all in the new test file — and both the senior plan-vs-impl (`clean`) and r0b R0-B (G6 stated "mypy ✓") missed the red gate. The gate-report-integrity gap is worth a retro candidate — flagged to the architect, not logged here unless dispatched.)

### R0A-Y1 → α — rename the duplicate test method (un-shadow the ReentryDigest frozen test)

`test_schema.py` defines `test_frozen_raises_on_mutation` twice in the same class; Python keeps the last, so the **ReentryDigest** frozen-mutation test never runs (RC-25 family — a test that can't fail because it doesn't execute). Rename one (e.g. `test_reentry_result_frozen_raises_on_mutation`). Co-located with R1 in `test_schema.py` — fix in the same careful pass.

### R0A-Y2a → α — secondary sort key for `new_since_leave`

`assemble_reentry`'s `new_since_leave.sort(key=lambda x: x.occurred_at)` breaks ties on insertion order. Add a secondary key (e.g. `(occurred_at, ref_id)`) for scan-order-independent determinism (the project's determinism discipline).

### R0A-Y2b → α — **architect-ruled: decision-class events only**

The `new_since_leave` **event** part must include **decision-class events only** (mirror `produce_decision_log`'s filter — DECISION / DECISION_PIVOT / REJECTION / RETRACTION), **not** all post-marker events. Rationale: the catch-up surfaces what *changed* (decisions), not raw utterance/system noise. Junior scopes the event diff to the decision-class filter; the e2e's discriminating assertion updates accordingly (a post-marker utterance should NOT appear; a post-marker decision should). The VK part (last_validated > marker) is unchanged.

### R0B-Y1 → α — **architect-ruled: degradation marker + test, NOT raise**

`_parse_archive_summary` must **not** silently persist garbled LLM output as a durable artifact. On parse failure, **persist but mark it degraded** (do **not** raise — raising would lose the archive on a transient LLM glitch, and the archive is the milestone's durable identity). Junior:
- Mark the fallback degraded — `evidence={"summary_degraded": true}` on the `ProjectArchive` **or** a `"[degraded] "` prefix on `one_line_summary` (junior picks; the marker must be downstream-visible).
- Use the clean **`"Summary unavailable."` sentinel**, not raw `content[:120]` (which persists garbled text).
- **Add the missing fallback test** — mock the LLM returning non-JSON prose, assert the archive persists with the degradation marker (the fallback path is currently untested — Q5).

## Constitutional note (no action)

The code/LLM boundary held at impl and is structurally guarded — confirmed by R0-A's live planted-bypass tests (guard (i) caught a `reentry` import in `llm/`; guard (ii) caught `llm_router` in `assemble_reentry`) + the shipped self-tests + r0b G1/G2/G5. None of R1/Y1/Y2/R0B-Y1 is a boundary breach (R0B-Y1 is error-handling discipline; Y2 is granularity/determinism; R1/Y1 are test hygiene). The render-output prompt-enforced seam (plan-stage G2) remains the accepted MVP forward-hook — not reopened.

## Junior absorb scope (literal-reading)

All five fixes land in `tests/reentry/test_schema.py` (R1 + Y1), `src/orchestrator/reentry/digest.py` (Y2a + Y2b), and `src/orchestrator/reentry/leave.py` + `tests/reentry/test_leave.py` (R0B-Y1). No ADR change (ADR-021 D8 already pins VK+event; Y2b narrows the *event* sub-set within that, an impl-detail consistent with D8). Re-run gates to green (esp. `uv run mypy`). Architect-deferral literal-reading: the render-output-validation seam (r0b G2 / plan-stage) stays a forward hook — do NOT bundle.
