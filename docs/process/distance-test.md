# Distance test

When and how architectural inscriptions get a fresh-eye pause before landing.

## The rule

Between **drafting** an architectural inscription and **landing** it, a fresh-eye revisit by the architect — typically after a sleep cycle — must occur. The architect's self-report (explicit "I've slept and re-thought; the decision still stands" OR an implicit absence of commits during a sleep window followed by a return to the decision) is the canonical signal.

**Strict elapsed time is NOT the rule.** Wording like "24h+ minimum" appeared in earlier briefs as a useful proxy and rule-of-thumb default, but the substrate the rule was designed to capture is **cognitive freshness via sleep cycle + revisit**. Three documented instances in the P1.2 / W-001 / P1.3 period showed the architect consistently choosing substrate over letter (see § "How this rule emerged" below); the rule is now codified at the substrate.

## What triggers the distance test

- ADR acceptance (status flip Proposed → Accepted).
- Frozen Pydantic schema changes (new field, removed field, validator addition or removal).
- New `EventType` enum value.
- Workflow rule changes (changes to this document, to `senior-planner.md`, to `contributing.md` Q1–Q4, to ADR-008 state machine vocabulary or transitions).
- Role-doc changes (architect-partner / senior / junior / reviewer role definitions).
- Dropping, weakening, or replacing a forcing function (e.g., constitutional test removal, 5-surface scan rule modification).
- Distance-test rule itself changing (this doc).

## What does NOT trigger the distance test

- Senior task plans (planning artifact; design discussion, not architectural inscription).
- Architect briefs (same).
- Plan-vs-impl reviews (verification artifact).
- R0-A / R0-B reviews (verification artifact).
- Junior implementation commits (mechanical execution of an accepted plan).
- Trivial-fix commits routed to junior (typo / single-line / fixture fix patterns established in C3 Y1 / C4 Y1+G1+G3 / W-001-impl R0-A-1 / etc.).
- Documentation cleanups that don't change architectural rules (typo fixes, narrative additions, cross-link additions).
- Retrospective candidate captures and retrospective-document writing (process meta, not architectural inscription).
- State-machine state advances and override commits (operational, not architectural).

## Substrate vs proxy

| Concept | What it is | Used as |
|---|---|---|
| **Substrate** | Sleep cycle + fresh-eye revisit. The architect's actual cognitive break between drafting and landing. | The canonical rule. The thing the project actually wants. |
| **Proxy: 24h+ elapsed time** | A measurable wall-clock threshold. | Useful default reminder when briefs are written: "are you sure you want to land this same-day?" Not binding. |
| **Proxy: same-calendar-day-in-architect-timezone forbidden** | An alternate proxy considered during RC-8 codification (option γ). | Rejected at codification time: too brittle (architect-side timezone changes, multi-day work-from-bed scenarios) and not closer to the substrate than the 24h proxy. |

## Architect waiver

The architect can waive the distance test for any specific inscription. The waiver must be recorded in the commit body of the accepting commit. Suggested formula:

> *"Distance test: architect waiver — [reason]."*

Reasons that have appeared in practice: "no novel decision content; this is a rename / numbering refresh"; "sleep cycle has happened (last commit was N hours ago, architect-on-record sleeping in between)"; "decision is purely about reverting a recent inscription where the original distance test held but the implementation surfaced a defect."

Waivers ARE logged in git history; future readers see the explicit choice. **Self-loop check**: a waiver that doesn't articulate a substrate-respecting reason is a yellow flag for the next retrospective.

## Architect-partner's role

When dispatching architectural inscriptions:

- **Surface the distance-test pause as default**: "ADR ready for Accept; standard fresh-eye pause expected before bump."
- **If architect waives**: record the waiver verbatim in the commit body of the Accept commit; do not silently proceed without the explicit signal.
- **Do NOT auto-execute the architect-Accept** (status flip Proposed → Accepted) without an explicit architect signal — either a "go" message or a waiver.
- **Track repeated waivers**: if the architect waives 3+ consecutive distance tests across a single module, surface as a retrospective candidate (the rule may be wrong, or the architect's project tempo may have shifted, or the substrate may be drifting from the proxy).

## Architect's role

- Self-report the substrate (sleep happened; fresh-eye revisit done) **OR** explicitly waive with reason.
- Avoid implicit waiver: silence between "draft" and "accept" is ambiguous; either signal explicitly OR let the standard 24h+ proxy apply.
- Drop the proxy when it's not needed; lean on it when it is. The waiver mechanism makes this possible without rewriting the rule.

## How this rule emerged

Three observed instances of substrate-over-letter divergence graduated this rule from candidate (RC-4 / RC-8 in P1.2 and W-001 retrospectives) to codified text (this file):

1. **2026-05-20 (P1.2-C4)**: Junior impl commits for ADR-007 landed same calendar day as ADR-007 Accept. The W-001 brief had explicitly said "no earlier than 2026-05-21" — interpreted at brief time as next-calendar-day. Architect-partner flagged the deviation in `docs/process/reviews/P1.2-C4/R0-A.md` as a meta-observation.
2. **2026-05-21 (W-001 ADR-008)**: Status flip Proposed → Accepted requested ~13 hours after senior's last revision push. Architect-partner surfaced the math (brief required 24h+); architect chose substrate (sleep separation was preserved) over strict letter.
3. **2026-05-26 (P1.3 ADR-009)**: Architect explicitly stated "24h+ distance test pause is not needed at all" when architect-partner surfaced the standard wording. Third consecutive substrate-over-letter resolution; threshold for graduation per RC-8 was met.

Each instance was a yellow flag in its own moment. Three instances were the signal that the proxy had become the wrong rule. This codification swaps proxy for substrate; the proxy remains a default reminder but no longer binds.

## See also

- ADR-005, ADR-007, ADR-008 — past ADRs whose acceptance moments exercised the rule.
- `docs/retrospectives/W-001-candidates.md` RC-8 (now graduated by this doc).
- `docs/retrospectives/P1.2.md` §6 (distance test observations).
- `docs/process/senior-planner.md` § "ADR drafting" (where the distance test is referenced in the planning loop).
- `docs/process/workflow-overview.md` §7 (where the disputed-state was previously documented; supersede when this doc lands).
