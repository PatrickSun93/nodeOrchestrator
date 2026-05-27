---
task_id: P1.5.5
round: R0-A-on-plan
verdict: needs_architect
findings_count:
  red: 0
  yellow: 2
  green: 8
---

# P1.5.5 R0-A-on-plan review (architect-partner lens)

| Field | Value |
|---|---|
| Round | R0-A-on-plan (plan-stage external review per RC-9; architect leans dispatch per brief Architect-settled decision 5) |
| Reviewer | architect-partner (Claude Opus 4.7, 1M context) in primary session |
| Date | 2026-05-27 |
| Artifacts reviewed | `claude/P1.5.5-plan` @ `093eb04` — `docs/process/senior-plans/P1.5.5.md` (323 lines) + `docs/decisions/ADR-013-operator-tool-dispatch.md` (164 lines, `Proposed`). Brief read on main @ `docs/process/architect-briefs/P1.5.5.md`. Cross-checked against runtime code: `agents/dispatch.py`, `agents/loader.py`, `agents/schema.py`, `autonomy/emission.py`, `autonomy/scoring.py`, `llm/types.py`, `llm/providers/openai_compatible.py`, `llm/parsers/claude_code_output.py`, `tests/agents/test_integration.py`, `tests/agents/test_loader.py`, `config/llm_models.yaml.example`. |
| Workflow context | First plan-stage R0-A since W-003-plan; first 3-atomic-parallel set (`[P1.5.5-1 ‖ P1.5.5-2 ‖ P1.5.5-3]`) post-RC-17 codification (W-003 had 2-parallel). First plan landing alongside an ADR (`adr: ADR-013` → W-002-1 single-ADR path β) since P1.5. First plan to absorb the W-003 routing pattern at scale (pre-investigates ~8 brief push-backs + ~6 self-discoveries in plan §5 instead of deferring to junior at impl time). |

---

## Findings

### 🟡 Y1 — Test fixture `_make_model` capability gap is unaddressed; will surface at junior P1.5.5-1 impl time

**Where:** `tests/agents/test_integration.py:50-58` `_make_model` + `tests/agents/test_integration.py:90-97` `_models_for_config`. Plan §2 P1.5.5-1 acceptance says:

> `validate_consistency` passes for all 3 — first real exercise of `required_capabilities: [tools]` path against operator (per P1.4 R0-A G2 — validation implemented but never run against real data).

**What's missing:** the existing integration tests in `tests/agents/test_integration.py` already load **the real `config/agents/` directory** via `_CONFIG_DIR = Path(__file__).parent.parent.parent / "config" / "agents"` (line 45) and call `load_agents(_CONFIG_DIR, models=_MODELS)`. After P1.5.5-1 promotes `operator.yaml` into `config/agents/`, those existing tests will see operator.yaml + execute `_validate_required_capabilities`. The test fixture `_make_model` declares `capabilities=[]` unconditionally (line 55), so `deepseek_v4_flash` + `qwen_mlx_30b` in the test `_MODELS` registry have no `tools` capability — operator's `required_capabilities: [tools]` validation will **fail at integration-test time**.

**Plan §5 self-discovery #3 caught the `test_loader.py` count assertion** ("currently asserts 2; should assert 5") but missed the parallel impact on `test_integration.py`'s fixture surface.

**Why this matters (W-003 routing pattern):** the W-003 R0-A Y1+Y2 → α routing pattern said "senior pre-investigates deferred-to-impl items at plan revision instead of letting them migrate to junior." This is exactly the same shape — a test-fixture impact that junior P1.5.5-1 will discover when CI breaks + improvise a fix (most likely: extend `_make_model` to inject `[tools]` for `deepseek_v4_flash`/`qwen_mlx_30b`, OR rebuild `_models_for_config()` to construct caps-aware profiles per model_id). The improvise will probably be fine, but the discipline is to pre-pin so the surface area at impl time is "implement the body" not "discover + design the fixture extension."

**Architect-partner lean: α — senior pre-pins the fixture extension in P1.5.5-1 acceptance.** Concrete spec sketch:

```python
# tests/agents/test_integration.py — replace _make_model with caps-aware variant
_CAPS_BY_MODEL: dict[str, list[ModelCapability]] = {
    "deepseek_v4_flash": [ModelCapability.TOOLS],
    "qwen_mlx_30b": [ModelCapability.TOOLS],
    "claude_code_opus_47": [ModelCapability.EFFORT],
    "claude_code_sonnet_46": [ModelCapability.EFFORT],
    "claude_code_haiku_45": [],
    "deepseek_v4_pro": [],
}

def _make_model(mid: str) -> ModelProfile:
    return ModelProfile(
        id=ModelId(mid),
        provider=_PROVIDER,
        provider_model_id=mid,
        capabilities=_CAPS_BY_MODEL.get(mid, []),
        context_window=8192,
    )
```

And extend `_models_for_config` to include `claude_code_haiku_45` + `qwen_mlx_30b` (divergence_mapper / logger / operator chains).

**Alternative routing β: skip — accept impl-time discovery.** Junior is competent + the fix is mechanical. The W-003 routing pattern was about decisions that have lasting refactor cost; this is a fixture-arithmetic decision with trivial reversal cost. Architect may judge the pre-pin overhead > impl-time discovery cost.

**Recommendation: route α** — matches the discipline gradient the project has been climbing (P1.5 Y1 → W-003 Y1+Y2 → P1.5.5 Y1 — same shape, same routing). β is defensible but breaks the curve.

### 🟡 Y2 — Plan §5 #7 claim "Reversibility values match" is empirically incorrect (3 deltas)

**Where:** plan §5 brief push-back #7 (line 268-270):

> Existing `tools.yaml.example` contains all entries brief's architect-partner table suggested plus extras (...). Reversibility values match (the `.example` was architect-approved at creation time per ADR-005 D2; brief's table values are sub-set of what's already approved).

**Empirical check** (diff brief line 179 leans vs `config/tools.yaml.example` current values):

| Tool | Brief lean | `.example` | Delta |
|---|---|---|---|
| `web_fetch` | 9 | 10 | +1 |
| `log_event` | 10 | 8 | −2 |
| `run_tests` | 8 | 9 | +1 |

The other 9 tools brief enumerates (`read_file`, `list_files`, `search_text`, `search_code`, `web_search`, `get_current_time`, `propose_edit`, `apply_edit`, `git_diff`) do match. So "values mostly match (9/12)" is true; "values match" elides the 3 deltas.

**Why this matters:** P1.5.5-2 is described as "rename + delete `.example`; no value-touching" (line 270). That framing is fine for the 9 matching tools but silently picks the `.example` value over the brief lean for the 3 deltas. The plan does NOT call this out, so a casual reader walks away thinking the brief's table was fully reflected.

**Architect-partner lean: α — senior amends plan §5 #7 to explicitly enumerate the 3 deltas + state the routing decision.** Defensible defaults:

- "Earlier `.example` architect-approval at ADR-005 D2 supersedes the brief's table (brief leans, not authoritative override); promote verbatim retains the older values."
- OR: "Brief leans represent most-recent architect thinking; P1.5.5-2 actually-touches values to align with brief (`web_fetch: 10→9`, `log_event: 8→10`, `run_tests: 9→8`)."

Either is fine; the plan should pick + name + defend. **Pre-investigation done well finds these — plan §5 #7 is one architect-routing item that the W-003 routing pattern would have caught earlier.**

**Alternative routing β: skip — promote `.example` verbatim + leave plan §5 #7 framing as-is.** Architect may judge the 3 deltas as small enough that the pre-merge audit cost > post-merge re-tune cost; reversibility values are P1.5+ usage-based tuning territory anyway.

**Recommendation: route α** — the architect-partner lens caught this in ≤5 minutes of grep + diff; the discipline is naming the deviation rather than masking it as "match." Future readers tracing "where did `web_fetch=10` come from?" find the rationale in the plan if α; find silence if β.

### 🟢 G1 — ADR-013 substance is contract-locking + accurate

ADR-013 D1-D5 each map cleanly to a brief Architect-settled decision OR a brief push-back invitation:

- **D1 (sibling module)** ← brief push-back #2 lean + pre-investigation refutation of option (b). Pre-investigation traced `agents/dispatch.py:117-127` and confirmed `response.tool_calls` discarded (`_log.info` records `response.content` only; no `.tool_calls` reference exists in `dispatch.py` — independently verified via `grep -n "tool_calls" src/orchestrator/agents/dispatch.py` → 0 hits). Option (b) "structurally impossible" framing is correct without contract surgery on `TurnResult`.
- **D2 (tier-to-event mapping)** ← brief Architect-settled decision 2. ADR-013 D2 table is verbatim-faithful to ADR-005 D6 + ADR-007 D3 semantics; the "operational restatement" framing avoids re-litigation while keeping the contract visible at the call site.
- **D3 (`user_explicit_intent` derivation)** ← brief predicted self-discovery #2. The "single-event signal sufficient + forward-compatible additive enrichment" rationale is forward-defensible for P1.6+ chain-based intent inference.
- **D4 (tools registry as keyword param)** ← brief predicted self-discovery #5 + pattern-match to `available_skills`/`available_agents`/`regex_registry` threading (P1.4 + P1.5 precedent).
- **D5 (no shim; reuse `LLMResponse.tool_calls`)** ← brief push-back #3 lean + pre-investigation refutation. Pre-investigation cites verified: `openai_compatible.py:270-283` ✓ + `claude_code_output.py:89-108` ✓; both produce `ToolCall(id, name, arguments)` with Pydantic `min_length=1` validation; field mapping in D5 matches `llm/types.py:149-158` exactly.

The "Considered alternatives A/B/C/D" section mirrors the brief's push-back invitation list, making the decision-vs-alternative trace readable.

### 🟢 G2 — Pre-investigation refutations are independently verifiable + remove junior queue items

Three pre-investigations in plan §5 are independently checkable + each removes a junior queue item:

- **#3 (LLM-tool-call parsing shim refuted)**: removes ~1 day of speculative shim work. Brief explicitly leaned "probably needs a shim"; senior refuted with verified cites. Verified independently via grep.
- **#2 (option (b) structurally impossible)**: removes "junior chooses between (a), (b), (c)" from impl-time scope; forces explicit decision in ADR-013 D1.
- **#7 (tools.yaml verbatim-promotable)**: removes "senior derives reversibility values" risk. (See Y2 for the partial-claim caveat.)

This is the **first plan to systematically apply the W-003 routing lesson at the plan-revision boundary** (W-003 pre-resolved 2 items; P1.5.5 pre-resolves ~6). Cumulative "decision-deferred-to-impl" pattern instances stay flat at 3 (P1.5 R0-A Y1 + W-003 R0-A Y1+Y2); P1.5.5 surfaces Y1 + Y2 here at plan stage, so the pattern's pre-impl catch ratio is rising.

### 🟢 G3 — Causal ordering + emit_gate_decision contract use correct

Plan §2 P1.5.5-3 acceptance + ADR-013 D2 both pin: `autonomy_decision` (from `emit_gate_decision`) lands before `tool_call` (appended by `process_tool_calls`) in stream timestamp order, for `AUTO_EXECUTE` tier. Verified against `autonomy/emission.py:35-90`: `emit_gate_decision` appends `autonomy_decision` synchronously before returning `AutonomyScore`; the per-call site then appends `tool_call` only on `AUTO_EXECUTE` tier read. The "decision-then-action" causality from ADR-005 §6 carries through.

`UnknownToolError` path: `emit_gate_decision` (line 64) appends `autonomy_refusal` then re-raises; `process_tool_calls` catches per plan §2 P1.5.5-3 acceptance (line 119) + records `ToolDispatchDecision(tier=None, refusal_reason="unknown_tool")`, continues to next call. The "one bad tool_call doesn't poison the batch" semantic + ADR-007 §3 "append failure must not mask `UnknownToolError`" semantic both honored.

### 🟢 G4 — Layering / constitutional invariant preserved

Plan §2 P1.5.5-3 acceptance line 132:

> No LLM imports (`agents/tool_dispatch.py` imports from `autonomy/emission`, `core/event`, `agents/schema` only). Constitutional test `test_constitution_no_llm_calls_in_autonomy_module` stays green; the new module lives in `agents/` which is allowed to import `autonomy/`, but tool_dispatch itself touches no LLM call site (it consumes pre-parsed `ToolCall` instances).

Verified against `tests/agents/test_constitution.py:23-60`: the agents-module constitutional test forbids `import anthropic` / `from anthropic` / `import openai` / `from openai`. `tool_dispatch.py` consumes `ToolCall` from `llm.types` (allowed — type import, not SDK). The `agents → autonomy` direction is silent in the constitutional tests (no rule forbids it); `autonomy → agents` reverse direction is the explicitly-forbidden one and remains unviolated.

ADR-013 "Consequences §Harder" bullet 3 correctly names: "The `agents → autonomy` runtime import edge is now real (not just allowed)." First runtime use of an allowed-but-quiet edge — matches the P1.4 R0-A G2 forward-looking watch item.

### 🟢 G5 — Parallelism set [P1.5.5-1 ‖ P1.5.5-2 ‖ P1.5.5-3] is file-disjoint + first post-RC-17 3-parallel use

File-disjointness check:
- **P1.5.5-1**: `config/agents/{operator,divergence_mapper,logger}.yaml` (new) + `tests/agents/test_loader.py` (extend).
- **P1.5.5-2**: `config/tools.yaml` (new) + (possibly) test fixture path updates if hardcoded.
- **P1.5.5-3**: `src/orchestrator/agents/tool_dispatch.py` (new) + `tests/agents/test_tool_dispatch.py` (new).

No shared-file edit. Y1 above flags `tests/agents/test_integration.py` as a hidden shared surface across P1.5.5-1 and the existing test fixture — addressing Y1 either pins the fixture update inside P1.5.5-1's acceptance (where it belongs) or skips and lets junior discover.

RC-17 codification (`senior-planner.md` post-`7606093`): "each atomic = one commit with its own subject, no bundling." Plan §3 names 5 distinct commit subjects (`P1.5.5-1: ...`, `P1.5.5-2: ...`, ..., `P1.5.5-5: ...`). First 3-parallel set post-codification raises the bar from 2-parallel (W-003) to 3-parallel; the discipline test is whether 3 parallel junior agents return 3 commits with respective subjects.

### 🟢 G6 — Interface freeze discipline correctly scoped

Plan §2 P1.5.5-3 acceptance (line 115):

> Function signature matches above (frozen via `interface freeze` discipline — see [[feedback_interface_freeze]]: ToolDispatchResult + ToolDispatchDecision shipped this commit; body in same commit since the function is short; **freeze-then-implement gap not required** for a function this small per interface-freeze rule's "for new modules with multiple coupled functions" scoping).

Defensible. `process_tool_calls` is a single function with no internal cross-function coupling; the freeze-then-implement gap exists to let consumers (other tasks) pin against the signature before the body lands. P1.5.5-4 (the only consumer this cycle) lands in the same series; P1.6+ future consumers inherit the frozen `ToolDispatchResult` schema (which IS landed in the signature commit). The scoping interpretation is correct.

### 🟢 G7 — Workflow integration named correctly

Plan §3 + plan §6 + ADR-013 D1 D4 cross-references all converge on:
- `adr: ADR-013` in plan frontmatter → W-002-1 single-ADR path β routing through `awaiting_architect_accept` (NOT W-002-2b no-ADR path; ADR-013 is new).
- Post-architect-Accept: `workflow advance` fires `awaiting_architect_accept → awaiting_junior_impl`.
- `workflow verify-merge-readiness --task-id P1.5.5` (new from W-003-2) referenced as forcing function in P1.5.5-5 acceptance.
- `workflow verify-workspace` (codified in CLAUDE.md per W-003-4) referenced as forcing function at session start + pre-landing.

The W-003 closures (RC-13 + RC-16 + RC-17) all flow through correctly. P1.5.5 is the first cycle to consume all three closures together.

### 🟢 G8 — Brief Architect-settled decisions 1-7 all honored

Verified against brief:

| Brief decision | Plan/ADR landing |
|---|---|
| 1 (tool-call gating is code; LLM-proposes-code-decides first runtime exercise) | ADR-013 Context §3 + D1 |
| 2 (tier-to-event mapping per ADR-005 D6 + ADR-007 D3) | ADR-013 D2 (operational restatement) |
| 3 (operator `llm_config` per handoff §5.5) | Plan §2 P1.5.5-1 acceptance lines 41-43 verbatim |
| 4 (tool execution defer to P1.6+) | ADR-013 Considered Alternative D rejected + Consequences "Neutral" bullet 3 |
| 5 (architect-partner R0-A dispatch RC-9) | This file |
| 6 (cross-family R0-B skip per RC-15) | Plan §6 line 313 |
| 7 (workflow integration via W-002-1 path β) | Plan §3 line 182 + plan §6 line 309 |

The brief's "Open invitation" (line 222-231) bullets that explicitly invited push-back also addressed in plan §5 (push-backs #1-#8); senior didn't push back on any of the architect-settled decisions (correctly — they're settled).

---

## Push-back disposition table

Plan §5 addresses 8 brief push-backs + 6 brief predicted self-discoveries + 3 senior NEW self-discoveries. Architect-partner concurrence per item:

### Brief push-backs

| # | Brief lean | Plan disposition | Architect-partner concurrence |
|---|---|---|---|
| 1 | YES on ADR-013 | YES — D1-D5 inscribed | ✓ Concur — first runtime `agents → autonomy` edge merits contract-lock |
| 2 | Sibling module | Sibling module (option (c)) — option (b) refuted as structurally impossible | ✓ Concur — independently verified `tool_calls` discard at `dispatch.py:117-127` |
| 3 | Probably shim needed | NO shim — refuted by pre-investigation | ✓ Concur — independently verified both parsers produce normalized `ToolCall(id, name, arguments)` |
| 4 | `[user_input, hypothesis]` triggers | Accepted; pinned in operator.yaml | ✓ Concur — workhorse pattern, no auto-activation on `state_change` |
| 5 | Explicit `applies_to.room_types` excluding `free_chat` | Accepted; `[research, bug_fix, code_review, idea_validation]` pinned | ✓ Concur — no tool-using dynamics in `free_chat` |
| 6 | TODO placeholders for divergence_mapper/logger content | Accepted | ✓ Concur — Skeptic pattern from P1.4 decision 4 |
| 7 | Promote `.example` verbatim | Accepted | ⚠ See Y2 — "values match" claim is partially incorrect (3 deltas); routing needed |
| 8 | `autonomy_decision` before `tool_call` for AUTO_EXECUTE | Accepted; ADR-013 D2 locks | ✓ Concur — verified causal ordering invariant in `autonomy/emission.py:35-90` |

### Brief predicted self-discoveries

| # | Brief content | Plan disposition | Concurrence |
|---|---|---|---|
| 1 | `Operation.estimated_cost_usd` | Default `0.0` (P1.7+ HG layer adds) | ✓ Concur |
| 2 | `Operation.user_explicit_intent` derivation | Derive from `current_event.type == EventType.USER_INPUT` (ADR-013 D3) | ✓ Concur — single-event signal sufficient + forward-compatible |
| 3 | `autonomy_decision.operation_initiating_agent` | Pass-through from agent.id via Operation.initiating_agent | ✓ Concur |
| 4 | Operator cooldown | 10s (mid of 5-15s suggestion) | ✓ Concur |
| 5 | Tools registry threading | Keyword param on run_turn + dispatch_turn (ADR-013 D4) | ✓ Concur — mirrors `available_skills` etc. |
| 6 | `call_id` validation | Already enforced by `ToolCall.id` Pydantic `min_length=1`; PermanentProviderError on omit | ✓ Concur |

### Senior NEW self-discoveries

| Tag | Content | Concurrence |
|---|---|---|
| S1 | Operator `autonomy_thresholds` source = `agent.autonomy_thresholds` (per-agent, not global) | ✓ Concur |
| S2 | `process_tool_calls` return logged but NOT in TurnResult | ✓ Concur — preserves reviewer-validated contract; observability via event_store query (ADR-001 canonical) |
| S3 | `test_loader.py` 2→5 assertion bump | ✓ Concur — but see Y1 for the unaddressed `test_integration.py` impact |

---

## Cross-checks

- [x] Brief Architect-settled decisions 1-7 all honored.
- [x] ADR-013 status `Proposed`; will bump to `Accepted` post-architect-Accept commit per project pattern.
- [x] Plan frontmatter declares `adr: ADR-013` → W-002-1 single-ADR path β (NOT W-002-2b).
- [x] Constitutional invariant: `agents → autonomy` direction allowed; reverse stays forbidden. No new constitutional test needed.
- [x] Pre-investigation cites independently verifiable: `dispatch.py:117-127`, `openai_compatible.py:270-283`, `claude_code_output.py:89-108`, `autonomy/emission.py:35-90`.
- [x] Tier-to-event mapping (ADR-013 D2) faithful to ADR-005 D6 + ADR-007 D3 + ADR-006.
- [x] `TurnResult` contract preserved (ADR-013 D1 rationale).
- [x] `process_tool_calls` signature uses `EventStore` (synchronous, ADR-011 D1 shape — matches `dispatch_turn`'s P1.5+ async-reshape watch).
- [x] Parallelism set [P1.5.5-1 ‖ P1.5.5-2 ‖ P1.5.5-3] file-disjoint at write level (Y1 flags a hidden test-fixture coupling).
- [x] RC-17 codification: 5 distinct commit subjects named in plan §3.
- [x] W-003 closures referenced: RC-13 (`verify-merge-readiness` in P1.5.5-5 acceptance), RC-16 (origin/main frontmatter reads — implicit; will exercise on `workflow advance` calls), RC-17 (parallelism commit-subject discipline).
- [x] Distance test honored: same-day plan-stage per RC-8 substrate canon; junior impl per substrate canon; no per-task pause beyond ADR-013 Accept.

---

## Net assessment

**Verdict: needs_architect.** Two 🟡 architect-routing-eligible findings; zero 🔴; eight 🟢.

Both Y findings are the **same shape as W-003 R0-A Y1+Y2**: pre-investigation gap at plan-revision boundary where senior catches most items (~6 well-resolved push-backs + self-discoveries) but misses 1-2 that would benefit from explicit pre-pin instead of deferring to impl time.

- **Y1 (test fixture capability gap)** is the higher-stakes of the two; the W-003 routing pattern's discipline gradient pulls toward α (senior pre-pins the fixture extension).
- **Y2 (`.example` 3-delta-from-brief)** is lower-stakes; α (senior names + defends) is the discipline-consistent route; β (skip + accept the elision) defensible if architect judges the audit cost > value.

If both route α, **senior revision pass at most ~30 minutes of edit time** (one §5 #7 paragraph rewrite + one §2 P1.5.5-1 acceptance bullet addition + sketch test fixture edit). Post-revision, R0-A-on-plan verdict bumps `needs_architect → clean` per RC-10 codified protocol.

## Forward implications

- **3-parallel discipline test pending**: P1.5.5 impl phase will be the first 3-parallel post-RC-17-codification run. Discipline-held empirics: 3 commits with respective subjects → discipline scales linearly. Discipline-broken empirics: bundling → RC-17 needs sharper enforcement (CI grep? `senior-planner.md` further codification?).
- **First runtime use of `agents → autonomy` edge** at P1.5.5 close; constitutional test surface gains a load-bearing pass instead of vacuous one. Set up the "edge has a real user" watch for P1.6+.
- **First exercise of `required_capabilities: [tools]` validation against real config data** at junior impl time (per brief Architect-settled decision 3 + P1.4 R0-A G2 forward-looking watch). Y1 routing α positions this exercise to land cleanly.
- **Override count freezes at 2** (P1.3 + W-002 pre-fix bridges) if P1.5.5 closes without override; **6th consecutive zero-override cycle** (W-002.5 → P1.4 → P1.5 → W-003 → P1.5.5 → P1.6). Substrate at mature steady state.
- **P1.6 (snapshot mechanics + decision log + e2e) inherits** a runtime-exercised autonomy gate + tool-call event stream. The "no orphaned spec" principle 9 closure at P1.5.5 means `tool_call` events flow from real producers; P1.6's snapshot can consume them uniformly.

## Captured for P1.5.5 retro

- **W-003 routing pattern adoption depth**: plan §5 pre-resolves ~6 items at plan revision; 2 items (Y1+Y2) still surface at R0-A. Pattern adoption ratio: 6/8 = 75% — high but not 100%. Codification target: `senior-planner.md` addendum on "checklist of test-fixture impacts when promoting `.example` configs."
- **First 3-parallel set post-RC-17**: empirical outcome (3 commits with respective subjects vs bundling) is the RC-17 discipline-scaling proof.
- **First runtime exercise of `required_capabilities: [tools]` validation path**: closes P1.4 R0-A G2 watch (validation implemented but never run against real data).
- **First runtime use of `agents → autonomy` edge**: closes P1.4 R0-A G4 watch + post-P1.5 deferred item.
- **Brief withdrawal + re-authorship precedent** (architect-partner authored P1.5.5 brief after withdrawing senior-delegated draft `e29e42b` at `c3461ee`): per brief §"Brief-authorship integrity note" first documented case; sets precedent for future drift discipline. Worth a retro section.
- **Decision-deferred-to-impl pattern** count: still 3 cumulative (P1.5 R0-A Y1 + W-003 R0-A Y1+Y2). P1.5.5 Y1+Y2 surface at plan stage (caught by reviewer) instead of impl stage (would surface as junior improvisation). The catching-mechanism moved upstream by one boundary. Worth a retro note.

## Cross-references

- `docs/process/architect-briefs/P1.5.5.md` — architect-partner authored brief (commit `7606093`); load-bearing for the Architect-settled decisions disposition table above.
- `docs/process/senior-plans/P1.5.5.md` — plan under review (this file's subject).
- `docs/decisions/ADR-013-operator-tool-dispatch.md` — proposed ADR landing alongside the plan; reviewed inline above.
- `docs/process/reviews/W-003/R0-A-on-plan.md` — pattern-source for the Y1/Y2 routing shape.
- `docs/process/reviews/W-003/architect-routing.md` — precedent for the "decision-deferred-to-impl" routing pattern.
- `docs/process/reviews/README.md` § Post-resolution verdict-bump protocol — protocol for the `needs_architect → clean` bump after senior absorbs routing.
- `docs/process/dual-lens-r0b.md` — RC-15 codification (this review skips cross-family R0-B per architect-routed skip + brief explicit skip).
- `docs/process/senior-planner.md` (post-`7606093`) — RC-17 parallelism commit-subject discipline; P1.5.5 is first 3-parallel post-codification.
