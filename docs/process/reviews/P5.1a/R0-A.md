---
task_id: P5.1a
stage: R0-A (impl)
reviewer: architect-partner
verdict: needs_architect
must_fix_before_accept: ["B1"]
findings_count: 3
findings: ["B1 (🔴 security must-fix): billion-laughs DoS reachable in RSS parser", "Y1 (🟡): bounded re-dispatch loop is dead code", "Y2 (🟡): succeeded hard-coded True → run status always 'completed'"]
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
date: "2026-06-09"
---

# R0-A (impl) — P5.1a deterministic analysis pipeline

> **⚠️ Verdict `needs_architect` — and one finding is a hard security stop.** The
> constitutional spine and the entire Lens-B contract are **clean** (byte-frozen,
> independently verified) and all three gates are **green**. But **B1 is a confirmed,
> exploitable billion-laughs DoS** on the one greenfield attack surface the plan flagged
> for adversarial testing — **do NOT Accept the impl until B1 is fixed** (recommend α →
> `defusedxml`). Y1/Y2 are genuine α/β routing decisions. I surface + lean; you route.

## Method

Reviewed `origin/claude/P5.1a-impl @ abe4d55` **without checking out** the branch (shared
worktree stayed on `main`; read via `git show`/`git diff origin/main...`). Ran the gates in
an **isolated detached worktree** (`git worktree add --detach`, `uv sync --all-extras`) so
the shared tree was never disturbed. Both ratified lenses applied: **A** = pipeline safety +
determinism + SSRF/XXE/sandbox floors + no over-authorized output; **B** = spine
no-regression. I also **empirically reproduced** B1 (Python 3.12.3) rather than asserting it.

## Lens B — spine no-regression: **CLEAN** ✅ (the whole contract held)

Every ADR-041 D9 invariant verified against the living diff:

| Invariant | Result |
|---|---|
| `_execute_local_call` + gate (`tool_dispatch.py`) + `executor.py` byte-frozen | ✅ **0 diff lines** |
| `net_trust.py`, `local.py`, `event.py`, `room.py`, `dispatch.py`, `scoring.py`, `purposes.py` | ✅ **0 diff lines each** |
| `_write_and_turn` / `_writer_approve_helper` / `_countdown_sweeper` / `_post_intent` | ✅ untouched — `app.py` diff is **pure addition** (models before `_writer_approve_helper`; routes appended; `0` deletions across all 22 files) |
| **D2 fork honored** — gate+executor reused verbatim, ~30-line scaffolding duplicated, interactive spine byte-untouched | ✅ structurally met *(but the duplicated copy carries Y1 — see below)* |
| No new `LLMPurpose` | ✅ `purposes.py` frozen; all 3 call sites `AGENT_RESPONSE`; `test_llm_purpose_is_agent_response` asserts it |
| `countdown_auto_fire=None` at both `process_tool_calls` sites (no headless actuation) | ✅ `runner.py:160,196` + `test_countdown_auto_fire_none` |
| `ThresholdConfig(8,5,0)` explicit, no code-level default | ✅ `runner.py:67` + test |
| No new `EventType` / `RoomType`; output = reversible `OBSERVATION` append, not gate-routed | ✅ `FREE_CHAT` reused; `test_output_room_is_free_chat` |
| Backend-authoritative: `owner_user_id` server-derived from `request.state.principal`, never body | ✅ create-body is `extra="forbid"` with no `owner_user_id` field; `test_create_pipeline_owner_from_principal` |
| Owner-private `/pipelines*` fail-closed | ✅ middleware allowlist is `{/login,/health}` only; non-owner → **403** on get/run; list own-only; unauth → 401/403 — all tested |
| SSRF/sandbox floor reuse | ✅ web/rss via `build_ssrf_client`; file via `_check_path`; denied-IP + traversal + absolute-path **tested, not asserted** |

Lens B is the strongest part of this slice — the spine freeze is exemplary and the auth
surface is genuinely fail-closed and well-tested.

## Findings

### B1 — 🔴 **security must-fix (recommend α)** — billion-laughs DoS is reachable in the RSS parser; the DOCTYPE byte-scan guard is evadable; and the docs claim a defense that isn't in the code

- **Mechanism.** `sources/rss.py` defends XML parsing with a hand-rolled pre-scan
  (`_check_no_entity_declarations`, `rss.py:22-32`) that inspects only **the first
  `_DOCTYPE_SCAN_BYTES = 8192` characters** (`rss.py:19,30`) for `<!DOCTYPE`/`<!ENTITY`,
  then calls plain `ET.fromstring` (`rss.py:86`). The comment deliberately rejects the
  expat entity-handler approach as "not portable."
- **Confirmed reachable (empirical, Py 3.12.3):**
  1. `xml.etree.ElementTree` **expands internal entities** — a 3-level `&a;→&b;→&c;` chain
     expanded a `<title>` to 1000 chars. (External `SYSTEM` entities *are* blocked by stdlib
     — "undefined entity" — so classic file-read XXE is safe; the **billion-laughs** vector
     is not.)
  2. The 8192-char window is **evadable**: XML grammar permits comments in the prolog before
     the DOCTYPE, so a `<!-- …9000 bytes… -->` pushes `<!DOCTYPE` to byte 9030. The guard
     scans `[:8192]`, returns **False** (misses it), and `ET.fromstring` then processes the
     DTD → entity expansion. A `&lol9;`-style payload (<1 KB on the wire — `max_bytes` does
     **not** bound *expansion*) blows up to gigabytes in expat.
- **Blast radius.** The run executes on `writer_executor` (`max_workers=1`). A billion-laughs
  expansion there is **whole-orchestrator DoS** — it stalls every interactive turn too, not
  just the pipeline. The feed *content* is third-party-controlled (owner configures a URL;
  whoever serves it controls the bytes), and a malicious feed on a public host sails through
  the SSRF floor.
- **Acceptance criterion violated.** T1 / ADR-041 D4 require "billion-laughs/XXE **must not be
  reachable**" and explicitly recommend `defusedxml`. The two tests
  (`test_rss_parse_xxe_entity_blocked`, `test_rss_parse_billion_laughs_blocked`) only cover
  **DOCTYPE-at-the-start** (which the scan catches), so the suite gives false assurance — the
  padded-prolog evasion is untested *and* unguarded.
- **Doc/impl mismatch (compounds it).** `docs/architecture/sources-vs-connectors.md` (T6)
  states parsing "uses `_SafeXMLParser` (blocking `EntityDeclHandler`) to prevent XXE …and
  billion-laughs." **No such class exists** in `rss.py`. The documented (and genuinely robust,
  position-independent) mechanism was described but not built; the shipped byte-scan is the
  evadable one.
- **Lean (α — fix; this is not a β-defer candidate):** swap to `defusedxml` (`forbid_dtd=True`)
  per the plan's own recommendation — robust, portable, and it makes the docs' claim true. (An
  `EntityDeclHandler`-based parser or a whole-document DOCTYPE scan would also close it, but
  `defusedxml` is the plan-sanctioned choice.) A safe-by-design slice should not ship with a
  live unbounded-expansion path on the single writer. **Recommend you not Accept until fixed.**

### Y1 — 🟡 **route α/β** — the bounded re-dispatch loop in `_run_analyze_branch` is dead code (no analyze branch ever re-dispatches)

- **Evidence.** The interactive reference (`_write_and_turn`) sets `prev_pass_cursor` **once,
  before pass 0**, and reuses that same cursor as the pass-0 window *and* the loop's first
  look-back — so iteration 1 sees pass-0's `TOOL_CALL`+`TOOL_RESULT` and can re-dispatch. The
  runner instead uses a **separate** variable `prev_cursor` for the pass-0 window
  (`runner.py:143`) and then **re-initializes** `prev_pass_cursor = len(events)` *after*
  pass-0 execute (`runner.py:166`), immediately before the loop. So on iteration 1,
  `events[prev_pass_cursor:]` is **empty** → `new_tool_calls == []` → `break`
  (`runner.py:172-175`). The loop body is unreachable; the branch is capped at pass 0 (one LLM
  call + one round of AUTO_EXECUTE).
- **Consequence.** A branch can call a tool once but can never see the result and follow up.
  ADR-041 D2's "re-dispatch on result events, bounded by the ADR-033 caps" is **inscribed but
  inert**. No test catches it (`test_countdown_auto_fire_none` can't distinguish dead vs live).
- **Not a safety issue** — fewer passes is strictly more conservative; nothing extra executes.
  This is a correctness/honesty divergence, and a nice illustration of the D2-vs-B tradeoff you
  routed: duplication bought a byte-frozen spine but gave the copy an independent bug the
  original doesn't have.
- **Lean (you call):** **α** = one-line fix (`prev_pass_cursor = prev_cursor`, mirroring the
  interactive loop) + a multi-pass test; **β** = consciously accept single-pass analyze for the
  P5.1a safe primitive (simpler, less surface), **delete the dead loop**, and correct ADR-041
  D2 + the runner docstring to say "single bounded pass." Either is fine — but dead code that
  reads as live + an unrealized ADR claim should not stand silently.

### Y2 — 🟡 **route α/β** — `run_pipeline` hard-codes `succeeded=True`, so `pipeline_runs.status` is always `"completed"` — even when every source and every branch fails

- **Evidence.** `runner.py:427` returns `succeeded=True` unconditionally (no path sets False).
  `app.py` maps `status = "completed" if result.succeeded else "failed"` → always `"completed"`.
  `test_run_pipeline_returns_run_result` documents this: a failing web source still yields
  `succeeded=True`. The store has a `running → update_pipeline_run_status` lifecycle
  (`store.py`, tested), but the endpoint **never uses it** — it writes one terminal row *after*
  the run returns, so an in-flight run is invisible and a run that *raises* writes **no row** +
  500s.
- **Consequence.** The run-status surface can't distinguish success from total failure
  (observability/honesty gap; no safety impact). The `branches_succeeded/failed` counts carry
  the real story, making the top-level boolean actively misleading.
- **Lean (you call):** **α** = make `succeeded` reflect reality (e.g. `branches_succeeded > 0`,
  or write a `"running"` row first then update) ; **β** = rename `succeeded → completed`
  ("ran to completion without crashing") and accept that for P5.1a. Either resolves the
  mislabel; the current always-True shouldn't ship unflagged.

### Nits (🟢 — recording, no routing needed)

- **N1** `output_config.room_prefix` (schema + example fixture) is **unused** — the runner names
  the room `room_<uuid>`, ignoring the prefix. Dead config advertised in the example.
- **N2** Two `run_id`s per run: `store.create_pipeline_run` mints the canonical `prun_…` (used in
  the response), while `runner.run_pipeline` mints a **different** `prun_…` embedded in the
  run-anchor `OBSERVATION`. The index row's `run_id` ≠ the room anchor's → can't join
  index→room-events by `run_id` (the `room_id` join still works). Low traceability wart.
- **N3** The reduce call wraps **branch outputs** with the "Source data (fetched this run …)"
  header — defensively fine (they're downstream of untrusted data) but the "fetched this run"
  label is inaccurate for LLM-generated branch text. Cosmetic.

## Strengths worth recording

- The **spine byte-freeze is exemplary** — 9 constitution-critical modules at exactly 0 diff,
  pure-addition `app.py`, the D2 reuse done as designed.
- **Auth is genuinely fail-closed**: owner-derived-from-principal, owner-private 403, own-only
  list — and *all of it tested* (non-owner, unauth, cross-user).
- **SSRF + file-sandbox floors tested, not asserted** (denied-IP feed URL, traversal, absolute
  path) — exactly the §4 forcing function.
- The `external`-XXE half is correctly closed (stdlib blocks `SYSTEM` entities); the gap is
  narrowly the internal-expansion/evasion path (B1).
- Gates independently reproduced green (ruff + mypy 297 files + full pytest).

## What the architect does next

1. **B1 — 🔴 do not Accept until fixed.** My read: the only sane route is **α** (`defusedxml`).
   Confirm.
2. **Y1** — α (fix the cursor → live re-dispatch) vs β (accept single-pass + delete dead loop +
   correct ADR-041 D2). Your call.
3. **Y2** — α (truthful `succeeded`) vs β (rename to `completed`). Your call.
4. **ADR-041 Accept** stays yours (RC-3). This review is input, not a substitute — and it
   carries one hard blocker (B1).

Routing nothing here — surface-only, per role. Awaiting your α/β string.
