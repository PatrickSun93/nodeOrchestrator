---
task_id: P4.2-B4
round: R0-B-on-plan
verdict: needs_architect
findings: 1🔴 + 4🟡 + 10🟢
lenses_applied:
  - SSRF / data-exfil trust boundary (standard bypass checklist)
  - Liveness (single-writer boundedness under (1+N) passes)
review_stage: plan
---

# R0-B on-plan review — P4.2-B4 (network local tools)

## Lens preamble

This review applies the two lenses from the mandatory dual-lens R0-B dispatch
(`docs/process/reviews/P4.2-B4/external-r0b-prompt.md`). The design artifacts
reviewed are the senior plan (`docs/process/senior-plans/P4.2-B4.md`) and
ADR-035 Proposed (`docs/decisions/ADR-035-network-local-tools.md`), plus the
ADR-028 D3 amendment annotation. No code exists yet — this is a plan-stage
structural review against the design, not a code audit.

The over-correction vector for this review: Claude-family biases toward
trusting that "if the types align, the runtime holds." I specifically probe
for gaps at the boundary between the stated mechanism and the OS-call reality
— DNS resolution timeout vs httpx.Timeout coverage, the actual byte path
of IP-literal-encoded URLs through httpx URL parsing before they reach the
classifier, and whether every declared-bounded term is genuinely bounded at
the syscall level.

---

## Lens A — SSRF / Data-Exfil Trust Boundary

### 🔴 Findings — none

The SSRF posture design is genuinely thorough. The resolve-then-pin transport,
the IP-range denylist using Python `ipaddress` properties (encoding-safe),
the redirect re-validation on every hop, the anonymous credential-stripped
client, the scheme allowlist, and the constitution-enforced no-bypass test
(`t10`) collectively form a real defense. No blocking structural gap in the
design.

### 🟡 A1 — `100.64.0.0/10` (CGNAT/shared address space) not covered

- **File/line:** plan B4-1 "Pinned SSRF floor" (lines 36–42), ADR-035 D2
  (lines 50–51)
- **Claim:** The denylist relies exclusively on Python `ipaddress` module
  properties: `is_loopback`, `is_private`, `is_link_local`, `is_unspecified`,
  `is_multicast`, `is_reserved`. Python's `is_private` covers `10/8`,
  `172.16/12`, `192.168/16`, and `fc00::/7` — but does **not** cover
  `100.64.0.0/10` (RFC 6598, Shared Address Space / CGNAT).
- **Why it matters:** Alibaba Cloud's metadata endpoint is at
  `100.100.100.200` (within `100.64.0.0/10`). In deployments where the
  orchestrator runs on Alibaba Cloud, a prompt-injected agent could fetch
  `http://100.100.100.200/latest/meta-data/` and read instance metadata
  including credentials. The plan explicitly tests `169.254.169.254` but
  does not test `100.100.100.200`.
- **Suggested investigation:** Add `100.64.0.0/10` to the explicit denylist
  (either as a manually-added range or via `ip.is_reserved` if the Python
  version covers it — verify at impl time). Alternatively, document it as a
  known gap in the residual if the architect judges CGNAT-internal is
  deployment-specific. Add an explicit test for `100.100.100.200`.

### 🟡 A2 — No explicit CNAME-chain-to-internal test case

- **File/line:** plan B4-1 "Tests" (line 50), ADR-035 D2 (lines 52–53)
- **Claim:** The test plan lists "DNS-rebind: a stub resolver returning an
  internal IP → denied even when the hostname looks public" — this tests a
  **rebind** where the resolver flips, and "multi-A-record where one IP is
  internal → denied." Neither explicitly tests a **CNAME chain** where
  `safe.example.com CNAME internal.corp.local A 10.0.0.5` — the resolver
  follows the CNAME, `getaddrinfo` returns `10.0.0.5`, and the IP check
  should deny it. The resolve-then-pin transport *should* handle this
  correctly (DNS resolution follows CNAMEs to final IPs), but the explicit
  test case closes a known SSRF bypass class that differs from rebind
  (permanent CNAME, not TOCTOU).
- **Suggested investigation:** Add a test case: `evil.example.com CNAME
  169.254.169.254` → stub resolver returns `169.254.169.254` → `ssrf_blocked`.
  Verify the transport's `getaddrinfo` call follows CNAMEs to final IPs.

### 🟡 A3 — IP-literal encoding bypass at URL-parsing level untested

- **File/line:** plan B4-1 "Pinned SSRF floor" (line 36), ADR-035 D3-i
  (lines 65–67)
- **Claim:** The plan states "classify the resolved IP via Python `ipaddress`,
  never the raw host string, so encoding tricks are normalised away." This
  correctly handles decimal/octal/hex IPs that reach the classifier. However,
  the **URL parsing** stage (httpx URL parser → host extraction → custom
  transport) is never tested for edge cases like `http://2130706433/`
  (decimal `127.0.0.1`), `http://0x7f.0.0.1/`, or `http://0177.0.0.1/`.
  The question is whether httpx's URL parser normalizes these to IP addresses
  before the host string reaches `getaddrinfo`, or passes them as raw strings
  (which some resolvers may interpret differently). The existing tests mock
  the resolver — they don't exercise the full URL→host→resolution chain.
- **Suggested investigation:** Add an integration-level test (stubbed
  transport, not mocked resolver) that feeds `http://2130706433/` through the
  full `web_fetch` path and asserts it's blocked. If httpx normalizes
  decimal-encoded IPs → safe (the resolved IP hits the classifier). If it
  doesn't → the behavior depends on the OS resolver's handling of
  decimal-encoded hostnames, which is a deployment-variable gap.

### 🟢 G1 — IP-range floor uses `ipaddress` properties (encoding-safe by design)

ADR-035 D2 + plan B4-1: "classify the **resolved** IP via Python `ipaddress`,
never the raw host string." Python's `ipaddress` normalizes all representations
of the same IP to a canonical form — octal `0177.0.0.1`, hex `0x7f000001`,
decimal `2130706433`, and mixed encodings all become the same `IPv4Address`
object. This is the correct SSRF posture: validate post-resolution, not
pre-resolution, so string-level tricks are inert. ✓

### 🟢 G2 — Resolve-then-pin transport thoroughly designed

ADR-035 D2 + plan B4-1: one `getaddrinfo` call, validate ALL resolved IPs
(deny if ANY is internal), connect to pinned IP, TLS uses original hostname
for SNI/cert verification. The multi-A-record test case (one internal IP
among many → denied) closes the split-horizon rebind variant. ✓

### 🟢 G3 — Redirect re-validation on every hop, bounded

ADR-035 D2: `max_redirects = 5`, every hop re-runs full scheme + resolve-then-pin.
The test plan explicitly tests `302 → http://169.254.169.254` → `ssrf_blocked`.
No redirect-chain unbounded loop. ✓

### 🟢 G4 — Anonymous credential-stripped client

ADR-035 D2 + D3-iv + plan B4-1: no `Authorization`, no cookies, no env/api-key.
Cross-origin redirect cannot forward auth (none was sent). `verify=True`
always. The assertion is architecturally sound — an empty auth set cannot
leak. `web_search` provider key goes ONLY to the fixed provider endpoint
(plan B4-3 acceptance), never onto a fetched URL, never logged. ✓

### 🟢 G5 — Constitution-enforced no-bypass test (t10)

Plan B4-8: `t10` asserts the floor rejects loopback/private/link-local/
cloud-metadata/`0.0.0.0` + IPv4-mapped-IPv6; an AST/structural check that
`net_trust`'s validating transport is the only client `web_fetch` uses; no
`verify=False` anywhere on the network surface. The test-enforced no-bypass
pattern (ADR-032/ADR-034 precedent) is correctly applied. ✓

### 🟢 G6 — Output-as-untrusted framing correctly extended

ADR-035 D3-iii + plan B4-6: `_NETWORK_TOOL_NAMES` frozenset beside
`_SUBPROCESS_TOOL_NAMES`, drift sync-test (`registry keys == name set`),
two-channel split preserved (`current_event` carries bytes to acting agent;
excerpt exclusion removes from cross-agent system-block steering surface).
The same-pass coupling known-limitation (batched-non-last web results
invisible next pass) is inscribed by reference to ADR-034 D3-iv. ✓

### 🟢 G7 — Data-exfil residual inscribed honestly

ADR-035 D2: "the network half of RB-FS/NET … now ACTIVE," "NOT prevented
without the P4.3 egress firewall," "NOT claimed solved." The residual is
stated bluntly: public-host data-exfil is an Accepted residual on one P4.3
retirement path. No softening language, no over-claiming of "isolation" or
"sandbox." The operator egress-allowlist is named as the opt-in tightening,
not shipped in B4. ✓

---

## Lens B — Liveness (single-writer boundedness)

### 🔴 B1 — DNS resolution in custom transport is outside `httpx.Timeout` (unbounded block)

- **File/line:** plan B4-1 "Resolve-then-pin" (line 46), ADR-035 D2 (line 52)
- **Claim:** The resolve-then-pin transport calls `socket.getaddrinfo` to
  resolve the host, then connects to a pinned IP through httpx's connection
  pool. `httpx.Timeout` bounds **connect, read, write, and pool** timeouts —
  but `socket.getaddrinfo` is called **before** httpx's timeout machinery
  engages. A hung/slow DNS resolver (e.g., a malicious upstream, a congested
  resolver, a resolver under DoS) would block `getaddrinfo` **indefinitely**
  on the single writer thread (`max_workers=1`), stalling writes for **every**
  room. This is the ADR-028 D5 liveness invariant broken at the DNS boundary.
- **Impact:** The compounding term is severe: `≤ MAX_NETWORK_CALLS_PER_TURN
  (10) × unbounded_DNS_time × (1 + max_redirects (5)) × (1+N) passes`. A
  single slow resolver makes the worst-case unbounded, not "finite but large."
- **Why this isn't theoretical:** The plan's own test design uses "stubbed
  resolvers" (no real DNS) — so the DNS-resolution path is exactly the
  untested syscall in the liveness chain. The `httpx.Timeout` is tested (httpx
  enforces it), but `getaddrinfo` never enters httpx's timeout scope.
- **Suggested investigation:** Wrap DNS resolution in a timeout — either
  (a) `concurrent.futures.ThreadPoolExecutor.submit(getaddrinfo, ...).result(
  timeout=dns_timeout)` for the sync path, (b) use `asyncio.wait_for` if the
  transport is async, (c) use a resolver library with built-in timeout
  (e.g., `dns.resolver.Resolver` with `timeout` + `lifetime`), or (d) set a
  per-call deadline via `signal.alarm` / `threading.Timer` as a belt-and-
  suspenders guard. Document the DNS timeout constant (`DNS_RESOLVE_TIMEOUT_S
  = 5.0` would be reasonable) in ADR-035 D5's bounded-terms list.

### 🟡 B2 — `httpx.Timeout` component granularity not specified

- **File/line:** plan B4-2 "Pinned liveness constants" (line 59), ADR-035 D2
  (line 55)
- **Claim:** The plan pins `WEB_FETCH_TIMEOUT_S = 20.0` but does not specify
  whether this is a single total timeout or granular `httpx.Timeout(connect=…,
  read=…, write=…, pool=…)`. Different httpx versions interpret a scalar
  timeout differently (older: read-only; newer: all components). A
  connect-only timeout of 20s with an unbounded read timeout would leave slow
  bodies unbounded.
- **Suggested investigation:** Pin explicit granular timeouts at impl time,
  e.g., `httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)` for the
  20s total. Document this in a code comment beside the constant. This is
  junior's call at impl time; flagging it here so the design intent
  ("bounded on connect AND read AND pool" per the dispatch prompt) survives
  the transition to code.

### 🟡 B3 — No explicit confirmation that httpx auto-retry is disabled

- **File/line:** plan B4-1 (no explicit retry policy), ADR-035 D2
- **Claim:** httpx does NOT auto-retry by default (unlike `requests` with
  `Retry` adapters). However, `httpx`'s `transport.retries` can be configured
  (default: 0). The plan doesn't mention verifying that no retry loop exists
  — a retry loop on the single writer would silently multiply the per-fetch
  block time. Low likelihood (default is no retry), but worth asserting at
  impl time.
- **Suggested investigation:** Add a one-line assertion in `t10` or the
  `net_trust` tests: "the client's transport has `retries=0`" or equivalent.
  Belt-and-suspenders for the single-writer liveness model.

### 🟢 G8 — Bounded streamed read at `MAX_RESULT_BYTES`

ADR-035 D2 + plan B4-1/B4-2: body read as it streams, stops at
`MAX_RESULT_BYTES` (64 KiB), +1 byte to detect truncation, `output_truncated_at`
set. The B3 R0-A Y1 OOM-via-unbounded-read lesson is correctly carried forward
to network scale. A slow body is bounded by `httpx.Timeout` read component
(modulo the DNS gap, B1). ✓

### 🟢 G9 — Per-turn network cap separate from subprocess cap

ADR-035 D4 + plan B4-5: `MAX_NETWORK_CALLS_PER_TURN = 10`, counted in
`execute_pending_tool_calls` loop, separate counter from subprocess cap,
`_execute_local_call` byte-frozen (empty-executor-diff, t3b). The subprocess
branch is byte-unchanged. Excess → `TOOL_FAILED(turn_network_cap_exceeded)`.
The plan's §5-2 justification (network connections and subprocess forks are
distinct resource classes) is sound. ✓

### 🟢 G10 — All compounding terms inscribed

ADR-035 D4: the worst-case bound `≤ MAX_NETWORK_CALLS_PER_TURN × network_timeout
× (1+N) passes` (ADR-028 D5 × ADR-033 D4) is explicitly stated. The three terms
(cap, timeout, turn-loop multiplier) are all named and finite in the design.
The `max_redirects=5` bound is additive within a single fetch's timeout (httpx
applies timeout to the overall operation including redirects), not a separate
multiplier. ✓ (Modulo B1 — the DNS-resolution term makes this bound notional,
not real.)

### 🟢 G11 — `web_search` uses standard httpx with proper timeout

Plan B4-3: `WEB_SEARCH_TIMEOUT_S = 15.0`. Since `web_search` hits a single
operator-configured provider endpoint (not through the SSRF transport), it
uses standard httpx — DNS is covered by httpx's built-in timeout (no custom
transport, no bare `getaddrinfo`). The provider key is never on a fetched
URL, never logged. ✓

---

## Synthesis

The SSRF posture is well-designed at the plan level — the IP-range floor,
resolve-then-pin transport, redirect re-validation, anonymous client, and
constitution-enforced no-bypass test collectively form a genuine defense.
The remaining gaps are edge cases (CGNAT range, CNAME test, IP-literal URL
parsing) that are within the design's explicit scope to address.

The liveness posture has one structural gap (B1) that blocks the ADR-028 D5
single-writer boundedness guarantee: DNS resolution in the custom transport
is not covered by `httpx.Timeout`. This is a real gap because `getaddrinfo`
is a known-unbounded syscall and every other term in the liveness model is
genuinely bounded. The fix is small (wrap DNS in a timeout), but without it
the worst-case per-pass block time is not "large but finite" — it's unbounded.
The 🟡 liveness findings (B2, B3) are implementation-detail tightening.

**Pattern:** The 4 🟡 cluster around "tested at the unit level, untested at
the syscall integration level" — DNS timing (B1), IP-literal URL parsing (A3),
CNAME-following (A2), and CGNAT coverage (A1). All four sit at the boundary
between "the mechanism is correct" and "the OS actually does what the mechanism
assumes." The impl-stage R0-B should re-probe these exact four integration
boundaries against real (stubbed-transport, not mocked-resolver) tests.
