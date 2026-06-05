---
task: P4.1
stage: impl
reviewer: senior
lens: plan-vs-impl
verdict: clean
plan: docs/process/senior-plans/P4.1.md
adr: ADR-033 (Accepted) + ADR-028 D3/D4 + ADR-011 amendments
impl_range: e097d2d..952cfcc (8 atomics; merge-base 4d76d67)
gates: ruff clean · mypy --strict 236 files clean · pytest full suite exit 0 · test_constitution t1-t8 (9) green
---

# P4.1 — Senior plan-vs-impl (impl stage)

Reviewed the 8 atomics on `origin/claude/P4.1-impl` (`e097d2d..952cfcc`) against **my plan** (`senior-plans/P4.1.md`, 8 atomics) and ADR-033 (Accepted). The plan-vs-impl lens is *plan vs deliverable* — does the impl deliver what the plan said and respect the plan-implied invariants (distinct from R0-A's deliverable-vs-spec and R0-B's cross-family lenses). Every load-bearing claim below is verify-cited `file:line`.

**Verdict: `clean`.** Every atomic delivered its acceptance criteria; the atomic→commit subject mapping is 1:1 (RC-17); no scope drift breaks a plan-implied invariant; no unplanned surface beyond the one *mandatory* roster-coherence change (P4.1-7 `templates.py`, forced by a consistency-invariant test — §Observations). Gates green. The R0-A (Y1/Y2/Y3) and R0-B (A1/B4) 🟡 findings are real but sit on the **external** lenses (untrusted-injection framing, symlink-escape depth, pass-0-deadline arithmetic, TODO-placeholder polish) — those are the architect's to route via their own review files; none is a plan-vs-impl drift, so I do not re-raise them here.

## Atomic-by-atomic verification

| Atomic | Acceptance delivered? | Verify-cite |
|---|---|---|
| **P4.1-1** extract `select_dispatch_agents` (behavior-preserving) | ✅ | Helper is pure (`decide_agents_for_room` + the same dict-comprehension that was inline) `runtime.py:47-62`; `run_turn` now calls it `runtime.py:139` with byte-identical filter logic to the pre-diff inline block (`e097d2d` diff: the `["*"] or room.state in …` comprehension is moved verbatim). Direct unit test added `tests/rooms/test_runtime.py` (+59). |
| **P4.1-2** B2 code-intel tools + traversal bound + registry | ✅ | In-process `os.walk`+`re`, **no subprocess** (`local.py:138-340`); reuse `_check_path` via `_walk_sandbox` `local.py:139-148`; `MAX_SEARCH_FILES=500` traversal cap `local.py:35,156-159`; per-file bounded read `_SEARCH_FILE_READ_BYTES` `local.py:38,169`; output byte-cap → `output_truncated_at` `local.py:172-177`; `find_definition` matches `def/class/<sym>=` `local.py:303-307`; all 5 registered `local.py:357-362`. |
| **P4.1-3** `log_event` tool + registry | ✅ | `dict → LocalToolOutput`, **no** `event_store` handle, **no** new `EventType`, bounded to `MAX_RESULT_BYTES` `local.py:328-348`; boundary tests (`94f19eb`, +81). *Impl landed under the P4.1-2 commit subject — see §Observations (benign).* |
| **P4.1-4** B1 driver turn-loop | ✅ | `MAX_TURN_LOOP_PASSES=4` `app.py:75`; `dispatch_turn` called **directly** per re-dispatch (state machine once/turn) `app.py:457-466`; 3 termination conditions — zero-new-`TOOL_CALL` `app.py:438-443`, no-new-result `app.py:445-448`, N passes (the `for` bound) `app.py:430`; single publish `app.py:471+`. Tests: ≤1+N dispatch asserted `test_turn_loop.py:219`; zero-`TOOL_CALL` exit `:267`; `COUNTDOWN`→`TOOL_CALL_PENDING`→terminate, not executed `:366-379`; **state machine once/turn** `:432`. |
| **P4.1-5** wall-clock deadline (Y1) | ✅ | `MAX_TURN_LOOP_WALL_CLOCK_S=120.0` `app.py:84`; stamped before pass 0 `app.py:391`; 4th condition, **boundary** check `app.py:431-433`; docstring names the cross-room single-writer rationale `app.py:78-83`. Test: deadline at boundary → no re-dispatch `test_turn_loop.py:442-488`. |
| **P4.1-6** `snapshot_excerpt` (Y3 / ADR-011 amend) | ✅ | Additive optional field on the frozen model `schema.py:213` (default `None`, `extra="forbid"`); populated bounded `MAX_SNAPSHOT_EXCERPT_CHARS=8000` `selection.py:28,91-122,156`; **fed** to the `dispatch_turn` system block `dispatch.py:105-110`; no new `LLMPurpose`/`EventType`. **The feed is regression-guarded:** `test_build_agent_context_snapshot_excerpt_in_llm_request` runs the real `dispatch_turn` and asserts a prior-snapshot marker reaches `req.system` `test_selection.py:392-487` (assert `:485`) — deleting the `dispatch.py` append block fails this test. Population + bound also asserted `test_selection.py:347,365`. |
| **P4.1-7** investigator agent (Y2 / R2-Y1 pin) | ✅ | `cooldown_seconds: 0`; `threshold_auto: 8`, `threshold_confirm: 3`, `user_intent_modifier: 0` (`investigator.yaml`); `applies_to.room_types: [bug_fix, code_review, research]`, `room_states: ["*"]`; triggers `user_input` + `tool_result`; read-only persona. `8 > 3` ThresholdConfig invariant holds. Live chain + mutation-not-AUTO guard tests (`test_turn_loop.py` §7, `:560-627`). Promotion-impact roster fixtures updated (§Observations). |
| **P4.1-8** constitution t5-t8 | ✅ | t5 driver-loop no autonomy-decision symbol `test_constitution.py:301`; t6 no subprocess/Popen/os.system in `local.py` `:337`; t7 `TOOL_CALL` guard before `execute_pending_tool_calls` `:381`; t8 no `OBSERVATION` in `local.py` `:439`. t1-t4(+t3b) stay green — 9 passed, exit 0. |

## The five dispatch-flagged deep checks

1. **`select_dispatch_agents` behavior-preserving (P4.1-1)** — ✅ extracted logic is identical to the prior inline block; `run_turn` delegates (`runtime.py:139`). No `next_room_state`/dispatch change.
2. **Loop terminates + state machine once/turn (P4.1-4)** — ✅ bounded `for _ in range(MAX_TURN_LOOP_PASSES)` with three early-exits; re-dispatch calls `dispatch_turn` directly (never `run_turn`), so `next_room_state` runs only at pass 0 — asserted `test_turn_loop.py:432` (exactly 1 transition eval).
3. **Wall-clock as the 4th condition (P4.1-5)** — ✅ `app.py:431-433`, boundary-only (in-flight pass not interrupted), per ADR-033 D3 condition 4.
4. **`snapshot_excerpt` populated + fed + bounded, no new purpose (P4.1-6)** — ✅ all four properties verify-cited above; the feed-to-LLM path is independently test-guarded (`test_selection.py:485`).
5. **Investigator `threshold_auto: 8` (P4.1-7)** — ✅ pinned in `investigator.yaml`; least-privilege AUTO floor at rev≥8 (read-only set) per ADR-033 D5; mutation tools fall to COUNTDOWN/HARD — guarded by the §7 mutation-not-AUTO test.

## RC-17 atomic→commit mapping

8 atomics → 8 commits, subjects `P4.1-1:`…`P4.1-8:`, **1:1** (`e097d2d` `a844c4d` `94f19eb` `05b0df3` `da70766` `f106588` `b04ccbb` `952cfcc`). No bundling of two atomics under one subject (the P1.5 failure RC-17 targets is absent). One benign content nuance noted below.

## Observations (🟢 — benign; recorded for the architect / retro ledger, not verdict-changing)

- **🟢 G1 — P4.1-7 touched `rooms/templates.py`, a source surface the plan's "Where" did not name; the change is *mandatory*, not drift.** The plan's P4.1-7 "Where" listed only `config/agents/investigator.yaml` + tests. But `investigator`'s `applies_to.room_types` makes `decide_agents_for_room`/`_room_agents` load it into bug_fix/code_review/research, and two consistency invariants — `test_declared_agents_match_loaded` (`_room_agents == _ROOM_ROSTER`, `test_scaffold_activation.py:202-207`) and `test_declared_agents_match_plan_roster` (`ROOM_TEMPLATES.declared_agents == _ROOM_ROSTER`, `:174-178`) — force `ROOM_TEMPLATES.declared_agents` to include `investigator` (`templates.py:66,82,97`). So the junior's `templates.py` edit + the roster-enumeration fixture updates (`test_loader.py:350`, `test_config_loader.py:455` `TestExampleConfigs` glob, `test_scaffold_activation.py:86`) are exactly the **promotion-impact grep** the plan's §4 forcing function mandated — the discipline worked. Flagging only because the plan under-specified the "Where"; the impl is correct.

- **🟢 G2 — `log_event`'s implementation landed under the P4.1-2 commit subject; the P4.1-3 commit is its boundary tests only.** `a844c4d` (subject `P4.1-2`) explicitly names "+ `log_event` + registry" and contains `_log_event_tool` + the registry entry; `94f19eb` (subject `P4.1-3`) adds only the `log_event` boundary tests. The subject↔atomic-number mapping stays 1:1 and both atomics' acceptance is verifiable, so this is **not** the bundling RC-17 targets. It is defensible (all 5 new tools registered in one `build_local_tool_registry` edit avoids editing the registry dict twice). Noted so the RC-17 ledger reflects the content/subject split for atomic-3.

## Relationship to the external reviews (out of the plan-vs-impl lens)

R0-A (`needs_architect`, Y1/Y2/Y3) and R0-B (`needs_architect`, A1/B4) already filed architect-routing 🟡s on the untrusted-result framing (R2-N1 divergence), symlink-escape depth, pass-0-vs-120s arithmetic, and the `investigator.yaml` `TODO:` placeholders. Through my plan lens none of these is a plan-vs-impl drift: the plan delegated the trust-boundary depth to "reuse the ADR-028 D3 boundary" and the liveness arithmetic to ADR-033 D4, and did not specify the `dissent_dimensions`/`forbidden_behaviors` content. They are the architect's to route via their own files; I neither re-raise nor route them (CLAUDE.md "never LLM-judge a routing decision").

**Expected auto-advance:** per ADR-008 Amendment 1 (W-005, Route B) the state advances to `awaiting_R0_A`/synthesis regardless of this verdict; the architect synthesizes all three impl-stage review files (plan-vs-impl `clean` + R0-A + R0-B `needs_architect`) and routes the external yellows before ADR-033 is considered fully cleared at impl.
