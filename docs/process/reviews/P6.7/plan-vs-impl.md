---
task_id: P6.7
round: plan-vs-impl
cycle: 2
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 6          # 5 cycle-1 atomic-fidelity 🟢 + 1 cycle-2 α-rework 🟢
notes_count: 3       # cycle-1 advisory notes; none re-opened by the α rework
covers_cycles: [1, 2]
---

# Review: P6.7 — plan-vs-impl (cron evaluation for pipeline schedules)

> **This file spans both review cycles.** Cycle 2 (the α horizon-bump rework) is verified
> first; the cycle-1 atomic-by-atomic review is preserved below verbatim as audit history.
> Both cycles are **clean**.

---

# Cycle 2 — α rework verification (never-match horizon bump)

**Reviewer:** senior planner (Claude Opus 4.8 [1M], primary session)
**Date:** 2026-06-15
**Under review:** `origin/claude/P6.7-impl` @ `90a2a1e`, diffed `git diff ce4e074..origin/claude/P6.7-impl`
(`ce4e074` = cycle-1 R0-B review tip → the cycle boundary).
**Routing absorbed:** `docs/process/reviews/P6.7/architect-routing-on-impl.md` — single finding **Y1**
routed **α** (R0-A + R0-B independently confirmed): `_CRON_SEARCH_HORIZON_MIN` (~4y / 2.1M min)
under-covers the **century-boundary 8-year Feb-29 gap** (1896→1904, 2096→2104 skip the non-leap
1900/2100 → consecutive Feb-29s are ~8y apart). α fix = double the horizon to `8 × 366 × 24 × 60`,
sync the constant comment **and** ADR-042 D3 text, add a matching test pair.

## Verdict: **clean**

The α rework is implemented **exactly** to the routed scope — one constant doubled, two text sites
synced, two additive tests — with **no plan-external expansion**. The cycle-2 diff is exactly 3 files
(`schedule.py`, `ADR-042`, `test_schedule.py`); no spine file, no `app.py`/`schema.py`/`openapi.json`/
`schema.ts`, no `pyproject.toml`, no stray `.workflow/` state-advance commit. Single commit `90a2a1e`.

## α-fidelity checks (routing → impl, point-for-point)

🟢 **Horizon constant bumped + arithmetic verified** (`schedule.py`)
`_CRON_SEARCH_HORIZON_MIN: int = 8 * 366 * 24 * 60  # 4_216_320` — value comment arithmetically
correct (8·366·24·60 = 4,216,320). Exactly doubles the prior bound per the α call; no other
`schedule.py` change (the matcher, parser, union, weekday offset, fail-closed branch all byte-stable —
this is a pure bound widening). Faithful.

🟢 **Both text sites synced** (constant comment + ADR-042 D3)
The plan/routing required updating **both** the inline constant comment **and** the ADR-042 D3 prose
(both previously asserted "~4 years … covers Feb-29", now factually stale). Both are updated to "~8
years" with the same century-boundary rationale (1896→1904, 2096→2104 skip non-leap 1900/2100). The
fail-closed-on-exhaustion semantics text is preserved unchanged — only the horizon magnitude + its
justification moved. No drift between the two sites or against the routing wording. Faithful.

🟢 **Test pair added, fail-on-revert framed, math hand-verified** (`test_schedule.py`, additive +40 LOC)
Two new C5.8 tests, appended after the existing suite (no existing test removed or altered — the
cycle-1 C5.2 `0 0 29 2 *` → 2028 ~4y test still stands):
- `test_cron_feb29_century_boundary_8yr_gap_matches` — `after = 2096-02-29 00:00`, strictly-after
  skips that minute; 2100 is non-leap (÷100 not ÷400) → next Feb-29 is **2104**. Hand-verified span
  = 2,921 days = 4,206,240 minutes **< 4,216,320 horizon** (≈7-day margin) → resolves, asserts
  `year==2104, month==2, day==29, 00:00`. Docstring states the fail-on-revert: restoring the 4y
  horizon makes this incorrectly raise `ValueError`. ✓
- `test_cron_feb30_still_fail_closes_at_century_boundary` — `0 0 30 2 *` (Feb 30 never exists)
  anchored at the gap start still raises `ValueError`, guarding that the wider horizon does not let a
  genuinely-unsatisfiable expr slip past fail-close. Docstring fail-on-revert: removing the cap loops
  forever. ✓

  Both tests pass `after_ms` explicitly (wall clock never read); required symbols
  (`pytest`, `compute_next_fire`, `_ms`, `_dt`) all already imported/defined in the file head. The
  pair is the exact test the routing prescribed ("Feb-29 across a century-boundary 8-year gap → matches;
  `0 0 30 2 *` still fail-closes within the new horizon").

## Forcing-function checks (cycle-2 delta)

- **No plan-external expansion** — cycle-2 diff = 3 files, all named by the α routing; nothing else.
- **Spine byte-frozen** — no spine file in the diff; `schedule.py` change is one constant + its comment.
- **No new dependency / no new `LLMPurpose`** — `pyproject.toml` untouched; cron arithmetic stays code.
- **ADR-042 stays an in-place amendment** — D3 prose edit only, no Accept gate (per routing; same
  weight as the cycle-1 inscription). Reversibility/Consequences/D9 untouched this cycle.
- **No stray state-advance** — branch carries no `.workflow/` commit.

The α rework clears the senior gate. Per `requires_cross_family_review: true`, the dual-lens
(R0-A ∥ R0-B) re-confirmation on the bumped horizon is the architect's call; the bound is now true to
the inscribed "covers legitimate `0 0 29 2 *`" contract claim, which was the sole point of the rework.

---

# Cycle 1 — original atomic-by-atomic review (preserved as audit history)

**Reviewer:** senior planner (Claude Opus 4.8 [1M], primary session)
**Date:** 2026-06-14
**Plan:** `docs/process/senior-plans/P6.7.md` (no new ADR; amends ADR-042 D3 in place; hand-rolled 5-field cron subset).
**Under review:** `origin/claude/P6.7-impl` @ `85a0eab`, diffed `git diff origin/main…origin/claude/P6.7-impl`.
**Impl commits:** `4dd12ae` P6.7-1+2 (parser + validate + compute_next_fire) → `6b8626b` P6.7-3 (adversarial suite) → `791183e` P6.7-4 (un-gate docs + openapi/schema.ts regen + endpoint tests) → `fc4b2bf` ruff B904/UP017 fix → `85a0eab` P6.7-5 (ADR-042 D3 amendment).
**Diff scope:** 8 files, +800/−78. File set exactly matches the plan's path map; no stray `.workflow/` state-advance commit on the branch.

## Verdict: **clean**

Every plan atomic is implemented faithfully, with no plan-external behavioral expansion, no new dependency, and the constitutional spine byte-frozen. Gate green in an isolated `--all-extras` worktree: `ruff format --check` (310 files clean), `ruff check` (all passed), `mypy` (Success, 310 files), `pytest` (full suite all-pass; targeted `tests/pipeline/test_schedule.py` + `tests/api/test_schedule_endpoints.py` = 77 passed). Three non-blocking notes below (advisory; none gate merge).

## Atomic-by-atomic fidelity

🟢 **P6.7-1 — cron parse + validate** (`schedule.py`)
The cron branch of `validate_schedule_expr` now calls `_parse_cron` (raises `ValueError` on malformed) and returns; the interval branch is byte-unchanged. `_parse_cron` enforces exactly-5-fields, per-field domains (min 0-59 / hour 0-23 / DOM 1-31 / month 1-12 / DOW via `_expand_field_dow` over 0-7 with 7→0 normalisation). Tokens `*`, `a`, `a-b`, `*/n`, `a-b/n` all expand as specified; step `n≥1` enforced; inverted range rejected; names excluded. **Restricted-flag is the literal-`*` test** (`dom_raw.strip() != "*"`), captured at parse time per the plan's §5 Vixie push-back — not full-domain-coverage inference. ✓ All ≥6 malformed-reject classes from the plan are reachable and rejected.

🟢 **P6.7-2 — cron `compute_next_fire`** (`schedule.py`)
`_compute_cron_next_fire` reuses the P6.7-1 parser, floors `after_ms` to the minute and steps `+timedelta(minutes=1)` (strictly-after semantics), bounded by `_CRON_SEARCH_HORIZON_MIN = 4×366×24×60 = 2_108_160`, raising `ValueError` (fail-closed) on exhaustion. Match predicate is minute∧hour∧month∧`_cron_day_matches`. **Weekday conversion `cron_dow = (dt.weekday()+1)%7`** and the **DOM-vs-DOW OR-union (both-restricted)** are implemented exactly per the plan's load-bearing C3 contract. All calendar math is delegated to stdlib `datetime`/`UTC` — no hand-rolled calendar arithmetic. Interval branch byte-unchanged. ✓

🟢 **P6.7-3 — adversarial correctness suite** (`tests/pipeline/test_schedule.py`)
The three cron-deferred tests are replaced; interval/unknown-kind tests untouched. All C5 classes present with fail-on-revert framing: C5.1 boundary rollover incl. **year boundary** (`59 23 31 12 *`); C5.2 month-end + **leap `0 0 29 2 *` → 2028** (exercises the ~4y horizon, resolves not raises); C5.3 `*/15` **aligned-to-0**, `*/7` ragged-reset, `*/90` step>range→{min}; C5.4 union **Friday-not-13th AND 13th-not-Friday** both match + Sun=0 pin + DOW-7-alias equality; C5.5 year-wrap; C5.6 ≥6 malformed-reject + Feb-31/Feb-30 never-match raise; C5.7 DST-irrelevance (UTC `30 2 10 3 *` on a spring-forward day). Spot-checked the calendar assertions (2024-06-01 = Sat, 2024-01-05 = Fri, 2024-02-13 = Tue, 2024-06-02 = Sun, next Feb-29 = 2028) — all correct. Every `after_ms` passed explicitly; wall clock never read. ✓

🟢 **P6.7-4 — un-gate seam + contract regen** (`app.py`, `schema.py`, `openapi.json`, `schema.ts`, `test_schedule_endpoints.py`)
`app.py:2183` docstring, `schema.py:97` comment, `openapi.json` create-schedule `description`, and `schema.ts` JSDoc are **all doc/comment-only** — endpoint logic is zero-diff (confirmed: the only logic file in the whole diff is `schedule.py`). `openapi.json` diff is description-only at the create-schedule path; `schema.ts` mirrors it. The cron-deferred endpoint test is replaced by valid-cron-201 (asserts `next_fire` whole-minute-aligned) + malformed-cron-422 (`*/0 …`). ✓

🟢 **P6.7-5 — ADR-042 D3 amendment** (`ADR-042-recurring-pipeline-scheduler.md`)
Amended **in place**: D3 flipped to "cron implemented" with the full subset contract inscribed (tokens, domains, DOW-7 alias, DOM-vs-DOW OR-union, bounded never-match guard, stdlib-only calendar math, UTC-only); D9 narrowed ("malformed cron 422; valid accepted"); Reversibility D3 row Medium→Low; Consequences "Cron is deferred"→"Cron implemented"; the historical Y1 deferral rationale **preserved as annotated history** (not erased); a new "Amendments carried by P6.7" block records `plan_has_adr=False`, **no Accept gate**, architect ratification 2026-06-14, dual-lens reviews the inscription. Matches the plan's P6.7-5 spec point-for-point. No new ADR; no other ADR touched. ✓

## Forcing-function checks

- **No plan-external expansion** — diff is exactly the 8 files the plan named; nothing outside the path map.
- **Spine byte-frozen** — no spine file appears in the diff at all (`_execute_local_call`, gate trio, `_countdown_sweeper`/`_writer_approve_helper`, `run_pipeline`, `_schedule_sweeper`, and all schedule-endpoint *logic* are zero-diff; the only logic change is `pipeline/schedule.py`).
- **No new dependency** — `pyproject.toml` diff is empty; `croniter` not added; stdlib `datetime`/`UTC` only (ratified C1=(a), ADR-040 D1 posture preserved).
- **No new `LLMPurpose`** — cron arithmetic is code; the diff introduces no `LLMPurpose`; the only LLM in a scheduled run stays the content-gen inside the byte-unchanged `run_pipeline`.
- **codegen-lock** — `openapi.json` + `ui/src/api/schema.ts` regenerated together (#95/#64 precedent); both description-only.

## Non-blocking notes (advisory — do not gate merge)

1. **`a/n` token accepted beyond the inscribed grammar.** `_expand_field` treats a single-value-with-step term `a/n` (e.g. `5/2`) as "from `a` to domain-max stepped by `n`" — a 6th term form not in the inscribed token list `* */n a-b a-b/n a,b,c`. This is **permissive only** (no valid expr is wrongly rejected; none of the plan's enumerated malformed-reject classes is affected) and matches genuine Vixie `N/M` semantics, so it is **not a behavioral infidelity** against any ratified accept/reject case. The mismatch is purely that the parser accepts slightly more than the ADR text enumerates. Recommend the dual-lens/architect decide between (a) acknowledging `a/n` as a Vixie-faithful superset in the ADR token list, or (b) tightening the parser to the strict 5-form subset. Either is a one-touch follow-up; neither blocks this slice.

2. **Parser duplication: `_expand_field` vs `_expand_field_dow`.** The two are ~40 lines of near-identical structure, diverging only in the DOW 0-7/wildcard-spans-0-6 handling. The plan prescribed only "a new module-private parser" without structure, so this is a code-quality observation, not a fidelity issue. A future refactor could parameterise the wildcard ceiling; out of scope here.

3. **Cosmetic comment nit** in `test_create_schedule_valid_cron_201` — the inline comment says "multiple of 300_000 ms" but the assertion is `next_fire % 60_000 == 0` (whole-minute). The assertion is correct; the comment is slightly misleading. Trivial.

## Routing note

This plan-vs-impl review is the senior gate. Per `requires_cross_family_review: true`, the full-impl **dual-lens (R0-A ∥ R0-B)** still follows — R0-B's exhaustiveness lens is well-aimed at the greenfield evaluator (the `a/n` over-acceptance and the union/weekday/horizon guards are the natural targets). Note 1 is the only finding worth the architect's attention; it is advisory, not a routing decision I am making.
