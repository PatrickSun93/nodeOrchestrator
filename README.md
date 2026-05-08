# Orchestrator

AI research and decision assistant. Honest interlocutor, not obedient executor.

> "Think a thing through, with an assistant who can challenge your ideas."

## Core architecture rule

**Decision paths in code, content generation in LLMs.**

Routing, gating, scoring, ranking, selection — code.
Writing, reasoning, responding — LLMs.

See `handoff.md` for the full design and 12 governing principles.
See `chat-history.md` for the reasoning behind each decision.

## Status

P0 in progress. Current PR: event store foundation.

## Setup

```bash
uv venv
uv pip install -e . --group dev
uv run pytest
```

## Layout

```
src/orchestrator/
  core/         # Event store, Room, Relations (this PR)
  agents/       # Future
  tools/        # Future
  memory/       # Future
  autonomy/     # Future
docs/
  contributing.md      # PR template — read before opening any PR
  architecture/        # System-level design notes
  decisions/           # ADRs (added per-decision)
```

## Reading order for new contributors

1. `handoff.md` sections 1–3 (project, 12 principles, core architecture)
2. `chat-history.md` section 8 (decision-path codification — most important rule)
3. `handoff.md` sections 4–13 (data model through implementation priority)
4. `docs/contributing.md` (PR rules)
