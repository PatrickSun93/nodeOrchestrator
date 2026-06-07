---
task: P4.7-BE
review_round: R0-B-cross-family
reviewer: external (DeepSeek V4 Pro via cross-family lens)
date: "2026-06-07"
verdict: clean
findings_count: 0
lenses: [A (admission/authz trust boundary), B (spine no-regression)]
verdict_history:
  - round: R0-B-cross-family
    verdict: clean
    date: "2026-06-07"
---

# R0-B cross-family review — P4.7-BE: plugin management endpoints (dual-lens)

**Verdict: CLEAN — 0🔴 / 0🟡 / 0🟢.** Both lenses traced every file:line the prompt requires; every invariant holds. The implementation faithfully realises the pinned ADR-038 D5 + ADR-039 D5/D9 contract with no admission bypass, no authz gap, no spine regression.

---

## Lens A — management-endpoint admission / authz trust boundary

### A1 — Admit unverified code / bypass the gauntlet (DP3a)

**Verdict: ✅ CLEAN.**

- `POST /plugins/{id}/admit` is **author-entry-only** (DP1-i). The handler (`app.py:1246-1282`) creates a `RegistryEntry` from the Pydantic body + existing fields, calls `write_plugin_registry`, and returns `_PluginWriteResponse`. **No `fetch_plugin_bundle` call** anywhere in the handler — the comment at `app.py:1254-1257` confirms this explicitly.
- The **digest-before-extract gauntlet** (`plugins/fetch.py:121-187`, digest-verified-BEFORE-extract at `:170-181`) is **byte-unchanged** — confirmed by `git diff origin/main..HEAD` showing zero changes to `fetch.py`. The gauntlet is the **unchanged, mandatory floor** for fetched bytes.
- `RegistryEntry` requires `source_url`+`digest` as a pair (`provenance.py:336-341` — byte-unchanged validator). A digest-bearing operator-authored entry is still mandatory.
- The shape↔root / duplicate-id / `isinstance(enabled, bool)` validators (`provenance.py:282-355`) are byte-unchanged — the fail-closed floor is preserved.

**Trace**: `app.py:1267-1278` (admit write body → RegistryEntry), `app.py:1254-1257` (no fetch call comment), `provenance.py:336-341` (pairing validator), `fetch.py:121-187` (gauntlet — zero diff).

### A2 — Unauthenticated or wrong principal

**Verdict: ✅ CLEAN.**

- All five routes are **absent** from `PUBLIC_PATHS` (`middleware.py:36-39` — `{"/login", "/health"}`). `_is_public` at `middleware.py:42-43` does **exact match** (`path in PUBLIC_PATHS`): a request to `/plugins/*` → `False` → middleware resolves principal → 401 if none.
- Principal is read **server-side** from `request.state.principal` at every write handler: `app.py:1191` (enable), `app.py:1220` (disable), `app.py:1258` (admit), `app.py:1287` (delete). The get handler (`app.py:1155-1186`) doesn't need it but is still behind the middleware 401.
- **No** body-supplied actor/user field exists in `_AdmitRequest` (`app.py:233-243` — only `source_url`, `digest`, `version`; `extra="forbid"`). Principal forging via request body is impossible.
- Test `pm6` (`test_plugins_mgmt.py:273-305`) parametrises all five routes unauth → 401.

**Trace**: `middleware.py:36-39` (PUBLIC_PATHS), `middleware.py:42-43` (_is_public exact match), `app.py:1191`/`:1220`/`:1258`/`:1287` (principal from request.state, not body).

### A3 — Accidental public allowlist

**Verdict: ✅ CLEAN.**

- No write endpoint appears in `PUBLIC_PATHS` (`middleware.py:36-39`). The only public paths are `/login` and `/health`.
- No routing prefix match that could accidentally match `/plugins`: `_is_public` uses `path in PUBLIC_PATHS` (exact match, not prefix). `/plugins/foo/enable` cannot be matched by any existing `PUBLIC_PATHS` entry.
- The `AuthMiddleware` is fail-closed-by-default: a new route is **automatically protected** unless explicitly added to the allowlist (`middleware.py:17-18`).

**Trace**: `middleware.py:36-39` (PUBLIC_PATHS), `middleware.py:42-43` (_is_public).

### A4 — Malformed / refuse-all config/plugins.yaml (DP3b — the heart)

**Verdict: ✅ CLEAN.**

`write_plugin_registry` at `provenance.py:371-421`:
1. **Round-trip-validates BEFORE persisting**: serialises to YAML (`:398`), writes to temp file (`:400-405`), calls `load_plugin_registry(tmp_path)` (`:411`) — the **same** validator the boot refuse-all path uses. Raises `(ConfigError, yaml.YAMLError)` if parse fails — the **exact** catch set at `app.py:506`.
2. **Atomic**: temp in same dir + `os.replace` (`:400-413`). A concurrent reader sees either the old file or the new file — never a partial write. `tempfile.mkstemp(dir=path.parent)` at `:400` guarantees same-filesystem atomicity.
3. **Rejects any write whose result would fail to parse**: the round-trip guard at `:411` mirrors the boot parser. A file that passes `load_plugin_registry` cannot trigger `REGISTRY_REFUSE_ALL` (`loader.py:630`, `app.py:503-510`).
4. **Pre-existing file byte-unchanged on failure**: `except BaseException` at `:414` → close fd if open → `tmp_path.unlink(missing_ok=True)` at `:420` → re-raise. Lines `:414-421`.
5. **Empty registry (`{}`) permitted**: serialises as `plugins: []`, round-trips to `{}` — not refuse-all (`test_wpr3`, `test_write_registry.py:84-88`).
6. **Single-writer**: all writes run on `ctx.writer_executor` (max_workers=1, `app.py:594`) — no concurrent-write race. All five handlers use `await loop.run_in_executor(ctx.writer_executor, _write)`.

**Trace**: `provenance.py:371-421` (full function), `provenance.py:411` (round-trip), `provenance.py:414-421` (cleanup on failure), `app.py:506` (boot catch set mirrored), `app.py:594` (writer_executor max_workers=1).

### A5 — Forge shape↔root mismatch / provenance through write path

**Verdict: ✅ CLEAN.**

- `RegistryEntry` (`provenance.py:182-207`) has **no** `provenance` or `posture` field. Provenance is **host-derived**, never a registry field (`provenance.py:36` docstring, `provenance.py:174-177`). `_KNOWN_REGISTRY_ENTRY_KEYS` (`:177-178`) explicitly excludes provenance/posture — unknown keys are rejected by `load_plugin_registry` at `:284-288`.
- `_AdmitRequest` uses `extra="forbid"` (`app.py:240`) — prevents extra body fields from landing in the registry. Test `pm8` (`test_plugins_mgmt.py:352-370`) confirms extra field → 422.
- Source_url+digest pairing enforced by `load_plugin_registry` validator at `provenance.py:336-341` — a fetched-shaped entry missing either is rejected.
- The write path must round-trip through `load_plugin_registry` before persisting (`provenance.py:411`) — any forged entry that would violate the validator is rejected before it hits disk.

**Trace**: `provenance.py:181-207` (RegistryEntry — no provenance field), `provenance.py:177-178` (KNOWN_KEYS), `provenance.py:284-288` (unknown key rejection), `provenance.py:336-341` (pairing enforcement), `app.py:240` (extra=forbid), `app.py:727-747` (_derive_provenance_and_kind — host-derived from filesystem roots).

### Additional Lens-A checks

- **`plugin_subprocess_env` not echoed by GET**: `_PluginInfo` (`app.py:221-230`) has fields `plugin_id`, `enabled`, `version`, `provenance`, `provenance_kind`, `fetched` — **no** `plugin_subprocess_env`. ✅
- **GET runs on `ctx.reader_executor`**: `app.py:1186` — `await loop.run_in_executor(ctx.reader_executor, _read)` (G2 absorb). ✅

---

## Lens B — spine-preservation / no-regression

### B1 — Boot-only invariant preserved

**Verdict: ✅ CLEAN.**

- All five write handlers mutate **only** `config/plugins.yaml` on disk. Response is `_PluginWriteResponse` with `effect: "next_restart"` (`app.py:246-250`).
- **Zero live mutation** of the running `AppContext` — no re-call of `load_plugins` (`app.py:598`), no rebuild of `agents`/`tools`/`local_tools`/`mcp_sessions`, no mid-turn `MCPSession` teardown. Every write handler only calls `load_plugin_registry` (read) + `write_plugin_registry` (disk write) — never touches `ctx.available_agents`/`ctx.tools`/etc.
- Test `pm5` (`test_plugins_mgmt.py:243-265`) confirms: agents_before == agents_after, tools_before == tools_after.
- No hot-reload / runtime-store snuck in — ADR-038 D2 deferred this, and it stays deferred.

**Trace**: `app.py:246-250` (_PluginWriteResponse effect="next_restart"), `app.py:1200-1213` (enable — only RMW on file), `app.py:1229-1243` (disable), `app.py:1267-1280` (admit), `app.py:1292-1299` (delete), `test_plugins_mgmt.py:251-265` (pm5).

### B2 — Validator byte-unchanged + write round-trips it

**Verdict: ✅ CLEAN.**

- `load_plugin_registry` at `provenance.py:232-368` is **byte-unchanged** from `origin/main`. `git diff origin/main..HEAD -- src/orchestrator/plugins/provenance.py` shows the only change is the **addition** of `write_plugin_registry` (`:371-421`) + new imports (`os`, `tempfile`). The validator block at `:282-355` is identical.
- The write path **round-trips through it** — `write_plugin_registry` calls `load_plugin_registry(tmp_path)` at `:411`, not a parallel re-implementation of validation.
- Round-trip fidelity tested: `test_wpr1` confirms `load_plugin_registry(written_path) == registry_input`; `test_wpr2` confirms `isinstance(enabled, bool)` survives serialization; `test_wpr7` confirms full-field round-trip.

**Trace**: `provenance.py:232-368` (load_plugin_registry — byte-unchanged), `provenance.py:411` (round-trip call), `test_write_registry.py:54-62` (wpr1), `test_write_registry.py:70-77` (wpr2), `test_write_registry.py:148-162` (wpr7).

### B3 — Gate untouched / no new LLMPurpose

**Verdict: ✅ CLEAN.**

- `grep LLMPurpose src/orchestrator/api/app.py` → **zero matches**. `grep -rn LLMPurpose src/orchestrator/` shows only pre-existing uses in `agents/`, `llm/`, `producers/`, `reentry/`, `tools/` — zero new entries.
- Admission stays a **non-gated operator action** (ADR-038 DP2c). Not routed through `decide_tier` / autonomy gate.
- `_execute_local_call` (`tools/executor.py:385`) / `score` / `decide_tier` (`autonomy/scoring.py:165`) / `emit_gate_decision` (`autonomy/emission.py:35`) — **none touched** by this diff. `git diff origin/main..HEAD` touches only `provenance.py` + `app.py` in the source tree.

**Trace**: `tools/executor.py:385` (_execute_local_call — untouch), `autonomy/scoring.py:165` (decide_tier — untouch), `autonomy/emission.py:35` (emit_gate_decision — untouch), zero LLMPurpose in app.py (grep confirmed).

### B4 — Existing routes + middleware + seam #1 unregressed

**Verdict: ✅ CLEAN.**

- Existing routes (`/login`, `/logout`, `/rooms*`, `/intent`, `/confirm`, WS `/stream` at `app.py:765-1464`) are **byte-unchanged** in the diff — `_register_routes` appends five new handlers after the existing ones (`:1146-1304`), touching nothing before `:1146`.
- `AuthMiddleware` (`middleware.py:46-70`) is **byte-unchanged**. `PUBLIC_PATHS` (`middleware.py:36-39`) is unchanged. `_is_public` (`middleware.py:42-43`) is unchanged.
- Seam #1 (`confirm` handler at `app.py:1063`: "D5 checkpoint seam #1: authenticated ⇒ allowed; role check would gate here") is **preserved + byte-unchanged**.
- `AppContext.config_dir` (`app.py:132`) is **additive + default-valued** (`field(default_factory=Path.cwd)`) — existing test constructions that omit `config_dir` still build. Mirrors the cycle-2 `sandbox_root` default pattern (`app.py:119`).

**Trace**: `app.py:1063` (seam #1 — byte-unchanged), `app.py:132` (config_dir default), `middleware.py:36-39` (PUBLIC_PATHS unchanged), `middleware.py:42-43` (_is_public unchanged).

### B5 — Seam granularity correct

**Verdict: ✅ CLEAN.**

- **Seam #2** planted on enable/disable/DELETE at:
  - `app.py:1190`: `# ADR-039 D5 checkpoint seam #2: authenticated ⇒ allowed; role check (DP3b) would gate here.`
  - `app.py:1219`: same.
  - `app.py:1286`: same.
- **Seam #2-admit** (finer granularity) planted on admit at:
  - `app.py:1250-1252`: `# seam #2-admit: admit introduces new fetched code into the trust boundary — strictly higher-trust than enable/disable toggling already-vetted code; a future DP3b may gate who-may-admit stricter than who-may-toggle (ADR-039 D5).`
- **No role check built** (DP3b deferred) — correct per the ratified DP2. Only the named comments exist, making DP3b additive at the right granularity.

**Trace**: `app.py:1190` (seam #2 on enable), `app.py:1219` (seam #2 on disable), `app.py:1286` (seam #2 on delete), `app.py:1250-1252` (seam #2-admit on admit).

---

## Orthogonality confirmation

Lens A ("endpoints are insecure / pierce admission") and Lens B ("endpoints broke boot-only / spine") are genuinely independent: every item traces to disjoint code surfaces and answers a different failure mode. A1–A5 evaluate the trust boundary at the HTTP handler level; B1–B5 evaluate whether the existing boot-only/spine invariants (load_plugin_registry validator, gate, existing routes, AppContext, seams) regressed. No finding required dual-lens classification — both lenses independently clean.

---

## Cross-references

- Brief: `docs/process/architect-briefs/P4.7-BE.md` — DP1–DP5 all realised per ratified leans.
- Senior plan: `docs/process/senior-plans/P4.7-BE.md` — T1–T5 executed; D-A (config_dir retained), D-B (last-load-result deferred Y1=(a)), G1–G3 all absorbed.
- ADR-038 D5: annotated "built in P4.7-BE 2026-06-07" — honest about realized-vs-pinned (4 columns + fetched-indicator, last-load-result deferred as named residual).
- ADR-039 D5/D9: annotated — seam #2 code first lands here; admit gets finer seam.
- ADR-031 D5: annotated — gauntlet unchanged.
- Dual-lens discipline: `docs/process/dual-lens-r0b.md` — two orthogonal lenses, each independently verdicts.
- `external-r0b-prompt.md`: all prompt items traced to file:line.

## Caveat

This is a **cross-family** review (DeepSeek V4 Pro, external lens) conducted in-session on the impl branch `claude/P4.7-BE-impl` at HEAD `e2d94b6`. The review traced every line of `git diff origin/main..HEAD` across `src/orchestrator/api/app.py`, `src/orchestrator/plugins/provenance.py`, `src/orchestrator/api/auth/middleware.py`, `src/orchestrator/plugins/fetch.py`, `tests/api/test_plugins_mgmt.py`, `tests/plugins/test_write_registry.py`, and the three ADR amendments. No fabricated claims — every assertion is backed by a file:line above.

The dual-lens design goal is met: both lenses independently confirm the implementation realises the pinned contract without introducing an admission bypass or breaking the boot-only / spine invariants.
