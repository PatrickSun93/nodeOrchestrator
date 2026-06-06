# ADR-037: Container syscall/egress sandbox — the RB-FS/NET retirement substrate (isolation profile, seam, fail-mode, residual inscription)

**Status:** Proposed — 2026-06-05 (senior-drafted for P4.3, the Wave-2 trust-hardening opener; architect ratified all 5 decision-surface points DP1–DP5 in the dispatch — **container-based, cross-platform** — before drafting; the plan-stage dual-lens routing was absorbed 2026-06-05 — the egress mechanism pinned, seccomp/mount/latency/config-fail-mode specified — see D2–D5). **Mandatory dual-lens** (`requires_cross_family_review: true`, P4-roadmap §8): the impl-stage review is R0-A ∥ R0-B (cross-family), the external lens probing sandbox liveness + the container-escape checklist. Stays **Proposed** until architect Accept after the dual-lens clears (RC-23). Annotations to ADR-031 D1a / ADR-034 D2,D4 / ADR-035 D2,D4,impl-degradation (R5 resolved + R6 folded) / ADR-036 D3-i,ii,iii are inscribed at impl (plan task P4.3-13), matching the eventual Accepted status (the B3/B4/B5 precedent).

**Scope:** The **execution substrate** that retires the accumulated `RB-FS/NET`-class residuals (R1–R4, R7, R8; R3 via subtree-kill) by wrapping the existing subprocess/egress exec in an **OS container** — a real FS / network / syscall / UID / resource boundary. Inscribes: the **sandbox mechanism** (containers, runtime-abstracted across Docker Desktop / podman / native), the **isolation profile** (the per-call container's FS/net/seccomp/UID/resource shape), the **one seam** all subprocess exec routes through + the **web_fetch egress reversal** (ADR-035 D4), the **posture + fail-mode** (default-on; fail-closed-default + loud operator opt-in to degraded app-level posture), and **P4.3's own honest residuals** (R9 recipient-exfil DLP tail; sandbox-escape surface; degraded-posture path; per-call latency; the cross-platform R7/image tails). Does **NOT** govern: the autonomy gate's decision logic (unchanged, ADR-027 D2 / ADR-028 D6 — the sandbox is a substrate **below** `_execute_local_call`, byte-frozen); the confirm-then-execute machinery (unchanged, ADR-030); the app-level scoping it wraps (scoped-env, SSRF floor, `_check_path` — they become **defense-in-depth that does not reverse**, ADR-034/035 Reversibility); real-credential injection (still deferred, ADR-036 D3-iii); DLP / within-allowed-domain recipient control (R9 — explicitly NOT retired, a deployment concern past P4.3).

---

## Context

P4.2 shipped the heavy tool surfaces — B3 subprocess (ADR-034), B4 network (ADR-035), B5 mutation (ADR-036) — and ADR-031 shipped the Posture-B fetched-plugin executor, **each Accepting an honest `RB-FS/NET`-class residual on one named retirement path: "the sandbox WRAPS the existing exec; the app-level scoping does not reverse"** (ADR-031 D1a Reversibility; ADR-034 D2 forward-watch; ADR-035 D2). After all four, an activated tool/plugin runs with the host user's full FS-read + outbound-net privilege (`open()` `~/.ssh/id_rsa`, `socket()` to `evil.com`). The boundary was **named and deferred**, never softened.

P4.3 is that retirement. It does **not** rebuild the execution substrate — it wraps it. The closed-residual ledger it must retire / bound (each Accepted + inscribed today, gated by operator activation — none a live incident):

| # | Residual | Source | Surface | Retired by (this ADR) |
|---|---|---|---|---|
| R1 | fetched-plugin child runs with full FS-read + outbound-net | ADR-031 D1a | subprocess (`_PostureBFn`) | D2 FS+net isolation |
| R2 | B3 tools + `git_push` run with operator FS-read + outbound-net | ADR-034 D2 | subprocess (`run_scoped_command`) | D2 FS+net isolation |
| R3 | `setpgid(0,0)`-escape kill residual (grandchild orphans) | ADR-034 D4 | subprocess | D2 container subtree-kill |
| R4 | `web_fetch` public-host data-exfil (`https://evil.com/?d=<secret>`) | ADR-035 D2/D3-ii | **in-process** httpx | D3 egress-container + deny-default |
| R7 | `apply_edit` parent-component TOCTOU (`O_NOFOLLOW` is final-only) | ADR-036 D3-i | **in-process** FS | D3 app-level `openat2(RESOLVE_NO_SYMLINKS)` |
| R8 | `git_push` exfil-by-remote (arbitrary remote URL) | ADR-036 D3-iii | subprocess | D2 egress deny-default + allowlist |

**The seam tension (drives D3):** R1/R2/R3/R8 are **subprocess** residuals — a container that spawns children inside it retires them naturally. But R4/R7 are **in-process** (`web_fetch` is in-process `httpx`, ADR-035 D4 chose in-process *because a subprocess bought no isolation pre-sandbox*; `apply_edit` is in-process FS). A per-subprocess container does **nothing** for in-process egress/FS — so D3 reverses ADR-035 D4 for `web_fetch` (route its egress through a container) and retires R7 with an **app-level** syscall hardening (not a container).

**Environment reality (drives D4):** the product deploys cross-platform (mac/win/linux); the dev box is WSL2 where the only container runtime is Windows Docker Desktop whose **daemon is down by default**. A fail-closed posture must therefore be paired with an explicit, loud operator escape hatch or it bricks development.

---

## ⭐⭐ Constitutional carry-forward (non-negotiable; inherited)

- **Gate unchanged / executor-decision-free.** The sandbox is a **substrate wrap below `_execute_local_call`** (in `subprocess_trust` / `net_trust` / the new `sandbox/` package). The gate stays the sole chokepoint; `_execute_local_call` stays **byte-frozen** (empty-executor-diff, ADR-028 D6 — 5th exercise). No tier/score/decide symbol enters the sandbox path.
- **No new `LLMPurpose`.** Pure infra; no judgment/routing LLM call enters the sandbox path (P4-roadmap §10).
- **Single-writer liveness (ADR-028 D5).** Container setup/teardown is a **new finite term** in the `(1+N)`-pass single-writer budget (ADR-033 D4). It must be bounded (timeout + kill), not become the unbounded term (the R5 lesson). Measured + capped.
- **Honest-residual inscription.** Accept the *real* post-P4.3 surface (D5), never a softened one; **no silent fail-open** (D4). The discipline that governed `RB-FS/NET`'s creation governs its retirement.
- **One retirement path.** The container wraps the existing exec; the app-level scoping (scoped-env, SSRF floor, `_check_path`) is **defense-in-depth that does not reverse**.

---

## Decisions

### D1 — Sandbox mechanism: OS containers, runtime-abstracted (cross-platform)

The sandbox mechanism is **OS containers** (Docker / podman), accessed through a **runtime abstraction** that detects the available runtime, probes daemon liveness, and builds the container invocation. Rationale (architect-ratified DP1): the **product deploys cross-platform** (mac/win/linux), and containers are the one sandbox mechanism with a cross-platform story (Docker Desktop on mac/win runs a Linux VM; native engine on Linux). Linux-native mechanisms (bubblewrap / nsjail / raw namespaces+seccomp) were the lighter-weight technical sweet spot **but are Linux-only** and are therefore **rejected** as the primary mechanism for a cross-platform product.

The abstraction (`sandbox/runtime.py`) detects `podman` then `docker` (prefer **rootless/podman** user-namespace semantics where present — better unprivileged-userns story), probes `info` for daemon liveness, and exposes a single `run(spec) -> result` + `available() -> bool`. The container CLI/API is the seam; no code path assumes one runtime.

### D2 — Isolation profile: FS + net(deny-default) + seccomp + UID + resources

Each sandboxed call runs in a **per-call container** (D3) with this isolation profile (`sandbox/profile.py`), retiring the residuals named:

- **FS** — read-only rootfs (`--read-only`); **bind-mount ONLY the workspace rw**, everything else absent/ro. Retires **R1/R2 (FS half)**. The host `~/.ssh`, `.env`, `config/*.yaml` are not in the container mount namespace. **Mount-leak stance (absorbed R0-B Y2):** `/var/run/docker.sock` is **NEVER** bind-mounted — a **constitutional invariant** (docker-sock = container-escape-via-API; test-enforced, plan P4.3-12 s6); `/sys` is read-only (Docker default, no `--privileged`); the container runs in a **private PID namespace** (Docker default, no `--pid=host`, so `/proc/1/root` stays the container's own root) with sensitive `/proc` paths masked (e.g. `/proc/sysrq-trigger`).
- **Network** — **deny-by-default egress** (`--network none` for tools that need no net; pytest/ruff/git-history). For the tools that legitimately egress (`git_push`, `web_fetch`) the boundary is **parent-pinned-IP per-call container egress** (architect-ratified, absorbed R0-B 🔴 R1): the parent's SSRF floor already resolves+validates+**pins a single IP** (`_resolve_and_validate`, `net_trust.py:79-122`); per call the container egress is constrained to **exactly that pinned IP:port** via a per-call ephemeral network + a daemon-side nftables/iptables rule on the bridge forward chain. **Container-internal DNS is disabled** (`--dns 0.0.0.0` / no resolver — DNS would bypass the pin). **Single-family pin** — the one resolved family (v4 or v6) is allowed; the other family's egress is blocked (no dual-stack escape). **Cross-platform honesty:** native Linux (rootless podman / native docker) supports the host-side per-call firewall fully; on the Docker Desktop VM (mac/win) where the host orchestrator cannot reach the VM's firewall, `web_fetch` (http/https) routes through a host-side filtering proxy pinned to the validated IP, and any (runtime × tool) combination where neither a pinned firewall nor a proxy is viable (e.g. `git_push` over ssh on Docker Desktop) is **deny-default → fail-closed** (the tool fails loudly on that runtime — never silently unconstrained). Retires **R1/R2 (net half), R4, R8** for the sandboxed surface (D3-coupled for `web_fetch`).
- **Syscall** — **strategy PINNED (absorbed R0-B Y1): the container runtime default seccomp profile (a curated blocklist baseline) AUGMENTED** with an explicit additional-deny set — *not* a full default-deny allowlist (rejected: first-party pytest/ruff/git need a broad syscall set, an allowlist is brittle + high-maintenance → the stronger-but-deferred tail, D5). **Enumerated additional denials** (shipped as a concrete `sandbox/seccomp.json` asset): `unshare`, `clone` (with `CLONE_NEWUSER`/`CLONE_NEWNET`/`CLONE_NEWNS`), `bpf`, `io_uring_setup`, `add_key`, `request_key`, `keyctl`, `ptrace`, `mount`, raw `socket`/`AF_PACKET`. Applied via `--security-opt seccomp=<profile>` + `--cap-drop=ALL` + `--security-opt no-new-privileges`.
- **UID** — run as **non-root** (`--user` / rootless user-namespace mapping to an unprivileged id). Privilege-escalation hardening; free with the namespace.
- **Resources** — `--memory`, `--cpus`, `--pids` + the existing per-call timeout. **The container kill (`<runtime> kill` + `rm -f`) tears down the whole process tree regardless of `setpgid`** — this is the clean retirement of **R3** (`setpgid(0,0)`-escape): a grandchild cannot orphan past the container boundary.

### D3 — The seam: one sandboxed-spawn interface; web_fetch egress reversal; app-level apply_edit; per-call; executor byte-frozen

- **One subprocess seam.** A single `sandboxed_run(argv, *, cwd, env, timeout_s, max_bytes, profile)` (`sandbox/spawn.py`) is the one interface **both** `run_scoped_command` (`subprocess_trust.py:202` → B3 tools + `git_push`) **and** the Posture-B plugin spawn (`plugins/code.py` `_PostureBFn` → `subprocess_mcp_stdio`) route through. Not per-tool — one interface, matching the ADR-034/035 "one retirement path."
- **In-process egress → container (REVERSES ADR-035 D4).** `web_fetch`'s egress is routed through a **per-call egress container** constrained to the parent-pinned IP:port (D2 Network) with container-internal DNS disabled. ADR-035 D4 chose in-process *specifically because a subprocess bought no isolation pre-sandbox*; post-sandbox that calculus flips. The **SSRF floor stays as defense-in-depth, re-homed around the sandboxed egress**: the parent still resolves-then-pins-then-validates **every redirect hop** (ADR-035 D2) and the container egress is constrained to that validated pinned target. R4 retired on the sandboxed surface.
- **apply_edit R7 = app-level, not a container.** R7 (parent-component TOCTOU) is retired by an **app-level `openat2(RESOLVE_NO_SYMLINKS)` / dir-fd walk** in `mutation_tools.py` — a narrow syscall-level hardening for one in-process writer, **not** forcing `apply_edit` into a container. (`openat2` is Linux-only; the cross-platform fallback + its residual posture is D5.)
- **Per-call container.** Fresh namespace per call (isolation correctness > latency); no cross-call state leak. Setup/teardown is the **new finite term** in the ADR-028 D5 / ADR-033 D4 `(1+N)`-pass budget. **Bounded (absorbed R0-B Y3):** the existing `run_sync` timeout wraps the whole `docker run` incl. container startup (setup is *inside* the deadline); teardown (`<runtime> kill` + `rm -f`) is **shielded** so a timeout-cancel still reaps the container (no leaked container). **Target: ≤ 3s p95 per-call setup/teardown** — the plan-vs-impl gate (P4.3-4 measures+logs against it; exceed → review rejects). The runtime **liveness probe is called once at bootstrap + cached per turn (short TTL ~30s)**, has its **own ~2s timeout** (a wedged `docker info` cannot hang the writer), and **daemon-dies-at-spawn** (available-at-probe, dead-at-run) raises `SandboxUnavailableError` and follows the same posture path (D4).
- **Executor byte-frozen.** The wrap lives **below** `_execute_local_call` (in `subprocess_trust`/`net_trust`/`sandbox/`). `_execute_local_call` stays byte-identical — the sandbox is a **substrate** change, not an executor-decision change (ADR-028 D6, empty-executor-diff 5×).

### D4 — Posture: default-on where available; fail-CLOSED default + loud operator opt-in to degraded

- **Default-on where the runtime is available** + operator-config (runtime select, egress allowlist, image). P4.3's whole point is to retire the residuals, which argues default-on.
- **Fail-mode when the runtime is UNAVAILABLE** (no daemon / no userns — a live WSL2 scenario): **FAIL-CLOSED by default.** No subprocess/egress executes without a working sandbox; the B3/B4/B5 tools fail with a loud, surfaced `sandbox_unavailable` (`TOOL_FAILED`), never silently unsandboxed. **Config-parse failure** (malformed `sandbox.yaml` / invalid `runtime` / missing keys) **→ FAIL-CLOSED** (same as runtime-unavailable + no opt-in — never a default that fails open) (absorbed R0-B Y5a). The `available()` result is **cached per turn** (short TTL) so a wedged daemon fails fast: the first unavailable probe blocks subsequent calls in the turn without re-probing (no per-call probe-timeout stack-up) (absorbed R0-B Y5b).
- **Explicit operator opt-in to the degraded app-level posture.** The operator may consciously opt in (config flag) to the **today posture** — scoped-env + SSRF-floor + `_check_path` app-level scoping — when the runtime is absent. This path is **LOUDLY LOGGED + surfaced on every degraded call** (a `WARNING`, not a debug line). The operator consciously chooses "run unsandboxed" exactly as they consciously activate a fetched plugin (ADR-031 D4). **Never a silent fallback** — that is the "softened surface" the honest-residual discipline forbids.

### D5 — P4.3's own honest residuals (Accept the real surface, not a softened one)

P4.3 leaves these, inscribed honestly (P4-roadmap §10; the ADR-029 D4 / ADR-031 D1a discipline):

- **R9 `send_email` recipient-exfil — NOT retired.** A netns bounds `send_email`'s *transport reachability* (which hosts), but the exfil is in the **recipient** (an allowed-domain address). The within-allowed-domain recipient-exfil persists past P4.3 as an **application/DLP** concern (ADR-036 D3-ii already framed it so). P4.3 bounds the transport; it does **not** claim to retire R9.
- **R8-if-broad-allowlist.** A real egress boundary retires R8, but an operator allowlist permitting a broad host set re-opens exfil-by-remote within that set — bounded by the allowlist breadth, an operator config concern.
- **Sandbox-escape surface.** The sandbox is new security code with its own escape history (userns CVEs, seccomp-hole syscalls, mount/`proc`/`sys` leaks, time-of-check races on the bind setup, rootless-vs-rootful surface). Probed at impl against the container-escape checklist (the R0-B threat lens).
- **Seccomp blocklist-not-allowlist (deferred-stronger tail).** D2 ships a Docker-default-blocklist-**augmented** profile (the enumerated denials), not a full default-deny allowlist. A default-deny allowlist is the stronger posture but brittle for first-party pytest/ruff/git (broad syscall need); it is the inscribed-deferred hardening tail — the residual is the syscalls left available outside the enumerated denials + Docker's default block.
- **Degraded-posture residual.** When D4's loud opt-in is active, the `RB-FS/NET` surface is re-exposed by operator choice — the named, loud fallback path.
- **Per-call setup latency.** The new finite term in the D5 single-writer budget; measured + bounded, not eliminated.
- **Cross-platform tails.** `openat2(RESOLVE_NO_SYMLINKS)` (R7 fix) is **Linux-only**; on macOS/Windows R7 degrades to a per-component dir-fd `O_NOFOLLOW` walk (best-effort) or the current final-component residual. And the subprocess **container image must carry a toolchain-complete environment** (python + pytest + ruff + the workspace deps) for `run_tests`/`run_lint` to work — an **operator-config burden** (the image is operator-provided; an incomplete image fails the tool, fail-closed).

---

## Considered alternatives

- **Bubblewrap / nsjail (lightweight jailers).** The technical sweet spot in this dev env (namespaces+seccomp+bind-mounts for one binary dep, no daemon) — but **Linux-only**. Rejected because the product deploys cross-platform (DP1). Would have been the lean had "Linux-only deployment" held.
- **Raw namespaces + seccomp + cgroups v2 (in-process).** Zero external dep, works unprivileged in WSL2 today, most portable *within Linux* — but Linux-only and highest engineering (you reimplement a jailer: UID maps, mount setup, seccomp BPF, cgroup wiring). Rejected: cross-platform + cost.
- **gVisor (runsc).** Strongest isolation (user-space kernel) but overkill for first-party fixed-argv commands over a trusted workspace, heaviest to stand up, WSL2-nested-virt friction. Rejected.
- **Persistent / warm container** (one long-lived sandbox, reused across calls). Lower per-call latency — but cross-call state-leak + lifecycle complexity. Rejected for **per-call** (D3): isolation correctness over latency.
- **Fail-open-to-today when runtime absent.** Preserves capability when Docker is down — but **silently re-exposes the `RB-FS/NET` residual P4.3 exists to retire**, the exact softened surface the honest-residual discipline forbids. Rejected for D4's fail-closed + loud opt-in.
- **Netns the whole orchestrator** (ADR-035's literal "network-namespace the process"). Hard to separate orchestrator-egress (LLM APIs, remote MCP, providers) from agent-egress in one process. Rejected for per-call egress containers (D3).

## Consequences

**Easier:** a real FS/network/syscall boundary; R1/R2/R3/R4/R8 retired on the sandboxed surface; R3's `setpgid`-escape cleanly killed by the container boundary; the egress firewall finally bounds agent-induced exfil to an operator allowlist; one seam for all subprocess exec.

**Harder:** a **container runtime dependency** (and its availability story — fail-closed breaks the loop when the daemon is down); the **image toolchain-completeness** operator burden; **per-call setup/teardown latency** added to the single-writer block × `(1+N)` passes; the **egress-allowlist mechanism** is non-trivial cross-platform (deny-default is `--network none`; a host allowlist needs a pinned-IP per-call network / filtering path); new security code with its own escape surface.

**Neutral:** the app-level scoping is retained as defense-in-depth (no reversal); the gate / confirm path / `_execute_local_call` are untouched.

## Reversibility

| Decision | Reverse cost | Forward-watch |
|---|---|---|
| D1 containers (vs jailer/raw-ns) | **Medium** — the runtime abstraction localizes the mechanism; a Linux-only deployment could add a jailer backend behind the same `sandboxed_run` seam | If a deploy target is Linux-only and latency-sensitive, a bwrap backend is additive behind the seam |
| D2 isolation profile | **Low** — the profile is data (`sandbox/profile.py` + seccomp asset); tightening the seccomp allowlist or adding dimensions is additive | The conservative seccomp allowlist's tight long tail is deferred (D5) |
| D3 web_fetch egress reversal | **Medium** — reverses ADR-035 D4; the SSRF floor stays so the app-level path is intact if reverted; `apply_edit` app-level fix is independent | Per-call egress-container latency for every `web_fetch` is the new liveness term |
| D4 fail-closed + loud opt-in | **Low** — a posture flag; the degraded path IS the old code, retained | If fail-closed proves too disruptive, the loud opt-in is the pressure valve — never a silent flip |
| D5 residuals | **N/A** (inscription) | R9 recipient-exfil → DLP slice past P4.3; cross-platform R7 / image tails tracked |

## References

- **Residual sources:** ADR-031 D1a + Reversibility; ADR-034 D2 + D4; ADR-035 D2 + D3-ii + D4 + impl-degradation ¶ (R5/R6); ADR-036 D3-i/ii/iii.
- **Constraints:** ADR-028 D5 (single-writer liveness) + D6 (empty-executor-diff); ADR-033 D4 (`(1+N)`-pass budget).
- **Substrate it wraps:** `mcp/subprocess_trust.py:202` (`run_scoped_command`; exactly 2 call sites — `subprocess_tools.py:114` `_dispatch`, `:251` `_make_git_push`), `:245-268` (`_kill_watchdog`), `:344` (`subprocess_mcp_stdio`); `tools/net_trust.py:37` (DNS executor — R5), `:40-63` (SSRF floor), `:79-122` (`_resolve_and_validate` — the pin), `:125` (`_SSRFValidatingTransport`), `:178` (`build_ssrf_client`); `plugins/code.py:93` (`_PostureBFn._async_call`); `tools/mutation_tools.py:71` (`apply_edit`); `api/app.py:205-262` (registry composition root).
- **Process:** P4-roadmap §3-A1 / §4 / §8 / §10; `docs/process/dual-lens-r0b.md`; the ADR-035 / P3.6 external-r0b-prompt precedent.
