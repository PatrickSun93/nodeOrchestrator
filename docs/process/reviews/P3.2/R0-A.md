---
task_id: P3.2
round: R0-A
stage: impl
reviewer: architect-partner
impl_commit: fa5aa18
lens: single
verdict: needs_architect
findings_count:
  red: 0
  yellow: 1
  green: 12
verdict_history:
  - verdict: needs_architect
    at_commit: fa5aa18
    findings_count: { red: 0, yellow: 1, green: 12 }
    note: >-
      Initial impl-stage R0-A (in-family, single-lens — the dual-lens R0-B re-runs on the impl in
      parallel, requires_cross_family_review: true). Reviewed the api/ package vs ADR-025 + plan +
      Q1-Q5 in an isolated worktree at fa5aa18, with active plant-bypass verification of the forge
      boundary. Exemplary new-infra impl — the constitutional/security spine holds and all four
      plan-stage α-folds landed, each discriminatingly tested. Spine: (1) forge-prevention is
      fail-closed at TWO layers — IntentRequest has no author/id/timestamp + extra="forbid" rejects
      them at parse; the allowlist check + validate_metadata run before any I/O (422); author is
      hardcoded "user". Plant-bypass tests confirm it: author:system / id / agent_id fields → 422;
      off-allowlist STATE_TRANSITION/AUTONOMY_DECISION/UTTERANCE/TOOL_CALL → 422; bad typed-metadata
      → 422; with USER_INPUT/RETRACTION/valid-DECISION controls → 200. (2) backend-authoritative —
      the intent path is exactly append(user_event) + run_turn; no LLMPurpose added (9 unchanged,
      only a comment in api/); select_model_and_provider appears ONLY in the decision-free
      llm_adapter; no should_agent_speak/next_room_state/decide_agents/scoring in api/. α-folds:
      Y1 subscribe-then-replay+dedup (subscribe-first, replay, replay_complete, live with sent_ids
      dedup — tested no-dup + e2e); Y2 separate WAL read connection + read-only executor (reader vs
      writer executor — tested GET completes <0.25s while the writer is busy with a turn); Y3
      partial-turn error envelope (append-stage 422 no-id vs turn-stage 500 + appended_event_id —
      both stages tested, store-consistent); arch-Y1 allowlist kept (UTTERANCE excluded) + a test
      proving DECISION{promotion:true} appends but reaches NO promotion path (per R0-B G3). Wire raw
      (状态机不暴露 → GUI). Contract pinned + OpenAPI committed + drift-tested. pubsub bounded/
      drop-slow/loop-confined. wrap-don't-reimplement: only net-new api/ + the optional [api] extra;
      core/rooms/autonomy/llm unchanged. Gates green WITH --extra api (ruff/format/mypy 187-files-
      clean/pytest 100%). One LOW 🟡 (Y1): the canonical gates REQUIRE the [api] extra (without it,
      mypy on api/ + tests/api collection fail with import-not-found); no CI/contributing change in
      the diff installs it — confirm the gate/CI does. Process/landing, not an impl defect. Did NOT
      advance state.
---

# P3.2 R0-A (architect-dispatched post-impl review, in-family, single-lens, plant-bypass)

| Field | Value |
|---|---|
| Round | R0-A impl-stage (in-family; the **dual-lens R0-B re-runs on the impl in parallel**, `requires_cross_family_review: true`) |
| Impl | `claude/P3.2-impl` @ `fa5aa18` (P3.2-1..5: contract pin → read+bootstrap → WS/pubsub → intent/forge → failure-modes+landing) |
| Artifacts | `src/orchestrator/api/{wire,app,pubsub,llm_adapter,__main__}.py` + `openapi.json`/`asyncapi.md` + `tests/api/*` vs ADR-025 + plan + Q1–Q5 |
| Reviewed at | isolated worktree `/tmp/p32-impl` @ `fa5aa18` (shared tree had concurrent branch-switching — RC-7 isolation) |
| Gates | re-run in-worktree **with `--extra api`**: **ruff ✅ · format ✅ · mypy canonical (187 files) ✅ · pytest full (100%) ✅** |

## Verdict: needs_architect — 0🔴 · 1🟡 · 12🟢

> **Exemplary new-infra impl.** The constitutional/security spine holds and **all four plan-stage α-folds landed, each discriminatingly tested.** I ran active **plant-bypass** verification of the forge boundary (the architect's emphasis): a client cannot set `author`/`id`/`timestamp` (schema `extra="forbid"` → 422), cannot post an off-allowlist type (`STATE_TRANSITION`/`AUTONOMY_DECISION`/`UTTERANCE`/`TOOL_CALL` → 422), and the server hardcodes `author="user"` — all confirmed by tests with passing controls. **One LOW 🟡 (Y1)** — process/landing: the canonical gates require the `[api]` extra and no CI/contributing change in the diff installs it.

## The six named checks (plant-bypass emphasis)

| # | Check | Verdict | Evidence |
|---|---|---|---|
| 1 | **[plant-bypass]** forge-prevention fail-closed — can a client forge `author:system`/`agent:<id>` or `STATE_TRANSITION`/`AUTONOMY_DECISION`? `UTTERANCE` excluded? | **clean (G1)** | **Two-layer block.** `IntentRequest` (wire.py) has no `author`/`id`/`timestamp` + `extra="forbid"` → forged fields rejected at parse. `_post_intent` (app.py): allowlist check + `validate_metadata` **before any I/O** → `422`; `author="user"` **hardcoded** (`app.py:270`). **Plant tests pass:** `{author:"system"}`/`{id}`/`{agent_id}` → 422 (`test_intent.py:99-129`); `state_transition`/`autonomy_decision`/`utterance`/`tool_call` → 422 (`:138-168`); bad metadata → 422 (`:209-254`); controls (`user_input`/`retraction`/valid `decision`) → 200. |
| 2 | backend-authoritative — any hidden decision surface (routing/gating/state)? new routing/judgment `LLMPurpose`? | **clean (G2/G3)** | Intent path = `append(user_event)` + `run_turn` only. **No `LLMPurpose`** in `api/` (grep: only a comment; enum 9 unchanged). `select_model_and_provider` **only** in the decision-free `llm_adapter` (delegates the routing decision, executes it, adds no judgment). No `should_agent_speak`/`next_room_state`/`decide_agents`/scoring in `api/` (the `ToolMeta` import is `run_turn`'s arg type; the openapi.json `autonomy_*` hits are the generated schema reflecting backend enums). |
| 3 | subscribe-then-replay no-gap (register queue **before** replay SELECT)? | **clean (G4)** | `_room_stream` (app.py:355): `q = ctx.bus.subscribe(rid)` **first**, then replay from the reader, then `replay_complete`, then live with **dedup** (`if live_event.id not in sent_ids`). `pubsub.subscribe` docstring pins the invariant. Tested: `test_no_duplicate_ids_in_replay` + the e2e stream. |
| 4 | separate WAL read conn truly isolated (GET/WS-replay not blocked by `run_turn`)? | **clean (G5)** | `_build_context`: `writer_store`/`writer_executor` (1 worker, holds `run_turn`) + `reader_store`/`reader_executor` (4 workers), WAL `journal_mode`. Reads + WS-replay use the reader; writes + `run_turn` use the writer. **Discriminating timing test:** `test_get_events_not_blocked_while_writer_busy` occupies the writer then asserts a GET completes `<0.25s`. |
| 5 | partial-turn error envelope distinguishes append-fail / turn-fail (discriminating)? | **clean (G6)** | `_AppendFailedError` → `422` `IntentError{stage:"append", appended_event_id:None}` (nothing persisted); `_TurnFailedError` → `500 {stage:"turn", appended_event_id:<id>}` (persisted, reconcile via replay). Tested both stages: `test_invalid_parent_id_returns_422_append_stage` (+ store empty) vs `test_run_turn_raise_returns_500_turn_stage` (+ `appended_event_id` set + persisted in store). |
| 6 | state-machine 不暴露 (wire raw)? Q1–Q5 + test §1–§4/§6? | **clean (G7–G12)** | Wire re-exports `Event`/`Room`/`Snapshot` **raw** (frozen, `extra="forbid"`); GUI humanizes (P3.3). Q1 (no new `LLMPurpose`, split preserved); Q5 (discriminating — plant tests + timing + controls). Tests cover §1 (read+intent e2e), §2 (concurrency), §3 (failure modes), §4 (boundary), §6 (round-trip + OpenAPI-drift). |

## Findings

### Y1 🟡 (low) — the canonical gates require the `[api]` extra; no CI/contributing change in the diff installs it (process/landing)

`pyproject.toml [tool.mypy] files=["src","tests"]` makes the canonical `mypy` check `api/` + `tests/api`, which import `fastapi`/`uvicorn`/`starlette`. The `[api]` deps are an **optional** extra (ADR-025 D1 — correct: core stays importable without the server). Consequence: **without** `--extra api`, `mypy` reports 20 `import-not-found` (+ untyped-decorator) errors and `pytest` cannot collect `tests/api` (`ModuleNotFoundError: fastapi`). **With** the extra, all green (I verified: mypy 187 files clean, pytest 100%). The diff adds no `.github/`/CI or `contributing.md` change ensuring the gate installs the extra.

**Lean (surface, not decide): α (or note-for-landing).** Either the senior updates the gate/CI command + `contributing.md` to install `[api]` for `mypy`/`pytest` on this package (e.g. `uv run --extra api …` / `uv sync --extra api` in CI), **or** confirm the existing CI already installs all extras (`--all-extras`). Low; process/CI, not a product defect — but if the gate runs without the extra, this slice (and every later one touching `api/`) breaks `mypy`/`pytest` collection. Architect: α-update-gate-config / note-for-landing / confirm-CI.

## What holds — verified clean (G1–G12)

- **G1 — forge-prevention fail-closed, plant-bypass verified** (check 1): two-layer block (schema `extra="forbid"` + allowlist/`validate_metadata` before I/O + hardcoded `author:"user"`); the plant tests (`author:system`/`id`/`agent_id`/off-allowlist/bad-metadata → 422) pass with passing controls. The backend stays the sole author of system/agent/transition events.
- **G2 — backend-authoritative, no hidden decision surface**: intent = `append` + `run_turn`; no `LLMPurpose` in `api/` (9 unchanged); no activation/state/routing/scoring logic in `api/`.
- **G3 — `llm_adapter` decision-free glue**: `RealLLMRouter.call` delegates the routing decision to `select_model_and_provider` and executes `provider.call`; bridges sync↔async (new loop on the writer-executor thread); adds no purpose/judgment. The one LLM-touching seam, kept decision-free.
- **G4 — Y1 α landed (subscribe-then-replay + dedup)**: WS handler subscribes first, replays, sends `replay_complete`, streams live with `sent_ids` dedup; `pubsub.subscribe` documents the invariant; tested no-dup + e2e.
- **G5 — Y2 α landed (separate WAL read conn + read-only executor)**: reader vs writer connection/executor; tested reads stay responsive (`<0.25s`) while the writer is busy with a turn — the liveness fix verified by a timing assertion.
- **G6 — Y3 α landed (partial-turn error envelope)**: `append`-stage (422, no id, store empty) vs `turn`-stage (500, `appended_event_id`, persisted) — both discriminatingly tested; store stays append-only-consistent.
- **G7 — arch-Y1 α-lite landed**: allowlist `{USER_INPUT, DECISION, RETRACTION}` kept (UTTERANCE excluded + tested 422); `test_decision_promotion_true_appends_but_no_vk_created` proves a client-posted `DECISION{promotion:true}` appends but reaches **no** promotion path (asserts no VK/`autonomy_decision` events) — the Principle-11 question I raised, closed by test (per R0-B G3).
- **G8 — wire raw (状态机不暴露)**: `Event`/`Room`/`Snapshot` emitted raw; GUI owns humanization (`config/ui_strings/`, P3.3).
- **G9 — contract pinned + drift-tested**: `wire.py` models + committed `openapi.json` + `asyncapi.md`; `extra="forbid"` is itself a forge guard; round-trip + OpenAPI-drift tests green (inscribe-before-producer for P3.3).
- **G10 — pubsub correct**: bounded `asyncio.Queue` (512); a full-queue subscriber is dropped (`put_nowait`/`QueueFull` → unsubscribe), never blocking the writer; state is loop-thread-confined (subscribe on the loop, publish via `call_soon_threadsafe`) — no lock needed.
- **G11 — wrap-don't-reimplement**: only net-new `api/` + the optional `[api]` dep; `core/rooms/autonomy/llm` decision logic untouched (the read-conn + error-envelope live in `api/`).
- **G12 — gates green with `--extra api`** (ruff/format/mypy-187-clean/pytest-100%); the test suite is discriminating — plant-bypass + controls + a liveness timing assertion + both partial-turn stages.

## Forward-notes (green — defense-in-depth / for the dual-lens R0-B + P3.3; not findings)

- **(a) reader connection not enforced read-only**: the reader conn is used only for reads (code discipline), but isn't opened `PRAGMA query_only=ON` — a one-line defense-in-depth hardening so a future bug can't write via the reader. No live bug.
- **(b) turn-fail persists but does not publish live**: on a `turn`-stage failure the user event (and any partial-turn events `run_turn` appended before raising) are persisted but **not** published to live WS subscribers — the poster gets `stage:"turn"` and reconciles via replay (documented). Fine for the single-subscriber localhost MVP; a second live subscriber would see them only on next replay. Worth a P3.3 note (handle a turn-stage error by replaying to see what actually landed).
- **(c) `llm_adapter` opens a new event loop per call**: functional sync↔async bridge on the writer thread; a per-call loop is a minor perf nit (acceptable MVP; reuse is a forward hook).
- These are the concurrency/failure-mode surface the **dispatched dual-lens R0-B** will pressure-test on the impl — handed across rather than routed.

## What I did NOT do

- Did not advance `.workflow/P3.2.yaml` (architect/workflow only); committed-state lag noted previously.
- Did not decide Y1 — surfaced with a lean (α-update-gate-config / note-for-landing / confirm-CI); low, process/CI, not a product defect.
- Single-lens in-family (the dual-lens R0-B re-runs on the impl); reviewed in an isolated worktree, left the shared tree untouched. The architect synthesizes this R0-A + the impl-stage R0-B.
