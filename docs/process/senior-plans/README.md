# Senior plans

Senior's task plan outputs. One file per task, named `{task-id}.md`
matching the corresponding architect brief filename
(e.g. `P1.2-C3.md`). Written by senior after reading the brief; read
by junior to implement and by architect to review. Follows the
six-field task structure (What / Where / Why / Acceptance / Out of
scope / Number) per `../senior-planner.md` §2.

Pre-brief-convention plans (`P1.2-R0.md`, `P1.2-R0-FU2.md`) live here
too. They were authored before `architect-briefs/` existed; they have
no corresponding brief file — that is the documented gap, not a bug.

---

## Frontmatter contract (post-W-002)

Plans may optionally carry a YAML frontmatter block at the top of the
file (the same `---`-fenced convention as review files per
[ADR-008 Decision 7](../../decisions/ADR-008-workflow-state-machine.md)):

```markdown
---
task_id: W-002
adr: ADR-009
---

# Plan body ...
```

### Required keys

None. Frontmatter itself is optional. Plans without frontmatter (all
plans authored before W-002: W-001-impl, P1.3, P1.4, etc.) are
honored as-is; the workflow harness falls back to a direct
`docs/decisions/ADR-{task-id}.md` lookup for those.

### Optional keys

| Key | Shape | Semantics |
|-----|-------|-----------|
| `adr` | `ADR-NNN` string | The ADR drafted alongside this plan. The harness resolves `docs/decisions/ADR-NNN-*.md` via glob. One match → read its Status. Zero matches → treat as "not yet drafted" (blocks at `awaiting_architect_accept`). Multiple matches → harness error (authoring bug: two files share the same NNN prefix). |

**`adr` as a list** (e.g. `adr: [ADR-099, ADR-100]`) is not yet
supported and raises a WorkflowError. Multi-ADR-per-task design is
deferred to W-003.

### W-002-2b semantics: frontmatter present but no `adr` key

If a plan **has frontmatter** (opens with `---`) but declares **no
`adr` key**, the harness skips the `awaiting_architect_accept` gate
and advances directly `awaiting_senior_plan → awaiting_junior_impl`.
This is the "no-ADR task" path (W-002-2b fix). Example: W-002 itself
carries frontmatter without an `adr` key.

If a plan has **no frontmatter at all**, the harness uses the legacy
path (`awaiting_senior_plan → awaiting_architect_accept`), which is
correct for plans predating this convention.

### Pre-W-002 backwards compatibility

Plans without frontmatter (W-001-impl, P1.3, P1.4, and earlier) are
not required to be retrofitted. The harness fallback handles them
transparently. See [W-002 plan](W-002.md) §1 for the RC-11 context
that motivated this convention.
