---
task_id: P3.7-content
kind: R0-A
cycle: 1
stage: impl
reviewer: architect-partner
lens: single-lens (no dual-lens — brief §c; zero of dual-lens-r0b.md's 4 criteria hold)
based_on_impl: claude/P3.7-content-impl @ b84d451
based_on_plan: docs/process/senior-plans/P3.7-content.md
based_on_brief: docs/process/architect-briefs/P3.7-content.md
verified_against: origin/main @ ab5af6b
gate: >-
  Independently re-run by the reviewer (not trusting junior's report): ruff check = All checks
  passed; ruff format --check = 224 files already formatted; mypy (strict, files=src+tests) =
  Success, no issues in 222 source files; pytest (full suite incl tests/) = exit 0, zero failures
  (incl. the 4 new P3.7-content test modules). All green.
verdict: clean
note: >-
  Impl is a clean, faithful execution of the (architect-dialed 4/3/2/2) breadth plan. Full gate
  re-run green. All 5 architect-set review foci pass: purely additive (the ONLY src/ change is
  rooms/templates.py rosters — pure data; no loader/gate/executor/autonomy code touched); every
  unit has a genuinely discriminating test (real loader / real gate tier / real fail-closed);
  agent activation stays code (should_agent_speak + event_type/state_change triggers); connector
  write tools gate via ADR-027 pre-classify-allowlist (NOT ADR-028 D3 local-impl); plugins run
  Posture A in-process + 不暴露 holds. Modified existing tests are PRECISE assertion updates
  (e.g. frozenset()→{synthesizer}), NOT loosened. No Y finding. Three non-blocking advisories
  (N-1 new agents show generic 助手 in GUI — fallback-safe, frontend follow-up; N-2 TODO: dissent
  placeholders match the EXISTING convention (skeptic et al. use them too) — not introduced here; N-3 impl-branch
  state still awaiting_junior_impl, architect-owned).
---

# R0-A (impl-stage) — P3.7-content (single-lens; architect-partner)

## 1. Scope & method
Single-lens impl-stage R0-A on `claude/P3.7-content-impl @ b84d451` (11 atomics — 4 agents / 3 skills / 2 connectors / 2 plugins; the architect-dialed quantity, plan §5 quantity-dial). Reviewed against the plan, the brief, and the four reused ADRs (024/009/027/029) + the live schemas/loaders. **Per the architect's dispatch, the full gate was re-run independently by the reviewer** (not trusting the junior's "green" report — the recurring "junior ran src/-only gates" failure class). Focus = the architect's five foci + the brief's constitutional carry-forward.

## 2. Gate (independently re-run — the architect's explicit ask)
| Gate | Command | Result |
|---|---|---|
| lint | `uv run ruff check .` | **All checks passed** |
| format | `uv run ruff format --check .` | **224 files already formatted** |
| types | `uv run mypy` (strict; `files=["src","tests"]`) | **Success: no issues found in 222 source files** |
| tests | `uv run pytest` (full suite, `testpaths=["tests"]`) | **exit 0, zero failures** — incl. the 4 new P3.7-content modules (`test_p3_7_content_{agents,skills,connectors,plugins}.py`) |

All green. No `src/`-only blind spot (mypy + pytest both span `tests/`).

## 3. Verdict — **clean**
A clean, faithful pattern-reuse impl. No product-correctness, constitutional, trust-surface, or discriminating-test defect. **No Y finding.** Three non-blocking advisories in §6.

## 4. The five review foci — all pass

**(1) Purely additive; reuses frozen loaders; no reshape / no gate-executor decision-logic touch / no new `LLMPurpose` / no trust surface.** ✓✓
- **The single most load-bearing evidence:** `git diff --stat main...HEAD` shows the **only** `src/orchestrator/` change is `rooms/templates.py` (+20, roster lists — pure data; the module is LLM-import-free, enforced by `test_constitution_no_llm_calls_in_rooms_module`). **Zero** edits to any loader (`agents/loader`, `skills/loader`, `mcp/`, `plugins/loader`), the gate (`autonomy/`, `agents/tool_dispatch`), or the executor (`tools/`). Everything else is `config/`, `plugins/<new>/`, `tests/`.
- No new `LLMPurpose` (the frozen-purpose constitution tests stay green in the full run); connectors are local stdio (`transport: stdio`, `api_key_env: null`); plugins are Posture-A local. No remote, no new trust face.

**(2) Discriminating tests per unit (real registration / real gate tier / real fail-closed — not "renders something").** ✓✓
- **connectors** (`test_p3_7_content_connectors.py`): drive the **real** `process_tool_calls` gate path — read tools (rev 10) → `AUTO_EXECUTE`; write tools (`create_entities`/`write_query`/`create_table`, rev 1-2) → `HARD_CONFIRM` with `tool_call_event_appended is False`; **exposed-but-unlisted** `delete_entities`/`drop_table` → `tier is None`, `refusal_reason == "unknown_tool"` (HR#3 discovery≠permission). Loaded via real `load_mcp_servers_config` + `build_tool_registry`.
- **plugins** (`test_p3_7_content_plugins.py`): real `load_plugins` + real `score`/`decide_tier`. host-preclassified `context_summary` (rev 10) → `AUTO_EXECUTE`; **plugin-classify-only `annotate_context` declared rev 4 but capped to `reversibility == 0`** → `HARD_CONFIRM` (advisory-cap, ADR-029 D5 — a plugin cannot self-raise its tier); **fail-closed** bad-manifest → `result.agents == {}` (host unchanged) and MCP name-collision (`insights_db`) → `result.mcp_sessions == {}` (refused).
- **agents** (`test_p3_7_content_agents.py`): `should_agent_speak` → `speak=True` in **each** declared room type (via real `decide_agents_for_room`), **and** `not in _room_agents(<non-declared>)` (present/missing partition).
- **skills** (`test_p3_7_content_skills.py`): real `decide_skills_for_context` — **selected** in the declared room, **rejected** in ≥2 non-declared rooms with `rejection_reason == "room_type_mismatch"` (checked on the trace, not just absence).

**(3) New-agent activation stays code.** ✓ All four agents activate via `should_agent_speak` + declarative `event_type`/`state_change` triggers (synthesizer→`decision`; planner/verifier→`state_change` to states valid for each room's machine — `diagnosed`/`reviewing`/`pitching`/`fix_proposed`/`approved`; mentor→`user_input`). No LLM in the activation path; responses stay content-gen.

**(4) Connector write tools gate via ADR-027 pre-classify-allowlist (NOT ADR-028 D3 deferred local tools).** ✓ The write tools (`create_entities`/`write_query`/`create_table`) are **MCP-server tools** classified in `config/mcp_servers.yaml`'s per-server allowlist (the ADR-027 D3 mechanism) → `HARD_CONFIRM` via the existing gate; they are **not** local `LocalToolFn` impls, so they do **not** touch the ADR-028 D3 deferred network/subprocess/mutation local-tool classes (which `config/tools.yaml` classifies but leaves unimplemented). Brief §b honored.

**(5) Plugins run Posture A; 不暴露 carry-forward holds.** ✓ `plugins/context/tools_impl.py::context_summary` is a pure, no-I/O, deterministic in-process callable (header explicitly: *"Posture A in-process import (ADR-029 D4)"*) — **no Posture-B/subprocess** (that is the sibling P3.7-remote). Plugins are internal distribution units (never surfaced as "plugin"/"MCP" vocabulary, P3.6 D-C); their tools route through the host gate + advisory-cap. 不暴露 unaffected.

## 5. Modified existing tests — precise updates, NOT loosened (verified line-by-line)
The impl edits 4 existing test modules; I diffed each to confirm they **tighten/track**, not weaken:
- `test_scaffold_activation.py` (+67): every change updates an activation assertion to the **exact** new speaking set — e.g. `test_decision_fires_no_existing_trigger` (`frozenset()`) → `test_decision_fires_synthesizer` (`{"synthesizer"}`); `..._diagnosed_fires_skeptic_only` (`{"skeptic"}`) → `..._skeptic_and_planner` (`{"skeptic","planner"}`). These are **stronger** (an empty-set assertion becomes a specific-agent assertion). No coverage deleted; `_ROOM_ROSTER` updated to the new rosters.
- `test_loader.py`: `test_all_six_canonical_agents_load` → `test_all_canonical_agents_load` now asserts `set(agents) == {10 agents}` (was count==6 + 6-set) — a **set-equality** assertion is at least as strong (identity + count).
- `test_config_loader.py` / `test_templates.py`: expected agent sets + missing-list counts updated to reflect the new rosters (3→4, 4→5). Precise, not loosened. ✓

## 6. Advisory notes (non-blocking)
- **N-1 (cross-track, carry-forward from R0-A-on-plan §5):** none of the 4 new agents are in `ui/src/uiStrings.ts::AGENT_NAME_MAP`, so the GUI renders them as the generic `"助手"`. **不暴露 NOT broken** (fallback-safe; `uiStrings.test.ts:128-133` asserts the safe fallback for unknown agents) and the backend gate suite is unaffected (no backend↔ui coupling). A frontend-track `AGENT_NAME_MAP` addition (P3.6 territory) would give them named labels — architect's call whether to bundle into a frontend cycle. Not in P3.7-content's backend scope.
- **N-2 (existing convention, not introduced here):** the new agents' `dissent_dimensions`/`forbidden_behaviors` are `"TODO: <name>"` placeholders — **but so are the existing canonical agents'** (`skeptic.yaml`: `"TODO: assumption_audit"`, etc.). The new agents match the established convention exactly; this is **not** a P3.7-content regression. If the project wants these fleshed out, it is a project-wide content-debt item (retro territory), not this slice's.
- **N-3 (state, architect-owned):** the impl-branch `.workflow/P3.7-content.yaml` is still `awaiting_junior_impl` (not auto-advanced to `awaiting_senior_plan_vs_impl` despite the 11 impl commits — likely the junior commit env didn't fire the post-commit hook). Flagged only; the architect owns the P3.7-split state. (This R0-A does not advance/override; the hook's advance on my commit was restored.)

## Conclusion
**Verdict: clean.** The impl is a faithful, well-tested pattern-reuse breadth slice: gate green (independently re-run), all five foci pass, discriminating tests are real (gate tiers / fail-closed / present-missing / match-reject), and the existing-test edits are precise (not loosened). No product, constitutional, or trust-surface issue; no Y finding. The three advisories are non-blocking (N-1/N-2 cross-track/convention, N-3 architect-owned state).
