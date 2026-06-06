---
task_id: P4.3
review: senior plan-vs-impl (impl-stage, dual-lens)
plan: docs/process/senior-plans/P4.3.md (P4.3-0..13)
adr: ADR-037 (Accepted 2026-06-05)
branch: claude/P4.3-impl
reviewed_commits: 2d5b163..311f4ca (P4.3-1..13)
author: senior planner
date: 2026-06-05
verdict: blocking
findings: {blocking: 1, needs_architect: 3, nits: 4}
---

# Senior plan-vs-impl — P4.3 (container syscall/egress sandbox)

Reviewed all 13 impl atomics on `origin/claude/P4.3-impl` against the plan + ADR-037.
Dual-lens (R0-A ∥ R0-B) runs in parallel; this is the plan-vs-impl lens only
(plan-implied-invariant drift the external reviewers structurally cannot see).

## Verdict: **blocking**

One blocking gap: the load-bearing per-call egress constraint — the exact mechanism
that RESOLVED the R0-B round-1 BLOCKING R1 — is **computed but never installed**, so
sandboxed egress is silently unconstrained. This is the senior-unique class: the
literal per-atomic acceptance criteria are met, but the plan-implied invariant +
ADR-037 D2/D3 promise is not. I surface; architect routes.

## Gate status (all green, no live daemon)

- **ruff** `src tests`: All checks passed.
- **mypy --strict** `src tests`: Success, no issues in 260 source files.
- **pytest** `tests/sandbox` = 86 passed; full touched surface (`sandbox tools mcp
  plugins`) exit 0. **Docker daemon NOT reachable** during the run (CLI present, daemon
  down) → confirms tests pass **stubbed** (runtime mocked / `available()→False` paths).
  One non-fatal `PytestUnhandledThreadExceptionWarning` from `tests/tools/test_net_trust.py:446`
  (R5 abandoned-future test leaks a thread that raises `InvalidStateError` on a cancelled
  future) — tied to Y2 below.
- **executor byte-frozen:** `git diff b68d59b..HEAD -- tools/executor.py` is **empty**;
  s3 AST guard added. Empty-executor-diff invariant holds.
- **atomic↔commit 1:1 (RC-17):** 13 commits `P4.3-1..13`, each subject-named after its
  atomic; P4.3-0 (ADR-037 draft) landed at plan stage. No bundling. ✓

## Per-atomic delivery

| Atomic | Delivered | Notes |
|---|---|---|
| P4.3-1 runtime | ✓ (partial) | podman→docker liveness detect, 2s probe, no-escape, kill primitive ✓. **G1:** no `SandboxRuntime.run(spec)`; `ContainerSpec`/`ContainerResult` dead code (run logic relocated to spawn). |
| P4.3-2 profile+seccomp | ✓ (drift) | `--read-only`, bind-only-root, cap-drop ALL, no-new-privileges, nonroot, limits, docker-sock assert ✓. **Y1:** seccomp asset omits raw `socket`/`AF_PACKET`. **G3:** `/proc` mask via `--tmpfs` (vs comment's `/dev/null` bind). |
| P4.3-3 egress | ✓ shape / **B1** enforcement | spec shape, DNS-disabled, single-family flags, deny-default, Docker-Desktop fail-closed ✓. **Firewall rule emitted as a string but never installed** (see B1). |
| P4.3-4 spawn | ✓ (drift) | result-shape parity, container-kill, shielded teardown, network create/teardown, p95 logging, daemon-dies-at-spawn→raise ✓. **G2:** post-hoc slice, not streaming bounded-read. |
| P4.3-5 posture+config | ✓ | fail-closed default, degraded loud opt-in, config-parse→fail-closed, per-turn cache ✓; s1/s2 enforce. |
| P4.3-6 subprocess wire | ✓ (see Y3) | posture-resolved dispatch; FAIL_CLOSED→LocalToolError; **DEGRADED→app-level fallback ✓**; git_push remote-host resolution. Routes at closure layer not `run_scoped_command` (Y3). |
| P4.3-7 plugin wire | ✓ | Posture-B harness in-container, deny-default net, FAIL_CLOSED/DEGRADED branches; pb6/executor frozen ✓. |
| P4.3-8 web_fetch | ✓ (drift) | per-call egress container, in-process SSRF fallback on DEGRADED ✓. **Per-hop SSRF revalidation NOT preserved** — see B1 compounding. |
| P4.3-9 apply_edit openat2 | ✓ | `_hardened_open` openat2(RESOLVE_NO_SYMLINKS) Linux 5.6+ + O_NOFOLLOW fallback; residual inscribed ✓. |
| P4.3-10 NAT64 | ✓ | `is_denied_ip` unwraps `64:ff9b::/96` low-32 → floor; tests cover internal-denied/public-allowed ✓. |
| P4.3-11 R5 DNS | ✓ (drift) | head-of-line 1→8 fixed. **Y2:** fixed `max_workers=8`, not abandonable-thread/bounded-growth. |
| P4.3-12 constitution | ✓ (see Y3) | s1–s6 green; s5 allowlist widened vs plan (Y3). |
| P4.3-13 ADR annotations | ✓ | All residuals annotated to eventual-Accepted; R9 NOT-retired, R5 resolved ✓. |

---

## 🔴 B1 (BLOCKING) — pinned-IP egress rule computed but never installed → silent unconstrained egress

**The mechanism that resolved the R0-B round-1 BLOCKING R1 is not enforced at runtime.**

- `sandbox/egress.py:194 _build_firewall_rule()` produces the iptables/ip6tables DROP
  rule as a **string** in `EgressSpec.firewall_rule` (`egress.py:73,112,121`).
- **No consumer installs it.** Repo-wide grep for `firewall_rule`/`iptables`/`nftables`
  finds matches *only inside `egress.py`* (the builder). `spawn.py` does `_create_network`
  = bare `docker network create --driver bridge` (`spawn.py:198-208`) + `_remove_network`;
  it **never** installs the rule. `container_network_args` (`egress.py:166`) emits only
  `--network <name>`, `--dns 0.0.0.0`, and (v4-pin only) an ipv6-disable sysctl.
- **Consequence:** a sandboxed `web_fetch`/`git_push` container runs on a plain bridge
  with **full outbound egress**. The ADR-037 D2/D3 promise — "constrain egress to exactly
  the parent-validated pinned IP:port" — is not met. `build_egress_spec` returns
  `mechanism=HOST_FIREWALL` (i.e. *success*), so the caller believes egress is pinned
  when it is not → **silent fail-open**, the precise posture constitution s2 forbids
  ("never silently unconstrained").
- **Compounding (web_fetch, P4.3-8):** the in-container fetcher
  (`network_tools.py _SANDBOX_FETCHER_SCRIPT`) uses `urllib.request.urlopen`, which
  **follows redirects with no per-hop SSRF revalidation**; only the *first* hop is
  validated parent-side. The plan's P4.3-8 acceptance — *"the SSRF floor still validates
  **every hop**"* — is delegated to the (un-installed) egress pin. So a redirect to an
  internal IP is reachable: the per-hop SSRF protection B4 had in-process is **lost** on
  the sandboxed path. (Code comment at `_sandbox_web_fetch` concedes this: "for sandbox,
  the egress constraint is the primary enforcement.")

**Why plan-vs-impl, not R0-A/R0-B:** P4.3-4's literal acceptance only required "per-call
egress network created + torn down" (met), and P4.3-3 said the rule is "emitted" (met —
as a string). The plan **intended** installation as P4.3-4's job ("actual installation is
the caller's responsibility (P4.3-4 spawn.py)", `egress.py:201`), and did **not** scope it
out — only live-container *integration tests* (P4.3-12) were scoped out. So this is an
under-delivery against plan intent on a security boundary, invisible to deliverable-vs-spec.

**Architect routes:** (a) install the rule (+ teardown) in `spawn.py` and add a
runtime-mocked test asserting the install/remove calls fire — the real fix; or
(b) if live firewall-install is genuinely operator-env-only, make `build_egress_spec`
**not** report `HOST_FIREWALL` success when the rule won't be installed (so the gap is
loud, not silent) and inscribe the deferral in ADR-037 — but that implies fail-closed on
every egress tool until enforcement lands, conflicting with default-on. This is the
architect's call (security-completeness + honest-deferral inscription), not mine.

---

## 🟡 Needs-architect (drift on plan-implied invariant; not blocking)

**Y1 — seccomp asset omits raw `socket`/`AF_PACKET`.** Plan P4.3-2 enumerated
`unshare, clone{NEWUSER,NEWNET,NEWNS}, bpf, io_uring_setup, add_key, request_key, keyctl,
ptrace, mount, raw socket/AF_PACKET` and said "ship the concrete JSON asset … denying
**every** enumerated syscall." `seccomp.json` denies the first 11 but **not** socket; its
own `_note` is self-contradictory: *"raw socket/AF_PACKET is denied by Docker default;
enumerated here for auditability"* — yet they are **not** enumerated. `test_profile.py`
asserts `unshare`/`ptrace` only. **Route:** accept Docker-default reliance (then fix the
misleading `_note`), or add an explicit `socket`-with-AF_PACKET-arg deny to match the plan.

**Y2 — R5 fix is a fixed 8-slot pool, not the planned abandonable thread.** Plan P4.3-11
offered: per-call abandonable thread / `asyncio` true-cancel / "a small **bounded-growth**
pool." Impl set `ThreadPoolExecutor(max_workers=8)` (`net_trust.py:46`) — a **fixed** pool.
It raises the head-of-line threshold 1→8 but does not eliminate it: a permanently-hung
`getaddrinfo` (uncancellable at the C layer) **leaks its slot**, so 8 sustained hangs
re-wedge DNS — worse than the "abandon and move on" the plan intended. The ADR-035
annotation + commit msg call it "bounded-growth" (imprecise). The R5 test leaks a thread
(`InvalidStateError` warning above), a sign the abandonment isn't clean. **Route:** accept
8-slot bound for the single-writer model (+ fix terminology + quiet the test thread), or
require the abandonable-thread approach the plan named first.

**Y3 — sandbox-import leaf boundary widened vs plan/ADR.** Plan §1 + P4.3-12 s5 stated
sandbox is "imported only by api/ + subprocess_trust/net_trust." Impl routes the seam at
the **tool-closure** layer (`subprocess_tools._sandbox_dispatch`,
`network_tools._sandbox_web_fetch`, `plugins/code._PostureBFn`) rather than inside
`run_scoped_command`/`net_trust`, so those three modules import `orchestrator.sandbox.*`
directly and the **s5 test allowlist was broadened** to match (`test_constitution.py:207-215`).
Net: `run_scoped_command` itself is **not** sandbox-routed (its 2 real call sites are
covered at the closure layer, so functionally equivalent — but the architectural boundary
inscribed in ADR-037/plan no longer matches the code). **Route:** ratify the wider boundary
(reconcile ADR-037 §1 + plan wording) or require routing at the `run_scoped_command`/
`net_trust` seam as planned.

## 🟢 Nits (no routing needed; record)

- **G1 — dead code:** `runtime.py` `ContainerSpec`/`ContainerResult` unused; planned
  `SandboxRuntime.run(spec)` absent (relocated to `spawn._run_container`). Delete or wire.
- **G2 — bounded-read post-hoc:** `spawn._run_container` `subprocess.run(capture_output=True)`
  then slices `[:max_bytes]` — full output buffered in host memory before truncation; plan
  said "reuse existing bounded-read machinery" (streaming cap). Low risk (timeout + memory
  limit bound it indirectly).
- **G3 — `/proc` mask via `--tmpfs <file>`** (`profile.py:89`) vs the docstring's "bind
  `/dev/null`"; `--tmpfs` over a file path likely no-ops at runtime. Operator-env follow-up.
- **G4 — private-attr reach:** `posture_resolver._config.image` accessed across module
  boundaries in 3 wirings; add a public `image` accessor.

## Confirmed faithful (positive record)

empty-executor-diff held (executor byte-frozen + s3); docker-sock NEVER mounted
(`_assert_no_docker_sock` + s6, 3 tests); fail-closed default + degraded-loud-opt-in with
real app-level fallback in all 3 wirings (s1/s2); NAT64 R6 fold-in; apply_edit
openat2 R7 retirement + inscribed residual; P4.3-13 annotations match eventual-Accepted
(R9 NOT-retired, R5 resolved); gates green stubbed without a live daemon; 13 atomics 1:1
commits per RC-17.

**Expected next:** state advances to `awaiting_R0_A` (ADR-008 Amendment 1, Route B — never
short-circuits). Architect routes B1 (blocking) + Y1/Y2/Y3 after the dual-lens lands.
