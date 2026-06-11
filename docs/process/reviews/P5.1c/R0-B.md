---
task_id: P5.1c
round: R0-B
cycle: 2
verdict: clean
findings_count:
  red: 0
  yellow: 0
  green: 7
commit_reviewed: c658685
lens: cross-family (isolated dual-lens — Lens A = crossing/over-actuation + irreversible-send safety; Lens B = spine + reversible-envelope no-regression)
verdict_history:
  - round: R0-B (cycle 1)
    commit: 4f08f20
    verdict: needs_architect
    findings: "0🔴 + 2🟡 + 6🟢"
  - round: R0-B (cycle 2)
    commit: c658685
    verdict: clean
    findings: "0🔴 + 0🟡 + 7🟢"
---

# P5.1c R0-B cross-family review — cycle-2 re-review (covers cycle-1)

## Lens preamble

This is the cycle-2 re-review of the all-α impl rework at `c658685`. Cycle-1
(`4f08f20`) produced `needs_architect` with 0🔴 + 2🟡 + 6🟢 across three review
perspectives (R0-A, R0-B, plan-vs-impl). The architect routed all-α: Y1 doc-only,
Y2 both-non-empty, Y3 fail-closed, 🟢 cross-pipeline IDOR test, R0B-Y2 codegen
accept-hygiene. The rework is 1 commit, 4 files, +118/−3.

The cross-family failure-mode lens for this re-review focuses on the **irreversible
path**: does the Y3 `== "live"` explicit branch genuinely fail-closed on every
non-live value? Does Y2 both-non-empty cover the degenerate both-empty case? Do
the IDOR tests actually guard cross-pipeline access? And does the spine remain
byte-frozen through all of it?

---

## Cycle-1 findings — resolved status

| ID | Cycle-1 verdict | Cycle-2 disposition |
|---|---|---|
| **R0B-Y1** (TYPED_METADATA not registered) | 🟡 needs_architect | **Resolved.** ADR-043 D6 text amended to describe callsite-typed construction + the OBSERVATION-conflict rationale. The ADR text now matches the code; no code change needed. |
| **R0B-Y2** (openapi codegen overshoot) | 🟡 accept-hygiene | **Accepted as-is per architect routing.** No rework. |
| **R0B-G1–G6** | 6 🟢 invariants confirmed | **Still hold.** Cycle-2 touches none of the G1–G6 evidence surfaces except the eligibility gate (G2 recipient match) which the Y2 change tightens, not relaxes. |

---

## Cycle-2 diff — per-α-item analysis

### Y1: ADR-043 D6 text amendment (doc-only, `docs/decisions/ADR-043-headless-pipeline-email.md`)

The D6 paragraph now reads: *"enforced via **callsite-typed construction** — the
actuator constructs `PipelineEmailDryRunMeta(...)` directly and calls `model_dump()`
before storing; the reader calls `PipelineEmailDryRunMeta.model_validate(event.metadata)`
to round-trip-validate. Registering `EventType.OBSERVATION → PipelineEmailDryRunMeta`
in `TYPED_METADATA` is infeasible: `validate_metadata()` applies the registered
schema to **every** `OBSERVATION` event at append; all pre-existing free-form
`OBSERVATION` events (runner output, MCP interpret) would fail validation."*

This is honest and accurate. The code was already correct; the ADR text now
matches. No runtime change.

### Y3: `== "live"` explicit, unknown → fail-closed (`app.py:+8`, `test_pipeline_email_actuator.py:+42`)

**Before (cycle-1):**
```python
if schedule.email_mode == "dry_run":
    _record_email_dry_run(...)
    continue
# Falls through — ANY non-dry_run value reaches live actuation
pending_to = str(meta.params.get("to", ""))
```

**After (cycle-2):**
```python
if schedule.email_mode == "dry_run":
    _record_email_dry_run(...)
    continue
elif schedule.email_mode != "live":
    # Unknown mode → fail-closed (ADR-043 D5)
    _log.debug(...)
    continue
# Only "live" reaches here
```

**Cross-family failure-mode analysis.** The D5 spec names exactly two valid modes:
`'dry_run'` and `'live'`. The `!= "live"` guard catches **all** non-live values:
garbage strings (`'bogus_unknown'`), SQL injection residues, corrupted DB values,
future code drift. This is **structurally fail-closed** — the only permitted
transition to send is an exact `'live'` match. The guard also catches `None` (no
Python `None` can appear in the DB column — `TEXT NOT NULL DEFAULT 'dry_run'` —
but even if it could, `None != "live"` → True → skip). The test
`test_unknown_email_mode_does_not_actuate` patches `email_mode = 'bogus_unknown'`
and asserts **both** 0 TOOL_CALL events **and** 0 OBSERVATION events — the dry-run
path also never reached, which is correct (a garbage mode should not produce
misleading preview records either).

### Y2: both-non-empty + case-insensitive match (`app.py:-2+2`, `app.py:1`, comment change)

**Before (cycle-1):**
```python
if pending_to.lower() != pinned.lower():
    ... skip ...
```

**After (cycle-2):**
```python
if not (pending_to and pinned and pending_to.lower() == pending_to.lower()):
    ... skip ...
```

**Cross-family failure-mode analysis.** The original condition had a deterministic
fail-OPEN path: when both `pending_to` and `pinned` are empty strings,
`"".lower() != "".lower()` → `False` → the `if` body **not taken** → execution
falls through to actuation. An empty-pending-to + empty-pin would call
`_writer_approve_helper` with `params["to"] = ""`, which would be caught
downstream by the `send_email` mandatory-recipient check inside
`network_tools.py` — so the email wouldn't *send*, but the actuation attempt
would still log a TOOL_CALL, and the pending would be resolved erroneously.

The new condition `pending_to and pinned and pending_to.lower() == pinned.lower()`
covers all degenerate cases:
- Both empty → `not ("" and "" and ...)` → `not False` → skip ✅
- `pending_to` empty, `pinned` non-empty → skip ✅
- `pending_to` non-empty, `pinned` empty → skip ✅
- Both non-empty, no match → skip ✅
- Both non-empty, case-insensitive match → actuate ✅

**Crucially**, `_record_email_dry_run` (`app.py:740+`) already computed
`would_actuate = bool(pending_to and pinned and pending_to.lower() == pinned.lower())`
— the dry-run path already had the both-non-empty guard. Cycle-2 brings the
**live** path into alignment with the **dry-run** path. This eliminates the
only divergence point between the two paths' recipient-validation logic.

### 🟢 Cross-pipeline IDOR tests (`test_schedule_endpoints.py:+59`)

Three tests added: `test_email_optin_cross_pipeline_idor_404`,
`test_email_promote_cross_pipeline_idor_404`,
`test_email_disable_cross_pipeline_idor_404`. Each creates a schedule under
`pipe_other`, then calls the endpoint under `pipe_self`'s URL with
`pipe_other`'s `schedule_id`. All assert `status_code == 404`.

**Cross-family analysis.** The endpoint guards (`sched.pipeline_id != pipeline_id
→ 404`) were already present in cycle-1. The test gap was the exact class that
P5.1b A1 proved can persist unnoticed through review: cross-pipeline IDOR on
side-table endpoints. The promote test correctly opts-in first under the correct
pipeline (since promote requires `email_enabled=1`), then attempts promotion via
the wrong pipeline URL — a realistic 2-step attack sequence. All three tests
pass. This closes the P5.1b A1 residual on P5.1c's security-critical surface.

---

## Findings

### 🔴 Red — blocking

None.

### 🟡 Yellow — architect attention recommended

None. All four α-routed items are faithfully resolved.

### 🟢 Green — cycle-2 confirmed invariants

| ID | Claim | Evidence |
|---|---|---|
| **R0B-G7** | Y3 fail-closed is structurally complete. The `!= "live"` guard catches all values that are not the exact string `'live'`: garbage, corruption, future drift, `'dry_run'` (already handled above). Only `'live'` reaches the `_writer_approve_helper` call. | `app.py:689` (`elif schedule.email_mode != "live":`) + `test_unknown_email_mode_does_not_actuate` (0 TOOL_CALL + 0 OBSERVATION on `'bogus_unknown'`). |
| **R0B-G8** | Y2 both-non-empty aligns live with dry-run. The dry-run path already computed `would_actuate = bool(pending_to and pinned and ...)`. The live path now uses identical logic. The both-empty degenerate case (fail-OPEN in cycle-1) is now fail-CLOSED. | `app.py:699` (`if not (pending_to and pinned and ...)`) — structurally identical to `app.py:740+` (`would_actuate = bool(pending_to and pinned and ...)`). |
| **R0B-G9** | Cross-pipeline IDOR tests structurally guard all three email endpoints. Each test exercises the `sched.pipeline_id != pipeline_id → 404` guard at the HTTP layer. The promote test models a realistic 2-step attack (opt-in under correct pipeline, promote via wrong). | `test_schedule_endpoints.py:546-603` — 3 tests, all assert 404. All pass. |
| **R0B-G10** | Cycle-1 🟢 invariants G1–G6 all still hold. Cycle-2 diff touches none of their evidence surfaces except G2 (recipient matching) which Y2 tightens. The spine (gate, executor, runner, autonomy, COUNTDOWN, LLMPurpose), the constitution test, the Literal widening, the `_PIPELINE_EMAIL_TOOL` literal constant, the dry-run mandatory-first-state, and the idempotency pre-filter are all untouched by the cycle-2 diff. | `git diff 4f08f20..c658685 --stat` = 4 files (ADR-043, app.py, 2 test files). Manual byte-frozen scan: `tool_dispatch.py`, `executor.py`, `runner.py`, `autonomy/`, `purposes.py`, `test_constitution.py` all zero-diff. |
| **R0B-G11** | ADR-043 D6 text is now honest about the actual enforcement mechanism. The ADR text names the callsite-typed-construction pattern, explains the `OBSERVATION` universal-`validate_metadata()` conflict, and describes the write-time + read-time enforcement. | `ADR-043-headless-pipeline-email.md:64` — amended paragraph. |
| **R0B-G12** | No new LLMPurpose; existing `human`/`auto_timer` callers behavior-identical. The cycle-2 diff adds no imports, no new types, no new caller paths — only tightens existing guards in `_actuate_pipeline_emails`. | `git diff 4f08f20..c658685 -- src/orchestrator/llm/` = empty. |
| **R0B-G13** | The `_record_email_dry_run` function (`would_actuate` computation) is untouched by cycle-2. Its existing both-non-empty logic was the reference Y2 aligns to — no regression risk. | `git diff 4f08f20..c658685 -- src/orchestrator/api/app.py` — dry-run branch unchanged. |

---

## Synthesis

The cycle-2 rework is faithful, tight, and addresses the exact set the architect
routed. The four changes form a coherent "close the irreversible-actuation guard
gaps" bundle:

- **Y3** closes the fail-open channel on unknown `email_mode` — the irreversible
  crossing's outermost guard.
- **Y2** closes the degenerate both-empty channel on the live eligibility gate,
  aligning it with the dry-run path's already-correct logic.
- **IDOR tests** close the P5.1b A1 cross-pipeline test gap on the three new
  email endpoints.
- **ADR D6 text** closes the spec-code fidelity gap without changing any code.

No new issues introduced. The cross-family failure-mode lens finds no residual
bypass, no silent drift, no regression. The spine remains byte-frozen across
all constitutional surfaces. The three new tests (Y3 unknown-mode + 3 IDOR)
add genuine coverage on the exact gaps the architect identified.

**Verdict: clean.** The P5.1c impl is ready for merge.

---

## Gate results (isolated worktree @ `c658685`)

```
ruff check:     All checks passed
mypy --strict:  Success: no issues found in 305 source files
pytest:         37 passed (test_pipeline_email_actuator: 10, test_schedule_endpoints: 27)
                No failures, no errors
```

Byte-frozen zero-diff confirmed:
```
tool_dispatch.py    (gate, RB-AUTOFIRE stamps):    0 diff-lines
executor.py         (_execute_local_call):         0 diff-lines
runner.py           (run_pipeline, countdown_auto): 0 diff-lines
autonomy/           (score/decide_tier):            0 diff-lines
purposes.py         (LLMPurpose enum):              0 diff-lines
test_constitution.py (field-set pin):               0 diff-lines
```

---

## Diff summary

`4f08f20..c658685` — 1 commit, 4 files, +118/−3:

| File | + | − | Purpose |
|---|---|---|---|
| `docs/decisions/ADR-043-...md` | 1 | 1 | D6 text: TYPED_METADATA → callsite enforcement |
| `src/orchestrator/api/app.py` | 12 | 2 | Y3 fail-closed branch + Y2 both-non-empty guard |
| `tests/api/test_pipeline_email_actuator.py` | 48 | 0 | Y3 unknown-mode fail-closed test |
| `tests/api/test_schedule_endpoints.py` | 59 | 0 | 3 × cross-pipeline IDOR tests |
