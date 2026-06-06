---
task_id: P4.3
review: senior plan-vs-impl (impl-stage, dual-lens)
plan: docs/process/senior-plans/P4.3.md (P4.3-0..13)
adr: ADR-037 (Accepted 2026-06-05)
branch: claude/P4.3-impl
reviewed_commits: 2d5b163..311f4ca (P4.3-1..13)
author: senior planner
date: 2026-06-05
verdict: clean
findings: {blocking: 0, needs_architect: 0, nits: 1}
verdict_history:
- round: 1
  verdict: blocking
  reviewed_commits: 2d5b163..311f4ca (P4.3-1..13)
  summary: B1 — pinned-IP egress rule computed but never installed (silent unconstrained egress).
- round: 2
  verdict: needs_architect
  reviewed_commits: 311f4ca..f248a69 (P4.3-RW1..RW8)
  summary: B1 CLEARED (egress proxy live). Rework substantially plan-faithful. Two routable
    items, neither a delivered-code security hole — RA1 (ruff gate RED at HEAD, trivial 1-line)
    + RA2 (RW8-2 composition-root tests re-implement the branch instead of driving _build_context).
- round: 3
  verdict: clean
  reviewed_commits: f248a69..d3180f1 (P4.3-RW9)
  summary: RA1 CLEARED (ruff green at HEAD). RA2 CLEARED — `_resolve_sandbox_posture(config_dir)`
    extracted from `_build_context`; the 3 RW8-2 tests now drive the REAL function (no duplicated
    branch), so a fail-open regression in app.py breaks them. app.py change is a clean extract-method
    (both absence + parse-fail → fail_closed(); no `resolver=None` path; RW4 holds). All gates green
    stubbed (ruff + mypy --strict 262 + pytest 517 passed; no live daemon). No routable items remain.
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

---

# Round 2 — rework re-verify (P4.3-RW1..RW8)

Reviewed `311f4ca..f248a69` (the 8 rework commits) against the Rework R1 contract
(`senior-plans/P4.3.md` "# Rework R1") + my round-1 B1. Same plan-vs-impl lens (plan-implied
invariant drift). Daemon NOT reachable during the run — gates exercised stubbed.

## Verdict: **needs_architect** (was: blocking)

**B1 is CLEARED.** The load-bearing per-call egress constraint is now actually installed and
enforced at runtime — the exact gap that made round-1 blocking is closed. The rework is
**substantially plan-faithful** (RW1–RW7 match the contract; RW8 closes 4/5 of the wired-whole
gap). Two items remain for architect routing, **neither a security hole in delivered code**:
a RED ruff gate (trivial) and one wired-whole test that reproduces the very test-gap RW8 exists
to close. I surface; architect routes.

## ✅ B1 cleared — pinned-IP egress now installed + enforced (was the round-1 blocker)

The dead firewall-string is gone and a real, root-free, cross-platform boundary replaces it:

- **Proxy lifecycle inside `sandboxed_run`** (the exact "install/remove fires" demand of B1):
  `EgressProxy.start()` runs **before** `docker run` (`spawn.py:110-118`); `proxy.stop()` runs
  in the **shielded `finally`** (`spawn.py:158-159`), symmetric with network create/teardown,
  and fires on the timeout-cancel path.
- **Allowlist = exactly the one SSRF-pinned `(host, port)`**, dialing `pinned_ip` not the
  hostname (`egress_proxy.py:159-173`) → SSRF pinning preserved end-to-end; every other
  `CONNECT` (incl. a redirect-host) → 407 (resolves the round-1 per-hop-SSRF compounding for
  free via the per-CONNECT allowlist).
- **Dead string deleted:** repo-wide grep for `iptables`/`nftables`/`firewall_rule` finds only
  two *descriptive* doc-prose mentions of the **withdrawn** approach (`egress.py:12`,
  `test_egress.py:21` comment) — no enforcement string emitted, no `_build_firewall_rule`.
- **`build_egress_spec` no longer reports false success:** returns `PROXY` mechanism (the
  honest mechanism that *is* wired), not a `HOST_FIREWALL` success for an uninstalled rule.
- **Wired-whole test exists** (`test_spawn.py:216-292`): spies on the real `EgressProxy.start`/
  `stop` with `subprocess.run` mocked at the CLI boundary — asserts start AND stop fire,
  including on timeout-cancel. This is the RW8-1 class and it is genuinely wired.

## Rework plan-faithfulness (per RW atomic)

| RW | Contract | Delivered | Verdict |
|---|---|---|---|
| RW1 egress proxy | host-side filtering CONNECT proxy started/stopped in `sandboxed_run`; dead string deleted; allowlist=pinned host; ssh ProxyCommand | ✓ proxy live (above); `container_network_args` injects `HTTP(S)_PROXY` + `GIT_SSH_COMMAND` ProxyCommand + `--add-host host.docker.internal:host-gateway` + DNS-disabled (`egress.py:134-178`) | **faithful** |
| RW2 web_fetch | fetcher uses proxy env; no per-target `--add-host`; hostname → spec | ✓ `_sandbox_web_fetch` passes `hostname=` to `build_egress_spec` (`network_tools.py:199`); proxy env carries DNS-free fetch; only `host.docker.internal` add-host | **faithful** |
| RW3 seccomp | ALLOW-default + ERRNO denylist ⊇ P4.3 set; un-bricked | ✓ `defaultAction=SCMP_ACT_ALLOW`; 55 ERRNO denials incl. all enumerated (ptrace/unshare/bpf/mount/keyctl/io_uring_setup/add_key/request_key/…) | **faithful** |
| RW4 config fail-CLOSED | composition root never `None`; absence+parse-fail→`fail_closed()`; ordering before `load_plugins` | ✓ `posture.py:81-88` `fail_closed()`; `app.py:218-232` always assigns, both branches → `fail_closed()`; old `resolver=None` fail-open path deleted; block moved before `load_plugins` | **faithful** |
| RW5 plugin route | resolver threaded `load_plugins`→`_PostureBFn`; `-i`; container-teardown | ✓ end-to-end forwarding (`loader.py` + `code.py`); `app.py:252-253` passes resolver+sandbox_root; `-i` + `--network none` injected; `runtime.kill(cname)` in `_run_mcp_session` `finally` (`code.py`) | **faithful** |
| RW6 yellows | overhead-only latency gate; send_email warning; R5 wording | ✓ `spawn.py` measures setup+teardown only (not workload); send_email per-call WARNING threaded; "fixed 8-slot pool" wording corrected in net_trust + ADR-035 | **faithful** |
| RW7 inscription | R1/R4/R8 annotations match proxy+injected-plugin surface; no over-claim | ✓ ADR-031/035/036 annotations re-worded with "corrected RW7" markers + honest residuals (degraded-opt-in re-exposes R1; broad allowlist re-opens within-set exfil) | **faithful** |
| RW8 wired-whole | 5 wired-whole assertions; no mocking `sandboxed_run` for egress/plugin | ◑ 1/3/4/5 genuinely wired; **RW8-2 re-implements the composition-root branch** (see RA2) | **partial — RA2** |

## 🔴-gate RA1 (needs_architect — gate RED) — ruff fails at HEAD

The rework's own forcing function is "ruff + mypy `--strict` + pytest green **per commit**" — and
`uv run ruff check src tests` is **RED** at HEAD:

```
I001 [*] Import block is un-sorted or un-formatted
  --> tests/sandbox/test_egress.py:7  (one extra blank line after the import block)
```

Introduced by RW1/RW2 (`d063fb3`). **Trivial** (1-line, `ruff --fix`-able) but real: the branch
is not mergeable while a gate is red, and the per-commit-green discipline was not met. **mypy
`--strict src tests` = Success (262 files); pytest touched surface (`sandbox plugins tools`) exit
0 stubbed** (no daemon) with the known R5 thread-leak warning (round-1 Y2, non-fatal). Executor
byte-frozen since baseline (`b68d59b..HEAD` empty; s3 holds). **Route:** α quick-fix the blank
line (re-run ruff to green) — no design question, just an unmet gate.

## 🟡 RA2 (needs_architect) — RW8-2 reproduces the exact test-gap RW8 exists to close

RW8's stated purpose is to close the structural gap that let 5🔴 pass CI: *"every sandboxed path
is unit-tested by … hand-injecting a `PostureResolver`"*. RW8-2's acceptance is explicit: a test
that drives the **real `_build_context`/registry-build path** with no `sandbox.yaml`, **"NOT a
hand-injected resolver."**

The delivered tests (`test_constitution.py:148-251`) **re-implement** `app.py`'s
`if config_path.exists(): … else: PostureResolver.fail_closed()` branch **inline** (lines
163-170, 198-205, 233-240) and then inject the locally-built resolver — the comment concedes it:
*"via the REAL composition-root code path (**same logic as** api/app.py `_build_context`)."*
"Same logic as" is the tell: it is a **copy of the control flow, not a drive of it**. A fail-open
regression in `_build_context` (e.g. a revert to `resolver=None`) would **not** be caught — the
test builds its own `fail_closed()` regardless of what `app.py` does. That is the precise
anti-pattern RW8-2 was written to eliminate, relocated from "hand-inject SANDBOXED" to
"hand-build fail_closed via duplicated branch."

**Why this is 🟡 not 🔴:** the *delivered* production behavior is correct — I read `app.py:218-232`
and it does fail closed on both absence and parse-failure; and RW8 assertions 1/3/4/5 (proxy
start-stop, plugin-loader drive, seccomp, proxy semantics) **are** genuinely wired. So this is a
**regression-guard weakness on one assertion**, not a live hole. **Route:** α — call
`_build_context` directly (or extract a `_resolve_sandbox_posture(config_dir)` helper used by both
`app.py` and the test) so the composition-root branch is actually exercised; or accept the
duplicated-logic test as sufficient and inscribe the limitation.

## 🟢 Nit (record only)

- **G-rw1 — plugin deny-default built-then-discarded:** `code._build_sandboxed_harness_params`
  calls `build_deny_default_spec()` and discards it (`# validate path; args added separately`),
  then hand-adds `--network none`. Functionally identical (deny-default == `--network none`) but
  the spec→args path is bypassed for the plugin route. Tidy-up, not a finding.

## Round-2 confirmed faithful (positive record)

B1 cleared (egress proxy live + wired-whole test); dead firewall string deleted; RW1–RW7 match
the Rework R1 contract; RW8 1/3/4/5 wired at the CLI boundary (not `sandboxed_run`); config
fail-CLOSED at the composition root with the fail-open `None` path deleted + ordering fixed;
plugin resolver injected end-to-end with `-i` + `finally`-kill; seccomp un-bricked (ALLOW-default
⊇ Docker∪P4.3); inscriptions corrected to the delivered surface; executor byte-frozen; mypy
clean; pytest green stubbed without a daemon.

**Expected next:** state advances to `awaiting_R0_A` (Route B). Architect routes RA1 (ruff red —
trivial α) + RA2 (RW8-2 composition-root test fidelity) alongside the impl-stage dual-lens
re-run. B1 needs no further action.

---

# Round 3 — verdict bump → clean (P4.3-RW9, commit d3180f1)

Re-verified `f248a69..d3180f1` against my round-2 RA1 + RA2. Same plan-vs-impl lens. Daemon
NOT reachable — gates exercised stubbed.

## Verdict: **clean** (was: needs_architect)

Both routable items are resolved; the delivered production behavior is unchanged-correct and the
one weak regression-guard is now genuinely wired. No routable items remain.

## ✅ RA1 cleared — ruff green at HEAD

`uv run ruff check src tests` → **All checks passed!** The extra blank line in
`tests/sandbox/test_egress.py:7` is gone (auto-fixed in RW9). Per-commit-green discipline met.

## ✅ RA2 cleared — RW8-2 tests now drive the REAL composition-root branch

RW9 extracts `_resolve_sandbox_posture(config_dir) -> PostureResolver` from `_build_context`
(`app.py:172-198`) and `_build_context` now **calls** it (`app.py:245`). The 3 RW8-2 tests
(`test_constitution.py`) replace their inline `if exists/try/except/else` copy with a direct call
to `_resolve_sandbox_posture(tmp_path)` — they now drive the **same function** production uses, so
a fail-open regression in app.py (e.g. a revert of `except→fail_closed()` or the `else` branch)
**breaks the tests**. This is exactly the α-fix RA2 named ("extract a `_resolve_sandbox_posture`
helper used by both `app.py` and the test"). The copy-of-control-flow anti-pattern is gone.

## app.py change is a sound fail-closed refactor (RW4 still holds)

I read the full `app.py` diff (+59/−). It is a pure **extract-method**, not a behavior change:

- `_resolve_sandbox_posture` reproduces the old control flow byte-for-byte:
  `config_dir/"sandbox.yaml"` exists → `load_sandbox_config` + `from_config`; on
  `SandboxConfigError` → `fail_closed()`; **else** (absence) → `fail_closed()`. Both the
  **absence** AND **parse-fail** legs return `fail_closed()` — neither fails open.
- **No `resolver=None` path reintroduced.** Grep of `app.py` shows the only resolver origins are
  the two `fail_closed()` returns (+ `from_config` on a valid config); the single resolver is
  threaded into all three registries (local `:265`, subprocess `:283`, network `:299`) — never
  `None`. RW4's "composition root never None / no fail-open" invariant holds.
- Docstring + comment correctly cite ADR-037 D4 / A1-3 and label it the sole injection point.

## Gate status (all green, no live daemon)

- **ruff** `src tests`: All checks passed.
- **mypy --strict** `src tests`: Success, no issues in 262 source files.
- **pytest** touched surface (`sandbox tools plugins mcp`): **517 passed**, 3 warnings, exit 0.
  RW8-2 subset (`-k rw8`): **3 passed**. Warnings are the known round-1 Y2 R5 thread-leak
  (`test_net_trust.py:448`, non-fatal). Docker daemon NOT reachable → confirms stubbed pass.
- **executor byte-frozen:** `git diff b68d59b..HEAD -- tools/executor.py` empty. Invariant holds.

## Round-3 confirmed faithful (positive record)

RA1 cleared (ruff green); RA2 cleared (`_resolve_sandbox_posture` extracted + tests drive the real
function); app.py is a clean extract-method fail-closed on both absence and parse-fail with no
fail-open path (RW4 intact); B1 remains cleared (round 2); gates green stubbed without a daemon;
executor byte-frozen. **No routable items remain — plan-vs-impl is clean.**
