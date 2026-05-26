#!/bin/bash
set -euo pipefail

# SessionStart hook for Claude Code on the web.
#
# Two responsibilities:
# (1) Install Python dependencies in remote env (idempotent; first
#     run installs, subsequent runs are no-op via uv's resolver cache).
# (2) Report workflow state + workspace freshness via the workflow CLI
#     (per W-001-impl ADR-008 Decision 9 — session-start trigger).
#
# Locally, (1) is skipped (deps assumed installed); (2) still runs so
# the developer sees state on each resume.

# (1) Remote-only: dependency install.
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
  uv sync --frozen
fi

# (2) Workflow state + workspace verification — runs in all envs.
# Suppress exit codes so hook itself never blocks session start
# (per W-001-impl R0-A-on-plan-4 — hook is informational only).
uv run workflow status || true
uv run workflow verify-workspace || true

exit 0
