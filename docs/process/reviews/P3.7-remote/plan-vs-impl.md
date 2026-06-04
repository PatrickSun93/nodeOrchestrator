---
review: plan-vs-impl
task_id: P3.7-remote
stage: impl
reviewer: senior
date: 2026-06-04
reviewed_ref: claude/P3.7-remote-impl @ a49e86f (9 atomics; HEAD 3b9ad10 adds only the R0-B review file)
plan_under_review: docs/process/senior-plans/P3.7-remote.md
adr_under_review:
  - ADR-031
  - ADR-032
gate_run:
  ruff_check: pass
  ruff_format: pass
  mypy_canonical_strict: FAIL
  pytest: pass
verdict: clean
verdict_history:
  - needs_architect
  - [2026-06-04, clean, "Architect routed via orchestrator (architect-routing-on-impl.md). PvI-2 mypy gate-red → alpha (junior fix2 fc13ba0; senior re-verified mypy Success/235 files). PvI-1 Posture-A-divergence → restore-per-contract (junior fix1 0563034 restored dual posture operator-placed→A / fetched→B; architect chose restore over the senior alpha-amend recommendation — the architect routing call; code now matches Accepted ADR-031 D3, no ADR edit). I1 structural guarantees absorbed (junior fix3 8353d85). PvI-3 advisory → P4. All 4 canonical gates green; fetched test-enforced-unreachable re-verified."]
findings:
  blocking: 0
  needs_architect: 2
  advisory: 1
note: >-
  Senior plan-vs-impl lens (plan + Accepted ADR-031/032 vs the 9 impl atomics).
  Independent full gate run per dispatch: ruff check + ruff format + pytest all
  green; canonical mypy --strict (files=src,tests — NOT 'mypy --strict .', the
  plugins-scope gotcha) RED — 2 unused type:ignore in tests/plugins/test_posture_b.py.
  Two routable findings, both converged by the concurrent R0-A + R0-B impl reviews
  (3-way, cross-family): PvI-1 the impl retired Posture A entirely (B-for-all) —
  faithful to the architect's A→B-migration ratification but contradicting the
  Accepted ADR-031 D3 text, which I (senior) introduced when absorbing the R2
  routing — and the ADR is internally self-contradictory (D3 vs Consequences);
  PvI-2 the canonical mypy gate is RED (merge-blocker, mechanical 2-line junior fix).
  Spine + the entire max-trust surface are otherwise faithfully implemented with
  file:line evidence (§4 cleared list). The impl is strong; nothing is a plan-design
  break — the routable items are an ADR-text amendment + a gate cleanup.
---

# Senior plan-vs-impl — P3.7-remote (Posture-B subprocess executor + remote MCP transport)

**Verdict: `needs_architect`.** The 9 impl atomics faithfully realise the plan + the constitutional spine, and every plan-stage routed finding (R0-A Y1-Y4 + R0-B R1/R2 + Y1-Y7, all → α) is verified absorbed in code. The senior lens — *plan/ADR-as-authored vs deliverable* — surfaces **two routable items**, both independently corroborated by the concurrent impl-stage R0-A + R0-B (3-way convergence): **PvI-1** the impl retired Posture A in-process **entirely** (all plugin tool code → Posture B subprocess), which is faithful to the architect's A→B-migration ratification but **contradicts the Accepted ADR-031 D3 text** (and the ADR is internally self-contradictory on this point); **PvI-2** the mandatory canonical `mypy --strict` gate is **RED** (a mechanical 2-line junior fix, but a hard merge-blocker). Neither is a plan-design break — the impl is correct; the fixes are an ADR amendment + a gate cleanup.

## 1. Independent gate run (per dispatch — full gate incl. canonical mypy)

Ran on `claude/P3.7-remote-impl`, canonical scope (`pyproject [tool.mypy] files=["src","tests"], strict=true` — **not** `mypy --strict .`, which collides on the two `plugins/*/tools_impl.py`, the known scope gotcha):

| Gate | Result | Evidence |
|---|---|---|
| `ruff check .` | 🟢 pass | "All checks passed!" |
| `ruff format --check .` | 🟢 pass | "238 files already formatted" |
| `mypy --strict` (src+tests) | 🔴 **FAIL (exit 1)** | `tests/plugins/test_posture_b.py:153` + `:172` — `error: Unused "type: ignore" comment [unused-ignore]`; "Found 2 errors in 1 file (checked 235 source files)" |
| `pytest` | 🟢 pass | full suite green to [100%], exit 0 (1 pre-existing unrelated StarletteDeprecationWarning) |

→ **PvI-2 (the gate-red).** The branch as-pushed fails the mandatory gate. Running the *canonical* invocation independently (per dispatch) is what caught it — likely a local mypy-version/scope skew when the junior gated.

## 2. Plan-fidelity sweep — per atomic (the senior lens: plan/ADR-as-authored vs code)

| Atomic | Plan/ADR requirement | Impl | Verdict |
|---|---|---|---|
| -1 | remote config: `transport ∈{stdio,streamable_http}` + `url` https-validated, frozen | `config.py` `_validate_transport_fields` model_validator; `command:str|None` re-required for stdio | ✅ faithful |
| -4 | seam split (G1): transport-agnostic `_async_bridge` vs subprocess-only `subprocess_trust`; LAYER-1 watchdog (Y1) | `_async_bridge.run_sync` generic; `subprocess_trust.build_scoped_env` + `_kill_watchdog` + SIGTERM→SIGKILL + `start_new_session` pgid + shielded teardown | ✅ faithful |
| -2 | non-deprecated `streamable_http_client` + host-built `httpx.AsyncClient(verify=True,headers,timeout)`; api_key→header | `transport.py:28,209,231` non-deprecated symbol; `_remote_client_for_*` explicit `verify=True`; `_remote_auth_headers` never logs secret | ✅ faithful |
| -3 | remote connector + hermetic e2e | `config/mcp_servers.yaml` `remote_demo`; `tests/mcp/test_p3_7_remote_connectors.py` | ✅ faithful |
| -5 | Posture-B subprocess; parent never imports; `_execute_local_call` byte-unchanged; `MAX_POSTURE_B_CALLS_PER_TURN` | `code.py` `_PostureBFn` + `_harness.py` (import in child); executor cap in `execute_pending_tool_calls` (not `_execute_local_call`) | ✅ faithful — **but see PvI-1** (Posture A in-process *removed*, not branched) |
| -6 | provenance-by-origin; segregated `fetched_plugins_dir`; fetched→activation fail-closed; manifest can't self-request env/secret | `loader.py` disjoint-root guard + per-root provenance; `provenance.py` activation registry + `check_fetched_activation`; operator-authored `plugin_subprocess_env` | ✅ faithful |
| -7 | bundle .zip/.tar.gz; digest-before-extract; path-traversal guard; atomic staging cleanup | `fetch.py` digest verified (step 3) before extract (step 4); `_safe_member_path` + symlink reject; temp-file/dir → rename, cleanup on failure | ✅ faithful |
| -8 | Posture-B demo + fail-closed (env-leak incl. manifest-requests-secret, cap, laundering, digest, unactivated) | `plugins/demo_posture_b/` + `tests/plugins/test_posture_b.py` / `test_p3_7_remote_plugins.py` / `test_fetch.py` / `test_provenance.py` | ✅ faithful |
| -9 | constitution: new modules in scan; no-new-LLMPurpose; empty-diff; `verify=False` scan | `test_constitution_c6_no_verify_false_*`, `test_p5_new_remote_modules_in_scan`, `test_t3b_executor_empty_decision_diff` (AST) | ✅ faithful |

## 3. Findings (I surface; architect routes — I do not decide)

### 🟡 PvI-1 (needs_architect) — Posture A retired entirely (B-for-all); impl ↔ Accepted-ADR-031-D3 divergence + an ADR internal self-contradiction I authored

**Evidence (code):** `plugins/code.py` no longer contains any `importlib`/`exec_module` of plugin code — `load_plugin_code` returns `_PostureBFn` subprocess closures for **every** plugin, and the in-process import now lives **only** in `plugins/_harness.py` (the child). So **operator-placed plugins also run Posture B**; the in-process Posture-A path **physically no longer exists** in the host. The P3.5 demos (`plugins/demo/`, `plugins/context/`) now execute via subprocess (their tests — `test_merge.py`, `test_failure_modes.py` — were adapted to match).

**Why it matters (the senior-unique diagnosis — I wrote both the plan and the ADR):**
1. **The impl is faithful to the architect's ratification.** The dispatch ruled *"A→B 迁移:plugins/code.py 的 importlib in-process → 子进程协议"* — a full executor migration to subprocess. Uniform Posture-B is the literal reading and is **strictly safer** (no in-process path to mis-route fetched code through).
2. **But it contradicts the Accepted ADR-031 D3 text**, which I introduced **when absorbing the R0-B-R2 → α routing**: D3 says *"operator-placed → Posture A remains valid … the P3.5 in-process path is **preserved** … (no regression)"* and *"the in-process `importlib` path **still physically exists in the module** (it serves operator-placed plugins)"* — the latter being the substrate of the "test-enforced unreachable" wording. The impl removed that path, so the claim is now false.
3. **ADR-031 is internally self-contradictory** (R0-A Y1 also caught this): D3 *"in-process preserved / path exists"* vs **Consequences/Harder** *"the in-process convenience of Posture A is **gone**."* These cannot both hold. This is an authored-ADR defect, independent of the impl — **it must be reconciled regardless of how Posture-A-retirement is routed.**

**Senior recommendation (architect routes):** **α — amend ADR-031 D3** to match the impl + the ratification: all plugin tool code runs **Posture B**; the in-process Posture-A path is **removed** (not "preserved"); operator-placed vs fetched differ in **activation/consent** (presence vs pinned-digest), **not** execution posture; the R2 enforcement strengthens from *"test-enforced unreachable"* to *"structurally unreachable"* (the path no longer exists — strictly stronger than what R2 settled). Reconcile D3 with Consequences. **vs** β — restore an in-process Posture-A fast path for operator-placed (match D3 as-written) — **not recommended** (gives up the stronger posture for a convenience the ratification did not ask to keep). Either way the ADR self-contradiction must be fixed; the architect's call is which side D3 lands on.

### 🟡 PvI-2 (needs_architect → junior fix) — canonical `mypy --strict` gate is RED (merge-blocker)

**Evidence:** `tests/plugins/test_posture_b.py:153` (`def route(...) -> Any:  # type: ignore[override]` — `_NoLLM.route` overrides nothing incompatible) and `:172` (`assert fn._is_posture_b_subprocess is True  # type: ignore[union-attr]` — `fn` is a `_PostureBFn`, no union) carry **unused** `type: ignore` comments → `mypy --strict` exits 1.

**Why it matters:** per CLAUDE.md the full gate is mandatory; **a branch that fails `mypy` cannot merge.** Mechanical (delete 2 comments, re-run `uv run mypy` to confirm green) — no design input — but an objective hard blocker until green. Root cause is likely a local mypy version/scope skew when the junior gated; the junior should re-run the **canonical** invocation (`uv run mypy`, not `mypy --strict .`).

**Senior recommendation:** dispatch a junior fix-commit (2-line deletion); re-confirm `uv run mypy` green before merge.

### 🟢 PvI-3 (advisory — senior note, no architect call) — fetch size-cap is post-download-into-memory

`fetch.py:164` reads the whole `response.content` into memory, then checks `_MAX_BUNDLE_BYTES` at `:171`. The 50 MB cap is enforced **after** the body is buffered, so a malicious endpoint could buffer >50 MB before the check. Low risk (the source URL is operator-pinned in the activation entry; only an operator-trusted host is fetched from) and the plan/ADR did not require a streaming bound. Advisory: a future hardening could stream with an early byte-count abort. Not blocking; not a plan divergence.

## 4. What I explicitly cleared (the sweep was real — plan-implied invariants held, with cites)

- **Empty-gate-diff** — no file under `autonomy/` and not `agents/tool_dispatch.py` touched (`git diff --name-only` empty); `score`/`decide_tier`/`emit_gate_decision`/`process_tool_calls` untouched.
- **Empty-executor-diff** — `_execute_local_call` byte-unchanged; the Posture-B cap lives in `execute_pending_tool_calls`; `test_t3b_executor_empty_decision_diff` AST-guards that `_execute_local_call` references no decision symbol.
- **Reuse-the-MCP-subprocess-mechanism (no second protocol)** — the harness is an MCP **stdio `Server`** child (`_harness.py`); the parent drives it via the reused `subprocess_mcp_stdio` + `ClientSession`; one protocol.
- **Kill-no-orphan + LAYER-1 watchdog (Y1)** — `subprocess_trust._kill_watchdog` (post-teardown PID check → SIGKILL + reap) + SIGTERM→SIGKILL escalation + `start_new_session` pgid kill + `CancelScope(shield=True)` surviving `wait_for` cancellation.
- **Provenance un-launderable (D3 / R0-A Y3 / R0-B Y3)** — `loader.load_plugins` disjoint-root guard (both directions); provenance host-set by discovery root, never manifest-asserted.
- **Fetched-env operator-authoritative (D4 / R0-A Y4 / R0-B Y2)** — `ActivationEntry.plugin_subprocess_env` operator-authored; `build_scoped_env` for the harness has no `api_key_env` path from the manifest; env-leak probe (`env_probe_tool`) covers it.
- **digest-before-extract + atomic staging (Y5/Y7)** — `fetch.py` verifies sha256 of compressed bytes (step 3) before `_detect_and_extract` (step 4); path-traversal + tar symlink/hardlink rejection; temp→rename with except/finally cleanup.
- **streamable-http: non-deprecated client + verify=True + verify=False-banned (Y1/Y4)** — `transport.py` `streamable_http_client` + explicit `verify=True`; `test_constitution_c6_no_verify_false_in_remote_transport` regex-bans it in `mcp/`.
- **Per-turn cap (Y6)** — `MAX_POSTURE_B_CALLS_PER_TURN=10`, marker-gated (`_is_posture_b_subprocess`), Posture-A exempt, excess → `TOOL_FAILED(turn_posture_b_cap_exceeded)`.
- **RB-FS/NET residual respected (no over-build)** — `subprocess_trust` scopes **env** only; **no** seccomp/container/UID-drop was added — the impl stays inside the Accepted residual (D1a), not beyond it.

## 5. Convergence note (RC-20)

**3-way convergence, two families + the senior authorship lens.** Both concurrent impl reviews independently hit the **same two** items: R0-A (in-family) `blocking` = B1 gate-red + Y1 Posture-A-retired/ADR-D3-divergence; R0-B (cross-family, DeepSeek) `clean` 0🔴/1🟡/7🟢 = the same ADR-031-D3 text-vs-code staleness + 7🟢 mechanism confirmations. My plan-vs-impl adds the **senior-unique diagnosis**: I authored both the plan and ADR-031, so I can attribute the D3 defect to **my R2-routing-absorption** ("in-process path physically exists") and confirm it contradicts **both** the impl **and** the ADR's own Consequences — i.e. the fix is a self-contained ADR-031 D3↔Consequences reconciliation, not an impl change. No in-family false-positive corrections; all findings net-new and mutually reinforcing.

## Expected state transition

Per ADR-008 Amendment 1 (W-005, Route B): state advances to `awaiting_R0_A` regardless of this verdict (this split cycle the architect manages the state machine manually). Both impl-stage reviews (R0-A, R0-B) already landed concurrently. **Next: architect routes PvI-1/Y1 (amend ADR-031 D3 + reconcile Consequences) + dispatches the PvI-2/B1 junior mypy fix; re-confirm `uv run mypy` green before merge.**
