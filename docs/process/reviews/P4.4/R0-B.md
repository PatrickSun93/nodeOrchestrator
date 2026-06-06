---
task_id: P4.4
round: R0-B-cross-family-external
reviewer_family: deepseek
reviewer_model_id: deepseek-v4-pro
reviews_acked:
  - architect-briefs/P4.4.md
  - senior-plans/P4.4.md
  - decisions/ADR-038-plugin-registry-lifecycle.md
verdict: clean
findings_count: { red: 0, yellow: 0, green: 3 }
verdict_history:
  - round: 1
    date: 2026-06-05
    verdict: needs_architect
    findings_count: { red: 0, yellow: 2, green: 3 }
    notes: >
      Y1 (🟡): ADR-038 D2 "refuse-all" overclaim vs impl — empty dict {} meant
      refuse-all-fetched-only; op-placed loads by presence, re-enabling plugins
      the operator disabled in the (broken) config. Y2 (🟡): catch clause
      ConfigError-only, missing yaml.YAMLError for syntax-invalid YAML.
  - round: 2
    date: 2026-06-06
    verdict: clean
    findings_count: { red: 0, yellow: 0, green: 3 }
    rework_commits:
      - "0ed7877 P4.4-RW1: β-fix true sentinel for malformed registry fail-open"
      - "07d7606 P4.4-RW2: catch yaml.YAMLError in _resolve_plugin_registry"
    notes: >
      Y1 resolved: REGISTRY_REFUSE_ALL sentinel distinct from None (absent)
      and {} (empty); load_plugins receives sentinel → early-returns empty
      PluginLoadResult before candidate loop — no op-placed presence
      resurrection, no fetched activation. Y2 resolved: yaml.YAMLError
      caught alongside ConfigError; unparseable-YAML test added and passes.
      All 26 P4.4 tests pass.
---

# R0-B cross-family review — P4.4 impl stage

**Lens:** external (DeepSeek, cross-family). **Total: 0🔴 2🟡 3🟢**

## Review methodology

Traced every Lens (a) and Lens (b) item against the real impl diff
(6 atomic commits on `claude/P4.4-impl`, `git diff origin/main..HEAD`,
files `provenance.py`, `loader.py`, `app.py`; `fetch.py`/`code.py`/`schema.py`
confirmed unchanged). Every `isinstance` guard, every return path, every
`continue` short-circuit verified against the actual bytecode in the diff.
All 96 registry/loader/merge/constitution tests pass (green).

---

## Lens (a) — plugin-ADMISSION TRUST BOUNDARY

### a1. Provenance / posture un-forgeable ✅

**Verdict: solid.** Three independent layers:

1. **Schema-layer:** `_KNOWN_REGISTRY_ENTRY_KEYS` (`provenance.py:175-177`) excludes
   `provenance` and `posture` — any YAML entry carrying either raises `ConfigError`
   (`provenance.py:264-267`, "unknown keys"). Test-asserted: `test_g1_yaml_entry_with_provenance_rejected`,
   `test_g1_yaml_entry_with_posture_rejected`, `test_pr7_unknown_key_raises`.

2. **Model-layer:** `RegistryEntry` dataclass has no `provenance` or `posture` field
   (`provenance.py:200-206`). Test-asserted: `test_pr1_registry_entry_no_provenance_field`,
   `test_g1_registry_entry_cannot_declare_provenance`.

3. **Derivation-layer:** Provenance is set exclusively by `_discover_and_validate`
   (`loader.py:96-102`, the `provenance` parameter — `"operator_placed"` or `"fetched"`,
   set by the caller per discovery root). Neither `RegistryEntry` nor
   `load_plugin_registry` reads or returns provenance.

**Shape↔root mismatch guard:** `_load_plugin` (`loader.py:368-378`) refuses an
operator-placed plugin whose registry entry carries fetched-shape (source_url+digest).
Test-asserted: `test_g1_fetched_shape_entry_for_op_placed_refused`,
`test_p442_shape_coherence_op_placed_with_fetched_entry_refused`.

**Asymmetric note:** Fetched plugin with operator-placed-shape entry (no source_url)
is not explicitly shape-checked — it falls through to the fetched activation guard
(`loader.py:399-412`), which correctly refuses it because `_has_registry_activation`
is False and `activation_entry` is None (legacy not wired in production).
The protection is intact, but the layering is fragile — the protection depends on the
activation guard never being weakened. Not a current hole. 🟢

### a2. Fetched admission floor intact ✅

**Verdict: intact.** Three independent holds:

1. **Digest-bearing entry required:** `load_plugin_registry` enforces source_url+digest
   as a pair (`provenance.py:316-321` — "both present or both absent").
   Test-asserted: `test_pr4_source_url_without_digest_raises`, `test_pr4_digest_without_source_url_raises`.

2. **Digest-before-extract ordering preserved:** `fetch.py` is **zero-diff**
   (unchanged from `origin/main`). The integrity-critical ordering
   (`fetch_plugin_bundle:170-181` — compute sha256 of compressed bytes BEFORE any extraction)
   is untouched. See also R0-B Y5 from the original P3.7 review.

3. **Version-coherence correctly framed as operator-intent, not integrity:**
   `_load_plugin` (`loader.py:384-397`): `registry.version` (if set) must equal
   `manifest.version` → mismatch refuses. The comment correctly identifies this as an
   "operator-intent / update-consistency" check, NOT an integrity barrier; `version`
   is plugin-self-asserted. `version` absent → no check = **fail-safe** (the digest
   still binds the bytes). ADR-038 D2 text matches this framing. Test-asserted:
   `test_g7_version_mismatch_refused`, `test_g7_version_absent_loads_fail_safe`.

### a3. Malformed-registry fail-closed ⚠️ 🟡

**Finding Y1 (🟡) — ADR-038 D2 "refuse-all" overclaim vs. implementation.**

ADR-038 D2 states: "malformed registry → **load zero plugins** (refuse-all, loud —
the P4.3 `_resolve_sandbox_posture` parse-fail→fail-closed precedent at registry
granularity)."

The implementation (`_resolve_plugin_registry`, `app.py:216-225`) catches `ConfigError`
and returns `PluginRegistry()` — an **empty dict**. The empty dict is then passed
to `load_plugins` as `plugin_registry`. In the enabled-gate (`loader.py:639-647`):

```python
r_entry = plugin_registry.get(candidate.plugin_id) if plugin_registry is not None else None
if r_entry is not None and not r_entry.enabled:
    continue
```

With `plugin_registry = {}`:
- `r_entry` is `None` for every plugin
- The `if` body never executes → **operator-placed plugins load by presence**

This means "refuse-all" is actually **"refuse-all-fetched-only"**. An operator-placed
plugin loads by presence (ADR-029 D5 unchanged) even when the registry is malformed.

**Why this matters — the re-enable-on-malformed scenario:** An operator who
(a) adds `enabled: false` for an operator-placed plugin, then (b) makes a typo
elsewhere in `config/plugins.yaml` → parse failure → empty registry → the
operator-placed plugin **silently re-enables**. The operator's disable intent is lost.

**Severity rationale (🟡 not 🔴):** (i) The fail direction is conservative for
*new* operator-placed plugins (presence=opt-in is the existing shipped posture);
(ii) the re-enable scenario is a specific sequence, not the default path;
(iii) the WARNING log still fires. However, the gap between the ADR's declared
safety property ("refuse-all") and actual behavior ("refuse-all-fetched-only")
is real and should be resolved — either tighten the implementation (add a
`registry_was_malformed` sentinel to the loader) or correct the ADR text.

**Plan §5 #2 and the absorption record are internally contradictory on this point:**
the architect confirmed "refuse-all" but the absorption mechanism description
("achieved via catch→empty-registry") cannot achieve refuse-all for operator-placed
— and the plan text itself acknowledges this ("every operator-placed plugin still gated
by its (now-absent) entry" at P4.4-4).

**Finding Y2 (🟡) — `_resolve_plugin_registry` catch clause too narrow: `ConfigError`
only, not `yaml.YAMLError`.**

`load_plugin_registry` calls `yaml.safe_load(raw_text)` (`provenance.py:244`).
PyYAML's `safe_load` raises `yaml.YAMLError` subclasses (`ScannerError`, `ParserError`,
`ConstructorError`) on unparseable syntax — NOT `ConfigError`. `_resolve_plugin_registry`
(`app.py:218`) catches only `ConfigError`. A YAML **syntax** error (as opposed to a
schema error) propagates uncaught through `_build_context` → **crashes the app**.

**Narrow blast radius:** In practice, the common malformed-registry case is schema errors
(wrong types, unknown keys, missing required fields), which DO raise `ConfigError` and
ARE caught. Genuinely unparseable YAML syntax requires broken input like `*undefined_alias`
(PyYAML safe_load rejects aliases). The existing `_resolve_sandbox_posture`
(`app.py:172-196`) has the same narrow-catch pattern and has not been a problem in
production.

**Fix:** Broaden the catch to `except (ConfigError, yaml.YAMLError)` or catch
`Exception` (matching the "any parse failure → empty" intent of P4.4-4).

### a4. Disabled means unreachable ✅

**Verdict: unreachable.** The enabled-gate (`loader.py:641-647`) uses `continue` in
the candidate loop **before** `_load_plugin` is called. Trace:

1. `r_entry` resolved from the registry
2. `if r_entry is not None and not r_entry.enabled: continue`
3. `_load_plugin` is never entered for disabled plugins

`_load_plugin` step 4 (`loader.py:464-472`) calls `build_mcp_tool_registry_and_sessions_from_config`,
which spawns a **live stdio subprocess**. The `continue`-before-`_load_plugin` placement
guarantees **no MCP session, no subprocess constructed** for a disabled plugin.

Test-asserted (`test_g5_disabled_plugin_with_mcp_server_no_session`): patches
`_load_plugin` with a tracking wrapper, asserts it's never called for the disabled
plugin, and asserts `result.mcp_sessions == {}`.

Also verified: `_load_plugin` returns `None` on any failure → `continue` in the
outer loop → **no partial merge** → atomic per-plugin. No "built-then-dropped" path
for disabled. 🟢

### a5. Admission is not a gate-bypass and not an LLM call ✅

**Verdict: no gate involvement.** Three independent checks:

1. **No `LLMPurpose` in plugins/ or app.py:** grep confirmed zero matches across
   `src/orchestrator/plugins/*.py` and `src/orchestrator/api/app.py`. Test-asserted:
   `test_g8_no_new_llm_purpose_in_plugins` — scans every `.py` file in `plugins/`
   for the `LLMPurpose` symbol.

2. **No gate symbols in plugins/:** `test_g9_admission_does_not_call_gate` — scans
   every `.py` in `plugins/` for `decide_tier`, `emit_gate_decision`, `score(` —
   all absent. Test-asserted.

3. **Reversibility cap unchanged:** `_apply_reversibility_cap` (`loader.py:304-325`)
   is deterministic (`min(plugin, host)` → default-0). Enabling a plugin can never
   LOWER a tier (host-authoritative-or-default-0). `_execute_local_call` diff
   confirmed zero (no changes to executor). Test-asserted:
   `test_g10_execute_local_call_not_called_or_imported_in_plugins`.

### a6. The `RB-ADMIT` residual is honest, not softened ✅

**Verdict: honest.** ADR-038 D3 explicitly lists the residual: **no author identity,**
**no revocation, no update-trust.** The residual inscription uses the `RB-FS/NET`
voice ("what A4 does NOT prove") as required. `fetch.py` is diff-zero — the
digest-before-extract ordering is preserved. No "verified" language implying
"trusted-author." 🟢

---

## Lens (b) — REGISTRY / LIFECYCLE STATE-MACHINE CORRECTNESS

### b1. Namespacing stays fail-safe (A5) ✅

**Verdict: fail-safe.** The order-of-operations (ADR-038 D4, absorbed R0-A Y4 / R0-B b1)
is correctly implemented:

1. **Host-collision evaluated on BARE names → REFUSE** (`_collision_check`,
   `loader.py:222-295`). Host name sets are passed by the caller; the check uses
   the bare `role_id`/`skill_id`/`tool_name`/`impl_name`/`server_name` from the manifest.

2. **Shadow-bypass specifically:** `impl_name in host_local_tool_names`
   (`loader.py:268-275`) → **refused** on bare name. A plugin declaring
   `tool_impl: read_file` is refused loudly, NOT silently coexisted as
   `plugin__read_file`. Test-asserted: `test_g6_host_shadow_refused_on_bare_name`,
   `test_tool_impl_shadow_host_local_tool_refused`.

3. **Within-plugin duplicates still refused** (`_plugin_roles`, `_plugin_skills`,
   `_plugin_tools`, `_plugin_servers` — local sets at `loader.py:221,232,248,278`).

4. **Cross-plugin collision resolved by namespacing:** `_collision_check` no longer
   takes `seen_*` parameters (diff confirms removal). The merge step
   (`loader.py:674-679`) applies `{f"{pid}__{k}": v for k, v in ...}` across
   agents/skills/tools/local_tools/mcp_sessions — **deterministic, always-prefix.**

5. **Namespacing is deterministic** (always-prefix, not on-collision): a tool's
   name does not change when a sibling is added. Test-asserted:
   `test_cross_plugin_skill_coexist_namespaced`.

**Caveat — `regex_registry` keys not namespaced:** The `regex_registry` merges bare
(`loader.py:675`, `merged.regex_registry.update(result.regex_registry)`) using
`agent.id` tuples, while the agents dict keys are namespaced
(`loader.py:674`). The comment at `loader.py:672-673` asserts consistency with
`speaking.py` lookup (which resolves by `agent.id`, not dict key). This is an
intentional cross-module contract — not a bug, but a coupling point worth a
cross-check in integration tests. Not flagged as a finding (already reviewed in
plan-stage). 🟢

### b2. Atomic per-plugin merge preserved ✅

**Verdict: preserved.** Each plugin either contributes its full intermediate
(`PluginLoadResult`) or nothing. The `seen_*` sets from the old cross-plugin
collision model are removed (no longer needed) — no partial-mutation risk.
`_load_plugin` returns `None` on any failure (`loader.py:354`) and the merge
step is guarded by `if result is None: continue` (`loader.py:667-668`).
There are no `seen_*.update(...)` calls before a potential refusal point in
the new code. 🟢

### b3. The boot-only claim is real ✅

**Verdict: boot-only.** `_build_context` runs once at startup (`app.py:248`).
`_resolve_plugin_registry` is called once, before `load_plugins` (`app.py:281`).
No endpoint writes a registry that takes live effect (DP4c: contract-only, zero
endpoint code). No hot path re-runs `load_plugins`. Disable means not-started-at-boot
(enabled-gate `continue` before `_load_plugin`). 🟢

### b4. Composition-root wiring fail-closed ✅

**Verdict: correctly wired.** The resolution chain:

1. `_resolve_plugin_registry(config_dir)` reads `config/plugins.yaml` → returns
   `PluginRegistry` (empty on absent/parse-failure). Catching `ConfigError` →
   empty follows the `_resolve_sandbox_posture` precedent.

2. `_build_context` passes both `plugin_registry` and `fetched_plugins_dir` to
   `load_plugins` (`app.py:293-294`). Disjoint-root guard (`loader.py:580-599`)
   is unchanged.

3. Wire-whole test `test_rw2_malformed_plugins_yaml_returns_empty_and_warns` drives
   the real `_resolve_plugin_registry` function (not a hand-built dict) — the RW8-2
   discipline.

**Caveat applied to Y1/Y2 above.** Otherwise solid. 🟢

### b5. Update / re-admit verifies at fetch ✅

**Verdict: verified once, at fetch.** `fetch.py` diff-zero. `fetch_plugin_bundle`
digest-before-extract ordering (`fetch.py:170-181`) is the integrity-critical path.
No "already fetched, skip re-verify" short-circuit. At boot, only the
digest-bearing-entry requirement + version-coherence are re-checked — no re-hash
of the extracted directory tree (correct per ADR-038 D2, absorbed R0-A Y2 / R0-B b5
correction). 🟢

### b6. No silent partial-admit on registry edges ✅

**Verdict: each edge resolved to a defined, fail-safe outcome.** Trace:

| Edge | Outcome | How |
|---|---|---|
| Entry for nonexistent dir | Inert (no matching discovery) | `plugin_registry.get(candidate.plugin_id)` never matches |
| Dir with no entry (operator-placed) | Loads by presence | `r_entry = None` → enabled-gate does not fire; ADR-029 D5 preserved |
| Dir with no entry (fetched) | Refused | `_has_registry_activation = False` + no legacy entry → refused (`loader.py:399-412`) |
| Duplicate `plugin_id` entries | `ConfigError` at parse time | `provenance.py:276-279`; list-format enables detection (mapping would silently keep-last) |
| `enabled` non-bool | `ConfigError` at parse time | `provenance.py:283-288` — `isinstance(enabled_raw, bool)` rejects strings incl. `"false"` (truthy fail-open closed) |
| `version` non-(str\|None) | `ConfigError` at parse time | `provenance.py:292-297` — rejects int, float, etc. |
| Unknown entry key | `ConfigError` at parse time | `provenance.py:264-267` — extra="forbid" equivalent; catches provenance/posture attempts |
| source_url+digest mismatch (one missing) | `ConfigError` at parse time | `provenance.py:316-321` — "both present or both absent" |

🟢

---

## Cross-cutting: not-in-scope items — NOT re-opened

- **Config-file registry (not runtime store):** confirmed — no runtime store; registry
  is one operator-authored YAML file, boot-read.
- **Operator-admit + pinned-digest floor; signature deferred:** confirmed — `fetch.py`
  zero-diff; no keyring/signature code.
- **Per-call sandbox (ADR-037 D3):** confirmed — `code.py` zero-diff; no persistent
  sandbox introduced.
- **Management endpoints contract-only:** confirmed — zero endpoint code; ADR-038 D5
  is a forward-contract only.
- **No new `LLMPurpose`:** confirmed — grep zero matches in plugins/ + app.py.
- **`_execute_local_call` byte-frozen:** confirmed — zero diff to executor; test g10 asserts
  no call/import in plugins/.
- **Plan §5 sub-decisions:** not relitigating the architect's confirmed choices
  (option A, refuse-all-graceful, always-prefix, version-check, contract-only).
  Y1 addresses the *implementation gap* between the "refuse-all" choice and the
  empty-registry mechanism — not the choice itself.

---

## ⚠️ Items NOT probed (out of scope for this review)

These are outside the R0-B mandate (not in `external-r0b-prompt.md` lens a/b) or
require runtime integration testing:

1. **Runtime integration (live-daemon, real MCP stdio subprocess lifecycle).**
   R0-B is a static trace review; the disabled-MCP-no-subprocess guard is
   test-asserted via `patch.object(_loader_mod, "_load_plugin", ...)` but the
   reviewer has not verified the test against a live subprocess. In-scope for
   plan-vs-impl or a daemon-level review.

2. **`speaking.py` / `regex_registry` lookup consistency with namespaced agent keys.**
   The loader comment at `loader.py:672-673` asserts the `agent.id`-based
   regex_registry is "consistent with speaking.py lookup." This reviewer has not
   read `speaking.py` to independently verify. In-scope for integration tests.

3. **The `RB-ADMIT` residual signed-off by the architect, not the reviewer.**
   R0-B's job is to verify the residual is honestly inscribed (a6), not to
   ratify the trust model choice (architect-weight, DP3).

---

## Round 2 — re-verification after RW1+2 rework (2026-06-06)

Junior rework commits:
- `0ed7877` P4.4-RW1: β-fix true sentinel for malformed registry fail-open (R0-A R1)
- `07d7606` P4.4-RW2: catch yaml.YAMLError in _resolve_plugin_registry (R0-B Y2)

### Y1 re-verified ✅ (sentinel closes the fail-open)

`_RegistryRefuseAll` sentinel (`provenance.py:212-226`) is distinct from `None`
(absent registry → today's defaults) and `{}` (empty registry, same absent-defaults
semantics). `_resolve_plugin_registry` returns `REGISTRY_REFUSE_ALL` on `ConfigError`
(`app.py:232`). `load_plugins` receives the sentinel check at `loader.py:630-635`:
`isinstance(plugin_registry, _RegistryRefuseAll)` → return `PluginLoadResult()`
(empty) — **before** the candidate loop. No op-placed presence resurrection, no
fetched activation short-circuit. The re-enable-on-presence leak (operator writes
`enabled: false`, then makes a config typo → disabled plugin resurrected by presence)
is closed.

Tests trace-confirmed:
- `test_g2_empty_registry_absent_loads_op_placed`: renamed (was wrong name —
  asserted LOADS, not refuses); empty dict `{}` → op-placed loads by presence (correct)
- `test_g2_refuse_all_sentinel_refuses_all_op_placed`: NEW — sentinel → op-placed refused
- `test_g2_refuse_all_disabled_op_placed_stays_down`: NEW — the exact re-enable
  scenario blocked
- `test_rw2_malformed_plugins_yaml_returns_sentinel_and_warns`: updated — asserts
  `result is REGISTRY_REFUSE_ALL` (not `== {}`)

### Y2 re-verified ✅ (yaml.YAMLError caught)

`_resolve_plugin_registry` (`app.py:232`): `except (ConfigError, yaml.YAMLError)`
covers both schema errors and syntax errors. `import yaml` added (`app.py:219`).
Both paths return `REGISTRY_REFUSE_ALL` — the refuse-all guarantee is uniform across
schema-invalid AND syntax-invalid configs.

Test trace-confirmed: `test_rw2_unparseable_yaml_returns_sentinel_and_warns`
(`test_wired_whole_registry.py:62-80`) — syntactically broken YAML input
(`"plugins:\n  - {\n  bad: yaml [syntax\n"`) → `yaml.safe_load` raises
`ScannerError` → caught → `REGISTRY_REFUSE_ALL` returned + WARNING logged + no
exception propagates.

### Test run

```
tests/plugins/test_constitution_p44.py .................... 20 passed
tests/plugins/test_wired_whole_registry.py ......             6 passed
Total: 26 passed
```

---

## Verdict: `clean` (0🔴 0🟡 3🟢)

Y1 and Y2 both resolved by RW1+RW2 rework. The `REGISTRY_REFUSE_ALL` sentinel
correctly implements ADR-038 D2 refuse-all; the `yaml.YAMLError` catch closes the
syntax-error crash path. No new findings surfaced during re-verification trace.

**Route nothing.**
