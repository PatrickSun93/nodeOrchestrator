---
task_id: P4.2-B4
review: senior-plan-vs-impl
stage: impl
cycle: 1
reviewer: senior
verdict: needs_architect
verdict_rationale: >
  All 8 atomics delivered, no scope drift, all gates green (ruff + mypy --strict
  242 files + full pytest + t1–t10). Two 🟡 surfaced for architect routing:
  F1 (RC-17 commit-subject — web_search/B4-3 folded into the B4-2 commit, no own
  subject; work fully landed; audit-trail only; pushed → unamendable) and
  F2 (the shared module-level max_workers=1 DNS executor weakens B1's hung-resolver
  spirit — single-writer-never-blocked invariant HOLDS, but a truly-infinite
  getaddrinfo poisons the one DNS worker process-wide; non-blocking, self-healing
  under a normal libc resolver). Plus 3 🟢. Nothing blocking; the impl-stage
  dual-lens R0-B re-probes the SSRF/exfil boundary.
gates:
  ruff: pass
  mypy_strict_src_tests: pass (242 source files)
  pytest_full: pass
  b4_targeted: pass (66 net_trust+network_tools; t1–t10 + executor caps green)
findings_yellow: 2
findings_green: 3
findings_red: 0
---

# P4.2-B4 — senior plan-vs-impl (impl-stage)

**Lens:** plan (`docs/process/senior-plans/P4.2-B4.md`, B4-1..8) + ADR-035
(Accepted) vs the impl pushed on `origin/claude/P4.2-B4-impl`
(`cb28249..f7d2909`, 7 commits). Verify-cite throughout. Senior's unique
surface: plan-implied invariants the deliverable-vs-spec reviewers can't see.

The whole slice landed as **one green unit** (both tools; §5-1 Brave routed) as
the plan §3 required. Gates: ruff ✓, `mypy --strict src tests` → *Success, no
issues found in 242 source files*, full pytest ✓, B4 targeted 66 passed.

---

## 1. Atomic → commit mapping (RC-17 one-atomic-one-commit)

| Atomic | Plan subject | Commit | Subject match |
|---|---|---|---|
| B4-1 | SSRF validator + resolve-then-pin transport (`net_trust.py`) | `cb28249` | ✓ |
| B4-2 | `web_fetch` closure + network registry (`network_tools.py`) | `9221cad` | ✓ (**also carries B4-3**) |
| **B4-3** | `web_search` closure + Brave provider config | **— (folded into `9221cad`)** | ✗ **F1 / RC-17** |
| B4-4 | wire `build_network_tool_registry` at `api/app.py` | `1975e58` | ✓ |
| B4-5 | per-turn network cap in `executor.py` + independence test | `dfae12c` | ✓ |
| B4-6 | extend `snapshot_excerpt` exclusion to web tools (`selection.py`) | `9191222` | ✓ |
| B4-7 | amend ADR-028 D3 + annotate ADR-031 D1a | `c33e432` | ✓ |
| B4-8 | constitution `t10` SSRF floor | `f7d2909` | ✓ |

`git diff b0c62f4..f7d2909` touches exactly 12 files; **zero** `.workflow/`
edits (junior did not self-advance state this cycle — clean).

**web_search IS fully implemented + registered despite the missing B4-3 label**
(F1, below): closure `_make_web_search` (`network_tools.py:176-253`), Brave
endpoint + `X-Subscription-Token` auth (`:48,211`), `api_key_env` env-read
(`:181-184`), fail-closed `not configured` (`:191-192`), `config/web_search.yaml.example`
(provider+`api_key_env`, no key value), registry entry (`:274-277`), and 11
`web_search` tests (`test_network_tools.py` §4–6). The work landed in full; only
the **commit subject** was folded.

---

## 2. Per-atomic acceptance verification (verify-cite)

**B4-1 `net_trust.py`** — *all acceptance met.*
- Floor classifier `is_denied_ip` (`:40-63`): loopback / private / **CGNAT
  `100.64.0.0/10` explicit** (`_CGNAT_NETWORK`, `:30,55` — incl.
  `100.100.100.200`, test-asserted) / link-local (incl. `169.254.169.254`,
  test-asserted) / unspecified / multicast / reserved; **IPv4-mapped-IPv6 unwrapped**
  first (`:47-48`). Deny-if-any (`:112-115`).
- Scheme allowlist `http`+`https` only, **before resolving** (`_validate_scheme`,
  `:66-71`, called first in `handle_request`, `:144`).
- **Resolve-then-pin** (`:79-122,143-172`): resolve once → validate all → pin a
  validated IP into the URL (`copy_with(host=pinned_ip)`, `:152`); original
  hostname kept for SNI/cert via `sni_hostname` extension (`:154-159`),
  `verify=True` (`:141`).
- **🔴 B1 bounded DNS** (`DNS_RESOLVE_TIMEOUT_S = 5.0`, `:25`): `getaddrinfo`
  wrapped in `ThreadPoolExecutor.submit(...).result(timeout=…)` (`:86-94`) →
  `network_timeout:` on expiry. Verified: `test_bounded_dns_timeout`.
- Redirect re-validation each hop (`follow_redirects=True` + `handle_request`
  re-entered per hop, `max_redirects=5`, `:197-198`). Verified:
  `test_redirect_to_internal_blocked`.
- Credential-stripped anon client (`auth=None, cookies={}, headers={}`, `:200-202`);
  `retries=0` (`:141`); granular `httpx.Timeout(connect=5,read=15,write=5,pool=5)`
  (`network_tools.py:39`).
- Tests: floor (parametrized 25 cases), DNS-rebind, multi-A-one-internal,
  **CNAME-chain-to-internal** (A2), **IP-literal via full path** (A3/Y3,
  `test_ip_literal_encoding_blocked_via_resolver` — real resolver, stubbed
  transport), bounded-DNS, redirect. ✓

**B4-2 `web_fetch`** — allowlist `{url}` (`:122-128`); flows **only** through
`build_ssrf_client` (`:131-138`); non-200 → `TOOL_RESULT` (`:152-153`, verified
`test_web_fetch_non_200_is_tool_result_not_failure`); error classes
`scheme_rejected:` / `ssrf_blocked:` / `network_timeout:` / `fetch_failed:`
(`:139-150`); bounded stream `_stream_bounded` (`:94-113`) + `output_truncated_at`;
`_is_network_tool=True` (`:68`). ✓ **Empirically verified** (live check) that
`file://`/`ftp://`/`gopher://` route through the custom transport (default
transport for all schemes when no mounts) and yield the **plan-faithful
`scheme_rejected:`** — see F4.

**B4-3 `web_search`** (folded) — allowlist `{query, max_results}` with clamp
`[1,20]` default 10 (`:194-207`); Brave endpoint + `X-Subscription-Token`
(`:48,211`); fail-closed (`:191-192`); 5xx → `search_provider_error:` (`:224-227`);
parse `web.results[]` (`:236-242`); key **only** in the Brave header, asserted
absent from params/URL/output (`test_web_search_api_key_only_in_brave_header`). ✓

**B4-4 wiring** — composed at the `api/` root (`app.py:242-251`), `local.py`
**not** importing the network module; `web_search.yaml` loaded once, absent →
`None` → fail-closed. ✓

**B4-5 network cap** — `MAX_NETWORK_CALLS_PER_TURN = 10` (`executor.py:57`);
**separate** `elif _is_network:` branch (`:209-238`) keyed on `_is_network_tool`;
subprocess branch **byte-unchanged**; `_execute_local_call` **byte-frozen**
(t3b green). Pre-existing `turn_network_cap_exceeded` consumer grep at plan-base
→ **zero** (B4-5 precondition confirmed). Independence proven:
`test_subprocess_and_network_caps_are_independent` (10 sub + 10 net → 0 failures);
`test_network_cap_exceeded` (11 → 10 + 1 `turn_network_cap_exceeded`). ✓

**B4-6 excerpt exclusion** — `_NETWORK_TOOL_NAMES = {web_fetch, web_search}`
(`selection.py:108-113`); third disjunct in the predicate (`:145`); docstrings
name the third **network** trust-class origin (`:111-118,160-164`); drift
sync-test `test_b46_network_tool_names_drift_guard` (registry keys ==
name-set); behavioral two-channel test `test_b46_network_result_excluded_from_excerpt`. ✓

**B4-7 ADR amendments** — ADR-028 D3 strike-through + top-block
`[Amended P4.2-B4 → ADR-035, Accepted 2026-06-05]`; ADR-031 D1a annotation (the
**network half** of `RB-FS/NET` is now the **active** surface). Both carry
`Accepted` — matching ADR-035's Accepted status (**RC-23 satisfied**). ✓

**B4-8 `t10`** — (a) floor denial behavioral; (b) IP-literal integration via the
full path; (c) `verify=False` AST-banned on the network surface; (d)
`build_ssrf_client` referenced; (e) `retries=0` AST-asserted; meta: t6/t9 still
pass. ✓ (see F3 on the strength of (d))

**No scope drift:** no edit to `local.py`, no edit to `_execute_local_call`, no
new `LLMPurpose`, no new `EventType`, subprocess + B3 surface byte-unchanged.
Constitutional carry-forward #1–#6 hold.

---

## 3. Findings (surface; architect routes)

### 🟡 F1 — RC-17: `web_search` (B4-3) has no own commit; folded into the B4-2 commit
`9221cad` ("P4.2-B4-2: …") carries the full B4-3 deliverable (web_search closure
+ Brave provider + `config/web_search.yaml.example` + 11 web_search tests). The
plan §3 was explicit: *"`web_fetch` (B4-2) and `web_search` (B4-3) are distinct
trust surfaces → distinct commits even though they share the module."* This is
the **same class** as the P1.5-4-under-P1.5-6 bundling RC-17 codifies — coverage
is unaffected, **subject-discipline / atomic→commit-mapping is the breach**.
- **Evidence:** no `P4.2-B4-3:` commit exists in `cb28249..f7d2909`; web_search
  code+tests live under `9221cad`.
- **Note:** the dispatch pre-flagged this. The commit is **pushed** → per
  "never amend pushed commits", it cannot be re-split without architect
  go-ahead. Likely routing: **note-for-retro / accept** (audit-trail only).

### 🟡 F2 — shared module-level `max_workers=1` DNS executor weakens B1's hung-resolver spirit
`_DNS_EXECUTOR = ThreadPoolExecutor(max_workers=1, …)` is a **module-level
singleton** (`net_trust.py:37`) shared across every call.
- **The B1 invariant HOLDS:** the single writer is never blocked indefinitely —
  `future.result(timeout=DNS_RESOLVE_TIMEOUT_S)` always returns control in ≤5s.
- **The plan-implied nuance:** the B1 fix exists to defend against a
  *"hung/slow/DoS'd resolver"* (plan B4-1; ADR-035 D2). But `future.cancel()`
  (`:90`) is a **no-op on an already-running `getaddrinfo`** — so a thread that
  is genuinely stuck keeps occupying the **one** DNS worker. While stuck, every
  later `web_fetch` submits behind it and times out at 5s → **web_fetch DNS is
  degraded/disabled process-wide** (each call a 5s tax, then `network_timeout`).
- **Severity is bounded / self-healing in practice:** a normal libc resolver
  returns/fails within its own `resolv.conf` bound (~10–15s), freeing the worker;
  the writer is single-threaded so futures do **not** pile up. Only a
  *truly-infinite* `getaddrinfo` poisons the worker until process restart. This
  is **strictly better** than the pre-B1 bug (which stalled *all* room writes) —
  but it re-introduces a **milder capability-DoS under the exact threat B1
  targets**, which a per-call executor / daemon-thread-per-call / bounded-growth
  pool would contain. The plan specified `submit(...).result(timeout=…)` but did
  **not** mandate a shared singleton.
- **Suggested routing:** α (isolate per-call) **or** γ/β (accept — infinite
  `getaddrinfo` unrealistic; the metadata/IP floor is the load-bearing defense;
  fold any hardening into the P4.3 egress sandbox). Non-blocking; flagged for the
  dual-lens R0-B liveness lens too.

### 🟢 F3 — `t10d` no-bypass check is weaker than the plan's stated acceptance
Plan B4-8 asked for *"an AST/structural check that `net_trust`'s validating
transport is the **only** client `web_fetch` uses."* The impl
`test_t10d_no_plain_httpx_get_in_web_fetch` is a **string-presence** check
(`"build_ssrf_client" in source`), which cannot detect a future `web_fetch` that
*also* reaches a plain `httpx` — partly because `web_search` legitimately uses
plain `httpx.Client` in the same module (`network_tools.py:213`), making a true
per-function structural check harder. The real invariant is covered
behaviorally (floor tests + `build_ssrf_client` wiring + the `t10c` `verify=False`
ban + `t10e` `retries=0`); the residual is **test-strength only**. Informational.

### 🟢 F4 — `file://` test is looser than (and understates) the actual plan-faithful behavior
`test_web_fetch_file_scheme_rejected` accepts both `fetch_failed:` and
`scheme_rejected:`, and its docstring claims `fetch_failed:`. I verified live
that the **full client path** actually yields the plan-faithful `scheme_rejected:`
for `file://` / `ftp://` / `gopher://` (the custom transport is the default
transport for all schemes when `_mounts` is empty, so `_validate_scheme` fires
inside `handle_request`). The impl is **more** plan-faithful than its own test
asserts; the test could tighten to `scheme_rejected:` only. Cosmetic.

### 🟢 F5 — `web_search` truncation is post-format, not streamed
`web_search` encodes the formatted result then slices at `MAX_RESULT_BYTES`
(`network_tools.py:246-249`) rather than streaming like `web_fetch`. Plan B4-3
said only *"result text bounded at `MAX_RESULT_BYTES`"* (not streamed) and the
payload is small bounded provider JSON — **no drift**. Informational.

---

## 4. Verdict

**`needs_architect`** — the impl is plan-faithful and green across all 8 atomics
with no scope drift; the two 🟡 (F1 audit-trail / RC-17, F2 DNS-executor
liveness nuance) are **non-blocking** and want an architect routing call. The
3 🟢 are informational. Per ADR-008 Amendment 1 (Route B) the state advances to
`awaiting_R0_A` regardless; the mandatory impl-stage dual-lens R0-B
(`requires_cross_family_review: true`) re-probes the SSRF/exfil trust boundary +
liveness on the implementation (F2 is a natural item for its liveness lens).
