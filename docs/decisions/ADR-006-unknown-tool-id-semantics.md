# ADR-006: Unknown `tool_id` Semantics

**Status:** Accepted — 2026-05-20
**Scope:** Governs how `orchestrator.autonomy.scoring.score()` and its
caller `gate()` behave when an `Operation.tool_id` is not present in the
loaded tools registry. Out of scope: the case where a tool *is* in the
registry but its `reversibility` field is missing (ADR-005 Decision 2
settles that via `ToolMeta.reversibility = Field(default=0, …)`);
P1.3 Hard Guards' separate refusal semantics for known but
destructive operations.

## Context

The P1.2 autonomy gate scores an operation by looking up its tool's
`reversibility` value in the loaded `tools` registry (per ADR-005
Decision 2). Two semantically distinct things can go wrong at lookup
time, and the C2 interface freeze (`da65165`) did not yet specify how
to distinguish them:

1. **Tool in registry, `reversibility` field missing.** The author of
   `tools.yaml` added a tool entry but forgot or deferred the
   `reversibility` value. ADR-005 Decision 2 already settles this:
   `ToolMeta.reversibility = Field(default=0, …)` makes the absence
   default to 0 (conservative-low) at the Pydantic schema layer.
2. **Tool not in registry at all.** The caller supplied a `tool_id`
   the loader has no knowledge of — typo, stale config, agent
   referencing a tool that has been renamed or removed.

Case 1 is honest forgetfulness about a known tool; the default-0 path
is the conservative-low resolution. Case 2 is a structural mismatch
between the agent's knowledge of available tools and the registry's
ground truth — there is *no* defensible reversibility value to assign
because the operation itself is undefined relative to the registry.

C2's `score()` interface (`scoring.py:105-113`) elided the difference
with the single sentence *"If the tool is not in `tools`, returns 0
(conservative-low; ADR-005 Decision 2)"*. That sentence conflates the
two cases. Senior surfaced the conflation during P1.2-C3 planning;
architect ruled Q3=b — registry-miss raises, missing-field defaults to 0.

This ADR records the rule and its rationale. Two of the project's
twelve constitutional principles bear on the call:

- **Principle 4 — Structured uncertainty.** An empty or default value
  must not impersonate a well-defined value. Returning `0` for case 2
  tells downstream callers "this is a known irreversible operation"
  when the actual signal is "this operation is undefined relative to
  the registry". Two different epistemic states, one observable, is
  exactly the drift Principle 4 names.
- **Principle 9 — Terminology audit.** "Unknown tool" and
  "irreversible tool" are distinct semantics. Collapsing them into a
  single numeric output discards the distinction at the API surface;
  no downstream consumer can recover it. The P1.3 Hard Guards layer,
  agent runtime logging, and event-stream audit all need to see the
  distinction; the scorer is the only place it can be made.

The decision must support:

- Downstream callers (P1.3 Hard Guards, P1.3 agent runtime, event
  emission code in C4) can distinguish unknown-tool from irreversible-tool
  on the basis of structured exception data alone (not by parsing logs).
- The decision is enforced at the deepest schema/code layer that can
  enforce it, consistent with `feedback_schema_enforcement.md`.
- The audit trail (event log) records *what happened* in the
  registry-miss case — not silently substituting a fake score.

## Decisions

### 1. Registry-miss raises `UnknownToolError`

`score()` raises a new exception `UnknownToolError` when
`operation.tool_id not in tools`. The exception is defined in
`orchestrator.autonomy.scoring`. The default-0 path is reserved
exclusively for the case where the tool *is* in the registry but its
`reversibility` field is missing — that path is owned by Pydantic
schema (`ToolMeta.reversibility = Field(default=0, …)`), per ADR-005
Decision 2.

The two cases route differently because they encode different facts:

| Case | Fact | Resolution | Source of truth |
|---|---|---|---|
| Field missing on registered tool | "Tool exists, reversibility not declared" | Pydantic default 0 | `ToolMeta` schema |
| Tool absent from registry | "Operation undefined relative to registry" | `raise UnknownToolError` | `score()` body |

Schema enforces case 1; code enforces case 2 (no schema-layer
expression can catch "not in dict" at construction time). Both
enforcements live at the deepest layer that can express them.

### 2. `UnknownToolError` carries `tool_id` as a structured attribute

```python
class UnknownToolError(Exception):
    def __init__(self, tool_id: str) -> None:
        self.tool_id = tool_id
        super().__init__(f"tool_id {tool_id!r} not found in tools registry")
```

The `tool_id` attribute is the load-bearing surface. Log-based
diagnosis and downstream handling (event metadata, refusal reason)
read `e.tool_id` directly, not `str(e)`. This satisfies
`docs/architecture/test-coverage-standard.md` §4 (exception payload
contracts must be structured, not stringly-encoded).

The message string is informational only — its format is not part
of the contract and may change.

### 3. `gate()` propagates `UnknownToolError` unwrapped

`gate()` does not catch `UnknownToolError`. It does not convert the
exception into a default `AutonomyScore`. It does not return a
sentinel value. The exception propagates to the caller (P1.3 agent
runtime, eventually).

Catching the exception in `gate()` would re-introduce the
case-collapse this ADR exists to prevent: a downstream caller
receiving `AutonomyScore(score=0, tier=HARD_CONFIRM)` cannot
distinguish "the scorer determined this is a known irreversible
operation" from "the scorer didn't know the tool and gave up".
The whole-system invariant *every `AutonomyScore` corresponds to a
real registry lookup* is preserved by unwrapped propagation.

The C4 caller (event emission code) is responsible for deciding
whether to emit an `autonomy_decision` event with metadata noting
the unknown tool, or to route the error to a separate event type.
That call is not made here.

## Considered alternatives

### A. Default `0` for both cases

`score()` returns `0` whether the tool is in the registry with a
missing field, or absent entirely. This is what the C2 interface
freeze's docstring suggested.

Rejected on Principle 4 grounds. Downstream code receiving `score=0`
cannot distinguish "we looked up an irreversible tool" from "we
looked up nothing". The P1.3 Hard Guards layer wants the
distinction — its refusal rules differ for known-irreversible vs
unknown — and there is no place else to recover it. Conflating the
cases at the lowest layer means the higher layers must reconstruct
the distinction by parallel registry lookup, defeating the
abstraction.

### B. Raise `UnknownToolError` for both cases

`score()` raises whether the tool is absent or has a missing field.
Both paths force the caller to handle the exception explicitly.

Rejected on layering grounds. ADR-005 Decision 2 already specified
that the missing-field case is handled at the Pydantic schema layer
via `Field(default=0, …)` — schema-level enforcement of the
conservative-low default. Re-litigating that decision here would
mean (i) removing the `Field(default=0, …)` (changing C2's Pydantic
schema, which is frozen), or (ii) duplicating the logic in `score()`
to re-raise on a value that the schema already supplied as 0. Option
(i) violates the freeze; (ii) duplicates schema responsibility into
code.

The missing-field case is also semantically different: it IS a
known tool, just one whose author chose silence on reversibility.
Conservative-low (the default) is the right resolution. The
registry-miss case has no equivalent "author chose silence" framing
— there is no author of the missing tool entry.

### C. Per-call override flag (`allow_unknown_tools: bool = False`)

`score()` accepts a keyword arg that, when `True`, returns `0` on
registry-miss instead of raising. Calls that legitimately want the
old behavior (e.g., test setup, recovery scenarios) opt in.

Rejected. The flag re-creates the case-collapse this ADR rejects,
just gated by a parameter. Any code path that sets
`allow_unknown_tools=True` is back in case A's world, with the same
Principle 4 issue. Worse, the flag's existence invites future code
to default it to `True` "for compatibility" and lock in the bad
semantic. The flag is a re-introduction surface; the cleanest
defense is not having the surface.

If a test or recovery scenario needs the registry-miss → 0
behavior, the right tool is a test-local `tools` dict that
explicitly contains the tool with `reversibility=0` — making the
intent visible at the call site.

## Consequences

**Easier:**

- Downstream callers (P1.3 Hard Guards, P1.3 agent runtime) can
  distinguish unknown-tool from irreversible-tool in one line:
  `except UnknownToolError as e: …` vs `score == 0`.
- Audit and log diagnosis is structured: `e.tool_id` is the
  field, not a substring of a message format that may change.
- The autonomy module's API surface is honest — every returned
  `AutonomyScore` corresponds to a real registry lookup, and the
  exception type carries the structural failure.
- Test-coverage-standard §4 has a concrete instance in C3 (the
  `UnknownToolError` payload assertion); the abstract category
  acquires a canonical exemplar.

**Harder:**

- Callers of `gate()` and `score()` must wrap in `try/except` if
  the registry could plausibly be incomplete (which it can, during
  development or after a tool rename). Slightly more boilerplate
  than a silent default.
- The two-case rule (schema-default for one, raise for the other)
  is a stylistic split that a reader skimming `score()` might miss
  without the docstring. Mitigation: `score()` docstring's Raises
  section names `UnknownToolError` and references this ADR; the
  failure-mode table above lives in this ADR for future readers.
- The C4 event-emission caller has a new branch to design: what
  event (if any) records an `UnknownToolError`? That design is
  not made here; it is C4's call.

**Neutral:**

- C2's pre-existing `score()` docstring sentence *"If the tool is
  not in `tools`, returns 0 (conservative-low; ADR-005 Decision 2)"*
  is superseded by this ADR. The docstring updates as part of C3-3.
  Future readers of `da65165` will see the original sentence; this
  ADR is the load-bearing reconciliation.
- `UnknownToolError`'s location is `scoring.py`, not a new
  `autonomy/exceptions.py` module — the autonomy module currently
  has one exception; refactoring to a dedicated file is reserved
  for when P1.3 introduces ≥ 2 more (senior plan §5 push-back #1).

## Reversibility

| Decision | 6-month reversal cost |
|---|---|
| 1. Registry-miss raises `UnknownToolError` | Medium — reverting to default-0 invalidates the Principle 4 framing of this ADR and forces re-derivation. Any downstream consumer (P1.3 Hard Guards, C4 event emission) that branches on `except UnknownToolError` has to fall back to numeric-equality on score=0, which is the exact ambiguity the decision exists to remove. Reversal also requires re-litigating Principle 9 (term audit) for the next time a similar "empty vs absent" question lands. |
| 2. `tool_id` as structured attribute on the exception | Low — removing the attribute breaks log diagnosis and downstream metadata propagation; restoring it is a one-line code change but requires re-deploying anything that depended on it. |
| 3. `gate()` propagates unwrapped | Low — wrapping later is a one-line change in `gate()`. Reversal cost is the cost of the new event-type design C4 implies. |

## References

- ADR-001 (event store foundation) — establishes the EventType
  enum and the constitutional-test convention this ADR's
  `test-coverage-standard.md` §4 application reuses.
- ADR-005 (autonomy scoring) — Decision 2 (reversibility in
  `tools.yaml`, schema-level default), which this ADR refines by
  distinguishing the missing-field case from the registry-miss case.
- `docs/architecture/test-coverage-standard.md` §4 (exception
  payload contracts) — `UnknownToolError`'s structured `tool_id`
  attribute is the canonical instance.
- `docs/process/senior-planner.md` § "ADR drafting" — this ADR
  is the first non-bootstrap application of the senior-drafts-ADR
  rule.
- `docs/process/architect-briefs/P1.2-C3.md` § "Architect-settled
  design decisions" decision 3 — architect's framing of the
  Q3=b ruling that this ADR records.
- `docs/process/senior-plans/P1.2-C3.md` — task plan that lands
  the implementation; this ADR's acceptance gates the impl tasks
  (P1.2-C3-2 onward).
- Implementation entry point: P1.2-C3-2 (exception class) and
  P1.2-C3-3 (`score()` body update).
