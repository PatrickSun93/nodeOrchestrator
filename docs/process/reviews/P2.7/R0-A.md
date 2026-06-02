---
task_id: P2.7
round: R0-A
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 12
verdict_history:
  - verdict: needs_architect
    at_commit: ce0d043
    findings_count: { red: 0, yellow: 1, green: 11 }
    note: >-
      initial R0-A (impl-stage, in-family; the FINAL P2 slice). Both cruxes plant-bypass-PROVEN — c1 (planted .call in override.py → AST guard + spy both fail) and c2/Y2 (planted strip-regression → 3 env-inheritance tests fail). Gates all green incl. mypy (173 files); no new LLMPurpose; S1 pure; allowlist fail-closed; _build_child_env live. Y1 (the only 🟡) — the Y1 absorb is incomplete: the kept-unknown-cost decision_trace (the "kept-despite" visibility the architect routed α for) is NOT emitted (override.py defers to the router via a comment; the router doesn't implement it), so the default on_unknown_cost=keep softness is still silent — contradicting the absorb's "never silent". Nothing blocking.
  - verdict: clean
    at_commit: d25cf7f
    findings_count: { red: 0, yellow: 0, green: 12 }
    note: >-
      Bumped after junior Y1 fix (d25cf7f) + RC-10. The kept-unknown-cost decision_trace visibility
      is now genuinely emitted — exactly this review's α lean: apply_global_override returns a third
      dict kept_unknown_cost; the router emits a pre-walk RouteCandidate (reason "unknown cost ...
      kept by on_unknown_cost='keep' (ceiling=X)") for each unknown-cost model retained under a
      ceiling in the default keep mode, so the soft-ceiling is no longer silent (ADR-023 D2 satisfied
      for both modes). The keep-mode test is now discriminating (asserts a distinct unpriced entry
      containing both "unknown" and "keep"; fails if absent). Stale override.py comments removed.
      Convergent with plan-vs-impl Y1 (same finding, same fix). Orchestrator verified FULL gates
      green (ruff, ruff-format, mypy --strict 174 files, pytest all pass); independently re-confirmed
      (on_unknown_cost tests pass + mypy clean). Y1 🟡 → 🟢 (12🟢). Did NOT advance or merge.
---

# P2.7 R0-A (impl-stage, in-family) — the final P2 slice

| Field | Value |
|---|---|
| Commit reviewed | `ce0d043` (`origin/claude/P2.7-impl` tip; prelude → S1/S2/S3 → S4 → landing, batched-B) |
| ADR | ADR-023 + ADR-002/ADR-012 amendments **Accepted** (PR #39 merged) |
| Reviewed in | isolated git worktree at `ce0d043` |
| Gates (run in worktree) | **ALL green** — ruff ✓ · ruff-format ✓ (173) · **`mypy` (canonical) ✓ (173)** · pytest ✓ |

## Verdict: clean (bumped from needs_architect at `d25cf7f`)

> **Y1 resolution note (RC-10).** Junior fix `d25cf7f` finishes the absorb exactly as this review's α lean described: `apply_global_override` returns a third dict `kept_unknown_cost`, and the router emits a pre-walk `RouteCandidate` trace entry (reason "unknown cost … kept by on_unknown_cost='keep' (ceiling=X)") for each unknown-cost model kept under a ceiling in the default mode — the soft-ceiling is no longer silent (ADR-023 D2 satisfied both modes). The keep-mode test is now discriminating (asserts a distinct unpriced entry with "unknown" + "keep"; fails if absent). Stale `override.py` comments removed. Same finding + fix as plan-vs-impl Y1 (convergent). Gates green (orchestrator: mypy --strict 174 + pytest all; re-confirmed here). Y1 🟡 → 🟢. Original finding preserved below.

**Exemplary on both cruxes — and I proved both with live plant-bypass** (your checks 1+2). The constitutional core (c1 routing-is-code) and the security must-fix (c2/Y2 env-inheritance) are not just present but **structurally guarded against regression**: planting a `.call` in `override.py` trips the AST guard **and** the spy test; planting a strip-regression in `_build_child_env` trips 3 env-inheritance tests (incl. the hostile-parent + the live `call()`/`health_check` paths). The override is a pure deterministic transform (zero LLM, static attrs); no new `LLMPurpose`; the allowlist is fail-closed; S1 is pure code; gates fully green. The batched-B integration even **caught its own parallel-atomics collision** (commit `0531c93` removed a duplicate `GlobalLLMOverride` — the reconcile step working).

**One 🟡 (Y1 — an incomplete absorb, not blocking, not constitutional):** the architect routed Y1 → α to make the soft-ceiling **visible** via a `decision_trace` entry for unknown-cost models "kept-despite / dropped-as". The impl ships the configurable `on_unknown_cost` (keep/drop, default keep) **and** the trace for the **dropped** path — but the **kept** path (the default) emits **no** trace entry. `override.py` defers it to "the router separately" (a comment), but the router doesn't implement it. So with the default `keep`, an unpriced model silently bypasses the ceiling with **no** trace — exactly the softness Y1 was routed to surface. As the final P2 slice, worth your call before close.

## The five named checks

| # | Check | Verdict | Evidence |
|---|---|---|---|
| 1 | **c1 (S2)** zero LLM in selection; structural test (spy + AST) discriminating (plant a `.call`); no new routing `LLMPurpose`; composes Layer-3 | **clean (G1) — PROVEN** | `apply_global_override` is a pure fn over static `ModelProfile` attrs (`override.py`, zero LLM/IO). **Planted `.call` in override.py → BOTH `test_constitution_override_module_has_no_provider_call` (AST guard) AND `test_constitution_override_path_makes_no_llm_call` (spy) FAILED; revert → pass.** No new `LLMPurpose` (9, unchanged). Composes: the router walks `effective_chain` through the unchanged capability/provider/tools/health filters (`router.py:176+`); empty-chain → `NoSuitableModelError` fail-loud. |
| 2 | **c2/Y2 (S3)** env-clear blocks parent `ANTHROPIC_BASE_URL` inheritance (plant); allowlist fail-closed (plant untrusted); api_key not inline | **clean (G2) — PROVEN** | `_build_child_env` strips parent `ANTHROPIC_BASE_URL` then injects only an allowlisted `base_url`; **live** (`subprocess.run(env=...)` :146 health + :231 call). **Planted strip-regression → 3 env tests FAILED** (`test_child_env_clears_…_when_base_url_none`, `test_call_passes_child_env_to_subprocess`, `…health_check…`); revert → pass. Allowlist fail-closed: `test_base_url_not_in_allowlist_raises_config_error` (`ConfigError`, incl. empty). `api_key_env` indirection (no inline). |
| 3 | **S1** scaffold transition tables = pure code | **clean (G3)** | ADR-012 amendment's 4 state sets + per-arc tables landed in `rooms/state_machine.py`; pure code (the `rooms/` no-LLM constitution test is in the green run); discriminating per-arc tests (gate green); `rule_matched` traces (Q2). |
| 4 | ADR-002 4th-layer amendment landed + RC-23-safe | **clean (G4)** | ADR-002 (4th layer) + ADR-012 (scaffold) amendments **Accepted** (PR #39); were RC-23-safe at Proposed (verified plan-stage — appended `## Amendments`, Proposed-marked, no spurious `status: accepted` substring); now legitimately Accepted by the architect. |
| 5 | decision_trace / 5-surface / Q5 | **clean (G11); Y1 (the kept-unknown-cost trace)** | Q2: S1 `rule_matched`, S2 override **drop** reasons in `decision_trace`. Q3: handoff updated (5-surface, S2/S3/S4). Q5: discriminating (the plant-bypass proves the c1/Y2 structural tests; the allowlist + e2e). **Y1: the kept-unknown-cost trace is the gap — see finding.** |

## Findings

### Y1 🟡 — the Y1 absorb is incomplete: the kept-unknown-cost `decision_trace` (the routed visibility) is not emitted

The architect routed **Y1 → α** as: *"add a `decision_trace` entry for every unknown-cost model met under a ceiling (kept-despite / dropped-as), so the softness is never silent"* + configurable `on_unknown_cost`. The impl delivers two of the three:
- ✅ `on_unknown_cost: Literal["keep","drop"] = "keep"` (configurable; default unchanged).
- ✅ the **dropped** path traces: `on_unknown_cost="drop"` → `drop_reasons[model_id] = "unknown cost … dropped by on_unknown_cost='drop'"` → a `RouteCandidate(accepted=False)` trace entry.
- ❌ the **kept** path (the **default**) emits **no** trace entry. `override.py:58-63` appends the kept-unknown-cost model to `kept` with **no** `drop_reason`; the comment (`:59-62`, `:73-77`) says *"kept unknown-cost models are visible purely through the effective chain … (Trace entries for kept-unknown-cost are added by the router separately.)"* — but `router.py:176+` only emits trace entries from `drop_reasons` (dropped) + the normal chain walk; **no "kept despite unknown cost under ceiling X" entry exists**. So the comment is aspirational/stale.

**Consequence:** with the **default** `keep`, an unpriced model silently bypasses the cost ceiling and the `decision_trace` shows it selected like any other — the user has **no signal** the ceiling was bypassed by missing pricing. That is exactly the "soft-ceiling is silent" gap Y1 was routed to close; the absorb-note's "the softness is never silent" is unmet for the default path. (Not constitutional — the override is still deterministic code; this is an observability/absorb-completeness gap.)

**Lean (surface, not decide):** **α** — finish the absorb: `apply_global_override` returns the kept-unknown-cost set (or a third trace channel) and the router records a `decision_trace` note (`accepted=True, reason="kept despite unknown cost (cost_per_1m_output=None) under ceiling X"`) for each — so the default-keep softness is visible; + a test asserting the trace entry. Fix the stale `override.py` comment either way. **Or β** — accept default-keep-as-silent (the configurable `drop` + the dropped-path trace are "enough"; downgrade the absorb-note's "never silent" claim) — but that leaves the routed visibility partially unmet. Your call; low, and it's the final P2 slice.

## What holds — verified clean (G1–G11)

- **G1 — c1 (S2) PROVEN**: pure deterministic transform; AST guard **+** spy test both catch a planted `.call` (live); no new `LLMPurpose`; composes Layer-3 (router filters unchanged; empty-chain fail-loud).
- **G2 — c2/Y2 (S3) PROVEN**: `_build_child_env` strips parent `ANTHROPIC_BASE_URL` (3 tests catch a planted strip-regression; live at both `subprocess.run` sites); allowlist fail-closed (`ConfigError`); `api_key_env` no-inline.
- **G3 — S1** scaffold transition tables: pure code (no-LLM constitution test green), discriminating per-arc, `rule_matched` traces.
- **G4 — ADR-002/ADR-012 amendments** Accepted (PR #39); RC-23-safe at Proposed; legitimately accepted now.
- **G5 — S4**: `bootstrap.py` + `StartupError` + `render_startup_error`; the S3-allowlist hint + S2-override failure modes render actionable messages (`test_bootstrap.py` asserts message content — §4 load-bearing).
- **G6 — gates ALL green** (ruff + format + `mypy` 173 + pytest) — the P2.5 R1 mypy lesson stayed learned.
- **G7 — no new `LLMPurpose`** (9, unchanged — S2's override is code, not a judgment surface).
- **G8 — composition + fail-loud**: override pre-filters/reorders; router still guards (capability/health); empty-chain → `NoSuitableModelError` with the override drop reasons in `decision_trace`.
- **G9 — the batched-B integration caught its own collision**: `0531c93` removed a duplicate `GlobalLLMOverride` (parallel-atomics → reconcile step working; deduped to `types.py`).
- **G10 — Y1 partially absorbed** (configurable `on_unknown_cost` + the dropped-path trace; only the kept-path trace is the Y1 gap).
- **G11 — Q2/Q3/Q5** addressed (decision_trace present; handoff 5-surface; discriminating tests, plant-bypass-proven).

## What I did NOT do

- Did not decide Y1 — surfaced with a lean (α finish the kept-unknown-cost trace / β accept default-keep-silent); low, non-constitutional.
- Did not modify the impl (both planted bypasses reverted; tree clean before commit).
- Did not touch the shared working tree, the ADRs, or the plan.
