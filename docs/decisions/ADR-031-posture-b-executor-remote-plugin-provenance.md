# ADR-031: Posture-B Subprocess Plugin Executor + Remote-Plugin Provenance

**Status:** Proposed — 2026-06-04 (senior-drafted for P3.7-remote; dual-lens R0-B mandatory before architect review — `requires_cross_family_review: true`). The architect ruled **B-coupled** (the Posture-B executor + the actual remote-fetch ship together) and **reuse-the-MCP-subprocess-mechanism** (no second subprocess protocol); this ADR drafts the contract for architect Accept after the plan-stage dual-lens. Not yet ratified.

**Scope:** P3.7-remote (P3 Wave-3 closer, heavy half) — the **A→B migration** of the plugin tool-code executor (in-process `importlib` → killable subprocess) **and** the **remote-plugin provenance / consent** surface it gates. Governs: the Posture-B execution model (D1), the reuse of the ADR-027 MCP-subprocess machinery (D2), the provenance model (D3), the activation/consent posture for untrusted provenance (D4), the minimal remote-fetch contract (D5), the demo (D6), and the constitutional carry-forward (D7). Does **NOT** govern: the autonomy gate decision logic (`score`/`decide_tier`/`emit_gate_decision`/`process_tool_calls` — **unchanged**, ADR-027 D2 / ADR-028 D6); the runtime executor's dispatch (`tools/executor.py::_execute_local_call` — **unchanged**; a Posture-B plugin tool runs through it via the `local_tools` registry, no executor edit); the remote MCP *transport* (ADR-032); a plugin registry/marketplace, remote upgrade/version-coexistence/uninstall (deferred P4); GUI plugin management (frontend track).

## Context

ADR-029 D4 Accepted **Posture A (in-process import) only because plugins are operator-placed — curation IS the trust boundary** — with three exposures fully inscribed and Accepted: **L1** (no technical isolation + zero env protection: in-process plugin code reads all `os.environ`), **L1b** (import-time top-level code runs ungated at boot), **L2** (Posture A VOIDS ADR-028 D5's absolute per-turn liveness bound — a buggy/hung in-process tool blocks the `max_workers=1` writer for **every** room, with no cap and no kill). ADR-029 D4 also **reserved Posture B as the REQUIRED posture once provenance becomes untrusted (P3.7 remote)** and itemized the A→B migration surface (Reversibility table / R0-B Y6): `plugins/code.py` (`importlib` + `LocalToolFn`) → a subprocess protocol; `LocalToolFn` → a subprocess-runner adapter.

Verified `origin/main` @ cbadf6d:
- `plugins/code.py:42-104` is the Posture-A in-process loader (`spec_from_file_location` + `exec_module` — module top-level runs in the **orchestrator process**; the L1/L1b/L2 surface).
- `tools/executor.py:297-347` (`_execute_local_call`) looks up `local_tools[name]` and calls `impl(params)`, wrapping every call fail-closed → `TOOL_FAILED` (ADR-028 D4). It is **mechanism-agnostic**: it does not care whether `impl` runs in-process or launches a subprocess.
- `mcp/transport.py` already implements the **exact** subprocess trust machinery B needs: `_build_scoped_env` (minimal-scoped env, never the orchestrator's full `os.environ` — the c2 lesson), `asyncio.wait_for`-bounded sync calls, and stdio_client kill-no-orphan teardown (ADR-027 D1/D4). ADR-029 D4 itself observed *"a Posture-B plugin executable tool ≈ a bundled MCP server."*
- `plugins/loader.py` discovers plugins by **presence** in `plugins/` (`_discover_and_validate`, `D5 presence=opt-in`) and has **no notion of provenance** — every plugin is implicitly operator-placed.

**The crux this ADR inscribes.** A **fetched/remote** plugin is **not operator-placed**, so curation — the entire basis of the Posture-A Accept — **no longer holds**. Therefore **Posture A is constitutionally invalid for remote provenance**: shipping remote-fetch on the in-process executor is the L1 (full host privilege + every secret) + L1b (import-time ungated) + L2 (server-wide DoS) surface **with no curation backstop** — a real vulnerability, not an accepted MVP posture. **Posture B (killable subprocess, scoped env, bounded-timeout, fail-closed) is REQUIRED, not optional** — the architect already ruled this in ADR-029 D4. B1 is therefore the **enabling precondition** for any remote-plugin capability; the two are coupled.

## Hard requirements — the constitutional spine (NON-NEGOTIABLE; carries ADR-005/006/027/028/029 forward — *not* new choices)

1. **The gate stays the sole chokepoint — unchanged.** A Posture-B/remote plugin tool routes through the **same** code gate (`process_tool_calls → emit_gate_decision`); tier from code-classified reversibility; unregistered/unclassified → `UnknownToolError` → refused (fail-closed). The empty-gate-diff invariant (ADR-027 D2) holds; this ADR extends it to an **empty-gate-diff-with-a-new-executor-mechanism**.
2. **The executor's decision path is unchanged.** B1 swaps the *mechanism* of a plugin `LocalToolFn` (in-process function → subprocess-launching closure); `tools/executor.py::_execute_local_call` is **byte-unchanged** (it still calls `impl(params)`). The empty-executor-diff invariant (ADR-028 D6) holds.
3. **Self-asserted tier is never authoritative.** A fetched plugin's claimed reversibility is advisory-capped → host-authoritative-or-default-0 (ADR-029 D5). A remote source cannot self-classify a write tool to dodge `HARD_CONFIRM`.
4. **Fetching ≠ trusting (discovery ≠ permission, one level up).** Remote/fetched plugin code is **never** auto-trusted on fetch; the *consent granularity changes* (presence=opt-in → an explicit activation entry, D4) but never to "auto-trust on fetch." No remote infra introduces an LLM routing/judgment decision; **no new routing/judgment `LLMPurpose`** (D7).
5. **Credential safety + scoped env become REAL.** The Posture-B subprocess gets a **minimal scoped env** (the c2 env-leak lesson) — and Posture B is exactly what makes the env boundary **real** for plugin code (it is **zero** under Posture A, ADR-029 D4 L1).
6. **Fail-closed everywhere.** Unverified provenance / missing activation / fetch failure / TLS failure / integrity mismatch / subprocess crash-hang-timeout-orphan → **refuse / `TOOL_FAILED`**, never degrade-open, never crash/hang the orchestrator.
7. **Restore the ADR-028 D5 liveness bound.** The killable subprocess re-establishes the absolute per-turn bound Posture A voided (L2): a Posture-B tool call is bounded-timeout + killable, so a hung/runaway plugin tool does **not** block the single writer indefinitely.

## Decisions

### D1. The Posture-B execution model — killable subprocess, parent never imports plugin code

`plugins/code.py` is reworked: instead of `importlib`-ing the plugin tool module **in the orchestrator process**, the loader produces, for each `tool_impls` entry, a **`LocalToolFn` that launches a subprocess** running the plugin tool code. The subprocess gets a **minimal scoped env** (HR#5), a **bounded timeout** (HR#7), is **killed-with-no-orphan** on timeout/hang (HR#6), and **fails closed → `TOOL_FAILED`** on crash/timeout/malformed output. **The parent process never imports the plugin module** — the `importlib`/`exec_module` of plugin code happens **in the child** (a generic harness, D2), so L1 (privilege/env), L1b (import-time code), and L2 (unkillable hang) are all resolved: import-time code now runs **inside the scoped, killable child**, not the orchestrator.

The resulting `LocalToolFn` drops into the **same** `local_tools` registry the executor already consumes — `_execute_local_call` runs it **unchanged** (HR#2). What changes is *what a plugin `LocalToolFn` is*, not how the executor dispatches it.

### D2. Reuse the ADR-027 MCP-subprocess mechanism — one subprocess protocol, not two (architect-ratified)

**The architect ruled: reuse the MCP-server subprocess machinery; do not build a second subprocess protocol.** A Posture-B plugin executable tool is treated as **a local stdio MCP server** (ADR-029 D4's "≈ a bundled MCP server", made literal). The shared trust machinery — `_build_scoped_env`, the `asyncio.wait_for`-bounded sync bridge, the kill-no-orphan teardown — is **extracted from `mcp/transport.py` into a reusable seam** (e.g. `mcp/subprocess_trust.py`) that **both** the MCP transport and the Posture-B plugin executor use. A generic **child harness** wraps a plugin's `<module>:<callable>` (`tool_impls` ref) as a stdio MCP-server child: the harness imports the callable **in the child**, exposes it as a single MCP tool, and the parent drives it via the reused stdio client. The extraction is a **pure refactor** (MCP transport behavior unchanged — the empty-behavior-diff is a forcing function, plan P3.7-remote-4).

**Consequence (inscribe):** Posture B's marginal value over "just bundle an MCP server" is thin (ADR-029 D4 observed this) — but `tool_impls` remains the manifest surface for **packaging convenience** (a plugin author writes a Python callable, not a full MCP server); the harness is what bridges it to the one subprocess protocol. The cost (a plugin tool must now be subprocess-safe) is the price of the real isolation boundary the remote/untrusted case requires.

### D3. The provenance model — operator-placed vs fetched; fetched VOIDS curation

The loader gains a **provenance** mark per plugin: `operator-placed` (present in the local `plugins/` dir — the P3.5 case) or `fetched` (obtained via the remote-fetch mechanism, D5). **The provenance determines the required posture:**

- `operator-placed` → Posture A remains valid (curation holds; ADR-029 D4 unchanged) **or** Posture B (if the operator opts a local plugin into subprocess isolation). The P3.5 in-process path is **preserved** for operator-placed plugins (no regression).
- `fetched` → **Posture B is FORCED** (curation void — HR, the crux). A `fetched` plugin's `tool_impls` running in-process is **structurally unreachable**: the loader refuses to register a `fetched` plugin's code via the Posture-A path. A test asserts the in-process loader is never invoked for `fetched` provenance.

Provenance is **not** plugin-self-asserted (a plugin cannot claim `operator-placed` to dodge Posture B) — it is set by **how the loader obtained the plugin** (local dir vs fetch), which is host-authoritative (HR#3 analog, one level up).

### D4. The activation / consent posture for untrusted provenance — fetching ≠ trusting

ADR-029 D5 deferred "a discovered-but-not-activated registry" to P3.7 "when provenance becomes untrusted." This ADR lands it as the **minimal operator-pinned activation allowlist**:

- A `fetched` plugin is **discovered-but-not-activated** by default — fetching it does **not** load it.
- It loads **only** if the operator adds an explicit **activation entry** pinning its **source** (the `https://` fetch URL) **and an integrity digest** (e.g. a SHA-256 of the bundle). The fetched bundle **must match** the pinned digest or it is **refused** (HR#6).
- This is the **remote analog of presence=opt-in** (ADR-029 D5): for the local dir, presence in `plugins/` IS the operator's opt-in; for fetched provenance, **the pinned activation entry IS the opt-in** — *fetching ≠ trusting*. The consent stays **operator-authoritative + fail-closed**, with **no registry/marketplace** (deferred P4).
- All the per-surface guards (gate, allowlist, advisory-cap, fail-closed loading, collision-check) from ADR-029 still apply unconditionally **on top of** activation.

### D5. The minimal remote-fetch contract — pinned source, integrity-checked, fail-closed

A new `plugins/fetch.py` fetches **one** plugin bundle from a **pinned `https://` source** into a staging dir:

- **TLS-verified** (`https://` only — a non-`https://` source is refused; TLS-verify failure → refused, HR#6).
- **Integrity-checked** against the activation digest (D4) — a mismatch → refused, nothing staged.
- **Fail-closed** on unreachable / fetch error / malformed bundle — nothing staged, no orchestrator crash (per-plugin isolation, ADR-029 D6 analog).
- The staged bundle is marked provenance `fetched` (D3) → Posture B forced + activation required.

This is the **minimal pinned-source fetch only**. **Out (deferred P4):** a registry/marketplace, plugin upgrade / version coexistence / uninstall, auth beyond the bundle integrity check.

### D6. The demo — one fetched-and-Posture-B plugin, end-to-end + fail-closed

ONE demo (mirroring P3.4/P3.5's one-demo discipline): a plugin **fetched** (pinned source + digest) → **activated** → run under **Posture B** (subprocess) end-to-end → `TOOL_RESULT`. The demo also proves the **fail-closed paths**: a subprocess crash/hang/timeout → `TOOL_FAILED` + kill-no-orphan (the D5-bound restoration); an **env-leak probe** asserts the child env lacks the orchestrator's secrets (the c2 lesson made real); an **unactivated** fetched plugin → refused; a **digest-mismatch** → refused.

### D7. Constitutional carry-forward — the constitution test extends to the new code

The new code (`plugins/fetch.py`, the provenance/activation module, the subprocess-runner + harness) makes **no** autonomy/routing/model decision. The `plugins/` + `mcp/` + `tools/` constitution tests extend to forbid the new modules referencing `decide_tier`/`emit_gate_decision`/`score`/`gate`/`select_model_and_provider`, forbid any `llm/` provider call, and assert the frozen `LLMPurpose` set is unchanged (**no new purpose**). Provenance + activation + fetch are deterministic code/config, never an LLM judgment (HR#4). This ADR **binds** ADR-005/006 (gate + fail-closed), ADR-027 D2/D4 (feed-the-gate-unchanged + the trust machinery reused), ADR-028 D5/D6 (the liveness bound restored + the executor invariants), ADR-029 D4/D5 (the A→B migration + presence→activation) — it does **not** restate them.

## Considered alternatives

- **B-executor-first (build + test Posture B on a local plugin; defer remote-fetch)** — **Overridden by the architect** (B-coupled ruled). Recorded: executor-first is lower-risk (the migration is the hard, testable part) but leaves the remote-plugin story incomplete for P3's last cut; the architect ruled the full untrusted-remote-plugin story end-to-end.
- **Build a distinct plugin-subprocess protocol** (not the MCP one) — **Rejected** (D2, architect-ratified): a second subprocess surface duplicates the dual-lens-vetted scoped-env/kill/timeout machinery; reuse is maximal-reuse, one trust boundary.
- **Keep Posture A for fetched code, rely on curation** — **Rejected, constitutionally** (the crux): a fetched plugin is not operator-placed; curation does not hold; Posture A for remote provenance is the L1/L1b/L2 surface with no backstop.
- **A signature / keyring trust model for fetched plugins** (vs. operator-pinned source+digest) — **Deferred** (D4): heavier (key distribution/rotation); the pinned-source+digest activation entry is the minimal operator-authoritative consent for the MVP. (Surfaced for architect confirmation, plan §5.2.)
- **A full plugin registry/marketplace + lifecycle** — **Deferred P4** (D5): out of the MVP's minimal-fetch scope.
- **In-process import isolation (RestrictedPython / audit hooks)** — **Rejected** (carried from ADR-029 D4 Posture C): not a real boundary in CPython.

## Consequences

**Easier:** remote/untrusted plugin code reaches the system through a **real** technical isolation boundary (subprocess + scoped env + kill-no-orphan), reusing the **one** dual-lens-vetted MCP-subprocess machinery; the ADR-028 D5 liveness bound is **restored** (L2 resolved); the env boundary is **real** for plugin code (L1 resolved); the executor + gate are untouched.

**Harder:** a plugin tool must now be **subprocess-safe** (the in-process convenience of Posture A is gone — the price of real isolation); a new provenance + activation + fetch surface to get fail-closed; the harness bridging `tool_impls` → a stdio MCP child is new machinery (though it reuses the transport seam).

**Neutral:** Posture A is **preserved** for operator-placed plugins (no P3.5 regression); Posture B is **forced** only for fetched provenance; the activation allowlist is the minimal operator-pinned consent (a registry is additive later).

## Reversibility

| Decision | 6-month reversal cost |
|---|---|
| D1 Posture-B execution model | **Do-not-reverse** — the required posture once provenance is untrusted (ADR-029 D4); reverting to in-process for fetched code re-opens L1/L1b/L2 with no curation. |
| D2 reuse-the-MCP-subprocess-mechanism | **Medium** — the extracted seam is a refactor; building a second protocol later is additive but discouraged (architect-ratified reuse). |
| D3 provenance model | **Do-not-reverse** — fetched-voids-curation is the constitutional crux. |
| D4 activation/consent (pinned source+digest) | **Medium** — moving to a signature/keyring model is a consent-granularity change (P4); fetching≠trusting is do-not-reverse. |
| D5 minimal remote-fetch | **Low** — a self-contained module; a registry/marketplace is additive. |
| D6 demo | **Trivial** — content + tests. |
| D7 constitution carry-forward | **Do-not-reverse** — gate-sole-surface / no-new-purpose / fail-closed. |

## References

- `docs/process/architect-briefs/P3.7-remote.md` (the ⭐⭐ spine + the crux + the (a)/(c)/(d) decisions; B-coupled + reuse-MCP-subprocess ratified).
- `docs/process/senior-plans/P3.7-remote.md` (this ADR's plan; atomic graph P3.7-remote-1..9, the §5 architect calls).
- `docs/process/reviews/P3.7-remote/external-r0b-prompt.md` (dual-lens R0-B — malicious-fetched-code / subprocess-escape / TLS-bypass / provenance-spoof / env-leak / autonomy-bypass cross-family lens).
- **ADR-029** D4 (Posture A-now-B-later; **B REQUIRED once provenance untrusted**; the itemized A→B migration; L1/L1b/L2) + D5 (presence=opt-in valid only for operator-placed; the activation/allowlist for untrusted provenance) + scope (remote install/registry/fetch deferred to P3.7 — **this ADR**). **ADR-028** D5 (the single-writer per-turn liveness bound Posture B **restores**) + D4 (per-call fail-closed) + D6 (executor constitution test). **ADR-027** D1 (the stdio sync-bridge + bounded-timeout) + D4 (the trust machinery **reused**, D2). **ADR-005/006** (gate + fail-closed). **ADR-032** (the remote MCP *transport* — the sibling surface in this slice).
- `src/orchestrator/plugins/code.py` (the Posture-A in-process executor B1 replaces) + `plugins/loader.py` (provenance/activation added) + `tools/executor.py::_execute_local_call` (the `local_tools` path — **unchanged**) + `mcp/transport.py` (the subprocess trust machinery **extracted + reused**, D2). `docs/process/dual-lens-r0b.md`. The P2.7-S3 c2 env-leak precedent (now at untrusted-remote scale).
