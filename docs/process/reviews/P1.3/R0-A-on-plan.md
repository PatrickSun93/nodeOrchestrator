---
task_id: P1.3
round: R0-A-on-plan
verdict: needs_architect
findings_count:
  red: 0
  yellow: 2
  green: 3
---

# P1.3 R0-A on plan (architect-dispatched pre-impl review)

| Field | Value |
|---|---|
| Round | R0-A-on-plan (architect-dispatched per RC-9; second instance after W-001-impl) |
| Reviewer | A (architect-partner Claude session) |
| Family | Claude (Opus 4.7) — same as senior |
| Cross-family R0-B | not dispatched (per brief — P1.3 not categorical shape change; W-001 retro §6) |
| Lens | ADR design + plan structure + push-back verification + cross-reference integrity + edge cases senior may not have surfaced |
| Commits in scope | `2158e82` (ADR-009 + plan) on `claude/P1.3-plan` |
| Gates | N/A — plan-only review; 379 tests still green on this branch |

## Findings

| # | 🚦 | Where | What | What should be |
|---|----|-------|------|----------------|
| R0-A-on-plan-1 | 🟡 | ADR-009 Decision 6 (`SkillMatchRecord`) + P1.3-3 schema acceptance | **Field redundancy: `matched: bool` and `rejection_reason: Literal[..., "matched"]` carry the same information.** `matched=True` iff `rejection_reason="matched"`. Two fields for one fact — they can drift if one is set wrong (e.g., `matched=True, rejection_reason="agent_mismatch"` is a syntactically valid but semantically broken record). Pydantic doesn't enforce the cross-field invariant by default. Two paths: (a) **drop `matched: bool`**, derive from `rejection_reason != "matched"`; the Literal becomes the single source of truth (with "matched" as one value). (b) **Drop `"matched"` from the Literal**, make `rejection_reason: Literal[3 mismatches] | None` (None when matched); the bool becomes primary. Either is cleaner than the current shape. | Architect picks (a) or (b). Senior's lean (probably (a)) is fine — the Literal is more searchable than a bool ("why did this skill not match?" → grep the rejection_reason). If picking (a), update ADR-009 Decision 6 + the P1.3-3 schema acceptance code block + the P1.3-5 matcher behavior contract. One-line change in ADR; senior revises in-place same as W-001 R0-A pattern. |
| R0-A-on-plan-2 | 🟡 | ADR-009 (missing) + P1.3-4 acceptance (line 6) | **Filename-stem-equals-id rule is contract-locking but lives only in the plan, not in the ADR.** P1.3-4 acceptance says *"a file `config/skills/general/research-decomposition.md` MUST declare `id: research-decomposition`"* — this is a real rule that every future skill author follows. But ADR-009 doesn't mention it; Decision 2 just says `id: str` (min length 1). If a future contributor reads only ADR-009 + writes a skill loader implementation, they could miss the filename-stem constraint and pass validation with mismatched filenames. The rule is in P1.3-4's loader-implementation acceptance, not in the architectural contract. | Add an 8th decision to ADR-009: "Filename stem must equal `id`". Brief reason: clarity for human navigation (`grep "research-decomposition"` finds the file); prevents duplicates that share an id; matches the pattern other config conventions use (e.g., agent yaml stem = agent id). Single paragraph addition; senior revises ADR-009 in-place. |
| R0-A-on-plan-3 | 🟢 | ADR-009 Decision 2 (`category: Literal["general", "engineering", "business"]`) + Consequences | Closed-enum category is correct per Principle 4 (closed vocabulary over open strings). But the three buckets came from `handoff.md` §5.3's directory structure; that pre-dates real skill authoring. Future skills that don't fit (e.g., "test-related", "meta", "ops") force authors into the wrong bucket OR ADR amendment friction. Worth one sentence in Consequences acknowledging the tension and signposting "ADR-009 amendment is cheap if a category misfit shows up — additive Literal extension is reversibility-Low per ADR-007 §2 precedent." | Defer; or one-sentence addition by senior. |
| R0-A-on-plan-4 | 🟢 | ADR-009 Decision 2 + P1.3-3 schema (`Skill.body: str`) | `Skill.body` is required but unbounded — no `Field(min_length=1)`, no upper-length limit. Empty body silently passes today; very large bodies (10MB+ markdown) load into memory without truncation. Not a P1.3 concern in practice (MVP placeholder bodies are short), but worth noting: schema-level enforcement of `body` non-empty would catch authoring errors at load time; an upper bound could land later via additive ADR amendment when first agent runtime hits memory pressure. | Senior's call: add `Field(min_length=1)` to body in the P1.3-3 schema (no ADR change needed if just a validator). Skip if architect prefers "Run > polish". |
| R0-A-on-plan-5 | 🟢 | P1.3-4 acceptance (loader frontmatter parsing) | **Edge case not covered**: YAML frontmatter that parses successfully but to a non-dict (e.g., `---\nfoo\n---` parses to the string `"foo"`). Loader should detect and raise — same pattern as `llm/config_loader.py` `_read_yaml` (P1.2-C2 precedent) which checks `isinstance(raw, dict)`. P1.3-4 acceptance mentions "missing or malformed" raises but not the typed-but-wrong-shape case. | Senior adds one test case + one validator line: assert frontmatter parses to a dict before passing to Pydantic. Mechanical addition to P1.3-4 acceptance criteria. |

**🔴 None.** ADR is design-complete; plan is implementer-ready modulo R0-A-on-plan-1 + R0-A-on-plan-2 architect resolutions.

## Senior's 6 push-backs — architect-partner judgements

| Senior push-back | Architect-partner read |
|---|---|
| #1: ADR-009 yes (contract-locking) | ✅ **Accept.** Frontmatter is the contract every future skill author follows. ADR is the right surface for this. Brief lean was "probably ADR"; senior reading confirms. |
| #2: `applies_to.room_states = None` = all (Optional) | ✅ **Accept.** Empty list as footgun is the right framing; `None` (key omitted) is unambiguous. Alternative C in ADR-009 captures the rejected case. |
| #3: Sample skills count = 2 | ✅ **Accept.** Two skills cover all schema branches (both `agents` shapes, both `room_states` shapes, both categories, priority tie-break). Three would add test-bloat without exercising new shapes. |
| #4: Tie-breaking alphabetical by `id` | ✅ **Accept.** Deterministic, portable, greppable. FS order is OS-dependent (rejected). |
| #5: `triggering_event_type` accepted but unused (P1.4+ hook) | ✅ **Accept.** Avoiding a P1.4 signature change is the right trade. Documented "no effect in P1.3" + tested. |
| #6: `dict[str, Skill]` not `SkillRegistry` wrapper | ✅ **Accept.** Dict is the natural Python shape; wrap later if hot-reload / multi-directory loading enters scope. |

All 6 accepted. None challenged.

## Cross-checks performed (no findings)

- **7 atomic tasks vs 7 ADR-009 decisions coverage matrix**: every decision exercised by at least one task. Decision 1 → P1.3-6 sample skills; Decision 2 → P1.3-3 schema; Decision 3 → P1.3-3 + P1.3-5 + P1.3-6; Decision 4 → P1.3-3 + P1.3-5 + P1.3-6; Decision 5 → P1.3-5; Decision 6 → P1.3-3 + P1.3-5; Decision 7 → P1.3-3 constitutional tests. ✓
- **Layering**: `skills → core` (RoomType import) declared in P1.3-3; reverse direction forbidden via `test_constitution_core_does_not_import_skills` (W-001-impl Y1 precedent). `skills → llm` forbidden via `test_constitution_no_llm_calls_in_skills_module` (autonomy / workflow analogues). ✓
- **6-category coverage standard mapping**: §1 (P1.3-5 + P1.3-6 cross-module source ≠ sink); §2 N/A documented; §3 (P1.3-4 file-handle cleanup); §4 (P1.3-3 `SkillError` payload assertion); §5 (P1.3-3 multi-position agents-star validator test); §6 (P1.3-3 all 5 Pydantic models). Complete. ✓
- **Decision-trace shape vs `contributing.md` Q2**: `SkillSelection` embeds `SkillDecisionTrace`; precedent ADR-005 Decision 6 (autonomy_decision metadata). Match. ✓
- **ADR-009 Considered Alternatives count**: 5 (A-E), enumerated and rejected with reasons. Matches commit body claim. ✓
- **ADR-009 Reversibility table**: 7 rows for 7 decisions; calibration honest (Decision 1 + 7 marked Expensive correctly — format and layering are hard to reverse; rest cheaper). ✓
- **ADR-009 References completeness**: ADR-001 (closed-enum precedent), ADR-005 D6 (embed-trace), ADR-007 D2 (Literal extensibility), ADR-008 (state machine), brief, plan, handoff §3.1/§3.3/§5.3, contributing Q1/Q2/Q3, test-coverage-standard. ✓
- **Workflow state machine integration**: P1.3-2 advances state on Accept; P1.3-7 advances on landing; matches ADR-008 Decision 1 gated transitions. ✓
- **Workflow-overview canonical path for R0-A-on-plan**: this file at `docs/process/reviews/P1.3/R0-A-on-plan.md` per the RC-9 codified path. ✓
- **Distance test**: P1.3 brief 2026-05-26; senior plan + ADR-009 same-day; **same-day brief + plan is allowed** (planning artifacts, not architectural inscription). Architectural inscription happens at ADR-009 Accept (24h+ pause from now per ADR-008/W-001 brief Decision 8 precedent). ✓

## Architect-decision dependencies

Before junior dispatch, architect resolves:

1. **R0-A-on-plan-1** (matched + rejection_reason redundancy): pick (a) drop `matched` bool / (b) drop `"matched"` from Literal / (c) keep both as-is. Senior revises ADR-009 + P1.3-3 schema acceptance.
2. **R0-A-on-plan-2** (filename-stem-equals-id in ADR): add 8th decision to ADR-009? Recommend yes.
3. **R0-A-on-plan-3 / -4 / -5**: small refinements; can be folded into senior revision OR junior absorbs at impl time.

Architect-partner leans: (a) for #1, yes for #2, fold #3/#4/#5 into senior revision for minimum future drift.

Once architect resolves: senior revises in-place; architect-partner light re-review (small-edits-only pass); 24h+ distance test pause before ADR-009 Accept; junior dispatch follows.

## Cross-family R0-B status

Skipped per brief (P1.3 not categorical shape change; W-001 retro §6 RC-2 accept). Sixth consecutive P1.2+ skip. RC-2 trail intact; re-evaluate at P1.4 (multi-agent dispatch — true shape change).

## Verdict

**🟡 — plan is implementer-ready pending two small ADR-009 refinements (R0-A-on-plan-1 + -2) + three optional 🟢 doc-clarity touches.** Senior's quality is high: 6 well-reasoned push-backs, full coverage matrix, dependency chain clean, length within calibration. ADR-009 is structurally complete (7 decisions, 5 alternatives, calibrated reversibility); the 🟡s are refinements not redesigns.

Frontmatter `verdict: needs_architect` per ADR-008 Decision 7 — any 🟡 routes to `awaiting_architect_decision`. State machine should hold at `awaiting_architect_decision` until architect resolves R0-A-on-plan-1 + -2.

Once R0-A-on-plan-1 + -2 resolve:
- Senior revises ADR-009 (small edits)
- Architect-partner light re-verify (single pass)
- Distance-test pause 24h+
- Architect bumps ADR-009 Accepted
- Junior dispatch to `claude/P1.3-impl` branch
- impl-1 through impl-7 sequential per plan §3
