---
task_id: P4.4
round: R0-A
reviewer_role: architect-partner
stage: impl
impl_branch: claude/P4.4-impl
impl_head: 329b490
reviews_acked:
  - decisions/ADR-038-plugin-registry-lifecycle.md
  - reviews/P4.4/R0-A-on-plan.md
  - reviews/P4.4/R0-B-on-plan.md
  - senior-plans/P4.4.md
verdict: blocking
findings_count: { red: 1, yellow: 0, green: 2 }
verdict_history:
  - round: 1
    impl_head: db564db
    verdict: blocking
    summary: "1🔴 R1 (malformed registry graceful-but-NOT-refuse-all → op-placed incl. operator-disabled silently load) + 1🟡 Y1 (role/agent namespacing dict-key-only)."
  - round: 2
    impl_head: 329b490
    verdict: blocking
    summary: "R1 RESOLVED (RW1 0ed7877 refuse-all sentinel + RW2 07d7606 yaml.YAMLError broaden); Y1 RESOLVED (RW3 329b490 ADR-038 D4 deferred-residual inscription + F2 coexistence test). NEW 1🔴 R2: mypy --strict red (7 errors, test-only, runtime-green) — RW1's union return-type not narrowed in rw3/rw4 valid-registry test paths; mechanical β-fix. Gates: ruff ✅ / mypy ❌ / pytest tests/plugins ✅ 156."
---

# R0-A — P4.4 impl (plugin registry + lifecycle + admission + namespacing)

**Scope.** The real impl at `claude/P4.4-impl` (6 atomics, `98acf34..db564db`): `plugins/provenance.py` (RegistryEntry + `load_plugin_registry`), `plugins/loader.py` (enabled-gate, version/shape coherence, namespaced merge, `_collision_check`), `api/app.py` (`_resolve_plugin_registry` wiring), `config/tools.yaml` (Y3 rebind), and the P4.4-5 guard suite. I ran the six dispatch lenses against the *traced code path* (not the ADR prose) and verified the absorbed A–I against the implementation. Gates: `pytest tests/plugins/test_constitution_p44.py tests/plugins/test_wired_whole_registry.py` → **22 passed**.

**Bottom line — `blocking`.** Five of six lenses pass cleanly and the load-bearing trust invariants hold: provenance is host-derived and un-forgeable (lens 1), the fetched digest-floor is intact (lens 2), disabled is truly unreachable on a well-formed registry (lens 4), and the executor + gate are byte-frozen with no new `LLMPurpose` (lens 6). **One 🔴 (R1)**: the malformed-registry path is *graceful* but is **not** refuse-all — it collapses `malformed` into `absent`, so operator-placed plugins (including ones the operator explicitly **disabled**) load by presence on a broken config. That contradicts ADR-038 D2 / the Constitutional carry-forward, stated three times. **One 🟡 (Y1)**: role/agent namespacing is incomplete — only the dict key is prefixed, not the runtime identity. I route nothing.

---

## 🔴 R1 — malformed `config/plugins.yaml` is graceful but NOT refuse-all → operator-disabled op-placed plugins silently re-enable

**Lens 3.** ADR-038 says this three times, and each time it draws an explicit `absent ≠ malformed` line:

- D2: *"absent registry → today's shipped defaults (operator-placed by presence, fetched none); **malformed** registry → **load zero plugins** (refuse-all, loud — the P4.3 `_resolve_sandbox_posture` parse-fail→fail-closed precedent at registry granularity)."*
- Constitutional: *"a malformed registry **refuses**, never admits."*
- Consequences/Harder: *"A malformed `config/plugins.yaml` **refuses all plugins** (strict fail-closed)."*

**What the impl actually does.** `_resolve_plugin_registry` (`api/app.py:202-223`) returns the **same empty dict** for both absent and malformed:

```python
if config_path.exists():
    try:
        return load_plugin_registry(config_path)
    except ConfigError as exc:
        ...warning("plugins.yaml parse failed → empty registry ...")
        return PluginRegistry()      # ← parse-fail  → {}
return PluginRegistry()              # ← absent      → {}
```

That empty dict flows to `load_plugins(plugin_registry={})`. The enabled-gate (`plugins/loader.py:639-647`) cannot distinguish `{}` from `None`:

```python
r_entry = plugin_registry.get(candidate.plugin_id) if plugin_registry is not None else None
if r_entry is not None and not r_entry.enabled:   # {} .get(...) → None → never taken
    continue
```

So on a malformed registry every operator-placed candidate has `r_entry is None` → **loads by presence** (ADR-029 D5). `load zero plugins` becomes `load all operator-placed plugins, including any the operator set `enabled: false``.

**Mis-applied precedent.** The ADR cites `_resolve_sandbox_posture` as the model. That function (`api/app.py:173-199`) maps parse-fail → `PostureResolver.fail_closed()` — the **most-restrictive** resolver, docstring *"never fail-open."* The registry analog of `fail_closed()` is a **refuse-all sentinel**; the impl instead returns the analog of `.default()` (permissive empty). It imported the *shape* of the precedent (catch → graceful) but inverted its *direction* (restrictive → permissive).

**The junior's own test documents the gap under a misleading name** (`test_constitution_p44.py:165-175`):

```python
def test_g2_empty_plugin_registry_refuses_all_op_placed(...):   # name says "refuses all"
    ...
    result = _load(plugins_dir, plugin_registry={})
    assert "op_plugin__echo_tool" in result.local_tools          # body proves op-placed LOADS
```

The wired test `rw2` (`test_wired_whole_registry.py:41-54`) only asserts `_resolve_plugin_registry → {}` + WARNING in isolation; nothing exercises the downstream "does a disabled op-placed plugin stay down". So the fail-open is unobserved by the suite, not contradicted by it.

**Blast radius (the honest bound).** Fetched plugins stay **fail-closed** on a malformed registry: with an empty unified registry and no legacy activation wired (`load_plugins` is called without `activation_registry_path`), the fetched-activation guard (`loader.py:399-411`) refuses every fetched candidate. So **no untrusted code is admitted** — this is not an RCE-class breach. The damage is bounded to *curation-trusted* Posture-A code: a plugin the operator deliberately disabled (e.g. decommissioned, or found vulnerable) **silently re-enables on the next restart after any unrelated typo in `plugins.yaml`**, with only a WARNING. That is exactly the fail-open the refuse-all rule exists to prevent, and it silently reverts an operator security decision.

**Why plan-stage cleared this 0🔴.** R0-A-on-plan read *"malformed → refuse-all (returns empty registry)"* and accepted it at face value. The contradiction is only visible when you trace the empty dict through `load_plugins` and watch presence=opt-in re-admit. This is the increment impl-stage review adds over plan-stage — the ADR's *mechanism* ("return empty") cannot deliver its *intent* ("load zero") under ADR-029 D5.

**Routing options (architect decides; I do not).**
- **β-fix impl:** make `_resolve_plugin_registry` return a *refuse-all sentinel* on parse-fail (distinct from absent→`{}`), and have `load_plugins` refuse every candidate when handed it — the true `fail_closed()` analog. Achieves the literal D2 intent.
- **α-absorb + ADR amend:** consciously narrow "refuse-all" to "refuse all *fetched* + ignore partial enabled-state; op-placed-presence preserved", accept the disabled→enabled fail-open as a named residual, and rename test g2 + fix its docstring. (This weakens the stated fail-closed posture — an architect-weight call, not a junior or partner one.)

---

## 🟡 Y1 — role/agent namespacing is dict-key-only; `Agent.id` + `regex_registry` keys stay bare, so same-id roles don't truly coexist

**Lens 5.** D4: *"every plugin contribution name (roles / skills / tools / tool_impls / mcp_servers) is merged as `<plugin_id>__<name>` ... Two plugins both declaring `echo` now coexist as `pluginA__echo` + `pluginB__echo`."*

The merge (`loader.py:670-679`) prefixes the **dict keys** for agents/skills/tools/local_tools/mcp_sessions, but `regex_registry` is merged **bare** (`:675`) and the junior's comment (`:671-672`) acknowledges this: *"regex_registry uses agent.id as key ... so it merges bare — consistent with speaking.py lookup."* It is consistent for a single plugin — but it misses the cross-plugin case, because for **roles** the runtime identity is `Agent.id`, not the dict key, and `Agent.id` is never prefixed:

- dispatch iterates `agents.values()` sorted by `a.id` (`dispatch.py:85`) — the namespaced key is unused;
- regex lookup is `regex_registry.get((agent.id, i))` (`speaking.py:87`) — bare;
- event attribution / cooldown key on `agent.id` — bare.

So two plugins each declaring a role `echo`: both survive the dict (keys `A__echo`, `B__echo`) and both dispatch, but they share identity `echo` — `regex_registry[("echo", 0)]` is **clobbered last-write-wins** (one plugin's agent silently evaluates the *other's* regex trigger), and their utterances are attributed indistinguishably. For tools this is fine (the namespaced key *is* the callable name the LLM emits); for roles the dict-key prefix is largely cosmetic.

**Severity.** Not a trust/admission/gate breach — no 🔴. But it contradicts D4's stated coexistence guarantee for the `roles` contribution, and P3.5 previously made this *impossible* by fail-closed refusal, so P4.4 traded a loud refusal for a silent collision. Requires the uncommon "two plugins, same bare role id" config; no test exercises it (which is why it slipped). **Routing options:** α-absorb (also prefix `Agent.id` + rekey `regex_registry` on the namespaced id; or keep cross-plugin *role*-id collisions fail-closed while namespacing the rest), or β-defer with an inscribed residual ("role namespacing is dict-key-only this slice").

---

## Lens-by-lens + absorbed-A–I verification

| Lens | Verdict | Evidence |
|---|---|---|
| **1 — provenance/posture un-forgeable; shape↔root refuse** | 🟢 pass | `RegistryEntry` has no provenance/posture field; `_KNOWN_REGISTRY_ENTRY_KEYS` rejects them (`provenance.py:175-177,264-268`; g1 tests). Provenance host-derived by root (`loader.py:613,625`). Fetched-shape-for-op-placed refused (`loader.py:365-378`; g1). |
| **2 — fetched floor not weakened** | 🟢 pass | digest-bearing entry required, else refuse (`loader.py:399-411`; g3). No boot re-hash (none in `_load_plugin`); `fetch.py` untouched. Version-coherence is label-equality only, fail-safe when absent (`loader.py:380-397`; g7) — **not** an integrity barrier (absorbed Y2b/a2). |
| **3 — malformed graceful refuse-all** | 🔴 **R1** | Graceful ✅ (catch→empty+WARNING, no crash; `app.py:202-223`, rw2). Refuse-all ❌ — see R1. |
| **4 — disabled truly unreachable** | 🟢 pass | enabled:false short-circuits **before** `_load_plugin` (`loader.py:642-647`); g5 patches `_load_plugin` and asserts it's never entered + `mcp_sessions == {}` + `local_tools == {}` for a disabled mcp-shipping plugin (absorbed Y1). *Caveat: holds only for a well-formed registry — on malformed, R1 re-enables it.* |
| **5 — namespacing always-prefix; host-collision+shadow fail-closed on bare** | 🟡 **Y1** | always-prefix ✅ (`loader.py:670-679`). Host-collision + shadow-bypass + within-plugin all refuse on the **bare** name before any prefix (`loader.py:220-296`; g6); order-of-ops correct (absorbed Y4/b1). Gap: role identity not namespaced — see Y1. |
| **6 — no LLMPurpose; admission not gated; executor+gate byte-frozen** | 🟢 pass | g8 (no `LLMPurpose` in plugins/), g9 (no `decide_tier`/`emit_gate_decision`/`score(`), g10 (no `_execute_local_call` call/import). Confirmed via diff: `tools/executor.py` + `autonomy/scoring.py` **byte-frozen** (zero diff `98acf34..HEAD`). `_apply_reversibility_cap` host-authoritative-or-default-0 unchanged (`loader.py:304-325`). |

**Absorbed-finding spot-checks.** **C** (`isinstance(enabled, bool)`): enforced (`provenance.py:283-289`) — `enabled: "false"` → ConfigError, blocks the silent fail-open enable. **D** (duplicate `plugin_id`): list-shaped parse raises ConfigError on dup (`provenance.py:276-279`). **E** (`config/tools.yaml` rebind): `word_count → demo__word_count`, `context_summary → context__context_summary`, both rev-10 preserved (`config/tools.yaml:48-58`) — the AUTO_EXECUTE host-classification path is re-bound to the namespaced names, fail-direction safe.

## 🟢 Observations (no action implied)

1. **Shape-coherence guard is asymmetric.** Only the fetched-shape-for-op-placed direction is an explicit refuse (`loader.py:365-378`); the bare-entry-for-fetched direction is enforced indirectly by the activation-required guard. The *dangerous* sub-case (bare entry, fetched, no digest proof anywhere) is still refused, so the **floor holds** — noting only that a bare unified entry coexisting with a legacy activation is tolerated rather than loudly refused per D1's letter.
2. **No test pins D4's gate-path acceptance** (`demo__word_count → AUTO`, `demo__text_stats → HARD`). The `config/tools.yaml` rebind is correct and the fail-direction is safe, but the D4 acceptance criterion ("assert each demo's documented gate path still resolves") has no dedicated assertion.

---

**Routing:** none — surfaced for architect synthesis alongside senior plan-vs-impl + R0-B. Verdict **blocking** on R1.

---

# Round 2 — RC-10 verdict-bump re-review (impl_head `329b490`)

Re-reviewed the junior rework (RW1 `0ed7877`, RW2 `07d7606`, RW3 `329b490`) against the round-1 🔴 R1 + 🟡 Y1. **Both original findings are resolved at the code level.** The R1 fix, however, introduced a **new mandatory-gate regression (R2)**, so the verdict **stays `blocking`** — not bumped to clean. I route nothing.

## ✅ R1 — RESOLVED (RW1 `0ed7877`, reinforced by RW2 `07d7606`)

The β-fix matches the routed option exactly:
- `provenance.py:212-227` adds a true `_RegistryRefuseAll` sentinel (`REGISTRY_REFUSE_ALL`), structurally distinct from both `None` and `{}`.
- `_resolve_plugin_registry` (`app.py:204-238`) returns the sentinel on parse-fail; absent still returns `PluginRegistry()` — the `absent ≠ malformed` line D2 demands. RW2 broadened the catch to `(ConfigError, yaml.YAMLError)` so syntax-broken YAML reaches the same sentinel instead of crashing `_build_context` (R0-B Y2) — additive reinforcement of refuse-all.
- `load_plugins` (`loader.py:630-639`) refuses every candidate on the sentinel via an `isinstance` guard placed **after** discover/validate but **before** Steps 3-7 (`_load_plugin` + merge — the only stage that spawns MCP subprocesses / mutates host registries). Malformed registry ⇒ empty `PluginLoadResult()`, **zero** op-placed or fetched admission, **zero** host mutation — the genuine `fail_closed()` analog. The enabled-gate presence-resurrection path (`loader.py:651-659`) is never reached.
- Tests fixed: the misleading `test_g2_empty_plugin_registry_refuses_all_op_placed` (name said "refuses", body proved "loads") renamed to `test_g2_empty_registry_absent_loads_op_placed` (body now matches: `{}` = absent ⇒ op-placed loads); new `test_g2_refuse_all_sentinel_refuses_all_op_placed` (`local_tools == {}`) and `test_g2_refuse_all_disabled_op_placed_stays_down` (the exact disabled-op-placed-stays-down case R1 flagged); wired `rw2` updated to `assert result is REGISTRY_REFUSE_ALL`. Targeted set 5/5 green.

The round-1 mechanism→intent gap ("return empty" could not deliver "load zero" under ADR-029 D5 presence=opt-in) is closed: malformed now yields a sentinel structurally incapable of presence-resurrection.

## ✅ Y1 — RESOLVED (RW3 `329b490`, α-absorb+inscribe)

- ADR-038 D4 gains a **"Deferred residual — role/skill identity-level namespacing"** paragraph that faithfully records the finding: dict-key prefix only (`<plugin_id>__<name>`); `Agent.id`/`Skill.id`/`applies_to`/`regex_registry` keys stay bare; the cross-plugin routing-collision consequence; the honest bound (*"current real-world impact is zero — all shipping plugin ids are globally unique"*); and the deferral rationale (needs a coordinated dispatch/speaking rewrite). This is exactly the inscribed-residual option offered for Y1.
- `test_f2_cross_plugin_same_name_tool_impl_coexist` added and green: two plugins each declaring `tool_impl: echo` coexist as `pluginA__echo` + `pluginB__echo`, bare `echo` absent — pins D4's always-prefix coexistence for the *tool_impl* contribution (the case round-1 noted already works; the role-identity case is the inscribed deferral, correctly **not** built this slice).

## 🔴 R2 — NEW: `mypy --strict` red (7 errors) — RW1's union return-type not narrowed in the valid-registry test paths

`uv run mypy` (canonical `files=["src","tests"]`) → **7 errors, all in `tests/plugins/test_wired_whole_registry.py`**:

```
:100 / :114 / :164      Unsupported right operand type for in ("dict[str, RegistryEntry] | _RegistryRefuseAll")
:101 / :102 / :115 / :165   Value of type "dict[str, RegistryEntry] | _RegistryRefuseAll" is not indexable
```

RW1 widened `_resolve_plugin_registry`'s return to `PluginRegistry | _RegistryRefuseAll` and updated the *malformed* test (rw2 → `is REGISTRY_REFUSE_ALL`), but the **sibling valid-registry tests** rw3/rw4 (`test_rw3_valid_plugins_yaml_entries_applied`, `test_rw3_disabled_entry_present`, `test_rw4_load_plugins_receives_real_registry`) still do `"x" in result` / `result["x"]` on the now-union value without narrowing the sentinel away → mypy-strict rejects `in` / indexing.

- **Nature:** mechanical, **test-only**, **runtime-green** (`pytest tests/plugins` → 156 passed; the valid paths *do* return a dict at runtime). Not a trust / admission / gate-logic breach — distinct in character from round-1 R1. But `mypy --strict` is a **mandatory merge gate** (CLAUDE.md) and it is red, so it blocks merge → verdict cannot reach clean.
- **Fix (junior; I describe, do not apply — reviewer/impl separation):** insert one narrowing assert before the dict ops in each of the 3 valid-registry tests, after `result = _resolve_plugin_registry(config_dir)`:
  ```python
  assert isinstance(result, dict)  # valid config → real registry, not the refuse-all sentinel
  ```
  This narrows the union for mypy *and* strengthens the test (asserts the valid path is a real registry, not the sentinel). Three insertion points (`test_wired_whole_registry.py` ~L99, ~L113, ~L163); covers all 7 errors.

## Gate results (impl_head `329b490`)

| Gate | Result |
|---|---|
| `ruff check src tests` | ✅ All checks passed |
| `mypy` (`files=src,tests`) | ❌ **7 errors** in `tests/plugins/test_wired_whole_registry.py` (R2) |
| `pytest tests/plugins` | ✅ **156 passed** (incl. all RW1/RW2/RW3 tests) |

**Round-2 verdict: `blocking`** — R1 + Y1 substantively resolved; one new mechanical blocker (R2, `mypy --strict` red) stands between the rework and clean. A narrow β-fix dispatch (3 one-line asserts) clears it — no design question, no re-routing. I route nothing.
