---
task_id: P4.4
round: R0-B-on-plan-cross-family-external
reviewer_family: deepseek
reviewer_model_id: deepseek-v4-pro
reviews_acked:
  - architect-briefs/P4.4.md
  - senior-plans/P4.4.md
  - decisions/ADR-038-plugin-registry-lifecycle.md
verdict: needs_architect
findings_count: { red: 0, yellow: 5, green: 1 }
---

# R0-B-on-plan: P4.4 cross-family external lens — plugin registry + lifecycle + admission + namespacing

**Stance:** Deliberately outside-Claude lens. Every finding traced against the live substrate in `src/orchestrator/plugins/{provenance,loader,schema,code,fetch}.py` and `src/orchestrator/api/app.py`, NOT trust-the-types. All plan/ADR claims probed for admission-bypass, provenance-forge, silent-fail-open, pierced-gauntlet, and atomicity-break.

---

## Lens (a) — Admission trust boundary

### (a1) Provenance / posture un-forgeable — ✅ CLEAN

**Claim:** Registry entry never declares provenance/posture; provenance stays host-derived-by-which-root (ADR-031 D3, un-launderable). Shape↔root mismatch refused.

**Traced against:**
- `loader.py:557-566`: operator-placed root → `_discover_and_validate(... provenance="operator_placed")` — provenance parameter set by the CALLER based on which root, never read from manifest or entry.
- `loader.py:569-578`: fetched root → `provenance="fetched"` — same pattern.
- `code.py:327-333`: `load_plugin_code` dispatches on `provenance` parameter → `_load_posture_a_fns` (in-process) vs `_load_posture_b_fns` (subprocess). Unspoofable — not read from plugin-authored content.
- `provenance.py`: `ActivationEntry` has `source_url`, `digest`, `plugin_subprocess_env` — NO `provenance` or `posture` field. Plan's `RegistryEntry` adds `enabled` + `version`, keeps the same invariant.

**The plan's shape↔root mismatch guard (P4.4-2, new):** An entry carrying `digest`/`source_url` found in `plugins/` (operator-placed root) → refuse. Vice-versa (bare entry in `fetched_plugins/`) → already refused by `loader.py:359-367` (fetched-requires-activation). Clean.

**Verdict:** Plan's provenance-un-forgeable claim is structurally honest and consistent with the existing architecture. No 🔴.

### (a2) Fetched admission floor intact — ✅ CLEAN

**Claim:** Fetched plugin still requires digest-bearing operator-authored entry AND digest-before-extract (ADR-031 D4/D5). Version coherence check fail-closes on mismatch.

**Traced against:**
- `loader.py:359-367`: `if provenance == "fetched": if activation_entry is None: return None` — fail-closed. Plan **preserves** this (P4.4-2).
- `fetch.py:170-181`: Digest verified BEFORE extraction — the ordering IS the security property. Plan **does not touch** `fetch.py`.
- Version coherence check (P4.4-2, new): `registry.version` (if set) must equal `manifest.version` → mismatch refuses. This is a **consistency guard**, not a new integrity barrier — the digest already pins exact bytes. The plan's `version` is optional (None → check skipped, by design — senior plan §5 #4). This is NOT a hole: the digest is the real integrity guarantee; version coherence catches operator error (pinning wrong version label for the digest), not malicious substitution.

**Verdict:** Fetched admission floor intact. The version-optional bypass is by design and harmless (digest is the real guard). No 🔴.

### (a3) Malformed-registry fail-closed — 🟡 FINDING

**Claim:** Parse error → load zero plugins (refuse-all, loud). Absent registry → shipped defaults. Malformed vs absent distinguished correctly.

**Traced against:**
- Current `load_activation_registry` (`provenance.py:64-137`): raises `ConfigError` on malformed YAML/schema violation (lines 89,96,101,105,109,115,119,125); returns `{}` for absent/None/empty (lines 80-86).
- `load_plugins` at `loader.py:553`: calls `load_activation_registry(activation_registry_path)` — if this raises `ConfigError`, it propagates **uncaught** up through `_build_context` (`app.py:255`) → **bootstrap crash**, not graceful "zero plugins."
- Plan P4.4-2 says: "malformed registry → empty result + WARNING." Plan P4.4-1 says: "`load_plugin_registry` raises `ConfigError` on malformed."

**The gap:** The plan specifies the INTENT (refuse-all, return empty) but the exception-throwing mechanism in `load_plugin_registry` + the uncaught call site in `load_plugins` would produce a **bootstrap crash**, not a graceful refusal. The crash IS fail-closed (nothing loads → safe), but it isn't the "load zero plugins + WARNING" behavior the plan promises. Risk: junior follows the letter (raises ConfigError, doesn't wrap in try/except) → crash-on-malformed-registry → operational brittleness beyond what the plan intends (the plan's "operationally brittle" trade-off is about refusing-all-plugins, not about crashing the entire app).

**Severity:** 🟡 — plan specification gap. The intent is correct (refuse-all, fail-closed) but the mechanism is underspecified. The `_resolve_plugin_registry(config_dir)` helper (P4.4-4, `app.py` level, following the P4.3 `_resolve_sandbox_posture` precedent at `app.py:172-198`) could catch `ConfigError` and return an empty dict + WARNING — this is the right pattern but the plan doesn't wire it through explicitly.

**Concrete fix:** P4.4-2 or P4.4-4 should specify: `load_plugins` (or `_build_context` via `_resolve_plugin_registry`) catches `ConfigError` from `load_plugin_registry` → logs WARNING → returns empty registry (refuse-all, no crash). Follow the `_resolve_sandbox_posture` pattern at `app.py:192-196`.

**Artifact:** Plan P4.4-2 / Plan P4.4-4; ADR-038 D2; `provenance.py:89,96,101,105,109,115,119,125` (raise sites); `app.py:255` (uncaught call site).

### (a4) Disabled means unreachable — ✅ CLEAN

**Claim:** `enabled: false` → plugin contributions (agents/skills/tools/tool_impls/MCP sessions) absent from merged `AppContext` — not merely flagged.

**Traced against:**
- Plan P4.4-2: "Per discovered candidate: look up its entry by plugin_id; skip (do not load) any plugin whose entry sets `enabled: false`."
- `load_plugins` at `loader.py:588-627`: the for-loop calls `_load_plugin` per candidate; only on success (line 611: `if result is None: continue`) does it update `seen_*` sets and merge into `merged.*` dicts. The enabled-gate inserted BEFORE `_load_plugin` (or at its start) means: disabled → `_load_plugin` never called → no MCPSession started, no tool_impls registered, no contributions merged.
- Boot-only (DP2b): no code mutates a running `AppContext`. MCPSession (persistent) is only started in `_load_plugin` → disabled plugin's MCP server never starts. `tool_impls` (per-call) are never registered → can't be dispatched. No mid-turn teardown surface.

**Verdict:** The plan gates at the correct level. Disabled plugins are structurally unreachable. No 🔴.

### (a5) Admission not gate-bypass / not LLM call — ✅ CLEAN

**Claim:** No new `LLMPurpose`; admission deterministic operator config, never routes through autonomy gate.

**Traced against:**
- `grep -rn "LLMPurpose" src/orchestrator/plugins/` → **zero hits**.
- `grep -rn "LLMPurpose" src/orchestrator/api/app.py` → **zero hits**.
- `LLMPurpose` exists only in `src/orchestrator/llm/purposes.py` and `types.py` — no plugin/registry surface introduces it.
- Plan P4.4-5 item 8: "zero new `LLMPurpose`" — consistent with code.
- The enabled gate is `if not entry.enabled: skip` — deterministic bool check, no gate scoring, no LLM call.
- `_apply_reversibility_cap` (`loader.py:297-318`): host-authoritative-or-default-0, unchanged. Enabling/disabling a plugin does not affect reversibility capping.

**Verdict:** Admission stays outside the autonomy gate. No new LLMPurpose. No reversibility-cap bypass. Clean.

### (a6) RB-ADMIT residual honest — ✅ CLEAN

**Claim:** Pinned digest proves integrity, not authorship. No author-identity, no revocation, no update-trust. "Verified" not "trusted-author."

**Traced against:**
- `fetch.py:170-181`: sha256 of compressed bundle bytes — integrity only. No signature verification, no keyring, no signer identity.
- ADR-038 D3 residual inscription: "Operator-admit + pinned-digest proves integrity... and nothing about authorship or revocation." This is factually accurate.
- No signature verification code exists or is planned for P4.4 (DP3 ratified: signature deferred).
- The residual explicitly names: no author-identity, no revocation (vetted-then-malicious stays admitted until hand-removed), no update-trust (every new version re-pinned by hand).

**Verdict:** The RB-ADMIT residual is inscribed honestly, in the RB-FS/NET voice. No softening detected. Clean.

---

## Lens (b) — Registry / lifecycle state-machine correctness

### (b1) Namespacing stays fail-safe — 🟡 FINDING

**Claim:** Cross-plugin collisions auto-namespace `<plugin_id>__<name>`; host-collision stays fail-closed (incl. shadow-bypass). Namespacing deterministic (always-prefix).

**Traced against:**
- Current `_collision_check` (`loader.py:194-289`): fail-closed on ALL collisions — host and cross-plugin. Lines 253-262: the shadow-bypass check (`impl_name in host_local_tool_names`).
- Plan P4.4-3: "Replace **cross-plugin** fail-closed-on-collision with deterministic always-namespace... KEEP fail-closed for host-collision and within-plugin duplicate."

**The specification gap:** The plan says always-prefix (merged name = `<plugin_id>__<name>`) AND "KEEP fail-closed for host-collision." But with always-prefix, the merged name structurally cannot equal a host bare name (unless the host coincidentally has a `pluginA__something` entry). The plan doesn't specify the ORDER: does the host-collision check run on BARE names (before prefixing) or PREFIXED names (after prefixing)?

- **Bare-name-first:** Plugin declares `read_file` → host-collision check sees `read_file` vs host `read_file` → refused. But the merged name would have been `pluginA__read_file` (no actual collision). This creates **false positives** — innocent bare-name matches refuse plugins that wouldn't actually shadow.
- **Prefixed-name-first:** Plugin declares `read_file` → prefix to `pluginA__read_file` → host-collision check sees `pluginA__read_file` vs host `read_file` → no match → allowed. Correct for always-prefix model. Catches only contrived collisions (host has `pluginA__read_file`).
- **Current shadow-bypass** (`loader.py:253-262`): checks `impl_name in host_local_tool_names` with BARE names. This is the security-load-bearing check.

The plan's intent is correct (host-shadow protection preserved), and the always-prefix model makes bare-name shadowing structurally impossible regardless of ordering. But the specification doesn't resolve the ordering ambiguity → risk of junior implementing the wrong ordering (bare-name-first → false-positive refusals for innocent plugins) or removing the check entirely (which is safe under always-prefix but loses defense-in-depth).

**Severity:** 🟡 — specification ambiguity, not a safety hole. Always-prefix structurally prevents host-shadowing regardless of check ordering. Recommend: specify "host-collision check runs on prefixed names; always-prefix makes bare-name shadowing structurally impossible; the check provides defense-in-depth against contrived prefixed-name collisions."

**Artifact:** Plan P4.4-3; `loader.py:253-262` (shadow-bypass check); ADR-038 D4.

### (b2) Atomic per-plugin merge preserved — ✅ CLEAN

**Claim:** Failure at any stage discards the whole intermediate. Host registries never half-mutated.

**Traced against:**
- `load_plugins` at `loader.py:588-627`: The for-loop calls `_load_plugin` → returns full `PluginLoadResult` or `None`. The `seen_*` sets and `merged.*` dicts are updated ONLY at lines 614-627, AFTER the `if result is None: continue` guard at line 611-612.
- Plan's additions (enabled-gate, version-coherence) would be inserted in `_load_plugin` before it returns a result → same atomicity guarantee maintained by the outer loop.
- `_collision_check` (`loader.py:370-383`): called inside `_load_plugin`, only READS `seen_*` sets (no mutation). Mutation only in the outer loop after success.

**Verdict:** Atomic per-plugin merge structurally preserved. Plan additions don't create partial-admit paths. Clean.

### (b3) Boot-only claim real — ✅ CLEAN

**Claim:** Zero runtime-mutation surface. No live `AppContext` swap. Disable means not-started-at-boot, never mid-turn teardown.

**Traced against:**
- `_build_context` (`app.py:201-333`): runs once at FastAPI lifespan startup (`app.py:806`).
- `load_plugins` called at `app.py:255` within `_build_context` — once, at boot.
- `AppContext` (`app.py:94-112`): regular `@dataclass` with mutable fields. No route handler mutates `available_agents`, `local_tools`, `mcp_sessions`, etc.
- No endpoint writes a registry that takes live effect. No hot path re-runs `load_plugins`.
- `_PostureBFn` (`code.py:59-240`): per-call container spawn-and-kill (lines 237-240: `runtime.kill(container_name)` in finally). No persistent sandboxed plugin process.
- Plan adds no mutation surface (DP2b boot-only, DP4b per-call preserved).

**Verdict:** Boot-only claim honest. No runtime mutation. MCPSession/`tool_impl` distinction respected. Clean.

### (b4) Composition-root wiring fail-closed — ✅ CLEAN

**Claim:** `_resolve_plugin_registry` driven by real function (RW8-2 lesson). Disjoint-root guard holds.

**Traced against:**
- Plan P4.4-4: extract `_resolve_plugin_registry(config_dir)` helper following the P4.3 `_resolve_sandbox_posture` precedent at `app.py:172-198`.
- `_resolve_sandbox_posture`: a real, importable function that tests can call directly — parse-fail branch is the real code, not a re-implemented copy. The plan copies this pattern.
- Disjoint-root guard at `loader.py:531-550`: still holds because both roots are passed through the same `load_plugins` call.
- Current `app.py:255-267`: no `fetched_plugins_dir`, no `activation_registry_path` passed — fetched path unreachable. Plan P4.4-4 wires both.

**Verdict:** Composition-root wiring follows established P4.3 pattern. Disjoint-root guard preserved. Clean.

### (b5) Update / re-admit re-verifies — 🟡 FINDING

**Claim:** ADR-038 D2: "the digest floor (ADR-031 D5) **re-runs at boot** and, for fetched, registry.version (if set) must equal manifest.version → mismatch refuses."

**Traced against:**
- `fetch.py:170-181`: sha256 verified on compressed bundle bytes BEFORE extraction — but this runs in `fetch_plugin_bundle()` (an explicit fetch operation), NOT at boot.
- `load_plugins` → `_discover_and_validate` (`loader.py:94-186`): reads `plugin.yaml` from the plugin directory. Does NOT re-hash the extracted bundle contents. No boot-time digest re-verification.
- The plan does NOT add a boot-time digest re-check (none of P4.4-1 through P4.4-6 add it).

**The gap:** "Re-runs at boot" is factually overstated. The digest is a one-time integrity check at fetch time on the compressed bundle. Once extracted, the directory contents are not re-verified against the digest at boot. The actual boot-time check is version-coherence only (`registry.version == manifest.version`).

This is NOT a security hole (the residual — post-fetch tampering of the extracted directory — requires host filesystem access, which means the operator trust root is already compromised). But the ADR claim is inaccurate and should be corrected.

**Severity:** 🟡 — ADR documentation accuracy. The actual security property is sound (digest-at-fetch + version-coherence-at-boot). The ADR should say "the digest floor verified at fetch time" not "re-runs at boot."

**Concrete fix:** ADR-038 D2: s/re-runs at boot/is verified at fetch time (digest-before-extract ordering)/. Add: "At boot, the version-coherence check (registry.version == manifest.version) catches operator version/digest mismatches; post-fetch tampering of the extracted directory is not re-verified (operator trust-root assumption)."

**Artifact:** ADR-038 §D2; `fetch.py:170-181` (digest check is fetch-time only); `loader.py:94-186` (no boot-time re-hash).

### (b6) Registry edge cases — 🟡 FINDING (x2)

**Claim:** Each edge case (typo dir, missing entry, duplicate plugin_id, non-bool enabled) resolves to a defined, fail-safe outcome.

**Traced against the plan:**

**🟡 (b6a) `enabled` type-validation not explicitly specified.**

- YAML `enabled: "false"` (quoted string) → Python `str("false")` → `bool("false")` is `True` (non-empty string truthy) → plugin loads → **fail-open** if type not validated.
- **Confirmed by live test:** `yaml.safe_load('enabled: "false"')` → `{'enabled': 'false'}` (string, not bool). `isinstance("false", bool)` → `False`.
- YAML `enabled: false` (unquoted) → Python `False` (bool) → correct. But `enabled: "false"` is a plausible user error in a handwritten config file.
- The CURRENT `load_activation_registry` (`provenance.py:100-129`) explicitly validates EVERY field's type with `isinstance()` checks. The plan P4.4-1 says "fail-closed validation" but the acceptance criteria don't explicitly list `isinstance(enabled, bool)` or `extra="forbid"` (reject unknown keys in entry).
- **Risk:** Junior follows the plan's acceptance criteria literally (frozen dataclass with type hints) but doesn't add runtime `isinstance` validation → Python dataclass type hints are NOT enforced at runtime → `enabled: "false"` silently enables plugin.

**Concrete fix:** P4.4-1 acceptance criteria should explicitly require: (1) `isinstance(enabled, bool)` validation in `load_plugin_registry`, following the existing `provenance.py:100-129` pattern; (2) reject unknown keys in each registry entry (`extra="forbid"` equivalent); (3) `version` must be `str | None` (reject non-string, non-null values).

**🟡 (b6b) Duplicate `plugin_id` entries silently overwrite — plan doesn't specify detection.**

- If the registry YAML uses a **mapping** keyed by `plugin_id` (as ADR-038 D1 table suggests with "plugin_id (key)"):
  ```yaml
  plugins:
    my_plugin:
      enabled: false
    my_plugin:
      enabled: true
  ```
  → PyYAML 6.0.1 **silently takes the last value** (confirmed via live test). The first entry is lost with no warning.

- If the registry uses a **list** (like the current `load_activation_registry` with its `activations` list), the validator can detect duplicate `plugin_id` values when inserting into the dict.

- The plan doesn't specify the YAML format. The current `load_activation_registry` uses a list format with duplicate detection possible. The ADR-038 D1 table suggests a mapping format. The plan should pick one and specify duplicate detection.

**Concrete fix:** Specify the YAML format (recommend list format matching the existing `load_activation_registry` pattern) and require: when building the `dict[plugin_id, RegistryEntry]`, a duplicate `plugin_id` raises `ConfigError` (fail-closed).

**Severity:** 🟡 (both) — specification gaps. The existing code pattern (explicit `isinstance` validation, list-based format) already covers these; the plan just needs to explicitly carry forward the pattern.

**Artifact:** Plan P4.4-1 acceptance; ADR-038 D1; `provenance.py:100-129` (existing pattern).

---

## 🟢 Nit

**🟢 (g1) ADR-038 D2 digest-vs-boot precision.** The ADR could note that the digest floor operates at fetch time on the compressed bundle, not at every boot on the extracted directory. This is an acceptable residual (operator is the trust root; host filesystem access implies broader compromise). The version-coherence check at boot provides the consistency guard. See (b5) for the related 🟡 on the overstated "re-runs at boot" claim.

---

## Cross-cutting self-checks

- **No new `LLMPurpose`** — confirmed: zero hits in `src/orchestrator/plugins/` or `src/orchestrator/api/app.py`. All `LLMPurpose` usage stays in `src/orchestrator/llm/purposes.py`.
- **Admission not gated** — confirmed: the enabled check is a deterministic `if not entry.enabled: skip`, not a gate scoring call. DP2c honored.
- **Provenance un-launderable** — confirmed: provenance parameter set by caller based on which root, never read from entry/manifest. Shape↔root mismatch guard (new) adds defense-in-depth.
- **Per-call sandbox inherited** — confirmed: `_PostureBFn` per-call spawn-and-kill preserved (ADR-037 D3). Plan adds zero persistent-sandbox surface.
- **`_execute_local_call` byte-frozen** — confirmed: not in scope of this plan; no change planned.
- **Plan §5 sub-decisions** — the senior's five forks are architect-confirm items. I reviewed them for correctness problems:
  - §5 #1 (preserve operator-placed presence=opt-in): preserves ADR-029 D5, correct.
  - §5 #2 (refuse-all on malformed): safest choice, operational brittleness acknowledged honestly — see (a3) 🟡 on the mechanism gap.
  - §5 #3 (always-prefix namespacing): deterministic, correct — see (b1) 🟡 on ordering specification.
  - §5 #4 (version coherence check): small new check, defendable, surfaced for architect confirm — no correctness objection.
  - §5 #5 (management endpoints contract-only): consistent with DP4c, no correctness objection.

---

## Summary

| Severity | Count | IDs |
|---|---|---|
| 🔴 blocking | **0** | — |
| 🟡 should fix | **5** | (a3) malformed→crash gap, (b1) namespacing ordering, (b5) ADR "re-runs" overstated, (b6a) enabled type validation, (b6b) duplicate plugin_id entries |
| 🟢 nit | **1** | (g1) ADR digest-vs-boot precision |

**Verdict: `needs_architect`** — 0 🔴 (no admission-bypass, provenance-forge, silent-fail-open, pierced-gauntlet, or partial-admit atomicity break), 5 🟡 (plan/ADR specification gaps the architect should route before junior dispatch). The plan's trust-boundary architecture is sound; all five 🟡 are specification-precision issues that can be absorbed (α) without re-architecting.

**Route nothing** — architect routes α/β/γ/δ.
