# External R0-B prompt — P4.6 (COUNTDOWN auto-fire-on-timer — the first human-out-of-loop execution) — lean dual-lens

> **Dispatch context.** `requires_cross_family_review: true` (ratified; P4-roadmap §8 — lean dual-lens). You are the **cross-family** reviewer (DeepSeek via the role-rewriting proxy). This is the **plan-stage** prompt; the architect dispatches it at **impl stage** against the impl branch. P4.6 gives the `COUNTDOWN_CONFIRM` tier **auto-fire-on-timer**: after a configured window with no human action, the system **executes the gated call itself**. This is the **opposite** of the trust surface ADR-030 built — ADR-030 D7(c) listed *"COUNTDOWN has no server-side auto-fire (no headless execution)"* as a **probed trust invariant**, and P4.6 **conditionally inverts it** for the COUNTDOWN tier when an operator opts in. Everything before P4.6 kept a human in *every* execution loop; P4.6 introduces the first **human-out-of-loop** execution, bounded three ways (COUNTDOWN-only, reversibility-floored, opt-in default OFF) and inscribed as the honest residual `RB-AUTOFIRE`. **Your job is to find where the timer fires something it must never fire / fires when it must not / over-authorizes (Lens A), or where adding the timer silently broke the existing confirm/gate/executor constitution (Lens B).** These two lenses are genuinely orthogonal — "auto-fire is unsafe / over-authorized" vs "auto-fire regressed ADR-005/028/030."

---

## Your stance

Take a deliberately **outside-Claude** lens. Over-correct for Claude's biases: trust-the-types-means-trust-the-runtime, "there's a guard in the code therefore the invariant holds at runtime," over-engineering, agreeableness, "the sweeper checks the tier therefore HARD can't fire." **Trace failure modes across the gate → pending record → sweeper → writer helper → executor → event chain** and ask: "what happens when the server restarts mid-window / crashes repeatedly within each window / a HARD pending somehow carries an `expires_at` / the config is malformed / two sweeps overlap / a human cancels exactly as the timer fires / the room closes between discovery and fire / an irreversible op sits on COUNTDOWN / the marker is a silent null / the sweeper isn't cancelled on shutdown?" Default to **refuted/skeptical** when uncertain; a finding you can't substantiate by tracing the code is not a finding. Cite `file:line` or `artifact §`.

## Artifact bundle — read from disk (in-repo dispatch)

Read in full:
1. `docs/process/architect-briefs/P4.6.md` — the decision-surface (5 DPs + leans + the §6 watch-list + the §5 two-lens design).
2. `docs/process/senior-plans/P4.6.md` — the plan (atomics P4.6-0..7 + the §5 two senior pre-investigation findings).
3. `docs/decisions/ADR-040-countdown-auto-fire-on-timer.md` — the proposed ADR (D1–D9 + the `RB-AUTOFIRE` residual + the two append-only/no-room-listing store invariants it is built around).

Plus the live substrate it threads (probe claims against the working tree):
- `src/orchestrator/agents/tool_dispatch.py` (`process_tool_calls` — the COUNTDOWN/HARD `else` `:126-154`; where `expires_at` is stamped + the eligibility gate).
- `src/orchestrator/agents/dispatch.py` (`:150-163` — the call site + how the auto-fire config threads in).
- `src/orchestrator/autonomy/scoring.py` (`AutonomyTier`/`decide_tier` `:11-16,165-207` — must be **byte-frozen**; reversibility-only, no timer).
- `src/orchestrator/api/app.py` (`_post_confirm` `:734-867` — the closure C1 extracts/reuses; `writer_executor` `:316`; `lifespan` `:1054-1062` — the sweeper start + clean shutdown; `AppContext`/`_build_context` `:100-145` — the config field + load).
- `src/orchestrator/core/event.py` (`ToolCallMeta`+`approver_user_id` `:203-218`; `ToolCallPendingMeta` `:351-365` — the new `expires_at`; `PENDING_RESOLUTION_TYPES` `:401-408`; `now_ms` `:33-35`).
- `src/orchestrator/core/event_store.py` (the **append-only** triggers `:78-90`; `get_room`/`get_room_events` `:358-382` + the new room-enumeration read method).
- ADR-030 (D1/D3/D4/D7(c) + Consequences L104-106), ADR-005 (D4/§5(c)), ADR-028 (D2/D6), ADR-039 (D5/D6), ADR-025 (D6).

---

## Lens A — AUTO-FIRE SAFETY / OVER-AUTHORIZATION / RACE (the "headless execution done wrong" adversary)

Can the timer fire something it must never fire, fire when it must not, or over-authorize? Trace each:

1. **HARD never auto-fires (the spine invariant — ADR-040 D2/4a).** A HARD pending must be **structurally unreachable** by the timer. Trace: is `expires_at` provably `None` for `tier == hard_confirm` at every stamp site (`tool_dispatch.py`)? Does the sweeper *additionally* hard-guard `tier == countdown_confirm` (defense-in-depth)? Is there **any** path — a malformed/forged pending record, a future caller of the helper, a config edge — by which a HARD call acquires a deadline or reaches the fire? Is the constitutional test real (does it *fail* if the guard is removed, or is it vacuous)?
2. **Fires only when enabled + only within/after the window (D2/4c, D1/D7 runtime gate).** With auto-fire **OFF** (the default — absent config), is **no** `expires_at` ever stamped and is the sweeper inert (or unstarted)? Can a stale `expires_at` stamped during a *previous enabled run* fire after the operator disables — **including across a restart** (the sweeper must be gated on `enabled` at **runtime**, not only at stamp time: not-started-when-disabled, or re-checks before each fire — D1/D7, R0-B-on-plan A2)? Does the fire trigger strictly at `effective_deadline` (D6) — not early?
3. **The reversibility floor actually bounds the irreversible tail (D2/4b).** COUNTDOWN ≠ reversible (ADR-005 §5(c): `git_push` rev=1 → COUNTDOWN). Trace: is `reversibility` read from the same `tools` map the gate uses, and is a COUNTDOWN call with `reversibility < floor` left **`expires_at = None`** (degraded to explicit-confirm, waits for a human)? Can an **irreversible** op ever headless-fire? Is the floor code/config (not an LLM judgment)?
4. **Idempotency under the timer-vs-human race (D5, inherited).** Trace: early human approve/cancel during the window → does the later timer fire hit `already_resolved` and no-op (≤ one `TOOL_CALL`)? The simultaneity instant (human approves exactly as the timer fires) — both on `writer_executor` (`max_workers=1`): exactly one winner? Two overlapping sweeps (a slow fire + the next tick) — can the same pending fire twice? Is the still-pending check position-anchored after the pending event, keyed on `PENDING_RESOLUTION_TYPES` + `call_id` (never on the new `approval_source`/`expires_at`)?
5. **Restart / crash semantics — never fire without a live cancel window having existed (D6 / DP1″-ii, architect-ratified fresh-full-window).** Trace the boot re-arm: the branch is on **whether the pending was armed by *this* process** — `effective_deadline = expires_at if pending_event.timestamp ≥ server_start_ms else server_start_ms + window_s*1000`. So **any** pending armed by a *prior* process (`pending_event.timestamp < server_start_ms`) — i.e. every restart-interrupted window, whether or not its original deadline had elapsed — must be re-armed to a **fresh full window** and must **not** fire on the first post-boot sweep. Could a window that elapsed (wholly or partly) before boot fire immediately, or fire on a shrunken residual window (the failures the fresh-full-window re-arm prevents)? Is the branch on the **arming event's timestamp** (not on `expires_at` vs `server_start_ms` — the narrower deadline-branch R0-A-on-plan F2 rejected)? Is `server_start_ms` captured once at lifespan start (not per-sweep)? The over-conservative tail (a sustained restart loop re-arms every boot → defers the fire indefinitely) — is it inscribed as a residual, not a silent bug?
6. **The no-human-approver fact is recorded honestly (D4 — the honesty crux).** Trace: does an auto-fired `TOOL_CALL` carry `approval_source="auto_timer"` + `approver_user_id=None` (never a **silent** null that collides with pre-P4.5 legacy `None`)? Does the human path carry `approval_source="human"`? Is `RB-AUTOFIRE` (ADR-040 D8) the **real** surface, un-softened — does it honestly say "no account at all actuates within the window; the human-in-loop moment moved to config-time"?
7. **Fire into a closed/transitioned room, or a boundary escalation (inherited D3 / ADR-030 D3 step 2).** Trace: a COUNTDOWN whose room **closed** between discovery and fire — does the helper's room-state gate reject it (closed → no fire)? Can the auto-fire path **escalate** beyond the configured boundary (fire a non-COUNTDOWN, fire with no floor, fire when disabled) anywhere?
8. **Clean shutdown.** Is the sweeper task **cancelled** in lifespan teardown (no fire-after-shutdown, no "Task was destroyed but it is pending")? Can a fire be in-flight on the writer as the executor tears down?

## Lens B — SPINE NO-REGRESSION (the "did the timer break the existing constitution" adversary)

Does adding the timer **regress** an invariant the prior ADRs established? Trace each:

1. **The gate decision logic is byte-frozen (ADR-040 D2 / roadmap §10).** `score`/`decide_tier`/`emit_gate_decision` (`autonomy/scoring.py:165-207`, `autonomy/emission.py`) must be **untouched** — the timer **actuates, never decides**. Trace: does the eligibility-gate stamp run strictly *after* the tier decision, never altering it? Is the tier still reversibility-only (no timer/window input)? **No new `LLMPurpose`** anywhere on the auto-fire surface (grep)?
2. **Confirm idempotency + human path preserved after the helper extraction (ADR-030 D7).** P4.6-4 extracts `_post_confirm`'s approve branch into a shared helper. Trace: is the HTTP confirm path **behavior-identical** post-extraction (the position-anchored still-pending check, the agent-authored reconstruct, the partial-turn `stage` envelope, the `approver_user_id` from principal, the bus-publish — all byte-equivalent)? Did the refactor change any response or error path?
3. **The executor is unchanged + tier-agnostic (ADR-028).** Trace: does `execute_pending_tool_calls` see any auto-fire-specific input? Is the `call_id` double-exec guard (idempotency layer 2) intact? Does the auto-fire path reach the executor by the **same** call shape as the human path?
4. **The t4 appender-guard holds (ADR-028 D6 / ADR-030 D1).** The `TOOL_CALL` appenders must stay **two** (HTTP-confirm + timer-confirm), each **downstream-of-gate**. Trace: does the auto-fire append reconstruct `{tool_name, call_id, params, author}` **only** from the persisted `ToolCallPendingMeta` — never inventing a call, never reading a request? Does the new actuation surface re-open the "who may append a `TOOL_CALL`" invariant?
5. **`PENDING_RESOLUTION_TYPES` + the snapshot derivation unchanged (ADR-030 D2/D7, ADR-039 D6).** The timer appends an **ordinary `TOOL_CALL`** (already a resolution) — trace: is **no new resolution event type** added? Does the snapshot/still-pending derivation see anything new? Do the additive fields (`expires_at`, `approval_source`) leak into the still-pending scan (they must not — it keys on type+call_id)?
6. **Backward-compat: opt-in-OFF ⇒ byte-identical to today (ADR-040 D7).** Trace: with no config file, are `expires_at`/`approval_source` **never set and never inspected** on any existing path? Does the existing confirm suite pass unchanged? Do the additive nullable fields break any existing `ToolCallMeta`/`ToolCallPendingMeta` consumer / constitutional schema test (the docstrings say the field set is "locked by the constitutional test" — was the test *extended*, not bypassed)?
7. **The new background-task + read surface respects ADR-025 D6.** Trace: does the sweeper **discover on the reader path** and **actuate on the writer** (a multi-second `run_turn` holding the writer must not block discovery; discovery must never append)? Does the new room-enumeration method run read-only (no `check_same_thread` violation, no write)? Is there a half-fire crash window worse than the one ADR-030 D7 already inherits?

---

## NOT IN SCOPE to re-raise (architect-decided / constitutional — probe whether the DESIGN honors them, do not relitigate)

- **DP1(b) durable `expires_at` + in-process sweeper; (a) per-pending in-memory timer + (c) external scheduler REJECTED** — architect-ratified. Probe the durability/restart story, **not** whether to use an external scheduler.
- **DP1″ re-arm (ii) (expired-during-downtime → fresh window); (i) fire-immediately + (iii) leave-for-human REJECTED** — architect-ratified. Probe the re-arm is correct + conservative, **not** the posture choice.
- **DP2(a) reuse the confirm closure; DP2b(i) `approver_user_id=None` + positive `approval_source` marker; (ii) sentinel principal REJECTED** — architect-ratified. Probe the reuse preserves the spine + the marker is honest, **not** whether to use a sentinel.
- **DP3 inherited (writer-serialized + position-anchored still-pending; NO new resolution event type)** — architect-ratified. Probe the inheritance actually covers the race.
- **DP4(a) COUNTDOWN-only/HARD-never; (4b) reversibility floor (over fire-all); (4c) opt-in default OFF; (4d) inscribe `RB-AUTOFIRE`** — architect-ratified. Probe each bound holds + the residual is honest, **not** whether to weaken/strengthen the boundary. (A *per-tool opt-in* `auto_fire_eligible` is a noted compatible future extension, not this slice.)
- **DP5 new ADR-040; amend ADR-030 D4/D7(c); annotate ADR-005 / ADR-025 D6** — architect-ratified. Probe the amendments are honest (D7(c) annotated-not-deleted: true-when-OFF, bounded-when-ON), **not** whether to write the ADR.
- **The two senior pre-investigation findings (append-only ⇒ re-arm is a read-time derivation + expiry-clear dropped; new room-enumeration read API)** are senior plan refinements already folded into ADR-040 — if you see a **correctness** problem with the drafted mechanism, raise it as a finding; do not relitigate the refinement.
- **Constitutional:** gate byte-frozen; no new `LLMPurpose`; executor unchanged + tier-agnostic; the executed `TOOL_CALL` agent-authored; events append-only. Probe whether the DESIGN honors them.

## Output

Land at `docs/process/reviews/P4.6/R0-B.md` with YAML frontmatter:

```
---
task_id: P4.6
round: R0-B-cross-family-external
reviewer_family: <deepseek | gpt-5 | gemini | other>
reviewer_model_id: <specific model>
reviews_acked:
  - architect-briefs/P4.6.md
  - senior-plans/P4.6.md
  - decisions/ADR-040-countdown-auto-fire-on-timer.md
verdict: <clean | needs_architect | blocking>
findings_count: { red: N, yellow: N, green: N }
---
```

Per finding: `file:line` (or `artifact §`), the failure mode **traced** (the concrete HARD-fire / fire-when-disabled / irreversible-headless-fire / fire-without-a-live-window / silent-null-provenance / un-honest-residual / boundary-escalation for Lens A; the concrete gate-decision-leak / confirm-idempotency-break / executor-coupling / pierced-appender-guard / new-resolution-type / off-path-regression / writer-blocking-discovery for Lens B), severity (🔴 must-fix / 🟡 should / 🟢 nit), and your confidence. **Route nothing yourself** — the architect routes (α absorb / β defer / γ reject / δ later). A **🔴 only** for a concretely-traced HARD auto-fire, a fire-when-disabled / outside-window / into-a-closed-room execution, an irreversible op firing headless below the floor, a fire without a live cancel window having existed, a silent-null provenance, a gate-decision-logic regression, a pierced appender guard, a confirm-idempotency break, or a sweeper that blocks the writer — not a hypothetical.

**Verdict semantics:**
- `clean` = 0🔴 / 0🟡 / any 🟢 → architect proceeds to Accept ADR-040 + junior dispatch.
- `needs_architect` = ≥1🟡 OR an issue needing routing → architect Decision blocks.
- `blocking` = ≥1🔴 (HARD-fire / fire-when-disabled / irreversible-headless / fire-without-live-window / silent-null / gate-regression / pierced-appender / idempotency-break / writer-blocking-sweeper) → plan + ADR-040 revised before junior dispatch.
