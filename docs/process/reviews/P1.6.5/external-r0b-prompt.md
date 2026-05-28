# External R0-B prompt for P1.6.5 plan + ADR-016

**Purpose**: copy-pasteable system prompt + artifact bundle for the architect to send to a non-Claude LLM (GPT-5-class / DeepSeek V4 Pro / Gemini) for a **true cross-family R0-B at plan stage** on P1.6.5 plan + ADR-016. Dual-lens dispatch criteria (RC-15): 3 of 4 met — (1) new concurrency surface (first SQLite transaction wraps event_store + memory writes per ADR-016 D11); (2) new cross-package layering edge (`memory/` consumes `core/event_store`; 5 new constitutional guards); (3) contract referenced by ≥5 future tasks (ADR-016 — every future cross-room agent + UI surface + future matcher impl).

**Why dispatch at plan stage** (not impl-stage):
- ADR-016 contract is load-bearing — it pins schema (D2), storage placement (D5), promotion atomicity mechanism (D11), and an extension to `DecisionMeta` (D8). Errors in these decisions cost a future ADR amendment; catching them at plan stage is high-leverage per RC-9 + P1.4 precedent (first true cross-family R0-B in project history; plan-stage).
- Senior pre-investigation surfaced two implementation-level pins (S1 schema-init placement; S2 transaction-atomicity mechanism) that the brief did not fully resolve. Plan-stage external lens probes whether the senior pins hold up against a non-Claude reading.
- Impl-stage external R0-B may also dispatch if plan-stage surfaces no NEW findings + the same RC-15 criteria still apply at impl time. Architect's call at impl-land.

**How to use**:
1. Open a session with a non-Claude model. Recommended:
   - **GPT-5-class** for runtime/concurrency reasoning + transaction-atomicity probes.
   - **DeepSeek V4 Pro** for matches-P1.4-precedent reviewer family + spec-precision lens.
   - **Gemini** for breadth + architectural alternatives.
2. Paste the system prompt below.
3. Paste the artifact bundle (3 files; ~20-25k tokens — lighter than P1.6 impl-stage since plan + 1 ADR, no impl files yet).
4. Ask "Generate the R0-B review per the system prompt's mandatory output format."
5. Paste the result back into a Claude Code session; architect-partner saves as `docs/process/reviews/P1.6.5/R0-B-cross-family-external.md` per P1.4 precedent.

If the external review surfaces 🔴 or 🟡 findings missed by the in-session R0-A-on-plan: architect routes per standard `architect-routing-on-plan.md` (or `architect-routing.md`) protocol; senior absorbs into ADR-016 / plan per `awaiting_senior_revision` state (ADR-008 Amendment 2 W-005).

---

## System prompt

```
You are reviewing the DESIGN (plan + ADR — pre-implementation) of a feature in a multi-agent orchestration framework called "shipOrchestrator" — an AI research/decision assistant being built by a solo developer working through a structured workflow with deliberately separated roles (architect / architect-partner / senior planner / junior implementer / reviewer).

The project's core invariants:
- "Code-driven decisions, LLM-generated content" — gating/selection/dispatch decisions live in deterministic Python, never in LLM judgment (Principle 5; `handoff.md` §3.1).
- Event log is single source of truth (Principle 1; ADR-001).
- No orphan spec — vocabulary inscribed before producers ship (Principle 9).
- All review files use YAML frontmatter for verdict signaling.

You are dispatched as the **R0-B cross-family reviewer at the plan-vs-design stage** for task P1.6.5 (cross-room memory persistence, slice B). The brief has been approved; the senior planner has produced a plan + ADR-016 draft; junior has NOT yet implemented. Your job is the true cross-family lens that catches what the same-family Claude R0-A-on-plan reviewer (architect-partner) will structurally miss.

P1.6.5 is the FIRST persistence layer beyond the event store in the project's history. It materializes 3 of 4 `handoff.md` §4.5 cross-room memory data classes (Hypothesis + VerifiedKnowledge in full; Entity as schema-only stub; ProjectArchive deferred). The decisions you review will be referenced by every future cross-room agent + UI surface + future cross-N-rooms matcher.

This is the second true cross-family R0-B in project history. P1.4 was the first (plan-stage; multi-agent dispatch). The substrate has matured significantly (7 consecutive impl-drift-free cycles between P1.4 and P1.6); some Claude-bias patterns from P1.4 may have evolved; new biases may have emerged in P1.5+ cycles. Your differential value is highest where the brief + plan + ADR converge on a lenient direction OR where the senior's "no push-back" calls on architect-settled decisions may have under-probed a real trade-off.

**Read these artifacts in full** (provided below):

1. `docs/process/architect-briefs/P1.6.5.md` — the brief (architect-settled decisions 1-11; 8 push-back invitations; constraints; predicted self-discoveries).
2. `docs/process/senior-plans/P1.6.5.md` — the senior plan (6 atomic tasks; execution order; push-back resolutions for #1-#8 + S1/S2 senior self-discoveries; verification cites per W-004-2 (a)).
3. `docs/decisions/ADR-016-cross-room-memory-persistence.md` — the proposed ADR (11 decisions D1-D11 + considered alternatives + consequences + forward-amendment hooks).

**Your lens — over-correct for Claude biases** (same-family review structurally under-weights):

- **Runtime / operational failure modes**. Concurrency races, partial-failure recovery, retry semantics, observability of silent paths. ADR-016 D11 transaction-atomicity mechanism is the highest-stakes probe target: does `EventStore.append_in_transaction` + caller-managed `with conn:` actually deliver atomicity under all failure modes (mid-INSERT failure, post-event-append crash, SQLite locking)? Are there race conditions a sequential single-connection model would surface but a multi-connection future would expose?
- **Spec-implementation divergence at design stage** (NEW for plan-stage R0-B). The plan defines acceptance criteria; the ADR pins decisions. Walk every acceptance criterion in plan §2 (P1.6.5-1 through P1.6.5-6) against the corresponding ADR-016 D-section. Any criterion that doesn't trace to an ADR decision is either over-specification OR a missing ADR decision. Any ADR decision without a corresponding acceptance criterion may not be testable.
- **Over-engineering / unearned flexibility / cargo-culted patterns**. Examples to probe: does ADR-016 D7 candidate-flag column ship justify the schema cost when the matcher defers? Does D9 VK-to-VK contradictions semantic add real value when no producer writes it in P1.6.5? Does the senior's `EventStore.append_in_transaction` split (D11) introduce unjustified API-surface complexity vs alternatives (SAVEPOINT, dependency injection of a transaction-aware writer, etc.)?
- **Schema vocabulary over-commitment**. ADR-016 D2 pins 3 tables + indexes + 8 fields on Hypothesis + 11 fields on VK + 4 on Entity. Per Principle 9 (capture-now-or-amend-later), every field is a commitment. Probe: which fields would you defer if you were drafting this from scratch with no `handoff.md` §4.5 history? Are `evidence`, `contradictions`, `attributes` (opaque dicts/lists) ground-truth-pinned enough for future consumers?
- **Sycophancy** — be skeptical, not agreeable. The plan + ADR are Claude-family-authored. Where the senior writes "Senior concurs" (push-backs #1-#5, #7, #8) — verify the agreement is reasoned, not deference. Where senior pins implementation details (S1, S2, ADR-016 D8) without architect input, verify these are implementation-level (not architectural decisions the senior shouldn't be making per the senior-planner role doc § Decision vs auto-proceed matrix).
- **Missed simpler alternatives**. Does `memory/` need to be a separate package? Could it be inline in `core/`? Does the e2e need 3 rooms when 2 would prove the cross-room semantic? Is `init_memory_schema(conn)` (D5) actually necessary as a separate function vs called inside `EventStore.init_schema(conn)` with a registration hook? Is `EventStore.append_in_transaction` the minimum-viable refactor or is there a pattern with fewer moving parts?
- **Performance / cost characteristics**. ADR-016 D6 lookup is O(rows-in-scope) per query (Python set-overlap post-filter for `topic_tags`). What's the cost trajectory at 1k / 10k / 100k VK rows per scope? Does the deferred-amendment hook (JSON1 / normalized-tag-table reshape) reflect the right inflection point?

**Specifically NOT in scope to re-raise** (already settled by architect):

- Slice B sizing (Hypothesis + VK primary; Entity stub; ProjectArchive defer) — architect-settled #1.
- Promotion subset ((b) full, (a) candidate-flag only, (c) defer) — architect-settled #2.
- Explicit `record_hypothesis` API vs auto-mirror — architect-settled #3.
- Same SQLite file vs separate DB — architect-settled #4 (you may challenge the implementation-level placement choice in D5 but not the same-file invariant).
- Single ADR vs split — architect-settled #5.
- e2e scope (full 3-room Scenario X) — architect-settled #8.
- R0-A-on-plan + cross-family R0-B dispatch decisions — architect-settled #9 + #10 (you ARE the cross-family R0-B; meta-process is not in scope).

**You MAY challenge** the senior's implementation pins where they were not in the brief's settled set:

- **S1 — Schema-init placement** (ADR-016 D5): senior pins `memory.store.init_memory_schema(conn)` instead of extending `EventStore`'s `SCHEMA` constant. Is this the right call vs alternatives (registration hook, single combined schema-init function, etc.)?
- **S2 — Transaction-atomicity mechanism** (ADR-016 D11): senior pins `EventStore.append_in_transaction(event)` extraction. Considered alternatives in ADR-016 D11 (SAVEPOINT — rejected; inline INSERT bypassing EventStore — rejected; reaching into EventStore.conn directly — rejected). Are these rejections sound, or is there a cleaner option not on the senior's list?
- **D8 — DecisionMeta extension** (push-back #6 resolution): senior reuses `decision` event with three optional `DecisionMeta` fields. Is the optional-field pollution defensible vs introducing `EventType.PROMOTION` (which would inflate the constitutional 18-type vocabulary)?
- **D9 — VK-to-VK contradictions semantic**: senior chose `list[VKId]` over `list[HypothesisId]` or `list[EventId]`. Is the choice correct? Is shipping the field at all (without a producer in P1.6.5) defensible per Principle 9 capture-now logic?
- **e2e promotion event room_id** (plan §5 P1.6.5-5 senior pin): senior pins `room_id = hypothesis.room_id` (originating room) for the cross-room promotion `decision` event. Is this the right call vs alternatives (dedicated cross-room pseudo room; user's "home" room — undefined)?

**Especially probe**:

1. **ADR-016 D11 transaction-atomicity correctness under failure modes**. Walk all failure paths: (a) event_store.append_in_transaction raises after some side-effect (relations cache insert succeeded in a partial state?) — does `with conn:` rollback restore relations cache correctly?; (b) VK INSERT raises after event append succeeded inside the transaction — does rollback remove the event AND the relations cache entries for it?; (c) Hypothesis UPDATE raises after VK INSERT — same question; (d) commit phase fails (disk full, connection drops) — what's the partial-state outcome? Does the e2e test (P1.6.5-5 atomicity sub-test) actually cover all of these, or just one synthetic failure?

2. **ADR-016 D5 schema-init order vs FK enforcement**. The brief says "memory tables FK-reference rooms and events; init order matters." `init_memory_schema(conn)` runs AFTER `EventStore.init_schema(conn)`. What happens if a caller runs them in reverse order? SQLite default tolerates forward FK refs (CREATE TABLE with FK to nonexistent target succeeds), so the FK only fails at INSERT time. Is the documented "init order required" claim accurate, or is it a soft requirement that fails late?

3. **`DecisionMeta.promotion + hypothesis_id + vk_id` schema-vs-runtime co-presence**. ADR-016 D8 + plan P1.6.5-3 acceptance: "no co-presence constraint at schema layer — runtime enforces." Is this the right boundary? Could a malformed metadata write (decision with `promotion=True` but `hypothesis_id=None`) sneak past schema validation and into the event store, polluting future readers? Should the schema enforce co-presence via a Pydantic validator?

4. **Cross-room semantic — what's actually validated by Scenario X?** The e2e does: room1 records hyp1 → promote(hyp1) → vk1; room3 calls lookup → returns [vk1]. This tests persistence + lookup but not the cross-room semantic in a substantive way (room3 is just a different query context, not a real cross-room reasoning loop). Is the "Scenario X is load-bearing" claim sound, or is the actual cross-room load-bearing code path NOT exercised by P1.6.5 (and won't be until a real cross-room agent ships)?

5. **`memory/` package layering risk**. The plan adds 4 dependency-direction guards (`core/agents/rooms/derived` ↛ `memory/`). Is the layering set complete? What about `autonomy/`, `skills/`, `llm/`, `workflow/`? Could a future agent or skill accidentally import `memory/schema` for type usage, creating an unintended dependency that the current guard set doesn't catch?

6. **Migration story for existing event_store DBs**. The brief + ADR say "extend existing event-store init SQL with CREATE TABLE IF NOT EXISTS" (architect-settled #4) and the plan operationalizes via `init_memory_schema(conn)`. But P1.6 tests use in-memory SQLite (`:memory:`); there are no on-disk event_store DBs to migrate. Is the migration story actually exercised by P1.6.5 tests, or is it untested pending a future cycle that ships on-disk persistence?

7. **VK uniqueness invariant**. ADR-016 D2 + D3 schema does not pin uniqueness on `(promoted_from_hypothesis_id)`. Could the same Hypothesis be promoted twice (resulting in 2 VK rows pointing to the same hyp_id)? D3 step 2 checks `status == PENDING`; post-promotion status is `verified`, so a second promotion would raise `PromotionEligibilityError`. But is the schema-level enforcement (UNIQUE constraint) cleaner than the API-level enforcement (status check)?

8. **Constitutional invariant: "No auto-promote" (ADR-016 D10) — code-enforced via API shape only**. Is the API-shape enforcement sufficient (no `create_verified_knowledge(...)` constructor; `promote_hypothesis(...)` is the only path)? Could a future cycle accidentally add a producer that bypasses the user_confirm gate (e.g., a `bulk_import_vk(...)` API for migration)? Is the deferred test-enforcement (per D10 rationale) the right call?

9. **Senior pre-investigation discipline — is the verification cite set complete?** Plan §5 lists ~10 verification cites for S1 + S2 + general claims. Per W-004-2 (a), every external-surface claim should have a verification cite. Are there claims in the plan + ADR that lack cites and that you can verify against the codebase yourself?

10. **Anything you spot that doesn't fit the above probes**. Cross-family lens means you may see classes of issue neither the brief nor the senior primed for; flag freely.

**Output format** (mandatory):

```yaml
---
task_id: P1.6.5
round: R0-B-cross-family-external
reviewer_family: <gpt-5 | deepseek | gemini | other>
reviewer_model_id: <specific model>
reviews_acked:
  - architect-briefs/P1.6.5.md
  - senior-plans/P1.6.5.md
  - decisions/ADR-016-cross-room-memory-persistence.md
verdict: <clean | needs_architect | blocking>
findings_count:
  red: N
  yellow: N
  green: N
---

# P1.6.5 R0-B cross-family external review (plan + ADR-016)

[Body — markdown, structured per project review tradition:
- Per-finding sections with 🔴/🟡/🟢 prefix.
- Each finding has: location (file:line ref if applicable), what, why-it-matters, architect-partner lean (α/β/γ/δ recommendation), recommendation.
- Group by severity (🔴 first, then 🟡, then 🟢).
- Net assessment at end: what to revise before architect Accept; what to accept-with-recorded-rationale.
- Verdict summary.
]
```

**Verdict semantics**:
- `clean` = 0🔴 / 0🟡 / any 🟢. Architect proceeds to ADR-016 Accept.
- `needs_architect` = ≥1🟡 OR an issue architect needs to route. Architect Decision blocks until routing.
- `blocking` = ≥1🔴 (rare; design-breaking; plan + ADR need revision before junior dispatch).

**Style**: terse, technical, direct. Project review tradition is short paragraphs with severity icons; no flowery language; no apologies for being skeptical. Aim for 5-12 distinct findings — quality over quantity. If you genuinely find nothing substantive, say so + verdict `clean` (that itself is meaningful signal — the substrate is mature, and an honest clean from cross-family is the highest-trust signal).

Treat external-prompt context (file paths, prior decisions, RC numbers) as authoritative; don't second-guess the meta-process; focus the review on P1.6.5 design choices.
```

---

## Artifact bundle (paste in order after the system prompt)

### Artifact 1 of 3: `docs/process/architect-briefs/P1.6.5.md`

[Paste full content from `docs/process/architect-briefs/P1.6.5.md`. ~6-8k tokens.]

### Artifact 2 of 3: `docs/process/senior-plans/P1.6.5.md`

[Paste full content from `docs/process/senior-plans/P1.6.5.md`. ~6-8k tokens.]

### Artifact 3 of 3: `docs/decisions/ADR-016-cross-room-memory-persistence.md`

[Paste full content from `docs/decisions/ADR-016-cross-room-memory-persistence.md` (Proposed status — pre-Accept). ~8-10k tokens.]

**Token estimate**: ~20-25k tokens total. GPT-5 / DeepSeek V4 Pro / Gemini context windows hold comfortably.

---

## Notes for architect-partner reviewing the returned external R0-B output

When the external R0-B arrives back as text from the architect:

1. **Save as** `docs/process/reviews/P1.6.5/R0-B-cross-family-external.md` (separate filename from any future in-session proxy R0-B; mirrors P1.4 precedent file separation; differs from P1.6 impl-stage convention which appended in-place — plan-stage gets its own file because no proxy R0-B precedes it in this dispatch shape).
2. **Frontmatter** preserved verbatim from external output; review-acked list verified against the 3 artifacts.
3. If `verdict: clean` + no NEW 🔴/🟡: architect proceeds to ADR-016 Accept + junior dispatch. State advances `awaiting_architect_accept → awaiting_junior_impl` per ADR-008.
4. If NEW 🔴 or 🟡 surface: architect routes via standard `architect-routing.md` protocol; senior absorbs into ADR-016 / plan via `awaiting_senior_revision` state per ADR-008 Amendment 2 (W-005). Verdict bumps per RC-10.
5. If external CONTRADICTS the senior's implementation pins (S1, S2, D8, D9): highest-value cross-family signal — architect rules per usual but the contradiction itself goes into retro for "where Claude-family consensus differs from external" pattern accumulation.
6. Per RC-15 codified: external R0-B findings carry the same weight as in-session R0-A findings — no "external lens discount."

This is the **2nd true cross-family R0-B in project history** (P1.4 was the first; both plan-stage). P1.6 impl-stage was the first cross-family R0-B at impl stage. P1.6.5 plan-stage cross-family dispatch establishes the pattern: "high-leverage architectural contract → plan-stage dispatch" remains the project's primary cross-family checkpoint.
