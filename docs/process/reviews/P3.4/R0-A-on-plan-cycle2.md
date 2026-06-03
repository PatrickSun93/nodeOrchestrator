---
task_id: P3.4
cycle: 2
round: R0-A-on-plan
stage: plan + ADR-028 (Proposed)
reviewer: architect-partner (in-family, single-lens)
verdict: needs_architect
findings_count:
  red: 0
  yellow: 2
  green: 7
artifacts_reviewed:
  - docs/process/senior-plans/P3.4-cycle2.md            # atomic graph C2-1..C2-4
  - docs/decisions/ADR-028-runtime-tool-executor.md     # Proposed (D1..D6)
predecessors_verified:
  - docs/process/reviews/P3.4/R0-B-cross-family.md       # impl-stage Y2 (read from claude/P3.4-impl)
  - docs/process/reviews/P3.4/architect-routing-on-impl.md  # Y2 → α wire-now; decision #1 build-local-impls-now
baseline: origin/claude/P3.4-impl (cycle-1 landed) + origin/main
note: >-
  Cycle-2 R0-A-on-plan. Distinct filename from cycle-1's R0-A-on-plan.md (same path collides
  despite the cycle counter — exactly the naming hazard the senior plan §4 flags). Constitutional
  carry-forward spine verified STRUCTURAL against the impl-branch source + the live constitution
  tests; the two 🟡 + the four surfaced architect calls sit on the net-new local trust boundary
  and the four MVP-posture deferrals. Did NOT accept ADR-028, did NOT route any finding, did NOT
  advance state.
---

# P3.4 cycle-2 R0-A-on-plan — the runtime tool-executor (plan + ADR-028)

| Field | Value |
|---|---|
| Round | R0-A-on-plan (cycle-2; in-family, single-lens; the dual-lens R0-B is mandatory + separate — `requires_cross_family_review: true`) |
| Stage | Senior plan (`P3.4-cycle2.md`, C2-1..C2-4) + ADR-028 (Proposed, D1..D6) |
| Baseline | `origin/claude/P3.4-impl` (cycle-1: MCP client + gating + executor *function*) + `origin/main` |
| Lens | Spine carry-forward (downstream-of-gate / no-LLM-judgment / no-new-purpose / empty gate diff / leaf placement) + the net-new local trust boundary + plant-bypass |
| Date | 2026-06-03 |
| Verdict | **needs_architect** — 0🔴 · 2🟡 · 7🟢 (spine clean+structural; both 🟡 on the net-new local FS surface; four surfaced architect calls below) |

> **Provenance.** I verified Y2's wording (gated-but-not-executed) + the impl-stage routing (Y2 → α wire-now; decision #1 = build-local-impls-now; scope = a general runtime tool-executor; ADR-028 + senior + dual-lens recommended) by reading the impl-stage `R0-B-cross-family.md` + `architect-routing-on-impl.md` **from `claude/P3.4-impl`** (they are not on this plan branch — see O1). The plan + ADR transcribe both faithfully.

---

## 1. What I verified (the constitutional carry-forward is STRUCTURAL, not asserted)

The architect's review foci are the spine carry-forward. I traced each against the **actual** impl-branch source + the **live** constitution tests, not the plan's prose:

- **Execution stays downstream-of-gate — structural.** `EventType.TOOL_CALL` has exactly **one** appender in `src/`: `agents/tool_dispatch.py:105`, inside the `if result.tier == AUTO_EXECUTE` block (`:100`). The only other `TOOL_CALL` touches are `core/event.py:347` (meta-type map), `derived/snapshot.py:79,168` (the reducer **reads** it — projection, not execution), and `mcp/execution.py:60` (a guard that **requires** a `TOOL_CALL` event be passed in). So the cycle-2 executor's input — the `[pre_cursor:]` window filtered to `TOOL_CALL` — can only contain gate-approved `AUTO_EXECUTE` records. Execution-without-gate is **constructively impossible**, not a discipline. C2-4 t4 makes a regression load-bearing. ✓ (carry-forward #1)
- **No-LLM-judgment / no new `LLMPurpose`.** `tests/mcp/test_constitution.py` c4 pins the frozen 9-value purpose set; every value is content-gen (`purposes.py`). The executor's sole LLM touch is the **reused** content-gen `TOOL_OUTPUT_INTERPRET` (MCP-only, untrusted-framed). C2-4 t3 mirrors c4 for `tools/`. Routing (α/β/γ) is nowhere in the purpose set — it stays an architect decision, never an LLM judgment. ✓ (carry-forward #2)
- **Gate/dispatch diff stays empty.** The executor imports none of `decide_tier`/`emit_gate_decision`/`score`/`gate`; C2-4 t2 mirrors mcp-c2 to enforce it; the plan §4 commits the `git diff origin/main..HEAD -- src/orchestrator/autonomy/ src/orchestrator/agents/tool_dispatch.py` **empty** check into the C2-3 landing commit. `process_tool_calls`/`dispatch_turn`/`run_turn` are untouched. ✓
- **`tools/` leaf placement is sound — and the `run_turn`-fold is doubly-rejected.** `mcp` c1 is an explicit **denylist** of 12 upstream packages (`core/autonomy/agents/llm/rooms/skills/connectors/memory/producers/reentry/derived/workflow`) — **`tools` is not in it**, so a new `tools/` package importing `orchestrator.mcp` does **not** break c1. `tests/rooms/test_constitution.py` scopes its no-LLM rule to `rooms/` only, so `tools/` importing the LLM (via `agents.mcp_interpret`) is fine. Conversely, ADR-028 D1's claim that folding into `run_turn` is impossible is **doubly** verified: `run_turn` lives in `rooms/runtime.py`, so the fold would break **both** mcp-c1 (rooms→mcp) **and** rooms-no-LLM (rooms→LLM SDK). C2-4 t1 mirrors mcp-c1 for `tools/`. ✓ (carry-forward — the leaf is the right home)
- **Plant-bypass — closed.** No path to execution from (a) a server (discovery≠permission, cycle-1 G3; unclassified→`UnknownToolError`), (b) a tool **result** (→ content-gen interpret, describe-don't-act → `OBSERVATION`; **no** in-turn re-dispatch, D4), or (c) a non-`TOOL_CALL` event (sole-appender above). The local registry is a **static** name→callable dict (no `getattr`/`importlib` on the tool-name string — C2-2 must keep it static; noted). The double-execution guard (check room for an existing `TOOL_RESULT`/`TOOL_FAILED` by `call_id`) is race-free **because** it runs inline on the single writer (D5). ✓
- **Session-retention (Y2 sub-fix) is safe.** I confirmed `adapter.py:121` discards the `session` local (`return registry` only, `:140`). The fix retains them — and a retained `MCPSession` is a dataclass of `{server_name, tools, transport(config)}` (`client.py:22-31`); the transport spawns+kills a **fresh subprocess per operation** (`transport.py:3-4`; `list_tools(session)` returns cached tools with "no new subprocess spawn", `client.py:51`). So retaining N sessions = **zero** idle subprocesses/fds — no resource leak from the fix. The cycle-1 `asyncio.wait_for` + kill-no-orphan (`transport.py:107,128`) backs D5's "bounded, finite block." ✓
- **`tools.yaml` needs no change for the MVP three.** `read_file`/`list_files`/`get_current_time` are `reversibility: 10` (`config/tools.yaml:17-26`) → AUTO_EXECUTE. ("rev 10" in the plan = the reversibility **value**, not a file revision.) `MAX_RESULT_BYTES = 65_536` exists at `mcp/execution.py:37` for the local size-cap reuse. ✓

---

## 2. Findings

| # | Sev | Finding | Lean |
|---|---|---|---|
| **Y1** | 🟡 | **`read_file` size-cap must be enforced on READ, not on store — else an oversized in-sandbox file is a memory-exhaustion DoS on the single writer.** ADR-028 D3 + plan C2-2 say "size-capped (reuse the `MAX_RESULT_BYTES` truncation pattern from `mcp/execution.py`)". But that pattern truncates an **already-received** bytes buffer (`execution.py:99` — the subprocess already returned the bytes). For a **local** read, "read the file then truncate to 64 KiB" loads the **whole** file into the writer thread first. A multi-GB file **inside the sandbox root** (a log, a checkpoint, a dataset) + an LLM-proposed `read_file(path=…)` → the single `max_workers=1` writer OOMs → **the whole process dies (every room)**. No adversary needed — just a large file in the workspace. The C2-2 acceptance criterion "no oversized content **stored**" does not constrain what is **read into memory**. | **α-fold into C2-2** (no design change): read **at most** `MAX_RESULT_BYTES (+1)` bytes (bounded read, not read-all-then-truncate); sharpen the criterion to "oversized file → reads at most the cap, never loads the whole file"; add a §3 failure-mode test (oversized file → bounded read, not OOM). This is the cross-family DoS class (same lens that caught the cycle-1 timeout-hang + env-leak) — cheaper to bake in at C2-2 than to let the mandatory dual-lens catch post-impl. |
| **Y2** | 🟡 (low) | **The local-FS sandbox threat model is unstated — the resolve-then-open TOCTOU boundary should be named, not left implicit.** The plan correctly closes symlink-**escape** (`Path.resolve()` follows the link; target-outside-root → `TOOL_FAILED`). The residual is the resolve-then-open **TOCTOU** (an on-disk adversary swapping a symlink between the check and the open) — which is **out** of the MVP threat model (the sandbox root is a *trusted* workspace; the untrusted input is the LLM-proposed **path param**, not concurrent FS mutation; the inline single-writer gives a near-nil window). The design is sound *for its threat model*; the gap is that the threat model isn't **written down**, so the dual-lens can't tell a deliberate boundary from an oversight. | **α-lite** (one sentence in ADR-028 D3): state "untrusted = the LLM-proposed path param; NOT a concurrent on-disk adversary (no `O_NOFOLLOW`/re-validate in the MVP)" — so the dual-lens evaluates a **known posture**, mirroring how D5 flags the liveness posture. Defensible alternative: **δ-watch** (carry as a retro/watch item, no inscription this cycle) if you'd rather not spend the ADR beat. Your call — this is posture-documentation, not a hole. |
| G1 | 🟢 | Execution **downstream-of-gate is structural** — sole `TOOL_CALL` appender = `process_tool_calls` AUTO_EXECUTE-only (`tool_dispatch.py:100,105`); snapshot only **reads**; the executor can't reach a server/impl without a gate-approved event. t4 load-bearing. | — |
| G2 | 🟢 | **No-LLM-judgment / no new `LLMPurpose`** — c4 frozen 9-set; only the reused content-gen `TOOL_OUTPUT_INTERPRET` (MCP-only); t3 mirrors. α/β/γ never an LLM purpose. | — |
| G3 | 🟢 | **Gate/dispatch diff stays empty** — executor imports no decision symbol; t2 mirrors mcp-c2; the empty-diff check is committed into C2-3; `process_tool_calls`/`dispatch_turn`/`run_turn` untouched. | — |
| G4 | 🟢 | **`tools/` leaf placement sound; `run_turn`-fold doubly-rejected** — mcp-c1 denylist excludes `tools/`; rooms-no-LLM scopes `rooms/` only; the fold would break **both**. t1 mirrors mcp-c1. | — |
| G5 | 🟢 | **Plant-bypass closed** — no server/result/non-`TOOL_CALL` path to execution; static local registry (no dynamic dispatch); double-exec guard race-free under the single writer. | — |
| G6 | 🟢 | **Session-retention safe** — a retained `MCPSession` holds config only (per-operation subprocess spawn/kill); N sessions = 0 idle subprocesses; bounded-kill backs D5's finite block. | — |
| G7 | 🟢 | **`not_implemented` fail-closed is honest + the missing-session edge fail-closed** — AUTO-but-deferred tools (`web_search`/`web_fetch`, rev 10) get a `TOOL_CALL` → `TOOL_FAILED("not_implemented")`; mutation/low-reversibility tools never reach the executor (gated-not-executed); a `mcp_sessions[server]` miss is caught by per-call isolation (D4) → `TOOL_FAILED`. (Nit: prefer `mcp_sessions.get(server)` → explicit `not_available` over a bare `KeyError`.) | — |

---

## 3. The net-new surface (where I focused — the local trust boundary)

The carry-forward spine is **carry-forward** — already-inscribed, already-tested, and (above) structurally re-verified. The genuinely **new** code this cycle is `tools/local.py`'s sandbox. Both 🟡 sit there, and so will the dual-lens's hardest probes:

- **Y1 (read-cap-on-read)** is the substantive one: a process-wide memory-DoS reachable with no adversary. It folds into C2-2 with a one-line read-bound + one acceptance criterion — surface it now.
- **Y2 (threat-model statement)** is documentation-of-posture: the stated escape vectors (`..` / absolute-outside / symlink-escape) are the right ones and are closed; only the TOCTOU boundary needs naming so the dual-lens reads a deliberate MVP line, not a gap.
- The rest of the sandbox spec is right: resolve-the-root + `is_relative_to` is the correct check; static registry; `not_implemented` fail-closed for the deferred set; **no** write/move/delete in the MVP local set (mutation tier → gated-not-executed anyway).

Two forward-watches (not cycle-2 findings — flagged so they aren't lost):
- **Double-exec guard ↔ deferred D5.** The guard is check-then-execute; it is correct **only** under the inline single-writer. If the deferred separate-execution-lane (D5) lands, the guard becomes a TOCTOU race — the lane slice must replace it with an atomic claim.
- **Windowed consumption.** The executor runs on the `[pre_cursor:]` window **after** `run_turn` returns. A `TOOL_CALL` that `run_turn` appended **then** raised before returning (`_TurnFailedAfterAppend`) is stranded — not in a later turn's window, never executed. Fail-closed (executes *less*, no security impact), acceptable for MVP; worth a one-line note that the **window**, not the room, is the execution unit.

---

## 4. Surfaced architect calls (the senior's §5 — I ACK + lean; I do NOT route these)

The senior surfaced four. Per my role I give a lean; **you** confirm. None is mine to decide.

1. **Local-tool MVP breadth (§5 #1 — decision #1 boundary).** The senior scoped `{get_current_time, read_file, list_files}` + sandbox and deferred network/subprocess/mutation. **This is exactly the breadth your dispatch already set** (`{get_current_time, read_file, list_files}` + 沙箱) — so this is **convergence**, not an open choice: the senior independently landed on your pre-set line. §5 #1 is effectively **pre-confirmed**; you need only nod (or narrow to clock-only / broaden — both move the dual-lens surface). **Lean: confirm as-is** (the breadth is yours, already given).
2. **`not_implemented` fail-closed seam visible (§5 #2).** Deferred-but-AUTO tools fail at runtime for a "known" tool. **Lean: keep-classified-fail-closed** (no `tools.yaml` churn; the gate still gates them correctly; honest failure ≻ silent no-op). Confirm.
3. **No-re-dispatch (§5 #3 / D4).** Agent reacts to a result on the **next** turn. **Lean: confirm the deferral** (conservative, terminating, matches existing causality; in-turn re-dispatch is additive ADR-011 work with loop-bounding/liveness cost).
4. **Inline-on-single-writer liveness (§5 #4 / D5).** A slow MCP tool blocks all room writes for the bounded timeout. **Lean: accept for MVP** (bounded + fail-closed; local tools fast) — and note this **is** the documented surface the mandatory dual-lens will probe. Confirm the posture.

---

## 5. Process / provenance observations (dev-harness, not product)

- **O1 — cross-branch predecessor links.** The plan's `predecessors:` + ADR-028's References cite `R0-B-cross-family.md` ("impl-stage Y2") and `architect-routing-on-impl.md`. On **this** plan branch (`claude/P3.4-cycle2-plan`, cut from `8bb6e31`, pre-impl) those paths resolve to the **plan-stage** R0-B (different content) / are absent — the impl-stage artifacts live on `claude/P3.4-impl`. They coexist once the plan branch merges into the impl branch (PR #48 accumulates). Low-severity audit-trail nit: a reader on the plan branch following the link lands on the wrong/absent file. Optional: a one-line "(impl-branch)" note on those predecessor entries. Not blocking.
- **O2 — cycle-2 review-file naming (ACK).** The senior plan §4 correctly flags that cycle-2 review files must be suffixed (`R0-A-cycle2.md` / `R0-B-cross-family-cycle2.md` / `plan-vs-impl-cycle2.md`) to avoid overwriting cycle-1's at the same path — the exact collision that already happened in cycle-1 (impl-stage `R0-B-cross-family.md` overwrote the plan-stage one on the impl branch). This review complies: `R0-A-on-plan-cycle2.md`, distinct from cycle-1's `R0-A-on-plan.md`. Good catch by the senior; binding it for the cycle's reviewers.

---

## 6. What the architect needs to route / confirm

1. **Y1 (🟡, real)** — `read_file` size-cap on **read**, not store (memory-DoS on the single writer). **Lean α-fold into C2-2** (bounded read + one acceptance criterion + one failure-mode test; no design change).
2. **Y2 (🟡, low)** — state the local-FS threat model (resolve-then-open TOCTOU is out-of-scope; untrusted = the path param). **Lean α-lite** (one sentence in ADR-028 D3) **or δ-watch** — your call.
3. **The four §5 calls** — breadth-confirm (#1, already your pre-set line → just nod), keep-classified-fail-closed (#2), no-re-dispatch deferral (#3), inline-liveness posture (#4). My leans above; all "confirm/defer."
4. **The spine is clean** — execution-downstream-of-gate / no-LLM-judgment / no-new-purpose / empty-gate-diff / leaf-placement / plant-bypass are **structural** and re-verified against the impl-branch source + the live constitution tests. No spine rework.

After your routing: the senior absorbs Y1 (+ Y2 if α) into ADR-028 + the plan, you Accept ADR-028 (Proposed → Accepted), then junior implements C2-1..C2-4 — with the **mandatory dual-lens R0-B** re-probing the local sandbox (Y1's read-bound, Y2's TOCTOU posture) + the D5 liveness block on the impl.
