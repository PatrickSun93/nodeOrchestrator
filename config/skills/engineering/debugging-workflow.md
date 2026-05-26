---
id: debugging-workflow
category: engineering
applies_to:
  agents: ["*"]
  room_types: [bug_fix, code_review]
  room_states: ["open"]
priority: 70
---

# Debugging Workflow

Use a structured approach when investigating bugs or reviewing code for defects.

Steps:
1. Reproduce the issue with a minimal, isolated test case before editing code.
2. State the expected behavior and the actual behavior explicitly.
3. Identify the boundary where expected and actual diverge — trace inward.
4. Form one hypothesis at a time; test it before forming the next.
5. After a fix, verify the original test case passes and run the full suite.

Avoid applying multiple changes simultaneously — it obscures which change
fixed the bug. Prefer small, reversible edits with verification between each.
