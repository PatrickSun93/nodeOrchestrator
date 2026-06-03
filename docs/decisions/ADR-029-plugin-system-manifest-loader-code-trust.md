# ADR-029: Plugin System — Manifest + Loader + Code-Trust/Isolation Model

**Status:** Proposed (senior-drafted; awaiting architect Accept — RC-23-safe, no literal accepted-status substring until the architect accepts). Dual-lens R0-B dispatched at plan stage (`requires_cross_family_review: true`, architect-ruled per brief §Decisions(e)).

**Scope:** P3.5 (P3 Wave-2 closer — the backend-track join) — a new `plugins/` package: a **plugin-manifest schema** (`plugin.yaml`) + a **plugin loader** that discovers / validates / registers a **distribution unit** bundling **roles + skills + tool-classifications + executable tool code + MCP-server config**, merging each contribution into the **existing** agents / skills / tools / local-tools / MCP registries **at the existing `_build_context` merge point, reusing the four existing per-surface loaders** (`load_agents`, `load_skills`, `load_tools_config`, `load_mcp_servers_config` + `build_mcp_tool_registry_and_sessions_from_config`). Governs: the manifest contract (D1), the loader/aggregation mechanism (D2), the constitutional spine carry-forward (D3), **the code-trust / isolation model for plugin-delivered executable tool code (D4 — the architect-ruled security crux; admit-code overrides the brief's declarations-only lean)**, the trust/consent posture (D5), the dependency + collision model (D6), and the demo plugin (D7). Does **NOT** govern: the autonomy gate decision logic (`score` / `decide_tier` / `emit_gate_decision` / `process_tool_calls` — **unchanged**, ADR-027 D2 / ADR-028 D6); the MCP client / transport / adapter (ADR-027); the runtime tool-executor dispatch (ADR-028 — **unchanged**; plugin tools execute through it via the `local_tools` registry, no executor edit); remote install / a plugin registry / fetch-from-network (deferred to P3.7); runtime plugin lifecycle (enable/disable/upgrade/uninstall — deferred); GUI plugin management (frontend track).

## Context

The four surfaces a plugin packages **already have loaders, and they already converge in one place** (verified `origin/main`):

- `api/app.py::_build_context` (lines 142–158) is the single bootstrap merge point. It builds, in order: `load_agents(config_dir/"agents", models=…) → (dict[str, Agent], regex_registry)`; `load_skills(config_dir/"skills") → dict[str, Skill]`; `load_tools_config(config_dir/"tools.yaml") → dict[str, ToolMeta]`; `build_mcp_tool_registry_and_sessions_from_config(config_dir/"mcp_servers.yaml") → (dict[str, ToolMeta], dict[str, MCPSession])` (merged into `tools`); `build_local_tool_registry(sandbox_root) → dict[str, LocalToolFn]` (`local_tools`). The `AppContext` carries `available_agents`, `available_skills`, `tools`, `mcp_sessions`, `local_tools`.
- **Two distinct tool registries** (verified): `tools: dict[str, ToolMeta]` is the **gate's classification registry** (flows `process_tool_calls → emit_gate_decision`); `local_tools: dict[str, LocalToolFn]` is the **executor's implementation registry** (`tools/executor.py::_execute_local_call` looks up `local_tools[name]` and calls `impl(params)`, wrapping every call fail-closed → `TOOL_FAILED`, ADR-028 D4). A tool needs a `ToolMeta` to be *gated* and a `LocalToolFn` (or an MCP session) to be *executed*.
- `ToolMeta{reversibility: int 0–10, default 0}` (frozen, `extra="forbid"`; `autonomy/scoring.py:36`); `score(op, tools)` raises `UnknownToolError` if the tool is not in `tools` (ADR-006 fail-closed). All four loaders' models are **frozen + `extra="forbid"`** (Agent, Skill, ToolMeta, MCPServersConfig — verified).
- `build_local_tool_registry(sandbox_root)` (`tools/local.py:131`) is **hard-coded** to three host builtins (`get_current_time`, `read_file`, `list_files` — in-process closures). **There is no mechanism today to load a third-party `LocalToolFn`.**
- ADR-027 **D5** pre-committed the MCP half: a plugin's `mcp_servers` block is the **same shape** as `config/mcp_servers.yaml`; the loader merges plugin-provided server configs into the registry **without re-architecting the client** ("P3.5 wraps; it doesn't reshape").

So a plugin loader is an **aggregation layer above the existing loaders**: discover plugin manifests → validate → feed the **same five registries** at `_build_context`. It builds **no** new agent/skill/tool/MCP machinery and **no** new decision surface — with **one** genuinely-new mechanism: loading a plugin's **executable tool code** into `local_tools` (there is no existing loader for that). That new mechanism is the **code-trust / isolation surface** this ADR's D4 designs — **the project's largest security surface to date** (third-party Python, *loaded = runs*).

## Hard requirements — the constitutional spine + trust boundary (NON-NEGOTIABLE; inscribed; carries ADR-005/006/027/028 forward — *not* new choices)

A plugin is **third-party** (roadmap §3(B)/§9). Per Principle 5 + roadmap §9 the ADR inscribes and the impl enforces:

1. **Plugin-delivered tools route through the existing CODE gate, unchanged.** A plugin tool contributes a `ToolMeta` into the **same** `tools: dict[str, ToolMeta]` that flows `_build_context → process_tool_calls → emit_gate_decision`. It gates **identically** to a local/MCP tool: classified → tier from reversibility (code); **unregistered/unclassified → `UnknownToolError` → refused** (ADR-006 fail-closed). **No second decision surface; the gate stays the sole chokepoint.**
2. **Plugin-delivered MCP servers route through the existing trust boundary (ADR-027 D4), unchanged.** A plugin's `mcp_servers` block is the ADR-027 D5 shape; the **same** allowlist + `api_key_env` credential-indirection + scoped-subprocess-env + result-size-limit + bounded-timeout + fail-closed posture applies. A plugin **cannot** deliver a server that bypasses the allowlist — its declared server *is* an allowlist entry, so **loading a plugin = opting into its servers** (D5).
3. **Plugin loading is deterministic CODE/config, never an LLM judgment.** Discovery + manifest-validation + registration is code (mirrors the four loaders). **No `LLMPurpose` decides whether to load a plugin, whether it validates, or what its contributions do** (D3 constitution test).
4. **A plugin introduces NO new routing/judgment `LLMPurpose` and NO routing decision.** Roles activate via code `should_agent_speak` (responses stay content-gen `AGENT_RESPONSE`); skills are content; tool-classifications gate; MCP config gates + allowlists. Model-selection stays the code router + the P2.7 Layer-4 override. No new purpose (roadmap §9).
5. **Fail-closed loading + execution.** A bad/unparseable manifest, an unknown schema-version, a missing declared dependency (a role's `model_id` absent from the host model registry; a required `room_type` absent), a tool with no usable classification, a server not matching the D4-validatable shape, **executable tool code that fails to import**, or a **name collision** → the plugin **fails to load (refused)** — never partially-registers, never silently degrades into a half-wired/unsafe state. At call time, a plugin tool that raises → `TOOL_FAILED` for that call only (per-call isolation, ADR-028 D4). *Bundling ≠ trust*: load only the valid, fully-satisfiable, classified bundle.

**Trust boundary (the P2.7-S3 → MCP pattern, now a *bundle*; inscribe).** One plugin can bundle MCP servers **and** tool-classifications **and** executable tool code **and** roles **and** skills at once — **loading one plugin = trusting the whole bundle.** The S3 / ADR-027-D4 posture carries forward and *composes*: **opt-in** (loaded only by explicit presence in `plugins/` — never auto-fetched), **manifest-validated** (schema + dependency + classification checks **before** any registration), **credential-safe** (servers reuse `api_key_env`; the manifest carries no plaintext secret), **fail-closed** (HR#5). The worst a malicious plugin's **declarations** do is bounded by the gate + allowlist it cannot bypass. **Its executable code is a different matter — see D4.**

## Decisions

### D1. The plugin package + manifest schema — `plugins/`, `plugin.yaml` (frozen, `extra="forbid"`, schema-versioned)

A new **`plugins/` package** (`src/orchestrator/plugins/`) + a **content directory** (`plugins/` at repo root, mirroring `config/`'s directory-discovery). Each plugin is a **subdirectory** with a `plugin.yaml` manifest + its content. The manifest is a frozen, `extra="forbid"` Pydantic model (`PluginManifest`), schema-versioned (an unknown `schema_version` → fail-closed refuse, HR#5):

```yaml
schema_version: 1                       # loader rejects an unknown version → fail-closed
id: demo                                # plugin identity (== subdir name; collision key)
name: "Demo bundle"
version: "0.1.0"
contributions:                          # all optional; a plugin declares only what it ships
  roles:        ["facilitator"]         # → config/agents/-shape YAML under plugins/<id>/agents/
  skills:       ["research-decomposition"]   # → config/skills/-shape MD under plugins/<id>/skills/
  tools:        ["echo"]                # tool-classifications (ToolMeta) under plugins/<id>/tools.yaml
  tool_impls:                           # EXECUTABLE tool code (admit-code, D4) — name → impl ref
    echo: "tools_impl:echo_tool"        # "<module>:<callable>" within plugins/<id>/
  mcp_servers:  ["filesystem"]          # ADR-027 D5 shape under plugins/<id>/mcp_servers.yaml
dependencies:                           # fail-closed if unmet (HR#5)
  model_ids:    ["claude_code_haiku_45"]   # a role's model_id must exist in the host model registry
  room_types:   ["free_chat"]              # a required room_type must exist
  min_host_contract: 1                     # minimum host plugin-contract version
```

The manifest **declares** contributions; the **content** lives in per-surface subpaths whose shapes are the existing loaders' inputs (so the loader **reuses**, not reimplements — D2). The schema is frozen + `extra="forbid"` + `schema_version`-gated (D6 / HR#5).

### D2. The loader = aggregation above the four loaders + the local-tool-impl loader; merge at `_build_context`

`plugins/loader.py::load_plugins(plugins_dir, *, models, host_room_types, sandbox_root) → PluginLoadResult` (a typed bundle of the merged contributions). It is an **aggregation layer**:

1. **Discover** — iterate `plugins/` subdirs; each with a `plugin.yaml` is a candidate. (Presence = opt-in, D5; no auto-fetch.)
2. **Validate** — parse + validate each manifest (frozen/`extra="forbid"`/`schema_version`); check declared **dependencies** against the host (`models`, `host_room_types`, contract version). A failure → that plugin is **refused, isolated** (logged + skipped; never crashes the bootstrap; never half-registers — HR#5).
3. **Load each surface by reusing the existing loaders, pointed at the plugin's subpaths**: `load_agents(plugin_dir/"agents", models=models)`; `load_skills(plugin_dir/"skills")`; `load_tools_config(plugin_dir/"tools.yaml")`; `load_mcp_servers_config` / `build_mcp_tool_registry_and_sessions_from_config(plugin_dir/"mcp_servers.yaml")`. The executable tool code (`tool_impls`) is loaded by the **new** D4 mechanism (no existing loader). **No loader is reimplemented or forked.**
4. **Collision-check + reversibility-cap + merge** (D5/D6) — collision-check every contributed name against the host registries and across plugins (fail-closed, D6); cap plugin-asserted reversibility (host-authoritative-or-default-0, D5); merge into the host registries.

**Merge points (verified, unchanged downstream):** plugin roles → the `agents` dict; skills → `skills`; tool-classifications + MCP `ToolMeta`s → the gate's `tools` dict; **executable tool impls → the executor's `local_tools` dict** (so `tools/executor.py::_execute_local_call` runs them via the existing path — **no executor edit**); MCP sessions → `mcp_sessions`. `_build_context` gains **one aggregation pass** after the four loaders; the gate, the executor, and the MCP client are **untouched** (the empty-gate-diff invariant, ADR-027 D2 / ADR-028 D6, holds — and extends to an empty-executor-diff invariant).

### D3. The constitutional spine — feed the existing surfaces unchanged (HR#1–4); the `plugins/` constitution test

`plugins/` makes **no** autonomy/routing/model decision. A constitution test (`tests/plugins/test_constitution.py`, the ADR-027 D2 / ADR-028 D6 analog) forbids `plugins/` referencing `decide_tier` / `emit_gate_decision` / `score` / `gate` / `select_model_and_provider`, forbids any `llm/` provider call, and asserts the frozen `LLMPurpose` set is unchanged (no new purpose, HR#4). Plugin loading is discovery + validation + registration — code, not judgment (HR#3). This ADR **binds** ADR-005/006 (gate + fail-closed), ADR-027 D2 (feed-the-gate-unchanged), ADR-028 D6 (the executor invariants) — it does **not** restate them.

### D4. ⭐ The code-trust / isolation model for plugin-delivered executable tool code — **the architect-ruled security crux**

**The architect ruled `admit-plugin-code-now`, overriding the brief's declarations-only lean (brief §Decisions(b)).** A plugin may carry **third-party executable tool code** (Python): a `tool_impls` entry binds a tool name to a `<module>:<callable>` within the plugin, which becomes a `LocalToolFn` in the executor's `local_tools` registry. This is *loaded = runs* — code executes both at **import time** (the module's top level runs when the loader imports it) and at **call time** (the executor calls `impl(params)` when the gate `AUTO_EXECUTE`s the tool). **This is the project's largest security surface to date** and is **explicitly recorded here as the admit-code override of the brief's declarations-only lean.**

The brief delegated the **isolation mechanism** to senior-design-and-surface-for-architect-Accept. Three postures (the architect's three named options), with their honest threat models:

- **Posture A — in-process import, operator-curation-IS-trust (the local-tools-today posture, one level up).** The loader `importlib`s the plugin's tool module and registers the declared callable as a `LocalToolFn`, running **in-process**, exactly like today's `build_local_tool_registry` builtins. Trust model: **the `plugins/` directory IS the operator's curation boundary** — placing a plugin there = the operator vetted and trusts it, *as trusted as the code in `src/orchestrator/tools/local.py`*. **Fail-closed-against-breakage is fully delivered**: a bad import / bad manifest → that plugin refused at load (per-plugin isolation, HR#5); a raise at call → `TOOL_FAILED` for that call (per-call isolation, ADR-028 D4). **Two honest, named limits** (stated, not implicit — the ADR-028 D3 discipline): **(L1)** a *malicious* in-process plugin is **NOT technically contained** — Python in-process has no privilege boundary; its import-time/call-time code runs with full host privilege (FS, network, env). Security rests **entirely on operator-curation**, not a runtime sandbox. **(L2)** in-process code **cannot be safely timeout-bounded or killed** (CPython has no safe thread-kill; `signal.alarm` is main-thread/Unix-only) — so a runaway/blocking plugin tool **relaxes the ADR-028 D5 single-writer liveness bound** (a subprocess can be killed on timeout; in-process code cannot). Note: the host's *own* local tools already run in-process unbounded (D5 bounds MCP via subprocess-kill; local tools are "fast + bounded by assumption"); Posture A does not change the *mechanism* — it widens *who writes the in-process code* (host → operator-curated-third-party).
- **Posture B — subprocess isolation (the ADR-027 MCP-server pattern, applied to plugin tool code).** Plugin tool code is **never imported in-process**; it runs as a **subprocess** with a **minimal scoped env** (ADR-027 D4 / the P2.7-S3 c2 env-leak lesson), **bounded-timeout + killable + fail-closed** → `TOOL_FAILED`. This delivers a **real technical boundary** against malicious code (L1) **and restores the D5 liveness bound** (L2) — both limits resolved. Cost: plugin tool code must speak a subprocess protocol, at which point a "plugin executable tool" ≈ a **bundled MCP server** — which the plugin's `mcp_servers` block (HR#2) **already supports**. So Posture B's marginal value over "bundle an MCP server" is thin; the *distinctive* value of admit-code (in-process convenience) is exactly what Posture B removes.
- **Posture C — in-process import isolation (RestrictedPython / audit hooks).** **Rejected as a live option** (recorded as a considered alternative): in-process Python restriction is **not a real security boundary** (well-documented escapes) — it gives a false sense of isolation (the worst of both: restriction complexity + no real guarantee).

**The single hinge question put to the architect (the Accept crux):** *Is an operator-placed local plugin a **TRUSTED tier** (like the host's own code) or an **UNTRUSTED third-party** (like an MCP server)?*
- If **TRUSTED** (operator-curation is the boundary) → **Posture A**: consistent with local tools; "no malicious escalation" is met by curation (malicious code never enters the curated dir); the D5 bound is relaxed to the same well-behaved-code assumption the host's own local tools already make. *A local plugin is exactly as trusted as adding a file under `src/orchestrator/tools/`.*
- If **UNTRUSTED** (third-party; *bundle ≠ trust*, the brief's framing) → **Posture B**: meets the brief's hard requirement *"malicious code cannot escalate beyond host"* with a **technical** boundary — at the cost that admit-code converges with bundle-an-MCP-server.

**The two readings of the brief's fail-closed requirement diverge here and the architect must rule.** "恶意代码不能越权 host" is satisfied by Posture A *only via curation* (a policy boundary) and by Posture B *technically* (a runtime boundary). **Senior lean: Posture A for the operator-curated local-dir MVP** — framed as *extending the operator-curated-local-code-is-trusted boundary from `src/` to `plugins/`* — **with L1 + L2 inscribed as named limits, fail-closed-against-breakage hard-required and demo-proven, and Posture B reserved as the required posture when provenance becomes untrusted (P3.7 remote install / registry — when a plugin is fetched, not operator-placed, curation no longer holds)**. This parallels ADR-027's "stdio local = most-trusted tier; remote deferred." The architect Accepts the posture (A, B, or A-now-B-later) knowing L1/L2.

### D5. The trust / consent posture (the knobs around the boundary; ADR-027 D4 carried forward — bind, not restate)

- **Consent / opt-in = presence.** A plugin's presence in the `plugins/` directory **is** the opt-in (the dir IS the host's curation, mirroring `config/`); loading a plugin = opting into its bundled servers + tool-classifications + (per D4) code. No separate per-plugin allowlist entry for the local-dir MVP (a discovered-but-not-activated registry is a P3.7 concern when provenance becomes untrusted). Per-surface guards (gate / allowlist) still apply unconditionally.
- **Plugin-asserted reversibility is advisory-capped → host-authoritative-or-default-0** (the ADR-027 HR#2 analog — a third-party self-claim is **never** authoritative for the tier). A plugin **cannot** claim `rev=10` on a write tool to dodge `HARD_CONFIRM`: the host may only *lower* trust (cap), never accept a raise; an unclassified/over-claimed plugin tool defaults to **reversibility 0** (conservative-low, ADR-005 D2). A test asserts a plugin-claimed high reversibility does not change the gate tier.
- **Credential + scoped-env** for plugin-delivered servers **reuse ADR-027 D4 verbatim** (`api_key_env`, minimal scoped subprocess env) — **bound, not restated**. The manifest carries no plaintext secret.

### D6. Dependency model + collision policy — fail-closed (HR#5)

- **Dependencies** (manifest `dependencies`): a role's `model_id`s must exist in the host model registry; required `room_type`s must exist; `min_host_contract` ≤ the host contract version. **Any unmet dependency → the plugin is refused** (fail-closed; never half-registers).
- **Collision policy = fail-closed on collision** (architect-ruled lean; loudest, safest for the MVP). Two plugins — or a plugin + core config — both defining a role `operator` / a tool name / a skill id / a server name → the colliding plugin **fails to load (refused)**. (Considered alternative: namespacing `<plugin>__<id>`, the MCP-namespacing analog — deferred; fail-closed is the MVP posture.) A test asserts a colliding plugin is refused and the host registry is unmodified.
- **Per-plugin load isolation:** one plugin's validation/collision/dependency/import failure refuses **only that plugin**; other valid plugins load (mirrors ADR-028 D4 per-call isolation, at load granularity).

### D7. The demo plugin — one bundle exercising all surfaces end-to-end (incl. admit-code)

ONE demo plugin (`plugins/demo/`, mirroring P3.4's one demo connector) bundling: a **reused role** (`facilitator`), a **reused skill** (`research-decomposition`), an **MCP-server config** (the ADR-027 filesystem demo), a **tool-classification**, **and one executable tool** (admit-code, D4 — a trivial *pure, no-I/O, deterministic* function, e.g. `echo`/`word_count`) — proving the loader merges **all five surfaces** and that the merged plugin tool **gates** (classified → tier), **executes** (via the existing executor), and **fails closed** (a deliberately-broken variant — import error / raise — refused/`TOOL_FAILED`, in tests). The demo proves the integration point's value *is* the bundle merging across every surface, including the new code surface.

## Considered alternatives

- **Declarations-only MVP (the brief's lean, b(i))** — **Overridden by the architect** (admit-code-now, D4). Recorded: declarations-only would have bounded the trust surface to "third-party config" with no code-execution/sandboxing surface; the architect ruled the executable-code surface in now.
- **Posture C (in-process import restriction)** — Rejected (D4): not a real security boundary in CPython; false isolation.
- **Namespace plugin contributions (`<plugin>__<id>`)** instead of fail-closed-on-collision — Deferred (D6): fail-closed is the loudest/safest MVP posture; namespacing is the considered relaxation (the MCP-namespacing analog) for a later multi-plugin slice.
- **A separate per-plugin host allowlist (discovered-but-activated-when-listed)** instead of presence=opt-in — Deferred (D5): presence=opt-in matches `config/` curation for the local-dir MVP; the discovered-but-not-activated registry is a P3.7 concern (untrusted provenance).
- **Reimplement per-surface loaders inside `plugins/`** — Rejected (D2): the four loaders are reused (pointed at plugin subpaths); reimplementing would fork the validated schemas + duplicate fail-closed logic.
- **Plugin-provided remote install / registry / fetch** — Deferred to P3.7 (the ADR-027 "defer remote transport" parallel; a network + untrusted-provenance surface that *changes the D4 posture* — see D4's Posture-B-reserved note).
- **Trust the plugin's asserted reversibility** — Rejected, constitutionally (D5 / ADR-027 HR#2): a third-party self-claim is never authoritative for the tier.

## Consequences

**Easier:** roles/skills/tools/MCP from a third-party bundle reach the running system through the **one** existing gate + the existing executor + the existing MCP trust boundary (no second decision surface; reuse the four loaders; the executor runs plugin tools unchanged via `local_tools`). The manifest is the inscribed distribution contract every future plugin (P3.7) binds.

**Harder:** the **executable-code surface (D4)** is the project's largest security surface — import-time + call-time third-party code, with the L1 (malicious-not-contained in-process) + L2 (D5-liveness-bound-relaxed in-process) limits that the architect's posture ruling resolves (A via curation-policy, B via subprocess-technical). A new aggregation layer + a frozen distribution contract + a fail-closed collision/dependency model to get right; the dual-lens R0-B evaluates the code-trust posture as a *named* boundary, not an accident.

**Neutral:** presence=opt-in matches `config/` curation; fail-closed-on-collision is the loudest MVP posture (namespacing additive later); the demo is one bundle. The gate / executor / MCP-client decision logic is untouched (ADR-027 D2 / ADR-028 D6 preserved; the empty-diff invariant extends to the executor).

## Reversibility

| Decision | 6-month reversal cost |
|---|---|
| D1 manifest schema + `plugins/` package | **Medium** — once P3.7 binds it the schema is a contract migration (inscribe-before-producer front-loads the cost). |
| D2 aggregation-above-the-four-loaders + merge-at-`_build_context` | **Low** — an additive bootstrap pass; reuses the loaders. |
| D3 constitutional spine + constitution test | **Do-not-reverse** — the gate-sole-surface / no-LLM-judgment / no-new-purpose carry-forward. |
| **D4 code-trust / isolation posture** | **A→B: Medium-High** — moving in-process (A) → subprocess (B) is a real execution-model change (the L1/L2 resolution); **A is the cheaper MVP, B the stronger boundary.** The *decision to admit code at all* is **Do-not-reverse** (the surface, once opened, is the security posture). |
| D5 presence=opt-in + advisory-cap + ADR-027-D4 reuse | **Medium** — presence→explicit-allowlist is a consent-granularity change (P3.7); the advisory-cap is constitutional (do-not-reverse). |
| D6 fail-closed dependency + collision | **Low** — relaxing to namespacing is additive; the fail-closed posture is the safe default. |
| D7 demo plugin | **Trivial** — content + tests. |

## References

- `docs/process/architect-briefs/P3.5.md` (the ⭐⭐ spine + ⭐ trust boundary + the 5 decisions; **architect ruled admit-code-now overriding the declarations-only lean** — D4).
- `docs/process/senior-plans/P3.5.md` (this ADR's plan; atomic graph, test plan, the D4 posture surfaced in §5).
- `docs/process/reviews/P3.5/external-r0b-prompt.md` (dual-lens R0-B — the third-party-code-execution / isolation / gate-unbypassed / allowlist / collision-fail-closed / load-fail-closed cross-family lens).
- `src/orchestrator/api/app.py::_build_context` (lines 142–158 — the four-loader merge point P3.5 wraps) + `agents/loader.py::load_agents` + `skills/loader.py::load_skills` + `llm/config_loader.py::load_tools_config` + `mcp/config.py::load_mcp_servers_config` / `mcp/adapter.py::build_mcp_tool_registry_and_sessions_from_config` (the loaders **reused**) + `tools/local.py::build_local_tool_registry` (the in-process local-tool pattern D4 extends) + `tools/executor.py::_execute_local_call` (the `local_tools` execution path — **unchanged**).
- `src/orchestrator/autonomy/scoring.py` (`score` / `decide_tier` / `ToolMeta` / `UnknownToolError` — the gate plugin tools feed) + `agents/tool_dispatch.py::process_tool_calls` (the gate path — **unchanged**).
- **ADR-027** (D4 trust boundary + D5 the config-as-plugin pre-commit — ADR-029 **binds both, does not restate**), **ADR-028** (D3 local-tool trust boundary + D4 per-call fail-closed + D5 single-writer liveness bound — D4's L2 / the executor path; **unchanged**), **ADR-005/006** (gate + fail-closed), **ADR-009** (skill frontmatter + loading), **ADR-024** (facilitator role shape), **ADR-002/023** (LLM routing = code + the Layer-4 override).
- `handoff.md` §3.3 ("Plugins: 分发单元,打包 skills + tools + MCP 配置 + roles"). `docs/process/dual-lens-r0b.md` (the (e) dispatch criteria). The P2.7-S3 alt-backend review (the trust-boundary + c2 env-leak pattern, now magnified to a bundle).
