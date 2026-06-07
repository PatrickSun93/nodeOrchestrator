---
task_id: P4.6
review: R0-A
stage: impl
reviewer: architect-partner
lens: "dual-lens A (auto-fire safety / over-auth / race) + B (spine no-regression)"
verify_base: "claude/P4.6-impl @ 1f34a3b (commits P4.6-1..7; base b224c40); ADR-040 contract + live impl code re-read this review"
verdict: clean
findings_count: 2
date: "2026-06-07"
---

# R0-A (on impl) — P4.6: COUNTDOWN auto-fire-on-timer

**Dispatch:** architect-partner R0-A impl review of the junior impl (`claude/P4.6-impl`, 6 commits = P4.6-1..7). Verify the impl faithfully realizes **ADR-040 D1–D9** and that the four plan-stage findings absorbed into the contract — **F1** (helper extraction span), **F2** (D6 fresh-window re-arm), **A2** (enabled gates both paths), **F3** (exact-field-set pins) — are *genuinely implemented*, not just nominally present. Two orthogonal lenses (lean dual-lens, roadmap §8): **A** = can the timer fire wrong (HARD / disabled / out-of-window / already-resolved / irreversible / no-live-window / dishonest provenance / fire-after-shutdown); **B** = did the timer regress the spine (gate byte-freeze / no new `LLMPurpose` / executor tier-agnostic / confirm idempotency / t4 appender-guard / no new resolution type / `PENDING_RESOLUTION_TYPES` + snapshot unchanged / opt-in-off byte-identical). **Route nothing** — findings surfaced for the architect.

**Method:** read every load-bearing line against the live impl (not trusting the commit messages or the plan's verify-cites). Ran the canonical gates myself (`ruff check` + `ruff format --check` + `mypy --strict` + `pytest`). Reviewed independently of `R0-B.md` (cross-family independence preserved; `requires_cross_family_review: true`) — synthesis is the architect's step.

**Not relitigated** (ratified `96a9a4d` + Accepted ADR-040, per dispatch): the five DP leans themselves. I checked only whether the **impl honors** them.

---

## What holds (verified clean against live impl)

**The spine is byte-frozen and every ADR-040 decision is realized as written.**

- **Gate byte-freeze + no new `LLMPurpose` (Lens B).** `git diff b224c40..1f34a3b -- autonomy/scoring.py autonomy/emission.py tools/executor.py` is **empty** — `score`/`decide_tier`/`emit_gate_decision` and the executor are untouched. The stamp lands in `tool_dispatch.py:129-160`, in the existing COUNTDOWN/HARD `else`, **after** the tier is decided; `reversibility` is read from the `tools` dict already passed (`:138-139`) — no new data source. No `LLMPurpose` added (slice-diff grep: the only hit is a test comment). The timer **actuates, never decides**. ✓

- **D1 — durable `expires_at` + single in-process sweeper.** `expires_at: TimestampMs | None = None` is additive nullable on `ToolCallPendingMeta` (`event.py:376`); stamped `= pending_ts + window_s*1000` from the *same* `now_ms()` written as the event timestamp (`tool_dispatch.py:131,149` — no skew). The sweeper is a single lifespan-started asyncio task (`app.py:1273-1281`), discovers on the **reader_executor** (`_discover_expired_pendings`, `:326-369`, `:393-396`), actuates each on `writer_executor` via the shared helper (`:397-409`). Discovery never appends → never blocks the writer (ADR-025 D6 reader-liveness). ✓

- **D2 — eligibility gate (COUNTDOWN-only 4a / floor 4b / enabled 4c) + sweeper double-guard.** Stamp iff all three hold (`tool_dispatch.py:132-141`); else `expires_at` stays `None`. The sweeper independently hard-guards `meta.tier != "countdown_confirm"` → skip (`app.py:350`) **and** `meta.expires_at is None` → skip (`:352`), so a HARD pending is structurally unreachable by the timer **even if** a deadline were somehow stamped. Two independent guards, both test-pinned (`TestHardNeverFires::test_hard_expires_at_always_none` with `floor=0` so only the *tier* guard can stop the stamp; `::test_discover_skips_hard_pending` plants a HARD pending *with* a past `expires_at` and asserts 0 candidates). ✓

- **D3 / F1 — shared writer-helper, steps 2–5, both guards inside.** `_writer_approve_helper` (`app.py:231-323`) contains the **room-state gate** (`:250-254`), the **position-anchored still-pending check** (`:274-281`), the agent-authored **reconstruct** (`:285-302`), **execute** (`:308-319`), and **bus-publish** (`:322`) — all on `writer_executor`. The HTTP approve path **delegates** to it (`:1063-1076`); it does **not** re-implement either guard. The sweeper calls the same helper (`:397-409`), so the **writer-side still-pending re-check is genuinely the sole TOCTOU guard** (the reader discovery at `:362-367` is an explicit *approximate* pre-filter) and the closed-room rejection is genuinely *inherited*, not duplicated. The cancel branch keeps its own inline guards (`:1008-1061`) — correct: ADR-040 D3 extracts "steps 2–5 **minus the cancel branch**," and cancel is never shared with the sweeper. **F1 is implemented exactly as the contract demands** — the reconstruct-only-tail anti-pattern the plan-stage finding warned against did not happen. ✓

- **D3 — caller-agnostic outcome contract.** The helper returns a discriminated `_ApproveOk | _ApproveSkipped | _ApproveFailed` (`:217-228`). HTTP maps `_ApproveSkipped → _ConfirmAppendError` (422) and `_ApproveFailed → _ConfirmExecuteError` (`:1074-1076`); the sweeper **log+skips** every non-OK outcome and never lets it surface as an unhandled task exception (`:410-430`). ✓

- **D4 — honest provenance.** `approval_source: Literal["human","auto_timer"] | None = None` is a **distinct** additive field on `ToolCallMeta` (`event.py:218`), not polluting the bare-`<user_id>` `approver_user_id` namespace. The HTTP path passes `"human"` (`app.py:1067`), the sweeper `"auto_timer"` (`:405`); the helper writes both (`:299-300`). Auto-fire records `approval_source="auto_timer"`, `approver_user_id=None` → audit reads "executed BY TIMER, no human approver," never a legacy-colliding null. The `TOOL_CALL` stays `agent:<initiating_agent>`-authored (`:292`). Pinned: `TestProvenance::test_writer_approve_helper_sets_auto_timer` asserts both fields. ✓

- **D5 — inherited idempotency, no new mechanism.** No new event type; `PENDING_RESOLUTION_TYPES` untouched (slice-diff confirms); no snapshot file in the slice; no expiry-clear (immutable under the append-only store). The still-pending check is the sole correctness guarantee. Pinned: `TestIdempotency::test_double_sweep_no_duplicate` (second fire → `already_resolved`, exactly one `TOOL_CALL`) + `::test_human_cancel_then_timer_noop` (HTTP cancel, then timer → `already_resolved`). ✓

- **D6 / F2 — restart re-arm branches on the *arming event*, not the deadline.** `_discover_expired_pendings` (`app.py:354-358`):
  ```
  if evt.timestamp >= server_start_ms:  effective_deadline = meta.expires_at          # this process
  else:                                 effective_deadline = server_start_ms + window  # prior process → fresh full window
  ```
  This is the **F2-corrected** formula (branch on `pending_event.timestamp`), not the narrower `expires_at >= server_start_ms` derivation the plan-stage finding flagged — **any** restart-interrupted window (armed by a prior process), regardless of whether its original deadline elapsed during downtime, gets a fresh full window. `server_start_ms = now_ms()` is captured **once** at lifespan start (`:1276`). Both branches exercised: `TestBootRearm::test_prior_process_pending_gets_fresh_window` (prior-process, elapsed deadline → 0 candidates) + `::test_current_process_pending_uses_original_deadline` (current-process, expired → fires). ✓ *(See N2 for an optional test-strengthening on the partial-downtime sub-case.)*

- **D7 / A2 — opt-in OFF; `enabled` gates BOTH paths.** `CountdownAutoFireConfig` defaults `enabled=False` (`config.py:39`); absent file / absent section / empty file → default disabled, malformed / unknown-field / non-mapping → `ValueError` refuse-start (`config.py:42-57`, all eight cases tested in `tests/autonomy/test_config.py`). `enabled` gates the **stamp** path (`tool_dispatch.py:134-136`) **and** the **fire** path — the sweeper is started *only* `if ctx.countdown_auto_fire.enabled` (`app.py:1275`). So a deadline stamped during a prior enabled run cannot fire after disable+restart (config loads disabled → sweeper never starts). **A2 satisfied via the "not-started-when-disabled" arm** the ADR sanctions; the config is load-once-immutable per process, so there is no within-process toggle the start-gate would miss. Opt-in-off byte-identical is proven by the unchanged `tests/api/test_confirm.py` passing in the full green suite. ✓

- **D8 — `RB-AUTOFIRE` + amendments inscribed honestly (P4.6-7).** The three amendments are **annotations** (P4.5 `[Annotated … Accepted …]` form), not rewrites: ADR-005 (COUNTDOWN *consequence* gains a timer; `decide_tier` byte-frozen; HARD never), ADR-025 D6 (bounded background-task surface beside the single writer; discover-on-reader / actuate-on-writer; two-connection model unchanged), ADR-030 D4 (deferral **landed**) and — the load-bearing one — **ADR-030 D7(c) conditionally inverted**: explicitly "remains fully true when auto-fire is OFF (the default)," bounded three ways when ON, "inscribed honestly in ADR-040 D8 as `RB-AUTOFIRE`, not softened." Matches P4.6-7 acceptance (2) verbatim. ✓

- **D9 — room-enumeration read API.** `EventStore.list_room_ids()` (`event_store.py:394-401`) — read-only `SELECT id FROM rooms ORDER BY created_at ASC`, `[]` on empty. Tested empty / populated / read-only (`tests/core/test_event_store.py`). ✓

- **F3 — the exact-field-set pins genuinely exist now.** `tests/core/test_constitution.py` adds `test_constitution_tool_call_pending_meta_field_set_pin` (`set(model_fields) == {tool_name, call_id, params, tier, initiating_agent, expires_at}`) and `test_constitution_tool_call_meta_field_set_pin` (`== {tool_name, call_id, params, approver_user_id, approval_source}`) — both fail on **missing or extra**, the real lock the prior `event.py` docstring overstated. The docstrings were corrected to point at the constitutional test. ✓

- **Clean shutdown (Lens A).** Lifespan teardown cancels the task and `await`s it under `suppress(CancelledError)` **before** `ctx.shutdown()` (`app.py:1285-1290`); the sweeper re-raises `asyncio.CancelledError` ahead of its broad `except Exception` (`:431-432`) so cancellation is not swallowed. Pinned: `TestSweeperShutdown::test_sweeper_cancels_cleanly` (asserts `CancelledError` propagates — would fail if the broad except ate it). No fire-after-shutdown, no pending-task warning. ✓

**Gates (run this review):** `ruff check` → *All checks passed*. `mypy --strict` → *Success, no issues in 278 source files*. `pytest` (full suite) → ran to **100%, all-dots, 0 failed / 0 errored** (two pre-existing `PytestUnhandledThreadExceptionWarning`s from `tests/tools/test_net_trust.py`'s DNS-timeout daemon thread — warnings, not failures, unrelated to P4.6). P4.6's four test files: **70 passed**.

This is a faithful, high-quality impl: it realizes every ADR-040 decision as written and lands the four absorbed findings (F1/F2/A2/F3) exactly. The findings below are precision/hygiene, **neither blocking, neither a spine violation, neither requiring an architect routing decision**.

---

## Findings

### 🟡 N1 — Four P4.6-touched files fail `ruff format --check` (cosmetic; net-new code should pass the format gate)

**Where:** `src/orchestrator/api/app.py`, `src/orchestrator/autonomy/config.py`, `src/orchestrator/core/event.py`, `tests/api/test_auto_fire.py`.

`uv run --extra api ruff format --check` reports these four would be reformatted. The delta is **purely cosmetic line-wrapping** (e.g. collapsing `field(default_factory=CountdownAutoFireConfig)` and a multi-line `raise ValueError(...)` onto one line) — `ruff check` (lint) and `mypy --strict` both pass, so there is **zero correctness or spine impact**. Two of the four (`config.py`, `test_auto_fire.py`) are net-new files, so this is partly P4.6-attributable; however the repo also carries **34 other pre-existing** files that fail `ruff format --check` (including a hunk at `event.py:425` `_AUTHOR_PATTERN`, *outside* the P4.6 diff), so whole-tree `ruff format --check` is **not currently a clean/enforced gate** — this is not a regression of an otherwise-green gate.

**Surface (mechanical pre-merge fix — no architect decision needed):** the junior should run `uv run --extra api ruff format` on the four files before the landing commit / merge, so net-new P4.6 code satisfies the stated `ruff format` gate (contributing.md §gates). I did not apply it myself (R0-A reviews; the junior implements). Does not affect the `clean` verdict.

### 🔵 N2 (advisory) — D6 boot-rearm test pins the safety floor but not the F2 fresh-window-vs-tail distinction

**Where:** `tests/api/test_auto_fire.py::TestBootRearm::test_prior_process_pending_gets_fresh_window`.

The **impl is correct** — `_discover_expired_pendings` branches on `evt.timestamp` (`app.py:354-358`), the F2-ratified fresh-full-window formula (verified above). But the test that guards it uses `old_expires = old_ts + window` with `old_ts = now - 1000s` (deadline already *elapsed* during downtime, `old_expires < server_start_ms`). In that configuration **both** the implemented `evt.timestamp` branch *and* the rejected `expires_at` branch yield "fresh window → no fire," so the test would pass under either formula — it pins the safety property (prior-process pending doesn't fire immediately) but does **not** lock the specific F2 fix against a future regression to the narrower derivation.

**Surface (optional regression-guard, no design change):** a partial-downtime case — `evt.timestamp < server_start_ms` **AND** `expires_at >= server_start_ms` (restart mid-window, deadline survives) — would distinguish the two formulas: the `evt.timestamp` branch re-arms a fresh window (no fire), the `expires_at` branch fires at the surviving tail. Adding it would make F2 test-enforced. Low value-add; the code is already correct and the constitutional intent (no fire without a live window) is covered. Optional — flagging for completeness, not as a defect.

---

## Verdict

**clean** — the impl faithfully realizes ADR-040 D1–D9; all four absorbed findings (**F1** helper steps 2–5 with both guards inside + HTTP-delegates / sweeper-inherits; **F2** D6 branch on `evt.timestamp` fresh-full-window; **A2** `enabled` gates both stamp + fire; **F3** both exact-field-set constitutional pins) are genuinely implemented. The spine is preserved (gate/emission/executor byte-frozen, no new `LLMPurpose`, `PENDING_RESOLUTION_TYPES`/snapshot/resolution-types unchanged, t4 appender-guard intact, opt-in-off byte-identical) and the human-out-of-loop residual `RB-AUTOFIRE` is inscribed honestly across ADR-030 D4/D7(c) + ADR-005 + ADR-025. Canonical gates green (`ruff check` ✓, `mypy --strict` ✓, `pytest` 100% / 0 failed). **N1** is a mechanical pre-merge `ruff format` fix on net-new files (cosmetic, no architect decision needed); **N2** is an optional advisory test-strengthening. **No spine violation, nothing blocking, nothing to route.**

*Reviewed independently of `R0-B.md` (cross-family independence preserved; synthesis is the architect's step).*
