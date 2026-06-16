---
task_id: P6.11
stage: architect-routing-on-impl
cycle: 1
actor: architect
date: "2026-06-16"
routing: alpha
disposition:
  F1-Y1-stream-bounded-operator: alpha-option1   # revert >= → > + fix the 2 stream-stop tests; preserve web_fetch byte-freeze
inputs:
  - docs/process/reviews/P6.11/plan-vs-impl.md   # senior, needs_architect (F1)
  - docs/process/reviews/P6.11/R0-A.md           # arch-partner, needs_architect (Y1 = F1, independently)
  - docs/process/reviews/P6.11/R0-B.md           # r0b cross-family, clean (resource-exhaustion exhausted)
---

# P6.11 impl-stage routing — α (option 1: restore the byte-freeze), one rework cycle

H1🔴 + H2 + fetch-wall-clock + H3 are **faithful and merge-ready**; R0-B clean (resource-exhaustion adversarial search exhausted — stream truly stops at the cap, caps unbypassable, the 90s fetch budget cuts slow sources). The **single** finding, caught **independently by senior (F1) and R0-A (Y1)** — 2-of-3 convergence:

**F1/Y1** — the junior made an **unplanned `>`→`>=`** edit in `_stream_bounded` (to satisfy a strict reading of "stops at the cap" in the two new stream-stop tests). Content bytes stay identical in every case, but `web_fetch`'s structured `output_truncated_at` **flips** (complete → truncated) for a response body of length **exactly** `MAX_RESULT_BYTES` — breaking the asserted `web_fetch` byte-freeze at the measure-zero exact-cap boundary. The existing web_fetch witness uses a strictly-over body, so the flip is invisible to the suite (the silent-spine-drift class the byte-freeze discipline exists to catch).

**Routing = α, option 1** (both reviewers' recommendation; the byte-freeze is a constitutional invariant the architect owns — not orchestrator-routable, hence ratified here):
- **Revert `_stream_bounded` to `>`** (`if len(chunk) > remaining`). `>` is OOM-safe: it reads the single boundary chunk then truncates `[:remaining]` — never buffers unbounded. The 🔴's OOM/HoL intent is fully satisfied by `>`.
- **Rewrite the two new stream-stop tests** (`test_web_source_stream_stops_at_cap`, `test_rss_source_stream_stops_at_cap`) so the would-raise / sentinel chunk is **strictly past the cap with real data** (not at the exact cap), and the assertion checks "bounded + did not fully drain" rather than over-specifying "the boundary chunk is not read at all."
- Net: `web_fetch` stays **genuinely byte-frozen** (the `_inprocess_web_fetch` caller's `truncated_at` is identical in all cases incl. exact-cap); the new docstring's "preserves web_fetch byte-identity" becomes true again.

cycle-2 = the operator revert + the 2-test rewrite, on `claude/P6.11-impl`. No other change (H1 readers / H2 caps / fetch budget / H3 / ADR-041 amendment all stand). Spine restored to byte-frozen. After cycle-2 clears → merge → the holistic 🔴 is closed.
