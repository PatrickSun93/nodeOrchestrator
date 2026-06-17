---
task: P7
cycle: 1
stage: impl
review: R0-A
reviewer: architect-partner
verdict: clean
date: 2026-06-17
impl_reviewed: claude/P7-impl @ 7623597 (atomics ce71805 / cea653b / e302728)
plan: docs/process/senior-plans/P7.md
brief: docs/process/architect-briefs/P7.md
---

# R0-A (impl) — P7 (loader cleanup + config/scoring hardening)

## Verdict: `clean`

All three atomics faithfully implement the plan + brief. The RC-19 `eff_auto`
guardrail and the #2/#3/#4/#5 out-of-scope fences are honored, the constitutional
spine is byte-untouched, and the full gate is green (verified by me, not just
trusting the junior's "gates green"). No `🔴` / `🟡`. One `🔵` test-completeness
nit, non-blocking.

## Method

Reviewed the diff `main..claude/P7-impl` per atomic against the plan + brief +
the live ADR clauses; re-ran the full gate after `uv sync --all-extras`.

## Per-atomic verification

### P7-1 `ce71805` — `skills/loader.py` — clean
- `seen_paths: dict[str, Path] = {}` added beside `skills`; recorded
  `seen_paths[skill.id] = md_path` at the registration point (after the
  `stem == id` check, so every entry is keyed by a verified `stem == id` — the
  dup branch can never `KeyError`).
- The duplicate branch now reads `existing_path = seen_paths[skill.id]` — the
  redundant `next(p for p in directory.rglob("*.md") …)` and its **bare
  `StopIteration` footgun** (+ the TOCTOU re-scan) are gone.
- `SkillError` still cites **both** paths and keeps `path=md_path, field="id"`.
  ADR-009 D8 (`stem == id`) untouched. Matches plan P7-1 + brief #1 exactly.

### P7-6 `cea653b` — `autonomy/config.py` — clean
- `@model_validator(mode="after") _window_ge_sweep` raises `ValueError` when
  `window_s < sweep_interval_s`, message cites both values + "ADR-040 D7
  fail-closed". Returns `self`.
- **No loader change** — confirmed correct: the validator's `ValueError` surfaces
  as `ValidationError`, caught by the existing `except ValidationError` (`:54`)
  and wrapped into the `countdown_auto_fire:` `ValueError` (refuse-start). `import`
  adds only `model_validator`. `frozen=True`/`extra="forbid"` untouched. Matches
  plan P7-6 + brief #6.

### P7-7 `e302728` — `autonomy/scoring.py` — clean (guardrail honored)
- A 2-line comment explains the `eff_confirm` `max(0, …)` floor (a negative
  `eff_confirm` would pull all scores into `COUNTDOWN_CONFIRM`, inverting the tier
  ladder; ADR-005 D4/D5).
- **`eff_auto` is byte-untouched** — and the comment explicitly states
  "eff_auto intentionally has no floor." The RC-19 / P6-deferred-residual
  guardrail is honored, and now self-documenting. `decide_tier` logic byte-identical.
  Matches plan P7-7 + brief #7 (doc-only).

## Guardrails (affirmed)

- **RC-19** (the live risk this cycle): `eff_auto` **not** clamped. ✓
- **#5** `selection.py` newest-first walk **untouched**; **#2/#3/#4** untouched. ✓
- **Constitutional spine zero-diff**: the diff touches only `loader.py` /
  `config.py` / `scoring.py` + their two tests + the state file —
  `_execute_local_call`, the gate decision logic (`decide_tier`/`score`/
  `emit_gate_decision`), and `LLMPurpose` are byte-untouched. ✓

## Gates (re-verified)

- `ruff format --check`: clean (310 files).
- `ruff check`: all checks passed.
- `mypy --strict` (`src tests`): **Success, 0 issues / 310 files** — after
  `uv sync --all-extras`. (The transient 86 `fastapi`/`fastapi.testclient`
  `import-not-found` errors were an un-synced-venv artifact in `tests/api/`, not a
  P7 regression — no P7 file appeared in them. [[reference-isolated-gate-run-extras]].)
- `pytest`: **`PYTEST_EXIT=0`** (all passed). One **pre-existing, non-P7** warning:
  a `net_trust` DNS-timeout test leaks a daemon-thread `LocalToolError`
  (`hung.example.invalid`) as a `PytestUnhandledThreadExceptionWarning` —
  `net_trust.py` is untouched by P7; non-fatal (warnings don't affect exit code).

## 🔵 N-1 — test completeness (non-blocking)

`test_window_lt_sweep_raises` asserts `ValidationError` on **direct construction**
(`CountdownAutoFireConfig(window_s=10, sweep_interval_s=30)`). The brief's wording
is "`ValueError` **at load**." The validator + the loader-wrap are both correct,
and the equal-boundary + defaults cases are covered, so this is a directness nit,
not a gap: a loader-path test (a YAML with `window_s < sweep_interval_s` →
`load_countdown_auto_fire_config` → `ValueError` carrying the `countdown_auto_fire:`
prefix) would exercise the brief's literal "at load" contract. Optional.

## Expected next

`plan-vs-impl` (senior) is pending. If the senior verdict is also `clean`,
joint-verdict + merge-clean advances `AWAITING_R0_A → AWAITING_PR_MERGE`; the PR
merge stays the architect's gate. I'll synthesize both reviews (overlap +
divergence) for you before the merge call.
