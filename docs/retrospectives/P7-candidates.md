# P7 Retrospective — Candidates

Accumulating during the P7 (loader cleanup + config/scoring hardening) cycle.
Folded into the final `P7.md` retrospective at task close-out. Same accumulation
pattern as the prior `*-candidates.md` files.

Captured by the **architect-partner** during the `awaiting_brief` ground-truth
reconciliation (architect ratified scope + "record retro candidate" in chat,
2026-06-16). Do not edit candidates after capture without leaving a note.

---

## RC-29 — Unverified LLM-generated code-review used as a brief premise (5 of 7 findings didn't survive a ground-truth check)

**Surfaced:** 2026-06-16, at P7 `awaiting_brief`, during architect-partner
verification of the intake `docs/code-review/P7-findings.md` against `HEAD`.

**Routing:** process discipline (brief-intake verification) — **not** a
code / ADR-008 change.

**Observation:** The P7 intake brief + `P7-findings.md` presented 7 findings
(3 High "O(n²)" + 4 Medium) with **confabulated code snippets** — e.g. it quoted
`skill.yaml` and a `for path in plugin_dir.rglob(...)` loop that **does not
exist** (real code is `*.md` + `next()`). Verified against current source:

| Finding | Claim | Reality |
|---|---|---|
| #1 `skills/loader.py` | High O(n²) | Reproduces, **milder** — redundant rglob on the error path + `StopIteration` footgun; not hot-path |
| #2 `agents/loader.py` | High O(n²) | **Does not reproduce** — already `if id in agents: raise` (O(1)); cited lines are the regex path |
| #3 `agents/dispatch.py` | High silent swallow | **Does not reproduce** — type guard already present; errors logged + `snapshot_failed` (ADR-014 D7) |
| #4 `autonomy/emission.py` | Medium silent swallow | **Deliberate** (ADR-007 §3) |
| #5 `agents/selection.py` | Medium O(n) | **Does not reproduce**; suggested fix is a **behavior regression** |
| #6 `autonomy/config.py` | Medium missing validator | Real gap, but **mis-cited by 13 lines**; minor |
| #7 `autonomy/scoring.py` | Medium undocumented floor | Doc-only; legit-trivial |

Net: **1 of 7** reproduced as written. Had the brief been finalized on the intake
premise, junior would have chased non-existent bugs (#2 / #3) and **introduced a
regression "fixing" #5**.

**What worked:** the architect-partner brief-stage verification (CLAUDE.md
"Surface, don't improvise") caught it **before** senior/junior dispatch — the
multi-role chain functioning as designed (no single unverified pass reaches
impl). This RC is about hardening the *intake* convention, not the catch.

**Candidate remedies:**
- **(a)** Make "verify each finding against current `HEAD` before it enters a
  brief" an **explicit checklist step** in `architect-partner.md` (brief-writing
  section) — today it is only implicit under "Surface, don't improvise."
- **(b)** When an intake cites an external / LLM-generated code-review, treat its
  line numbers + code snippets as **claims to verify**, not facts; require a
  `file:line` reconciliation table before brief finalization.
- **(c)** Convention: a code-review artifact dropped as task intake should carry
  a **"verified against commit `<sha>`?"** marker, so provenance/trust is
  explicit up front.

**Trigger to revisit:** the next time a task intake is seeded from an automated /
LLM code-audit rather than architect-authored intent.

**Cross-references:** `docs/process/architect-briefs/P7.md` (the corrected
brief); `docs/code-review/P7-findings.md` (the unreliable source); the session
chat reconciliation table; CLAUDE.md "Surface, don't improvise"; P1.5.5 RC-19
(the `eff_auto`-bundle trap precedent this brief explicitly fences in #7).
