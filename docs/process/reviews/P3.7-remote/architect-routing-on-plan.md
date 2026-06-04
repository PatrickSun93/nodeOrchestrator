---
task_id: P3.7-remote
stage: architect-routing-on-plan
adr_under_review:
  - ADR-031
  - ADR-032
plan_under_review: docs/process/senior-plans/P3.7-remote.md
routed_by: architect (Peidong)
routed_via: orchestrator
date: 2026-06-04
reviews_routed:
  - docs/process/reviews/P3.7-remote/R0-B-cross-family.md   # blocking: 2🔴 / 7🟡 / 4🟢 (DeepSeek)
  - docs/process/reviews/P3.7-remote/R0-A-on-plan.md        # needs_architect: 0🔴 / 4🟡 / 1🟢 (architect-partner)
disposition: all-α (no β/γ/δ — every finding absorbed; two 🔴 are claim-narrowings, not redesigns)
---

# Architect routing — P3.7-remote plan-stage (ADR-031 + ADR-032 + senior plan)

Architect (Peidong) routed the two plan-stage reviews on 2026-06-04 via the orchestrator. **All findings → α (senior absorb).** No β/γ/δ. The two 🔴 are **honesty/claim-narrowings** the mechanisms already supported (Posture B's real boundary is env/secret/DoS, not a syscall sandbox; the fetched-in-process path is test-enforced-unreachable, not type-level) — **documentation/contract fixes, not redesigns**. The 11 🟡 are contract/impl-contract tightenings on the project's largest trust surface, each absorbed into the ADRs + plan before junior dispatch.

This split cycle: **the architect owns the state machine** (no auto-advance); after absorption + verdict-bump the architect walks the ADR Accept.

## 🔴 R0-B R1 → α — narrow the L1/"real isolation boundary" claim (Posture B = env/secret/DoS only; FS/network = Accepted residual)

The cross-family lens traced the subprocess boundary and asked "what CAN the child still do?" — answer: read any file the host user can, open any socket. The env scoping IS real; FS/network isolation is **absent**. **Architect routes α (honest inscribe):** narrow ADR-031's "L1 RESOLVED" / "real isolation boundary" to **env/secret/DoS-scoped only**, and inscribe the **FS/network residual `RB-FS/NET`** exactly as Posture A's L1/L1b/L2 were inscribed in ADR-029 D4 — the operator who activates a fetched plugin assumes it. **Real FS/network sandboxing (container/seccomp/UID/chroot) is explicitly DEFERRED to P4.** Senior absorbed:
- **ADR-031 new §D1a** — the residual trust surface inscribed (env/secret/DoS bounds; NOT a syscall sandbox; `RB-FS/NET` Accepted; the operator assumes it).
- **HR#5 + D1 + Consequences** — "L1 resolved" → "L1-env resolved; L1-FS/network = `RB-FS/NET` residual"; "real isolation boundary" → "env/secret/DoS boundary, NOT a sandbox."
- **Reversibility + Considered-alternatives** — the P4 syscall-sandbox forward-watch named.
- (This subsumes **R0-A Y2**, the same residual from the in-family lens — convergent → strong α.)

## 🔴 R0-B R2 → α — "structurally unreachable" → "test-enforced unreachable" + segregated loader interface

The in-process `importlib` path still physically exists (it serves operator-placed plugins); the fetched→Posture-B guarantee is **one runtime guard**, not a type-level impossibility. **Architect routes α:** narrow the wording to **"test-enforced unreachable"** (runtime provenance guard + discriminating test = the enforcement), **and** adopt the separated/segregated loader interface (which R0-A Y3 + R0-B Y3 also want). Senior absorbed:
- **ADR-031 D3** — "structurally unreachable" → "test-enforced unreachable"; provenance is **host-set by ORIGIN** via a **segregated `fetched_plugins_dir` NOT under the `plugins/` presence root**, making provenance **un-launderable** (a fetched bundle can never be discovered as operator-placed = the exact crux breach prevented).
- **plan -6** — `load_plugins` gains `fetched_plugins_dir`; provenance-by-origin; the laundering test + the test-enforced-unreachable test.

## 🟡 ×11 → all α (tightened into ADR-031/032 + plan)

| Finding | Lens | Absorption |
|---|---|---|
| **R0-A Y1** — pinned SDK symbol `streamablehttp_client` is `@deprecated`; credential/TLS shape doesn't match the non-deprecated client | TLS/contract | ADR-032 Context+D2+HR#5/#6+alts+refs: pin **non-deprecated `streamable_http_client`** + a **host-built `httpx.AsyncClient(verify=True, headers=…, timeout=…)`**; plan -2 rewritten. |
| **R0-A Y2** — Posture B is not a syscall sandbox (host over-privilege) | host-over-privilege | = R0-B R1 (D1a `RB-FS/NET`). |
| **R0-A Y3** — fetch staging vs presence-discovery root (provenance laundering) | provenance-spoof | = R0-B R2/Y3 (segregated `fetched_plugins_dir`, ADR-031 D3). |
| **R0-A Y4** — fetched child env must be operator-authoritative, never fetched-manifest-authoritative | env-leak/c2 | ADR-031 D4/HR#5: fetched manifest **cannot self-request** env/`api_key_env`; env via the operator-authored activation entry only; env-leak probe covers the manifest-requests-a-secret attack. |
| **R0-B Y1** — kill-no-orphan rests on SDK internals, no orchestrator watchdog | subprocess-escape | ADR-031 D2 + plan -4: a **LAYER-1 orchestrator kill watchdog** (post-teardown PID check → force SIGKILL). *(partner leaned β; architect overrode → α.)* |
| **R0-B Y2** — harness env construction underspecified | env-leak | = R0-A Y4 (operator-authoritative env; `plugin_subprocess_env`; forbid `api_key_env` for plugins). |
| **R0-B Y3** — fetched-loader interface unspecified | provenance | = R0-B R2 (segregated `fetched_plugins_dir`, host-set-by-origin). |
| **R0-B Y4** — no constitution test for "never `verify=False`" | TLS-bypass | ADR-032 D5 + plan -9: a **`verify=False` AST/grep scan** asserting zero occurrences. |
| **R0-B Y5** — bundle integrity-check ordering (digest-before-extract) | fail-closed | ADR-031 D5 + plan -7: single `.zip`/`.tar.gz`; **digest on compressed bytes BEFORE extraction**; path-traversal guards. |
| **R0-B Y6** — no per-turn cap for Posture-B plugin tools | DoS | ADR-031 D1 + plan -5/-9: **`MAX_POSTURE_B_CALLS_PER_TURN`** (the MCP `=10` analog), subprocess closures only; cap test. *(partner leaned β; architect overrode → α.)* |
| **R0-B Y7** — half-stage fetch cleanup undesigned | fail-closed | ADR-031 D5 + plan -7: **atomic staging** (temp file/dir → verify → rename; on failure delete/rmtree); `fetched_plugins_dir` never touched by a failed fetch. |

**R0-A G1 (advisory, senior-resolved):** the extracted seam is split by scope — `mcp/_async_bridge` (transport-agnostic sync/timeout/fail-closed, reused by stdio + remote) vs `mcp/subprocess_trust.py` (subprocess-only scoped-env/kill) — so the remote (non-subprocess) path does not import a "subprocess_trust" helper. Absorbed in ADR-031 D2 + plan -4.

## Convergence note (RC-20)

R0-A Y2/Y3/Y4 and R0-B R1/Y3/Y2 **converged from different families** on the same three vectors (host over-privilege, provenance laundering, fetched-env authority) — the strongest α signal at routing. No in-family false-positives (R0-B RC-20: all net-new; the cross-family lens added the FS/network-isolation + integration-completeness dimensions the in-family pass under-probes).

## Verdict bumps (RC-10)

Both plan-stage reviews bumped → `clean` (with `verdict_history` recording the prior verdict + the absorption summary):
- `R0-B-cross-family.md`: `blocking` → `clean`.
- `R0-A-on-plan.md`: `needs_architect` → `clean`.

ADR-031 + ADR-032 remain **Proposed** (RC-23-safe — no `Accepted` on their Status headers).

## State / next

`.workflow/P3.7-remote.yaml` stays architect-managed (this split cycle). Plan branch `claude/P3.7-remote-plan` carries the absorption + the bumped verdicts + this routing record. **Next: architect walks the ADR-031 + ADR-032 Accept**, then junior dispatch (the serial chain P3.7-remote-1..9).
