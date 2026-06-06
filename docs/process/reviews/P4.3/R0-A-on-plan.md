---
task_id: P4.3
round: R0-A-on-plan
lens: in-family (Claude; cross-family R0-B-on-plan runs in parallel in r0b)
reviewer: architect-partner
dispatch: manual (no state change; plan-stage) — round 2 = absorption re-verify (architect-routed; senior absorbed in commit 3263726)
reviews_acked:
  - architect-briefs/P4.3.md
  - senior-plans/P4.3.md
  - decisions/ADR-037-syscall-egress-sandbox.md
  - reviews/P4.3/external-r0b-prompt.md
  - reviews/P4.3/R0-B-on-plan.md (cross-family blocker — absorption verified against it)
verdict: clean (round 2; was needs_architect round 1 — all routed items absorbed)
verdict_history:
  - round: 1
    verdict: needs_architect
    findings: { red: 0, yellow: 2, green: 3 }
    summary: spine + 5 DPs faithful; routed F2/R5 + F1 + 4 of 5 senior push-backs.
  - round: 2
    verdict: clean
    summary: absorption (commit 3263726) re-verified — every routed item (🔴 R1 + Y1/Y2/Y3/Y5 + R5 + §5.2/§5.3 + F1/F3/F4/F5) resolved; ADR-037 stays Proposed (RC-23); 2 non-blocking impl-stage R0-B watch-items.
findings_count: { red: 0, yellow: 2, green: 3 }  # round 1 counts; round 2 opens no new finding
verify_cite_base: round 1 = origin/main; round 2 = claude/P4.3-plan @ 3263726 (absorption is docs-only — ADR-037 + senior-plan, +150/-120, no src/ change → round-1 substrate ledger holds verbatim, spine not re-derived per dispatch)
---

# Round 2 — absorption re-verification (2026-06-05) — verdict `clean`

**Dispatch:** architect manual re-run. The round-1 plan-stage dual-lens — this R0-A-on-plan (`0🔴/2🟡`) ∥ the cross-family `R0-B-on-plan.md` (`1🔴/5🟡` **blocking**) — was architect-routed; the senior **absorbed** the routing into the plan + ADR-037 in **commit `3263726`** (`claude/P4.3-plan`). This round **re-verifies the absorption item-by-item against the committed artifacts**; it does **not** re-derive the round-1-cleared spine (5 DPs, empty-executor-diff, fail-closed posture — confirmed faithful in round 1 below, untouched by the absorption).

**Base:** `git fetch`; branch tip `3263726`. The absorption diff is **docs-only** (`ADR-037` + `senior-plans/P4.3.md`, +150/−120, **no `src/` change**) → the round-1 substrate verify-cite ledger (§5 below) **holds verbatim**. The two new atomics P4.3-3 (egress) / P4.3-11 (R5) describe not-yet-written code (nothing to cite-check at plan stage).

## Routed-item resolution ledger (every routed item → resolved? → verified locus)

| Routed item (round-1 id) | ✓ | Verified locus |
|---|---|---|
| **🔴 R1 — egress MECHANISM**, ratified (a) parent-pinned-IP per-call egress | ✅ | New atomic **P4.3-3** (plan:55–60) + **ADR-037 D2 Network** (:53) + **D3** (:61). Pins all four R0-B sub-asks: **(a)** egress → exactly the `_resolve_and_validate` pinned IP:port via per-call ephemeral net + daemon-side nftables/iptables rule; **(b) single-family pin** (other family blocked — no dual-stack escape); **(c) container DNS disabled** (`--dns 0.0.0.0`; the IP:port pin itself also blocks reaching any `:53`); **(d) cross-platform-honest** — native-Linux host firewall / Docker-Desktop web_fetch via host-side pinned proxy / non-viable combo (git_push-ssh-on-DD) → **deny-default fail-closed** (loud). Acceptance is buildable (pinned-IP rule shape; DNS-disabled; v6-blocked-when-v4-pinned; DD-ssh→fail-closed). **Retires R4/R8 on the sandboxed surface, bounded by allowlist breadth** (honestly inscribed ADR-037 D5 R8-if-broad-allowlist:77). |
| **R5 — DNS head-of-line** (R0-B Y4 / R0-A F2), ratified (a) FOLD IN | ✅ | New atomic **P4.3-11** (plan:111–116): *"This RESOLVES R5 (not a deferral) — R5 leaves the deferred-residual set entirely."* Honors ADR-035 impl-degradation ¶ ("folds into P4.3") → **no deferral re-annotation**. **Confirmed out of every deferred list:** ADR-037 D5 (:72–82) names only **R8/R9** as R-residuals — R5 absent; line 3 + :115 frame R5 *resolved*; P4.3-13 (:126) marks it resolved alongside R6. |
| **§5.2 — operator image + fail-closed** | ✅ | ADR-037 D5 (:82) + P4.3-5 config `image` (:70) + §5 (:186): operator-provided image; incomplete toolchain → fail-closed (loud), no silent gap. |
| **§5.3 — R7 cross-platform** | ✅ | ADR-037 D5 (:82) + P4.3-9 (:98) + §5 (:188): openat2 (Linux 5.6+) / dir-fd `O_NOFOLLOW` walk (macOS) / final-component residual (Windows, accepted posture). |
| **Y1 — seccomp PINNED + enumerated** | ✅ | ADR-037 D2 Syscall (:54) + P4.3-2 (:49): strategy **pinned = runtime-default blocklist AUGMENTED** (full default-deny allowlist rejected as brittle for first-party pytest/ruff/git → deferred tail D5:79). 11 enumerated denials (`unshare`, `clone[CLONE_NEW{USER,NET,NS}]`, `bpf`, `io_uring_setup`, `add_key`, `request_key`, `keyctl`, `ptrace`, `mount`, raw `socket`/`AF_PACKET`) — **identical across D2 / P4.3-2 / §5(:176)**; shipped as a concrete `seccomp.json` asset. |
| **Y2 — docker.sock + /proc + /sys** | ✅ | ADR-037 D2 FS (:52) + P4.3-2 (:49): **`/var/run/docker.sock` NEVER mounted = new constitutional invariant**, test-enforced **P4.3-12 s6** (:119); `/sys` ro; private PID-ns + sensitive-`/proc` masking. Elevated to §1 invariants (:28) + forcing functions (:162). |
| **Y3 — latency + probe race** | ✅ | ADR-037 D3 (:63) + P4.3-4 (:63): **≤3s-p95 setup target = plan-vs-impl gate**; probe once-at-bootstrap + **cached per turn (~30s TTL)** with own **~2s timeout** (P4.3-1:42, P4.3-5:70); **daemon-dies-at-spawn → `SandboxUnavailableError`** on the posture path; teardown **shielded** (no leaked container on cancel). |
| **Y5 — config-parse + repeated-probe** | ✅ | ADR-037 D4 (:69) + P4.3-5 (:70): **config-parse failure → fail-closed**; `available()` cached per turn so a wedged daemon fails fast. Mechanized by **P4.3-12 s2** (:119). |
| **F1 — stale task-refs** | ✅ | Resolved by **renumber to 14 atomics (P4.3-0…13)** — the two new atomics restore constitution=**12** / annotations=**13**. Verified: **every `P4.3-NN` ref in the plan ∈ [0,13]**, the §2 canonical header list is exactly 0–13 (no gap), the three ADR refs (P4.3-4/12/13) all resolve. The round-1 dangling `P4.3-12/13` refs are now *valid* targets. |
| **F3 / F4 / F5** (round-1 greens) | ✅ | **F3:** D3-ii added to frontmatter `annotates` (:6) + ADR list "D3-i,**ii**,iii" (:3). **F4:** net_trust shared-module sequencing restated for the new numbering — **P4.3-8/10/11** disjoint functions, **P4.3-9** genuinely independent (§3:155). **F5:** cites tightened (`:344`; `_dispatch:114`/`_make_git_push:251`; `_make_web_fetch:124`) (§1:22–26). |

## RC-23 + atomic-graph coherence

- **RC-23-safe ✅** — ADR-037 has **exactly one** `**Status:**` header (line 3) = `Proposed`; the W-006-2-fixed parser (`_parse_adr_status`) reads only that line; the body "Accepted" mentions are prose ("matching the eventual Accepted status"). The Accept is yours, post impl-stage dual-lens.
- **Atomic graph coherent ✅** — §3 spine P4.3-0→1→2→**3**→4→5, parallel {6,7,8}, app-level {9,10,11}, then 12→13: all 14 tasks present, the new egress atomic correctly inserted **before** spawn (P4.3-3 feeds P4.3-4 which consumes it), the new R5 atomic in the app-level `net_trust` cluster. No orphan, no cycle.

## Still-off / watch-items (NON-blocking — for the impl-stage R0-B, not plan gaps; I surface, you route if you disagree)

Both are inherent to **reversing in-process egress into a container** (P4.3-8) and sit **below** the plan-stage bar the R0-B 🔴 set (which asked only for the four mechanism sub-asks — all now answered). Flagging so the **impl-stage** cross-family lens (`requires_cross_family_review: true`) carries them:

1. **In-process httpx → container netns routing (native Linux).** P4.3-3/8 pin *what* the constraint is (pinned-IP:port rule, DNS off); *how* an in-process `httpx` socket is placed behind that per-call netns on native Linux (relay/proxy container vs netns-join) is scoped out (P4.3-8 out-of-scope: "the proxy implementation detail beyond the allowlist contract"). The HTTPS forward-proxy path must enforce the pin **without re-resolving** the `CONNECT` host (else DNS re-enters) — the parent already pins the IP, so the proxy should allow only the pinned IP:port. Impl-stage R0-B escape lens.
2. **`--dns 0.0.0.0` vs the embedded resolver on user-defined networks.** A per-call *user-defined* Docker network ships Docker's embedded DNS at `127.0.0.11`; confirm at impl that `--dns 0.0.0.0` actually suppresses it (belt — the IP:port pin already blocks reaching any `:53` resolver). Impl-stage R0-B.

## Verdict — `clean` (round 2)

The absorption is **faithful and complete**: every architect-routed item (🔴 R1 + Y1/Y2/Y3/Y5 + R5 + §5.2/§5.3 + F1/F3/F4/F5) is banked into the atomics + ADR-037 with a verified locus; no routed item was softened, dropped, or silently re-interpreted; the plan opens **no new finding**. The plan is **junior-dispatchable**. The only remaining gate is **yours**: Accept ADR-037 (stays `Proposed`, RC-23) — then junior dispatch / the mandatory impl-stage dual-lens. The two impl-stage watch-items above are handed to the cross-family lens.

---

*(Round-1 review verbatim below — the audit record; not re-derived this round.)*

# R0-A-on-plan — P4.3 container syscall/egress sandbox (the RB-FS/NET retirement)

## 0. Verdict — `needs_architect` (0🔴 / 2🟡 / 3🟢)

**The plan + ADR-037 FAITHFULLY implement all 5 ratified decision-surface points (DP1–DP5). No re-litigation; no design-breaking flaw.** The seam topology, the empty-executor-diff (5th), the fail-closed posture, and the honest-residual inscription all verify against the working tree. `needs_architect` is driven by **one consequential scope item (F2 — R5, an Accepted-ADR-vs-dispatch gap)** + **4 of the 5 senior push-backs needing routing (§5.1–§5.4)** + **doc-integrity cleanups (F1 task-number drift)**. None is blocking — the plan is sound; these are routing surfaces and pre-junior cleanups. **I surface; you route.**

## 1. DP-faithfulness (the primary R0-A-on-plan job — verify, not re-litigate)

| DP | Ratified call | Plan/ADR locus | Faithful? |
|---|---|---|---|
| **DP1** | OS containers, runtime-abstracted, cross-platform | ADR-037 D1; plan P4.3-1 | ✅ podman→docker detect, **liveness** probe (`info`), `available()==False` on daemon-down (no raise); Docker-Desktop-via-WSL handled. |
| **DP2** | FS ro-rootfs+workspace-mount; net deny-default+allowlist; seccomp; nonroot/userns; resource-limits; R3 via subtree-kill; R6 app-level; R9 DLP residual | ADR-037 D2; plan P4.3-2/5/9 | ✅ R3 retired by container kill (`<runtime> kill`+`rm -f`) regardless of `setpgid`; R6 folded (P4.3-9); R9 honestly **not** retired (D5). |
| **DP3** | one spawn seam (`run_scoped_command`+Posture-B); web_fetch egress→per-call container (reverses ADR-035); apply_edit R7 = app-level `openat2`; per-call; empty-executor-diff 5th | ADR-037 D3; plan P4.3-3/5/6/7/8 | ✅ all 5 D3 sub-points present; apply_edit explicitly **not** containerized (D3 ¶3); seam verified below the executor (§5 ledger). |
| **DP4** | default-on + **FAIL-CLOSED** default + loud operator opt-in; NO silent fail-open | ADR-037 D4; plan P4.3-4 + P4.3-10 s1/s2 | ✅ `SandboxUnavailableError`→`TOOL_FAILED`; degraded path requires explicit `degraded_app_level` flag + `WARNING` every call; **test-enforced** (s1 no-exec-without-sandbox-unless-opt-in). |
| **DP5** | ADR-037 + residual-retirement annotations | ADR-037 D5; plan P4.3-0/11 | ✅ faithful; doc-integrity nits F1/F3 below. |

**Headline: the plan does not soften, re-route, or re-open any ratified DP.** The override of the brief (DP1 containers over the brief's bwrap/nsjail lean) is correctly inscribed and the brief's jailer lean correctly demoted to a Considered-alternative (ADR-037 line 87) + a Reversibility forward-watch (a bwrap backend behind the same `sandboxed_run` seam, line 106).

## 2. Probe results (dispatch (i)–(vi))

- **(i) Retirement honesty** — R1/R2/R3/R8 (subprocess) + R4 (web_fetch egress) retired on the sandboxed surface ✅. **No over-claim:** R6 = app-level floor extension (P4.3-9, not "container-retired"); R7 = app-level `openat2`, **Linux-only**, non-Linux degraded + inscribed (§5.3 / D5); R9 = **bounded transport, NOT retired** (D5 — "P4.3 bounds the transport; it does not claim to retire R9"). The honest-residual discipline holds.
- **(ii) Empty-executor-diff (5th)** — ✅ the wrap lives **below** `_execute_local_call` (`tools/executor.py:385`): the two spawn primitives (`run_scoped_command` `subprocess_trust.py:202`, `subprocess_mcp_stdio` `:344`) and the egress builder (`build_ssrf_client` `net_trust.py:178`) are all in `subprocess_trust`/`net_trust`; no task's "Where" touches `executor.py`. Guard exists: `t3b` (`tests/tools/test_constitution.py:190`) + `pb6` (`tests/plugins/test_posture_b.py:411`), extended by P4.3-10 s3. *(Honesty note, not a finding: "byte-frozen" is mechanized as **decision-symbol-absence** (t3b/pb6/s3) + the structural fact that the wrap is below the executor — the established 4× precedent (ADR-031/034/035/036), not a P4.3 weakening; literal byte-identity is verifiable by `git diff executor.py` at impl.)*
- **(iii) Fail-closed + loud opt-in** — ✅ inscribed honestly (D4: "Never a silent fallback"); test-enforced (P4.3-10 s1/s2). No path reaches a raw host spawn when unavailable-and-not-opted-in.
- **(iv) Runtime-detection / daemon-down** — ✅ P4.3-1 acceptance: liveness (not CLI-presence), no exception escapes, daemon-down→`available()==False`. Cross-platform (Docker-Desktop-via-WSL shim + native) named.
- **(v) Per-call term as the new finite ADR-028 D5 / ADR-033 D4 `(1+N)` term** — ✅ **bounded on the happy path** (P4.3-3 reuses `run_scoped_command`'s timeout machinery, which wraps the whole `docker run` invocation incl. container startup → setup is inside the deadline, not outside it). P4.3-3 measures+logs the term. **Residual liveness risk correctly tasked to R0-B Lens A:** the *teardown-on-hung-daemon* path (`<runtime> kill`/`rm -f` itself hanging) is the one place the term could leak a container or block at teardown — the external prompt Lens A point 1 explicitly probes "is the teardown shielded so a timeout-cancel still reaps the container." Confirm R0-B carries this (it does). Watch-item, not a finding.
- **(vi) ADR-037 narrows/annotates correctly + RC-23 (Proposed)** — D-ref mapping **all verified correct** (R1→031 D1a, R2→034 D2, R3→034 D4, R4→035 D2/D3-ii, R7→036 D3-i, R8→036 D3-iii, R9→036 D3-ii, R5/R6→035 impl-degradation ¶). **RC-23-safe confirmed clean:** ADR-037 has exactly one `**Status:** Proposed` header (line 3); the accept-gate parser (`_parse_adr_status`, fixed W-006-2 e050cdc — reads only the `**Status:**` line) will read `Proposed`; the 2 body "Accepted" mentions are prose, not status lines. ("RC-23-safe" is the established idiom — P2.7/P3.4/P3.1/P2.2 reviews all use it the same way.)

## 3. Findings (severity + cite; **architect routes**)

**🟡 F2 — R5 (DNS head-of-line) is an Accepted-ADR commitment to P4.3, not just a brief entry.** The senior surfaces R5 in §5.4 as a "brief-vs-dispatch gap" and correctly does **not** bank it (surface-don't-improvise — right call). But the gap is **sharper than stated:** **ADR-035's impl-degradation ¶ (Accepted 2026-06-05) explicitly says the R5 isolation hardening "folds into the P4.3 egress-sandbox pass on the same retirement path"** (`docs/decisions/ADR-035-*.md:63`, verified). P4.3-7 re-homes the web_fetch egress to a container but **keeps the SSRF resolve-then-pin in the parent** (the plan's own design, P4.3-7) — which is exactly the `_DNS_EXECUTOR = ThreadPoolExecutor(max_workers=1)` (`net_trust.py:37`) that owns R5. So **R5 persists in the parent unless explicitly fixed, and the plan banks no fix.** Consequence the architect should weigh: **leaving R5 deferred is not free** — ADR-035's "folds into P4.3" inscription goes stale, so P4.3-11 must **re-annotate ADR-035** to re-home R5 to a later slice, else the residual is silently dropped (the honest-residual discipline forbids exactly that). *Routing surface:* (a) fold R5 in (small `net_trust` executor change, rides P4.3-7/9, honors ADR-035's inscription); or (b) leave deferred **and** add the R5 re-annotation to P4.3-11. *I do not route.*

**🟡 F1 — Task-number drift (stale cross-references → junior-confusion).** Plan §2 defines tasks **P4.3-0..11**, but three cross-refs point at non-existent numbers, consistently +2 on the last two tasks:
- Plan §1 line 25: "guarded by **P4.3-12**" → constitution tests are **P4.3-10**.
- Plan §2 P4.3-0 out-of-scope (line 38): "editing predecessor ADRs (**P4.3-13**)" → annotations are **P4.3-11**.
- ADR-037 line 3: "inscribed at impl (plan task **P4.3-13**)" → should be **P4.3-11**.

An earlier draft evidently had 2 more atomics; the §2 list was renumbered without fixing the refs (the §3 execution graph IS internally consistent with §2 — only these 3 prose refs are stale). A junior dispatched against this plan hits dangling task numbers. *Recommend a senior cleanup pass (3 edits) before junior dispatch.* Not product-correctness; navigability.

**🟢 F3 — ADR-037 / plan-frontmatter annotation list omits D3-ii (R9).** ADR-037 line 3 + plan frontmatter line 6 list annotation targets as "ADR-036 **D3-i,iii**" (omitting D3-ii), but plan §2 **P4.3-11 does annotate D3-ii** (R9 "bounded-not-retired", line 111+114). The task body is more complete than the summary lists. *Confirm whether ADR-037 line 3 should add D3-ii (R9-bounded annotation) for completeness, or intentionally lists only retired-residual targets* (defensible — but then the summary lists and P4.3-11's actual scope diverge).

**🟢 F4 — Execution-order independence claim inaccurate for P4.3-9.** Plan §3 line 139 says "P4.3-9 (`net_trust.py::is_denied_ip`) touch no chain files." But **P4.3-7 (a chain task) also edits `net_trust.py`** (egress routing + re-homed validator, line 84) → P4.3-7 and P4.3-9 **share the module** (disjoint functions, so textual conflict is unlikely, but the 5-surface scan / mypy run on the combined file). The no-junior-parallelism serial default makes this moot in practice; flagged for accuracy. *(P4.3-8 / `mutation_tools.py` IS genuinely independent — only P4.3-9 collides.)* Recommend: sequence P4.3-9 after P4.3-7, or restate as "disjoint functions in a shared module."

**🟢 F5 — Minor verify-cite drifts (none load-bearing).** `subprocess_mcp_stdio` cited `:343` (plan §1 line 20; ADR References line 116; ext-prompt line 19) — actual `async def` is **`:344`** (off-by-one). The `_dispatch (:114, :251)` label (plan §1 line 20) bundles git_push's `:251` under `_dispatch`, but `:251` is the `run_scoped_command` call inside `_make_git_push` (def `:227`), not `_dispatch` (def `:98`) — the line **numbers are the correct `run_scoped_command` call sites** (verified: exactly 2 repo-wide), only the label is imprecise. `web_fetch` cited `network_tools.py:134` is the `build_ssrf_client` call inside `_make_web_fetch` (closure def `:124`) — apt for the egress seam, imprecise as a def-cite. Recommend a light cite-tightening at impl; the seam topology is correct.

## 4. Senior push-back assessment (dispatch: "flag which need architect routing")

| § | Push-back | Senior lean | Needs routing? |
|---|---|---|---|
| **5.1** | Egress-allowlist *mechanism* (Docker has no native per-host egress filter) | (a) parent-pinned-IP per-call egress (reuse the SSRF floor's already-computed pinned IP) for web_fetch + git_push | **YES** — genuine cross-platform design choice; lean is sound (clean reuse) but it's a real call vs (b) host-proxy / (c) deny-default-only. |
| **5.2** | Subprocess container **image** (toolchain-completeness for `run_tests`/`run_lint`) | operator-provided `image`; incomplete → fail-closed (loud), no silent toolchain gap | **YES** — operator-burden/usability posture; lean honors no-silent-fail but it's the real operational cost of containers-over-jailer. |
| **5.3** | `openat2` is Linux-only → R7 fully retired only on Linux | openat2 (Linux) + dir-fd `O_NOFOLLOW` walk (macOS) + final-component residual (Windows), inscribed in D5 | **YES (confirm)** — means R7's cross-platform posture is asymmetric; honestly inscribed; confirm the Windows residual is the accepted posture. |
| **5.4** | R5 scope (= **F2**) | leave OUT, pending your call | **YES** — see F2; the Accepted-ADR-035 inscription raises the stakes (re-annotation needed if deferred). |
| **5.5** | Per-call latency vs D5 budget | NOT a decision — a flag to the R0-B liveness lens | **NO** — correctly a flag to R0-B Lens A + plan-vs-impl measurement, not an architect routing item. |

**4 of 5 push-backs (§5.1, §5.2, §5.3, §5.4) need your routing; §5.5 is a correct flag-to-R0-B, not a decision.**

## 5. Verify-cite ledger (checked vs working tree == origin/main)

✅ `run_scoped_command` `subprocess_trust.py:202`; call sites **exactly 2** repo-wide — `:114` (`_dispatch`), `:251` (`_make_git_push`) → confirms "one subprocess chokepoint". ✅ `subprocess_mcp_stdio` **:344** (cited :343). ✅ kill machinery `_kill_watchdog:245` / `_pgid_kill:276` / `_terminate_subprocess:287`. ✅ `scoped_env:74` / `_SAFE_ENV_KEYS:49`. ✅ `net_trust.py` DNS exec `:37`, `is_denied_ip:40`, `_SSRFValidatingTransport:125`, `build_ssrf_client:178`. ✅ `web_fetch` closure `_make_web_fetch:124` (egress build `:134`). ✅ `mutation_tools.py` `_make_apply_edit:71`, `os.replace:134`, `O_NOFOLLOW:122-123`. ✅ `plugins/code.py` `_PostureBFn:56`, `_async_call:93`, `subprocess_mcp_stdio` use `:105`. ✅ composition root `api/app.py:205-262` (local_tools merges :207/:240/:252/:262). ✅ `_execute_local_call` `tools/executor.py:385` — untouched by all tasks. ✅ ADR D-ref mapping (§2 (vi)). ✅ RC-23-safe (single `**Status:** Proposed` header; parser fixed W-006-2).

**Bottom line:** plan + ADR-037 are faithful to the 5 DPs and structurally sound. Route §5.1–§5.4 (esp. F2/R5, which carries an ADR-035 re-annotation consequence); ask senior to fix F1 (3 stale task-refs) + optionally F3/F4/F5 before junior dispatch. ADR-037 stays **Proposed** — the Accept is yours, after the cross-family R0-B-on-plan lands.
