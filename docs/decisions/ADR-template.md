# ADR-NNN: [Decision title — noun phrase, 5-10 words]

**Status:** [Proposed | Accepted | Superseded by ADR-XXX] — YYYY-MM-DD
**Scope:** [One sentence describing the boundary of what this ADR governs.
The reader should know after this line whether the ADR applies to the
question they have.]

## Context

[2-5 paragraphs.]

What problem are we solving? What constraints are in play (technical,
project-philosophical, time)? Which 12 principles does this touch?
What was tried before, if anything?

End this section by stating what the foundation must support — the
hard requirements the decision must satisfy. Reviewers can use these
to validate the decision.

## Decisions

[Numbered list. Each decision is one self-contained call. Most ADRs
have 1-3 decisions; some have many (ADR-001 had 11). Don't artificially
inflate or compress.]

### 1. [First decision — declarative, present tense]

[Statement of what is decided.]

[Why: 1-3 paragraphs justifying. Cite principles, prior ADRs,
project constraints. If this overrules a prior decision (project's,
LLM's, contributor's), name what was overruled and why.]

[How: code sketch or concrete example if it sharpens the decision.
Keep short — full impl belongs in the code, not the ADR.]

### 2. [Next decision]

[Same shape.]

## Considered alternatives

[Each alternative gets a short subsection. Name it, sketch it, then
say why it lost. The point is to record what was *considered and
rejected* so the next reader doesn't relitigate.]

### A. [Alternative one]

[Sketch. One paragraph.]

[Why rejected. One paragraph. If multiple decisions in this ADR ruled
it out, point to which.]

### B. [Alternative two]

[Same shape.]

[Note: ADRs that span architectural strategies AND implementation
mechanisms — like ADR-003 — should split alternatives into two
groups: "Architectural strategies considered" (the broader call)
and "Implementation alternatives within the chosen strategy" (the
narrower call). Don't flatten the two; readers ask different
questions.]

## Consequences

[What does the decision change about how the system feels to work
with? Three subsections, each a bulleted list.]

**Easier:**

- [Specific things that become better. Don't wave: "auditing,
  testing" is bad; "every routing decision now returns a
  decision_trace, so 'why did this fall back?' is one log line"
  is good.]

**Harder:**

- [Honest list of what becomes worse. Every architectural choice
  trades something off; if you can't list anything, you haven't
  thought about it. Hidden costs surface here.]

**Neutral:**

- [Things that change but neither help nor hurt. Useful for noting
  surface-level differences that future readers might mistake for
  improvements or regressions.]

## Reversibility

[Table. For each decision (and any non-trivial alternative we'd
realistically reverse to), estimate the cost of undoing it in 6
months. The cost shapes how much weight to give the decision today
— cheap-to-reverse decisions can be made on weaker evidence; hard-
to-reverse decisions deserve more care.]

| Decision | 6-month reversal cost |
|---|---|
| [Decision 1 short label] | [Trivial / Low / Medium / Expensive — followed by one sentence on what makes it that.] |
| [Decision 2 short label] | [...] |

## References

- [Links to handoff.md sections, chat-history.md sections, prior
  ADRs, related code paths, external sources cited.]
- [If this PR establishes the decision, mention the PR / commit
  range so the implementation can be found from the ADR.]
