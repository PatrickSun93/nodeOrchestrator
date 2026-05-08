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

### Q3. For schema-changing PRs: did you scan all five reference surfaces?

When the PR changes a schema — a data field, validator, type, structure,
required vs optional, the shape of a config block — every reference must
be updated. Five surfaces to scan:

1. **Main code** — `src/orchestrator/**/*.py` (types, protocol, router,
   loader, providers, …).
2. **Example YAML** — `config/**/*.yaml.example`.
3. **Architecture Decision Records** — `docs/decisions/*.md`. Especially
   the ADR that established the schema; if its decision text or
   reversibility row references the old shape, fix it.
4. **Architecture docs** — `docs/architecture/*.md` (`event-model.md`,
   `llm-layer.md`, …).
5. **Project narrative** — `handoff.md` and `chat-history.md` at the
   repo root.

If a schema change appears in code but not in the example YAML, or in
an ADR but not in `handoff.md`, that is **doc-spec drift**: the schema's
mentioned-in-code definition and its mentioned-in-docs definition
silently diverge, and future readers can't tell which one is canonical.

In the followup-commit tracking table, a `Status: Done` row is not
legitimately checked until all five surfaces are consistent. If a
surface is intentionally left at the old shape (e.g. an ADR being
superseded keeps its text), call that out explicitly in the row's
status field, not silently.

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
