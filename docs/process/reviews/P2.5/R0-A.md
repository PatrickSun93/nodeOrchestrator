---
task_id: P2.5
round: R0-A
verdict: needs_architect
findings_count:
  red: 1
  yellow: 2
  green: 10
verdict_history:
  - verdict: needs_architect
    at_commit: 203c606
    findings_count: { red: 1, yellow: 2, green: 10 }
    note: initial R0-A (impl-stage, in-family). Constitutional core CLEAN + actively verified (both AST guards proven to fail on real-source planted bypasses; selection LLM-free; no routing/judgment LLMPurpose). All 4 plan-stage α-absorptions faithfully implemented. R1 (🔴) — the mandatory mypy --strict gate is RED (5 test-only errors in tests/reentry/test_schema.py) despite the landing claiming gates green; blocks merge, α-fix. Y1/Y2 low.
---

# P2.5 R0-A (impl-stage, in-family)

| Field | Value |
|---|---|
| Commit reviewed | `203c606` (`origin/claude/P2.5-impl` tip; impl atomics P2.5-2..6) |
| ADR | ADR-021 **Accepted** (PR #35 merged); plan-stage 4🟡 all α-absorbed |
| Reviewed in | isolated git worktree at `203c606` (shared-tree churn precaution) |
| Gates (run in worktree) | ruff ✅ · ruff-format ✅ (155 files) · pytest ✅ · **`mypy --strict` ❌ — 5 errors (R1)** |

## Verdict: needs_architect

**The constitutional core is clean and I verified it actively — the thing this milestone most needed to get right is right.** Selection/ranking/ordering is pure code (`assemble_reentry` imports no `llm/`); the two LLM calls (`REENTRY_DIGEST_RENDER`, `ARCHIVE_SUMMARY_RENDER`) are both content-gen over code-assembled facts; `purposes.py` still has **no routing/judgment purpose**. I **planted real-source bypasses** and confirmed both AST guards fail (not vacuous): guard (i) caught a `reentry` import planted in `llm/` (proving the Y2 four-layer coverage works), guard (ii) caught an `llm_router` reference planted inside `assemble_reentry`. All four plan-stage α-absorptions landed faithfully.

**But one 🔴 blocks merge:** the mandatory **`mypy --strict` gate is RED** — 5 errors in `tests/reentry/test_schema.py` — even though the landing commit + the state advance imply gates were green. `src/` is type-clean (69 files); the errors are test-only and runtime-correct (pytest passes), but the canonical `uv run mypy` (config `files=["src","tests"]`) exits 1, so the impl **cannot merge as-is**. Plus Y1 — a shadowed duplicate-name test silently drops a frozen-invariant assertion. Both are localized to `test_schema.py`; everything else is clean. → route R1 (+Y1) **α-fix this cycle**.

## The five named checks

| # | Check | Verdict | Evidence |
|---|---|---|---|
| 1 | LLM confined to phrasing — no creep into selection/ranking/judgment; both content-gen purposes are content-gen; no routing/judgment purpose | **clean (G1)** | `digest.py` imports no `llm/`; `render_reentry_prose` serializes the **already-frozen** digest + "add no facts" system prompt; `generate_and_record_archive` generates the archive's *semantic* fields from **code-derived** `decision_log`/duration (ADR-020 D3 narrative content-gen). `purposes.py`: 8 values, all content-gen / candidate-to-human-pool — **none routing/judgment**. |
| 2 | Both AST guards fail on a planted bypass (not vacuous); LLM-free-selection by named function; no-import covers 4 upstream layers | **clean (G2) — actively proven** | **Planted & confirmed:** guard (i) `from orchestrator.reentry.digest import …` in `llm/purposes.py` → **FAIL** (`line 24 … import`); guard (ii) `llm_router` Name inside `assemble_reentry` → **FAIL** (`forbidden Name 'llm_router' in selection fn 'assemble_reentry'`); both PASS post-revert. `_UPSTREAM_LAYERS=[core,memory,derived,llm]`; `_SELECTION_FUNS={assemble_reentry,derive_query_tags}`. Ships its own discriminating self-tests too. |
| 3 | new_since_leave first-visit = [] | **clean (G3); Y2 (precision)** | `digest.py:75-76` — the diff is gated by `if last_seen_ts is not None`, so first visit → `[]`. e2e `test_scenario_first_visit_no_marker_no_crash` asserts `new_since_leave == []` + `last_seen_ts is None` discriminatingly. |
| 4 | Q2 decision_trace / Q3 5-surface / Q5 discriminating | **clean (G8/G10)** | **Q2** — N/A stated with reason (P2.5.md:128: deterministic composition, not a scored decision; the trace is the query). **Q3** — handoff updated (11 reentry mentions). **Q5** — e2e asserts post-marker facts present **and** pre-marker absent by stable label (`"new question after leave"` in / `"session start"` not in), determinism across runs, render purpose — RC-25-discriminating. |
| 5 | derive_query_tags code-deterministic, feeds non-empty tags | **clean (G4)** | `derive_query_tags` = `list_room_topic_tags` (code union of the room's hypothesis tags); `assemble_reentry` calls `lookup_verified_knowledge(tags, …) if tags else []` — **never passes `[]`** (which `lookup.py:33` raises on). |

## Findings

### R1 🔴 — `mypy --strict` (mandatory gate) is RED: 5 errors in `tests/reentry/test_schema.py`

The canonical `uv run mypy` (pyproject `[tool.mypy] strict=true, files=["src","tests"]`) **exits 1**:
```
tests/reentry/test_schema.py:49: error: Unused "type: ignore" comment  [unused-ignore]
tests/reentry/test_schema.py:81: error: Unused "type: ignore" comment  [unused-ignore]
tests/reentry/test_schema.py:82: error: Argument "fact_type" … incompatible type "Literal['hypothesis']" … [arg-type]
tests/reentry/test_schema.py:98: error: Unused "type: ignore" comment  [unused-ignore]
tests/reentry/test_schema.py:161: error: Unused "type: ignore" comment  [unused-ignore]
```
Two distinct mistakes: (a) **3× unused `# type: ignore[misc]`** on frozen-mutation tests (lines 49/98/161) — pydantic frozen-attr mutation is a *runtime* `ValidationError`, not a mypy error, so the ignores are unnecessary and trip `warn_unused_ignores`; (b) the **invalid-literal test** has the ignore on the wrong line/code — `# type: ignore[call-arg]` on line 81 (unused) while the real `[arg-type]` error on line 82 (`fact_type="hypothesis"`) is uncovered. `src/` is clean (69 files); these are test-only and runtime-correct (pytest green) — but **`mypy --strict` is mandatory** (contributing.md; the config includes `tests`), and at P2.4 my identical `mypy --strict src tests` run was clean, so **P2.5 introduced this regression**. The landing claimed gates green; this is the discrepancy R0-A exists to catch.

**Lean:** α-fix this cycle — remove the 3 unused `[misc]` ignores; fix the invalid-literal test to `fact_type="hypothesis",  # type: ignore[arg-type]` (and drop the line-81 `[call-arg]`). Mechanical; no design change. **The impl cannot merge until `uv run mypy` is green.**

### Y1 🟡 — duplicate test-method name silently drops a frozen-invariant test

`tests/reentry/test_schema.py` defines **`def test_frozen_raises_on_mutation` twice in the same class** (~lines 155 + 159): the first asserts `ReentryDigest.last_seen_ts` is frozen, the second asserts `ReentryResult.prose` is frozen. Python keeps the **last** definition, so the **ReentryDigest** frozen test is shadowed and **never runs** — a "test that can't fail because it never executes" (RC-25 family). The §6 frozen invariant for `ReentryDigest` is claimed-covered but isn't. **Lean:** α-fix — rename one (e.g. `test_reentry_result_frozen_raises_on_mutation`). (Both Y1 and R1 are in `test_schema.py` — that one file warrants a careful pass; the rest of the suite is well-written.)

### Y2 🟡 (low) — `new_since_leave` precision: sort-tie determinism + all-events granularity

Two low refinements on `assemble_reentry`'s diff (`digest.py:75-100`): (a) **sort key is `occurred_at` only** — ties break on insertion order (VK-then-events + input `events` order); for the project's determinism discipline, add a secondary key (`ref_id`) so the order is scan-order-independent even on equal timestamps (the e2e uses distinct ts, so it's latent). (b) the diff includes **every** room event after the marker (no type filter), so raw utterances/system events surface as "new since you left" — deterministic + code (no constitutional issue), but possibly noisy; consider scoping to decision-class events (mirror `produce_decision_log`'s filter). **Lean:** α (cheap) or β (defer (b) as a UX-tuning call) — your call; neither is constitutional.

## What holds — verified clean (G1–G10)

- **G1** Principle-5/11 core: selection LLM-free; both renders content-gen over code-assembled facts; no routing/judgment purpose (`purposes.py`).
- **G2** both AST guards **actively proven** discriminating on real-source plants (4-layer no-import; by-named-function LLM-free) + shipped self-tests.
- **G3** first-visit `new_since_leave == []` (code guard + discriminating e2e).
- **G4** `derive_query_tags` code-deterministic; never passes `[]` to `lookup`.
- **G5** `record_leave_marker` uses atomic `INSERT OR REPLACE` — **no RC-26 read-modify-write race** (cleaner than the P2.4 preference upsert it cites).
- **G6** `ReentryDigest`/`ReentryResult`/`NewSinceLeaveItem` frozen + `extra="forbid"`; `new_since_leave` is a **typed** `NewSinceLeaveItem` (Y3-plan absorbed), `generated_at` clock-injected.
- **G7** `ARCHIVE_SUMMARY_RENDER` is content-gen (semantic fields from code-derived facts; graceful JSON-parse fallback); confined to `leave.py`, not a selection function.
- **G8** e2e is cross-room + discriminating (RC-25): post-marker present **and** pre-marker absent, determinism, render purpose, graceful empties.
- **G9** all 4 plan-stage α-absorptions faithful (verified vs P2.5.md revision + code): Y1 (`ARCHIVE_SUMMARY_RENDER` + `derive_query_tags`→`digest.py` + guard by-named-function), Y2 (4 layers), Y3 (typed + first-visit=[] + 2 fact-types), Y4 (Q2 N/A).
- **G10** Q2/Q3 addressed; ruff + ruff-format + pytest green (only mypy red = R1).

## What I did NOT do

- Did not fix the impl (the two planted bypasses were reverted; tree clean before commit).
- Did not decide routing — R1/Y1/Y2 surfaced with leans for the architect (R1 is a hard gate failure → must α-fix before merge; Y2(b) is a genuine α-vs-β call).
- Did not touch the shared `main`/impl working tree or ADR-021/plan.
