# W-001 Retrospective — Candidates

Accumulating during the W-001 (workflow state machine) cycle. Folded
into the final `W-001.md` retrospective at task close-out, alongside
W-001-impl. Same accumulation pattern as `P1.2-candidates.md` per
the convention established at P1.2 close (retro §10).

Captured by the architect partner. Do not edit candidates after
capture without leaving a note — these are session-time observations,
and rewriting them post-hoc is the same reverse-drift the project's
review discipline exists to prevent.

---

## RC-7 — Stale-workspace-as-truth pattern observed twice in W-001 cycle

**Surfaced:** 2026-05-20, two instances within ~4 hours of each other during the W-001 design and review cycle.

**Observation:** Two distinct sessions made the same class of error — treating local in-memory or local-filesystem state as canonical truth without verifying against `origin`.

### Instance 1 — Architect paste-error

Architect pasted a stale plan-vs-impl message (the C2 freeze plan-vs-impl audit for `da65165`, originally produced earlier in this multi-day session) into the W-001 cycle thread, implicitly asking architect-partner to do R0-A on it. Architect-partner caught that the message was word-for-word identical to an earlier-in-session message — six-point checklist phrasing, "Stopping per architect instruction" closing sentence, the watch item about `llm/config_loader.py` importing `ToolMeta`. Architect acknowledged: *"oh forgot the branch. lol"*. Recovery: no action; architect-partner did not proceed and surfaced the duplicate.

### Instance 2 — Senior workspace divergence

Senior pushed ADR-008 draft as commit `b00c779` on `claude/w-001-plan`. The pushed file had 13 decisions; the commit body itself said "13 decisions covering..." When senior returned to apply the four architect-acked R0-A revisions, senior reported that the local files had **only 6 decisions** and that no Decisions 10/11/13 existed (which the R0-A items referenced). Senior surfaced the mismatch correctly per the senior-planner rule — did not guess at restructure — and asked architect-partner to clarify. Architect-partner verified via `git show b00c779:docs/decisions/ADR-008-workflow-state-machine.md` that the **pushed** file has 13 decisions, matching the commit body. Senior was looking at uncommitted local files (an older draft) shadowing the tracked, pushed version. Resolved by senior with `git stash` (set local drafts aside) + `git pull` (resync with origin).

### Pattern

Each session's working memory or local working tree can diverge from `origin` without local awareness. Two paths to the same failure mode:

- **Chat memory > git:** the architect remembered "I was reviewing da65165" from earlier in the session, pasted the wrong message because session context was stale relative to repo state (which had moved through C3, C4, P1.2 close, W-001 brief).
- **Local files > git:** senior had an older draft locally that was never pushed, treated it as authoritative when pushing newer work would have produced the correct view.

Both share a deep structural cause: **divergence between mental model of repo state and actual `origin` state, with no forcing function at session-start to catch the divergence.**

### Why this matters

ADR-008 (`docs/decisions/ADR-008-workflow-state-machine.md`, Proposed at time of capture) is **designed exactly for this class** — `.workflow/{task-id}.yaml` is meant to be ground truth, not session memory. The state machine reads state from disk + git on session launch (Decision 9 — session-start trigger), explicitly displacing chat memory.

But RC-7's specific failure mode (local files shadowing tracked files) is a workspace-hygiene issue not directly resolved by ADR-008's state machine. ADR-008 assumes that git IS the source of truth and that sessions read git. If a session edits files without committing AND then later reads those files without `git status` / `git pull`, the state machine cannot detect the divergence — the state machine reads the working tree.

### Proposed forcing function (decision deferred — P1.3 retro evaluates)

Add a **session-start git-verify** check, complementary to ADR-008's state file reads:

- On session launch, after reading `.workflow/{task-id}.yaml`, the harness runs `git fetch origin && git status --short`. If there are **untracked** or **modified** files in paths the state file expects to be at a specific revision, surface a warning to the session: *"Local workspace diverges from origin/`branch`. Files: [list]. Confirm intent before proceeding."*
- The check is implementable as a one-liner in the Claude Code SessionStart hook from ADR-008's impl plan §3 push-back #2.
- Optional escalation: refuse to advance state until divergence is resolved (commit or stash).

This is preventive — it does not fix the underlying habit, but it surfaces the divergence at the moment a session starts to act on stale memory, before any work compounds the error.

### Sub-question for ADR-008 / W-001-impl

Does W-001-impl's session-start hook (plan stub impl-4) already cover this, or is the divergence check a separate addition? Senior plan stub §3 push-back #2 (hook vs CLI) doesn't currently mention divergence checking — the hook's described job is "read state, surface what to do." Adding "verify workspace not stale" is a small extension.

### Status

**Open.** Two instances in one cycle is data that the failure mode is **real, not theoretical**. P1.2 retro RC-4 set a precedent: one instance is not enough to codify (test-coverage 6→3→6 deferred). RC-7 has two instances in the same cycle, which is a stronger case for codification at W-001 close than RC-4 had at P1.2 close. But codification waits for W-001-impl to land — at that point the forcing function can be implemented in the same harness as state machine launch.

W-001 close-out retrospective evaluates whether:

- (a) ADR-008's design + a session-start git-verify check covers the class.
- (b) The check graduates into a forcing function in the harness.
- (c) Or the pattern continues even with automation, and a deeper intervention is needed (e.g., docs requiring `git status` confirmation in every session's first response).

---

## Notes for final W-001 retrospective

When folding into `docs/retrospectives/W-001.md` at close:

- RC-7 is the first observation captured during W-001 itself (not inherited from P1.2). If W-001-impl surfaces additional candidates during its cycle, they accumulate here.
- The "absence-as-evidence" convention from P1.2-C4 R0-A (RC-2 evidence-trail framing) applies: if W-001-impl ships with the session-start git-verify check AND no third instance of RC-7 occurs through P1.3, the check is the empirical resolution. If the pattern recurs despite the check, the underlying habit needs a stronger intervention.
- W-001 close-out also evaluates whether the candidates-per-cycle convention (originally P1.2's invention) survives one cycle of use. If `W-001-candidates.md` proved load-bearing, the pattern is robust; if it was mostly empty, the pattern is overhead and P1.3+ can collapse to per-milestone files only.
