"""Workflow state machine CLI.

`verify-workspace` exists because two W-001-cycle instances of
stale-workspace-as-truth (RC-7) surfaced the failure mode.

Subcommands: status, init, advance, override, verify-workspace,
verify-merge-readiness.
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

import yaml

from orchestrator.workflow.exceptions import WorkflowError
from orchestrator.workflow.io import (
    _git_branch_exists,
    _git_log_ahead_of_main_since,
    _git_show,
    _read_plan_frontmatter,
    read_state,
    write_state,
)
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


def _review_file_in_cycle(path: Path, since: datetime, repo_root: Path) -> bool:
    """Return True if the review file is considered "in cycle" for state-
    machine purposes (ADR-008 Decision 14 — cycle-boundary artifact filter).

    Three cases:
    - File doesn't exist on disk → True (caller sees 'absent' anyway).
    - File exists but has NO git history at all → True (file is fresh in
      working tree; never committed; treat as in-cycle. Real workflow
      never produces this state since review pushes commit + push; synthetic
      tests do.)
    - File exists with git history → True iff at least one commit since
      `since`. Stale cycle-1 artifacts in cycle 2+ return False.

    Prevents the P1.6 cycle-2 cascade where workflow advance read cycle-1
    plan-vs-impl + R0-A files and inappropriately reached AWAITING_R0_A.
    """
    if not path.exists():
        return True  # caller will see 'absent' regardless; don't double-filter
    try:
        rel = str(path.relative_to(repo_root))
        # First: does the file have ANY git history?
        any_log = subprocess.run(
            ["git", "log", "--format=%H", "-1", "--", rel],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            cwd=str(repo_root),
        )
        if not any_log.stdout.strip():
            # Never committed → working tree artifact; not stale.
            return True
        # Has history → check for commits since the cycle boundary.
        cycle_log = subprocess.run(
            [
                "git",
                "log",
                f"--since={since.isoformat()}",
                "--format=%H",
                "--",
                rel,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            cwd=str(repo_root),
        )
        return bool(cycle_log.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        # Conservative on failure: treat as "in cycle" to avoid silently
        # hiding artifacts. State-machine self-check will surface
        # inconsistencies (per CLAUDE.md "halt + surface" rule).
        return True


def _safe_load_verdict_cycle_filtered(
    path: Path, since: datetime, repo_root: Path
) -> Literal["clean", "blocking", "needs_architect", "absent"]:
    """Like _safe_load_verdict but additionally returns 'absent' for files
    that exist on disk but have no commit-since-{since} (ADR-008 Decision 14).
    """
    if not _review_file_in_cycle(path, since, repo_root):
        return "absent"
    return _safe_load_verdict(path)


def _parse_adr_status(content: str) -> Literal["proposed", "accepted", "none"]:
    lowered = content.lower()
    if "status: accepted" in lowered or "**status:** accepted" in lowered:
        return "accepted"
    if "status: proposed" in lowered or "**status:** proposed" in lowered:
        return "proposed"
    return "none"


def _normalize_adr_refs(adr_val: list[object], plan_path: Path) -> list[str]:
    """Validate and normalize a list-form `adr` frontmatter value to plain strings.

    Raises WorkflowError if the list is empty or any element is not a non-empty string.
    """
    if not adr_val:
        raise WorkflowError(
            f"{plan_path}: empty `adr` list in frontmatter — "
            "declared multi-ADR but specified zero ADRs",
            path=plan_path,
        )
    refs: list[str] = []
    for i, elem in enumerate(adr_val):
        if not isinstance(elem, str):
            raise WorkflowError(
                f"{plan_path}: `adr` list element {i} must be a string, "
                f"got {type(elem).__name__} ({elem!r})",
                path=plan_path,
            )
        if not elem.strip():
            raise WorkflowError(
                f"{plan_path}: `adr` list element {i} is an empty string",
                path=plan_path,
            )
        refs.append(elem.strip())
    return refs


def _read_adr_status(task_id: str, repo_root: Path) -> Literal["proposed", "accepted", "none"]:
    """Check ADR status via plan frontmatter (path β) or direct file lookup (fallback).

    Plan-frontmatter path (W-002/W-002.5): reads senior-plans/{task_id}.md frontmatter
    for an `adr: ADR-NNN` string or `adr: [ADR-NNN, ...]` list, globs each ADR file,
    and returns aggregated status (all-or-nothing for lists: all Accepted → "accepted";
    any Proposed → "proposed"; any missing → "none").

    Fallback: if the plan has no frontmatter or no `adr` key, reads
    docs/decisions/ADR-{task_id}.md directly (pre-W-002 backwards compat).

    Raises WorkflowError if `adr` is a non-string/non-list type; list is empty or
    contains non-string elements; multiple ADR files match a single NNN-slug prefix.
    """
    plan_path = repo_root / "docs" / "process" / "senior-plans" / f"{task_id}.md"
    fm = _read_plan_frontmatter(plan_path)

    if fm is not None and "adr" in fm:
        adr_val = fm["adr"]
        decisions_dir = repo_root / "docs" / "decisions"
        if isinstance(adr_val, list):
            refs = _normalize_adr_refs(adr_val, plan_path)
            statuses: list[Literal["proposed", "accepted", "none"]] = []
            for ref in refs:
                matches = sorted(decisions_dir.glob(f"{ref}-*.md"))
                if not matches:
                    statuses.append("none")
                elif len(matches) > 1:
                    raise WorkflowError(
                        f"Multiple ADR files match {ref!r}: {[str(m) for m in matches]}",
                        path=decisions_dir,
                    )
                else:
                    statuses.append(_parse_adr_status(matches[0].read_text(encoding="utf-8")))
            if "none" in statuses:
                return "none"
            if "proposed" in statuses:
                return "proposed"
            return "accepted"
        if not isinstance(adr_val, str):
            raise WorkflowError(
                f"{plan_path}: `adr` field must be a string like 'ADR-099', "
                f"got {type(adr_val).__name__}",
                path=plan_path,
            )
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


def _has_junior_impl_commits(task_id: str, since: datetime, repo_root: Path) -> bool:
    """Return True if claude/{task_id}-impl branch exists on origin and has commits
    ahead of origin/main since `since`. Task-scoped RC-19 fix replacing _has_commit_since."""
    branch_ref = f"refs/remotes/origin/claude/{task_id}-impl"
    if not _git_branch_exists(branch_ref, repo_root):
        return False
    return _git_log_ahead_of_main_since(branch_ref, since, repo_root)


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
    senior_plan_path = repo_root / "docs" / "process" / "senior-plans" / f"{task_id}.md"
    senior_plan_exists = senior_plan_path.exists()
    adr_status = _read_adr_status(task_id, repo_root)
    junior_impl_commit_present = _has_junior_impl_commits(
        task_id, state.last_transition_at, repo_root
    )
    # W-005 Decision 14: cycle-boundary filter — review files only count if
    # touched by a commit since state.last_transition_at. Prevents cycle-2
    # advance from cascading through cycle-1 artifacts (P1.6 c2b7a12 incident).
    plan_vs_impl_verdict = _safe_load_verdict_cycle_filtered(
        reviews_dir / "plan-vs-impl.md", state.last_transition_at, repo_root
    )
    r0_a_verdict = _safe_load_verdict_cycle_filtered(
        reviews_dir / "R0-A.md", state.last_transition_at, repo_root
    )
    pr_merged = _is_pr_merged(repo_root)

    # Compute plan_has_adr for W-002-2b no-ADR routing in next_state.
    # None = no frontmatter (legacy); False = frontmatter without adr key; True = has adr.
    plan_fm = _read_plan_frontmatter(senior_plan_path)
    if plan_fm is None:
        plan_has_adr: bool | None = None
    else:
        plan_has_adr = "adr" in plan_fm

    # W-005 Amendment 2: detect architect-routing*.md in reviews dir. Any file
    # matching the glob (architect-routing.md, architect-routing-on-impl.md,
    # architect-routing-deepseek.md, etc.) signals architect has routed; senior
    # begins absorption.
    architect_routing_exists = (
        reviews_dir.exists() and any(reviews_dir.glob("architect-routing*.md"))
    )

    return ArtifactSnapshot(
        brief_exists=brief_exists,
        senior_plan_exists=senior_plan_exists,
        adr_status=adr_status,
        junior_impl_commit_present=junior_impl_commit_present,
        plan_vs_impl_verdict=plan_vs_impl_verdict,
        r0_a_verdict=r0_a_verdict,
        pr_merged=pr_merged,
        plan_has_adr=plan_has_adr,
        architect_routing_exists=architect_routing_exists,
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


def cmd_verify_merge_readiness(args: argparse.Namespace) -> int:
    """RC-13 forcing function: check impl branch has clean reviews before merge.

    Checks docs/process/reviews/<TASK_ID>/plan-vs-impl.md and R0-A.md
    for presence + verdict: clean. Warn-don't-block; always exits 0.
    """
    task_id: str = args.task_id
    reviews_dir = Path("docs") / "process" / "reviews" / task_id
    required = ["plan-vs-impl.md", "R0-A.md"]
    all_ready = True

    for filename in required:
        path = reviews_dir / filename
        if not path.exists():
            print(
                f"WARNING: {task_id} — {filename} missing; merge not ready.",
                file=sys.stderr,
            )
            all_ready = False
            continue
        try:
            verdict = parse_verdict(path)
        except WorkflowError:
            print(
                f"WARNING: {task_id} — could not parse verdict from {filename}; merge not ready.",
                file=sys.stderr,
            )
            all_ready = False
            continue
        if verdict != "clean":
            print(
                f"WARNING: {task_id} — {filename} verdict={verdict!r}; merge not ready.",
                file=sys.stderr,
            )
            all_ready = False

    if all_ready:
        print(f"✓ {task_id} merge-ready (plan-vs-impl + R0-A both clean).")
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

    # W-003-3: state-file divergence detection.
    # For each local .workflow/*.yaml, compare content to origin/main.
    # If file is not on origin/main (new local task) → skip silently.
    # If content differs → warn naming the task + diverged state field.
    wdir = Path(args.workflow_dir)
    diverged: list[str] = []
    if wdir.is_dir():
        for state_file in sorted(wdir.glob("*.yaml")):
            task_id = state_file.stem
            origin_content = _git_show(f".workflow/{task_id}.yaml")
            if origin_content is None:
                continue  # new local task; not on origin/main
            local_content = state_file.read_text(encoding="utf-8")
            if local_content == origin_content:
                continue
            # Summarise: extract 'state' field from each for a brief diff hint.
            local_state = _extract_state_field(local_content)
            origin_state = _extract_state_field(origin_content)
            if local_state != origin_state:
                diverged.append(
                    f"  {task_id}: state local={local_state!r} vs origin/main={origin_state!r}"
                )
            else:
                diverged.append(f"  {task_id}: content differs from origin/main")

    if diverged:
        print(
            "WARNING: state-file divergence detected:\n" + "\n".join(diverged),
            file=sys.stderr,
        )
    return 0


def _extract_state_field(yaml_text: str) -> str:
    """Extract the 'state' field value from a .workflow yaml string.

    Returns the raw string value, or '<unknown>' if not parseable.
    """
    try:
        data = yaml.safe_load(yaml_text)
        if isinstance(data, dict):
            return str(data.get("state", "<unknown>"))
    except Exception:
        pass
    return "<unknown>"


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

    # verify-merge-readiness
    p_vmr = sub.add_parser(
        "verify-merge-readiness",
        help="Check plan-vs-impl + R0-A reviews are clean before merging (RC-13).",
    )
    p_vmr.add_argument("--task-id", required=True, metavar="TASK")
    p_vmr.set_defaults(func=cmd_verify_merge_readiness)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))
