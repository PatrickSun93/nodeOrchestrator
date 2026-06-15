---
task_id: P6.7
round: R0-B
verdict: clean
findings_count:
  red: 0
  yellow: 5
  green: 2
review_lens: adversarial-exhaustion — cross-family greenfield-correctness, boundary/leap/rollover/
  step-alignment/DOM-vs-DOW-union/malformed-reject/never-match/DST-irrelevance, attacker-model edge-case
  enumeration. Independent verification with 18 adversarial probes beyond the committed test suite.
gates_rerun: ruff-format ✓ / ruff-check ✓ / mypy ✓ / pytest 49+28=77 ✓ (detached worktree @ 85a0eab)
---

# P6.7 R0-B cross-family review — cron evaluator greenfield-correctness

Reviewed `origin/claude/P6.7-impl` @ `85a0eab` (read-only from `main` on shared worktree;
gates run in isolated detached worktree `uv sync --all-extras`). Five commits per senior plan
(P6.7-1+2 cron parser+compute / P6.7-3 adversarial suite / P6.7-4 un-gate docs+openapi /
P6.7-5 ADR-042 amendment).

**Lens:** adversarial-exhaustion (boundary/leap/step-alignment/DOM-vs-DOW union/malformed-reject
completeness/never-match fail-closed/DST-irrelevance), attacker-model edge-case enumeration. The
cross-family value here is a genuinely-different cognitive substrate probing the arithmetic:
where in-family lenses trust the spec text, I trace "what actually happens when stdlib `datetime`
sees Feb 29 1900" — the spec says "4 years covers Feb-29-only", the Gregorian calendar says
otherwise (see Y1 below).

## Verdict — **clean** (with one 🟡 elevated above the in-family assessment)

The cron evaluator is correct against every edge of the ratified subset contract *except* the
4-year horizon's under-coverage of century-boundary Feb-29 gaps. This is a **ratified-scope**
defect (brief+plan+ADR all inscribed "~4 years…covers Feb-29"), not an impl defect — the junior
faithfully implemented the ratified constant. R0-A's Y1 correctly identifies it; I independently
confirmed the gap and **agree with R0-A's analysis**. My earlier G3 (in the impl-branch
`R0-B-cross-family.md`) labeling the horizon "correctly-sized" was wrong — the Gregorian
century-boundary gap (1896→1904, 2096→2104) is ~8 years / ~4.2M minutes, exactly 2× the
current 2.1M-minute horizon. The practical impact is latent (~2100 is 74 years out), but the
code's stated contract ("covers legitimate `0 0 29 2 *`") is factually inaccurate — a legitimate
Feb-29-only schedule with `after_ms` in the wrong half of an 8-year gap incorrectly raises
`ValueError`. See Y1 below.

All other findings are maintenance/cost advisories. Spine byte-frozen; no new dependency; no
new `LLMPurpose`; 422 narrows correctly; adversarial suite is thorough and fail-on-revert.

## Findings

| ID | Sev | File:Line | Claim |
|----|-----|-----------|-------|
| Y1 | 🟡 | `schedule.py:41` | **`_CRON_SEARCH_HORIZON_MIN` = 4×366×24×60 under-covers century-boundary Feb-29 8-year gaps.** Agree with R0-A Y1. Gregorian century rules (÷100 but not ÷400 → non-leap, e.g. 1900/2100) create a max gap of ~4.2M minutes between consecutive Feb 29s. Verified empirically: `0 0 29 2 *` with `after_ms=1896-02-29 00:01` and `after_ms=2096-02-29 00:01` both exhaust the 2.1M horizon and raise `ValueError` on satisfiable expressions. The fix is one-line: bump to `8 * 366 * 24 * 60`. Architect routes per R0-A's α-vs-accept framing. |
| Y2 | 🟡 | `schedule.py:237-270` | **`_expand_field_dow` ~35-line near-duplicate of `_expand_field`** (lines 174-220). Shared term-splitting, step-validation, range-parsing, comma-list logic; only the `*`/`*/n` upper bound (`6` vs `hi`) and DOW 7→0 normalization differ. A future parser fix applied to one but not the other creates a split-surface defect. Correct as written — pure maintenance hazard. |
| Y3 | 🟡 | `schedule.py:241,255` | **`_expand_field_dow` wildcard uses `range(lo, 7)` not `range(lo, hi+1)` (which would be `range(0, 8)`).** Correct — 7 must be excluded from wildcard expansion — but the asymmetry with the generic `_expand_field`'s `range(lo, hi+1)` pattern is a silent semantic divergence that would surprise a maintainer. The inline comments `# DOW wildcard spans 0-6 (not 7)` and `# 0-6 inclusive` mitigate but don't eliminate the hazard. |
| Y4 | 🟡 | `tests/pipeline/test_schedule.py` (C5.3) | **No dedicated test for DOW `*/n` stepping with step > 1** (e.g. `0 0 * * */3` → fires Sun/Wed/Sat). The minute `*/n` tests cover the shared `_expand_field` logic path, but a refactor that breaks DOW-specific step alignment while preserving minute step alignment could pass the suite. |
| Y5 | 🟡 | `schedule.py:486-497` | **Per-minute search cost for near-horizon matches.** `0 0 29 2 *` from a leap-year midnight searches ~2.1M iterations (~9s test, ~0.5-1s prod). Correct result, and the smarter field-advance is explicitly deferred (brief C4), but the per-minute step blocks the background-task loop for seconds in cold scenarios. The century-boundary bump (Y1) doubles the worst-case iteration count — still acceptable for a guard, not a hot path. |
| G1 | 🟢 | `schedule.py:404-425` | **DOM-vs-DOW union correctly implements standard Vixie OR-union** with literal-`*` restriction test, four-case branching, and correct Python→cron weekday conversion `(dt.weekday()+1)%7`. Independently verified: the OR-union means `0 0 29 2 0` fires on "Feb AND (29 OR Sunday)" — any Sunday in February, not "Feb 29 that IS a Sunday." This is correct Vixie semantics; my initial adversarial probe mistakenly expected intersection, and the code's OR behavior proved correct. |
| G2 | 🟢 | `schedule.py:219,486-497` | **Never-match guard correctly fail-closes.** `for _ in range(...)` cannot become infinite (Python `range` bounded by construction); unsolvable exprs (`0 0 31 2 *`, `0 0 31 4,6,9,11 *`) consistently raise `ValueError`. |

## Independent adversarial verification (18 probes beyond the test suite)

| Class | Probes | Result |
|---|---|---|
| Boundary rollover (minute→hour, cross-midnight, year-wrap) | 4 | All correct |
| Leap-day (Feb 29 from leap year, non-leap year, century gap exhausts) | 3 | Normal cases correct; century gap exhausts → Y1 |
| `*/n` alignment (aligned-to-0, ragged, step>range, range-step) | 4 | All aligned correctly |
| DOM-vs-DOW union (DOW-only, DOM-only, Friday-not-13th, 13th-not-Friday, Feb-29+Sun union) | 5 | All OR-union, never intersection |
| Weekday conversion + DOW 7 alias | 2 | Sunday=0 in cron, 0↔7 identity confirmed |
| Year-wrap | 1 | Dec→Jan with year increment |
| DST-irrelevance | 1 | UTC-only; no DST skip/repeat |
| Never-match (Feb 31, Feb 30) | 2 | Both raise ValueError |
| Malformed validation (14 classes) | 14 | Every reject class verified |

## Cross-family vs in-family delta

R0-A (in-family) and R0-B (cross-family) agree on the substantive finding: **Y1 — century-boundary
Feb-29 gap exhausts the 4-year horizon**. R0-A surfaced it by tracing the Gregorian century rule
(1900/2100 non-leap) against the ratified constant; R0-B independently confirmed it by empirical
probe (1896→1904 and 2096→2104 both raise `ValueError`). This is the kind of finding dual-lens
exists for: the in-family reviewer caught it by reading the spec; the cross-family reviewer caught
it by running the code against the Gregorian calendar rules stdlib actually implements.

The other findings diverge predictably by lens: R0-A's O1/O2/O3 (maintainability/lenient-superset/
double-parse) are in-family quality observations; R0-B's Y2/Y3 (DOW expander duplication +
wildcard-hi asymmetry) are the same phenomenon seen from a structural-audit angle. The lenses agree
on the core correctness picture: the implementation is faithful, gate-green, spine-clean; the one
gap is Y1.

## Spine / contract / dependency attestation

- **Spine byte-frozen:** `git diff origin/main...origin/claude/P6.7-impl` on `core/`, `llm/`,
  `autonomy/`, `rooms/`, `agents/` → **zero diff**.
- **`pyproject.toml`:** zero diff — 4 runtime deps preserved.
- **No new `LLMPurpose`:** grep confirms zero change to any LLM-calling path.
- **Endpoint logic unchanged:** `app.py:2183` diff is a single docstring change; 422 narrows
  from "all cron" to "malformed cron only" via the emergent `validate_schedule_expr` behavior,
  no endpoint-body logic change.
- **`openapi.json` + `schema.ts`:** description-only diffs, matching the docstring update.
- **ADR-042 D3 amendment:** accurate; historical Y1 deferral preserved; the "~4y" wording
  should be corrected alongside Y1 resolution.

## Gates (independently run at detached worktree @ 85a0eab)

| Gate | Result |
|---|---|
| `ruff format --check` | 2 files already formatted ✓ |
| `ruff check` | All checks passed ✓ |
| `mypy --strict` | Success — no issues ✓ |
| `pytest tests/pipeline/test_schedule.py` | 49 passed (8.77s) ✓ |
| `pytest tests/api/test_schedule_endpoints.py` | 28 passed (10.91s) ✓ |
