---
task_id: P7
review_type: plan-vs-impl
reviewer: senior
cycle: 1
verdict: clean
impl_commits:
  - ce71805  # P7-1 skills/loader
  - cea653b  # P7-6 autonomy/config
  - e302728  # P7-7 autonomy/scoring
plan: docs/process/senior-plans/P7.md
brief: docs/process/architect-briefs/P7.md
---

# P7 plan-vs-impl — verdict: clean

Verdict formed **independently** from a diff-level read of the three impl atomics
against `senior-plans/P7.md` + the corrected brief, before reading `R0-A.md`. The
unique senior lens here is plan-vs-deliverable (does the impl drift on a
plan-implied invariant the acceptance surface doesn't pin?), not deliverable-vs-spec.

## Per-atomic audit

### P7-1 — `skills/loader.py` (ce71805) — faithful, strictly more robust

- `seen_paths: dict[str, Path]` is declared beside `skills` (`:92`) and populated
  in lockstep at registration (`seen_paths[skill.id] = md_path`, `:131`).
- The duplicate branch reads `existing_path = seen_paths[skill.id]` (`:123`); the
  `next(p for p in directory.rglob("*.md") ...)` expression is deleted entirely.
  Both plan-mandated defects are closed: (a) no error-path re-traversal; (b) no
  `next()`-without-default `StopIteration`.
- The dict lookup is **guaranteed to hit** — the branch is reached only when
  `skill.id in skills`, and `skills`/`seen_paths` are written together — so even the
  theoretical empty-generator footgun is gone (the new code can't raise `KeyError`
  on the error path). Strictly more robust than the plan's minimum.
- ADR-009 D8 (`stem == id`) and the raise-on-duplicate contract are untouched.
  `SkillError` still carries `path=md_path`, `field="id"`.
- **Acceptance criteria met.** No out-of-scope edits (docstring, `stem != id`
  branch, discovery pass all untouched).

### P7-6 — `autonomy/config.py` (cea653b) — faithful

- `@model_validator(mode="after") _window_ge_sweep` raises `ValueError` when
  `window_s < sweep_interval_s`; `model_validator` is the only new import.
  `frozen=True` / `extra="forbid"` untouched.
- Equal case passes (reject condition is strict `<`); defaults (300/30) satisfy.
  The loader (`load_countdown_auto_fire_config`, `:52-55`) already wraps
  `ValidationError → ValueError("…countdown_auto_fire: …")`, so the new check
  inherits the refuse-start path with no loader change — exactly as the plan
  predicted.
- **Acceptance criteria met.**

### P7-7 — `autonomy/scoring.py` (e302728) — faithful, RC-19 guardrail held

- A 2-line comment above `eff_confirm = max(0, …)` explains the floor (tier-ladder
  inversion, ADR-005 D4/D5). **Zero executable change** — the comment is the only
  diff (1 file, +2 lines); `decide_tier` / `eff_confirm` / `eff_auto` logic is
  byte-identical.
- **`eff_auto` (`:177`) is not touched** — the P1.5.5 RC-19 out-of-scope-bundle
  risk is fenced. The comment even inscribes "eff_auto intentionally has no floor",
  reinforcing the deferred-residual posture rather than acting on it.
- **Acceptance criteria met.**

## Cross-cutting

- **Out-of-scope non-issues untouched.** The three commits touch only
  `skills/loader.py`, `autonomy/config.py`, `autonomy/scoring.py` (+ their tests).
  `agents/loader.py` (#2), `agents/dispatch.py` (#3), `agents/selection.py` (#5),
  `autonomy/emission.py` (#4) are all unmodified — #5's intentional newest-first
  walk is **not** "fixed" (no behavior regression introduced).
- **Constitutional spine zero-diff.** No `_execute_local_call` / gate-decision edit;
  no new `LLMPurpose`. P7-7's only autonomy-gate-adjacent change is a comment.
- **ADR.** No new ADR; no ADR-040 D7 amendment note (plan §5 senior judgment —
  the validator tightens within D7's existing fail-closed contract). Impl message
  for P7-6 restates the same reasoning. Consistent.

## 🟢 Observations (non-blocking — no action required this cycle)

1. **P7-1 regression test scope.** `test_duplicate_id_names_both_paths_no_stopiteration`
   asserts both paths appear in the error and `field == "id"`. With two real
   same-stem files present, the *old* `next(rglob)` would also have found the other
   path — so the test confirms the new behavior is correct but does not, by
   construction, reproduce the original empty-generator `StopIteration` (which was
   only reachable if the earlier file vanished mid-load, a TOCTOU). This is fine:
   the brief framed #1 as error-path robustness, and the new dict lookup removes
   the footgun unconditionally. The test is adequate for the acceptance criterion.

2. **P7-6 test asserts at construction, not at load.** The new tests instantiate
   `CountdownAutoFireConfig(window_s=10, sweep_interval_s=30)` and expect
   `ValidationError`. The brief/plan wording is "ValueError **at load**"; the
   loader-path `ValidationError → ValueError` wrap for *this* validator is covered
   only transitively by the pre-existing malformed-section loader test, not
   asserted end-to-end. The wrap is verified correct by reading `config.py:52-55`,
   so behavior is right; a future hardening could add one loader-path assertion to
   pin the brief's exact wording. Non-blocking.

## Verdict

**clean.** All three atomics implement the plan and brief faithfully; the RC-19
`eff_auto` fence and the constitutional spine zero-diff both hold; out-of-scope
non-issues are untouched. The two 🟢 observations are test-surface notes, not
drift — no plan-implied invariant is violated. Per ADR-008 Amendment 1 (W-005,
Route B), state advances to `awaiting_R0_A`.
