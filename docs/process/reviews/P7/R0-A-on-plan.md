---
task: P7
cycle: 1
stage: plan
review: R0-A-on-plan
reviewer: architect-partner
verdict: needs_architect
date: 2026-06-17
plan_reviewed: docs/process/senior-plans/P7.md @ cc8809a
brief: docs/process/architect-briefs/P7.md
---

# R0-A-on-plan — P7 (loader cleanup + config/scoring hardening)

## Verdict: `needs_architect`

The plan's **substance is clean**: all three tasks are verified accurate against
`HEAD` (line citations correct — unlike the confabulated `P7-findings.md`), the
guardrails are correctly fenced, and the cited ADR clauses check out. There are
**no product-correctness defects**.

The `needs_architect` verdict is for **one workflow-routing item that requires an
architect action** (P-1: the task is parked at the accept gate and only an
override moves it) plus **one discretionary doc call** (P-2: an optional ADR-040
D7 annotation the senior left to you). Neither is a flaw in the three fixes
themselves.

## Method

Verified each plan claim against `HEAD@cc8809a`, not the intake findings doc:
the three code sites by line (`skills/loader.py`, `autonomy/config.py`,
`autonomy/scoring.py`), the cited ADR clauses (ADR-009 D8; ADR-040 D1/D7;
ADR-005 D4/D5), and the workflow state-machine routing
(`workflow/transitions.py` + `cli.py`).

---

## Findings

### 🟡 P-1 (needs architect action) — plan lacks frontmatter → P7 mis-routed + parked at the accept gate

The senior plan opens with `# P7 — …` and carries **no YAML frontmatter**. The
snapshot builder computes `plan_has_adr = "adr" in plan_fm` only when frontmatter
is present; with none, `plan_has_adr = None` (the legacy path, `cli.py:355-359`).
In `next_state` (`transitions.py:147-152`) `None` (or `True`) **routes through
`awaiting_architect_accept`**; only `False` (frontmatter present, no `adr` key)
**skips** it straight to `awaiting_junior_impl`.

Consequence: on plan-land the post-commit hook advanced
`awaiting_senior_plan → awaiting_architect_accept`. But P7 is a **no-ADR task**
(brief-ratified), so the accept-gate exit guard
(`adr_status == "accepted"`, `transitions.py:154`) can never be satisfied —
`_read_adr_status` returns `"none"` (no ADR file). `uv run workflow advance` is a
permanent no-op here; **P7 is parked** until an override moves it.

This is a regression from the established no-ADR convention — **every** recent
no-ADR plan carries frontmatter that skips the gate: `P6.1`, `P6.3`, `P6.8`,
`P6.9` all set `plan_has_adr: false` (no `adr` key); only ADR-bearing plans
(`P5.1c`: `adr: "ADR-043"`) route through accept. Had P7's plan carried the same,
it would have auto-advanced to `awaiting_junior_impl` and this review would be
`clean`.

**Architect action (override is architect-only — I cannot run it):**

```
uv run workflow override --task-id P7 --to-state awaiting_junior_impl \
  --reason "no-ADR task (brief-ratified); plan lacked frontmatter so the plan-land transition routed through awaiting_architect_accept (plan_has_adr=None legacy) instead of skipping it. No ADR to accept; advancing to impl per the P6.1/6.3/6.8/6.9 no-ADR convention."
```

Adding the frontmatter *now* would **not** un-park the state (P7 has already left
`awaiting_senior_plan`; the accept-gate advance reads `adr_status`, not
`plan_has_adr`). So the override is the operative fix; a frontmatter back-fill is
optional hygiene only (see 🔵 N-1).

### 🟡 P-2 (architect discretion) — #6 ADR-040 D7 annotation: optional, senior's call affirmed

The brief delegated the "does #6 warrant an ADR-040 D7 amendment note?" call to
senior judgment (arch-partner lean: no). The senior concurs (plan §5a) and I have
verified the reasoning against ADR-040:

- **D1** (ADR-040 line 38) frames fire latency as "one `sweep_interval_s` tick —
  negligible for a seconds-to-minutes window," which **presumes
  `sweep_interval_s ≤ window_s`**; a coarser sweep would let auto-fire overshoot
  the cancel window — exactly what #6 guards.
- **D7** (lines 115-119; the attribution in `config.py:1-7`) is the
  opt-in/default-OFF **fail-closed, refuse-start** posture ("Malformed section →
  `ValueError` at startup"). The new `window_s ≥ sweep_interval_s` check is one
  more malformedness rejection **inside** that contract — no decided behavior is
  inverted.

So **no new ADR and no amendment is technically required**; the constraint
tightens within the existing contract. **My lean: agree with the senior — skip
it.** This is yours only if you want the constraint pinned as an explicit
operational guarantee, in which case it's a **one-line D7 annotation**, not a new
ADR (and could ride the impl commit). It does **not** block junior dispatch
either way.

---

### 🟢 Affirmations (verified accurate against `HEAD`)

- **P7-1** (`loader.py`): `:91` `skills={}`; the `stem == id` check (`:113-119`,
  ADR-009 D8) runs *before* the dup branch, so the id-keyed `seen_paths` map **is**
  the stem→path map the brief describes; `:121-129` holds the `next(p for p in
  directory.rglob("*.md") …)` with **no `default`** → the bare-`StopIteration`
  footgun is real (a TOCTOU re-scan, narrow but real). `Skill` carries no source
  path, so a separate `seen_paths` is genuinely needed. The `path=`/`field="id"`
  kwargs are preserved. **Fix direction is correct and contract-preserving.**
- **P7-6** (`config.py`): `:28-29` fields and `:52-55` loader confirmed. The
  senior's load-bearing claim is **correct** — a `model_validator(mode="after")`
  raising `ValueError` is surfaced by Pydantic as `ValidationError`, which the
  loader's existing `except ValidationError` (`:54`) already wraps into the
  `countdown_auto_fire:` `ValueError`, so **no loader change is needed**.
  `frozen=True`/`extra="forbid"` untouched. The plan's explicit **equal-case**
  (`window_s == sweep_interval_s` loads) test matches the brief's `≥` boundary.
- **P7-7** (`scoring.py`): `:177` `eff_auto` has **no** floor (confirmed —
  "no floor by design"); `:178` `eff_confirm = max(0, …)` has it. The **RC-19
  guardrail** — do not add a clamp to `eff_auto` — is correctly fenced (plan §2
  P7-7 out-of-scope + §5b names it as the live RC-19 risk this cycle). Doc-only,
  bytes unchanged.
- **Spine-orthogonality**: all three are clear of `_execute_local_call`, the gate
  decision logic (`decide_tier`/`score`/`emit_gate_decision` stay byte-frozen —
  P7-7's change is a comment), and introduce no new `LLMPurpose`. Plan §4's
  zero-spine-diff claim holds.
- **Out-of-scope discipline**: #2/#3/#4/#5 correctly excluded; #5's "build
  chronologically" regression is not in the task list (junior works from the plan,
  which omits it).
- **Tests** match the brief and are adequate (P7-1 regression incl. no-StopIteration
  assertion; P7-6 reject + valid incl. equal; P7-7 none). No perf bench — correct,
  #1 is error-path-only.

### 🔵 Minors (no action required)

- **N-1 (optional hygiene)**: back-filling the plan's frontmatter
  (`plan_has_adr: false` + the usual `task_id`/`surface`/`requires_cross_family_review`
  keys, per P6.x) would make the artifact match convention, but — per P-1 — it
  will **not** change the parked state now. Skip unless you want the record clean;
  not worth a senior round-trip on its own.
- **N-2 (parallelism)**: plan §3 offers the three atomics as optional parallel
  agents. Given the project's single-junior-serial norm (and that three parallel
  agents committing to one shared working tree would race the index), **recommend
  serial — three commits `P7-1`/`P7-6`/`P7-7`**. The plan already says serial is
  equally acceptable, so this is a steer, not a defect.
- **N-3 (positive)**: the P7-1 rewrite also makes the duplicate-id error message
  **more deterministic** — it names the actually-first-registered path (sorted
  discovery order) rather than an arbitrary unsorted-`rglob` match. A small
  correctness improvement, not just a footgun removal.

---

## Expected next architect action

1. **Unstick the state**: `workflow override` P7 → `awaiting_junior_impl` (P-1
   command above). This is the only item that blocks forward motion.
2. **Decide P-2**: skip the D7 annotation (my + senior's lean) or request a
   one-line note. Optional; does not gate dispatch.
3. Then **dispatch junior** to implement P7-1/P7-6/P7-7 (serial, three commits)
   per `docs/process/senior-plans/P7.md`.

No ADR to Accept. No `🔴`. Plan content is implementation-ready.
