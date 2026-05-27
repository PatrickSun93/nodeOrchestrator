---
task_id: P1.4
round: R0-A
verdict: clean
findings_count:
  red: 0
  yellow: 1
  green: 6
---

# P1.4 R0-A review

| Field | Value |
|---|---|
| Round | R0-A (post-impl, architect-partner) |
| Reviewer | architect-partner (Claude Opus 4.7, 1M context) in primary session |
| Date | 2026-05-27 |
| Artifacts reviewed | 7 impl commits on `claude/P1.4-impl`: `1efa981` (P1.4-4 schema + StateTransitionMeta + build_author + 3 constitutional tests), `a29d08c` (P1.4-5 loader + regex_registry + capabilities validation), `8d5066b` (P1.4-6 decide_agents_for_room + build_agent_context), `5236af0` (P1.4-7 should_agent_speak + cooldown unit regression tests), `d743ddc` (P1.4-8 dispatch_turn + LLMRouterProtocol + 14 §1/§2/§3 tests), `dd8bc2d` (P1.4-9 skeptic.yaml + prober.yaml + integration), `162650a` (P1.4-10 doc updates + scan + state advance). Plus senior plan-vs-impl review `7087fc6` (read to avoid duplication; 5 🟢; verdict clean). +2902 / -34 lines across 21 files. 602 tests post-impl (+124 from W-002.5 close at 478). |
| Brief lean | P1.4 brief explicitly mandated **dispatch R0-A** post-impl (RC-9 architect-decision-gated, but architect's prior decisions on P1.4 plan all dispatched R0-A; impl-side mirror is the standard). |
| Distinct from plan-vs-impl | Plan-vs-impl already enumerated: 10/10 tasks acceptance ✓, 18 routing items (12 first-pass + 6 DeepSeek) all present ✓, 3 constitutional tests load-bearing ✓, all 6 test-coverage categories non-trivially exercised ✓, gates green. This R0-A focuses on **architect-partner-distinct lens**: ADR-010 + ADR-011 invariant compliance in code (not just spec); constitutional discipline under first-real-load; RC-16 status; forward implications for P1.5+. |

---

## Findings

### 🟢 G1 — ADR-010 + ADR-011 invariants land correctly in code

Both ADRs were Accepted at `54d002e` + `e26aca3` with their post-routing-absorption text. Architect-partner verification that the impl matches the inscribed Decisions:

**ADR-010 D2 (cooldown unit conversion):** `src/orchestrator/agents/speaking.py:74` reads:
```python
elapsed_s = (current_event.timestamp - last_utterance.timestamp) / 1000.0
if elapsed_s < agent.cooldown_seconds:
    cooldown_remaining_s = float(agent.cooldown_seconds) - elapsed_s
```
**Exact match to the ADR-inscribed conversion site.** The 1000× bug DeepSeek R0-B 🔴#1 caught is closed in code, not just spec. Regression test in `test_should_agent_speak.py` (per senior's plan-vs-impl table).

**ADR-010 D1 + D6 + 🟡#6 (build_author + StateTransitionMeta + separate regex_registry):**
- `src/orchestrator/core/event.py:298` defines `build_author(agent_id: str) -> str` (single point of format truth per DeepSeek R0-B 🟡#6).
- Used at `speaking.py:64` (cooldown lookup author match) AND `dispatch.py:121` (utterance event construction).
- Same `build_author` used at both producer (Event constructor in dispatch) and consumer (cooldown match in speaking) — closes the silent-bypass class.
- `StateTransitionMeta` from `core/event.py` imported into `speaking.py:28` for typed `metadata.new_state` access (not `metadata["new_state"]` dict access).
- `regex_registry: dict[(agent_id, trigger_index), Pattern]` threaded as keyword-only parameter through `dispatch_turn` → `should_agent_speak` (verified via `grep regex_registry`).

**ADR-011 D1 (sync def):** `dispatch.py:58` reads `def dispatch_turn(...) -> TurnResult` — no `async`. No `await` anywhere in dispatch.py. The async-shape-now anti-pattern DeepSeek R0-B 🟡#4 challenged is closed.

**ADR-011 D3 (alphabetical-id only, no Agent.priority):** `Agent` Pydantic model in `schema.py` lacks `priority` field. `dispatch.py` agent iteration uses `sorted(..., key=lambda a: a.id)` per spec.

**ADR-011 D7 (LLM exception log+skip+continue) + D7-b (event_store abort):** `dispatch.py:126` reads `event_store.append(utterance)  # propagates unwrapped per ADR-011 D7-b`. Asymmetric handling between per-agent LLM failure (caught + logged + continue) and event-store-append failure (raise + abort turn) — exact ADR-011 D7-b semantic.

**ADR-011 D1+D7 TurnResult return:** `schema.py:184` defines `class TurnResult` with `utterances`, `failed_agents`, `total_asked`. `dispatch_turn` returns `TurnResult(...)` per ADR-011 D1 revised signature.

**Net**: every load-bearing ADR Decision has a verifiable code site. Zero spec-vs-impl drift found.

### 🟢 G2 — Constitutional discipline under first-real-load

P1.4 is the first task to load real agent yamls. Three constitutional tests landed at `tests/agents/test_constitution.py`:
- `test_constitution_no_llm_calls_in_agents_module` (line 23) — green
- `test_constitution_core_does_not_import_agents` (line 63) — green
- `test_constitution_skills_does_not_import_agents` (line 97) — green

R0-A independent grep verification: `grep -rn "from orchestrator.agents" src/orchestrator/core/ src/orchestrator/llm/ src/orchestrator/skills/` returns **zero matches**. No reverse imports introduced. Layering invariant load-bearing for P1.5+ when operator agent + autonomy-aware tool dispatch lands.

`from anthropic` / `from openai` grep in `src/orchestrator/agents/` returns zero. LLM-free dispatch layer; LLM calls flow through `LLMRouter` per existing protocol.

### 🟢 G3 — RC-16 latent risk did not bite; status unchanged

RC-16 (`_read_plan_frontmatter` reads working-tree, not `origin/main`) captured in W-002.5 PR #11 body. P1.4 cycle exercised the relevant code path multiple times (plan-publish auto-advance at P1.4-10 → R0-A read of plan + ADRs). All advance runs happened post-merge-to-main; the risk window didn't open.

Latent risk remains for W-003 scope. Lean for W-003 fix path: read plan via `git show origin/main:path` semantically (preserves auto-trigger intent without working-tree dependency).

### 🟢 G4 — `verify-workspace` not run during junior impl (audit-trail note)

Junior session's commit body for `162650a` (P1.4-10 landing) notes `verify-workspace` was NOT run (junior session lacked CLI access). Per W-002 + W-002.5 precedent, `verify-workspace` should fire pre-landing as a forcing function. **Not blocking R0-A**: the workspace is verified clean via `pytest` + `ruff` + `mypy` independently, AND the architect's own merge-readiness check serves the same role at PR-merge time. **Captured as a watch item for next impl-cycle brief**: ensure junior session has `uv run workflow verify-workspace` capability before P1.5 dispatch.

### 🟢 G5 — Forward implications for P1.5+

P1.4 impl enables four P1.5+ surfaces:
- **`decide_agents_for_room` is the future-hook for room-type filtering** (P1.4 returns all agents; P1.5+ adds `agent.applies_to.room_types` field + filtering logic alongside additive `room_type, room_state` parameter add — already designed in plan §5).
- **`Agent.priority` additive expansion** (P1.5+ when 3+ agents per room creates real conflict; deferred per ADR-011 D3 revised).
- **Concurrent dispatch upgrade** (`dispatch_turn` sync → async + body to `asyncio.gather` in one P1.5+ commit; zero callers in P1.4 to migrate; designed in ADR-011 D1).
- **Operator agent + autonomy-aware tool dispatch** (P1.5; will add `from orchestrator.autonomy import gate` to agents/; current constitutional test allows this direction).

`TurnResult.failed_agents + total_asked` are programmatically observable by the future room runtime (P1.5+); the all-fail vs no-trigger distinction is detectable from outside dispatch_turn without log-watching.

### 🟢 G6 — Dual-lens R0-B retrospective: paid for itself

P1.4 ran the project's first true cross-family R0-B (DeepSeek V4 Pro at `d60cd99`). Of 6 DeepSeek findings:
- 2 🔴 are now closed in code: cooldown unit conversion (`speaking.py:74`) + event_store.append abort path (`dispatch.py:126`). Both would have been production bugs without W-002.5-style pre-impl absorption.
- 4 🟡 are also closed in code: `decide_agents_for_room` no unused params, regex_registry §1 threading test (in `test_dispatch.py`), AgentContext docstring deferrals, build_author helper.

Proxy-lens R0-B caught 2 🔴 spec-level errors (cooldown unit; StateTransitionMeta gap). True cross-family caught 2 🔴 runtime-integration errors (event_store failure; all-fail caller contract). **Different lenses caught different errors; both passes were needed.** RC-15 (dual-lens R0-B for shape-change) is empirically validated.

### 🟡 Y1 — Two impl commits modified `senior-planner.md` (-31 lines) which was changed on main mid-cycle

**Where:** `git diff --stat origin/main..origin/claude/P1.4-impl` shows `docs/process/senior-planner.md | 31 -`. The impl branch removed 31 lines from senior-planner.md. Architect's own status report flagged this: "impl branched before my parallelism-rule commit (`2868d83`); merge will be clean (no overlap)".

**What:** the impl branch was cut from main before `2868d83` (architect-partner's senior-planner.md edit). When the PR merges, git will (almost certainly) auto-resolve since the lines are disjoint, but the merge needs verification. If the auto-resolve drops the architect's parallelism-rule addition, the merge regresses that doc change.

**Options for resolution:**
- (a) **Verify pre-merge**: run `git fetch origin main && git merge origin/main` on the impl branch locally; resolve any conflict in senior-planner.md by keeping BOTH the parallelism-rule (from `2868d83`) AND the impl branch's -31-line removal of the older section. Push the merge commit to the impl branch; then PR merge is auto-clean.
- (b) **Trust GitHub's auto-merge**: open PR, observe the merge result post-merge, and add a fix-up commit on main if the parallelism-rule was clobbered.
- (c) **Rebase impl branch on main**: cleaner history but harder if the impl commits get rewritten — and impl branch has been pushed + R0-A is now on it.

**My lean: (b)** — trust git's three-way merge for disjoint lines; verify post-merge with `grep parallelism docs/process/senior-planner.md` on main. If clobbered, add architect-partner-direct fix-up commit on main referencing the original `2868d83`. Lowest-friction; impl branch stays clean.

**Severity 🟡**: documentation surface only; no code impact; auto-resolvable. Surfaced because pre-impl context drift on a non-locked doc path is the kind of thing that should be named explicitly rather than discovered post-merge.

---

## Cross-checks

- [x] All 602 tests green; ruff/format/mypy strict clean across 90 source files.
- [x] Three new constitutional tests load-bearing (`grep`-verified zero LLM imports in agents/, zero reverse imports).
- [x] ADR-010 D2 cooldown /1000.0 conversion at `speaking.py:74` — DeepSeek 🔴#1 closed.
- [x] ADR-010 D1 StateTransitionMeta typed access at `speaking.py` — DeepSeek 🔴#2 closed.
- [x] ADR-010 D6 separate regex_registry threaded through `dispatch_turn → should_agent_speak`.
- [x] ADR-011 D1 sync `def dispatch_turn`; no `async`/`await` in dispatch.py.
- [x] ADR-011 D3 alphabetical-id ordering; no `Agent.priority` field in schema.py.
- [x] ADR-011 D4 `build_agent_context` separate function; docstring lists P1.5+ deferrals.
- [x] ADR-011 D7 LLM exception log+skip+continue; failed_agents tracking.
- [x] ADR-011 D7-b event_store.append abort — "propagates unwrapped per ADR-011 D7-b" comment at dispatch.py:126.
- [x] TurnResult return type at schema.py:184; dispatch_turn returns it; failed_agents + total_asked + utterances tracked.
- [x] `build_author` helper at core/event.py:298; used at speaking.py + dispatch.py (single point of format truth — DeepSeek 🟡#6 closed).
- [x] `AgentContext.snapshot_excerpt` dropped (DeepSeek 🟡#6 absorbed).
- [x] `AgentMatchRecord.reason` dropped (R0-A Y1 absorbed).
- [x] `decide_agents_for_room` no `room_type/room_state` params (DeepSeek 🟡#3 absorbed).
- [x] skeptic.yaml + prober.yaml exist with full P1.4 fields + `autonomy_thresholds` (pre-impl-spec DRIFT D1 absorbed).
- [x] §1 cross-module integration test in `test_integration.py`.
- [x] §2 snapshot-semantics test in `test_dispatch.py`.
- [x] §3 cleanup test for event_store-append-failure in `test_dispatch.py`.
- [x] §4 exception payloads tested for 3 new error classes.
- [x] §5 multi-position boundary tests on Agent fields.
- [x] §6 schema invariants on all Pydantic models (test_schema.py — 53 tests, 462 LoC; largest §6 surface in project).
- [ ] RC-16 (working-tree vs origin/main) — latent, not bitten; W-003 scope.
- [ ] Y1 above — senior-planner.md merge verification needed pre-or-post PR merge.

---

## Net assessment

**Verdict: clean.** Six 🟢 confirmatory findings + one 🟡 merge-verification item that's documentation-surface only and auto-resolvable.

P1.4 is the most architecturally consequential task in the project to date AND the first end-to-end clean cycle through impl:
- **18/18 routing items present in code** (12 first-pass + 6 DeepSeek).
- **All ADR-010 + ADR-011 inscribed Decisions verified at named code sites.**
- **3 constitutional tests load-bearing under first-real-agent-load.**
- **All 6 test-coverage categories non-trivially exercised** (project's first task to do so).
- **Dual-lens R0-B retrospective validates the pattern**: proxy caught spec-level errors; true cross-family caught runtime-integration errors; both passes needed.

**Override count at this advance: still 2** (P1.3 + W-002; both pre-fix bridges). P1.4 ran with zero overrides through plan + impl + state advance. The W-002 + W-002.5 + RC-11 cluster work paid off exactly as the design intended.

**Recommendation:** state machine auto-trigger chain (`awaiting_R0_A → awaiting_PR_merge → closed`) fires on next `workflow advance --task-id P1.4`. Verify Y1 senior-planner.md merge cleanliness post-PR-merge.

## Cross-family R0-B for impl

P1.4 brief mandated **true cross-family R0-B for impl** alongside the plan-stage R0-B that already ran. The architect's status report notes this is the next-step parallel mandate.

**Architect-partner stance:** the impl-side R0-B is high-value but lower-stakes than the plan-side was. The plan-side DeepSeek R0-B caught 2 🔴 (spec-level cooldown unit + missing typed metadata) that would have shipped to code without it. The impl-side R0-B's analogous yield is checking that the absorbed-into-spec items are also absorbed-into-code AND surfacing any runtime concerns the spec couldn't see.

My R0-A above did the spec-vs-code spot-checks (G1) which is half of the impl-side R0-B value. A true external cross-family R0-B would still add:
- Independent runtime-error-mode review (test cases the impl missed; edge cases the design didn't predict).
- Confirmation that the test suite genuinely exercises the design (vs being green-by-tautology).

**Lean: dispatch external R0-B per the mandate.** Same external-prompt artifact as `docs/process/reviews/P1.4/external-r0b-prompt.md` — architect updates it to point at impl commits instead of plan, sends to GPT-4 / DeepSeek session, pastes result back.

**Alternative: skip + ship.** Brief mandated dispatch; architect can override with documented retro capture. The R0-A spec-vs-code verification (G1 above) is enough to clear merge; the cross-family lens would catch additional issues that aren't load-bearing for this merge but would inform P1.5+ design.

Architect picks. If dispatched, the cycle absorbs whatever findings come back (same routing pattern as DeepSeek plan-stage R0-B). If skipped, capture as P1.4 retro candidate.

## Captured for P1.4 retro

- **RC-15 validated**: dual-lens R0-B for shape-change is project standard going forward; paid for itself on P1.4.
- **Y1**: senior-planner.md mid-cycle drift on a non-locked doc path; W-003 candidate for "locked-paths convention extends to process docs that govern session behavior."
- **`verify-workspace` capability check** for junior sessions: confirm pre-dispatch that junior has CLI access; W-003 or P1.5 brief candidate.
- **P1.4 is the first end-to-end clean cycle through impl** (W-002.5 was first clean plan-publish-through-merge; P1.4 extends clean to impl). Override count freezes at 2.
