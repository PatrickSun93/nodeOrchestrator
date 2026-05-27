"""Workflow state machine CLI.

`verify-workspace` exists because two W-001-cycle instances of
stale-workspace-as-truth (RC-7) surfaced the failure mode.

Subcommands: status, init, advance, override, verify-workspace.
Framework-agnostic primitive; the Claude Code SessionStart hook
(impl-5) shells out to this CLI. No logic lives in the hook beyond
the invocation.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from orchestrator.workflow.exceptions import WorkflowError
from orchestrator.workflow.io import _read_plan_frontmatter, read_state, write_state
from orchestrator.workflow.schema import OverrideEntry, TaskState, WorkflowState
from orchestrator.workflow.transitions import (
    ArtifactSnapshot,
    GateSnapshot,
    evaluate_merge_clean,
    next_state,
    parse_verdict,
    record_override,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _state_path(workflow_dir: Path, task_id: str) -> Path:
    return workflow_dir / f"{task_id}.yaml"


# Recognized review filenames per stub §5.2 — only these reach parse_verdict.
_REVIEW_FILENAMES = frozenset({"plan-vs-impl.md", "R0-A.md", "R0-B.md", "R1-A.md", "R1-B.md"})


def _safe_load_verdict(
    path: Path,
) -> Literal["clean", "blocking", "needs_architect", "absent"]:
    """Parse a review file verdict. Returns 'absent' if the file is missing.
    Only call with filenames from _REVIEW_FILENAMES (side-channel filter).
    """
    if not path.exists():
        return "absent"
    return parse_verdict(path)


def _parse_adr_status(content: str) -> Literal["proposed", "accepted", "none"]:
    lowered = content.lower()
    if "status: accepted" in lowered or "**status:** accepted" in lowered:
        return "accepted"
    if "status: proposed" in lowered or "**status:** proposed" in lowered:
        return "proposed"
    return "none"


def _read_adr_status(task_id: str, repo_root: Path) -> Literal["proposed", "accepted", "none"]:
    """Check ADR status via plan frontmatter (path β) or direct file lookup (fallback).

    Plan-frontmatter path (W-002): reads senior-plans/{task_id}.md frontmatter for
    an `adr: ADR-NNN` key, globs docs/decisions/ADR-NNN-*.md, and returns its status.

    Fallback: if the plan has no frontmatter or no `adr` key, reads
    docs/decisions/ADR-{task_id}.md directly (pre-W-002 backwards compat).

    Raises WorkflowError if `adr` is a list (W-003 scope) or if multiple ADR
    files match the NNN-slug prefix (authoring error).
    """
    plan_path = repo_root / "docs" / "process" / "senior-plans" / f"{task_id}.md"
    fm = _read_plan_frontmatter(plan_path)

    if fm is not None and "adr" in fm:
        adr_val = fm["adr"]
        if isinstance(adr_val, list):
            raise WorkflowError(
                f"{plan_path}: multi-ADR-per-task not yet supported (W-003 scope); "
                f"found `adr: {adr_val!r}`",
                path=plan_path,
            )
        if not isinstance(adr_val, str):
            raise WorkflowError(
                f"{plan_path}: `adr` field must be a string like 'ADR-099', "
                f"got {type(adr_val).__name__}",
                path=plan_path,
            )
        decisions_dir = repo_root / "docs" / "decisions"
        matches = sorted(decisions_dir.glob(f"{adr_val.strip()}-*.md"))
        if not matches:
            return "none"
        if len(matches) > 1:
            raise WorkflowError(
                f"Multiple ADR files match {adr_val!r}: {[str(m) for m in matches]}",
                path=decisions_dir,
            )
        return _parse_adr_status(matches[0].read_text(encoding="utf-8"))

    # Fallback: direct ADR-{task_id}.md lookup (pre-W-002 backwards compat)
    adr_path = repo_root / "docs" / "decisions" / f"ADR-{task_id}.md"
    if not adr_path.exists():
        return "none"
    return _parse_adr_status(adr_path.read_text(encoding="utf-8"))


def _has_commit_since(since: datetime, repo_root: Path) -> bool:
    """Return True if any git commit was authored after `since`."""
    since_str = since.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"--after={since_str}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            cwd=str(repo_root),
        )
        return bool(result.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return False


def _is_pr_merged(repo_root: Path) -> bool:
    """Return True if HEAD is an ancestor of origin/main (branch merged)."""
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", "HEAD", "origin/main"],
            capture_output=True,
            timeout=10,
            check=False,
            cwd=str(repo_root),
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _current_branch(repo_root: Path) -> str:
    """Return the current git branch name, or 'HEAD' if detached."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            cwd=str(repo_root),
        )
        return result.stdout.strip() or "HEAD"
    except (OSError, subprocess.TimeoutExpired):
        return "HEAD"


def build_artifact_snapshot(
    task_id: str,
    state: TaskState,
    workflow_dir: Path,
) -> ArtifactSnapshot:
    """Build ArtifactSnapshot from filesystem + git log.

    Side-channel files are excluded: this builder only reads the specific
    paths listed in _REVIEW_FILENAMES before calling parse_verdict. Stub
    §5.2 side-channel-no-op invariant lives at this filter.
    """
    repo_root = workflow_dir.parent
    reviews_dir = repo_root / "docs" / "process" / "reviews" / task_id

    brief_exists = (repo_root / "docs" / "process" / "architect-briefs" / f"{task_id}.md").exists()
    senior_plan_exists = (
        repo_root / "docs" / "process" / "senior-plans" / f"{task_id}.md"
    ).exists()
    adr_status = _read_adr_status(task_id, repo_root)
    junior_impl_commit_present = _has_commit_since(state.last_transition_at, repo_root)
    plan_vs_impl_verdict = _safe_load_verdict(reviews_dir / "plan-vs-impl.md")
    r0_a_verdict = _safe_load_verdict(reviews_dir / "R0-A.md")
    pr_merged = _is_pr_merged(repo_root)

    return ArtifactSnapshot(
        brief_exists=brief_exists,
        senior_plan_exists=senior_plan_exists,
        adr_status=adr_status,
        junior_impl_commit_present=junior_impl_commit_present,
        plan_vs_impl_verdict=plan_vs_impl_verdict,
        r0_a_verdict=r0_a_verdict,
        pr_merged=pr_merged,
    )


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
    """Evaluate and apply the next auto-transition for a task.

    Reads the state file, builds ArtifactSnapshot + GateSnapshot, calls
    next_state, and writes the new state file if a transition fires.
    Writes-then-renames atomically via write_state (§3 cleanup obligation).
    """
    wdir = Path(args.workflow_dir)
    path = _state_path(wdir, args.task_id)
    try:
        state = read_state(path)
    except WorkflowError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        artifacts = build_artifact_snapshot(args.task_id, state, wdir)
    except WorkflowError as exc:
        print(f"ERROR: building artifact snapshot: {exc}", file=sys.stderr)
        return 1

    repo_root = wdir.parent
    branch = _current_branch(repo_root)
    try:
        merge_clean = evaluate_merge_clean(branch)
    except WorkflowError:
        merge_clean = False

    gates = GateSnapshot(merge_clean=merge_clean)
    result = next_state(state.state, artifacts, gates)

    if result is None:
        print(f"{args.task_id}: no transition fires (current state: {state.state})")
        return 0

    new_state = state.model_copy(
        update={
            "state": result,
            "last_transition_at": datetime.now(UTC),
        }
    )
    try:
        write_state(new_state, path)
    except WorkflowError as exc:
        print(f"ERROR: writing state: {exc}", file=sys.stderr)
        return 1
    print(f"{args.task_id}: {state.state} → {result}")
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
        help="Evaluate and apply the next auto-transition.",
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
