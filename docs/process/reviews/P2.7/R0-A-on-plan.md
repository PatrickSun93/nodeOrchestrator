---
task_id: P2.7
round: R0-A-on-plan
verdict: needs_architect
findings_count:
  red: 0
  yellow: 2
  green: 11
verdict_history:
  - verdict: needs_architect
    at_commit: b564633
    findings_count: { red: 0, yellow: 2, green: 11 }
    note: initial R0-A-on-plan (in-family). Exceptional plan — every named check (c1 S2 routing-is-code, c2 S3 security, S1 scaffold-SM, RC-23-safe amendments, split, Q1-Q5) verifies clean; the S1 halt-and-resurface (param-consumption already shipped → architect re-pin) is a process win. Two architect-confirm-at-accept 🟡 beyond the checks — Y1 (S2 cost_ceiling keeps unknown-cost models = soft ceiling) + Y2 (split-into-4-full-lifecycles re-derives brief/plan already done here). Neither blocking.
---

# P2.7 R0-A on plan (architect-dispatched pre-impl review, in-family)

| Field | Value |
|---|---|
| Round | R0-A-on-plan (architect-dispatched per RC-9; in-family) |
| Artifacts | `senior-plans/P2.7.md` + `ADR-023` (Proposed) + the ADR-002 + ADR-012 **amendments** vs `origin/main` substrate + brief P2.7 |
| ADR status | ADR-023 left **Proposed**; ADR-002/ADR-012 amendments left **Proposed** — this review informs accept; I did not accept (architect-only). |
| Cross-family | `requires_cross_family_review: true` — dual-lens R0-B on S2/S3 runs after me; I leave the tree clean. |

## Verdict: needs_architect

**This is the strongest plan I've reviewed this cycle — every check the dispatch named verifies clean against the actual artifacts.** c1 (S2 override is deterministic code) and c2 (S3 alt-backend security) are pinned with structural enforcement; the two closed-ADR amendments are RC-23-safe; S1 was **halted-and-resurfaced** correctly (the senior found the param-consumption interpretation already shipped in P1.5, halted rather than plan a no-op, and the architect re-pinned S1 to scaffold-buildout — a textbook surface-don't-improvise). I verified the substrate (router.py:15 "zero LLM calls", `_next_scaffold_state` always-None, `ANTHROPIC_BASE_URL` absent in `claude_code_cli.py`, no `main.py`, `config_loader.py` coupling) — all the plan's §7 self-discoveries are accurate.

**Two 🟡, both architect-confirm-at-accept, neither blocking, neither constitutional:** Y1 — S2's `cost_ceiling` **keeps** unknown-cost models (a *soft* ceiling); confirm that's the intended cost-governance semantic vs fail-closed (hard ceiling). Y2 — the split realizes as **4 full ADR-008 lifecycles** (brief→plan→ADR→impl…), which re-derives a brief + plan per sub-slice for designs **already** impl-ready in *this* plan + ADR-023 + the amendments; confirm the split granularity (impl-level vs full re-plan).

## The six named checks

| # | Check | Verdict | Evidence |
|---|---|---|---|
| 1 | **c1 (S2)** Layer-4 override deterministic code: pure fn, zero LLM in selection, structural test (spy `.call`==0 + AST guard), composes Layer-3, no new routing `LLMPurpose` | **clean (G1)** | `apply_global_override(chain, override, models) -> chain` pure fn over **static** `ModelProfile` attrs (ADR-023 D2); `test_constitution_override_path_makes_no_llm_call` = spy provider asserts `.call`==0 across all tier/ceiling combos + AST guard (D3); composes via the existing `select_model_and_provider` loop (Layer-3 filters unchanged, D2); **no new `LLMPurpose`** (D3, verified taxonomy content-gen-only). Foundation verified: `router.py:15` "zero LLM calls." |
| 2 | **c2 (S3)** alt-backend opt-in + fail-closed allowlist; `api_key_env` (no inline); allowlist in-provider | **clean (G2)** | `base_url: str\|None=None` (unset = Anthropic, D4); fail-closed `trusted_base_urls` — set-and-∉-list (incl. empty) ⇒ `ConfigError` at startup (D5, discriminating §5 test); `api_key_env` indirection, never inline (D6); allowlist validated **in-provider** (senior fork — keeps S3 off `config_loader.py`, preserving the split's disjointness). Trust tier documented vs the local r0b proxy (D6). |
| 3 | **S1** scaffold transition tables = pure code decision; ADR-012 amendment RC-23-safe | **clean (G3)** | ADR-012 amendment (line 477+) pins 4 state sets (BugFix/CodeReview/IdeaValidation 5-state, FreeChat 3-state) + per-arc transition tables + `rule_matched` traces (Q2); each arc a **pure code** match on `room.state`+`current_event.type` → `_guard_valid_state` (no LLM); `setup`+`closed` preserved (backward-compat); `SUMMARY_SNAPSHOT` universal close. Amendment marked **Proposed** (RC-23-safe). |
| 4 | ADR-002/ADR-012 amendments RC-23-safe (no literal `Status: Accepted` substring) | **clean (G4)** | ADR-023: only `Status: Proposed` (grep clean — no `status: accepted`). ADR-002 + ADR-012: amendments appended as `## Amendments` → `### 2026-06-02 (…) — **Proposed** (awaiting architect accept)` — **not** "Status: Accepted"; the originals' accepted headers are their own legitimate status. ADR-023 HR#6 explicitly states the RC-23-safety intent. |
| 5 | split structure (P2.7a-d + wave orchestration) reasonable | **sound (G6); Y2 (granularity)** | P2.7a(S1)/b(S2)/c(S3)/d(S4); **Wave 1** a∥b∥c (file-disjoint concurrent), **Wave 2** d-last (sequenced after b+c merged — `config_loader.py` + allowlist errors); dual-lens b+c only; ADR-024-for-S3 fork flagged. Sound. **Y2: the "4 full lifecycles" granularity re-derives brief/plan — see finding.** |
| 6 | contributing Q1–Q5 | **clean (G7)** | Q1 (no LLM judgment; no new `LLMPurpose`); Q2 (S1 `rule_matched`, S2 override-filter reason in `decision_trace`); Q3 (5-surface per sub-item); Q4 (6-cat at PR); Q5 (discriminating per sub-item — ceiling drops the would-be-selected model, untrusted URL raises, wrong event no-transition, message-content asserted). |

## Findings

### Y1 🟡 (low) — S2 `cost_ceiling` keeps unknown-cost models (a *soft* ceiling); confirm the governance semantic

ADR-023 D2: the `cost_ceiling_per_1m_output` filter drops a candidate only when its `ModelProfile.cost_per_1m_output` is *known and strictly greater* than the ceiling; **a model with `cost_per_1m_output is None` (unknown cost) is KEPT** (the ADR reasons: dropping unknown-cost would be "surprising for a cost dial"). The tradeoff: for a cost-**governance** dial (the S2 crux feature), a soft ceiling means an unknown-cost model **can exceed the budget and still be selected** — the ceiling isn't a hard guarantee. The choice is deterministic + documented + reasoned either way (so **not constitutional** — both keep and drop are code rules); it's a *semantic* call worth the architect's eyes since S2 is the governance crux. **Lean (surface):** confirm soft-ceiling (keep-unknown) is intended, **or** fail-closed (drop-unknown = hard ceiling) for a true budget guarantee — possibly with the `decision_trace`/startup error noting "kept N models of unknown cost" so the softness is visible. Architect's call; low.

### Y2 🟡 — the split realizes as 4 full lifecycles, re-deriving brief/plan already done in this plan

The architect ruled "split" (decision a); the plan realizes it (§3) as **"init 4 tasks, each a full ADR-008 lifecycle (brief→plan→ADR→impl→R0-A/R0-B→plan-vs-impl→merge)."** The ADRs are correctly **shared** (ADR-023 umbrella + the amendments — not re-derived per task, §3). But a **brief + plan** per sub-slice would re-state design that is **already impl-ready here**: S1's state sets/arcs are pinned in the ADR-012 amendment; S2/S3/S4's contracts are pinned in ADR-023 D1–D8; this plan §2 gives per-sub-item acceptance. So 4 fresh briefs + 4 fresh plans largely duplicate completed work (+ 4× the brief/plan process overhead). The split's *value* (independent mergeability + scoped dual-lens) is achievable with a lighter structure. **Lean (surface):** realize the architect-ruled split at the **impl level** — 4 parallel impl tasks consuming *this* plan + ADR-023 + the amendments (impl→R0-A/R0-B→plan-vs-impl→merge), skipping per-sub-slice brief/plan re-derivation (none of the four needs fresh design — all are pinned). If the architect prefers full lifecycles, this P2.7 plan becomes a meta-plan the sub-slices thin-pointer to (state that explicitly). **Architect rules the split granularity at accept** (it has real overhead/duplication implications); the wave orchestration (Wave 1 a∥b∥c, Wave 2 d-last) is sound either way.

## What holds — verified clean (G1–G11)

- **G1 — c1 (S2) structurally enforced** (pure fn + spy/AST no-LLM test + Layer-3 composition + no new purpose; router-zero-LLM foundation verified).
- **G2 — c2 (S3)** opt-in + fail-closed allowlist + `api_key_env` no-inline + in-provider validation.
- **G3 — S1** scaffold transition tables: pure code, decision-traced, backward-compat-preserving, discriminating per-arc.
- **G4 — RC-23-safe**: ADR-023 only `Status: Proposed`; both amendments appended + marked `Proposed`; HR#6 states the intent.
- **G5 — amendment format**: cleanly appended `## Amendments` sections (not rewriting the originals), dated, content matches ADR-023/the design.
- **G6 — split + wave orchestration sound** (Wave 1 a∥b∥c disjoint; Wave 2 d-last sequenced; dual-lens b+c; ADR-024 fork flagged) — modulo the Y2 granularity.
- **G7 — Q1–Q5** all addressed (Q2 decision_trace present; Q5 discriminating, no count-only).
- **G8 — honest parallelism**: the plan adopts + sharpens the brief's "partial parallelism" (`config_loader.py` coupling → S4-last), didn't oversell a clean four-way.
- **G9 — the S1 halt-and-resurface** (param-consumption already shipped → halt → architect re-pin) is a process win, transparently recorded in the ADR-012 amendment note.
- **G10 — substrate verified**: router.py:15 zero-LLM, `_next_scaffold_state` always-None, `ANTHROPIC_BASE_URL` absent in `claude_code_cli.py`, no `main.py`, `config_loader.py` hub — every §7 self-discovery accurate.
- **G11 — composition + fail-loud**: S2 composes with Layer-3 (never bypasses; empty-chain → `NoSuitableModelError` fail-loud); S3 fail-closed; S4 fail-loud-accumulate (ADR-002 D5).

## What I did NOT do

- Did not accept ADR-023 / the amendments (architect-only).
- Did not decide Y1 (ceiling semantic) or Y2 (split granularity) — both surfaced with a lean for the architect's accept-time call; neither is constitutional or blocking.
- Did not touch the tree beyond this review file (r0b dual-lens R0-B on S2/S3 runs next on the shared tree).
