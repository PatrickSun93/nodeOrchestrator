# Session-start hook

## What it does

On every Claude Code session start, the hook runs two CLI commands:

```
uv run workflow status
uv run workflow verify-workspace
```

`workflow status` prints the current state of every tracked task to stdout,
giving the operator an immediate view of what state the workflow is in before
any work begins.

`workflow verify-workspace` fetches `origin` and checks `git status --short`.
If the local workspace is diverged or has uncommitted changes, it writes a
warning to stderr. This is the RC-7 mitigation: two W-001-cycle instances of
stale-workspace-as-truth made the failure mode concrete enough to warrant a
forcing function at session boundary.

## Design constraints

The hook is **non-blocking by design** — the hook command always exits 0 so
session startup is never gated on CLI outcome (including hard errors). Warnings
surface to the operator as stderr output; the operator decides whether to
act on them before proceeding.

This applies equally to informational warnings (dirty workspace) and to CLI
hard-errors (e.g., `.workflow/` directory absent on first use). Session
continues regardless. See W-001-impl plan §impl-5 and R0-A-on-plan-4.

## Dependency

The hook depends on the `workflow` CLI entry-point defined in `pyproject.toml`
(installed via `uv run`). The hook contains no logic beyond the CLI invocation:
all state-machine logic lives in `src/orchestrator/workflow/`.

## References

- ADR-008 Decision 9 — session-start trigger rationale
- `src/orchestrator/workflow/cli.py` — CLI implementation
- `pyproject.toml` `[project.scripts]` — `workflow` entry-point declaration

## Disabling

To disable for a session: comment out or remove the `SessionStart` block from
`.claude/settings.json`. Re-enable after the session by reverting.
