---
task_id: P2.6
round: R0-A
verdict: needs_architect
findings_count:
  red: 0
  yellow: 1
  green: 10
verdict_history:
  - verdict: needs_architect
    at_commit: fbcc5c6
    findings_count: { red: 0, yellow: 1, green: 10 }
    note: initial R0-A (impl-stage, in-family). Gates FULLY green incl. mypy --strict (169 files, canonical files=[src,tests] — P2.5 R1 lesson learned). Both c1+c2 AST guards PROVEN discriminating on real-source planted bypasses. Constitutional boundaries clean + structurally enforced; B3 advisory no-status-mutation; e2e discriminating; Y2-overwrite absorbed. Y1 (architect-relevant) — the tagging producer's LLM-call pattern (async + provider-direct + Any) deviates from the established sync-typed-router convention (agents/dispatch + reentry); as the FIRST producer it sets the pattern. Nothing blocking.
---

# P2.6 R0-A (impl-stage, in-family)

| Field | Value |
|---|---|
| Commit reviewed | `fbcc5c6` (`origin/claude/P2.6-impl` tip; atomics P2.6-2..6) |
| ADR | ADR-022 **Accepted** (PR #37 merged); plan-stage c2+c1 guards + Y2-overwrite α-absorbed |
| Reviewed in | isolated git worktree at `fbcc5c6` |
| Gates (run in worktree) | **ALL green** — ruff ✓ · ruff-format ✓ (169 files) · **`mypy` (canonical `files=[src,tests]`) ✓ (169 files)** · pytest ✓ |

## Verdict: needs_architect

**Strong impl — and notably, the P2.5 R1 lesson landed: `mypy --strict` is green** (the junior's `58084d7` "fix mypy" commit; the canonical `uv run mypy` passes 169 files). The constitutional boundaries are clean **and I verified the guards actively, not by inspection**: I planted real-source bypasses and confirmed **both** AST guards fail — c1 caught `run_matcher` in `producers/tagging.py` (line 80), c2 caught `ExternalValidationMeta(...)` in `connectors/dataset_check.py` (line 52); both pass after revert. B1 tagging is content-gen (descriptive, no matcher/promotion symbols); B2's verdict is `evidence_ref`-anchored (the emit helper raises on empty, is the sole construction site, appends via `EventStore.append`); B3 is a pure advisory reader (no status mutation); the e2e is discriminating (positive + negative per block); Y2-overwrite is absorbed + tested.

**One 🟡, architect-relevant (Y1).** The tagging producer's LLM-call pattern deviates from the project's established **sync, typed `LLMRouterProtocol`** convention (agents/dispatch + reentry) on three axes — it's `async`, calls the **provider** directly (not the router), and types it `Any`. As the **first producer**, it sets the producer-LLM-call pattern, so the deviation warrants a deliberate call. Nothing blocking.

## The five named checks

| # | Check | Verdict | Evidence |
|---|---|---|---|
| 1 | B1: LLM emits only descriptive tags (content-gen), never select/rank/gate; new `LLMPurpose` content-gen | **clean (G1); Y1 (call-pattern)** | `propose_hypothesis_tags` builds a content-gen request (`HYPOTHESIS_TAG_PROPOSAL`, verified content-gen + no routing/judgment purpose), parses to raw descriptive tags; references **no** `run_matcher`/`promote_hypothesis`/`candidate_for_promotion` (c1 guard enforces). Per-hypothesis tagging structurally prevents cross-hypothesis selection. **Y1: the LLM *call mechanism* (async/provider-direct/Any) deviates — see finding.** |
| 2 | B2: connector verdict `evidence_ref`-anchored (required+non-empty); `EventStore.append`, not raw-INSERT | **clean (G2)** | `emit_external_validation` raises `ValueError` on empty `evidence_ref` (`_emit.py:61`), constructs the meta (sole site) + `validate_metadata` + `event_store.append` (never raw-INSERT). Demo connector `dataset_check` is deterministic (keyword-overlap, no LLM), calls the emit helper (never constructs the meta directly), sets `evidence_ref` to the matched key. |
| 3 | **Both AST guards discriminating on a planted bypass (not vacuous, Q5)** | **clean (G3) — actively proven** | **Planted & confirmed:** c1 — `run_matcher` in `producers/tagging.py` → guard FAILED (`line 80: forbidden Name 'run_matcher'`); c2 — `ExternalValidationMeta(...)` in `dataset_check.py` → guard FAILED (`line 52: …outside allowed site`); both PASS post-revert. Plus the shipped synthetic self-tests + the 4-layer no-upstream-import guard. |
| 4 | B3 refuted advisory, no status mutation (ADR-019 push-back #4) | **clean (G4)** | `list_refuted_candidates` (`validation.py:62`) is a pure SELECT reader mirroring the confirmed reader (verdict=='refuted'); **no UPDATE / no status mutation**; e2e asserts status stays PENDING + the confirmed reader excludes it. User-confirm reject actuator deferred. |
| 5 | decision_trace (Q2) / 5-surface (Q3) | **clean (G6)** | Q2 N/A — no new decision function (producers feed the *existing* deterministic rules; tagging is content-gen, emit/reader are write/read). Q3 — handoff updated (producers/connectors materialized; 5-surface). Q1 (only LLM is content-gen tagging; demo deterministic) + Q5 (e2e discriminating, positive+negative per block) also clean. |

## Findings

### Y1 🟡 — the first producer's LLM-call pattern deviates from the established sync-typed-router convention (architect-relevant; pattern-setting)

`propose_hypothesis_tags` (`producers/tagging.py:47`) calls the LLM as:
```python
async def propose_hypothesis_tags(..., *, llm_provider: Any, model: ModelProfile | None = None):
    response = await llm_provider.call(request, effective_model, model_id_requested=...)
```
This deviates from the project's two prior LLM-consumer surfaces on **three axes**:
- **(a) async vs sync.** `agents/dispatch.py` and `reentry/render.py` (P2.5) both use a **sync** `llm_router.call(request)`; `dispatch.py:48` explicitly notes the project has "no async color … P1.5+ re-shapes to async when concurrent dispatch lands" — which hasn't happened. The tagging producer introduces `async` **unilaterally**, ahead of the project-wide reshape (ADR-011 D1 sync posture).
- **(b) provider-direct vs router.** It calls the **provider** (`llm_provider.call(request, model, *, model_id_requested=…)` — the async `LLMProvider` signature) directly, bypassing the **router** (`LLMRouter`) that agents + reentry use — so it skips the router's model-resolution/fallback, and uses a **sentinel model profile** (`_TAG_MODEL_PROFILE`).
- **(c) `Any` vs a typed Protocol.** `llm_provider: Any` (untyped) — reentry/dispatch use a typed `LLMRouterProtocol`. `Any` passes `mypy --strict` by sidestepping it, but loses the type contract.

None of this is a constitutional breach (the call is still content-gen `HYPOTHESIS_TAG_PROPOSAL`) or a gate failure — but P2.6 is the **first producer**, so this sets the **producer-LLM-call pattern** every future producer will mirror. The deviation should be a deliberate architect call, not a default.

**Lean (surface, not decide):** **α** — align to the established **sync, typed `LLMRouterProtocol`** pattern (consistent with agents + reentry; gets fallback/routing; typed). **Or β** — accept provider-direct/async as the deliberate producer convention (e.g. producers are async leaf consumers) and **document why** (so the next producer isn't a coin-flip). **Architect: α (align) / β (accept + document the new producer pattern) / γ (defer to a producer-pattern ADR)?** — it's pattern-setting for the producer layer, not a defect.

## What holds — verified clean (G1–G10)

- **G1 — c1 boundary clean:** descriptive content-gen tagging; no matcher/promotion symbols (guard-enforced); per-hypothesis scope blocks cross-hypothesis selection; `HYPOTHESIS_TAG_PROPOSAL` content-gen (no routing/judgment purpose).
- **G2 — c2 boundary clean:** `evidence_ref` required+non-empty (emit helper raises); sole construction site; `EventStore.append`-only; deterministic demo connector.
- **G3 — both AST guards actively proven discriminating** (live real-source plants: c1 caught `run_matcher`, c2 caught out-of-site `ExternalValidationMeta`) + shipped self-tests + 4-layer no-upstream-import guard.
- **G4 — B3 advisory, no status mutation** (pure SELECT reader; e2e asserts PENDING-unchanged + confirmed-reader-excludes).
- **G5 — gates ALL green incl. `mypy --strict`** (169 files, canonical `files=[src,tests]`) — the **P2.5 R1 lesson learned** (commit `58084d7`).
- **G6 — Q1/Q2/Q3/Q5** clean (only-LLM-is-content-gen; decision_trace N/A; handoff 5-surface; discriminating e2e).
- **G7 — Y2-overwrite absorbed + tested** (`update_hypothesis_tags` overwrite semantic; `test_b1_e2e_update_hypothesis_tags_overwrite_semantics`).
- **G8 — parallel structure held** — landed in disjoint atoms (B1→`producers/`+`memory/store.py`; B2→`connectors/`; B3→`memory/validation.py`).
- **G9 — faithful to ADR-022 + the absorbed routing** — both guards present as specified; **no closed-ADR-019/`core/event.py` edit** (`evidence_ref` stays `str|None`; the connector contract enforces it).
- **G10 — import guard** covers all four upstream layers for both `producers/` + `connectors/` (mirrors reentry; discriminating self-tests).

Minor notes (non-findings, for awareness): (a) the demo connector only emits `confirmed` (or `None` on no-match); `refuted`/`inconclusive` are test-injected for B3 — intended scope (deterministic-confirmed demo), so the connector→B3 path isn't exercised end-to-end. (b) the c2 guard exempts by **basename** `_emit.py` (not the full `connectors/_emit.py` path) — a future `_emit.py` elsewhere would be exempt; a one-line hardening, very low risk.

## What I did NOT do

- Did not decide Y1 — surfaced with a lean (α align / β accept+document / γ) for the architect; it's a producer-pattern-setting call, not a defect.
- Did not modify the impl (the two planted bypasses were reverted; tree clean before commit).
- Did not touch the shared working tree, ADR-022, or the plan.
