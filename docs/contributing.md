# Contributing

## PR template (mandatory)

Every PR description must answer these two questions explicitly. PRs that
skip them get bounced back. The questions enforce the project's two
load-bearing architecture rules.

### Q1. Does this PR contain LLM calls? If yes, why couldn't each one be done in code?

The most important architecture rule: decision paths go in code, LLMs
generate content. See `handoff.md` §3.1 and `chat-history.md` §8.

A "decision path" is anything that routes, gates, scores, ranks, or selects:

- "Should this agent speak now?"
- "What autonomy level applies to this operation?"
- "Which skills should we load for this event?"
- "Does this hypothesis qualify for promotion to verified knowledge?"
- "What's in the agent's context window for this turn?"

These are tempting to delegate to LLMs ("just ask Claude"). The rule says:
**don't**. Build a data structure and a pure function. The function is testable,
auditable, free, deterministic, and survives LLM API outages. Per Principle 11,
LLM-judgment without ground truth is drift in disguise.

If your PR adds an LLM call, the description must list the call site and
explain why no code-only path achieves the same outcome. Reviewers should
challenge each one.

### Q2. Do all decision functions return a `decision_trace`?

Any function that makes a routing/gating/scoring/selection decision must
return enough information to explain *why* that decision was reached, not
just *what* the decision was.

```python
# bad
def determine_autonomy_level(op) -> AutonomyLevel: ...

# good
def determine_autonomy_level(op) -> tuple[AutonomyLevel, DecisionTrace]: ...
```

`DecisionTrace` should include: the rule(s) matched, the score(s) computed,
the inputs considered, and the precedence order applied. The principle is
the same as compiler error messages — saying "no" without saying "why" is
useless.

This applies even to "obviously correct" decisions. If the code is correct,
the trace is cheap. If the code becomes wrong later, the trace is the
fastest path to the bug.

### Q3. For schema-changing PRs: did you scan all five reference surfaces?

When the PR changes a schema — a data field, validator, type, structure,
required vs optional, the shape of a config block — every reference must
be updated. Five surfaces to scan:

1. **Main code** — `src/orchestrator/**/*.py` (types, protocol, router,
   loader, providers, …).
2. **Example YAML** — `config/**/*.yaml.example`.
3. **Architecture Decision Records** — `docs/decisions/*.md`. Especially
   the ADR that established the schema; if its decision text or
   reversibility row references the old shape, fix it.
4. **Architecture docs** — `docs/architecture/*.md` (`event-model.md`,
   `llm-layer.md`, …).
5. **Project narrative** — `handoff.md` and `chat-history.md` at the
   repo root.
   - When modifying `docs/architecture/test-coverage-standard.md`:
     grep-verify every P1.x example file and test name still exists.

If a schema change appears in code but not in the example YAML, or in
an ADR but not in `handoff.md`, that is **doc-spec drift**: the schema's
mentioned-in-code definition and its mentioned-in-docs definition
silently diverge, and future readers can't tell which one is canonical.

In the followup-commit tracking table, a `Status: Done` row is not
legitimately checked until all five surfaces are consistent. If a
surface is intentionally left at the old shape (e.g. an ADR being
superseded keeps its text), call that out explicitly in the row's
status field, not silently.

- **RC-1 pre-edit grep sub-rule**: For each surface in the scan, grep
  the file for pre-edit values that the schema change rendered obsolete
  and confirm they are absent. A `Status: Done` row is not legitimately
  checked until this grep is clean. Reverse drift — re-stating a
  position the architect already ruled out — is harder to catch than an
  initial error and must be guarded against explicitly.

**README.md is intentionally excluded from the 5-surface scan.** README
is the project's entry point for new users — intro, motivation,
quick-start. It should not contain spec-level detail (data structures,
schema fields, configuration syntax). Spec details that leak into
README are README's own bug, not a 5-surface failure. If you find
yourself wanting to add schema detail to README, the right move is a
link to the relevant doc, not duplication.

### Layer-crossing field plumbing

The 5-surface scan above checks **static** drift — surfaces that
describe the same schema getting out of sync. There is a second
shape of drift the static scan does NOT catch: **fields added in
one type but not plumbed through the signatures that connect their
producer to their consumer.**

Example from this project: ``RouteResult.model_id_requested`` was
added to the router's return type, but ``Protocol.call``'s signature
did not gain a ``model_id_requested`` parameter. Result: the field
existed at the router boundary but couldn't reach the provider
boundary, and the provider's ``LLMResponse`` filled
``model_id_requested`` from ``model.id`` (silently swallowing
fallback signal).

When a schema change adds a field meant to flow across module
boundaries:

- Identify the **source** (where the field is first populated).
- Identify the **sink** (where the field is finally read or persisted).
- Trace every signature the field traverses between source and sink.
- Each intermediate signature must accept and pass the field.
- A unit test must verify the data flow with the source and sink
  values **distinct** — it is the only way to catch the
  ``source = sink`` shortcut that hides the missing plumbing.

Type checking does NOT catch this on its own: if every intermediate
function happens to derive a sensible-looking value from data it
already has, the chain compiles cleanly while leaking the original
signal. The data-flow test is the catch.

### Q4. Test coverage standard compliance

Did you check the change against
`docs/architecture/test-coverage-standard.md` (all 6 categories)?

For each applicable category, confirm compliance. For each
non-applicable category, mark N/A with one-line reason in the
commit message under "Coverage standard compliance:".

Required when ANY of the following apply (matches
`docs/architecture/test-coverage-standard.md` §1-§6 "When it applies"):

- §1: A field is computed in one module and consumed in another
- §2: New shared mutable state accessed from async code
- §3: New subprocess, file handle, or network connection used
  outside a context manager
- §4: A new custom exception class is raised
- §5: A validator constrains a list/sequence field
- §6: A new Pydantic model is added to `src/`

### Q5. Does each new/changed test actually fail on the defect it guards?

A test is only a guard if it can fail when the thing it names is broken.
For any test added or changed to cover a specific defect/invariant,
confirm it is **discriminating** — that you saw (or can reason precisely
that) it fails when the guarded behavior is wrong, not just that it passes
today.

This is the **"test that can't fail its own bug"** anti-pattern, graduated
after three instances (RC-25): P1.6.5 vacuous tag-rollback atomicity test
(injected the failure before the registration it claimed to guard), P2.1
vacuous promotion-atomicity test (same shape), P2.2 non-discriminating
determinism test (asserted a property that held by construction regardless
of scan order, so it could not catch a scan-order regression). All three
passed green while guarding nothing.

Cheapest check: for a rollback/error-path test, the failure must be
injected *after* the state the test asserts was rolled back exists; for a
"property X holds under condition Y" test, seed a case where X would be
violated if the code were wrong and assert the discriminating outcome
(not a by-construction tautology).

## Architecture decisions (ADRs)

Decisions that change the shape of the system live in `docs/decisions/`
as `ADR-NNN-slug.md`. Each ADR is short and structured:

- **Context** — what problem, what constraints, what was considered
- **Decision** — what we chose
- **Consequences** — what becomes easier and what becomes harder
- **Reversibility** — how expensive is it to undo this in 6 months

Add an ADR when:

- Adding a new event type
- Changing autonomy scoring weights
- Adding a new agent role
- Changing how memory promotion works
- Touching anything in `handoff.md` §3 (core architecture)

You don't need an ADR for a typical feature PR.

## Code style

- `ruff check` and `ruff format` must pass.
- `mypy --strict` must pass.
- `pytest` must pass.
- Tests live next to the module they cover, mirrored under `tests/`.
- Public functions get docstrings only when the *why* is non-obvious. Type
  hints carry the *what*.

The `api/` package (from P3.2) depends on the **`[api]` optional extra**
(`fastapi`, `uvicorn`). Install it before running the gates, or `mypy`/`pytest`
break on `api/` with import-not-found: set up with `uv sync --all-extras` (or run
the gate per-command as `uv run --extra api mypy --strict` / `uv run --extra api
pytest`). There is no CI workflow — the gates are these local commands.
`plugins/` is not in the canonical mypy scope (bundles are loaded by path at runtime
and may contain same-named `tools_impl.py` files; they are excluded from the global
`[tool.mypy] files` setting in `pyproject.toml`).

## Frontend gate (`ui/`)

The frontend has its **own separate gate** (node/TS — the Python ruff/mypy/pytest do not
apply to `ui/`). Run it from inside `ui/` after `nvm use` + `npm install`:

```bash
cd ui
nvm use           # ensure node 24 per .nvmrc
npm run gate      # lint + format:check + typecheck + test + codegen:check
```

The **codegen-freshness** step (`npm run codegen:check`) re-generates `src/api/schema.ts`
from the committed `openapi.json` and fails if the committed file is stale. When the
HTTP contract changes, run `npm run codegen` in `ui/` and commit the updated `schema.ts`.

### Frontend PR checklist

For any PR touching `ui/`:

- [ ] **View+intent only?** No client-side state-machine/routing/autonomy decision logic.
- [ ] **Binds-API-only?** No `fetch`/`WebSocket` outside `src/api/`; no DB/fs/sqlite dep
  in `package.json`; no `orchestrator`-path import.
- [ ] **`ui_strings` no-raw-vocab?** Every `EventType`/`RoomType`/state value shown in the
  UI is mapped through `uiStrings.ts`; no raw wire token leaks to the rendered DOM.
- [ ] **Partial-turn handled?** `IntentError`/`StreamError stage:"turn"` → reconcile via
  replay, Composer does **not** re-post.
- [ ] **Gate green?** `npm run gate` passes (lint + format + typecheck + vitest +
  codegen-freshness).

## Commit messages

Imperative mood, focus on the why. The diff already shows the what.

Bad: `update event store`
Good: `enforce append-only via TRIGGER, not convention`

## What goes in `src/`, what goes in `config/`

- `src/` — code that runs.
- `config/` — data the code consumes (agent YAMLs, autonomy rules,
  UI strings, state machine definitions). Editable without code review
  in the same way runtime code is.

If you find yourself hardcoding strings the user will see, route them
through `config/ui_strings/` instead.
