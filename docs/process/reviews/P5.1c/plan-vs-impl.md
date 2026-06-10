---
task_id: P5.1c
stage: plan-vs-impl
actor: senior
date: "2026-06-10"
verdict: needs_architect
reviewed_branch: origin/claude/P5.1c-impl
reviewed_commit: 4f08f20
plan: docs/process/senior-plans/P5.1c.md
adr: ADR-043
routing_absorbed: docs/process/reviews/P5.1c/architect-routing-on-plan.md
summary: >
  6 atomics all present and faithful to plan + ADR-043 + the 5 α-absorbed routing
  items. Byte-frozen surfaces verified zero-diff. One 🟡 deviation from a routed
  absorption (R0B-Y2 TYPED_METADATA registration) — justified and invariant-preserving,
  but on an explicitly-routed item, so surfaced for architect blessing. Two 🟢 test
  hygiene notes. No plan-external expansion, no omissions.
findings:
  - id: PvI-Y1
    severity: yellow
    title: PipelineEmailDryRunMeta not registered in TYPED_METADATA (deviates from R0B-Y2 routed text)
  - id: PvI-G1
    severity: green
    title: No cross-pipeline IDOR (schedule-not-for-pipeline → 404) test on the 3 new email endpoints
  - id: PvI-G2
    severity: green
    title: Two Lens-B supplementary tests assert substring presence, not byte content
---

# P5.1c — Senior plan-vs-impl review

**Branch reviewed:** `origin/claude/P5.1c-impl` @ `4f08f20` (read via
`git diff origin/main...origin/claude/P5.1c-impl` from `main`; no checkout — shared worktree).

**Audit lens (per senior-planner.md §"plan-vs-impl"):** I am the only party who knows
what the plan said. External reviewers see deliverable-vs-spec; I see plan-vs-deliverable
— specifically whether the impl satisfies the acceptance criteria's *surface* while
drifting on a plan-implied *invariant* or a routed absorption instruction. This review's
one 🟡 is exactly that class.

---

## 1. Per-atomic fidelity

| Atomic | Plan intent | Impl @ 4f08f20 | Verdict |
|---|---|---|---|
| **P5.1c-1** | 3-state email columns + guarded ALTER + record fields + 3 mutators, defaults OFF/dry_run | `store.py`: `email_enabled/email_mode/email_recipient` in `CREATE TABLE` + `_ensure_schedule_email_columns` PRAGMA-guarded idempotent ALTER, called after `executescript`; all 4 readers populate the 3 fields; `create_schedule` defaults OFF; `set_schedule_email_optin` (→dry_run) / `promote_schedule_email_live` (→live) / `disable_schedule_email` (→off), each commits; `schema.py` record gains the 3 fields | ✅ faithful |
| **P5.1c-2** | Owner-private 3-state endpoints (optin→dry-run / promote→live / disable→off), mirror `_patch_schedule` auth, response surfaces email fields, codegen lock | 3 POST endpoints (`/email-optin` `/email-promote` `/email-disable`); each does `_principal` + `owner_user_id != principal → 403`, `get_pipeline None → 404`, `get_schedule None → 404`, **`sched.pipeline_id != pipeline_id → 404`**; promote on `not email_enabled → 409`; optin `email_recipient: str = Field(min_length=1)` → 422 on empty; `_ScheduleResponse` gains email fields; `openapi.json` + `ui/src/api/schema.ts` regenerated | ✅ faithful (one 🟢 test gap, PvI-G1) |
| **P5.1c-3** | Actuator: dedicated scan (NOT `_discover_expired_pendings`), eligibility gate (tool==send_email ∧ live ∧ case-insensitive recipient), actuate via `_writer_approve_helper(...,"auto_pipeline",owner,loop)`, two Literal widenings only, keyword `loop`, docstring honesty | `_PIPELINE_EMAIL_TOOL="send_email"` literal const; `_actuate_pipeline_emails` early-returns on `not email_enabled`; dedicated `get_room_events` scan keyed on `tool_name`/resolution, never touches `expires_at`; gate `pending_to.lower() != pinned.lower()` (R0B-Y1); live actuation via helper with `"auto_pipeline"` + `owner_user_id`; only edits are the two `Literal` annots (`app.py:383`, `event.py:224`); `_schedule_act_on_writer` gains **keyword** `loop=None` (R0A-Y3 — 6 positional test call-sites untouched); step 6 guarded by `email_enabled and loop is not None`; docstring rewritten to state the crossing truthfully (R0A-Y1) | ✅ faithful |
| **P5.1c-4** | Dry-run posture: typed `PipelineEmailDryRunMeta` **registered in TYPED_METADATA** keyed to OBSERVATION; dry-run records preview, no actuate/transport; pending stays waiting | Typed `PipelineEmailDryRunMeta(recipient, subject, would_actuate, owner_user_id, approval_source)` exists; `_record_email_dry_run` appends an OBSERVATION carrying `model_dump()`; no `_writer_approve_helper`, no TOOL_CALL, no transport; pending unresolved. **BUT not registered in `TYPED_METADATA`** — validated at callsite via the typed constructor instead (see PvI-Y1) | ⚠️ 🟡 deviation (PvI-Y1) |
| **P5.1c-5** | Honest rewrite of ADR-042 D1 isolation test (R0A-Y1) + Lens A/B pins; field-set pin byte-unchanged (R0A-Y2) | `test_schedule_act_on_writer_does_not_call_countdown_spine` rewritten: drops `_writer_approve_helper` from `_schedule_act_on_writer`'s forbidden set, keeps COUNTDOWN spine forbidden for **both** `_schedule_act_on_writer` and `_actuate_pipeline_emails`, adds positive pins (sole reach is `_actuate_pipeline_emails`; it is the only helper-caller). HARD-never test genuinely exercises `git_push`/`apply_edit` live pendings → 0 TOOL_CALL. `test_constitution.py` **byte-unchanged** (R0A-Y2 ✓). Recipient-pin, default-OFF, idempotency, owner-attribution all tested | ✅ faithful (two 🟢, PvI-G2) |
| **P5.1c-6** | Inscribe cross-ADR amendments (041 D5/D10, 042 D1, 040 D3/D4/D8, 036, 005/013/027), ADR-042 amendment explicitly names the D1 isolation as *deliberately lifted* | All seven ADRs annotated; ADR-042 amendment names the intentional-lift-not-silent-bypass + points at the rewritten test; ADR-043 own decision text not edited; not self-accepted (RC-3) | ✅ faithful |

**Routing absorption (all 5 α-items) verified landed in impl:**
D1 test honest-rewrite (R0A-Y1) ✓ · field-set pin untouched, value-set widen only (R0A-Y2) ✓ ·
keyword `loop`, positional call-sites unchanged (R0A-Y3) ✓ · case-insensitive recipient,
both sides lowercased (R0B-Y1) ✓ · typed `PipelineEmailDryRunMeta` (R0B-Y2) ✓ *mechanism deviates — PvI-Y1*.

---

## 2. Byte-frozen surface scan (the load-bearing check)

`git diff origin/main...origin/claude/P5.1c-impl` produces **zero diff-lines** on every frozen surface:

| Surface | Result |
|---|---|
| `pipeline/runner.py` (incl. `run_pipeline`, `countdown_auto_fire=None` ×2) | **0 diff-lines** ✓ |
| `agents/tool_dispatch.py` (the two RB-AUTOFIRE `expires_at` stamps) | **0 diff-lines** ✓ |
| `tools/executor.py` (`_execute_local_call`) | **0 diff-lines** ✓ |
| `autonomy/scoring.py` (`score`/`decide_tier`/gate) | **0 diff-lines** ✓ |
| `_countdown_sweeper` / `_discover_expired_pendings` defs | unchanged — names appear in the diff **only** in docstrings + the rewritten isolation test, never as edited defs ✓ |

The crossing is, as designed, a narrow post-run authorization layer (`_actuate_pipeline_emails`
+ `_record_email_dry_run` + step 6 wiring) that reaches the **non-frozen** `_writer_approve_helper`
and touches nothing in the spine. No plan-external expansion: the only other large hunks
(`openapi.json` +755, `ui/src/api/schema.ts` +661) are the codegen lock P5.1c-2 explicitly required.

---

## 3. Findings

### 🟡 PvI-Y1 — `PipelineEmailDryRunMeta` not registered in `TYPED_METADATA` (deviates from the routed R0B-Y2 absorption)

**Plan P5.1c-4 acceptance + routing R0B-Y2 both say, literally:** "*registered in
`TYPED_METADATA` (`event.py:394`) keyed to the existing OBSERVATION event type*" /
"*registered in `TYPED_METADATA`, structurally enforced rather than convention.*"

**Impl does NOT register it.** `event.py:428-431` instead adds a NOTE explaining that
OBSERVATION is deliberately left out of the global registry, because existing OBSERVATION
events (runner output, MCP interpret) carry free-form metadata and would fail
`PipelineEmailDryRunMeta` validation; structural typing is enforced at the callsite via the
typed `PipelineEmailDryRunMeta(...)` constructor in `_record_email_dry_run`.

**My assessment (evidence, not a routing call):** the deviation is *technically forced* — I
confirmed `validate_metadata` (`event.py:574`) applies a registered schema to **every** event
of that type, so registering OBSERVATION globally would byte-break existing free-form
OBSERVATION producers. The R0B-Y2 *intent* ("structurally typed rather than convention,
caught immediately") **is** preserved: the dry-run record is constructed through the Pydantic
model, so a schema drift fails at construction. So this is a faithful realization of the
*invariant* via a *different mechanism* than the routed text named.

**Why I'm not waving it through (`needs_architect`, not `clean`):** R0B-Y2 was an explicit
α-absorption the architect routed; the routed text named a specific mechanism
(`TYPED_METADATA` registration) that the impl could not follow. Per senior-planner.md
§"Halt + surface" ("impl satisfies acceptance criteria but drifts on plan-implied invariant
→ surface the drift; don't fix in the review; that's architect routing") this is the architect's
call to bless. Three dispositions the architect may pick:
  1. **Accept callsite-validation as faithful** (my lean — invariant preserved, registration
     was infeasible as written) → amend P5.1c-4 / ADR-043 D6 text to say "typed class
     enforced at callsite (OBSERVATION stays globally free-form)"; verdict bumps clean.
  2. Want the registry mechanism after all → would require a sub-keyed/per-author registry
     or a dedicated EventType (the latter was explicitly rejected in ADR-043 D6 scope-narrowing).
  3. Want a `model_validate()` round-trip assertion added to the dry-run path to harden the
     "caught immediately" guarantee.

Not blocking — no product-correctness hole; the dry-run path is reversible and typed.

### 🟢 PvI-G1 — No cross-pipeline IDOR test on the 3 new email endpoints

P5.1c-2 acceptance lists "*schedule-not-for-pipeline → 404 (mirror `_patch_schedule`)*". The
guard **is implemented** in all three email endpoints (`if sched.pipeline_id != pipeline_id:
raise 404`). But `test_schedule_endpoints.py` has no `test_email_*_cross_pipeline_idor_404`,
while the pre-existing endpoints each have a `test_*_cross_pipeline_idor_404`. Given P5.1b cyc1
landed a cross-pipeline IDOR **must-fix** on exactly this side-table auth surface (senior+R0-A
caught it, r0b missed it), the missing test on the new security-relevant surface is worth a
finder pass. Code is correct; only the test is absent. (Dual-lens Lens A may want to add it.)

### 🟢 PvI-G2 — Two Lens-B supplementary tests assert substring presence, not byte content

`test_lens_b_no_new_llm_purpose` (`test_schedule_sweeper.py`) filters the purpose set by
substring (`"pipeline"|"email"|"routing"`) rather than asserting the full set is unchanged —
a new `AGENT_RESPONSE`-adjacent purpose without those substrings would slip past it.
`test_lens_b_autofire_guard_logic_unchanged` asserts the strings `"ADR-040 D2"` / `"expires_at"`
/ `"HARD_CONFIRM"` / `"reversibility_floor"` are *present* in `tool_dispatch.py` source — it
would still pass if the stamp **logic** changed while keeping those tokens. The **real** guards
are the project's existing constitutional/byte-frozen tests (which my §2 scan confirms pass
with zero diff), so these are belt-and-suspenders; flagging only so a reviewer doesn't read
them as the primary byte-pin.

---

## 4. Verdict

**`needs_architect`** — driven solely by **PvI-Y1**: the impl deviates from the literal
mechanism of a routed (α-absorbed) instruction (R0B-Y2 `TYPED_METADATA` registration). The
deviation is justified and invariant-preserving (my lean: accept), but blessing a deviation
from a routed absorption is the architect's call, not mine — I surface, the architect routes.
The two 🟢 are test-hygiene notes for the dual-lens finders, not blockers.

Everything else — all 6 atomics, all 5 routing absorptions, the honesty-crux test rewrite
(R0A-Y1, the headline), the field-set pin byte-unchanged (R0A-Y2), and every byte-frozen
surface — is faithful with zero drift. No plan-external expansion; no omissions.

Per ADR-008 Amendment 1 (Route B) the state advances to `awaiting_R0_A` regardless of
verdict; this `needs_architect` frontmatter flags PvI-Y1 for the architect's routing pass
alongside the dual-lens R0 reviews.
