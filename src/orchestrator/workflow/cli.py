"""Workflow state machine CLI.

`verify-workspace` exists because two W-001-cycle instances of
stale-workspace-as-truth (RC-7) surfaced the failure mode.

Subcommands: status, init, advance (stub — see impl-6), override,
verify-workspace. Framework-agnostic primitive; the Claude Code
SessionStart hook (impl-5) shells out to this CLI. No logic lives
in the hook beyond the invocation.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from orchestrator.workflow.exceptions import WorkflowError
from orchestrator.workflow.io import read_state, write_state
from orchestrator.workflow.schema import OverrideEntry, TaskState, WorkflowState
from orchestrator.workflow.transitions import record_override

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _state_path(workflow_dir: Path, task_id: str) -> Path:
    return workflow_dir / f"{task_id}.yaml"


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    wdir = Path(args.workflow_dir)
    if not wdir.is_dir():
        print(
            f"ERROR: .workflow/ directory not found at {wdir.resolve()}",
            file=sys.stderr,
        )
        return 1

    if args.task_id:
        path = _state_path(wdir, args.task_id)
        try:
            state = read_state(path)
        except WorkflowError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(f"{state.task_id}: {state.state} (cycle {state.cycle})")
    else:
        yaml_files = sorted(wdir.glob("*.yaml"))
        if not yaml_files:
            print("No task state files found.")
            return 0
        for path in yaml_files:
            try:
                state = read_state(path)
                print(f"{state.task_id}: {state.state} (cycle {state.cycle})")
            except WorkflowError as exc:
                print(f"WARNING: {path.name}: {exc}", file=sys.stderr)
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    wdir = Path(args.workflow_dir)
    path = _state_path(wdir, args.task_id)

    if path.exists() and not args.force:
        print(
            f"ERROR: {path} already exists. Use --force to overwrite.",
            file=sys.stderr,
        )
        return 1

    try:
        workflow_state = WorkflowState(args.state)
    except ValueError:
        valid = ", ".join(s.value for s in WorkflowState)
        print(
            f"ERROR: invalid state {args.state!r}. Must be one of: {valid}",
            file=sys.stderr,
        )
        return 1

    wdir.mkdir(parents=True, exist_ok=True)
    state = TaskState(
        task_id=args.task_id,
        state=workflow_state,
        cycle=1,
        last_transition_at=datetime.now(UTC),
    )
    try:
        write_state(state, path)
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Created {path}: {workflow_state}")
    return 0


def cmd_advance(args: argparse.Namespace) -> int:
    """Stub in impl-4. Auto-trigger glue body filled in impl-6."""
    wdir = Path(args.workflow_dir)
    path = _state_path(wdir, args.task_id)
    try:
        state = read_state(path)
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    # impl-6 replaces this stub body with transition evaluation.
    print(
        f"{state.task_id}: currently {state.state} — "
        "auto-trigger evaluation not yet wired (impl-6 pending)",
        file=sys.stderr,
    )
    return 0


def cmd_override(args: argparse.Namespace) -> int:
    wdir = Path(args.workflow_dir)
    path = _state_path(wdir, args.task_id)

    try:
        state = read_state(path)
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        to_state = WorkflowState(args.to_state)
    except ValueError:
        valid = ", ".join(s.value for s in WorkflowState)
        print(
            f"ERROR: invalid --to-state {args.to_state!r}. Must be one of: {valid}",
            file=sys.stderr,
        )
        return 1

    try:
        entry = OverrideEntry(
            timestamp=datetime.now(UTC),
            actor=args.actor,
            from_state=state.state,
            to_state=to_state,
            reason=args.reason,
        )
    except Exception as exc:
        print(f"ERROR: override entry validation failed — {exc}", file=sys.stderr)
        return 1

    new_state = record_override(state, entry)
    try:
        write_state(new_state, path)
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"{args.task_id}: {state.state} → {to_state} (cycle {new_state.cycle})")
    return 0


def cmd_verify_workspace(args: argparse.Namespace) -> int:
    """RC-7 mitigation: fetch origin then report any local divergence to stderr.

    Always exits 0 — this is informational only. A blocking forcing function
    would be wrong: senior may legitimately work on multiple tasks per session.
    """
    try:
        subprocess.run(
            ["git", "fetch", "origin"],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        print("WARNING: git fetch timed out; workspace freshness unknown.", file=sys.stderr)
        return 0
    except (subprocess.CalledProcessError, OSError):
        print("WARNING: git fetch failed; workspace freshness unknown.", file=sys.stderr)
        return 0

    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        print("WARNING: git status failed; workspace freshness unknown.", file=sys.stderr)
        return 0

    if result.stdout.strip():
        print(
            "WARNING: workspace has uncommitted changes or untracked files:\n"
            + result.stdout.rstrip(),
            file=sys.stderr,
        )
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="workflow",
        description="Workflow state machine CLI. See ADR-008.",
    )
    parser.add_argument(
        "--workflow-dir",
        default=".workflow",
        metavar="DIR",
        help="Path to the .workflow/ state directory (default: .workflow).",
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    # status
    p_status = sub.add_parser("status", help="Print current state of one or all tasks.")
    p_status.add_argument("--task-id", metavar="TASK", help="Show only this task.")
    p_status.set_defaults(func=cmd_status)

    # init
    p_init = sub.add_parser("init", help="Create a new task state file.")
    p_init.add_argument("--task-id", required=True, metavar="TASK")
    p_init.add_argument(
        "--state",
        default="awaiting_brief",
        metavar="STATE",
        help="Initial state (default: awaiting_brief).",
    )
    p_init.add_argument("--force", action="store_true", help="Overwrite if file already exists.")
    p_init.set_defaults(func=cmd_init)

    # advance
    p_advance = sub.add_parser(
        "advance",
        help="Evaluate and apply the next auto-transition (auto-trigger glue in impl-6).",
    )
    p_advance.add_argument("--task-id", required=True, metavar="TASK")
    p_advance.set_defaults(func=cmd_advance)

    # override
    p_override = sub.add_parser("override", help="Record an architect override (Decision 10).")
    p_override.add_argument("--task-id", required=True, metavar="TASK")
    p_override.add_argument("--to-state", required=True, metavar="STATE")
    p_override.add_argument("--reason", required=True, metavar="TEXT")
    p_override.add_argument(
        "--actor",
        required=True,
        choices=["architect", "architect-partner"],
        metavar="ACTOR",
        help="architect | architect-partner",
    )
    p_override.set_defaults(func=cmd_override)

    # verify-workspace
    p_verify = sub.add_parser(
        "verify-workspace",
        help="Fetch origin and warn on local divergence (RC-7 mitigation).",
    )
    p_verify.set_defaults(func=cmd_verify_workspace)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))
