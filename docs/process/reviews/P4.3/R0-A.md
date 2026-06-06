---
task_id: P4.3
round: R0-A
verdict: clean
verdict_history:
  - round: 1
    date: 2026-06-05
    verdict: blocking
    red: 4
    yellow: 1
    summary: >-
      4🔴 — Y1 egress pin a dead string (+ sandboxed web_fetch DNS-broken),
      Y2 plugin sandbox dead code (resolver never injected), Y3 config fails
      OPEN on absence+parse-fail, Y4 seccomp default-deny brick. Suite green
      only because it mocked sandboxed_run / hand-injected resolvers.
  - round: 2
    date: 2026-06-06
    verdict: needs_architect
    red: 0
    yellow: 2
    summary: >-
      All 4 round-1 🔴 RESOLVED and re-verified end-to-end against RW1–RW8
      (host-side CONNECT proxy actually installed + wired into the spawn
      lifecycle; resolver injected through the full loader chain; composition
      root fail-CLOSED on absence+parse-fail; seccomp defaultAction=ALLOW +
      denylist). Y5 latency-gate fixed; RW7 inscriptions now honest; RW8
      wired-whole tests mock at the CLI boundary and close the test-gap.
      Two NEW non-blocking 🟡 — (a) ruff I001 in tests/sandbox/test_egress.py
      (one blank line, auto-fixable; the ONLY non-green gate, must-fix before
      merge); (b) CONNECT-only proxy → sandboxed plain-http web_fetch 407/405s
      (fails-closed, https unaffected). Dual-lens convergence: R0-B round 2
      (1abd9d4) also cleared all 4🔴. needs_architect = dispatch the 1-line
      ruff micro-fix (RW9) before merge; NOT a 🔴/design re-route.
  - round: 3
    date: 2026-06-06
    verdict: clean
    red: 0
    yellow: 0
    summary: >-
      RW9 (d3180f1) resolves BOTH round-2 gating 🟡 with no regression and no
      fail-open reintroduced. RA1: ruff I001 fixed — `ruff check src tests`
      (canonical) + `ruff check .` GREEN. RA2: app.py extract-method
      `_resolve_sandbox_posture(config_dir) -> PostureResolver` — non-Optional
      return → mypy --strict structurally forbids a fail-open path; present →
      from_config, parse-fail → log + fail_closed(), absent → fail_closed();
      resolver threaded into all 3 registries (plugins/subprocess/network),
      none receives None. The 3 RW8-2 constitution tests now import + call the
      REAL helper (absence / parse-fail / web_fetch), so a fail-open revert
      breaks them — the round-2 "test re-implements the branch inline" note is
      CLOSED. Pure refactor, NOT a RW4 regression (it strengthens the contract).
      s3 executor byte-frozen still holds (empty diff vs origin/main). Gates
      green (no live daemon): ruff clean; mypy --strict 262 files; pytest
      sandbox+integration+tools+plugins exit 0 (~451 tests, zero FAILED/ERROR);
      constitution 15 passed. Round-2 N2 (CONNECT-only plain-http) remains a
      non-blocking inscription follow-up — does not gate clean.
findings_count:
  red: 0
  yellow: 0
  green: 18
---

# P4.3 R0-A review (architect-partner lens) — impl-stage, dual-lens

| Field | Value |
|---|---|
| Round | R0-A (impl-stage, mandatory; dual-lens — R0-B cross-family ran in parallel and landed `blocking`) |
| Reviewer | architect-partner (Claude Opus 4.8, 1M context), primary session |
| Date | 2026-06-05 |
| Against | ADR-037 (Accepted 2026-06-05) + the sandbox constitution (tests/sandbox/test_constitution.py s1–s6) |
| Artifacts | 13 impl commits `f6d93fe`(P4.3-1) … `311f4ca`(P4.3-13) on `claude/P4.3-impl`; reviewed at `311f4ca` (branch later doc-only-advanced to `0f670a1` = R0-B's own review file — source tree byte-identical, cites valid). New `sandbox/` package (runtime/profile/seccomp/egress/spawn/posture) + tool wiring (subprocess_tools, network_tools, mutation_tools, net_trust, plugins/code, api/app) + tests + P4.3-13 ADR annotations. |
| Gates | ruff **clean**; mypy --strict **clean** (260 files); full pytest **green** (exit 0; targeted sandbox+wired suites 179 pass; stubbed — no live Docker daemon). |

**Verdict: blocking.** The sandbox *package primitives* are well-built and the *in-process* residual fixes (R5/R6/R7) are correctly wired and active. But the three retirements that require the container to actually **run and enforce** — R1 (plugin), R4/R8 (egress pin) — plus the **fail-closed posture itself** are not delivered end-to-end, and the seccomp asset would brick the container on a live daemon. The suite is green because it mocks `sandboxed_run`, hand-injects resolvers, and runs no daemon — it validates the units in isolation but never the wired, enforcing whole. **I surface; architect routes** (rework vs accept-with-followup-slice + ADR-037/inscription correction). Strong dual-lens convergence: R0-B independently landed `blocking` on the same core cluster.

---

## 🔴 RED — blocking (4)

### 🔴 Y1 — The pinned-IP egress constraint is never enforced; sandboxed `web_fetch`/`git_push` are also functionally broken
The load-bearing network boundary — the mechanism that retired the plan-stage R0-B round-1 🔴 R1 and unblocked Accept (`P4.3.yaml` override_history; ADR-037 D2 ¶Network: *"constrained to exactly that pinned IP:port via a per-call ephemeral network + a daemon-side nftables/iptables rule on the bridge forward chain"*) — is **a dead string**.

- `_build_firewall_rule` (`sandbox/egress.py:194-213`) returns an iptables/nftables rule as text; it is stored on `EgressSpec.firewall_rule` (`egress.py:73,112,121`) and **consumed by nothing** (grep `firewall_rule` / `iptables` → only the definition, the build, and docstrings; no installer anywhere in `src/`).
- `container_network_args` (`egress.py:166-191`) emits only `--network <ephemeral-bridge>` + `--dns 0.0.0.0` (+ optional ipv6 sysctl). `spawn.py:198-208` `_create_network` creates a plain `--driver bridge` network — **full NAT'd outbound**, no `--internal`, no rule.
- **Security consequence:** the container egress is NOT constrained to the pin. A literal-IP exfil URL (`https://<public-ip>/?d=secret`) bypasses DNS-disable and the bridge permits it → **R4/R8 are not retired on the sandboxed surface** as the new ADR-035 D2 / ADR-036 D3-iii annotations claim. DNS-disable only blocks *hostname* egress, not the pin.
- **Functional consequence:** the fetcher receives the original **hostname** URL (`network_tools.py:208-214` passes `url_str`), the container has DNS off (`egress.py:184`) and **no `--add-host hostname:pinned_ip`** (grep: none) and the URL is not rewritten to the IP → on a live daemon the in-container `urllib.urlopen(url)` cannot resolve the host → **every sandboxed `web_fetch` fails**; `git_push` likewise (git can't resolve the remote with DNS off). The correct resolve-then-pin pattern *exists in-process* (`net_trust.py:168-176` — `copy_with(host=pinned_ip)` + `sni_hostname`) but was not carried into the container.
- **Why the suite misses it:** every SANDBOXED `web_fetch` test mocks `orchestrator.sandbox.spawn.sandboxed_run` (`test_web_fetch_sandbox.py:42,60`) — the container never runs; the spec is never enforced. No test asserts the firewall rule is installed or that the container can reach only the pin.
- **Converges with R0-B R0B-2 (firewall informational-only) + R0B-3 (DNS-disabled+hostname breakage).**

### 🔴 Y2 — Posture-B plugin sandbox routing is unreachable dead code (R1 not retired)
`_PostureBFn.__init__` accepts `posture_resolver`/`sandbox_root` (`plugins/code.py:84-92`) and `_async_call` routes through a container when set (`code.py:115-133`). **But the production loader never injects it:** `_load_posture_b_fns` constructs `_PostureBFn(...)` with no resolver arg (`code.py:252-257`), `load_plugin_code` has no resolver parameter to forward (`code.py:261-279`), and the composition root calls `load_plugins(...)` with no resolver (`api/app.py:216-226`). So `_PostureBFn._posture_resolver` is **always `None`** in production → the entire P4.3-7 sandbox branch + `_build_sandboxed_harness_params` is dead code → **R1 (fetched-plugin child runs with full FS-read + outbound-net) is NOT retired**, contradicting the ADR-031 D1a P4.3 annotation (*"R1 … RETIRED … the container sandbox wraps the Posture-B subprocess"*).
- **Why the suite misses it:** `test_posture_b_sandbox.py` hand-injects a resolver via `_make_fn(..., resolver=resolver)` (`:36-43,:53`) and unit-tests `_build_sandboxed_harness_params` in isolation; **no test drives `load_plugin_code`/`load_plugins`** to verify the resolver reaches the closure.
- **Secondary (same area):** even if reached, `_build_sandboxed_harness_params` builds `StdioServerParameters(command=cli, args=["run", …])` with **no `-i`** (`code.py:162-173`; `build_container_args` never adds it) — MCP stdio needs the child's stdin held open (`docker run -i`), so the handshake would hang.
- **Goes deeper than R0-B R0B-8**, which critiqued the sandboxed-plugin path's teardown but assumed it was *reachable*; the primary defect is that it is never taken.

### 🔴 Y3 — Composition root fails OPEN on config-parse-failure AND config-absence (inverts ADR-037 D4)
`api/app.py:245-256`: if `sandbox.yaml` is **absent** (`_sandbox_config_path.exists()` False) **or** `load_sandbox_config` raises `SandboxConfigError`, `_sandbox_posture_resolver` stays `None`. The registries then receive `posture_resolver=None` (`app.py:264,280`), and with `None` the tools take the app-level branch — `_dispatch`/`run_scoped_command` (`subprocess_tools.py:240-245`) and `_inprocess_web_fetch` (`network_tools.py:147-150`) — i.e. **unsandboxed, no FAIL_CLOSED, no per-call WARNING.** The comment at `app.py:237` inscribes the fail-open as intended.
- Directly contradicts ADR-037 D4 (*"Config-parse failure → FAIL-CLOSED … never a default that fails open"*; *"never silently unsandboxed"*) + the absorbed R0-B-plan Y5a, and is the rejected *"Fail-open-to-today when runtime absent"* alternative (ADR-037 Considered alternatives).
- **Current dev-box reality:** there is no `config/sandbox.yaml` (only `.example`) and no live daemon → **post-P4.3 runtime behavior is byte-identical to pre-P4.3 unsandboxed**, while R1–R4/R8 are inscribed retired.
- **Constitution s2 tests the wrong layer:** `test_s2_config_parse_failure_is_fail_closed` (`test_constitution.py:120-138`) asserts only that the *primitive* (`load_sandbox_config` raises; a `runtime=None` resolver resolves FAIL_CLOSED) — not the composition-root wiring that decides whether a resolver exists. s1 likewise hand-injects a resolver. So s1/s2 are green while the wired behavior fails open.
- **Converges with R0-B R0B-4 (config-parse fail-open).** My lens additionally covers the **config-absence** case (the broader, currently-active hole).

### 🔴 Y4 — seccomp asset is default-deny with zero allowed syscalls → bricks the container + contradicts ADR-037 D2
`sandbox/seccomp.json:2` sets `"defaultAction": "SCMP_ACT_ERRNO"` and every `syscalls` entry is also `SCMP_ACT_ERRNO` (more denials) — **there is no `SCMP_ACT_ALLOW` anywhere.** `profile.py:130-135` (`_seccomp_arg`) passes the file verbatim as `--security-opt seccomp=<json>`, which **replaces** the runtime default profile (it does not merge/augment). Net effect on a live daemon: deny-by-default + allow-nothing → every syscall returns EPERM → the container cannot exec a single instruction.
- This also **contradicts ADR-037 D2 verbatim**: *"the container runtime default seccomp profile (a curated blocklist baseline) AUGMENTED with an explicit additional-deny set — **not** a full default-deny allowlist."* The asset *is* a full default-deny. The `_note` (`seccomp.json:106`) and `profile.py:101-102` comment ("Docker default augmented") encode a merge-with-default mental model that `--security-opt seccomp=` does not provide.
- **Stubbed tests miss it:** `get_additional_deny_syscalls` only asserts names are present; nothing applies the profile to a running container.
- **Converges with R0-B R0B-1.** Surfaced here on re-reading D2 against `seccomp.json:2`; R0-B's runtime-brick framing is the sharper operational statement of the same defect. (Subsumes my earlier socket/AF_PACKET enumeration nit — moot under default-deny.)

---

## 🟡 YELLOW — should-fix (1)

### 🟡 Y5 — The ≤3s p95 setup/teardown gate measures total wall-time (incl. the workload)
`spawn.py:136-150` compares `total_s` (the whole `docker run`, including e.g. a 120s `run_tests`) against `SETUP_TEARDOWN_P95_TARGET_S=3.0` → the plan-vs-impl "≤3s p95 setup/teardown" budget metric conflates container overhead with workload, and the warning fires on every real `run_tests`/`run_lint`. `setup_s` (network-create only) and `teardown_s` are measured separately, but container-startup overhead is not separable from the workload in this `subprocess.run`-blocking structure. The *bound* itself (timeout-wrapped run + shielded `finally` teardown) is sound; only the **measurement feeding the gate** is wrong. **Converges with R0-B R0B-5.**

---

## 🟢 GREEN — confirmed (11)

1. **Executor byte-frozen (5th exercise).** `git diff origin/main -- tools/executor.py` **empty**; s3 AST test (`test_constitution.py:146`) passes; `_execute_local_call` (`tools/executor.py:385`) references no sandbox symbol. ✓ (R0B-9)
2. **`/var/run/docker.sock` never bind-mounted.** `_assert_no_docker_sock` (`profile.py:138-148`) + s6 (3 tests) green across all profile variants. ✓ (R0B-11)
3. **`--cap-drop=ALL` + `no-new-privileges` + `--user nobody` + `--read-only` + workspace-only rw mount** (`profile.py:81-114`). ✓ (R0B-10/11)
4. **Deny-default `--network none`** for no-net tools (`build_deny_default_spec` → `container_network_args`; s4 green) — genuinely retires the net-half of R1/R2 for `run_tests`/`run_lint`/`git_blame|log|diff`. ✓
5. **R3 container subtree-kill, shielded.** `spawn.py` `_safe_kill`→`runtime.kill` (`kill` + `rm -f`) in `finally` (`spawn.py:130-135,222-224`) — reaps the tree past `setpgid`. ✓ (R0B-17)
6. **R5 DNS head-of-line fix.** bounded-growth pool `max_workers=8` + per-future timeout/abandon (`net_trust.py:46,103-111`). ✓ (R0B-14)
7. **R6 NAT64 fold-in.** `is_denied_ip` unwraps `64:ff9b::/96` → re-checks embedded v4 (`net_trust.py:61-65`). ✓ (R0B-13)
8. **R7 openat2.** `_try_openat2(RESOLVE_NO_SYMLINKS)` Linux + `O_NOFOLLOW` fallback (`mutation_tools.py:58-114`); in-process, **always active** (no resolver dependency) → R7 genuinely retired on Linux, cross-platform residual honestly inscribed (D5). ✓ (R0B-15)
9. **In-process SSRF floor correct** (DEGRADED + no-resolver path): resolve-then-pin via `copy_with(host=pinned_ip)` + `sni_hostname`, `verify=True`, `retries=0`, every-redirect-hop re-validation (`net_trust.py:142-189`). ✓
10. **Liveness probe bounded + per-turn cached** (`runtime.py:100-114` 2s timeout; `posture.py:98-106` TTL cache). ✓ (R0B-16)
11. **Gates green** — ruff clean; mypy --strict 260 files clean; full pytest exit 0 (stubbed). ✓

---

## Meta: P4.3-13 inscriptions currently describe a softer-than-real surface
P4.3's own thesis is *"honest-residual inscription — Accept the real surface, never a softened one"* (ADR-037 ⭐⭐). Given Y1/Y2/Y4, the P4.3-13 annotations now assert retirements the impl does not deliver: **ADR-031 D1a** ("R1 … RETIRED"), **ADR-035 D2** ("R4 … RETIRED … constrained to the parent-pinned IP"), **ADR-036 D3-iii** ("R8 … RETIRED/NARROWED"). The R3/R5/R6/R7/R9 annotations are accurate. So the inscriptions are presently *softer-than-real* — the precise discipline the ADR foregrounds. Whatever the routing, the R1/R4/R8 inscriptions should be corrected to match the delivered surface.

## Cross-lens map (for synthesis)
| Finding | R0-A (this) | R0-B (cross-family) | Relationship |
|---|---|---|---|
| Egress pin not enforced | 🔴 Y1 | 🔴 R0B-2 | converge |
| Sandboxed web_fetch DNS-break | 🔴 Y1 | 🔴 R0B-3 | converge |
| seccomp default-deny brick | 🔴 Y4 | 🔴 R0B-1 | converge (R0-B operational; mine ADR-D2) |
| Config fail-OPEN | 🔴 Y3 (parse **+ absence**) | 🔴 R0B-4 (parse) | converge; mine broader |
| Plugin sandbox not delivered | 🔴 Y2 (**dead code — resolver never injected**) | 🟡 R0B-8 (teardown/path divergence) | mine deeper |
| p95 measures total time | 🟡 Y5 | 🟡 R0B-5 | converge |
| Sandbox redirect re-validation absent | — | 🟡 R0B-6 | R0-B-only (valid; coupled to Y1) |
| `send_email` no per-call DEGRADED warning | — | 🟡 R0B-7 | R0-B-only (transparency) |
| Structural spine sound (frozen/nonroot/cap-drop/read-only/sock-never/NAT64/R5/R7/probe/teardown) | 🟢 ×11 | 🟢 ×10 | converge |

Both lenses independently land **blocking** on the same cluster: the container, as wired, does not enforce the isolation ADR-037 claims (egress pin, plugin route, fail-closed posture) and the seccomp asset would brick it on first live run. **Architect: route the 🔴 cluster** (the natural shape is plan + ADR-037/inscription revision → junior re-dispatch), and call whether config-presence-gating (Y3) is an acceptable staged-rollout posture or must fail-closed per D4 — that routing/scope decision is yours.

---

# Round 2 re-verification — rework RW1–RW8 (architect-partner lens)

| Field | Value |
|---|---|
| Round | R0-A **round 2** (impl-stage rework re-verify; dual-lens — R0-B cross-family re-ran in parallel, `1abd9d4`) |
| Reviewer | architect-partner (Claude Opus 4.8, 1M context), primary session |
| Date | 2026-06-06 |
| Against | the round-1 4🔴 + the architect-ratified rework design (ADR-037 Amendment 1 — host-side CONNECT proxy **A1-1**; config fail-CLOSED per **D4**; seccomp **ALLOW-default + denylist**) |
| Reviewed at | `f248a69` (RW7 HEAD of the impl) on `claude/P4.3-impl`. Rework commits: `0e6b09d`(RW4) `381e1d4`(RW3) `dfe7640`(RW6) `d063fb3`(RW1/RW2) `29d6edc`(RW5) `c2dd860`(RW8) `f248a69`(RW7), atop design `ce692e3`/`898ea36`. |
| Gates | mypy --strict **clean** (262 files); pytest **green** across every rework-touched surface — `tests/sandbox`+`tests/integration` (149) and `tests/plugins`+`tests/tools` (exit 0); **ruff = 1 error** (I001, `tests/sandbox/test_egress.py:18`, auto-fixable — the only non-green gate). Full-suite not separately re-confirmed this round (parallel-session workspace contention); unchanged areas carry round-1's green + mypy. No live Docker daemon (stubbed at the CLI boundary). |

**Round-2 verdict: all 4 round-1 🔴 are RESOLVED and re-verified end-to-end.** The rework did not paper over the findings — it replaced each dead mechanism with a working, wired, enforcing one, and the new wired-whole tests exercise them at the **CLI / loader boundary** (not the `sandboxed_run` mock + hand-injected resolvers that let round 1 pass CI). The only thing standing between this branch and merge is a **one-blank-line ruff auto-fix** (a new, post-rework gate regression — not one of the 4🔴). **I surface; the architect dispatches the 1-line fix → merge.** This is `needs_architect` only in the mechanical sense (a junior micro-dispatch), **not** a 🔴 or a design re-route.

## The 4 🔴 — each re-verified RESOLVED

### ✅ Y1 (egress pin a dead string + sandboxed web_fetch DNS-broken) → RESOLVED
- Dead `_build_firewall_rule` / `firewall_rule` / iptables string **deleted** (grep: only a docstring noting the *withdrawn* nftables approach remains — honest).
- A real host-side filtering CONNECT proxy (`sandbox/egress_proxy.py`) is **installed and wired into the spawn lifecycle**: `spawn.py:110-118` starts `EgressProxy` **before** `docker run`; `spawn.py:158-159` stops it in the **shielded `finally`** — re-verified by `test_spawn.py::test_rw8_proxy_stop_fires_on_timeout_cancel` (stop fires even when the run raises `TimeoutExpired`). `proxy_port` flows to `container_network_args` (`spawn.py:130`); net args merged before the image (`:132-136`).
- Container pointed at the proxy: `HTTP(S)_PROXY=http://host.docker.internal:<port>` + `--add-host host.docker.internal:host-gateway` + `--dns 0.0.0.0` (`egress.py:155-176`).
- Proxy **dials the SSRF-pinned IP, not the hostname** (`egress_proxy.py:170-174`) and **refuses every non-pinned CONNECT — incl. redirect-hosts and wrong-port — with 407** (`egress_proxy.py:159-168`). SSRF pin preserved end-to-end; redirect/literal-IP exfil blocked at the proxy.
- Functional break fixed: the in-container urllib fetcher receives the **hostname** URL (`network_tools.py:209-215`) and honors `HTTPS_PROXY` → CONNECTs via the proxy → no in-container DNS needed (resolve happens on the host, in the proxy's `create_connection(pinned_ip)`).
- ssh `git_push`: `GIT_SSH_COMMAND` with `ProxyCommand nc -X connect` routes ssh through the same proxy (`egress.py:170-176`; `subprocess_tools.py:432-442` resolves the remote host + builds the PROXY spec). Architect-ratified (supported via ProxyCommand, not disabled).
- Fail-closed when the posture is FAIL_CLOSED (`network_tools.py:191`, `subprocess_tools.py:173`).
- **R4/R8 genuinely retired on the sandboxed surface** for the **fixed cooperative clients** (urllib fetcher, git) the sandbox actually runs.
- *Honest residual, inherent to the ratified A1-1 (not a regression):* the PROXY-mechanism network is a NAT'd bridge, **not** `--internal`; enforcement relies on the in-container client honoring the proxy env. This holds because the only PROXY surfaces run **fixed** clients; the **untrusted** plugin container uses `--network none` (Y2). The `egress_proxy.py` docstring inscribes this D5 tail. **R0-B round 2 surfaces the same as a new non-blocking 🟡 ("bridge -internal" / "proxy bind 0.0.0.0") — converges with this note.**

### ✅ Y2 (plugin sandbox dead code — resolver never injected) → RESOLVED
- Resolver now injected through the **full loader chain**: `load_plugins(...posture_resolver...)` (`loader.py:507`) → `_load_plugin` (`:608-609`) → `load_plugin_code` (`:458-459`) → `_load_posture_b_fns` (`code.py:303-304`) → `_PostureBFn` (`code.py:298-305`).
- **Composition-root ordering fixed:** `app.py:219-232` builds the resolver **before** `app.py:242-254` calls `load_plugins(..., posture_resolver=_sandbox_posture_resolver)`.
- `-i` injected for MCP-stdio (`code.py:182-183`); container teardown in `finally` via `runtime.kill` (`code.py:237-240`).
- Untrusted plugin container uses **deny-default `--network none`** (`code.py:185-192`) — the Y1 NAT'd-bridge residual does **not** apply to fetched (potentially-malicious) plugin code.
- Re-verified by `test_posture_b_sandbox.py::test_rw8_load_plugin_code_sets_resolver` — drives the real `load_plugin_code(...fetched...)` and asserts `_PostureBFn._posture_resolver IS resolver` (the exact assertion **absent** in round 1) + `-i` / `--cap-drop` / `--read-only` / `--network none` / non-empty container name. **R1 retired** (SANDBOXED posture).

### ✅ Y3 (config fails OPEN on absence + parse-fail) → RESOLVED
- `app.py:219-232`: resolver is **always** constructed — present → `from_config`; `SandboxConfigError` → `fail_closed()` (`:230`); **absent → `fail_closed()`** (`:232`). The three registries (`:252,270,286`) never receive `None`.
- `PostureResolver.fail_closed()` → FAIL_CLOSED on every resolve (`posture.py:88,102`); `assert_sandboxed_or_raise` never returns a runtime when unavailable, never silently spawns (`:117-141`).
- `config/sandbox.yaml` is **shipped** (not just `.example`) for the repo dev loop with `degraded_app_level: true` — the architect-ratified, committed, **loud-per-call** DEGRADED opt-in (`posture.py:128-137`), categorically distinct from round 1's silent fail-open.
- Re-verified by `test_constitution.py::test_rw8_config_absence_real_path_fail_closed` + `…parse_failure…` + `…web_fetch…`: fail_closed resolver → real registry builder → tool raises `sandbox_unavailable` **and** the app-level fallback (`run_scoped_command` / `build_ssrf_client`) is **never called**. (Minor: the test replicates the composition-root branch inline rather than importing `_build_context`; I independently confirmed `app.py:219-232` matches it byte-for-logic.)

### ✅ Y4 (seccomp default-deny brick) → RESOLVED
- `seccomp.json:2` now `"defaultAction": "SCMP_ACT_ALLOW"`; the `syscalls` denylist = Docker-default dangerous set ∪ P4.3 denials (incl. arg-filtered `clone` NEWUSER/NEWNET/NEWNS). **Augments rather than bricks** — exactly the ratified fix.
- `profile.py:130-135` applies it via `--security-opt seccomp=`; the asset is now a complete standalone allow-default+denylist profile, honest about replace-not-merge (`seccomp.json:60` comment; `socket/AF_PACKET` denied by `--cap-drop=ALL`/no CAP_NET_RAW, not here). `_assert_no_docker_sock` invariant intact (`profile.py:121`).
- Re-verified by `test_profile.py` (defaultAction=ALLOW, **not** ERRNO; denylist ⊇ P4.3 set ∪ Docker-default sample).

## Y5 (latency gate measured total wall-time) → RESOLVED
`spawn.py:140` measures `setup_s` **before** the workload; `:163` `overhead_s = setup_s + teardown_s` excludes the workload; the gate warning (`:172`) fires on overhead only. Converges with R0-B R0B-5.

## Inscriptions (RW7) → corrected + honest
ADR-031 D1a (R1), ADR-035 D2 (R4), ADR-036 D3-iii (R8) annotations now describe the **delivered** proxy / injected-container mechanism and each carries its residual (degraded-opt-in re-exposes R1; broad allowlist re-opens within-set for R8; R9 remains correctly BOUNDED-NOT-RETIRED). The round-1 "softer-than-real" gap is closed.

## Test-gap (RW8) → closed at the right boundary
New tests mock at `subprocess.run` / the CLI / the loader entrypoints — **not** at `sandboxed_run` — and assert the install/teardown actually fires, the resolver actually reaches the closure, and the composition-root fail-closed path actually blocks. This is the discipline whose absence let round 1's reds pass CI. s3 (executor byte-frozen) holds (empty diff vs `origin/main`); s5 updated for the new `loader.py` TYPE_CHECKING import.

## 🟡 NEW (round 2) — non-blocking, surfaced for completeness

### 🟡 N1 — ruff I001 in `tests/sandbox/test_egress.py:18` (the only non-green gate; must-fix before merge)
RW1's rewrite of `test_egress.py` (dropping the nftables/firewall_rule tests) left **one extra blank line** after the import block. `ruff check .` (0.15.12, the pinned gate) exits non-zero (1 error, `[*]` auto-fixable). mypy + every rework-touched pytest suite are green; this is the sole red gate. Mechanical, test-file-only, **not** a correctness defect — but a red gate blocks merge by the project bar (CLAUDE.md "Tests + gates still mandatory"). **Recommend: junior micro-fix (RW9: `ruff --fix tests/sandbox/test_egress.py` + recommit) → gates green → merge.** A pre-commit ruff hook would have caught it; worth a glance at why it didn't.

### 🟡 N2 — CONNECT-only proxy: sandboxed plain-`http://` web_fetch fails (https unaffected; fails-closed)
The proxy handles only `CONNECT` (`egress_proxy.py:140-141` → non-CONNECT → 405). In-container `urllib` with `HTTPS_PROXY` uses CONNECT for `https://` ✓, but with `HTTP_PROXY` it sends an **absolute-form GET** for `http://` (no CONNECT) → proxy 405 → the plain-http fetch fails. Security-safe (fails closed, no exfil; https is the dominant path), but the `egress_proxy.py` docstring's "http(s): … → CONNECT" slightly over-claims plain-http. Follow-up / inscription nit, **not** blocking — flagging because P4.3's whole thesis is honest-residual inscription. (git_push ssh is fine: `nc -X connect` is genuine CONNECT.)

## Cross-lens map (round 2 — for synthesis)
| Finding | R0-A r2 (this) | R0-B r2 (`1abd9d4`) | Relationship |
|---|---|---|---|
| Y1 egress pin / proxy installed+enforcing | ✅ RESOLVED | ✅ R0B-2/3 RESOLVED | converge |
| Y2 plugin resolver injected (R1) | ✅ RESOLVED | (✅ via RW5) | converge |
| Y3 config fail-CLOSED | ✅ RESOLVED | ✅ R0B-4 RESOLVED | converge |
| Y4 seccomp ALLOW-default | ✅ RESOLVED | ✅ R0B-1 RESOLVED | converge |
| Y5 latency gate | ✅ RESOLVED | ✅ R0B-5 RESOLVED | converge |
| Proxy bridge not `--internal` / binds 0.0.0.0 | 🟡 honest residual (Y1 tail) | 🟡 NEW (non-blocking) | converge |
| ruff gate-red | 🟡 N1 (must-fix) | — | R0-A-only (gate) |
| CONNECT-only / plain-http | 🟡 N2 (inscription) | — | R0-A-only |
| plugin latency | — | 🟡 NEW (non-blocking) | R0-B-only |

**Both lenses converge: all 4🔴 CLEARED, all round-1 🟡 resolved, no new blocker.** The rework genuinely delivered the enforcing, wired surface ADR-037 claims. Recommended path: **junior RW9 (ruff one-liner) → gates fully green → architect Accept → merge.** Whether N2 (plain-http) warrants a follow-up slice or a one-line inscription correction is a minor call for the architect; it does not gate this merge.

---

# Round 3 re-verification — RW9 (verdict bump) (architect-partner lens)

| Field | Value |
|---|---|
| Round | R0-A **round 3** (verdict-bump re-verify; the two round-2 gating 🟡) |
| Reviewer | architect-partner (Claude Opus 4.8, 1M context), primary session |
| Reviewed at | `d3180f1` (RW9 HEAD) on `claude/P4.3-impl`. RW9 touches `api/app.py`, `tests/sandbox/test_constitution.py`, `tests/sandbox/test_egress.py` only. |
| Gates | ruff `src tests` (canonical) **clean** + `ruff check .` **clean**; mypy --strict **clean** (262 files); pytest `tests/sandbox`+`integration`+`tools`+`plugins` **exit 0** (~451 dots, zero FAILED/ERROR); constitution **15 passed**. No live Docker daemon (stubbed). |

**Round-3 verdict: clean.** RW9 resolves both round-2 gating 🟡 and introduces no regression. The `api/app.py +59` change is a **pure extract-method** — not a fail-open reintroduction.

### ✅ RA1 (round-2 N1 — ruff I001 gate-red) → RESOLVED
`tests/sandbox/test_egress.py:18` lost the one extra blank line after the import block (RW9 diff: single `-` blank line). `ruff check src tests` → *All checks passed!* (exit 0); `ruff check .` likewise. The sole non-green gate from round 2 is now green.

### ✅ RA2 (the wired-whole test drives the real composition root; app.py sound, no fail-open) → RESOLVED
- **Refactor is sound, fail-closed on both paths.** `_resolve_sandbox_posture(config_dir) -> PostureResolver` (`app.py:172-198`) — return type is **non-Optional**, so mypy --strict *structurally forbids* a `None`/fail-open return (clean gate proves every branch yields a real resolver). Branches: present+valid → `from_config(cfg)`; `SandboxConfigError` → `logging.warning(...)` + `fail_closed()`; absent → `fail_closed()`. Byte-for-logic identical to the RW4 inline block round 2 verified — this is a **strengthening** (contract now enforced at the function boundary), **not a RW4 regression**.
- **Resolver reaches every sandbox surface, none gets `None`.** `_build_context` calls the helper once (`app.py:245`) and threads the result into all three registries: `load_plugins(..., posture_resolver=...)` (`:265`, Y2 surface), `build_subprocess_tool_registry(..., posture_resolver=...)` (`:283`, Y3 subprocess), `build_network_tool_registry(..., posture_resolver=...)` (`:299`, Y3 web_fetch). No fail-open path exists.
- **Tests now bind to the real branch.** The three RW8-2 constitution tests (`test_rw8_config_absence_real_path_fail_closed`, `…parse_failure…`, `…web_fetch…`) drop their inline `if exists / try / except` copy and `from orchestrator.api.app import _resolve_sandbox_posture` → call it directly (absence: empty tmp_path; parse-fail: invalid `sandbox.yaml`). A fail-open revert in `app.py` (e.g. `except → None` or `else → None`) flips the resolver to `None` → registry takes the app-level unsandboxed branch → the tool no longer raises `sandbox_unavailable` → these tests fail. The round-2 "test replicates the composition-root branch inline rather than importing it" note is **closed**.

### ✅ s3 (executor byte-frozen, 6th exercise) → holds
`git diff origin/main -- src/orchestrator/tools/executor.py` empty; the constitution s3 AST test passes. RW9 touches no executor / spawn surface (empty-executor-diff invariant intact).

### Residual (non-gating)
Round-2 **N2** (CONNECT-only proxy → sandboxed plain-`http://` web_fetch 405s; fails-closed, https unaffected) was an **inscription/follow-up nit**, not a must-fix, and RW9 did not (and was not asked to) touch it. It remains a non-blocking follow-up and **does not gate clean**.

**Both round-2 gating 🟡 cleared; no regression; no fail-open. R0-A → clean.** Dual-lens note: this verdict bump concerns the R0-A-only gate/test items; the shared 4🔴 cluster was already cleared and re-verified at round 2 (converging with R0-B `1abd9d4`).
