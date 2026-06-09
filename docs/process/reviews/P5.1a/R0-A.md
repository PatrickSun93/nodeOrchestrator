---
task_id: P5.1a
stage: R0-A (impl)
reviewer: architect-partner
verdict: needs_architect
findings_count: 3
findings: ["B1 (🟡, revised 🔴→🟡 after empirical test): RSS XXE/billion-laughs floor — evadable pre-scan + doc claims a parser that doesn't exist; catastrophic case capped by libexpat — converges with senior Y1", "Y1 (🟡, R0-A-unique): bounded re-dispatch loop is dead code (empirically confirmed)", "Y2 (🟡): succeeded hard-coded True → run status always 'completed'"]
lenses: ["A: pipeline safety + determinism", "B: spine no-regression"]
reviewed_branch: "origin/claude/P5.1a-impl @ abe4d55 (5 atomics T1–T6, +2512 / 22 files, 0 deletions)"
reviewed:
  - "src/orchestrator/pipeline/{runner,store,schema,__init__}.py"
  - "src/orchestrator/sources/{reader,web,rss,file,schema,__init__}.py"
  - "src/orchestrator/api/app.py (added routes + models only)"
  - "tests/{pipeline,sources,api}/* + conftest + example fixture + docs note"
against:
  - "docs/process/senior-plans/P5.1a.md (T0–T6 acceptance)"
  - "docs/decisions/ADR-041-deterministic-analysis-pipeline.md (D1–D10)"
gates_independently_run: "isolated detached worktree @ abe4d55, uv sync --all-extras"
gates_result: "ruff: All checks passed ✅ | mypy: Success, no issues in 297 source files ✅ | pytest: full suite green, exit 0 ✅ (+61 new tests: runner 13 / store 10 / sources 22 / api 14 / example 2)"
correction_log: "B1 initially filed 🔴 (catastrophic billion-laughs DoS). Empirical retest (CPython 3.12 / libexpat ≥2.4) showed the amplification-factor limit blocks the catastrophic case (10^8 → ParseError 'amplification factor breached'; 10^6 still expands). Revised to 🟡 — converges with senior plan-vs-impl Y1. Original 🔴 framing preserved in git history (commit 97eede1)."
date: "2026-06-09"
---

# R0-A (impl) — P5.1a deterministic analysis pipeline

> **Verdict `needs_architect` — 3×🟡, no 🔴, no spine/safety regression.** The
> constitutional spine and the whole Lens-B contract are **clean** (9 modules byte-frozen,
> independently verified) and all three gates are **green**. Three findings need an α/β
> routing call: **B1** (RSS XXE floor — evadable pre-scan + a doc that describes a parser
> the code doesn't have; *converges with senior Y1*), **Y1** (the bounded re-dispatch loop
> is dead code — *R0-A-unique, senior rated it working*), and **Y2** (`succeeded` always
> True). I surface + lean; you route.
>
> **⚠️ Honest correction (read this).** I first filed **B1 as 🔴** ("catastrophic
> whole-orchestrator billion-laughs DoS"). I then tested it harder and **was partly wrong**:
> CPython 3.12's libexpat (≥2.4) amplification-factor limit **blocks** the catastrophic case
> (a 10^8 payload raises `ParseError: limit on input amplification factor … breached`). What
> survives is a *bounded* residual + a doc-honesty gap. **B1 is revised to 🟡.** The original
> 🔴 reasoning is preserved in git (commit `97eede1`); see `correction_log`.

## Method

Reviewed `origin/claude/P5.1a-impl @ abe4d55` **without checking out** the branch (shared
worktree stayed on `main`; read via `git show`/`git diff origin/main...`). Ran the gates in
an **isolated detached worktree** (`git worktree add --detach`, `uv sync --all-extras`) so
the shared tree was never disturbed. Both lenses applied. Where I make a security or
correctness claim I **reproduced it empirically** (libexpat amplification test; a faithful
cursor-arithmetic simulation for the dead loop) rather than asserting from reading.

## Lens B — spine no-regression: **CLEAN** ✅ (the whole contract held)

Every ADR-041 D9 invariant verified against the living diff:

| Invariant | Result |
|---|---|
| `_execute_local_call` + gate (`tool_dispatch.py`) + `executor.py` byte-frozen | ✅ **0 diff lines** |
| `net_trust.py`, `local.py`, `event.py`, `room.py`, `dispatch.py`, `scoring.py`, `purposes.py` | ✅ **0 diff lines each** |
| `_write_and_turn` / `_writer_approve_helper` / `_countdown_sweeper` / `_post_intent` | ✅ untouched — `app.py` diff is **pure addition** (`0` deletions across all 22 files) |
| **D2 fork honored** — gate+executor reused verbatim, ~30-line scaffolding duplicated, interactive spine byte-untouched | ✅ structurally met *(but the duplicated copy carries Y1)* |
| No new `LLMPurpose` | ✅ `purposes.py` frozen; all 3 call sites `AGENT_RESPONSE`; `test_llm_purpose_is_agent_response` asserts it |
| `countdown_auto_fire=None` at both `process_tool_calls` sites | ✅ + `test_countdown_auto_fire_none` |
| `ThresholdConfig(8,5,0)` explicit, no code-level default | ✅ `runner.py:67` + test |
| No new `EventType`/`RoomType`; output = reversible `OBSERVATION` append, not gate-routed | ✅ `FREE_CHAT` reused |
| Backend-authoritative: `owner_user_id` server-derived from principal, never body | ✅ create-body `extra="forbid"`, no `owner_user_id` field; test present |
| Owner-private `/pipelines*` fail-closed | ✅ middleware allowlist `{/login,/health}` only; non-owner → **403**; list own-only; unauth → 401/403 — all tested |
| SSRF/sandbox floor reuse | ✅ web/rss via `build_ssrf_client`; file via `_check_path`; denied-IP + traversal + absolute-path **tested** |

Lens B is the strongest part of this slice — exemplary spine freeze + a genuinely
fail-closed, well-tested auth surface.

## Findings

### B1 — 🟡 **(revised 🔴→🟡)** route α/β — RSS XXE/billion-laughs floor: the DOCTYPE pre-scan is evadable, and the T6 doc describes a parser that does not exist *(converges with senior plan-vs-impl Y1)*

- **Mechanism.** `sources/rss.py:22-32` guards XML parsing with a pre-scan
  (`_check_no_entity_declarations`) over **only the first `_DOCTYPE_SCAN_BYTES = 8192`
  characters** (`rss.py:19,30`), then calls plain `ET.fromstring` (`rss.py:86`).
- **Evadable (confirmed).** XML grammar permits prolog comments before the DOCTYPE, so a
  `<!-- …>8192 bytes… -->` pushes `<!DOCTYPE` to byte ~9030; the scan reads `[:8192]`, misses
  it, and `ET.fromstring` then processes the DTD. (`xml.etree` *does* expand internal
  entities — verified: a 3-level chain expanded a title to 1000 chars; external `SYSTEM`
  entities are blocked by stdlib, so file-read XXE is safe.)
- **But the catastrophic case is capped (the correction).** CPython 3.12 ships libexpat ≥2.4
  with billion-laughs **amplification-factor protection**. Empirically: 10^4 and 10^6 payloads
  expand fully, but a 10^8 payload **raises** `ParseError: limit on input amplification factor
  (from DTD and entities) breached`. So unbounded GB expansion is **not** reachable; the
  practical residual is bounded (~tens of MB worst case, further bounded by the source
  `max_bytes`) — a transient writer-thread blip, **not** the whole-orchestrator DoS I first
  claimed.
- **What's genuinely wrong (still worth routing):** (a) **doc/impl honesty** —
  `docs/architecture/sources-vs-connectors.md` states parsing "uses `_SafeXMLParser` (blocking
  `EntityDeclHandler`)"; **no such class exists** — an audit reader is told a parser-handler
  enforces the floor when an evadable string pre-scan does. (b) The plan's literal T1 criterion
  ("billion-laughs/XXE **must not be reachable**") is **technically violated** for bounded
  expansion via the evasion, and the two tests only cover DOCTYPE-at-start, so the suite
  doesn't exercise the bypass.
- **Lean (you call):** **α** = switch to `defusedxml` (`forbid_dtd=True`) per the plan's own
  recommendation (robust, position-independent, portable) **and** correct the doc to describe
  the real mechanism — this both closes the bounded residual and makes the doc honest. A
  lighter **β** = keep stdlib but scan the *whole* document for DOCTYPE (not an 8 KiB window)
  + fix the doc. I lean α (it's what the doc already claims). *Senior independently filed this
  as Y1 with the same evasion; we converge on 🟡.*

### Y1 — 🟡 **route α/β — R0-A-unique (senior rated the loop working)** — the bounded re-dispatch loop in `_run_analyze_branch` is dead code

- **Evidence (empirically confirmed).** The interactive reference (`_write_and_turn`) sets
  `prev_pass_cursor` **once before pass 0** and reuses it, so iteration 1 sees pass-0's
  `TOOL_CALL`+`TOOL_RESULT`. The runner instead uses a separate `prev_cursor` for the pass-0
  window (`runner.py:143`) and **re-initializes** `prev_pass_cursor = len(events)` *after*
  pass-0 execute (`runner.py:166`) — so iteration 1's window `events[prev_pass_cursor:]` is
  **empty** → `new_tool_calls == []` → `break` (`runner.py:172-175`). A faithful simulation of
  the exact cursor arithmetic confirms **0 loop-body executions**; with the one-line fix
  (`prev_pass_cursor = prev_cursor`) the window holds 2 events and the body would run.
- **Consequence.** Every analyze branch is capped at pass 0 (one LLM call + one round of
  AUTO_EXECUTE). A branch can call a tool but can never see the result and follow up. ADR-041
  D2's "re-dispatch on result events, bounded by ADR-033 caps" is **inscribed but inert**. No
  test catches it (`test_countdown_auto_fire_none` can't distinguish dead vs live), and the
  senior plan-vs-impl read it as "a bounded forced-single-agent loop" (working) — so this is a
  net-new finding this round.
- **Not a safety issue** — fewer passes is strictly more conservative. It's a correctness +
  honesty divergence, and a clean illustration of the D2-vs-B tradeoff you routed: duplication
  bought a byte-frozen spine but gave the copy a bug the original doesn't have.
- **Lean (you call):** **α** = one-line fix + a multi-pass test; **β** = consciously accept
  single-pass analyze for the P5.1a safe primitive (simpler, less surface), **delete the dead
  loop**, and correct ADR-041 D2 + the runner docstring to "single bounded pass." Either is
  fine — dead code that reads as live + an unrealized ADR claim shouldn't stand silently.

### Y2 — 🟡 **route α/β** — `run_pipeline` hard-codes `succeeded=True`, so `pipeline_runs.status` is always `"completed"` — even when every source and branch fails

- **Evidence.** `runner.py:427` returns `succeeded=True` unconditionally. `app.py` maps
  `status = "completed" if result.succeeded else "failed"` → always `"completed"`;
  `test_run_pipeline_returns_run_result` documents a failing source still yielding
  `succeeded=True`. The store has a `running → update_pipeline_run_status` lifecycle (tested)
  but the endpoint never uses it — it writes one terminal row *after* the run, so an in-flight
  run is invisible and a run that *raises* writes **no row** + 500s. *(Senior noted the same in
  green-notes; I rate it route-worthy because the index is the T2 audit surface.)*
- **Lean (you call):** **α** = make `succeeded` reflect reality (`branches_succeeded > 0`, or a
  `running`-then-update row) ; **β** = rename `succeeded → completed` and accept that semantics
  for P5.1a. Either resolves the mislabel.

### Nits (🟢 — recording)

- **N1** `output_config.room_prefix` (schema + example) is **unused** — runner names the room
  `room_<uuid>`. Dead config advertised in the example.
- **N2** Dual `run_id` — `store.create_pipeline_run` mints the canonical `prun_…` (returned),
  while `runner.run_pipeline` mints a *different* `prun_…` embedded in the run-anchor
  `OBSERVATION`; index→room-events can't join by `run_id` (`room_id` still works). *(= senior
  Y2; senior rated it 🟡 — fine to bundle into the same routing round.)*
- **N3** Reduce wraps **branch outputs** with the "Source data (fetched this run …)" header —
  defensively fine, label mildly inaccurate. Cosmetic.

## Cross-review map (for your synthesis — senior plan-vs-impl + R0-A; R0-B-on-impl still pending)

| Finding | senior plan-vs-impl | R0-A (me) | Convergence |
|---|---|---|---|
| RSS XXE floor (evadable scan + phantom `_SafeXMLParser` doc) | 🟡 Y1 | 🟡 B1 (revised from 🔴) | **agree 🟡** — route α(defusedxml+doc) |
| Dead re-dispatch loop | rated working ("bounded loop") | 🟡 Y1 | **R0-A-unique** — senior missed it |
| `succeeded`=True always | green-note | 🟡 Y2 | overlap, I rate higher |
| Dual `run_id` | 🟡 Y2 | 🟢 N2 | overlap, senior rates higher |

## What the architect does next

1. **B1 / senior-Y1** (RSS floor) — α (`defusedxml` + correct the doc) vs β (whole-doc DOCTYPE
   scan + doc fix). I lean α. *Not* a 🔴 after the libexpat retest, but the doc misrepresents a
   security floor — worth closing.
2. **Y1** (dead re-dispatch loop) — α (fix the cursor) vs β (accept single-pass + delete loop +
   correct ADR-041 D2). My R0-A-unique find; your call.
3. **Y2** (truthful `succeeded`) + N2 (dual `run_id`) — bundle; α-cleanup or β-defer.
4. **ADR-041 Accept** stays yours (RC-3). This review is input; it now carries **no 🔴**.

Routing nothing here — surface-only, per role. Awaiting your α/β string (and R0-B-on-impl,
still running, before you synthesize).
