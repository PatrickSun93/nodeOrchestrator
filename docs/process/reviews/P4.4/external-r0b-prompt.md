# External R0-B prompt — P4.4 (plugin registry + lifecycle + admission + namespacing) — MANDATORY dual-lens

> **Dispatch context.** `requires_cross_family_review: true` (ratified; P4-roadmap §8 — A2/A3/A4 heavy, A5 light). You are the **cross-family** reviewer (DeepSeek via the role-rewriting proxy). This is the **plan-stage** prompt; the architect dispatches it at **impl stage** against the impl branch. P4.4 is the **admission** half of the Wave-2 trust slice — orthogonal to P4.3 (ADR-037), which sandboxed what admitted plugin code can *do*. P4.4 decides **what gets admitted, how admission is declared, and how it is revised over time**: a unified config-file registry over both discovery roots, a boot-evaluated lifecycle (enable/disable/update/remove), the shipped operator-admit + pinned-digest admission floor (signature deferred), and cross-plugin namespacing. **The registry is new trust-boundary surface — your job is to find where an entry admits code it should not, forges what it must not, or where the loader's fail-closed gauntlet is pierced.**

---

## Your stance

Take a deliberately **outside-Claude** lens. Over-correct for Claude's biases: trust-the-types-means-trust-the-runtime, over-engineering, agreeableness, "the validator has a field for it therefore the boundary holds." **Trace failure modes across the registry → loader → merge → composition-root chain** and ask "what happens when the registry is malformed / an entry lies about its plugin's provenance / a fetched entry omits its digest / a disabled plugin is still reachable / two plugins race for the same name / `config/plugins.yaml` is absent vs present-but-broken?" Default to **refuted/skeptical** when uncertain; a finding you can't substantiate by tracing the code is not a finding. Cite `file:line` or `artifact §`.

## Artifact bundle — read from disk (in-repo dispatch)

Read in full:
1. `docs/process/architect-briefs/P4.4.md` — the decision-surface (A2–A5 ledger + 5 DPs + watch-list).
2. `docs/process/senior-plans/P4.4.md` — the plan (atomics P4.4-0..6 + the 5 surfaced sub-decisions in §5).
3. `docs/decisions/ADR-038-plugin-registry-lifecycle.md` — the proposed ADR (D1–D5 + the `RB-ADMIT` residual).

Plus the live substrate it declares over (probe claims against the working tree):
- `src/orchestrator/plugins/provenance.py` (`RegistryEntry` / `load_plugin_registry` — the generalised registry; was `ActivationEntry` / `load_activation_registry`).
- `src/orchestrator/plugins/loader.py` (`load_plugins` boot-merge `:494`, `_collision_check` `:194`, the fetched-activation gate `:359-367`, the disjoint-root guard `:531-550`).
- `src/orchestrator/plugins/schema.py` (`PluginManifest.version`/`id` — made load-bearing).
- `src/orchestrator/plugins/fetch.py` (digest-before-extract admit floor — the integrity floor, unchanged), `src/orchestrator/plugins/code.py` (`_PostureBFn` per-call container).
- `src/orchestrator/api/app.py` (`:247-275` registry composition root — the only sanctioned config-injection point; `_resolve_plugin_registry` the wired-whole seam).
- ADR-029 (D2/D4/D5/D6), ADR-031 (D1a/D3/D4/D5), ADR-037 D3 (per-call sandbox — context for what is NOT re-opened).

---

## Lens (a) — the plugin-ADMISSION TRUST BOUNDARY

Probe whether the registry can admit/enable code that should have been refused, or forge what must stay host-derived:

1. **Provenance / posture un-forgeable.** Provenance is host-set-by-which-root (ADR-031 D3, un-launderable). Can a `config/plugins.yaml` entry **turn a fetched plugin into operator-placed** (Posture A in-process import of fetched code — the worst case) or vice-versa? Can an entry declare `provenance`/`posture` at all? Trace: does the entry schema accept those fields, and does the loader **derive** provenance from the root or ever read it from the entry? Is a **shape↔root mismatch** (digest-bearing entry for a `plugins/` plugin) refused?
2. **Fetched admission floor intact.** A fetched plugin must still require a digest-bearing operator-authored entry (ADR-031 D4) AND pass digest-before-extract (ADR-031 D5). Does the generalisation **weaken** either — e.g. does an entry with `enabled:true` but **no digest** load a fetched plugin? Does the `version` coherence check (`registry.version == manifest.version`) actually fail-close on mismatch, or is it skippable (version omitted → check bypassed → is that a hole)?
3. **Malformed-registry fail-closed.** A `config/plugins.yaml` that fails to parse must load **zero** plugins (refuse-all, loud). Trace `_resolve_plugin_registry` / `load_plugin_registry`: does a parse error **refuse all** (incl. operator-placed), or does it silently fall through to "no registry → presence defaults" (which would **re-enable** an operator-disabled plugin — a fail-OPEN on the disable path)? Is absent vs malformed distinguished correctly (absent → shipped defaults; malformed → refuse-all)?
4. **Disabled means unreachable.** `enabled:false` must mean the plugin's contributions (agents/skills/tools/tool_impls/**MCP session**) are **absent** from the merged `AppContext` — not merely flagged. Can a disabled plugin's `tool_impl` still be dispatched, or its bundled MCP server still started? Trace the merge in `load_plugins`.
5. **Admission is not a gate-bypass and not an LLM call.** Admission/lifecycle is deterministic operator config (ADR-029 D3 / ADR-031 D7) — confirm **no new `LLMPurpose`** on this surface and that admission does **not** route through the autonomy gate (it is an operator action, not an agent op, DP2c). Conversely: does enabling a plugin **lower** any tool's reversibility cap (`_apply_reversibility_cap`, host-authoritative-or-default-0)? It must not.
6. **The `RB-ADMIT` residual is honest, not softened.** ADR-038 D3 keeps operator-admit + pinned-digest and Accepts a residual: **no author-identity, no revocation, no update-trust**. Verify it is inscribed in the `RB-FS/NET` voice and is **true** — a pinned digest proves bytes, not a signer; a later-known-malicious bundle stays admitted until hand-removed. Is anything claimed-proven that is only integrity (e.g. "verified" reading as "trusted-author")?

## Lens (b) — the REGISTRY / LIFECYCLE STATE-MACHINE CORRECTNESS

Probe the loader's fail-closed gauntlet + the namespacing relaxation for consistency and atomicity:

1. **Namespacing stays fail-safe (A5).** Cross-plugin collisions auto-namespace `<plugin_id>__<name>`; **host-collision must still fail-closed-refuse**, including the **shadow-bypass** check (a plugin `tool_impl` must never shadow a host `local_tool` like sandboxed `read_file`; `loader.py:253-262`). Did the relaxation accidentally namespace a **host** collision (letting a plugin shadow `read_file` under a prefix that the dispatcher later strips)? Is namespacing **deterministic** (always-prefix, not collision-dependent) so a name does not change when a sibling is added? Trace whether the prefixed name is what the executor/gate actually dispatches (no bare-name leak).
2. **Atomic per-plugin merge preserved (ADR-029 D2 / R0-B Y4).** The loader merges per-plugin atomically — a failure at any stage discards the whole intermediate (host registries never half-mutated). Does the enabled-gate + namespacing keep this? Can a plugin that passes collision but fails version-coherence leave a partial `seen_*` / `merged` mutation? Trace the `seen_role_ids.update(...)` ordering vs the refuse points.
3. **The boot-only claim is real (DP2b).** ADR-038 D2 claims **zero runtime-mutation surface** — the lifecycle is registry-expressed + boot-evaluated, no live `AppContext` swap. Verify **nothing** mutates a running context: no endpoint writes a registry that takes live effect, no hot path re-runs `load_plugins`. Is the persistent `MCPSession` vs per-call `tool_impl` distinction respected (disable means not-started-at-boot, never mid-turn teardown)?
4. **Composition-root wiring fail-closed (the P4.3 RW4 analog).** `_build_context` now passes `config/plugins.yaml` + the `fetched_plugins/` root (today **both unpassed** — fetched is unreachable). Trace `_resolve_plugin_registry`: is the parse-fail→fail-closed branch driven by the **real** function (a wired-whole test, not a re-implemented branch — the RW8-2 lesson)? Does the disjoint-root guard (`loader.py:531`) still hold with the real `fetched_plugins/` path?
5. **Update / re-admit re-verifies.** "Update a fetched plugin" = new `version` + new `digest`, re-pinned by the operator. Confirm the digest floor (`fetch.py` digest-before-extract) **re-runs at boot** for the new bytes and the version-coherence check binds them — there is no "already fetched, skip re-verify" path that admits unverified new bytes.
6. **No silent partial-admit on registry edges.** An entry referencing a `plugin_id` with **no** matching discovered dir (typo / removed dir); a dir with **no** entry (operator-placed → presence default; fetched → refused); duplicate `plugin_id` entries; an entry with `enabled` of a non-bool type. Each must resolve to a **defined, fail-safe** outcome (refuse or documented default), never an exception that crashes bootstrap or a silent admit.

---

## NOT IN SCOPE to re-raise (architect-decided / constitutional — probe whether the DESIGN honors them, do not relitigate)

- **Config-file registry (not runtime store), boot-time-only (not hot)** — architect-ratified (DP1/DP2). Probe whether boot-only is *actually* enforced (no live mutation), not whether to use a store / hot-reload.
- **Operator-admit + pinned-digest floor; signature/keyring DEFERRED (not built)** — architect-ratified (DP3). Probe whether the floor is intact + the `RB-ADMIT` residual is honest, **not** whether to add signature now.
- **Per-call sandbox kept (ADR-037 D3); persistent sandboxed-plugin DEFERRED** — architect-ratified (DP4b). Probe per-call isolation is inherited, not whether to build a persistent model.
- **Namespacing `<plugin>__<id>` always-prefix; admission = operator-authored entry, NOT gated** — architect-ratified (DP4a/DP2c). Probe fail-safety + no-gate-bypass, not the choice.
- **Management endpoints contract-only (no impl this slice)** — architect-ratified (DP4c). Probe the contract is coherent + backend-authoritative, not whether to build the UI.
- **New ADR-038; no new `LLMPurpose`; gate-unchanged; provenance un-launderable; `_execute_local_call` byte-frozen** — constitutional. Probe whether the DESIGN honors them.
- The five plan §5 sub-decisions (preserve-presence / refuse-all-on-malformed / always-prefix / version-check / contract-only) are **architect-confirm** items — if you see a *correctness* problem with the drafted choice, raise it as a finding; do not relitigate the choice itself.

## Output

Land at `docs/process/reviews/P4.4/R0-B.md` with YAML frontmatter:

```
---
task_id: P4.4
round: R0-B-cross-family-external
reviewer_family: <deepseek | gpt-5 | gemini | other>
reviewer_model_id: <specific model>
reviews_acked:
  - architect-briefs/P4.4.md
  - senior-plans/P4.4.md
  - decisions/ADR-038-plugin-registry-lifecycle.md
verdict: <clean | needs_architect | blocking>
findings_count: { red: N, yellow: N, green: N }
---
```

Per finding: `file:line` (or `artifact §`), the failure mode **traced** (the concrete admission-bypass / forge / fail-open / lost-isolation, or the consistency/atomicity break), severity (🔴 must-fix / 🟡 should / 🟢 nit), and your confidence. **Route nothing yourself** — the architect routes (α absorb / β defer / γ reject / δ later). A **🔴 only** for a concretely-traced admission of code that should be refused, a provenance/posture forge, a silent fail-open (incl. re-enable-on-malformed), a pierced host-collision/shadow-bypass gauntlet, or a partial-admit atomicity break — not a hypothetical.

**Verdict semantics:**
- `clean` = 0🔴 / 0🟡 / any 🟢 → architect proceeds to Accept ADR-038 + junior dispatch.
- `needs_architect` = ≥1🟡 OR an issue needing routing → architect Decision blocks.
- `blocking` = ≥1🔴 (admission-bypass / provenance-forge / silent fail-open / pierced gauntlet) → plan + ADR-038 revised before junior dispatch.
