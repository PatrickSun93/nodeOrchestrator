---
task_id: P1.6.5
round: R0-A
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 9
verdict_history:
  - verdict: needs_architect
    at_commit: 0212e35
    findings_count: { red: 0, yellow: 3, green: 6 }
    note: original (impl stage) — Y1 (ADR-016 D11 + plan non-functional, guard ambiguity sharpening) + Y2 (promotion event omits user_id, sided route over R0-B accept) + Y3 (dev-harness scope-bleed).
  - verdict: clean
    at_commit: c5c971c
    findings_count: { red: 0, yellow: 0, green: 9 }
    note: impl-stage 3rd revision (Path A) absorbed Y1 α(a) + Y2 α(a); Y3 dismissed by architect (不用管). Per architect-routing-on-impl.md. Senior-bumped per W-005 awaiting_senior_revision flow + the routing's RC-10 allowance.
---

> **RC-10 verdict bump (impl-stage routing absorption, 2026-05-29; senior-bumped)** — frontmatter as live signal. Per `architect-routing-on-impl.md`, Path A same-branch absorption on `claude/P1.6.5-impl`. Original finding bodies preserved below as audit trail.
> - **Y1 → 🟢 absorbed** — same fix as plan-vs-impl Y1: ADR-016 D11 + plan P1.6.5-2 reconciled to the impl's `_append_body` + DML-first shape; R0-A's guard-ambiguity sharpening captured as the ADR-016 D11 forward-amendment hook.
> - **Y2 → 🟢 absorbed** — `DecisionMeta.user_id` added (required under `promotion=True`); promotion event carries the confirming user; `author` stays `system`. R0-A's route-over-R0B-accept lean honored.
> - **Y3 → 🟢 dismissed** — architect ruled 不用管; the format-only dev-harness reflow stays as landed (benign, semantically null, disclosed). No senior action. The pre-existing dev-harness format-debt root cause is noted, not actioned this cycle (architect discretion).
> - G2 (Y9 UNIQUE closes the in-function check-then-act TOCTOU) + G5 (store.py:222 dead import) preserved as 🟢 observations; the dead import remains non-routed this cycle.

# P1.6.5 R0-A review (architect-partner lens, impl stage)

| Field | Value |
|---|---|
| Round | R0-A on impl (Route B — mandatory regardless of plan-vs-impl verdict, per ADR-008 Amendment 1 / W-005) |
| Reviewer | architect-partner (Claude Opus 4.7, 1M context) in primary session |
| Date | 2026-05-29 |
| Artifacts reviewed | 6 impl commits on `claude/P1.6.5-impl` (`4ba8654` → `5cd6f34`). Independent reads of: `src/orchestrator/memory/{promotion,store,schema}.py`, `core/event_store.py:185-303` (`_append_body` + `append_in_transaction` guard + `append` wrapper), the dev-harness `-w` diff (`workflow/{cli,transitions}.py`, `tests/workflow/`, `test_constitution_line_endings.py`), `handoff.md` §4.5/§5.8/§10/§15 diff, `store.py:222` flagged import. Plus the two prior reviews: `plan-vs-impl.md` (senior, 0🔴/2🟡/9🟢) + `R0-B.md` (cross-family impl, clean 0🔴/0🟡/8🟢). |
| Workflow context | First impl-stage review on the cross-room memory layer; first cycle to ship persistence beyond the event store. ADR-016 Accepted `2026-05-29`. Gates already run by senior (ruff/format/mypy PASS; pytest **893**) + reconfirmed by R0-B; not re-run here (recent, two-party-verified). |
| Distinct from plan-vs-impl / R0-B | Senior = plan-fidelity + the runtime interaction (Y1/Y2). R0-B = runtime/atomicity absorption (clean). **This R0-A lens = doc/narrative + scope-boundary + principle**, plus independent confirmation of Y1/Y2 from the code (not echoing the reviews). |

---

## Findings

### 🟡 Y1 — ADR-016 D11 (Accepted) example + plan P1.6.5-2 wrapper are non-functional as written; impl diverged correctly. **Confirm senior Y1, sharpened.**

**Independently verified in code.** The proxy-Y2 entry guard at `event_store.py:266-272` is `if not self.conn.in_transaction: raise RuntimeError(...)`. Python sqlite3 (default isolation) sets `in_transaction=True` only **after the first DML** — so:
- ADR-016 D11's Accepted example shows `append_in_transaction(decision_event)` as the **first** statement in `with conn:` → `in_transaction is False` → the guard raises. **The Accepted ADR's own example violates its own guard.**
- Plan P1.6.5-2's literal `append = with self.conn: return self.append_in_transaction(event)` would raise identically.

The impl resolves both correctly (verified `event_store.py:300-303` + `promotion.py:99-128`): `append()` calls the shared `_append_body` **directly** (sidesteps the guard); `promote_hypothesis` reorders to **c→a→b** (UPDATE-first to open the txn, then `append_in_transaction`, then VK INSERT). Atomicity preserved; all 6 `append` callers unaffected.

**Sharpening beyond senior Y1 (my independent add):** the entry guard is only a *partial* closer of the proxy-Y2 footgun. Its own docstring (`event_store.py:254-264`) admits it **cannot distinguish** "first statement inside a legitimate `with conn:`" from "bare call outside any transaction" — both have `in_transaction=False`. Consequences: (a) it false-positives on the natural append-first usage, **forcing** the non-obvious DML-first caller contract; (b) it still **passes** a bare call that follows an earlier uncommitted DML on the same connection (the exact silent-loss case it was meant to stop). So the real atomicity guarantee comes from the c→a→b discipline, not the guard. The guard earns partial keep (catches the truly-bare-first case) but ships a caller contract sharper than its routing (proxy-Y2 α(b)) anticipated.

**Lean α(a):** amend Accepted ADR-016 D11 + plan P1.6.5-2 to match impl — show the `_append_body` factoring, document the "DML-first" caller contract explicitly, and add a forward-amendment hook noting the guard's first-statement/bare-call ambiguity (so a future concurrency reshape revisits the mechanism). ADR amendment is architect-only. This is a real no-orphan-spec issue: an **Accepted** ADR whose canonical reusable-primitive example raises if copied.

### 🟡 Y2 — Promotion `decision` event omits the promoting `user_id` (author=`system`). **Confirm senior Y2; I side with route-it over R0-B's accept.**

**Independently verified:** `promotion.py:78-92` builds the event with `author="system"` and metadata `{based_on, trade_offs, promotion, hypothesis_id, vk_id}` — no `user_id`. The user (`user_id` param) lands **only** in `verified_knowledge.promoted_by_user_id` (line 125).

**Divergence to flag for the architect:** senior routes this 🟡 Y2 (lean mild α(a)); R0-B keeps it 🟢 ("defensible design choice, confirm intent"). **I side with senior — route it.** The cycle's *entire* shipped mechanism is "(b) user-confirm" promotion (`handoff.md` §4.5 "用户显式确认"; brief architect-settled #7 frames promotion *as a user decision*). Principle 1 makes the event stream the canonical record. A *user decision* whose canonical `decision` event records the actor as `system` is an asymmetry worth a deliberate call, not a silent default. Mitigation (real): the VK row is authoritative durable storage, so attribution isn't at risk of loss — this is completeness, not correctness.

**Lean mild α(a):** add `user_id` to the `decision` event metadata (one key; `promote_hypothesis` already has it) so the canonical event is self-describing for an event-stream-only audit. Or **(b)** accept VK-row-only and inscribe the rationale in ADR-016 D3. Either is fine; the point is the plan left it unpinned and it deserves an explicit architect line given it's the headline mechanism.

### 🟡 Y3 — Product cycle's landing reformats dev-harness files (`workflow/`); benign + disclosed, but crosses the CLAUDE.md product/dev-harness boundary. **Net-new (my scope lens).**

**Independently verified:** the `-w` (ignore-whitespace) diff of `workflow/cli.py`, `workflow/transitions.py`, `tests/workflow/test_integration.py`, `test_constitution_line_endings.py` shows only line-rewrapping of boolean expressions (`(A and B)` → `A and B`, multi-line → one-line) — **semantically null**, confirmed. The senior disclosed it honestly (plan-vs-impl G9): `ruff format` reflows of pre-existing unformatted dev-harness debt, bundled into the P1.6.5 landing to pass the repo-wide `ruff format --check` gate.

**Why I route it (neither senior nor R0-B did):** CLAUDE.md § Scope draws a hard product/dev-harness line ("zero runtime coupling"); `workflow/` is dev-harness. A *product* cycle's landing commit modifying dev-harness source — even format-only — crosses that boundary. The root cause isn't the junior: it's **pre-existing dev-harness format debt + a repo-wide format gate** → every product cycle inherits the cleanup. The junior's options were "reformat (scope-bleed, gate passes)" or "leave it (gate fails)"; (a) was effectively forced.

**Lean γ (accept this instance) + α (future):** accept the bundled reflow here (benign, gate-forced, disclosed); separately normalize the dev-harness format debt in a dedicated **dev-harness** commit (or scope the format gate per-surface) so future product cycles don't inherit dev-harness churn. Low severity — surfaced for the boundary principle + the root-cause fix, not because anything is wrong in the impl.

---

### 🟢 G1 — Y1 resolution (`_append_body` factoring) verified cleaner than the plan
`append()` (`event_store.py:300-303`) calls `_append_body` directly, not through `append_in_transaction` — so the guard never fires on the self-managed path. `validate_metadata` runs in both paths. All 6 `append` callers (incl. `rooms/runtime.py:103`, proxy-Y1's corrected 6th) unaffected. Better-factored than the plan's "thin wrapper" phrasing (which would have raised — that's Y1).

### 🟢 G2 — Independent insight: the Y9 UNIQUE closes a check-then-act TOCTOU inside `promote_hypothesis` itself
`get_hypothesis_by_id` + the `status == PENDING` check (`promotion.py:65-71`) run **outside** the `with conn:` transaction; the UPDATE/append/INSERT run **inside** it (lines 99-128). That's a time-of-check-to-time-of-use gap. The reviews framed the Y9 `UNIQUE` on `promoted_from_hypothesis_id` as defense against *future* concurrent writers — but its more immediate value is closing *this function's own* check-then-act window: a racing promoter that passes the status check still hits `IntegrityError` at the VK INSERT. The UNIQUE backstop is load-bearing today, not just forward-compat. (Single-connection P1.6.5 isn't actually concurrent, so no live bug — but the design is correctly robust.)

### 🟢 G3 — `handoff.md` §4.5/§5.8/§10 narrative is thorough + accurate (doc/narrative lens)
§4.5 updates all 4 dataclasses to real types (`HypothesisId`/`RoomId`/`EventId`/`VKId`/`TimestampMs`), names every deferral (`candidate_for_promotion` "written by P1.7+ matcher; no auto-promote"; `contradictions` "VK-to-VK, no producer P1.6.5"; ProjectArchive "推迟至 P1.7+"), and documents promotion atomicity (D11) + lookup signature. §5.8 captures same-SQLite-file + init order + in-place migration. §10 marks `memory/` materialized. Cites ADR-016 D-sections throughout. Faithful to impl + ADR.

### 🟢 G4 — All 17 plan-stage routed findings present + tested (concur senior coverage)
R0-A Y1-6 + proxy Y1-6 + external Y7-11 all in the impl with tests (independently spot-confirmed: `promotion.py` no-conn (ext Y7); `store.py:57` UNIQUE (ext Y9); 7 product-package guards, no `workflow/` (ext Y10/proxy Y4); `Field(pattern=…)` (proxy Y5); existence check (R0-A Y2)). No deferred-scope bleed (Entity stub-only, ProjectArchive/matcher/ground-truth/UI untouched — W-004-2 (c) held).

### 🟢 G5 — Concur senior cleanliness note: dead import + misleading `noqa` at `store.py:222`
`_row_to_vk` opens `from orchestrator.memory.schema import EntityType, VKScope  # noqa: F401 (used via dict)` — neither symbol is referenced (`scope=raw["scope"]` passes a raw str; Pydantic coerces via the field type). The import is dead **and** the `# noqa: F401 (used via dict)` is inaccurate — it suppresses a real F401 (masks the linter). Marginally more than cosmetic (defeats a lint); fold the removal into whichever follow-up touches Y1/Y2.

### 🟢 G6 — `handoff.md` §15 ADR index is stale since ADR-007 — pre-existing doc-debt, NOT a P1.6.5 regression
§15 lists only ADR-001..007; ADR-008..015 (W-001/P1.4/P1.5/P1.6) were **all** never added — the index lapsed at P1.2. ADR-016's absence is consistent with that lapse, not a P1.6.5 miss; the substantive narrative correctly landed in §4.5/§5.8/§10. Flagging the **pre-existing** debt for a future doc-sweep (refresh §15, or retire it in favor of `docs/decisions/` as the canonical index) — explicitly **not** a finding against this cycle.

---

## Verdict

**`needs_architect`** — 0🔴 / 3🟡 / 6🟢.

The impl is high quality: every plan acceptance criterion met, all 17 plan-stage routed findings present + tested, gates green (893), the EventStore split + atomicity model better-factored than the plan, and both runtime interactions surfaced proactively by the junior. No 🔴.

### Routing surface (synthesis across the 3 impl-stage reviews)

- **Y1 (ADR-016 D11 + plan non-functional-as-written)** — **2-way overlap**: senior Y1 + R0-A Y1, both **α(a)** (amend Accepted ADR + plan to match impl + document DML-first contract). R0-B: not flagged (it verified the impl works, didn't check the ADR-text-vs-code). High confidence. My added angle: also note the guard's first-statement/bare-call ambiguity as a forward-amendment hook.
- **Y2 (promotion event omits user_id)** — **divergence**: senior 🟡 + R0-A 🟡 (route, lean α(a) add user_id) **vs** R0-B 🟢 (accept as design choice). 2-of-3 lean route. Architect call: α(a) add `user_id` to event metadata, or (b) accept VK-row-only + inscribe in ADR-016 D3.
- **Y3 (dev-harness scope-bleed)** — **R0-A only** (my scope lens). Lean γ accept-this-instance + α future-cleanup of dev-harness format debt. Low severity.

All three are amendment/contract/scope judgments — none blocks the impl's correctness. Per ADR-008 Amendment 1 (Route B), state advances to `awaiting_architect_decision`; after routing → `awaiting_senior_revision` for any α absorption (ADR-016 + plan amendments + this file's RC-10 bump in the absorption commit).

## Cross-references
- `docs/process/reviews/P1.6.5/plan-vs-impl.md` — senior Y1 (origin) + Y2 (origin) + G9 (scope-bleed disclosure, my Y3) + cleanliness note (my G5).
- `docs/process/reviews/P1.6.5/R0-B.md` — clean; `author="system"` 🟢-note (my Y2 divergence) + all-absorption-verified table.
- `docs/decisions/ADR-016-cross-room-memory-persistence.md` — D11 (Y1 amendment target) + D3 (Y2 amendment target).
- `docs/process/senior-plans/P1.6.5.md` — P1.6.5-2 (Y1 wrapper text).
- Impl sites verified: `core/event_store.py:185-303` (`_append_body`/guard/`append`); `memory/promotion.py:62-132` (no-conn, c→a→b, author=system, TOCTOU+UNIQUE); `memory/store.py:222` (dead import); `handoff.md` §4.5/§5.8/§10 (narrative) + §15 (stale index).
- `CLAUDE.md` § Scope (product vs dev-harness) — Y3 boundary basis.
