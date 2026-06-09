---
task_id: P5.1a
stage: R0-A (impl)
reviewer: architect-partner
verdict: needs_architect
cycle: 2
supersedes: "cycle-1 R0-A (needs_architect; B1 RSS-XXE + Y1 dead loop + Y2 succeeded)"
findings_count: 1
findings: ["F-deadloop-test (🟡): the F-deadloop CODE fix is correct and empirically restores ADR-041 D2 multi-pass — but the shipped regression test is VACUOUS (passes identically on fixed and reverted code), so the routed 'add a multi-pass test' mandate is functionally unmet"]
resolved_from_cycle1: ["B1 (RSS billion-laughs) → defusedxml(forbid_dtd=True), empirically blocks the comment-padded-prolog evasion; doc corrected; phantom _SafeXMLParser gone", "F-deadloop CODE (dead re-dispatch loop) → prev_pass_cursor=prev_cursor, empirically live (3 LLM calls w/ a real tool)", "F-succeeded → succeeded=branches_succeeded>0, valid all-fail/partial tests", "F-runid → single caller-supplied run_id across runner/store", "F-ownerparam → build_user_author(owner_user_id) anchors the run"]
lenses: ["A: pipeline safety + determinism", "B: spine no-regression"]
reviewed_branch: "origin/claude/P5.1a-impl @ 267da97 (cycle-2 rework, +252 / -111, 11 files)"
reviewed:
  - "src/orchestrator/sources/rss.py (defusedxml swap)"
  - "src/orchestrator/pipeline/{runner,store}.py + api/app.py (4 F-fixes)"
  - "pyproject.toml + uv.lock (defusedxml>=0.7 + mypy override)"
  - "docs/architecture/sources-vs-connectors.md (B1 doc)"
  - "tests/pipeline/{test_runner,test_store}.py + tests/sources/test_sources.py (+195)"
against:
  - "docs/process/reviews/P5.1a/architect-routing-on-impl.md (the all-α mandate)"
  - "docs/decisions/ADR-041-deterministic-analysis-pipeline.md (D2/D4/D9)"
gates_independently_run: "isolated detached worktree @ 267da97, uv sync --all-extras (defusedxml 0.7.1)"
gates_result: "ruff: All checks passed ✅ | mypy: Success, no issues in 297 source files ✅ | pytest: 2352 passed, exit 0 ✅ (zero failure markers; the only thread-warning is the pre-existing by-design net_trust DNS-timeout test — net_trust is byte-frozen)"
empirical_log: "B1: reproduced the cycle-1 padded-prolog billion-laughs (DOCTYPE at byte 9009 > old 8192 window) → now BLOCKED by defusedxml; benign feed still parses; confirmed old 8 KiB scan was genuinely evadable + old stdlib path expanded the entity. F-deadloop: built a real-tool probe (get_current_time, reversibility=10) — FIXED code = 3 LLM calls + a pass-1 re-dispatch utterance (LIVE); REVERTED one-line = 2 calls, no pass-1 (DEAD). The shipped test uses read_file with empty tools registry → autonomy_refusal (no TOOL_CALL) → loop breaks at guard 1 → test passes on BOTH fixed and reverted code."
date: "2026-06-09"
---

# R0-A (impl) — P5.1a cycle-2 re-review (all-α rework)

> **This file supersedes the cycle-1 R0-A** (verdict `needs_architect`; B1 RSS-XXE +
> Y1 dead loop + Y2 succeeded). The cycle-2 scope is the all-α rework commit `267da97`
> routed by `architect-routing-on-impl.md`.
>
> **Verdict `needs_architect` — 1×🟡, no 🔴, no spine/safety/regression.** Four of the
> five routed fixes are **fully resolved and empirically verified** (B1, F-runid,
> F-succeeded, F-ownerparam). The fifth, **F-deadloop**, has a **correct code fix that I
> empirically proved restores ADR-041 D2 multi-pass** — but the *test* shipped to guard
> it is **vacuous** (it passes identically on the fixed and the reverted code). That is
> the single thing needing your α/β call. Gates are green (2352 passed); the
> constitutional spine and the whole Lens-B contract are byte-frozen.

## Method

Reviewed `origin/claude/P5.1a-impl @ 267da97` **without checking out** the branch (shared
worktree stayed on `main`; read via `git show`/`git diff origin/main...`). Ran gates in an
**isolated detached worktree** (`git worktree add --detach`, `uv sync --all-extras`). Per
the dispatch I did **not** trust the tests — I reproduced B1 and F-deadloop empirically with
standalone probes (billion-laughs payloads; a real auto-executing tool; and a
revert-the-fix-and-rerun experiment in the disposable worktree).

## Per-fix verification

| # | Routed fix | Code | Test | Empirical check |
|---|---|---|---|---|
| **B1** | defusedxml(forbid_dtd) + doc + padded test | ✅ `rss.py:72-73` `_defused_ET.fromstring(…, forbid_dtd=True)` catches `DTDForbidden`/`EntitiesForbidden` → `SourceReadError` | ✅ `test_sources.py` padded-prolog test valid | ✅ **reproduced & BLOCKED** |
| **F-runid** | single caller-supplied run_id | ✅ `store.py:141,148` accepts `run_id`; `app.py:1692` threads `result.run_id` | ✅ store + runner unit tests; 🟢 nit below | ✅ row id == anchor run_id |
| **F-deadloop** | `prev_pass_cursor=prev_cursor` + multi-pass test | ✅ `runner.py:170` (correct; `prev_cursor` is the pre-pass-0 snapshot `runner.py:144`) | 🟡 **VACUOUS** (finding below) | ✅ fixed=LIVE(3) / reverted=DEAD(2) |
| **F-succeeded** | `succeeded=branches_succeeded>0` | ✅ `runner.py:433` | ✅ all-fail + partial tests valid (assert real counts) | ✅ pass |
| **F-ownerparam** | use `owner_user_id` in runner | ✅ `runner.py:281` `build_user_author(owner_user_id)` | ✅ anchor-author test valid (`user:alice`) | ✅ event[0] author=`user:alice` |

### B1 — ✅ resolved (empirically verified)

I rebuilt the exact cycle-1 evasion — a 9000-byte prolog comment pushing `<!DOCTYPE` to
byte **9009**, past the old `_DOCTYPE_SCAN_BYTES = 8192` window — and ran it through the new
`_parse_feed`:

- padded-prolog billion-laughs → **`SourceReadError` (BLOCKED)** ✅
- plain DOCTYPE-at-start billion-laughs → **BLOCKED** ✅
- benign RSS feed → **parses** (no false positive) ✅
- confirmed the old 8 KiB scan *would have missed* the padded DOCTYPE (`<!DOCTYPE in head == False`) and the old stdlib `ET.fromstring` *did* expand the entity — i.e. the hole was real, and `forbid_dtd=True` closes it **position-independently** exactly as the corrected
  `sources-vs-connectors.md` now claims. The phantom `_SafeXMLParser` /
  `_check_no_entity_declarations` / `_DOCTYPE_SCAN_BYTES` symbols are gone from `src` and docs.

## The one finding

### F-deadloop-test — 🟡 **route α/β** — the code fix is correct, but the regression test that was supposed to guard it is vacuous

**The code is right.** `runner.py:170` sets `prev_pass_cursor = prev_cursor`, where
`prev_cursor` (`runner.py:144`) is the snapshot taken *before* pass-0 `process_tool_calls`,
so the first loop window `events[prev_cursor:]` holds the pass-0 `TOOL_CALL` + `TOOL_RESULT`.
I proved this with a **real auto-executing tool** (`get_current_time`, `reversibility=10`):

```
FIXED code      → 3 LLM calls; events: …tool_call, tool_result, UTTERANCE 'resp2' (pass-1!), reduce
REVERTED 1-line → 2 LLM calls; events: …tool_call, tool_result, reduce  (no pass-1)  ← cycle-1 bug
```

So F-deadloop genuinely **restores ADR-041 D2** at runtime. ✅

**The test does not test it.** `test_analyze_branch_multi_pass_redispatch`
(`test_runner.py:453`) makes pass-0 emit a **`read_file`** tool call with the helper's
**empty `tools={}` registry** (`test_runner.py:471`, `_make_deps`). With no registry entry the
gate raises an **`autonomy_refusal`** — *no `TOOL_CALL` event is ever appended* — so the
re-dispatch loop breaks at its **first** guard (`runner.py:178` `if not new_tool_calls:
break`) before the cursor is ever read. The assertion `re_dispatch_executed`
(`test_runner.py:481`) is set in the `if call_count == 2` branch — and on this scenario
**call 2 is the reduce call**, not a re-dispatch. I confirmed the consequence directly:

- shipped test on **fixed** code → passes
- shipped test on **reverted** (cycle-1-bug) code → **also passes** (exit 0)

A test that passes whether or not the bug is present cannot guard the bug. This is the
cycle-1 theme recurring: cycle-1 R0-A said *"no test catches it"*; the rework added a test
that **still** doesn't. The architect's routing for F-deadloop=α explicitly required *"Add a
multi-pass analyze test"* — the code half is delivered, the test half is not effective.

- **Not a 🔴 / not a safety issue** — the product code is correct (verified above); the gap
  is a future-regression guard, not current behaviour.
- **Lean (you call):** **α** = make the test use a real AUTO tool (e.g.
  `tools={"get_current_time": ToolMeta(reversibility=10)}` + `build_local_tool_registry`) and
  assert the re-dispatch actually ran (router call-count == 3, or a pass-1 utterance after the
  `tool_result`) — my probe is essentially the corrected test, cheap to land. **β** = accept
  this cycle (R0-A has independently proven the code correct) and book a retro candidate on
  *"vacuous regression guard via the empty-registry test helper"* so it isn't reintroduced. I
  lean **α** (the routed mandate asked for a working test), but β is defensible since the
  runtime behaviour is verified.

## Lens B — spine no-regression: **CLEAN** ✅

- `_execute_local_call` + gate + `executor.py` + `net_trust.py` + `local.py` + `event.py` +
  `room.py` + `purposes.py` + `scoring.py` → **0 diff lines** across the full
  `origin/main...267da97` range.
- **No new `LLMPurpose`** — only `AGENT_RESPONSE` at the 3 runner call sites; sources have none.
- **No ADR-041 amendment.** (The lone ADR-019 `+1` line is a benign cycle-1 cross-reference
  note — name-collision pointer — already reviewed; not a decision change.)
- `build_user_author` (`event.py:460`) is **pre-existing** — F-ownerparam imports it, it does
  not modify the spine.
- Process note satisfied: the stray `R0-B-cross-family.md` was `git rm`'d from the impl branch;
  canonical `R0-B.md` lives on main.

## Nits (🟢 — recording, not routing)

- **N1 (F-runid)** No API-level end-to-end correlation assertion: `test_pipelines.py:309-312`
  only checks the response `run_id` exists + `prun_` prefix. The store + runner unit tests
  bracket the one-line `app.py:1692` wiring, so the fix is correct, but nothing asserts the
  *returned* run_id equals the in-room anchor run_id. Cheap to add alongside any α.
- **N2 (F-ownerparam)** The run **anchor** is now `user:alice` while the branch-trigger and
  output events remain `agent:pipeline`. Fine (the param is genuinely used now), mildly mixed
  attribution; cosmetic.

## Cross-review map (for your synthesis)

All three cycle-2 reviews are in: **senior plan-vs-impl `clean`**, **R0-B cross-family
`clean` (0🔴 0🟡 7🟢, `c8e7046`)**, and this R0-A `needs_architect` (1🟡). The
`requires_cross_family_review` obligation is satisfied.

| Finding | senior pvi (cy-2) | R0-B cross-family (cy-2) | R0-A (me, cy-2) | Convergence |
|---|---|---|---|---|
| B1 / F-runid / F-succeeded / F-ownerparam | clean | clean (7🟢 nits) | ✅ resolved (empirical) | **agree** |
| F-deadloop **code** | clean ("prev_cursor is pre-pass-0 snapshot") | clean | ✅ correct (empirical: 3 vs 2 calls) | **agree** |
| F-deadloop **test** | took the added test at face value | took the added test at face value | 🟡 **vacuous** (passes on fixed AND reverted) | **R0-A-unique** — dual-lens catch |

Both other lenses cleared the rework; the lone divergence is my empirically-reproduced
test-efficacy gap — the **same shape as cycle-1**, where R0-B's N7 cleared XXE ✅ and R0-A
reproduced the evasion. Per the dual-lens precedent (`architect-routing-on-impl.md` §"why B1
is a hard stop"), **weight the reproduced result.** Here it is *not* a hard stop — the code is
correct — but it is the one thing to route.

## What the architect does next

1. **F-deadloop-test** — α (harden the test with a real AUTO tool; I can hand the exact
   recipe) vs β (accept — code is R0-A-verified — + retro candidate). I lean α. **This is the
   only routing call.**
2. **N1 / N2** — bundle into any α as cleanup, or leave.
3. **ADR-041 Accept** stays yours (RC-3). This review carries **no 🔴**; 4/5 fixes are clean,
   the 5th's runtime is correct.

Routing nothing here — surface-only, per role. Awaiting your α/β.
