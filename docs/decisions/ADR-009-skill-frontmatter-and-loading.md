# ADR-009: SKILL.md Frontmatter Schema + Loading Decision

**Status:** Accepted — 2026-05-26
**Scope:** Governs the `SKILL.md` file format (YAML frontmatter +
markdown body), the frontmatter contract every future skill author
must follow, and the shape of the code-driven loading decision
(`decide_skills_for_context`) — including its `decision_trace`. Also
inscribes the layering rules for the new `src/orchestrator/skills/`
package. Out of scope: actual agent context-window integration (P1.4
agent runtime), cross-skill dependencies (deferred), skill versioning
or hashing (P2+), and the full 10-skill MVP library content (a
separate content task downstream of P1.3).

## Context

`handoff.md` §3.3 commits the project to a SKILL.md format —
"compatible with industry standard". §5.3 lists a 10-skill MVP
library across three categories (`general/`, `engineering/`,
`business/`). §3.1 commits to "decisions in code, LLM generates
content" — for skills this means: **the loading and matching of
skills is code; the markdown body is what the LLM reads**. P1.3
turns these commitments into a working loader plus a deterministic
matcher.

The contract every future skill author follows is **the
frontmatter**. Without an explicit ADR, each new skill drifts in
field name, list shape, default semantics. The autonomy `tools.yaml`
precedent (ADR-005) and the `EventType` precedent (ADR-001) both
show that user-facing schema choices that span the project lifetime
pay for an ADR even when the implementation is small — the cost of
relitigating "should `applies_to` be a list or a glob?" six months
later is higher than the cost of pinning it now.

Five sub-decisions need settling: (a) what fields are required and
what are optional; (b) the shape of `applies_to` (list / glob /
literal); (c) the semantic of empty / omitted `room_states`; (d) the
type and bounds of `priority` and its tie-breaking; (e) the layering
rules for the new package (`skills → core` direction, plus what's
forbidden). Three constraints bind the choices: Principle 3.1 (no
LLM in match), Principle 4 (closed-enum vocabulary over free strings),
the project's schema-level-enforcement preference
(`feedback_schema_enforcement.md`).

Hard requirements the decision must satisfy:

1. Pure-code loading and matching — no LLM call anywhere in
   `src/orchestrator/skills/`. Locked by a constitutional test
   (P1.3 adds `test_constitution_no_llm_calls_in_skills_module`).
2. The decision function returns a `decision_trace` per
   `contributing.md` Q2 — every skill considered, matched or not,
   with the predicate that decided.
3. Frontmatter is validated at schema time, not at match time. A
   malformed SKILL.md is a load-time error, not a runtime surprise.
4. Layering: `skills → core` allowed (RoomType is consumed);
   `core → skills` and `skills → llm` forbidden (locked by
   constitutional tests, additive to the W-001-impl precedent).

## Decisions

### 1. SKILL.md format: YAML frontmatter + markdown body

Each skill is one file under `config/skills/<category>/<id>.md`. The
file begins with a YAML frontmatter block fenced by `---`; the body
is markdown read by the consuming LLM at agent runtime (P1.4).

```markdown
---
id: research-decomposition
category: general
applies_to:
  agents: [prober, skeptic]
  room_types: [research, idea_validation]
  # room_states omitted → matches all states (see Decision 4)
priority: 50
---

# Research decomposition

(markdown body — instruction text consumed by the agent at runtime)
```

YAML chosen over JSON/TOML because: (a) YAML frontmatter is the
industry convention `handoff.md` §3.3 commits to; (b) human readers
edit these by hand; (c) the project's other config (`tools.yaml`,
agent YAML, model YAML) is YAML, and consistency matters more than
per-file optimality. See Considered Alternative A for the JSON case.

### 2. Required frontmatter fields: `id`, `category`, `applies_to`, `priority`

All four are required (no Pydantic default). The schema-level rule
("if the loader is to do anything with this skill, it must know
where it applies and how to rank it") means defaults would only
hide authoring errors.

- `id: str` — unique within `config/skills/`; matches the filename
  stem (validator enforces). Min length 1.
- `category: Literal["general", "engineering", "business"]` — fixed
  per `handoff.md` §5.3 directory structure. New categories require
  an ADR amendment (Principle 4: closed enum over open strings).
- `applies_to: AppliesTo` (see Decision 3 for its shape).
- `priority: int = Field(ge=0, le=100)` — bounded range. 0 = least
  preferred; 100 = most. Default value across the MVP library is 50;
  authors set lower/higher only when there's a comparative claim.

### 3. `applies_to` shape: list-of-ids, with `["*"]` convention

```python
class AppliesTo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    agents: list[str] = Field(min_length=1)        # agent ids or ["*"]
    room_types: list[RoomType] = Field(min_length=1)  # RoomType enum values
    room_states: list[str] | None = None           # see Decision 4
```

`agents` is a list of agent id strings; the sentinel `["*"]` means
"all agents". Lists are greppable (`grep "prober" config/skills/`
surfaces every skill that targets prober); a glob library would
abstract that away. `["*"]` as a single-element list is a small
convention — Pydantic accepts it; the matcher treats `"*"` in the
list as "match anything." Mixed lists like `["*", "prober"]` are
forbidden by a validator (redundant — if `*` is present, other ids
add nothing; reject to keep skill authoring honest).

`room_types` is a list of `RoomType` enum values (5 choices, per
`src/orchestrator/core/room.py`). Empty list is forbidden by
`min_length=1` — every skill applies to at least one room type
explicitly. The `["*"]` convention is **not** extended to
`room_types` because `RoomType` is a closed enum (5 values) and
listing all five takes seven characters more than `["*"]` — clarity
wins over brevity at this scale.

See Considered Alternative B for the glob/regex case.

### 4. `applies_to.room_states` semantic: `None` = match all states

`room_states` is optional. `None` (the default) means "match any
state for the room_types this skill targets." A non-None list
restricts the match to those specific states; the list must be
non-empty (Pydantic validator — empty list is rejected as a
likely authoring error: "did you mean to omit the key, or did you
mean a non-empty list?").

This shape is chosen because Pydantic's natural absent-key behavior
(`Optional[X] = None`) maps cleanly to "no restriction." The
sentinel `["*"]` is **not** used for `room_states` (unlike `agents`)
because `room_states` is a string field with no closed enum — the
sentinel would be indistinguishable from a literal room-state named
`"*"` if one existed. The `None` vs `[<value>, ...]` distinction is
unambiguous.

See Considered Alternative C for the empty-list-as-"all" case.

### 5. `priority` tie-breaking: alphabetical by `id`

When two skills share `priority`, deterministic order is by `id`
ascending (Unicode codepoint order). Documented in the matcher
docstring and tested. File-system traversal order is **not**
relied on — filesystem order is OS-dependent and observably
non-deterministic across platforms.

If a future skill author wants stricter ordering between specific
pairs, they bump priorities to be distinct. The matcher does not
support "skill X must come before skill Y" cross-references — that
is cross-skill dependency territory, deferred to P1.4+.

### 6. `decide_skills_for_context` returns a `SkillSelection` carrying trace

The matcher's return type is one frozen Pydantic model:

```python
class SkillDecisionTrace(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    considered: list[SkillMatchRecord]   # one per available skill
    selected_count: int
    rejected_count: int

class SkillMatchRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    skill_id: str
    rejection_reason: Literal[
        "agent_mismatch",
        "room_type_mismatch",
        "room_state_mismatch",
        "matched",
    ]
    # "matched"-ness is derived: record.rejection_reason == "matched".
    # No separate `matched: bool` field — single source of truth in the
    # Literal avoids the two-field-can-disagree drift class. Per R0-A-on-
    # plan-1(a).

class SkillSelection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    selected: list[Skill]   # ordered by priority desc, then id asc
    trace: SkillDecisionTrace
```

Embedding the trace inside the return type follows the autonomy
module's `AutonomyScore` precedent (ADR-005 Decision 6): the trace
lives with the decision, not in a side channel that the caller might
forget to log. The rejection-reason `Literal` is closed-enum per
Principle 4. Future reasons (e.g., per-event-type triggers in P1.4)
extend the Literal additively, mirroring the `refusal_reason` pattern
from ADR-007.

See Considered Alternative D for the separate-getter case.

### 7. Layering: `skills → core` allowed; `core → skills`, `skills → llm` forbidden

`orchestrator.skills` imports from `orchestrator.core` (for
`RoomType`, possibly `EventType` in P1.4+ triggers). This direction
is natural — `core` defines vocabulary; `skills` consumes it.

Forbidden directions, locked by new constitutional tests:

- `test_constitution_core_does_not_import_skills` — `core` must
  never depend on the higher-level `skills` package. Same shape as
  `test_constitution_core_does_not_import_autonomy` from W-001-impl
  (Y1 finding pattern).
- `test_constitution_no_llm_calls_in_skills_module` — no LLM SDK
  import anywhere under `src/orchestrator/skills/`. Same shape as
  the autonomy / workflow analogues. Vacuously passes at directory
  creation; load-bearing immediately.

`skills → autonomy` is **not** addressed by this ADR — P1.3 does
not need it. If P1.4 finds a reason to thread tool/autonomy data
into skill matching, that's an additive ADR amendment.

### 8. Filename stem equals `id`

A skill file at `config/skills/<category>/<id>.md` MUST declare
`id: <id>` in its frontmatter. The loader validates the equality on
load; mismatch raises `SkillError` with `path` and `field="id"`
populated. The rule enforces a 1:1 mapping between file location
and skill identifier — `grep -r "id: research-decomposition"
config/skills/` finds exactly one file. This is contract-locking for
every skill author and lives in the ADR (not just the loader
implementation) so future loader implementations stay consistent.

The validator lives at load time, not at Pydantic-construction time:
the `Skill` model has no access to the filesystem path the file was
loaded from, and surfacing the filename into the schema as a field
would mix two concerns (the canonical id is one piece of data, not
two). The loader is the only code that sees both pieces and can
compare them.

## Considered alternatives

### A. JSON or TOML frontmatter instead of YAML

JSON has stricter syntax and faster parse; TOML has cleaner
multi-line strings. **Rejected**: `handoff.md` §3.3 commits to "SKILL.md
compatible with industry standard" — the de-facto standard around
SKILL-style docs (Anthropic's claude-skills, openai-cookbook, etc.)
is YAML frontmatter. Consistency with the project's other config
(all YAML) outweighs per-file syntax preferences.

### B. `applies_to.agents` as glob string instead of list

A single string like `"prober|skeptic"` or `"all"` instead of a
list. **Rejected**: globs require a parser inside the matcher
(more code, more drift surface). The list shape is grep-friendly
(`grep "prober" config/skills/` finds every targeting skill) and
maps directly to set-membership matching. The `["*"]` sentinel
covers the "match all" case at minor convention cost.

### C. Empty list `[]` as "match all room_states"

Use `room_states: list[str] = []` with empty-list meaning "all
states." **Rejected**: empty list is a common authoring error
(forgot to fill in) that becomes silently equivalent to "all" —
the worst-case footgun. `None`-as-default (key omitted) makes the
"no restriction" intent explicit, and any explicit list is
required to be non-empty (validator catches the slip).

### D. `decide_skills_for_context` returns `list[Skill]` only; trace via separate getter

Match autonomy's `score()` function (which returns `int`, not
`AutonomyScore`). **Rejected** for the matcher specifically:
unlike `score()` which is one of three composed functions, the
matcher is the load-bearing decision in the skills module. Burying
the trace in a side-channel invites callers to log just the result
and lose the explanation. ADR-005 Decision 6 set the precedent that
the highest-stakes decision function carries its trace inline; this
ADR follows that precedent.

### E. Priority as `Literal["low", "medium", "high"]` instead of int

Three discrete buckets instead of 0–100. **Rejected**: forces a
second decision (which order? what about "very high"?) without
gain. Int 0–100 sorts naturally, ties cleanly, and authors can use
50 as a default without picking a bucket. If buckets emerge as a
useful UX (e.g., a CLI command surfaces priority), the bucketing
can be a presentation choice over the int — the wire format stays
int.

## Consequences

**Easier:**

- Adding a new skill: one file at `config/skills/<category>/<id>.md`,
  frontmatter validates at load time, matcher includes it on the
  next launch. No code change.
- "Why was this skill loaded?" is a single trace read — every
  considered skill carries its match/reject reason in
  `SkillDecisionTrace.considered[i].rejection_reason`.
- Constitutional tests catch layering or LLM-import slips
  immediately; new `core → skills` violations fail the test before
  PR.
- The `["*"]` agents convention is greppable: searches for an
  agent's targeting skills return concrete file paths.

**Harder:**

- Skill authors must learn the closed-enum `category` field plus
  the four required fields. Mitigated by the sample skills in
  P1.3-6 acting as templates.
- The `None`-vs-`[]`-vs-`["*"]` distinctions across the three
  `applies_to` sub-fields take a docstring paragraph to explain;
  the asymmetry (`agents` allows `["*"]`, `room_states` uses None)
  is deliberate but not obvious.
- A typo'd `category` (e.g., `enginering`) is caught at load time
  with a Pydantic error pointing at the file path and field name
  — clearer than a silent skip, but more friction than a
  free-string category would impose.
- The closed-enum `category` (3 values) and `rejection_reason` (4
  values) trade flexibility for vocabulary discipline. When a real
  category mismatch surfaces (e.g., a skill that doesn't fit
  general / engineering / business), the resolution path is
  Literal extension via ADR-009 amendment — reversibility-Low,
  following the `refusal_reason` precedent from ADR-007 Decision 2.
  Don't pre-extend on speculation; let the first misfit name the
  fourth category.

**Neutral:**

- The trace is verbose for a no-match case (every skill explained
  in a fresh `SkillDecisionTrace.considered` list). For a 10-skill
  MVP library this is 10 records per call; for 100+ skills it
  becomes a budget question P2+ addresses.
- `priority: int [0,100]` is wider than needed for an MVP library
  but cheap to keep narrow later. Bounds removal would be
  additively-compatible.
- The `Literal` rejection_reason can grow; P1.4+ may add
  `event_trigger_mismatch` or similar without an ADR amendment if
  the field semantics stay "why didn't this skill match?".

## Reversibility

| Decision | 6-month reversal cost |
|---|---|
| 1. SKILL.md format (YAML frontmatter + markdown body) | **Expensive** — the file format is the contract with every skill author; flipping to JSON/TOML migrates every skill file and changes documentation everywhere. |
| 2. Required frontmatter fields (`id`, `category`, `applies_to`, `priority`) | **Medium** — adding fields is additive (default value or `Optional`); removing or renaming is a migration across all skill files. |
| 3. `applies_to` shape (list-of-ids with `["*"]` sentinel) | **Medium** — switching to globs is a parser change + sentinel removal across the MVP library. |
| 4. `room_states = None` for "all" | **Low** — the alternative (`[]` for "all", or `["*"]` sentinel) is a one-line Pydantic validator change + matcher change; no migration if applied alongside the change. |
| 5. Tie-breaking alphabetical by id | **Trivial** — one line in the matcher; the alternative (FS order, or undefined) is mostly cosmetic. |
| 6. `SkillSelection` embeds `SkillDecisionTrace` | **Low** — splitting trace out to a separate getter is a return-type refactor; calls update, but only the matcher's callers (few). |
| 7. Layering (`skills → core` OK; reverse + LLM forbidden) | **Expensive** — once `skills` is depended on by `core`, breaking that cycle requires reorganization of either the imports or the package boundary itself. Pick the direction once, deliberately. |
| 8. Filename stem equals `id` | **Low** — one validator + one docstring; reversal is renaming a small set of skill files (~10 in MVP library) plus removing the validator. The 1:1 grep guarantee disappears on reversal, but no code depends on it beyond the validator. |

## References

- `handoff.md` §3.1 (decision paths in code), §3.3 (Skills/MCP/Plugins),
  §5.3 (MVP 10 skills library) — the project commitments this ADR
  operationalizes.
- `docs/contributing.md` Q1 (no LLM calls in decision paths), Q2
  (`decision_trace` obligation), Q3 (5-surface scan).
- `docs/architecture/test-coverage-standard.md` — six categories
  applied per P1.3 tasks.
- ADR-001 (event store foundation) — closed-enum precedent reused
  for `category` and `rejection_reason`.
- ADR-005 Decision 6 (autonomy_decision metadata) — the
  embed-trace-in-return-type precedent reused by `SkillSelection`.
- ADR-007 Decision 2 (`refusal_reason` Literal extensibility) —
  same pattern reused for `rejection_reason`.
- ADR-008 (workflow state machine) — the `.workflow/P1.3.yaml`
  state file governing this task's lifecycle.
- `docs/process/architect-briefs/P1.3.md` — architect-settled
  decisions feeding into this ADR.
- `docs/process/senior-plans/P1.3.md` — implementation plan
  consuming this ADR.
- Implementation entry point: P1.3-3 schema module (interface-freeze
  shape) lands the Pydantic models declared in Decisions 1–6; the
  load-time filename-stem validator (Decision 8) lands in P1.3-4.
