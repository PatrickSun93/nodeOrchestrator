---
task_id: P6.11
round: R0-B
verdict: clean
findings_count:
  red: 0
  yellow: 2
  green: 3
annotates: [ADR-041 D4, ADR-041 D8, ADR-041 risks, ADR-028, ADR-035 D2/D3, ADR-037 D3]
reviewed_commit: 083ba25
---

# P6.11 R0-B cross-family review

## Lens preamble

This review applies **Lens A** (adversarial resource exhaustion) — exactly the surface ADR-041's
own risks named: *"must be tested adversarially (Lens A)"* (ADR-041:384). The cross-family
value-add is tracing failure modes across the read → parse → join → analyze chain and asking
"what happens when this specific read returns 5 GiB at 3am on the single writer thread?"

Lens over-corrects for: (1) trusting that type-bound safety implies runtime safety (it doesn't
— the old `.content` buffer was type-safe and still OOM-capable); (2) under-weighting the
blast radius of the single `writer_executor(max_workers=1)` — every room's writes stall behind
one slow pipeline source.

The impl was reviewed by reading `git diff origin/main...origin/claude/P6.11-impl` on all 10
changed files and running the full gate suite (ruff + mypy + 121 pytest) in an isolated
worktree. Spine zero-diff was verified via `git diff` on `src/orchestrator/core/`, `llm/`,
`autonomy/`, `agents/tool_dispatch.py` — empty output, confirmed. `_inprocess_web_fetch`
passes no argument to `_stream_bounded` → default `MAX_RESULT_BYTES` (64 KiB) → web_fetch
byte-frozen, confirmed at `network_tools.py:251`. Only `LLMPurpose.AGENT_RESPONSE` used in
pipeline, confirmed.

---

## Findings table

| ID | Severity | File:line | Claim | Suggested investigation |
|---|---|---|---|---|
| Y1 | 🟡 | `sources/schema.py:16` | **`timeout_s` has no ceiling** — `gt=0.0` only, default 15 s. An operator can set `timeout_s=1_000_000` on a source, making per-source timeout effectively infinite. The A4 fetch budget (90 s aggregate) bounds total loop occupancy but a single source with an absurd timeout can monopolize the writer for the full 90 s budget. The plan explicitly deferred this as architect-deferral literal-reading (senior plan §5.3: "did not bundle it"), correctly. | Architect may want this inscribed as a residual alongside the four H2 ceilings. A ceiling (e.g. 30 s) would close the gap without design change. Low urgency — the 90 s fetch budget is the practical backstop. |
| Y2 | 🟡 | `pipeline/runner.py:324-327` | **Context truncation on raw byte boundary** — `fetched_context_bytes[:_MAX_FETCHED_CONTEXT_BYTES].decode("utf-8", errors="replace")` can produce U+FFFD replacement characters at the truncation point if the boundary falls mid-codepoint. Not a correctness bug (the marker makes truncation visible; analyze branches treat the context as untrusted data), but the replacement character may confuse an LLM that encounters it. | Consider truncating at the last valid UTF-8 boundary before the cap rather than using `errors="replace"`. Low priority — the `errors="replace"` path is existing idiom and the truncation marker already serves as the primary signal. |
| G1 | 🟢 | `tests/sources/test_sources.py:274-305` | **H1 revert-gate correctly designed** — `test_web_source_stream_stops_at_cap` uses a generator that raises if drained past cap; `test_rss_source_stream_stops_at_cap` uses a sentinel list. Both prove `iter_bytes` iteration stops at the cap, not after draining. Reverting to `.content` would cause full drain and test failure — the 🔴's gate holds. | — |
| G2 | 🟢 | `sources/web.py:34-37`, `sources/rss.py:121-124` | **Belt-and-suspenders min() clamp** — both readers pass `max_bytes=min(source.options.max_bytes, _SOURCE_MAX_BYTES_CEILING)`. The schema validator (`le=`) catches bad values at `POST /pipelines`; the `min()` clamp catches stored definitions that predate the validator. Defense-in-depth correctly applied. | — |
| G3 | 🟢 | `pipeline/runner.py:295-312` | **Fetch wall-clock bound correctly implemented** — budget check at top of each iteration, fail-closed OBSERVATION event + break on exceed, no crash. The budget check uses `time.monotonic()` (monotonic, immune to clock adjustment). Test `test_fetch_budget_exceeded_stops_loop` mocks monotonic to verify the break path; `test_fetch_budget_fast_sources_unaffected` verifies normal path unperturbed. | — |

---

## Synthesis

No 🔴 findings. The implementation correctly closes every exploit surface named in the brief:

- **H1** — both readers stream via the parametrized `_stream_bounded`; the revert-gate tests prove
  `iter_bytes` stops at the cap (would-raise generator + sentinel). RSS over-cap fails closed
  (`ET.ParseError` → `SourceReadError` → OBSERVATION → continue). The `_inprocess_web_fetch`
  default-param seam preserves web_fetch byte-identity.
- **H2** — all four ceilings enforced at both schema (Pydantic validators reject at
  `POST /pipelines`) and runtime (the `min()` clamp, RSS entry slice, context truncate +
  marker). Revert-gate tests exist for each. No bypass via encoding/unit confusion:
  all bounds are in bytes, `encode("utf-8")` correctly measures byte length.
- **Fetch wall-clock** — 90 s budget bounds the time dimension of single-writer HoL that the
  source-count cap alone leaves open. Check-at-each-iteration correctly prevents unbounded
  occupancy; per-source `timeout_s` bounds individual reads.
- **H3** — confirmed as-designed: `sources/` readers use the in-process SSRF floor
  (`build_ssrf_client`), never the egress-sandbox container. ADR-041 amended in place.
- **Spine** — `web_fetch` byte-frozen, gate/`_write_and_turn`/countdown spine untouched,
  no new `LLMPurpose`.

The two 🟡 findings are genuine residuals (both pre-acknowledged in the plan) — neither
enables a practical attack given the existing 90 s fetch budget and the truncation marker.
No new ADR or change required; architect may inscribe Y1 as a residual for a future cycle.

All 121 tests pass (ruff + mypy + pytest), spine zero-diff confirmed, web_fetch byte-identical
confirmed at `network_tools.py:251`.
