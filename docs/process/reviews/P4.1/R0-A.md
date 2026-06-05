---
task_id: P4.1
stage: impl
reviewer: architect-partner (in-family R0-A)
adr: ADR-033 (+ ADR-028 D3/D4, ADR-011 amendments)
verdict: needs_architect
findings: 0R / 3Y / spine-green
cross_family: R0-B (DeepSeek) runs in parallel — external-r0b-prompt.md lenses (a) liveness, (b) snapshot_excerpt injection
date: 2026-06-04
impl_head: 952cfcc
---

# P4.1 impl-stage R0-A — agent turn-loop + read-only code-intel tools

Mandatory impl-stage R0-A (ADR-008 Amendment 1 / W-005 Route B — runs regardless of plan-vs-impl verdict). Reviewed the 8 atomics on `origin/claude/P4.1-impl` (`e097d2d..952cfcc`, merge-base `4d76d67`) against ADR-033 (Accepted), the ADR-028 D3/D4 + ADR-011 amendments, and the §⭐⭐ constitutional carry-forward. Every load-bearing claim is verify-cited `file:line` vs the impl.

**State note (surfaced, not auto-fixed):** `.workflow/P4.1.yaml` reads `awaiting_junior_impl`, not `awaiting_R0_A`. Consistent with the known post-commit-hook / junior-self-advance lag; the architect dispatch acknowledges all 8 atomics pushed, so I treated this as the manual R0-A-on-impl dispatch and proceeded. Flagging per the state-machine self-check; no override taken.

## Verdict: needs_architect

The **constitutional spine is fully intact and verify-cited** — every non-negotiable carry-forward holds in the impl, and `ruff` + `mypy --strict` are green. **Nothing blocks merge on correctness.** Three 🟡 findings each present an α/β routing choice that is the architect's to make (I surface; I do not route). None breaches the spine; none blocks the capability. Hence `needs_architect`, not `clean` and not `blocking`.

---

## Constitutional spine — verified green (the carry-forward §⭐⭐)

| # | Invariant | Verify-cite | Status |
|---|---|---|---|
| 1 | Loop is CODE-driven; no LLM judges "loop again" | `app.py:430` `for _pass in range(MAX_TURN_LOOP_PASSES)`; conditions all code (`:432`,`:438-443`,`:445-448`) | ✅ |
| 2 | No new `LLMPurpose`; reuse `AGENT_RESPONSE` | `dispatch.py:116` `purpose=LLMPurpose.AGENT_RESPONSE`; t3 frozen-set (9 values) `test_constitution.py:151-175`; no new `EventType` (`test_local.py:574`) | ✅ |
| 3 | Every pass routes the **unchanged** gate; t4 holds per pass; COUNTDOWN/HARD→`TOOL_CALL_PENDING`→not executed in-loop, no confirm-block | loop calls only `dispatch_turn`(→`process_tool_calls` `dispatch.py:146`) + `execute_pending_tool_calls`; executor **unchanged** (not in diff); t5 AST (`test_constitution.py:301`) no autonomy symbol in `_write_and_turn`; §4 + §7-guard (`test_turn_loop.py:323,579`) assert PENDING→terminate, no `TOOL_CALL`, `call_count==1` | ✅ |
| 4 | Single-writer preserved; loop inline on writer | `app.py:425` filter once; passes inline; `ThreadPoolExecutor(max_workers=1)` `app.py:185` | ✅ |
| 5 | Loop TERMINATES; block absolutely bounded | 4 conditions: wall-clock `:432`, zero-`TOOL_CALL` `:438-443`, no-result `:445-448`, N=4 range-bound `:430`; `loop_start` before pass 0 `:391`; deadline checked at pass boundary (loop top) | ✅ |
| 6 | B2 read-only, in-process, sandboxed, trusted-not-interpreted | `os.walk`+`re` only, t6 no subprocess/Popen/os.system (`test_constitution.py:337`); `_check_path` reuse `local.py:150`; `MAX_SEARCH_FILES=500` `local.py:36`; bounded output `MAX_RESULT_BYTES` `local.py:188`; no `OBSERVATION` t8 + `test_b2_no_observation_event:510` | ✅ |

**Routed-surface probes (dispatch checklist):**
- **Termination / loop_start / deadline:** `loop_start = time.monotonic()` at `app.py:391` (before pass 0 `run_turn` at `:399`); deadline `if time.monotonic() - loop_start >= MAX_TURN_LOOP_WALL_CLOCK_S` at `:432` is the **first** statement of each loop iteration (pass boundary); §6 test `test_turn_loop.py:442` patches the constant to `-1.0` and asserts `call_count==1` (no re-dispatch) with pass-0 `TOOL_RESULT` intact (in-flight pass not interrupted). `MAX_TURN_LOOP_PASSES=4` (`app.py:76`), `MAX_TURN_LOOP_WALL_CLOCK_S=120.0` (`app.py:85`). ✅
- **State machine once/turn:** passes 1…N call `dispatch_turn` directly (`app.py:457`), not `run_turn`; §5 test (`test_turn_loop.py:388`) patches `next_room_state`, asserts ran exactly once. ✅
- **snapshot_excerpt:** populated from the dispatch-entry snapshot (`selection.py:155` ← `dispatch.py:78,97-103` `snapshot=snapshot`) — **no live read**; bounded `MAX_SNAPSHOT_EXCERPT_CHARS=8000` (`selection.py:30,114`); fed **additively** to the system block (`dispatch.py:108-113`), still `AGENT_RESPONSE`; `current_event.content` stays the user message (`dispatch.py:119`). ✅
- **log_event:** `dict→LocalToolOutput` (`test_log_event_direct_signature:550`), no `event_store` handle (`local.py:320-339`), no new `EventType` (`test_log_event_eventtype_enum_unchanged:574`). ✅
- **investigator.yaml:** `threshold_auto:8 / threshold_confirm:3 / user_intent_modifier:0` (`investigator.yaml:42-44`), read-only persona (`:3-8`), `cooldown_seconds:0` (`:24`); gate backstops mutation — §7-guard (`test_turn_loop.py:579`) asserts `propose_edit` (rev 5) → COUNTDOWN, no AUTO `TOOL_CALL`. ✅
- **Amendments inscribed:** ADR-028 D3/D4 `[Amended P4.1 → ADR-033, Accepted]` (`ADR-028:63,69`); ADR-011 amendment `[Amendment — P4.1 → ADR-033]` (`ADR-011:5-9`). ✅
- **P4.1-1 extraction behavior-preserving:** the dispatch-filter dict-comprehension moved **verbatim** from `run_turn`'s inline body into `select_dispatch_agents` (`runtime.py:47-63`); diff `e097d2d` is character-identical. ✅
- **Promotion-impact (P4.1-7):** `investigator` added to RESEARCH/BUG_FIX/CODE_REVIEW declared rosters (`templates.py:64,84,96`) matching its `applies_to.room_types`; roster-count/membership tests updated (`test_templates.py`, `test_scaffold_activation.py`, `test_config_loader.py`, `test_loader.py`). Legitimate housekeeping, not scope creep. ✅

---

## Findings (architect routes — I do NOT route)

### 🟡 Y1 — `snapshot_excerpt` renders raw untrusted MCP `TOOL_RESULT` with only a type-label; diverges from the inscribed R2-N1 framing intent (overlaps R0-B lens (b))

`_EXCERPT_EVENT_TYPES` (`selection.py:81-89`) includes **both** `TOOL_RESULT` and `OBSERVATION`. For an MCP call the executor appends a **raw** `TOOL_RESULT` (untrusted external content) **and** an interpreted `OBSERVATION` (`executor.py:84-85,251-266`; on interpret timeout only the raw `TOOL_RESULT` stands, `:289,304`). Both render through the uniform `[{type}] {author}: {content}` template (`selection.py:112`) with no untrusted-data demarcation beyond the type tag. ADR-033 D6 **R2-N1** inscribed that the excerpt should "prefer the interpreted/trusted view (the `OBSERVATION`) … or otherwise carry explicit untrusted-result framing." The impl does neither for the raw MCP `TOOL_RESULT` — it renders it alongside the `OBSERVATION`, type-label only. The `AgentContext` trust-framing docstring (`schema.py:204-209`) justifies trust for `OBSERVATION` + local `TOOL_RESULT` but is **silent on the raw MCP `TOOL_RESULT`** it actually renders.

**Spine intact:** every tool call the agent then emits still routes the unchanged gate (`dispatch.py:146`) → any mutation lands COUNTDOWN/HARD, not executed in-loop. Injection **cannot** bypass autonomy. This is framing-fidelity vs the inscribed intent, not a spine breach.

**Overlap:** the *deep* injection probe (can crafted result text steer the re-dispatched agent) is explicitly owned by the external R0-B (`external-r0b-prompt.md` lens (b)). I surface the **impl-vs-inscription** gap; R0-B probes exploitability; synthesis should reconcile.

**The choice (yours):** α (honor R2-N1 — prefer the `OBSERVATION` over the raw MCP `TOOL_RESULT`, or wrap raw external result content in explicit untrusted framing) vs β (defer to a P4.2 context-hardening slice; the spine holds and the gate backstops).

### 🟡 Y2 — B2 search tools diverge from the ADR-028 D3 symlink-escape rejection that carry-forward #6 says to "reuse"; untested

`read_file`'s `_check_path` resolves symlinks and rejects escape (`local.py:120-135`; tested `test_read_file_symlink_escape_rejected:207`). But `_collect_hits` walks via `os.walk` (default `followlinks=False` → symlinked **dirs** not descended, good) and reads each file via `fpath.read_bytes()` (`local.py:181`) **without** re-applying `_check_path` — so a symlinked **file** inside the sandbox pointing outside would be read and returned in hits. No test covers this (`test_local.py` has scope-escape `:423` but no search-symlink case). This is an internal inconsistency (read_file rejects in-sandbox symlink-escape; search follows it) and a divergence from the D3 boundary (`ADR-028:59` — "symlink-escape → `TOOL_FAILED`") that carry-forward #6 says to reuse.

**Threat-model nuance:** the local-tool threat model (`local.py:14-15`) trusts sandbox **contents**; the LLM cannot create symlinks in P4.1 (no mutation tools). So exploitability requires a pre-existing escaping symlink in the operator's trusted workspace — narrow. But the asymmetry + the untested gap are real.

**The choice (yours):** α (add per-file containment/`lstat` rejection in `_collect_hits` + a test) vs β (document the search-trusts-sandbox-contents posture + the `os.walk` dir-symlink safety explicitly, accept the narrowness).

### 🟡 Y3 — `investigator.yaml` ships `TODO:` placeholder strings in `dissent_dimensions` + `forbidden_behaviors`

`investigator.yaml:10-16` carries `["TODO: investigation_thoroughness", …]` and `["TODO: mutating_files_or_state", …]`. The schema defaults both to `[]` (`schema.py:108,110`), so omission would have been the clean-minimal form; literal `TODO:` strings read as stubbed, not minimal. Currently **inert** — the `dispatch_turn` system block does not consume these fields (`dispatch.py:108-113`), so no runtime/security effect; the gate backstops mutation regardless. ADR-033 D5 frames the investigator as "deliberately minimal … broader tuning a later content surface," so deferral is defensible.

**The choice (yours):** α (replace with real values or empty lists now — a one-line cleanup) vs β/δ (defer to the investigator-tuning content surface per D5).

### Notes (not findings — no routing needed)

- **N1 — hard-N termination not exercised by a greedy agent.** `for _pass in range(MAX_TURN_LOOP_PASSES)` (`app.py:430`) structurally guarantees ≤N, and §1/§7 assert `call_count ≤ 1+N` — but with agents that stop voluntarily (≤3 calls); none drive a greedy always-tool-calling agent to the hard N=4 cap to assert `== 1+N`. The structure makes regression unlikely; a greedy test would lock the most-important liveness property in. Low-priority completeness only.
- **N2 — investigator triggers on `tool_result` but not `tool_failed`.** The loop's `_result_types` admits `TOOL_FAILED` as a valid `current_event` (`app.py:427`), but the investigator's `speaking_triggers` are `user_input` + `tool_result` only (`investigator.yaml:18-22`) — so after a `TOOL_FAILED` the investigator won't re-speak in-loop (loop terminates next iteration; the agent reacts on the next real turn). Consistent with "minimal" + correct causality; recording the interaction, not a defect.
- **Pre-existing (not P4.1):** `templates.py:11` docstring "Research template declares 5 agents" is stale (now 7); blame shows P1.5-6 origin (`5d21370c`), not P4.1. P4.1 updated the inline comment (`:60` → "7") but not the module docstring.

---

## Gates

- `ruff check .` — **All checks passed.** ✅
- `mypy --strict src tests` — **Success: no issues found in 236 source files.** ✅
- `pytest -q` — **full suite green** (exit 0, `[100%]`, zero failures/errors). ✅
- Constitution t1–t8 present + well-formed (AST/structural + behavioral): t5 (no autonomy symbol in `_write_and_turn`), t6 (no subprocess in `local.py`), t7 (TOOL_CALL guard before execute), t8 (no `OBSERVATION` in `local.py`) — `tests/tools/test_constitution.py`. ✅

## What I do NOT route

Per role: I surface Y1/Y2/Y3 with the α/β choice articulated; the architect routes. The cross-family R0-B (DeepSeek) probes lens (a) the enumerated liveness bound + 120s deadline + `(1+N)×agents×≤600s` cross-room block, and lens (b) the `snapshot_excerpt` injection surface (overlaps Y1). Both lenses should be on the table before ADR-033's spine is considered fully cleared at impl; synthesis reconciles Y1 with R0-B lens (b).
