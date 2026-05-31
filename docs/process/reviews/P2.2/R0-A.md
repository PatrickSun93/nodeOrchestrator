---
task_id: P2.2
round: R0-A
verdict: needs_architect
findings_count:
  red: 0
  yellow: 1
  green: 4
---

# P2.2 R0-A (post-impl, architect-partner lens) — cross-room hypothesis matcher

| Field | Value |
|---|---|
| Round | R0-A (post-impl; architect-dispatched) |
| Reviewer | architect-partner (Claude family; doc / architecture / invariant-correctness lens) |
| Commit | `a7f529d` on `claude/P2.2-impl` (atomics P2.2-2/-3/-4 at `d68b61b`, `5a763b3`, `a7f529d`) |
| Baseline | `main` (ADR-017 Accepted; ADR-018 registry; ADR-016) |
| Date | 2026-05-31 |
| Gates | ruff ✓ · mypy ✓ (33 files) · pytest **all passed** · no-LLM constitution (covers `matcher.py`) ✓ |
| Verdict | **needs_architect** — 0🔴 · 1🟡 · 4🟢 |
| Note | Senior `plan-vs-impl.md` not yet present (runs parallel; not my artifact). R0-B (cross-family) separate dispatch. ADR-017 NOT re-accepted (architect-only; already Accepted at plan stage). |

## Summary

Clean, correct implementation of the matcher itself. The 3 impl atomics map 1:1 to the plan; `run_matcher` + `list_promotion_candidates` are faithful to ADR-017 on every load-bearing invariant I traced (normalize-at-read via the registry's `normalize_tag`, empty-canonical-set exclusion, distinct-**room** counting, structural determinism, idempotency, monotonicity, advisory orthogonality). Gates fully green. The two routed **plan-stage** items that touch *code* both landed and are genuinely substantive: **A→α** (untagged-across-rooms → zero-flagged: a real direct-insert test + e2e line) and **B→α** (orthogonality guard reimplemented as a real `ast.walk` call/import check — the RC-23-family substring fragility is gone).

One **🟡**, and it's a process/tracking issue rather than a code defect: the **third routed item, G2→α-small, was NOT absorbed — but the senior revision commit `d9003a7` explicitly claims it was.** `grep idempoten` returns **zero** hits in both ADR-017 and ADR-018; ADR-018 was never touched by that commit. G2's own severity is low (α-small, explicitly Accept-optional, and the property holds in code), so the harm is minimal — but a commit message asserting "Done" on an item that is "Skipped" is exactly the reverse-drift the tracking-table forcing function exists to prevent, and it slipped through the ADR-017 accept (mine — see self-note). The architect should route G2 (inscribe vs consciously drop) and the false "absorbed" claim must be corrected on the record either way.

## Findings

| # | Sev | Finding | Lean |
|---|---|---|---|
| Y1 | 🟡 | G2→α-small (normalize_tag idempotency inscription) NOT absorbed in ADR-017 D2 or ADR-018 D3, but `d9003a7` commit body claims both were done (verified: 0 idempotency hits either ADR; ADR-018 untouched). Tracking-accuracy/reverse-drift; G2 itself low-severity + Accept-optional | α (inscribe into ADR-017 now) or γ (drop G2) — **either way correct the false claim** |
| G1 | 🟢 | `run_matcher` correct on all traced invariants: normalize-at-read, empty-set exclusion, distinct-room counting, determinism, idempotency, monotonicity | affirm |
| G2 | 🟢 | A→α landed + substantive — untagged-across-rooms→zero-flagged (unit + e2e), the dominant early-life case now guarded | affirm |
| G3 | 🟢 | B→α landed + correct — orthogonality guard is a real `ast.walk` call/import/SQL-literal check; docstring-excluded by construction; RC-23 fragility gone | affirm |
| G4 | 🟢 | Gates green; advisory orthogonality holds (no promote/VK-insert/append in `matcher.py`); atomic-commit discipline 1:1 with plan; handoff §4.5 touch | affirm + 1 minor note |

---

### 🟡 Y1 — G2 routed item not absorbed, yet the revision commit claims it was (tracking-accuracy / reverse-drift)

**The routing.** P2.2 plan-stage routing (`architect-routing-on-plan.md`) routed **G2 → α-small**: inscribe `normalize_tag` idempotency (`normalize_tag(normalize_tag(x)) == normalize_tag(x)`) as a required property in **ADR-017 D2**, plus an **ADR-018 D3 cross-reference note** (with the explicit option to drop the D3 note if the architect preferred not to touch the closed ADR-018).

**What landed.** Neither inscription exists. Verified:
- `grep -ic idempoten docs/decisions/ADR-017-cross-room-hypothesis-matcher.md` → **0**. ADR-017 D2 (read in full) makes the normalize-at-read argument but never names the idempotency property the routing required.
- `grep -ic idempoten docs/decisions/ADR-018-cross-room-tag-registry.md` → **0**. And `d9003a7` never touched ADR-018 at all (`git show d9003a7 --stat` lists no ADR-018).

**The reverse-drift.** The senior revision commit `d9003a7` body states, verbatim, under "G2 (α-small) — normalize_tag idempotency inscribed": *"ADR-017 D2: idempotency property note (normalize_tag(normalize_tag(x))==normalize_tag(x)) · ADR-018 D3: cross-reference note."* **Both claims are false.** This is the precise failure the tracking-table forcing function (`feedback_review_followup_tracking.md`) exists to catch: a per-item `Status: Done` that is actually `Skipped`. The matcher's own *runtime* idempotency ("re-running returns `rows_newly_flagged == 0`") IS implemented + tested — which may be how the author conflated the two and self-reported G2 done; but that is a different property from `normalize_tag`'s idempotency, which is what G2 required and what the cross-family lens (R0-B G2) specifically asked to inscribe so a future `normalize_tag` amendment can't silently break the matcher's cross-slice equivalence.

**Why 🟡, not 🔴:** G2 was routed **α-small**, explicitly "Accept-optional, not Accept-blocking" — the idempotency property is *true and P2.1-tested today*, so nothing is broken; only the *named-invariant guardrail* against a future amendment is missing. No code defect, no shipped-behavior risk. The severity is in the **inaccurate tracking claim**, not the missing inscription.

**Why it still needs routing:**
1. The false "absorbed" claim must be corrected regardless of what we do with G2 — an uncorrected `Done`-that-was-`Skipped` in the audit trail is the reverse-drift precedent the project treats as serious.
2. ADR-017 is now **Accepted** (it was Proposed when G2 should have landed). So inscribing G2 now means a one-line touch to an *accepted* ADR — small and RC-23-safe (a D2 body sentence, far from the status line), but it's a real (minor) decision the architect owns.

**Lean:** **α** — inscribe the one-sentence idempotency property into ADR-017 D2 now (cheap; closes the guardrail the cross-family lens asked for; the touch-an-accepted-ADR cost is negligible for a body note). Acceptable alternative **γ** — consciously drop G2 (it's optional and the property holds), and record that decision. **Non-negotiable either way:** correct the `d9003a7` tracking claim (a follow-up commit noting G2 was not actually absorbed, → now inscribed (α) or → dropped by architect call (γ)). This is a senior/plan-doc fix, not junior impl.

**Self-note (architect-partner accountability):** I inscribed the ADR-017 Proposed→Accepted bump (`6ca9f93`) trusting the accept dispatch's "A→α/B→α/G2→α-small absorbed at d9003a7" claim — I verified RC-23 + the status line but did **not** re-verify each routed item was actually present before inscribing the accept. That is how a false-absorbed claim passed the accept gate. Process improvement for future accept-inscriptions: grep-verify each routed item is absorbed (not just trust the revision commit's self-report) before bumping status. Same lesson family as the P2.1 R0-A fabricated-probe self-note — do not trust a claim I can cheaply verify.

### 🟢 G1 — `run_matcher` correct on every traced invariant

Read `matcher.py:35-110` line by line:
- **Normalize-at-read (D2)**: `canonical_set = frozenset(normalize_tag(t) for t in stored_tags)` — reuses the registry's `normalize_tag` (not ad-hoc `.lower()`), so the matcher's canonical form equals the stored vocabulary. ✓ (the central rebase point.)
- **Empty-set exclusion (D1)**: `if not canonical_set: continue` — untagged/`[]` rows never grouped. ✓
- **Distinct-room counting (D4)**: `distinct_rooms = {room_id for _, room_id in entries}; if len(distinct_rooms) >= min_rooms` — counts distinct rooms, not rows. ✓
- **Determinism**: groups built from `ORDER BY id ASC` rows; flagged set is a pure function of `{(id, room_id, canonical-set, status)}`; `ids_to_flag.sort()` for stable UPDATE/report only. ✓
- **Idempotency**: `rows_newly_flagged` counts rows that are `candidate_for_promotion=0 AND status='pending'` *before* the UPDATE → a second run counts 0. ✓
- **Monotonic + PENDING-scoped write**: `UPDATE … SET candidate_for_promotion=1 WHERE id IN (…) AND status='pending'` — only 0→1, never clears, defensive status guard (D4). ✓
- **`min_rooms < 1` → `ValueError`** ✓.

### 🟢 G2 — A→α landed and is substantive

`test_untagged_hypotheses_across_rooms_never_flagged` (test_matcher.py:174) inserts 3 untagged (`topic_tags=[]`) hypotheses across 3 rooms via a direct-insert helper (correctly bypassing `resolve_tags` to test the *matcher's own* empty-set guard, not the registry's write-time rejection), then asserts `rows_newly_flagged == 0`, zero flagged rows, and `list_promotion_candidates == []`. Plus `test_empty_after_normalization_excluded` (whitespace-only tags → `""` → excluded) and the e2e `test_untagged_across_rooms_not_flagged_e2e`. The dominant early-life case both lenses flagged at plan stage is now genuinely guarded — not a no-op test.

### 🟢 G3 — B→α landed and is correct

`test_matcher_advisory_orthogonality_ast_guard` (test_constitution.py:63) is a real `ast.parse` + `ast.walk` checking: (a) forbidden `import`/`from` of `promotion`/`promote_hypothesis`; (b) `Name`/`Attribute` nodes `promote_hypothesis`/`append_in_transaction` + `event_store.append`; (c) `INSERT INTO verified_knowledge` only in `ast.Constant` string nodes (excludes comments/docstrings *by construction*). This is exactly the routed fix — the matcher's own orthogonality docstring ("NEVER calls `promote_hypothesis`…", matcher.py:5) does **not** trip it, and I confirmed the guard passes. The RC-23-family substring fragility the plan would have introduced is gone. Good. (The *other* test in the file — the no-LLM guard — is still the whole-file substring scan; that's the pre-existing instance RC-24 tracks, correctly left untouched this cycle per the architect-deferral on RC-24.)

### 🟢 G4 — gates, orthogonality, discipline (+ one minor note)

ruff ✓ · mypy ✓ (33 files) · pytest all green · no-LLM constitution covers `matcher.py`. Advisory orthogonality holds in code (the matcher's only write is the flag UPDATE; no promote/VK-insert/append — enforced now by the AST guard). 3 atomics → 3 commits 1:1 (RC-17). handoff §4.5 touch present; no §7-P1.2 bundling.

**Minor note (non-blocking):** `run_matcher` calls `conn.commit()` internally (matcher.py:104), unlike the registry's transaction-neutral `resolve_tags`. For a standalone advisory batch with no composition requirement this is fine (and the matcher isn't meant to compose inside another write transaction). Worth a one-line note in the docstring that `run_matcher` self-commits (so a future caller doesn't assume it's transaction-neutral and wrap it). Junior/senior discretion; not a finding.

## What the architect needs to route

1. **Y1 (🟡):** G2 inscription missing despite `d9003a7` claiming it absorbed. **α** (inscribe the idempotency sentence into now-Accepted ADR-017 D2; optional ADR-018 D3 note) or **γ** (consciously drop G2). **Either way:** correct the false "absorbed" tracking claim on the record. My lean: α (cheap, closes the cross-family-requested guardrail).
2. **Greens** are affirmations; the G4 self-commit docstring note is optional.

R0-A does not change state. R0-B (cross-family) is the separate dispatch; I'll synthesize R0-A + R0-B + senior plan-vs-impl for routing once they land. The matcher impl itself is correct and merge-worthy modulo the Y1 tracking/inscription cleanup.
