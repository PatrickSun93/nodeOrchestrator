# ADR-032: Remote MCP Transport (streamable-http) + the Remote Trust Surface

**Status:** Proposed — 2026-06-04 (senior-drafted for P3.7-remote; dual-lens R0-B mandatory before architect review — `requires_cross_family_review: true`). The architect leaned **streamable-http** (SSE = legacy; confirm one or both — plan §5.1) and ratified a **new ADR** for the remote transport vehicle. Drafts the contract for architect Accept after the plan-stage dual-lens. Not yet ratified.

**Scope:** P3.7-remote — extend the **stdio-only** MCP client (ADR-027 D1) with a **remote streamable-http transport** over the existing sync bridge, with the **remote trust knobs** that stdio did not need (a remote server is *not* a user-launched local process). Governs: the remote config contract (D1), the transport runtime (D2), the remote trust surface — TLS + URL-allowlist + credential-via-`api_key_env` + bounded network timeout + fail-closed + untrusted-result limits (D3), the demo connector (D4), and the constitutional carry-forward (D5). Does **NOT** govern: the autonomy gate decision logic (`score`/`decide_tier`/`emit_gate_decision`/`process_tool_calls` — **unchanged**; B2 is a **transport** change, ADR-027 D2 holds verbatim); the tool-adapter / pre-classify-allowlist mechanism (ADR-027 D3 — **reused unchanged**, a remote tool gates exactly like a stdio one); the execution/interpret path (ADR-028 — **unchanged**); the Posture-B plugin executor (ADR-031); GUI surfacing.

## Context

ADR-027 D1 ruled the MCP client **stdio-only** for the MVP ("a local subprocess server the user launched via `npx`/`uvx` — the most-trusted tier") and **deferred SSE/streamable-http (remote = a larger trust surface) to P3.7** — this ADR. Verified `origin/main` @ cbadf6d:
- `mcp/config.py:43-60` (`MCPServerConfig`) is stdio-shaped: `transport: str = "stdio"`, `command`, `args`, `api_key_env`, `env`, `timeouts`, `tools`. No `url`; no remote validation.
- `mcp/transport.py` (`MCPTransport`) drives `stdio_client(StdioServerParameters(...))` over a sync bridge: `asyncio.wait_for`-bounded calls, `MCPTimeoutError`/`MCPConnectionError` fail-closed, `_build_scoped_env` minimal-scoped subprocess env (the c2 lesson). This sync-bridge + bounded-timeout + fail-closed envelope is **transport-agnostic** and reused for remote.
- The installed SDK exposes the remote clients: `mcp/client/streamable_http.py:686` `streamablehttp_client(url, headers=None, timeout=30, sse_read_timeout=..., auth=None)` — **yields a 3-tuple** `(read, write, get_session_id)` (vs stdio's 2-tuple); `mcp/client/sse.py` `sse_client` (legacy). `mcp/client/auth` exists (OAuth) but is **out of scope** (MVP uses the simpler `api_key_env`→header).
- `mcp/adapter.py` (the pre-classify allowlist + `mcp__<server>__<tool>` namespacing) and `mcp/execution.py` (size-limited, untrusted-framed, fail-closed result handling) are **transport-agnostic** — a remote tool flows through them unchanged.

**The change is a transport addition, not a gating change.** A remote MCP tool is **still** a `ToolCall{name="mcp__<server>__<tool>"}` that gates identically; **still** an allowlist entry (a remote server URL is the remote analog of a stdio command); **still** size-limited + content-gen-interpreted + untrusted-framed. What is genuinely new is the **remote trust surface**: a remote server is not a user-launched local subprocess, so it is **more** untrusted, and the stdio scoped-env defense does not apply (there is no subprocess) — it is replaced by **TLS verification + a URL allowlist + credential-via-header**.

## Hard requirements — the constitutional spine + the remote trust surface (NON-NEGOTIABLE; carries ADR-027 forward — *not* new choices)

1. **Remote MCP tool-calls route through the existing CODE gate, unchanged** (ADR-027 D2 verbatim). Tier from `score`+`decide_tier`; **unregistered → `UnknownToolError` → refused**. **B2 is a transport change, not a gating change** — the empty-gate-diff invariant survives.
2. **Reversibility is CODE/config-classified, not server-provided** (ADR-027 HR#2) — a remote server's protocol hints are advisory-capped → host-authoritative-or-default-0; a remote source cannot self-classify a write tool to dodge `HARD_CONFIRM`.
3. **Remote does NOT bypass the allowlist** — a remote MCP server is **still** an allowlist entry; an undeclared / non-allowlisted server URL is refused (fail-closed). **Discovery ≠ permission.**
4. **Untrusted results — *more* untrusted, not less** — a remote server is **not** a user-launched local subprocess → results stay size-limited (`mcp/execution.py` `MAX_RESULT_BYTES`), content-gen-interpreted (`TOOL_OUTPUT_INTERPRET`), untrusted-framed, no auto-action; **no tool-result drives a routing/autonomy decision**. **No new `LLMPurpose`.**
5. **Credential safety** — remote auth via **`api_key_env` indirection only** (no plaintext in config); the secret is read from the env var and passed as an **`Authorization` header**, never logged.
6. **TLS verification ON + plaintext refused** — only `https://` endpoints are connectable; TLS verification is **never disabled**; a TLS-verify failure → fail-closed (`TOOL_FAILED`/refused).
7. **Bounded network timeout + fail-closed** — every remote call is bounded (`asyncio.wait_for` over the SDK call); unreachable / TLS failure / auth failure / hang / malformed-protocol → `TOOL_FAILED`, never degrade-open, never crash/hang the orchestrator.

## Decisions

### D1. The remote config contract — `transport: streamable_http` + `url` (https-validated)

`MCPServerConfig` is extended (frozen + `extra="forbid"` preserved):
- `transport ∈ {"stdio", "streamable_http"}` (SSE deferred unless the architect rules both — plan §5.1).
- `url: str | None` — required for `streamable_http`, with an **`https://` scheme** (a non-`https://` or missing `url` for a remote entry → `ConfigError`, HR#6); `stdio` keeps requiring `command` (and `url` is null/forbidden).
- `api_key_env` is **reused** as the remote credential indirection (HR#5); `MCPTimeouts` is **reused** as the network bound (HR#7); `tools` is the **same** pre-classify allowlist (ADR-027 D3 — reused unchanged).

**The URL allowlist (HR#3):** the set of `streamable_http` server entries in the config **is** the remote allowlist (the remote analog of the stdio command allowlist) — only declared `https://` endpoints are connectable; an undeclared server name is refused, exactly as for stdio (ADR-027 D4 server-allowlist, lifted to URLs). This is **stricter** than stdio in that the scheme is constrained to `https://` and TLS is mandatory.

### D2. The transport runtime — streamable-http over the existing sync bridge

`MCPTransport` branches on `transport`. For `streamable_http`:
- Drive `streamablehttp_client(url, headers, timeout, auth)` (the SDK remote client) inside the **same** sync bridge as stdio — `loop.run_until_complete(asyncio.wait_for(<coro>, timeout=<bounded>))` (HR#7). **Note (impl):** the remote client yields a **3-tuple** `(read, write, get_session_id)` — the bridge ignores `get_session_id` (per-operation connections, no session reuse in the MVP, mirroring stdio).
- **Credential → header:** build `{"Authorization": f"Bearer {secret}"}` from `api_key_env` (read from the env var; never inline; never logged) (HR#5). There is **no subprocess env** for remote, so `_build_scoped_env` does not apply — the credential boundary is the header, not the env.
- **TLS:** rely on the SDK/httpx default `verify=True`; **never** pass `verify=False`; the `https://`-only scheme (D1) + default verification = HR#6. A TLS-verify failure surfaces as a transport exception → fail-closed (HR#7).
- **Fail-closed envelope reused:** `MCPTimeoutError` (bounded-timeout) / `MCPConnectionError` (any transport failure) → `TOOL_FAILED` via the existing `mcp/execution.py` path (unchanged).

### D3. The remote trust surface — stricter than stdio (architect-posture-nod)

The remote trust knobs are the **stdio/local posture lifted to remote endpoints, and stricter** (a remote server is more untrusted than a user-launched one):
- **TLS verification** (reject plaintext/unverified — HR#6).
- **Server-URL allowlist** (`https://` endpoints — the remote analog of the stdio command allowlist, D1/HR#3).
- **Credential via `api_key_env`** → `Authorization` header (HR#5).
- **Bounded network timeouts** (`MCPTimeouts` reused — HR#7).
- **Fail-closed** on every failure mode (HR#7).
- **Untrusted-result limits** — the **same** size-limit + untrusted-framed content-gen interpret (`mcp/execution.py`, ADR-027 D4/D6) applies; a remote result is **at least as** untrusted as a stdio one (HR#4).

The gating spine is **unchanged** — a remote MCP tool gates exactly like a stdio one (ADR-027 D2/D3 reused verbatim; HR#1–2).

### D4. The demo connector — one https:// streamable-http endpoint (hermetic CI)

ONE remote demo (the P3.4/P3.5 one-demo discipline): a `streamable_http` server entry in `config/mcp_servers.yaml` + an e2e proving the remote loop AUTO-executes a read-tier tool and the **fail-closed paths refuse**. The CI e2e uses a **hermetic local-TLS streamable-http mock** (network-independent, no auth dependency), with the "real public `https://` endpoint" captured as **documented config** (a manual/opt-in demo) — mirroring P3.4's local-subprocess demo posture (architect confirms demo shape, plan §5.3). The e2e demonstrates: read-tier AUTO end-to-end; TLS-fail / unreachable / auth-fail / non-allowlisted-URL / unclassified-tool → refused / `TOOL_FAILED`.

### D5. Constitutional carry-forward — the constitution test extends to the remote path

`mcp/` makes **no** autonomy/routing/model decision (HR#1/#4). The `mcp/` constitution test extends to the remote transport code: no `decide_tier`/`emit_gate_decision`/`score`/`gate`/`select_model_and_provider` reference, no `llm/` provider call, the frozen `LLMPurpose` set unchanged (no new purpose). This ADR **binds** ADR-027 D2/D3/D4/D6 (the gate-unchanged + allowlist + trust boundary + interpret path, all reused) — it does **not** restate them.

## Considered alternatives

- **SSE transport (instead of / in addition to streamable-http)** — **streamable-http leaned** (plan §5.1; architect confirms one or both): SSE is the legacy MCP variant; streamable-http is the current standard. Both SDK clients exist (`mcp/client/{streamable_http,sse}.py`), so SSE is additive if the architect rules it in.
- **OAuth via `mcp/client/auth`** — **Deferred:** the MVP uses the simpler `api_key_env`→`Authorization` header; full OAuth (token refresh/flows) is a later auth slice (brief §Out — "auth beyond the MVP token/TLS").
- **Disable TLS verification for self-signed dev endpoints** — **Rejected, constitutionally** (HR#6): TLS verification is never disabled; the hermetic CI mock uses a properly-verifiable local TLS cert (D4), not `verify=False`.
- **A remote-specific second decision/allowlist surface** — **Rejected** (HR#1/#3): the remote URL allowlist is the **same** pre-classify-allowlist mechanism (ADR-027 D3) lifted to URLs; no second decision surface.
- **Session reuse across remote calls** (keep the streamable-http session warm) — **Deferred:** the MVP uses per-operation connections (mirroring stdio); session reuse is a perf slice.

## Consequences

**Easier:** real remote MCP tools reach agents through the **one** existing gate + the existing allowlist + the existing untrusted-result path (no second decision surface); the sync bridge + bounded-timeout + fail-closed envelope is reused; SSE / session-reuse / OAuth are all additive.

**Harder:** a new remote trust surface (TLS + URL-allowlist + credential-header) to test fail-closed; a hermetic-TLS CI mock for the e2e (network-independence); the 3-tuple vs 2-tuple client shape is a small impl footgun (noted).

**Neutral:** streamable-http-only is an MVP scope (SSE additive); the credential boundary moves from scoped-env (stdio) to a header (remote) — different mechanism, same `api_key_env` indirection; the demo is one connector.

## Reversibility

| Decision | 6-month reversal cost |
|---|---|
| D1 remote config contract | **Low** — additive fields on a frozen model; once P4 binds the remote config shape it is a contract migration (inscribe-before-producer front-loads it). |
| D2 streamable-http over the sync bridge | **Low** — a self-contained transport branch; SSE/session-reuse are additive. |
| D3 remote trust surface (TLS / URL-allowlist / credential-header / fail-closed) | **Do-not-reverse** — the security crux for untrusted remote endpoints. |
| D4 demo connector | **Trivial** — config + tests. |
| D5 constitution carry-forward | **Do-not-reverse** — gate-sole-surface / no-new-purpose. |

## References

- `docs/process/architect-briefs/P3.7-remote.md` (the (b) remote-transport decision + the spine; streamable-http leaned).
- `docs/process/senior-plans/P3.7-remote.md` (this ADR's plan; atomics P3.7-remote-1..3 + -9, the §5.1/§5.3 architect calls).
- `docs/process/reviews/P3.7-remote/external-r0b-prompt.md` (dual-lens R0-B — TLS-bypass / remote-untrusted-result / autonomy-bypass cross-family lens).
- **ADR-027** D1 (stdio-only; **remote SSE/streamable-http deferred to P3.7** — this ADR) + D2 (feed-the-gate-unchanged — held verbatim) + D3 (the pre-classify allowlist + namespacing — **reused**) + D4 (the trust boundary the remote knobs lift) + D6 (the size-limit + content-gen interpret path — **reused**). **ADR-028** (the executor + interpret path — **unchanged**). **ADR-031** (the Posture-B plugin executor — the sibling surface in this slice). **ADR-005/006** (gate + fail-closed).
- `src/orchestrator/mcp/config.py` (`MCPServerConfig` — extended, D1) + `mcp/transport.py` (the sync bridge — the remote branch added, D2) + `mcp/adapter.py` (allowlist + namespacing — **reused unchanged**) + `mcp/execution.py` (size-limit + fail-closed result — **reused unchanged**). `mcp/client/streamable_http.py:686` (the SDK remote client). `docs/process/dual-lens-r0b.md`.
