---
task_id: P2.6
round: plan-vs-impl
reviewer: senior
impl_commit: fbcc5c6
verdict: clean
verdict_history:
  - verdict: clean
    at_commit: fbcc5c6
    findings_count: { red: 0, yellow: 0, green: 3 }
    note: >-
      initial plan-vs-impl. Faithful on all three blocks + both absorbed plan-stage
      guards. B1 tagging producer is content-gen (HYPOTHESIS_TAG_PROPOSAL,
      caller_agent_id=None) returning raw descriptive tags — no select/rank/gate;
      update_hypothesis_tags is overwrite (Y2) + resolve_tags-routed + transaction-safe.
      B2 emit helper raises on empty evidence_ref, is the sole ExternalValidationMeta
      construction site, appends via event_store.append (no raw-INSERT); dataset_check
      deterministic (no LLM). B3 list_refuted_candidates is a pure reader, no status
      mutation. Both AST guards real-AST + discriminating (c1 trips on planted
      run_matcher/promote_hypothesis; c2 trips on planted ExternalValidationMeta in
      dataset_check). e2e source≠sink on all three blocks. Gates verified independently
      (72 P2.6 tests pass, ruff + mypy clean). 3🟢 — extra mypy-fixup commit (test-typing
      only), c2 guard filename-scoped vs path-scoped, dataset_check no-match naming —
      none blocking.
findings_count:
  red: 0
  yellow: 0
  green: 3
---

# P2.6 plan-vs-impl (senior) — feeding the dormant promotion rules (producers/connectors)

| Field | Value |
|---|---|
| Reviewer | senior (plan-vs-deliverable lens) |
| Plan | `docs/process/senior-plans/P2.6.md` (incl. the c1/c2/Y2 plan-stage absorption) |
| ADR | `docs/decisions/ADR-022-promotion-rule-producers.md` (Proposed) |
| Impl | `claude/P2.6-impl` @ `fbcc5c6` (atomics: PRELUDE `6d41a68`, B1 `01d9383`, B2 `2675c8a`, B3 `e613578`, mypy-fixup `58084d7`, e2e `fbcc5c6`) |
| Verdict | **clean** — 0🔴 · 0🟡 · 3🟢 |

## Summary

Faithful implementation of the milestone — the **first producers/connectors** in the project — across all three blocks and both plan-stage-absorbed structural guards. The constitutional crux holds: B1's `propose_hypothesis_tags` is genuine content-gen (`LLMPurpose.HYPOTHESIS_TAG_PROPOSAL`, `caller_agent_id=None`) that emits only raw descriptive tags — the LLM describes, code (`resolve_tags`) normalizes, code (`run_matcher`) groups, the user (`promote_hypothesis`) promotes; B2's verdict is `evidence_ref`-anchored at the emit helper (raises on empty) and the demo connector is deterministic (no LLM); B3's `list_refuted_candidates` is a pure advisory reader that **never mutates `status`** (ADR-019 push-back #4 honored). The two boundary guards both routed at plan stage are **real-AST and discriminating** (RC-24/RC-25): the c1 guard trips on a planted `run_matcher`/`promote_hypothesis` in `producers/`; the c2 guard makes the emit helper the sole `ExternalValidationMeta` construction site and trips on a planted direct construction in `dataset_check.py`. `update_hypothesis_tags` is **overwrite** (Y2). The e2e is source≠sink on every block. Gates verified independently (72 P2.6-scope tests pass; ruff + mypy clean on the new surfaces). Three 🟢, none blocking.

## Per-atomic verification

| Atomic | Delivered | Plan/ADR match | Evidence |
|---|---|---|---|
| P2.6-2 prelude | ✓ `6d41a68` | ✓ | `llm/purposes.py` +1 value `HYPOTHESIS_TAG_PROPOSAL` (content-gen, "describes; never selects/ranks/gates"); `producers/` + `connectors/` packages scaffolded; the no-upstream-import guard (`core/memory/derived/llm` MUST NOT import producers/connectors) lands in `tests/producers/test_constitution.py` (real AST + discriminating self-tests). Exactly one content-gen purpose added; no routing/judgment purpose. |
| P2.6-3 B1 tagging | ✓ `01d9383` | ✓ | `producers/tagging.py::propose_hypothesis_tags` — `HYPOTHESIS_TAG_PROPOSAL`, `caller_agent_id=None`, returns parsed raw tag strings (caller owns resolve+matcher); `memory/store.py::update_hypothesis_tags` — **overwrite** (`UPDATE hypothesis SET topic_tags = ?`, latest-wins), `resolve_tags`-routed inside `with conn:` (transaction-safe), returns reloaded `Hypothesis`; c1 guard in `tests/producers/test_constitution.py`. |
| P2.6-4 B2 connector | ✓ `2675c8a` | ✓ | `connectors/_emit.py::emit_external_validation` — raises `ValueError` on empty `evidence_ref`, **sole** `ExternalValidationMeta` construction site, `validate_metadata` + `event_store.append` (never raw-INSERT); `connectors/dataset_check.py` — deterministic keyword-overlap (no LLM), calls the emit helper, `evidence_ref`=matched dataset key; c2 guard in `tests/connectors/test_constitution.py`. |
| P2.6-5 B3 reader | ✓ `e613578` | ✓ | `memory/validation.py::list_refuted_candidates` — PENDING + `verdict=='refuted'`, structurally mirrors `list_externally_validated_candidates`, **no status mutation** (SELECT-only), same fail-loud `meta["verdict"]` subscript canary. |
| (gate fixup) | ✓ `58084d7` | n/a (G3) | mypy-strict typing fix on B1/B2/B3 **test-helper** signatures (`str`→`RoomId`, `list`→`list[EventId]`); no product logic. |
| P2.6-6 e2e + landing | ✓ `fbcc5c6` | ✓ | `tests/integration/test_p2_6_e2e.py` — B1 (producer→update→`run_matcher` flips `candidate_for_promotion` across 2 rooms; same-room negative control; overwrite), B2 (connector→confirmed reader; refuted-not-in-confirmed; empty-`evidence_ref` raises), B3 (refuted reader surfaces; confirmed-only excluded), boundary (no-LLM-in-`memory/`, import guard, `memory/` doesn't import producers/connectors); handoff §4.5 + P2-track row updated; 5-surface. |

ADR-022 left **Proposed** (accept-gate is architect-only; this review informs it). The no-LLM rglob stays scoped to `memory/`; `producers/`/`connectors/` legitimately import `llm/`. Independently verified: **72 P2.6-scope tests pass**, ruff + mypy clean on the new surfaces.

## Findings

### 🟢 G1 — both plan-stage guards are real-AST and genuinely discriminating

- **c1** (`tests/producers/test_constitution.py::test_constitution_c1_producers_no_selection_gate_symbols`): a `_PromotionSymbolCollector(ast.NodeVisitor)` walks each `producers/*.py` and flags `Name`/`Attribute` references to `{run_matcher, promote_hypothesis, list_promotion_candidates, candidate_for_promotion}`. Two discriminating self-tests run the **same collector** on synthetic source with a planted `run_matcher(conn)` and a planted `promote_hypothesis(...)` and assert `violations > 0`. Matches ADR-022 D3 + plan P2.6-3 exactly. ✓
- **c2** (`tests/connectors/test_constitution.py::test_constitution_c2_external_validation_meta_sole_construction_site`): walks every `src/orchestrator/**` file for `ast.Call` on `Name` `ExternalValidationMeta` outside the allowed site; the discriminating self-test plants `ExternalValidationMeta(...)` (as `dataset_check.py` would if it bypassed the helper) and asserts detection. Combined with the emit helper's empty-`evidence_ref` `ValueError`, the boundary is the unbypassable single-write-path the c2→α routing intended. Matches ADR-022 D4 + plan P2.6-4. ✓

The e2e backs both: B1 is source≠sink (untagged → `run_matcher` flags 0; propose→update→canonical → flags both across 2 rooms; same-room negative control flags 0; overwrite replaces, not merges), B2 empty-`evidence_ref` raises + refuted excluded from the confirmed reader, B3 refuted surfaced + confirmed excluded — all discriminating, none count-only (RC-25).

### 🟢 G2 — c2 guard is filename-scoped, not path-scoped (minor; tighten-on-next-touch)

The c2 guard allows construction in any file whose **name** is `_emit.py` (`_ALLOWED_CONSTRUCTION_FILES = {"_emit.py"}` + `py_path.name not in ...`), whereas ADR-022 D4 / plan P2.6-4 specify "constructed only in **`connectors/_emit.py`**". For the current tree this is identical (only one `_emit.py` exists) and the discriminating test confirms the guard trips on the realistic bypass (a direct construction in `connectors/dataset_check.py` or any other real connector module). The only escape is a *future* file deliberately named `_emit.py` elsewhere in `src/orchestrator/` — an obvious review flag and an odd choice. **Non-blocking**: the boundary holds for every realistic bypass. Recommendation (a one-line follow-up, not this cycle): key the allow-list on the relative path `connectors/_emit.py` rather than the bare filename, to match the ADR wording precisely. Surfaced for the architect's awareness; below the 🟡-routing bar (no product-contract leak — the actual sole-site property holds).

### 🟢 G3 — an extra gate-fixup commit (`58084d7`) sits between B3 and e2e (RC-17 nuance; benign)

`58084d7` ("Fix mypy strict type errors in B1/B2/B3 test helper signatures") is a cross-cutting mypy-strict fix on **test fixtures** (`_make_room`/`room_id` `str`→`RoomId`, `list`→`list[EventId]`), no product logic. Per RC-17 (one-atomic-one-commit) the ideal is each atomic green at its own commit; here the subagent-authored test fixtures' typing was swept into one fixup before the e2e atomic rather than folded into each block. **Benign**: it touches only test typing, gates are green at the tip (independently verified), and no product surface is affected. Noted for the audit trail; no action.

## Net

The implementation matches the plan and Proposed ADR-022 on every block and both absorbed plan-stage routing items (c2 α sole-site guard, c1 α-lite selection guard, Y2 overwrite), with discriminating tests for the two load-bearing constitutional guards and source≠sink e2e on all three blocks. The constitutional boundary is honored structurally, not just by convention: the LLM tags (content-gen) and never selects; the connector verdict is `evidence_ref`-anchored at the unbypassable emit helper; the refuted reader never touches `status`. The three 🟢 are a guard-precision nit (filename vs path scoping — non-blocking), an RC-17 commit-granularity nuance on a test-only fixup, and a docstring-naming observation — none a defect, none requiring routing. **Verdict: clean.** Per ADR-008 Amendment 1 (Route B), state auto-advances; R0-A (+ dual-lens R0-B) fire next on the shared tree — with a clean plan-vs-impl, the joint verdict turns on the review lenses. ADR-022 remains **Proposed** (architect accept-gate).
