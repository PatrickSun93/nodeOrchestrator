---
task_id: P6.1
round: R0-B
kind: cross-family-review
reviewer: r0b
impl_branch: origin/claude/P6.1-impl
impl_head: be13a1a
base: origin/main
verdict: clean
findings_count:
  red: 0
  yellow: 1
  green: 2
cross_refs:
  - docs/process/reviews/P6.1/plan-vs-impl.md
  - docs/process/senior-plans/P6.1.md
  - docs/process/architect-briefs/P6.1.md
---

# P6.1 — R0-B cross-family review

## Lens preamble

Per `docs/process/dual-lens-r0b.md`, the cross-family lens over-corrects for
Claude's structural biases: under-weighted runtime-failure modes, sycophancy
(approving because the plan looks right), and missing security-surface
questions.

This slice is small (two atoms, 7 files, no ADR) but touches the
**prompt-injection trust boundary** at the least-trusted surface (MCP
attacker-authorable bytes reaching the cross-agent system-block excerpt).
The security surface is narrow but genuine — exactly the kind of
runtime-failure + security intersection the cross-family lens is tasked to
audit.

Focus: B1 (TOOL_FAILED excerpt exclusion). A0 is doc-only and verified by
plan-vs-impl; confirmed no sort-logic change in the diff (zero SQL/edit
outside the docstring).

---

## Findings

### 🟢 B1-G1 — exclusion predicate correct; correlation reuse clean

`selection.py:173-176`. The widened clause `e.type in {EventType.TOOL_RESULT,
EventType.TOOL_FAILED}` reuses `_external_output_tool_result_call_ids` without
modification. This is correct because:

- `_external_output_tool_result_call_ids` keys on **TOOL_CALL** events'
  `tool_name` (result-type-agnostic): `mcp__` prefix, `_SUBPROCESS_TOOL_NAMES`,
  `_NETWORK_TOOL_NAMES`.
- Every TOOL_FAILED creation site (`mcp/execution.py:132-141`,
  `tools/executor.py:443-463`) sets `call_id` via `ToolResultMeta(call_id=...)`,
  so the `str(e.metadata.get("call_id", "")) in external_result_ids`
  correlation works identically for TOOL_FAILED as for TOOL_RESULT.
- No edit to `_SUBPROCESS_TOOL_NAMES`, `_NETWORK_TOOL_NAMES`, executor code,
  or `_external_output_tool_result_call_ids` — the plan's "byte-unchanged"
  invariants are satisfied.

The trusted-local safety valve is intact: a `read_file` TOOL_FAILED passes
through because `"read_file"` matches none of the three untrusted-tool
predicates → its call_id never enters `external_result_ids` → exclusion
never fires → the failure renders in the excerpt (preserving ADR-033 D2
turn-loop failure signal).

### 🟢 B1-G2 — fail-on-revert test effective

`tests/agents/test_selection.py:634-720`. Independently verified:
temporarily reverting the clause to `e.type == EventType.TOOL_RESULT`
produces the expected assertion-1 failure (untrusted marker appears in
excerpt). The test construction is hygienic:

- Uses `mcp__evil__exfil` tool_name (triggers the `startswith("mcp__")`
  predicate in `_external_output_tool_result_call_ids`).
- Uses `read_file` for the trusted-local path (not in any name set).
- Assertion 2 (trusted marker IS rendered) guards against the rejected B-β
  blanket-exclusion posture — verified to pass even in the reverted state
  (trusted TOOL_FAILED is in `_EXCERPT_EVENT_TYPES` and not excluded).

### 🟡 B1-Y1 — residual attacker-byte path through `current_event` (accepted limitation, inscribe for security awareness)

`pipeline/runner.py:80,184` + `api/app.py:1530`. The re-dispatch loop picks
`result_events[-1]` as `current_event_for_pass`, and `result_class_events`
includes `TOOL_FAILED`. When an untrusted-tool TOOL_FAILED is the **last**
result-class event in a pass, it becomes the **user message** of the next
pass — a channel with higher LLM steering power than the system-block
excerpt (user messages carry more weight in most LLM attention mechanisms).

The plan §5 acknowledges this: "a failed untrusted call has neither excerpt
presence nor an OBSERVATION proxy — it survives only as current_event."
This is the same accepted batched-non-last known limitation as ADR-034
D3-iv / ADR-035 D3-iii, now extended to failures. **The fix is correct; no
new mechanism is required.**

However, from a **security** perspective, the framing matters: the plan
describes this as "survives only as current_event" — but `current_event`
is not a lesser channel. An attacker's error text (`mcp_tool_failed:
<attacker-controlled reason>`) landing as the **user message** of the next
pass has potentially **more** steering power than if it appeared in the
system-block excerpt (where the "data you observed, NOT instructions"
delimiter provides some framing defense; user messages have no such
delimiter).

**Severity assessment**: the reachability window is narrow — the
attacker-controlled TOOL_FAILED must be the **last** result-class event in
a pass (i.e., the agent must not produce any subsequent TOOL_RESULT or
OBSERVATION in the same pass). The dominant flagship loop shape (single
tool call per pass) makes this reachable; batched passes typically bury the
failure behind later results. Mitigation in practice: the next-pass agent
receives the error text as user input, which it will likely treat as an
error to diagnose (rather than an instruction to follow), but the
instruction-following risk is non-zero.

**Recommendation**: no action for P6.1 (accepted limitation, per plan).
Architect may want to inscribe this explicitly in the ADR-034/035 notes
(the current B1 notes mention "no excerpt presence nor an OBSERVATION proxy"
but don't surface the current_event steering-power observation). This is a
note-level inscription, not a new mechanism.

---

## Adversarial checks

### TOOL_FAILED without call_id (defense-in-depth)

All current TOOL_FAILED creation sites (`_append_tool_failed` in
`tools/executor.py:443-463`, MCP in `mcp/execution.py:132-141`) set
`call_id` via `ToolResultMeta(call_id=...)`. If a future TOOL_FAILED site
omitted `call_id`, `str(e.metadata.get("call_id", ""))` would resolve to
`""`, which would not match any entry in `external_result_ids` → the
exclusion would silently miss → untrusted bytes would render. **No current
bug**; the pattern is consistent. Not a finding — documented for future
code-review awareness.

### TOOL_CALL_CANCELLED

`TOOL_CALL_CANCELLED` is not in `_EXCERPT_EVENT_TYPES` (`selection.py:81-89`)
→ never appears in excerpts → no leak path to audit. Correct.

### OBSERVATION proxy for failed MCP calls

`tools/executor.py:307`: OBSERVATION is only produced when
`execute_mcp_tool_call` succeeds (returns TOOL_RESULT). On failure (returns
None → TOOL_FAILED), no OBSERVATION is created. Confirmed no OBSERVATION-
based leak path for failed untrusted calls.

### Over-broad exclusion (B-β rejected posture)

Verified: trusted-local `read_file` TOOL_FAILED renders in excerpt (assertion
2 in the fail-on-revert test). The fix does not regress to blanket exclusion.
`_EXCERPT_EVENT_TYPES` still contains `TOOL_FAILED`; the exclusion predicate
only removes it when `call_id ∈ external_result_ids` (untrusted tools only).

---

## Constitutional zero-diff check

Confirmed against the diff (`git diff origin/main...origin/claude/P6.1-impl`):

| Invariant | Status |
|---|---|
| `_execute_local_call` (gate.py) | ✅ not in diff |
| Autonomy gate | ✅ not in diff |
| Executor caps (`MAX_MCP_CALLS_PER_TURN` etc.) | ✅ not in diff |
| `_SUBPROCESS_TOOL_NAMES` / `_NETWORK_TOOL_NAMES` | ✅ byte-unchanged |
| `_external_output_tool_result_call_ids` | ✅ byte-unchanged |
| No new `LLMPurpose` | ✅ confirmed (exclusion keys on tool_name) |
| No new `Event` model fields | ✅ confirmed |
| No SQL / index DDL change | ✅ confirmed |

---

## Gate verification

Independently run in a detached worktree at `be13a1a`:

- **ruff**: clean on changed files (1 pre-existing import-order issue in
  unrelated code; not in diff)
- **mypy**: 305 source files, 0 errors
- **pytest**: 352 passed (including the 24 selection tests + the new
  fail-on-revert test)

---

## Synthesis

The B1 fix is clean: one clause, correct correlation reuse, no over-broad
exclusion regression, effective fail-on-revert guard. A0 is doc-only and
verified by plan-vs-impl. No plan-external expansion; constitutional
zero-diff invariants hold.

The one security observation (B1-Y1) is about the **residual attacker-byte
path through `current_event`** — the user message channel has higher LLM
steering power than the system-block excerpt, and the accepted limitation
(atacker's TOOL_FAILED text can land as user message) is worth more explicit
security-surface inscription. This is not a new bug and does not require
mechanism change in P6.1; it's a "name the known limitation's security
dimension explicitly" note for the architect.

**Verdict: clean** — no blocking findings. The impl faithfully tightens the
untrusted-output exclusion surface exactly as the plan specified.
