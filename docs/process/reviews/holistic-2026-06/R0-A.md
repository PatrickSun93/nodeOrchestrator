---
review: holistic-2026-06
stage: R0-A (architect-partner)
type: holistic (cross-slice, NOT single-slice)
date: 2026-06-15
reviewer: architect-partner
scope: PRs #67–#80 — P5.1 analysis-pipeline wave (ADR-041/042/043) + agy CLI provider (#71) + P6.1–P6.10 correctness phase
diff_range: 200c006 (parent of PR#67 merge) .. 2f8bc2e (origin/main)
verdict: needs_architect
gate_status: GREEN (ruff check + ruff format[313] + mypy strict[310] + pytest 2579 passed, isolated detached worktree, uv sync --all-extras)
blocking_count: 0
needs_architect_count: 6
green_count: 1
---

# Holistic R0-A — P5.1 pipeline wave + agy provider + P6 correctness phase

**One-sentence conclusion:** The constitutional spine is byte-clean and gates are fully green across all 14 slices, but the holistic lens surfaces **one genuine cross-slice drift** — the new pipeline data-ingress path (`sources/`) skipped the OOM-streaming guard that the parallel `web_fetch` path already established — plus a cluster of resource-bound and accretion tech-debt items that warrant architect routing; **no blocking findings.**

This is a *holistic* pass: it deliberately looks for what single-slice reviews (each already clean) could not see — interactions, accretion, and pattern-drift across PRs that were reviewed in isolation.

---

## 0. Findings at a glance

| ID | Sev | Dim | Title | Anchor |
|----|-----|-----|-------|--------|
| **H1** | 🟡 *(🔴-lean, calibrated — see note)* | 2+3 | `sources/` buffers full response body before applying `max_bytes` — reintroduces the OOM exposure `_stream_bounded` exists to prevent; runs on the `max_workers=1` writer → cross-room head-of-line | `sources/web.py:28`, `sources/rss.py:122` |
| **H2** | 🟡 | 3 | Pipeline ingress has no upper resource ceilings (source-count, RSS item-count, per-source `max_bytes`, aggregate context) | `pipeline/schema.py:33`, `sources/schema.py:15`, `sources/rss.py:136`, `runner.py:287-308` |
| **H3** | 🟡 | 3 | Pipeline source fetches always use the **in-process** SSRF floor, never the egress-sandbox container, even under FAIL_CLOSED/SANDBOXED posture | `runner.py:81-91`, `app.py:863`, `app.py:2140-2148` |
| **H4** | 🟡 | 3 | `api/app.py` god-file: 2632 lines (+1096 this wave ≈ 42%), 3.4× the next product file; pipeline+scheduler+email+rooms+auth all accreted in one module | `api/app.py` |
| **H5** | 🟡 | 2+3 | Spine-adjacent constants duplicated with no shared source-of-truth (by-design per ADR-041 D2, but silently divergeable) | `runner.py:57-58`, `agy_cli.py:42-53` |
| **H6** | 🟡 | 3 | Inscribed-residual ledger + one guard-philosophy inconsistency (visibility only, no action) | `mutation_tools.py:173`, `subprocess_tools.py:438,444` |
| **H7** | 🟢 | 3 | Unbounded `int()`/`content` on untrusted agy CLI stdout (pre-existing pattern, shared with claude CLI) | `agy_cli_output.py:97-98` |

**Verdict: `needs_architect`** — spine clean + gates green, but H1 (real drift) and the H2/H3/H4 cluster need a routing call (a hardening follow-on slice, and a decision on the app.py refactor). Nothing is blocking: the spine holds, gates pass, and H1 is bounded by the SSRF allowlist + owner-authored source URLs + the opt-in pipeline feature.

---

## 1. Constitutional spine integrity — **CLEAN** ✅

The single most important holistic question — did 14 slices erode the spine by a thousand cuts? — answers cleanly.

- **Gate + executor byte-frozen.** `git diff 200c006..origin/main` over `autonomy/emission.py` (`emit_gate_decision`), `autonomy/scoring.py` (`score` / `decide_tier` / COUNTDOWN scoring), and `tools/executor.py` (`_execute_local_call`) is **empty**. Zero semantic drift across the whole wave.
- **`run_pipeline` frozen post-introduction.** `pipeline/runner.py` changed only 12 lines after P5.1a introduced it (`e318721..HEAD`), and every line is P6.6 ruff-format reflow — the runner logic is untouched by the scheduler, email, and P6 slices that built around it.
- **No new routing LLMPurpose.** `llm/purposes.py` diff is byte-empty; `AGENT_RESPONSE` remains the only agent content-gen purpose. The agy provider adds **zero** purposes and makes no routing/tier/gate decision (`grep agy router.py` → no matches; the router diff is a pure `select_viable_routes` refactor). Routing authority stays with the architect.
- **COUNTDOWN spine intact; the one crossing is documented.** The sweeper path is untouched. `approval_source` widened additively `Literal["human","auto_timer"]` → `+"auto_pipeline"` (`core/event.py:224`) — this is the single ADR-043 D2 irreversible-actuation crossing, and it is implemented as a **third caller** of the shared `_writer_approve_helper`, not a fork of the sweeper. All three callers (HTTP confirm `app.py:1665`, auto_timer sweeper `app.py:562`, auto_pipeline email `app.py:703`) reconstruct the approval from the persisted `ToolCallPendingMeta` inside the shared helper, so the room-state gate + still-pending idempotency check are inherited identically. `run_pipeline` passes `countdown_auto_fire=None` at both sites, so a pipeline `send_email` (HARD, rev 3 < floor 5) is triple-excluded from the COUNTDOWN sweeper.
- **Constitution test still guards.** `tests/core/test_constitution.py:287` pins the `ToolCallMeta` *field set* `{tool_name, call_id, params, approver_user_id, approval_source}`. The `auto_pipeline` Literal widening is additive and does not change the field set, so the freeze test remains load-bearing.
- **Residual chain honest, no gap.** `RB-FS/RB-NET → RB-ADMIT → RB-AUTHZ → RB-AUTOFIRE → RB-PIPELINE-SCHED → RB-PIPELINE-EMAIL` recited intact (`ADR-043:70`). The low `RB-NET` occurrence count is **not** a hole: `RB-NET` is deliberately grouped with `RB-FS` as the single "sandboxed I/O" link (P4.3), always cited as the pair. Each link's escalation claim (reversible-floored → reversible-initiate → irreversible-actuate) is consistent and non-overlapping.

---

## 2. Cross-slice consistency / integration — **mostly clean; H1 is the exception**

What the seams do correctly (verified, not assumed):

- **Pipeline runner ↔ scheduler ↔ email actuator.** The schedule sweeper (`app.py:928`) duplicates the ADR-040 *loop shape* but **none** of its spine code, and reaches actuation only via `_schedule_act_on_writer` → `_actuate_pipeline_emails` (single caller, `app.py:917`), never `_writer_approve_helper` directly. The honesty test (`tests/.../test_schedule_sweeper.py:488`) correctly drops `_writer_approve_helper` from the forbidden set while keeping the countdown spine forbidden for both functions.
- **Headless-email actuation is fail-closed at every branch.** Traced end-to-end: `email_enabled=False` → return; non-`live` → skip; live requires `pending_to and pinned and pending_to.lower()==pinned.lower()` before the helper fires (`app.py:688`). `send_email`-only is a literal module constant (`_PIPELINE_EMAIL_TOOL`, `app.py:614`), not a config list; `git_push`/`apply_edit` HARD pendings are pinned never-actuated by test. Scheduled-only holds structurally (the manual `/run` endpoint actuates nothing). Idempotency is single-sourced: `next_fire` advances *before* the run (`app.py:837`, drop-not-retry), and the helper re-reads fresh room state per call.
- **git_push / apply_edit hardening composes across P6.1–P6.9.** The three git_push refspec guards (leading-`-` flag ban, leading-`:`/`+`, glob `*`) each cover a distinct class and don't contradict; the P6.9 fail-on-revert proved no guard is dead code. `apply_edit`'s `.git/`-deny operates on the post-`.resolve()` path, so traversal / `./` / `//` / in-root symlink are all denied while `git-data/`, `.gitignore`, `.github/` decoys are correctly allowed. Path containment routes through the single shared `_check_path` (`tools/local.py`) — no normalization drift.
- **agy provider parity.** Same Protocol surface as siblings; system prompt prepended (not dropped), temperature forwarded, usage reported, tools rejected fail-closed, `base_url` allowlist + parent-env strip mirror the vetted `claude_code_cli` pattern.

**The exception — H1 (see §5):** `sources/` and `network_tools` both fetch untrusted HTTP, but they bound it differently. `network_tools._stream_bounded` streams and caps *during* read; `sources/web.py` + `sources/rss.py` buffer the **entire** body via `response.content`, *then* slice. This is exactly the cross-slice drift a single-slice P5.1a review could not catch — it required comparing the new ingress path against the older tool path.

---

## 3. Cumulative tech debt / invariant risk

- **H4 — `api/app.py` accretion.** Now 2632 lines (the wave added 1096, ~42% of current size), vs 773 for the next-largest product file. Pipeline run endpoint, schedule CRUD, schedule sweeper, email actuator, rooms list, and auth plumbing have all landed in this one module across the wave. No correctness issue, but it is the highest-friction file in the product and a future-review hazard (the holistic seams in §2 were *all* in this one file). Candidate for an extract-router refactor — architect's call on timing.
- **H2 — no upper resource ceilings on the pipeline ingress** (companion to H1): `PipelineDefinition.sources` is `min_length=1` with **no `max_length`** (`pipeline/schema.py:33`); per-source `max_bytes` is `gt=0` only, no ceiling (`sources/schema.py:15`); RSS renders *every* entry before truncating the joined string (`rss.py:136`); `runner.py:287-308` concatenates all source content into one prompt context with no aggregate cap. Owner-authored definitions (ADR-041 D7) lower the severity to self-inflicted, but there is no defense-in-depth ceiling anywhere on the ingress path.
- **H3 — pipeline fetch never engages the egress sandbox container.** `PipelineDeps` carries no `posture_resolver`; both call sites build it without one (`app.py:863` scheduler, `app.py:2140` manual). So pipeline reads always use the **in-process** `build_ssrf_client` floor even when the operator runs FAIL_CLOSED/SANDBOXED expecting container-confined egress. The in-process SSRF floor is genuinely strong (this is not an SSRF bypass), and ADR-041 D4 only promises "reuse the SSRF-validating client," so this is *arguably as-designed* — surfacing for an explicit one-line ADR confirmation rather than as a contract violation.
- **H5 — duplicated constants.** `runner.py:57-58` hard-codes `_PIPELINE_MAX_PASSES=4` / `_MAX_WALL_CLOCK_S=120.0` mirroring the interactive caps in `app.py` (the ADR-041 D2 "duplicate, don't share, to keep `_write_and_turn` byte-untouched" decision) — by-design, but the two literals can now silently diverge. `_TRANSIENT_STDERR_MARKERS` is copied verbatim across `agy_cli.py:42` and `claude_code_cli.py:61` (3rd subprocess provider). Both are cleanup-class, noted for the ledger.
- **H6 — inscribed-residual ledger (no action; cross-slice visibility).** Two consciously-deferred items remain honest and bounded: (a) the `.git/`-deny is case-sensitive, so `.GIT/config` bypasses on case-insensitive filesystems (`mutation_tools.py:173`) — ratified out-of-scope at P6.9; (b) git_push `src:dst` permits creating an arbitrary *new* remote ref name (`subprocess_tools.py:438,444`) — documented-accepted, bounded by always-HARD-confirm + git's non-ff rejection. Note one **philosophy inconsistency** worth an eventual one-liner: the `.git` deny is case-sensitive while sibling guards lowercase (`network_tools.py` send_email domain allowlist, `egress_proxy.py` hostnames) — same-family guards disagree on case handling.

Cumulative state of the protected surfaces (sandbox / auth / plugin / llm-router): no new interaction risk found among the previously-inscribed residuals (owner-scoped rooms, session-revocation, eff_auto trace-clamp). The auth surface changes in this wave are owner-private endpoint guards (403 + IDOR 404) consistent with ADR-039.

---

## 4. Test & gate health — **GREEN**, one coverage blind spot

Full isolated run (detached worktree at `origin/main`, `uv sync --all-extras`):

```
ruff check          All checks passed!
ruff format --check 313 files already formatted
mypy (strict, src+tests)  Success: no issues found in 310 source files
pytest              2579 passed, 1 warning in 226s
```

- The lone warning is a `StarletteDeprecationWarning` (httpx vs starlette TestClient) — environmental, not product code.
- **Coverage blind spot (feeds H1):** `tests/sources/test_sources.py` asserts `max_bytes` *output* truncation, which passes precisely because the body is buffered-then-sliced — so the existing tests give **false confidence**: they verify the forwarded content is capped, but nothing asserts memory is bounded *during* fetch. The OOM gap is invisible to the current suite. A streaming-bound test (mirroring the `network_tools` OOM test) would catch H1 and any regression.
- No flakiness observed, but a single run cannot establish flake-freedom; the sweeper/scheduler tests use injected clocks (`now_ms`) rather than wall-clock sleeps, which is the right design and lowers flake risk.

---

## 5. H1 detail (the one finding I personally re-verified end-to-end)

**Drift:** `sources/web.py:28` (`raw = response.content`) and `sources/rss.py:122` (`xml_bytes = response.content`) read the **entire** HTTP body into memory, then apply `max_bytes` by slicing (`web.py:38-39`, `rss.py:150-152`). httpx's `.content` fully buffers before the cap is honored. The sibling `tools/network_tools.py:_stream_bounded` (`:98-117`) instead streams via `iter_bytes()` and `break`s at `MAX_RESULT_BYTES`, with the explicit docstring *"Never buffers an unbounded response into memory (ADR-028 D3 / ADR-035 D2 OOM guard)."* The `max_bytes` knob in `sources/` bounds the *stored/forwarded* content, **not** the memory consumed during fetch.

**Blast radius (verified):** the scheduled pipeline path runs `run_pipeline` (hence `read_web_source` / `read_rss_source`) inside `ctx.writer_executor` (`app.py:954`), which is `ThreadPoolExecutor(max_workers=1)` with the comment at `app.py:98`: *"Cross-room head-of-line: the single ThreadPoolExecutor(max_workers=1) serialises all."* So an unbounded body buffered during a scheduled fetch is not merely a memory spike — it **head-of-line-blocks every room's writes** until it completes or OOMs the process. Threat model: an owner-authored source `locator` (allowlisted host) whose *third-party content* (a hostile/compromised endpoint, or a legitimately huge feed) returns a multi-GB body.

**Severity calibration (honest):** the deep read leaned 🔴. I calibrate to **🟡 / needs_architect** because (a) the spine and gates are unaffected, (b) it is bounded by the SSRF allowlist + owner-authored URLs + the opt-in pipeline feature, and (c) per role I surface + lean; the 🔴↔🟡 routing is the architect's call. I am flagging it as the **#1 finding** and stating the 🔴-lean explicitly so nothing is hidden — if you read OOM-on-the-shared-writer as release-blocking, re-escalate. Suggested remedy shape (for routing, not prescription): reuse `_stream_bounded` (or a shared streaming-cap primitive) in both source readers + add the missing streaming-bound test.

---

## 6. Verified-clean (coverage map — what this review actively checked and cleared)

So the architect knows the breadth of the pass, the following were checked and found correct: gate/executor byte-freeze · `run_pipeline` freeze · no new LLMPurpose · COUNTDOWN sweeper untouched · 3-caller approval consistency + idempotency · headless-email live-send gating (case-insensitive pin, send_email-only literal, scheduled-only, dry-run-first, default-OFF) · owner-private schedule/email endpoints + IDOR guards · git_push 3-layer refspec guards compose + no dead code · `.git/`-deny robustness (traversal/symlink/substring) · single `_check_path` normalization · agy argv-not-shell / stdin-not-argv / fail-closed base_url / fail-loud parser / tools-rejected · `sources/` SSRF floor reuse (file://, localhost, 169.254.169.254 blocked) · `sources/file.py` `_check_path` containment · consistent untrusted-data framing across all source types · RSS XXE/billion-laughs block · constitution field-set freeze · residual-chain honesty.

---

*Holistic R0-A complete. No code modified (review only). Findings surfaced for architect routing; I have not decided severity routing on any 🟡.*
