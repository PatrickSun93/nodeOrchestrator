---
review: senior plan-vs-impl
task_id: P4.4
cycle: 1
branch: claude/P4.4-impl
commits_reviewed: a089d89..db564db   # P4.4-1..6
plan: docs/process/senior-plans/P4.4.md
verdict: needs_architect
findings_count: 3   # 1 yellow + 2 green
gates:
  ruff: pass            # ruff check src tests → All checks passed!
  mypy: pass            # mypy --strict src tests → no issues, 264 files
  pytest: pass          # pytest tests/plugins tests/tools → exit 0 (only pre-existing net_trust thread-warning)
---

# Senior plan-vs-impl — P4.4 (plugin registry / lifecycle / admission / namespacing)

**Lens (per senior-planner.md):** I am the only party who knows what the plan
*said*. External R0-A/R0-B see deliverable-vs-spec; I see plan-vs-deliverable —
where the impl satisfies the acceptance criteria's surface but drifts on a
**plan-implied invariant**. One such drift found (F1, 🟡); two completeness
observations (F2/F3, 🟢). **Route nothing — architect routes.**

## Verdict rationale

Every atomic's stated acceptance criteria are met and all three gates are green.
The single 🟡 is a plan-implied-invariant drift (uniform identity-level
coexistence across all five namespaced surfaces) with **no live impact** on the
shipped plugins — but it is an architect-routable scoping call (ratify
dict-key-coexistence as the MVP, or name identity-level namespacing for
roles/skills a deferred residual). Hence `needs_architect`, not `clean`. It is
**not** blocking: nothing here is wrong against the acceptance criteria; the
mandatory impl-stage dual-lens (R0-A ∥ R0-B, `requires_cross_family_review:true`)
runs next regardless (ADR-008 Amendment 1, Route B → `awaiting_R0_A`).

---

## Per-atomic faithfulness (What / Where / Acceptance)

| Atomic | Plan acceptance | Impl | Verdict |
|---|---|---|---|
| **P4.4-1** unified `PluginRegistry` schema | `RegistryEntry` frozen, `enabled` default-true, `version` optional; `load_plugin_registry` → `{}` for absent/None, `ConfigError` on malformed; fetched missing digest/source_url raises; `enabled` non-bool raises (incl. `"false"` quoted-string); `version` non-(str\|None) raises; unknown key raises; dup `plugin_id` raises; **no provenance/posture field accepted** | `provenance.py` `RegistryEntry` + `load_plugin_registry`: `_KNOWN_REGISTRY_ENTRY_KEYS` extra-forbid, `isinstance(enabled,bool)`, `version` str\|None, list-format + dup-`plugin_id` `ConfigError`, source_url/digest **pair** guard, strings-only env. Tests: g1 (4) + test_provenance | ✅ faithful (incl. absorbed C/D, `enabled:"false"` case) |
| **P4.4-2** enabled-gate + version/shape coherence | disabled (either root) absent from merge **AND `_load_plugin` never entered** (no MCP subprocess); operator-placed-no-entry still loads; fetched-no-entry refused; version-mismatch refused / version-absent loads; boot-only | `loader.py:631-645` enabled-gate `continue` **before** `_load_plugin`; shape-coherence + version-coherence refusals inside `_load_plugin`. Tests: g5 (patches `_load_plugin`, asserts never-entered + `mcp_sessions=={}`), g7, p442_* | ✅ faithful (absorbed A/H; A4-Y1 placement correct) |
| **P4.4-3** A5 namespacing | two plugins same `echo` tool_impl coexist; host-shadow `read_file` → **plugin REFUSED** (assert plugin rejection); within-plugin dup refused; deterministic always-prefix; `config/tools.yaml` rebound; demo gate paths resolve post-rebind | `_collision_check` host+within-plugin on **bare** name; cross-plugin via prefix merge; `config/tools.yaml` `demo__word_count`/`context__context_summary`. Tests: g6 (`local_tools=={}` ⇒ plugin refused), test_failure_modes coexist, test_p3_7_content rebind | ✅ acceptance met — **see F1/F2** for plan-implied-invariant nuance |
| **P4.4-4** composition-root wiring | `_build_context` passes both roots + registry; wired-whole test drives **real** `_resolve_plugin_registry`; malformed → empty + WARNING + **no exception escapes**; disjoint-root holds | `app.py` `_resolve_plugin_registry` catches `ConfigError`→empty+WARNING (`_resolve_sandbox_posture` pattern); `_build_context` passes `fetched_plugins_dir` + `plugin_registry`. Tests: test_wired_whole_registry rw1-4 drive real fn | ✅ faithful (absorbed B/a3) — **see F3** |
| **P4.4-5** constitutional/registry tests | all 10 guards present + green; no new `LLMPurpose`; disabled-MCP no-subprocess; byte-frozen executor/gate diff | test_constitution_p44 g1-g10 (489 lines); g8 greps `LLMPurpose` absent in `plugins/`; g9 gate-symbol absent; g10 `_execute_local_call` not called/imported in `plugins/` + cap intact | ✅ faithful (absorbed I) — confirmed by diffstat: **zero** edits to `executor.py` / gate / autonomy |
| **P4.4-6** ADR annotations | ADR-029 D5 (presence narrowed-not-reversed) + D6 (namespacing landed); ADR-031 D4 (activation→unified entry) + D5 (registry/lifecycle landed, still-deferred set named) | ADR-029 D5/D6 + considered-alt annotations; ADR-031 D4/D5 inline `[Annotated P4.4 → ADR-038, Accepted 2026-06-05: …]` naming hot-reload/runtime-store/signature/persistent-plugin as still-deferred | ✅ faithful, residuals honest |

**Byte-frozen invariant (I / P4.4-5 g10) independently confirmed:** the
`origin/main..HEAD` diffstat touches only `provenance.py`, `loader.py`, `app.py`,
tests, `config/tools.yaml`, and the two ADRs — **no** `tools/executor.py`, gate,
or `autonomy/` file. The ADR-029 D2 / ADR-031 HR#2 / ADR-037 D3 lineage holds:
namespacing changes dict **keys** only; both consumers are name-agnostic.

---

## Findings

### 🟡 F1 — Namespacing is identity-complete for 3 of 5 surfaces; for roles + skills it is dict-key-only

**The plan-implied invariant.** Plan §1 says all five contribution surfaces
"coexist"; P4.4-3 acceptance says namespacing is "deterministic ... name
**independent of sibling collisions**." The impl applies `<plugin_id>__<name>`
to the **merge dict key** for all five (`loader.py:668-678`). Whether that key
*is* the runtime resolution identity differs by surface:

- **tools** — resolved `tools[operation.tool_id]` (`autonomy/scoring.py:162`)
- **local_tools** — resolved `local_tools.get(tool_name)` (`tools/executor.py:174,396`)
- **mcp_sessions** — resolved by dict key

  → For these three the prefix **IS** the runtime identity. Correctly namespaced.
  (This is exactly why the `config/tools.yaml` rebind in P4.4-3 was load-bearing,
  and the impl did it.)

- **agents (roles)** — resolved by the object's `.id`, **not** the dict key:
  `regex_registry.get((agent.id, i))` (`agents/speaking.py:87`); selection
  iterates `available_agents.values()` (`agents/selection.py:54`).
- **skills** — resolved by `skill.id` + `skill.applies_to`: `decide_skills_for_context`
  iterates `available_skills.values()` and matches bare `skill.id` / bare
  `agent_id` (`skills/decision.py:49-76`).

  → For these two, the merged Agent/Skill object's `.id` stays **bare**. Prefixing
  the dict key prevents the dict-overwrite (both objects survive) but does **not**
  namespace their runtime identity. Two plugins sharing a bare role id coexist as
  `a__helper`/`b__helper` keys yet both carry `.id == "helper"` → their
  `regex_registry` entries `("helper", i)` collide (`dict.update` last-wins,
  `loader.py:675` merges regex **bare**, correctly per the single-instance model
  but with no cross-plugin disambiguation), and a room would receive two agents
  with identical `.id`. Same shape for two plugins sharing a bare skill id.

**Severity / live impact: none today.** The shipped plugins (demo / insights /
context) use distinct role + skill ids, so no collision occurs. Single-plugin
behaviour is fully correct and **un-regressed**: because resolution is by bare
`.id`, prefixing the agents/skills *keys* is harmless to intra-plugin wiring
(`skill.applies_to.agents → agent.id` still resolves bare). It is a **latent
multi-plugin-same-id edge**, and the junior's bare-`regex_registry` merge is
defensible + documented (`loader.py:671-674`).

**Why this is a plan-vs-impl drift, not an R0 finding.** The plan's language
("all five coexist", "independent of sibling collisions") implies *uniform*
identity-level coexistence. The impl delivers identity-level namespacing for
tools/impls/mcp but only dict-key-level for roles/skills — an asymmetry that is
invisible from deliverable-vs-spec (the acceptance tests assert dict-key
coexistence — `"a__shared_skill" in result.skills` — which **passes**) and only
visible from plan-vs-deliverable. The plan's coexistence test
(`test_cross_plugin_skill_coexist_namespaced`) checks key presence, **not**
identity-layer resolution of two same-id contributions.

**Architect call (I route nothing):** (a) ratify dict-key-coexistence as the
intended MVP and inscribe "identity-level namespacing for roles/skills (rewrite
`agent.id`/`skill.id` + `applies_to`/regex cross-refs) is a deferred residual"
in ADR-038 D4; or (b) treat it as in-scope and dispatch a follow-up making
roles/skills identity-level (larger — touches the Agent/Skill identity + their
intra-plugin cross-references). Either is an architect decision, not mine.

### 🟢 F2 — Cross-plugin tool_impl coexistence (plan's literal `echo` example) not directly tested

P4.4-3 acceptance names "two plugins declaring the same `echo` **tool_impl**
coexist as `pluginA__echo` + `pluginB__echo`." The suite tests cross-plugin
**skill** coexistence (`test_cross_plugin_skill_coexist_namespaced`,
`test_merge.py`) and single-plugin `local_tools` namespacing (g-tests /
test_provenance `*__echo_tool`), but not the literal two-plugin **tool_impl**
case. The merge mechanism is shared (same loop prefixes `local_tools`), so
coverage is mechanism-equivalent — a test-completeness nit. Per F1, tool_impls
are the surface where namespacing **is** identity-level, so a direct test would
also be the cleanest positive proof of that property. Optional add.

### 🟢 F3 — `activation_registry_path` left unwired in the composition root (consistent with ADR-038 D1 unification — observation, not a defect)

`_build_context` passes `fetched_plugins_dir` + `plugin_registry` but **not**
`activation_registry_path` (`app.py:288-292`). This is **correct** under the
unified design: fetched activation now flows through the unified registry —
`_load_plugin` accepts a fetched plugin when `registry_entry.source_url is not
None` (`loader.py:391-400`), so a `config/plugins.yaml` entry carrying
`source_url`+`digest` is the activation proof. The legacy `activation_registry_path`
/ `ActivationEntry` path is retained for backward-compat (named in the ADR-031 D4
annotation) and simply not wired into production. Matches plan P4.4-4 ("pass the
resolved registry + the fetched root") and ADR-038 D1. Recorded so the dual-lens
reviewers don't read the unwired legacy path as a fetched-admission gap.

---

## Forcing-function checklist (plan §4)

- ✅ Inscribe-before-producer — ADR-038 landed with the plan (pre-impl); annotations match (P4.4-6).
- ✅ Promotion-impact grep — `config/tools.yaml` `word_count`→`demo__word_count`, `context_summary`→`context__context_summary` rebound; content-plugin test fixtures updated (test_p3_7_content).
- ✅ Atomic↔commit 1:1 (RC-17) — six commits `P4.4-1:`..`P4.4-6:`, one subject each, no bundling.
- ✅ Constitutional tests — provenance-un-forgeable (g1), malformed→refuse-all-graceful (g2/rw2), no-new-`LLMPurpose` (g8), admission-not-gated (g9), byte-frozen (g10).
- ✅ Honest-residual inscription — A4 no-author-identity/no-revocation + hot-reload/runtime-store/signature/persistent-plugin named deferred (ADR-031 D5 annotation).

## Gates (run by senior for plan-vs-impl self-check)

```
ruff check src tests        → All checks passed!
mypy --strict src tests     → Success: no issues found in 264 source files
pytest tests/plugins tests/tools → exit 0
    (sole warning: pre-existing net_trust DNS-timeout thread-warning, unrelated to P4.4)
```

**Expected next (ADR-008 Amendment 1, Route B):** state auto-advances to
`awaiting_R0_A`; mandatory impl-stage dual-lens (R0-A ∥ R0-B against
`external-r0b-prompt.md` two lenses) proceeds. F1 is flagged for architect
routing at synthesis; F2/F3 are informational.
