---
task_id: P6.3
kind: R0-A
reviewer: architect-partner
state_at_write: awaiting_R0_A
cycle: 1
impl_ref: origin/claude/P6.3-impl @ 50f9428
plan_ref: docs/process/senior-plans/P6.3.md (no ADR; G1 + H1)
brief_ref: docs/process/architect-briefs/P6.3.md
verdict: clean
---

# P6.3 R0-A (impl) — verdict: **clean**

Independent second lens (I authored the P6.3 brief) over `origin/main...origin/claude/P6.3-impl`
(`ffab366` G1, `50f9428` H1) against the senior plan + the brief ratification. Read-only from `main`
(no checkout); gates run in an isolated detached worktree (`uv sync --all-extras`). Both atoms are
faithful, each ships its discriminating fail-on-revert test, the cited contracts (ADR-020 D2 /
ADR-031 D5) are preserved, the spine and `LLMPurpose` surfaces are untouched, and the full suite is
green. **I converge with the senior's plan-vs-impl (clean)** and add two things its scope didn't
cover: a **full-suite** pytest run and a **repo-wide `ruff format --check`** (one pre-existing,
out-of-scope hygiene observation, below).

## Scope containment — exactly the 4 planned files

```
src/orchestrator/memory/entity.py
src/orchestrator/plugins/fetch.py
tests/memory/test_entity.py
tests/plugins/test_fetch.py
```

`git diff --name-only` = these four only. No `.workflow/`, no `docs/`, no stray junior self-advance
commit, no opportunistic edits. Two independent atoms, two commits, the plan's decomposition exactly.
Spine grep over the diff (`_execute_local_call` / `emit_gate_decision` / `decide_tier` / `COUNTDOWN` /
`run_pipeline` / `LLMPurpose` / `select_model_and_provider`) = **zero hits** — no spine touch, no new
purpose, no ADR amendment, no schema migration.

## G1 — preserve `created_at` on upsert-update (`memory/entity.py`) — conforms to ADR-020 D2

ADR-020 D2 inscribes a preference re-declaration as "**updates that row's value in place**" — it pins
the value and the one-row-per-`(user_id, key, scope)` identity, says **nothing** about mutating
`created_at`, and the data model it carries has **no `updated_at`** (I re-confirmed: `grep updated_at
src/ tests/` = zero). Overwriting create-time on every upsert was the deviation; preserving it makes
the code match the inscribed decision. The impl:

- captures `existing_created_at = TimestampMs(row["created_at"])` at the scan-loop `break`;
- drops `created_at` from the `UPDATE … SET` (G-lean, not the rejected no-op-rewrite G-alt):
  `UPDATE entity SET attributes = ?, evidence = ? WHERE id = ?`;
- returns `created_at=existing_created_at` (was `=ts`); INSERT branch + `ts = now_ms()` untouched;
- inscribes the invariant: code comment `# created_at is immutable across upserts … (ADR-020 D2)` +
  docstring now "… in place; `created_at` is preserved (only value/evidence mutate)".

The guard reads `if existing_id is not None and existing_created_at is not None:` (the plan showed
only the `existing_id` guard). This is **mypy strict** narrowing `existing_created_at: TimestampMs |
None` before it is passed as `created_at=`; the two are set together at the same `break`, so the added
clause never diverges — logically identical, no behavioral expansion, and it does not falsy-trip on a
`created_at == 0` row (the check is `is not None`). Correct and minimal. (Senior flagged the same as a
non-blocking micro-deviation; I concur.)

**Fail-on-revert (executed, not just read).** Reverted the fix to its buggy form in the throwaway
worktree (`UPDATE … created_at = ?` binding `ts` + `created_at=ts` return) and ran
`test_upsert_preserves_created_at` → **FAILED** as designed:
`assert prefs[0].created_at == 1000` → `AssertionError: assert 2000 == 1000` (the persisted row's
create-time reset to t2). The test's paired asserts (persisted row **and** the 2nd call's returned
`Entity.created_at`) are the discriminating revert-catchers; the pre-existing
`test_upsert_same_key_yields_one_row` is necessary-but-not-discriminating (passes both sides). Fix
restored, retested green.

## H1 — stream-to-temp + incremental hash + cap-during-stream (`plugins/fetch.py`) — preserves ADR-031 D5 (cross-family lens)

ADR-031 D5 is the governing contract (not ADR-038, whose §Scope explicitly excludes the fetch
mechanism). Its security property is the **digest-before-extract ordering**: sha256 of the **complete
compressed bytes** computed and verified **before any extraction**, with atomic staging + cleanup
(`fetched_plugins_dir` never touched by a failed fetch). The impl preserves all of it:

1. `_stream_to_file` streams the body into the **already-created** `tmp_bundle`, updating a running
   `hashlib.sha256` and a running `total` per chunk, and **aborts mid-stream** the instant
   `total > _MAX_BUNDLE_BYTES` (`FetchError("… capped during stream")`). The cap moved from post-hoc
   on a materialized buffer to **enforced during the download** — strictly stronger, and the OOM
   vector (unbounded `response.content`) is gone. Boundary semantics unchanged: strict `>` (exactly
   50 MB still allowed), matching the old check — no off-by-one.
2. Order preserved: `actual_digest = _stream_to_file(...)` → `_parse_digest` → mismatch raises →
   **then** `bundle_bytes = tmp_bundle.read_bytes()` (DP-3(a): now verified **and** ≤ cap, so the
   read-back is bounded-safe) → `_detect_and_extract`. No extracted byte hits disk before the digest
   passes. Incremental hash over the streamed chunks == a full-bytes hash (ft10 proves it on a 16-byte
   multi-chunk body).
3. `except FetchError: raise` shields the "too large"/status errors from the generic
   `download failed: …` re-wrap, so the substring survives (ft6 + ft9 both `match="too large"`).
   Default-client path keeps `verify=True` + `_FETCH_TIMEOUT_S = 30.0`; a caller-supplied client keeps
   its own timeout. `_download` and `_compute_sha256` are fully removed — `git grep` over `src`/`tests`
   = **zero** remaining callers (no dangling ref; mypy/ruff would have caught one).
4. Cleanup unchanged: the `except`/`finally` still `rmtree` `tmp_staging` + `unlink` `tmp_bundle`; a
   stream aborted mid-way leaves only a partial temp file that the existing cleanup removes —
   `fetched_plugins_dir` untouched on failure (ft7 holds). The ADR-038 admission-proof path
   (`app.py:1777`) is not in the diff.

**Fail-on-revert (executed, not just read).** Reverted `_stream_to_file._consume` to a buffer-all
(`response.read()` then post-hoc cap) and ran `test_ft9_oversized_bundle_capped_during_stream_bounded`
→ **FAILED** as designed: `assert pulled["bytes"] <= _MAX_BUNDLE_BYTES + chunk` →
`assert 73400320 <= (52428800 + 1048576)` — i.e. the full `total_n` (cap + 20 MB) was pulled. This is
the same discriminator the senior independently hit; it confirms ft9 guards the **bounded-consumption
(OOM)** property, not merely "rejects oversized" (that is ft6's necessary-but-not-discriminating role —
note the `match="too large"` assert still passed under the revert, exactly because the post-hoc cap
still raises). Fix restored, retested green.

## Gates (isolated detached worktree @ `50f9428`, `uv sync --all-extras`)

- **ruff check** — `All checks passed!` (`src` + `tests`).
- **mypy --strict** — `Success: no issues found in 310 source files` (full `files=[src,tests]` scope,
  broader than the senior's 2-file run).
- **pytest (full suite)** — **2519 passed**, 1 warning (a pre-existing `StarletteDeprecationWarning`
  on `fastapi.testclient`, unrelated to P6.3). The three new tests
  (`test_upsert_preserves_created_at`, `test_ft9_…_bounded`, `test_ft10_…_streamed_stages`) collect
  and pass by node id. The full run (vs the senior's 40-test touched-suite run) confirms no
  cross-suite regression.
- **ruff format --check** — see the one observation below.

## Non-blocking observations (no architect decision required)

1. **Repo-wide `ruff format --check` is RED on 51 PRE-EXISTING files — not a P6.3 regression.**
   The dispatch asked me to run `ruff format --check`; at repo scope it reports 51 files would be
   reformatted. **None** are P6.3-touched — `ruff format --check` on the 4 changed files alone =
   `4 files already formatted`, and the 51 are byte-identical between `main` and the impl branch (the
   diff touches only 4 files), so `main` is equally red. This is pre-existing format-hygiene debt
   (the same class as the prettier debt that drove the #95 follow-on), **out of P6.3 scope**.
   *Recommendation (orchestrator, under the P6 hygiene-backlog delegation):* track a separate
   format-hygiene sweep — do **not** bundle it into P6.3 (that would breach scope discipline /
   architect-deferral literal-reading). Surfaced, not routed.
2. The plan's **optional** ADR-020 D2 clarification note was not inscribed (only the mandatory
   docstring + code comment). The plan made the ADR note explicitly optional ("rides along, no Accept
   gate"), so its absence is conformant, not a miss. No ADR amendment was required and none was made.

## Convergence with the senior plan-vs-impl

Two independent lenses → same conclusion. Senior (plan-fidelity): clean, scope-contained, ft9
fail-on-revert executed. R0-A (this, brief-author + cross-family/contract lens): clean, ADR-020 D2 /
ADR-031 D5 preserved, **full**-suite green, G1 **and** H1 fail-on-revert both executed. No divergence;
the only additive signal is the pre-existing repo-format-debt observation, which is out of scope.

## Verdict

**clean** — both atoms faithful to the plan + brief ratification; ADR-020 D2 and ADR-031 D5 contracts
preserved; spine and `LLMPurpose` untouched; gates green on the full suite; G1 and H1 fail-on-revert
empirically verified. The lone gate-red signal (repo-wide `ruff format --check`) is pre-existing debt
unrelated to P6.3. **No architect decision required from this lens.**
