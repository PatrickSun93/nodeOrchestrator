---
task_id: P6.1
kind: plan-vs-impl
reviewer: senior
plan: docs/process/senior-plans/P6.1.md
impl_branch: origin/claude/P6.1-impl
impl_head: be13a1a
base: origin/main
verdict: clean
blocking_findings: 0
non_blocking_notes: 1
---

# P6.1 — plan-vs-impl review (senior)

Reviewed `git diff origin/main...origin/claude/P6.1-impl` (`be13a1a`), two
atomic commits `A0` (`35c3ac7`) + `B1` (`be13a1a`), against the senior plan
`docs/process/senior-plans/P6.1.md`. **Verdict: faithful.** Each atom implements
exactly its planned scope; no plan-external expansion; constitutional zero-diff
invariants hold; the B1 fail-on-revert forcing function is satisfied and
demonstrated.

Diff touches **exactly** the seven planned files and no others:
`ADR-014`, `ADR-015`, `ADR-034`, `ADR-035`, `core/event_store.py`,
`agents/selection.py`, `tests/agents/test_selection.py`.

---

## A0 — store-layer doc-drift fix + ADR-014/015 precondition notes

**Faithful.** Plan §P6.1-A0 acceptance criteria all met, verified against
reality on the impl branch:

- **Docstring target correct.** `get_room_events` now reads `(timestamp ASC,
  rowid ASC)` and names index `idx_events_room_ts`. Verified against the actual
  SQL on the impl branch: `ORDER BY timestamp ASC, rowid ASC`, and the real DDL
  `CREATE INDEX idx_events_room_ts ON events(room_id, timestamp)`
  (`event_store.py:69-73`). The nonexistent `idx_events_room_ts_id` and the
  spurious `id`-as-tiebreak claim are both removed. The corrected text matches
  the canonical schema comment as the plan required.
- **Right disambiguation direction.** The plan's load-bearing reviewer note (§5)
  warned a junior could "fix" this the wrong way — changing the SQL or keeping
  `id`. Neither happened: **no SQL change, no index DDL change, no Event-model
  change** (confirmed by file list + diff). The store's `(timestamp, rowid)`
  insertion-order is described, not altered.
- **ADR notes correct and minimal.** ADR-014 §2.5 and ADR-015 §4 each receive a
  single `[P6.1 A-i note]` line stating the precondition was re-reviewed and
  still holds, the derived `(timestamp, id)` lex order stands, the store order is
  unchanged, and the rowid-on-Event migration is **not** opened here — exactly
  the plan's wording.
- **Out-of-scope respected.** No derived-layer comment (`snapshot.py`,
  `decision_log.py`, `digest.py`) is touched — confirmed by the file list.

## B1 — exclude untrusted `TOOL_FAILED` from excerpt + ADR-034/035 notes

**Faithful.** Plan §P6.1-B1 acceptance criteria all met:

- **Predicate widened exactly as specified.** `_render_snapshot_excerpt` now
  excludes `e.type in {EventType.TOOL_RESULT, EventType.TOOL_FAILED}` under the
  same `external_result_ids` correlation. One-clause symmetric change; nothing
  else in the predicate moved.
- **Correlation source byte-unchanged.** `_external_output_tool_result_call_ids`
  is **not** in the diff — it still keys on the `TOOL_CALL`'s `tool_name`
  (`mcp__` prefix ∪ `_SUBPROCESS_TOOL_NAMES` ∪ `_NETWORK_TOOL_NAMES`),
  result-type-agnostic. Because `TOOL_FAILED` carries `call_id` via
  `ToolResultMeta`, widening the type set is sufficient — no edit to
  `_SUBPROCESS_TOOL_NAMES`, `_NETWORK_TOOL_NAMES`, or any executor code, as
  required.
- **Docstring updated.** The trust-framing paragraph now states untrusted-tool
  `TOOL_FAILED` is excluded on the same basis while trusted-local `TOOL_FAILED`
  stays rendered (with the ADR-033 D2 failure-signal rationale).
- **Fail-on-revert test genuine.** The new
  `test_untrusted_tool_failed_excluded_trusted_local_rendered_p6b1` is a true
  fail-on-revert: assertion 1 uses an `mcp__` `TOOL_CALL` whose `call_id` lands
  in `external_result_ids`, so its `TOOL_FAILED` marker is excluded only because
  of the widened predicate — reverting to `TOOL_RESULT`-only puts the marker back
  in the excerpt and the assertion fails. Assertion 2 uses a trusted `read_file`
  failure (not in the set, and `TOOL_FAILED ∈ _EXCERPT_EVENT_TYPES`) and asserts
  the marker **renders**, guarding the rejected B-β blanket-exclusion posture.
  The B1 commit message **demonstrates** the revert producing the assertion-1
  failure (contributing.md Q5 satisfied).
- **ADR notes correct.** ADR-034 D3-iv and ADR-035 D3-iii each receive a single
  `[P6.1 B1 note]` line that the exclusion set covers both `TOOL_RESULT` and
  `TOOL_FAILED`, acknowledging in passing the same accepted batched-non-last
  known-limitation extended to failures (no new mechanism) — matching plan §5's
  inscribe-don't-expand instruction.

## Plan-external expansion check

**None.** Confirmed absent across the whole diff:
- No `_execute_local_call` / autonomy-gate / executor-cap edit (byte-frozen).
- No new `LLMPurpose` (exclusion keys on `tool_name`, as the existing filter does).
- No SQL `ORDER BY` change, no index DDL, no `rowid`/`seq` added to `Event`.
- No derived-layer comment touched; no second A-surface (none of the 9 sort
  sites, no A-ii/A-iii); no OBSERVATION/`current_event` carrier change.
- Atoms committed separately with atom-named subjects (RC-17 respected); ADR
  notes ride in the same commit as their change (inscribe-with-change).

## Non-blocking note (1)

- **Plan ADR-014 filename typo — not an impl defect.** The plan refers to
  `docs/decisions/ADR-014-snapshot-derivation.md` (§A0 "Where", line 82); the
  real file is `docs/decisions/ADR-014-snapshot-contract.md`. The impl correctly
  edited the existing file, so there is no impl deviation — this is a stray name
  in the plan doc only. Flagging so a later reader doesn't mis-cite it; no action
  required for this slice.

---

**Disposition:** faithful — ready for the dual-lens impl-stage review (R0-A +
cross-family R0-B, per `requires_cross_family_review: true`). Senior does not
self-advance state.
