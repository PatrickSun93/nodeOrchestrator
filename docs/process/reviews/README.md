# Reviews

Per-task review artifacts, one subfolder per task ID
(e.g. `P1.2-C3/`). Inside each subfolder:

- `plan-vs-impl.md` — senior's self-verification that the impl
  matches the plan. Written by senior, read by architect before
  external reviewer dispatch.
- `R0-A.md`, `R0-B.md` — first-round external reviewers. `-A` is
  Claude family, `-B` is cross-family (DeepSeek / Gemini / other).
  Both follow the tracking-table format (🔴/🟡/🟢 + file:line +
  what's wrong + what should be).
- `R1-A.md`, `R1-B.md`, etc. — subsequent rounds if needed.
- `meta.md` — close-out meta-review across all rounds.

Empty `-B.md` slots stay empty: an absent `R0-B.md` is the evidence
that cross-family R0 was not dispatched that round. The empirical
question "was a single-reviewer R0 sufficient?" is answerable from
the absence + subsequent round outcomes.
