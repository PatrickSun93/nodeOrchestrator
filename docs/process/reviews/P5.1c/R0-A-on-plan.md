---
task_id: P5.1c
stage: plan (R0-A-on-plan; plan + ADR-043 Proposed, no impl yet)
reviewer: architect-partner (R0-A)
verdict: clean
verdict_history:
  - "2026-06-10: R0-A-on-plan → needs_architect (0🔴; Y1 headline d1-test-vacuous + Y2/Y3 minor)"
  - "2026-06-10: architect routed all-α (architect-routing-on-plan.md); senior absorbed Y1/Y2/Y3 into plan + ADR-043 (RC-10) → clean"
scope: faithfulness to ratified C0–C8 + atomic decomposition + ADR-043 completeness/implementability + structural boundary-guard tightening
verified_against: origin/main @ dd5ced5 (HEAD 7779622); plan 60e973a; brief dd5ced5
lenses_pre-checked: A (crossing/over-actuation + irreversible-send safety) · B (spine + reversible-envelope no-regression)
---

# R0-A-on-plan — P5.1c headless pipeline email (the honesty crux)

This is the first headless **irreversible actuation** in the product; reviewed strict. I verified every seam the plan/ADR depend on against live source (cited inline). **The design is sound and faithful to the ratified C0–C8.** One finding (**Y1**) is a genuine plan gap at the honesty bar that needs an architect routing call before impl; two are minor accuracy/completeness items.

## Verdict

**needs_architect** — design + ADR-043 are faithful and implementable; **but** the plan leaves an existing ADR-042 D1 constitutional test silently vacuous (Y1), which at *this* slice (the honesty crux) is exactly the failure mode the slice must not ship. Y1 should be absorbed into the plan (senior revision) before junior dispatch. Y2/Y3 are minor and can ride along.

## What I verified faithful (no findings)

- **C0/D1 scheduled-only** — opt-in lives on `pipeline_schedules`; `/run` untouched (plan §5 confirms zero code there). Faithful.
- **C1/D2 reuse `_writer_approve_helper` 3rd caller** — the helper (`app.py:379-471`) reconstructs the `TOOL_CALL` from the persisted `ToolCallPendingMeta` (`:434-449`), **never from the caller**; widening `approval_source` to `["human","auto_timer","auto_pipeline"]` is additive at both pin sites (`app.py:383`, `event.py:224`). The actuator validating `to` *before* calling the helper preserves reconstruct-from-record. Faithful + implementable.
- **C2/D3 config-pinned recipient** — discovery + match are implementable: `ToolCallPendingMeta` carries `tool_name` + `params` (`event.py:371-373`), so `params['to']` is readable for the exact-match gate; `send_email`'s own allowlist stays enforced downstream inside `_make_send_email` (`network_tools.py:478-495`, `to` from `params.get("to")` `:458`) — the pin is an *additional* narrowing, not a replacement. Faithful.
- **C3/D4 boundary guard** — module-level literal `_PIPELINE_EMAIL_TOOL = "send_email"` + the HARD-never constitutional test (P5.1c-5 Lens A) is the structural guard against "any HARD tool headless," and it is specified to *actually exercise* a non-`send_email` HARD pending. Structurally tight, test-pinned. Faithful.
- **C4+C5/D5 3-state default-OFF** — `email_enabled INTEGER DEFAULT 0` / `email_mode TEXT DEFAULT 'dry_run'` / `email_recipient TEXT` via guarded `ALTER TABLE ADD COLUMN`; precedent verified at `memory/store.py:107-118` (`PRAGMA table_info` guard, per-column). Fail-closed in both dimensions. Owner-private endpoints mirror `_patch_schedule` (`app.py:2119-2176`, `_principal` + `owner_user_id != → 403`, schedule-not-for-pipeline → 404). Faithful + implementable.
- **C5/D6 dry-run mandatory first state** — opt-in lands in dry-run (`set_schedule_email_optin`), promote is an explicit second action, dry-run records an `OBSERVATION` and does not call helper/transport. Faithful to the architect's strengthening.
- **C6/D7 `RB-PIPELINE-EMAIL`** — inscribed plainly, bounded by the full union, "once sent, no recall — never softened." Lens A honestly states "a crash between run and actuation **under**-sends, never double-sends." Faithful, not over-claimed.
- **C7/D8 ADR-043 + amendment set** — new ADR-043; amends ADR-041 D5/D10, ADR-042, ADR-040 D3/D4/D8, ADR-036, note on ADR-005/013/027. (Gap on the ADR-042 amendment text — see Y1.)
- **Byte-frozen surface** — plan §4 + ADR Lens B pin `countdown_auto_fire=None` (`runner.py:153,223`), the two RB-AUTOFIRE stamps (`tool_dispatch.py:137-145`), `_execute_local_call` + gate, and explicitly forbid reusing `_discover_expired_pendings` (new dedicated scan, never reads `expires_at`). No new `LLMPurpose`. Faithful.

## Findings

### 🟡 Y1 (headline) — the ADR-042 D1 isolation test goes silently vacuous; the plan addresses it nowhere

**Evidence.** `tests/api/test_schedule_sweeper.py:492-516` (`test_schedule_act_on_writer_does_not_call_countdown_spine`) parses `inspect.getsource(_schedule_act_on_writer)`, walks the AST, and asserts `"_writer_approve_helper" ∉ {func.id of direct ast.Name calls}`, with the message *"`_schedule_act_on_writer` must not call `_writer_approve_helper` (ADR-042 D1)"*. The in-code docstring at `app.py:618-619` states the same invariant ("Never calls … `_writer_approve_helper` (D1 — sibling shares zero spine-critical code)").

Plan **P5.1c-3** adds step-6: `_schedule_act_on_writer → _actuate_pipeline_emails → _writer_approve_helper`. Because the test detects only **one-hop** `ast.Name` calls, the indirection through the separate `_actuate_pipeline_emails` function means `_writer_approve_helper` is **not** in `_schedule_act_on_writer`'s direct call set → **the test keeps passing while the invariant it names is deliberately violated.** (I confirmed the mechanism: `_actuate_pipeline_emails` is defined as a separate function and called by name, so the AST sees `_actuate_pipeline_emails`, not `_writer_approve_helper`.)

**Why this matters at *this* slice.** The plan's own §4 forcing function says "Constitutional tests must load, not be vacuous." Leaving this test untouched produces a green test that asserts "the schedule path never actuates (ADR-042 D1)" *at the exact moment P5.1c makes the schedule path the **one** path that actuates an irreversible op* — a durable, misleading honesty defect in the suite, on the honesty-crux slice. This is the P5.1b cyc3 vacuous-test failure mode recurring. The plan names this test in P5.1c-3 / -5 / -6 **nowhere**; the docstring fix and the ADR-042 amendment text are likewise silent on the *deliberate lifting* of the D1 no-actuation isolation.

**Lean (architect routes α vs β):** revise the plan so —
- **P5.1c-5 (or -3)** honestly rewrites `test_schedule_act_on_writer_does_not_call_countdown_spine`: **drop** `_writer_approve_helper` from `forbidden_calls` (now legitimately reachable, but *only* via the narrow `_actuate_pipeline_emails` email path), **keep** `_countdown_sweeper` + `_discover_expired_pendings` forbidden (COUNTDOWN spine stays untouched — Lens B), and add a **positive** pin that the sole new actuation reach is `_actuate_pipeline_emails` (the D4 `send_email`-only + HARD-never tests carry "*what* it actuates").
- **P5.1c-3** updates the `app.py:618-619` docstring to state the crossing truthfully.
- **P5.1c-6**'s ADR-042 amendment explicitly names that D1's "sibling shares zero spine-critical code / never calls `_writer_approve_helper`" isolation is **deliberately lifted for the email actuator** (not silently bypassed).

This is honest-inscription completeness, not a design change — the crossing itself is ratified (C1a). α = absorb into the plan now (lean); β = note + fix at impl (weaker — leaves the junior to discover an unflagged green-but-lying test, against "surface, don't improvise").

### 🟡 Y2 (minor, accuracy) — the `approval_source` constitutional-test change is mischaracterized (field-set vs value-set)

`tests/core/test_constitution.py:281-287` (`test_constitution_tool_call_meta_field_set_pin`) pins `ToolCallMeta` to **exactly five field names** `{tool_name, call_id, params, approver_user_id, approval_source}` — it does **not** enumerate `approval_source`'s Literal *values*. P5.1c adds **no field**; it only widens the Literal value set. So that field-set pin needs **zero change** (stays five names). Plan P5.1c-3 ("`test_constitution.py` is updated to admit the new value") and P5.1c-5 Lens B ("the `ToolCallMeta` constitutional test updated **additively**") are imprecise and risk the junior either weakening the field-set pin or hunting a nonexistent value-list. **Lean:** the only required production change is the two type annotations (`event.py:224`, `app.py:383`); the field-set pin at `test_constitution.py:287` stays **byte-unchanged**; the new `auto_pipeline` value is exercised by the P5.1c-3 actuator tests (`test_auto_fire.py` only ever *uses* `"auto_timer"`, it does not assert a value set, so nothing there breaks). Re-word P5.1c-3/-5 accordingly.

### 🟡 Y3 (minor, completeness) — signature-change blast radius undercounts test call-sites

Threading `loop` into `_schedule_act_on_writer` (`app.py:600`) changes its signature. Plan P5.1c-3 names only the `functools.partial` at `:758`, but **six** existing positional call-sites in `tests/api/test_schedule_sweeper.py` (`:273, 301, 328, 333, 385, 428`, all `_schedule_act_on_writer(ctx, sid, _NOW)`) will break. **Lean:** either add these six to the blast-radius list, or make `loop` a keyword param so existing call-sites need no change (the dry-run / `email_enabled=0` paths those tests exercise never reach the helper anyway). The full-pytest gate would catch the break, but the plan enumerates blast radius meticulously elsewhere — this omission is inconsistent and worth one line.

## Boundary-guard structural check (does it resist "any HARD tool headless"?)

**Yes, structurally.** The crossing is pinned to a single named tool by a literal constant (D4) **and** a HARD-never constitutional test that actually exercises a non-`send_email` HARD pending (P5.1c-5). No reversibility band, no per-tool flag. Combined with default-OFF + dry-run-first + owner-pinned recipient + the unchanged `send_email` allowlist, the generalization risk is contained at the structural level — **provided Y1 is fixed**, so the suite does not *also* carry a now-false "schedule never actuates" assertion that obscures the real, narrow crossing.

## Routing surface for the architect

| Finding | Lean | Your call |
|---|---|---|
| **Y1** ADR-042 D1 test vacuous + docstring/amendment silent on the deliberate crossing | **α** — absorb into plan (rewrite the test honestly, fix docstring, name the lifting in the ADR-042 amendment) before junior dispatch | α / β |
| **Y2** `approval_source` field-set vs value-set test imprecision | α — reword P5.1c-3/-5 (annotations only; field-set pin unchanged) | α / β |
| **Y3** 6 unflagged `_schedule_act_on_writer` test call-sites | α — list them or make `loop` keyword | α / β |

No 🔴. Nothing blocking, nothing impossible — the seams are real and the design honors C0–C8. The single load-bearing item is **Y1**: at the honesty crux, a constitutional test that silently stops meaning what it says is the highest-leverage way this slice fails its bar, and the fix is plan-completeness, not redesign.
