---
task_id: P6.11
kind: plan-vs-impl
reviewer: senior
surface: product
verdict: clean
cycle: 2
plan: docs/process/senior-plans/P6.11.md
impl_ref: origin/claude/P6.11-impl @ c1cc210
state_at_write: awaiting_senior_plan_vs_impl
cross_family: true   # resource-exhaustion (Lens A) + frozen web_fetch spine-surface (Lens B)
supersedes: cycle-1 needs_architect (F1)
routing: docs/process/reviews/P6.11/architect-routing-on-impl.md  # α option 1
---

# P6.11 plan-vs-impl (cycle 2) — F1 remediation: restore the `web_fetch` byte-freeze

**This review supersedes cycle-1.** Cycle-1 surfaced a single finding (**F1**, converged
2-of-3 with R0-A's Y1): the junior had made an **unplanned `>`→`>=`** edit in
`_stream_bounded` that flipped `web_fetch`'s `output_truncated_at` (complete → truncated) for a
body of length **exactly** `MAX_RESULT_BYTES`, breaking the plan's asserted byte-freeze at the
measure-zero exact-cap boundary. The architect routed **α, option 1** (revert the operator +
rewrite the two stream-stop tests to a strictly-over-cap shape; preserve byte-identity) — see
`architect-routing-on-impl.md`. Cycle-2 (`c1cc210`) is that remediation. The other five atoms
(A2/A1-minus-F1/A3/A4/A5) were already confirmed faithful in cycle-1 and are **byte-unchanged**
this cycle.

**Scope of this review.** The cycle-2 delta only: `git diff 083ba25..origin/claude/P6.11-impl`
(083ba25 = cycle-1 impl ref). **Exactly two files, +14/-14:**
`src/orchestrator/tools/network_tools.py` (1 line) + `tests/sources/test_sources.py` (the two
stream-stop tests). No third file touched — option 1's scope landed verbatim, no plan-外
expansion, no opportunistic bundling.

**Verdict: `clean`.** F1 is fixed per option 1. `web_fetch` is genuinely byte-frozen again;
the two stream-stop tests are rewritten to a strictly-over-cap shape that still hard-gates the
OOM revert; nothing else moved; the full gate is green (2594 passed, ruff / ruff-format / mypy
all clean).

---

## F1 remediation — confirmed faithful to α option 1

### Operator reverted: `>=` → `>` ✔
`network_tools.py:111` (`_stream_bounded`):

```diff
-        if len(chunk) >= remaining:
+        if len(chunk) > remaining:
```

This is the **only** source-line change in cycle-2. Verified byte-freeze restoration by
re-tracing every branch against the original (pre-P6.11) `>` behavior:

- **strictly-under** chunk: `len < remaining` → appended whole, loop continues. Identical
  under `>` / `>=`. ✔
- **strictly-over** chunk: `len > remaining` → `[:remaining]` truncate, `truncated_at=max_bytes`,
  `break`. Identical under `>` / `>=`. ✔
- **exact-cap** body (`len == remaining`, the F1 case): under `>`, `len > remaining` is
  **False** → the chunk is appended whole, `total` reaches the cap, the loop ends **naturally**
  with `truncated_at` still `None`. This is byte-for-byte the original behavior. Under the
  reverted code a `web_fetch` of an exactly-`MAX_RESULT_BYTES` resource again reports
  `output_truncated_at=None` (complete), **not** `=MAX_RESULT_BYTES` (truncated). The frozen
  structured field no longer flips. ✔

`>` remains OOM-safe (ADR-028 D3 / ADR-035 D2): the boundary chunk is read once and truncated
to `[:remaining]`; nothing is ever buffered unbounded. The 🔴's OOM/HoL intent is fully
satisfied — option 1's premise holds. The docstring's "preserves web_fetch byte-identity"
(`network_tools.py:105`) is true again.

### The two stream-stop tests rewritten to strictly-over-cap + still revert-gated ✔

Both tests previously forced `>=` by putting the would-raise / sentinel chunk one read past an
**exactly-at-cap** first chunk. They are now reshaped per option 1: the first chunk is
**strictly over** the cap (real data), and the assertion checks "bounded **and** did not fully
drain" rather than over-specifying "the boundary chunk is not read at all."

- **`test_web_source_stream_stops_at_cap`** — first chunk `b"A" * (max_bytes + 10)`; a
  `drained_past_cap` flag is appended **only if** the reader advances past the first chunk to a
  second chunk. Asserts `len(content) <= max_bytes` **and** `not drained_past_cap`.
- **`test_rss_source_stream_stops_at_cap`** — first chunk `b"X" * (max_bytes + 5)`; a
  `sentinel_hit` flag guards the second (sentinel) chunk. Asserts `SourceReadError` (truncated
  XML fails closed) **and** `not sentinel_hit`.

**Guard still bites (the revert-gate is intact).** I traced both against the OOM regression they
exist to catch — reverting `_stream_bounded` to an unbounded read (`.content` / full drain):

- web test: full drain → the generator runs past the first chunk → `drained_past_cap == [True]`
  → `assert not drained_past_cap` **fails**; and `content` would exceed `max_bytes` →
  `assert <= max_bytes` **also fails**. Double gate. ✔
- rss test: full drain → `sentinel_hit == [True]` → `assert not sentinel_hit` **fails**. ✔

And under the current `>`: the strictly-over first chunk hits `len > remaining` → truncate +
`break` before the flag/sentinel line, so both tests **pass** without the regression. ✔

**Side benefit (matches option 1's intent).** Because the first chunk is now strictly over the
cap, neither test discriminates `>` from `>=` — so they no longer *force* `>=`. The exact-cap
boundary is left at the correct `>` semantics, protected by the unchanged `web_fetch` witness
suite. (Option 1 deliberately did **not** add an exact-cap witness — that was option 2; not in
scope, correctly absent.)

---

## Scope / spine-freeze re-confirmation

- **Cycle-2 diff = exactly 2 files**, both in option 1's edit list. No `_execute_local_call` /
  gate / countdown-spine / `_write_and_turn` touch (none in the diff). No new `LLMPurpose`. ✔
- The cycle-1-confirmed atoms (A2 schema ceilings, A1 stream-bound readers, A3 runtime caps, A4
  90 s fetch budget, A5 H3 + ADR-041 in-place amendment) are **byte-identical** to cycle-1
  (only the F1 line + the 2 tests differ between 083ba25 and c1cc210). No regression, no
  re-litigation needed. ✔
- `tests/tools/test_network_tools.py` (the web_fetch witness) remains **out of the diff** —
  unchanged, as the plan required, and now correctly green against the restored `>`. ✔
- **N1 (`timeout_s` ceiling residual)** and **N2 (RSS truncated semantic shift)** from cycle-1
  stand as inscribed non-blocking residuals — untouched this cycle (no opportunistic bundling
  under deferral language). ✔

## Gate

Full gate run on `origin/claude/P6.11-impl @ c1cc210` in an isolated worktree
(`uv sync --all-extras`):

- `ruff check src tests` — All checks passed
- `ruff format --check src tests` — 310 files already formatted
- `mypy src tests` — Success, no issues in 310 source files
- `pytest` — **2594 passed**, 1 warning (unchanged count vs cycle-1)

## Recommendation

`clean`. F1 is remediated exactly per α option 1: `web_fetch` byte-freeze restored, the two
stream-stop tests reshaped to a strictly-over-cap form that still hard-gates the OOM revert,
zero plan-外 expansion, gate green. The holistic 🔴 (H1) and all of H2 / fetch-budget / H3 are
faithful and merge-ready. **→ merge.**
