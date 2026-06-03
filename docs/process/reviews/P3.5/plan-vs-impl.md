---
task_id: P3.5
review: plan-vs-impl
reviewer: senior
stage: impl
impl_branch: claude/P3.5-impl
impl_head: 7bec33d
artifacts_reviewed:
  - docs/process/senior-plans/P3.5.md
  - docs/decisions/ADR-029-plugin-system-manifest-loader-code-trust.md (Accepted)
verdict: clean
findings:
  blocking: 0
  needs_architect: 0
  clean_notes: 3
note: >-
  Impl is high-fidelity to the plan + ADR-029 on 7 of 8 focus checks, plus the
  empty-diff invariant (gate/executor/mcp = 0 diff vs origin/main) and the full
  gate (1538 passed, ruff + mypy clean) — all independently verified, not taken
  on the junior's word. ONE substantive drift (Y1): the tool_impls collision
  check is TWO-way (host local_tools + cross-plugin), intentionally dropping the
  plan/ADR's third leg (vs the host tools ToolMeta registry). The shadow-bypass
  (the original R0-A Y1 hole) IS closed by the host-local_tools leg; but dropping
  the host_tools leg is a deviation from the Accepted ADR-029 D2/D6 AND opens a
  residual name-adoption tier-elevation (a plugin tool_impl named after a host
  ToolMeta-only classification adopts that tier). The deviation is reasoned and
  actually exposes a latent contradiction in MY plan/ADR (D5/D7's
  host-pre-classification requires dropping that leg). Architect routes: accept
  the two-way check + amend ADR-029 (lean), or restrict name-adoption.
  verdict_history shape per RC-10; routes via ADR-008 Amendment 1 Route B.
verdict_history:
  - verdict: needs_architect
    at_commit: 7bec33d
    findings: { blocking: 0, needs_architect: 1, clean_notes: 2 }
    note: tool_impls two-way-vs-three-way collision drift + name-adoption residual
  - verdict: clean
    at_commit: post-routing-revision (7065d17 + ADR-029 Amendment 1)
    findings: { blocking: 0, needs_architect: 0, clean_notes: 3 }
    note: >-
      Y1 resolved by ADR-029 Amendment 1 (architect 2026-06-03 via orchestrator;
      architect-routing-on-impl.md) — two-way tool_impls check accepted
      correct-by-design, name-adoption inscribed as the D5/D7 mechanism; no
      behavior change, ADR stays Accepted. N1/N2 junior-fixed (8255549 / de11b76).
---

# Plan-vs-impl — P3.5 (Plugin system; impl `claude/P3.5-impl` @ 7bec33d)

> **RC-10 — frontmatter as live signal: `needs_architect → clean`.** Y1 resolved
> by **ADR-029 Amendment 1** (architect routing 2026-06-03 via orchestrator;
> `architect-routing-on-impl.md`): the two-way `tool_impls` collision check is
> accepted **correct-by-design** (the as-Accepted ADR's "three-way" prose
> contradicted D5/D7); **name-adoption** is inscribed as the intended D5/D7
> host-pre-classification mechanism, not a hole. **Clarification only — no
> behavior change; ADR-029 remains Accepted.** The two 🟢 notes were also
> junior-fixed: N1 (dead demo `tools.yaml`) → live `text_stats` surface
> (`8255549`); N2 (mislabeled import-order test) → real sentinel guard
> (`de11b76`, senior-confirmed non-vacuous). Original finding bodies preserved
> below as audit trail (the 🟡 marker is historical).

## 0. Method

I traced the impl against `senior-plans/P3.5.md` + Accepted `ADR-029`, and
independently verified the junior's gate + empty-diff claims (the
`verify-junior-gates` discipline — not taken on report):

- **Empty-diff invariant — VERIFIED ✓.** `git diff origin/main` is **0 lines**
  on `autonomy/scoring.py`, `agents/tool_dispatch.py`, `autonomy/emission.py`,
  `tools/executor.py`, and the entire `mcp/` package. Plugin contributions feed
  the registries without touching any decision surface (the brief's
  gate-diff-must-be-empty, extended to executor + MCP-client). ✓
- **Full gate — VERIFIED ✓.** `uv run pytest` = **1538 passed**, 0 failed;
  `ruff check` clean; `mypy src/orchestrator/plugins/` clean. The
  `tests/plugins/` suite (31 tests) passes; constitution tests
  (plugins/tools/mcp/autonomy) pass.
- **Four-loader reuse — VERIFIED ✓.** `plugins/` defines no `load_agents` /
  `load_skills` / `load_tools_config` / `load_mcp_servers_config` /
  `build_mcp_tool_registry`; it imports and calls them (`loader.py:26-33,357-400`).
  No loader reimplemented.

## 1. Verdict — `needs_architect` (1 🟡; 0 🔴)

| # | Sev | Finding | Lean |
|---|---|---|---|
| **Y1** | 🟡 | `tool_impls` collision check is **two-way** (host `local_tools` + cross-plugin), **dropping the plan/ADR's third leg** (vs the host `tools` ToolMeta registry). Shadow-bypass closed; but it deviates from Accepted ADR-029 D2/D6 + opens a residual **name-adoption tier-elevation**. | **α** (accept the two-way + amend ADR-029 D2/D6 to match; the dropped leg is *required* by D5/D7) — architect rules; OR restrict adoption |

The 7 other focus checks are **faithful** (§2). The deviation is the one place
the impl and the Accepted ADR disagree, so it must route to the architect (I
cannot bless an impl that contradicts an Accepted ADR).

## 2. Focus-check fidelity (the 8 architect-named checks)

1. **D2 security-load-bearing ordering — FAITHFUL ✓.** `_load_plugin`
   (`loader.py:312`) runs collision-check (step 3, `:339`) and returns `None`
   **before** any `importlib` (step 5, `:408–422`); `_discover_and_validate`
   (steps 1–2) precedes it entirely. Verified order: validate → collision →
   non-code load → **code import** → cap → atomic merge. A refused plugin's code
   never runs. (See §3 N2 for a test-label nit, not a code defect.)
3. **Posture A in-process + per-plugin isolation — FAITHFUL ✓.** `code.py`
   uses `spec_from_file_location` + `exec_module` without polluting
   `sys.modules` (`:42–54`); an import error / missing-or-non-callable attr →
   `PluginCodeLoadError` → the caller refuses that plugin (`loader.py:414–422`),
   bootstrap not crashed. The L1/L1b/L2 exposures are inscribed verbatim in the
   module docstring (`code.py:7–26`). `test_broken_module_import_refused` +
   `test_missing_callable_in_module_refused` pass.
4. **Reversibility cap — FAITHFUL ✓.** `_apply_reversibility_cap`
   (`loader.py:283`): host-present → `min(plugin, host)`; host-absent → `ToolMeta(0)`.
   The plugin's claimed value is never authoritative.
   `test_reversibility_cap_new_tool_defaults_zero` (plugin claims rev=10, host
   absent → 0) + `test_unclassified_plugin_tool_defaults_hard_confirm` (gates to
   `HARD_CONFIRM`) pass.
5. **Atomic merge / no half-register — FAITHFUL ✓.** `_load_plugin` returns a
   per-plugin `PluginLoadResult` or `None`; `load_plugins` updates `seen_*` +
   `merged` **only after** full success (`loader.py:503–518`).
   `test_partial_plugin_leaves_no_trace` (`test_merge.py:111`) asserts a plugin
   failing mid-load leaves zero trace. ✓
6. **Fail-closed loading — FAITHFUL ✓.** Bad YAML (`:111`), non-mapping (`:115`),
   manifest `ValidationError` (`:122`), unknown `schema_version` (`schema.py:73`),
   id≠dir (`:127`), unmet `min_host_contract` / `model_ids` / `room_types`
   (`:136–167`) → refuse, per-plugin isolated. Tests present + passing.
7. **Demo distinct ids + host classification — FAITHFUL ✓** (one 🟢 nit, §3 N1).
   `plugins/demo/`: role `demo_facilitator`, skill `demo-research`, server
   `demo_filesystem` (all distinct from core — not refused); host-side
   `config/tools.yaml` has `word_count` rev=10 so the demo's executable tool
   AUTO_EXECUTEs (`config/tools.yaml:52–53`). `test_host_preclassified_tool_impl_gates_auto`
   exercises the AUTO path end-to-end.
8. **Four-loader reuse — FAITHFUL ✓** (verified §0).

(Check 2 — `tool_impls` collision — is the Y1 drift; see §3.)

## 3. Findings (detail)

### Y1 🟡 — `tool_impls` collision check dropped the host-`tools` leg (deviation from Accepted ADR-029 D2/D6; residual name-adoption)

**Where:** `loader.py::_collision_check` (`:239–256`) checks each `tool_impls`
name against **(i)** host `local_tools` keys and **(iii)** cross-plugin
`tool_impls` — but **not (ii)** the host `tools` ToolMeta registry. The code
documents this as deliberate (`:233–238`). ADR-029 D2 step 3 + D6 + plan P3.5-3
each specify a **three-way** check: "(i) host `local_tools` keys, (ii) the host
`tools` registry, and (iii) cross-plugin `tool_impls`."

**What the impl gets right (the actual Y1 hole is closed).** The original R0-A Y1
shadow-bypass — a plugin shadowing a host builtin with a real impl (e.g.
`read_file`) to bypass the sandbox — is closed by leg **(i)**:
`test_tool_impl_shadow_host_local_tool_refused` (`test_failure_modes.py:403`)
passes (a `tool_impl: read_file` → refused, host impl unchanged). The
constitutional concern is genuinely defended.

**Why leg (ii) was dropped — a latent contradiction in MY plan/ADR.** D5/D7
require the demo's executable tool to be **host-pre-classified** in
`config/tools.yaml` (so it clears default-0 and AUTO_EXECUTEs). The demo provides
the impl via `tool_impls: {word_count: …}` with **no** `contributions.tools`
(`plugin.yaml:11–15`). If leg (ii) were enforced, `word_count` ∈ host `tools`
(the operator's pre-classification) → the demo's own `tool_impl` would
**collide with the very classification it depends on** → the demo would be
refused. So leg (ii) and the D5/D7 host-pre-classification mechanism are
**mutually exclusive** — my plan/ADR specified both. The junior resolved it by
dropping leg (ii) and keeping leg (i) (which already distinguishes
"shadow a real host impl" = refuse from "adopt a ToolMeta-only classification" =
allow). The impl is arguably *more* correct than the plan here.

**The residual exposure the architect must rule on (name-adoption
tier-elevation).** With leg (ii) dropped, a plugin `tool_impl` named after **any**
host ToolMeta-only classification (a tier set for a *future host impl*, not a
plugin) **adopts that tier**. `config/tools.yaml` classifies many AUTO-tier names
with no host impl today — `web_search`/`web_fetch`/`git_log`/`git_diff`/
`run_lint`/`find_references`/… all rev=10. A plugin shipping
`tool_impls: {web_search: <code>}` (no `contributions.tools`) passes leg (i)
(`web_search` ∉ host `local_tools`) and **runs its code at AUTO_EXECUTE** via the
host's `web_search` ToolMeta — **without the operator classifying the plugin's
tool specifically.** This contradicts D5's stated intent ("a brand-new plugin
tool defaults to 0 until the operator adds a host-side classification" — implying
*the plugin's* tool). `test_host_preclassified_tool_impl_gates_auto`
(`test_loader.py:281`) demonstrates the mechanism with a benign `auto_tool`; the
same path admits `web_search`.

**Severity = 🟡, not 🔴.** Bounded within the *already-Accepted* Posture A trust
model: plugin code runs in-process regardless (L1/L1b — import-time ungated),
the operator curates both `plugins/` and `config/tools.yaml`, and the gate tier
only controls AUTO-vs-HARD_CONFIRM at call time. The exposure is a tier-elevation
**intent-drift** (the operator's classification intent silently repurposed for
plugin code), not a gate bypass — the gate is still the sole chokepoint.

**Architect routing (lean α).** I lean **α: accept the two-way check + amend
ADR-029 D2/D6** to (a) split the `tool_impls` rule explicitly — check vs host
`local_tools` (shadow, refuse) + cross-plugin, **not** vs host `tools`
(pre-classification, allowed) — and (b) inscribe the **adoption semantics**:
"a host `tools` classification applies to *any* impl of that name, host or
plugin; classifying a name = accepting that tier for whatever implements it
(operator responsibility under Posture A)." Optionally restrict adoption to
classifications the operator marks plugin-eligible — but that adds surface to a
deliberately-loud MVP; the simpler honest fix is to document the semantics. **I
do not fix this in the impl or the ADR — the architect routes** (the ADR is
Accepted; the deviation is the architect's to bless or reject).

## 4. Clean notes (no action; audit trail)

- **N1 🟢 — `plugins/demo/tools.yaml` is dead.** The demo ships a
  `plugins/demo/tools.yaml` classifying `word_count` rev=10, but
  `contributions.tools` is empty (`plugin.yaml:11`), so the loader filters it out
  (`loader.py:383–385` — only declared entries load). The file is harmless but
  vestigial (the live classification is the host `config/tools.yaml`); a reader
  may think it is load-bearing. Either delete it or declare `word_count` in
  `contributions.tools` — but the latter would then collide with the host
  classification (the Y1 leg-(ii) tension), so **deleting it is the clean fix**.
  Recording, not routing.
- **N2 🟢 — import-ordering test fires on the wrong gate.**
  `test_collision_refused_plugin_not_imported` (`test_failure_modes.py:451`) uses
  a fixture whose manifest `id: collison_bomb` ≠ dir `collision_bomb` (a typo), so
  the plugin is refused at the **id-mismatch check (step 2)**, before the
  collision check (step 3) it claims to exercise. The assertion (no import-time
  exception) still holds — but it proves "validate-before-import," not
  "collision-before-import." The **code ordering is correct regardless** (verified
  by reading `_load_plugin`); only the test's discriminating power is weaker than
  labeled. A one-char fixture fix (correct the id) would restore the intended
  coverage. Recording, not routing.

## 5. Net

High-fidelity impl. The empty-diff invariant, the full gate, the atomic-merge,
the fail-closed gauntlet, the Posture-A isolation, and the reversibility cap are
all real and independently verified. The single substantive item (Y1) is a
deviation from the Accepted ADR that **the plan itself made necessary** (the
leg-(ii) ⊥ host-pre-classification contradiction) — exactly the plan-implied-
invariant drift plan-vs-impl exists to surface. Route Y1; expected next per
ADR-008 Amendment 1 Route B: state → `awaiting_R0_A` (the mandatory impl-stage
dual-lens R0-B independently re-probes the code-trust + name-adoption surface).
