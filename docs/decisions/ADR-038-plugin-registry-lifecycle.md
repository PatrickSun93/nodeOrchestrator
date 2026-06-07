# ADR-038: Plugin registry + lifecycle + admission/signature + namespacing — the *admission* half (config-file registry, boot-evaluated lifecycle, pinned-digest floor, deterministic namespacing, the management-endpoint forward-contract, residual inscription)

**Status:** Accepted (architect, 2026-06-05) — senior-drafted for P4.4 (Wave-2 trust-hardening middle slice); architect Accepted after plan-stage dual-lens cleared 0🔴 + all 9 🟡 absorbed + the five §5 sub-decisions confirmed (RC-3: senior did **not** self-accept). **Plan-stage dual-lens cleared with 0🔴** (R0-A-on-plan 0🔴5🟡4🟢 + R0-B-on-plan 0🔴5🟡1🟢, both `needs_architect`); the architect routed all **9 de-duplicated 🟡 as α-absorb** (no β/γ/δ) and confirmed the five §5 sub-decisions (option A / refuse-all-graceful / always-prefix / version-coherence-as-operator-check / endpoints-contract-only). The absorptions (A–I) are inscribed in D1/D2/D4 + Constitutional carry-forward below + `senior-plans/P4.4.md` (absorption-round table). **Mandatory dual-lens** (`requires_cross_family_review: true`, P4-roadmap §8): the impl-stage review is R0-A ∥ R0-B (cross-family) for A2/A3/A4 (heavy), single-lens for A5 (light); the external lens probes the **plugin-admission trust boundary** + the **registry/lifecycle state-machine correctness** (`reviews/P4.4/external-r0b-prompt.md`). Annotations to ADR-029 D5,D6 / ADR-031 D4,D5 are inscribed at impl (plan task P4.4-6), matching the eventual Accepted status (the ADR-037 / B3-B4-B5 precedent). All 5 decision-surface points (DP1–DP5) were architect-ratified along the **lean** lines (commit `e47a491`); §"Considered alternatives" records the forks the senior drafted a choice on (plan §5) for architect confirmation.

**Scope:** The **admission substrate** — how plugin code is **declared, enabled, version-managed, and admitted**, the orthogonal half to ADR-037's **execution** substrate. Inscribes: the **unified config-file registry** (one operator-authored YAML generalising today's fetched-only activation allowlist to cover operator-placed **and** fetched), the **registry-entry schema** (the inscribe-before-producer contract), the **boot-evaluated lifecycle** (install/fetch → admit → enable ⇄ disable → update → remove, effect at next restart, **zero new runtime-mutation surface**), the **admission/signature model** (keep the shipped operator-admit + pinned-digest floor; signature/keyring is an **additive, deferred** upgrade path), the **namespacing rule** (deterministic `<plugin_id>__<name>` for cross-plugin coexistence, host-collision stays fail-closed), the **P4.7 management-endpoint forward-contract** (pinned here, built in P4.7), and **P4.4's own honest residuals** (no author-identity/no-revocation; hot-reload; runtime-store; persistent sandboxed-plugin). Does **NOT** govern: the autonomy gate (admission is an **operator** action, not a gated **agent** op — ADR-029 D3 / HR#1, no new `LLMPurpose`); the per-call execution sandbox (ADR-037 D3, unchanged — per-call already gives inter-plugin isolation); provenance-by-origin (ADR-031 D3 un-launderable, **a registry entry never declares or forges provenance/posture**); the digest-before-extract fetch mechanism (ADR-031 D5, unchanged); **live/hot** management (deferred — boot-time-only this slice).

---

## Context

ADR-037 sandboxed what admitted plugin code can **do** (per-call container, deny-default net, killed-in-finally). It did **not** decide what gets **admitted**. That is P4.4. The admission surface today is deliberately minimal — ADR-029 and ADR-031 both scoped registry/lifecycle/signature **out**, to P4 (ADR-029 D5/D6 considered-alternatives; ADR-031 D4 Reversibility + D5 "deferred P4"). This ADR lands those deferrals.

**What exists today (verified `origin/main`):**

| Item | Today | The gap P4.4 closes |
|---|---|---|
| **A2 registry** | No registry object. Operator-placed = directory presence in `plugins/` (no entry). Fetched = the activation allowlist (`provenance.py::ActivationEntry{source_url,digest,plugin_subprocess_env}`) — a proto-registry for **fetched only**. The fetched path is **not even bootstrap-wired** (`app.py:255` calls `load_plugins` with no `fetched_plugins_dir`/`activation_registry_path`). | One declared registry covering both roots, carrying the **new** enabled-state, bootstrap-wired. |
| **A3 lifecycle** | None. Install = place dir / `fetch.py`; enable = presence; disable = delete; update = re-fetch. No toggle, no machine. `manifest.version` parsed but **never read**. | A boot-evaluated per-plugin lifecycle; `version` made load-bearing. |
| **A4 admission** | Operator-pinned source + sha256 digest-before-extract (`fetch.py`, TLS-only, traversal-guarded); the operator authors the entry = the trust anchor. No crypto signature/keyring. | Keep the floor; name signature as a deferred additive layer; inscribe the residual. |
| **A5 namespacing** | Fail-closed-on-collision (`loader.py::_collision_check`) refuses a second plugin re-declaring a name. | Auto-namespace `<plugin>__<id>` so contributions coexist. |

**The trust split P4.4 turns on:** P4.3 answered *"what can admitted code DO"* (container-bounded). P4.4 answers *"what gets admitted, and how is admission expressed and revised."* The sandbox lowers the cost of being **wrong** about admission — it does **not** lower the admission bar. "It's sandboxed" is **never** a reason to admit unverified code (DP3).

---

## ⭐⭐ Constitutional carry-forward (non-negotiable; inherited)

- **Trust boundary — opt-in, fail-closed, provenance-honest.** The registry/lifecycle **must not** become a path to admit code that skips activation + integrity. A fetched plugin still requires a digest-bearing operator-authored entry; a malformed registry **refuses**, never admits (fail-closed only as strong as its parser).
- **Provenance un-launderable (ADR-031 D3).** Provenance is host-set-by-which-root and **un-spoofable**. A registry entry carries enabled-state / admission-proof / version — it **never** declares provenance or posture; those stay derived. An entry whose admission-proof shape mismatches its plugin's root is **refused**.
- **Gate unchanged / no LLM-judgment (ADR-029 D3 / ADR-031 D7).** Admission/lifecycle is **deterministic operator config**, never an LLM decision. No new `LLMPurpose`. Plugin admission is an **operator** action, not a gated **agent** op (DP2c) — it does **not** route through the autonomy gate.
- **`_execute_local_call` + gate byte-frozen (empty-executor-diff + empty-gate-diff; ADR-029 D2 / ADR-031 HR#2 / ADR-037 D3 lineage, absorbed R0-A Y5).** P4.4 makes **zero** edits to `_execute_local_call` or the gate: namespacing rewrites dict **keys** only and both consumers are name-agnostic; the reversibility cap (`_apply_reversibility_cap`, host-authoritative-or-default-0) is untouched (enabling a plugin can never **lower** a tier). The invariant is **named + regression-tested** (P4.4-5 (10)), matching the lineage.
- **Inscribe-before-producer (roadmap §10; ADR-029-D1 manifest lesson).** The registry-entry schema + management-endpoint contract are expensive-to-change; pinned here **before** plugins + the P4.7 GUI bind them.
- **Honest-residual inscription (ADR-031 D1a discipline).** Accept the *real* post-P4.4 admission surface, never a softened one. The discipline that governed `RB-FS/NET` governs A4's residual.
- **Backend-authoritative (ADR-026 HR#2).** The registry is the source of truth; the P4.7 GUI sends intent, never decides. The management endpoints are a backend contract, not a decision surface.

---

## Decisions

### D1 — Unified config-file registry: one operator-authored YAML over both roots (A2)

The registry is **one operator-authored YAML** (`config/plugins.yaml`), boot-read like every other `config/` surface — generalising today's fetched-only activation allowlist to cover **operator-placed and fetched**. No runtime store; no mutable code-admission database (the heaviest option, deferred — see Considered alternatives). This **is** today's posture, generalised: the activation allowlist already proves the shape.

**Registry-entry schema (the inscribe-before-producer contract; `RegistryEntry`):** the YAML is a **list** of entries under a top-level key (matching today's `activations:` list shape, `provenance.py:91-99`) — **not** a `plugin_id`-keyed mapping. A mapping would let PyYAML **silently keep the last** value on a duplicate key (loss without warning); a list lets the validator **raise `ConfigError` on a duplicate `plugin_id`** when building the `dict[plugin_id, RegistryEntry]` (fail-closed; absorbed R0-B b6b).

| Field | Type | Both roots? | Meaning |
|---|---|---|---|
| `plugin_id` | str (non-empty) | yes | Identity = the plugin subdir name (matched to a discovered dir; ADR-029 id==dirname). Duplicate across entries → `ConfigError`. |
| `enabled` | bool, default **true** | yes | **The genuinely-new field.** `false` = declared-but-disabled (not loaded). Default-true = **consent-by-authoring** (DP2c). |
| `version` | str \| None | informational for operator-placed; **coherence-checked** for fetched | The operator-pinned admitted version (A3 makes `manifest.version` load-bearing — D2). |
| `source_url` | str | **fetched only** | The exact `https://` bundle URL (ADR-031 D4, unchanged). |
| `digest` | str (`sha256:…`) | **fetched only** | The pinned digest verified before extraction (ADR-031 D5, unchanged). |
| `plugin_subprocess_env` | dict[str,str] | **fetched only** | Operator-authored non-secret env for the Posture-B child (ADR-031 D4, unchanged). |

**Runtime type-validation is mandatory and fail-closed (absorbed R0-B b6a)** — a frozen dataclass's type hints are **not** enforced at runtime, so `load_plugin_registry` validates every field with the per-field `isinstance` discipline already at `provenance.py:100-129`: **`isinstance(enabled, bool)`** (without it, YAML `enabled: "false"` parses to a non-empty **string** — truthy — a **silent fail-open enable**; live-confirmed `isinstance("false", bool) is False`), **`version` is `str` or `None`**, and **unknown entry keys are rejected** (`extra="forbid"` equivalent). The registry is only as fail-closed as this validator (constitutional, below).

**Provenance is NOT a field.** The entry never declares `provenance` or `posture`; both stay host-derived (operator-placed ⇒ Posture A; fetched ⇒ Posture B; ADR-031 D3). An entry carrying `digest`/`source_url` is fetched-shape admission proof; an entry carrying neither is operator-placed-shape. A **shape↔root mismatch** (a digest-bearing entry for a `plugins/` plugin, or a bare entry for a `fetched_plugins/` plugin) is **refused** (fail-closed, loud) — the registry is only as fail-closed as its validator.

### D2 — Boot-evaluated lifecycle: registry-expressed state, no runtime transition engine (A3)

The per-plugin lifecycle — `fetched/placed → admitted → enabled ⇄ disabled → (update) → removed` — is **expressed in the registry and evaluated once at boot** (`load_plugins` in `_build_context`, `app.py:255`). There is **no runtime state-transition engine** and **no live mutation** of a running `AppContext`. Operations map to registry edits whose effect lands **at next restart**:

- **install / fetch** = place a dir in `plugins/` or fetch into `fetched_plugins/` (`fetch.py`, unchanged).
- **admit** = author the entry (fetched: with `source_url`+`digest`; operator-placed: presence already admits, entry optional — **presence=opt-in preserved**, ADR-029 D5 narrowed-not-reversed).
- **enable ⇄ disable** = `enabled: true/false`.
- **update** = re-admit a new version: change `version` + `digest` (+ re-fetch). **Byte-integrity is established once, at fetch** — `fetch.py` verifies the sha256 of the compressed bundle **before extraction** (the digest-before-extract *ordering* IS the property, ADR-031 D5); this runs in the explicit fetch action, **not** at boot, and there is **no boot-time re-hash** of the extracted directory (absorbed R0-A Y2 / R0-B b5 — the earlier "digest re-runs at boot" wording was an over-claim and is corrected here). A post-fetch tamper of the on-disk `fetched_plugins/` tree is **out of scope** — it requires host-FS write, which already compromises the operator trust-root (an attacker with that access could equally drop an operator-placed plugin needing no digest). **At boot**, for fetched, `registry.version` (if set) **must equal `manifest.version`** → mismatch refuses. **This version-coherence check is an operator-intent / update-consistency guard, NOT an integrity barrier** (absorbed R0-A Y2b / R0-B a2): `manifest.version` is **plugin-self-asserted** (an untrusted bundle can claim any version), so the check catches an operator pinning the **wrong version label for a digest**, not a malicious substitution — **the digest is the integrity anchor**. `version` absent → **no check** is therefore **fail-safe** (the digest still binds the bytes). This is the A3 use that makes `version` load-bearing.
- **remove** = delete the entry / dir.

**Why boot-only is the safe lean (the liveness argument):** the system already runs `_build_context` once (boot-immutable reality), and a plugin's bundled MCP server is a **persistent `MCPSession`** while its `tool_impls` run **per-call** (ADR-037 D3). Boot-only means **no mid-turn `MCPSession` teardown** and **no registry rebuild on a running single-writer** (`max_workers=1`, ADR-028 D5) — the entire liveness/consistency surface of hot-reload is avoided.

**Disable means `_load_plugin`-never-called, not built-then-dropped (absorbed R0-A Y1).** The `enabled: false` check **short-circuits in the `load_plugins` candidate loop, before `_load_plugin` is invoked** — because `_load_plugin` builds a plugin's bundled MCP server (a **live stdio subprocess**, `build_mcp_tool_registry_and_sessions_from_config`) *before* it returns. A "built-then-not-merged" placement would leak that subprocess for a disabled MCP-shipping plugin (`demo`→`demo_filesystem`, `insights`→`insights_db`). So disabled ⇒ no `_load_plugin` ⇒ **no MCP session, no subprocess, no non-code surface** constructed.

**Default-application semantics:** absent registry → today's shipped defaults (operator-placed by presence, fetched none); **malformed** registry → **load zero plugins** (refuse-all, loud — the P4.3 `_resolve_sandbox_posture` parse-fail→fail-closed precedent at registry granularity). The refuse-all is achieved **gracefully, not by crashing the app** (absorbed R0-B a3): `load_plugin_registry` raises `ConfigError` on malformed input; `_resolve_plugin_registry` (the composition-root helper) **catches it, logs a `WARNING`, and returns an empty registry** — the exact `_resolve_sandbox_posture` pattern (`app.py:192-196`); the exception never propagates uncaught through `_build_context` (`app.py:255`). **Admission carries no autonomy-gate step** (DP2c): authoring the entry is the operator's deliberate consent; a GUI confirm (P4.7) is a frontend concern over the same backend intent, not new backend trust.

### D3 — Admission/signature: keep the operator-admit + pinned-digest floor; signature is additive + deferred (A4) ⭐⭐ the load-bearing trust call

P4.4 **keeps exactly today's admission floor**: **(c) operator-admit** (the operator authors the entry — the operator **is** the trust root) **+ (b) pinned-digest** (`fetch.py` verifies the sha256 of the compressed bundle bytes **before** any extraction — cryptographic **integrity**). A **signature / keyring** model (a) — a signer signs the bundle, the operator pins a public key / trust-root, verify-on-admit — is **NOT** built in P4.4. It is named as an **additive, separately-justified upgrade path** (ADR-031 D4 Reversibility: "moving to a signature/keyring model is a consent-granularity change, P4").

**Rationale (architect-weight trust call, ratified):** (i) the shipped digest model already gives cryptographic **integrity**; A4's real *new* value would be **author-identity + update-trust**, which only matters once there is a multi-author *distribution* story (a registry/marketplace — explicitly still deferred); (ii) a keyring's trust collapses to **key management** (distribution / rotation / revocation / TOFU-on-first-key), a heavier and easier-to-get-wrong surface than a single operator vetting bundles currently needs; (iii) the P4.3 sandbox already bounds the blast radius of an admission mistake.

**The inscribed residual (in the `RB-FS/NET` voice — what A4 does NOT prove):**

> **`RB-ADMIT` (post-P4.4 admission residual, Accepted-honest, gated by operator authoring — not a live incident).** Operator-admit + pinned-digest proves **integrity** ("these are exactly the bytes the operator vetted") and **nothing about authorship or revocation.** There is **no author identity** (the digest binds bytes, not a signer), **no revocation** (a vetted-then-later-known-malicious bundle stays admitted until the operator removes the entry by hand), and **no update-trust** (every new version must be **re-pinned by hand** — a new digest the operator vets out-of-band; signed-updates-verify-without-re-pinning is exactly what signature would buy and is not bought here). Trust = "the operator vetted these exact bytes." This residual **persists past P4.4** until/unless the signature upgrade path (a) is justified by a third-party distribution story and separately Accepted.

### D4 — Namespacing: deterministic `<plugin_id>__<name>` for cross-plugin coexistence; host-collision stays fail-closed (A5)

Cross-plugin name collisions relax from **fail-closed-refuse** to **deterministic auto-namespacing**: every plugin contribution name (roles / skills / tools / tool_impls / mcp_servers) is merged as **`<plugin_id>__<name>`** (the MCP-namespacing analog), **always prefixed** (not only on collision) so a name is deterministic and does not change when a sibling is added. Two plugins both declaring `echo` now **coexist** as `pluginA__echo` + `pluginB__echo` (ADR-029 D6 considered-alternative, landed).

**What stays fail-closed (the gauntlet is NOT pierced):** (i) **host-collision** — a plugin name colliding with a **host** registry name is **still refused**, including the **shadow-bypass** check that a plugin `tool_impl` must never shadow a host `local_tool` (e.g. the sandboxed `read_file`; `loader.py:253-262`); (ii) **within-plugin duplicate** names still refused. Only the **cross-plugin** branch of `_collision_check` becomes namespacing.

**Order-of-operations (absorbed R0-A Y4 / R0-B b1 — architect-resolved):** the host-collision and within-plugin checks **evaluate the BARE declared name and REFUSE** *before* any prefixing; namespacing applies **only** to the cross-plugin merge. A plugin declaring `tool_impl: read_file` is **refused loudly** (it shadows the host sandboxed `read_file`) — **not** silently coexisted as `plugin__read_file`. The architect ratified this **conservative bare-name refusal** over the prefix-first "always-prefix makes shadowing structurally impossible, so allow" reading (R0-B b1): a plugin shadowing a host name is an **operator authoring error** that should surface as a loud refusal to rename, not be silently absorbed under a prefix. (The accepted cost: a plugin may not *reuse* a host tool's bare name even though prefixing would have de-conflicted it — a deliberate, fail-safe conservatism.)

**Inscribed ripple — gate-tier re-binding (fail-safe) + UX, NOT "UX-only" (absorbed R0-A Y3):** always-prefix changes the tool **names agents see** AND **orphans host-pre-classifications** in `config/tools.yaml`. `word_count` (`config/tools.yaml:53`, rev-10→AUTO — the `demo` plugin's host-pre-classify path) becomes `demo__word_count`; the bare classification is orphaned and the documented **AUTO_EXECUTE path silently downgrades to default-0 → HARD_CONFIRM**. Same for `context_summary` (`config/tools.yaml:57`, rev-10 — the `context` plugin's path) → `context__context_summary`. The fail **direction is safe** (orphan → more gating, never less) — not a trust finding — but a real functional regression: the P4.4-3 promotion-impact grep MUST re-bind these `config/tools.yaml` classifications, and assert each demo's documented gate path still resolves (host-classified `demo__word_count` → AUTO; plugin-classified `demo__text_stats` → HARD).

**Deferred residual — role/skill identity-level namespacing (inscribed, P4.4 MVP boundary; α-absorb+inscribe from R0-A Y1/plan-vs-impl F1):** the P4.4 implementation uses `<plugin_id>__<name>` as the **dict key** for cross-plugin agent/skill coexistence, which is sufficient to prevent dict-key clobbering. It does **not** rewrite `Agent.id` / `Skill.id` themselves, nor update `applies_to` patterns or `regex_registry` cross-references to carry the namespaced identity — that is identity-level namespacing, the deferred work. Consequence: two plugins that declare agents/skills with the **same bare id** (e.g. both have a role `summariser`) will not dict-clobber (keys become `pluginA__summariser` + `pluginB__summariser`) but their `agent.id` fields remain `"summariser"`, and any `applies_to` regex or `regex_registry` entry keyed by that bare id will match both, creating a cross-plugin routing collision. **Current real-world impact is zero** — all shipping plugin ids are globally unique so bare-id collision across plugins does not occur in any known config. **This residual persists past P4.4** and becomes load-bearing only when two plugins with the same internal role/skill id are deployed together. Full identity-level namespacing (rewriting `Agent.id`, `Skill.id`, `applies_to`, and `regex_registry` keys to `<plugin_id>__<id>`) is the deferred upgrade path; it was deliberately not built in P4.4 because it requires coordinated changes to the dispatch/speaking subsystems (ADR-029 D5 downstream) and no current operator need justifies the risk.

### D5 — The P4.7 management-endpoint forward-contract (pinned here, built in P4.7) + residual set

**Management-endpoint contract (backend-authoritative, ADR-026 HR#2 — pinned, NOT implemented in P4.4):** the GUI-facing surface E2 (plugin-management UI, roadmap §E2) binds in P4.7 is a **read + intent** contract over the registry; every write **edits `config/plugins.yaml`** and takes effect **at next restart** (boot-only, D2):

| Endpoint | Semantics |
|---|---|
| `GET /plugins` | List declared plugins + resolved state (id, provenance [derived], enabled, version, last-load result). Read-only. |
| `POST /plugins/{id}/enable` · `/disable` | Set `enabled` in the registry. Effect next restart. |
| `POST /plugins/{id}/admit` | Author/replace a fetched entry (source_url + digest + version). Effect next restart. |
| `DELETE /plugins/{id}` | Remove the entry (and/or signal dir removal). Effect next restart. |

The config UI **sends intent, never decides** (ADR-026 HR#2). No UI and no endpoint code ship in P4.4 (frontend track).

**[Annotated P4.5 → ADR-039, Accepted 2026-06-06: the authz dimension of this forward-contract is now pinned. These management endpoints are **operator actions requiring an authenticated principal** (ADR-039 D9 / D5): any authenticated user under DP3a (all-or-nothing operator); the D5 checkpoint seam #2 is where a role check (DP3b) would later gate. No endpoint code is built in P4.5 — P4.7 builds against an authz-aware contract rather than inheriting an authz-blind one (inscribe-before-producer). The no-RBAC residual (`RB-AUTHZ`) is inscribed in ADR-039 D10.]**

**Residuals P4.4 leaves (inscribe, don't soften — roadmap §10):**

- **`RB-ADMIT`** (D3) — no author-identity / no-revocation / no-update-trust; persists past P4.4 unless signature is separately justified.
- **Hot-reload deferred** — lifecycle is boot-only (D2); live enable/disable/update lands on restart. The runtime-mutation surface (single-writer consistency, mid-turn `MCPSession` teardown) is **named and not built**.
- **Runtime-store deferred** — the registry is a config file (D1); a mutable backend-owned store (the GUI-driven live-management substrate) is the additive step, not built.
- **Persistent sandboxed-plugin process deferred** (DP4b forward-watch) — per-call stays (ADR-037 D3, unchanged); a long-lived warm in-sandbox process (e.g. an in-sandbox stdio MCP server) would reverse/extend ADR-037 D3 with its own cross-call state-leak surface — **not** in P4.4.
- **Registry only as fail-closed as its parser** (D1/D2) — a malformed/over-broad entry refuses, never admits; the malformed-registry→refuse-all posture is the registry-granularity ADR-031-D4 discipline.

---

## Considered alternatives

- **Runtime store (sqlite/event-store) instead of a config file (DP1a)** — Rejected for the MVP: enables GUI-driven **live** enable/disable but introduces a runtime-mutation path on the largest trust boundary + a registry-rebuild-on-running-system liveness problem (DP2). Reserved as the additive step if live management is ruled in (deferred to P4.7).
- **Hot-reload instead of boot-only (DP2b)** — Rejected for the MVP: true live management but mutating `agents/tools/local_tools/mcp_sessions` under the `max_workers=1` writer with in-flight rooms + tearing down a persistent plugin `MCPSession` mid-turn is a real liveness/consistency surface (ADR-028 D5 territory). Named residual.
- **Signature/keyring as the default admission model (DP3, the architect-weight fork)** — Rejected as default: keyring trust collapses to key management (heavier than the single-operator-vetting threat needs); integrity is already shipped via digest; author-identity only matters with a multi-author distribution story (deferred). **Legitimate to revisit** if a near-term third-party distribution story is the goal — an additive, separately-Accepted layer (D3).
- **Uniform require-entry for both roots instead of preserving operator-placed presence=opt-in (plan §5 #1)** — the senior drafted **preserve presence=opt-in** (entry optional for operator-placed, defaults enabled): it does not reverse the shipped ADR-029 D5 posture and needs no migration. Uniform-require would give one mental model but **reverses D5** + forces every operator-placed plugin to gain an entry. **Architect confirms** the preserve-presence reading at Accept.
- **Namespace-only-on-collision instead of always-prefix (plan §5 #3)** — the senior drafted **always-prefix** (deterministic; matches `<plugin>__<id>` + the MCP analog). On-collision would keep backward-compatible bare names but makes a tool's name depend on whether a sibling collides (non-deterministic). **Architect confirms** always-prefix + the bare-name ripple at Accept.

---

## Consequences

**Easier.** One declared registry over both roots; the fetched path finally bootstrap-wired (it is unreachable today); a real enable/disable toggle (config-edit + restart); `version` becomes load-bearing for the update model; multi-plugin coexistence (namespacing) instead of fail-closed refusal; the P4.7 GUI plans against a pinned backend contract rather than discovering it.

**Harder.** A malformed `config/plugins.yaml` refuses **all** plugins (strict fail-closed — operationally brittle, loud); namespacing ripples into any config binding bare plugin tool names (one-time migration); admission gains no new cryptographic strength over today (the integrity floor is unchanged — `RB-ADMIT` persists); live management is **not** available (boot-only — the GUI shows intent that lands on restart).

**Neutral.** Provenance/posture remain host-derived and un-spoofable (a registry entry cannot forge them); the per-call execution sandbox is unchanged (ADR-037 D3); admission stays a deterministic operator action outside the autonomy gate (no new `LLMPurpose`); the digest-before-extract fetch mechanism is unchanged (ADR-031 D5).

## Reversibility

| Decision | Reverse cost | Forward-watch |
|---|---|---|
| **D1 config-file registry** | **Medium** — moving to a runtime store is additive (config seeds, overlay carries live state); the entry schema is the expensive-to-change part (every producer binds it) → pinned now. | A mutable runtime store if live management is ruled in (P4.7). |
| **D2 boot-only lifecycle** | **Low-Medium** — hot-reload is additive over boot-only; do-not-reverse is the registry-is-source-of-truth direction. | Hot-reload + the single-writer consistency surface. |
| **D3 pinned-digest floor / no signature** | **Medium** — adding signature is a consent-granularity change (ADR-031 D4); the digest floor + operator-admit do-not-reverse. | A third-party distribution story → signature/keyring (separately Accepted). |
| **D4 namespacing** | **Low** — namespacing is the relaxation; reverting to fail-closed-on-collision is mechanical but breaks coexistence. Host-collision fail-closed is do-not-reverse. | The bare-name→namespaced config ripple. |
| **D5 endpoint contract** | **Low** (contract only) — the shapes are pinned; P4.7 implements. | E2 plugin-management UI binds it. |

## References

- **Ledger sources:** ADR-029 **D5** (presence=opt-in / per-plugin-allowlist considered-alt) + **D6** (collision / namespacing `<plugin>__<id>` considered-alt) + **D1** (manifest schema, the inscribe-before-producer lesson) + **D2** (loader step-order / atomic-merge) + **D4** (operator-curation = trust); ADR-031 **D1a** (`RB-FS/NET` honest-residual discipline) + **D3** (provenance-by-origin / disjoint-roots / un-launderable) + **D4** (activation entry / signature considered-alt + Reversibility) + **D5** (registry/marketplace/upgrade/version-coexistence/uninstall deferred-P4, + digest-before-extract fetch).
- **The substrate this declares over:** `plugins/provenance.py` (`ActivationEntry` + `load_activation_registry` — the proto-registry), `plugins/loader.py` (`load_plugins` boot-merge + `_collision_check`), `plugins/schema.py` (`PluginManifest.version`/`id` — made load-bearing), `plugins/fetch.py` (digest-before-extract admit floor, unchanged), `plugins/code.py` (`_PostureBFn` per-call container), `api/app.py:255` (boot-time `load_plugins`, fetched path un-wired).
- **The execution sandbox underneath (P4.3):** ADR-037 D3 (per-call container; executor byte-frozen — inter-plugin isolation for free).
- **Backend-authoritative:** ADR-026 HR#2 (view+intent; API the sole boundary).
- **Roadmap:** P4-roadmap §3-A (A2/A3/A4/A5 ledger), §4 (`P4.3 → P4.4` Wave-2), §8 (dual-lens A2/A3/A4, single-lens A5), §10 (inscribe-before-producer + watch-list).
- **Process:** `docs/process/architect-briefs/P4.4.md` (decision-surface); `reviews/P4.4/external-r0b-prompt.md` (dual-lens prompt); `docs/process/dual-lens-r0b.md`.
