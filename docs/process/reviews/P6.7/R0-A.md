---
task_id: P6.7
kind: R0-A
stage: impl
surface: product
reviewer: architect-partner
lens: A (cron-evaluator correctness) + B (spine / scheduler no-regression)
state_at_review: awaiting_senior_plan_vs_impl
reviewed_ref: origin/claude/P6.7-impl @ 85a0eab
gates: ruff-format ✓ / ruff-check ✓ / mypy ✓ (310 files) / pytest full-suite exit 0 (0 failed)
verdict: needs_architect
findings: 1 🟡 (Y1 — non-blocking; architect routing only)
---

# P6.7 R0-A (impl) — cron evaluator, dual-lens Lens A ∥ Lens B

Reviewed `origin/main...origin/claude/P6.7-impl` @ `85a0eab` (read-only from `main`;
gates run in an isolated detached worktree, `uv sync --all-extras`). Five commits
(P6.7-1+2 / -3 / -4 / B904+UP017 fix / -5). Against brief `architect-briefs/P6.7.md`
(+ Ratification 2026-06-14) and plan `senior-plans/P6.7.md`.

## Verdict — `needs_architect`

The slice is **correct, gate-green, spine-clean, and faithful to the ratified contract.**
Lens A (cron arithmetic) and Lens B (spine no-regression) both clear. **One non-blocking
🟡 (Y1)** needs an architect routing call — a latent inaccuracy in the *ratified* ~4-year
search horizon, not an impl defect. It does **not** block merge on correctness grounds; it
is a ~5-second route (trivial-bump vs accept-as-documented).

## 🟡 Y1 — `_CRON_SEARCH_HORIZON_MIN` (~4y) under-covers the century-boundary 8-year Feb-29 gap

- **Where:** `pipeline/schedule.py:41` — `_CRON_SEARCH_HORIZON_MIN = 4 * 366 * 24 * 60`
  (1 464 days). Inscribed *identically* in ADR-042 D3 ("~4 years … to cover legitimate
  `0 0 29 2 *`"), brief C4, and plan P6.7-2.
- **What:** The horizon covers the **normal** 4-year leap cadence with ~3 days of margin
  (verified: `test_cron_feb29_only_on_leap_year` Feb-29-2024 → Feb-29-2028 needs 1 461 days
  < 1 464). But the **maximum** gap between consecutive Feb 29s is **8 years**, not 4, across
  a non-leap century boundary: **2100 is ÷100 but not ÷400 → not a leap year**, so Feb-29-2096
  → Feb-29-2104 is an 8-year gap. A `0 0 29 2 *` schedule whose `after_ms` falls in ≈
  [Mar 2096, Feb 2100] exhausts the ~4y horizon and raises `ValueError` on a **satisfiable**
  expression (next real match, 2104, is > 1 464 days out).
- **Severity: Low / latent.** (a) **Fail-closed** — it *raises*, never hangs; the C4 safety
  property holds. (b) **~70 years out** — no schedule created before ~2096 is affected.
  (c) **Faithful to the ratified spec** — brief + plan + Ratification all asserted "~4y …
  covers Feb-29"; the impl implemented exactly that. This is **not an impl defect** — it is a
  latent inaccuracy in the *ratified contract's stated assumption* (the 8-year century gap was
  never accounted for when "~4y covers Feb-29" was ratified).
- **Why surfaced (not silently passed):** the ADR-042 D3 amendment now **inscribes** "`4 ×
  366 × 24 × 60` minutes (~4 years) to cover legitimate `0 0 29 2 *`" as the durable contract.
  That sentence is factually wrong for the century case. R0-A surfaces new information that
  contradicts a stated ratification assumption; the architect routes — I do not.
- **Lean (architect decides — α-absorb vs accept):** both one-line.
  - **α (absorb now):** bump to `8 * 366 * 24 * 60` (covers the max Feb-29 gap; only doubles
    the *already-ratified-acceptable* pathological-Feb-29 worst-case iteration count — a guard,
    not a hot path) **and** correct the ADR-042 D3 / brief "~4y" → "~8y" text.
  - **accept:** keep ~4y and inscribe it as an explicit **documented horizon limit** ("valid
    for any Feb-29 schedule resolving within ~4y; the 2096→2104 century gap is a known,
    accepted edge"), fixing only the now-inaccurate "covers legitimate Feb-29" wording.
  - I do **not** route this. If α, ADR-042 D3 text + the constant + its comment update together.

## Lens A — cron correctness: **CLEAN**

Verified each ratified semantic by inspection **and** empirical fail-on-revert (mutated in the
worktree, tests confirmed red, reverted):

- **DOM-vs-DOW OR-union** (`_cron_day_matches:240-248`) — the four cases match Vixie exactly
  (both-`*`→True; one restricted→that field; both restricted→`day ∈ dom OR cron_dow ∈ dow`).
  **Empirical:** `or`→`and` ⇒ `test_..._union_friday_not_13th` + `test_..._union_13th_not_friday`
  both FAIL. ✓
- **Weekday conversion** `cron_dow = (dt.weekday() + 1) % 7` (Python Mon=0…Sun=6 → cron
  Sun=0…Sat=6). **Empirical:** drop `+ 1` ⇒ `test_cron_dow_only_restriction` +
  `test_cron_weekday_conversion_sunday_is_0` both FAIL. ✓
- **`*/n` alignment-to-0** (`_expand_field:120` `range(lo, hi+1, step)`) — `*/15`→{0,15,30,45},
  `*/7`→ragged-then-reset, `*/90`→{0}. Tests pin each (C5.3). ✓
- **DOW `7`=Sunday alias** — `_expand_field_dow(…,0,7)` then `7→0` normalize (`_parse_cron:175`);
  `test_cron_dow_7_alias_treated_as_sunday` asserts `0 0 * * 7` == `0 0 * * 0`. ✓
- **Restricted = literal-`*` test** (`_parse_cron:178-179`) — `*/n`/range/list count as
  *restricted* even if full-domain (per plan §5 push-back; captured at parse, not inferred). ✓
- **Calendar math = stdlib only** (`_compute_cron_next_fire:289-306`) —
  `fromtimestamp(after_ms/1000, tz=UTC)` → `replace(second=0, microsecond=0)` →
  `+timedelta(minutes=1)` step → `int(candidate.timestamp()*1000)`. **Zero** hand-written
  rollover/leap/month-length/year-wrap. Minute-aligned UTC ⇒ `timestamp()` is an exact integer
  second, no float-precision drift. Start is strictly-after `after_ms`. ✓
- **Bounded never-match guard** — `for _ in range(_CRON_SEARCH_HORIZON_MIN)`, `ValueError` on
  exhaustion, fail-closed; malformed never reaches the loop (rejected at `_parse_cron`). The
  only residual is Y1 (the horizon *size*). ✓
- **Malformed-reject** — ≥6 mandated, **14 implemented** (4/6-field, each-field-OOR, `*/0`,
  `5-2` inverted, `*/x`/`a` non-numeric, empty, whitespace). ✓

**Adversarial suite (`tests/pipeline/test_schedule.py`): comprehensive + fail-on-revert.** All
C5.1–C5.7 classes present (boundary/leap/`*/n`/union/year-wrap/malformed/DST-irrelevance); every
test passes `after_ms` explicitly (wall clock never read). The two subtlest guards verified
fail-on-revert *empirically*, not just by inspection.

## Lens B — spine / scheduler no-regression: **CLEAN**

- **Diff scope:** only `pipeline/schedule.py` is a logic change. `api/app.py:2183`,
  `pipeline/schema.py:97`, `api/openapi.json:718`, `ui/src/api/schema.ts:361` are **one-line
  doc/description-only** each (verified). ADR + 2 test files. **No spine file touched**
  (`_execute_local_call`, gate, `run_pipeline`, `_countdown_sweeper`, `_writer_approve_helper`,
  `_schedule_sweeper`, all schedule-endpoint logic — zero-diff).
- **Interval branches byte-unchanged** — diff confirms only the cron `raise ValueError`
  (validate) and `raise NotImplementedError` (compute) branches were replaced; the interval
  paths + unknown-kind guards are untouched.
- **No new dependency** — `pyproject.toml` / `uv.lock` untouched; `croniter`/`dateutil` appear
  **only** in ADR prose (the rejected-alternative note), no import. 4-runtime-dep posture
  (ADR-040 D1) preserved.
- **No new `LLMPurpose`** — appears only in ADR prose ("Cron arithmetic = code"). ✓
- **422 narrows, not removed** — endpoint logic unchanged; `test_create_schedule_valid_cron_201`
  (201 + minute-aligned `next_fire`) + `test_create_schedule_malformed_cron_422` (`*/0…`→422)
  confirm the gate narrows from "all cron" to "malformed cron only". ✓
- **openapi/schema.ts codegen-lock** (#95/#64 precedent) — both regenerated; diff is
  description-only and mirrors the `app.py` docstring. ✓

## ADR-042 D3 amendment (P6.7-5): **accurate**

D3 flipped deferred→implemented with the full subset contract inscribed; D9 narrowed;
Reversibility D3 row Medium→**Low**; Consequences "Cron is deferred"→"Cron implemented";
**historical Y1 deferral rationale preserved** ("Historical note … preserved for audit trail" —
not erased); amendment note records `plan_has_adr=False`, **no Accept gate**, ratification
2026-06-14, dual-lens reviews the inscription. Matches the ratified weight. *(Carries the same
~4y Feb-29 wording as Y1 — updates with the Y1 route if α.)*

## Gates — independently run (detached worktree @ 85a0eab)

| Gate | Result |
|---|---|
| `ruff format --check` | 313 files already formatted ✓ |
| `ruff check` | All checks passed ✓ |
| `mypy` (files=src,tests) | Success — no issues, 310 source files ✓ |
| `pytest` full suite | **exit 0** (0 failed / 0 errors) ✓ |
| cron schedule + endpoint subset | 77 passed (24.4s; the 4 Feb-29 / never-match searches dominate ≈2M iters each — ratified guard cost, not a hot path) |
| empirical fail-on-revert | union `or`→`and` ⇒ 2 FAIL; weekday `+1` drop ⇒ 2 FAIL; restored == committed ✓ |

*(The captured pytest log tail shows a `network_timeout` warning from the `net_trust` DNS-timeout
test — that test's expected path, unrelated to P6.7; exit 0 is authoritative.)*

## Non-blocking observations (not findings — recorded for completeness)

- **O1 (maintainability):** `_expand_field` and `_expand_field_dow` are ~95% duplicate; the DOW
  variant's "wildcard spans 0-6 not 7" special-case is *moot* post-`7→0`-normalization (a `*`
  spanning 0-7 normalizes to the same {0..6}). Correctness unaffected; a future refactor could
  unify via an alias param. Pure cleanliness.
- **O2 (lenient superset):** bare `a/n` (e.g. `5/15`) is accepted as `a-<hi>/n`
  (`_expand_field:108-118` `else … end = hi`), one token shape beyond the inscribed list
  `* a a-b */n a-b/n`. Matches common cron (`croniter`/Vixie treat `N/step` as `N-max/step`),
  so reasonable — but the contract doesn't enumerate it.
- **O3 (negligible):** create path parses twice (validate → `_parse_cron`, compute →
  `_parse_cron`). Plan's "parse-once" was about the *search loop* (satisfied — parsed once
  before the loop); the 2-parse-per-create is not a hot path.

## Dispatch checklist
(1) no new dep ✓ · (2) stdlib calendar arithmetic ✓ · (3) subset faithful (5-field UTC, tokens,
DOW-7 alias, DOM-DOW OR-union, bounded guard) ✓ · (4) compute/validate cron branch + 422 narrow
✓ · (5) ADR-042 D3 amendment accurate ✓ · (6) spine 0-diff / no new LLMPurpose ✓ · adversarial
tests cover + fail-on-revert (inspection + empirical) ✓ · gates independently green ✓ · **one
🟡 (Y1) for architect routing.**
