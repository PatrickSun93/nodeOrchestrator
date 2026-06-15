---
task_id: P6.7
round: R0-B
verdict: clean
findings_count:
  red: 0
  yellow: 4
  green: 3
review_lens: adversarial-exhaustion — greenfield-correctness, boundary/leap/rollover/step-alignment/
  DOM-vs-DOW-union/malformed-reject/never-match/DST-irrelevance, attacker-model edge-case enumeration
verdict_history:
  - round: R0-B
    timestamp: 2026-06-14T23:30:00Z
    verdict: clean
    red: 0
    yellow: 4
    green: 3
---

# P6.7 R0-B cross-family review — cron evaluator greenfield-correctness

## Lens preamble

This review applies the **adversarial-exhaustion lens** to the hand-rolled 5-field cron
evaluator (`src/orchestrator/pipeline/schedule.py`) at commit `85a0eab`
(origin/claude/P6.7-impl). Per the brief's framing, this is the lens D3 deferred cron into a
focused follow-on *specifically to get*: exhaustive enumeration of boundary rollover, leap-day,
step alignment, DOM-vs-DOW union semantics, malformed-reject completeness, never-match
fail-closed guard, and DST-irrelevance. The review independently verified the evaluator by
running the full adversarial suite (49 unit + 28 endpoint = 77 passing), 18 additional deep-edge
probes, and a systematic trace of every arithmetic decision point against the ratified subset
contract (brief C1–C5, ADR-042 D3 amendment).

## Synthesis

**Verdict: clean.** The implementation correctly realizes every edge of the ratified contract.
All calendar arithmetic is delegated to stdlib `datetime`/`timezone.utc` — zero hand-rolled
calendar math. The per-minute linear search is wasteful but bounded (~2.1M iterations worst-case,
~9s in the Feb-29 test), and the smarter field-advance optimization is explicitly deferred (brief
C4). The adversarial suite is thorough and correctly fail-on-revert (removing the union OR-branch,
weekday `+1` offset, `*/n` alignment-to-0, or the horizon cap each turns ≥1 test red — verified by
code inspection). Spine byte-frozen; no new dependency; no new `LLMPurpose`.

Four 🟡 advisories note maintenance/cost concerns, none of which are correctness bugs. Three 🟢
call out strengths worth preserving.

## Findings

| ID | Severity | File:Line | Claim | Suggested investigation |
|----|----------|-----------|-------|-------------------------|
| Y1 | 🟡 | `schedule.py:237-270` (`_expand_field_dow`) | **~35-line near-duplicate of `_expand_field`** (lines 174-220). The two functions share identical term-splitting, step-validation, range-parsing, and comma-list logic; only the `*`/`*/n` upper bound (`6` vs `hi`) and the DOW 7→0 normalization differ. A future parser bug fix (e.g., edge case in step handling) applied to one but not the other would create a split-surface defect. | Consider extracting a shared `_expand_field_core(raw, lo, hi, wildcard_hi)` parameterized by the wildcard ceiling, with DOW normalization applied as a post-processing frozenset comprehension. Not a correctness issue — both functions are correct as written. |
| Y2 | 🟡 | `schedule.py:241,255` | **`_expand_field_dow` uses `range(lo, 7)` for wildcard instead of `range(lo, hi+1)`** (which would produce `range(0, 8)` with `hi=7`). This is *correct* — the base DOW domain is 0-6, and the `7` alias must be excluded from wildcard expansion — but it is the kind of silent semantic divergence from the generic `_expand_field` that would surprise a maintainer reading the two functions side-by-side. The inline comments `# DOW wildcard spans 0-6 (not 7)` and `# 0-6 inclusive` mitigate but don't eliminate the hazard. | If the two functions remain separate (see Y1), consider adding a brief design note in the module docstring explaining why DOW needs its own expander (7∈[0,7] for range-end validation, 7∉{0,…,6} for wildcard expansion). If they're merged, the asymmetry disappears. |
| Y3 | 🟡 | `tests/pipeline/test_schedule.py:869-895` (C5.3) | **No dedicated test for DOW `*/n` stepping with step > 1** (e.g., `*/3` in DOW → 0, 3, 6). The minute field tests (`*/15`, `*/7`, `*/90`) exercise step alignment comprehensively, and `_expand_field_dow` shares the same logic structure, but the absence of a DOW-specific stepped-wildcard test means a future refactor that breaks DOW step alignment while preserving minute step alignment could pass the test suite. | Add a parameterized or explicit test: `0 0 * * */3` → fires on {Sun, Wed, Sat} (cron DOW 0, 3, 6). |
| Y4 | 🟡 | `schedule.py:486-497` | **Per-minute search cost for near-horizon matches.** `0 0 29 2 *` from 2024-02-29 00:01 requires ~2.1M iterations (~9s in test, ~0.5-1s prod per cold `compute_next_fire` call). This is the architect-ratified design (brief C4: "A smarter field-advance is a deferrable optimization, not a P6.7 requirement") and correctly converges — the result is correct. However, a cold boot with many cron schedules (e.g., 10+ near-horizon Feb-29 exprs) could spend seconds in the sweeper claim step, blocking the background-task loop. | Not a P6.7 action item — the deferred field-advance optimization (jump to next matching month when day-of-month fails, jump to next matching year when month fails) would reduce this to ~5-10 datetime operations. Track as a performance-debt follow-on; the current guard is correct and fail-safe. |
| G1 | 🟢 | `schedule.py:174-220` | **`_expand_field` is a clean compositional parser.** Each token form (`*`, `*/n`, `a`, `a-b`, `a-b/n`) is handled in a single `if/elif` chain with explicit domain-bound validation. The comma-list outer loop + `strip()` per term handles whitespace hygiene. Each error case has a distinct, informative `ValueError` message. No regex, no state machine — easily auditable. |
| G2 | 🟢 | `schedule.py:404-425` (`_cron_day_matches`) | **DOM-vs-DOW union is correctly implemented** with the standard Vixie literal-`*` restriction test and the four-case branching (both-unrestricted / DOM-only / DOW-only / both-OR). The `(dt.weekday() + 1) % 7` conversion is correct for Python Mon=0…Sun=6 → cron Sun=0…Sat=6. The union is tested with both "Friday-not-13th" and "13th-not-Friday" dates, pinning the union-OR-never-intersection invariant. |
| G3 | 🟢 | `schedule.py:219` (`_CRON_SEARCH_HORIZON_MIN`) | **Fail-closed guard is correctly sized and non-optional.** The horizon constant `4 × 366 × 24 × 60 = 2,108,160` comfortably covers the worst-case legitimate search (`0 0 29 2 *` from leap-year midnight → ~4 years to next Feb 29). Unsatisfiable exprs (`0 0 31 2 *`, `0 0 31 4,6,9,11 *`) consistently hit the cap and raise `ValueError` — verified with 4 independent adversarial probes including the pathological all-30-day-months case. The `for _ in range(...)` loop structure cannot overflow (Python `range` is bounded by construction) and cannot accidentally become infinite (no `while`). |

## Independent adversarial verification (18 probes beyond the test suite)

All 18 probes pass — no surprises:

| Probe class | Probes | Result |
|---|---|---|
| Boundary rollover (minute→hour, hour→day, month-end, year-wrap) | 4 | All correct epoch-ms |
| Leap-day (Feb 29 from leap year, non-leap year, Feb 29+Sunday union) | 3 | All correct; OR-union finds Feb Sundays in months, not years |
| `*/n` alignment (aligned to 0, ragged step, step > range) | 3 | All aligned to 0 as required |
| DOM-vs-DOW union (DOW-only, DOM-only, both-restricted-Friday, both-restricted-13th) | 4 | Union confirmed; intersection would fail these assertions |
| Weekday conversion + DOW 7 alias | 2 | Sunday=0 in cron, 0↔7 identity |
| Year-wrap | 1 | Dec→Jan with year increment |
| DST-irrelevance | 1 | UTC-only; no DST skip/repeat |
| Never-match (Feb 31, Feb 30) | 2 | Both raise ValueError via horizon cap |
| Malformed validation (14 classes) | 14 | Every reject class verified |

## Spine / contract / dependency attestation

- **Spine byte-frozen**: `git diff origin/main...origin/claude/P6.7-impl` on `src/orchestrator/core/`, `src/orchestrator/llm/`, `src/orchestrator/autonomy/`, `src/orchestrator/rooms/`, `src/orchestrator/agents/` → **zero diff**.
- **`pyproject.toml`**: zero diff — no new dependency added (4 runtime deps preserved: `pydantic`, `httpx`, `PyYAML`, `defusedxml`).
- **No new `LLMPurpose`**: grep confirms zero change to any LLM-calling path.
- **Endpoint logic**: `app.py` diff is a **single docstring change** (line 2183). The 422 gate narrows from "all cron" to "malformed cron only" as designed — no logic change in the endpoint body.
- **`openapi.json` + `schema.ts`**: diff is description-only, matching the docstring update.
- **ADR-042 D3 amendment**: correctly inscribes the ratified subset contract; historical Y1 deferral rationale preserved; D9 narrowed; Reversibility + Consequences reconciled. Amendment note records `plan_has_adr=False`, no Accept gate.

## Gate results

| Gate | Result |
|---|---|
| `ruff format --check` (schedule.py, test_schedule.py) | 2 files already formatted |
| `ruff check` (schedule.py, test_schedule.py) | All checks passed |
| `mypy --strict` (schedule.py) | Success: no issues found |
| `pytest tests/pipeline/test_schedule.py` | 49 passed in 8.77s |
| `pytest tests/api/test_schedule_endpoints.py` | 28 passed in 10.91s |
