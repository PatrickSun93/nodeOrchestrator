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

## RC-8 — Distance-test letter vs spirit (substrate over timestamp)

**Surfaced:** 2026-05-21, on architect's ADR-008 status-flip decision.

**Observation:** Two consecutive instances where architect explicitly chose the **substrate** (sleep cycle / cognitive freshness) over the **letter** (strict timestamp threshold) of the project's distance-test rule:

- **Instance 1 (P1.2-C4):** Junior impl commits for ADR-007 landed 2026-05-20 same-day as ADR-007 Accept. W-001 brief Decision 8 had explicitly said "impl commits land no earlier than 2026-05-21" — interpreted as next-calendar-day. Architect-partner flagged the deviation in `docs/process/reviews/P1.2-C4/R0-A.md`'s "Distance test" section as a meta-observation but did not block; P1.2 close-out retrospective §6 captured it as a class-of-concern not yet codified.
- **Instance 2 (W-001 ADR-008 Accept):** ADR-008 status flip `Proposed → Accepted` requested ~13h after senior's last revision push (`788cd90` at 2026-05-21 04:50 UTC; request at 17:36 UTC). W-001 brief Decision 8 had explicitly said "24h+ minimum from senior's last revision push." Architect-partner surfaced the math; architect explicitly picked Option (b) sleep-cycle-spirit, citing that sleep separation between architectural inscription and action had been preserved despite strict-24h not being met.

**The substrate question:** The distance-test rule has two interpretable substrates that don't always agree:

- **(X) Strict elapsed time** (24h+ from a reference timestamp). Cheap to verify; auditable by clock; doesn't account for the actual cognitive context (a sleep-deprived architect at hour 25 is no better positioned than at hour 12).
- **(Y) Sleep cycle and fresh-eye revisit.** Honors the principle the rule was created to capture (fresh perspective on a load-bearing decision); requires self-report or proxy detection (no commits in architect's nighttime window).

When (X) and (Y) diverge — as in both instances above — which is the canonical rule?

**Why this matters:** The brief committed to (X) wording but architect interpreted as (Y) at the moment of the act. Either:

- (a) (Y) is the canonical rule and (X) was shorthand that doesn't map cleanly. Write the rule as (Y) and stop binding future architects (including future architect-self) to the (X) proxy.
- (b) (X) is the canonical rule, and the two instances were rule violations. Acknowledge the violations explicitly or revise the rule in a documented amendment.
- (c) The rule has both substrates and the project accepts case-by-case resolution. Then document the trade-off and the decision criteria, not the strict (X) wording alone.

**Parallel to other letter-vs-spirit pairs in the project:**

- **RC-1 (5-surface scan):** "surface edited" letter vs "pre-edit values gone" spirit — resolved by adding the substrate (pre-edit grep) as an explicit forcing function. Codification recommended at P1.2 close, paying off.
- **Constitutional test criterion:** "test exists" letter vs "invariant holds" spirit — resolved by criterion "checks a property the type system cannot check" (P1.1 retro §3 closing observation).

Both resolved by writing the substrate explicitly. Distance test might follow the same pattern: codify (Y) as the canonical rule, deprecate (X) as a useful-but-imperfect proxy.

**Proposed forcing function (decision deferred — W-001 close evaluates):**

Option α: **Replace "24h+ minimum" with "at least one sleep cycle + fresh-eye revisit."** Auditable by absence of commits in architect's nighttime window AND by an explicit "fresh-eye revisit" attestation in the commit body of the action commit (e.g., status-flip commit, merge commit, accept commit).

Option β: **Keep strict 24h+ as default, add an explicit sleep-cycle override mechanism.** The override is documented in the action commit body with phrase like *"sleep-cycle override: slept and re-thought between push and action."* Future readers see the deliberate substrate choice.

Option γ: **Make the substrate observable in artifacts.** Forbid same-calendar-day-in-architect-timezone status flip on Accepted-state ADRs, with explicit override-with-reason allowed. Calendar-day proxy is auditable; reason text records the deliberate deviation.

Architect-partner lean: **α or β**. α is cleaner if the project trusts self-report (consistent with project's "honest interlocutor" framing). β preserves (X) as default for future readers who don't know the substrate history. γ adds a third proxy that may itself need its own substrate override.

**Why two instances within ~12 hours is faster-than-deferrable:**

RC-4 (test-coverage 6→3→6) was deferred at P1.2 close because **one** instance is not enough to codify. RC-8 has **two** instances in **one** cycle, with the second happening within ~12 hours of architect committing the very brief wording that the second instance overrode. This is fast enough that the rule needs evaluation **at W-001 close, not deferred indefinitely.**

**Sub-question for ADR-008 harness:** Does W-001-impl's session-start logic help here? Partial — if the harness gates status transitions on a "fresh-eye attestation" check, the substrate is enforced at the moment of the act. But forcing architect to type "I slept" may degrade compliance over time (theatre tax). Better: detect the substrate via observable artifacts (commit-history-shows-architect-nighttime-gap) rather than self-report.

**Status:** open. Two instances within ~12 hours of each other constitutes data, not a coincidence. W-001 close-out evaluates: (1) which of α/β/γ to codify; (2) whether ADR-008 harness should enforce it; (3) whether the brief's wording template ("24h+ minimum") needs revision to reflect (Y) substrate.

---

## Notes for final W-001 retrospective

When folding into `docs/retrospectives/W-001.md` at close:

- RC-7 is the first observation captured during W-001 itself (not inherited from P1.2). If W-001-impl surfaces additional candidates during its cycle, they accumulate here.
- The "absence-as-evidence" convention from P1.2-C4 R0-A (RC-2 evidence-trail framing) applies: if W-001-impl ships with the session-start git-verify check AND no third instance of RC-7 occurs through P1.3, the check is the empirical resolution. If the pattern recurs despite the check, the underlying habit needs a stronger intervention.
- W-001 close-out also evaluates whether the candidates-per-cycle convention (originally P1.2's invention) survives one cycle of use. If `W-001-candidates.md` proved load-bearing, the pattern is robust; if it was mostly empty, the pattern is overhead and P1.3+ can collapse to per-milestone files only.
- RC-8 has the strongest graduate-now case of any candidate so far — two instances within ~12 hours, second of which overrode wording from the same cycle's own brief. W-001 close should not defer RC-8 to "watch for third instance"; the data is already in. Pick α/β/γ and codify.
