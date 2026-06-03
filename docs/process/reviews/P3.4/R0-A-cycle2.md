---
task_id: P3.4
cycle: 2
round: R0-A
stage: impl
reviewer: architect-partner (in-family, single-lens)
verdict: needs_architect
findings_count:
  red: 0
  yellow: 2
  green: 12
artifact_reviewed: claude/P3.4-impl @ 6a72c99 (C2-1..C2-4)
baseline: origin/main + cycle-1 (b5a742c)
parallel_review: docs/process/reviews/P3.4/R0-B-cross-family-cycle2.md (deepseek, needs_architect 0R/1Y/10G)
note: >-
  Impl-stage R0-A on the runtime tool-executor. Distinct filename from cycle-1 R0-A.md (same path
  collides despite the cycle counter). All six spine carry-forward foci verified STRUCTURAL on the
  actual code at 6a72c99; the four plan-stage routed findings (R1 interpret-timeout, read-bounded,
  TOCTOU posture, double-exec full-room, t4 split, Σ-cap) all landed. Two 🟡, both on the executor's
  failure/output paths. The cross-family R0-B (impl-stage) independently caught the same interpret
  race (2-way overlap on Y1) — and I add that its proposed one-liner is insufficient. Did NOT accept,
  did NOT route, did NOT advance state.
---

# P3.4 cycle-2 R0-A (impl-stage) — the runtime tool-executor

| Field | Value |
|---|---|
| Round | R0-A (impl-stage; in-family, single-lens; runs alongside the mandatory cross-family R0-B — `requires_cross_family_review: true`) |
| Artifact | `claude/P3.4-impl` @ `6a72c99` — C2-1 executor framework + MCP wiring, C2-2 local tools + trust boundary, C2-3 bootstrap/turn-driver wiring + e2e, C2-4 constitution tests |
| Baseline | `origin/main` (gate untouched) + cycle-1 (`b5a742c`) |
| Lens | Spine carry-forward, **structural on the running code**: (1) downstream-of-TOOL_CALL, (2) no-LLM-judgment / no new purpose, (3) empty gate diff, (4) tools/ leaf vs rooms constitution, (5) plant-bypass, (6) static local registry |
| Date | 2026-06-03 |
| Verdict | **needs_architect** — 0🔴 · 2🟡 · 12🟢 (spine structurally intact; both 🟡 on the executor's failure/output paths; converges with R0-B's needs_architect) |

> **Method.** All code claims traced against the content-addressed blobs at `6a72c99` (`git show <sha>:path`), immune to the working-tree branch-switching that a concurrent session kept doing in the shared checkout. Gates run in an isolated worktree pinned to `6a72c99`.

---

## 1. Spine carry-forward — verified STRUCTURAL on the impl (the six foci)

| # | Focus | Verdict on the code |
|---|---|---|
| 1 | **Execution downstream-of-TOOL_CALL** | ✅ `executor.py:88` filters the window to `e.type == EventType.TOOL_CALL` and returns early if none; the executor only ever appends `TOOL_RESULT`/`TOOL_FAILED`/`OBSERVATION`, never forges a `TOOL_CALL`. The window is `get_room_events(rid)[pre_cursor:]` (`app.py:327`). Sole-appender re-confirmed: `EventType.TOOL_CALL` is appended only by `agents/tool_dispatch.py:105` (AUTO_EXECUTE branch); `snapshot.py` only reads it. C2-4 **t4** makes this load-bearing as **both** a structural AST sole-appender scan **and** the behavioral no-TOOL_CALL→no-execution test (the plan-stage R0-B Y3 "structural vs behavioral" split landed correctly). |
| 2 | **No-LLM-judgment / no new `LLMPurpose`** | ✅ The executor's only LLM touch is the MCP interpret (`TOOL_OUTPUT_INTERPRET`, content-gen); `mcp_interpret.py` is **unchanged** in cycle-2 (0-line diff). C2-4 **t2** (no `decide_tier`/`emit_gate_decision`/`score`/`gate` in `tools/`) + **t3** (frozen 9-value purpose set) enforce it. No re-gating, no routing in the execution path. |
| 3 | **Gate/dispatch diff stays empty** | ✅ `git diff origin/main..6a72c99 -- src/orchestrator/autonomy/ src/orchestrator/agents/tool_dispatch.py` = **empty** (verified). `process_tool_calls`/`dispatch_turn`/`run_turn` untouched. The executor feeds the gate; it never changes it. |
| 4 | **`tools/` leaf vs rooms constitution** | ✅ `executor.py` imports `agents.dispatch`/`agents.mcp_interpret`/`core`/`mcp` — **not** `rooms`. C2-4 **t1** denylist includes `rooms` (and 10 other upstream roots) → rooms cannot import `tools/`. The executor lives outside `rooms/` and is invoked by the `api/` composition root post-`run_turn` (`app.py:328`), so `rooms/` stays LLM-free + mcp-free (the D1 fold-rejection holds on the impl). |
| 5 | **Plant-bypass** | ✅ No path to execution from (a) a server — it cannot append a `TOOL_CALL` (sole appender = the gate); (b) a tool **result** — `TOOL_RESULT`→`OBSERVATION` (interpret), **no re-dispatch** (D4; the executor returns after appending), and an `OBSERVATION`/`TOOL_RESULT` is a different `EventType` → filtered out; (c) a non-`TOOL_CALL` event — filtered at `executor.py:88`. Double-execution guard scans **full room history** for prior `TOOL_RESULT`/`TOOL_FAILED` by `call_id` → skips re-execution (cross-turn `call_id` collisions covered). |
| 6 | **Static local registry, no dynamic dispatch** | ✅ `build_local_tool_registry` (`local.py:128`) returns a **literal** dict `{get_current_time, read_file, list_files}`; dispatch is `local_tools.get(tool_name)` (`executor.py:233`) → no `getattr`/`importlib`/`eval` on the tool-name string. A miss → `TOOL_FAILED(not_implemented)`; an MCP session miss → `.get()` → `TOOL_FAILED(not_available)` (no bare `KeyError`). |

**Plan-stage routed findings — all landed on the impl:**
- **R1 (the plan-stage 🔴, interpret no-timeout):** the executor runs interpret on a **separate** pool (`_INTERPRET_EXECUTOR`, off the single writer) under `future.result(timeout=INTERPRET_TIMEOUT_S=30s)`; on timeout the raw `TOOL_RESULT` stands, no `OBSERVATION`. The writer blocks ≤30s per interpret, never indefinitely. **The liveness contradiction is resolved** — but the off-writer move introduces a residual race (**Y1** below).
- **read-bounded (my plan-stage Y1):** `read_file` does `fh.read(MAX_RESULT_BYTES + 1)` then truncates — **never loads the full file** (`local.py:71`). The OOM vector is closed. ✅
- **TOCTOU posture (plan Y2 / R0-B Y2):** stated inline (`local.py:9-10`) + ADR-028 D3 — "untrusted = LLM-proposed path; root = trusted; TOCTOU out of MVP scope." ✅
- **double-exec scope (R0-B plan Y1):** full-room-history (`executor.py:92`). ✅  **t4 split (R0-B plan Y3):** structural + behavioral. ✅  **Σ-cap (R0-B plan Y4):** `MAX_MCP_CALLS_PER_TURN=10`, excess → `TOOL_FAILED(turn_mcp_cap_exceeded)`. ✅

---

## 2. Findings

| # | Sev | Finding | Lean |
|---|---|---|---|
| **Y1** | 🟡 | **The R1 interpret-timeout fix leaves a residual cross-thread write race — and R0-B's proposed one-liner doesn't close it.** `_interpret_bounded` (`executor.py:202`) submits interpret to `_INTERPRET_EXECUTOR` and waits `future.result(timeout=30s)`. **Success path is safe** (the writer parks on `future.result()` while the pool thread appends the `OBSERVATION` via `writer_store.conn` — exclusive, serialized by the barrier). **Timeout path races:** on `_FutureTimeout` the writer **resumes** (next tool call / the `new_events` read / the next turn) while the leaked interpret thread is **still running**; when the slow LLM returns, that thread appends the `OBSERVATION` via the **same** `writer_store.conn` (`check_same_thread=False`, WAL) — two threads on one sqlite connection, violating the single-writer invariant that `check_same_thread=False` relies on. **The cross-family R0-B independently caught this (2-way overlap, high confidence).** My addition: R0-B's recommended fix `future.cancel()` is a **no-op for an already-running future** (`cancel()` returns False once a ThreadPool worker has started the task — and it has, that's why it timed out), so it does **not** prevent the late write. Also the race can surface on the **writer** thread (a `sqlite3.OperationalError`/cursor-state error on the writer's next op = a user-facing turn failure), not only as an "untidy" traceback in the advisory thread. | **α-fix properly** (not `future.cancel()`): isolate the interpret write — give the interpret pool its **own** EventStore/connection, **or** marshal the `OBSERVATION` append back onto the writer thread, **or** a cooperative-cancel flag the interpret checks before appending, **or** (cheapest) wrap the late append in a swallow-the-sqlite-error guard **and** accept out-of-order `OBSERVATION` as a documented posture. The mandatory dual-lens R0-B already flags it; the fix must actually isolate, not cancel. |
| **Y2** | 🟡 (low) | **`list_files` output is not size-capped — the one local output path that ignores `MAX_RESULT_BYTES`.** `_list_files` (`local.py:90`) builds `"\n".join(sorted(e.name for e in resolved.iterdir()))` with **no** cap and no `output_truncated_at`. `read_file` is bounded (the Y1 read-fix) and MCP results are capped at `MAX_RESULT_BYTES`, but `list_files` materializes **every** entry name. A pathologically large in-sandbox directory (a generated tree, `node_modules`, a data dir) → a large in-memory string + an oversized `TOOL_RESULT` stored and fed into the next-turn snapshot/LLM context. Lower severity than the `read_file` case (filename listings are smaller than file bodies), but it breaks the "all tool outputs size-capped" discipline. **R0-B did not flag this — single-lens, lower confidence.** | **α-fold into C2-2** (or a C2-5 cleanup): cap `list_files` output at `MAX_RESULT_BYTES` (truncate + set `output_truncated_at`) **or** an entry-count limit, matching `read_file`/MCP. |

---

## 3. Greens (verified on the code — abbreviated; full traces in R0-B's 10🟢 confirm the same)

`G1` constitution t1–t4 genuine (AST-walk, non-vacuous). `G2` session-retention via `build_mcp_tool_registry_and_sessions_from_config` (old fn kept for back-compat; `skip_unavailable` preserved; retained session holds no long-lived subprocess). `G3` executor placement correct (post-`run_turn`, pre-`new_events`-publish; `app.py:328`). `G4` local results trusted — not interpreted, no `OBSERVATION`. `G5` per-call fail-closed isolation (one tool raises → `TOOL_FAILED`, others continue). `G6` HARD/COUNTDOWN genuinely not executed (no `TOOL_CALL` → e2e demonstrates it). `G7` `not_implemented`/`not_available` fail-closed via `.get()`. `G8` bounded read (no OOM). `G9` TOCTOU posture stated. `G10` double-exec full-room race-free (under single-writer; forward-watch for the deferred D5 lane noted). `G11` e2e exercises the real `POST /intent` path (local AUTO → TOOL_RESULT; MCP AUTO → TOOL_RESULT+OBSERVATION; HARD → neither). `G12` handoff de-claimed (cycle-1 vs cycle-2 runtime-execution distinction corrected).

---

## 4. Gates (isolated worktree @ 6a72c99, all extras)

- **ruff** `src/orchestrator/{tools,mcp,api}/ tests/tools/` → **All checks passed**.
- **mypy** `src/orchestrator/` → **Success: no issues found in 92 source files** (the cycle-2 `tools/` is clean; the earlier `api/` import-not-found errors were a fresh-venv missing-`[api]`-extra artifact, gone after `uv sync --all-extras`).
- **pytest** (full suite incl. `tests/`) → **__PYTEST_RESULT__**.

---

## 5. Low observations (not findings — flagged so they aren't lost)

- **Interpret pool lifecycle isn't owned by `AppContext`.** `_INTERPRET_EXECUTOR` is a module-global `ThreadPoolExecutor` created at import and **never shut down** (`AppContext.shutdown()` tears down writer/reader executors but not this one). On a hung interpret + shutdown, threads leak; across multiple test apps the pool is shared. Tied to Y1's fix — whatever isolates the interpret write should also own its lifecycle.
- **Repeated full-room scans per turn.** `get_room_events(room_id)` is called for the window (`app.py`), again for the dedup set (`executor.py:92`), and again per MCP interpret (`executor.py:191`) — O(events) each, several times per turn. Fine for the MVP; a perf note for long-lived rooms.
- **Process (not product): the C2-4 commit bundles `.workflow/P3.4.yaml` restoration churn.** Three `actor: architect-partner` "restoring (post-commit hook advanced early)" overrides landed inside `6a72c99`. End state is correct (`awaiting_junior_impl`); the audit overrides are legitimate; only the bundling-into-the-impl-commit is untidy. Matches the known post-commit-hook-fight pattern.

---

## 6. What the architect needs to route / confirm

1. **Y1 (🟡, 2-way with R0-B)** — the interpret-timeout late-write race. **Lean α-fix-properly** — isolate the interpret write (own connection / marshal-to-writer / cooperative-cancel / swallow-late-error+document). **Note for routing: R0-B's `future.cancel()` one-liner does not close it** (can't cancel a running future). This is the one substantive impl finding; both lenses agree it's real.
2. **Y2 (🟡, low, mine-only)** — `list_files` output not size-capped. **Lean α-fold** (cap like `read_file`/MCP).
3. **Spine is clean** — all six foci structurally verified on the running code; every plan-stage routed finding (R1 + the six 🟡) landed. No spine rework.
4. **Joint with R0-B** — both lenses return **needs_architect**; the only overlap is Y1 (the residual race). The dual-lens ROI on cycle-2: the plan-stage 🔴 (interpret no-timeout) was fixed, and the impl-stage re-probe converges on the one residual the fix introduced.

After your routing I'll write `architect-routing-on-impl-cycle2.md` (cycle2-distinct). I did not accept, route, or advance state.
