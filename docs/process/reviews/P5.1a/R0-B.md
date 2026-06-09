---
task_id: P5.1a
round: R0-B
verdict: needs_architect
findings_count:
  red: 0
  yellow: 3
  green: 9
---

# R0-B cross-family review — P5.1a impl (abe4d55)

## Lens preamble — runtime-integration + failure-mode focus

This review applies the true cross-family lens per `dual-lens-r0b.md`: trace failure
modes across module boundaries, ask "what happens when this call fails at 3am,"
and over-correct for the Claude-family bias that "if the types are right, the
runtime is right." The P5.1a scope is a deterministic pipeline primitive with
reversible output only — no scheduler, no email. The risk surface that matters
here is **data consistency across the runner/store boundary** and **signature
honesty** (dead parameters that look active). The review also verifies the
constitutional invariants (ADR-041 D9) and security floors (SSRF/sandbox/XXE).

**Inputs read:** brief (P5.1.md DP0–DP8), ADR-041 (Accepted), senior plan v2,
impl branch `origin/claude/P5.1a-impl` (abe4d55, 5 commits T1–T6).
**Gates run (worktree):** 61/61 pytest, mypy --strict (17 files, 0 issues),
ruff (0 issues).

## Findings

| ID | Severity | Surface | Claim | Suggested investigation |
|----|----------|---------|-------|-------------------------|
| F1 | 🟡 | `pipeline/runner.py:250` / `api/app.py:1560-1568` | **run_id mismatch across runner/store boundary.** `run_pipeline()` generates `run_id = f"prun_{uuid4().hex}"` and embeds it in the room anchor event text ("Pipeline run started: run_id=X"). `create_pipeline_run()` in the endpoint generates a **different** `run_id = f"prun_{uuid4().hex}"` for the `pipeline_runs` table row. The endpoint returns `create_pipeline_run`'s run_id (the table's), discarding the runner's run_id from `PipelineRunResult.run_id`. Consequence: the run_id visible in room events does not match the run_id in the `pipeline_runs` index — correlating a room event with its run record requires joining on `room_id`, not the natural key. | (a) Have `run_pipeline` accept `run_id` as an optional parameter (caller-supplied), or (b) return the runner-generated `run_id` from `create_pipeline_run` instead of generating a new one. Either resolves the mismatch. |
| F2 | 🟡 | `pipeline/runner.py:246` | **`owner_user_id` dead parameter.** `run_pipeline()` accepts `owner_user_id: str` in its signature but **never references it** in the function body. The parameter looks as if it should attribute the run (e.g. stamp the room or an event author), but the actual attribution happens in the endpoint's `_run_on_writer` via `create_pipeline_run(owner_user_id=owner_user_id)`. This is a signature-honesty gap: a future caller (P5.1b scheduler) passing `owner_user_id` to `run_pipeline` would silently get no attribution from the runner, only from whichever caller also writes the `pipeline_runs` row. | Either use `owner_user_id` inside `run_pipeline` (e.g., stamp it on the room or run-anchor event author) or remove it from the signature and document that attribution is the caller's responsibility. |
| F3 | 🟡 | `docs/architecture/sources-vs-connectors.md:20` vs `src/orchestrator/sources/rss.py:22-33` | **Docs-vs-impl mismatch on XXE protection mechanism.** The architecture doc describes `_SafeXMLParser` (blocking `EntityDeclHandler`), but the implementation uses `_check_no_entity_declarations` — a string-scan pre-filter on the first 8192 bytes looking for `<!DOCTYPE` / `<!ENTITY`. Both approaches are safe (entity declarations are blocked), but the doc describes a mechanism that doesn't exist in the code. Minor, but a future reader tracing the security floor from the doc would be confused. | Update the doc to describe the actual mechanism (`_check_no_entity_declarations`, a byte-budgeted string pre-scan for DOCTYPE/ENTITY declarations) or rename the implementation to match the doc. |

### 🟢 N1–N9 — Verified invariants (no action needed)

| ID | Check | Result |
|----|-------|--------|
| N1 | Gate + executor spine byte-frozen | ✅ `agents/tool_dispatch.py`, `tools/executor.py` — zero diff |
| N2 | No new `LLMPurpose` | ✅ All LLM calls use `LLMPurpose.AGENT_RESPONSE` only (grep-confirmed: 3 call sites in runner, all content-gen) |
| N3 | `countdown_auto_fire=None` | ✅ Verified in test `test_countdown_auto_fire_none` — all `process_tool_calls` calls pass `countdown_auto_fire=None`; sweeper cannot auto-fire pipeline pendings |
| N4 | Owner-private access control | ✅ Tested: non-owner → 403 on `GET /pipelines/{id}` and `POST /pipelines/{id}/run`; `GET /pipelines` returns only caller's definitions |
| N5 | SSRF floor | ✅ Tested: denied-IP web source → `SourceReadError`, denied-IP RSS source → `SourceReadError`, private-range IP → `SourceReadError` |
| N6 | Sandbox floor | ✅ Tested: traversal (`../etc/passwd`) → `sandbox_rejected`, absolute path → `sandbox_rejected` |
| N7 | XXE/billion-laughs blocked | ✅ Tested: DOCTYPE with external entity → `SourceReadError`, DOCTYPE with internal entity expansion → `SourceReadError`; mechanism is `_check_no_entity_declarations` — a string-scan pre-filter, safe and portable |
| N8 | No schedule columns | ✅ Verified: schema has zero `cron`/`interval`/`next_fire` fields; example config test asserts same |
| N9 | `_write_and_turn` byte-untouched | ✅ Interactive spine (`api/app.py:933-1044`) — zero diff; the ~30 lines of bounded-pass scaffolding in `_run_analyze_branch` are duplicated, not extracted |

Additional verified properties (not in plan checklist but confirmed by review):

- `EventType` enum unchanged (no new members) — grep-confirmed
- `RoomType` enum unchanged (no new `PIPELINE` type) — uses existing `FREE_CHAT`
- `approval_source` Literal unchanged — grep-confirmed
- `_writer_approve_helper` unchanged — grep-confirmed (the grep hit was a false match on function name in a comment)
- All 61 new tests pass; mypy strict + ruff clean on all new files
- Example pipeline config validates against `PipelineDefinition` and has no schedule fields

## Synthesis

The implementation is **constitutionally sound** — the gate, executor, `LLMPurpose`,
`EventType`, `RoomType`, and interactive spine are all byte-frozen per ADR-041 D9.
The security floors (SSRF, sandbox, XXE) are tested, not just asserted. The three
🟡 findings cluster around the **runner↔caller boundary**: the runner and the
endpoint each generate independent IDs (F1), the runner accepts a parameter it
doesn't use (F2), and a docs note describes a different implementation mechanism
than what the code uses (F3). None are safety-critical; they are **contract
consistency** issues that would matter most when P5.1b (scheduler) becomes a
second caller of `run_pipeline` — at that point, a dead parameter and mismatched
run IDs could produce harder-to-diagnose bugs than they do today with a single
caller.

Verdict: **needs_architect** (3🟡, architect-routed α/β/γ per role boundary).