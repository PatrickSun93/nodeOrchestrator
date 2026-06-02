# ADR-024: The `facilitator` Agent Role (free_chat conversational host)

**Status:** Accepted — 2026-06-02 (architect-accepted; P3.1 R0-A-on-plan clean after Y1 → α-fold (net activation table); facilitator preserves code-activation/LLM-content split, no new routing LLMPurpose)

**Scope:** P3.1 — adds a single new agent role, **`facilitator`** (`config/agents/facilitator.yaml`), to give the `free_chat` scaffold room a working roster. Governs the role's purpose, its `applies_to` scope, and its preservation of the code-activation / LLM-content split. Does NOT govern: the per-room rosters of the other three scaffold rooms (`bug_fix` / `code_review` / `idea_validation` — reuse-only, no ADR; covered in the P3.1 plan), new skills (deferred to P3.7), or any change to the selection/dispatch machinery (`should_agent_speak`, `applies_to` filtering — unchanged code).

## Context

P2.7-S1 gave the four scaffold RoomTypes real state machines but left their rosters empty (`rooms/templates.py` `declared_agents=[]`). P3.1 populates them. Three of the four are well served by the existing five agents (architect-ruled rosters; P3.1 plan §2): `bug_fix` = prober + skeptic + logger + operator; `code_review` = skeptic + logger + operator; `idea_validation` = prober + skeptic + divergence_mapper + logger + operator.

`free_chat` is the exception. Among the existing five, only `logger` (`applies_to.room_types: ["*"]`) is a natural fit; the others are **dissent/analysis** roles — `skeptic` (challenge assumptions), `prober` (surface assumptions / interrogate), `divergence_mapper` (map disagreement), `operator` (run tools). None hosts a *casual, open-ended* conversation; dropping a skeptic or prober into `free_chat` would turn light chat into an audit or an interrogation (the opposite of the room's purpose). A logger-only `free_chat` would record but never converse — a room with no one to talk to.

Per `docs/contributing.md` ("Adding a new agent role" → requires an ADR), the architect ruled P3.1 adds **one** new role for `free_chat`: a light **facilitator**. This ADR inscribes it.

## Decisions

### D1. A new `facilitator` role — a conversational host, not a critic

`facilitator` keeps a casual conversation flowing: it greets, asks warm open follow-ups, lightly reflects back, and surfaces threads — without leading toward an agenda or interrogating. It is **collaborative, not adversarial** — deliberately *not* a dissent role (no `dissent_dimensions`), distinguishing it from skeptic/prober/divergence_mapper. Its `forbidden_behaviors` guard the failure modes of a host (dominating, steering to a hidden agenda, interrogating, fabricating to keep talking).

This is the **sixth** agent role; it follows the existing `Agent` schema (`agents/schema.py`) exactly — no schema change. It is the first role authored for a scaffold room specifically (the original five were Research-era).

### D2. Code-activation / LLM-content split preserved (the constitutional invariant)

The facilitator changes **nothing** about the constitutional spine:
- **Activation is code** — *whether/when* the facilitator speaks is decided by `should_agent_speak` over its `speaking_triggers` + the `applies_to` filters (all code, no LLM), exactly as for the other five agents.
- **Response is LLM content-gen** — *what* it says is generated through the existing `dispatch_turn` path using `LLMPurpose.AGENT_RESPONSE` (`dispatch.py:109`). **No new `LLMPurpose`** is added; the taxonomy stays content-gen-only.

There is no facilitator-specific code, no `rooms/`/`memory/` change, no new decision surface. It is pure config consumed by the existing machinery.

### D3. `applies_to` + triggers — scoped to free_chat, active in setup + active

- `applies_to.room_types: ["free_chat"]` — the facilitator is a casual-room host; it does **not** join the analytical rooms (a single concrete value, not `["*"]`, keeps it scoped and keeps the other rooms' rosters exactly as the architect ruled).
- `applies_to.room_states: ["setup", "active"]` — it greets/kicks off in `setup` and converses in `active`, and falls silent at `closed` (the conversation has ended). This is a clean per-state gate, available because the facilitator is **unshared** (free_chat-only) — narrowing a *shared* agent's flat `room_states` would couple rooms (see the plan §2 activation note). free_chat's lifecycle is `setup → active → closed`.
- `speaking_triggers`: `event_type: user_input` (respond when the user speaks) + `state_change target_state: active` (engage when the room becomes active). `cooldown_seconds: 30` so it converses without spamming.

### D4. Cheap model, warm temperature; no new skill

`llm_config`: `default_model: claude_code_haiku_45` (casual chat does not need a frontier reasoner — same cheap tier as logger), `fallback_chain: [deepseek_v4_flash]`, `temperature: 0.7` (conversational warmth vs the analytical agents' 0.2–0.4), `required_capabilities: []` (no tools). The facilitator needs **no new skill** to function (it is pure conversation) — consistent with the architect's "defer new skills to P3.7."

## Considered alternatives

- **Reuse `prober` for free_chat** — Rejected: prober *surfaces assumptions / asks clarifying questions to interrogate a problem space*; in a casual room that reads as an interrogation, not hosting. (The P3.1 plan §5 records the senior fork: free_chat = facilitator + logger, **prober excluded**.)
- **logger-only free_chat (no new role, no ADR)** — Rejected: logger records but never converses; free_chat would have no conversational participant. The architect ruled a new role over a deliberately-empty room.
- **A general "conversationalist" applying to all rooms (`["*"]`)** — Rejected for P3.1: the analytical rooms already have full rosters; a universal chatty agent would dilute them. Scope to free_chat now; broaden later only if a need surfaces (forward hook).
- **Make facilitator a dissent role with `dissent_dimensions`** — Rejected: the whole point is a *non-adversarial* host; dissent dimensions would make it argue, duplicating skeptic.

## Consequences

**Easier:** free_chat runs end-to-end (a host + a logger); the scaffold-room roster pattern now has a template for "a room needs a bespoke light role" (P3.7 can add more); the code-activation/LLM-content split is demonstrated on a sixth, non-analytical role.

**Harder:** one more agent config to maintain; the facilitator's persona/forbidden_behaviors are MVP `TODO:`-stubbed (matching the existing five agents' stub style) and will want fleshing out as content (P3.7).

**Neutral:** `applies_to.room_types: ["free_chat"]` means a future RoomType wanting a host must either add the facilitator's type or define its own role (consistent with the per-RoomType-roster model). The cheap-model/warm-temperature choices are tunable yaml (ADR-002 operational-knob granularity).

## Reversibility

| Decision | 6-month reversal cost |
|---|---|
| D1 new `facilitator` role | **Low** — it is one additive config file consumed by existing machinery; removing it reverts free_chat to logger-only (a roster edit). |
| D2 code-activation / LLM-content split | **Trivial / do-not-reverse** — constitutional; the facilitator simply honors it. |
| D3 free_chat scope + setup/active gate | **Low** — `applies_to` is yaml; broadening to more rooms or states is a config edit. |
| D4 model/temperature/no-skill | **Trivial** — operational yaml knobs. |

## References

- `docs/process/architect-briefs/P3.1.md` (the roster decision + the free_chat new-role question).
- `docs/process/senior-plans/P3.1.md` (this ADR's plan; §2 rosters + the activation design, §5 senior forks incl. prober-excluded).
- `docs/contributing.md` ("Adding a new agent role" → ADR — the gate this ADR satisfies).
- `src/orchestrator/agents/schema.py` (`Agent`, `AgentAppliesTo`, `SpeakingTrigger` — the unchanged schema the facilitator instantiates).
- `src/orchestrator/agents/dispatch.py:109` (`LLMPurpose.AGENT_RESPONSE` — the existing content-gen path the facilitator reuses; no new purpose).
- `src/orchestrator/agents/speaking.py` (`should_agent_speak` — the code activation the facilitator's triggers feed).
- ADR-010 (should_agent_speak contract) + ADR-011 (multi-agent dispatch) + ADR-012 (room state machine / `applies_to` filtering) — the machinery the facilitator plugs into unchanged.
- `config/agents/facilitator.yaml` (the role's instantiation).
