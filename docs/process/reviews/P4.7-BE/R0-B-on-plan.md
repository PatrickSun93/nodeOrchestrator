---
task_id: P4.7-BE
round: R0-B-on-plan-cross-family-external
reviewer_family: deepseek
reviewer_model_id: deepseek-v4-pro
reviews_acked:
  - architect-briefs/P4.7-BE.md
  - senior-plans/P4.7-BE.md
  - decisions/ADR-038-plugin-registry-lifecycle.md
  - decisions/ADR-039-auth-identity-session.md
  - decisions/ADR-031-plugin-fetch-sandbox.md
  - decisions/ADR-029-plugin-discovery-loading.md
verdict: clean
findings_count: { red: 0, yellow: 0, green: 0 }
---

# R0-B-on-plan (cross-family external) — P4.7-BE plugin management endpoints

**Artifact bundle read:** brief (`docs/process/architect-briefs/P4.7-BE.md`), senior plan (`docs/process/senior-plans/P4.7-BE.md`), ADR-038 (D5), ADR-039 (D5/D9), ADR-031 (D5), ADR-029 (D2/D5), plus the full live substrate: `api/app.py`, `api/auth/middleware.py`, `plugins/provenance.py`, `plugins/fetch.py`, `plugins/loader.py`, `llm/purposes.py`. Traces cited as `file:line` or `artifact §`.

**Method.** Read the plan → read every live source file the plan references → verify each plan claim against the live bytes → apply both Lens A (admission/authz trust boundary) and Lens B (spine no-regression) against the plan design, tracing failure modes across module boundaries. Did not trust-the-types.

---

## Lens A — management-endpoint admission / authz trust boundary

### A1. Admit cannot bypass the gauntlet (DP3a) — ✅ CLEAN

- **Plan posture:** admit = author-entry-only (DP1-i). The plan T3 explicitly says: "No `fetch_plugin_bundle` call — fetch stays out-of-band (ADR-038 D2 fetch≠admit)."
- **Gauntlet untouched:** `fetch_plugin_bundle` at `fetch.py:121-187` with digest-before-extract ordering at `:170-181` is byte-unchanged. The digest verification step (`_compute_sha256` at `:175`, comparison at `:177-181`) still runs BEFORE extraction (`_detect_and_extract` at `:187`). The ordering IS the security property (ADR-031 D5).
- **Registry entry validated by the same parser:** the plan T1's `write_plugin_registry` round-trips the serialized YAML through `load_plugin_registry`'s validator (`provenance.py:282-355`), which enforces the source_url+digest pairing (`:334-339`) and rejects unknown keys (`:282-285`) including forged provenance/posture fields. A digest-bearing entry is structurally required for fetched plugins.
- **No synchronous fetch coupling:** the plan's admit handler writes the entry and returns `{"effect": "next_restart"}` — the gauntlet runs at the separate fetch step. The admission path and the integrity path are distinct (ADR-038 D2).
- **Residual honesty:** the plan's §6 residual `RB-ADMIT` explicitly documents: "admit-author-only → refused-at-boot-until-fetched — an admitted entry whose bytes aren't yet on disk is refused at next boot until the separate out-of-band fetch runs."
- **Admit body forge-guard:** the Pydantic model uses `extra="forbid"` (mirroring `_LoginRequest` at `app.py:166-171` and `_ConfirmRequest`). No body-supplied user/actor/provenance field can enter the registry through the endpoint.

**Verdict:** design holds. The endpoint writes operator intent; the gauntlet at `fetch.py:121-187` is the unchanged mandatory floor. No path to admit unverified code through an HTTP endpoint.

### A2. Auth boundary inherited (fail-closed-by-default) — ✅ CLEAN

- **No PUBLIC_PATHS exemption:** the plan T3 says all five routes are NOT added to `PUBLIC_PATHS`. `PUBLIC_PATHS` at `middleware.py:36-39` is `{"/login", "/health"}` — a frozenset, exact-match only. `/plugins`, `/plugins/{id}/enable`, etc. match no public prefix. The `AuthMiddleware` at `middleware.py:57-70` returns 401 before any handler logic for unauthenticated callers.
- **Principal server-derived, never body-read:** the plan T3 says: "Read the principal from `request.state.principal` (server-derived, never the request body — ADR-039 D7), mirroring seam #1 (`app.py:997`, `:1002`)." The existing seam #1 at `app.py:997` through `:1002-1005` reads `request.state.principal` — set by `AuthMiddleware.dispatch` at `middleware.py:69` AFTER session/token validation. The plan mirrors this pattern verbatim.
- **Admit body has no principal field:** `{source_url, digest, version}` with `extra="forbid"` — no `user_id`, `actor`, `principal`, or `approver` field to forge. The principal is the authenticated session holder, resolved by the middleware.
- **Enable/disable body-less:** no body at all on enable/disable endpoints — zero forge surface.

**Verdict:** design holds. The inscribe-before-producer win (ADR-039 D9 front-loaded the auth boundary) is correctly realized. No path for an unauthenticated or forged-principal caller to actuate any of the five endpoints.

### A3. No accidental public-allowlist landing — ✅ CLEAN

- **Fail-closed-by-default architecture:** `AuthMiddleware` (`middleware.py:46-70`) protects every route NOT in `PUBLIC_PATHS`. Adding a new route requires no opt-in — it's automatically protected unless explicitly exempted via the frozenset. The plan does not add any route to `PUBLIC_PATHS`.
- **No prefix-matching bypass:** `_is_public` at `middleware.py:42-43` uses exact `path in PUBLIC_PATHS` membership, not `startswith`. A path like `/plugins/enable` cannot match `/login` by prefix.
- **WS is not applicable:** the plugin endpoints are HTTP-only; no WebSocket upgrade path exists. The WS auth check at `app.py:1128-1196` is unchanged and irrelevant.

**Verdict:** design holds. No path for a write endpoint to land on the public allowlist accidentally.

### A4. write_plugin_registry: validate-before-persist + atomic + reject-refuse-all (DP3b — the heart) — ✅ CLEAN

- **Round-trip validation:** plan T1 serializes the mutated `PluginRegistry` to YAML, then round-trips it through the existing `load_plugin_registry` (`provenance.py:230-366`, validator at `:282-355`) BEFORE persisting. If `load_plugin_registry` raises `ConfigError`, the write is aborted.
- **REFUSE_ALL prevented:** the `REGISTRY_REFUSE_ALL` sentinel at `loader.py:630-639` is triggered ONLY by `ConfigError` or `YAMLError` from `load_plugin_registry` at `app.py:503-510`. A file that round-trips through `load_plugin_registry` cleanly CANNOT trigger the sentinel — the refuse-all gate and the round-trip gate are the SAME parser. This is the correct fail-closed design.
- **Atomic write:** temp file in same directory → `os.replace`. `os.replace` is atomic on POSIX filesystems. An interrupted write never leaves a partial `config/plugins.yaml`.
- **Byte-unchanged on rejection:** plan T1 acceptance criteria: "a deliberately malformed serializer path or a monkeypatched validator → the function raises, and the pre-existing `config/plugins.yaml` is byte-unchanged (no torn write, no temp left behind)."
- **Empty-registry permitted:** plan T1 says `{}` round-trips to `{}` — not the refuse-all sentinel. The validator at `provenance.py:269-271`: `entries_raw = raw.get("plugins"); if entries_raw is None: return {}`. Absent `plugins` key or empty list → empty dict. No ConfigError path from an empty registry. This is correct — an empty registry is "no declared plugins" (defaults), not "config is broken" (refuse-all).
- **Identity fidelity:** plan T1 acceptance: `load_plugin_registry(written_path) == registry_input`. The round-trip preserves `isinstance(enabled, bool)` through YAML serialization (YAML `true`/`false` → Python `True`/`False` → re-serialized as `true`/`false`). YAML string `"false"` (a common operator error) would be caught — `yaml.safe_load("false")` returns `False` (bool), but if the serializer somehow produced `"false"` (quoted string), the validator at `provenance.py:302-307` would catch it with `isinstance(enabled_raw, bool)` → False → `ConfigError`.
- **First-write path:** plan T1 says path absent → the function authors the file. `os.replace(temp, target)` where target doesn't exist atomically creates it.

**Verdict:** design holds. This is the heart of DP3b — the plan realizes it correctly. A malformed config that would trigger `REGISTRY_REFUSE_ALL` and disable every plugin at next boot cannot be produced by any endpoint write path.

### A5. Provenance unforgeable — ✅ CLEAN

- **Provenance is host-derived, never a registry field:** `_KNOWN_REGISTRY_ENTRY_KEYS` at `provenance.py:175-177` explicitly excludes `provenance` and `posture` — "Provenance is NEVER a registry field — it stays host-derived by root" (module docstring, `provenance.py:36`). Any write attempting to include a `provenance` key in a registry entry would fail the round-trip at `provenance.py:282-285` (unknown keys rejected).
- **GET derives provenance from disk:** plan T3 says GET checks which root dir contains the plugin id — `sandbox_root/plugins/<id>` → operator_placed, `sandbox_root/fetched_plugins/<id>` → fetched. The disjoint-root guard at `loader.py:579-600` prevents the same plugin from existing in both roots at bootstrap.
- **Shape↔root mismatch prevented:** the plan's write path round-trips through `load_plugin_registry`, which enforces the source_url+digest pairing (`provenance.py:334-339`). A half-entry (source_url without digest, or vice versa) is rejected by the validator. After the round-trip passes, the entry's shape is coherent.

**Verdict:** design holds. Provenance is structurally un-spoofable through the write path.

### A6. Single-writer discipline — ✅ CLEAN

- **Writes on `ctx.writer_executor`:** plan T3 says all writes follow read-modify-write on `ctx.writer_executor`. The executor at `app.py:552` has `max_workers=1` (single-threaded serialization). The existing `/intent` write path already uses this executor at `app.py:972`. The plugin write path reuses the same serialization guarantee.
- **No concurrent-write race:** with `max_workers=1`, only one write function runs at a time. The read → mutate → write sequence is effectively atomic with respect to other plugin writes. The `os.replace` further ensures filesystem-level atomicity against external reader processes (a reader sees either the old file or the new file, never a partial write).

**Verdict:** design holds.

### A7. `plugin_subprocess_env` not leaked — ✅ CLEAN

- **GET column list excludes env:** plan T3 says GET returns "plugin_id, enabled, version, provenance (derived read-only), fetched-indicator (has source_url/digest)." No `plugin_subprocess_env` in the response shape.
- **Plan explicitly calls out the restriction:** "`plugin_subprocess_env` values are not echoed (avoid surfacing operator-authored env wholesale; expose only key presence if needed)."

**Verdict:** design holds.

---

## Lens B — spine-preservation / no-regression

### B1. Boot-only invariant preserved — ✅ CLEAN

- **Zero live mutation of AppContext:** plan T3: "No live AppContext mutation (no re-call of `load_plugins`, no agents/tools/mcp_sessions rebuild — Lens B boot-only)." The writes mutate ONLY `config/plugins.yaml` on disk. The response signals `{"effect": "next_restart"}`.
- **config_dir additive-only:** plan T2 adds `config_dir: Path` to `AppContext` at `app.py:103-127` — a new field with a default value, following the existing `sandbox_root` default pattern (`field(default_factory=lambda: Path.cwd())` at `app.py:119`). Existing test constructions that omit `config_dir` still build with the default.
- **No hot-reload snuck in:** the plan explicitly says "zero new runtime-mutation surface" (ADR-038 D2). No `load_plugins` re-call, no `MCPSession` teardown, no `AppContext` rebuild. This is the ADR-038 D2 deferred posture (Considered-alternatives: "Runtime store (DP1a)" / "Hot-reload (DP2b)" — both deferred, not built).
- **config_dir not recoverable from sandbox_root:** verified — `sandbox_root = config_dir.parent` at `app.py:580`. The parent relationship is directional: parent → child, but `config_dir` cannot be derived from `sandbox_root` alone (no known child name). The plan's D-A discovery is correct: `config_dir` must be explicitly retained.

**Verdict:** design holds. No runtime mutation, no hot-reload, no ADR-038 deferral reversal.

### B2. Validator byte-unchanged + write round-trips it — ✅ CLEAN

- **`load_plugin_registry` untouched:** the plan T1 adds `write_plugin_registry` as a NEW function in `provenance.py`, sibling to `load_plugin_registry` at `:230`. The validator block at `provenance.py:282-355` (unknown key rejection, plugin_id validation, bool enforcement, source_url+digest pairing, env validation) is byte-unchanged.
- **Write round-trips through the existing parser:** plan T1 serializes → `load_plugin_registry(temp_file)` → if OK, `os.replace`. The validator is the single source of truth for both read and write paths — no parallel re-implementation of validation logic.
- **No write-path-specific validation:** the plan does not add a separate `_validate_registry_entry_for_write` function. All validation flows through the existing `load_plugin_registry` parser.

**Verdict:** design holds. The validator is the single-gate for both read and write paths.

### B3. Gate untouched / no new LLMPurpose — ✅ CLEAN

- **Admission stays a non-gated operator action:** ADR-038 DP2c: "Plugin admission is an operator action, not a gated agent op — it does NOT route through `decide_tier`/the autonomy gate." The plan does not add any gate call in the plugin endpoint handlers.
- **No new LLMPurpose:** grep across `src/` — `LLMPurpose` enum at `llm/purposes.py:25-91` has 9 values (AGENT_RESPONSE, SNAPSHOT_SEMANTIC, HYPOTHESIS_CANDIDATE, KEY_NODE_CANDIDATE, TOOL_OUTPUT_INTERPRET, TERM_DEFINITION_PROPOSAL, REENTRY_DIGEST_RENDER, ARCHIVE_SUMMARY_RENDER, HYPOTHESIS_TAG_PROPOSAL). The plugin endpoint handlers are pure file I/O — they make zero LLM calls and introduce zero new `LLMPurpose` values.
- **`_execute_local_call` / `score` / `decide_tier` / `emit_gate_decision` byte-frozen:** the plan does not touch `orchestrator/autonomy/`, `orchestrator/tools/executor.py`, or any gate-related module.
- **Plan forcing function §4:** "`grep LLMPurpose` post-impl — confirm zero new entries." Correctly placed.

**Verdict:** design holds. The gate surface is byte-frozen.

### B4. Existing routes + auth middleware + seam #1 unregressed — ✅ CLEAN

- **Routes additive only:** plan T3 registers new routes in `_register_routes` at `app.py:684-1310` alongside existing routes (`/login`·`/logout`·`/rooms*`·`/intent`·`/confirm`·`WS /stream` at `:699-1006`). No existing route handler is modified.
- **AuthMiddleware unchanged:** `_configure` at `app.py:1241-1254` registers `AuthMiddleware` once at construction time for both `create_app` and `_make_test_app`. No change to the middleware registration or the `AuthMiddleware` class.
- **Seam #1 untouched:** the existing seam #1 at `app.py:997` ("D5 checkpoint seam #1: authenticated ⇒ allowed; role check would gate here") is on the confirm handler — not modified by the plugin endpoints. The plugin endpoints mirror its pattern (read `request.state.principal`, plant seam comment, no role check).
- **config_dir default-valued:** the new `config_dir: Path` field on `AppContext` follows the cycle-2 default pattern (`sandbox_root` at `app.py:119`, `mcp_sessions` at `:117`, `local_tools` at `:118`). Existing test constructions that omit `config_dir` still build — the default `Path.cwd()` means `load_plugin_registry(cwd()/"plugins.yaml")` returns `{}` (absent → empty registry, safe).
- **`_build_context` already receives `config_dir`:** at `app.py:514`, `_build_context(config_dir, db_path)` accepts `config_dir: Path`. The plan T2 only needs to add it to the `AppContext(...)` construction at `:664-681` — a one-line additive change.

**Verdict:** design holds. No regression to existing routes, middleware, or seam #1.

### B5. Seam granularity correct — ✅ CLEAN

- **Seam #2 on enable/disable:** plan T3 plants: "ADR-039 D5 checkpoint seam #2: authenticated ⇒ allowed; role check (DP3b) would gate here." Matches ADR-039 D5's pinned seam #2 contract.
- **Finer admit seam:** plan T3 plants a SEPARATE comment on admit: "seam #2-admit: admit introduces new fetched code into the trust boundary — strictly higher-trust than enable/disable toggling already-vetted code; a future DP3b may gate who-may-admit stricter than who-may-toggle." This realizes the DP2 seam-granularity sub-decision (admit gets its own finer seam).
- **No role check built:** DP3b is deferred (ADR-039 D5/D10). Both seams are comments-only, marking where future gating would land. Correct per the ratified DP2 posture.

**Verdict:** design holds. Seams are planted at the correct granularity for future DP3b role checks.

### B6. Plan-codebase consistency (all plan claims verified against live bytes) — ✅ CLEAN

Each claim the plan makes about the existing codebase was verified:

| Plan claim | Live verification |
|---|---|
| Registry read-only, no `write_plugin_registry` | `provenance.py:230` — `load_plugin_registry` exists; no serialize/write function. ✅ |
| `config/plugins.yaml` does not exist | `ls config/plugins.yaml` → file not found. ✅ |
| `_plugin_registry` is a local, discarded after `load_plugins` | `app.py:596` — `_plugin_registry = _resolve_plugin_registry(config_dir)`; consumed at `:609`; never stored on `AppContext`. ✅ |
| `AppContext` has `sandbox_root` but no `config_dir` | `app.py:103-127` — `sandbox_root` at `:119`; no `config_dir`. ✅ |
| `sandbox_root = config_dir.parent` | `app.py:580`. ✅ |
| `PUBLIC_PATHS = {/login, /health}` | `middleware.py:36-39`. ✅ |
| Seam #1 at `app.py:997` | Verbatim: "D5 checkpoint seam #1: authenticated ⇒ allowed; role check would gate here." ✅ |
| `REGISTRY_REFUSE_ALL` at `loader.py:630` | `loader.py:630-639`. ✅ |
| `_resolve_plugin_registry` at `app.py:476-511` | Absent→empty, parseable→registry, malformed→sentinel. ✅ |
| `request.state.principal` server-derived | `/intent` at `app.py:843`, `/confirm` at `app.py:1002`. ✅ |

**Verdict:** all plan claims verified against the live codebase. The plan's pre-investigation discoveries (D-A, D-B) are accurate.

---

## Cross-cutting observations

### Plan push-back points (already surfaced — NOT R0-B findings)

The plan's §5 honestly surfaces three decision points for the architect. These are NOT findings — they are the plan doing its job of surfacing gaps:

1. **§5-P1 — `last-load result` column deferred.** ADR-038 D5 L103 pins `GET /plugins` returning "last-load result." The plan identifies (D-B) that there is no per-plugin load report retained at boot — `PluginLoadResult` (`loader.py:61-76`) carries only merged contributions. Faithfully reporting last-load-result requires either modifying `load_plugins` (the spine function) or deferring the column. The plan defers it as a named residual (§6). **Architect to rule: defer the column, or fund the additive load-report?**

2. **§5-P2 — GET file-vs-running divergence.** Under boot-only, after a write the `config/plugins.yaml` file (configured intent) diverges from the running plugin set (effective at next restart). GET reads the document and signals "effect next restart." The plan inscribes this as a residual (§6). **Architect to confirm the response signaling is explicit enough.**

3. **§5-P3 — enable/disable on registry-absent operator-placed plugin.** Presence=opt-in (ADR-029 D5) means an operator-placed plugin can load with no registry entry. `disable` on such a plugin authors a `{plugin_id, enabled: false}` entry; `enable` is a no-op-but-author. The writer's round-trip enforces validity. **Plan judges this settle-able in-plan; flag if you disagree.**

### Residual set faithfully inscribed

The plan's §6 inscribes all named residuals: `RB-AUTHZ`, `RB-ADMIT`, boot-only/no-live-management, `last-load result` deferred, config-mgmt E3 deferred, rate-limiting deferred, admit-author-only→refused-at-boot-until-fetched. None are softened. The discipline matches the brief's §6.

---

## Verdict

**`clean`** — 0🔴 / 0🟡 / 0🟢.

The plan faithfully realizes the pinned ADR-038 D5 + ADR-039 D9/D5 contracts at the plan level. All five Lens A invariants (admit-gauntlet-unchanged, auth-fail-closed, no-public-allowlist, validate-before-persist-refuse-all, provenance-unforgeable) and all six Lens B invariants (boot-only, validator-unchanged, gate-untouched, existing-routes-unregressed, seam-granularity-correct, plan-codebase-consistency) trace cleanly through the plan design against the live substrate.

The three push-back points in §5 are the plan honestly surfacing architect decisions, not gaps — they are properly routed for architect resolution. The plan's pre-investigation discoveries (D-A: discarded registry, D-B: no per-plugin load report) are verified accurate against the live codebase.

The dual lenses are genuinely orthogonal: Lens A found zero admission/authz trust-boundary issues; Lens B independently found zero spine-regression issues. Neither lens found a finding the other would have caught — confirming the orthogonal design.

**Routing:** architect routes (α/β/γ/δ). No re-routing performed by this review.
