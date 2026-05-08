# Writing ADRs for the Orchestrator project

ADRs (Architecture Decision Records) live in `docs/decisions/` as
`ADR-NNN-slug.md`. They are short, structured records of *why* a
decision was made — not *what* was done (that's in code) and not
*how it works* (that's in `docs/architecture/`).

The template lives at `ADR-template.md` in this directory. This
guide explains when to write one, how to write one well, and what
to avoid.

## When to write an ADR

Write an ADR when **the next person reading the code would ask "why
this way?" and the answer is non-obvious from the code itself**.

Specific triggers:

- Adding a new event type, agent role, room template, or LLM purpose.
- Changing append-only / immutability guarantees.
- Changing routing, gating, scoring, or selection logic in a way
  that affects user-facing behavior.
- Establishing or changing a project-wide pattern (interface freeze
  process, PR template, naming convention).
- Choosing one of several plausible implementations where the
  choice has trade-offs.
- Reversing or superseding a prior ADR.
- Decisions that span multiple modules and need a single canonical
  reference.

You don't need an ADR for:

- A typical feature PR that follows established patterns.
- Bug fixes (unless the bug reveals a design flaw worth recording).
- Refactors that don't change behavior.
- Style and formatting choices.
- Adding a new test.

When in doubt, write one. ADRs are cheap; the cost of *not* writing
one (people relitigating the same call six months later) is much
higher.

## Length and shape

Aim for **400-1500 words**. ADR-001 is on the long end (~1500) because
it established many foundational patterns at once; ADR-002 and ADR-003
should each be ~600-900 words.

If your ADR is under 400 words, you're probably under-explaining the
*why* (the part that matters most). If it's over 2000, you're either
covering multiple decisions that should be split, or you're writing
documentation instead of a decision record.

The template's six sections are mandatory. Empty sections are a
signal to either fill them or reconsider whether this is really an
ADR.

## What makes an ADR good

**The Context section makes the constraints concrete.** A reader who
has never seen the project should understand, after Context, why a
decision needs to be made at all. Concrete: "Multiple agents share
a model id. Swapping a model's parameters propagates everywhere."
Vague: "We need flexibility."

**Each Decision is declarative and self-contained.** The decision
itself fits in one sentence; the justification follows. If you can't
state the decision in one sentence, it's probably two decisions.

**Considered alternatives are named and rejected, not strawmanned.**
Give each alternative its strongest form. If "we considered using
Postgres but it was too complex" is the whole entry, you didn't
really consider it. The good shape: name it, sketch what choosing
it would have looked like, then say specifically what made it lose.

**Consequences are honest about both directions.** "Easier" with no
"Harder" is propaganda, not analysis. Every choice trades something
off; if you can't find the trade, you haven't found the choice yet.

**Reversibility is calibrated.** If everything is "Trivial," you
might be optimizing for ADRs that look easy to walk back. If
everything is "Expensive," you're treating the project as more
fragile than it is. ADR-001's table mixes both — that's healthy.

## Common anti-patterns

**The retrospective summary.** Writing the ADR after the work is
done, just describing what happened. The decision record exists to
record *the call*, not to narrate the implementation. Even when
written after the fact (some are), the focus is on the choice and
its alternatives.

**The compound ADR.** Several unrelated decisions packaged into one
file because they happened in the same PR. Split them. ADR-001 is an
exception only because the decisions are tightly coupled (event store
foundation) — most PRs that touch many areas should produce multiple
ADRs.

**The strawman alternatives.** Listing alternatives that nobody would
seriously propose, just to fill the section. If you can't think of a
real alternative, say so explicitly: "No alternatives seriously
considered — the decision was forced by [constraint]." Empty
alternatives section is better than fake ones.

**The hedge.** "We chose X, but it might be wrong, and we should
revisit." That's not a decision — that's an expression of uncertainty
deferred. If the decision is provisional, name what would change it:
"We chose X. If [specific signal] occurs, we should reverse to Y."

**The future-proof ADR.** Padding the ADR with discussion of
hypothetical future scenarios. Stick to the decision being made now,
in this context. Future scenarios can be footnotes; if a real future
decision arrives, write a new ADR.

**The implementation manual.** Code-level detail that belongs in
docstrings, architecture docs, or the code itself. The ADR is about
*why*, not *how to use*. If it reads like a tutorial, the level is
wrong.

## Status field

- **Proposed** — drafted, not yet accepted. Useful for ADRs that need
  review before commit (rare in this project, since ADRs are usually
  written after the corresponding implementation is reviewed).
- **Accepted** — the canonical record. Most ADRs spend their lives here.
- **Superseded by ADR-NNN** — replaced by a later ADR. The old ADR is
  *not deleted* — it stays as the historical record. The new ADR
  references it in its References section.

Don't use **Deprecated** or **Rejected**. If a decision is no longer
correct, supersede it. If a proposed ADR doesn't get accepted, just
don't merge it; an ADR that was never the project's position
shouldn't sit in `docs/decisions/`.

## Numbering and slugs

ADRs are numbered sequentially: ADR-001, ADR-002, ... Numbers don't
get reused; superseded ADRs keep their number.

The slug in the filename matches the title's noun phrase, lowercased
and hyphenated:

- ADR-001: Event Store Foundation → `ADR-001-event-store-foundation.md`
- ADR-003: Tool calling architecture: why CLI providers can't control
  orchestrator tools → `ADR-003-claude-code-no-orchestrator-tools.md`
  (slug is shorter than title — that's fine, optimize for filename
  readability, not 1:1 mirroring)

## When the implementation precedes the ADR

In this project, the typical sequence is: interface freeze → review →
implementation → ADR. The ADR is written *after* the work, capturing
the decisions that the work embodies. This is fine and intentional —
it means the ADR records what was actually decided, not what was
proposed.

The exception: a decision so consequential that it needs review *before*
implementation should get a Proposed ADR first. Cases include
introducing a new persistence boundary, adding an LLM purpose,
changing the autonomy gateway. These are rare; most decisions surface
naturally during the interface freeze and get recorded after.

## Cross-references

- Reference relevant `handoff.md` sections by number.
- Reference relevant `chat-history.md` sections — these explain the
  reasoning history, complementing the ADR's "what was decided".
- Reference prior ADRs by number. If superseding, name the relationship.
- Reference the PR or commit range that produced the work, so future
  readers can find the implementation from the ADR.

## Final note

ADRs are for the next person who reads the code and wonders "why?".
That person is often *future you*, six months later, with the
context faded. Write what would have helped you then. Don't write to
impress; write to inform.
