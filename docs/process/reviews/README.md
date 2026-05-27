# Reviews

Per-task review artifacts, one subfolder per task ID
(e.g. `P1.2-C3/`). Inside each subfolder:

- `plan-vs-impl.md` — senior's self-verification that the impl
  matches the plan. Written by senior, read by architect before
  external reviewer dispatch.
- `R0-A.md`, `R0-B.md` — first-round external reviewers. `-A` is
  Claude family, `-B` is cross-family (DeepSeek / Gemini / other).
  Both follow the tracking-table format (🔴/🟡/🟢 + file:line +
  what's wrong + what should be).
- `R1-A.md`, `R1-B.md`, etc. — subsequent rounds if needed.
- `meta.md` — close-out meta-review across all rounds.

Empty `-B.md` slots stay empty: an absent `R0-B.md` is the evidence
that cross-family R0 was not dispatched that round. The empirical
question "was a single-reviewer R0 sufficient?" is answerable from
the absence + subsequent round outcomes.

---

## Frontmatter contract (post-ADR-008)

All review files created after ADR-008 Accepted (2026-05-21) **must** begin
with a YAML frontmatter block. See [ADR-008 Decision 7](../../decisions/ADR-008-workflow-state-machine.md#7-auto-trigger-detection-yaml-frontmatter-not-emoji-grep).

Required keys:

```yaml
---
task_id: <task-id>          # e.g. W-001-impl
round: R0-A                 # e.g. plan-vs-impl, R0-A, R0-B, R1-A, …
verdict: clean              # clean | blocking | needs_architect
findings_count:
  red: 0
  yellow: 0
  green: 4
---
```

`verdict` values and their auto-trigger semantics:

| Value | Meaning | Auto-trigger effect |
|---|---|---|
| `clean` | No 🔴 or 🟡 findings | State machine may auto-advance (see ADR-008 Decision 1) |
| `blocking` | One or more 🔴 findings | Routes to `awaiting_architect_decision`; no auto-advance |
| `needs_architect` | One or more 🟡 findings (or reviewer explicitly requests architect input) | Routes to `awaiting_architect_decision`; no auto-advance |

A **missing or malformed** frontmatter block raises a `WorkflowError` from
`parse_verdict()` — it never silently defaults. Review authors are responsible
for writing correct frontmatter before pushing.

Use `docs/process/reviews/_template-review.md` as a starting point.

---

## Pre-ADR-008 review files

The following task review directories predate the frontmatter convention and
remain in their existing format. The state machine **never reads closed-task
review files**; no retroactive frontmatter edit is needed or desired
(ADR-008 Decision 12 reasoning: manufacturing retroactive audit data would
misrepresent what was true at the time the reviews were written):

- `P1.2-C3/` — closed; reviewed before ADR-008.
- `P1.2-C4/` — closed; reviewed before ADR-008.

Any `R0-A.md` or `plan-vs-impl.md` in these directories is read by humans
only, not by the workflow harness.

---

## Post-resolution verdict-bump protocol (RC-10 codification, post-P1.5)

When a review's findings are resolved post-review-write (via senior revision,
junior fix-on-same-branch, or architect routing), the **verdict is updated
in place via frontmatter edit**, not via a new review file. The pattern
emerged in W-001-impl R0-A (commit `96c1469`); accumulated 6 distinct uses
across 3 distinct shapes by P1.5 close; codified here.

### When to bump

Bump the verdict on the existing review file when:

- **Post-fix bump**: junior fixed a 🔴 / 🟡 finding via commit on the same
  branch; no new review round needed.
  - Example: P1.5 plan-vs-impl `blocking → clean` after R1 fix at `307a8fa`.
- **Post-routing-revision bump**: architect routed an architect-partner /
  cross-family review's findings via `architect-routing.md` artifact;
  senior absorbed routing in revision; original review's verdict bumps to
  `clean`.
  - Example: P1.5 R0-A-on-plan `needs_architect → clean` after senior
    revision at `fe3dd82` absorbing Y1 → β routing.
- **Post-R1-fix bump**: a reviewed-once-as-blocking artifact gets a same-
  branch fix; verdict bumps without a new review round.
  - Example: same as P1.5 plan-vs-impl above (R1 fix path).

### How to bump

1. **Edit the frontmatter** in place. Update:
   - `verdict:` to the new value (typically `clean`).
   - `findings_count:` to the post-resolution count. Resolved 🔴 / 🟡
     typically reclassify as 🟢 to document the absorption; the tally
     must match the body's finding markers exactly.
   - Add a `verdict_history:` array entry recording the prior verdict +
     the commit SHA at which it was current + a short note.
2. **Add a blockquoted preamble** below the H1 title naming the bump:
   - The protocol applied (`RC-10 — frontmatter as live signal`).
   - Which findings were absorbed + how (one bullet per finding;
     trace to the routing artifact / fix commit).
3. **Preserve the original finding bodies** below the preamble. Findings
   exist as audit trail. Do NOT delete or rewrite them; the bump is
   additive history, not a rewrite.
4. **Commit + push**. Bump-only commits are valid atomic commits;
   `<task-id> R0-A verdict bump: <prior> → <new>` is a common subject.

### `verdict_history:` shape

```yaml
verdict_history:
  - verdict: needs_architect
    at_commit: <sha>
    findings_count: { red: 0, yellow: 2, green: 5 }
    note: <short reason for the original verdict>
  - verdict: clean
    at_commit: <sha>
    findings_count: { red: 0, yellow: 0, green: 7 }
    note: <how findings were absorbed; cross-reference routing / fix commit>
```

The `verdict_history` is **append-only** — each bump grows the array.
Git history is the deeper audit; `verdict_history` is the file-level
self-record.

### When NOT to bump

Do not bump in-place when:

- **The review is structurally outdated** (the underlying artifact was
  substantially redrafted from scratch). Write a new review round
  instead (`R0-A.md` exists; new round is `R1-A.md`).
- **The bump would reclassify a 🔴 finding as something other than 🟢
  after-absorption**. The protocol assumes the resolution mechanism
  closed the finding cleanly; if the resolution introduced a different
  finding, that's a new review surface.
- **Architect disagreement with the original review** is being recorded.
  Use the `architect-routing.md` artifact for that (per architect-routing
  pattern from P1.4 + P1.5); the original review's verdict bumps only
  after senior absorbs the routing into revisions.

### Empirical trail (instances this section codifies)

| # | Review file | Bump commit | Shape |
|---|---|---|---|
| 1 | `W-001-impl/R0-A.md` | `96c1469` | post-fix |
| 2 | `W-002/R0-A-on-plan.md` | `440ab3b` | post-revision |
| 3 | `P1.4/R0-A-on-plan.md` + `P1.4/R0-B-cross-family.md` | `047daa4` | dual-review |
| 4 | `P1.4/R0-B-cross-family.md` (second routing absorption) | `e8a1ee8` | dual-routing-on-same-file |
| 5 | `P1.5/R0-A-on-plan.md` | `dd1d267` | post-routing-revision |
| 6 | `P1.5/plan-vs-impl.md` | `a7ddf4f` | post-R1-fix |

The protocol replaces "write a new review file" when the same review's
findings have been resolved on the same artifact. New review files
(`R1-A.md`, `R1-B.md`) exist for genuinely new rounds, not for verdict
updates on an existing round.
