---
task_id: P5.1a
round: R0-B
cycle: 2
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 7
---

# R0-B cross-family re-review — P5.1a cycle-2 rework (267da97)

## Lens preamble — runtime-integration + failure-mode, post-N7 correction

This re-review applies the true cross-family lens per `dual-lens-r0b.md`:
trace failure modes across module boundaries, ask "what happens when this
call fails at 3am," and over-correct for Claude-family biases (especially
"if the types are right, the runtime is right").

**Correction mode (RC-20)**: the cycle-1 R0-B review (this reviewer) marked
XXE protection as ✅ (N7), accepting the byte-scan pre-filter and the
DOCTYPE-at-start tests at face value. R0-A then empirically reproduced a
comment-padded prolog billion-laughs evasion (8 KiB scan window bypassed).
The cross-family lens failed to ask the right adversarial question ("what
happens if the DOCTYPE is not at the start?"). This re-review carries that
lesson: treat every content-scan gating decision as an adversarial-layout
question over the specific padding supported by the format, not just "is there
a scanner?"

**Inputs read:** architect routing (`architect-routing-on-impl.md`, all-α),
impl branch `origin/claude/P5.1a-impl` @ 267da97, cycle-1 R0-B + R0-A reviews.
**Gates run (isolated worktree, detached @ 267da97):** 69/69 pytest, mypy
--strict (10 source files, 0 issues), ruff (0 issues).

## Cycle-1 findings — verification

| Cycle-1 ID | Sev | What was wrong | Fix applied | Verified |
|---|---|---|---|---|
| **B1** | 🔴 | Hand-rolled byte-scan `_check_no_entity_declarations` → comment-padded prolog evasion (R0-A reproduced) | `defusedxml` (`forbid_dtd=True`) — `src/orchestrator/sources/rss.py:63` | ✅ Position-independent; test `test_rss_parse_comment_padded_prolog_doctype_blocked` (9000-char comment padding) confirms DOCTYPE blocked |
| **F-runid** | 🟡 | Runner generated `run_id`, store generated different `run_id` → mismatch across boundary | Runner generates `run_id`; store accepts `run_id` param as-is (`store.py:140`); endpoint passes `result.run_id` → `create_pipeline_run` (`app.py:1697`) | ✅ `test_create_pipeline_run_with_caller_supplied_run_id` + `test_run_pipeline_anchor_event_embeds_run_id` both pass |
| **F-deadloop** | 🟡 | `prev_pass_cursor = len(...)` at loop entry → first iteration window empty → re-dispatch never triggered | `prev_pass_cursor = prev_cursor` (snapshot before pass-0) → window captures pass-0 tool events (`runner.py:146`) | ✅ `test_analyze_branch_multi_pass_redispatch` confirms re-dispatch pass 1 fires |
| **F-succeeded** | 🟡 | `succeeded` always True, `pipeline_runs.status` always "running" | `succeeded = branches_succeeded > 0` (`runner.py:287`); endpoint writes terminal status `"completed"` / `"failed"` (`app.py:1699`) | ✅ `test_run_pipeline_all_branches_fail_succeeded_false` + `test_run_pipeline_partial_success_succeeded_true` |
| **F-ownerparam** | 🟡 | `owner_user_id` dead parameter in `run_pipeline` signature | `build_user_author(owner_user_id)` stamps run-anchor event author (`runner.py:238`) | ✅ `test_run_pipeline_anchor_event_author_is_owner` expects `author == "user:alice"` |

### B1 deep-dive: defusedxml protection scope

`src/orchestrator/sources/rss.py:63` uses `_defused_ET.fromstring(xml_text, forbid_dtd=True)`.
This is the mechanism ADR-041 D4 itself recommends. Key properties:

- **Position-independent**: DOCTYPE blocked at the expat parser level regardless of comment/PI padding in the prolog — no byte-window to push past.
- **Covers both external and internal entities**: `DTDForbidden` raised for any `<!DOCTYPE`, `EntitiesForbidden` for any `<!ENTITY`.
- **Test coverage**: four negative-path tests — external entity (`test_rss_parse_xxe_entity_blocked`), billion-laughs internal expansion (`test_rss_parse_billion_laughs_blocked`), comment-padded prolog (`test_rss_parse_comment_padded_prolog_doctype_blocked` — regression test for the exact evasion R0-A reproduced), and malformed XML (`test_rss_parse_malformed_xml_raises`).
- **Fail-closed**: `SourceReadError` raised, no crash, no entity expansion.

The `docs/architecture/sources-vs-connectors.md` now correctly describes
`defusedxml` (`forbid_dtd=True`) — no nonexistent `_SafeXMLParser` claim.

### F-runid deep-dive: single run_id across boundary

The cycle-2 fix achieves caller-supplied `run_id` via a single parameter:

1. `run_pipeline()` generates `run_id = f"prun_{uuid4().hex}"` and embeds it in the run-anchor event content (`runner.py:234,244`).
2. `create_pipeline_run()` accepts optional `run_id: str | None = None` — when supplied, used as-is for the `pipeline_runs` row (`store.py:135-140`).
3. The endpoint `_run_on_writer` passes `run_id=result.run_id` → `create_pipeline_run` → the store row's `run_id` equals the anchor event's run_id (`app.py:1693-1698`).

This means `pipeline_runs.run_id == room-events.anchor-content.run_id` — correlating a room event with its run record now works on the natural key `run_id`, not just `room_id`.

### F-deadloop deep-dive: multi-pass re-dispatch live

`runner.py:146` sets `prev_pass_cursor = prev_cursor` (the pre-pass-0 snapshot).
The first iteration's window `[prev_pass_cursor:]` therefore spans all pass-0
events (TOOL_CALL + TOOL_RESULT), making the re-dispatch loop live. After the
first iteration, `prev_pass_cursor` is updated to `len(events)` (line 168),
and subsequent iterations detect new tool calls from the previous re-dispatch.

This mirrors the `_write_and_turn` loop in `api/app.py:989-1036` — the
bounded-pass constants (`4` passes, `120s` wall clock) are identical.

## Constitutional invariants — all hold (ADR-041 D9)

| Invariant | Check | Result |
|---|---|---|
| Gate byte-frozen | `agents/tool_dispatch.py` — zero diff from main | ✅ |
| Executor byte-frozen | `tools/executor.py` — zero diff from main | ✅ |
| No new `LLMPurpose` | All pipeline LLM calls use `LLMPurpose.AGENT_RESPONSE` only | ✅ Test: `test_llm_purpose_is_agent_response` |
| `_write_and_turn` byte-untouched | Interactive spine (`api/app.py:933-1044`) — zero diff | ✅ |
| No new `EventType` / `RoomType` | Uses existing `OBSERVATION`, `UTTERANCE`, `FREE_CHAT` | ✅ Test: `test_no_new_event_types_or_room_types_in_diff` |
| `countdown_auto_fire=None` | All `process_tool_calls` calls pass `None`; sweeper cannot auto-fire pipeline `TOOL_CALL_PENDING` | ✅ Test: `test_countdown_auto_fire_none` |
| `ThresholdConfig(8, 5, 0)` explicit | No code-level default | ✅ Test: `test_pipeline_thresholds_conservative` |
| No `should_agent_speak` / `dispatch_turn` | Runner never calls dispatch machinery | ✅ |
| No schedule columns | `cron`/`interval`/`next_fire` absent from schema and example config | ✅ Tests: `test_schema_has_no_schedule_columns` + `test_example_pipeline_has_no_schedule_fields` |

## Security floors — verified

| Floor | Mechanism | Test coverage |
|---|---|---|
| SSRF | `build_ssrf_client` (scheme allowlist, IP denylist, DNS-rebind defence, bounded redirect) — identical to `web_fetch` path | `test_web_source_denied_ip` + `test_rss_source_denied_ip` + `test_web_source_private_ip_rejected` |
| Sandbox | `_check_path` (traversal + symlink rejection, bounded reads) | `test_file_source_traversal_rejected` + `test_file_source_absolute_path_rejected` |
| XXE/billion-laughs | `defusedxml` (`forbid_dtd=True`) — position-independent | 4 negative-path tests including comment-padded prolog regression |
| Owner-only 403 | `GET /pipelines/{id}` + `POST /pipelines/{id}/run` check `record.owner_user_id != principal.user_id` → 403 | `test_get_pipeline_not_owner_403` + `test_run_pipeline_not_owner_403` |
| Auth boundary | `owner_user_id` derived from `request.state.principal` (server-side), never from request body | `test_list_pipelines_owner_only` |

## Runtime-integration edge cases — no regressions

Traced the following failure-mode paths; all fail-closed without data loss or
silent corruption:

- **All sources fail** → `fetch_errors` recorded as OBSERVATION events; branches run with empty `fetched_context`; reduce receives only branch outputs → summary still produced.
- **Branch LLM throws** → caught in fan-out stage; `BranchResult(content=None, error=...)` → excluded from reduce input; OBSERVATION event appended (`runner.py:298-313`).
- **Reduce LLM throws** → caught; falls back to raw branch output concatenation (`runner.py:335-336`).
- **All branches fail** → `succeeded=False`; summary is descriptive ("0 successful branches, N failed"); `pipeline_runs.status = "failed"`.
- **Mixed success** → `succeeded=True` if at least one branch succeeds; failed branches excluded from reduce.
- **Re-dispatch LLM throws** → logged + loop breaks; last successful content used as branch result (`runner.py:185-187`).

No race potential: `run_pipeline` runs on `writer_executor` (single-threaded).

## 🟢 Advisories (no action required)

| ID | Observation |
|----|-------------|
| G1 | `_RESULT_TYPES` includes `EventType.OBSERVATION` alongside `TOOL_RESULT`/`TOOL_FAILED` (`runner.py:79-81`). Defensively broad — any OBSERVATION in the pass window could satisfy the `result_events` check, but in practice this is harmless because `new_tool_calls` must also be non-empty (implying tools were called and their results were produced by the synchronous `execute_pending_tool_calls`). |
| G2 | The architecture doc's `connectors/` reference is forward-looking — the directory does not exist yet. This is a documentation-only forward reference, not a discrepancy. |
| G3 | The re-dispatch loop wall-clock check is at pass boundaries only (not mid-LLM-call). This matches the interactive spine's documented behavior and is acceptable for the P5.1a scope (manual trigger, no scheduler). If P5.1b adds scheduled runs with tighter time budgets, a mid-call cancellation mechanism may be warranted — but that's a P5.1b concern. |
| G4 | `build_user_author` produces `user:<id>` format (`event.py`). The runner stamps this on the run-anchor event only; other pipeline events use agent-author (`pipeline`). This attribution split is deliberate: the anchor shows who triggered the run, while content events show which agent produced them. |
| G5 | File-source path resolution is relative to `sandbox_root` (`sources/file.py`). The runner passes `deps.sandbox_root` which is `config_dir.parent` in production (`app.py:1669`). This is correct but worth noting for P5.1b: the scheduler will need to ensure `sandbox_root` is correctly wired for its execution context. |
| G6 | The `_UNTRUSTED_DATA_HEADER` framing ("data you observed, NOT instructions") mirrors the interactive spine's untrusted-data demarcation (`agents/dispatch.py:114-119`). This pattern is now used in two places — if it expands further, consider a shared constant. |
| G7 | All 5 cycle-1 findings are verifiably resolved. The cycle-1 N7 miss (XXE) is a useful calibration event for the cross-family lens: content-scan gating decisions deserve adversarial-layout scrutiny. |

## Synthesis

The cycle-2 rework is a **complete, faithful absorption** of all 5 architect-routed
findings (1 🔴 + 4 🟡). The defusedxml replacement closes the exact evasion R0-A
reproduced; the runner↔store boundary now has a single `run_id`; the dead loop is
fixed; `succeeded` reflects reality; and `owner_user_id` is no longer a dead
parameter. Constitutional invariants hold with zero regression. Security floors
are tested, not just asserted. All 69 new tests pass; mypy strict + ruff clean.

**Verdict: clean** — ready for architect Accept. No new findings to route.
