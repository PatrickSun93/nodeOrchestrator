---
task_id: P3.4
cycle: 2
round: architect-routing-on-impl
stage: impl
decided_by: architect (Peidong) — recorded via orchestrator
date: 2026-06-03
reviews_routed:
  - reviews/P3.4/plan-vs-impl-cycle2.md          # senior — needs_architect (0R/1Y/8G)
  - reviews/P3.4/R0-A-cycle2.md                  # arch-partner — needs_architect (0R/2Y/12G)
  - reviews/P3.4/R0-B-cross-family-cycle2.md     # r0b (deepseek, dual-lens) — needs_architect (0R/1Y/10G)
joint_verdict: >-
  needs_architect (impl-stage; 0 red across all three lenses). Three-way convergence on a
  single residual (Y1) introduced by the R1 interpret-timeout fix; one extra low yellow (Y2)
  from R0-A only. No spine/trust regression — the constitutional carry-forward verified
  structural on the impl by R0-A; all seven plan-stage hard points landed.
decisions:
  Y1: >-
    alpha — fix in-cycle. The R1 interpret-timeout fix (interpret_mcp_tool_result run on a
    4-worker pool with future.result(timeout)) bounded the writer (R1 acceptance met) but ran
    the OBSERVATION event_store.append ON the pool thread — off the single writer — violating
    the ADR-028 D1/D5 single-writer invariant ("same writer thread / no store concurrency"),
    and the timed-out future was not cancelled, so a leaked interpret thread could append a
    late OBSERVATION racing the writer on the same check_same_thread=False connection
    (SQLITE_BUSY; could fail a turn, not merely advisory-untidy). Three lenses converged
    (senior Y1 = R0-A Y1 = R0-B yellow). REMEDY: the pool task computes ONLY the interpret
    content (the LLM call) and returns it; the OBSERVATION append happens on the SINGLE WRITER
    thread after future.result() returns; on timeout -> future.cancel() + NO append (raw
    TOOL_RESULT stands, writer unblocked). This preserves both the liveness bound and the
    single-writer invariant. NO ADR-028 change — the impl violated an already-inscribed
    invariant; the fix makes the impl match the ADR.
  Y2: >-
    alpha-fold — fix in-cycle. R0-A-only (low). list_files output had no size-cap while
    read_file (bounded read) and MCP (MAX_RESULT_BYTES) do. REMEDY: cap list_files output at
    MAX_RESULT_BYTES (consistent with read_file), trim to last whole entry + set
    output_truncated_at on over-cap.
implementation:
  - 1bd3a07  # P3.4-Y1: pool task LLM-only; OBSERVATION on writer thread; future.cancel on timeout
  - 640a9e3  # P3.4-Y2: list_files output byte-cap (MAX_RESULT_BYTES)
verification: >-
  orchestrator-verified at 640a9e3 — full gate green (ruff + ruff format + mypy --strict[209]
  + pytest) AND the empty-gate-diff invariant holds (autonomy/ + agents/tool_dispatch.py
  unchanged vs origin/main). Y1 code confirmed: pool task never calls event_store.append;
  OBSERVATION append after future.result on the writer; future.cancel() + no-append on timeout.
  Y2 code confirmed: list_files byte-capped at MAX_RESULT_BYTES with truncation flag.
rc10_bump: >-
  Deferred cycle-1 verdict-bump + the cycle-2 verdict-bump both occur at cycle-2 close
  (senior, RC-10): cycle-1 impl-stage (R0-B Y2 resolved by cycle-2 executor) and cycle-2
  impl-stage (Y1+Y2 resolved) all -> clean.
state_note: >-
  Did not advance state or bump verdicts in this artifact. The orchestrator drives the RC-10
  bumps (senior) + the PR #48 close-merge under the manual cycle-2 state management
  (see P3.4 retro candidates RC-27/RC-28 — the dev-harness state-machine gaps that make
  cycle-2-on-same-task require manual override + post-commit-hook restore).
---

# P3.4 cycle-2 architect routing — impl stage (Y1 alpha, Y2 alpha-fold; spine clean)

The cycle-2 runtime tool-executor impl (`6a72c99`, C2-1..C2-4) drew three impl-stage lenses,
all **needs_architect, 0 red**. The mandatory dual-lens R0-B and the architect-partner R0-A
both confirmed the constitutional carry-forward holds **structural** on the implementation
(execution downstream-of-`TOOL_CALL` via the sole-appender + behavioral filter; no LLM
judgment / no new `LLMPurpose`; empty gate diff; `tools/` leaf placement; plant-bypass closed),
and that **all seven plan-stage hard points landed** (R1 interpret-timeout, bounded read,
TOCTOU posture, full-room double-exec guard, `MAX_MCP_CALLS_PER_TURN` cap, etc.).

The single substantive residual (**Y1**, three-way converged) is a concurrency hazard the R1
fix *introduced*: the bounded interpret ran its `OBSERVATION` append off the single writer.
The architect routed **alpha** with the remedy that restores the ADR-028 D1/D5 single-writer
invariant (pool computes the interpret content; the writer appends; cancel on timeout). **Y2**
(`list_files` uncapped output, R0-A-only, low) routed **alpha-fold** for consistency with the
`read_file`/MCP size-cap.

Both fixes landed (`1bd3a07`, `640a9e3`) and are orchestrator-verified green. The senior bumps
the deferred cycle-1 + the cycle-2 impl-stage verdicts to **clean** at cycle-2 close (RC-10),
then the whole P3.4 (cycle-1 MCP client/gating + cycle-2 executor) merges via PR #48.
