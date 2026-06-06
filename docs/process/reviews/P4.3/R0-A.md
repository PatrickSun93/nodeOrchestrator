---
task_id: P4.3
round: R0-A
verdict: blocking
findings_count:
  red: 4
  yellow: 1
  green: 11
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
