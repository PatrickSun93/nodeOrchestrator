---
task_id: P3.4
round: R0-A-on-plan
stage: plan
reviewer: architect-partner
plan_commit: 1cbb86d
lens: single
adr: ADR-027
verdict: needs_architect
findings_count:
  red: 0
  yellow: 1
  green: 13
verdict_history:
  - verdict: needs_architect
    at_commit: 1cbb86d
    findings_count: { red: 0, yellow: 1, green: 13 }
    note: >-
      Initial R0-A-on-plan (in-family, single-lens — the dual-lens R0-B is dispatched in parallel,
      requires_cross_family_review: true). Reviewed senior-plans/P3.4.md + ADR-027 (Proposed) in an
      isolated worktree at 1cbb86d. P3's heaviest constitutional/security slice — and an EXEMPLARY
      plan: the spine + trust boundary are faithfully inscribed (ADR-027 HR#1-10) and largely
      STRUCTURALLY enforced. Spine: (1) MCP tool-calls route through the EXISTING code gate via a
      registry merge — score/decide_tier/gate/emit_gate_decision/process_tool_calls UNCHANGED (a
      feed-the-gate empty-diff test + a constitution test forbidding mcp/ from referencing the
      decision functions + leaf-consumer); (2) reversibility is code/config-classified, server hints
      never authoritative (a test asserts a "safe" hint doesn't change the tier); (3) pre-classify
      allowlist + discovery≠permission (unclassified → no ToolMeta → UnknownToolError → refused,
      ADR-006 fail-closed); (4) execution downstream of the gate is STRUCTURAL (the executor keys on
      the TOOL_CALL event); (5) result interpret = content-gen (reuse TOOL_OUTPUT_INTERPRET, no new
      LLMPurpose — 9 unchanged) + untrusted-framing, outside mcp/. Trust boundary: server allowlist;
      api_key_env credential indirection; untrusted-result size-limit + no-decision; subprocess
      isolation + fail-closed + minimal scoped env (the c2 env-inheritance lesson). Sharp
      self-discoveries (the gate is tool-source-agnostic; there is no existing tool-executor; the c2
      recurrence). ADR-027 RC-23-safe; the adapter/config contract anticipates plugin-delivery (P3.5).
      One 🟡 (Y1, medium-low): execution references a "post-user-confirm" path that does NOT exist
      (verified — process_tool_calls appends TOOL_CALL only for AUTO_EXECUTE; no confirm→TOOL_CALL
      flow consumes a user-confirm; the snapshot's tool_calls_pending_confirm only tracks). MVP
      execution is AUTO-only; COUNTDOWN/HARD MCP tools are gated-and-unexecutable. Constitutionally
      fine (the gate refuses auto-exec — that IS the demonstration), but the wording implies a path
      that isn't there — clarify AUTO-only + defer confirm-then-execute (GUI-coupled). Traces partly
      to my own brief's wording (a shared clarification, not a senior miss). Concurrency/untrusted-
      result watch-items handed to the dispatched R0-B. Did NOT accept ADR-027 or advance state.
---

# P3.4 R0-A on plan (architect-dispatched pre-impl review, in-family, single-lens)

| Field | Value |
|---|---|
| Round | R0-A-on-plan (RC-9; single-lens — the **dual-lens R0-B is dispatched in parallel**, `requires_cross_family_review: true`) |
| Artifacts | `senior-plans/P3.4.md` + `ADR-027` (Proposed) vs the autonomy gate + `config/tools.yaml` substrate + brief P3.4 |
| Reviewed at | isolated worktree `/tmp/p34-plan` @ plan `1cbb86d` (shared-tree instability — RC-7 isolation) |
| ADR status | ADR-027 left **Proposed** — informs accept; I did not accept (architect-only). |

## Verdict: needs_architect — 0🔴 · 1🟡 · 13🟢

> **An exemplary plan for P3's heaviest constitutional/security slice.** The spine + trust boundary aren't just inscribed (ADR-027 HR#1–10) — they're **structurally enforced**: MCP feeds the **unchanged** gate via a registry merge (a *feed-the-gate empty-diff* test + a constitution test forbidding `mcp/` from referencing the decision functions / being imported upstream); the server's hints **never** touch the tier (a test asserts it); discovery≠permission is `UnknownToolError`-fail-closed; execution-downstream-of-gate is **structural** (keys on the `TOOL_CALL` event); the c2 env-inheritance lesson is applied. **One 🟡 (Y1, medium-low)** — the plan/ADR reference a "post-user-confirm" execution path that **doesn't exist** (I verified); clarify the MVP is `AUTO_EXECUTE`-only + defer confirm-then-execute. Non-constitutional (the gate works). Concurrency/untrusted-result pressure-points handed to the dispatched R0-B.

## The named checks

| # | Check | Verdict | Evidence |
|---|---|---|---|
| 1 | **[autonomy-gating]** MCP tool-call through the **existing code gate** (ToolCall→`emit_gate_decision`, tier from code `score`+`decide_tier`)? not server-decided? pre-classify allowlist (unclassified→`UnknownToolError` refused)? discovery≠permission? server hints not authoritative? feed-the-gate (decision logic unchanged)? no new routing/judgment `LLMPurpose`? | **clean (G1–G5)** | D2/§2: registry merge; `score`/`decide_tier`/`gate`/`emit_gate_decision`/`process_tool_calls` **unchanged** (a §8 empty-diff check). D3: pre-classify allowlist; unclassified → no `ToolMeta` → `UnknownToolError`→refused (ADR-006). Server `readOnlyHint`/`destructiveHint` **ignored for the tier** (a test asserts). **No new `LLMPurpose`** (9; interpret reuses `TOOL_OUTPUT_INTERPRET`); a constitution test forbids `mcp/` referencing the decision fns + leaf-consumer. |
| 2 | **[trust boundary]** server allowlist? `api_key_env` credential indirection? untrusted-result (size-limit + no-auto-action)? subprocess isolation fail-closed? scoped env (c2)? server can't escalate autonomy? | **clean (G8–G11)** | D4/§6/HR#7–10: only declared servers connect (undeclared refused); `api_key_env` per-server, secret only into the scoped subprocess env; results size-capped + untrusted-framed + drive no decision; bounded timeouts → crash/hang/malformed → `TOOL_FAILED` (orchestrator never crashes); **minimal scoped subprocess env** (not the orchestrator's full env — the c2 lesson). Server can't escalate (calling still passes the code gate). |
| 3 | execution downstream of gate (only approved/confirmed contacts the server)? namespacing collision-free? | **clean (G6/G12); Y1 (confirm-path)** | D6/HR#4: the executor keys on the `TOOL_CALL` event → **never contacts a server without it** (structural). `mcp__<server>__<tool>` collision-free (a test asserts). **Y1: the "post-user-confirm" half of that path doesn't exist — see finding.** |
| 4 | ADR-027 RC-23-safe? Q1–Q5 + test (§1–§4 discriminating: unclassified→refused, low-rev→HARD-not-auto, server safe-hint doesn't change tier)? | **clean (G13)** | ADR-027 `Status: Proposed`; grep clean. §8 discriminating: `read_file` rev10→AUTO (executed) vs `write_file` rev2→HARD (no auto-exec, no `TOOL_CALL`); a server "safe" hint **doesn't** change the tier; §3 fail-closed; §4 env-leak/allowlist/credential; the feed-the-gate empty-diff. |

## Findings

### Y1 🟡 (medium-low) — execution references a "post-user-confirm" path that doesn't exist; clarify the MVP is `AUTO_EXECUTE`-only + defer confirm-then-execute (scope/completeness, not constitutional)

ADR-027 D6/HR#4 + plan §5 say MCP execution keys on a `TOOL_CALL` event "appended only post-`AUTO_EXECUTE` **or post-user-confirm**." I verified the codebase: **the post-user-confirm path does not exist.** `process_tool_calls` appends a `TOOL_CALL` event **only** for `AUTO_EXECUTE`; `COUNTDOWN`/`HARD` append none ("await confirm"), and **no flow consumes a user-confirm to append the `TOOL_CALL`** (the snapshot's `tool_calls_pending_confirm` only *tracks* pending calls for surfacing — nothing executes them; there is no tool-executor at all today, as ADR-027 itself notes). So in the MVP, MCP execution runs **only** for `AUTO_EXECUTE`; `COUNTDOWN`/`HARD` MCP tools are gated-and-**permanently-unexecutable**.

**Constitutionally this is fine** — the gate correctly refuses auto-exec for low-reversibility tools (the demo's `write_file` rev2 → `HARD_CONFIRM` → not executed *is* the constitutional demonstration). But the "post-user-confirm" wording implies a working path that isn't there, which (a) could lead the junior to wire against a non-existent confirm flow (or build one = scope creep), (b) leaves the e2e's expectations ambiguous (it demonstrates AUTO-executes + HARD-gated-not-executed, **not** confirm-then-execute), and (c) sets a false expectation that `COUNTDOWN`/`HARD` MCP tools are executable in the MVP.

**Honest note:** this traces partly to **my own brief** (§c said "execution downstream of approval, AUTO **or user-confirmed**" without flagging the confirm flow's absence) — the senior faithfully followed it; this is a shared clarification, not a senior miss. The confirm-then-execute flow is **GUI-coupled** (the snapshot's `tool_calls_pending_confirm` + handoff §899's `COUNTDOWN_CONFIRM` UI contract feed it) → it belongs with the GUI-interaction work, not P3.4's backend MCP client.

**Lean (surface, not decide): α-lite-fold or note-for-impl.** The senior clarifies plan §5 + ADR-027 D6/HR#4: *"MVP execution = `AUTO_EXECUTE` only; `COUNTDOWN`/`HARD` tools are correctly gated-and-not-executed (the constitutional demonstration); the user-confirm → `TOOL_CALL` → execute flow does not exist yet (GUI-coupled — deferred). The e2e demonstrates AUTO-executes + HARD-gated-not-executed."* A one-paragraph scope clarification + the D6/HR#4 wording fix. Medium-low; non-constitutional. Architect: α-lite-fold / note-for-impl / (or rule confirm-then-execute *into* P3.4 scope — heavier; needs the confirm flow built + tested).

## What holds — verified clean (G1–G13)

- **G1 — HR#1 MCP through the existing code gate** (D2/§2): a registry merge — an MCP tool-call is a `ToolCall` gated by `score`+`decide_tier`; no MCP-server-decided autonomy.
- **G2 — feed-the-gate-unchanged**: `score`/`decide_tier`/`gate`/`emit_gate_decision`/`process_tool_calls` untouched (a §8 **empty-diff** verification); a constitution test forbids `mcp/` referencing `decide_tier`/`emit_gate_decision`/`gate`/`select_model_and_provider` and forbids upstream layers importing `mcp/` (leaf consumer) — the gate stays the **sole** decision surface, structurally.
- **G3 — HR#2 reversibility code/config-classified**: `ToolMeta.reversibility` from `config/mcp_servers.yaml`; the protocol's `readOnlyHint`/`destructiveHint` are **advisory-only, never authoritative** — a test asserts a server "safe" hint does **not** change the tier.
- **G4 — HR#3 pre-classify allowlist + discovery≠permission**: only allowlisted+classified tools get a `ToolMeta`; a discovered-but-unclassified tool → not in the registry → `UnknownToolError`→refused (ADR-006, fail-closed). Reversibility-omitted → default 0 (irreversible → HARD_CONFIRM).
- **G5 — no new `LLMPurpose` / `mcp/` decision-free** (HR#5/#6): interpret reuses `TOOL_OUTPUT_INTERPRET` (content-gen; 9 unchanged); `mcp/` is transport+adapter+post-gate-execution only (constitution-tested).
- **G6 — HR#4 execution downstream of the gate, STRUCTURAL**: the executor runs only for a `TOOL_CALL` event (the gate's approval record) → never contacts a server without it. *(The confirm-path scope is Y1.)*
- **G7 — HR#5 result interpret = content-gen + untrusted-framing, outside `mcp/`**: the untrusted `TOOL_RESULT` is described (not acted on); no result drives a routing/autonomy decision.
- **G8 — HR#7 server allowlist**: only servers declared in `config/mcp_servers.yaml` connect; undeclared → refused (fail-closed).
- **G9 — HR#8 credential indirection**: `api_key_env` per server; the secret is read from the env at connect, passed **only** into that server's scoped subprocess env — never inline.
- **G10 — HR#9 untrusted results**: size-capped; untrusted-external-data framing; no result drives a decision.
- **G11 — HR#10 subprocess isolation + fail-closed + scoped env**: bounded timeouts (connect + every `tools/call`); crash/hang/timeout/malformed → `TOOL_FAILED` (orchestrator never crashes/hangs); **minimal scoped subprocess env** (`{**minimal_base, **server.env, [api_key_env→secret]}`), not the orchestrator's full env — the c2 env-inheritance lesson applied (the cross-family catch from S3).
- **G12 — namespacing `mcp__<server>__<tool>` collision-free** (no local tool carries `mcp__`; a §4 test asserts).
- **G13 — RC-23-safe + discriminating test plan + contract anticipates plugin-delivery + sharp self-discoveries**: ADR-027 Proposed (no `status: accepted`); §8 discriminating (unclassified→refused, low-rev→HARD-not-auto, server-hint-doesn't-change-tier, env-leak, gate-empty-diff); the adapter/config contract (D5) is shaped so a P3.5 plugin carries the same `mcp_servers` block (wraps, doesn't reshape); §11 self-discoveries (gate tool-source-agnostic; no existing tool-executor → execution-on-`TOOL_CALL` is structural; the c2 recurrence) are accurate + load-bearing.

## Watch-items for the dual-lens R0-B (green — flagged, not findings)

The cross-family R0-B is dispatched (the S3-magnified lens). I hand these to it rather than route:
- **W-a (untrusted-result truncate-vs-reject):** D4 leaves "over-cap → truncated (`output_truncated_at`) **or** rejected" — the choice is unspecified. Both bound DoS; note that truncation still feeds untrusted *head*-bytes to the interpret LLM, so the **untrusted-framing** (not the size-cap) is the injection mitigation. R0-B should pin the behavior + pressure-test the injection-via-truncated-result path.
- **W-b (the interpret wiring):** the one net-new LLM-touching piece (outside `mcp/`) — R0-B should confirm it stays content-gen + untrusted-framed + drives no decision.
- **W-c (sync-bridge / executor blocking):** a slow/hanging `tools/call` on the sync bridge could block the turn (the P3.2 single-writer-executor liveness interaction); the **bounded timeout** is the mitigation — R0-B should verify the timeout fires before any orchestrator-level stall, and the session lifecycle (connect-once/reuse/close) across the bridge.

## What I did NOT do

- Did not accept ADR-027 (architect-only) or advance `.workflow/P3.4.yaml` (committed-state lag is the usual pattern).
- Did not decide Y1 — surfaced with a lean (α-lite-fold / note-for-impl), and flagged it traces partly to my own brief's wording.
- Single-lens in-family (the dual-lens R0-B runs in parallel); reviewed in an isolated worktree, left the shared tree untouched.
