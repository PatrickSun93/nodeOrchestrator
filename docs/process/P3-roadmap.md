# P3 roadmap — 完整产品 (scope-decision surface for the architect)

**Status:** Proposed by architect-partner — 2026-06-02. **This is the P3 scope-decision artifact** (analogous to the P2 "long close" decision, handoff §7). It **surfaces** a dependency-ordered slice breakdown + parallelism + a recommended start + scope-ambition options + per-direction priority/risk/constitutional touchpoints. **The architect ratifies scope, priority, and starting slice — this doc does not decide them.**

---

## 1. Framing

P2 is fully closed (P2.1–2.7: cross-room memory + the platform-evolution long close). **P3 = 完整产品** (handoff §7): *"加更多 agent / 模板 / skill,Plugin 系统,MCP 集成,GUI 完整."* It is a large epic, not yet sliced.

Per handoff §3.3, three of the four directions form a **layered stack**:
- **Skills** — capability units (the loader + decision exist: `skills/{loader,decision,schema}.py`; `config/skills/{engineering,general}`).
- **MCP** — external-world connections (GitHub, Postgres, …), *"as a plugin, not core."*
- **Plugins** — the **distribution unit**, packaging *skills + tools + MCP config + roles*.

Plus the fourth, cross-cutting direction: **GUI** (React + TypeScript, handoff §1048/§1101).

**The scope question P3 poses (the architect's to ratify):** 完整产品 spans agent/skill *content* (incremental, low-risk) **and** three from-scratch infrastructures (Plugin system, MCP integration, GUI) — each a multi-slice build with security/constitutional edges. That is far larger than P2's scope. So §6's **ambition options (tight / full / phased)** are the lead decision.

## 2. The P1–P2 foundation P3 extends (verified `origin/main`)

| Built | Package | P3 relevance |
|---|---|---|
| Agent runtime | `agents/` (dispatch, selection, speaking, loader, schema) | (A) more agents plug in via the existing loader |
| Autonomy gate | `autonomy/` (risk scoring, tiers) | **(C) MCP + (B) plugin tools route through this code gate** |
| Event store + rooms | `core/`, `rooms/` (state_machine — P2.7 scaffold tables, runtime, templates) | (A) the 4 scaffold rooms now transition but have **empty agent rosters** (P2.7-S1 deferred); (D) GUI reads the event stream |
| LLM layer | `llm/` (providers, router, override [P2.7], purposes) | (C)/(B) tool-result interpretation = content-gen; **routing stays code** |
| Skills | `skills/` (loader, decision, schema) + `config/skills/` | (A)/(B) plugins package skills |
| Memory + consumers | `memory/`, `reentry/`, `producers/`, `connectors/` | mature; P3 doesn't re-open |
| Boot | `bootstrap.py` (P2.7) | **(D) GUI/external clients need an API/server layer — there is no `main.py`/API today** |
| Dev harness | `workflow/` | unchanged |

**Two gaps that shape P3:** (a) the **4 scaffold rooms have no agents** (`rooms/templates.py` rosters `[]` — the P2.7-S1 deferred content); (b) there is **no API/server boundary** (only `bootstrap.py`) — the GUI's hard prerequisite. Neither plugins/, mcp/, nor any frontend exists.

## 3. The four directions — scope · value · risk · constitutional touchpoints

| Dir | Scope | Value | Build risk | Constitutional / security touchpoint |
|---|---|---|---|---|
| **(A) agent / template / skill expansion** | finish the 4 scaffold rooms' agent rosters (P2.7-deferred) + add more agents/skills/templates | **High, incremental** — makes the multi-room product usable | **Low** — loaders exist; mostly data + established-pattern code | **Low** — reuses code-decides / LLM-generates; new agent roles keep `should_agent_speak`=code, content=LLM |
| **(B) Plugin system** | distribution unit: manifest + loader + install/discovery, packaging skills+tools+MCP+roles | **High** — extensibility / distribution | **High** — new infra **+ trust/security** (a plugin is third-party code/config) | **High** — a plugin must **not** bring a routing/LLM-judgment decision (routing=code); plugin-provided tools route through the **code autonomy gate**; **trust boundary** (like P2.7-S3 alt-backend) |
| **(C) MCP integration** | MCP client/transport + tool-adapter + autonomy-gating for MCP tools | **High** — real external tools (GitHub, Postgres) | **Med-High** — new transport + external I/O | **High** — MCP tool-calls go through the **code-driven autonomy gate** (NOT MCP-server-decided autonomy — Principle 5 operation-gating=code); MCP servers are **external (trust boundary)**; tool-result interpretation = content-gen (`TOOL_OUTPUT_INTERPRET` exists) |
| **(D) GUI** | React+TS frontend (+ the API boundary it needs) | **High** — usable by non-CLI users; demo-able | **Med-High** — whole new stack + the API layer | **Low-but-real** — GUI is a **view; backend-authoritative** (handoff §747/§898 "state machine → 不暴露 / backend authoritative"); it displays + sends user intent, never decides state |

**Constitutional watch-list (the directions that touch the spine):** **(B) + (C)** are the heavy ones — they bring external code/tools/servers and touch the **autonomy/routing boundary** (operation-gating = code; routing = code; no LLM judgment) **and the trust boundary** (third-party plugins/MCP-servers — the P2.7-S3 security pattern recurs, magnified). **(A)** is low-risk content. **(D)** is low-constitutional but must respect backend-authoritative.

## 4. Recommended dependency-ordered slice breakdown (architect-partner lean — phased)

Marked as a **lean**; §6's ambition choice reshapes it. Dependency arrows are hard deps.

```
WAVE 1 — usable, visible product
  P3.1  agent/template/skill expansion   (finish scaffold rooms + add content)   [foundation exists]
  P3.2  API/server boundary              (HTTP/WS over event store + rooms + bootstrap)   [GUI prereq]
  P3.3  GUI MVP                          (read-mostly room view + send user intent)   ← depends on P3.2
WAVE 2 — extensibility
  P3.4  MCP integration                  (client + tool-adapter + autonomy-gating)   [tool layer exists]
  P3.5  Plugin system                    (manifest + loader, packages skills+tools+MCP+roles)   ← depends on P3.1 (role/skill shapes) + P3.4 (MCP config)
WAVE 3 — completeness / polish
  P3.6  GUI completeness                 (full interactivity, remaining views)   ← extends P3.3
  P3.7  content depth                    (more agents/templates/skills/connectors to 完整 breadth)   ← extends P3.1/P3.4
```

**Dependency order:** P3.1 ∥ P3.2 (disjoint: config-content vs a new `api/` package) → P3.3 (after P3.2's API contract). **P3.4 (MCP) is independent of Wave 1** (tool/autonomy layer) and can run alongside it. **P3.5 (Plugin) is the integration point** — it packages roles/skills (P3.1) + MCP config (P3.4), so it comes **after both**. Waves 3 extend earlier slices.

*(Each slice still runs the full ADR-008 lifecycle: brief → plan → ADR → impl → R0-A/R0-B → plan-vs-impl → merge. P3.5/P3.4 will likely want dual-lens R0-B for the trust/autonomy boundaries — like P2.7-S3.)*

## 5. Parallelism assessment

| Pair | Parallel-safe? | Why |
|---|---|---|
| **P3.1 ∥ P3.2** | **✅ yes** | content (`config/`, `agents/`, `rooms/templates`) vs a new `api/` package — disjoint footprints |
| **P3.4 (MCP) ∥ Wave 1** | **✅ mostly** | MCP touches the tool/autonomy layer (new `mcp/` package + `tools.yaml`/`tool_dispatch` edges); independent of content/API/GUI |
| **GUI frontend ∥ backend** | **✅ the biggest opportunity** | once the **P3.2 API contract is pinned**, the React/TS frontend (P3.3/P3.6) is a **separate codebase + skillset** — a frontend track runs concurrently with all backend slices. This is where subagent/worktree parallelism pays most (a distinct stack). |
| **P3.5 (Plugin)** | **❌ integration point** | depends on P3.1 (roles/skills) + P3.4 (MCP) — sequence after both; it's the convergence, not a parallel leaf |
| **P3.3 → P3.2** | sequential | GUI needs the API contract first |

**Net:** the cleanest parallelism is a **frontend track (P3.2-contract → P3.3 → P3.6) ∥ a backend track (P3.1 → P3.4 → P3.5)** — two largely-independent streams meeting at the API contract + the plugin integration. Within the backend track, P3.1 ∥ P3.4 are independent; P3.5 is the join.

## 6. ⭐ Scope-ambition options (the lead decision — architect ratifies)

P2 was ratified as the **long close** (full, nothing deferred to P3). P3's "完整产品" is far larger (three from-scratch infrastructures). Three ambitions:

| Option | What | Trade-off |
|---|---|---|
| **Tight** | Wave 1 (usable rooms + API + GUI MVP) **+ a minimal slice of each Wave-2 direction** (one MCP connector, one plugin, read-only GUI) — defer "complete" depth to P4 | Fastest to a **usable, extensible-in-principle** end-to-end product; the "MVP of each" proves the architecture; depth deferred. **Risk:** "完整产品" not literally met (P4 finishes breadth). |
| **Full** | All four directions to completion in P3 (many agents/templates/skills, full plugin system, multiple MCP connectors, complete GUI) — the literal "完整产品" | Matches handoff §7's wording; **but** very large (3 infra builds + a frontend), long, and front-loads the heavy constitutional/security surfaces (B/C) before the product is even usable. |
| **Phased** | P3 = the §4 waves run as **ordered waves**, each a closeable milestone: Wave 1 (usable) → Wave 2 (extensible) → Wave 3 (complete). Re-evaluate scope between waves. | **Lean.** De-risks by sequencing value: a usable product (Wave 1) before the heavy extensibility infra (Wave 2) before completeness (Wave 3). Each wave is a natural "ratify the next" checkpoint — mirrors how P1/P2 themselves were waves. **The architect re-decides ambition at each wave boundary.** |

**Architect-partner lean: phased** — P3 is too large for one scope decision; phasing lets each wave be a usable/closeable milestone and a re-ratify point, exactly as P1→P2 worked. But this is the architect's call (tight if a fast usable+extensible MVP is the goal; full if literal completeness is required now).

## 7. ⭐ Recommended first slice + why (architect ratifies the start)

**Lean: start with P3.1 — agent/template/skill expansion (finish the scaffold rooms' rosters + add content).**

Why:
- **De-risks usability + finishes P2.7's loose end.** P2.7-S1 built the 4 scaffold rooms' *state machines* but left their *agent rosters* empty (`templates.py` `[]`). Until they're populated, `bug_fix`/`code_review`/`idea_validation`/`free_chat` rooms transition through states with **no agents doing anything**. P3.1 makes the multi-room product actually work end-to-end — the natural continuation of P2.7.
- **Lowest risk, fastest value.** The loaders (`agents/loader`, `skills/loader`, `rooms/templates`) exist; it's mostly data + established-pattern code. **No new infra, no constitutional/security surface** — a clean win to open P3.
- **Foundation for the rest.** The agent/role/skill shapes settle here, which the **Plugin system (P3.5) packages** — so doing it first de-risks the plugin manifest design.

**Alternatives I surface (the architect's call on the start):**
- **API + GUI-MVP (P3.2→P3.3) first** — if the priority is "make it **visible / demo-able** to non-CLI users" soonest (a product-facing milestone). De-risks the "is the product approachable" question + unblocks the frontend track early.
- **MCP (P3.4) first** — if "**real external tools**" is judged the highest-value differentiator, and you want the autonomy-gating-of-external-tools constitutional surface settled early.
- **(Not recommended first: Plugin P3.5)** — it's the integration point (depends on P3.1 + P3.4); starting there inverts the dependency order.

## 8. What the architect needs to ratify (the three P3-scope decisions)

1. **Ambition** — tight / full / **phased (lean)** (§6). Shapes the whole breakdown.
2. **Priority** — the relative order of the four directions (§3/§4). Lean: A (content) → API/GUI (D-surface) + MCP (C) in parallel → Plugin (B) → completeness. But e.g. "GUI-first" or "MCP-first" are legitimate re-prioritizations.
3. **Starting slice** — **P3.1 (lean)**, or one of the §7 alternatives.

Once ratified, the chosen first slice gets a normal architect brief (architect-partner) → senior plan → the ADR-008 lifecycle. The heavy slices (Plugin P3.5, MCP P3.4) should carry **dual-lens R0-B** (the trust/autonomy boundaries — the P2.7-S3 security pattern, magnified) and likely new ADRs (a plugin-manifest ADR, an MCP-transport/autonomy-gating ADR, an API-contract ADR).

## 9. Constitutional / security watch-list for P3 (carry into every slice's brief)

- **Routing = code** (Principle 5; `llm-layer.md`; CLAUDE.md) — no plugin/MCP/GUI brings an LLM routing/judgment decision; model-selection stays the code router (+ the P2.7 Layer-4 override).
- **Operation-gating = code** — MCP/plugin **tool-calls** route through the existing **code autonomy gate** (risk-scored), never an external-server-decided autonomy. The autonomy gate is the chokepoint.
- **Trust boundary** (the P2.7-S3 pattern, recurring) — plugins (third-party code/config) and MCP servers (external) are **trust boundaries**: opt-in, allowlist/manifest-validated, credential-safe (`api_key_env` indirection), fail-closed. Each needs its security posture ratified (like S3's allowlist).
- **Backend-authoritative** — the GUI is a **view**: it displays the event stream + sends user intent; it never decides state/routing/autonomy (handoff §747/§898).
- **content-gen vs judgment** — tool-result interpretation, agent responses = content-gen (existing `LLMPurpose`s); no new **routing/judgment** purpose. New content-gen purposes (if any) are ADR-gated.
- **Inscribe-before-producer / wait-for-a-real-consumer** — the plugin manifest + MCP tool contract + the API contract are expensive-to-change; pin them before broad producers/consumers bind (the P1.6/P2 discipline).

## 10. Cross-references
- `handoff.md` §3.3 (Skills/MCP/Plugins three layers), §7 P3 row (完整产品) + the P2 long-close precedent, §5.2 (room templates), §1015/§1048/§1101 (the `ui/` + React+TS frontend plan), §747/§898 (backend-authoritative).
- `src/orchestrator/` (the P1–P2 foundation P3 extends); `rooms/templates.py` (the empty scaffold rosters — P3.1's first target); `skills/` + `config/skills/` (the skill layer); `autonomy/` (the gate MCP/plugin tools route through); `bootstrap.py` (the boot the API layer wraps).
- `docs/decisions/ADR-012` (room state machine — P2.7 scaffold tables), `ADR-003` (Claude Code tools posture — relevant to MCP/plugin tools), `ADR-002`/`ADR-023` (LLM layer — routing=code, the Layer-4 override).
- `docs/process/dual-lens-r0b.md` (the heavy P3 slices — B/C — warrant dual-lens), `docs/process/distance-test.md`.

## Authorship note
Architect-partner-authored, verified vs `origin/main` (P2 closed; the 12 product packages; the empty scaffold rosters; the absent api/plugins/mcp/frontend) + handoff §3.3/§7. This is a **scope-surface**: the slice breakdown, the phased ambition, and the P3.1 start are **leans**, not decisions — the architect ratifies ambition + priority + start (§8). No slice is briefed until the architect ratifies.
