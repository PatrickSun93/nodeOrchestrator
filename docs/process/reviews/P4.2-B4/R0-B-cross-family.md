---
task_id: P4.2-B4
round: R0-B (cross-family, impl-stage)
verdict: needs_architect
findings_count:
  red: 0
  yellow: 2
  green: 5
lenses_applied:
  - SSRF / data-exfil trust boundary (standard bypass checklist)
  - Liveness (single-writer boundedness under (1+N) passes)
review_stage: impl
impl_commits_reviewed:
  - cb28249 P4.2-B4-1: SSRF validator + resolve-then-pin transport in tools/net_trust.py
  - 9221cad P4.2-B4-2: web_fetch closure + network registry in tools/network_tools.py
  - 1975e58 P4.2-B4-4: wire build_network_tool_registry at api/app.py composition root
  - dfae12c P4.2-B4-5: per-turn network cap in executor.py + independence test
  - 9191222 P4.2-B4-6: extend snapshot_excerpt exclusion to network tools (selection.py)
  - c33e432 P4.2-B4-7: amend ADR-028 D3 + annotate ADR-031 D1a
  - f7d2909 P4.2-B4-8: constitution t10 SSRF floor
---

# R0-B cross-family review — P4.2-B4 (impl-stage)

## Lens preamble

This review applies the two lenses from the mandatory dual-lens dispatch
(`docs/process/reviews/P4.2-B4/external-r0b-prompt.md`) against the **implementation**
on `claude/P4.2-B4-impl` (7 commits). The plan-stage R0-B-on-plan found 1🔴 (B1 — DNS
unbounded) + 4🟡 (A1 CGNAT, A2 CNAME, A3 IP-literal-encoding, B2 granular timeout, B3
retries=0) — all five were absorbed into the plan and are now implemented. This impl-stage
review re-probes each resolved finding against the code and tests.

The over-correction vector: cross-family models are structurally more likely to ask "what
happens when this specific OS-level call fails at 3am?" — so I specifically probe the
syscall-level behavior of the `getaddrinfo` wrapping, the httpx transport byte path, and
the compounding liveness terms under the single writer.

**Verdict rationale:** No 🔴 — the SSRF floor is complete, the resolve-then-pin transport
is correctly implemented, every plan-stage R0-B finding is resolved, and the constitution
test suite (t10a–t10e) enforces the trust boundary. Two 🟡 liveness observations
(DNS executor head-of-line blocking after timeout; web_search non-streamed response) that
do not break the bounded-writer guarantee but merit architect awareness. → `needs_architect`
for routing the two 🟡.

---

## Lens (a) — SSRF / data-exfil trust boundary

### 🔴 Findings — none

The SSRF posture is genuinely thorough at the implementation level. Every check from the
standard bypass checklist is addressed in code and test-enforced. No blocking gap.

### 🟡 Findings — none

All five plan-stage R0-B findings are resolved in the implementation:

| Plan-stage finding | Resolution in code | Verdict |
|---|---|---|
| 🔴 B1 (DNS unbounded) | `net_trust.py:86-93` — `ThreadPoolExecutor.submit(getaddrinfo).result(timeout=DNS_RESOLVE_TIMEOUT_S)` | ✓ Resolved |
| 🟡 A1 (CGNAT missing) | `net_trust.py:30,55-56` — `_CGNAT_NETWORK = IPv4Network("100.64.0.0/10")`; `100.100.100.200` tested | ✓ Resolved |
| 🟡 A2 (CNAME-chain untested) | `test_net_trust.py:192-207` — `test_cname_chain_to_internal_blocked` | ✓ Resolved |
| 🟡 A3 (IP-literal-encoding untested) | `test_net_trust.py:219-243` + `test_constitution.py:788-808` — real resolver, stubbed transport | ✓ Resolved |
| 🟡 B2 (granular timeout) | `net_trust.py:196-199` + `network_tools.py:39,42` — `httpx.Timeout(connect=5, read=15, write=5, pool=5)` | ✓ Resolved |
| 🟡 B3 (retries unconfirmed) | `net_trust.py:141` — `HTTPTransport(verify=True, retries=0)`; `test_constitution.py:858-880` asserts | ✓ Resolved |

### 🔍 SSRF bypass checklist — traversal against the code

**1. IP-range floor completeness.** `net_trust.py:40-63` (`is_denied_ip`):
- Loopback (`is_loopback`), private (`is_private`), CGNAT (`_CGNAT_NETWORK` explicit,
  `is_private` does not cover it), link-local (`is_link_local` — subsumes
  `169.254.169.254`), unspecified (`is_unspecified` — covers `0.0.0.0`/`::`),
  multicast (`is_multicast`), reserved (`is_reserved`). ✓
- IPv4-mapped IPv6 unwrapped at `net_trust.py:47-48`; `::ffff:127.0.0.1` →
  `is_denied_ip(127.0.0.1)` → True. ✓
- Classification is on the **resolved** IP, never the raw host string
  (`_resolve_and_validate:109` calls `ipaddress.ip_address(addr_str)`). ✓

**2. DNS-rebind / TOCTOU (resolve-then-pin).** `net_trust.py:125-172` (`_SSRFValidatingTransport`):
- Host resolved once via `_resolve_and_validate` (`handle_request:149`). ✓
- ALL resolved IPs validated; deny-if-any (`_resolve_and_validate:112-115`). ✓
- Connection to pinned IP via `pinned_url = request.url.copy_with(host=pinned_ip)`
  (`handle_request:152`). ✓
- TLS SNI/cert verification against original hostname via `sni_hostname` extension
  (`handle_request:158`). ✓
- `_inner = httpx.HTTPTransport(verify=True, retries=0)` (`net_trust.py:141`). ✓
- Multi-A-record one-internal → denied (`test_net_trust.py:166-176`). ✓

**3. Redirect + credential-on-redirect.** 
- `build_ssrf_client(follow_redirects=True, max_redirects=5)` (`net_trust.py:197-198`).
  httpx calls `handle_request` for each redirect hop → full re-validation. ✓
- `max_redirects` bounded at 5; `httpx.TooManyRedirects` caught →
  `LocalToolError("fetch_failed: too many redirects")` (`network_tools.py:143-146`). ✓
- Client is anonymous: `auth=None, cookies={}, headers={}` (`net_trust.py:200-203`).
  Nothing to forward on cross-origin redirect. ✓
- `web_search` API key sent only via `X-Subscription-Token` header to the Brave
  endpoint; assert in `test_network_tools.py:305-336` confirms key absent from query
  params and output content. ✓

**4. Scheme allowlist.** `net_trust.py:32,66-71` (`_ALLOWED_SCHEMES = {"http", "https"}`;
`_validate_scheme` raises `scheme_rejected:` before resolving). `file://`/`ftp://`/
`gopher://` tested (`test_net_trust.py:96-114`). ✓

**5. No-bypass (constitution-enforced).** `test_constitution.py`:
- `t10c` (`:811-838`): AST check — no `verify=False` in `net_trust.py`/`network_tools.py`. ✓
- `t10d` (`:841-855`): AST check — `web_fetch` must reference `build_ssrf_client`. ✓
- `t10e` (`:858-880`): AST check — transport has `retries=0`. ✓
- Actual code: `network_tools.py:131` calls `build_ssrf_client(...)` — the only
  httpx client `web_fetch` uses. `web_search` uses its own `httpx.Client` at
  `network_tools.py:213` for the fixed provider endpoint (by design — SSRF N/A). ✓

**6. Output-as-untrusted framing.** `selection.py:111-116`:
- `_NETWORK_TOOL_NAMES = {"web_fetch", "web_search"}` beside `_SUBPROCESS_TOOL_NAMES`. ✓
- `_external_output_tool_result_call_ids:145` adds `tool_name in _NETWORK_TOOL_NAMES`
  as third disjunct. ✓
- Drift sync-test `test_b46_network_tool_names_drift_guard` (`:652-671`):
  `registry keys == _NETWORK_TOOL_NAMES`. ✓
- Behavioral test `test_b46_network_result_excluded_from_excerpt` (`:674-734`):
  injection string absent from excerpt, trusted local result still present. ✓
- The two-channel split (excerpt exclusion does not blind the acting agent because
  `current_event` is a distinct channel) is carried forward from ADR-034 D3-iv. ✓

**7. Residual honesty.** ADR-035 D2 (`:59`): "We do NOT claim data-exfil is solved."
  The implementation does not soften this — there is no code path that claims to
  prevent public-host exfil. The IP floor permits public hosts by design. ✓

---

## Lens (b) — Liveness under the single writer × (1+N) passes

### 🔴 Findings — none

The writer is bounded on every term. No indefinite block vector.

### 🟡 B4-R0B-Y1 — DNS executor head-of-line blocking after a timeout (liveness degradation)

- **File/line:** `net_trust.py:37,86-93`
- **Claim:** `_DNS_EXECUTOR = ThreadPoolExecutor(max_workers=1)`. When a DNS
  resolution hangs and times out (5s), `future.cancel()` returns but the worker
  thread is still executing `getaddrinfo` — Python `ThreadPoolExecutor` cannot
  interrupt a running callable. Subsequent `submit()` calls queue behind the stuck
  worker. They will also time out after 5s (because `future.result(timeout=...)`
  fires even for queued-but-not-started tasks), so the writer is never blocked
  **indefinitely** — but DNS resolution becomes **completely unavailable** for the
  lifetime of the hung `getaddrinfo` call (potentially forever if the resolver never
  returns).

- **Impact:** After one malicious/slow resolver triggers a timeout, all subsequent
  `web_fetch` calls fail with `network_timeout:` until the process restarts. The
  compounding term is: the first fetch gets a 5s timeout → `TOOL_FAILED`; all
  subsequent fetches also get 5s timeouts → `TOOL_FAILED`. The writer is bounded
  (5s per call), but the tool is effectively dead.

- **Why this isn't theoretical:** `getaddrinfo` is a blocking syscall with no
  built-in timeout. A resolver under DoS, a malicious upstream DNS server, or a
  congested network path could trigger this. The `ThreadPoolExecutor` model has no
  mechanism to kill a stuck worker thread.

- **Mitigations already in place:** The 5s timeout ensures the writer is never
  blocked indefinitely — each call fails within the bound. The degradation is
  "tool unavailable" not "system hung."

- **Possible investigation (architect routes; I do not design):**
  (a) Use `max_workers=2` or higher so one stuck thread doesn't block all DNS
  (the head-of-line issue persists per-worker but other workers stay available).
  (b) Switch to `asyncio.get_event_loop().getaddrinfo(...)` + `asyncio.wait_for`
  if the executor loop is async-compatible (true cancellation on async path).
  (c) Accept the degradation — bounded failure is better than unbounded block,
  and in healthy deployments DNS doesn't hang.

### 🟡 B4-R0B-Y2 — `web_search` response not streamed (mild OOM asymmetry)

- **File/line:** `network_tools.py:213-218`
- **Claim:** `web_search` calls `httpx.Client.get()` **without** `stream=True`,
  then calls `response.json()` — the entire provider response is buffered in
  memory. This differs from `web_fetch` (`network_tools.py:134-138`, `stream=True`
  → `_stream_bounded`). For the Brave Search API (response bounded by `count ≤ 20`),
  this is low risk in practice. But if a future provider returns large responses,
  or if the provider endpoint is compromised and serves a multi-GB payload, the
  single writer would OOM.

- **Why it's mild:** The timeout (`read=10.0`) still bounds the read time; the
  provider is operator-configured (trusted endpoint); and the formatted result is
  post-truncated at `MAX_RESULT_BYTES`. The OOM window is the raw JSON in memory
  before truncation.

- **Suggested investigation:** Stream the `web_search` response too (iterate
  `response.iter_bytes()` up to `MAX_RESULT_BYTES`, then parse JSON from the
  accumulated bytes) — symmetric with `web_fetch`.

### 🟢 G1 — Bounded streamed read (B3 R0-A Y1 OOM lesson carried forward)

`network_tools.py:94-113` (`_stream_bounded`): iterates `response.iter_bytes()`,
accumulates chunks up to `MAX_RESULT_BYTES`, stops reading. The response body is
never fully buffered into the single writer. Combined with `stream=True` at
`network_tools.py:136` and the `read=15.0` timeout component, a slow-drip or
large response is bounded on both time and memory. ✓

### 🟢 G2 — Bounded DNS resolution (🔴 B1 resolved)

`net_trust.py:86-93`: `_DNS_EXECUTOR.submit(_get_addrs, hostname, port).result(
timeout=DNS_RESOLVE_TIMEOUT_S)`. The `getaddrinfo` call that was previously
outside httpx's timeout scope is now wrapped in a 5s deadline. Test
`test_bounded_dns_timeout` (`test_net_trust.py:251-265`) mocks the future raising
`TimeoutError`. The last previously-unbounded term in the single-writer liveness
model is now bounded. ✓

### 🟢 G3 — Granular `httpx.Timeout` with transport `retries=0`

`network_tools.py:39`: `httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)`.
Bounded on every component — not a version-dependent scalar. `net_trust.py:141`:
`HTTPTransport(verify=True, retries=0)` — no silent retry loop multiplying the
write block. Constitution test `t10e` asserts `retries=0` in AST. ✓

### 🟢 G4 — Per-turn network cap independent from subprocess cap

`executor.py:53-58`: `MAX_NETWORK_CALLS_PER_TURN = 10`. `executor.py:209-239`:
`elif _is_network:` branch in the loop, separate counter `network_calls_this_turn`,
excess → `TOOL_FAILED(turn_network_cap_exceeded)`. `_execute_local_call` is
byte-unchanged (t3b still passes). Independence test
`test_subprocess_and_network_caps_are_independent` (`test_executor.py:756-800`):
10 subprocess + 10 network calls in one pass → all 20 succeed. ✓

### 🟢 G5 — All compounding terms finite and inscribed

The worst-case single-writer block is: `≤ MAX_NETWORK_CALLS_PER_TURN (10) ×
network_timeout (20s connect+read+write+pool) × (1+N) passes`. Each term is
finite and explicit in the code. The per-fetch bound adds `DNS_RESOLVE_TIMEOUT_S
(5s)` + body-stream timeout + `max_redirects=5` within the httpx timeout scope.
No unbounded inline dependency (no retry loop, no unbounded redirect chain, no
unbounded resolver). The ADR-028 D5 guarantee holds at the implementation level. ✓

---

## Synthesis

The implementation is **thorough and plan-faithful**. The SSRF posture — IP-range
denylist with explicit CGNAT, resolve-then-pin transport with TLS SNI preservation,
per-hop redirect re-validation, anonymous credential-stripped client, and
constitution-enforced no-bypass — is a real, test-enforced defense. Every
plan-stage R0-B finding (1🔴 + 4🟡) is resolved in code with matching tests. The
liveness posture bounds every previously-unbounded term.

The two 🟡 findings are degradation-mode observations, not correctness defects:
the DNS executor's head-of-line blocking after a timeout (Y1) and `web_search`'s
non-streamed response (Y2). Neither breaks the bounded-writer guarantee; both
merit architect awareness for the P4.3 hardening pass or the next network-tool
cycle.

**Pattern:** The implementation quality on this slice — the project's first
agent-chosen-URL surface and its heaviest trust call to date — is high. The
cross-family lens confirms that the resolve-then-pin transport, the constitution
enforcement, and the liveness bounds are real at the code level, not merely
well-specified at the plan level.
