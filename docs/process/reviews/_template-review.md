---
task_id: <task-id>          # e.g. W-001-impl
round: R0-A                 # plan-vs-impl | R0-A | R0-B | R1-A | …
verdict: clean              # clean | blocking | needs_architect
findings_count:
  red: 0
  yellow: 0
  green: 0
---

# Review: <task-id> — <round>

**Reviewer:** <name / model>
**Date:** <YYYY-MM-DD>
**Artifacts reviewed:** <!-- list files, commits, or plan sections examined -->

---

## Findings

| # | Severity | File:line | What's wrong | What should be |
|---|----------|-----------|--------------|----------------|
| 1 | 🟢 | | | |

<!-- Severity key: 🔴 blocking  🟡 needs_architect  🟢 observation/minor -->

---

## Cross-checks

- [ ] Implementation matches the plan (no silent scope change)
- [ ] All 5 doc surfaces updated for schema changes (code / example yaml / ADRs / arch docs / narrative)
- [ ] No LLM imports in `src/orchestrator/workflow/` (ADR-008 Decision 2)
- [ ] CI gates pass: ruff check / ruff format --check / mypy --strict / pytest

---

## Verdict summary

<!-- One paragraph. State overall assessment, reference specific findings by
     number, and explain why verdict is clean / blocking / needs_architect. -->
