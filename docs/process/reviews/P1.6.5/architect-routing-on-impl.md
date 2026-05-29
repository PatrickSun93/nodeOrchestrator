---
task_id: P1.6.5
kind: architect-routing (impl stage)
date: 2026-05-29
reviews_acked:
  - plan-vs-impl.md
  - R0-A.md
  - R0-B.md
decisions:
  Y1: α (a) (amend Accepted ADR-016 D11 + plan P1.6.5-2 to the impl's _append_body shape + document the DML-first caller contract + forward-amendment hook)
  Y2: α (a) (add user_id to the promotion decision event metadata — DecisionMeta gains a user_id field; promotion.py populates it)
  Y3: dismissed (architect: 不用管 — no action; the format-only dev-harness reflow stays as landed; not routed)
---

# P1.6.5 architect routing — impl stage ("Y1 α(a) · Y2 α(a) · Y3 dismissed")

**Architect decisions (this session):** routes the impl-stage reviews — senior `plan-vs-impl.md` (0🔴/2🟡/9🟢), architect-partner `R0-A.md` (0🔴/3🟡/6🟢), cross-family `R0-B.md` (clean, 0🔴/0🟡/8🟢). The impl is correct and gates green (893); these are contract/text/completeness amendments, not correctness fixes. No 🔴.

This file is the **signal artifact for the senior revision session** (impl-stage; ADR-008 Amendment 2 / W-005 Route B). Senior reads this + the three reviews + ADR-016 + plan + the impl, applies the routed actions, bumps `plan-vs-impl.md` + `R0-A.md` verdicts per RC-10.

## Per-finding routing

### Y1 → α (a) — amend Accepted ADR-016 D11 + plan P1.6.5-2 to the impl shape

**2-way overlap** (senior Y1 + R0-A Y1, both α(a)); R0-B verified the impl works but didn't check ADR-text-vs-code. The proxy-Y2 entry guard (`event_store.py:266`, `if not self.conn.in_transaction: raise`) fires on the **first** statement inside `with conn:` — Python sqlite3 sets `in_transaction=True` only after the first DML. So ADR-016 D11's Accepted example (shows `append_in_transaction` first) and plan P1.6.5-2's literal `append` wrapper both **raise if copied verbatim**. The impl resolved correctly: `append()` calls shared `_append_body` directly (`event_store.py:300-303`); `promote_hypothesis` reorders **c→a→b** (UPDATE-first to open the txn) (`promotion.py:99-128`).

**Action (senior absorption):**
- Amend **ADR-016 D11** (Accepted — architect-authorized amendment): replace the example with the `_append_body` factoring; document the **DML-first caller contract** (callers must execute ≥1 DML before `append_in_transaction`, OR the self-managed `append()` path uses `_append_body` directly); add a **forward-amendment hook** noting the guard's first-statement/bare-call ambiguity (R0-A sharpening — the guard can't distinguish a legitimate first-statement call from a truly-bare call; revisit the mechanism at a future concurrency reshape).
- Amend **plan P1.6.5-2** "EventStore split" block to match (`_append_body` + DML-first), so plan and impl agree.
- Status line: add a 3rd amendment entry (impl-stage routing absorption).

**Why α(a):** an Accepted ADR whose canonical reusable-primitive example raises is a no-orphan-spec violation; the next module copying D11 hits `RuntimeError`. Doc-to-impl reconciliation (impl is the correct shape). No code change — impl already right.

### Y2 → α (a) — add `user_id` to the promotion `decision` event metadata

**Routed over R0-B's accept** (senior 🟡 + R0-A 🟡 route, vs R0-B 🟢 design-choice). The promotion event is built with `author="system"` and no `user_id` (`promotion.py:78-92`); the promoting user lands only in `verified_knowledge.promoted_by_user_id`. The cycle's headline mechanism is **(b) user-confirm promotion**; Principle 1 makes the event stream canonical; a *user decision* whose canonical event omits the user is the gap to close.

**Action (senior absorption — code + ADR + plan + tests):**
- **`DecisionMeta`** (`core/event.py`) gains a `user_id: str | None = None` field (ADR-016 D8 amendment). **Senior decides** the co-presence shape: is `user_id` required when `promotion=True` (extend the `@model_validator`), or left optional? Lean for senior consideration: require it under `promotion=True` for symmetry with `hypothesis_id`/`vk_id`, since every promotion has a confirming user — but that's the senior's design call to pin in the absorption.
- **`promote_hypothesis`** (`promotion.py`) adds `"user_id": user_id` to the event metadata (it already has the `user_id` param).
- **ADR-016 D3 + D8**: inscribe that the promotion event carries `user_id` (canonical actor attribution); update the metadata field list.
- **Tests**: `tests/core/test_event.py` (DecisionMeta user_id) + `tests/memory/test_promotion.py` (event metadata includes user_id) + the e2e assertion.

**Why α(a):** cheap (one field + one key), closes the Principle-1 completeness gap on the cycle's headline mechanism, makes an event-stream-only audit ("who promoted X?") answerable. `author` stays `system` (the subsystem executed it); `user_id` records who confirmed it.

### Y3 → dismissed (no action)

Architect ruled **不用管** — the format-only dev-harness reflow (`workflow/{cli,transitions}.py`, `tests/workflow/`, `test_constitution_line_endings.py`) stays as landed. Verified semantically null (R0-A `-w` diff) + honestly disclosed (senior G9). **Not routed; no senior action.** The pre-existing dev-harness format-debt root cause is noted but not actioned this cycle (architect's discretion).

## Absorption shape + cycle mechanics (for architect awareness)

- **Y1 is doc-only** (ADR-016 + plan text; impl already correct) — pure senior absorption.
- **Y2 is a small code change** (`DecisionMeta` field + `promotion.py` + tests) — more than a doc absorption. **Architect decides the path**: senior-absorbed same-branch fix (P1.5 R1 precedent — fix-on-branch, cycle stays at 1) **vs** junior re-dispatch (cycle-2 rework via `workflow override`). Given Y2 is ~one optional field + one metadata key + tests, the same-branch absorption (no cycle increment) is the lighter path consistent with P1.5 R1 — but the override/dispatch is the architect's call, not mine. Surfaced, not decided.
- **RC-10 verdict bumps** at absorption: `plan-vs-impl.md` Y1+Y2 → 🟢 (senior); `R0-A.md` Y1+Y2 → 🟢 + Y3 → 🟢-dismissed (architect-partner, or senior notes the dismissal). `R0-B.md` already clean.

## Cross-references
- `docs/process/reviews/P1.6.5/plan-vs-impl.md` — senior Y1 (origin) + Y2 (origin).
- `docs/process/reviews/P1.6.5/R0-A.md` — R0-A Y1 (sharpened: guard ambiguity) + Y2 (route) + Y3 (origin, now dismissed) + G2 (TOCTOU/UNIQUE insight).
- `docs/process/reviews/P1.6.5/R0-B.md` — clean; `author="system"` 🟢-note (Y2 divergence resolved toward route).
- `docs/decisions/ADR-016-cross-room-memory-persistence.md` — D11 (Y1 amendment) + D3/D8 (Y2 amendment).
- `docs/process/senior-plans/P1.6.5.md` — P1.6.5-2 (Y1 wrapper text).
- Impl: `src/orchestrator/core/event_store.py:185-303` (Y1) + `src/orchestrator/memory/promotion.py:78-128` (Y1 reorder + Y2 event) + `src/orchestrator/core/event.py` DecisionMeta (Y2).
