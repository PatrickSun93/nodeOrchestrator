# External R0-B prompt — P4.3 (container syscall/egress sandbox) — MANDATORY dual-lens

> **Dispatch context.** `requires_cross_family_review: true` (ratified; P4-roadmap §8 — heaviest infra slice to date). You are the **cross-family** reviewer (DeepSeek via the role-rewriting proxy). This is the **plan-stage** prompt; the architect dispatches it at **impl stage** against the impl branch. P4.3 is the **real FS/network/syscall sandbox** that retires the accumulated `RB-FS/NET`-class residuals (R1–R4, R7, R8) that B3/B4/B5 + ADR-031 each Accepted on the named "the sandbox wraps the existing exec" retirement path. It crosses the project's heaviest containment boundary: from app-level scoping (scoped-env, SSRF floor, `_check_path`) to a real OS-container isolation boundary. **New code is security code with its own escape history** — your job is to find where the boundary is weaker than claimed or where the single writer can hang.

---

## Your stance

Take a deliberately **outside-Claude** lens. Over-correct for Claude's biases: trust-the-types-means-trust-the-runtime, over-engineering, agreeableness, "the container flag is set therefore the boundary holds." **Trace failure modes across module + process + namespace boundaries** and ask "what happens when this container fails to start / the daemon dies mid-call / a grandchild `setpgid`-escapes / the bind-mount races / this is replayed at 3am with Docker Desktop off?" Default to **refuted/skeptical** when uncertain; a finding you can't substantiate by tracing the code (or naming a concrete escape technique) is not a finding. Cite `file:line` or `artifact §`.

## Artifact bundle — read from disk (in-repo dispatch)

Read in full:
1. `docs/process/architect-briefs/P4.3.md` — the decision-surface (R1–R9 ledger + 5 DPs + watch-list).
2. `docs/process/senior-plans/P4.3.md` — the plan (atomic graph + the 5 surfaced design calls).
3. `docs/decisions/ADR-037-syscall-egress-sandbox.md` — the proposed ADR (D1–D5).

Plus the live substrate it wraps (probe claims against the working tree):
- `src/orchestrator/mcp/subprocess_trust.py` (`:202` `run_scoped_command`, `:245-268` `_kill_watchdog`/`_pgid_kill`, `:287` `_terminate_subprocess`, `:343` `subprocess_mcp_stdio`).
- `src/orchestrator/tools/net_trust.py` (`:37` DNS executor, `:40-63` SSRF floor `is_denied_ip`, `:125` `_SSRFValidatingTransport`).
- `src/orchestrator/tools/network_tools.py` (`:134` `web_fetch` build_ssrf_client call), `src/orchestrator/tools/subprocess_tools.py` (`:105` `_dispatch`).
- `src/orchestrator/plugins/code.py` (`_PostureBFn._async_call`), `src/orchestrator/tools/mutation_tools.py` (`apply_edit`).
- `src/orchestrator/tools/executor.py` (`_execute_local_call` — the byte-frozen line; verify it stayed unchanged).
- `src/orchestrator/api/app.py` (`:206-262` registry composition root — the only sanctioned config-injection point).
- the new `src/orchestrator/sandbox/` package + `tests/sandbox/`.
- ADR-028 (D5/D6), ADR-033 (D4), ADR-031 D1a, ADR-034 D2/D4, ADR-035 D2/D4, ADR-036 D3 (context for what's retired).

---

## Lens (a) — sandbox setup/teardown LIVENESS under the single writer

The sandbox runs **inline on the `max_workers=1` writer** (ADR-028 D5); per-call container setup/teardown is a **new finite term** in the `(1+N)`-pass turn-loop budget (ADR-033 D4), and `web_fetch` — previously in-process — now pays it too. Probe whether the writer stays **absolutely bounded**:

1. **Per-call setup/teardown bound.** Is the container spawn + `rm -f` teardown bounded by a real deadline that **actually unblocks the writer**, or can a slow/hung `docker run` / `docker kill` block indefinitely? Trace the timeout → does it kill the **container** (not just a host pgid)? Is the teardown shielded so a timeout-cancel still reaps the container (no leaked container per call)?
2. **The `(1+N)` multiplier.** With N=4 re-dispatch passes, each pass can issue multiple sandboxed calls (B3 cap = 10/turn). Does `(1+N) × per-call-container-setup` stay inside the D5 budget, or is the container term now the dominant/unbounded one? Is the setup latency **measured + logged** (the plan claims P4.3-3 does — verify the hook exists and is honest)?
3. **Hung-runtime degradation.** Daemon alive but wedged (a `docker run` that hangs on image pull / a wedged VM). Does `available()` (liveness probe) catch it, or only CLI-presence? Does a hung probe itself block the writer? Trace the `sandbox/runtime.py` probe.
4. **web_fetch egress container per call.** Every `web_fetch` now spins a container (was in-process httpx). Is the SSRF resolve-then-pin still bounded (the `DNS_RESOLVE_TIMEOUT_S` path)? Does the container's own DNS re-introduce an unbounded resolve? Does R5 (the `max_workers=1` getaddrinfo head-of-line) survive the re-homing (the plan flags R5 as an open scope question — confirm whether the design leaves it live)?
5. **Fail-closed path liveness.** When the runtime is unavailable, does the fail-closed path return **promptly** (not after a per-call timeout each time)? Repeated unavailable calls must not each pay a full timeout.

## Lens (b) — ISOLATION-COMPLETENESS vs the CONTAINER-ESCAPE CHECKLIST

Probe whether the boundary is **real where claimed and honest where not**. Test the isolation profile (ADR-037 D2, `sandbox/profile.py`) against the standard container-escape checklist:

1. **User-namespace / rootless.** Is the container non-root (`--user`/userns)? Rootful-Docker-Desktop vs rootless-podman have **different escape surfaces** — does the design's runtime abstraction collapse them unsafely? Can a workload gain host-uid-0 via a rootful daemon? Is `--security-opt no-new-privileges` set?
2. **Seccomp completeness.** The tightened profile drops `ptrace`/`mount`/`keyctl`/raw-`socket`. Is the profile **default-deny or default-allow**? Are the dropped syscalls actually escape-relevant and is anything escape-class **missing** (`unshare`, `clone(CLONE_NEWUSER)`, `bpf`, `io_uring`, `add_key`, `userfaultfd`)? Is `--cap-drop=ALL` set, or only some caps?
3. **Mount / `proc` / `sys` leaks.** Read-only rootfs + workspace bind-mount rw — can the workload reach the host via a leaked `/proc` (`/proc/1/root`, `/proc/sys`), `/sys`, the docker socket (`/var/run/docker.sock` — **never** mount it), or a bind-mount that escapes (symlink in the workspace pointing out, mount-namespace race on setup)? Is the workspace mount the **only** rw mount?
4. **Egress-boundary bypass.** Deny-default is `--network none`; the allowlist (the plan's §5.1 pinned-IP mechanism) is the soft spot. Can the workload reach a non-allowlisted host (DNS to a resolver outside the pin, IPv6 when only IPv4 pinned, a redirect to an internal IP, the NAT64 unwrap R6)? Does the SSRF floor (re-homed as defense-in-depth) still validate **every** hop, or did the reversal drop a redirect re-validation?
5. **The in-process surfaces left un-sandboxed (the honest-residual probe).** ADR-037 D5 claims R9 (`send_email` recipient-exfil) is **NOT retired** (DLP tail) and `apply_edit` R7 is an **app-level `openat2`** fix (not a container). Verify these are inscribed **honestly**, not softened: is R9 actually still open (a netns does not stop exfil to an allowed-domain recipient)? Is the `openat2(RESOLVE_NO_SYMLINKS)` fix real on Linux and **does the non-Linux fallback leave R7 partially open** (the plan §5.3 flags Windows stays at the residual)? Is anything claimed-retired that is actually only bounded?
6. **The DP4 degraded-posture path.** Fail-closed-default + loud operator opt-in to the app-level posture. Is the degraded path **genuinely loud** (a `WARNING` every call, surfaced — not a one-time debug line)? Can the system ever reach a **raw host spawn silently** (runtime flickers available→unavailable mid-turn; a config-parse failure defaulting open; an exception in the posture resolver falling through to the old path)? **This is the no-silent-fail-open invariant** — trace every path to the conclusion "unsandboxed exec only with the explicit flag + a loud log."
7. **Executor byte-frozen (the constitutional spine).** Verify the wrap lives **below** `_execute_local_call` (in `subprocess_trust`/`net_trust`/`sandbox/`) and `_execute_local_call` is byte-unchanged (empty-executor-diff, ADR-028 D6). A sandbox decision leaking into the executor is a 🔴.

---

## NOT IN SCOPE to re-raise (architect-decided / constitutional — probe whether the DESIGN honors them, do not relitigate)

- **DP1 = OS containers (not bwrap/nsjail/raw-ns).** The architect ratified containers for cross-platform deployment (mac/win/linux); the brief's jailer lean was overridden. **Probe the containers' isolation + liveness, not the choice of containers.**
- **Per-call (not warm/persistent) container** — architect-ratified (isolation over latency). Probe whether per-call is bounded, not whether to use it.
- **web_fetch egress → container (reverses ADR-035 D4)** — architect-ratified. Probe whether the reversal is safe + the SSRF floor survives as defense-in-depth, not whether to reverse.
- **apply_edit R7 = app-level `openat2` (not a container)** — architect-ratified. Probe whether the openat2 fix + fallback is complete, not whether to containerize apply_edit.
- **Fail-closed-default + loud opt-in (DP4)** — architect-ratified posture. Probe whether the design *enforces* no-silent-fail-open, not whether fail-closed is the right posture.
- **New ADR-037; `_execute_local_call` byte-frozen; no new `LLMPurpose`; gate-unchanged** — constitutional. Probe whether the DESIGN honors them.
- The gate's decision logic (score/decide_tier/tiers); the confirm-then-execute machinery (ADR-030); R9 being a DLP concern beyond P4.3 (architect-accepted — probe whether it's *inscribed honestly*, not whether to solve it now).

## Output

Land at `docs/process/reviews/P4.3/R0-B.md` with YAML frontmatter:

```
---
task_id: P4.3
round: R0-B-cross-family-external
reviewer_family: <deepseek | gpt-5 | gemini | other>
reviewer_model_id: <specific model>
reviews_acked:
  - architect-briefs/P4.3.md
  - senior-plans/P4.3.md
  - decisions/ADR-037-syscall-egress-sandbox.md
verdict: <clean | needs_architect | blocking>
findings_count: { red: N, yellow: N, green: N }
---
```

Per finding: `file:line` (or `artifact §`), the failure mode **traced** (the concrete escape technique or the hang scenario), severity (🔴 must-fix / 🟡 should / 🟢 nit), and your confidence. **Route nothing yourself** — the architect routes (α absorb / β defer / γ reject / δ later). A **🔴 only** for a concretely-traced sandbox escape / silent fail-open / writer-hang / lost-isolation — not a hypothetical.

**Verdict semantics:**
- `clean` = 0🔴 / 0🟡 / any 🟢 → architect proceeds to Accept ADR-037 + junior dispatch.
- `needs_architect` = ≥1🟡 OR an issue needing routing → architect Decision blocks.
- `blocking` = ≥1🔴 (design-breaking escape / silent fail-open / unbounded writer) → plan + ADR-037 revised before junior dispatch.
