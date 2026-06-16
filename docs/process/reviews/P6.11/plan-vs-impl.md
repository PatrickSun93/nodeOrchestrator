---
task_id: P6.11
kind: plan-vs-impl
reviewer: senior
surface: product
verdict: needs_architect
plan: docs/process/senior-plans/P6.11.md
impl_ref: origin/claude/P6.11-impl @ 083ba25
state_at_write: awaiting_senior_plan_vs_impl
cross_family: true   # resource-exhaustion (Lens A) + frozen web_fetch spine-surface (Lens B)
---

# P6.11 plan-vs-impl — pipeline-ingress hardening (H1 🔴 + H2 + fetch wall-clock + H3)

**Scope of this review.** Faithfulness of `origin/claude/P6.11-impl @ 083ba25` to
`senior-plans/P6.11.md`, atom by atom: no plan-外 expansion, the spine-freeze claim holds,
each ratified value lands. Read via `git diff origin/main...origin/claude/P6.11-impl` (10
files, +556/-40; six commits A2→A1→A3→A4→A5 + one lint/type-fix, one atom = one commit per
RC-17 ✔).

**Verdict: `needs_architect`.** Five of the six atomic deltas are faithful to the plan with
correct, revert-gated tests. **One unplanned edit sits on the frozen `web_fetch` surface**
and contradicts the plan's explicit *"byte-identical"* spine-freeze claim — that is an
architect-owned invariant, so I surface rather than wave through or unilaterally force a
revert. Detail in §F1.

---

## Atom-by-atom faithfulness

### A2 — H2 schema ceilings ✔ faithful
- `sources/schema.py`: `_SOURCE_MAX_BYTES_CEILING = 5 * 1024 * 1024` + `le=` on
  `SourceOptions.max_bytes` (default 512 KiB unchanged). ✔ plan §A2.
- `pipeline/schema.py`: `_MAX_SOURCES_PER_RUN = 16` + `max_length=` on
  `PipelineDefinition.sources` (`min_length=1` preserved). ✔ plan §A2.
- Tests: migration witness (`test_source_options_default_still_valid`,
  `test_pipeline_definition_default_still_valid`), boundary-accepted, and revert-gates
  (`...above_ceiling_rejected`, `...max_sources_accepted` with the 17th raising). ✔ all three
  acceptance criteria pinned.

### A1 — H1 🔴 stream-bound both readers ✔ faithful **except §F1**
- `_stream_bounded` signature → `(response, max_bytes: int = MAX_RESULT_BYTES)`, both
  internal `MAX_RESULT_BYTES` uses replaced with `max_bytes`. ✔ plan §A1.
- `web.py` / `rss.py`: `client.send(build_request("GET", …), stream=True)` →
  `_stream_bounded(response, max_bytes=min(source.options.max_bytes, _SOURCE_MAX_BYTES_CEILING))`;
  `truncated = truncated_at is not None`; `SourceReadError` re-raise + `HTTPStatusError`
  handler preserved; post-render truncation block removed (subsumed). ✔ plan §A1.
- Cross-module `_`-private imports (`_stream_bounded`, `_SOURCE_MAX_BYTES_CEILING`) match the
  cited precedent. ✔
- Tests: stream-stops-at-cap (web + rss, would-raise / sentinel generators), 300 KiB
  not-truncated-with-default-options (proves the param carries 512 KiB not the 64 KiB
  default), RSS over-cap fail-closed (`SourceReadError`), and the existing web/rss success +
  truncation mocks **rewritten** to the streaming path (not augmented — the plan's R0-A
  heads-up #2 holds). ✔ revert-gates present.
- **Deviation — see §F1:** the diff *also* changes the chunk-boundary comparison
  `if len(chunk) > remaining:` → `>=` in `_stream_bounded`. Not in A1's edit list; it alters
  the frozen `web_fetch` output contract at the exact-cap boundary.

### A3 — H2 runtime caps ✔ faithful
- `rss.py`: `_MAX_FEED_ENTRIES = 256`; `entries = _parse_feed(xml_text)[:_MAX_FEED_ENTRIES]`
  immediately after parse (bounds both render loop and DOM list). ✔ plan §A3.
- `runner.py`: `_MAX_FETCHED_CONTEXT_BYTES = 1 * 1024 * 1024`; after the join, UTF-8 length
  check → truncate to cap + `\n\n[context truncated at {…} bytes]` (`errors="replace"`). ✔
  plan §A3.
- Tests: `test_rss_entry_cap_applied` (300 → exactly 256, revert-gate),
  under-limit-unaffected, `test_fetched_context_truncated_at_1mib` (marker present, ≤ cap +
  headroom), under-limit-no-marker. ✔ both acceptance criteria pinned.

### A4 — fetch-stage wall-clock budget ✔ faithful
- `runner.py`: `_PIPELINE_FETCH_MAX_WALL_CLOCK_S = 90.0` (sibling to the analyze
  `_PIPELINE_MAX_WALL_CLOCK_S = 120.0`); `fetch_loop_start = time.monotonic()` before the
  loop; top-of-iteration check `>= budget` → OBSERVATION event (same field shape as the
  per-source-failure OBSERVATION: `generate_event_id` / `OBSERVATION` /
  `build_author(PIPELINE_AGENT_ID)` / `now_ms` / `parent_id=run_anchor.id`) → `break`.
  Fail-closed. ✔ plan §A4; the senior-picked `90.0` value landed verbatim.
- Tests: `test_fetch_budget_exceeded_stops_loop` (patches `runner.time.monotonic`, asserts
  `sources_read == 1`, OBSERVATION present, run still succeeds → analyze proceeds),
  `test_fetch_budget_fast_sources_unaffected`. ✔ both acceptance criteria pinned.

### A5 — H3 confirm + ADR-041 in-place ✔ faithful
- ADR-041 **D4**: H3 SSRF-floor-scope note (in-process floor vs ADR-037 D3 container;
  owner-configured deterministic reads; "As-designed") + the per-source 5 MiB ceiling +
  `_MAX_FEED_ENTRIES=256` + `_MAX_FETCHED_CONTEXT_BYTES=1 MiB` pinned. ✔
- ADR-041 **D8**: `max_length=16` + `le=5 MiB` amendment block. ✔
- ADR-041 **risks/Consequences**: occupancy risk amended (240 s → bounded by count-cap +
  90 s fetch budget + stream-bound, no full-body buffer). ✔
- Additive only, no decision reversed; **no new ADR file, no `adr:` key** in the plan
  frontmatter (`plan_has_adr: false`). ✔ plan §A5.

### Spine-freeze / scope ✔ (with the §F1 caveat)
- Net diff = exactly the 10 planned files; no new `LLMPurpose`; gate
  (`_execute_local_call` / `score` / `decide_tier`), `_write_and_turn`, countdown spine all
  untouched. ✔
- `tests/tools/test_network_tools.py` (the web_fetch witness) is **not** in the diff —
  unchanged, as the plan required. ✔ *but see §F1: that suite cannot see the boundary change.*

---

## Findings

### F1 (surfaced to architect) — unplanned `>`→`>=` edit changes the frozen `web_fetch` output contract at the exact-cap boundary

**What.** `src/orchestrator/tools/network_tools.py` `_stream_bounded`:

```diff
-        remaining = MAX_RESULT_BYTES - total
-        if len(chunk) > remaining:
+        remaining = max_bytes - total
+        if len(chunk) >= remaining:
```

The plan (§A1 "Where") authorized **only** the signature default + replacing the two
`MAX_RESULT_BYTES` uses with `max_bytes`. The `>`→`>=` operator change is not in the edit
list.

**Why it matters (the spine-freeze claim it breaks).** The plan asserts, twice, that
`web_fetch` is **byte-identical** ("the existing `_inprocess_web_fetch` caller (passes
nothing → 64 KiB) is byte-identical", plan §1 Spine note). With `>=` it is *not*, in exactly
one measure-zero case: a response body whose length is **exactly** `max_bytes`.

- Content bytes are identical in **all** cases (I checked every branch: strictly-under,
  strictly-over, and exact-cap — content is byte-for-byte the same).
- The single delta is `truncated_at`: for a body of length `== MAX_RESULT_BYTES`, the
  original returns `truncated_at=None`; `>=` returns `truncated_at=MAX_RESULT_BYTES`.
- That value is not internal — `_inprocess_web_fetch` returns it as
  `LocalToolOutput(output_truncated_at=truncated_at)` (`network_tools.py:266`). So a
  web_fetch of an exactly-64-KiB resource now reports the tool output as **truncated** where
  before it reported complete. A structured field of the frozen tool flips.

**Why the gate is green anyway (the silent part).** The web_fetch witness
`test_web_fetch_over_size_truncated` uses a **strictly-over** body, so it passes under both
`>` and `>=` — the boundary flip is invisible to the existing suite. This is precisely the
class of silent spine drift the byte-freeze discipline exists to catch.

**Why it almost certainly happened.** Both new A1 stream-stop tests
(`test_web_source_stream_stops_at_cap`, `test_rss_source_stream_stops_at_cap`) are written so
the would-raise / sentinel chunk fires when the reader reads **one chunk past** an
exactly-at-cap first chunk. Under the original `>`, a chunk of length `== remaining` does not
break (it is appended, `total` reaches the cap, the loop continues and reads the next chunk —
bounded, OOM-safe, but one extra read). So those two tests **require** `>=` to pass; the
junior changed the operator to satisfy the plan's "stops iterating at the cap" criterion in
its strict reading.

**The genuine fork (architect's call, not mine).** The 🔴's intent is OOM/HoL prevention.
There are two faithful readings of "stops iterating at the cap":
1. **OOM-sufficient** (preserves byte-identity): never buffer unbounded; reading the single
   boundary chunk and truncating to `[:remaining]` is fine. Keep `>`; rewrite the two
   stream-stop tests to use chunks that are **strictly past** the cap *with data* (as
   `test_rss_source_stream_stops_at_cap` already nearly does — the sentinel is a real extra
   chunk, only the assertion over-specifies "not read at all"). web_fetch stays byte-frozen.
2. **Strict-stop** (what landed): stop on the exact cap byte; accept that web_fetch's
   `output_truncated_at` flips for an exactly-cap body, and amend the plan's "byte-identical"
   understanding to "content byte-identical; truncation signal stops one chunk earlier."

I do **not** route this myself (CLAUDE.md: never re-interpret a frozen-spine contract; the
architect owns the byte-freeze invariant). Recommendation, for what it's worth: **option 1** —
it keeps the constitutional-adjacent `web_fetch` surface genuinely byte-frozen for the cost
of a two-test tweak, and the OOM-sufficient reading fully satisfies the 🔴. But the call is
the architect's.

**Disposition.** Send back to junior for the chosen remediation (option 1 = revert operator +
adjust the two stream-stop tests; option 2 = keep, add an exact-cap web_fetch boundary test +
amend the freeze wording in the plan/ADR). Either is a small, contained change.

---

## Non-blocking notes (no action required this cycle)

- **N1 — `timeout_s` ceiling residual.** Confirmed un-added, per plan §5.3 (architect-deferral
  literal-reading; not bundled). The A4 fetch budget bounds aggregate time, so this is a clean
  residual the architect may inscribe alongside the others — not a gap.
- **N2 — RSS `truncated` semantic shift** (rendered-output → raw-XML-fetch cap) landed as the
  plan's R0-A heads-up #1 describes; the over-cap → `ParseError` → `SourceReadError`
  fail-closed path is pinned by `test_rss_source_over_cap_fails_closed`
  (`match="rss_parse_failed"`). As-designed, flagged here for the R0-A reader.

## Recommendation
`needs_architect` on F1 only. The other five deltas are merge-ready as-is; F1 is a small,
contained fix once the architect picks the reading. No re-plan needed.
