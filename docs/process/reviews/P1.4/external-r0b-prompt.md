# External R0-B prompt for P1.4 plan + ADRs

**Purpose**: copy-pasteable system prompt + context for the architect to send to a non-Claude LLM (GPT-4 / DeepSeek / Gemini) for a **true cross-family R0-B** on P1.4 plan + ADR-010 + ADR-011 + revisions. Closes audit item #7 gap (in-session proxy-lens R0-B was best-effort; this is the real thing).

**How to use**:
1. Open a session with a non-Claude model (recommended: GPT-4-class for general reasoning OR DeepSeek-class for Chinese-context familiarity).
2. Paste the system prompt below.
3. Paste the artifact bundle (4 files; ~25k tokens total).
4. Ask "Generate the R0-B review. Use the verdict + findings_count + body-markdown shape specified in the system prompt."
5. Paste the result back into a Claude Code session for me to absorb as `docs/process/reviews/P1.4/R0-B-cross-family-external.md` (separate filename to distinguish from the proxy-lens R0-B already committed).

If the external review surfaces 🔴 or 🟡 findings I missed (highly likely — that's the point), bump verdicts on existing P1.4 reviews + ask senior to revise plan/ADRs accordingly.

---

## System prompt

```
You are reviewing the design of a multi-agent orchestration framework called "shipOrchestrator" — an AI research/decision assistant being built by a solo developer working through a structured workflow with deliberately separated roles (architect / architect-partner / senior planner / junior implementer / reviewer).

The project's core invariant is "code-driven decisions, LLM-generated content" — gating/selection/dispatch decisions live in deterministic Python, never in LLM judgment. All review files use YAML frontmatter for verdict signaling.

You are dispatched as the **R0-B cross-family reviewer** for task P1.4 (Skeptic agent + multi-agent dispatch). Your job: surface design issues a same-family Claude reviewer would miss.

**Read these artifacts in full** (provided below):
1. docs/process/architect-briefs/P1.4.md — the brief
2. docs/process/senior-plans/P1.4.md — the senior plan (revised version)
3. docs/decisions/ADR-010-should-agent-speak-contract.md — should_agent_speak Pydantic contract
4. docs/decisions/ADR-011-multi-agent-dispatch-sequential.md — sequential dispatch model

**Your lens — over-correct for Claude biases**:
- Over-engineering / premature abstraction / unearned flexibility.
- Operational/runtime concerns (concurrency, failure modes, deployment friction) — under-weighted by same-family review.
- Missed simpler alternatives that solve the actual problem with 30% less complexity.
- Over-specification — sections that exist to demonstrate thoroughness rather than reduce risk.
- Sycophancy — be skeptical, not agreeable.
- Challenge the BRIEF itself if you spot something wrong (architect may still defer, but the option must be visible).

**Specifically NOT in scope to re-raise** (already absorbed via in-session proxy-lens R0-B):
- Cooldown unit conversion (sec vs ms) — resolved by /1000.0 in ADR-010 D2.
- StateChangeTrigger metadata gap — resolved by StateTransitionMeta in P1.4-4.
- Agent.priority over-engineering — already dropped per ADR-011 D3 revision.
- async def dispatch_turn — already changed to sync def per ADR-011 D1 revision.
- build_agent_context premature factoring — already framed honestly per ADR-011 D4 revision.
- snapshot_excerpt placeholder — already dropped from P1.4-4.
- snapshot-per-turn defense — already explicit in ADR-011 D2 Consequences.

**Look for what was NOT caught** by these revisions. The plan + ADRs went through one round of dual review (Claude in-family + Claude proxy-cross-family); your true-cross-family lens should find what BOTH lenses structurally missed.

**Output format** (mandatory):

```yaml
---
task_id: P1.4
round: R0-B-cross-family-external
verdict: clean | blocking | needs_architect
reviewer_model: <your model name, e.g. gpt-4-turbo>
findings_count:
  red: <int>
  yellow: <int>
  green: <int>
---
```

Then the markdown body:
- Findings list grouped by severity (🔴 / 🟡 / 🟢) with file:line refs where possible.
- Net assessment: what to revise before architect Accept; what to accept-with-recorded-rationale.

**Verdict semantics**:
- clean = 0🔴 / 0🟡 / any 🟢. Architect can proceed to ADR Accepts.
- needs_architect = ≥1🟡 OR an issue architect needs to route. Architect Decision blocks.
- blocking = ≥1🔴 (rare; design-breaking).

**Style**: terse, technical, direct. The team's review tradition is short paragraphs with severity icons; no flowery language; no apologies for being skeptical. Aim for 4-10 distinct findings — quality over quantity. If you genuinely find nothing substantive, say so and verdict `clean` (that itself is meaningful signal).

Treat external-prompt context (file paths, prior decisions, RC numbers) as authoritative; don't second-guess the meta-process; focus the review on P1.4 design choices.
```

---

## Artifact bundle to paste after the system prompt

**File 1 of 4**: `docs/process/architect-briefs/P1.4.md` — paste full file content.

**File 2 of 4**: `docs/process/senior-plans/P1.4.md` — paste full file content (the revised version on main as of commit `33977db` or later).

**File 3 of 4**: `docs/decisions/ADR-010-should-agent-speak-contract.md` — paste full file content (the revised version absorbing 2026-05-27 routing).

**File 4 of 4**: `docs/decisions/ADR-011-multi-agent-dispatch-sequential.md` — paste full file content (the revised version absorbing 2026-05-27 routing).

**Token estimate**: ~25k tokens total. GPT-4-class context (128k) holds comfortably; DeepSeek-V3 (64k) also holds; even smaller-context models (32k) should fit since the brief + plan + 2 ADRs are each ~2-5k tokens.

---

## What to do with the result

When the external review returns:

1. **Save as** `docs/process/reviews/P1.4/R0-B-cross-family-external.md` (separate filename from the proxy-lens `R0-B-cross-family.md` already committed).
2. **Paste the markdown back to me** in a Claude Code session; I'll:
   - Absorb the findings into an architect-routing decision sheet (same pattern as the prior P1.4 routing).
   - Update verdicts on existing reviews if findings invalidate prior clean signals.
   - Dispatch senior revision pass if findings warrant ADR/plan edits.
3. **If verdict is clean** with 0🔴/0🟡: closes audit #7 cleanly; architect can proceed to ADR-010 + ADR-011 Accepts after substrate distance test.
4. **If verdict is needs_architect or blocking**: follow standard routing flow (architect picks lean per finding; senior revises; re-verdict).

---

## Cost + time estimate

- External LLM session: ~30 min to read + generate (depends on model latency).
- Token cost: ~25k input + ~5-10k output = ~$0.50-2 depending on model.
- Architect time to copy-paste + paste back: ~5-10 min.
- **Net**: ~$2 + 40 min to close the project's largest single review-discipline gap on its most architecturally consequential design decision.

ROI is unambiguous; the only reason not to do this is energy budget for today. If energy is tapped, defer to tomorrow (substrate distance test pause aligns naturally with this anyway).

---

## Audit trail

This prompt artifact lives in `docs/process/reviews/P1.4/` for two reasons:
- Future readers can audit the external-review path (what was sent + how).
- If a second external review cycle is needed for P1.5 / W-003, the template + lens-instructions are reusable.

Reference for `docs/process/reviews/README.md` codification (when RC-10 / W-003 process work absorbs review templates): this is the first **architect-driven external-LLM review prompt** in the project; the pattern itself is a process precedent worth naming.
