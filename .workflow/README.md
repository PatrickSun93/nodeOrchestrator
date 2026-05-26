# .workflow/

This directory contains per-task state files for the orchestrator workflow
harness. Each file tracks where one task is in the architect → senior →
junior → reviewer pipeline.

**See [ADR-008](../docs/decisions/ADR-008-workflow-state-machine.md) for
the full design rationale, transition rules, and override semantics.**

---

## File format

Each `{task-id}.yaml` file conforms to the `TaskState` Pydantic model
(`src/orchestrator/workflow/schema.py`):

```yaml
task_id: W-001-impl
state: awaiting_junior_impl
cycle: 1
last_transition_at: 2026-05-26T12:00:00Z
override_history: []
requires_cross_family_review: false
```

---

## The 9 states (ADR-008 Decision 6)

| State | Meaning |
|---|---|
| `awaiting_brief` | No brief at the locked path yet |
| `awaiting_senior_plan` | Brief exists; senior has not yet pushed a plan |
| `awaiting_architect_accept` | Senior plan + ADR draft pushed; awaiting architect status bump |
| `awaiting_junior_impl` | ADR Accepted; junior has not pushed an impl commit |
| `awaiting_senior_plan_vs_impl` | Junior pushed; senior has not yet written plan-vs-impl review |
| `awaiting_R0_A` | Plan-vs-impl posted with non-blocking verdict; R0-A not yet pushed |
| `awaiting_architect_decision` | A review carries 🟡 or 🔴; architect must rule on routing |
| `awaiting_PR_merge` | All gates clean; PR open; awaiting architect merge |
| `closed` | Terminal; task is in main |

---

## Git-tracked, not gitignored

State files are part of the project's audit history. Every state transition
is a git commit. The history of a state file shows exactly how a task
progressed (and where it was overridden).

---

## What to do if a state file is out of sync with reality

If you find a `.workflow/{task-id}.yaml` whose `state` does not match the
actual artifact and gate status (e.g., the file says `awaiting_junior_impl`
but junior already pushed weeks ago), use the override mechanism:

1. Run `workflow override --task-id TASK --to-state CORRECT_STATE --reason "explanation" --actor architect`.
2. Commit the resulting state-file change.
3. The `override_history` field records the deviation permanently (ADR-008
   Decision 10). Do NOT edit the file by hand without the CLI — the
   override entry is the audit record.

If the mismatch is a harness bug (state machine missed a transition),
file it and use the override to unblock the task. The override reason
should cite the bug.
