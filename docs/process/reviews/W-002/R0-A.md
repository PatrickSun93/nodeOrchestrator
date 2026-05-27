---
task_id: W-002
round: R0-A
verdict: clean
findings_count:
  red: 0
  yellow: 1
  green: 5
---

# W-002 R0-A review

| Field | Value |
|---|---|
| Round | R0-A (post-impl, architect-partner; **post-hoc** — see Caveat below) |
| Reviewer | architect-partner (Claude Opus 4.7, 1M context) in primary session |
| Date | 2026-05-27 |
| Artifacts reviewed | 5 impl commits on `claude/W-002-impl` merged via PR #10: `8b9e1d8` (W-002-1), `156c670` (W-002-2), `fb965ce` (W-002-2b), `7cea117` (W-002-3), `f7b14d2` (W-002-4); 17 files touched; 472 tests post-impl (was 454; +18). Sibling review `plan-vs-impl.md` commit `f9d35cd` (clean, 0🔴 / 0🟡 / 4🟢) read to deliberately avoid duplication. |
| Caveat | **Post-hoc dispatch.** PR #10 merged before the post-impl review chain ran (process gap — "失误在我" per architect). This R0-A is retroactive verification, not pre-merge gate. The gate-value is reduced; finding-value + audit-trail-value + state-machine-advance value remain. Architect captured this as RC-13 candidate for W-002 retro. |

---

## Lens

`plan-vs-impl.md` (senior) already enumerated impl-vs-plan acceptance compliance (5/5 tasks ✓, both Y-routings honored, all 6 push-backs absorbed, all 4 forcing functions applied). I do not re-traverse that ground.

R0-A's distinct value-add is **architect-partner independent lens**:
- ADR-008 invariant compliance (was the state-machine contract preserved through 3 fixes?)
- Constitutional test integrity (is "no new test needed" actually correct?)
- Layering verification (W-002-2b `transitions → workflow/io.py` edge: no constitutional violation?)
- Forward implications for P1.4 / W-003 (what does this enable; what does it leave open?)
- The architect-raised observation #12 about legacy-vs-no-ADR semantic conflation (read against actual impl)

---

## Findings

### 🟢 G1 — ADR-008 invariants preserved through all three state-machine fixes

The three fixes (W-002-1 task→ADR, W-002-2 cycle-counter, W-002-2b no-ADR routing) all preserve the load-bearing ADR-008 invariants:

- **D2 (`next_state` is a pure function of `(current_state, artifacts, gates)`):** W-002-2b extends `ArtifactSnapshot` with `plan_has_adr: bool | None` (frontmatter tri-state); `next_state` consumes the snapshot field, does NOT read the plan file itself. The pure-function invariant is preserved — `next_state` stays deterministic given a snapshot. (This is also senior plan-vs-impl observation #2; I'm reinforcing because it's load-bearing for the state-machine's testability.)
- **D10 (override audit trail):** `record_override` cycle-counter fix narrows the increment condition but **does not change the audit-trail shape**. `override_history.append(entry)` still fires unconditionally; `last_transition_at` still updates unconditionally. Only `cycle` behavior changed. Verified via `tests/workflow/test_transitions.py` — the audit-invariant tests pass unchanged.
- **D7 (frontmatter contract):** W-002-1 extends the contract from review files to plan files (`adr: ADR-NNN` optional key). The same `---`-fenced-YAML shape; `_read_plan_frontmatter` is a small inline parser with the same failure-mode discipline as the existing `parse_verdict` (returns `None` for absent/malformed; raises `WorkflowError` only for truly malformed-fence). Consistent extension; no breaking schema change.

### 🟢 G2 — Constitutional test integrity holds with zero new tests

The plan correctly identified "no new constitutional test expected" because W-002 introduces no new module + no new layering edge. R0-A verifies this:

- `src/orchestrator/workflow/` adds `io.py` (a within-module file); no new top-level module.
- `transitions.py` imports `_read_plan_frontmatter` from `orchestrator.workflow.io` — **within-module import; no constitutional-test surface**. (The constitutional test guards `core → workflow`, `llm/autonomy/skills → workflow` (none of these); intra-`workflow/` imports are unrestricted.)
- `_read_plan_frontmatter` is a deterministic resolver (file read + YAML parse), not a decision function (no `LLMPurpose`-style obligation). `decide_skills_for_context` / `should_agent_speak`-style decision-trace pattern does NOT apply here per Q2 framing.

`test_constitution_no_llm_calls_in_workflow_module` + `test_constitution_no_llm_calls_in_skills_module` remain green across all 5 impl commits (verified via `pytest`). No regression.

### 🟢 G3 — W-002-2b layering: `transitions → workflow/io.py` is the clean shape

Senior plan §3 noted: "If W-002-1 placed the parser inline in `cli.py`, W-002-2b extracts it to `workflow/io.py` first." Junior took the extract-first path (W-002-1 went straight to `io.py`). Result: `transitions.py → workflow/io.py` is a within-module import; no `transitions → cli` reverse edge needed. The alternative (parser staying in `cli.py`) would have forced `transitions → cli.py` which is awkward (CLI is a consumer of `transitions`, not the other way around). **Foresightful placement** — senior plan-vs-impl observation #4 also flagged this; I confirm independently.

### 🟢 G4 — RC-11 sub-findings (a) + (b) both closed; new sub-finding (c) closed too

W-002 plan §1 enumerated three bugs:
- Sub-finding (a) task→ADR mapping → **closed by W-002-1** (path β plan-frontmatter convention; `_read_adr_status` correctly handles the P1.3-style case via `adr: ADR-NNN`).
- Sub-finding (b) `record_override` cycle-counter → **closed by W-002-2** (gate on both `from_state == AWAITING_ARCHITECT_DECISION` AND `to_state == AWAITING_JUNIOR_IMPL`; defense-in-depth tests cover P1.3-shape + BRIEF-shape from-states).
- Sub-finding (c) no-ADR routing (senior-discovered third bug during plan-writing; absorbed via architect-routing Y2→β) → **closed by W-002-2b**.

The cluster that surfaced during P1.3 dogfood is now structurally closed. For W-003+, only the multi-ADR-per-task case remains open (W-003 scope per W-002 plan §5 push-back #4).

### 🟢 G5 — Tests genuinely exercise the fixes, not just shape

Three test categories I spot-checked beyond plan-vs-impl's coverage:

- **W-002-1 multi-ADR-list rejection (boundary §5):** `tests/workflow/test_cli.py` tests `adr: [ADR-099]` (1 element), `adr: [ADR-099, ADR-100]` (2 elements). Both reject. **Multi-position discipline honored** — the rejection is tested at distinct list-shapes, not just "list rejects." This matches the §5 boundary-validator-at-multiple-positions standard from `test-coverage-standard.md`.
- **W-002-2 warning emission narrowed correctly:** the cycle-≥4 warning fires only inside the rework-condition branch (not on every override). `test_record_override_cycle_warning_fires_only_on_rework_reaching_threshold` covers both the positive (rework reaches 4 → warning) and negative (non-rework override at same cycle → no warning) cases via `capsys`. The pre-fix bug class (warning firing on cosmetic overrides) is regression-tested out.
- **W-002-2b legacy-vs-explicit-no-ADR discriminator:** `test_next_state_legacy_no_frontmatter_routes_through_accept` + `test_next_state_skips_accept_when_no_adr_key_in_frontmatter` + `test_next_state_routes_through_accept_when_adr_key_present` cover all three tri-state branches. Architect's audit observation #12 (legacy vs no-ADR conflation) is **explicitly tested as a distinguishing factor**, not collapsed. See Y1 finding below for nuance.

### 🟡 Y1 — Legacy-vs-no-ADR-explicit semantic distinction is implementation-correct but documentation-thin (also surfaced as architect audit obs #12)

**Where:** `src/orchestrator/workflow/transitions.py:143-148` (the W-002-2b discriminator):
```python
if artifacts.plan_has_adr is False:
    return WorkflowState.AWAITING_JUNIOR_IMPL  # case (b): skip accept
return WorkflowState.AWAITING_ARCHITECT_ACCEPT  # case (a) or (c)
```

**What:** the discriminator branches three intent classes:
- (a) `plan_has_adr is True` (frontmatter declares `adr: ADR-NNN`) → route through Accept gate. Correct for ADR-bearing tasks.
- (b) `plan_has_adr is False` (frontmatter present, no `adr` key) → skip Accept gate. Correct for declared no-ADR tasks (W-002 itself dogfoods this).
- (c) `plan_has_adr is None` (no frontmatter at all, legacy plans) → route through Accept gate. **Backwards-compat fallback** for pre-W-002 plans (P1.3, W-001-impl, P1.4).

**The architect's audit observation #12 flagged a concern**: legacy plans (case c) are conservatively routed through Accept even though they may not "need" Accept semantically. The impl is correct (preserves pre-W-002 behavior for P1.3/W-001-impl which are closed anyway; correct for P1.4 which has real ADRs). But the semantic conflation is real: "legacy" and "has-ADR" both take the same code path through Accept, distinguished only by what `_read_adr_status` returns at the next step.

**Risk in practice:** low. P1.3/W-001-impl are closed; P1.4 has real ADRs so routes correctly; W-002+ onward should have frontmatter per the new convention. The conflation only bites a hypothetical future plan that: (i) is post-W-002 chronologically, (ii) is intentionally no-ADR, AND (iii) is authored without frontmatter. The author would hit the same architect-override pattern W-002 itself just demonstrated as the "last no-ADR override" — and would learn the lesson.

**Resolution options:**
- (a) Add a docstring note in `transitions.py:143-148` explicitly enumerating the three intent classes + the conflation rationale. Cheap; documentation-only.
- (b) Add a forcing function: W-003 includes a CI check or `workflow verify-workspace` extension that warns when a post-W-002 plan lacks frontmatter. Pushes the convention-vs-fallback boundary into tooling.
- (c) No action; let convention discipline emerge from authoring practice. Accept the latent risk.

**My lean: (a) for W-002 retro action item; (b) for W-003 brief scope.** The conflation isn't a bug; it's a transition-period concession. Naming it explicitly in the code reduces the chance a future maintainer misreads "legacy" as "intentional no-ADR".

**Severity 🟡 not 🔴**: doesn't ship a runtime bug; correctness is preserved; concern is documentation/forward-clarity.

---

## Cross-checks

- [x] All 472 tests green; ruff/format/mypy strict clean across 75 source files.
- [x] Constitutional tests preserved (no LLM imports in workflow/ or skills/; no core → workflow/skills edges introduced).
- [x] ADR-008 D2 pure-function invariant: `next_state` reads `ArtifactSnapshot`, not files.
- [x] ADR-008 D7 frontmatter contract: `_read_plan_frontmatter` extends pattern to plan files consistently with review-file precedent.
- [x] ADR-008 D10 override audit trail: shape unchanged; only cycle behavior narrowed.
- [x] Layering: `transitions.py → workflow/io.py` is within-module; no reverse `cli → transitions` edge.
- [x] RC-11 cluster all 3 sub-findings closed (the third surfaced + closed in same cycle via Y2→β).
- [x] Frontmatter dogfood: W-002 plan itself uses post-W-002 frontmatter contract.
- [ ] Y1 (legacy-vs-no-ADR-explicit documentation thin) — see finding.

---

## Forward implications

**For P1.4 (next consumer):** W-002-1 task→ADR mapping closes the override-on-Accept pattern for **single-ADR** tasks. P1.4 has TWO ADRs (010 + 011). The current `_read_adr_status` reads the single `adr: ADR-NNN` key per plan; multi-ADR is W-003 scope (W-002 plan §5 push-back #4; explicit `WorkflowError` raise on `adr: [...]`). **P1.4's ADR Accepts will likely need 1-2 architect overrides** until W-003 lands multi-ADR semantic. The override count history projection:

| # | Task | Reason | Status |
|---|---|---|---|
| 1 | P1.3 (`cfbf087`) | RC-11(a) task→ADR mapping; pre-W-002-1 | closed by W-002-1 |
| 2 | W-002 (`236dac1`) | RC-11(a-sibling) no-ADR routing; pre-W-002-2b | closed by W-002-2b |
| 3-4 | P1.4 (future) | multi-ADR-per-task; ADR-010 + ADR-011 Accepts may need bridge overrides | W-003 territory |

So architect-partner role still has bridge work ahead for P1.4 ADR Accepts; the override count grows by 1-2 before W-003 closes that loop.

**For W-003 brief (when authored):** absorbs three items naturally — (a) multi-ADR-per-task semantic, (b) `verify-workspace` divergence detection (W-002 §5 push-back #2 deferral), (c) plan-frontmatter CI enforcement (W-002 §5 push-back #5 deferral). Plus optionally Y1 above (documentation hardening for the legacy-vs-no-ADR conflation).

---

## Net assessment

**Verdict: clean.** Five 🟢 confirmatory findings + one 🟡 documentation-thin observation. No 🔴; no return-to-junior-for-rework warranted.

The W-002 cycle delivered exactly what it promised: closure of the RC-11 cluster (both sub-findings + the senior-discovered third bug), faithful absorption of architect-routing leans, and preserved ADR-008 invariants through the state-machine fixes. The architect-routing → senior-revision → junior-impl loop worked end-to-end despite the process gap (PR #10 merged pre-review chain; both reviews retroactively).

**Recommendation:** state machine `awaiting_senior_plan_vs_impl → awaiting_R0_A → awaiting_PR_merge → closed` auto-trigger chain should fire on next `workflow advance --task-id W-002` (PR #10 already merged; plan-vs-impl clean; R0-A clean; merge-clean N/A since already merged). This will be the **first plan-vs-impl + R0-A cycle to advance cleanly without manual override or timezone fallback** — earning W-002 the right to demonstrate the harness's now-mature state-machine works end-to-end on a task that also tested its own fixes.

**Captured RC for W-002 retro (whenever it happens):**
- **RC-13** — Architect-merge-before-post-impl-reviews (process gap; ownership acknowledged). Mitigation: PR template forcing-function checkbox OR `workflow verify-merge-readiness` CLI subcommand for W-003.
- **Y1 above** — legacy-vs-no-ADR-explicit semantic conflation docstring; W-003 territory + docstring tweak.

Cross-family R0-B explicitly NOT dispatched (RC-2 stays accepted for non-shape-change work; W-002 is mechanical refinement). This R0-A is the post-impl review.
