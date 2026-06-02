---
task_id: P2.7
kind: architect-routing
stage: plan
date: 2026-06-02
reviews_acked:
  - R0-A-on-plan.md
  - R0-B-cross-family.md
joint_verdict: needs_architect (R0-A 0🔴/2🟡/11🟢 + R0-B 0🔴/2🟡/6🟢; c1 routing solid, c2 security had an env-inheritance leak — Y2 closes it)
decisions:
  Y1: α (S2 cost_ceiling — add decision_trace for unknown-cost-skipped models + configurable on_unknown_cost, default keep; default behavior unchanged)
  Y2: α MUST-FIX (security — S3 base_url=None must explicitly clear ANTHROPIC_BASE_URL from the subprocess env so parent-process inheritance can't bypass the allowlist; + discriminating test)
  split: B (batched single P2.7 task — prelude → S1∥S2∥S3 → S4 → e2e; dual-lens R0-B dispatched to the S2/S3 atomics within ONE review; single merge; NOT 4 sub-slice tasks)
---

# P2.7 architect routing — plan stage (Y1 → α, Y2 → α MUST-FIX; split → B batched)

**Architect decision (this session):** joint **needs_architect**. The c1 routing boundary is solid (the override is deterministic code, structurally enforced — both lenses confirmed); the c2 security boundary had a real **design leak** (subprocess env inheritance — r0b's cross-family catch) that **Y2 closes**. Both 🟡 → α (Y2 a must-fix); the slice shape → **(B) batched single task**.

This file is the **signal artifact for the senior revision session.** Senior reads this + `R0-A-on-plan.md` + `R0-B-cross-family.md` + the current plan + ADR-023 + the amendments, absorbs the two α + re-shapes §3 to the batched orchestration, and bumps verdicts per RC-10. Then the architect accepts ADR-023 + the amendments.

## Per-finding routing

### Y1 → α — S2 cost_ceiling: trace unknown-cost skips + configurable `on_unknown_cost` (default keep)

**Finding (R0-A Y1 ≡ R0-B Y1, two-lens overlap):** `cost_ceiling` **keeps** unpriced models (`cost_per_1m_output is None`), so an unpriced model silently evades the cost-governance dial, with no trace visibility.

**Action (senior absorb — ADR-023 D2 + plan S2 acceptance):**
- **Add a `decision_trace` entry** recording "N models skipped the ceiling check (unknown cost)" — so the softness is **visible** (the minimum both lenses required); surfaced in the S4 startup error / `NoSuitableModelError` trace.
- **Add a configurable `on_unknown_cost: Literal["keep", "drop"]`** to `GlobalLLMOverride`, **default `keep`** — so the **default behavior is unchanged** (keep-on-unknown stays default, preserving None-cost sentinel/free models), but hard-ceiling deployments can opt into `drop` (fail-closed). Frozen + `extra="forbid"` (schema §6).
- **Not** γ (default-drop) — would silently break routing where sentinel/free models carry `None` cost.

*Boundary note:* this is **not** a c1 routing leak (the override is deterministic code either way) — it's a cost-**governance-completeness** gap. c1 stays solid.

### Y2 → α MUST-FIX (security) — S3 subprocess env must clear `ANTHROPIC_BASE_URL` when `base_url=None`

**Finding (R0-B Y2 — cross-family security catch; the in-family R0-A missed it):** the c2 fail-closed allowlist governs only the **configured** `base_url`. When `base_url` is unset (`None`), the `claude` CLI subprocess **inherits the parent process's environment**, so a parent-process `ANTHROPIC_BASE_URL` (OS env / wrapper / container / prior invocation) reaches the child **uncontrolled** — routing conversation content + the API key to an untrusted backend **without passing the allowlist**. The c2 guarantee is silently bypassed. **This is a real design leak, not enforcement-strength.**

**Action (senior absorb — ADR-023 D4 + plan S3 acceptance — MUST-FIX before P2.7 impl):**
- When `base_url is None`, `providers/claude_code_cli.py` must construct a **controlled subprocess env that clears/excludes `ANTHROPIC_BASE_URL`** (it does not inherit the parent's value) — so `base_url=None` ⇒ **true Anthropic default regardless of parent env**. (When `base_url` is set + allowlisted, it sets `ANTHROPIC_BASE_URL=<base_url>` as before.) State the **subprocess-env contract** in ADR-023 D4.
- **Add a discriminating test:** parent env has `ANTHROPIC_BASE_URL=<untrusted>` + config `base_url: None` → the child process does **NOT** receive `ANTHROPIC_BASE_URL` (the inheritance bypass is closed); and a set-but-allowlisted `base_url` still reaches the child.

*Severity:* 🟡 because it's caught **pre-impl** (a spec gap to close before the S3 atomic); it would be 🔴 if it reached impl (a shipped security-boundary bypass). **Treat as must-fix, not defer.** This closes the c2 leak — after Y2, c2 is fail-closed on **both** the config path (the allowlist, already solid) and the env-inheritance path.

### Split → (B) batched single P2.7 task (architect ruled; overrides the senior's split-4 recommendation)

The architect ruled **(B) batched single task** (not the plan §3 split-4 recommendation). One `P2.7` task, batched atomics:

```
prelude (config_loader shared struct)  →  S1 ∥ S2 ∥ S3 (parallel atomics)  →  S4 (sequenced)  →  e2e
```

- **One state file, one review, single merge** — "P2 closes" is one atomic moment.
- **Dual-lens R0-B dispatched to the S2 + S3 atomics within the ONE review** (`requires_cross_family_review: true` stays; the external R0-B prompt targets S2/S3); S1/S4 single-lens within the same review.
- **Senior absorb:** re-shape plan §3 from "split into 4 sub-slice tasks" to this **batched single-task** orchestration (prelude → S1∥S2∥S3 → S4 → e2e); the design (ADR-023 D1–D8 + the ADR-012 amendment + §2 acceptance) is unchanged — only the slice/workflow shape changes. (The senior's split-4 recommendation + the (A)/(B) trade-off in §3 are preserved as the considered-alternative for the audit trail; the architect chose B.)

## Senior absorb scope (literal-reading)

Edits land in **ADR-023 D2** (Y1: `on_unknown_cost` + trace) + **D4** (Y2: subprocess-env-clear contract + the discriminating-test requirement) + **plan §2 S2/S3 acceptance** (the Y1 trace+config tests; the Y2 env-clear + discriminating test) + **plan §3** (re-shape to batched single-task, decision B). No `core/event.py`/closed-ADR-002/012-original edits (the amendments stay Proposed; the override config + the env-clear are new code in S2/S3). Bump R0-A/R0-B verdicts per RC-10. Then architect accepts ADR-023 + the two amendments.

## Constitutional + security note (for the record)

- **c1 (S2 routing) — solid, no leak.** The override is deterministic code, structurally enforced (spy `provider.call`==0 + AST guard; both lenses confirmed). Y1 is a governance-completeness gap, not a routing leak. No change to the c1 enforcement.
- **c2 (S3 security) — leak closed by Y2.** The config-path allowlist was already fail-closed; the **env-inheritance path was the leak** (r0b Y2). After the Y2 must-fix, c2 is fail-closed on both paths. The dual-lens earned its cost here (the in-family lens missed the subprocess-env angle).
- Forward hooks (LLM-evidence-interpret connector, malicious-backend response hardening, schema-tighten) remain deferred — do NOT bundle.
