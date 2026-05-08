# ADR-EXAMPLE: Pydantic for data shapes (not dataclasses or attrs)

> **This is a teaching example, not a real ADR.** The decision is
> real; the file is here in `adr-template/` so writers can see what
> a filled-in template looks like. Do not commit to `docs/decisions/`.

**Status:** Accepted — 2026-05-08
**Scope:** All data shapes in `src/orchestrator/` — Event, Room,
LLM types, future memory types, future agent config types. Excludes
internal control structs that don't cross module boundaries.

## Context

The project needs a way to define many small typed data shapes
(Event, Room, LLMRequest, ModelProfile, AgentLLMConfig, …). Three
mainstream Python options:

- `dataclasses` (stdlib, zero dependencies)
- `attrs` (third-party, mature, fast)
- `pydantic v2` (third-party, validation-first)

Hard requirements:

1. **Frozen / immutable.** Append-only event log + 12-principle stance
   against in-flight mutation means most shapes are frozen.
2. **Forbid extra fields.** Catching typos in dict-shaped metadata
   at construction is overlapping defense (Principle 11).
3. **Field-level validation.** Author format, confidence ranges,
   non-empty strings — these need to fail at construction, not at
   first use.
4. **YAML-driven config.** Three layers of YAML (providers, models,
   agents) need to load into typed objects with validation.
5. **Round-trip serialization.** Storing dicts in SQLite, reading
   back into typed objects, must be lossless.
6. **mypy strict compatibility.** Project-wide constraint.

## Decisions

### 1. Pydantic v2 for all data shapes that cross module boundaries

Every `class Event`, `class Room`, `class LLMRequest`, `class
ModelProfile`, etc. inherits `BaseModel` and sets
`model_config = ConfigDict(frozen=True, extra="forbid")`.

Why: Pydantic v2 is the only option that gives all six requirements
out of the box. `dataclasses` lacks built-in validation;
`attrs.frozen` gives immutability but validators are hand-rolled;
neither has YAML/JSON round-trip without bolting on a schema library.
Adding a third dep (Pydantic) is cheaper than reinventing validators
across ~15 shape definitions.

### 2. Plain `dataclass` for internal control structs

Module-internal dataclasses that don't cross public APIs (e.g., a
`RouteCandidate` that is only constructed inside the router and
returned in a tuple) use `@dataclass(frozen=True)`. No validation,
no serialization needed.

Why: Pydantic has a small per-instance overhead (~5-10μs construction)
that isn't free at hot-path scale. For internal-only structs, the
cost isn't justified by benefit. The boundary rule is simple: if it
appears in a public function signature, it's Pydantic; if it's a
helper return type, it's dataclass.

## Considered alternatives

### A. Plain `dataclasses` everywhere

Use stdlib `@dataclass(frozen=True)` and write `__post_init__`
validators by hand.

Rejected: ~15 shapes × 2-4 validators each = ~50 hand-rolled validator
methods, all needing tests, all subject to drift. Pydantic's declarative
validators (`Field(ge=0, le=1)`, `field_validator`) compress this to
zero hand-rolled code in most cases. The dep cost (one package) is
much smaller than the maintenance cost of bespoke validation.

### B. `attrs` with `attrs-strict` or `cattrs`

`attrs.frozen` + `attrs-strict` for runtime validation, `cattrs` for
serialization.

Rejected: stack of three packages to match what Pydantic gives
in one. `cattrs` has more flexible serialization than Pydantic, but
the project doesn't need that flexibility. Pydantic's ecosystem
maturity (FastAPI, ORM bindings, OpenAPI generation) is also better
positioned for P3's API surface.

### C. Pydantic v1

Earlier, more permissive validation API.

Rejected: v2 is the current line; v1 is in maintenance only. The
project starts now; no reason to take on a deprecation path for free.

## Consequences

**Easier:**

- Field-level validation is one-line declarative
  (`Field(ge=0, le=1)`) and the failure message is automatic.
- YAML loading is `Model.model_validate(yaml.safe_load(text))` — no
  hand-written from_dict / to_dict per shape.
- mypy gets accurate types from Pydantic without `# type: ignore`.
- Future API endpoints (P3) can reuse the same models for request
  validation.

**Harder:**

- One non-stdlib dependency. The project starts with zero deps; this
  is the first.
- Construction cost (~5-10μs per instance) is non-zero. At
  per-event hot path (potentially thousands of events per minute in a
  long research session), this adds up. Mitigated by decision 2 —
  hot-path internal structs stay dataclass.
- Pydantic v2 occasionally surfaces sharp edges around generics and
  `Annotated`. Caught by mypy strict, fixable, but costs reading time
  when contributors hit them.

**Neutral:**

- Pydantic's `model_config` syntax is the modern v2 form. Examples
  found online may use v1 syntax (`Config` inner class) — readers
  should check version when copying patterns.

## Reversibility

| Decision | 6-month reversal cost |
|---|---|
| Pydantic for all shapes | Medium — mechanical conversion to attrs/cattrs (~15 classes), but then ~50 hand-rolled validators to write. Realistic only if a hard performance issue surfaces. |
| Dataclass for internal structs | Trivial — promote to Pydantic later if a struct gets serialized. The conversion is mechanical: change base class, set model_config. |

## References

- `handoff.md` §11 (technology stack — Pydantic listed)
- `chat-history.md` §11 — discussion of the "Pydantic for YAML
  loading (not raw dict)" decision
- `src/orchestrator/core/event.py` — first concrete use, demonstrates
  per-type metadata schemas
