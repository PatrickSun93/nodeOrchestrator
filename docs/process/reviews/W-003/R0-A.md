---
task_id: W-003
round: R0-A
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 6
---

# W-003 R0-A review

| Field | Value |
|---|---|
| Round | R0-A (post-impl, architect-partner) |
| Reviewer | architect-partner (Claude Opus 4.7, 1M context) in primary session |
| Date | 2026-05-27 |
| Artifacts reviewed | 5 impl commits on `claude/W-003-impl`: `5e07f17` (W-003-1), `284c175` (W-003-4), `fb14aff` (W-003-2), `d590ba6` (W-003-3), `db89e3a` (W-003-5). Plus senior plan-vs-impl `a6288bd` (read to avoid duplication; verdict clean; 5 🟢). +650 / -26 lines across 8 files. **693 tests post-impl** (was 677 at P1.5 close; +16). |
| Brief lean | R0-A dispatch per brief default for workflow refinement cycles (W-002 + W-002.5 precedent). |
| Distinct from plan-vs-impl | Senior plan-vs-impl (`a6288bd`) covered: 5 task acceptance, both architect-routing items (Y1+Y2 → α), 6 push-backs honored. This R0-A focuses on **Y1 + Y2 absorption verified in code**, **RC-13 forcing function correctness**, **RC-16 fix completeness**, **RC-17 codification dogfood** (first post-codification parallelism use), **CLAUDE.md fit-for-purpose**, **forward implications for P1.5.5**. |

---

## Findings

### 🟢 G1 — Y1 + Y2 absorption verified in code

**Y2 — `_git_show` helper extract:** `src/orchestrator/workflow/io.py:_git_show` matches the architect-routing spec exactly:
```python
def _git_show(rel_path: str, ref: str = "origin/main") -> str | None:
```
Centralizes: `subprocess.run` with `timeout=10`; `TimeoutExpired` catch returning `None`; non-zero exit returning `None`; missing-file semantic via stdout. Both consumers (`_read_plan_frontmatter` in W-003-1; `cmd_verify_workspace` divergence-detection in W-003-3) call the helper instead of inlining subprocess.

**Y1 — `_has_commit_since` UNTOUCHED:** `git show 5e07f17 -- src/orchestrator/workflow/cli.py | grep -c "_has_commit_since"` returns 0 (verified independently). Function body preserved per Y1 → α "correct-by-design; intentional asymmetry" routing. No silent drift; no W-003-1b atomic landed.

Both routing absorptions held at the code level, not just the plan/spec level. **Routing-→-impl trace is clean.**

### 🟢 G2 — RC-13 forcing function (`verify-merge-readiness`) implementation correct

`cmd_verify_merge_readiness` in `cli.py:415` (+ subparser registration at line 614):
- Checks both `plan-vs-impl.md` AND `R0-A.md` exist + parse `verdict: clean` via existing `parse_verdict` helper.
- Output: structured single-line + 1-3 detail lines per warning (matches `workflow status` style per push-back #3).
- Exit code 0 unconditionally (warn-don't-block per brief Architect-settled decision 2; matches `verify-workspace` discipline).
- Graceful handling of malformed frontmatter (parse fails → "could not parse" + treated as non-ready; exit 0).

5+ tests in `test_cli.py` (happy path + missing plan-vs-impl + missing R0-A + non-clean plan-vs-impl + non-clean R0-A). 

**This is the forcing function P1.4 retro §4 RC-13 said was the codification target.** Future cycles: architect runs `uv run workflow verify-merge-readiness --task-id <task>` before opening PR; structured output names which review is missing or what verdict is non-clean. P1.4 PR #10 pattern (merge-before-reviews) becomes detectable pre-merge.

### 🟢 G3 — RC-16 fix completeness verified

`_read_plan_frontmatter` in `io.py` now consumes `_git_show(rel_path_str)`:
- Reads from `origin/main` semantically; uncommitted working-tree mods don't fire bogus state advances.
- Backwards compat: plans on origin/main return their content as before; bug only affected sessions with uncommitted local mods.
- Edge case (plan on branch awaiting merge): treats "not on origin/main" as "no frontmatter" via fallback; matches ADR-008 D1 "merge IS the publish event" semantic.

Tests in `test_io.py` (101 LoC new) cover:
- Helper-level: existing ref + existing file → content; existing ref + missing file → None; subprocess timeout → None; non-zero exit → None.
- `_read_plan_frontmatter`-level: helper returns valid frontmatter → parsed dict; helper returns no frontmatter → None; helper returns None → None.

**Senior used `monkeypatch.setattr` on `_git_show`** for caller tests (helper has subprocess-level tests; callers don't re-mock subprocess). Cleaner than W-002.5's inline subprocess mocking pattern, as architect-routing predicted.

### 🟢 G4 — RC-17 codification dogfood: parallelism rule first post-codification use held

Plan §3 declared `[W-003-1 ‖ W-003-4]` parallel set. Actual commits:
- `5e07f17` "W-003-1: _git_show helper + _read_plan_frontmatter reads origin/main" ✓
- `284c175` "W-003-4: verify-workspace pre-landing discipline in CLAUDE.md" ✓

**Two standalone commits with respective task-id subjects per the RC-17 codified rule** (`senior-planner.md` post-`7606093`). No bundling. **First post-RC-17-codification parallelism use; discipline held.**

P1.5 bundled P1.5-4 under P1.5-6 (the precedent gap that prompted RC-17 codification); W-003 closed the loop. The codification works.

### 🟢 G5 — `CLAUDE.md` addition fit for purpose (W-003-4)

`CLAUDE.md` lines 26-31 carry the `## Workflow verify-workspace pre-landing` section with exact wording from plan acceptance:

> "Before pushing any landing commit (5-surface scan committed), run `uv run workflow verify-workspace`. If output surfaces a warning, address it OR note in commit body explicitly. The CLI exits 0 always; the architect lens on warnings is the load-bearing check."

Docs-gap-not-env-issue hypothesis from brief push-back #4 + plan §5 #4 lean held: env was fine in P1.4 + P1.5 + P1.5.5-brief; junior just didn't know to run it. The docs addition closes the discoverability gap.

W-003-5 landing commit body confirms `verify-workspace` was run before push — first self-validation of the new discipline. **W-003 dogfoods its own W-003-4 addition.**

### 🟢 G6 — Test count + quality

Test count: 677 → 693 (+16). Distribution per the impl:
- W-003-1 + RC-16 fix: `test_io.py` (new file, 101 LoC) covering `_git_show` helper-level + `_read_plan_frontmatter` integration via monkeypatch.
- W-003-2: `test_cli.py` extension (+291 LoC) — large because verify-merge-readiness has 5+ test cases × tracking-table-style output assertions.
- W-003-3: `test_cli.py` divergence-detection tests via `_git_show` monkeypatch.
- W-003-4: no automated tests (docs change; manual smoke-test in W-003-5 commit body).

All 25+ constitutional tests remain green (no new module; no new layering edge — confirmed). mypy strict 101 source files (+1 from P1.5's 100; the +1 is `io.py` gaining the `_git_show` helper as a new public symbol).

---

## Cross-checks

- [x] All 693 tests green; ruff/format/mypy strict clean across 101 source files.
- [x] Constitutional tests preserved (no LLM imports in `workflow/`; no reverse imports).
- [x] Y2 `_git_show` helper exact spec at `io.py:19-30`; both consumers (W-003-1 + W-003-3) call helper, not inline subprocess.
- [x] Y1 `_has_commit_since` UNTOUCHED — `grep -c` returns 0 in W-003-1 commit diff (independent verification).
- [x] RC-13 `cmd_verify_merge_readiness` implements warn-don't-block + structured output + 5+ tests.
- [x] RC-16 `_read_plan_frontmatter` reads origin/main via helper; tests cover helper + integration paths.
- [x] RC-17 codification dogfood: parallelism set `[W-003-1 ‖ W-003-4]` produced 2 commits with respective subjects.
- [x] CLAUDE.md docs-gap fix lands at lines 26-31; W-003-5 dogfoods the new discipline.
- [x] State file `.workflow/W-003.yaml` advances cleanly per ADR-008 D1 auto-trigger chain.
- [x] Cycle stays at 1 throughout (no overrides; 5th consecutive zero-override cycle after W-002.5 + P1.4 + P1.5 + (P1.5.5 still pending)).

---

## Forward implications for P1.5.5 + beyond

**P1.5.5 inherits a cleaner substrate post-W-003:**

- **`_read_plan_frontmatter`-reads-origin/main** — P1.5.5 plan (when it lands) gets RC-16-safe state advances. No bogus advances against uncommitted local plan files.
- **`verify-merge-readiness` available pre-PR** — architect runs it pre-merge on P1.5.5-impl; structured output names missing reviews; closes the P1.4 PR #10 gap.
- **`verify-workspace` divergence detection** — junior session opening on P1.5.5 will surface any local state-file divergence at session start.
- **`CLAUDE.md` verify-workspace pre-landing** — junior session knows to run verify-workspace before landing commit (closes P1.4 R0-A G4 watch).

**P1.6 (snapshot mechanics + decision log + e2e) sits on a fully-mature workflow substrate.** No deferred RC-debt; all four W-003 closures + W-002 + W-002.5 + the RC-10 + RC-15 + RC-17 codifications collectively form the post-substrate-cleanup baseline.

**Override count freezes at 2** (P1.3 + W-002 pre-fix bridges). **5 consecutive zero-override cycles**: W-002.5 → P1.4 → P1.5 → W-003 → (P1.5.5 pending). The harness substrate has reached its mature steady state.

---

## Net assessment

**Verdict: clean.** Six 🟢; zero 🔴; zero 🟡.

W-003 is **mechanical refinement done well**:
- All 4 brief In-scope items implemented per acceptance.
- Both architect-routing items (Y1+Y2 → α) absorbed faithfully at the code level, not just the spec level.
- RC-13 + RC-16 + RC-17-dogfood all close their respective deferred items.
- First post-RC-17-codification parallelism use held the discipline (2 standalone commits with task-id subjects).
- Tests + gates all green; 16 new tests; mypy strict clean across 101 source files.

**Recommendation: state machine auto-trigger chain (`awaiting_senior_plan_vs_impl → awaiting_R0_A → awaiting_PR_merge`) fires on next `workflow advance --task-id W-003`.** Three-advance close shape matching W-002 + W-002.5 + P1.4 + P1.5 close. PR merge → `closed`.

## Captured for W-003 retro

- **5-consecutive-zero-override-cycle streak** (W-002.5 → P1.4 → P1.5 → W-003 → next; P1.5.5 pending). Harness substrate at mature steady state.
- **First post-RC-17-codification parallelism use held cleanly** — discipline gap from P1.5 closed by W-003 commit-subject discipline (2 standalone commits per the parallel set).
- **Pattern-recurrence (3-instance threshold) of "decision deferred to junior at impl-time"** captured in architect-routing.md; codification target W-004 brief OR architect-partner-direct `senior-planner.md` addendum. Not addressed in W-003 (out-of-scope).
- **W-003-4 dogfood**: W-003-5 landing commit body confirms `verify-workspace` was run pre-push — first self-validation of the new discipline addition. The fix tests itself in the same cycle.
- **`_git_show` helper centralization** sets precedent for future subprocess shims (if W-004+ needs `_git_log` or `_git_diff`, the centralization pattern is established).
