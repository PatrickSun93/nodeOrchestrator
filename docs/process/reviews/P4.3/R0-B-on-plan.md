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
findings_count: { red: 1, yellow: 5, green: 6 }
---

# R0-B cross-family review (plan-stage) — P4.3 container syscall/egress sandbox

## Lens preamble

Two lenses applied per `docs/process/reviews/P4.3/external-r0b-prompt.md`:

**(A) Isolation-completeness vs the container-escape checklist.** Probe the design against: userns gaps, seccomp completeness, mount/proc/sys leaks, egress-boundary bypass, in-process surfaces honestly named vs silently softened, the no-silent-fail-open invariant.

**(B) Liveness under the single writer.** Probe per-call container setup/teardown as the new finite term in the ADR-028 D5 / ADR-033 D4 budget: bounded or unbounded, measured or claimed, what hangs and how it degrades.

Over-correction target: Claude-family bias to trust-the-types-means-trust-the-runtime — "the container flag is set therefore the boundary holds." Instead: trace the concrete mechanism between the design claim and the OS boundary, and ask what blocks the writer when the daemon is alive-but-wedged.

---

## Findings

### 🔴 R1 — Egress-allowlist enforcement mechanism is unresolved (the load-bearing gap)

**Severity:** 🔴 blocking
**Source:** Plan §5.1; ADR-037 D2 (Network paragraph), D3 (web_fetch reversal); `tools/net_trust.py:79-122` (the SSRF floor that must be re-homed)
**Confidence:** High

**The gap.** The design claims the container retires R4 (web_fetch data-exfil) and R8 (git_push exfil-by-remote) via an egress deny-default (`--network none`) + an allowlist for tools that legitimately egress. But the mechanism to constrain container egress to a **single pinned IP:port per call** is left as an open design call — plan §5.1 banks three options (pinned-IP per-call network, host-side proxy, deny-default-only-defer-allowlist) and asks the architect to confirm.

**Without a concrete mechanism, exactly two outcomes are possible, and both break the claimed retirement:**

1. **`--network none` for all tools** → `web_fetch` and `git_push` cannot reach their targets at all. The tools break — not a sandbox, a brick.
2. **Network enabled without per-host filtering** → the container can `connect()` to any IP the host routes. R4 (data-exfil to arbitrary hosts) is **not retired**. The SSRF floor running in the parent as defense-in-depth doesn't help — the container's own socket is unconstrained.

The plan's lean ("parent-pinned-IP per-call egress") is directionally correct — the parent already resolves + validates + pins an IP via `_resolve_and_validate` (`net_trust.py:79-122`). But the mechanism to translate a pinned IP into a per-call container network constraint is **the hard part**, and it's deferred. A Docker bridge network with per-call iptables rules, or a per-call network namespace with a veth pair + firewall, or an HTTPS_PROXY that the container's httpx routes through — each has different cross-platform viability and implementation cost. The plan does not pick one.

**Why this is blocking at plan stage.** The egress-allowlist mechanism is not an impl detail — it's the isolation boundary for the network dimension. Without it specified, the junior cannot implement P4.3-7 (web_fetch egress) or the git_push allowlist path in P4.3-5 with confidence that they're building the right thing. The architect must ratify the mechanism before junior dispatch.

**Suggested investigation.** Architect ratifies the mechanism from the three §5.1 options (or a fourth). The ratified mechanism must specify: (a) how a per-call container's egress is constrained to exactly one pinned IP:port; (b) whether the constraint covers IPv4 only or both IPv4+IPv6; (c) whether the container can do its own DNS (it must not — DNS bypasses the pinned-IP constraint); (d) cross-platform viability (mac/win/linux).

---

### 🟡 Y1 — Seccomp profile: blocklist vs default-deny oscillates; escape-class syscalls undefined

**Severity:** 🟡 needs_architect
**Source:** ADR-037 D2 (Syscall paragraph); plan P4.3-2; ADR-037 D5 (residuals)
**Confidence:** Medium-High

**The ambiguity.** The design language oscillates between two different seccomp strategies:

- **Plan P4.3-2:** "ship the tightened seccomp JSON asset (runtime default minus ptrace/mount/keyctl/raw-socket/AF_PACKET)" → this is **blocklist-augmentation** of Docker's default seccomp profile (which is itself a ~44-syscall blocklist, not a default-deny allowlist).
- **ADR-037 D2:** "A conservative **allowlist**; the tight long tail is inscribed as deferred (D5)" → this reads as **default-deny** with a small set of allowed syscalls.

These are different mechanisms with different escape surfaces. Docker's default profile leaves `bpf`, `io_uring_setup`, `clone` (with several flag combinations), and other syscalls available. "Tightening" adds more blocks but the residual surface is whatever isn't on the list. A default-deny allowlist has the inverse property — everything is blocked except what's explicitly allowed.

**The D5 inscription partially mitigates this** — "seccomp-hole syscalls" is named as a residual. But the junior implementing P4.3-2 needs to know which strategy to build: a blocklist JSON that augments Docker's default, or a default-deny allowlist JSON. The two produce different seccomp profiles with different escape surfaces.

**Suggested.** Architect confirms: (a) blocklist (augment Docker default) or default-deny allowlist; (b) if blocklist, a concrete enumeration of the additional blocked syscalls (at minimum: `unshare`, `clone` with `CLONE_NEWUSER`/`CLONE_NEWNET`/`CLONE_NEWNS`, `bpf`, `io_uring_setup`, `add_key`, `request_key`). The senior plan should inscribe the enumerated list so the junior doesn't guess.

---

### 🟡 Y2 — /proc, /sys, and docker.sock masking not addressed

**Severity:** 🟡 needs_architect
**Source:** ADR-037 D2 (FS paragraph); plan P4.3-2
**Confidence:** Medium

**The gap.** The design specifies `--read-only` rootfs + workspace bind-mount rw, but does not address three mount-namespace surfaces:

1. **`/proc`**: Docker's private PID namespace (default, no `--pid=host`) keeps `/proc/1/root` pointing to the container's own root. But `/proc/sys` is still readable — kernel configuration information leak (low severity). More importantly, the plan does not state whether additional `/proc` masking is applied (e.g., `--security-opt mask=/proc/sysrq-trigger`). The plan asserts the host `~/.ssh` is not in the container mount namespace, but that's about filesystem bind-mount scope, not `/proc` leaks.

2. **`/sys`**: Without `--privileged`, `/sys` is mounted read-only in Docker containers. The plan does not mention whether `/sys` should be further masked or if the default read-only mount suffices.

3. **`/var/run/docker.sock`**: The docker socket gives container-escape-via-API (launch a privileged container, mount the host rootfs). The design should explicitly state it is **never** mounted — not as a "should not," but as a constitutional invariant. The plan's silence on this is notable given the dispatch prompt specifically asks about it.

**Why it matters.** Mount leaks are a standard container-escape vector. The plan is otherwise thorough about what IS mounted (workspace bind-mount rw) — completing the picture with what is explicitly NOT mounted and what pseudo-filesystems are masked would close this gap.

**Suggested.** ADR-037 D2 (FS paragraph) should add: (a) `/proc` masking stance (Docker's default PID-ns isolation is accepted; specific `/proc` paths masked if needed); (b) `/sys` is read-only (Docker default); (c) `/var/run/docker.sock` is **never** mounted — constitutional invariant.

---

### 🟡 Y3 — Per-call latency budget undefined; probe→spawn race unspecified

**Severity:** 🟡 needs_architect
**Source:** Plan §5.5, P4.3-1, P4.3-3, P4.3-4; ADR-037 D3, D4
**Confidence:** Medium

**Two related liveness gaps:**

**(a) Latency budget.** Plan §5.5 explicitly defers the latency bound: "Not banking a latency budget number — that's the R0-B + impl-measurement output, surfaced at plan-vs-impl." ADR-037 D3 says "Measured + bounded" but the bound is undefined. With N=4 re-dispatch passes and the B3 cap of 10 sandboxed calls/turn, the worst-case writer block is `(1+4) × 10 × per_call_setup_teardown`. If per-call setup is 2s (a plausible `docker run --rm` on a warm cache), that's 100s of writer-block just from container overhead. If it's 5s (cold cache, image pull), it's 250s. The ADR-028 D5 budget is not infinite.

The plan's P4.3-3 logging of setup/teardown duration is correct — but measurement without a cap is not bounded. The design should specify a **maximum acceptable per-call setup time** (or a total sandbox-overhead budget per turn) as the target, so the impl can measure against it and the plan-vs-impl review can reject if it exceeds.

**(b) Probe→spawn race + probe cadence.** The design does not specify:
- Whether `available()` is called once at bootstrap or per-call. If per-call, the probe adds latency to every sandboxed call.
- Whether the probe has its own timeout (if `docker info` blocks on a wedged daemon, the probe itself hangs the writer).
- What happens when `available()` returns True but the daemon dies between probe and spawn. Does `sandboxed_run` raise `SandboxUnavailableError` (triggering the posture resolver to decide fail-closed vs degraded) or a different error? The design says `sandboxed_run` only raises `SandboxUnavailableError` "on runtime-unavailable" — but daemon-dead-at-spawn is a different condition from unavailable-at-probe.

**Suggested.** (a) Add a target per-call setup budget (e.g., 3s p95) to ADR-037 D3, with the plan-vs-impl review gate. (b) Specify: probe is called once at bootstrap + cached for the turn; probe has its own short timeout (e.g., 2s); daemon-dies-at-spawn raises `SandboxUnavailableError` and follows the same posture path (fail-closed or degraded per opt-in).

---

### 🟡 Y4 — R5 DNS head-of-line survives the re-homing (parent DNS executor still single-threaded)

**Severity:** 🟡 needs_architect
**Source:** Plan §5.4; `net_trust.py:37` (`_DNS_EXECUTOR = ThreadPoolExecutor(max_workers=1)`)
**Confidence:** High

**The gap.** The plan re-homes `web_fetch` egress to a per-call container, but the parent's SSRF floor still runs `_resolve_and_validate` (`net_trust.py:79-122`) before the container spawns. That function uses `_DNS_EXECUTOR` — a `ThreadPoolExecutor(max_workers=1)` — with a `DNS_RESOLVE_TIMEOUT_S=5.0` deadline. The R5 concern is: `future.cancel()` cannot interrupt a running `getaddrinfo` call. If a DNS resolution hangs inside the C library (slow resolver, packet loss, a malicious authoritative server that responds just enough to keep the TCP connection alive), the one worker thread is blocked for the full 5s timeout. During that 5s, any other concurrent DNS resolution (e.g., from a second `web_fetch` in the same turn via parallel tool calls) queues behind the hung one.

Section 5.4 explicitly flags R5 as a "brief-vs-dispatch gap" and leaves it out of the banked atomics pending architect confirm. The design is honest about this, but the reviewer's job is to confirm: **the re-homing does NOT fix R5.** The container's egress socket is constrained, but the parent's DNS resolution happens before the container starts and uses the same single-thread executor. R5 persists at full strength.

**Suggested.** Architect confirms whether R5 folds into P4.3 (a small `net_trust` executor fix — e.g., per-call thread with ` pthread_cancel` or switch to `asyncio.getaddrinfo` with a true-cancel) or stays deferred. If deferred, ADR-037 D5 should list R5 as a named residual (it is not currently in the D5 list).

---

### 🟡 Y5 — Config-parse failure default unspecified; fail-closed repeated-timeout risk

**Severity:** 🟡 needs_architect
**Source:** Plan P4.3-4; ADR-037 D4
**Confidence:** Medium

**Two DP4 edge cases:**

**(a) Config-parse failure.** The plan says config lives in `config/sandbox.yaml` (with an `.example`). If the file is malformed YAML, missing required keys, or has an invalid `runtime` value — does the parser default to fail-closed (safe) or does it fall through to a default that might be fail-open? The plan's posture resolver design (P4.3-4) covers the runtime-available vs unavailable decision, but not the config-parse-failure path. A parse error that silently defaults to `degraded_app_level: true` or `runtime: auto` with a broken detection path would violate the no-silent-fail-open invariant.

**(b) Repeated per-call probe timeout.** If `available()` is called per-call and has a timeout, a wedged daemon causes every sandboxed call to block for the probe timeout before failing closed. If the probe timeout is 5s and a turn issues 5 sandboxed calls, that's 25s of writer block just from probing a dead daemon. The design should cache the unavailable status for the remainder of the turn (or a short TTL) so the first failed probe blocks subsequent calls immediately.

**Suggested.** (a) Specify: config-parse failure → fail-closed (same as runtime-unavailable + no opt-in). (b) Cache `available()` result for the turn (or with a short TTL like 30s); first unavailable probe → all subsequent calls in the same turn fail fast without re-probing.

---

### 🟢 G1–G6 — Correctly handled / honestly inscribed

| ID | What | Why |
|----|------|-----|
| G1 | **R9 recipient-exfil honestly NOT retired** | ADR-037 D5: "bounded transport, not eliminated; a DLP/deployment tail past P4.3." The netns bounds which hosts `send_email` reaches, but the exfil is in the recipient address. Correctly not claimed as retired. (`docs/decisions/ADR-037-syscall-egress-sandbox.md` D5) |
| G2 | **R7 cross-platform tail honestly inscribed** | Plan §5.3 + ADR-037 D5: `openat2(RESOLVE_NO_SYMLINKS)` is Linux 5.6+ only; macOS gets a per-component dir-fd `O_NOFOLLOW` walk; Windows stays at the current final-component residual. Each platform's posture is named. (`docs/process/senior-plans/P4.3.md` §5.3) |
| G3 | **`_execute_local_call` byte-frozen invariant honored** | The sandbox wrap lives in `subprocess_trust`/`net_trust`/the new `sandbox/` package — all below the executor. Constitutional test s3 (P4.3-10) will verify empty-executor-diff. (`src/orchestrator/tools/executor.py:385-435` is the byte-frozen function) |
| G4 | **Sandbox package downstream-leaf constraint** | P4.3-10 s5 verifies only `api/` + `subprocess_trust` + `net_trust` import `sandbox/`. No executor import. (`docs/process/senior-plans/P4.3.md` P4.3-10) |
| G5 | **Fail-closed + loud opt-in posture well-designed for the happy path** | Runtime-unavailable + no opt-in → `SandboxUnavailableError` → `TOOL_FAILED` (fail-closed). Runtime-unavailable + opt-in → degraded path + `WARNING` every call (loud). Constitutional tests s1/s2 mechanize. The no-silent-fail-open invariant is correctly the design's spine. (`docs/decisions/ADR-037-syscall-egress-sandbox.md` D4) |
| G6 | **Subtree-kill via container boundary cleanly retires R3** | The `setpgid(0,0)`-escape residual (grandchild orphans) is killed by `<runtime> kill` + `rm -f` — the container boundary tears down the whole process tree regardless of pgid. Clean retirement. (`docs/decisions/ADR-037-syscall-egress-sandbox.md` D2 Resources paragraph) |

---

## Synthesis

The design's spine is sound: one seam, per-call, fail-closed-default, honest residuals. The five architect-ratified DPs are correctly carried into the plan and ADR-037.

The **single blocking gap** is the egress-allowlist mechanism (R1). The plan correctly identifies deny-default (`--network none`) as trivial and the allowlist as the hard part, then banks it as an open design call (§5.1). But the allowlist is not optional — it's the mechanism that makes the network isolation real for the tools that need egress (`web_fetch`, `git_push`). Without it, P4.3 either breaks those tools or doesn't retire R4/R8. The architect must ratify the mechanism before junior dispatch.

The five yellows cluster around two themes: **(a) specification precision** (seccomp blocklist-vs-allowlist ambiguity, /proc/sys/docker.sock masking not addressed, config-parse default unspecified) — these are the kind of gaps that cause a junior to guess and an R0-A to miss because the spec language is ambiguous; **(b) liveness edge cases** (latency budget undefined, probe→spawn race, R5 DNS head-of-line) — these are the runtime-integration failures that manifest at 3am when Docker Desktop is slow to start and the writer blocks for 100s.

The six greens confirm the design is honest where it counts: R9 is not softened, R7's platform tail is named, the executor stays byte-frozen, and the fail-closed invariant is mechanized by constitutional tests. These are the marks of the honest-residual discipline working as intended.
