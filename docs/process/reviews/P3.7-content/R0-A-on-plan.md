---
task_id: P3.7-content
kind: R0-A-on-plan
cycle: 1
reviewer: architect-partner
lens: single-lens (no dual-lens — brief §c; zero of dual-lens-r0b.md's 4 criteria hold)
based_on_plan: docs/process/senior-plans/P3.7-content.md
based_on_brief: docs/process/architect-briefs/P3.7-content.md
verified_against: origin/main @ ab5af6b (+ plan branch claude/P3.7-content-plan @ a2b8757)
verdict: clean
note: >-
  Plan DESIGN is clean — a model pattern-reuse breadth plan; all 4 architect-set review foci
  pass; the ADR-024/009/027/029 reuse is verified correct against the live schemas; every unit
  ships a genuinely discriminating test. ONE pre-dispatch procedural action (NOT a plan-design
  defect, surfaced for the architect who owns the P3.7-split state): the `adr: none` frontmatter
  sets plan_has_adr=True (cli.py:359 keys on key-PRESENCE, not value), so auto-advance routes to
  awaiting_architect_accept (awaiting a non-existent ADR) instead of awaiting_junior_impl — every
  prior no-ADR plan (P1.3, W-001..004) OMITS the adr key. Trivial fix. Plus ONE advisory: new
  agents render as the generic "助手" in the GUI until a frontend-track AGENT_NAME_MAP update —
  不暴露 is NOT broken (fallback-safe by design); flagged as a cross-track follow-up, not a blocker.
---

# R0-A-on-plan — P3.7-content (single-lens; architect-partner)

## 1. Scope & method
Single-lens R0-A on the senior plan (`a2b8757`), per the architect's manual dispatch (RC-9) and brief §c (no dual-lens — zero `dual-lens-r0b.md` criteria hold; pure pattern-reuse). Reviewed against: the brief, the four reused ADRs (024 role / 009 skill / 027 connector / 029 plugin), and the **live** schemas/loaders (`agents/schema.py`, `skills/schema.py`, `mcp/config.py`, the plugin loader, `ui/src/uiStrings.ts`, `workflow/cli.py`). Focus = the architect's four foci + the brief's constitutional carry-forward.

## 2. Verdict — **clean** (plan design), with 1 pre-dispatch procedural action + 1 advisory
The plan is a **model light-slice plan**: it instantiates all four architect-ratified leans concretely (2 agents / 2 skills / 1 connector / 1 plugin), keeps every unit on a frozen loader, and gives each a discriminating test. **No plan-design rework needed.** Two items are surfaced below — neither is a design defect; the first is a trivial frontmatter/state-routing fix to do **before** junior dispatch, the second a cross-track follow-up.

## 3. The four review foci — all pass

**(1) Purely additive content; reuses frozen loaders; no reshape / no `LLMPurpose` / no gate-executor touch / no trust surface.** ✓
- Every atomic feeds an existing loader (`load_agents` / `load_skills` / `ROOM_TEMPLATES` / `load_mcp_servers_config` / plugin loader); each "Out of scope" explicitly bars loader/schema change + new `LLMPurpose` (§2-1..6). §4 forcing function: *"if any unit appears to need a loader/schema edit → halt + surface."* ✓
- No gate/executor touch: connectors gate via ADR-027 D3 pre-classify-allowlist (§2-5); plugin tools gate via ADR-029 D5/D7 (§2-6). No new trust surface: the connector is local stdio (`server-memory` — no network/subprocess-shell class) and the plugin is local Posture-A; §2-5 Out-of-scope explicitly excludes the ADR-028 D3 deferred classes (network/subprocess/mutation **local-impl** tools) **and** remote transport. ✓

**(2) Discriminating tests per unit (real registration / real gate / frozen-schema — not "renders something").** ✓
- agents (1,2): `should_agent_speak` → `speak=True` in **each** declared room type **and** absent from a non-declared roster (present/missing partition) — the P3.1 facilitator pattern. ✓
- skills (3,4): `stem==id` (ADR-009 D8), validates, **matches** in a declared room **and** `rejection_reason != "matched"` in a non-declared type. ✓
- connector (5): a classified tool → its expected tier (read→AUTO, write→HARD_CONFIRM) **and** an exposed-but-unlisted tool → `UnknownToolError` (discovery≠permission, HR#3). ✓
- plugin (6): loads+merges; host-classified tool → expected tier while a plugin-classify-only tool **caps to rev 0/HARD_CONFIRM** (cannot self-raise); **plus** a fail-closed path (bad-manifest / collision → refused, host unchanged). ✓

**(3) New-agent activation stays code; new plugin/connector still routes through the existing gate/allowlist.** ✓
- §2-1/2: *"activation stays code `should_agent_speak`; responses stay `AGENT_RESPONSE` content-gen."* §2-5: connector tools via the ADR-027 gate path; §2-6: plugin tools via the gate; plugin-claimed reversibility advisory-capped → host-or-0. ✓

**(4) 不暴露 carry-forward not broken.** ✓ — verified, with a cross-track nuance (advisory N-1, §5).
- The plan adds only backend content (agents/skills/connectors/plugins). Skills/plugins/MCP-as-infra are internal (never surfaced, P3.6 D-C). The **only** wire-visible projection a new agent introduces is its event-author id, and `ui/src/uiStrings.ts::authorLabel` resolves an unknown agent to the safe generic `"助手"` (lines 110-112: *"Unknown author — do not surface raw string"*), with `uiStrings.test.ts:128-133` asserting exactly that safe fallback for a future-unknown agent. So a new agent **cannot leak a raw id** — 不暴露 holds by construction. The plan's choice to **not** touch `ui/` is the correct backend-track boundary and is safe. ✓

## 4. ⚠ Pre-dispatch procedural action (NOT a plan-design defect) — frontmatter `adr: none` mis-routes the state machine

**Finding.** The plan frontmatter declares `adr: none` (line 6). The auto-advance reads `plan_has_adr = "adr" in plan_fm` (`workflow/cli.py:359`) — it keys on **key-presence, not value** — so `adr: none` yields `plan_has_adr=True`. `next_state` (`transitions.py:147-152`) then routes `awaiting_senior_plan → awaiting_architect_accept` (the ADR-accept gate), i.e. it will **wait for a non-existent ADR to be Accepted** and never reach `awaiting_junior_impl`.

**Evidence it's a deviation, not the convention.** Every prior no-ADR plan **omits** the `adr` key entirely (P1.2-C3/C4, P1.3, W-001-impl, W-002/002.5/003/004 — all "(NO adr key)"); P3.7-content is the **first** plan to write `adr: none`. The W-002-2b no-ADR fast-path (`plan_has_adr is False → awaiting_junior_impl`) only fires when the key is **absent**.

**Why surfaced, not auto-fixed.** The architect owns the P3.7-split state machine (stated at split time); this R0-A does **not** advance/override. The fix is trivial and is the architect's to route:
- **Fix A (clean, matches precedent):** senior removes the `adr: none` line (move the "reuses ADR-024/009/027/029, no new contract" note into the plan body / a comment) → `plan_has_adr=False` → auto-advance reaches `awaiting_junior_impl` directly. *(Lean — it restores the documented no-ADR path + the established convention.)*
- **Fix B:** architect `override`s `awaiting_architect_accept → awaiting_junior_impl` manually.

This is a **dev-harness / state-routing** matter (frontmatter convention), not a product-design defect — hence verdict stays **clean** on the plan's substance. But it must be handled before junior dispatch, else the state stalls.

## 5. Advisory N-1 (cross-track follow-up; not a blocker) — new agents show as generic "助手" in the GUI

The two new agents (`synthesizer`, `planner`) are **not** in `ui/src/uiStrings.ts::AGENT_NAME_MAP` (6 product agents today). As established in §3(4), this does **not** break 不暴露 (fallback to `"助手"` is safe) and does **not** fail any test (the backend gate suite has no `ui/` coupling — `grep` confirms none; `uiStrings.test.ts:120-126` asserts only a hard-coded `skeptic`, not an enumeration of backend agents). The sole effect: the new agents display as the generic `"助手"` rather than a named label until a **frontend-track** `AGENT_NAME_MAP` addition (P3.6 territory). Correctly **out of P3.7-content's backend scope**; surfaced so the architect can decide whether to bundle the FE name-map update into a frontend cycle. No action required in this slice.

## 6. ADR-reuse correctness (spot-verified against live schemas)
- **ADR-024 (Agent):** `role: str` is a **free-string** (`agents/schema.py:106`), so `synthesizer`/`planner` need **no** new role-type contract (plan §5 correct); `applies_to.room_states` default `["*"]` satisfies `min_length=1` (§2-1 correct). ✓
- **ADR-009 (Skill):** `category: Literal["general","engineering","business"]` (`skills/schema.py:47`) — **`business` already exists and is unused**, so §2-3 fills it with **no** schema change (plan §2-3 assertion verified). `stem==id` (D8) honored. ✓
- **ADR-027 (connector) D3:** the partial pre-classify-allowlist + unlisted→`UnknownToolError` test (§2-5) matches the live gate path; tests gate classification, not live `npx` — correct (no CI dependency on a node runtime). ✓
- **ADR-029 (plugin) D5/D7:** the host-pre-classify vs plugin-classify-only (caps to rev 0) + fail-closed-on-collision tests (§2-6) match the live loader semantics (incl. Amendment 1's two-way `tool_impls` collision). ✓

## 7. Notes the plan got right (worth recording)
- §4 mandates the **full** gate suite incl. `tests/` (not `src/`-only) — directly pre-empts the recurring "junior ran src/-only gates" failure class. ✓
- §3 identifies the only shared-file coupling (`templates.py` for tasks 1&2, `config/tools.yaml` for task 6) and chooses serial to avoid merge contention. ✓
- §5 surfaces the quantity dial as the architect's (not self-decided) + offers to add atomics — correct role discipline.

## Conclusion
**Verdict: clean** — the plan's design is sound and ready for junior implementation with **no design rework**. Handle the one pre-dispatch procedural action (§4, `adr: none` → state mis-route; trivial Fix A) before dispatch; the GUI-name advisory (§5) is a separate frontend-track follow-up. No product-correctness, constitutional, or trust-surface issue found.
