"""Skill file loader.

Discovers all *.md files under a directory, parses the YAML frontmatter
block, validates against the Pydantic schema, and returns a dict keyed by
Skill.id.

Concurrency: §2 N/A — single-threaded one-shot load. Not safe for concurrent
writes to the config/skills/ directory during loading (no locking).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from orchestrator.skills.exceptions import SkillError
from orchestrator.skills.schema import Skill

logger = logging.getLogger(__name__)


class _NotASkillFile:
    """Sentinel returned by _parse_frontmatter for non-skill markdown files."""


_NOT_A_SKILL = _NotASkillFile()


def _parse_frontmatter(path: Path) -> tuple[dict[str, Any] | _NotASkillFile, str]:
    """Split a SKILL.md file into (frontmatter_dict, body_str).

    Returns `(_NOT_A_SKILL, "")` for files with no opening '---' fence or
    non-dict YAML frontmatter — these are non-skill markdown files (e.g.
    README.md) and should be skipped by the caller.

    Raises SkillError on unclosed frontmatter fence (file opened '---' but
    never closed — malformed, not absent) and on YAML parse errors.
    """
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)

    if not lines or lines[0].rstrip() != "---":
        return _NOT_A_SKILL, ""

    close_idx: int | None = None
    for i, line in enumerate(lines[1:], start=1):
        if line.rstrip() == "---":
            close_idx = i
            break

    if close_idx is None:
        raise SkillError(
            f"{path}: unclosed YAML frontmatter (no closing '---' found)",
            path=path,
        )

    frontmatter_text = "".join(lines[1:close_idx])
    body = "".join(lines[close_idx + 1 :]).strip()

    try:
        raw = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as exc:
        raise SkillError(
            f"{path}: frontmatter YAML parse error: {exc}",
            path=path,
        ) from exc

    if not isinstance(raw, dict):
        return _NOT_A_SKILL, ""

    return raw, body


def load_skills(directory: Path) -> dict[str, Skill]:
    """Discover and load all SKILL.md files under *directory*.

    Returns a dict keyed by Skill.id. All discovered files are loaded before
    raising — duplicate-id detection requires a complete pass.

    Raises:
        SkillError: missing directory, malformed frontmatter, schema
            validation failure, filename/id mismatch, or duplicate id.
    """
    if not directory.exists():
        raise SkillError(f"skills directory does not exist: {directory}", path=directory)

    skills: dict[str, Skill] = {}

    for md_path in sorted(directory.rglob("*.md")):
        result, body = _parse_frontmatter(md_path)
        if isinstance(result, _NotASkillFile):
            logger.debug("skipping non-skill file: %s", md_path)
            continue

        frontmatter = result
        frontmatter["body"] = body

        try:
            skill = Skill.model_validate(frontmatter)
        except ValidationError as exc:
            first_loc = ".".join(str(p) for p in exc.errors()[0]["loc"]) if exc.errors() else ""
            raise SkillError(
                f"{md_path}: schema validation failed: {exc}",
                path=md_path,
                field=first_loc or None,
            ) from exc

        stem = md_path.stem
        if skill.id != stem:
            raise SkillError(
                f"{md_path}: filename stem {stem!r} does not match id {skill.id!r} "
                f"(ADR-009 Decision 8: filename stem must equal id)",
                path=md_path,
                field="id",
            )

        if skill.id in skills:
            existing_path = next(
                p for p in directory.rglob("*.md") if p.stem == skill.id and p != md_path
            )
            raise SkillError(
                f"duplicate skill id {skill.id!r}: found in both {existing_path} and {md_path}",
                path=md_path,
                field="id",
            )

        skills[skill.id] = skill

    return skills
