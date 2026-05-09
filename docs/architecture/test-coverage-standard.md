# Test Coverage Standard

The five categories below are the minimum required for any module that
touches cross-module data flow, shared mutable state, subprocesses, custom
exceptions, or collection-validating boundary checks. A test suite that
omits a category is incomplete; the reviewer will flag the gap.

Each category has a concrete P1.1 example. The test author should read
the referenced test as a worked example before writing their own.

---

## 1. Cross-module integration

**When it applies**: data originates in one module and is consumed in a
different module (crosses a `src/orchestrator/` subpackage boundary).

**Acceptance criterion**: at least one test constructs distinct source
and sink values and asserts they are *different*. The `source == sink`
case is the bug; the type system will not catch it because both are the
same type.

**P1.1 example**: `tests/llm/test_mock_provider.py`,
`test_constitution_model_id_requested_flows_distinct_from_used` — the
router sets `model_id_requested` on `RouteResult`; the provider reads it
from `LLMRequest` and must forward it to `LLMResponse`. A test that used
the same value for both would have passed with the round-3 data-flow bug
present.

**Quantifiable measure**: source value ≠ sink value in the assertion.
One test per cross-module data path.

---

## 2. Concurrency safety

**When it applies**: any shared mutable state accessed from an async
context, including provider-internal counters, caches, and health-check
state.

**Acceptance criterion**: at least one test fires N concurrent calls
(where N ≥ the number of distinct expected outcomes) against a single
instance and asserts all expected outcomes are present.

**P1.1 example**: `tests/llm/test_mock_provider.py`,
`test_constitution_concurrent_calls_advance_cursor_atomically` — 20
concurrent calls against one instance, all distinct responses present.

**Quantifiable measure**: N concurrent calls via `asyncio.gather`, all
N distinct response contents present (no duplicates, no lost values).

---

## 3. Cleanup / cancellation paths

**When it applies**: any code that spawns a subprocess, opens a file
handle, or establishes a network connection outside a context manager.

**Acceptance criterion**: two tests minimum. (a) A cleanup failure
(e.g., `OSError` on `Process.kill()`) does not mask the original error.
(b) An outer `asyncio.CancelledError` propagates to the caller and the
underlying resource is released.

**P1.1 example**: `tests/llm/test_claude_code_cli_provider.py`,
`test_kill_failure_does_not_mask_original_error` and
`test_outer_cancellation_kills_subprocess` — OSError on kill
does not mask the original timeout; CancelledError propagates
unwrapped and subprocess is killed.

**Quantifiable measure**: (a) Original exception class present in the
raised error's chain or message. (b) `CancelledError` propagates unwrapped;
resource's closed/killed flag is True.

---

## 4. Exception payload assertions

**When it applies**: every custom exception class defined in `src/`.

**Acceptance criterion**: at least one test per exception class asserts
that the exception carries enough structured data to locate the root
cause from logs alone. For configuration errors, this means the offending
field name *and* the file identifier. For decision errors, this means the
decision trace has the expected length and each entry has distinct,
non-empty reason fields.

**P1.1 example**: `tests/llm/test_config_loader.py`,
`test_unknown_type_raises_with_violations` — asserts `ConfigError.violations`
contains the bad value and the field name.

**Quantifiable measure**: Exception message or structured attribute
contains (a) the field name or parameter that failed, and (b) the file or
model identifier where the failure was detected. For decision traces:
`len(trace) == expected_count` with all reasons distinct and non-empty.

---

## 5. Boundary validators — multi-position

**When it applies**: any validator that checks a collection for the
presence or absence of a forbidden value (e.g., "default model must not
appear in fallback chain").

**Acceptance criterion**: at least two tests place the forbidden value
at different positions in the collection and assert the validator catches
both. A single-position test (e.g., position 0 only) can pass against an
`[0] ==` check that a position-1 value would escape.

**P1.1 example**: `tests/llm/test_config_loader.py`,
`test_default_at_non_zero_index_in_chain_raises` and
`test_default_at_last_index_in_chain_raises` — default model at
position 1 and position last, both caught.

**Quantifiable measure**: Tests cover the forbidden value at index 0,
index non-zero, and index last (or -1). All expect the same error class.

---

## 6. Schema invariants

**When it applies**: every Pydantic model in `src/` that is user-facing
or crosses module boundaries.

**Acceptance criterion**: each model needs at minimum:

1. One test that mutation raises (`frozen=True`)
2. One test that unknown field raises (`extra="forbid"`)
3. One test per constrained `Field`, at the just-out-of-range value
4. One test per `Literal` field, with a non-allowed value

**P1.1 example**: none yet — `types.py` models lack direct schema tests;
this is a known gap. P1.2 round 1 will land `tests/llm/test_types.py`
as the first canonical example.

**Quantifiable measure**: for model *M* with *N* constrained fields and
*L* Literal fields, expect ≥ 2 + N + L tests in `test_<module>_schema.py`.

---

## PR Self-Check

Before committing, verify each applicable category from the standard:

- [ ] §1 Cross-module integration — source ≠ sink test
- [ ] §2 Concurrency safety — N concurrent calls, all distinct
- [ ] §3 Cleanup / cancellation — kill failure + cancellation test
- [ ] §4 Exception payloads — field + file in message/violations
- [ ] §5 Boundary validators — multi-position test
- [ ] §6 Schema invariants — frozen + extra + Field + Literal tests

Mark each applicable category checked or N/A with one-line reason in
the commit message under "Coverage standard compliance:".
