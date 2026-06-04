---
task_id: P3.7-remote
round: R0-B-cross-family
reviewer_family: deepseek
reviews_acked:
  - architect-briefs/P3.7-remote.md
  - senior-plans/P3.7-remote.md
  - decisions/ADR-031-posture-b-executor-remote-plugin-provenance.md
  - decisions/ADR-032-remote-mcp-transport.md
  - origin/claude/P3.7-remote-impl (9 atomics, a49e86f)
verdict: clean
verdict_history:
  - blocking
  - [2026-06-04, clean, "Architect routed R1+R2 🔴 + 7🟡 → all α (R1/R2 = honesty/claim-narrowings the mechanisms already supported, not redesigns; 7🟡 = contract tightenings incl. Y1-watchdog + Y6-cap which the architect overrode from partner-β to α). Senior absorbed into ADR-031 (D1/D1a/D2/D3/D4/D5/D6) + ADR-032 (D2/D5) + plan -2/-4/-5/-6/-7/-8/-9. See architect-routing-on-plan.md."]
  - [2026-06-04, needs_architect, "Impl-stage dual-lens R0-B: all 2🔴 + 7🟡 plan-stage findings verified resolved in code. 1 new 🟡 I1: ADR-031 D3 text-vs-code — in-process Posture-A importlib path removed entirely, all plugins forced Posture B via _PostureBFn closures; _PostureBFn constructs MCPServerConfig with api_key_env never set (always None) so build_scoped_env never injects a secret into the plugin child — the env boundary is structural, not just test-enforced. 7 🟢 confirmations (kill-watchdog, harness-env, loader interface, verify=False test, digest-before-extract, per-turn cap, staging cleanup). No new 🔴."]
  - [2026-06-04, clean, "Architect routed I1 → α absorb via orchestrator (architect-routing-on-impl.md). NOTE: I1's premise (Posture-A path removed / B-for-all) was REVERSED by the architect's Y1 restore-per-contract ruling — junior fix1 0563034 restored dual posture (operator-placed → in-process Posture A; fetched → subprocess Posture B), so the in-process path now physically exists exactly as ADR-031 D3 inscribes (I1's ADR-vs-code gap is closed by restoring code to the contract, not by amending the ADR). I1's 3 structural guarantees (import boundary, api_key_env/env boundary, anti-laundering) documented in code by junior fix3 8353d85; the env boundary is now fetched-only (operator-placed Posture A runs in-process). Senior re-verified all 4 canonical gates green + fetched test-enforced-unreachable. See architect-routing-on-impl.md."]
findings_count:
  red: 0
  yellow: 1
  green: 7
note: >-
  Impl-stage dual-lens R0-B (cross-family, DeepSeek) on P3.7-remote impl @ a49e86f.
  Plan-stage: 2🔴 + 7🟡 + 4🟢 (all α-absorbed, verdict bumped to clean).
  Impl-stage: 0🔴 + 1🟡 + 7🟢 (all plan-stage findings verified resolved; 1 ADR-text-vs-code doc gap I1:
  _PostureBFn constructs MCPServerConfig with api_key_env never set, so build_scoped_env
  is always None for the plugin child — the env boundary is structural, not just test-enforced).
  Cross-family lens: adversarial trace of env-leak, subprocess-escape, digest-before-extract,
  verify=False, provenance-laundering, empty-diff invariants.
---

# P3.7-remote R0-B cross-family review (plan-stage, dual-lens)

## Lens preamble

This review applies the cross-family lens per `dual-lens-r0b.md`: over-correct for Claude's structural biases — under-weighted runtime concerns, over-confidence in spec-level consistency, missing failure-mode questions. The probes match the external-r0b-prompt.md directive: malicious-fetched-code escape, TLS bypass, provenance spoofing, env-leak, fail-closed gaps, autonomy-bypass.

**What this lens catches that in-family passes under-probe**: the distance between what the ADR *claims* and what the mechanism *delivers* when traced through live source. The P1.4 cross-family precedent caught `event_store.append` failure paths and all-agents-fail caller contracts — runtime-integration errors invisible to spec-level review. This slice is structurally the same class (new trust boundary at runtime), scaled to the project's largest surface.

**Live source verified** (`origin/main` @ cbadf6d): `plugins/code.py:42-104` (Posture-A in-process importlib), `plugins/loader.py:85-172` (discovery/validate, no provenance concept), `tools/executor.py:297-347` (`_execute_local_call` — mechanism-agnostic, confirmed), `mcp/transport.py:58-162` (`_build_scoped_env` + sync bridge + kill-no-orphan via SDK), `mcp/config.py:43-60` (`MCPServerConfig` — stdio-shaped, transport="stdio"), `mcp/adapter.py` (allowlist + namespacing, transport-agnostic), `mcp/execution.py` (size-limit + fail-closed, transport-agnostic), `plugins/schema.py` (no provenance field), `tests/plugins/test_constitution.py` + `tests/mcp/test_constitution.py` (AST-scan pattern).

---

## Findings

### 🔴 Red — design-breaking

**R1 — Posture B subprocess isolation does NOT include filesystem or network restrictions (L1 only partially resolved)**

- **Location**: ADR-031 D1, HR#5; plan P3.7-remote-5 §acceptance; brief §⭐⭐ spine #5
- **What**: The ADR and plan claim Posture B delivers "a real technical boundary against malicious code (L1)" and "L1 (privilege/env) is resolved." Traced against the live mechanism: `_build_scoped_env` at `mcp/transport.py:58-73` scopes only `os.environ` (9 safe keys + explicit additions). The subprocess runs with the same UID as the orchestrator — it retains full filesystem access (`open()`, `os.access()`) to every file the orchestrator user can read (`.env`, SSH keys, `config/*.yaml`, any credential file on disk) and full outbound network access (`socket()` — exfiltrate data). The env boundary is real; the filesystem/network boundary is **non-existent**.
- **Why it matters**: A malicious fetched plugin can read `~/.ssh/id_rsa`, `config/mcp_servers.yaml` (with inline secrets if any), `.env` files, and exfiltrate via `requests.post` or raw sockets. The c2 env-leak precedent (P2.7-S3) caught env inheritance — that specific leak IS resolved. But the *new* attack surface (FS read + network exfiltrate by untrusted fetched code) is unaddressed, and the ADR's "L1 RESOLVED" claim creates a false sense of security. ADR-029 D4 L1 was explicitly defined as "FS, network, and full os.environ" — only the last is resolved.
- **Suggested investigation**: Either (a) inscribe the remaining FS/network exposure as an Accepted risk (like L1/L1b/L2 were inscribed for Posture A in ADR-029 D4), with explicit language that Posture B resolves *env only* and FS/network remain at the operator's risk; or (b) add FS/network isolation (separate UID, container, seccomp, or chroot); or (c) narrow all "L1 RESOLVED" / "real isolation boundary" claims to specify "env-scoped isolation, FS/network not isolated."
- **Architect-partner lean**: α (absorb — narrow the claim; inscribe the residual exposure). True FS/network isolation for fetched plugins is a container-orchestration problem (P4), not a P3 subprocess patch. The current design's env scoping IS a genuine improvement over Posture A's zero protection — the ADR just overstates what it delivers.

**R2 — Fetched→Posture-B enforcement is a runtime provenance branch, not structurally unreachable**

- **Location**: ADR-031 D3 ("structurally unreachable"); plan P3.7-remote-6 §acceptance
- **What**: The ADR claims "a `fetched` plugin's `tool_impls` running in-process is structurally unreachable." Traced against the design: the plan says `load_plugin_code` is "reworked" — the in-process `importlib` path is preserved for `operator-placed` plugins (ADR-031 D3: "Posture A remains valid for operator-placed"). Both the in-process and subprocess code paths coexist in the same module. The enforcement is a single runtime branch on `provenance` — a refactoring error, a missed edge case, or a provenance mis-mark means fetched code runs in-process. "Structurally unreachable" means the in-process path does not exist for fetched code — but it DOES exist; it's just gated by one `if provenance == "fetched":` guard.
- **Why it matters**: The L1/L1b/L2 resolution — the entire constitutional crux — depends on fetched plugin code never running in-process. One runtime guard is one failure point. The ADR's "structurally unreachable" claim would require the in-process `importlib` path to not even exist in the code path reachable from `fetched` provenance (e.g., separate loader entry points, or a type-system guarantee). A test asserting unreachability (plan P3.7-remote-6) only tests the known paths; it doesn't protect against a future code change adding a new path that bypasses the check.
- **Suggested investigation**: Either (a) separate the loading interfaces: `load_operator_placed_plugin()` (Posture A/B) vs `load_fetched_plugin()` (Posture B only, structurally incapable of in-process import); or (b) accept the runtime guard + test as sufficient and remove the "structurally unreachable" claim, replacing with "test-enforced unreachable."
- **Architect-partner lean**: α (absorb — narrow the claim to "test-enforced unreachable"; the runtime guard IS the enforcement; the wording overstates).

---

### 🟡 Yellow — needs architect attention

**Y1 — Kill-no-orphan depends on MCP SDK internals without an orchestrator-level watchdog**

- **Location**: ADR-031 D2; plan P3.7-remote-5 §acceptance ("kill-no-orphan"); `mcp/transport.py:7-10` (docstring describes SDK behavior)
- **What**: The kill-no-orphan guarantee rests on the MCP SDK's `stdio_client` async context manager: `asyncio.wait_for` cancellation → `__aexit__` → close stdin → SIGTERM → `PROCESS_TERMINATION_TIMEOUT` → SIGKILL. This is a **LAYER-2** (framework) guarantee, not LAYER-1 (orchestrator) enforcement. If the SDK's SIGKILL path has a bug, or if the child ignores SIGTERM and the SDK's escalation fails, the orchestrator has no independent kill watchdog. CPython asyncio cancellation is cooperative — a stuck subprocess writing to a full pipe might not respond.
- **Why it matters**: A hung plugin subprocess that survives SIGKILL (rare but possible — zombie-reaping races, PID namespace edge cases) becomes a permanent orphan consuming resources. The orchestrator has no fallback timer that says "if the child PID still exists after N seconds, force-kill it."
- **Suggested investigation**: Add an orchestrator-level watchdog: after the SDK teardown, check if the child PID still exists; if so, send SIGKILL directly. Or document the SDK dependency explicitly and accept the residual risk.
- **Architect-partner lean**: β (defer to P4 — the SDK's PROCESS_TERMINATION_TIMEOUT handles the common case; an orchestrator watchdog is defense-in-depth).

**Y2 — Posture B harness env construction is underspecified (MCPServerConfig vs PluginManifest mismatch)**

- **Location**: ADR-031 D2 ("the harness wraps a plugin's `<module>:<callable>` as a stdio MCP-server child"); plan P3.7-remote-4/5; `mcp/transport.py:58-73` (`_build_scoped_env` takes `MCPServerConfig`)
- **What**: The shared trust primitive `_build_scoped_env` at `mcp/transport.py:58-73` takes an `MCPServerConfig` — it reads `server_cfg.env` and `server_cfg.api_key_env`. A Posture B plugin has a `PluginManifest` (at `plugins/schema.py`), which has no `env` or `api_key_env` field. The plan says the harness constructs a config-equivalent for the subprocess, but how a plugin declares its needed env vars is not designed. Worse: if the harness allows `api_key_env` for plugins, a fetched plugin could request a credential env var by name — the operator activates it, and the plugin's subprocess gets the secret. If the harness does NOT allow `api_key_env`, the design gap is how to pass needed non-secret env to a plugin.
- **Why it matters**: Without a designed mechanism, the impl will improvise. The risk is either credential leak (if `api_key_env` is blindly supported for plugins) or broken plugins (if no env-passing mechanism exists).
- **Suggested investigation**: Add an `env` field to the plugin manifest (safe non-secret env vars only) and explicitly forbid `api_key_env` for plugins (plugins don't talk to external authenticated services — they're tool code, not MCP servers). Document the design in ADR-031 D2.
- **Architect-partner lean**: α (absorb — add a `plugin_subprocess_env: dict[str, str]` to the manifest or the activation entry; forbid `api_key_env` for plugins).

**Y3 — Loader interface for fetched plugins is not specified (staging path → discovery)**

- **Location**: ADR-031 D3/D5; plan P3.7-remote-6/7; `plugins/loader.py:85-172` (`_discover_and_validate` only walks one `plugins_dir`)
- **What**: The loader at `plugins/loader.py:452-520` (`load_plugins`) takes a single `plugins_dir: Path` and discovers plugins by iterating subdirectories. Fetched plugins (P3.7-remote-7) are staged to a **different** path (a staging dir). The plan and ADR do not specify how fetched plugins reach the loader — does `load_plugins` accept a second path? Does the fetch mechanism symlink/copy into `plugins/`? Does the loader get a new `fetched_plugins_dir` parameter? Without this interface, the "provenance is host-set by how the loader obtained the plugin" claim cannot be implemented — the loader has no way to distinguish a plugin from `plugins_dir` (operator-placed) from one in a staging dir (fetched).
- **Why it matters**: This is a missing API surface. The impl will have to invent it, and if it's wrong (e.g., fetched plugins get copied into `plugins/` and lose their provenance marking), the entire provenance model collapses.
- **Suggested investigation**: Extend `load_plugins` signature to accept `fetched_plugins_dir: Path | None = None`; plugins discovered there are marked `fetched` (provenance host-set, not manifest-asserted). Document in ADR-031 D3.
- **Architect-partner lean**: α (absorb — specify the loader extension in ADR-031 D3).

**Y4 — No constitution test to enforce "never `verify=False`" for remote transport**

- **Location**: ADR-032 D2/D3 (HR#6); `tests/mcp/test_constitution.py` (no TLS-verification scan)
- **What**: The ADR mandates TLS verification ON, never disabled. The constitution tests at `tests/mcp/test_constitution.py` scan for forbidden symbols (`decide_tier`, `emit_gate_decision`, etc.) and forbidden imports (`orchestrator.llm.providers`). There is no equivalent scan for `verify=False` in the MCP transport code. The enforcement is by convention only.
- **Why it matters**: A future maintainer adding a self-signed-dev-endpoint workaround could pass `verify=False` to `streamablehttp_client` or the underlying httpx client, silently disabling TLS verification. The gate-diff tests prove that AST-scan enforcement works; the same pattern should apply to TLS.
- **Suggested investigation**: Add a constitution test that scans `mcp/transport.py` (and any new remote transport file) for `verify=False` or `verify = False` — assert zero occurrences. Low-cost, high-signal.
- **Architect-partner lean**: α (absorb — add the scan in P3.7-remote-9).

**Y5 — Bundle format and integrity-check ordering not specified (digest-before-extract concern)**

- **Location**: ADR-031 D5; plan P3.7-remote-7
- **What**: The ADR says the fetched bundle is "integrity-checked against the activation digest" but does not specify the bundle format (zip? tar? directory?) or whether integrity is checked **before or after** extraction. If the bundle is an archive extracted before the digest is verified, a malicious archive can exploit extraction: zip bombs (disk exhaustion), path traversal (`../../.ssh/authorized_keys`), or symlink attacks during extraction — all before the digest check fails.
- **Why it matters**: Digest-check-too-late = arbitrary code already ran (or arbitrary files already written). This is the same class as "import before collision-check" (ADR-029 D2 step ordering, R0-B R1) — the ordering IS the security property.
- **Suggested investigation**: Specify: (1) bundle format is a single `.zip` or `.tar.gz`; (2) digest is computed on the compressed bundle BEFORE extraction; (3) extraction happens in a temp dir with path-traversal guards; (4) if extraction fails, the temp dir is removed. The digest MUST be verified before any byte of the bundle touches the filesystem in extracted form.
- **Architect-partner lean**: α (absorb — add the ordering constraint to ADR-031 D5).

**Y6 — No per-turn call cap for Posture B plugin tools (unlike MCP's `MAX_MCP_CALLS_PER_TURN=10`)**

- **Location**: `tools/executor.py:43` (`MAX_MCP_CALLS_PER_TURN = 10`), `tools/executor.py:152-161` (`_execute_local_call` — no cap)
- **What**: The executor has `MAX_MCP_CALLS_PER_TURN = 10` for MCP calls (line 43). Posture B plugin tools go through `_execute_local_call` (lines 152-161), which has **no per-turn cap**. A malicious or buggy fetched plugin could be called an unlimited number of times per turn — each call launches a subprocess, consuming OS resources (PIDs, memory, FDs). An attacker who gets a low-reversibility tool through the gate could DoS the host via subprocess exhaustion.
- **Why it matters**: Under Posture A (in-process), unlimited local tool calls are fast and cheap (function calls). Under Posture B (subprocess), each call is a process fork — much more expensive. The per-turn cap was designed for MCP (also subprocess/network), and the same rationale applies to Posture B plugins. The plan's ADR-028 D5 liveness bound test covers *one* hung call — not *many* rapid calls.
- **Suggested investigation**: Extend the per-turn cap to cover Posture B plugin calls, or add a separate `MAX_LOCAL_SUBPROCESS_CALLS_PER_TURN`. The cap applies only when the `LocalToolFn` is a subprocess closure (operator-placed Posture-A tools are exempt).
- **Architect-partner lean**: β (defer to P4 — the gate's default-0 tier limits this to HARD_CONFIRM tools; an attacker would need operator pre-classification to reach AUTO_EXECUTE).

**Y7 — Half-stage fetch cleanup not designed (integrity-failed bundles left in staging)**

- **Location**: ADR-031 D5 ("refused, nothing staged"); plan P3.7-remote-7
- **What**: The ADR says a failed fetch "refused, nothing staged" but does not specify cleanup. If a bundle is downloaded to a staging directory, integrity-check fails, and the download is not removed, the partially-staged bundle persists on disk. On the next load cycle, the loader might re-discover it (depending on the staging layout, Y3). Even if not re-discovered, it accumulates disk usage.
- **Why it matters**: "Nothing staged" is the desired end-state, not the designed mechanism. Without explicit cleanup on failure, the invariant is aspirational. The risk is low (the digest check prevents loading), but the defunct files are operational noise.
- **Suggested investigation**: Specify atomic staging: download to a temp file → verify digest → if valid, move to staging dir; if invalid, delete temp file. If the bundle is extracted, extract to a temp dir → verify contents → if valid, rename to staging; if invalid, `shutil.rmtree` the temp dir.
- **Architect-partner lean**: α (absorb — add atomic-staging semantics to ADR-031 D5).

---

### 🟢 Green — advisory / confirmed-correct

**G1 — Empty-gate-diff + empty-executor-diff claims are real, not aspirational**

- **Location**: ADR-031 HR#1/#2; ADR-032 HR#1; `tools/executor.py:297-347`
- **What**: Verified against live source. `_execute_local_call` at line 327 calls `impl(params)` — it is genuinely mechanism-agnostic. It does not care whether `impl` is an in-process function or a subprocess-launching closure. The gate path (`process_tool_calls → emit_gate_decision`) is in a separate module (`agents/tool_dispatch.py`) and is untouched by both B1 and B2. A Posture B plugin tool goes through the same `local_tools` registry → same executor → same gate. B2's remote transport goes through the same `mcp__` namespacing → same allowlist → same gate. Both empty-diff invariants hold.

**G2 — TLS/credential posture for remote MCP is solid**

- **Location**: ADR-032 D1/D2/D3
- **What**: `https://` enforced at config validation (reject `http://` → `ConfigError`); TLS `verify=True` (httpx default, never disabled); `api_key_env` → `Authorization` header (no plaintext, never logged); URL allowlist via the config entries (the set of declared `streamable_http` servers IS the allowlist — an undeclared endpoint is unreachable). The `api_key_env` indirection pattern is the same one already dual-lens-vetted in ADR-027 D4. No credential leak path found.

**G3 — Scoped-env allowlist is genuinely minimal**

- **Location**: `mcp/transport.py:33-43` (`_SAFE_ENV_KEYS`)
- **What**: Only 9 keys: `PATH`, `HOME`, `USER`, `LOGNAME`, `SHELL`, `TERM`, `TMPDIR`, `TEMP`, `TMP`. No `PYTHONPATH`, no `LD_LIBRARY_PATH`, no `AWS_*`, no `OPENAI_*`, no `ANTHROPIC_*`. The orchestrator's full `os.environ` is never passed. The c2 env-leak lesson IS applied correctly. For Posture B plugins, the harness would need to use this same function — Y2 covers the integration gap; the primitive itself is correct.

**G4 — ADR-028 D5 liveness bound is genuinely restored for Posture B**

- **Location**: ADR-031 D1/HR#7; `tools/executor.py:297-347` (unchanged `_execute_local_call`)
- **What**: Under Posture A, `impl(params)` at line 327 runs in-process — a hung function blocks the `max_workers=1` writer indefinitely. Under Posture B, `impl` is a closure that launches a subprocess via `asyncio.wait_for` with a bounded timeout → on timeout, the task is cancelled, the subprocess is killed, and an exception propagates to the `except Exception` at line 328 → `TOOL_FAILED`. The writer thread is blocked for at most the timeout duration, then unblocked. The bound is real. The test plan (P3.7-remote-5: "a hung/runaway plugin tool is killed and does NOT block the single writer past the bound — a discriminating test") is the right test.

---

## Synthesis

Two patterns cluster across the findings:

**Pattern A — Overstated isolation claims (R1, R2).** The ADRs use language like "L1 RESOLVED," "real isolation boundary," "structurally unreachable" that the mechanisms, when traced against live source, do not fully deliver. The env scoping IS real; the FS/network isolation is absent. The provenance branch IS enforced; it is not structurally unreachable. This is the cross-family lens's highest-value catch: an in-family reviewer reads "scoped env" and infers "isolated"; the cross-family reviewer traces the subprocess boundary and asks "what CAN the child still do?" The answer: read files, open sockets. Narrowing the claims to what the mechanism actually delivers turns R1+R2 from 🔴 to inscribed-accepted-risk.

**Pattern B — Underspecified integration surfaces (Y2, Y3, Y5, Y7).** The plan and ADRs describe the WHAT (Posture B, provenance, fetch, activation) but leave gaps in the HOW: how fetched plugins reach the loader (Y3), how the harness constructs the child env (Y2), when integrity is checked relative to extraction (Y5), and how failed fetches are cleaned up (Y7). These are all impl-fill-in-the-blank surfaces — the senior deferred them to junior, but the design doesn't constrain the answers enough to prevent a wrong choice. Each is individually 🟡; collectively they mean the junior is designing security-critical interfaces on the fly. The architect should confirm the answers before junior starts.

**Correction-mode note (RC-20):** No in-family false-positive corrections in this review. All findings are net-new — the cross-family lens is adding coverage on dimensions the in-family review structurally under-probes (filesystem/network isolation, integration-surface completeness).

---

## Verdict

**blocking** — 2🔴 (R1: FS/network isolation unaddressed — overstated L1 claim; R2: provenance enforcement is runtime-branch, not structurally unreachable). Both are claims the ADRs make that the design, as specified, does not deliver. Resolution: narrow the claims (α) — inscribe what Posture B actually isolates (env + memory + liveness) and what it does not (FS + network). This is a documentation/claims fix, not a redesign; the mechanisms themselves are correct for the P3 scope.

After R1+R2 absorption: 7🟡 remain for architect routing. None are individually blocking — each is a design refinement the senior can absorb before junior dispatch.


---

# P3.7-remote R0-B cross-family review — IMPL-STAGE (2026-06-04)

## Impl-stage lens

Reviewed `origin/claude/P3.7-remote-impl` @ a49e86f — 9 atomic commits (P3.7-remote-1..9), 26 source files, 3,929 insertions. Every plan-stage finding (2🔴 + 7🟡 + 4🟢) traced to its code resolution.

The ADR-031 was updated post-routing (D1a inscribed RB-FS/NET residual; D2 watchdog; D3 narrowed to "test-enforced unreachable" + segregated roots; D4 operator-authored env only; D5 digest-before-extract + atomic staging; D6 Y6 cap). This review verifies the code delivers it. Zero diff in `src/orchestrator/autonomy/` + `agents/tool_dispatch.py` — the empty-gate-diff holds at commit level.

---

## Plan-stage finding resolution — verified in code

### 🔴 R1 (FS/NET) → RESOLVED — ADR-031 D1a inscribed + code honest

`plugins/code.py:6-10`: "Scoped env: child inherits only safe keys; orchestrator secrets never reach it." No FS/network sandbox claim. `_PostureBFn` (lines 49-108) launches subprocess with `build_scoped_env(harness_cfg)` — env-scoped, killable, bounded-timeout. ADR-031 D1a explicitly inscribes: "NOT a syscall sandbox. Bounds three things and only three: memory/process, secrets/env, liveness/DoS." The RB-FS/NET residual is Accepted and inscribed. **Code delivers the honest contract.**

### 🔴 R2 (fetched unreachable) → RESOLVED — stronger than ADR requires

Three mechanisms converge:
1. **Segregated roots** — `loader.py:487-500`: `load_plugins()` takes separate `plugins_dir` + `fetched_plugins_dir`. Discovery at lines 548-569 calls `_discover_and_validate` with `provenance="operator_placed"` vs `provenance="fetched"`. Provenance-by-origin, not plugin-asserted.
2. **Disjoint-root guard** — `loader.py:522-541`: mutual `resolve().relative_to()` check; overlap → `ValueError` at bootstrap. A fetched bundle cannot be re-discovered as operator-placed (provenance-laundering prevented).
3. **All plugins forced Posture B** — `load_plugin_code` at `code.py:111-145` always returns `_PostureBFn` closures. The old in-process `importlib`/`exec_module` path is **entirely removed** from `plugins/code.py`. `_harness.py:31-35` runs `spec_from_file_location` + `exec_module` in the **child** process. `_is_posture_b_subprocess` ClassVar marker (line 61) is structural proof.

Test `test_pv5_fetched_tool_impls_are_posture_b` (`test_provenance.py:263-287`) + `test_pv5_operator_placed_tool_impls_are_also_posture_b` (lines 290-297). **The code is safer than the ADR describes** — see I1 below.

### 🟡 Y1 (kill-no-orphan watchdog) → RESOLVED

`subprocess_trust.py:279`: `_kill_watchdog(pid)` runs in `finally` after ALL SDK-equivalent teardown. Watchdog at lines 87-111: `os.kill(pid, 0)` → if alive, `os.kill(pid, SIGKILL)` → `os.waitpid(pid, 0)` to reap. Genuine LAYER-1 enforcement. `_terminate_subprocess` (lines 129-177) additionally does SIGTERM → SIGKILL escalation with `anyio.CancelScope(shield=True)`. Watchdog shared by both MCP stdio (`transport.py:180,189`) and Posture B executor (`code.py:97`).

### 🟡 Y2 (harness env) → RESOLVED

Activation entry at `provenance.py:36-51` has `plugin_subprocess_env: dict[str, str]` — **operator-authored, NOT plugin-authored.** `PluginManifest` (`schema.py`) has no `env` or `api_key_env` field. Loader at `loader.py:444-446` passes `activation_entry.plugin_subprocess_env` to `load_plugin_code`. `api_key_env` never set on harness MCPServerConfig (`code.py:86-89` — only `env`, `api_key_env` defaults to None). `build_scoped_env` (`subprocess_trust.py:75-78`) only injects secret if `server_cfg.api_key_env` is set — structurally unreachable for plugins.

### 🟡 Y3 (loader interface) → RESOLVED

`load_plugins` at `loader.py:487-500`: `fetched_plugins_dir: Path | None = None` + `activation_registry_path: Path | None = None`. Two separate roots, each with provenance tag. Disjoint-root guard prevents laundering. Global collision-check (lines 571-617) is cross-root.

### 🟡 Y4 (verify=False test) → RESOLVED

`tests/mcp/test_constitution.py:166-201`: `test_constitution_c6_no_verify_false_in_remote_transport` — scans ALL `mcp/*.py` files for `verify=False`/`verify = False`/`"verify": False`/`'verify': False`. Non-vacuous: `scanned > 0`. Remote transport at `transport.py:112-113` explicitly sets `verify=True` on `httpx.AsyncClient`.

### 🟡 Y5 (digest-before-extract) → RESOLVED

`fetch.py:131-138`: security ordering documented. Step 2 (download to tempfile, line 158) → Step 3 (digest verify, lines 170-181) → Step 4 (extract to tempdir, lines 184-187). Digest on compressed bytes BEFORE extraction. Path-traversal guards: `_safe_member_path` (lines 62-75), `_extract_zip` (78-88), `_extract_tar` (91-105, rejects symlinks/hardlinks). Size cap: `_MAX_BUNDLE_BYTES = 50 MiB` (line 36). Formats: `.zip` + `.tar.gz`/`.tgz` only (lines 108-118).

### 🟡 Y6 (per-turn cap) → RESOLVED

`tools/executor.py:48`: `MAX_POSTURE_B_CALLS_PER_TURN = 10`. Lines 159-202: `getattr(_impl, "_is_posture_b_subprocess", False)` identifies Posture-B fns → cap exceeded → `TOOL_FAILED(turn_posture_b_cap_exceeded)`. Posture-A in-process tools exempt (no marker). Cap is in `execute_pending_tool_calls` (mechanism), NOT `_execute_local_call` (decision). Test `t3b_executor_empty_decision_diff` (`test_constitution.py:160-201`) AST-scans `_execute_local_call` for decision symbols — zero violations.

### 🟡 Y7 (staging cleanup) → RESOLVED

`fetch.py:153-219`: tempfile download → digest verify → tempdir extract → atomic `tmp_staging.rename(dest_dir)` → `tmp_staging = None`. `except` block (lines 208-214): on ANY failure, `shutil.rmtree(tmp_staging)` + `tmp_bundle.unlink()`. `finally` block (lines 216-219) cleans temp bundle on success too. `fetched_plugins_dir` NEVER touched by a failed fetch.

### 🟢 G1–G4 → RE-CONFIRMED

- **G1 (empty-diff)**: Zero diff `autonomy/` + `tool_dispatch.py`. `_execute_local_call` at `executor.py:338-388` byte-level unchanged. Test `t3b` AST-scans it.
- **G2 (TLS)**: `transport.py:112-134` — `httpx.AsyncClient(verify=True)`. `_remote_auth_headers` (97-108): `Authorization: Bearer <secret>` from `api_key_env`, never logged.
- **G3 (scoped env)**: `subprocess_trust.py:42-52` — same 9 keys. `build_scoped_env` (63-79) unchanged.
- **G4 (D5 bound)**: `_PostureBFn.__call__` (`code.py:75-83`): `run_sync(coro, timeout=30.0)`. `run_sync` (`_async_bridge.py:30-59`): `asyncio.wait_for` → `MCPTimeoutError` → `except Exception` in `_execute_local_call` → `TOOL_FAILED`. Writer unblocked after ≤30s.

---

## New impl-stage finding

### 🟡 Yellow

**I1 — ADR-031 D3 text vs code: in-process Posture-A path removed entirely (all plugins forced Posture B)**

- **Location**: ADR-031 D3 ("the in-process `importlib` path still physically exists in the module — it serves `operator-placed` plugins"; "Posture A remains valid for operator-placed"); `plugins/code.py` (no `importlib`/`exec_module` — only `_PostureBFn`); `test_provenance.py:290-297` (`test_pv5_operator_placed_tool_impls_are_also_posture_b`)
- **What**: The ADR-031 D3 says the in-process Posture-A path is "preserved for operator-placed plugins (no regression)" and "still physically exists." The code removed it entirely — `plugins/code.py` has no `spec_from_file_location`, no `exec_module`, no `_import_module_from_file`. ALL `tool_impls` (both `operator-placed` AND `fetched`) produce `_PostureBFn` subprocess-launching closures. The test at `test_provenance.py:290-297` explicitly documents: "Operator-placed plugin tool_impls are also Posture-B (all plugins use subprocess now)."
- **Why it matters**: The code is **safer** than the ADR describes — there is zero in-process plugin code execution, which means the plan-stage R2 concern is resolved more strongly than required ("structurally unreachable" is now TRUE, not just "test-enforced"). But an ADR reader checking against the code will find a contradiction: the ADR says the path exists but the code has no trace of it. A future maintainer relying on the ADR text might expect a Posture-A opt-out that doesn't exist, or might re-add the in-process path thinking it was accidentally removed.
- **Suggested investigation**: Update ADR-031 D3: "The impl removed the in-process Posture-A path entirely; ALL plugins (operator-placed and fetched) run under Posture B subprocess isolation. The P3.5 in-process convenience is retired — the price of the real env/secret/DoS boundary. No regression: operator-placed plugins continue to function under subprocess isolation."
- **Architect-partner lean**: α (absorb — update ADR text to match code; the code is correct and safer).

---

## Impl-stage 🟢 confirmations

**G5 — `_harness.py` import boundary is the isolation contract.** `_harness.py:31-35`: `spec_from_file_location` + `exec_module` in the child process. Parent (`code.py:97`) calls `subprocess_mcp_stdio(harness_params)` — never imports `_harness.py`. Comment at `_harness.py:10-11`: "Never imported by the host orchestrator."

**G6 — Provenance-laundering vector closed.** `loader.py:522-541`: `plugins_dir` and `fetched_plugins_dir` mutually-disjoint-checked at bootstrap. A fetched bundle cannot be re-discovered as operator-placed.

**G7 — `api_key_env` structurally unreachable for fetched plugin subprocess.** `code.py:86-89`: `MCPServerConfig` with no `api_key_env` kwarg. `build_scoped_env` only injects secret if `server_cfg.api_key_env` is set — always `None` for plugins. Env-leak probe at `test_posture_b.py:362-377`: secret in `os.environ` returns `__absent__` in child.

**G8 — Empty-gate-diff confirmed at commit level.** `git diff origin/main..HEAD -- src/orchestrator/autonomy/ src/orchestrator/agents/tool_dispatch.py` → zero output. Zero diff in `mcp/adapter.py` and `mcp/execution.py`. `_execute_local_call` body identical to plan-stage verified version.

**G9 — Atomic fetch staging is battle-tested.** `fetch.py:153-219`: tempfile → digest → tempdir (traversal-guarded) → validate → atomic rename → cleanup. On any exception: `rmtree` + `unlink`. `finally` block handles success path. No half-staged residue.

**G10 — Watchdog shared by MCP stdio AND Posture B.** `subprocess_trust.py:276-279`: `finally` block with `_kill_watchdog(pid)` wraps every `subprocess_mcp_stdio` usage — MCP transport + Posture B executor both go through it.

**G11 — Constitution test coverage extended to all new modules.** `tests/mcp/test_constitution.py` c6 covers new `_async_bridge.py` + `subprocess_trust.py`. `tests/plugins/test_constitution.py` p1–p4 cover `provenance.py`, `fetch.py`, `_harness.py`, reworked `code.py`. `tests/tools/test_constitution.py` t3b covers executor empty-decision-diff. All scans non-vacuous.

---

## Impl-stage synthesis

The implementation delivers exactly what the revised ADR-031 (with D1a honesty + D2 watchdog + D3 segregated roots + D4 operator-only env + D5 digest-before-extract) and ADR-032 promise. Every plan-stage 🔴/🟡 finding has a specific, traceable code resolution. The code is in several respects **safer** than the ADR describes:

1. **All plugins forced Posture B** — in-process path gone entirely. R2 resolved structurally, not just test-enforced.
2. **Watchdog shared** — MCP stdio AND Posture B both get LAYER-1 kill watchdog via same `subprocess_mcp_stdio`.
3. **Provenance un-launderable** — disjoint roots + runtime guard at bootstrap.
4. **`api_key_env` structurally unreachable for plugins** — `MCPServerConfig` construction never sets it.

The one 🟡 finding (I1) is a documentation gap: ADR-031 D3 says Posture-A path "still physically exists" but code removed it. The ADR should be updated to match code, not the other way around.

**Cross-family value at impl-stage**: plan-stage caught the gap between ADR claims and mechanism capabilities (R1, R2). Impl-stage verifies the gap was closed — not just in ADR text (revised) but in code (built to revised contract).

**Correction-mode note (RC-20)**: No in-family false-positive corrections at impl-stage. The 1 🟡 is net-new (ADR-vs-code documentation drift).

---

## Impl-stage verdict

**needs_architect** — 0🔴 / 1🟡 / 7🟢. All plan-stage 🔴/🟡 verified resolved in code. The 1 new 🟡 (I1) is an ADR-text-vs-code doc gap: _PostureBFn constructs MCPServerConfig with api_key_env never set (always None), so build_scoped_env never injects a secret into the plugin child — the env boundary is structural, not just test-enforced. Code is correct and safer than ADR describes. Architect should confirm whether to update ADR-031 D3 or leave as-is.
