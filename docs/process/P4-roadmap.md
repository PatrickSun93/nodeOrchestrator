# P4 roadmap — deferred-completeness / 完整化 (scope-decision surface for the architect)

**Status:** ✅ **COMPLETE — 2026-06-07** (originally Proposed by architect-partner — 2026-06-04). All 8 ratified slices are closed + merged (P4.1 → P4.7-FE; PRs #53–64; ADR-033..040 Accepted) — see the realized-outcome table in §4. The architect ratified the **phased** ambition (§6) and started at **P4.1** (§7); **F (scale/concurrency hardening)** was ruled **out of P4 scope** (only the P4.5 reader-concurrency fix was pulled in). The body below is preserved as the original scope-decision record. **This is the P4 scope-decision artifact** (mirrors `docs/process/P3-roadmap.md`). It **collects every item explicitly deferred to P4** (grepped across ADRs + retro candidates + handoff), groups them into a dependency-ordered slice breakdown, surfaces scope-ambition options + a recommended start, and classifies each candidate's security weight + ADR need. **The architect ratifies scope, priority, and starting slice — this doc does not decide them.** No slice is briefed until the architect ratifies.

---

## 1. Framing — P4 is a *defined deferral ledger*, not a greenfield epic

P3 is fully closed (P3.1–3.7: scaffold rosters + API + GUI MVP + GUI-completeness/confirm-then-execute + MCP + Plugin + content-depth + remote-infra; ADR-024..032 all Accepted). **P4 = 完整化** — retire the residuals and complete the capabilities that P3 (and earlier phases) **deliberately and explicitly deferred**.

P4 differs from P3 in kind:
- **P3** was a greenfield epic ("完整产品" — four from-scratch directions to discover and slice). The P3-roadmap's job was *discovery + slicing*.
- **P4** is a **closed, named backlog**: every candidate below has a specific ADR source that **Accepted + inscribed** its deferral (the `RB-FS/NET` residual, the `not_implemented` local tools, the deferred turn-loop, the localhost-trust MVP, …). The job here is **prioritisation + ambition**, not discovery — the work is largely known.

**The one framing point the architect should weigh:** P4 **front-loads exactly the trust/security surfaces P3 deliberately deferred** — the syscall sandbox, untrusted-provenance plugin registry, and the auth/multi-user boundary. P3 sequenced *value-first* (usable → extensible → complete) and pushed the heaviest trust work to "later." That "later" is P4. So **P4 is more security-dense than P3, not less** — several candidates are heavy dual-lens + new-ADR (§8). The constitutional spine is **unchanged** (no new principles); P4 *exercises* it harder than any prior phase.

## 2. The P3 foundation P4 completes + the deferral ledger it draws from (verified `origin/main`)

| Built in P1–P3 | Where | What P4 completes on top |
|---|---|---|
| Autonomy gate + 3 tiers (AUTO/COUNTDOWN/HARD) | `autonomy/` | **auto-fire-on-timer** for COUNTDOWN (the 3rd-tier headless path, ADR-030 D4) |
| Runtime tool executor + MCP + **3 read-only local tools** | `tools/executor.py`, `tools/local.py` (`get_current_time`/`read_file`/`list_files` only) | the **16 classified-but-`not_implemented` local tools** (ADR-028 D3) + **agent re-dispatch / turn-loop** (ADR-028 D4) |
| confirm-then-execute (COUNTDOWN/HARD → human-approve → execute) | ADR-030, `api/` confirm endpoint | **unblocks the mutation local tools** — ADR-028 D3 called `propose_edit`/`apply_edit`/`send_email`/`git_push` "provably dead until confirm-then-execute lands"; it landed in P3.6, so they now have an execution path |
| Plugin system — Posture A (operator-placed) + Posture B (fetched, subprocess, **env/secret/DoS-scoped**) | `plugins/`, ADR-029/031 | the **`RB-FS/NET` residual** (real FS/network sandbox), **registry/marketplace**, **lifecycle** (upgrade/version-coexistence/uninstall/enable-disable), **signature trust** (ADR-031 D1a/D4/D5) |
| MCP client — stdio + streamable-http remote | `mcp/`, ADR-027/032 | **OAuth** + **session reuse** (ADR-032 considered-alternatives) |
| API/server — **localhost-trust, single-user** | `api/`, ADR-025 D7 | **auth / multi-user / remote bind / TLS / rate-limiting** (ADR-025 D7 forward hook) |
| GUI — L1 main view + P3.6 rich patterns / confirm UX | `ui/`, ADR-026/030 | the **L2 设置 / L3 高级 / L4 配置** layers (handoff §6.4/§765) — plugin-management, MCP-config, agent/model/autonomy config surfaces |

**Verified gaps that shape P4:** the executor wires only **3 read-only local tools** (`tools/local.py:137-141`) — the other 16 in `config/tools.yaml` fail-closed `not_implemented`; a tool result **never feeds back to the agent in-turn** (no re-dispatch); Posture B is **not a syscall sandbox** (fetched code can `open()` `~/.ssh/id_rsa` + exfiltrate — Accepted `RB-FS/NET`); there is **no auth** (localhost-trust); there is **no plugin registry / lifecycle**.

## 3. ⭐ The collected P4 candidate ledger (the inventory — each with its ADR/retro source)

Grouped by theme. **Src** = the ADR/retro that Accepted + inscribed the deferral. **Sec** = security weight (§8). **ADR** = new vs amend (§8).

### A. Plugin trust completeness — the heaviest cluster (untrusted remote plugins)
| # | Candidate | Src | Sec | ADR |
|---|---|---|---|---|
| **A1** | **Posture-B real FS/network syscall sandbox** (container / seccomp / separate-UID / chroot) — resolves the Accepted `RB-FS/NET` residual | ADR-031 D1a, Reversibility, Considered-alt (L41/106/122); R0-A §(3); routing-on-plan | **Heavy** | **New** |
| **A2** | **Plugin registry / marketplace** | ADR-031 D5 (L89/105); ADR-029 scope + Considered-alt (L34/117) | **Heavy** | **New** |
| **A3** | **Plugin lifecycle** — upgrade / version-coexistence / uninstall / enable-disable | ADR-031 scope (L5/89); ADR-029 scope (L34) | **Heavy** | New / amend ADR-029 |
| **A4** | **Signature / keyring trust model** for fetched plugins (vs operator-pinned source+digest) + remote-fetch beyond minimal pinned-source | ADR-031 D4 Considered-alt + Reversibility (L104/125); brief §Out | **Heavy** | New / amend ADR-031 D4 |
| **A5** | **Collision namespacing** (`<plugin>__<id>`) for multi-plugin coexistence | ADR-029 D6 (L103/114) | Light | Amend ADR-029 |

### B. Runtime tool depth — make agents actually *do* work
| # | Candidate | Src | Sec | ADR |
|---|---|---|---|---|
| **B1** | **Agent re-dispatch / tool-result→agent turn-loop** (single-re-dispatch or bounded-loop with an inscribed loop-bound) | ADR-028 D4 (L67/96/115); ADR-011 touch-point | Lean (liveness) | New / amend ADR-011+028 |
| **B2** | **Read-only code-intel local tools** — `search_text`/`search_code`/`find_references`/`find_definition` (+ `log_event`) | ADR-028 D3 (L63); `tools.yaml`; `local.py` | Low (read-only) | Classification; amend ADR-028 |
| **B3** | **Subprocess local tools** — `run_tests`/`run_lint`/`git_blame`/`git_log`/`git_diff` (the c2 env-leak class) | ADR-028 D3 (L63) | **Heavy** | Classification ADR |
| **B4** | **Network local tools** — `web_search`/`web_fetch` (SSRF / exfil surface) | ADR-028 D3 (L63) | **Heavy** | Classification ADR |
| **B5** | **Mutation local tools** — `propose_edit`/`apply_edit`/`send_email`/`git_push` — **now unblocked by ADR-030** (confirm-then-execute landed) | ADR-028 D3 (L63); ADR-030 (the unblock) | Lean (irreversible) | Classification; amend ADR-028 |

### C. Autonomy gating completeness
| # | Candidate | Src | Sec | ADR |
|---|---|---|---|---|
| **C1** | **COUNTDOWN auto-fire-on-timer** — durable backend scheduler + a *human-out-of-loop* execution posture | ADR-030 D4 (L65/69/95/117) | Lean (headless) | **New** |

### D. Remote / auth hardening — beyond localhost-trust single-user
| # | Candidate | Src | Sec | ADR |
|---|---|---|---|---|
| **D1** | **API auth / multi-user / remote bind / TLS / rate-limiting** (the first identity trust boundary) | ADR-025 D7 (L88/91/120) | **Heavy** | **New** |
| **D2** | **Remote MCP OAuth** (token refresh/flows via `mcp/client/auth`) | ADR-032 Considered-alt (L71) | **Heavy** | Amend ADR-032 (rides D1) |
| **D3** | **User-identity audit provenance** (`user_id`/`DECISION` on confirm) | ADR-030 N1 (L61) | Low (rides D1) | Amend ADR-030 |
| **D4** | **Remote MCP session reuse** (keep streamable-http session warm) | ADR-032 Considered-alt (L74) | Low (perf) | Amend ADR-032 |

### E. GUI advanced/config layers — frontend track (handoff §6.4/§765: L2 设置 / L3 高级 / L4 配置)
| # | Candidate | Src | Sec | ADR |
|---|---|---|---|---|
| **E1** | **L2/L3/L4 settings·advanced·config surfaces** | handoff §6.4/§765; ADR-026 scope | Low (backend-authoritative) | Frontend track + amend ADR-025 (mgmt endpoints) |
| **E2** | **Plugin management UI** (enable/disable/upgrade — surfaces A3) | ADR-029/031 scope ("GUI plugin management — frontend track") | Low | Frontend track |
| **E3** | **MCP-server / agent / model / autonomy-tier / LLM-Layer-4-override config UI** | handoff L3/L4; ADR-002/023/026 | Low | Frontend track |

### F. (Optional / lower-confidence) Scale·concurrency hardening + minor product debt
*Not "completeness" headline features — forward hooks + hardening. Surfaced so the architect can decide if **any** of F belongs in P4 at all.*
| # | Candidate | Src |
|---|---|---|
| **F1** | WAL / connection pooling | ADR-025 D6 (L97/108) |
| **F2** | Separate execution lane off the single writer + atomic-claim replacing the check-then-execute double-exec guard (TOCTOU forward-watch) | ADR-028 D2/D5 (L47/82/97) |
| **F3** | Product-side AST import-guards (vs substring scans) | P2.2-candidates RC-24 (L76/82) |
| **F4** | `entity.py`/`record_preference` atomic read-modify-write | P2.4-candidates (L17/25) |
| **F5** | Memory-intelligence depth hooks (semantic/embeddings matching, un-flag/recompute, cluster-identity, forgetting/降级, entity↔entity relations, multi-source trust-weighting, reject actuator) | ADR-016/017/018/019/020 forward hooks; ADR-022 |

> **F5 caveat (anti-over-claim):** P2.6 / ADR-022 **already shipped the first producers** that fed the dormant cross-room memory rules (tagging producer, external-validation connector, refuted handling). So the cross-room memory intelligence is **not** dormant — F5 is *depth* on a working substrate, mostly "wait for a real consumer," **not** a completeness headline.

## 4. Recommended dependency-ordered slice breakdown (architect-partner lean)

A **lean**; §6's ambition choice reshapes it. Arrows are hard deps.

```
CAPABILITY (lowest new-trust; flagship-scenario value)
  P4.1  turn-loop + read-only code-intel tools   (B1 + B2)      [no sandbox/auth needed]
  P4.2  heavier local tool surfaces              (B3 subprocess ∥ B4 network ∥ B5 mutation)  ← each its own classification review
TRUST HARDENING (the heavy half P3 deferred)
  P4.3  Posture-B real syscall sandbox           (A1)            [foundation for fetched-code safety]
  P4.4  plugin registry + lifecycle + signature  (A2 + A3 + A4 + A5)   ← depends on P4.3
  P4.5  auth / multi-user / remote hardening      (D1 + D2 + D3)  [unblocks networked deployment]
COMPLETENESS / POLISH
  P4.6  autonomy auto-fire-on-timer              (C1)            [small; rides ADR-030 confirm machinery]
  P4.7  GUI advanced/config layers               (E1 + E2 + E3)  ← trails the mgmt endpoints from P4.4/P4.5
  P4.8  (optional) scale/concurrency hardening    (F + D4)        ← only if the architect rules F in-scope
```

**✅ Realized outcome (2026-06-07)** — the lean below was followed (phased ambition, P4.1 start); P4.7 split into a backend (mgmt endpoints) + frontend (GUI) track; P4.8/F ruled out of scope:

| Slice | Shipped | ADR | PR |
|---|---|---|---|
| **P4.1** turn-loop + read-only code-intel (B1 + B2) | ✅ closed | ADR-033 (+ amends ADR-028 D3/D4, ADR-011) | #53 |
| **P4.2-B3** subprocess local tools | ✅ closed | ADR-034 | #54 |
| **P4.2-B4** network local tools | ✅ closed | ADR-035 | #56 |
| **P4.2-B5** mutation local tools | ✅ closed | ADR-036 | #57 |
| **P4.3** container syscall/egress sandbox (A1) | ✅ closed | ADR-037 | #58 |
| **P4.4** plugin registry + lifecycle + admission/signature + namespacing (A2–A5) | ✅ closed | ADR-038 | #59 |
| **P4.5** auth / identity / multi-user (D1 + D2 + D3) | ✅ closed | ADR-039 | #60 |
| **P4.6** COUNTDOWN auto-fire-on-timer (C1) | ✅ closed | ADR-040 | #61 |
| **P4.7-BE** plugin-management endpoints (E-track backend) | ✅ closed | — (realizes ADR-038 D5 + ADR-039 D5/D9; no new ADR) | #62 |
| **P4.7-FE** GUI advanced/config layers (E1 + E2 + E3) | ✅ closed | — (light frontend track; single-lens R0-A) | #63 |

*In-window UI changes outside the ledger slices:* **#55** gui-restyle (design-system application) + **#64** UI format-hygiene (8 prettier'd CSS files + N3 openapi-codegen lock of the plugin/auth contracts). **F (scale/concurrency hardening) + D4** were ruled out of P4 scope (only the P4.5 per-thread WAL reader-pool fix was pulled in).

**Dependency order:** within **A**, the sandbox (A1/P4.3) is the foundation — registry/lifecycle/signature (A2-A4/P4.4) only make sense once fetched code runs safely, so P4.3 → P4.4. **B1 (turn-loop)** is independent of the tool impls but *multiplies* their value; **B2 (read-only)** is the lowest-risk first tool surface and is exactly what the flagship bug-fix/code-review scenarios need (handoff §14). **D1 (auth)** is foundational for D2/D3. **E (GUI)** binds the API contract + needs the new management endpoints from P4.4/P4.5, so it trails them.

*(Each slice runs the full ADR-008 lifecycle: brief → plan → ADR → impl → R0-A/R0-B → plan-vs-impl → merge. The heavy slices (P4.3/P4.4/P4.5 + B3/B4) carry **mandatory dual-lens R0-B** — §8 — like P3.5/P3.7-remote.)*

## 5. Parallelism assessment

| Pair | Parallel-safe? | Why |
|---|---|---|
| **Frontend track (P4.7) ∥ backend** | **✅ the biggest opportunity** (as in P3) | once the P4.4/P4.5 mgmt-endpoint contracts are pinned, the React/TS track is a separate codebase + skillset — runs concurrently with all backend slices |
| **P4.1 (tool depth) ∥ P4.3 (sandbox)** | **✅ mostly** | P4.1 touches `executor.py` re-dispatch + `local.py`; P4.3 reworks `plugins/code.py` subprocess isolation — largely disjoint footprints |
| **P4.5 (auth) ∥ most** | **✅ yes** | auth is an API/transport concern, independent of tool/plugin internals |
| **B3 ∥ B4 ∥ B5** (within P4.2) | **✅ yes** | distinct tool surfaces (subprocess / network / mutation), each its own classification — independent impls |
| **P4.4 → P4.3** | sequential | registry/lifecycle ride the sandbox |
| **P4.7 → P4.4/P4.5** | sequential | the config UI needs the mgmt endpoints first |

**Net:** same shape as P3 — a **frontend track ∥ a backend track**, plus genuine intra-backend parallelism (P4.1 ∥ P4.3; B3 ∥ B4 ∥ B5; P4.5 alongside). The heavy trust cluster (P4.3 → P4.4) is the one hard sequence.

## 6. ⭐ Scope-ambition options (the lead decision — architect ratifies)

| Option | What | Trade-off |
|---|---|---|
| **Tight** | Close only the **capability gaps that block real use** + the cheapest honest-debt: **P4.1 (turn-loop + read-only tools)**, **P4.2 (a first real tool surface)**, maybe **P4.6 (auto-fire)** — **defer the heavy trust cluster (P4.3/P4.4 sandbox+registry) and auth (P4.5)** to a later phase | Fastest to "agents actually do work end-to-end"; P3 already delivered a usable+extensible product, so tight-P4 just makes it *capable*. **Risk:** "完整化" not literally met; the `RB-FS/NET` honest-debt + the localhost-only posture stay open (both **Accepted + gated** today — not live incidents). |
| **Full** | Resolve **every** ledger item in P4 — sandbox + registry + lifecycle + all local tools + turn-loop + auto-fire + auth/multi-user + GUI L2-L4 (+ optionally F) — the literal "100% 完整" | Matches "完整化" wording; **but** very large, and front-loads the heaviest container-orchestration + auth surfaces (multiple new dual-lens ADRs) — the security-densest phase yet. |
| **Phased** | P4 = the §4 slices as **ordered waves**, each closeable + a re-ratify point: Wave-1 **capability** (P4.1/P4.2) → Wave-2 **trust hardening** (P4.3/P4.4/P4.5) → Wave-3 **completeness/polish** (P4.6/P4.7/P4.8). Re-evaluate scope between waves. | **Lean.** De-risks by sequencing: make the product *capable* (cheap, low-trust) before taking on the *heavy* container/auth infra before polish. Each wave is a natural "ratify the next" checkpoint — exactly how P1/P2/P3 ran. The security-heavy Wave-2 gets its own ratify gate. |

**Architect-partner lean: phased** — P4, like P3, is too large for one scope decision, and its trust-heavy half (Wave-2) genuinely deserves its own ratify checkpoint rather than being committed up-front. But this is the architect's call (**tight** if "make agents do work, ship it" is the goal and the sandbox/auth debt can wait; **full** if literal completeness — incl. retiring `RB-FS/NET` + going multi-user — is required now).

## 7. ⭐ Recommended first slice + why (architect ratifies the start)

**Lean: start with P4.1 — agent turn-loop + the read-only code-intel local tools (B1 + B2).**

Why (the P3.1 logic, re-applied):
- **Highest usability payoff.** Today the executor runs only 3 read-only local tools + MCP, and **a tool result never feeds back to the agent in-turn** (no re-dispatch, ADR-028 D4). So an agent can't investigate→read-result→act within a turn — the flagship **bug-fix / code-review** scenarios (handoff §14: read → search → `find_references` → `git_blame` → … → re-investigate on a failed test) **cannot actually run**. P4.1 makes the product *do work*, end-to-end.
- **Lowest new-trust surface.** Read-only code-intel (`search_text`/`search_code`/`find_references`/`find_definition`) + a bounded turn-loop need **no sandbox, no auth, no container infra** — a clean, low-risk open to P4 (vs the heavy P4.3/P4.5).
- **De-risks the rest.** The turn-loop bound (termination/liveness) settles *before* the heavier tool surfaces (subprocess/network/mutation) and the plugin sandbox land on top of it; and it finishes ADR-028's most conspicuous loose end.

**Alternatives I surface (the architect's call on the start):**
- **P4.3 (Posture-B real sandbox) first** — if retiring the Accepted `RB-FS/NET` honest-debt, or an **imminent remote-plugin distribution story**, is judged top priority; it settles the heaviest security surface early. *(But it's heavy container infra, and the residual is **gated by operator-activation** today — not a live incident.)*
- **P4.5 (auth / multi-user) first** — if **networked / multi-user deployment** is the near-term goal; today localhost-trust single-user suffices.
- **(Not recommended first: P4.4 registry** — depends on the sandbox; **P4.7 GUI** — trails the backend mgmt endpoints.)

## 8. Heavy-security / dual-lens + new-ADR classification (architect ratifies the review posture)

**Mandatory dual-lens R0-B (heavy trust surface — the P3.5/P3.7-remote pattern):**
- **A1** syscall sandbox (container/seccomp/UID — the largest isolation surface to date), **A2** registry + **A3** lifecycle + **A4** signature-trust (untrusted-provenance + supply-chain), **D1** auth + **D2** OAuth (first identity boundary), **B3** subprocess tools (the c2 env-leak class), **B4** network tools (SSRF/exfil).

**Lean dual-lens (a real but narrower trust/liveness surface):**
- **B5** mutation tools (irreversible: `git_push` rev 1 / `apply_edit` rev 2 / `send_email` rev 3 — classification matters), **C1** auto-fire (introduces a **human-out-of-loop** execution — the *opposite* of the trust surface ADR-030 established; must be inscribed as honestly as `RB-FS/NET`), **B1** turn-loop (termination/liveness, ADR-011 territory).

**Single-lens / low:**
- **B2** read-only code-intel, **E1-E3** GUI (backend-authoritative view), **A5** namespacing, **D3** user_id, **D4** session-reuse, **F** hardening.

**New ADR** (a new contract): A1, A2/A3 (plugin registry+lifecycle — likely one ADR), A4 (or an ADR-031 D4 amendment), B1 (turn-loop — likely an ADR-011 amendment + a new loop-bound ADR), C1 (auto-fire durable scheduler), D1 (auth model), the B3/B4 classification ADRs, and F2 (concurrency redesign, if in scope).
**Amend existing**: ADR-031 D1a (narrow the residual when the sandbox lands), ADR-029 (lifecycle/namespacing), ADR-032 (OAuth/session-reuse), ADR-025 (auth + new mgmt endpoints + WAL), ADR-028 (local-tool impls + re-dispatch + execution-lane), ADR-030 (auto-fire + user_id), ADR-011 (turn loop).

## 9. What the architect needs to ratify (the three P4-scope decisions — mirrors P3-roadmap §8)

1. **Ambition** — tight / full / **phased (lean)** (§6). Shapes the whole breakdown.
2. **Priority** — the relative order of the clusters (§3/§4). Lean: capability (P4.1/P4.2) → trust hardening (P4.3/P4.4/P4.5) → completeness (P4.6/P4.7). But e.g. "sandbox-first" (retire `RB-FS/NET` now) or "auth-first" (go multi-user now) are legitimate re-prioritisations.
3. **Starting slice** — **P4.1 (lean)**, or one of the §7 alternatives.

Plus two narrower confirms: (a) is **F (scale/concurrency hardening + memory depth)** in P4 scope at all, or out? (b) the **review posture** (§8) — confirm the heavy dual-lens set.

Once ratified, the chosen first slice gets a normal architect brief (architect-partner) → senior plan → the ADR-008 lifecycle.

## 10. Constitutional / security watch-list for P4 (carry into every slice's brief)

The spine is **unchanged**, but P4 exercises it harder than any prior phase:
- **Operation-gating = code** — the new local tools (subprocess/network/mutation) + auto-fire route through the **existing code autonomy gate**. **Auto-fire (C1) must NOT become an external/timer-decided autonomy** — it is a scheduler *over an already-gated* COUNTDOWN tier (the gate decided the tier; the timer only actuates the operator's standing "approve-unless-cancelled"), and it must inscribe the **human-out-of-loop posture** as honestly as `RB-FS/NET`.
- **Trust boundary** (P2.7-S3 → P3.5 → P3.7-remote, now magnified) — the sandbox / registry / signature / auth (A1-A4, D1) are **all** trust-boundary work, now at the **syscall + network-identity** level. Opt-in, fail-closed, credential-safe, posture-ratified — the recurring discipline.
- **Routing = code** — no P4 item brings an LLM routing/judgment decision. The **turn-loop (B1) dispatch stays code-driven** (the loop bound + when-to-re-dispatch are code; the LLM only generates content within a dispatched turn).
- **content-gen vs judgment** — turn-loop tool-result interpretation stays **content-gen** (`TOOL_OUTPUT_INTERPRET` exists); **no new routing/judgment `LLMPurpose`**.
- **Backend-authoritative** — the GUI L2-L4 config surfaces (E1-E3) **send intent**; the backend owns plugin enable/disable, MCP config, autonomy tiers — the config UI must **not** become a decision surface.
- **Inscribe-before-producer** — the registry contract, the auth model, the turn-loop bound, the sandbox interface are expensive-to-change; pin them before broad producers bind (the P1.6/P2/P3.7 discipline; RC-23-safe ADRs).
- **Honest-residual inscription** — P4 *resolves* one inscribed residual (`RB-FS/NET` → A1) and *creates* a new one (C1's headless execution). Both must be inscribed exactly as ADR-029 D4 / ADR-031 D1a modelled — Accept the *real* surface, not a softened one.

## 11. Cross-references
- **ADRs (deferral sources):** ADR-028 D3/D4 (local tools + re-dispatch), ADR-030 D4 + N1 (auto-fire + user_id), ADR-031 D1a/D4/D5 + Reversibility (sandbox/registry/lifecycle/signature), ADR-029 D5/D6 + scope (registry/lifecycle/namespacing), ADR-032 Considered-alt (OAuth/session-reuse), ADR-025 D6/D7 (auth/multi-user/WAL), ADR-026 scope + handoff §6.4 (GUI L2-L4), ADR-016/017/018/019/020/022 (memory-depth forward hooks).
- **Retro candidates:** P2.2-candidates RC-24 (product AST guards), P2.4-candidates (entity atomic RMW).
- **Source verified `origin/main`:** `tools/local.py:137-141` (only 3 local tools), `config/tools.yaml` (16 classified-but-unimplemented), `plugins/`, `mcp/`, `api/`, `ui/`.
- **Process:** `docs/process/P3-roadmap.md` (the structure this mirrors), `docs/process/dual-lens-r0b.md` (the heavy P4 slices warrant dual-lens), `docs/process/distance-test.md`.

## Authorship note
Architect-partner-authored, verified vs `origin/main` (P3 closed; ADR-024..032 Accepted; the 3-tool local registry; the 16 deferred classifications; the `RB-FS/NET` residual; localhost-trust; no registry/lifecycle/auth). This is a **scope-surface**: the candidate ledger (§3) is the comprehensive grep result; the slice breakdown (§4), the phased ambition (§6), and the P4.1 start (§7) are **leans**, not decisions — the architect ratifies ambition + priority + start (§9). No slice is briefed until the architect ratifies.
