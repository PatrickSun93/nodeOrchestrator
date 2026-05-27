---
task_id: W-002.5
round: R0-A
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 4
---

# W-002.5 R0-A review

| Field | Value |
|---|---|
| Round | R0-A (post-impl, architect-partner) |
| Reviewer | architect-partner (Claude Opus 4.7, 1M context) in primary session |
| Date | 2026-05-27 |
| Artifacts reviewed | 2 impl commits on `claude/W-002.5-impl`: `c3f1fa3` (W-002.5-1), `5dceef5` (W-002.5-2); senior plan-vs-impl review `5a6e68c` (read to avoid duplication). 6 files touched; 478 tests post-impl (was 472; +6). |
| Brief lean | RC-9 default-skip per W-002 precedent. Architect-partner chose **dispatch** because the state-machine auto-trigger requires `R0-A.md` with verdict clean to advance `awaiting_R0_A → awaiting_PR_merge`; skipping means manual override. Cheaper to write a fast R0-A than introduce another override on a task whose entire purpose was closing override-frequency-creep. |
| Distinct from plan-vs-impl | Plan-vs-impl already enumerated impl-vs-plan acceptance compliance (2/2 tasks ✓, all 4 architect-settled decisions ✓, all 4 push-backs ✓, all 4 forcing functions ✓). This R0-A focuses on **architect-partner-distinct lens** — ADR-008 invariants under the multi-ADR extension; constitutional discipline; RC-16 latent-risk status; forward implications for P1.4 + W-003. |

---

## Findings

### 🟢 G1 — ADR-008 invariants preserved through multi-ADR aggregation

The W-002.5-1 change is the second extension to `_read_adr_status` after W-002-1. ADR-008 invariants checked:

- **D2 (`next_state` is pure function of `(current_state, artifacts, gates)`):** `_read_adr_status` is called by `build_artifact_snapshot` → returns `Literal["proposed", "accepted", "none"]` → fed into `ArtifactSnapshot.adr_status`. Signature unchanged; return type unchanged; pure-function chain preserved. `next_state` consumes the snapshot, not the file directly. ✓
- **D7 (frontmatter contract):** the `adr` field gains an additive shape (`str | list[str]`); W-002-1's single-string form is preserved bitwise. The `_read_plan_frontmatter` parser itself is unchanged — it returns the frontmatter dict as-is; the type-discrimination happens inside `_read_adr_status`. Cleanly layered.
- **D10 (override audit trail):** `record_override` unchanged; W-002.5 introduces no new override paths. W-002.5's entire lifecycle (`awaiting_senior_plan` → `awaiting_junior_impl` → ... → `closed`) is auto-trigger; zero override entries projected through close. **Cycle stays at 1 throughout** — this is the first task whose state-file cycle counter behaves correctly end-to-end under post-W-002-2 code (W-002-2's record_override fix takes effect on next override, but W-002.5 has no override to apply it to; the absence of override IS the test).

The multi-ADR-list raise was **removed** (W-002-1's `WorkflowError(f"multi-ADR-per-task not yet supported (W-003 scope)")`); this is the only spec-vs-impl direction change. The senior plan-vs-impl review verified the obsolete-test removal in `test_cli.py`. ✓

### 🟢 G2 — Constitutional discipline holds; zero new tests needed (correct)

W-002.5 introduces:
- No new module (extends existing `cli.py`).
- No new layering edge (intra-`workflow/` only).
- No new LLM-touching code path (constitutional test green).
- No new typed-metadata schema in `core/` (the multi-ADR aggregation is entirely in `workflow/cli.py`).

Plan correctly assessed "no new constitutional test expected." All 18 prior constitutional tests remain green (verified via `pytest tests/test_constitution.py` chains).

The `_normalize_adr_refs(adr_val, plan_path) -> list[str]` helper extraction (W-002.5-1) is a within-module refactor; no constitutional surface. **Defensive improvement over plan baseline**: junior added `.strip()` to empty-string element check (catches whitespace-only strings like `adr: [ADR-098, " "]`); plan-vs-impl flagged this as 🟢 #5 already. R0-A confirms: the defensive check is correct AND doesn't widen the contract (whitespace-only is always an authoring error per the project's general string-validation discipline).

### 🟢 G3 — RC-16 latent risk did not bite this cycle; remains for W-003

RC-16 (`_read_plan_frontmatter` reads working-tree, not `origin/main`) was captured in PR #11 body. This W-002.5 cycle exercised the relevant code path twice (state advance at `7c7391f` + plan-vs-impl post-impl). Both runs happened post-pull-from-main, so working-tree == origin/main; the risk window didn't open.

**Latent risk remains**: any future cycle where a session has uncommitted plan content can still trigger bogus state advances. W-003 fix paths:

- **(α) Read plan via `git show origin/main:path` semantically** — true canonical source. Adds subprocess overhead per advance; trivial cost.
- **(β) Document the locality + require post-merge advance pattern** — cheaper; relies on author discipline.

Lean for W-003: **(α)** — the auto-trigger semantic is "publish to main"; the impl should read main, not working tree. Cost is ~10 LoC + ~3 tests (mock `subprocess.run`).

**Not blocking W-002.5**; deferred to W-003 brief authorship. Captured here for retro.

### 🟢 G4 — Forward implications for P1.4 and W-003

**For P1.4 (immediate consumer):** W-002.5 closes the multi-ADR gap end-to-end. Post-merge sequence:
1. Architect-partner trivial-fix: add `---\ntask_id: P1.4\nadr: [ADR-010, ADR-011]\n---` to P1.4 plan frontmatter (~5 LoC; Architect-settled decision 3).
2. Architect bumps ADR-010 + ADR-011 status `Proposed → Accepted`.
3. `workflow advance --task-id P1.4` fires `awaiting_architect_accept → awaiting_junior_impl` via multi-ADR aggregation (both Accepted → `"accepted"` → state advances). **First multi-ADR clean advance in project history; zero overrides projected.**

**Override count history projection (post-W-002.5 merge + P1.4 ADR Accepts):**

| # | Task | Reason | Closed by |
|---|---|---|---|
| 1 | P1.3 `cfbf087` | RC-11(a) task→ADR mapping | W-002-1 ✓ |
| 2 | W-002 `236dac1` | RC-11(c) no-ADR routing | W-002-2b ✓ |
| (none projected) | W-002.5 | — | — (clean lifecycle; the proof that the cluster is closed) |
| (none projected) | P1.4 | — | W-002-1 + W-002.5 multi-ADR aggregation |

Override count stops at 2. **The override-frequency-creep audit #3 worried about is structurally closed.**

**For W-003 (next workflow-refinement task):** the natural scope absorbs three items:
- **RC-16** (working-tree-vs-origin/main read in `_read_plan_frontmatter`).
- **Granular N-of-M Accept tracking** (deferred from W-002.5 per brief; multi-ADR all-or-nothing aggregation may not scale to ADR-Accept-streamlining for tasks with 4+ ADRs).
- **`verify-workspace` divergence detection** (deferred from W-002 per its push-back #2).
- Plus optionally: RC-10 codification of post-resolution-frontmatter-bump protocol (P1.3 retro §4 graduation reached on P1.4 R0-B 4th use).

---

## Cross-checks

- [x] All 478 tests green; ruff/format/mypy strict clean across 75 source files (verified via `pytest` + `ruff check` + `ruff format --check` + `mypy --strict src tests`).
- [x] Constitutional tests preserved (no LLM imports in workflow/; no core→workflow edges introduced).
- [x] ADR-008 D2 pure-function invariant: `_read_adr_status` returns pure `Literal[...]`; no I/O leak into transitions.
- [x] ADR-008 D7 frontmatter contract: extended additively; W-002-1 single-string behavior preserved.
- [x] ADR-008 D10 override audit trail: shape unchanged; W-002.5 introduces no overrides.
- [x] Layering: `transitions.py → workflow/io.py` still the clean shape from W-002; W-002.5 doesn't widen this.
- [x] RC-11 cluster: 3/3 sub-findings closed (W-002-1 + W-002-2 + W-002-2b); W-002.5 closes the multi-ADR sibling.
- [x] Plan-vs-impl review present and clean (5 🟢 observations; 0 🔴 / 0 🟡).
- [x] Senior plan-vs-impl review identified the **first end-to-end W-002-2b proof** at `7c7391f` (state advance commit) — validates the dogfood intent.
- [ ] RC-16 (working-tree vs origin/main) — latent, not bitten this cycle; W-003 scope.

---

## Net assessment

**Verdict: clean.** Four 🟢 confirmatory findings; zero 🔴; zero 🟡.

W-002.5 is the cleanest cycle the project has run since W-001-impl:
- **First task with zero overrides through entire lifecycle** post-W-002 fixes landing.
- **First task whose state-file cycle counter stays at 1 throughout** (W-002-2's fix doesn't fire because no override fires; the absence IS the proof).
- **First end-to-end dogfood of W-002-2b** (no-ADR routing fires at `7c7391f`).
- **Closes the multi-ADR gap** that was projected to need 2-4 P1.4 overrides; now zero P1.4 overrides projected.

The W-002 → W-002.5 sequence demonstrates a learning-loop that worked correctly:
1. P1.3 surfaces RC-11 sub-findings (a) + (b) (commit `92f18d3`).
2. W-002 closes (a) + (b) and discovers sub-finding (c) during plan-writing.
3. W-002 closes (c) via W-002-2b — but multi-ADR remains gap.
4. W-002 plan §5 + W-002 R0-A "Forward implications" + audit #3 predict P1.4 will need 2-4 overrides without multi-ADR.
5. W-002.5 closes multi-ADR before P1.4 hits it.
6. W-002.5 itself runs through zero-overrides — the proof that the cluster is closed.

This is the harness's review-and-refinement discipline working end-to-end. The W-001 retro §9 prediction is now empirically validated under non-self-referential AND post-fix-validation pressure.

**Recommendation: state machine auto-trigger chain (`awaiting_R0_A → awaiting_PR_merge → closed`) fires on next `workflow advance --task-id W-002.5`** post-PR-merge. Same shape as W-002's clean three-advance close. Override count stops at 2.

Cross-family R0-B explicitly NOT dispatched (mechanical workflow refinement; RC-2 stays accepted for non-shape-change). This R0-A is the only post-impl review.
