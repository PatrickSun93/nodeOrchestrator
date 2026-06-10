---
task_id: P5.1c
round: R0-B
verdict: needs_architect
findings_count:
  red: 0
  yellow: 2
  green: 6
commit_reviewed: 4f08f20
lens: isolated dual-lens (Lens A = crossing/over-actuation + irreversible-send safety; Lens B = spine + reversible-envelope no-regression)
---

# P5.1c impl-stage R0-B cross-family review

## Lens preamble

This is the honesty crux of P5 — the first headless irreversible external actuation in the
product. The structural risks are over-actuation (any HARD tool becomes headless),
recipient-redirect (LLM exfils within the domain allowlist), dry-run→live state-machine
bypass (dry-run actually sends), and double-send (re-sweep / restart). I weighted these
four heaviest; the spine no-regression questions (COUNTDOWN byte-frozen, field-set pin
unchanged, existing callers behavior-identical) are secondary only because they're
pin-able via AST/field-set tests, which the impl includes.

## Findings

### 🔴 Red — blocking

None.

### 🟡 Yellow — architect attention recommended

| ID | Severity | File/Line | Claim |
|---|---|---|---|
| **R0B-Y1** | 🟡 | `core/event.py:428-430` (TYPED_METADATA NOTE) | **PipelineEmailDryRunMeta not registered in TYPED_METADATA — deviation from ADR-043 D6.** The ADR-043 D6 text states the metadata class is "registered in `TYPED_METADATA` (`core/event.py:394`)". The implementation does *not* register `EventType.OBSERVATION: PipelineEmailDryRunMeta` in `TYPED_METADATA`, with a code comment explaining that existing `OBSERVATION` events (runner output, MCP interpret) have free-form metadata and would fail `PipelineEmailDryRunMeta` model validation. Structural typing is instead enforced "at callsites via explicit `PipelineEmailDryRunMeta.model_validate()`". The technical reasoning is sound — registering would break pre-existing OBSERVATION deserialization — and the dry-run tests (`test_dry_run_records_observation_no_actuation`, `test_dry_run_would_actuate_false_on_mismatch`) validate the metadata at the callsite. But the ADR text now describes a registration that doesn't exist. **Suggested investigation:** either (a) amend ADR-043 D6 to note the callsite-enforcement pattern with the existing-OBSERVATION-conflict rationale, or (b) add a `_DRY_RUN_OBSERVATION_TYPES` registry separate from `TYPED_METADATA` and point the ADR there. The junior's code comment already cites "ADR-043 D6" — the intent to match is there; just the ADR text is stale. |
| **R0B-Y2** | 🟡 | `openapi.json` + `ui/src/api/schema.ts` (755+661 lines) | **openapi codegen regenerated entire /pipelines endpoint surface, not just email endpoints.** The `openapi.json` diff adds the full `/pipelines` CRUD surface (list, create, get, run, schedules CRUD) alongside the three new email endpoints. This is scope-overshoot in codegen — P5.1c only adds email-optin/promote/disable + the three new response fields on `_ScheduleResponse`. The overshoot is zero-risk (contract docs, not runtime code) but the diff is noisy and future readers will wonder why P5.1c appears to add `/pipelines` CRUD. **Suggested investigation:** confirm the codegen lock was intentionally regenerated whole-app (matching the P5.1b codegen pattern). If the codegen tool can be scoped to only the changed endpoints, that would be cleaner for future slices. Not blocking — this is a hygiene note. |

### 🟢 Green — confirmed invariants

| ID | Claim | Evidence |
|---|---|---|
| **R0B-G1** | `_PIPELINE_EMAIL_TOOL = "send_email"` is a module-level literal constant, the sole tool the actuator will ever actuate. | `app.py:614` (literal constant) + `app.py:294` (filter `meta.tool_name != _PIPELINE_EMAIL_TOOL`) + `test_hard_never_generalize_non_send_email_not_actuated` (git_push/apply_edit pendings never actuated even with live+enabled). |
| **R0B-G2** | Case-insensitive recipient matching: both sides lowercased before comparison. | `app.py:312`: `pending_to.lower() != pinned.lower()`. Test `test_live_mode_case_insensitive_recipient_match` exercises `Alice@Example.Com` vs `alice@example.com`. The `send_email` domain allowlist (ADR-036) is enforced downstream inside the tool impl — the pin is an additional narrowing, not a replacement. |
| **R0B-G3** | Dry-run is the mandatory first state. `set_schedule_email_optin` always sets `email_mode='dry_run'`. Promote requires an explicit second owner action (`promote_schedule_email_live`). The dry-run path records a typed `PipelineEmailDryRunMeta` OBSERVATION and does NOT call `_writer_approve_helper`, does NOT call the transport, does NOT append `TOOL_CALL`. | `store.py:388-401` (optin → dry_run) + `app.py:300-308` (dry-run branch: calls `_record_email_dry_run`, `continue` — never reaches `_writer_approve_helper`) + `test_three_state_transition_dry_run_then_live` (fresh optin → dry-run → no TOOL_CALL, promote → live → TOOL_CALL). |
| **R0B-G4** | No double-send on re-sweep/restart. Idempotency guaranteed by: (1) `resolved_call_ids` pre-filter in the actuator's dedicated scan, (2) the inherited still-pending check inside `_writer_approve_helper` (line 422-429). Crash between run and actuation → under-send, not double-send. | `app.py:280-285` (resolved_call_ids build) + `app.py:296` (skip if `meta.call_id in resolved_call_ids`) + `test_idempotency_no_double_send` (two calls → exactly one TOOL_CALL). |
| **R0B-G5** | Existing `human`/`auto_timer` `_writer_approve_helper` callers behavior-identical. Literal widening is additive: `Literal["human", "auto_timer"]` → `Literal["human", "auto_timer", "auto_pipeline"]`. Field-set pin byte-unchanged (5 fields, no new field added). | `app.py:383` (approval_source Literal widened, 1 line) + `event.py:225` (ToolCallMeta.approval_source widened, 1 line) + `tests/core/test_constitution.py` (zero diff — field-set pin unchanged) + `test_lens_b_field_set_pin_byte_unchanged` (asserts exactly the 5 canonical field names). |
| **R0B-G6** | COUNTDOWN spine genuinely untouched. `_countdown_sweeper` + `_discover_expired_pendings` never called from `_actuate_pipeline_emails`. `_schedule_act_on_writer` never calls them directly. `countdown_auto_fire=None` sentinels preserved; gate byte-frozen; no new LLMPurpose. | AST tests in `test_schedule_sweeper.py` verify both functions free from countdown spine. `test_lens_b_countdown_auto_fire_none_preserved` (≥2 sentinels in runner.py). `test_lens_b_no_new_llm_purpose` (no pipeline/email/routing LLMPurpose). `test_lens_b_autofire_guard_logic_unchanged` (ADR-040 D2 stamp guards present). |

## Synthesis

The implementation faithfully realizes all six plan tasks and all five all-α plan-stage-routing absorptions. The structural defenses against the four headline cross-family risks are correctly implemented:

- **Over-actuation**: `_PIPELINE_EMAIL_TOOL = "send_email"` literal constant + constitutional `HARD-never` test that git_push/apply_edit pendings are never actuated.
- **Recipient redirect**: case-insensitive exact-address match (both sides lowercased); the `send_email` domain allowlist is enforced downstream as a separate layer.
- **Dry-run bypass**: dry-run is the mandatory first state; `_record_email_dry_run` appends an OBSERVATION only and never reaches `_writer_approve_helper` or the transport.
- **Double-send**: `resolved_call_ids` pre-filter + inherited still-pending check. Crash semantics = under-send, never double-send.

The spine no-regression (Lens B) is pinned by AST tests, field-set tests, and sentinel-presence tests — all passing.

The two 🟡 findings are documentation/artifacts fidelity issues, not correctness issues. R0B-Y1 (TYPED_METADATA registration mismatch between ADR text and code) is the one worth architect attention — the code comment acknowledges the ADR text and explains the technical rationale for the deviation, but the ADR itself should be amended to match.

## Gate results

```
ruff check:     All checks passed
mypy --strict:  Success: no issues found in 305 source files
pytest:         All tests passed (no failures, no errors)
```

Diff: `origin/main...origin/claude/P5.1c-impl` @ 4f08f20 — +3086/−48 across 17 files (6 atomics + 1 fixup).
