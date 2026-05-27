---
task_id: P1.4
kind: pre-impl-spec
date: 2026-05-27
artifacts_addressed:
  - audit_item: 4
    title: required_capabilities startup validation never run
    status: resolved-by-discovery
  - audit_item: 5
    title: config/agents/ empty
    status: drift-surfaced
---

# P1.4 pre-impl spec (architect-partner)

**Purpose**: surface schema-content drift between the P1.4-4 plan schema and the existing P1.1/P1.2 `AgentLLMConfig` + `AgentAutonomyThresholds` types **before** P1.4 junior impl begins. Audit items #4 + #5 predicted this drift would otherwise surface mid-impl as a P1.4-5 scope expansion or P1.1 patch. Pre-emptive resolution: this artifact + 2 draft yamls (junior consumes during P1.4-9).

**Authored**: architect-partner in-session (low role-collapse risk — pre-impl spec is architect-partner-scope, NOT senior-replan or junior-impl). Junior session at P1.4-9 reads this + the senior plan + the ADRs; lands actual `.yaml` files per its own acceptance criteria.

---

## 1. Audit #4 — required_capabilities validation resolution

**Audit concern (verbatim)**: "Agent 配置的 required_capabilities 启动验证从未被实现过 ... 这个验证从 P1.1 close 到现在从未真正跑过 — 因为到目前为止没有任何一个 agent yaml 被实际加载过。"

**Resolution by discovery**: the validation IS implemented, at `src/orchestrator/llm/config_loader.py:295-345` (`validate_consistency`). The function checks:

- Every model's `provider` exists in `providers`.
- Every agent's `default_model` and `fallback_chain` entries exist in `models`.
- **Every agent with `required_capabilities: [tools]` resolves to at least one model whose provider returns `can_use_orchestrator_tools() == True`** — catches the ADR-003 canonical "operator pointed at Claude Code" misconfiguration at startup.

API surface for P1.4-5 agent loader to consume:

```python
from orchestrator.llm.config_loader import validate_consistency, load_agent_llm_config
from orchestrator.llm.types import Capability
from orchestrator.llm.router import ModelRegistry, ProviderRegistry

# In load_agents:
#   1. For each agent yaml, load via load_agent_llm_config(path, models)
#      → returns AgentLLMConfig (incl. autonomy_thresholds; see §2 drift below).
#   2. After all agents loaded, call validate_consistency(providers, models, agent_configs)
#      → raises ConfigError listing ALL violations at once.
```

**P1.4-5 plan acceptance criterion adjustment**: instead of P1.4-5 implementing `required_capabilities` validation from scratch, P1.4-5 **calls `validate_consistency`** post-load. Reuses existing logic; no scope expansion to P1.1 patch needed.

Audit item #4 status: **resolved by discovery + reuse**. The validation code path was built but never exercised because no agent yaml has been loaded; P1.4 is the first real load. No P1.1 amendment needed.

---

## 2. Audit #5 — config/agents/ drift findings

**Audit concern (verbatim)**: "config/agents/ 目录至今是空的 ... agent 配置从未被加载和验证过。"

**Partial counter-evidence**: `config/agents/` already contains 5 `.yaml.example` files (prober, skeptic, operator, divergence_mapper, logger) from P1.1/P1.2 era. They cover the `llm_config:` + `autonomy_thresholds:` sub-blocks but NOT the P1.4-added fields (id, role, persona, dissent_dimensions, forbidden_behaviors, speaking_triggers, cooldown_seconds).

The audit's stronger framing — "the full agent schema (handoff.md §4.4) Pydantic models will hit real data for the first time in P1.4" — **is correct**. Drift surfaced:

### 🟡 Drift D1 — P1.4-4 `Agent.llm_config: AgentLLMConfig` hides the `autonomy_thresholds` YAML key

**Where**: P1.4 plan §P1.4-4 schema (line 131-143 of plan), P1.4-9 acceptance (lines 290-291 of plan).

**What**: P1.4-4 declares:
```python
class Agent(BaseModel):
    ...
    llm_config: AgentLLMConfig
```

P1.4-9 acceptance writes the yaml as `llm_config: {default_model, fallback_chain, temperature}`.

But `AgentLLMConfig` (P1.2) REQUIRES `autonomy_thresholds: AgentAutonomyThresholds`. Today's yaml shape (from existing examples) puts `autonomy_thresholds:` at the **top level**, sibling to `llm_config:`, NOT nested:

```yaml
llm_config:
  default_model: ...
  fallback_chain: [...]
  temperature: 0.3
  required_capabilities: []
autonomy_thresholds:        # <-- top-level sibling, not nested in llm_config
  threshold_auto: 8
  threshold_confirm: 5
  user_intent_modifier: 2
```

`load_agent_llm_config` in `config_loader.py:198-228` reads both top-level keys and composes them into one `AgentLLMConfig` Pydantic object internally.

**Conflict for P1.4**: the new P1.4 Agent yaml has many top-level keys (id, role, persona, dissent_dimensions, forbidden_behaviors, speaking_triggers, cooldown_seconds, llm_config, autonomy_thresholds). The P1.4-5 agent loader needs to either:

- **(α) Replicate `load_agent_llm_config`'s sibling-key composition pattern**: read both `llm_config:` and `autonomy_thresholds:` from the yaml; pass them as separate kwargs to `AgentLLMConfig`; then wrap in the P1.4 `Agent` Pydantic model. This keeps yaml shape unchanged; P1.4 just adds more siblings (id, role, persona, etc.).
- **(β) Reuse `load_agent_llm_config` directly**: have P1.4-5 `load_agents` call the existing `load_agent_llm_config(path, models)` to get the `AgentLLMConfig`, then read the additional P1.4 fields (id, role, persona, etc.) from the same yaml and assemble the `Agent` model. Cleanest; preserves DRY.

**Recommended resolution: (β)** — reuse, don't replicate. Adds `from orchestrator.llm.config_loader import load_agent_llm_config` to P1.4-5 (within-module import; no constitutional violation since `agents → llm` is on the allowed direction).

**Plan revision required**: P1.4-4 schema docstring should note that `AgentLLMConfig` includes `autonomy_thresholds`; P1.4-5 acceptance should specify the reuse pattern. **NOT a re-do of the schema**, just a clarification. Junior should be able to make this clear in P1.4-5 commit body without senior re-revision.

### 🟢 Drift observation D2 — `output_schema` in handoff §4.4 deferred to P1.5+

**Where**: handoff §4.4 lists `output_schema: JSONSchema`. P1.4-4 plan dropped it explicitly: `# output_schema deferred to P1.5+ (no current LLM-side validator)`.

**Consistency check**: AgentLLMConfig also doesn't have `output_schema`. So the deferral is consistent across both layers. **No action**; documenting for completeness.

### 🟢 Drift observation D3 — `model_overrides: dict` in handoff §4.4 not in AgentLLMConfig

**Where**: handoff §4.4 lists `model_overrides: dict` under `llm_config`. AgentLLMConfig has no such field.

**Consistency check**: P1.1 LLM layer landed without `model_overrides`. Whether this is "P1.5+ scope" or "design dropped" is a P1.4 retro item, not a P1.4 blocker. **No action for P1.4**.

---

## 3. Draft yamls for P1.4-9 reference

The following draft yamls exercise the full P1.4 Agent schema (id, role, persona, dissent_dimensions, forbidden_behaviors, speaking_triggers + 3 trigger types, cooldown_seconds, llm_config, autonomy_thresholds). Junior reads these during P1.4-9; lands actual files at `config/agents/skeptic.yaml` + `config/agents/prober.yaml` per P1.4-9 acceptance.

### Draft `config/agents/skeptic.yaml`

```yaml
# Skeptic agent — challenges, finds holes, provides dissent.
#
# Defaults to Opus 4.7 because dissent quality is the most direct
# product value of this project. Falls back through Sonnet 4.6 to
# DeepSeek pro on Anthropic outage / rate limit.
#
# `effort_level` is NOT set here — it comes from the model profile
# (xhigh for Opus 4.7). Per ADR-002, effort lives on the profile.

id: skeptic
role: skeptic
persona: |
  Challenge surface-level assumptions; surface alternative interpretations;
  flag implicit confidence not earned by evidence. Direct and concise; do
  not soften dissent to avoid friction.
dissent_dimensions:
  # PLACEHOLDER content — P1.5+ content task tunes these against real runs.
  - assumption_audit
  - evidence_quality
  - alternative_hypotheses
forbidden_behaviors:
  # PLACEHOLDER — P1.5+ content task tunes.
  - agreeing_to_avoid_conflict
  - watering_down_dissent
cross_domain_borrowing: []
speaking_triggers:
  # All three trigger types — one of each per P1.4 design.
  - type: regex
    pattern: "(claim|assert|state|believe)"  # speak when user makes a claim
  - type: event_type
    event_type: hypothesis                     # speak when hypothesis lands
  - type: state_change
    target_state: research                     # speak when room enters research
cooldown_seconds: 60

llm_config:
  default_model: claude_code_opus_47
  fallback_chain:
    - claude_code_sonnet_46
    - deepseek_v4_pro
  temperature: 0.3
  required_capabilities: []

# PLACEHOLDER thresholds (not tuned; P1.5+ usage-based tuning).
# See ADR-005 Decision 3.
autonomy_thresholds:
  threshold_auto: 8
  threshold_confirm: 5
  user_intent_modifier: 2
```

### Draft `config/agents/prober.yaml`

```yaml
# Prober agent — explores, asks, surfaces assumptions.
#
# Default room participant. Lower-tier model (Sonnet); regex trigger
# on user input (responds to user's questions/statements).

id: prober
role: prober
persona: |
  Surface assumptions by asking precise probing questions. Decompose
  vague claims into testable sub-questions. Do not propose solutions;
  expose the question structure.
dissent_dimensions: []
forbidden_behaviors:
  - jumping_to_solution_before_clarifying
cross_domain_borrowing: []
speaking_triggers:
  - type: regex
    pattern: ".+"  # speak on any user input (default room behavior)
cooldown_seconds: 30

llm_config:
  default_model: claude_code_sonnet_46
  fallback_chain:
    - deepseek_v4_flash
  temperature: 0.5
  required_capabilities: []

# PLACEHOLDER thresholds (not tuned; P1.5+ usage-based tuning).
# See ADR-005 Decision 3.
autonomy_thresholds:
  threshold_auto: 8
  threshold_confirm: 5
  user_intent_modifier: 2
```

### What junior should verify during P1.4-9

- `load_agents(directory, *, models)` reads each yaml; calls `load_agent_llm_config` from `orchestrator.llm.config_loader` to assemble the `AgentLLMConfig` (per D1 resolution β); composes the full `Agent` Pydantic instance.
- `validate_consistency(providers, models, agent_configs)` runs post-load for the `required_capabilities: [tools]` check (P1.4 skeptic+prober have empty `required_capabilities` so this is N/A for them; will become live when operator agent lands in P1.5+).
- Filename-stem-equals-id rule (per ADR-009 D8 precedent extended to agents): `config/agents/skeptic.yaml` MUST declare `id: skeptic`. Mismatch raises `AgentLoadError(field="id")`.
- All three trigger types (regex, event_type, state_change) discriminated-union-parse correctly.
- RegexTrigger.pattern compiles at load time; cached in the separate registry (per ADR-010 D6 revised).

---

## 4. Summary of pre-impl spec deliverables

| Audit item | Pre-emptive action | Outcome |
|---|---|---|
| #4 — required_capabilities startup validation | Spec-check `LLMRouter` / `config_loader.py` for existing validation | **Resolved by discovery**: `validate_consistency` exists; P1.4-5 reuses it (no scope expansion to P1.1) |
| #5 — config/agents/ empty | Read existing `.example` files; write full P1.4-shape draft yamls; identify schema-content drift | **Drift D1 surfaced** (autonomy_thresholds composition); 2 draft yamls provided for P1.4-9 reference; recommended P1.4-5 reuse pattern (β) |

**Net effect on P1.4 impl scope**: zero new task added; one P1.4-5 acceptance clarification (reuse `load_agent_llm_config`); zero P1.1 patch needed. Drift D1 resolution (β) is a single import + delegation in the P1.4-5 body, NOT a schema revision.

**Junior session at P1.4 dispatch reads**: senior plan + ADRs + this pre-impl-spec + brief. The pre-impl-spec functions as a fourth read input alongside the standard three.

---

## 5. Forward implications

- **P1.5+ operator agent**: when it lands, `required_capabilities: [tools]` will populate; `validate_consistency` will exercise the canonical ADR-003 misconfiguration check (operator pointed at claude_code_cli → fail-fast at startup). This is the validation's load-bearing real use case; P1.4 skeptic+prober are setup, not exercise.
- **handoff §4.4 drift items D2 + D3**: `output_schema` (deferred P1.5+) and `model_overrides` (not in AgentLLMConfig) deserve a retro candidate when P1.5 brief is authored. RC-14 candidate territory.
- **Filename-stem-equals-id extension to yaml**: ADR-009 D8 was authored against `.md` skill files; P1.4-5 extends to `.yaml` agents. Junior should reference ADR-009 D8 explicitly in P1.4-5 acceptance criterion + add a test (file `config/agents/foo.yaml` with `id: bar` raises).
