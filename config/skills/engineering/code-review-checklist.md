---
id: code-review-checklist
category: engineering
applies_to:
  agents: ["*"]
  room_types: [code_review]
priority: 65
---

# Code Review Checklist

Work through the following checklist systematically when reviewing a code change.

**Correctness**
- Does the change do what the description says it does?
- Are edge cases (empty input, overflow, null/None, concurrency) handled?
- Are error paths tested and do they fail loudly rather than silently?

**Design**
- Is the change the smallest unit that delivers value (avoid scope creep)?
- Are abstractions at the right level — no premature generalisation, no unnecessary specialisation?
- Does the change introduce new state that increases coupling or makes testing harder?

**Security**
- Are inputs validated at trust boundaries?
- Are secrets / credentials handled via env vars or secret stores, never inlined?
- Are SQL/command/template injections prevented?

**Test coverage**
- Does every new behaviour have at least one test?
- Do tests assert on observable outcomes, not on implementation details?
- Is the test suite repeatable (no side-effects between runs)?

**Observability**
- Are errors logged with enough context to diagnose without a debugger?
- Are performance-sensitive paths instrumented where failure cost is high?

Guidance: flag blocking issues first; separate style/nit comments clearly.
