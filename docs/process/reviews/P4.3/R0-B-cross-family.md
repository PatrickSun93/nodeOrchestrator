---
task_id: P4.3
round: R0-B-cross-family-external
reviewer_family: deepseek
reviewer_model_id: deepseek-v4-pro
reviews_acked:
  - architect-briefs/P4.3.md
  - senior-plans/P4.3.md
  - decisions/ADR-037-syscall-egress-sandbox.md
verdict: blocking
findings_count: { red: 4, yellow: 4, green: 10 }
---

# R0-B Cross-Family Review — P4.3 impl-stage (DeepSeek lens)

**Lens stance:** deliberately outside-Claude. Over-correcting for: trust-the-types-means-trust-the-runtime, agreeableness, "the container flag is set therefore the boundary holds." Default to refuted/skeptical; only surface findings traceable to concrete file:line evidence.

**Result:** 4🔴 blocking, 4🟡 should-fix, 10🟢 confirmed. The 4🔴 are all concretely traced escape/breakage paths — the sandbox as implemented does not provide the isolation the ADR claims and the seccomp/econfig/firewall/egress surface has four independently-breaking issues that each prevent the container from functioning correctly or silently bypass the claimed boundary.

---

## 🔴 RED — BLOCKING (4 findings)

### 🔴 R0B-1: Seccomp profile is default-deny with ZERO allowed syscalls — container cannot start

- **File:line:** `sandbox/seccomp.json:2` (`"defaultAction": "SCMP_ACT_ERRNO"`), `sandbox/profile.py:130-135` (`_seccomp_arg`)
- **Traced failure mode:** Docker's `--security-opt seccomp=<profile>` **replaces** the default seccomp profile (which is a curated blocklist with `defaultAction: SCMP_ACT_ALLOW`). The shipped `seccomp.json` has `"defaultAction": "SCMP_ACT_ERRNO"` (deny-by-default) with **zero** `"action": "SCMP_ACT_ALLOW"` rules — every entry in the `syscalls` array also has `"action": "SCMP_ACT_ERRNO"`. Result: ALL syscalls are denied. The container cannot call `execve`, `read`, `write`, `mmap`, `brk`, `open`, `close`, `exit` — it fails at startup with EPERM on the first syscall after exec.
- **ADR-037 D2 design intent:** "the container runtime default seccomp profile (a curated blocklist baseline) AUGMENTED with an explicit additional-deny set." This is impossible with Docker's `--security-opt seccomp=<profile>` mechanism because the custom profile replaces, not augments, the default.
- **Severity:** 🔴 — container-based sandbox is non-functional. The seccomp asset bricked in all test scenarios but tests don't exercise live containers (CI has no daemon), so this passes CI unnoticed. First live deployment with a runtime would fail every sandboxed call with EPERM inside the container.
- **Confidence:** HIGH. The seccomp JSON semantics are unambiguous. A custom Docker seccomp profile with `defaultAction: SCMP_ACT_ERRNO` and zero allow-rules blocks all syscalls. This is verifiable with `docker run --security-opt seccomp=<this-json> alpine echo hello` which would fail.
- **Fix direction:** Either (a) change `defaultAction` to `SCMP_ACT_ALLOW` (matching Docker's default behavior for unlisted syscalls) **and** vendor Docker's full default denials into this file so the custom profile doesn't silently open Docker's blocked syscalls, or (b) switch to a different augmentation mechanism that doesn't replace Docker's default profile.

### 🔴 R0B-2: Per-call egress firewall rules are informational only — never installed — container has unrestricted internet access on the bridge

- **File:line:** `sandbox/spawn.py:110-113` (`_create_network` — creates bridge without `--internal`), `sandbox/egress.py:194-213` (`_build_firewall_rule` — returns an informational string, never applied), `sandbox/spawn.py:111` (no iptables/nftables invocation anywhere in the spawn path)
- **Traced failure mode:** The egress constraint mechanism (ADR-037 D2 Network — "the load-bearing network-isolation boundary") claims to constrain container egress to exactly the pinned IP:port via "a per-call ephemeral network + a daemon-side nftables/iptables egress rule on the bridge forward chain." The implementation:
  1. Creates a Docker bridge network (`sandbox/spawn.py:198-205`) **without `--internal`** → the bridge has full internet access via Docker's NAT/masquerade.
  2. `_build_firewall_rule` (`egress.py:194-213`) returns a firewall rule **as an informational Python string** stored in `EgressSpec.firewall_rule`. This string is **never used** — no code path invokes `iptables` or `nftables` to install it.
  3. The only egress restriction is `--dns 0.0.0.0` (DNS disabled), but:
     - IP-based connections bypass DNS entirely.
     - A server-side redirect to an IP-based URL (e.g. `http://93.184.216.34/exfil?d=secret`) is followed by `urllib.request.urlopen` in the fetcher script — no DNS needed.
     - The bridge NAT allows the connection to any reachable IP.
  **Exfiltration scenario:** The agent fetches `https://attacker-controlled.example/innocent`. The server returns HTTP 302 to `http://1.2.3.4/exfil?d=<workspace-secrets>`. The container's `urllib` follows the redirect. Since the target is an IP, DNS is irrelevant. Since the bridge has no firewall rules, the connection succeeds. Data exfiltrated.
- **Severity:** 🔴 — the egress boundary (the single most load-bearing isolation dimension for R4/R8 retirement) is a bridge with disabled DNS but no actual firewall enforcement. It protects against accidentally connecting to the wrong host but does NOT protect against a malicious server redirecting to an arbitrary IP.
- **Confidence:** HIGH. Verified: `_create_network` does not pass `--internal`; no `subprocess.run(["iptables", ...])` or `["nft", ...]` exists anywhere in the sandbox package. The `firewall_rule` field is set but never consumed by any code path.
- **Fix direction:** Either (a) add `--internal` to the Docker network create and add the pinned IP as an explicit route/exception, or (b) actually install+remove iptables/nftables rules in `_create_network`/`_remove_network` (requires root), or (c) use `--network none` + a SOCKS/proxy tunnel to the pinned IP, or (d) for the web_fetch case, use the host-side filtering proxy that was spec'd for Docker Desktop. The proxy approach (d) is described in ADR-037 D2 but is not implemented either — host.docker.internal is referenced in egress.py but no actual proxy is started.

### 🔴 R0B-3: Sandboxed web_fetch is architecturally broken — DNS disabled but URL has hostname, fetcher can't resolve

- **File:line:** `sandbox/egress.py:183-184` (`--dns 0.0.0.0`), `network_tools.py:208-214` (fetcher argv passes original `url_str` with hostname, not rewritten to use `pinned_ip`), `sandbox/spawn.py:100-103` (net_args merged but no `--add-host` for hostname→IP mapping)
- **Traced failure mode:** Independent of 🔴R0B-2. Even if the firewall rules were installed, the sandboxed web_fetch would **always fail** on any URL with a hostname:
  1. Parent resolves hostname → gets `pinned_ip` (e.g. `93.184.216.34` for `example.com`).
  2. Container args get `--dns 0.0.0.0` → container's `/etc/resolv.conf` has `nameserver 0.0.0.0`. The glibc resolver sends DNS queries to 0.0.0.0:53. The Linux kernel maps `connect(0.0.0.0, 53)` to `connect(127.0.0.1, 53)` (INADDR_ANY → localhost), but Docker's embedded DNS is at `127.0.0.11`, not `127.0.0.1`. DNS queries fail with ECONNREFUSED or timeout.
  3. The Python fetcher script receives the **original hostname-based URL** (`url_str`) — it is **never rewritten** to use the pinned IP. `urllib.request.urlopen("https://example.com/")` tries to resolve `example.com` → DNS fails → `socket.gaierror` → fetcher exits with error.
  4. The hostname→IP mapping known to the parent (`pinned_ip`) is **not communicated** to the container — no `--add-host example.com:93.184.216.34`, no `/etc/hosts` injection, no URL rewriting to `https://93.184.216.34/` with Host header.
- **Severity:** 🔴 — `web_fetch` inside the sandbox is non-functional. Every sandboxed web_fetch call will fail with a DNS resolution error inside the container. This would be caught the first time `web_fetch` is called in a live deployment.
- **Confidence:** HIGH. Trace the data flow: `url_str` (`network_tools.py:177`) → `pinned_ip` resolved (`:182`) → `url_str` passed unmodified to fetcher (`:208-214`) → container has `--dns 0.0.0.0` (`egress.py:183-184`) → no `--add-host` anywhere → fetcher's `urlopen(hostname_url)` fails.
- **Fix direction:** Pass `--add-host <hostname>:<pinned_ip>` in the container args (the hostname is available in `_sandbox_web_fetch` at `network_tools.py:178` but is not threaded through `build_egress_spec` / `container_network_args` — either thread it through or add the mapping in the caller after building the spec). The `EgressSpec` needs a `hostname` field or the `container_network_args` needs to accept a hostname→IP mapping.

### 🔴 R0B-4: Config-parse failure silently falls through to app-level execution — fail-OPEN, not fail-CLOSED

- **File:line:** `api/app.py:245-258` (config-parse failure → `_sandbox_posture_resolver` stays `None`), `subprocess_tools.py:240` / `network_tools.py:147` / `plugins/code.py:115` (`if posture_resolver is not None:` → False → app-level fallback)
- **Traced failure mode:** ADR-037 D4 states: "Config-parse failure (malformed `sandbox.yaml` / invalid `runtime` / missing keys) → **FAIL-CLOSED** (same as runtime-unavailable + no opt-in — never a default that fails open)." The implementation:
  1. `load_sandbox_config` raises `SandboxConfigError`.
  2. `app.py:249-258` catches it, logs a ONE-TIME warning, and leaves `_sandbox_posture_resolver = None`.
  3. All tools check `if posture_resolver is not None:` — when `None`, they silently fall through to the **old app-level posture** (raw `run_scoped_command`, in-process `httpx`, etc.) with **zero sandboxing**.
  4. The `WARNING` log fires once at bootstrap; no per-call warning. This is the definition of **silent fail-open** — the operator misconfigures the sandbox (typo in `sandbox.yaml`, missing `image` field, unknown `runtime`), and the system silently reverts to unsandboxed execution.
- **Severity:** 🔴 — violates the constitutional "no silent fail-open" invariant (ADR-037 D4, brief DP4). The `RB-FS/NET` residual the entire P4.3 exists to retire is silently re-exposed by a YAML typo. A post-P4.3 deployment where the operator accidentally misspells `image: sandbox:latest` as `image: sandbox:latst` would run EVERYTHING unsandboxed with a single bootstrap WARNING line buried in logs.
- **Confidence:** HIGH. Trace: `_sandbox_posture_resolver = None` → every tool's `if posture_resolver is not None:` is False → `return _dispatch(...)` / `return _inprocess_web_fetch(...)` / `pass  # DEGRADED fall through` → no sandbox, no per-call warning.
- **Fix direction:** When config-parse fails, construct a `PostureResolver` in FAIL_CLOSED mode (runtime=None, degraded_app_level=False) instead of leaving it as `None`. This way all tools hit the `assert_sandboxed_or_raise` → `SandboxUnavailableError` → `LocalToolError(sandbox_unavailable:...)` path instead of silently bypassing the sandbox. The `PostureResolver` must accept a pre-configured posture that forces FAIL_CLOSED regardless of config.

---

## 🟡 YELLOW — Should fix (4 findings)

### 🟡 R0B-5: Setup latency measurement excludes network creation time

- **File:line:** `sandbox/spawn.py:107-115` (network created at line 111-113, `t_setup` measured at line 115 — after network creation)
- **Traced issue:** The 3s-p95 target measurement captures `t_setup - t_start` where `t_setup` is sampled AFTER `_create_network`. Network creation (`docker network create`) can be slow (hundreds of ms to seconds). Excluding it means the "setup" measurement is optimistic. The warning at line 117-122 only fires when the remaining setup exceeds 3s, but the network creation cost is invisible.
- **Severity:** 🟡 — measurement inaccuracy; doesn't affect correctness but undermines the plan-vs-impl budget gate.
- **Confidence:** HIGH.
- **Fix direction:** Move `t_setup = time.monotonic()` to the very top of `sandboxed_run`, before `_create_network`. Or measure network creation as a separate term.

### 🟡 R0B-6: Sandboxed web_fetch redirect re-validation relies entirely on the (missing) egress firewall

- **File:line:** `network_tools.py:171-173` (comment acknowledges re-validation is now egress-constraint's job), `sandbox/egress.py:194-213` (firewall rule is informational), `network_tools.py:269-284` (fetcher script uses `urlopen` which follows redirects with no redirect-callback hook to re-validate)
- **Traced issue:** The in-process `web_fetch` (`_SSRFValidatingTransport`) re-validates every redirect hop via `handle_request`. The sandboxed path's only redirect defense is the egress firewall — which is never installed (🔴R0B-2). Even after fixing R0B-2, the defense relies entirely on the firewall. The fetcher's `urllib.request.urlopen` follows redirects automatically with no per-hop callback to re-validate the redirected URL against the SSRF floor.
- **Severity:** 🟡 — defense-in-depth regression. The ADR says the SSRF floor stays as defense-in-depth, but it doesn't operate on redirect hops in the sandboxed path. Coupled with 🔴R0B-2 this becomes critical; after fixing R0B-2 it's a secondary concern (the firewall is the primary enforcement).
- **Confidence:** MEDIUM. Could be mitigated by using `urllib.request.HTTPRedirectHandler` with a custom `redirect_request` that only allows same-IP redirects, but this is additive hardening.
- **Fix direction:** Either add a custom `urllib.request.HTTPRedirectHandler` in the fetcher script that re-validates redirect targets against a provided pinned IP, or document this as an accepted defense-in-depth regression (the firewall is the primary enforcement per ADR-037 D3).

### 🟡 R0B-7: `send_email` (R9) silently falls through without per-call WARNING when sandbox unavailable — inconsistent with DEGRADED posture

- **File:line:** `network_tools.py:546` (`send_email`: `_make_send_email(email_config)` — no `posture_resolver` argument), `app.py:280` (posture_resolver passed to build_network_tool_registry but not used by send_email), ADR-037 D5 (R9 inscribed as NOT-retired)
- **Traced issue:** `send_email` does not receive a `PostureResolver` and runs in-process with plain `httpx` regardless of sandbox state. While this is consistent with ADR-037 D5 (R9 NOT retired — DLP tail), it's inconsistent with the system's posture awareness: all other tools either go through the sandbox or loudly warn when degraded. `send_email` has no awareness of the sandbox state at all. If the operator configured sandbox.yaml, every other tool fails-closed on unavailable, but `send_email` silently continues unsandboxed without any log correlation.
- **Severity:** 🟡 — architectural inconsistency, not a vulnerability (ADR-037 D5 honestly inscribes this). But the honest-residual discipline requires explicitly naming the surface, and the current code doesn't even log that `send_email` is unsandboxed. A new operator might reasonably expect sandbox.yaml to affect all tools.
- **Confidence:** HIGH.
- **Fix direction:** Either (a) log a one-time INFO at bootstrap that `send_email` runs unsandboxed by design (R9 DLP tail), or (b) pass `posture_resolver` to `_make_send_email` and log `WARNING` on DEGRADED (even though the execution path is unchanged — the warning is the transparency mechanism).

### 🟡 R0B-8: Plugin sandbox path uses `StdioServerParameters` but doesn't route through sandboxed subprocess exec

- **File:line:** `plugins/code.py:142-169` (`_build_sandboxed_harness_params` builds `StdioServerParameters` with `command=docker/podman`, not using `sandboxed_run`)
- **Traced issue:** The plugin sandbox path builds a raw `StdioServerParameters` with `command=cli` (docker/podman) and `args=container_args`. This bypasses `sandboxed_run` — it uses `subprocess_mcp_stdio` which runs the raw CLI as a subprocess, not through the sandbox spawn interface. This means:
  1. No per-call timeout wrapping the container (uses `_CALL_TIMEOUT` for the MCP session, not a container-level timeout).
  2. No shielded `_safe_kill` on container finish — if the MCP session ends, the docker process exits but the container might still be running.
  3. Container kill+rm is not guaranteed (no `finally` block calling `runtime.kill(container_name)`).
  4. Setup/teardown latency not measured against the 3s-p95 target.
  5. Egress network is deny-default (`build_deny_default_spec()`) but the network args aren't merged into the container args (only `build_container_args` is used — `container_network_args` is never called for the plugin path).
- **Severity:** 🟡 — the plugin sandbox path diverges from the spawn.py interface designed for it. The plugin container may not be reliably reaped. A hung plugin inside a container that survives the MCP session timeout would leak the container.
- **Confidence:** MEDIUM. Need to verify whether `subprocess_mcp_stdio`'s teardown (`_terminate_subprocess` + `_kill_watchdog`) is sufficient for the docker process — it would kill the docker CLI process but not necessarily the container (docker CLI exits when the container stops, but the SIGKILL on the docker CLI might orphan the container).
- **Fix direction:** Route the plugin spawn through `sandboxed_run` instead of building raw `StdioServerParameters`. Or add container-level kill+rm in the plugin's teardown path.

---

## 🟢 GREEN — Confirmed (10 findings)

### 🟢 R0B-9: `_execute_local_call` byte-frozen — empty executor diff

- **File:** `tools/executor.py:385` — `git diff origin/main -- src/orchestrator/tools/executor.py` is empty; s3 AST test (`test_constitution.py:146-177`) confirms no sandbox symbols in the function.
- **Confidence:** HIGH. The wrap lives below the executor per ADR-028 D6.

### 🟢 R0B-10: `--user nobody` + `--cap-drop=ALL` + `--security-opt no-new-privileges` present

- **File:** `sandbox/profile.py:105-109` — all three flags unconditionally present in every `build_container_args` call.
- **Confidence:** HIGH. Non-root UID, full capability drop, no new privileges escalation.

### 🟢 R0B-11: `--read-only` rootfs + only workspace bind-mount rw + docker.sock NEVER mounted

- **File:** `sandbox/profile.py:81-83` (read-only + workspace rw bind), `sandbox/profile.py:120-121` (constitutional assertion), `tests/sandbox/test_constitution.py:264-302` (s6 tests)
- **Confidence:** HIGH. Constitutional invariant enforced at build time by `_assert_no_docker_sock` and tested by s6.

### 🟢 R0B-12: Sensitive `/proc` paths masked via `--tmpfs`

- **File:** `sandbox/profile.py:24-29`, `88-90` — `/proc/sysrq-trigger`, `/proc/kcore`, `/proc/kmsg`, `/proc/kallsyms` masked.
- **Confidence:** HIGH. Docker's private PID namespace keeps `/proc/1/root` as container root (not host); the tmpfs overlays close known `/proc` attack surface.

### 🟢 R0B-13: NAT64 `64:ff9b::/96` unwrap correctly implemented (R6)

- **File:** `tools/net_trust.py:35` (`_NAT64_PREFIX`), `:61-65` (unwrap logic in `is_denied_ip`)
- **Confidence:** HIGH. NAT64-embedded IPv4 is extracted from the low 32 bits and recursively validated against the floor.

### 🟢 R0B-14: R5 DNS head-of-line fix — `max_workers=1→8` bounded-growth pool

- **File:** `tools/net_trust.py:46` (`_DNS_EXECUTOR = ThreadPoolExecutor(max_workers=8)`)
- **Confidence:** HIGH. A hung `getaddrinfo` now consumes one of 8 slots; concurrent resolves in other slots are not head-of-line blocked. Individual resolves still bounded by `DNS_RESOLVE_TIMEOUT_S=5.0`.

### 🟢 R0B-15: `openat2(RESOLVE_NO_SYMLINKS)` for `apply_edit` (R7)

- **File:** `tools/mutation_tools.py:49-114` — `_try_openat2` + `_hardened_open` with fallback to `O_NOFOLLOW` on final component.
- **Confidence:** HIGH. Linux 5.6+ gets full parent-component TOCTOU protection. Cross-platform fallback honestly documented (AD-037 D5). Windows residual acknowledged.

### 🟢 R0B-16: Liveness probe has bounded timeout + per-turn caching

- **File:** `sandbox/runtime.py:26` (`LIVENESS_PROBE_TIMEOUT_S = 2.0`), `:100-114` (`_probe_liveness` with `timeout`), `sandbox/posture.py:32` (`_LIVENESS_CACHE_TTL_S = 30.0`), `:98-106` (`_check_available` with TTL caching)
- **Confidence:** HIGH. A wedged `docker info` is bounded at 2s. Repeated unavailable calls within a turn don't re-probe (30s TTL).

### 🟢 R0B-17: Shielded teardown — container kill+rm in `finally` block

- **File:** `sandbox/spawn.py:130-150` — `_safe_kill` in `finally` block; `runtime.py:84-97` (`kill`+`rm -f` each with `timeout=5.0` + `contextlib.suppress(Exception)`).
- **Confidence:** HIGH. Even on timeout or exception, the container is reaped.

### 🟢 R0B-18: R9 `send_email` honestly unsandboxed — consistent with ADR-037 D5

- **File:** `network_tools.py:546` — `_make_send_email` receives no `posture_resolver`; runs plain in-process `httpx`. ADR-037 D5 explicitly inscribes R9 as NOT retired.
- **Confidence:** HIGH. Design-intentional, not an oversight. (See 🟡R0B-7 for the transparency concern.)

---

## Cross-reference: findings that interact

- **🔴R0B-2 + 🔴R0B-3 + 🟡R0B-6 form a cluster:** The egress boundary (the most load-bearing isolation dimension) is broken three ways — the firewall isn't installed, DNS is disabled while URLs have hostnames, and redirect re-validation is absent. Fixing any one without the others doesn't restore isolation:
  - Fix R0B-3 (add `--add-host`) without fixing R0B-2: the container can reach the pinned host BUT can also reach any IP via redirect.
  - Fix R0B-2 (install firewall) without fixing R0B-3: the container CAN'T reach the pinned host (DNS fails), so `web_fetch` is broken.
  - Fix both: the container can reach the pinned host AND can't reach non-pinned IPs → egress constraint works as designed.

- **🔴R0B-1 (seccomp) + 🔴R0B-4 (config fail-open) are independent breakages:** each alone would block the sandbox from providing isolation. Both must be fixed.

- **🟡R0B-8 (plugin bypass) is independent:** even if the spawn.py path is perfect, the plugin harness takes a different code path that doesn't benefit from `sandboxed_run`'s shielded teardown.

---

## Verdict: BLOCKING

**4🔴 = design-breaking.** The sandbox as implemented does not provide the isolation the ADR claims:
1. Seccomp blocks ALL syscalls (container can't run).
2. Egress firewall is informational (no actual enforcement).
3. Sandboxed web_fetch is architecturally broken (DNS disabled + hostname URL).
4. Config-parse failure silently disables the sandbox (fail-OPEN, not fail-CLOSED).

The 4🟡 are real quality/debuggability gaps but not independently blocking. The 10🟢 confirm the structural spine (executor-frozen, non-root, cap-drop, read-only, docker-sock-never, NAT64, R5, R7, liveness-probe, shielded-teardown) is sound.

**Expected next action:** architect routes the 4🔴 → plan + ADR-037 revision → junior re-dispatch with fixes.
