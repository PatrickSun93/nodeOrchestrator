# ADR-008: Workflow State Machine + Automation

**Status:** Proposed — 2026-05-20
**Scope:** Governs the new `.workflow/` orchestration harness that
sequences the architect → senior → junior → reviewer workflow encoded
in `docs/process/senior-planner.md` and `handoff.md` §16. Defines the
state vocabulary, gated-vs-auto-triggered transition rules, file
layout, trigger mechanism, override semantics, and bootstrapping for
existing closed work. Out of scope: any non-orchestration automation
(CI / lint / format hooks unrelated to workflow advancement); LLM-
driven decisions about state transitions (forbidden); the
implementation details, which land in W-001-impl after Accept + the
standard distance-test pause.

## Context

The four-role workflow in `handoff.md` §16 (architect / architect-
partner / senior / junior + reviewer) ran five P1.2 cycles (C1
through C4 + R0-A close-out) under implicit state tracking. State
lived in chat history and in the architect's head: "which session
owes which artifact?" When the state was simple — one task, one
cycle — implicit tracking was fine. By the close of P1.2 the cost
had begun to show, surfaced in `docs/retrospectives/P1.2.md` §2/§5/§6:
the architect was the load-bearing scheduler; tasks blocked on
their attention even when the next step was a verification, not a
decision; multi-task interleaving (P1.3 in progress concurrent with
a hypothetical W-002 hot fix) would not survive the same model.

The P1.2 retrospective also surfaced a deliberate trade-off the
project has made repeatedly: *distance test* — architecturally
consequential decisions sit for 24h+ before inscribing, so the
architect (and reviewing partners) can revisit with fresh eyes. The
distance test must survive any automation that touches the workflow,
or the automation defeats one of the project's most-cited safeguards.

An architect-partner session enumerated three automation shapes:

- **Option A** (status-visible, manual trigger): state file
  documents current state; sessions read on start, write on end;
  architect manually triggers every transition. Minimal automation;
  preserves all distance tests; least friction-reduction.
- **Option B** (auto-trigger for low-risk segments only): like A,
  plus auto-trigger on transitions that are verifications, not
  decisions — specifically (a) senior plan-vs-impl appearing →
  architect-partner R0-A fires; (b) clean R0-A (0 🔴 / 0 🟡) +
  merge-clean → auto-open PR. **Any 🟡 / 🔴 or architect-decision
  point blocks for manual ack.**
- **Option C** (full automation with mandatory 24h delays): state
  machine progresses automatically, each state has 24h minimum
  dwell time. Highest friction-reduction; most surface area for
  drift.

Architect chose Option B with full awareness of the four concerns
architect-partner pushed back on (distance-test conflict at
verification transitions; bypassed intervention points; self-loop
risk on same-family review chain; ADR-008 itself needing distance
test). The route to ADR-008-via-senior (this task) was the
architect's chosen mitigation of the "architect-partner self-loops
on workflow design" concern — senior reads context fresh, drafts
ADR independently, architect-partner reviews. The bootstrap
exception that produced ADR-005 is **not** extended here.

Principles bearing on the design:

- **Principle 3.1 — decision paths in code, LLMs generate content.**
  State transitions are deterministic functions of (current state,
  git artifacts, gate status). No LLM in transition logic. Sessions
  consume LLM for their natural work; the orchestration layer is
  pure code.
- **Principle 4 — structured uncertainty.** The state vocabulary
  is a closed enum; free-form "states" or implicit transitions
  defeat the audit trail the state file is meant to be.
- **Principle 11 — no ground truth → drift.** The state file IS
  the ground truth for what comes next. Chat history is not
  ground truth; the architect's memory is not ground truth.
- **Principle 10 — environment shapes agent.** Sessions check
  state on launch and act per state, not per chat memory. The
  harness IS the environment.

Hard requirements the decision must support:

1. Architect retains intervention authority at the four gated
   transitions enumerated below; the state machine blocks
   unconditionally until architect acks.
2. Verification transitions auto-fire to reduce architect cognitive
   overhead on no-decision steps.
3. Any 🔴 or 🟡 finding in a review file blocks the chain
   unconditionally — no auto-trigger can override.
4. Override capability at every state — architect can force-advance,
   force-revert, or halt; all overrides are auditable.
5. State machine implementation is pure synchronous code; transitions
   are atomic file writes; no async / eventual consistency.

## Decisions

### 1. Option B shape — four gated + two auto-triggered transitions

**Gated** (architect intervention REQUIRED; state machine blocks):

| From state | To state | Trigger |
|---|---|---|
| `awaiting_brief` | `awaiting_senior_plan` | architect publishes brief at locked path |
| `awaiting_architect_accept` | `awaiting_junior_impl` | architect bumps ADR status `Proposed → Accepted` (or equivalent ack) |
| `awaiting_architect_decision` | `awaiting_junior_impl` (rework) or `awaiting_PR_merge` (proceed) | architect rules on 🟡 routing |
| `awaiting_PR_merge` | `closed` | architect merges PR |

**Auto-triggered** (state machine advances when prior session pushes
the required artifact AND all gates are clean):

| From state | To state | Auto-trigger condition |
|---|---|---|
| `awaiting_senior_plan_vs_impl` | `awaiting_R0_A` | review file at `docs/process/reviews/{task-id}/plan-vs-impl.md` appears AND its frontmatter `verdict` field is non-blocking |
| `awaiting_R0_A` | `awaiting_PR_merge` | `R0-A.md` frontmatter `verdict: clean` AND all gates green AND merge-tree clean against `origin/main` |

Any 🔴 or 🟡 in a review file's frontmatter (`verdict: blocking` or
`verdict: needs_architect`) routes to `awaiting_architect_decision`
instead of advancing.

### 2. State machine implementation in code (Principle 3.1)

Transitions are pure functions of `(current_state, git_artifacts,
gate_results)`. No LLM call in `transition()`, `should_auto_advance()`,
or `verdict()`. The implementation lives in a future
`src/orchestrator/workflow/` module or a sibling tooling module
(W-001-impl decides exact placement).

This is non-negotiable per Principle 3.1. If a future ADR proposes
LLM-assisted state advancement ("LLM determines if R0-A is clean
enough"), it must explicitly supersede this decision.

### 3. Per-task state files

Each task gets `.workflow/{task-id}.yaml`. Multiple tasks can be in
different states concurrently (P1.3 in `awaiting_R0_A`; W-002 in
`awaiting_senior_plan`). A global state file would force
serialization or invent locking, neither of which is needed when
tasks are independent in the dependency graph.

Cross-task dependencies (e.g., W-002 must wait for P1.3 close) are
**not** modelled by this state machine — they remain in the
architect's mind or in narrative docs. Future work may add a
`depends_on:` field; out of scope for ADR-008.

### 4. State file location: `.workflow/` at repo root

Matches `.github/`, `.claude/` precedent — project-level harness
config lives at the root in a dotted directory. `.workflow/` is
git-tracked (not in `.gitignore`); state changes are part of the
project's audit history.

### 5. State file shape: YAML

```yaml
task_id: P1.3-C1
state: awaiting_senior_plan_vs_impl
cycle: 1                # rework count: 1 = original, 2 = R1, etc.
last_transition_at: 2026-05-21T14:30:00Z
last_transition_by: junior  # role, not session id
expected_artifact: docs/process/reviews/P1.3-C1/plan-vs-impl.md
override_history: []    # see Decision 10
```

The shape is a flat dict. No nesting beyond `override_history` (a
list of structs). Future extensions are additive at the top level.

### 6. State vocabulary (8 states + closed)

Closed set, lower_snake_case:

1. `awaiting_brief` — no brief at locked path yet; rare in practice (briefs are usually the trigger to create the state file).
2. `awaiting_senior_plan` — brief exists; senior has not yet pushed a plan.
3. `awaiting_architect_accept` — senior plan + ADR draft pushed; awaiting architect status bump.
4. `awaiting_junior_impl` — ADR Accepted; junior has not pushed an impl commit.
5. `awaiting_senior_plan_vs_impl` — junior pushed; senior has not yet written plan-vs-impl review.
6. `awaiting_R0_A` — plan-vs-impl posted with non-blocking verdict; architect-partner has not yet pushed `R0-A.md`. (Auto-fires on transition.)
7. `awaiting_architect_decision` — a review (plan-vs-impl OR R0-A) carries a 🟡 or 🔴; architect must rule on routing.
8. `awaiting_PR_merge` — all gates clean; PR open; awaiting architect merge.
9. `closed` — terminal; task is in main.

R0-B is **not** a state — it's optionally dispatched in parallel
with R0-A from `awaiting_R0_A`; its absence is the documented
signal of single-reviewer R0 (per `docs/process/reviews/README.md`).
The state machine does not gate on `R0-B.md` existence; it gates on
the architect's decision once both available reviews are read.

### 7. Auto-trigger detection: YAML frontmatter, not emoji grep

Each review file (`plan-vs-impl.md`, `R0-A.md`, etc.) carries a YAML
frontmatter block:

```yaml
---
verdict: clean | blocking | needs_architect
findings_count:
  red: 0
  yellow: 0
  green: 4
---
```

Auto-advance reads `verdict`. Emoji-counting in markdown bodies is
fragile (a `🔴` in a code example or quote would mis-fire). The
review author writes the frontmatter as part of finalizing their
review; a missing frontmatter raises a state-machine error, never
silently defaults.

Mapping:

- `clean` → auto-advance.
- `blocking` (any 🔴) → halt; transition to `awaiting_architect_decision`.
- `needs_architect` (any 🟡 OR architect-explicit-requested) → halt; transition to `awaiting_architect_decision`.

### 8. Auto-PR open requires merge-clean check (senior self-discovery)

The `awaiting_R0_A` → `awaiting_PR_merge` auto-transition has two
preconditions, BOTH must be true:

- (a) `R0-A.md` frontmatter `verdict: clean`.
- (b) `git merge-tree origin/main HEAD` produces zero conflict
  markers.

If (b) fails, the state advances to `awaiting_architect_decision`
with a state-file field `merge_conflict_detected: true`. The
auto-trigger never opens a PR with conflicts.

### 9. Trigger mechanism: session-start check

Each Claude Code session (architect-partner, senior, junior,
reviewer) reads `.workflow/` on launch and identifies which task
states match its role. The session acts accordingly:

- Senior session sees `awaiting_senior_plan` → writes a plan.
- Architect-partner session sees `awaiting_R0_A` → writes R0-A.
- A session sees no states matching its role → reports
  "nothing for me to do" and exits.

No GitHub Actions integration; no cron; no daemon. The trigger is
"next session launched". This preserves human-in-the-loop on
session spawning while removing chat-based coordination from the
critical path.

### 10. Override capability + auditable history

Every state file carries `override_history: []`. An override is a
struct:

```yaml
override_history:
  - timestamp: 2026-05-21T16:00:00Z
    actor: architect
    from_state: awaiting_R0_A
    to_state: awaiting_PR_merge
    reason: "R0-A author unavailable; architect personally reviewed and cleared"
```

Override types:

- **Force-advance**: skip a state without the natural trigger.
- **Force-revert**: rewind to a prior state (e.g., after discovering
  the merged plan was wrong).
- **Halt**: terminal stop without `closed`; explicit "this task is
  abandoned" signal.

All overrides are written by architect (or architect-partner with
architect's authorization recorded in `reason`). The git commit
landing the override carries the state-file diff so the audit
trail is immutable beyond the file.

### 11. Rework loop semantics

R1 / R2 cycles transition `awaiting_architect_decision` →
`awaiting_junior_impl` with `cycle: cycle + 1`. The cycle counter
is visible in the state file and in subsequent review filenames
(`R1-A.md`, `R1-B.md`, etc., per existing locked-paths convention).

There is no maximum cycle count enforced by the state machine.
Architect's judgement: if a task is on cycle 4+, the task scope is
likely wrong — architect overrides to halt and re-briefs.

### 12. Bootstrapping: existing closed work and W-001 forward

Existing P1.2 tasks (C1 through C4) and earlier do **not** get
`.workflow/` files. They are by-definition `closed` (retrospective
written; work merged to main). Creating retroactive state files
would manufacture audit data that wasn't real.

`.workflow/` adoption begins with W-001-impl (the next task after
this ADR Accepts). The very first `.workflow/{task-id}.yaml`
written will be `.workflow/W-001-impl.yaml`, created when the impl
task starts.

ADR-008 itself runs **outside** the state machine — its state is
managed implicitly by this brief's distance-test pause. No
`.workflow/W-001.yaml` file exists for this task. The brief and
this ADR establish the system; the first user is the impl that
builds it.

### 13. Same-family R0 chain — orthogonal to this ADR

The "architect-partner R0-A is same Claude family as senior" risk
surfaced in retro §6 is **not** addressed by ADR-008. The state
machine auto-fires R0-A regardless of the reviewer family; whether
R0-B is dispatched (cross-family) is architect's decision per the
existing `docs/process/reviews/README.md` convention. ADR-008's
guarantee is *that* R0-A runs, not *who* runs it.

If a future ADR mandates cross-family R0, the state machine adds a
gate on R0-B existence — that change would be additive (new state
or new precondition on existing state), not a redesign.

## Considered alternatives

### A. Option A (manual trigger every transition)

No auto-trigger; architect manually advances every state. Considered
seriously because it preserves *every* distance test. Rejected
because verification transitions (plan-vs-impl → R0-A; clean R0-A →
PR open) are not architectural decisions — they are mechanical
checks. Forcing architect to ack a mechanical check both wastes
attention and creates a false signal ("architect approved this"
when architect merely clicked the button).

### B. Option C (full auto with 24h dwell)

Every transition auto-fires after 24h. Rejected: defeats the
distance-test intent by making delay performative, not deliberative.
Architect can't say "I want to think about this for 48h" without
overriding the timer; manual gates make the deliberative pause
*intentional*, not *imposed*.

### C. State machine driven by LLM

A small LLM call (`is R0-A clean?` → yes/no) instead of structured
frontmatter parsing. Rejected on Principle 3.1: this is a decision
path, not content generation. The cost of getting it wrong (auto-PR
on a non-clean review) is silent and propagates. Structured
frontmatter is deterministic and the review author authoritatively
declares the verdict.

### D. Architect-partner self-drafts ADR-008

Architect-partner proposed during the design session that the
ADR-008-bootstrap exception parallels ADR-005's. Architect
rejected: extending the bootstrap exception once devalues the
senior-drafts rule that RC-3 was supposed to codify. ADR-008's
existence as a senior-drafted ADR is part of its own message —
the senior-drafts rule applies even to workflow-itself ADRs.

### E. Single global state file (`.workflow/state.yaml`)

One YAML with all task states under a top-level dict. Rejected for
multi-task interleaving: two concurrent tasks would either need
file locking or accept merge conflicts on every transition. Per-
task files trivially parallel.

### F. State file in `docs/process/.workflow/` (under docs tree)

Conceptually attractive (state files ARE process artifacts).
Rejected because `.workflow/` is closer to `.claude/` and `.github/`
in nature (tooling-level config) than to `docs/process/architect-
briefs/` (human-authored content). The dotted-directory convention
at the repo root signals "machine reads this" to humans.

### G. Hidden directory `.workflow/` vs visible `workflow/`

Hidden (`.workflow/`) chosen to match `.github/` / `.claude/`. A
visible `workflow/` would show up in `ls`, which is fine but
inconsistent with the harness-config pattern. Both `git ls-tree`
and `find` find dot-directories anyway, so the "hidden" framing is
shell-cosmetic only.

### H. GitHub Actions auto-trigger

CI workflow fires on every push, reads the state file, advances the
state. Rejected for two reasons: (i) introduces CI dependency on
project state that humans should be able to drive locally without a
GitHub round-trip; (ii) GitHub Actions runs as a bot, which loses
the "session attribution" the audit trail wants.

### I. Implicit error recovery (crash semantics)

If a session crashes mid-state, the state file lags behind reality
(say, junior pushed a commit but didn't update state). Chosen
semantic: each transition is committed atomically (state-file write
+ artifact appearance are in one commit); a crashed session leaves
state at the prior committed snapshot; the next session sees the
artifact AND the prior state and treats this as a "next transition
not yet fired" — fires it on launch.

A more defensive alternative (lock files, in-progress flags) was
rejected as over-engineering for a project where sessions are
human-initiated and observable.

## Consequences

**Easier:**

- Multi-task interleaving without losing track of "what's next for
  P1.3 vs what's next for W-002."
- Sessions self-organize on launch — architect doesn't have to
  explicitly dispatch every step.
- Audit trail: state file history shows precise advancement; chat
  history is no longer load-bearing.
- Distance test preserved at the four architectural-inscribing
  transitions; mechanical verifications free up architect cognitive
  budget.
- Override mechanism: when architecture decisions arrive out of
  band, force-advance + reason text records the deviation
  permanently.

**Harder:**

- New mental model — every contributor learns the state vocabulary
  (8 + closed). Mitigated by short vocabulary and clear naming.
- Initial setup cost: W-001-impl must scaffold `.workflow/`, write
  the transition library, integrate session-start checks. ~3-5
  commits of plumbing before any task uses it.
- ADR-008 is self-referential — the very ADR that establishes the
  state machine runs outside it. Future readers may wonder why
  there's no `.workflow/W-001.yaml`; Decision 12 documents this.
- Frontmatter requirement on review files: existing P1.2 review
  files (`plan-vs-impl.md`, `R0-A.md` for C3 and C4) lack
  frontmatter. They are honored as "closed" without retroactive
  edits per Decision 12.

**Neutral:**

- `.workflow/` adds a top-level dir alongside `.claude/`, `.github/`.
- State files are tiny (≤30 lines); git tracks them like any small
  doc.
- The state machine is itself a small library (~100-200 lines of
  pure code anticipated). Test surface is the transition matrix —
  finite, exhaustive.

## Reversibility

| Decision | 6-month reversal cost |
|---|---|
| 1. Option B shape (gated + auto-triggered) | Medium — collapsing to Option A (manual everywhere) is a configuration change in the harness; collapsing to Option C (full auto) requires re-litigating Principle 11 grounding and the distance-test design. |
| 2. Code-only transitions (Principle 3.1) | Expensive — relaxing to LLM-assisted requires a new ADR superseding this, plus retroactive justification for any auto-trigger that fired incorrectly during the LLM-in period. |
| 3. Per-task state files | Low — collapsing to a single global file is a migration script + locking layer; reversible but mildly disruptive to in-flight tasks. |
| 4. `.workflow/` at repo root | Trivial — relocation is `git mv` + path constant change in harness library. |
| 5. YAML state file shape | Low — additive (new top-level keys) is free; removing keys requires migration of existing state files. |
| 6. State vocabulary | Medium — adding states is additive (existing transitions unchanged); renaming or merging states requires re-mapping all `.workflow/{task-id}.yaml` historical files (state-file history is git-tracked; the rename is a tree-wide edit). |
| 7. Frontmatter-based verdict detection | Low — switching to emoji grep is a one-line change in the transition library. |
| 8. Merge-clean precondition on auto-PR | Trivial — removing the precondition is a one-line change. Adding more preconditions (e.g., "all tests pass on CI") is also additive. |
| 9. Session-start trigger | Medium — switching to GitHub Actions or daemon-based requires re-architecting where state-read happens; reversal requires re-introducing CI/daemon infrastructure. |
| 10. Override + audit trail | Low — removing audit trail is trivial but unwise (loses the deliberate-deviation record). Adding audit categories is additive. |
| 11. Rework cycle semantics | Trivial — cycle counter is a state-file field; behavior change is in the transition library. |
| 12. Bootstrapping (P1.2 = closed; W-001-impl is first) | Trivial — retroactive bootstrapping of closed tasks is a one-shot script; reversal means deleting those state files. |
| 13. R0 family orthogonality | Trivial — adding a cross-family gate is a new precondition on `awaiting_R0_A → awaiting_PR_merge`, additive. |

## References

- `docs/decisions/ADR-001-event-store-foundation.md` — model for
  pure-code decision paths + structured state.
- `docs/decisions/ADR-005-autonomy-scoring-tiered-reversibility.md`
  — workflow-bootstrap exception; this ADR does NOT extend it.
- `docs/decisions/ADR-006-unknown-tool-id-semantics.md` and
  `ADR-007-autonomy-refusal-event-type.md` — precedents for the
  senior-drafts pattern.
- `docs/process/senior-planner.md` § "ADR drafting" — the rule
  this ADR reinforces by not invoking the bootstrap exception.
- `handoff.md` §16 — four-role workflow this ADR automates.
- `docs/retrospectives/P1.2.md` §2/§5/§6/§9 — operational pain
  points that motivated this ADR.
- `docs/process/architect-briefs/W-001.md` — architect-settled
  design decisions feeding into this ADR.
- `docs/process/senior-plans/W-001-impl.md` — implementation plan
  stub (sibling artifact to this ADR; full atomic task list lands
  post-Accept).
- Implementation entry point: W-001-impl-1 (scaffolding) — the
  first session that consumes `.workflow/` as ground truth.
