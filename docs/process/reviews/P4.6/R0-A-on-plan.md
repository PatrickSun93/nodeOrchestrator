---
task_id: P4.6
review: R0-A-on-plan
stage: plan
reviewer: architect-partner
lens: "dual-lens A (auto-fire safety / over-auth / race) + B (spine no-regression)"
verify_base: "claude/P4.6-plan @ fa477a5 (plan 9e05b06); live substrate re-read this review"
verdict: needs_architect
findings_count: 3
date: "2026-06-06"
---

# R0-A-on-plan — P4.6: COUNTDOWN auto-fire-on-timer

**Dispatch:** architect-partner R0-A-on-plan on the senior plan (`senior-plans/P4.6.md`) + ADR-040, against the ratified brief (`architect-briefs/P4.6.md`, 5 DP ratified `96a9a4d`). **Route nothing** — findings surfaced for architect routing.

**Method:** verified every load-bearing plan claim against the live substrate this review (not trusting the plan's own verify-cite). Two orthogonal lenses per the lean dual-lens design: **A** = can the timer fire wrong (HARD / disabled / out-of-window / already-resolved / irreversible / no-live-window / dishonest provenance); **B** = did the timer regress the spine (gate byte-freeze / no new `LLMPurpose` / executor tier-agnostic / confirm idempotency / t4 appender-guard / no new resolution type / opt-in-off byte-identical).

**Not relitigated** (ratified `96a9a4d`, per dispatch): DP1(b) durable+sweep, DP4b reversibility-floor, DP4c opt-in-OFF, DP4a COUNTDOWN-only. I checked only whether the design **honors** them. §5 sub-decisions reviewed for correctness only (F2 is one).

---

## What holds (verified clean)

The spine is preserved and the ratified leans are honored. Concretely re-confirmed against live code:

- **Gate byte-freeze (Lens B).** The stamp lands in `tool_dispatch.py` **after** `emit_gate_decision` returns, in the existing COUNTDOWN/HARD `else` (`:126-154`); `scoring.py` `score`/`decide_tier`/`gate` are pure and untouched (`:147-223`), `emission.py` is not on the stamp path. The timer **actuates, never decides**; `reversibility` is read from the `tools` dict already passed (`tool_dispatch.py:65`) — no new data source, **no new `LLMPurpose`** (grep clean). ✓
- **HARD structurally unreachable (4a / Lens A).** The stamp condition requires `tier == COUNTDOWN_CONFIRM`, so a HARD pending carries `expires_at is None`; the sweeper double-guards (`expires_at is not None` structurally + explicit `tier == countdown_confirm`). Two independent guards + the P4.6-6(a) constitutional test. ✓
- **Reversibility floor blocks irreversible headless (4b / Lens A).** `reversibility < floor ⇒ expires_at None ⇒ waits for human`; `ToolMeta.reversibility` defaults to `0` (conservative-low, `scoring.py:42-51`), so an absent/unknown reversibility never auto-fires. ✓
- **Opt-in OFF ⇒ byte-identical (4c / Lens B).** Absent config ⇒ disabled ⇒ no stamp + inert/unstarted sweeper. The additive `expires_at`/`approval_source` fields default `None` and are **never inspected on any existing path** — the still-pending scan keys on `type + call_id` only (`app.py:793-796`, `event.py:211`). Forcing function §4 "run the existing confirm suite unchanged" is a real guard (`tests/api/test_confirm.py` exists). ✓
- **Provenance honest (DP2b / Lens A).** `approval_source: Literal["human","auto_timer"] | None` is a **distinct** field (not polluting the bare-`<user_id>` `approver_user_id` namespace); auto-fire records `approval_source="auto_timer"`, `approver_user_id=None` → audit reads "executed BY TIMER, no human approver," never a silent legacy-colliding null. The `TOOL_CALL` stays `agent:<initiating_agent>`-authored (the helper reconstructs `author=build_author(pending_meta.initiating_agent)`, `app.py:834`). ✓
- **No new resolution type / inherited idempotency (DP3 / Lens B).** The timer appends an ordinary `TOOL_CALL`, already in `PENDING_RESOLUTION_TYPES` (`event.py:401-408`) → resolves the pending with zero ripple into the snapshot derivation. ✓
- **Store invariants the ADR is built on.** Append-only triggers `RAISE(ABORT)` (`event_store.py:78-86`) → `expires_at` immutable → D6 read-time-derivation + D5 drop-expiry-clear are the **correct** consequence. No room-enumeration API exists (`get_room`/`get_room_events` by id only, `:358-392`) → P4.6-5 is genuinely needed. Both senior §5 discoveries are verify-accurate. ✓
- **RB-AUTOFIRE inscribed honestly (DP4d).** ADR-040 D8 reads as honestly as `RB-FS/NET`/`RB-AUTHZ` — "no human in the loop at fire time," "qualitatively beyond `RB-AUTHZ`," bounded three ways. Not softened. ✓

This is a high-quality plan: it honors all five ratified leans, surfaces its own §5 discoveries, and the design is fundamentally sound. The findings below are **precision / posture-confirmation**, not spine breaks. None is blocking.

---

## Findings

### 🟡 F1 — The shared writer-helper extraction boundary is under-specified; the still-pending check + room-state gate **must** be inside the helper (on the writer), or the sweeper loses its TOCTOU guard

**Where:** plan P4.6-4 §What vs §Where; `app.py:769-865`.

**The contradiction.** P4.6-4 **§What** says extract "still-pending check → reconstruct → execute → bus-publish" into the shared writer helper — correct. But **§Where** says "extract from `:826-865`," which is the approve reconstruct/execute/publish **only** — it starts *after* the still-pending check (`:791-799`) and *after* the room-state gate (`:769-771`). Acceptance (4) (early human approve/cancel ⇒ later timer fire is `already_resolved` no-op) and (9) (fire into a closed room rejected, "**inherited via the helper**") both require those two guards to be **inside** the helper.

**Why it matters (correctness, not just tidiness).** The sweeper **discovers on the reader path** and **actuates on the writer** (ADR-040 D1). The reader-side discovery is necessarily stale — a human can `cancel`/approve in the gap between discovery and the writer append. The **only** thing that makes that TOCTOU-safe is the still-pending **re-check on the writer**, exactly as the HTTP path does it (`:791-799`, on `writer_executor`). If the junior anchors on §Where (`:826-865`) and extracts a reconstruct-only helper, the still-pending check stays in the HTTP handler and the sweeper either (a) double-fires a just-cancelled call, or (b) re-implements the check on the sweeper side → duplicated mechanism, which **defeats the DP3 "inherited, no new mechanism" claim** (a Lens-B regression). Same logic for the room-state gate (closed-room rejection can't be "inherited" if it's outside the helper).

**Also under-specified — the helper's true signature + error contract.** The plan names only the *new* params (`approval_source`, `approver_user_id`). The helper structurally also needs `rid`, the **target pending id** (HTTP: `body.pending_event_id`; sweeper: the discovered pending), and `loop` (for the `call_soon_threadsafe` bus-publish, currently closed over from the async handler, `app.py:756,864`). And the current closure raises HTTP-coupled `_ConfirmAppendError`/`_ConfirmExecuteError` (→ 422 via exception handlers); for the **sweeper** `already_resolved` / `room_closed` / `not_found` are **benign skips**, not errors — the helper's outcomes must be consumable by both callers (HTTP → 422; sweeper → log+skip, never an unhandled exception in the asyncio task).

**Surface (architect routes).** Pin the extraction span to the writer closure **steps 2–5 of the approve path** (`~:769-865` minus the cancel branch): room-state gate + still-pending check + reconstruct + execute + publish, all on `writer_executor`. Signature `(rid, pending_event_id, approval_source, approver_user_id, loop)`; outcome contract caller-agnostic. Self-correcting via acceptance (4)/(9) if the junior reads §What as authoritative — but the §Where pointer should be corrected so it can't mislead. *Lean: tighten in plan (senior-revision) before junior dispatch; cheap, removes the only real correctness ambiguity.*

---

### 🟡 F2 — D6 boot re-arm is **narrower** than the ratified "re-arm a fresh window" (DP1″-ii); the senior's "equivalent in posture" §5 claim holds on the safety floor but not the liveness generosity

**Where:** ADR-040 D6; senior plan §5 #1.

**The ratified lean.** DP1″ = **(ii) re-arm a fresh window** — brief: "give the operator the cancel window they 'lost' … no call fires without a live cancel window having existed."

**What D6 actually does.** Because `expires_at` is immutable, re-arm is a read-time derivation:
```
effective_deadline = expires_at                          if expires_at >= server_start_ms
                     server_start_ms + window_s*1000      otherwise           # re-armed
fire when: now_ms() >= effective_deadline AND still-pending AND tier == countdown_confirm
```
So a **fresh full window is granted only when the deadline fully elapsed during downtime** (`expires_at < server_start_ms`). In the **partial-downtime** case (server restarts mid-window, `expires_at >= server_start_ms`) it fires at the **original** `expires_at` — giving only the *residual* window `[server_start_ms, expires_at]`, which near the boundary shrinks toward one sweep tick (and at the exact-ms boundary `expires_at == server_start_ms`, `effective_deadline == server_start_ms` → the first post-boot sweep fires, post-boot live window ≈ time-to-first-sweep).

**Why it matters.** The architect's **safety floor** ("no fire without a live cancel window having existed in some running process") is satisfied — fire is gated on the sweep cadence, so there is always ≥ ~one `sweep_interval` of post-boot cancel-ability before any actuation. But the **liveness generosity** of "re-arm a *fresh* window" is **not** honored in the partial-downtime case: the operator gets the surviving tail, not a fresh window. The senior's §5 #1 states D6 is "**equivalent in posture** to the brief's lean" — that overstates it: it is equivalent on the safety floor, **divergent on the generosity** (a partial-downtime restart that lands just before expiry leaves a near-zero residual window rather than a fresh one).

**Surface (architect posture-confirm).** Is the narrowed re-arm intended (fire-at-original-deadline whenever the deadline survives the restart), or should **any** restart-interrupted window (i.e., armed by a *prior* process) re-arm a fresh full window? Both are safe; they differ only in how much live cancel time a mid-window restart preserves. This is the same `RB-FS/NET`-class posture call DP1″ was — worth one explicit architect confirmation rather than inheriting it silently through the read-time mechanism. *(D6 already inscribes the repeated-crash deferral residual honestly; this is the one un-surfaced sub-case.)*

---

### 🔵 F3 (advisory) — "Field set is locked by the constitutional test" overstates the existing lock for `ToolCallPendingMeta` / `ToolCallMeta`; add a real exact-field-set pin in P4.6-6

**Where:** `event.py:358` docstring + plan P4.6-2 §Where; `tests/core/test_event.py:640-697`; `tests/core/test_constitution.py:55,64,111`.

`TestToolCallPendingMeta` enforces `extra="forbid"` + per-field validity, but has **no** `set(Model.model_fields) == {…}` assertion — so adding `expires_at` (a *defined* field) will **not** fail any existing test, and the plan's "the test is extended, not bypassed" framing implies a lock that isn't there. The genuine exact-set pin exists only for `DecisionTrace`/`AutonomyDecisionMetadata`/`AutonomyRefusalMetadata` (`test_constitution.py`). The plan's *outcome* is right (P4.6-2(6)/P4.6-6 add positive presence/absence-per-tier coverage). **Recommendation:** in P4.6-6 also add an exact-field-set assertion for `ToolCallPendingMeta` **and** `ToolCallMeta` (mirroring the `DecisionTrace` pattern) — this genuinely pins the additive `expires_at`/`approval_source` fields, makes the "never inspected on existing paths" claim test-enforced, and catches future drift. Low severity; no design change.

---

## Verdict

**needs_architect** — the design is sound and honors every ratified lean; the spine (gate byte-freeze, no new `LLMPurpose`, executor tier-agnostic, inherited idempotency, no new resolution type, opt-in-off byte-identical, honest `RB-AUTOFIRE`) is preserved. Two routable findings: **F1** (pin the helper extraction span so the sweeper's TOCTOU/closed-room guards are genuinely *inherited*, not duplicated — a senior-revision tighten) and **F2** (confirm whether the narrowed D6 re-arm matches the ratified "fresh window" posture — an architect posture-confirm). **F3** advisory. Nothing blocking; no spine violation. ADR-040 Accept can proceed once F1/F2 are routed (F2 may want a one-line D6 confirmation/annotation either way).

*Reviewed independently of `R0-B-on-plan.md` (cross-family independence preserved; synthesis is the architect's step).*
