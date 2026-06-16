---
task_id: P6.11
kind: R0-A
cycle: 2
reviewer: architect-partner
surface: product
verdict: clean
plan: docs/process/senior-plans/P6.11.md
brief: docs/process/architect-briefs/P6.11.md
impl_ref: origin/claude/P6.11-impl @ c1cc210
state_at_write: awaiting_senior_plan_vs_impl
supersedes: "R0-A cycle-1 (needs_architect, Y1/F1) — full cycle-1 analysis preserved in git history of this file"
routing_applied: docs/process/reviews/P6.11/architect-routing-on-impl.md (α, option 1)
gates: "ruff clean · ruff format 313 already formatted · mypy 310 files clean (canonical scope) · pytest 2594 passed · web_fetch byte-freeze witnesses green (isolated worktree @ c1cc210, uv sync --all-extras)"
---

# P6.11 R0-A (impl) — cycle 2: byte-freeze restore re-review

**Verdict: `clean`.** The single finding that drove cycle-1's `needs_architect`
(**Y1 = senior F1** — an unplanned `>`→`>=` in `_stream_bounded` that flipped
`web_fetch`'s `output_truncated_at` at the exact-cap boundary) is **resolved**, exactly
per the architect's α/option-1 routing. `web_fetch` is genuinely byte-frozen again,
the two stream-stop tests still guard the H1 OOM bound, nothing else moved, and an
independent isolated gate run is green. The holistic 🔴 (H1) is closed; merge-ready.

**Scope & method.** Cycle-2 re-review of `origin/claude/P6.11-impl @ c1cc210` against
`architect-routing-on-impl.md` (α, option 1). Stay-on-`main` shared tree (no checkout);
this round read via `git diff 083ba25..c1cc210` — exactly **two files, one source line +
two tests**: `network_tools.py` (`>=`→`>`) and `tests/sources/test_sources.py` (the two
stream-stop tests rewritten). Gates re-run independently in a detached worktree @ c1cc210
with `uv sync --all-extras`. (Cycle-1's deep Y1 analysis + empirical revert proof are in
this file's git history; this supersedes it with the post-fix state.)

---

## The fix verified — three checks

### 1. `_stream_bounded` operator restored to `>` → `web_fetch` byte-frozen in *all* cases

`network_tools.py:112` is back to `if len(chunk) > remaining:`. The **only** remaining
delta vs. the original frozen helper is the plan-authorised A1 seam — the defaulted
parameter `max_bytes: int = MAX_RESULT_BYTES` plus the two internal `MAX_RESULT_BYTES`→
`max_bytes` substitutions. This makes the cycle-2 helper a **strict superset** of the
original: on the default path the code is line-for-line identical.

The byte-freeze is therefore **structural, not test-dependent**: `_inprocess_web_fetch`
calls `_stream_bounded(response)` (`network_tools.py:251`) with **no** `max_bytes`
argument → `max_bytes` defaults to `MAX_RESULT_BYTES` → `remaining`, the `>` branch, and
`truncated_at` are byte-identical to the frozen contract for every input, **including a
body of length exactly `MAX_RESULT_BYTES`** (the measure-zero case cycle-1 caught). The two
operators differ only at `len(chunk) == remaining`; under `>` an exactly-cap *complete*
body ends with `truncated_at=None` (correct — nothing dropped), matching the original. The
docstring's "preserves web_fetch byte-identity" claim is true again. The source readers
(`web.py:37`, `rss.py:134`) keep the parametrised H1 path (`max_bytes=min(options.max_bytes,
_SOURCE_MAX_BYTES_CEILING)`) — untouched this cycle.

### 2. The two stream-stop tests — operator-agnostic, still genuine OOM revert-gates

Both tests now use a **strictly-past-cap first chunk with real data** and assert
**bounded + did-not-fully-drain**, per the routing (no more over-specified "exact-cap chunk
never read"):

- `test_web_source_stream_stops_at_cap`: first chunk `b"A" * (max_bytes + 10)`, flag
  `drained_past_cap` set only if the reader pulls the 2nd chunk; asserts
  `not drained_past_cap` (+ content ≤ cap).
- `test_rss_source_stream_stops_at_cap`: first chunk `b"X" * (max_bytes + 5)`, sentinel set
  on 2nd pull; asserts `not sentinel_hit` (read still fails closed on truncated XML).

**Empirically confirmed** in the isolated worktree:
- Under the shipped `>`: **both PASS** (the strictly-over chunk trips the bound on the
  first chunk, so the 2nd is never pulled — no exact-cap ambiguity).
- **Revert-gate intact** — I reverted `_stream_bounded` to an unbounded drain (the
  `.content`-equivalent regression): **both FAIL** with
  `AssertionError: iter_bytes was drained past cap — OOM regression` (`assert not [True]`).
  So the tests still catch a re-introduction of the H1 OOM bug. Restored after; tree clean.

### 3. Nothing else moved

`git diff 083ba25..c1cc210` is confined to the two files above. H1 readers, the four H2
ceilings, the 90 s fetch wall-clock budget, H3, and the ADR-041 in-place amendment are
**byte-untouched**. No new `LLMPurpose`; the gate / `_execute_local_call` / countdown spine
are not in the diff. The cycle-1 "only spine touch = the operator" caveat is now retired.

---

## Independent gates (isolated worktree @ c1cc210, `uv sync --all-extras`)

- `ruff check` → **All checks passed**
- `ruff format --check` → **313 files already formatted**
- `mypy` (canonical `files=[src,tests]`) → **Success: no issues found in 310 source files**
  (note: `mypy .` trips the known `plugins/` dual-`tools_impl.py` scope collision — not a
  regression; the canonical-scope command is the gate)
- `pytest` → **2594 passed, 1 warning** (pre-existing Starlette `httpx`/testclient
  deprecation) in 237 s — same count as cycle-1 (2 tests rewritten, none added/removed)
- web_fetch byte-freeze witnesses (`test_network_tools.py` + `test_constitution.py`,
  incl. `test_web_fetch_happy_path` `output_truncated_at is None` and
  `test_web_fetch_over_size_truncated` `== MAX_RESULT_BYTES`) → **all green**

---

## One residual (🟢 — as-routed, no action)

The exact-cap boundary for `web_fetch` is **not pinned by a dedicated regression test** —
a future re-flip to `>=` would again be invisible to the suite (cycle-1's silent-drift
class). This is the **conscious consequence of option 1**: the architect routed option 1
(restore `>` + operator-agnostic tests) over option 2 (keep `>=` + add an exact-cap witness
+ amend the wording). The freeze now rests on the **structural** default-param identity
(check 1) plus the frozen-spine review discipline — which is exactly what surfaced Y1 this
cycle. Recorded for the audit trail; **not** re-litigating the routing.

## Recommendation

`clean`. α/option-1 realised faithfully and minimally; the byte-freeze invariant is whole
again and the OOM revert-gates hold. The holistic 🔴 is closed — merge once the sibling
cycle-2 senior plan-vs-impl concurs.
