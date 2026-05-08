# Contributing

## PR template (mandatory)

Every PR description must answer these two questions explicitly. PRs that
skip them get bounced back. The questions enforce the project's two
load-bearing architecture rules.

### Q1. Does this PR contain LLM calls? If yes, why couldn't each one be done in code?

The most important architecture rule: decision paths go in code, LLMs
generate content. See `handoff.md` §3.1 and `chat-history.md` §8.

A "decision path" is anything that routes, gates, scores, ranks, or selects:

- "Should this agent speak now?"
- "What autonomy level applies to this operation?"
- "Which skills should we load for this event?"
- "Does this hypothesis qualify for promotion to verified knowledge?"
- "What's in the agent's context window for this turn?"

These are tempting to delegate to LLMs ("just ask Claude"). The rule says:
**don't**. Build a data structure and a pure function. The function is testable,
auditable, free, deterministic, and survives LLM API outages. Per Principle 11,
LLM-judgment without ground truth is drift in disguise.

If your PR adds an LLM call, the description must list the call site and
explain why no code-only path achieves the same outcome. Reviewers should
challenge each one.

### Q2. Do all decision functions return a `decision_trace`?

Any function that makes a routing/gating/scoring/selection decision must
return enough information to explain *why* that decision was reached, not
just *what* the decision was.

```python
# bad
def determine_autonomy_level(op) -> AutonomyLevel: ...

# good
def determine_autonomy_level(op) -> tuple[AutonomyLevel, DecisionTrace]: ...
```

`DecisionTrace` should include: the rule(s) matched, the score(s) computed,
the inputs considered, and the precedence order applied. The principle is
the same as compiler error messages — saying "no" without saying "why" is
useless.

This applies even to "obviously correct" decisions. If the code is correct,
the trace is cheap. If the code becomes wrong later, the trace is the
fastest path to the bug.

## Architecture decisions (ADRs)

Decisions that change the shape of the system live in `docs/decisions/`
as `ADR-NNN-slug.md`. Each ADR is short and structured:

- **Context** — what problem, what constraints, what was considered
- **Decision** — what we chose
- **Consequences** — what becomes easier and what becomes harder
- **Reversibility** — how expensive is it to undo this in 6 months

Add an ADR when:

- Adding a new event type
- Changing autonomy scoring weights
- Adding a new agent role
- Changing how memory promotion works
- Touching anything in `handoff.md` §3 (core architecture)

You don't need an ADR for a typical feature PR.

## Code style

- `ruff check` and `ruff format` must pass.
- `mypy --strict` must pass.
- `pytest` must pass.
- Tests live next to the module they cover, mirrored under `tests/`.
- Public functions get docstrings only when the *why* is non-obvious. Type
  hints carry the *what*.

## Commit messages

Imperative mood, focus on the why. The diff already shows the what.

Bad: `update event store`
Good: `enforce append-only via TRIGGER, not convention`

## What goes in `src/`, what goes in `config/`

- `src/` — code that runs.
- `config/` — data the code consumes (agent YAMLs, autonomy rules,
  UI strings, state machine definitions). Editable without code review
  in the same way runtime code is.

If you find yourself hardcoding strings the user will see, route them
through `config/ui_strings/` instead.
