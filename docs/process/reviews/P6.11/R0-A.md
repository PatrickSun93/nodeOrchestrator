---
task_id: P6.11
kind: R0-A
reviewer: architect-partner
surface: product
verdict: needs_architect
plan: docs/process/senior-plans/P6.11.md
brief: docs/process/architect-briefs/P6.11.md
impl_ref: origin/claude/P6.11-impl @ 083ba25
state_at_write: awaiting_senior_plan_vs_impl
cross_family: true   # resource-exhaustion (Lens A) + frozen web_fetch spine-surface (Lens B)
gates: "ruff clean · ruff format 310/310 · mypy 310 files clean · pytest 2594 passed (isolated worktree, uv sync --all-extras)"
siblings: [plan-vs-impl.md (senior, needs_architect, F1), R0-B.md (clean, 0🔴/2🟡/3🟢)]
---

# P6.11 R0-A (impl) — pipeline-ingress hardening (H1 🔴 + H2 + fetch wall-clock + H3)

**Scope & method.** Independent R0-A on `origin/claude/P6.11-impl @ 083ba25` (6 commits,
+556/-40, 10 files) against `senior-plans/P6.11.md` + the brief §Ratification. Read via
`git diff origin/main...origin/claude/P6.11-impl` from a stay-on-`main` shared tree (no
checkout); gates re-run independently in a detached worktree at 083ba25 with
`uv sync --all-extras`. R0-A is mandatory regardless of the plan-vs-impl verdict (ADR-008
Amendment 1). Two sibling reviews already landed this cycle — senior `plan-vs-impl.md`
(`needs_architect`, F1) and `R0-B.md` (`clean`, 0🔴/2🟡/3🟢); this review is the
independent third lens and synthesises the three at the end.

**Verdict: `needs_architect`** — driven by a single finding (**Y1**), which is the same
frozen-`web_fetch` deviation the senior surfaced as **F1**. I reached it independently and
then **empirically proved** it (revert experiment below). Everything else — H1 mechanism,
the four H2 ceilings, the fetch wall-clock, H3/ADR inscriptions, spine-freeze, gates — is
faithful and merge-ready. Merge should wait only on the architect's routing of Y1/F1.

---

## Y1 (= senior F1) — unplanned `>`→`>=` in `_stream_bounded` breaks the `web_fetch` byte-freeze at the exact-cap boundary

**What landed** (`src/orchestrator/tools/network_tools.py`, `_stream_bounded`):

```diff
-        remaining = MAX_RESULT_BYTES - total
-        if len(chunk) > remaining:
+        remaining = max_bytes - total
+        if len(chunk) >= remaining:
```

The plan (§A1 "Where") authorized **only** the defaulted signature
(`max_bytes: int = MAX_RESULT_BYTES`) and replacing the two internal `MAX_RESULT_BYTES`
uses with `max_bytes`. The `>`→`>=` operator flip is **not** in the edit list — an
unrequested change to a frozen helper.

**Why it matters.** The plan asserts `web_fetch` is *byte-identical* (§1 Spine note), and
the new docstring even claims the default "preserves web_fetch byte-identity." With `>=`
that holds for **content bytes in every case**, but not for the structured `truncated_at`
signal at one input: a body whose length is **exactly** `max_bytes`.

- Original `>`: an exactly-cap body is fully delivered; the loop ends with
  `truncated_at=None` (correct — nothing was dropped).
- New `>=`: the same body breaks at the cap with `truncated_at=max_bytes` — a
  **false-positive truncation** flag on a complete body.

That value is surfaced: `_inprocess_web_fetch` returns it as
`LocalToolOutput(output_truncated_at=truncated_at)` (`network_tools.py:263`). So a
`web_fetch` of an exactly-64-KiB resource now reports `output_truncated_at=65536` where
the frozen contract returned `None`. The same false-positive applies to the new source
readers (`truncated = truncated_at is not None`) for any exactly-`max_bytes` body.

**Empirical proof** (run in the isolated worktree at 083ba25):

1. Revert the operator `>=`→`>` (the plan-authorized state) and run the two new
   stream-stop tests → **both FAIL**:
   `test_web_source_stream_stops_at_cap` and `test_rss_source_stream_stops_at_cap` →
   `AssertionError: iter_bytes was drained past cap — OOM regression`.
2. Under the **same** revert, run the `web_fetch` witnesses
   (`tests/tools/test_network_tools.py` + `tests/tools/test_constitution.py`) → **GREEN
   (exit 0)**.

This nails two things. (a) The operator flip is **load-bearing for two self-written
tests**: both use a first chunk of length **exactly** `max_bytes` (`b"A" * max_bytes`) and
assert the reader does not read the following would-raise/sentinel chunk. Under the
correct streaming `>`, a chunk equal to `remaining` is appended and the loop reads **one
more** chunk to discover EOF-vs-overflow (bounded, OOM-safe — just one extra read), so the
sentinel fires. The junior changed the spine operator to satisfy a strict reading of
"stops iterating at the cap" — whereas the plan's own acceptance wording said chunks
"summing **past** the cap" (§A1 OOM/stream gate), which the correct `>` already passes. (b)
The existing spine witnesses are **blind** to the flip (`test_web_fetch_over_size_truncated`
uses a strictly-over body, green under both operators) — exactly the silent spine drift the
byte-freeze discipline exists to catch.

**No OOM/security delta.** Both operators bound memory; `>` reads at most one extra
already-bounded chunk in the measure-zero exact-cap case. The flip buys nothing on the 🔴's
actual intent (OOM/HoL) and costs a false-positive truncation signal + a real (if tiny)
spine deviation.

**My lean (I do NOT route — architect owns the byte-freeze invariant; CLAUDE.md "never
re-interpret a frozen-spine contract", role-doc "never decide α/β/γ"):** **option 1**,
converging with the senior's F1 recommendation — restore `>`, and retune the two
stream-stop tests to use a first chunk **strictly past** the cap (e.g. `max_bytes + 10`, or
keep the real second chunk and drop the over-strict "not read at all" assertion). That
keeps `web_fetch` genuinely byte-frozen and still fully pins the 🔴, for a two-test tweak.
Option 2 (keep `>=`, add an exact-cap `web_fetch` boundary test, amend the "byte-identical"
wording in plan/ADR to "content byte-identical; truncation signal stops one chunk earlier")
is the architect's to choose. Either is small and contained — no re-plan.

---

## Cross-review synthesis (for routing)

```
🟡 Y1/F1  — >→>= flips web_fetch output_truncated_at at the exact-cap boundary
   R0-A (me): FOUND independently + empirically proven (revert → 2 src tests fail,
              web_fetch witnesses green); lean option-1
   senior  : FOUND (F1, needs_architect); lean option-1
   R0-B    : NOT flagged — G1 calls the revert-gate "correctly designed" and certifies
             "web_fetch byte-identity confirmed at :251". That check covered the
             default-param SEAM, not the in-helper operator change. Its byte-identity
             certification is therefore incomplete (true for content, false for the
             truncation signal at exact-cap).
   → 2-way overlap (R0-A + senior), 1 divergence (R0-B's clean did not examine the
     operator). Both who looked at the helper body agree. architect: option 1 / option 2?
```

**Why the divergence matters for routing:** R0-B's verdict is `clean`, but its byte-identity
line is a seam-level check, not a helper-level one — so a reader skimming "R0-B: clean"
should not down-weight F1/Y1. The two reviewers who diffed `_stream_bounded`'s body both
caught it.

**R0-B's two 🟡 — corroborated, both non-blocking residuals (no routing pressure):**
- **R0-B Y1 — `timeout_s` has no ceiling** (`sources/schema.py:16`, `gt=0.0` only). Same as
  senior N1 and plan §5.3: correctly **not bundled** (architect-deferral literal-reading;
  P1.5.5 RC-19 precedent). The A4 90 s fetch budget is the practical backstop. A clean
  residual the architect *may* inscribe alongside the four H2 ceilings — not a gap.
- **R0-B Y2 — context truncation can emit U+FFFD mid-codepoint** (`runner.py:324-327`,
  `errors="replace"`). As-designed: the plan §A3 chose `errors="replace"` "consistent with
  existing `truncated` semantics" (`web.py`/`rss.py` already do this), and the visible
  marker is the primary signal. Cosmetic; low priority.

---

## Independent confirmation of the rest (faithful — senior's atom-by-atom holds; I re-verified, not restating)

- **H1 🔴 mechanism** — both readers drop `.content` and stream via
  `client.send(build_request("GET", …), stream=True)` → `_stream_bounded(…,
  max_bytes=min(source.options.max_bytes, _SOURCE_MAX_BYTES_CEILING))`, mirroring
  `_inprocess_web_fetch`; `HTTPStatusError` handler + `SourceReadError` re-raise preserved;
  post-render RSS truncation block removed (subsumed). RSS over-cap fail-closed
  (truncated XML → `ParseError` → `SourceReadError` → runner per-source try/except records
  OBSERVATION + continues) is pinned by `test_rss_source_over_cap_fails_closed`
  (`match="rss_parse_failed"`). ✔ (the operator caveat is Y1, not the mechanism.)
- **H2 four ceilings** — `_MAX_SOURCES_PER_RUN=16` (`max_length` on
  `PipelineDefinition.sources`), `_SOURCE_MAX_BYTES_CEILING=5 MiB` (`le=` on
  `SourceOptions.max_bytes`), `_MAX_FEED_ENTRIES=256` (slice after `_parse_feed`),
  `_MAX_FETCHED_CONTEXT_BYTES=1 MiB` (truncate + marker). Values match ratification exactly.
  Schema pair is fail-closed at `POST /pipelines`: `PipelineDefinition(...)` is built inside
  the endpoint try/except → HTTP 422 (`api/app.py:2024-2031`), confirmed. Migration
  witnesses (`...default_still_valid` ×2) + boundary + revert-gate tests present. ✔
- **Fetch wall-clock** — `_PIPELINE_FETCH_MAX_WALL_CLOCK_S=90.0` (sibling to analyze 120 s),
  `time.monotonic()` budget at top-of-iteration → OBSERVATION (same field shape as the
  per-source-failure event) + `break`, fail-closed. Note: the impl emits an OBSERVATION on
  skip where the analyze-stage budget (`runner.py:169`) just `break`s silently — this is
  **as-planned** (§A4 explicitly specified the OBSERVATION) and is the better, more
  observable behavior; the asymmetry is a pre-existing nit, not this slice's concern. ✔
- **H3 + ADR-041 in-place** — D4 gains the SSRF-floor-scope note (in-process floor vs
  ADR-037 D3 container; owner-configured deterministic reads; "As-designed") + the three
  pinned ceilings; D8 gains the `max_length=16` / `le=5 MiB` block; risks/Consequences
  amended (240 s occupancy → bounded by count-cap + 90 s budget + stream-bound). Additive,
  no decision reversed, no new ADR file, `plan_has_adr:false`. ✔
- **Spine** — no new `LLMPurpose` (`grep` clean; pipeline uses only
  `LLMPurpose.AGENT_RESPONSE`); gate (`_execute_local_call`/`score`/`decide_tier`),
  `_write_and_turn`, countdown spine untouched (not in diff). The **only** spine touch is
  the `_stream_bounded` operator = Y1. ✔ (modulo Y1)
- **Gates (my independent isolated run @ 083ba25)** — ruff `All checks passed`; ruff format
  `310 files already formatted`; mypy `Success: no issues found in 310 source files`; pytest
  **2594 passed, 1 warning** (the pre-existing Starlette deprecation) in 230 s. ✔

---

## Recommendation

`needs_architect` on **Y1/F1 only** — restore the byte-freeze (option 1, my + senior's lean)
or consciously accept the truncation-signal shift (option 2). The other five atomic deltas
are merge-ready as shipped. R0-B Y1 (`timeout_s`) and Y2 (U+FFFD) are inscribe-or-ignore
residuals, no action required this cycle. No re-plan. Once routed, the fix is a small
contained junior change; merge should wait for that routing so option 2's spine shift is a
conscious call, not a silent one.
