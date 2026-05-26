---
task_id: W-001-impl
round: R0-A
verdict: needs_architect
findings_count:
  red: 0
  yellow: 1
  green: 4
---

# W-001-impl R0-A review

| Field | Value |
|---|---|
| Round | R0-A (post-impl, architect-dispatched per ADR-008 Decision 1) |
| Reviewer | A (architect-partner Claude session) |
| Family | Claude (Opus 4.7) — same as junior and senior plan-vs-impl |
| Cross-family R0-B | not dispatched (RC-2 evidence trail; 5th consecutive P1.2+ skip) |
| Lens | Code-level edge cases + env-portability + senior 🟢 verification + cross-checks senior may not have run |
| Commits in scope | `04eaf97` → `8ffabff` (impl-1..9) + `384c875` (senior plan-vs-impl) on `claude/w-001-impl` |
| Gates | ruff ✓ / ruff format ✓ / mypy --strict 64 files ✓ / **pytest: 1 failed, 378 passed** |

## Findings

| # | 🚦 | Where | What | What should be |
|---|----|-------|------|----------------|
| R0-A-1 | 🟡 | `tests/workflow/test_integration.py:36-50` (`git_repo` fixture) | **End-to-end integration test fails in environments with `commit.gpgsign=true` globally.** Fixture initializes a tmp git repo, sets `user.email` and `user.name`, but does NOT disable commit signing. If the host's global git config has `commit.gpgsign=true` (common in dev environments with security tooling, also possible in some CI runners), `git commit --allow-empty` returns exit 128 with signing-server errors. **Test passes on senior's env, fails on architect-partner's env (this session) and any environment with global signing enforced.** Senior's plan-vs-impl claim "pytest 78 tests green" was true on senior's machine, not on this branch under broader conditions. The 376 other tests pass; only the e2e integration test trips. Practical impact: any future contributor reviewing this branch in a stricter env hits a failed test on first checkout. | Add one line to the `git_repo` fixture: `subprocess.run(["git", "-C", str(tmp_path), "config", "commit.gpgsign", "false"], check=True, capture_output=True)` immediately after the `user.name` config. Defensive — repo-local config override, doesn't touch the host's global setting. Single-commit junior fix (mirroring C3 Y1 / C4 Y1+G1+G3 pattern). |
| R0-A-2 | 🟢 | `src/orchestrator/workflow/cli.py:43, 50, 126` + artifact-snapshot builder lines 138-139 | **`_REVIEW_FILENAMES` constant is defined but unused for actual filtering.** Senior plan-vs-impl flagged this as "nonexistent constant" — minor wording error; the constant IS defined at line 43, but the artifact-snapshot builder (cli.py:138-139) hardcodes `"plan-vs-impl.md"` and `"R0-A.md"` as literal path strings instead of iterating the constant. The constant lists `R0-B.md`, `R1-A.md`, `R1-B.md` which are NEVER read. Docstring at line 50 says "Only call with filenames from _REVIEW_FILENAMES" but the actual filter is the hardcoded literal paths. Effectively dead code. | Either: (a) delete `_REVIEW_FILENAMES` and update docstrings to drop the reference; (b) wire the builder to iterate `_REVIEW_FILENAMES` (more extensible — when R0-B / R1-A appear, the builder picks them up automatically; but the `ArtifactSnapshot` schema would need fields for them, which is a larger change). (a) is the "Run > polish" choice for now; (b) is the right shape for the future. Defer to W-001-impl close or W-002. |
| R0-A-3 | 🟢 | `src/orchestrator/workflow/transitions.py:183-200` (`record_override` cycle warning) | Confirmed senior's #2. `cycle >= 4` warning uses `print(..., file=sys.stderr)` instead of `warnings.warn`. Senior plan acceptance literally said "emit a stderr warning" — junior implemented the literal text. Conventional Python idiom is `warnings.warn`, which interacts with `pytest`'s `pytest.warns` ergonomics and respects user `-W` filtering. The current `print` choice is functional but unconventional. | Cosmetic; can defer. If addressed: swap `print(...)` to `warnings.warn(..., UserWarning, stacklevel=2)` and the test would exercise via `with pytest.warns(UserWarning): record_override(...)`. Not blocking. |
| R0-A-4 | 🟢 | `src/orchestrator/workflow/transitions.py:25-44` (ArtifactSnapshot, GateSnapshot) | Confirmed senior's #3. These two Pydantic models live in `transitions.py` rather than `schema.py`. The plan said either was acceptable; this location works (they're tightly coupled to `next_state` which lives here). Future reader scanning `schema.py` for "all Pydantic models" misses these two — but the file's module docstring and tightly-scoped use justify the placement. | Optional defer. If addressed: move to `schema.py` to centralize; would require import-cycle check (currently `transitions.py` imports from `schema.py`; moving would invert). Not blocking. |
| R0-A-5 | 🟢 | `src/orchestrator/workflow/cli.py:172-347` (numerous `print(...)` for errors and warnings) | Pattern consistency observation: the CLI uses `print(f"ERROR: ...", file=sys.stderr)` throughout — 12 instances. Each is functional but the pattern is repeated boilerplate. A small helper (`def _err(msg: str) -> None: print(f"ERROR: {msg}", file=sys.stderr)`) would tighten. Cosmetic; matches the "Run > polish" framing. | Defer to W-001-impl close-out or first time someone touches CLI for other reasons. |

**🔴 None.** Impl logic is correct; ADR-008 decisions all honored; constitutional test landed; freeze-vs-impl drift zero; layering preserved.

## Cross-checks performed

- **9 atomic tasks acceptance**: re-verified senior's coverage-of-plan-acceptance audit. All 9 task acceptance bullets satisfied per the diff. ✓
- **R0-A-on-plan items in impl**:
  - R0-A-on-plan-1 (b): `.workflow/W-001-impl.yaml` state is `awaiting_senior_plan_vs_impl` (impl-9's deterministic advance from impl-7's `awaiting_junior_impl`). Verified by reading the live state file. ✓
  - R0-A-on-plan-3 (drop `--strict`): `grep -n "strict" src/orchestrator/workflow/cli.py` returns 0 matches. ✓
  - R0-A-on-plan-4 (hook hard-error non-blocking): `.claude/settings.json` uses `; exit 0` to enforce; `docs/process/session-start-hook.md:24-31` documents and cites R0-A-on-plan-4. ✓
- **Constitutional tests**: `test_constitution_no_llm_calls_in_workflow_module` lands and passes; grep over `src/orchestrator/workflow/**.py` confirms no LLM SDK imports. ✓
- **Layering**: `src/orchestrator/workflow/` imports only from itself + stdlib + pydantic + yaml. No `orchestrator.autonomy` / `orchestrator.llm` / `orchestrator.core` imports. ✓
- **Freeze-vs-impl drift**: senior plan signatures (schema.py + transitions.py function signatures) match impl byte-for-byte where the plan specified exact code (schema.py impl-1 acceptance has full code block; matches impl). ✓
- **Frontmatter contract**: `docs/process/reviews/W-001-impl/plan-vs-impl.md` has correct frontmatter (task_id, round=plan-vs-impl, verdict=clean). This R0-A.md gains correct frontmatter (task_id, round=R0-A, verdict=needs_architect because of 🟡 R0-A-1, findings_count itemized). ✓
- **RC-1 graduation**: `docs/contributing.md` Q3 gained the pre-edit grep sub-bullet (impl-8). The sub-rule was also applied to impl-8's own doc edits per the plan. ✓
- **RC-7 mitigation**: `workflow verify-workspace` subcommand exists at `cli.py:319-356`; runs `git fetch origin` + `git status --short`; emits stderr warnings; exit 0 on divergence; module docstring cites RC-7. ✓
- **5-surface scan in impl-9**: tracking table present, 5 surfaces enumerated, RC-1 grep applied. ✓
- **Distance test**: ADR-008 Accepted 2026-05-21; impl 2026-05-26 (+5 days past floor); within plan-permitted window. ✓

## Senior plan-vs-impl review — accuracy audit

Architect-partner re-verified senior's 3 🟢 findings:

| Senior 🟢 # | Senior's claim | My read |
|---|---|---|
| 1 | "cli.py:126 docstring references **nonexistent** `_REVIEW_FILENAMES` constant; impl hardcodes paths directly. Docstring drift only." | Refined as R0-A-2 above. Constant **does exist** (cli.py:43); but it's **unused for actual filtering** (builder hardcodes literals at cli.py:138-139). Senior's spirit is right; the wording "nonexistent" is technically inaccurate. |
| 2 | "transitions.py:193 cycle warning uses `print(..., file=sys.stderr)` rather than `warnings.warn`" | Confirmed as R0-A-3. Accurate. |
| 3 | "ArtifactSnapshot / GateSnapshot live in transitions.py instead of schema.py" | Confirmed as R0-A-4. Accurate. |

Senior also claimed **"pytest: 78 tests green"** — this needs context. Total test count on this branch is **378 passed + 1 failed = 379 collected**. The "78 new tests added by W-001-impl" framing matches (`378 - 301 baseline = 77 new`, ~78). Senior's "78" was likely shorthand for "new tests added," not "total tests." The substantive issue is the **failing e2e integration test in environments with commit signing forced on** — flagged as R0-A-1 above. Senior's env did not trigger it; mine did.

## Architect-decision dependency

Before PR merge, architect picks resolution for R0-A-1:

- **(a)** Junior fix routing: single small commit on `claude/w-001-impl` branch adding `commit.gpgsign=false` config to the `git_repo` fixture. Mirrors C3 Y1 / C4 Y1+G1+G3 pattern. Then architect-partner light re-verify; then merge.
- **(b)** Accept as env-specific quirk: document in `tests/workflow/test_integration.py` docstring "requires `commit.gpgsign=false` in local git config or runs in env without signing." Senior's env was clean; future contributors may hit it. Weaker.
- **(c)** Skip; merge as-is. Test stays fragile; the failure surfaces for any future reviewer / CI configuration.

Architect-partner lean: **(a)**. One-line fixture fix; mirrors the established trivial-fix routing; eliminates the env-sensitivity entirely. Cost: one junior commit (~5 LoC including the line).

🟢 items (R0-A-2 through -5) are accept-or-defer-as-watch; none block.

## Verdict

**🟡 — impl is production-quality on all axes except one env-fragile test.** R0-A-1 is a real bug that surfaces in stricter environments; senior missed it because their env was permissive. Resolution is a single fixture line — same shape as prior Y1 fixes.

Frontmatter `verdict: needs_architect` per ADR-008 Decision 7: any 🟡 routes to `awaiting_architect_decision` for architect routing. Per ADR-008 Decision 1 auto-transition table: state machine should now route W-001-impl to `awaiting_architect_decision`, blocking the auto-PR-open path until architect rules R0-A-1 resolution.

Once R0-A-1 resolves:
- (a) → senior judges no plan-vs-impl re-review needed (single-line fixture fix is mechanical); junior pushes; architect-partner light re-verify; merge.
- (b) or (c) → merge as-is with documented env constraint.

🟢 items can fold into the same (a) fix-commit or defer to W-001-impl close-out as watch items.
