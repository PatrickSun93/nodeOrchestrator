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
