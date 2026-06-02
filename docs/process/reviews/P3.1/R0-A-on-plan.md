---
task_id: P3.1
round: R0-A-on-plan
verdict: needs_architect
findings_count:
  red: 0
  yellow: 1
  green: 11
verdict_history:
  - verdict: needs_architect
    at_commit: f30a1dd
    findings_count: { red: 0, yellow: 1, green: 11 }
    note: initial R0-A-on-plan (in-family, single-lens — dual-lens skipped as ruled). Exemplary for a light slice; every named check verifies clean — rosters match the ruling, the 2b backward-compat design is VERIFIED safe (scaffold state names are unique vs Research's setup/exploration/divergence/convergence/snapshot_pending/closed), facilitator preserves the code-activation/LLM-content split, ADR-024 RC-23-safe, no new LLMPurpose. One LOW 🟡 (Y1) — the 2b matrix specifies the state_change-trigger layer but the reused agents' EXISTING triggers also fire in scaffold rooms (additive, acknowledged but un-enumerated); the e2e's "exactly the matrix agents per state" must test the NET activation. Not blocking.
---

# P3.1 R0-A on plan (architect-dispatched pre-impl review, in-family, single-lens)

| Field | Value |
|---|---|
| Round | R0-A-on-plan (RC-9; single-lens — `requires_cross_family_review: false`, architect-ruled skip) |
| Artifacts | `senior-plans/P3.1.md` + `ADR-024` (Proposed) + `config/agents/facilitator.yaml` vs `origin/main` substrate + brief P3.1 |
| ADR status | ADR-024 left **Proposed** — informs accept; I did not accept (architect-only). |

## Verdict: needs_architect

**Exemplary plan for a "light" slice — every named check verifies clean, and the senior did genuinely sharp backward-compat work.** The non-obvious part (2b) is right and I verified it: `applies_to.room_states` is a *flat shared list*, so narrowing it would regress Research — the senior instead uses `speaking_triggers` keyed on **scaffold state names**, and I confirmed those names (`reproduced/diagnosed/fix_proposed/reviewing/changes_requested/approved/pitching/validating/decided/active`) are **unique** — none occurs in Research's set (`setup/exploration/divergence/convergence/snapshot_pending/closed`) — so a `state_change → <scaffold_state>` trigger fires **only** in that room (backward-compat-safe). The facilitator preserves the code-activation/LLM-content split (ADR-024 D2), ADR-024 is RC-23-safe, no new `LLMPurpose` (still 9), and the e2e is discriminating-by-design.

**One LOW 🟡 (Y1):** the 2b activation matrix specifies the *new* `state_change`-trigger layer, but the reused agents' **existing** triggers (regex / `hypothesis` / `user_input`) also fire in the scaffold rooms now that those agents are in-roster + `applies_to`-covered. The plan calls them "additive" (acknowledged) but doesn't enumerate the **net** per-room/state activation, and the e2e's "speak=True for *exactly* the matrix agents per state" must reconcile with the existing triggers firing on the same transition events. Low; impl/e2e-precision, not constitutional.

## The five named checks

| # | Check | Verdict | Evidence |
|---|---|---|---|
| 1 | 4 rosters + `applies_to` reconcile reasonable; agents activate in the right states | **clean (G1/G2); Y1 (net activation)** | Rosters (2a) match the ruling, alphabetical. The 2b two-lever design (`declared_agents` + `applies_to.room_types` narrowing keeping `research` + `speaking_triggers` on scaffold-unique states) is **verified backward-compat-safe** (state-name uniqueness). `prober`/`skeptic` were default `["*"]`; narrowed to their serving rooms (keeps `research`). `operator`/`divergence_mapper` already correct; `logger` stays `["*"]`. **Y1: existing triggers also fire in scaffold rooms — see finding.** |
| 2 | facilitator: persona/skill/`applies_to` reasonable; preserves activation=code/response=LLM; no new routing/judgment `LLMPurpose` | **clean (G4)** | `facilitator.yaml` matches ADR-024: non-adversarial host (no `dissent_dimensions`), `applies_to [free_chat]/[setup,active]`, triggers `user_input` + `state_change→active`, cheap `claude_code_haiku_45` / temp 0.7, no new skill. **Split preserved** (ADR-024 D2: activation = `should_agent_speak`+`applies_to` code; response = `AGENT_RESPONSE` content-gen). **No new `LLMPurpose`** (verified 9, unchanged). |
| 3 | ADR-024 RC-23-safe (Proposed; no literal `Status: Accepted` substring) | **clean (G5)** | Only `**Status:** Proposed` (line 3); grep clean — no `status: accepted`. References cite ADRs without quoting an accepted-status substring. |
| 4 | e2e discriminating (per room/state, not just roster non-empty) | **clean-by-design (G6); Y1** | P3.1-2 asserts per-room `load_room` partition + per-state `should_agent_speak` (True for the matrix agents, False for others) + facilitator activation — discriminating, mirrors `test_integration_research_room_state_advance_and_agent_speaks`. **Y1: the "exactly the matrix agents" assertion must test the NET activation (existing + state_change triggers), else it's confounded/incomplete.** |
| 5 | `rooms/templates.py` pure data; Q1–Q5 | **clean (G7/G8)** | Populating `declared_agents` is data; `templates.py` no-I/O/LLM (the `rooms/` no-LLM constitution test covers it). Q1 (no new `LLMPurpose`, split preserved); Q2 N/A (selection traces unchanged); Q3 5-surface; Q4 6-cat at PR; Q5 discriminating. |

## Findings

### Y1 🟡 (low) — the 2b matrix is the state_change layer; the reused agents' existing triggers also fire in scaffold rooms (specify + test the net)

The 2b activation design adds `state_change → <scaffold_state>` triggers to the shared agents — verified backward-compat-safe (state-name uniqueness, above). But once `prober`/`skeptic`/`operator`/`divergence_mapper` are in a scaffold room's roster + `applies_to`-covered, their **existing** triggers (skeptic's regex + `hypothesis`; operator's `user_input` + `hypothesis`; etc.) **also fire there**. The plan notes these are "additive" (so the senior is aware) but the **2b matrix only enumerates the `state_change` activations** — the *net* per-room/state activation (existing + new) isn't specified. Two consequences:
- **e2e precision (check 4):** "speak=True for **exactly** the matrix agents per state" can be **confounded** — e.g. `bug_fix → diagnosed` is driven by a `HYPOTHESIS` event, on which skeptic's *existing* `hypothesis` trigger also fires (alongside its new `state_change→diagnosed`). The discriminating assertion must test the **net** activation (existing + state_change), or it's incomplete / will mis-fire.
- **Possible over-activation:** a reused agent's Research-era triggers may fire where unintended in a scaffold room (e.g. does `operator`/`skeptic` firing on its existing triggers make sense in `code_review`, which has no `HYPOTHESIS` arc?). Likely fine (skeptic-on-hypothesis in bug_fix is sensible), but it's **unanalyzed**.

**Lean (surface, not decide):** **α** — the senior specifies the **net** per-(room, state) activation (existing triggers + the 2b state_change triggers) and the e2e asserts that net (RC-25 over the full picture), confirming no unintended over-activation from inherited triggers. **Or note-for-impl** — fold it into the impl + the impl-stage R0-A (verify the e2e tests the net). Low; the design is sound, this is precision/completeness. Architect: α-fold or note-for-impl.

## What holds — verified clean (G1–G11)

- **G1** rosters (2a) match the architect ruling, alphabetical; Research unchanged.
- **G2** the 2b backward-compat design **verified safe** — scaffold state names unique vs Research's `{setup, exploration, divergence, convergence, snapshot_pending, closed}`; `state_change` triggers on shared agents fire only in scaffold rooms. (The senior's flat-shared-list insight is a genuinely sharp catch.)
- **G3** `logger → closed` deferral sound — `closed` IS shared with Research, so a `→closed` trigger isn't Research-safe → correctly deferred to P3.7 (verified).
- **G4** facilitator preserves the constitutional split (ADR-024 D2); config matches; no new `LLMPurpose`.
- **G5** ADR-024 RC-23-safe (Proposed only).
- **G6** e2e discriminating-by-design (modulo the Y1 net-activation point).
- **G7** `templates.py` pure data (constitution-test-covered).
- **G8** Q1–Q5 addressed.
- **G9** backward-compat **test sweep correctly identified** (P3.1-1: the old scaffold-empty / prober-skeptic-`["*"]` tests must be updated to the new rosters; Research suites verified-green-not-assumed) — the senior caught that populating rosters breaks the old empty-state tests. *(Watch-item for the impl-stage R0-A: the updated tests must stay discriminating — assert the new rosters, not be weakened to "non-empty".)*
- **G10** `prober`/`skeptic` `room_types` narrowing keeps `research` (backward-compat) + matches the rosters (verified they were default `["*"]`).
- **G11** prober-excluded-from-free_chat fork recorded (ADR-024 alternatives) + reasonable (casual ≠ interrogation).

**Scope-clarity note (not a finding):** the facilitator's persona/`forbidden_behaviors` are MVP `TODO`-stubbed (matching the existing five agents' stub style — ADR-024 Consequences). So P3.1 makes all five rooms **run end-to-end mechanically** (agents activate + dispatch + respond), but the **conversation *depth*** (fleshed personas for all six agents) is P3.7 content. Consistent with the ratified scope (P3.1 = rosters/activation; P3.7 = content depth) — flagged so the "能跑端到端" expectation is calibrated (mechanism works now; rich personas later).

## What I did NOT do

- Did not accept ADR-024 (architect-only).
- Did not decide Y1 — surfaced with a lean (α specify+test the net activation / note-for-impl); low, non-constitutional.
- Single-lens (dual-lens skipped as ruled); left the tree clean.
