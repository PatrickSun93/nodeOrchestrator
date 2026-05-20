# W-001 R0-A review

| Field | Value |
|---|---|
| Round | R0 (first external review of ADR-008 draft + W-001-impl plan stub) |
| Reviewer | A (architect-partner Claude session) |
| Family | Claude (Opus 4.7) — same as senior (Sonnet 4.6) |
| Cross-family R0-B | not dispatched (architect not asked; surface as architect decision below) |
| Lens | ADR-design review (vocabulary completeness, decisions internal consistency, considered-alternatives quality, reversibility calibration, cross-reference integrity, edge cases ADR doesn't cover); plan stub review (rough-cuts coverage, dependency identification, push-back substance) |
| Commits in scope | `b00c779` (senior plan + ADR-008 draft) on `claude/w-001-plan` |
| Gates | N/A — doc-only artifacts; pytest 301 still green on main |

## Findings on ADR-008

| # | 🚦 | File : line | What's wrong | What should be |
|---|----|-------------|--------------|----------------|
| R0-A-1 | 🟡 | ADR-008 Decision 6 (lines 166-178) — "State vocabulary (8 states + closed)" | **Counting/framing inconsistency.** Decision header says "8 states + closed" but the enumerated list has **9 items** (closed at #9). The framing reads `closed` as outside the state set, but it's listed inside the enum with a number. Future readers (and the implementation) will be confused about whether the canonical state count is 8 or 9. Compare with `EventType` (17, all of equal status) — there's no "16 types + autonomy_decision" framing. Either `closed` is a state (count = 9, no parenthetical) or `closed` is a terminal-state-not-counted (don't list it under the same enumeration). | Two options: (a) re-title to "State vocabulary (9 states including terminal `closed`)" and treat `closed` as a normal state value; (b) split — "8 active states + 1 terminal state `closed`"; lift `closed` to a separate subsection. (a) is cleaner — `closed` IS a state, just one with no outgoing transitions. State-machine theory treats terminal states as members of the state set. |
| R0-A-2 | 🟡 | ADR-008 Decision 1 (lines 96-117) gated transitions table | **Rework transition missing from Decision 1's table.** Decision 1's "Gated" table lists 4 transitions but does not include `awaiting_architect_decision → awaiting_junior_impl` (R1/R2 rework). Decision 11 ("Rework loop semantics", line 269) describes this transition narratively but it's not in Decision 1's enumeration. Reader implementing the state machine off Decision 1's table alone would miss the rework path. The rework transition IS gated (architect rules on 🟡 routing), so it belongs in Decision 1's gated table, not in a separate decision. | Add a row to Decision 1's gated table: `awaiting_architect_decision` → `awaiting_junior_impl` (rework case) — trigger: "architect rules `rework` on 🟡 routing". And keep Decision 11 for the cycle-counter semantics specifically. The transition appears in both decisions; the table is the source of truth for "where it goes". |
| R0-A-3 | 🟢 | ADR-008 Decision 13 (lines 298-309) — "Same-family R0 chain orthogonal" | Declared orthogonal to ADR-008. Defensible architecturally (state machine fires R0-A; R0-B is architect-decision). But Decision 13 hard-codes R0-B as outside the state machine, which makes future "require R0-B at module-completion" enforcement an ADR amendment rather than additive precondition. Combined with RC-2's still-open status (3 consecutive P1.2 skips), this creates a small precedent of "ADR-008 sealed the door to R0-B-as-state-machine-gate before RC-2 reached its verdict." Senior's plan stub §5.1 mitigates by leaving room in the state-file schema (`requires_cross_family_review: bool`); ADR-008 itself doesn't reference that mitigation. | Either (a) cross-reference plan stub §5.1's schema hook in ADR-008 Decision 13's last paragraph (closes the loop), or (b) accept as documented orthogonal + watch RC-2 evolution. Architect call. |
| R0-A-4 | 🟢 | ADR-008 Decision 11 (lines 269-279) — "No maximum cycle count" | Relies on **architect judgement** as the implicit stop condition for runaway rework. This works because the architect IS in the loop at every R0-A/architect-decision transition. But it's tacit — no state-file field surfaces high cycle counts to architect attention. Future contributors may not notice cycle counter climbing. | Optional impl-time addition (NOT blocking for ADR): state-file field `cycle: 5` automatically triggers a state-machine warning in `awaiting_architect_decision`'s artifact (e.g., review file frontmatter `warnings: ["cycle_count_high"]`). Architect-partner can surface in their R0-A finding. impl-2 design choice; ADR text need not pre-commit. |
| R0-A-5 | 🟢 | ADR-008 Decision 12 + Consequences "Harder" (line 421-424) — Frontmatter retrofit silence | Existing P1.2 review files (`plan-vs-impl.md` for C3 + C4, `R0-A.md` for C3 + C4) lack the `verdict` frontmatter. ADR-008 says no retroactive edits (Decision 12), state machine never reads closed-task files. **Consequence:** if a future contributor reads `docs/process/reviews/P1.2-C3/R0-A.md` and `docs/process/reviews/P1.3-C1/R0-A.md` side-by-side, they will see two different review formats — confusing without context. The `reviews/README.md` should document the inflection point: "files in `P1.2-*/` predate ADR-008 frontmatter convention; files in `P1.3-*/` onward carry frontmatter." | impl-3 (per W-001-impl plan stub) updates `reviews/README.md` to document the inflection. ADR-008 doesn't need to change; surface for impl-3 acceptance criteria. |
| R0-A-6 | 🟢 | ADR-008 Decision 10 (lines 242-267) — Override audit | "Overrides written by architect (or architect-partner with architect's authorization recorded in `reason`)" — covers planned overrides. **Missing**: emergency state-file fix when state machine itself has a bug (e.g., frontmatter parser mis-reads, false auto-trigger fires, state file gets out of sync with reality). Should partner have unilateral fix authority in true state-machine-bug cases? Lean: same `reason`-recording pattern, treat state-machine-bug-fix as a category of override. | Add a sentence to Decision 10: *"Emergency overrides (e.g., state-machine bug, parser error, file corruption) follow the same `reason`-recorded pattern; the bug itself is filed separately and the reason cites it."* Half-sentence addition; closes the implicit edge case. |

## Findings on W-001-impl plan stub

| # | 🚦 | Location | What's wrong | What should be |
|---|----|----------|--------------|----------------|
| R0-A-7 | 🟢 | W-001-impl plan stub §3 (line 48-52) push-backs | Senior identifies 5 anticipated push-backs but the brief itself predicted no push-backs (it's a plan stub, full plan post-Accept). The §3 list has good architecture content — particularly push-back #1 (module location) and #2 (hook vs CLI). These deserve architect decision **before** full plan is written. Surface as gate items: "architect picks #1 + #2 before senior writes full plan." | Senior's plan stub already names this in §4 Dependencies ("Architect choice on §3 push-back #1 before impl-1 starts"). No change needed — calling out the visibility. |
| R0-A-8 | 🟢 | W-001-impl plan stub §5.3 (brief amendment cycles) | Senior 5.3 references `8b727c0` precedent ("amend brief intro mid-cycle"). Good catch. Senior leans (a) — state stays in current state on brief amendment, override available if material. **Edge case not covered**: what if architect amends a brief during `awaiting_brief` (before senior plan started)? Likely irrelevant in practice (brief amendments mid-`awaiting_senior_plan` are rare; pre-plan amendments are just revisions). Worth one sentence in impl-2's docstring. | impl-2 docstring: "Brief amendments after `awaiting_brief` exit are no-ops to the state machine; brief revisions before `awaiting_senior_plan` exit are also no-ops; senior reads the latest brief content as ground truth." |

**🔴 None.** ADR is design-complete; plan stub matches its declared scope (rough cuts, not full atomic tasks).

## Cross-checks performed (no findings)

- **Decisions enumeration vs commit body claim**: senior commit body says "13 decisions". ADR has 13 numbered Decisions sections. ✓
- **Considered alternatives count**: senior commit body says "6 considered alternatives" but ADR has 9 alternatives (A through I). Mismatch in commit body — alternatives section is larger than advertised. Defensible (more thorough than promised) but worth fixing the commit body claim for future audit; commit body is immutable so flagging only. ✓ (Minor — not in findings table because immutable.)
- **Reversibility table per-decision**: ADR has reversibility entries for all 13 decisions. Calibration looks honest — Decision 2 (code-only transitions) marked Expensive is correct; Decision 4 (`.workflow/` location) marked Trivial is correct. ✓
- **References section completeness**: ADR cross-links ADR-001 (pure-code precedent), ADR-005 (bootstrap exception NOT extended), ADR-006 + ADR-007 (senior-drafts precedent), senior-planner.md, handoff.md §16, P1.2 retro §2/§5/§6/§9, W-001 brief, W-001-impl plan stub. Complete. ✓
- **Bootstrap circularity**: ADR-008 itself runs outside state machine (Decision 12). W-001 (this task, which produces ADR-008 + plan stub) has no `.workflow/W-001.yaml`. Consistent. ✓
- **Senior self-discoveries 5.1-5.4**: each is a real edge case worth recording.
  - 5.1 (R0-B chain risk + schema hook) → R0-A-3 above bundles this.
  - 5.2 (side-channel artifacts as no-ops) → uncontroversial; impl-2 docstring should make explicit.
  - 5.3 (brief amendments) → R0-A-8 above bundles this with a small extension.
  - 5.4 (ADR Accept timing race; state machine reads origin/main only) → uncontroversial mitigation.
- **Senior's commit body alternatives-count claim of "6" but ADR has 9**: cosmetic only; senior's body undersells the work.
- **Bootstrap of P1.2 closed work**: Decision 12 explicitly says no retroactive `.workflow/` files. ✓
- **No `.workflow/` artifact in this PR**: scope respected; W-001 is ADR + plan stub only. ✓

## Architect-decision dependencies surfaced

Architect needs to decide before W-001-impl full plan is written:

1. **R0-A-1 resolution**: pick option (a) recount 9 states OR (b) terminal-state split. (a) is the simpler ADR edit.
2. **R0-A-2 resolution**: add rework row to Decision 1 table.
3. **R0-A-3 resolution**: cross-reference schema hook in Decision 13, or accept as-is.
4. **R0-A-6 resolution**: add emergency-override sentence to Decision 10, or accept as-is.
5. **Plan-stub gate item (R0-A-7)**: architect picks W-001-impl plan §3 push-back #1 (module location: `src/orchestrator/workflow/` vs `tools/`).
6. **Plan-stub gate item (R0-A-7)**: architect picks W-001-impl plan §3 push-back #2 (hook vs CLI vs both).

(2) and (4) are small ADR edits within senior's drafting scope (Proposed status; senior can revise then re-ping for architect-partner review). (1) is also small. (5) and (6) are architect-decision-not-ADR-content. (3) is architect-decision.

## Cross-family R0-B status

**Skipped this round** (architect not asked; defaulting to skip per recent pattern). RC-2 evidence trail now has 4 instances (C2/C3/C4/W-001). The ADR-008 design itself touches workflow architecture — arguably the highest-stakes ADR in the project so far in terms of breadth of impact. **This is the strongest case for cross-family R0-B in P1.2+** if architect wants one. Architect call.

## Verdict

**🟡 — ADR-008 is design-sound; two small ADR edits (R0-A-1 + R0-A-2) needed; four watch items (R0-A-3 through R0-A-6) carry architect decisions or impl-3 acceptance criteria.** Plan stub is correctly scoped; senior self-discoveries 5.1-5.4 are sharp; R0-A-7 + R0-A-8 are watch items not blocking.

Architect's next path:

- (i) Pick (a)/(b) for R0-A-1 + R0-A-2 → senior revises ADR-008 (same `Proposed` status, no Accept yet).
- (ii) Decide R0-A-3 and R0-A-6 — small ADR additions or accept-as-is.
- (iii) Decide module location + hook/CLI for plan stub.
- (iv) **Distance-test pause 24h+** before Accept (per W-001 brief explicit requirement).
- (v) If architect wants cross-family R0-B on ADR-008 (highest-stakes ADR), this is the moment to dispatch.

R0-A's full lens applied; architect-partner has no further findings. Doc-only artifacts so no gates to run.
