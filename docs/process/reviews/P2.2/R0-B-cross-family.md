---
task_id: P2.2
round: R0-B-cross-family
reviewer_family: deepseek
verdict: clean
verdict_history:
  - needs_architect  # original (0🔴 2🟡 5🟢); Y1→A→α + Y2→B→α absorbed, G2→α-small inscribed, bumped per RC-10
findings_count:
  red: 0
  yellow: 2
  green: 5
---

# P2.2 R0-B cross-family review (plan + ADR-017) — cross-room hypothesis matcher

| Field | Value |
|---|---|
| Round | R0-B-cross-family (true cross-family, plan-stage; dual-lens-r0b.md — runtime/invariant/failure-mode lens) |
| Reviewer family | deepseek |
| Stage | Plan + ADR-017 (Proposed), pre-impl |
| Artifacts | `senior-plans/P2.2.md`, `ADR-017-cross-room-hypothesis-matcher.md` |
| Baseline | `main` — merged P2.1 registry (ADR-018 closed); ADR-016 |
| Source verified | `tags.py:18` normalize_tag, `store.py:41/48` candidate column + index, `schema.py:87-95` Hypothesis (no scope), `store.py:236` _row_to_hypothesis |
| Prior reviews | R0-A-on-plan (`0🔴 2🟡 5🟢`) |
| Date | 2026-05-30 |
| Verdict | **needs_architect** — 0🔴 · 2🟡 · 5🟢 |

## Lens preamble

Cross-family runtime/invariant-tracing lens per `external-r0b-prompt.md` probes. Over-correcting for Claude biases: trusting spec claims without tracing the actual execution (the equivalence-relation property, normalize-at-read idempotency dependency, distinct-room counting off-by-one, monotonicity under threshold-change), and sycophancy toward consensus (R0-A already confirmed both yellows — independently verify, not rubber-stamp). This pass walks every invariant the prompt flags: the tag-set grouping partition, distinct-ROOM counting, determinism under scan order, idempotency/monotonicity of `candidate_for_promotion`, the `normalize_tag`-reuse equivalence relation, and advisory-only orthogonality. All source claims cited in the plan + ADR-017 were verified against `origin/main`.

## Findings

| # | Sev | Finding | Evidence |
|---|---|---|---|
| Y1 | 🟡 | **Empty/`[]`-tag-set exclusion untested (R0-A Y1 confirmed).** The matcher excludes `frozenset()` from grouping (ADR-017 D1, D3; plan P2.2-2 AC#2). This is the **dominant early-life case** — most hypotheses are untagged until an agent-tagging producer ships (ADR-017 calls the matcher "dormant-until-fed"). A regression (group map built before empty-set filter; empty frozenset accidentally groups across rooms) floods every untagged hypothesis with `candidate_for_promotion=True`. Scenario Y (P2.2-4) has no case with multiple `[]`-tagged hypotheses across distinct rooms. Cross-family confirmation of R0-A's Y1 — independent code-trace reaches the same conclusion. The omission is high-consequence precisely because the early-life blast radius is maximal (every untagged row) and the test is nearly free. | ADR-017 D1/D3; plan P2.2-2 AC#2; plan P2.2-4 Scenario Y (no `[]`-tagged cross-room case) |
| Y2 | 🟡 | **Structural orthogonality guard inherits whole-file substring fragility (R0-A Y2 confirmed; RC-23 family).** Plan P2.2-4 models the new guard on `test_constitution.py` — which uses `if pattern in content` (whole-file substring scan, verified at `test_constitution.py:46`). A matcher docstring saying "advisory only — never calls `promote_hypothesis`" trips the guard meant to enforce that property. The likely junior fix is deleting the explanatory docstring to satisfy a brittle test — strictly worse (loses the orthogonality contract for a mechanical pass). This is the **same fragility as RC-23** (`_parse_adr_status` misreading prose that quotes a status line), recurring in a test this plan introduces. Cross-family confirmation: independently verified both the constitutional test's substring mechanism and the plan's reliance on it. The RC-23 family of substring-scan bugs now spans the ADR parser AND the test suite — the cross-family lens flags the pattern consistency. | `test_constitution.py:46` (`if pattern in content`); plan P2.2-4 structural orthogonality guard description |
| G1 | 🟢 | **Normalize-at-read (D2) is sound — parallel to lookup's both-sides holds.** Re-normalizing stored tags at read is the right posture. The senior's deciding argument (consistency with lookup's both-sides from ADR-018 D7 / P2.1 Y1→α, plus robustness against raw-insert paths) is valid. Cost is negligible — one `normalize_tag` per stored tag in a small in-process scan. The cross-family lens confirms the parallel: if raw-insert was worth defending against for VK lookup (legacy rows, no backfill), it's worth defending against for the matcher for the same reason. No divergence. | ADR-017 D2; ADR-018 D7 (lookup both-sides precedent) |
| G2 | 🟢 | **`normalize_tag` idempotency is proven correct but implicit in the ADR — should be explicit.** The matcher's normalize-at-read re-normalizes already-canonical stored tags. Safety = `normalize_tag(normalize_tag(x)) == normalize_tag(x)`. Empirically confirmed for all boundary cases (`"llm-cost"`, `"LLM - Cost"`→`"llm---cost"`, `"C++"`, empty string). The property holds because the output of `normalize_tag` has no leading/trailing whitespace (`.strip()` no-op), is all-lowercase (`.lower()` no-op), and has no whitespace runs (`re.sub(r"\s+","-")` no-op). Neither ADR-017 nor the plan states this as a required invariant. If a future `normalize_tag` amendment adds hyphen/punctuation stripping (its own ADR-018 forward hook), idempotency could break and the matcher's group key would silently diverge from the registry's stored canonical — a cross-slice invariant with no explicit guardrail. Current P2.1 tests cover `normalize_tag("llm-cost") == "llm-cost"`, so the property is *tested* but not *named*. Recommend inscribing idempotency as an explicit property in ADR-017 D2 (or ADR-018 D3 as a cross-reference note) so a future normalize_tag amendment is forced to check it. | `tags.py:18-30` (empirical proof above); ADR-018 forward hooks (richer normalization) |
| G3 | 🟢 | **Equivalence-relation partition (D3) + distinct-room counting (D4) correct and e2e-guarded.** Exact canonical tag-set equality (`frozenset`-equality) is genuinely transitive → clean order-independent partition. Same-room-dup e2e case (P2.2-4 AC#3 — two hypotheses, same canonical `{solo-topic}`, both room1 → not flagged at min_rooms=2) proves distinct-**room** (not distinct-row) counting. Off-by-one at min_rooms boundary handled correctly: group with exactly min_rooms distinct rooms → flagged; group with min_rooms-1 → not flagged. Duplicate tags within a single row's `topic_tags` collapse under `frozenset` (correct — the canonical tag set is what matters, not repetition count). | ADR-017 D3/D4; plan P2.2-2 AC#2/AC#3; P2.2-4 AC#3 (same-room-dup) |
| G4 | 🟢 | **Determinism structural (set ops) + idempotency/monotonicity correct.** The flagged id-set is a pure function of `{(id, room_id, canonical-tagset, status)}` — set operations are order-independent by construction. The sort-by-id is for stable `MatcherResult` + UPDATE ordering only, not flag correctness. Idempotency: UPDATE only flips `0→1` for PENDING rows → second run finds them already flagged → `rows_newly_flagged == 0`. Monotonicity: only `False→True`, never clears. Plan P2.2-4 AC#5 (shuffle record order → same flagged set) correctly exercises scan-order independence. | ADR-017 D4; plan P2.2-2 AC#5/AC#6/AC#7 |
| G5 | 🟢 | **Advisory orthogonality preserved; RC-23 clean; cite discipline verified.** ADR-016 D3/D10 unchanged (flag-independent eligibility; no-auto-promote). E2e asserts no VK row + no promotion decision event after `run_matcher` + `promote_hypothesis` works on BOTH flagged and unflagged PENDING rows. RC-23: ADR-017 parses `proposed` (verified by running the accept-gate parser logic). Plan/ADR citations verified against `origin/main`: `tags.py:18` (normalize_tag), `store.py:41,48` (candidate column + index), `schema.py:87-95` (Hypothesis no scope), `store.py:236` (_row_to_hypothesis). All accurate. No §7-P1.2 bundling; all deferrals intact. | ADR-016 D3/D10; plan P2.2-4 AC#6/AC#9; verified source cites on `main` |

## Synthesis

Both R0-A yellows are independently confirmed by cross-family invariant-tracing. The pattern is notable: one finding is about a missing test for the dominant operational case (Y1 — empty tag-set, the matcher's dormant-until-fed state); the other is about a test mechanism that inherited a known fragility pattern (Y2 — substring scan, RC-23 family). Neither is a design defect — the design is sound, and the ADR/plan got the invariants right. This is a test-coverage + test-approach gap, which is what plan-stage R0-A/R0-B is supposed to catch.

One cross-family addition (G2): the `normalize_tag` idempotency property that normalize-at-read silently depends on. It holds today, it's test-covered by P2.1, but it's not named — and it should be, so a future `normalize_tag` amendment doesn't break the matcher's equivalence relation by accident. This is the cross-family lens's structural contribution: Claude-family reviewers trust that "if the function is reused, it's correct"; the cross-family lens asks "what property must hold for that reuse to stay correct under future amendment?"

No 🔴. The matcher design is correct across all invariants probed. Both 🟡 are test-approach items that don't require design changes.

## What the architect needs to route

1. **Y1 (🟡):** R0-A Y1 confirmed — add the untagged-across-rooms → zero-flagged test (unit in P2.2-2 + e2e line in Scenario Y). Guards the matcher's dominant early-life case. No design change.
2. **Y2 (🟡):** R0-A Y2 confirmed — implement the structural orthogonality guard as a real call/import check (or at minimum strip comments/docstrings before the substring scan), not a naive whole-file substring scan. Prevents the RC-23 fragility recurrence. No design change.
3. **G2 (🟢):** Optional — inscribe `normalize_tag` idempotency as an explicit property in ADR-017 D2 (one sentence: "normalize_tag is idempotent — re-normalizing an already-canonical stored tag is a guaranteed no-op — so normalize-at-read is safe for both raw-inserted AND registry-canonical rows"). ADR-018 D3 could also carry a cross-reference note. Not required for Accept — the property is already tested.
4. **Remaining greens** are affirmations; no action.

---

## Verdict bump (RC-10) — needs_architect → clean

Both yellows + the G2 green were routed and absorbed in the senior revision (`architect-routing-on-plan.md`, 2026-05-31; both Y's were two-lens-confirmed with R0-A-on-plan, zero divergence):
- **Y1 → A → α** (empty/`[]`-tag-set exclusion untested): unit test (plan P2.2-2 AC#11) + e2e line (P2.2-4 AC#1/#3) — untagged rows across rooms flag zero. Test-only.
- **Y2 → B → α** (orthogonality guard whole-file-substring fragility): re-spec'd as a real call/import **AST check** (code, not comments) — closes the RC-23-family recurrence (the wider whole-file-substring-scan audit is RC-24, a retro candidate, not bundled here).
- **G2 → α-small** (cross-family structural contribution): `normalize_tag` idempotency inscribed as a required property in ADR-017 D2 + a cross-reference note in ADR-018 D3 — so a future `normalize_tag` amendment cannot silently break the matcher's normalize-at-read equivalence with the registry.

No `src/` design change. Verdict → **clean**. (This cross-family pass added a genuine net-new structural inscription (G2) and two-lens-confirmed both test gaps — a clean dual-lens datapoint.)
