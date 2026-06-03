---
task_id: P3.5
stage: impl
artifact: architect-routing-on-impl
routed_by: architect (Peidong), via orchestrator
date: 2026-06-03
impl_branch: claude/P3.5-impl
impl_head_at_routing: 7bec33d
reviews_routed:
  - plan-vs-impl.md          # senior: needs_architect (1Y — name-adoption)
  - R0-A.md                  # in-family (architect-partner): needs_architect (2Y)
  - R0-B-cross-family.md     # true cross-family (DeepSeek): clean (0R/0Y/7G)
routing_summary: name-adoption → accept two-way + amend ADR-029 (Amendment 1); R0-A Y1/Y2 → α (junior-fixed)
fix_commits:
  - de11b76  # Y1.(1) R1-ordering sentinel (replaces vacuous raise)
  - 3121b47  # Y1.(2) D4+Y4 guards — remove collision short-circuits
  - 8255549  # Y2 demo tools.yaml → live text_stats classification surface
  - 7065d17  # ruff format
absorbed_into:
  - docs/decisions/ADR-029-plugin-system-manifest-loader-code-trust.md  # Amendment 1
---

# Architect routing — P3.5 impl stage

Three impl-stage reviews on `claude/P3.5-impl @ 7bec33d`: **plan-vs-impl**
(senior — `needs_architect`, 1Y), **R0-A** (in-family, architect-partner —
`needs_architect`, 2Y), and **R0-B-cross-family** (DeepSeek V4 Pro — **clean**,
0🔴/0🟡/7🟢). The architect routed all findings; this artifact is the signal for
senior absorption (`awaiting_senior_revision`). **Headline: the implementation is
correct and gate-green; one clarification amendment to the ADR (name-adoption) +
the junior's already-landed test/demo α-fixes close everything. No 🔴; no
runtime defect.** The three lenses converged: R0-B (cross-family) returned clean;
R0-A + plan-vs-impl both flagged the same two areas (the `tool_impls` collision
semantics + test/demo quality), from the design-fidelity and the
regression-guard angles respectively.

## 1. name-adoption (plan-vs-impl Y1) — RULED: **accept the two-way check + amend ADR-029 (clarification)**

The senior plan-vs-impl Y1 surfaced that the impl's `tool_impls` collision check
is **two-way** (host `local_tools` + cross-plugin), dropping the as-Accepted
ADR-029 D2/D6 third leg (vs host `tools`), with a residual **name-adoption**
(a plugin `tool_impl` named after a host ToolMeta-only classification adopts that
tier). R0-A §2.2 independently judged the two-way check **correct-by-design**.

**Ruling: the two-way check is correct; the ADR's "three-way" prose was the bug.**
Leg (ii) (`tool_impls` ↔ host `tools`) **contradicts D5/D7** — the
host-pre-classification mechanism requires a plugin to provide a `tool_impl` for a
host-classified name, which leg (ii) would refuse. **name-adoption is the
intended D5/D7 mechanism, not a hole:** the operator pre-classifies a name in
`config/tools.yaml` (authoritative, operator-curated) and the plugin supplies the
impl; under Posture A the operator curates **both** surfaces, so the tier is
operator-controlled. The shadow-bypass (overriding a host *implementation*)
remains closed by the host-`local_tools` leg; the plugin's self-asserted
reversibility is still advisory-capped (D5); the gate stays the sole chokepoint.

**Action (α): ADR-029 Amendment 1** (written; `ADR-029 §Amendment 1`) corrects
the D2 step 3 + D6 prose to the **two-way** `tool_impls` check + the **separate**
`contributions.tools` ↔ host `tools` check, and inscribes the name-adoption
semantics. **This is a clarification — no behavior change** (the impl was already
two-way; the empty-diff + gate + fail-closed invariants are unchanged). **ADR-029
remains Accepted** (an amendment does not downgrade). plan-vs-impl Y1 is thereby
**resolved**.

## 2. R0-A Y1 (weak regression guards) — RULED α — junior-fixed

R0-A Y1: the *code* is correct (§2.3/2.4/2.7) but four tests guarding the
security-load-bearing admit-code paths were vacuous/short-circuiting:
- **(a)** `test_collision_refused_plugin_not_imported` — vacuous (an import-time
  `raise` is caught by `code.py` either way, so it passed regardless of ordering).
- **(b/c)** `test_broken_module_import_refused` / `test_missing_callable_in_module_refused`
  — short-circuited at the `contributions.tools` collision before reaching the
  code-load path they claim to test.
- **(d)** `test_partial_plugin_leaves_no_trace` (the HR#5/Y4 atomicity guard) —
  short-circuited before any non-code surface loaded into the intermediate.

**Fixed (junior, `de11b76` + `3121b47`):** (a) the import-time module now writes an
observable **sentinel without raising**; the test asserts the sentinel does **not**
exist (proving `exec_module` never ran before the collision-check) — verified
non-vacuous + the fixture id now matches the dir (`collision_bomb`). (b/c/d) the
fixtures moved to the `tool_impls`-only pre-classify path so collision-check
passes and the genuine code-load-failure / half-register path is actually
exercised. **Senior-confirmed:** `tests/plugins/` 31 pass post-fix; the sentinel
guard is real.

## 3. R0-A Y2 (demo dead `tools.yaml`) — RULED α — junior-fixed

R0-A Y2 (≡ the senior plan-vs-impl N1): `plugins/demo/tools.yaml` was dead
(`word_count` in `tool_impls`, not `contributions.tools` → filtered out), so the
demo live-exercised 4 of 5 surfaces + shipped a misleading file.

**Fixed (junior, `8255549`):** the demo now declares a **`text_stats`**
classification-only tool in `contributions.tools` (capped to rev-0 → `HARD_CONFIRM`,
no host pre-classification — itself a useful D5 default-0 demonstration), making
`plugins/demo/tools.yaml` **live** and the demo exercise **all five surfaces** for
real: `demo_facilitator` (role), `demo-research` (skill), `demo_filesystem` (MCP),
`text_stats` (plugin-classify path), `word_count` (host-pre-classify + `tool_impls`
admit-code path → AUTO_EXECUTE).

## 4. R0-A clean notes / R0-B — no action

R0-A N1 (one-directional reversibility cap — commend), N2 (`config/tools.yaml`
permanently classifies `word_count` — harmless spare, prescribed by D7), N3
(`tool_impls` module ref not directory-scoped — **moot under Posture A** since a
curated plugin already runs arbitrary in-process code per L1; noted only for a
future Posture-B untrusted-provenance slice). **R0-B-cross-family returned clean**
(0🔴/0🟡/7🟢) — the cross-family lens found no runtime/isolation/bypass defect;
high-trust signal on the project's largest security surface.

## Result

Senior absorbs: **ADR-029 Amendment 1** (name-adoption clarification — no
behavior change, ADR stays Accepted); bumps **plan-vs-impl.md** (Y1 resolved by
Amendment 1) and **R0-A.md** (Y1/Y2 junior-fixed) `verdict_history → clean` per
RC-10 (R0-B already clean); writes this routing artifact. All three impl-stage
reviews now clean. **ADR-029 remains Accepted.** Expected next: architect verifies
→ PR merge / P3.5 close.
