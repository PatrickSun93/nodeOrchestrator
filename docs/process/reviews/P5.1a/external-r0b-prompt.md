# P5.1a — external (cross-family) R0-B dual-lens prompt

**Task:** P5.1a — deterministic staged analysis pipeline primitive (`fetch → fan-out(analyze×N) → reduce`), multi-source read (web/rss/file), dynamic per-branch prompts as config data, **reversible room/GUI output only**, manual trigger, definition persistence. **NO scheduler (P5.1b), NO email (P5.1c).**

**Contract:** ADR-041 (`docs/decisions/ADR-041-deterministic-analysis-pipeline.md`). Plan: `docs/process/senior-plans/P5.1a.md`. This is a `requires_cross_family_review: true` slice — review through **two orthogonal failure-family lenses**. Verify against the code, not the prose; cite `file:line`. Classify each finding 🔴 blocking / 🟡 needs-architect / 🟢 nit, and route nothing yourself (architect routes — CLAUDE.md "Never LLM-judge a routing decision").

---

## Lens A — pipeline safety + determinism + read-floor + no over-authorized output

The "unattended/staged execution done wrong" adversary. Ask:

1. **Determinism / no silent partial.** Are **all** configured sources fetched and **all** configured analysis prompts run every run? Is the stage order fixed in code (not LLM-chosen)? Does a single source/branch failure get recorded *and isolated* (fail-closed) without silently dropping the rest? Is there any path where the LLM decides *what* to fetch or *which* analyses to run (it must not — ADR-041 D4/D5)?
2. **Read floor — SSRF.** Do **web AND rss** source reads go through the **identical** SSRF floor as `web_fetch` (`net_trust._resolve_and_validate` / `build_ssrf_client`)? A user-suppliable **feed URL** resolving to a denied IP (loopback/CGNAT/link-local/metadata) — is it rejected? Are redirects re-validated per hop? Any bypass that reaches the SSRF-validated client conditionally?
3. **Read floor — sandbox.** Are file source reads path-sandboxed (traversal/symlink-escape rejected, bounded read)? Is the containment check **reused** from `tools/local.py` (not a weaker re-implementation)?
4. **RSS parser (the greenfield).** Is XML parsing **XXE / entity-expansion (billion-laughs) safe** — is external-entity resolution disabled (defusedxml or hardened stdlib)? Do malformed feeds **fail closed** (typed error, no crash, no partial-trust)?
5. **No over-authorized output.** Can the pipeline send **email** or actuate **any** HARD/irreversible tool headless? It must NOT (P5.1a is reversible-output-only). Verify: an analyze branch proposing `send_email` (or any HARD tool) produces a `TOOL_CALL_PENDING` that **waits** — the runner makes **no** `_writer_approve_helper` call, no auto-fire, no `approval_source="auto_pipeline"`. Is the room/summary output **internal/reversible/ungated** (never routed through the autonomy gate)?
6. **Identity / auth.** Is `owner_user_id` server-derived from the principal at definition time (never from the body)? Are all `/pipelines*` routes fail-closed behind auth? Does `POST /pipelines/{id}/run` reject unknown ids + unauthenticated callers?
7. **Untrusted data.** Is fetched source data fed to the analyze LLM as **untrusted-delimited** context (data, not instructions — mirror `agents/dispatch.py:114-119`)? Could feed/web content act as prompt injection that escalates beyond content-gen?

## Lens B — spine no-regression (did the pipeline break the existing constitution)

The "the new feature regressed the gate/spine/contracts" adversary. Ask:

1. **Gate byte-frozen.** Are `score` / `decide_tier` / `emit_gate_decision` and `agents/tool_dispatch.py`'s gate logic **zero-diff**? The pipeline must *reuse* `process_tool_calls`, never edit it, never re-tier a tool, never lower the reversibility floor.
2. **Executor / `_execute_local_call` zero-diff.** Is `tools/executor.py`'s execution core unchanged? Does the pipeline reuse `execute_pending_tool_calls` rather than a parallel executor?
3. **No new `LLMPurpose`.** Grep the diff: only `LLMPurpose.AGENT_RESPONSE` may be used by the analyze + reduce calls; **zero** new enum members. Orchestration (stage order / fan-out / source list / output routing) is code/config, never an LLM judgment.
4. **Headless-actuation surface unchanged.** Is `_writer_approve_helper` unchanged? Is `core/event.py`'s `approval_source: Literal["human","auto_timer"]` **unchanged** (no `auto_pipeline`)? Are the `RB-AUTOFIRE` stamp guards (`agents/tool_dispatch.py:133-145`) byte-intact?
5. **Interactive spine.** Per ADR-041 D2 (lean), is `_write_and_turn` (`api/app.py:933-1044`) **byte-untouched**? *(If the architect routed to alternative B — a shared `run_turn_loop` helper — instead verify the extraction is behavior-preserving: the interactive turn-loop semantics, caps, and cursor logic are unchanged, covered by the existing ADR-033 turn-loop tests + an equivalence test.)*
6. **Single-writer + reader-liveness (ADR-025 D6).** Does the pipeline append on the `writer_executor`? Does P5.1a add **any** new background/lifespan task? It must not (the scheduler is P5.1b) — verify lifespan (`api/app.py:1498-1523`) gains no new task.
7. **Room/agent contracts (ADR-010/011/012).** Is the `RoomType` enum unchanged (no new type)? Is the `EventType` enum unchanged (no new type)? Does the runner ever call `should_agent_speak` / `dispatch_turn` on the pipeline-run room (it must not)?
8. **Persistence.** Are definitions in a side table (mutable config, `users`/`sessions` precedent) and run history in the event log + thin index — with **no** `cron`/`interval`/`next_fire` columns (those are P5.1b)? No new `EventType` for runs?

---

**Orthogonality note:** Lens A = "the unattended pipeline is unsafe / over-authorized / non-deterministic"; Lens B = "the pipeline regressed the gate / spine / room contracts." A finding that fits both → report under the lens where the *root cause* lives. Reviewer B (cross-family) takes the lens assigned at dispatch (`docs/process/dual-lens-r0b.md`).
