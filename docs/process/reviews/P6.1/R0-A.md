---
task_id: P6.1
round: R0-A
kind: impl-stage-review
reviewer: architect-partner
impl_branch: origin/claude/P6.1-impl
impl_head: be13a1a
base: origin/main
verdict: clean
findings_count:
  red: 0
  yellow: 2
  green: 4
cross_refs:
  - docs/process/reviews/P6.1/plan-vs-impl.md
  - docs/process/reviews/P6.1/R0-B.md
  - docs/process/senior-plans/P6.1.md
  - docs/process/architect-briefs/P6.1.md
---

# P6.1 — R0-A impl-stage review (architect-partner lens)

## Lens + method

I authored the P6.1 brief, so my lens is closest to the **A-i scope intent**: did
the impl stay inside the ratified A-i + B-α boundary, is the B1 fix correct at the
prompt-injection trust boundary, and do the forcing functions actually force.

Reviewed `git diff origin/main...origin/claude/P6.1-impl` (`be13a1a`, two atoms
`A0`=`35c3ac7` + `B1`=`be13a1a`, 7 files). Stayed on `main` (shared worktree); ran
canonical gates + fail-on-revert in an isolated **detached worktree at `be13a1a`**
(`uv sync --all-extras`). Diff touches **exactly** the 7 planned files, no others.

---

## A0 — store-layer doc-drift + ADR-014/015 notes → **faithful** 🟢

Independently verified against the impl tree:

- **Docstring is factually correct now.** `get_room_events` reads `(timestamp ASC,
  rowid ASC)` + index `idx_events_room_ts`. Checked against the actual SQL
  (`event_store.py:374` `ORDER BY timestamp ASC, rowid ASC`), the real DDL
  (`:72-73` `CREATE INDEX idx_events_room_ts ON events(room_id, timestamp)`), and
  the schema comment (`:69-71`). All three brief-named drifts are fixed: `id`→`rowid`,
  the **nonexistent** `idx_events_room_ts_id` removed, and the false *"no sort step"*
  dropped. The new text is conservative — it does **not** re-assert sort-step
  presence/absence, exactly as the plan instructed.
- **A-i boundary intact.** No SQL / `ORDER BY` change, no index DDL change, no
  `Event`-model change, no `rowid` field; the derived-layer `(timestamp, id)` comments
  (`snapshot.py` / `decision_log.py` / `digest.py`) are untouched (confirmed by the
  7-file diff scope). The store's `(timestamp, rowid)` order is **described, not
  altered** — the junior did not "fix" it the wrong direction (the plan §5 risk).
- **ADR notes correct + minimal.** ADR-014 §2.5 and ADR-015 §4 each get one
  `[P6.1 A-i note]` line: precondition re-reviewed/still-holds, derived lex order
  stands, store order unchanged, migration **not** opened. Placement + wording match
  the plan.

## B1 — exclude untrusted `TOOL_FAILED` from excerpt + ADR-034/035 notes → **faithful** 🟢

- **Predicate widened exactly as specified.** `_render_snapshot_excerpt` excludes
  `e.type in {TOOL_RESULT, TOOL_FAILED}` under the **same** `external_result_ids`
  correlation; `_external_output_tool_result_call_ids` is byte-unchanged (keys on the
  **TOOL_CALL**'s `tool_name`, result-type-agnostic).
- **Production correlation holds (not just the synthetic test).** Both `TOOL_FAILED`
  append sites carry `call_id` via `ToolResultMeta` — `mcp/execution.py` (`content =
  "mcp_tool_failed: {reason}"`, attacker-authorable) and `tools/executor.py`
  (`"tool_failed: {reason}"`). So widening the type set is sufficient; no executor /
  name-set edit needed.
- **Not over-broad.** `TOOL_FAILED ∈ _EXCERPT_EVENT_TYPES` (`selection.py:86`) so it
  renders by default and is removed **only** when `call_id ∈ external_result_ids`.
  Trusted-local `read_file` failure renders (it matches none of
  `mcp__`/`_SUBPROCESS_TOOL_NAMES`/`_NETWORK_TOOL_NAMES`). B-β blanket exclusion
  correctly **rejected** — preserves the ADR-033 D2 turn-loop failure signal.
- **Docstring + ADR notes accurate.** The trust-framing paragraph and the ADR-034
  D3-iv / ADR-035 D3-iii one-line notes are factually right and correctly placed
  (after the excerpt-exclusion bullet, before the "Why excluding…" bullet).

## Fail-on-revert (contributing.md Q5) → **genuine** 🟢 (independently reproduced)

In my worktree I reverted the clause to `e.type == EventType.TOOL_RESULT` and ran the
new test:

```
FAILED tests/agents/test_selection.py::test_untrusted_tool_failed_excluded_trusted_local_rendered_p6b1
E  AssertionError: Untrusted mcp__ TOOL_FAILED must NOT appear in excerpt (P6.1 B1).
   ...Got excerpt: [tool_failed] agent:a: UNTRUSTED_TOOL_FAILED_MARKER_P6B1
                   [tool_failed] agent:a: TRUSTED_TOOL_FAILED_MARKER_P6B1
```

Assertion 1 fails on the un-fixed tree (the untrusted marker leaks); `git checkout` →
24/24 `test_selection.py` pass. This matches the B1 commit-message demonstration. The
forcing function forces.

## Constitutional zero-diff → **holds** 🟢

| Invariant | Status |
|---|---|
| `_execute_local_call` / autonomy gate / executor caps | ✅ not in diff |
| `_SUBPROCESS_TOOL_NAMES` / `_NETWORK_TOOL_NAMES` / `_external_output_tool_result_call_ids` | ✅ byte-unchanged |
| New `LLMPurpose` | ✅ none (exclusion keys on `tool_name`) |
| `Event`-model field / SQL `ORDER BY` / index DDL | ✅ none |

Agrees with senior plan-vs-impl + R0-B.

## Independent gates (worktree @ `be13a1a`, `uv sync --all-extras`)

- `ruff check .` → **All checks passed** ✅
- `mypy` → **Success, 0 issues / 305 source files** ✅
- `pytest tests/agents tests/core` (P6.1 blast radius) → **all pass, exit 0** ✅;
  `test_selection.py` → **24 passed** (incl. the new fail-on-revert test).
- Two caveats are **not** P6.1 defects → Y2 + the full-suite note below.

---

## Findings

### 🟡 Y1 — B1 residual attacker-byte path via `current_event` (overlaps R0-B B1-Y1; accepted, non-blocking)

I independently confirmed the mechanism: `pipeline/runner.py:180-194` picks
`result_events[-1]` (where `_RESULT_TYPES = {TOOL_RESULT, TOOL_FAILED, OBSERVATION}`)
as the next pass's `Message(role="user", content=...)` with **raw** content (no
untrusted-framing delimiter). So an untrusted `TOOL_FAILED` that is **last-in-pass**
still reaches the next pass via `current_event`; B1's excerpt-exclusion does not — and
is not meant to — cover that channel.

This is the **same** accepted limitation already inscribed in ADR-034 D3-iv (`:71-72`)
/ ADR-035 D3-iii, now extended to failures; plan §5 acknowledges it and the architect
ratified B-α with this side-effect noted. **Not a regression** — B1 strictly *shrinks*
the attack surface (removes the excerpt channel) and leaves the pre-existing
`current_event` channel unchanged.

**Added nuance beyond R0-B:** the "`current_event` has higher steering power" property
is **not specific to `TOOL_FAILED`** — an untrusted `TOOL_RESULT` that is last-in-pass
*also* becomes `current_event` today. So R0-B's security observation is really a
property of the whole untrusted-output→`current_event` carriage that **predates P6.1**.
If inscribed, it belongs as a broad note (or a tracked follow-on), **not** grown into a
P6.1 mechanism.

**Lean (architect routes):** δ-defer / α-one-line-note. No P6.1 rework. If you want it
named, the most P6.1 should do is a single clause on the ADR-034/035 B1 notes
("`current_event` carries the same bytes with higher steering power; broad hardening
deferred") — additive, optional.

### 🟡 Y2 — `ruff format` canonical gate is RED repo-wide (pre-existing; NOT P6.1; gate-hygiene) [R0-A only]

`ruff format --check .` reports **49 files would reformat** (exit 1), including the two
P6.1-touched files. `contributing.md:195` lists *"ruff format must pass"* as a canonical
gate, so the impl branch does not currently satisfy it.

**Attribution (decisive):** `origin/main`'s `selection.py` **and** `test_selection.py`
are **both already flagged pre-B1** (`git show origin/main:… | ruff format --check`
→ exit 1 for each). The lines ruff wants to change are **not** P6.1-edited:
- `test_selection.py:369` — a pre-existing list-comprehension; the P6.1 test is at
  `:624-720` and **is** format-clean.
- `selection.py:171` — the `e for e in snapshot` comprehension-split; **identical on
  `origin/main` pre-B1**. B1 edited `:176` (a different line), which ruff does not flag.

So **P6.1 introduces no new format violation on its own edited lines** — it inherits
pre-existing repo-wide format debt (47 of the 49 files are outside P6.1 entirely).
**Not a P6.1 defect, not blocking, and fixing it here would be scope-creep.** Surfacing
because (a) neither senior nor R0-B flagged it — both reported gates green (R0-B ran
`ruff check`, not `ruff format --check`); (b) the canonical gate is genuinely not green;
(c) candidate for a **separate format-hygiene slice** (cf. the P4.7 #95 prettier-hygiene
follow-on precedent). Architect awareness / routing call.

### Note (not a finding) — full-suite `pytest` hang is environmental

My full `pytest` run in the WSL2 `/mnt/d` worktree **hung at ~61%** (all dots, **zero
failures** up to the stall) on a `tests/plugins` posture-B sandbox harness subprocess
stuck in uninterruptible disk-sleep (`Ds`) — a `/mnt/d` filesystem-I/O stall, not a test
failure (4 stale prior-session pytest hangs corroborate the pattern). I killed it and
re-ran the P6.1 blast radius (`tests/agents` + `tests/core`) green. **R0-B's full run
independently reported 352 passed.** Full-suite green is corroborated; the hang is
environmental and outside P6.1's surface.

---

## Synthesis (for architect routing)

- **3-lens agreement:** A0 + B1 faithful, spine byte-frozen, no plan-external
  expansion. senior = `faithful` (0 blocking) · R0-B = `clean` (0🔴) · R0-A = `clean`
  (0🔴). No 🔴 from any lens.
- **Y1 (B1 `current_event` residual):** 2-way overlap (R0-B + R0-A). Accepted
  pre-existing limitation, non-blocking → lean δ-defer / α-one-line-note.
- **Y2 (`ruff format` gate-hygiene):** R0-A only. Pre-existing repo-wide, non-blocking
  → lean separate format-hygiene slice.
- **senior's plan-doc note** (ADR-014 filename `snapshot-derivation` vs real
  `snapshot-contract`): plan-doc-only, no impl defect — agree.

## Verdict: **clean**

The impl faithfully implements the ratified **A-i + B-α** scope; constitutional
invariants hold; the B1 forcing function is genuine (independently fail-on-revert
reproduced); P6.1's **own contribution** is gate-clean (`ruff check` + `mypy` + targeted
`pytest` + fail-on-revert all green). The two 🟡s are both **non-P6.1** — one accepted
pre-existing limitation, one pre-existing repo-wide gate-debt — surfaced for synthesis,
not rework.

**State note:** `.workflow/P6.1.yaml` remains `awaiting_senior_plan_vs_impl`; the
dual-lens stage (plan-vs-impl + R0-B + R0-A) is now complete → architect to synthesize
+ advance (state transition is architect-only; R0-A does not self-advance).
