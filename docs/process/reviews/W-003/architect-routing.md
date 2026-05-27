---
task_id: W-003
kind: architect-routing
date: 2026-05-27
reviews_acked:
  - R0-A-on-plan.md
decisions:
  Y1: α (senior pre-investigates `_has_commit_since` at plan revision; pins call up-front)
  Y2: α (senior pre-pins `_git_show` helper extract upfront in W-003-1)
---

# W-003 architect routing — "ack all leans"

**Architect decisions (this session):** both Y findings resolve to reviewer's lean α. The recurring "decision deferred to junior at impl-time" pattern (now 3 instances counting P1.5 R0-A Y1) is being closed at the plan-revision boundary, not at impl-time.

This file is the **signal artifact for the senior revision session**. The senior session that picks W-003 next reads this file + R0-A-on-plan + the current plan and applies the routed actions.

## Per-finding routing

### Y1 → α — Senior pre-investigates `_has_commit_since` at plan revision

**Action:** senior reads `_has_commit_since` body in `src/orchestrator/workflow/cli.py` during plan revision. ~5-10 minutes of grep + read. Pins the call:

- **If correct-by-design** (the function's current "any local commit since X" semantic matches what auto-trigger needs; local commits not yet pushed legitimately count as "junior activity since plan-publish"): plan §2 W-003-1 acceptance language updates to "investigation confirmed correct-by-design; no fix needed. `_has_commit_since`'s current semantic — 'any local commit since `since`' — is what `next_state`'s `junior_impl_commit_present` check needs, because junior commits land locally first then push. Reading from origin/main would miss the in-flight commit. Documented as intentional asymmetry from RC-16."
- **If buggy** (same RC-16 shape; auto-trigger fires on local-only commits in error-prone scenarios): plan §2 adds W-003-1b atomic explicitly with fix scope + tests. Could bundle into W-003-1 if fix is ≤10 LoC (per Y2 helper extract, W-003-1 already touches subprocess shape; one more call site is incremental).

**Removes the impl-time scope-decision burden from junior.** Plan §5 self-discovery #1 is replaced with "pre-investigated; result: <correct-by-design | buggy + W-003-1b atomic>."

### Y2 → α — Senior pre-pins `_git_show` helper extract upfront in W-003-1

**Action:** plan §2 W-003-1 acceptance language updates to specify the helper extract:

```python
# src/orchestrator/workflow/io.py
def _git_show(rel_path: str, ref: str = "origin/main") -> str | None:
    """Return file content from a git ref via subprocess. None if not found.

    Centralizes subprocess error handling (timeout; non-zero exit;
    missing-file return-None semantic) for git-show callers.
    """
    try:
        result = subprocess.run(
            ["git", "show", f"{ref}:{rel_path}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    return result.stdout
```

W-003-1 uses `_git_show(rel_path)` inside `_read_plan_frontmatter`. W-003-3 uses `_git_show(f".workflow/{task_id}.yaml")` inside the extended `verify-workspace` divergence detection. If Y1 investigation reveals `_has_commit_since` is buggy → W-003-1b (or W-003-1 extension) uses the same helper.

**Rationale:** centralizes subprocess error-handling (timeout + non-zero + missing-file) at one boundary; W-003-3 tests don't need to duplicate the subprocess-mock pattern from W-003-1; future call sites (W-004+) inherit the helper. Cost: ~5-10 LoC helper + identical-shape tests at one location instead of two-three.

Plan §5 self-discovery #3 is replaced with "pre-pinned: `_git_show` helper extracted in W-003-1 per architect routing Y2 → α; W-003-3 consumes; future call sites inherit."

## Senior revision actions (derived)

1. **W-003-1 acceptance update**: insert `_git_show` helper spec (per Y2 above); update tests to include helper-level subprocess mocking. `_read_plan_frontmatter` calls `_git_show(rel_path)` instead of inlining subprocess.
2. **W-003-1 acceptance update (Y1 result)**: senior runs the `_has_commit_since` investigation; documents result + updates plan acceptance accordingly. Either "correct-by-design — no fix" OR "buggy — W-003-1 extended (or W-003-1b atomic) to fix using `_git_show` helper."
3. **W-003-3 acceptance update**: state-file divergence detection uses `_git_show(f".workflow/{task_id}.yaml")` consistent with W-003-1.
4. **Plan §5 self-discoveries cleanup**: #1 and #3 reclassified from "deferred-to-impl" to "pre-resolved per architect routing." Self-discovery #2 (verify-workspace invariant scope; YAGNI) stays as-is.

## Pattern-recurrence note for future plans

P1.5 R0-A Y1 (required-vs-default for `Agent.applies_to`) + W-003 R0-A Y1 + Y2 = **three instances of "decision deferred to junior at impl-time" pattern**. Three-instance threshold for codifying a discipline rule.

**W-003 retro should capture as candidate**: `senior-planner.md` addendum stating "plan §5 self-discoveries flagged as deferred-to-impl should be pre-resolved in plan revision unless the impl-time decision genuinely depends on impl-time data." The discipline closes the role-collapse failure mode where architecturally-relevant decisions migrate downward through the role stack to junior.

Defer the codification itself to **W-004 brief** (alongside other accumulated process refinements) OR **architect-partner-direct addendum** to `senior-planner.md` if architect prefers a smaller cleanup. Not in W-003 scope (W-003 is code-only mechanical refinement).

## Status flips that follow

Once the senior revision pass lands on `claude/W-003-plan`:

- **R0-A verdict bumps `needs_architect → clean`** per RC-10 codified protocol (now codified in `reviews/README.md` post-`6365cce`; 7th project use).
- **PR opens** for `claude/W-003-plan`; merge brings senior plan + R0-A + this routing onto main alongside the pre-existing RC-10 + RC-15 codifications (clean 3-way merge per R0-A G7).
- **`workflow advance --task-id W-003`** fires `awaiting_senior_plan → awaiting_junior_impl` directly (W-002-2b no-ADR routing; third use after W-002.5 + P1.5.5-original).
- **Junior dispatches** to `claude/W-003-impl`; parallelism set [W-003-1 ‖ W-003-4] runs as 2 parallel agents per `senior-planner.md` RC-17-codified rule (first post-codification use).

## Out of scope for this routing

- Re-litigating any 🟢 finding from R0-A (all 8 confirm plan structural soundness).
- Re-opening brief's 6 architect-settled decisions.
- Cross-family R0-B for W-003 — already skipped per brief + RC-15 narrowly-applied precedent.
- Codifying the "decision-deferred-to-impl" pattern in `senior-planner.md` (W-004 brief OR architect-partner-direct addendum; orthogonal to W-003 impl).

## Cross-references

- `docs/process/reviews/W-003/R0-A-on-plan.md` — lean source.
- `docs/process/senior-plans/W-003.md` — file the senior revision session edits.
- `docs/process/reviews/README.md` (post-merge) — RC-10 verdict-bump protocol for the post-absorption R0-A verdict bump.
- `docs/process/dual-lens-r0b.md` (post-merge) — RC-15 dual-lens R0-B reference (not invoked for W-003; skip per brief).
- `docs/process/senior-planner.md` § "Self-organization on session start / resume" — the rule auto-routing senior revision session to this artifact.
