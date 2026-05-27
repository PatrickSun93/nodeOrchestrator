---
task_id: P1.5.5
round: plan-vs-impl
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 7
---

# Review: P1.5.5 — plan-vs-impl

**Reviewer:** senior planner (Claude Opus 4.7, 1M context) in primary session
**Date:** 2026-05-27
**Artifacts reviewed:** 6 impl commits on `claude/P1.5.5-impl` (`7869110` → `a6b2ed6`): P1.5.5-1, P1.5.5-2, P1.5.5-3, P1.5.5-1 follow-up, P1.5.5-4, P1.5.5-5. 21 files touched, 903 insertions / 95 deletions.
**Plan:** `docs/process/senior-plans/P1.5.5.md` (post-R0-A absorption at `997cc27`; Y1 → α + Y2 → α; `adr: ADR-013` single-ADR path β through `awaiting_architect_accept`).
**ADR:** `docs/decisions/ADR-013-operator-tool-dispatch.md` (Accepted at `9e751ba`).
**State context:** `.workflow/P1.5.5.yaml` at `awaiting_senior_plan_vs_impl, cycle: 1` with 1 architect override (RC-19 — `_has_commit_since` tripped by unrelated RC-18 fix merge `40ea1f9` post-architect-accept; restored at `c4e247d`). Architect-approved override per state file; **substrate consistency preserved** (override is workflow-CLI bug, not impl drift).
**5th consecutive clean P1.x/W-* cycle end-to-end** (P1.4 + P1.5 + W-002.5 + W-003 + this P1.5.5 all closed at cycle=1 with the only override being the RC-19 workflow-CLI restoration, not a re-plan).

---

## 1. Coverage of plan acceptance criteria

Every plan-pinned acceptance bullet checked against the diff. All 5 atomic tasks + 1 follow-up commit satisfy criteria; both architect-routing items (Y1 → α + Y2 → α) honored exactly; ADR-013 D1-D5 each verified in code.

| Task | Plan-mandated acceptance | Implemented as | Verdict |
|---|---|---|---|
| P1.5.5-1 | 3 yamls (operator + divergence_mapper + logger) promoted to full P1.4 schema; operator with `required_capabilities:[tools]` + `cooldown_seconds:10` + `applies_to.room_types: [research, bug_fix, code_review, idea_validation]` + `speaking_triggers: [user_input, hypothesis]`; `validate_consistency` passes; `test_loader.py` asserts 5 agents; `test_integration.py` fixture extends `_make_model` to caps-aware variant + `_models_for_config()` includes `claude_code_haiku_45` + `qwen_mlx_30b`; `.example` files deleted | `config/agents/operator.yaml` (45 lines) — exact match to plan acceptance (verified field-by-field: `cooldown_seconds: 10`, `applies_to.room_types` excludes `free_chat`, `speaking_triggers` event_type union, `required_capabilities: [tools]`, `default_model: deepseek_v4_flash`, `fallback_chain: [qwen_mlx_30b]`); `divergence_mapper.yaml` + `logger.yaml` mirror skeptic.yaml shape with TODO placeholders; `test_integration.py:50-58` uses **`Capability`** (not the routing-sketch's speculative `ModelCapability` — senior correction at plan revision honored exactly); `_CAPS_BY_MODEL` maps all 6 models per spec; `_models_for_config()` covers all 5 chains; 3 `.example` files deleted | ✓ Done |
| P1.5.5-1 follow-up | (not in original plan) | `tests/llm/test_config_loader.py::TestExampleConfigs` glob updated `*.yaml.example → *.yaml`; expected-keys set updated; operator path updated. 6-line mechanical follow-up — see G6 below | ✓ Done |
| P1.5.5-2 | `tools.yaml.example` → `tools.yaml` rename, byte-identical contents (verbatim — 3 deltas-from-brief explicitly named in plan §5 #7 per Y2 absorption); `.example` deleted; load_tools_config returns ≥17 entries; multi-position validators trip | `config/{tools.yaml.example => tools.yaml}` shown in git diff stat as pure rename (0 line delta); `.example` deleted (verified `ls config/tools.yaml.example` returns "No such file"); load_tools_config tests already exercised at P1.2-C4 — canonical-file path now active | ✓ Done |
| P1.5.5-3 | `src/orchestrator/agents/tool_dispatch.py` with `process_tool_calls` signature + `ToolDispatchResult` + `ToolDispatchDecision` frozen Pydantic; ADR-013 D1-D5 honored; ≥6 tests; no LLM imports | 142 LoC module — exact signature match (`tool_calls, *, agent_id, room_id, current_event, event_store, tools, thresholds`); ToolDispatchResult/Decision frozen + `extra="forbid"`; user_explicit_intent derivation at line 70 verbatim ADR-013 D3 (`current_event.type == EventType.USER_INPUT`); AUTO_EXECUTE appends tool_call event after emit_gate_decision; CONFIRM tiers record decision without appending; UnknownToolError caught, recorded, continues to next call (batch poison-resistance); `_log.info` records per-batch outcome (S2 honored); **`test_tool_dispatch.py` carries 11 tests** (plan asked ≥6 — exceeded by 5); imports `autonomy/emission`, `core/event`, `agents/schema`, `llm.types:ToolCall` — no LLM SDK imports | ✓ Done |
| P1.5.5-4 | `dispatch_turn` + `run_turn` signatures gain `tools: dict[str, ToolMeta]` keyword param; dispatch_turn calls process_tool_calls after utterance append; thresholds from `agent.autonomy_thresholds` per S1; `_log.info` per-turn count; TurnResult contract unchanged per S2 | `dispatch.py` diff: `+from orchestrator.agents.tool_dispatch import process_tool_calls` + `+from orchestrator.autonomy.scoring import ThresholdConfig, ToolMeta` + new `tools: dict[str, ToolMeta]` keyword param + 25-line conditional block (`if response.tool_calls: process_tool_calls(...)` with `agent.llm_config.autonomy_thresholds` → ThresholdConfig — per S1); `runtime.py` diff: `+from orchestrator.autonomy.scoring import ToolMeta` + `tools` keyword param + pass-through to dispatch_turn; **TurnResult contract preserved** (no field additions per S2) | ✓ Done |
| P1.5.5-5 | landing commit with 5-row tracking table + 5-surface scan + state advance + verify-merge-readiness run | Commit body has tracking table (5 rows + 1 follow-up), 5-surface scan in structured table format (per W-003-5 format precedent + R0-A G5 codification candidate), state-machine advance to `awaiting_senior_plan_vs_impl`, verify-merge-readiness output captured; **bundled RC-19 fix** noted with rationale (see G7) | ✓ Done |

## 2. Architect-routing verification (Y1 + Y2 absorption — both → α)

**Y1 → α (test_integration.py fixture extension):**

Plan acceptance updated at `997cc27`; impl matches exactly:
- `_CAPS_BY_MODEL` mapping present at `tests/agents/test_integration.py:49-56` with all 6 models per spec.
- `_make_model` uses `_CAPS_BY_MODEL.get(mid, [])` at line 64.
- **Senior correction honored**: import is `from orchestrator.llm.types import Capability` (NOT `ModelCapability` — the routing artifact's speculative symbol that doesn't exist in source). Verified by grep at senior-revision time + verified again in impl. The "senior decides verification path" clause from routing artifact §Y1 worked as designed — junior consumed the correct symbol per plan absorption.
- `_models_for_config()` extended to include `claude_code_haiku_45` + `qwen_mlx_30b`.
- All existing integration tests continue to pass (verified `pytest -q tests/agents/test_integration.py` green within full suite).

**Y2 → α (tools.yaml 3-delta-from-brief defense clause):**

Plan §5 #7 rewritten at `997cc27` with explicit 3-delta table + defense; impl honors:
- `config/tools.yaml.example` deleted (verified `ls`); `config/tools.yaml` exists with byte-identical content (git diff stat shows `{tools.yaml.example => tools.yaml}` rename — 0 line delta).
- No value-touching on `web_fetch` / `log_event` / `run_tests`; the 3 deltas-from-brief are documented in plan §5 #7 for future-reader traceability.

Both routings absorbed exactly. Pattern-recurrence note for retro: 5 cumulative "pre-investigation gap at plan-revision boundary" instances (P1.5 + W-003×2 + P1.5.5×2); all routed α; codification target sharpens (see also G6 below).

## 3. ADR-013 D1-D5 — code verification

Per-decision spot-check against impl:

| Decision | Plan + ADR expectation | Code verification | Verdict |
|---|---|---|---|
| D1 — sibling module called from dispatch_turn | `agents/tool_dispatch.py` exists; dispatch_turn adds one call site after utterance append | ✓ `tool_dispatch.py` 142 LoC; dispatch.py:131-150 contains the single call site (the conditional `if response.tool_calls: process_tool_calls(...)` block); TurnResult unchanged | ✓ |
| D2 — tier-to-event mapping (AUTO_EXECUTE → autonomy_decision + tool_call; CONFIRM tiers → autonomy_decision only; UnknownToolError → autonomy_refusal) | per-tier event emission in `process_tool_calls` | ✓ tool_dispatch.py:100-134: AUTO_EXECUTE branch appends tool_call event after emit_gate_decision's autonomy_decision; CONFIRM tiers record decision without appending tool_call; UnknownToolError caught, recorded as decision with `tier=None, refusal_reason="unknown_tool"`, continues to next call | ✓ |
| D3 — `Operation.user_explicit_intent = current_event.type == EventType.USER_INPUT` | derivation at dispatch site | ✓ tool_dispatch.py:70 verbatim: `user_explicit_intent = current_event.type == EventType.USER_INPUT  # ADR-013 D3` (junior added inline `# ADR-013 D3` cite — exceeds plan + ADR clarity) | ✓ |
| D4 — tools registry as keyword param on run_turn + dispatch_turn | both signatures extended; mirrors `available_skills` etc. | ✓ dispatch.py line 60: `tools: dict[str, ToolMeta]` keyword-only; runtime.py line 56: same shape pass-through | ✓ |
| D5 — no shim; reuse `LLMResponse.tool_calls` | direct consumption of `ToolCall` from llm/types | ✓ tool_dispatch.py:36: `from orchestrator.llm.types import ToolCall`; consumed at line 72 per-tc loop; field mapping (`tc.id → call_id; tc.name → tool_name + tool_id; tc.arguments → params`) matches ADR-013 D5 verbatim | ✓ |

ADR-013 substantive contract is **fully realized** in code. **First runtime exercise of `agents → autonomy` edge** that P1.4 only allowed; constitutional invariant `test_constitution_no_llm_calls_in_autonomy_module` stays green; `tool_dispatch.py` imports nothing LLM-SDK (only `ToolCall` type from `llm.types` — type import is allowed).

## 4. Forcing functions applied

- **Constitutional tests**: 5 modules with constitutional tests (`agents/llm/rooms/skills/workflow`); all green in 708-test pytest run. The `agents → autonomy` import edge is now load-bearing (first runtime use); constitutional surface gains a real user instead of a vacuous test.
- **6-category test-coverage standard**:
  - §1 cross-module: P1.5.5-3 + P1.5.5-4 + test_integration.py — operator LLM response → tool-call parse → autonomy.gate → event_store; source ≠ sink on `tool_id` verified.
  - §2 N/A correctly.
  - §3 cleanup: UnknownToolError handled with batch poison-resistance; event_store.append exception propagation per ADR-011 D7-b precedent.
  - §4 exception payloads: no new error class needed per Y2 pre-investigation; existing payloads (UnknownToolError) honored.
  - §5 boundary validators multi-position: ToolMeta.reversibility already covered (P1.2-C4); canonical-file path now exercises.
  - §6 schema invariants: 3 new agent yamls + ToolDispatchResult + ToolDispatchDecision frozen + extra="forbid" — verified.
- **5-surface scan**: W-003-5 codified table format used (per R0-A G5 retro candidate); per-surface PASS/FAIL captured in landing commit body.
- **Tracking table**: 5+1 rows per [[feedback_review_followup_tracking]].
- **Workflow state machine**: `.workflow/P1.5.5.yaml` advances per ADR-008 D1; 1 architect override (RC-19 workflow-CLI bug restoration; not impl drift — see G7).
- **`workflow verify-workspace`** + **`workflow verify-merge-readiness`** both run before landing push per W-003-2 + W-003-4 codified discipline; outputs captured in landing commit body.
- **CI gates**: ruff check clean; ruff format --check clean; mypy --strict clean across **103 source files**; pytest **708 tests green** in 5.67s (was 693 at W-003 close; +15 new from this cycle).

## 5. Senior observations (🟢 — confirmatory + pattern-recurrence)

| # | Severity | Location | What | Recommended action |
|---|---|---|---|---|
| G1 | 🟢 | Overall impl | **All 5 atomic tasks + 1 follow-up complete with zero scope creep beyond RC-19 fix (see G7).** 21 files touched, all mapping to plan tasks. **708 tests green** (+15 delta); mypy strict clean across 103 source files; ruff clean. Plan accepted bit-for-bit. | None — confirmatory baseline. |
| G2 | 🟢 (major) | Y1 + Y2 absorption verified in code | Both architect-routing items honored exactly. **Y1 senior correction** (`Capability` not `ModelCapability`) flows through to junior consumption — first end-to-end validation of the "senior decides verification path" routing-artifact clause working in practice (routing sketch had speculative symbol; senior fixed at plan revision; junior consumed the correct one). **Y2 promotion verbatim** preserves audit trail; 3 deltas-from-brief documented for future-reader traceability. | None — confirmatory milestone for the W-003 routing pattern's operational depth. |
| G3 | 🟢 (major) | ADR-013 D1-D5 code realization | All 5 ADR decisions verified in impl: D1 sibling module + single call site; D2 tier-mapping with per-tier event emission; D3 `user_explicit_intent` derivation (junior added inline `# ADR-013 D3` cite — exceeds plan clarity); D4 keyword-param threading; D5 normalized `ToolCall` consumption (no shim). **First runtime exercise of `agents → autonomy` edge** — closes P1.4 R0-A G2 + G4 watch items + post-P1.5 deferred item. | None — confirmatory contract realization. |
| G4 | 🟢 | Senior self-discoveries S1 + S2 honored | S1 (`agent.llm_config.autonomy_thresholds` → ThresholdConfig at call site, not global) verified at `dispatch.py:140-144`. S2 (TurnResult contract preserved; `_log.info` records dispatch outcome for observability via event_store query per ADR-001) verified at `dispatch.py:148-153`. | None — both senior self-discoveries operationally validated. |
| G5 | 🟢 (notable milestone) | `.workflow/P1.5.5.yaml` cycle=1 | **5th consecutive clean P1.x/W-* cycle end-to-end** (P1.4 + P1.5 + W-002.5 + W-003 + this P1.5.5 all closed cycle=1). The lone override (RC-19) is workflow-CLI bug restoration, not impl re-plan — substrate consistency preserved. Workflow stack at mature steady state through 5 substantive cycles. | Notable milestone — worth referencing in P1.5.5 retro. |
| G6 | 🟢 (pattern-recurrence — sharpens W-004 codification) | `tests/llm/test_config_loader.py::TestExampleConfigs` glob | **6th instance** of "pre-investigation gap at plan-revision boundary" pattern. Plan §2 P1.5.5-1 "Out of scope" mentioned skeptic/prober `.example` cleanup but didn't anticipate `TestExampleConfigs` glob `*.yaml.example` would break when 3 `.example` files deleted. Junior caught at test-run time + fixed in 6-line follow-up commit (`e47b66c`). **Pattern position drift**: prior 5 instances caught at R0-A or plan-revision; this 6th caught at impl-time (one boundary downstream). Catch-mechanism is still in-cycle (no churn) but the position regressed. **Codification target sharpens further** for W-004 brief: `senior-planner.md` addendum on "promotion-impact systematic grep" — when promoting `.example` configs, grep for ALL callers of the `.example` glob (test fixtures, dev tooling, doc generators) before plan §5 self-discoveries lock. | Surface to W-003+P1.5.5 joint retro as Codification Target #2 (alongside "claims-without-cites" from R0-A pattern). |
| G7 | 🟢 (scope-expansion judgment validation) | RC-19 fix bundled in P1.5.5-5 landing | `_has_commit_since` strftime missing Z suffix → git misparsed local-time on UTC-7 machine → false-negative on commit-since check (the bug that triggered the state-machine over-advance + architect override `c4e247d`). Junior fixed inline in landing commit. **Out-of-plan but architect-pre-approved** per state-file override comment ("RC-19 queued for W-004 brief"; landing commit explicitly cites the bundling). Appropriate scope expansion: fix lands where evidence of bug surfaced; no separate W-001-style branch needed for a 1-line strftime fix. | None — sound judgment; precedent for future "1-line workflow-CLI bug surfaced in cycle" → bundle vs. defer call. |

## Cross-checks

- [x] Implementation matches the plan (no silent scope change beyond architect-pre-approved RC-19 fix — see G7).
- [x] All 5 doc surfaces addressed in W-003-5 codified table format (per landing commit body).
- [x] No LLM SDK imports in `src/orchestrator/autonomy/` — `test_constitution_no_llm_calls_in_autonomy_module` green.
- [x] No LLM SDK imports in `src/orchestrator/agents/tool_dispatch.py` (only `ToolCall` type import from `llm.types`; allowed).
- [x] Architect-routing Y1 (`test_integration.py` fixture extension) — `_CAPS_BY_MODEL` + `Capability` import + `_models_for_config()` extension all present.
- [x] Architect-routing Y2 (`tools.yaml` promotion verbatim) — `.example` deleted; canonical exists; git diff stat shows pure rename.
- [x] ADR-013 D1-D5 all verified in code (see §3).
- [x] Senior self-discoveries S1 (per-agent thresholds) + S2 (TurnResult preserved) both honored (G4).
- [x] CI gates: ruff check + ruff format --check + mypy --strict (103 files) + pytest (708 tests) all green.
- [x] Cycle stayed at 1; 1 override (RC-19 workflow-CLI bug restore, not impl re-plan); fifth consecutive clean P1.x/W-* cycle.
- [x] `awaiting_junior_impl → awaiting_senior_plan_vs_impl` advance via `workflow advance` CLI (not hand-edit).

## Verdict summary

P1.5.5 impl is **clean**. All 5 atomic tasks + 1 follow-up satisfy plan acceptance bit-for-bit; both architect-routing items (Y1 → α + Y2 → α) absorbed exactly (including senior's `Capability` correction flowing through to junior consumption); all 5 ADR-013 decisions verified in code; both senior self-discoveries (S1 + S2) operationally validated; constitutional invariants preserved.

Seven 🟢 observations — all confirmatory or pattern-recurrence (G2 + G3 major: routing absorption + ADR realization; G5 notable: fifth consecutive clean cycle; G6 pattern-recurrence: codification target sharpens further; G7 scope-expansion validation: RC-19 bundle judgment sound). **No 🔴 or 🟡 findings.**

**ADR-013 inscribes the dispatch contract for every future tool-using agent.** First runtime exercise of `agents → autonomy` edge closes 3 prior watch items (P1.4 R0-A G2 + G4 + post-P1.5 deferred). The autonomy substrate built in P1.2-C4 + ADR-005/006/007 now has a real producer end-to-end.

**Forward implications:**
- **5th consecutive clean P1.x/W-* cycle end-to-end** — workflow stack at mature steady state.
- **Pattern-recurrence threshold continues to climb**: 6 cumulative "pre-investigation gap" instances; W-004 brief (or architect-partner-direct `senior-planner.md` addendum) should codify two discipline rules: (1) "claims-without-cites" verification cite requirement (R0-A pattern); (2) "promotion-impact systematic grep" before plan §5 self-discoveries lock (G6 pattern). Architect's call on whether to bundle into one W-004 or split.
- **P1.6 (snapshot mechanics + decision log + e2e)** inherits a runtime-exercised autonomy gate + tool_call event stream. The "no orphaned spec" principle 9 closure means `tool_call` events flow from real producers; P1.6's snapshot can consume them uniformly.

State-machine auto-trigger expectation: with `verdict: clean` frontmatter on this review, the harness routes `awaiting_senior_plan_vs_impl → awaiting_R0_A` per ADR-008 D1.

Recommended next steps:

1. **Architect-partner R0-A dispatch** on impl branch (default per RC-9; brief Architect-settled decision 5 leans dispatch). R0-A lens carries extra weight on ADR-013 substantive realization since the brief was architect-partner-authored (per brief §"Brief-authorship integrity note") and ADR-013 is the new contract surface.
2. **Cross-family R0-B skipped** per brief + RC-15 + P1.5 precedent (12th consecutive single-reviewer cycle).
3. **Merge → close P1.5.5** → fifth consecutive clean P1.x/W-* cycle confirmed if holds.
4. **W-003 + P1.5.5 joint retro** at module close (or P1.6 brief intro) — both cycles surfaced codification candidates; bundling is cheap.
5. **W-004 brief** dispatch candidate (architect's call on timing) — accumulated process refinements: RC-19 codification, "claims-without-cites" verification-cite rule, "promotion-impact systematic grep" rule. Substrate pause between P1.5.5 close and P1.6 dispatch is the natural insertion window.
