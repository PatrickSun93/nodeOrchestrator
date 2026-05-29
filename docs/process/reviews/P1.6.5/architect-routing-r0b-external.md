---
task_id: P1.6.5
kind: architect-routing (R0-B cross-family external / DeepSeek, plan stage)
date: 2026-05-29
reviews_acked:
  - R0-B-cross-family-external.md
decisions:
  Y7: α (b) (drop conn param from promote_hypothesis; use event_store.conn for all 3 writes — eliminates the conn≠event_store.conn atomicity invariant)
  Y8: confirms proxy Y3 (FK-timing acceptance-criterion error) — no new routing; folds into proxy Y3 α already in the pending senior absorption
  Y9: α (add UNIQUE to verified_knowledge.promoted_from_hypothesis_id)
  Y10: confirms proxy Y4 (layering-set incomplete) + REFINES the proxy-Y4 package set 4→3 (add autonomy/ + skills/ + llm/ ↛ memory; DROP workflow/ — dev-harness, outside the product layering universe)
  Y11: α (add on-disk migration test for init_memory_schema against a pre-existing event_store DB)
---

# P1.6.5 architect routing — R0-B cross-family external (DeepSeek) findings

**Architect decisions (this session):** the external (DeepSeek V4 Pro) R0-B reviewed the same baseline the proxy did (post-R0-A-absorption; the senior's proxy-routing absorption hasn't landed yet — architect chose current-state parallel dispatch over wait-for-revision). Result: **0🔴 / 5🟡 / 7🟢**, of which **4 confirm proxy findings** and **3 are net-new**. Y7 + Y9 + Y11 routed α; Y8 + Y10 are confirms (Y10 carries a package-set refinement). Y7 sub-option + Y9/Y11/Y10-set chosen by architect via architect-partner AskUserQuestion.

This file routes the external R0-B. It is distinct from `architect-routing.md` (R0-A-on-plan) and `architect-routing-r0b.md` (proxy R0-B). **Where it touches the proxy routing (Y10 → proxy Y4 package set), this file SUPERSEDES** — see Y10 below; the senior implements the refined 3-package set, not the proxy file's 4.

## Dual-lens result (synthesis)

DeepSeek **independently re-derived 4 of the 6 proxy findings without being told them** — strong validation of both the proxy lens (in-session Claude contrarian) and the plan:

| External finding | Maps to | Status |
|---|---|---|
| Y8 (FK-timing "raises" error) | **proxy Y3** | confirm — already α (pending absorption) |
| Y10 (layering set incomplete) | **proxy Y4** | confirm + package-set refinement (this file) |
| 🟢 "confirms proxy Y2 footgun" | **proxy Y2** | confirm — already α(b) |
| 🟢 "confirms proxy Y5 prefix gap" | **proxy Y5** | confirm — already α(a) |
| **Y7** (conn invariant) | — | **net-new** → α(b) |
| **Y9** (UNIQUE constraint) | — | **net-new** → α |
| **Y11** (migration untested) | — | **net-new** → α |

Proxy Y1 (grep miscount) + Y6 (keep contradictions) were not re-raised — Y1 is a cite/process matter the external wouldn't recount (it did spot-check cites in 🟢 G and found them accurate); Y6 the external explicitly agreed is a fair deferred concern (its probe-10 🟢). The external also affirmed (🟢): D11 `append_in_transaction` is the minimum-viable refactor (no simpler alternative missed), the D5 `init_memory_schema` layering choice is correct, the cross-room lookup is genuinely cross-room, and no sycophancy in the senior's push-back concurrences.

## Per-finding routing

### Y7 → α (b) — drop `conn` param from `promote_hypothesis`; derive from `event_store.conn`

**The finding (verified):** `promote_hypothesis(hyp_id, user_id, *, scope, topic_tags, evidence, conn, event_store)` (ADR-016 D11 lines 171-172) takes BOTH `conn` and `event_store`. D11 atomicity requires `conn is event_store.conn` — the `with conn:` wrapping `event_store.append_in_transaction(...)` + VK INSERT + Hypothesis UPDATE only shares one transaction if both objects share one connection. Nothing asserts this; a caller passing mismatched connections gets **silent atomicity loss** (event on one connection, VK/Hypothesis on another, two independent transactions, no error). Classic cross-family catch — same-family reviewers (R0-A G2, proxy G1) probed D11's nesting mechanics but accepted same-connection as obvious.

**Action (chosen mechanism (b) — eliminate, not guard):**
- `promote_hypothesis` signature drops the `conn` parameter:
  ```python
  def promote_hypothesis(
      hyp_id: HypothesisId,
      user_id: str,
      *,
      scope: VKScope,
      topic_tags: list[str] | None = None,
      evidence: dict[str, Any] | None = None,
      event_store: EventStore,
  ) -> VerifiedKnowledge:
      conn = event_store.conn   # single connection for all 3 writes — no mismatch possible
      with conn:
          event_id = event_store.append_in_transaction(decision_event)
          conn.execute("INSERT INTO verified_knowledge ...")
          conn.execute("UPDATE hypothesis SET status='verified' WHERE id=?", ...)
  ```
- ADR-016 D3 + D11: signature + transaction-sequence code blocks updated to drop `conn`; add a sentence — "the promotion writes all three rows on `event_store.conn`; there is no separate `conn` parameter, so the conn-mismatch atomicity hazard cannot arise."

**Why (b) over (a) guard:** (b) makes the invariant *unrepresentable* rather than *checked* — strictly safer, smaller surface, and aligns with architect-settled #4 (same SQLite file / same connection). The API stays coherent: memory-only ops (`record_hypothesis`, `lookup_verified_knowledge`) take a bare `conn`; the one op that also writes the event stream takes the richer `event_store` and derives the connection from it. (a) would keep the param for consistency but retain a guarded-not-eliminated hazard. Architect picked (b).

**Note for senior:** `EventStore` exposes `self.conn` (`core/event_store.py:164`); `event_store.conn` is the documented accessor. The e2e (P1.6.5-5) + promotion tests (P1.6.5-4) drop the `conn=` argument to `promote_hypothesis`.

### Y8 → confirms proxy Y3 (no new routing)

External Y8 ("init-order acceptance criterion factually wrong — SQLite tolerates forward FK refs at CREATE; enforcement is INSERT-time") is the **same finding** as proxy R0-B Y3, routed α at `architect-routing-r0b.md`. Independent cross-family re-derivation = strong confirmation the proxy Y3 fix is correct. No separate routing — the senior's pending absorption of proxy Y3 (ADR-016 D5 sentence → INSERT-time; P1.6.5-2 test asserts INSERT-time failure, not CREATE-time) resolves both. The external's suggested reword (its Y8 recommendation) is consistent with the proxy Y3 routed action; senior may use either phrasing.

### Y9 → α — add UNIQUE constraint to `verified_knowledge.promoted_from_hypothesis_id`

**The finding (verified):** ADR-016 D2 DDL (line 138) has `promoted_from_hypothesis_id TEXT NOT NULL` + FK, **no UNIQUE**. The API-level gate (`promote_hypothesis` checks `status == PENDING`, sets `verified`) prevents double-promotion in the single-writer model, but the schema doesn't enforce one-VK-per-Hypothesis. A future concurrent writer / bulk-import / buggy producer could create two VK rows for one Hypothesis.

**Action:**
- ADR-016 D2 DDL + plan P1.6.5-2 `_MEMORY_SCHEMA`: `promoted_from_hypothesis_id TEXT NOT NULL UNIQUE`.
- ADR-016 D3: note that double-promotion is prevented at two layers — API status-check (primary) + schema UNIQUE (defense-in-depth).
- P1.6.5-4 acceptance: +1 test — attempting to INSERT a second VK row with a duplicate `promoted_from_hypothesis_id` raises `sqlite3.IntegrityError` (schema-level backstop, independent of the status check).

**Why α (not β-defer):** greenfield table → one word, zero migration cost now; **cannot be added later without a table rebuild** (no migration tooling). Schema-level guarantee survives any future code path. Consistent with the project's cheap-now-vs-migrate-later bias (candidate-flag column; Y4 guards). Does not conflict with deferred cross-N-rooms promotion (which reshapes the hyp→VK relation entirely — a future amendment, not a slice-B concern). Architect picked α.

### Y10 → confirms proxy Y4 + REFINES the package set (4 → 3; supersedes proxy-Y4 routing)

External Y10 ("layering guard set incomplete") **confirms proxy R0-B Y4** (routed α at `architect-routing-r0b.md`). The routing decision — add the missing reverse-direction guards — stands. **What this file changes is the exact package set.**

**Verified:** `workflow/` imports zero product packages (`grep` of `src/orchestrator/workflow/` for product imports → empty); it is dev-harness with zero runtime coupling to product (CLAUDE.md § Scope). The existing `does_not_import` constitutional guards live only in product test dirs (`tests/{agents,core,rooms,skills}/`).

**Refined action (SUPERSEDES proxy-Y4's "add 4: autonomy/llm/skills/workflow"):**

Senior implements **3** new guards in P1.6.5-1, not 4:
- `tests/autonomy/test_constitution.py` — `test_constitution_autonomy_does_not_import_memory` (most plausible future violator per DeepSeek — autonomy scoring must not become a function of memory-query results; would breach handoff §3.1 code-driven-decisions).
- `tests/skills/test_constitution.py` — `test_constitution_skills_does_not_import_memory`.
- `tests/llm/test_constitution.py` — `test_constitution_llm_does_not_import_memory` (guards the anticipated-but-deferred LLM-augmented matcher/promotion path: an `llm/` → `memory/` import is exactly the future breach to forbid now).

Combined with the plan's existing 4 (`core/agents/rooms/derived`) → **7 guards = every PRODUCT package**. **`workflow/` is skipped** — dev-harness is outside the product layering universe; a `workflow/ → memory/` guard would be the first-ever product↔dev-harness constitutional guard, guarding a categorically-separate surface that imports no product code at all.

**Why drop workflow/:** the principled boundary is "guard the product layering invariant across product packages." `workflow/` is functionally separate (CLAUDE.md); adding it would be noise, not signal. DeepSeek's "workflow N/A (correct to skip)" is right; my proxy-Y4 routing's blanket "4" over-reached. Architect confirmed the 3-package refinement.

### Y11 → α — add on-disk migration test

**The finding (verified plausible):** ADR-016 D5 claims the migration story works (first `init_memory_schema(conn)` against a pre-P1.6.5 on-disk DB creates the 3 memory tables, leaves events/rooms/relations untouched). All P1.6.5 tests use `:memory:`; **no test exercises the on-disk extend-in-place path** the first real user hits.

**Action:** add one migration test (P1.6.5-2 `tests/memory/test_store.py`, or P1.6.5-5 if the senior prefers the integration suite):
1. on-disk temp DB → `EventStore(conn).init_schema()` only;
2. append a few rooms + events;
3. close connection; re-open;
4. `init_memory_schema(conn)`;
5. assert: 3 memory tables exist AND `events`/`rooms`/`relations` untouched (row counts preserved);
6. assert: `record_hypothesis` + `promote_hypothesis` work against the migrated DB.

~30 lines, one test function.

**Why α (over DeepSeek's own β-lean):** P1.6.5 **pins shared-DB-in-place-extend as the template** every future derived-but-persisted cache will copy (ADR-016 Consequences "the pattern becomes the template for any future derived-but-persisted cache"). An untested template that future cycles copy can propagate a latent bug; verifying it now while cheap is worth it, and it converts ADR-016 D5's untested *claim* into a *verified* one (W-004-2 (a)-adjacent discipline). DeepSeek leaned β (low risk; CREATE-IF-NOT-EXISTS is SQLite-tested) — reasonable, but the template-propagation argument tips α. Architect picked α.

## Combined second-revision shape (proxy + external, one revision)

The senior now absorbs **both** R0-B routings in a single 2nd revision commit on `claude/P1.6.5-plan`:

**From proxy routing (`architect-routing-r0b.md`):** Y1 α, Y2 α(b), Y3 α, Y4 α **(package set refined to 3 per external Y10 — implement autonomy/skills/llm, NOT workflow/)**, Y5 α(a), Y6 γ.

**From external routing (this file):** Y7 α(b), Y9 α, Y11 α. (Y8 folds into proxy Y3; Y10 is the Y4 refinement above.)

**ADR-016 amendments (union):**
- D2 DDL: `promoted_from_hypothesis_id TEXT NOT NULL UNIQUE` (Y9); FK-timing sentence → INSERT-time (proxy Y3 / ext Y8).
- D3 + D11: drop `conn` param from `promote_hypothesis`, derive from `event_store.conn` (Y7); double-promotion two-layer note (Y9); `append_in_transaction` entry guard (proxy Y2).
- D5: FK-timing (proxy Y3).
- D8: `str | None` + `@model_validator` (proxy Y1/Y3 — already?) + `Field(pattern=…)` prefix (proxy Y5).
- D9: keep-contradictions considered-and-declined (proxy Y6 γ).
- Forward-amendment hooks: +2 (proxy Y5 cross-N-rooms attribution + Y6 record_hypothesis atomicity).

**Plan amendments (union):**
- §4/§5 grep: 5→6 callers, name `rooms/runtime.py:103`, correct "Layering clean" (proxy Y1).
- P1.6.5-1: +3 dependency-direction guards — autonomy/ + skills/ + llm/ (Y10 refined; NOT workflow/).
- P1.6.5-2: `append_in_transaction` raise-guard + test (proxy Y2); FK init-order test → INSERT-time (proxy Y3 / ext Y8); UNIQUE-constraint backstop test (Y9); on-disk migration test (Y11); +`tests/rooms/` to behavior-preserve set (proxy Y1).
- P1.6.5-3: prefix-pattern tests (proxy Y5).
- P1.6.5-4: `promote_hypothesis` drops `conn` param + tests updated (Y7); double-promote IntegrityError test (Y9).
- P1.6.5-5: e2e drops `conn=` from promote call (Y7).
- P1.6.5-6: test-delta expectation bumps.

**Verdict bumps (RC-10):** senior bumps BOTH `R0-B-cross-family.md` (proxy) AND `R0-B-cross-family-external.md` (external) frontmatter `needs_architect → clean` at the 2nd revision commit. 13th + 14th project use of RC-10 verdict-bump.

## Path to Accept

After the 2nd revision lands (both R0-B files clean, R0-A already clean): **ADR-016 Proposed → Accepted is the architect's call**, then plan + ADR merge to main and state advances `awaiting_senior_plan → awaiting_junior_impl` (single-ADR path per ADR-008 D2). No third review round is required unless the architect wants one — the dual-lens plan-stage gate is complete (R0-A + proxy R0-B + external R0-B all run; all findings routed).

## Pattern-recurrence notes (retro candidates)

- **Dual-lens independent-confirmation rate: 4 of 6 proxy findings re-derived by an external family** (DeepSeek confirmed proxy Y2/Y3/Y4/Y5; missed Y1-cite + Y6-deferred which are non-runtime). This is the **strongest single data point yet for RC-15 dual-lens economics** — it directly answers "is the in-session proxy lens trustworthy enough to lean on, or does it need the external?" Answer this cycle: the proxy caught real issues the external independently confirmed, AND the external added 3 net-new (Y7/Y9/Y11) the proxy missed → **both lenses paid for themselves; neither is redundant.** Candidate for the P1.6.5 retro (dual-lens-r0b.md economics evidence).
- **Cross-family caught the canonical cross-family class:** Y7 (silent same-connection assumption) is the textbook "invariant the same-family reviewer accepts as obvious." First clean instance in P1.6.5 of the external lens earning its dispatch on a runtime-correctness gap (not just cite/completeness). Reinforces RC-15 dispatch-on-high-leverage-contract.
- **Proxy over-reach corrected by external:** my proxy-Y4 routing said "4 guards incl workflow/"; external Y10 + verification corrected to 3 (product-only). Minor, but a data point that architect-partner routing leans benefit from the second lens too — the synthesis caught my own over-reach.
- **Second cycle running the "α-with-sub-option via AskUserQuestion" pattern** (now proxy Y2/Y5/Y6 + external Y7/Y9/Y11/Y10 = 7 sub-option/judgment calls across two routings in one cycle). The codification candidate flagged in `architect-routing.md` is now well-supported; recommend a `senior-planner.md` / role-doc note on routing-sub-option capture at the P1.6.5 retro.

## Cross-references

- `docs/process/reviews/P1.6.5/R0-B-cross-family-external.md` — external (DeepSeek) findings Y7-Y11 + 7🟢.
- `docs/process/reviews/P1.6.5/R0-B-cross-family.md` — proxy R0-B (Y1-Y6); external confirms 4 (Y2/Y3/Y4/Y5).
- `docs/process/reviews/P1.6.5/architect-routing-r0b.md` — proxy routing (α α α α α γ); **this file supersedes its Y4 package set (4→3)**.
- `docs/process/reviews/P1.6.5/architect-routing.md` — R0-A-on-plan routing (immutable).
- `docs/decisions/ADR-016-cross-room-memory-persistence.md` — D2 (Y9 UNIQUE) + D3/D11 (Y7 drop-conn) + D5 (Y8/proxy-Y3) amended.
- `docs/process/senior-plans/P1.6.5.md` — P1.6.5-1 (Y10 3-guard set) + P1.6.5-2 (Y8/Y9/Y11) + P1.6.5-4/-5 (Y7) amended.
- `docs/process/dual-lens-r0b.md` RC-15 — dual-lens economics; this cycle's 4/6 confirmation rate is evidence.
- `docs/process/reviews/README.md` § RC-10 — both R0-B files bump at the 2nd revision.
- Verified runtime/schema cites: `promote_hypothesis` conn+event_store params (ADR-016 D11 L171-172, Y7); no UNIQUE on promoted_from_hypothesis_id (ADR-016 D2 L138, Y9); `workflow/` imports zero product packages + existing guards in product test dirs only (Y10).
