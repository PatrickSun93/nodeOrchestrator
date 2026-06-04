---
review: R0-A-on-plan
task_id: P3.7-remote
stage: plan
reviewer: architect-partner
date: 2026-06-04
verdict: needs_architect
reviewed_artifacts:
  - docs/process/senior-plans/P3.7-remote.md
  - docs/decisions/ADR-031-posture-b-executor-remote-plugin-provenance.md
  - docs/decisions/ADR-032-remote-mcp-transport.md
findings:
  blocking: 0
  needs_architect: 4
  advisory: 1
note: >-
  Spine carries forward cleanly (gate sole-chokepoint, allowlist, fail-closed,
  no-new-LLMPurpose, D5-bound restoration, Posture-B reuse-not-second-protocol,
  bind-not-restate — all intact and verified against origin/main @ cbadf6d).
  No blocking breach. The 4 Y findings are contract/impl-contract tightenings on
  the project's largest trust surface, each mapping onto a dispatch plant-bypass
  sub-lens (TLS, host over-privilege, provenance-spoof, env-leak/c2); route
  before architect Accept. Dual-lens R0-B should independently corroborate Y2-Y4.
---

# R0-A-on-plan — P3.7-remote (Posture-B subprocess executor + remote MCP transport)

**Verdict: `needs_architect`** — 4 Y findings (0 blocking), 1 advisory. The plan + both Proposed ADRs are fundamentally sound: the constitutional spine is carried forward correctly, the MCP-subprocess reuse is genuine (not a second protocol), bind-not-restate is clean, and RC-23 is satisfied. The Y findings are **tightenings to route before Accept** on the security crux — they are not spine breaches, but the dual-lens + this review exist precisely to harden the largest trust surface in the project before it is ratified.

## 1. What I verified (cites checked against `origin/main` @ cbadf6d)

Every live-surface cite in the plan/ADRs checks out **except one** (Y1):

| Claim | Verified |
|---|---|
| `plugins/code.py:42-104` is the Posture-A in-process loader (`spec_from_file_location`+`exec_module`; L1b comment in-code) | ✅ exact |
| `tools/executor.py::_execute_local_call` is mechanism-agnostic (`impl = local_tools.get(name); output = impl(params)`) — a subprocess-launching `LocalToolFn` drops in unchanged | ✅ exact (empty-executor-diff invariant is real) |
| `mcp/transport.py` holds `_build_scoped_env` + `asyncio.wait_for`-bounded sync bridge + stdio kill-no-orphan | ✅ exact |
| `mcp/config.py` `MCPServerConfig` is stdio-shaped, frozen + `extra="forbid"` | ✅ exact |
| `config/mcp_servers.yaml` all-stdio | ✅ (3 entries, all `transport: stdio`) |
| `plugins/loader.py::_discover_and_validate` discovers by **presence** (`plugins_dir.iterdir()` + `plugin.yaml`), no provenance notion | ✅ — and this grounds Y3 |
| constitution tests exist (`tests/{mcp,plugins,tools}/test_constitution.py`); `LLMPurpose` is a frozen `StrEnum` (`llm/purposes.py:25`) | ✅ — plan -9 "extend" is real, not invented |
| RC-23: both ADRs `Status: Proposed … Not yet ratified`; the only `Accepted` strings are historical references to ADR-029 D4 | ✅ clean |
| `streamable_http.py:686` `streamablehttp_client(...)` yields a 3-tuple | ⚠️ accurate **but the symbol is `@deprecated`** → **Y1** |

## 2. Spine carry-forward — the dimension sweep (all intact)

The dispatch asked me to carry the spine forward at maximal trust surface. Sweep result — **no breach**:

- **(1) Remote does not bypass the allowlist.** ADR-032 HR#3 + D1: the set of `streamable_http` entries **is** the URL allowlist (same `tools` pre-classify mechanism, ADR-027 D3 lifted to URLs — alternatives explicitly reject a "second decision surface"); non-allowlisted URL → refused; TLS-on (HR#6); `api_key_env` (HR#5). Fetched plugins → Posture-B forced (ADR-031 D3). Plan -3 acceptance includes the non-allowlisted-URL + TLS-fail refusals. ✅
- **(2) Posture B reuses the MCP-subprocess mechanism — one protocol, not two.** ADR-031 D2 + plan -4: `_build_scoped_env` + bounded sync-bridge + kill-no-orphan extracted into a shared seam, **pure refactor** with an empty-behavior-diff forcing function (`tests/mcp/*` green unchanged). The harness wraps `tool_impls`'s `<module>:<callable>` as a stdio MCP child; parent drives via the reused client. Genuine reuse. ✅ (one cohesion nit → G1)
- **(3) Gate/executor decision logic unchanged + no new LLMPurpose.** ADR-031 HR#1/HR#2/D7, ADR-032 HR#1/D5, plan -9. `_execute_local_call` verified byte-stable under a subprocess `LocalToolFn`; empty-gate-diff held; frozen-`LLMPurpose`-set assertion extended to the new modules. ✅
- **(5) ADR-031/032 ↔ ADR-027/028/029 — bind, don't restate.** ADR-031 D7 + ADR-032 D5 both carry explicit "**binds** … does **not** restate" language, with Reference sections citing the bound decisions by number (005/006/027 D2-D4/028 D5-D6/029 D4-D5). No re-litigation. ✅

**(4) plant-bypass** is where the four Y findings live — §3.

## 3. Findings (architect routes; I surface leans, I do not decide)

### 🟡 Y1 — ADR-032 D2 + plan -2 pin a `@deprecated` SDK symbol whose non-deprecated replacement has a materially different credential/TLS-injection shape

**Evidence:** `.venv/.../mcp/client/streamable_http.py:685` is `@deprecated("Use `streamable_http_client` instead.")`, immediately above the pinned `streamablehttp_client` (line 686). The non-deprecated `streamable_http_client` (line **601**) takes **no** `headers` / `timeout` / `auth` / `verify` kwargs — only `http_client: httpx.AsyncClient | None`. Its docstring: *"To configure headers, authentication, or other HTTP settings, create an httpx.AsyncClient and pass it here."*

**Why it matters:** ADR-032 D2 inscribes the credential model as *"build `{"Authorization": …}` … pass as `headers`"* (HR#5) and TLS as *"rely on the SDK/httpx default `verify=True`"* (HR#6). That maps onto the **deprecated** client's kwargs. On the **current** client the junior must construct the `httpx.AsyncClient` themselves — so `verify=True`, the auth header, and the timeout become the **junior's explicit responsibility**, not a factory default. "Rely on the default" is a weaker guarantee on the bring-your-own-client path, and this is a TLS-bypass-adjacent surface (a stray `verify=False` or a missing default lands here). ADR-032 is the inscribe-before-producer contract (D1 reversibility: P4 binds the remote config shape), so pinning the deprecated symbol + a credential/TLS-injection model that doesn't match the current SDK is a contract defect to resolve **before** Accept — not a downstream impl nit.

**Lean / architect call:** α — senior amends ADR-032 D2 + plan -2 to pin `streamable_http_client` and re-express credential/TLS as an explicit host-built `httpx.AsyncClient(verify=True, headers=…, timeout=…)`, updating the HR#5/HR#6 acceptance language. **vs** β — accept the deprecated symbol for the MVP, inscribe the deprecation + defer migration. The genuinely-architect input underneath: **is the MCP SDK version pinned/frozen, or subject to an upgrade that drops the deprecated symbol?** That answer decides α vs β.

### 🟡 Y2 — Posture B's residual trust surface is under-inscribed: it is process / secret / DoS isolation, **not** host-syscall sandboxing

**Evidence:** ADR-031 D1 + Consequences frame Posture B as a *"real technical isolation boundary."* It resolves L1 (env/secret), L1b (import-time runs in the child), L2 (killable → D5 bound restored). It does **not** sandbox host syscalls — an *activated* fetched plugin's child process runs with the orchestrator user's full filesystem + outbound-network privilege.

**Why it matters (dispatch lens "越权 host"):** a malicious *activated* fetched plugin can read any file / open any connection the host user can, **inside** the subprocess. The real backstops are operator-pinned activation+digest (don't run unapproved code), scoped-env (no orchestrator secrets — but see Y4), and kill (no DoS) — **not** a sandbox. For the project's largest trust surface, the ADR should inscribe this residual explicitly so a future reader does not over-read "real isolation boundary" as "sandbox." This is a do-not-over-claim honesty gap, not a code gap.

**Lean / architect call:** α — senior adds a one-paragraph residual-trust-surface inscription to ADR-031 (Posture B bounds memory/secret/DoS; host syscalls are **not** sandboxed; activation+digest is the don't-run-malicious-code authority). **vs** δ — accept as explicitly out-of-MVP-scope and capture a P4 "syscall sandbox / seccomp" candidate. Either way the residual should be **named**, not silent.

### 🟡 Y3 — provenance-laundering vector: the fetch staging location vs the presence-discovery root

**Evidence:** `plugins/loader.py::_discover_and_validate` walks `plugins_dir.iterdir()` and admits **any** subdir containing `plugin.yaml` — today all implicitly operator-placed. Plan -7 fetches a bundle *"into a staging dir"*; plan -6 marks provenance. The plan/ADR do **not** state that the staging dir is segregated from `plugins_dir`.

**Why it matters (dispatch lens "provenance 欺骗"):** if the fetch staging dir is under `plugins_dir`, a fetched bundle is re-discovered by the presence walk and marked **operator-placed** → curation laundered → Posture A wrongly re-validated for fetched code = the **exact crux breach** ADR-031 D3 exists to prevent. Provenance must be host-authoritative-by-origin; the presence-walk must be incapable of yielding `operator-placed` for a fetched-origin bundle.

**Lean / architect call:** α (clean) — senior pins in ADR-031 D3/D5 + plan -6/-7: the fetch staging dir is **NOT** under the `plugins/` presence-discovery root, and provenance is assigned by origin at discovery, so a fetched bundle can never be discovered as operator-placed. A contract tightening that directly protects the crux.

### 🟡 Y4 — for fetched provenance, env/secret injection into the Posture-B child must be operator-authoritative (activation entry), never fetched-manifest-authoritative

**Evidence:** `_build_scoped_env(server_cfg)` injects `server_cfg.env` **plus** the `api_key_env` secret — i.e., the *config* chooses which env keys + which secret reach the child. For curated stdio MCP that config is operator-authored (`mcp_servers.yaml`). Plan -4 extracts this exact seam for reuse by the Posture-B plugin executor; plan -5/-8 add an env-leak probe.

**Why it matters (dispatch lens "env-leak / c2"):** if a **fetched** plugin's own manifest can request env keys / an `api_key_env` (mirroring `MCPServerConfig.env`/`api_key_env`), a malicious fetched plugin manifests `api_key_env: <orchestrator secret>` and the scoped-env logic **hands it over** — the "minimal scoped env" becomes plugin-author-controlled. This is the c2 lesson at untrusted-remote scale. The env-leak probe as written (plan -5/-8: "child does not contain the orchestrator's secrets") tests the **default** case, not the **manifest-requests-a-secret** case.

**Lean / architect call:** α (clean) — senior inscribes in ADR-031 D4/HR#5: for fetched provenance the child env + any secret injection is operator-pinned **in the activation entry only**; a fetched plugin manifest cannot self-request env/secret keys; the env-leak probe covers the manifest-requests-a-secret attack, not just the default.

### 🟢 G1 (advisory — senior resolves, no architect call) — seam cohesion in plan -4

The bounded sync-bridge + fail-closed envelope is **transport-agnostic** — ADR-032 HR#7/D2 reuses it for the **remote, non-subprocess** path — whereas scoped-env + kill-no-orphan are subprocess-specific. Extracting all three into a module named `subprocess_trust.py` (plan -4) mis-scopes the sync-bridge: plan -2's remote branch would import a *"subprocess_trust"* helper for a non-subprocess concern. Suggest the seam separate the transport-agnostic sync/timeout/fail-closed envelope from the subprocess-only scoped-env/kill machinery (or name it neutrally, e.g. `mcp/_async_bridge` + `mcp/subprocess_trust`). Minor; does not block.

## 4. What I explicitly cleared (the sweep was real, not a rubber-stamp)

- **Gate empty-diff** — `_execute_local_call` verified mechanism-agnostic; the subprocess `LocalToolFn` claim holds. No gate/executor decision-path edit anywhere in the atomic graph.
- **Allowlist reuse** — confirmed the remote URL allowlist is the *same* pre-classify mechanism, not a second surface (ADR-032 D1 + alternatives).
- **D5-bound restoration** — plan forcing-function + -5/-8 acceptance ("hung Posture-B tool is killed, does not block the `max_workers=1` writer past the bound") is a discriminating test, correctly tied to L2.
- **RC-23** — both ADRs Proposed; no premature self-Accept.
- **Execution order** — the serial chain is genuinely serial (shared-file or output-consumption at every edge); the single-junior posture matches the brief; the -4-before-2 sequencing rationale is correct.
- **§5 architect calls** (SSE-only, consent model, demo hermeticity) are correctly surfaced by the senior as open — I am not re-deciding them; they remain architect calls alongside the Y findings.

## 5. Hand-off to dual-lens R0-B

Y2, Y3, Y4 are **cross-family plant-bypass** findings (host over-privilege, provenance laundering, env-injection authority). R0-B's malicious-fetched-code / subprocess-escape / provenance-spoof / env-leak lens should independently corroborate or extend them — if R0-B and I converge on the same vector from different families, that is a strong α signal at routing. Y1 is single-family (SDK-surface correctness); R0-B need not duplicate it.

---

**Bottom line for the architect:** sound plan, spine intact, no blocking breach. Four tightenings to route before Accept — Y1 (deprecated-symbol/credential-shape contract defect; needs the SDK-pinning answer), Y3 + Y4 (two clean-α crux protections: provenance laundering + fetched-env authority), Y2 (an inscription-honesty call: α-inscribe vs δ-defer the no-syscall-sandbox residual). I await your α/β/γ/δ string.
