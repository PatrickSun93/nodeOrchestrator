---
review: R0-A
task_id: P3.7-remote
stage: impl
reviewer: architect-partner
date: 2026-06-04
verdict: blocking
reviewed_ref: claude/P3.7-remote-impl @ a49e86f
gate_run:
  ruff_check: pass
  ruff_format: pass
  mypy_canonical_strict: FAIL
  pytest: pass
findings:
  blocking: 1
  needs_architect: 1
  advisory: 1
note: >-
  Independent full gate run (per dispatch): ruff + ruff-format + pytest all green;
  canonical mypy --strict (files=src,tests) RED — 2 unused type:ignore in
  tests/plugins/test_posture_b.py (B1, trivial 2-line fix, but the branch as-pushed
  fails the mandatory gate). One needs_architect divergence (Y1): the impl retired
  Posture A entirely (B-for-all) — safer, but contradicts the freshly-Accepted
  ADR-031 D3 (operator-placed → A preserved, in-process path physically exists) and
  exposes a D3-vs-Consequences internal contradiction in the ADR. Spine + max-trust
  surface otherwise faithfully implemented: kill-no-orphan + LAYER-1 watchdog + scoped
  env + per-turn cap, parent never imports plugin code, provenance-by-origin
  un-launderable, fetched-env operator-authoritative, non-deprecated SDK client +
  verify=True + verify=False constitution-banned, empty-decision-diff AST-guarded,
  RB-FS/NET honestly inscribed (no fake sandbox). All plan-stage routed findings
  (R0-A Y1-Y4 + R0-B R1/R2/Y1-Y7 → α) verified absorbed in code. Fix B1 + route Y1.
---

# R0-A (impl-stage) — P3.7-remote (Posture-B subprocess executor + remote MCP transport)

**Verdict: `blocking`** — 1 🔴 (canonical gate RED), 1 🟡 (needs_architect), 1 🟢 (advisory). The impl is **strong**: the constitutional spine and the largest-trust-surface mechanisms are faithfully built, and every plan-stage routed finding (R0-A Y1-Y4 + the R0-B 🔴🔴 + Y1-Y7, all → α) is verified absorbed in code. Two things block a clean accept: **(B1)** the branch as-pushed **fails the mandatory canonical `mypy --strict` gate** (2 unused `type: ignore`, a trivial fix but an objective gate-red), and **(Y1)** the impl **retired Posture A entirely** — safer than the contract, but a divergence from the freshly-Accepted ADR-031 D3 that the architect must route (and which surfaces an internal contradiction in the ADR itself).

## 1. Independent gate run (per dispatch — "独立跑完整 gate, 含 mypy --strict canonical")

Ran on `claude/P3.7-remote-impl @ a49e86f`, canonical scope (`pyproject [tool.mypy] files=["src","tests"], strict=true` — **not** `mypy --strict .`, which would collide on `plugins/*/tools_impl.py`, the known scope gotcha):

| Gate | Result | Evidence |
|---|---|---|
| `ruff check src tests` | ✅ pass | "All checks passed!" |
| `ruff format --check src tests` | ✅ pass | "235 files already formatted" |
| **`mypy` (strict, src+tests)** | 🔴 **FAIL (exit 1)** | `tests/plugins/test_posture_b.py:153` + `:172` — `error: Unused "type: ignore" comment [unused-ignore]`; "Found 2 errors in 1 file (checked 235 source files)" |
| `pytest -q` | ✅ pass (exit 0) | full suite green, incl. all new Posture-B / remote-transport / fetch / provenance / constitution tests |

→ **B1 (🔴 blocking).** The two ignores are genuinely unused under the canonical strict config: `test_posture_b.py:153` (`def route(...) -> Any:  # type: ignore[override]` — `_NoLLM` doesn't actually override an incompatible base) and `:172` (`assert fn._is_posture_b_subprocess is True  # type: ignore[union-attr]` — `fn` is a `_PostureBFn`, no union). Fix = delete the two comments. **But:** a branch that fails `mypy` cannot merge — the mandatory gate is RED, and R0-A running it independently (as dispatched) is exactly what caught it. This is mechanical, not a redesign, but it blocks accept until green.

## 2. Spine + max-trust-surface sweep — what I verified correct (the bulk of the impl is right)

I traced all six dispatch focus areas against the code. Result: **faithfully implemented**, with one divergence (§3 Y1).

**(1) Posture-B subprocess isolation reuses ADR-027 D4; parent never imports fetched code.** Verified:
- `subprocess_trust.py` — `build_scoped_env` (allowlist `_SAFE_ENV_KEYS` + `server_cfg.env` + optional `api_key_env`, never full `os.environ`); `_terminate_subprocess` (SIGTERM→SIGKILL escalation via **process group**, `start_new_session=True` so `pgid==pid` → `killpg` reaps the whole tree, no orphan), shielded with `anyio.CancelScope(shield=True)` so it survives the `asyncio.wait_for` cancellation; **`_kill_watchdog(pid)` LAYER-1 orchestrator kill** (post-teardown `os.kill(pid,0)` existence probe → `SIGKILL` + `waitpid` reap — the R0-B Y1→α addition, beyond the SDK's LAYER-2 teardown).
- `plugins/code.py` — `_PostureBFn` spawns `sys.executable _harness.py <module_file> <callable>` and drives it over the **reused** MCP stdio client; **the parent never imports plugin code** (the `importlib`/`exec_module` runs in the child harness). Per-call bounded `_CALL_TIMEOUT=30.0` via `run_sync`; fail-closed (timeout→`MCPTimeoutError`→`TOOL_FAILED`; `isError`→`RuntimeError`→`TOOL_FAILED`). The G1 seam-split landed: `_async_bridge` (transport-agnostic sync/timeout/fail-closed) vs `subprocess_trust` (subprocess-only env/kill).
- Discriminating tests present + green: `pb3` (SIGTERM-ignoring plugin killed by watchdog, no orphan), `pb2` (hung→timeout→`TOOL_FAILED`), `pb5` (env-leak probe — child env lacks orchestrator secrets).

**(2) fetched → Posture B + segregated loader + un-launderable provenance.** Verified:
- `provenance.py` — `PluginProvenance = Literal["operator_placed","fetched"]`, **host-set by origin** (which discovery root), never plugin-claimed.
- `loader.py:357-362` — `if provenance == "fetched" and activation_entry is None → refuse` (fail-closed, ADR-031 D4); `:178` provenance assigned at candidate creation by root; `:520-524` **disjoint-root runtime guard** (`plugins_dir.resolve().relative_to(fetched_plugins_dir.resolve())` → `ValueError` on overlap).
- Tests green: `pv2` (fetched-no-activation refused), `pv4`/`pv7` (laundering impossible / disjoint-root guard), `pv5` (fetched runs Posture B). **Caveat → Y1:** the "test-enforced unreachable" enforcement is weaker than ADR-031 D3 inscribes, because the impl removed the in-process path entirely (see §3).

**(3) RB-FS/NET residual — honest, no fake sandbox, no over-reach.** Exemplary. ADR-031 **D1a** inscribes the residual exactly: "Posture B is **NOT a syscall sandbox** … an activated fetched plugin's child still runs with the host user's full filesystem-read + outbound-network privilege — it can `open()` `~/.ssh/id_rsa` and `socket()`/`requests.post` to exfiltrate … real FS/network sandboxing (container/seccomp/UID/chroot) is **DEFERRED to P4**." The Status line Accepts `RB-FS/NET` explicitly. And the impl **does not** smuggle in any FS/network isolation — `subprocess_trust.py` has no chroot/seccomp/namespace machinery (correct: the residual is named, not faked). This is the dispatch's focus-3 done right.

**(4) Remote MCP: verify=True + URL allowlist + verify=False banned.** Verified:
- `transport.py` — `from mcp.client.streamable_http import streamable_http_client` (the **non-deprecated** symbol — Y1-on-plan → α); host-built `httpx.AsyncClient(verify=True, headers=…, timeout=…)` (bring-your-own-client contract); `Authorization: Bearer` from `api_key_env` (HR#5, never inline/logged).
- Global scan: **no `verify=False` anywhere in `src/`.** `tests/mcp/test_constitution.py::test_constitution_c6_no_verify_false_in_remote_transport` regex-bans `verify=False`/`"verify":False` in `mcp/` (R0-B Y4→α). URL allowlist = the reused pre-classify mechanism (config entries; ADR-027 D3, no second surface); `config.py` enforces `https://` for `streamable_http`.

**(5) Downstream-of-gate / empty-diff / no new LLMPurpose.** Verified rigorously:
- `tools/executor.py::_execute_local_call` is **byte-unchanged**; the 57-line diff is in the **caller** `execute_pending_tool_calls`, adding `MAX_POSTURE_B_CALLS_PER_TURN=10` (the **R0-B Y6→α** liveness cap — confirmed sanctioned in `architect-routing-on-plan.md:50`), structurally the twin of the pre-existing `MAX_MCP_CALLS_PER_TURN`. A liveness/resource cap, not a tier/routing decision.
- `tests/tools/test_constitution.py::test_t3b_executor_empty_decision_diff` **AST-parses** `_execute_local_call` and asserts zero `decide_tier`/`emit_gate_decision`/`score`/`gate`/`select_model_and_provider` references (with the comment "Posture-B cap must be in execute_pending_tool_calls, NOT in _execute_local_call"). Frozen-`LLMPurpose` guards in all three constitution suites (mcp c4 / plugins p3 / tools t3); `p5` is a non-vacuous scan that requires the new modules (incl. `provenance.py`) to be in-scope.

**(6) Plant-bypass / provenance-spoof / env-leak.** Closed:
- Provenance-spoof → un-launderable (disjoint roots + origin-set, §(2)).
- Env-leak / c2 → `loader.py:444-446` sources the child's `plugin_subprocess_env` from `activation_entry.plugin_subprocess_env` (**operator-authored**) for fetched, `{}` for operator-placed; the fetched **manifest cannot self-request env/secret keys** (Y4-on-plan → α; `provenance.py` docstring + `ActivationEntry` inscribe it); `pb5` probes it.
- Malicious-bundle → `fetch.py` digest-**before**-extract (R0-B Y5→α: "the ordering IS the security property"), https-only, path-traversal guards (`..`, absolute, symlink/hardlink rejected), atomic staging + cleanup so `fetched_plugins_dir` is never touched by a failed fetch (R0-B Y7→α), fail-closed throughout.

## 3. Findings

### 🔴 B1 (blocking) — canonical `mypy --strict` gate fails
Covered in §1. `tests/plugins/test_posture_b.py:153` + `:172` carry unused `type: ignore` comments → `mypy` exit 1. The branch cannot merge while the mandatory gate is RED. **Fix:** delete the two comments (2 lines); re-run `uv run mypy` to confirm green. Mechanical — a junior rework, no design input needed. (Root cause is likely a local mypy-version/scope skew when the junior gated; flagging so the junior re-runs the *canonical* invocation.)

### 🟡 Y1 (needs_architect) — Posture A retired entirely (B-for-all); diverges from Accepted ADR-031 D3 + exposes an ADR internal contradiction
**Evidence:** `plugins/code.py` has **no in-process `importlib` path** — `load_plugin_code` builds **only** `_PostureBFn` subprocess closures, for **every** plugin. Tests confirm operator-placed plugins now run Posture B: `pv1` ("operator-placed loads", as a `_PostureBFn`), `pv8` ("operator-placed get **empty env**" — i.e. via the subprocess path).

This **contradicts the freshly-Accepted ADR-031 D3**, which inscribes: *"operator-placed → Posture A remains valid … the P3.5 in-process path is **preserved** for operator-placed plugins (**no regression**)"* and *"the in-process `importlib` path **still physically exists in the module** (it serves operator-placed plugins)"* — the latter being the literal substrate of the **R0-B-R2→α** "test-enforced unreachable" design (an existing in-process path + a discriminating test that fetched never reaches it). Yet the ADR's own **Consequences** says the opposite: *"the in-process convenience of Posture A is **gone**."* So:
1. **ADR-031 is internally inconsistent** (D3 "A preserved / path exists" vs Consequences "A is gone") — must be reconciled regardless.
2. The **R0-B-R2 enforcement is weaker than inscribed**: with no in-process path at all, `pv5`'s "importlib never called at load time" now holds for *all* plugins, so it no longer **discriminates** fetched from operator-placed by posture (it still checks the `_PostureBFn` marker, so not vacuous — but the "never reaches the in-process loader" design the architect routed is moot because that loader no longer exists).
3. **P3.5 behavior change**: operator-placed plugins must now be **subprocess-safe** (no shared in-process state / fast in-proc calls) — the "no regression" promise is broken.

**Direction is safer** (B-for-all = strictly more isolation), so this is not a security regression — but it is an **unauthorized divergence from an Accepted ADR** (the junior simplified past the ratified contract without re-routing; cf. CLAUDE.md "surface, don't improvise"). **Lean: α** — bless B-for-all: amend ADR-031 D3 to match (Posture A retired; fetched→B enforced by "the loader only ever builds `_PostureBFn`"; reconcile the D3-vs-Consequences contradiction; acknowledge the operator-placed subprocess-safety change as intended). **vs β** — restore the in-process path for operator-placed per the Accepted D3 (makes the discriminating test meaningful + honors "no regression"). **Architect's call** — it turns on whether any operator-placed plugin is expected to rely on in-process execution, and on which side of the ADR contradiction is canonical.

### 🟢 G1 (advisory) — fetch bundle size cap is post-download-into-memory
`fetch.py:_download` returns `response.content` (whole body into memory), and `_MAX_BUNDLE_BYTES` (50 MB) is checked **after** that (`:171`). So the cap bounds disk-write, not **peak memory** — a compromised pinned source could stream a multi-GB body and OOM the orchestrator before the check. Defensible for the MVP (the source is operator-pinned + digest-checked), but a `Content-Length`-aware / streaming bound would close the OOM vector. Senior/junior may absorb or defer; no architect decision needed.

## 4. Routed-finding absorption audit (all plan-stage findings → α; verified in code)

| Routed (→α) | Landed in impl |
|---|---|
| R0-A Y1 — non-deprecated SDK client | ✅ `transport.py` `streamable_http_client` + host-built `httpx.AsyncClient(verify=True)` |
| R0-A Y2 / R0-B R1 — RB-FS/NET honest inscribe | ✅ ADR-031 D1a; no fake sandbox in `subprocess_trust.py` |
| R0-A Y3 / R0-B Y3 — un-launderable provenance, segregated root | ✅ `loader.py:520-524` disjoint guard; `provenance.py` origin-set |
| R0-A Y4 / R0-B Y2 — fetched-env operator-authoritative | ✅ `loader.py:444-446` from activation entry; manifest can't override |
| R0-B R2 — "test-enforced unreachable" + segregated loader | ⚠️ partially — segregated loader ✅, but the in-process path was removed entirely → enforcement weaker than inscribed (Y1) |
| R0-B Y1 — orchestrator kill watchdog | ✅ `subprocess_trust.py::_kill_watchdog` LAYER-1 |
| R0-B Y5 — digest-before-extract | ✅ `fetch.py:170-187` |
| R0-B Y6 — per-turn Posture-B cap | ✅ `executor.py` `MAX_POSTURE_B_CALLS_PER_TURN` |
| R0-B Y7 — atomic-staging cleanup | ✅ `fetch.py` try/except/finally, `fetched_plugins_dir` untouched on failure |
| G1-on-plan — seam cohesion split | ✅ `_async_bridge` + `subprocess_trust` |

## 5. Hand-off to impl-stage dual-lens R0-B

R0-B re-probes the subprocess boundary / provenance enforcement / fetch integrity on the implementation (mandatory, `requires_cross_family_review: true`). The two places I'd most want a cross-family second look: **(a)** the kill/watchdog/shield interaction under real cancellation (does `_terminate_subprocess`'s `shield=True` + the LAYER-1 watchdog actually guarantee no-orphan when `asyncio.wait_for` fires mid-`call_tool`? — `pb3` covers the SIGTERM-ignoring case; a SIGKILL-surviving / fork-bomb child is the harder probe), and **(b)** the Y1 Posture-A-removal — whether B-for-all introduces any operator-placed regression R0-B can construct. If R0-B converges on Y1 independently, that strengthens the α lean.

---

**Bottom line for the architect:** strong impl, spine intact, all routed findings absorbed, RB-FS/NET honest. **Blocked on two things:** B1 — fix the 2 unused `type: ignore` so the canonical `mypy` gate goes green (mechanical, junior); Y1 — route the Posture-A-retirement divergence (α bless-B-for-all + fix the ADR-031 D3/Consequences contradiction, vs β restore-A-for-operator-placed). I await your call + the R0-B synthesis.
